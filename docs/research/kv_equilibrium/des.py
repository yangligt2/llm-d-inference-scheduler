"""Phase 2: discrete event simulation of KV-cache serving.

Validates the fluid model from first principles: discrete requests, real
FIFO queues, per-node KV pools, and exact LRU via the virtual write clock -
none of the fluid model's closures (Che approximation, M/G/1, Sakasegawa).

Virtual write clock: each node keeps a monotone counter of KV tokens written.
A sequence stores the counter value at its last touch on that node. Its
prefix is resident in HBM iff (clock - last_touch) < free HBM pool, and in
the CPU tier iff < free HBM + CPU capacity. Exact for LRU when a sequence's
blocks are touched atomically; O(1) per request.

Service model per node: one prefill engine (chunked prefill is serialized in
vLLM) at p_tpt tokens/s; decode runs concurrently at fixed TPOT; a request
occupies KV (context + output tokens) from prefill start to decode end, and
admission blocks while the running set would overflow the pool. Requests
older than TIMEOUT in queue are shed.

Arrival modes:
  closed  fixed pool of l concurrent conversations (finished ones are
          replaced immediately). Timeout-shed conversations abandon.
  replay  pregenerated trace with nominal timestamps fired on schedule
          regardless of system state (benchmark / fixed-rate-producer
          regime - the true open loop where the bistable band lives).
          Within a sequence, ordering is preserved: a turn whose
          predecessor is still in flight fires at its completion. Sheds
          drop the single request; later turns still fire, and the stale
          cache entry gives them a partial hit (the missing suffix is
          prefilled). An admission gate (rate_schedule below the base
          rate) models operator load shedding without abandonment.
"""

import heapq
from collections import deque

import numpy as np

from fluid_model import (COMPACT_TRIGGER, COMPACT_POST, THINK_ZERO_FRAC,
                         THINK_MIX, SUB_CONV_FRAC, SUB_GROUPS_MEAN, SUB_TURNS,
                         SUB_D_IN, SUB_D_OUT, SUB_SUMMARY, SUB_GAP,
                         TURNS_MAIN, ln_musigma)

N_NODES = 16
P_TPT = 10_000.0
TPOT = 0.012
C_HBM = 0.95e6
RESTORE_TPS = 1.0e6      # CPU -> HBM re-onboarding, tokens/s (~50 GB/s)
TIMEOUT = 30.0
KV_HEADROOM = 0.95       # running set may use at most this fraction of HBM

# Mean requests per conversation, for arrival-rate conversion.
REQS_PER_CONV = TURNS_MAIN[0] + SUB_CONV_FRAC * SUB_GROUPS_MEAN * SUB_TURNS[0]


class Sampler:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)

    def ln(self, mean, std, lo, hi):
        mu, sigma = ln_musigma(mean, std)
        return float(np.clip(self.rng.lognormal(mu, sigma), lo, hi))

    def sys_prompt(self):
        if self.rng.random() < 0.87:
            return self.ln(52858, 18110, 640, 162624)
        return self.ln(23285, 48078, 640, 162624)

    def turn_input(self):
        if self.rng.random() < 0.85:
            return self.ln(2882, 11880, 1, 197760)
        return self.ln(1199, 261, 1, 197760)

    def turn_output(self):
        return self.ln(1258, 2977, 2, 40339)

    def sub_input(self):
        return self.ln(SUB_D_IN, 11850, 1, 161950)

    def sub_output(self):
        return self.ln(SUB_D_OUT, 762, 2, 59903)

    def think(self):
        if self.rng.random() < THINK_ZERO_FRAC:
            return 0.0
        (w1, m1, s1), (_, m2, s2) = THINK_MIX
        if self.rng.random() < w1:
            return self.ln(m1, s1, 0.05, 3600.0)
        return self.ln(m2, s2, 0.05, 3600.0)

    def sub_gap(self):
        return self.ln(SUB_GAP[0], SUB_GAP[1], 0.05, 60.0)

    def turns_main(self):
        return int(round(self.ln(*TURNS_MAIN[:2], TURNS_MAIN[2], TURNS_MAIN[3])))

    def turns_sub(self):
        return int(round(self.ln(*SUB_TURNS[:2], SUB_TURNS[2], SUB_TURNS[3])))

    def sub_groups(self):
        if self.rng.random() >= SUB_CONV_FRAC:
            return 0
        return int(round(self.ln(SUB_GROUPS_MEAN, 13, 1, 153)))


class Node:
    __slots__ = ("clock", "kv_used", "queue", "busy")

    def __init__(self):
        self.clock = 0.0     # cumulative KV tokens written (LRU virtual time)
        self.kv_used = 0.0   # KV held by running requests
        self.queue = deque()
        self.busy = False

    def cache_window_hbm(self):
        return max(C_HBM - self.kv_used, 0.0)


class Seq:
    """One request stream with a contiguous growing prefix: a main
    conversation thread or one subagent group."""
    __slots__ = ("kind", "ctx", "sys_len", "turns_left", "conv",
                 "last", "dead", "in_flight", "pending")

    def __init__(self, kind, sys_len, turns, conv=None):
        self.kind = kind
        self.ctx = 0.0
        self.sys_len = sys_len
        self.turns_left = turns
        self.conv = conv
        self.last = {}       # node idx -> (clock_at_touch, cached_len)
        self.dead = False
        self.in_flight = False
        self.pending = deque()


class Conversation:
    __slots__ = ("main", "groups_at_turn", "turn_no")

    def __init__(self):
        self.main = None
        self.groups_at_turn = {}
        self.turn_no = 0


# ---------------------------------------------------------------------------
# Replay trace generation. Timestamps assume warm nominal service (input-only
# prefill + decode); the trace starts `warmback` seconds before t=0 so the
# conversation population at t=0 has the stationary age mix.
# ---------------------------------------------------------------------------


def _gen_conversation(s: Sampler, start, t_end, events, warm):
    turns = s.turns_main()
    seq = Seq("main", s.sys_prompt(), turns)
    groups = {}
    for _ in range(s.sub_groups()):
        at = int(s.rng.integers(1, turns + 1))
        groups.setdefault(at, []).append(None)
    ctx, trunc, t = 0.0, None, start
    first_emitted = False
    for i in range(1, turns + 1):
        if t >= t_end:
            break
        in_tok = seq.sys_len + s.turn_input() if i == 1 else s.turn_input()
        out_tok = s.turn_output()
        if t >= 0:
            if not first_emitted and i > 1:
                warm.append((seq, ctx if trunc is None else min(ctx, trunc)))
            first_emitted = True
            events.append((t, seq, ctx, trunc, in_tok, out_tok))
            trunc = None
        done = t + in_tok / P_TPT + out_tok * TPOT
        ctx += in_tok + out_tok
        if ctx >= COMPACT_TRIGGER:
            trunc = seq.sys_len if trunc is None else min(trunc, seq.sys_len)
            ctx = COMPACT_POST
        for _ in groups.pop(i, []):
            _gen_group(s, done + 0.1, t_end, events, warm)
        t = done + s.think()


def _gen_group(s: Sampler, start, t_end, events, warm):
    turns = s.turns_sub()
    seq = Seq("sub", s.ln(36223, 21643, 640, 199424), turns)
    ctx, trunc, t = 0.0, None, start
    first_emitted = False
    for i in range(1, turns + 1):
        if t >= t_end:
            break
        in_tok = seq.sys_len if i == 1 else s.sub_input()
        out_tok = s.sub_output()
        if t >= 0:
            if not first_emitted and i > 1:
                warm.append((seq, ctx if trunc is None else min(ctx, trunc)))
            first_emitted = True
            events.append((t, seq, ctx, trunc, in_tok, out_tok))
            trunc = None
        done = t + in_tok / P_TPT + out_tok * TPOT
        ctx += in_tok + out_tok
        if ctx >= COMPACT_TRIGGER:
            trunc = seq.sys_len if trunc is None else min(trunc, seq.sys_len)
            ctx = seq.sys_len + SUB_SUMMARY
        t = done + s.sub_gap()


def generate_trace(rps, t_end, seed, warmback=12000.0):
    """Request trace at ~rps aggregate over [0, t_end); rate-calibrated.

    Returns (events, warm): warm lists (seq, prefix_len) for sequences whose
    earlier turns predate t=0 - the caches they would have built. The Sim
    stacks them into per-node LRU order so t=0 starts in the warm state.
    """
    conv_rate = rps / REQS_PER_CONV
    for _ in range(2):
        s = Sampler(seed + 7777)
        events, warm = [], []
        t = -warmback
        while True:
            t += s.rng.exponential(1.0 / conv_rate)
            if t >= t_end:
                break
            _gen_conversation(s, t, t_end, events, warm)
        got = len(events) / t_end
        if abs(got - rps) / rps < 0.03:
            break
        conv_rate *= rps / got
    events.sort(key=lambda e: e[0])
    return events, warm


# ---------------------------------------------------------------------------
# Simulator.
# ---------------------------------------------------------------------------


class Sim:
    def __init__(self, c_cpu=0.0, mode="closed", sessions=400, trace=None,
                 warm=None, gate_schedule=None, seed=0, t_end=1800.0,
                 flush_at=None):
        self.c_cpu = c_cpu
        self.mode = mode
        self.sessions = sessions
        self.trace = trace
        self.warm = warm
        self.gate_schedule = gate_schedule   # [(t, admit_prob)] for replay
        self.t_end = t_end
        self.flush_at = flush_at
        self.s = Sampler(seed)
        self.nodes = [Node() for _ in range(N_NODES)]
        self.events = []
        self.seq_no = 0
        self.now = 0.0
        self.records = []    # (t, prompt, cached, ttft, shed)

    def at(self, t, fn, *args):
        self.seq_no += 1
        heapq.heappush(self.events, (t, self.seq_no, fn, args))

    def run(self):
        if self.mode == "closed":
            for _ in range(self.sessions):
                self.at(self.s.rng.uniform(0, 60.0), self.spawn_conversation)
        else:
            # Traces are reused across Sim instances: reset sequence state.
            seqs = {ev[1] for ev in self.trace}
            for sq in seqs:
                sq.last.clear()
                sq.dead = False
                sq.in_flight = False
                sq.pending.clear()
            # Stack pre-t=0 prefixes into per-node LRU order: entry k on a
            # node was touched before entries 0..k-1, so ages at t=0 equal
            # the cumulative stacked tokens - a realistic warm cache where
            # only the most recent (pool-size) tokens are resident per tier.
            if self.warm:
                order = list(self.warm)
                self.s.rng.shuffle(order)
                cums = [0.0] * N_NODES
                for sq, length in order:
                    i = int(np.argmin(cums))
                    sq.last[i] = (-(cums[i] + length), length)
                    cums[i] += length
            for ev in self.trace:
                self.at(ev[0], self.replay_fire, *ev[1:])
        if self.flush_at is not None:
            self.at(self.flush_at, self.flush_caches)
        while self.events:
            t, _, fn, args = heapq.heappop(self.events)
            if t > self.t_end:
                break
            self.now = t
            fn(*args)
        return self.records

    def flush_caches(self):
        """Age every cached prefix out of both tiers (rolling deploy)."""
        for node in self.nodes:
            node.clock += C_HBM + self.c_cpu + 1.0

    def admit_prob(self):
        if not self.gate_schedule:
            return 1.0
        return [p for (t0, p) in self.gate_schedule if self.now >= t0][-1]

    # -- closed-loop workload ------------------------------------------------

    def spawn_conversation(self):
        conv = Conversation()
        turns = self.s.turns_main()
        seq = Seq("main", self.s.sys_prompt(), turns, conv)
        conv.main = seq
        for _ in range(self.s.sub_groups()):
            at_turn = int(self.s.rng.integers(1, turns + 1))
            conv.groups_at_turn.setdefault(at_turn, []).append(
                (self.s.ln(36223, 21643, 640, 199424), self.s.turns_sub()))
        self.issue_next_turn(seq, True)

    def issue_next_turn(self, seq, first=False):
        if seq.dead or seq.turns_left <= 0:
            if seq.kind == "main" and self.mode == "closed" and not seq.dead:
                self.spawn_conversation()
            return
        if first:
            in_tok = (seq.sys_len + self.s.turn_input() if seq.kind == "main"
                      else seq.sys_len)
        else:
            in_tok = (self.s.turn_input() if seq.kind == "main"
                      else self.s.sub_input())
        out_tok = (self.s.turn_output() if seq.kind == "main"
                   else self.s.sub_output())
        self.route(seq, seq.ctx, in_tok, out_tok)

    # -- replay workload -----------------------------------------------------

    def replay_fire(self, seq, prefix, trunc, in_tok, out_tok):
        if seq.dead:
            return
        if trunc is not None:
            # Compaction happened before this turn: existing cache entries
            # are trustworthy only up to the system prompt / seed.
            for k, (touched, length) in seq.last.items():
                seq.last[k] = (touched, min(length, trunc))
        if self.s.rng.random() > self.admit_prob():
            return                      # operator gate: dropped, not shed
        if seq.in_flight:
            seq.pending.append((prefix, in_tok, out_tok))
            return
        seq.in_flight = True
        self.route(seq, prefix, in_tok, out_tok)

    def _seq_done(self, seq):
        seq.in_flight = False
        if seq.pending and not seq.dead:
            seq.in_flight = True
            self.route(seq, *seq.pending.popleft())

    # -- routing and service ------------------------------------------------

    def cached_on(self, seq, node_idx, prefix):
        entry = seq.last.get(node_idx)
        if entry is None:
            return 0.0, None
        touched, length = entry
        node = self.nodes[node_idx]
        age = node.clock - touched
        length = min(length, prefix)
        if length <= 0:
            return 0.0, None
        if age < node.cache_window_hbm():
            return length, "hbm"
        if age < node.cache_window_hbm() + self.c_cpu:
            return length, "cpu"
        return 0.0, None

    def route(self, seq, prefix, in_tok, out_tok):
        best, best_key = 0, None
        for i, node in enumerate(self.nodes):
            cached, _ = self.cached_on(seq, i, prefix)
            load = len(node.queue) + node.kv_used / C_HBM
            key = (-cached, load, self.s.rng.random())
            if best_key is None or key < best_key:
                best_key, best = key, i
        self.nodes[best].queue.append(
            (seq, self.now, prefix, in_tok, out_tok))
        self.try_start(best)

    def try_start(self, node_idx):
        node = self.nodes[node_idx]
        if node.busy:
            return
        while node.queue:
            seq, arrival, prefix, in_tok, out_tok = node.queue[0]
            if self.now - arrival > TIMEOUT or seq.dead:
                node.queue.popleft()
                if not seq.dead:
                    self.records.append((self.now, prefix + in_tok, 0.0,
                                         float("nan"), True))
                    if self.mode == "closed":
                        seq.dead = True         # user abandons
                    else:
                        self._seq_done(seq)     # benchmark keeps firing
                continue
            need = prefix + in_tok + out_tok
            if node.kv_used + need > KV_HEADROOM * C_HBM and node.kv_used > 0:
                return               # wait for a decode to free KV
            node.queue.popleft()
            cached, tier = self.cached_on(seq, node_idx, prefix)
            prefill = prefix + in_tok - cached
            service = prefill / P_TPT
            if tier == "cpu":
                service += cached / RESTORE_TPS
            node.busy = True
            node.kv_used += need
            self.at(self.now + service, self.finish_prefill, node_idx, seq,
                    arrival, prefix, in_tok, out_tok, cached, prefill, tier)
            return

    def finish_prefill(self, node_idx, seq, arrival, prefix, in_tok, out_tok,
                       cached, prefill, tier):
        node = self.nodes[node_idx]
        node.busy = False
        node.clock += prefill + (cached if tier == "cpu" else 0.0)
        self.records.append((self.now, prefix + in_tok, cached,
                             self.now - arrival, False))
        self.at(self.now + out_tok * TPOT, self.finish_decode,
                node_idx, seq, prefix, in_tok, out_tok)
        self.try_start(node_idx)

    def finish_decode(self, node_idx, seq, prefix, in_tok, out_tok):
        node = self.nodes[node_idx]
        node.kv_used -= prefix + in_tok + out_tok
        node.clock += out_tok
        seq.last[node_idx] = (node.clock, prefix + in_tok + out_tok)
        self.try_start(node_idx)

        if self.mode != "closed":
            self._seq_done(seq)
            return

        seq.ctx = prefix + in_tok + out_tok
        seq.turns_left -= 1
        if seq.ctx >= COMPACT_TRIGGER:
            for k, (touched, length) in seq.last.items():
                seq.last[k] = (touched, min(length, seq.sys_len))
            seq.ctx = (COMPACT_POST if seq.kind == "main"
                       else seq.sys_len + SUB_SUMMARY)
        if seq.kind == "main":
            conv = seq.conv
            conv.turn_no += 1
            for seed_len, turns in conv.groups_at_turn.pop(conv.turn_no, []):
                g = Seq("sub", seed_len, turns, conv)
                self.at(self.now + 0.1, self.issue_next_turn, g, True)
        gap = self.s.think() if seq.kind == "main" else self.s.sub_gap()
        self.at(self.now + gap, self.issue_next_turn, seq)


def summarize(records, t_from, t_to):
    rows = [r for r in records if t_from <= r[0] < t_to]
    if not rows:
        return None
    served = [r for r in rows if not r[4]]
    prompt = sum(r[1] for r in served)
    cached = sum(r[2] for r in served)
    ttfts = sorted(r[3] for r in served) if served else [float("nan")]
    dur = t_to - t_from
    return {
        "h_tok": cached / prompt if prompt else 0.0,
        "served_rps": len(served) / dur,
        "offered_rps": len(rows) / dur,
        "shed_frac": 1.0 - len(served) / len(rows) if rows else 0.0,
        "ttft_mean": float(np.mean(ttfts)),
        "ttft_p50": ttfts[len(ttfts) // 2],
        "ttft_p95": ttfts[int(len(ttfts) * 0.95)],
    }
