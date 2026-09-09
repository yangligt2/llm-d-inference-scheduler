"""DES replication of the four measured B1/B2 session-arrival protocols.

SessionSim subclasses des.Sim (the Phase-2 artifact, untouched) with a
session_poisson arrival mode: base sessions arrive Poisson from t=0, a
surge population arrives Poisson in [t_on, t_off), and the whole surge
population is cancelled at t_off - queued surge requests are removed,
in-flight surge requests are aborted with their KV freed, and surge
conversations are marked dead. This mirrors the aiperf generator exit
at surge end. Finished sessions depart (no closed-mode replacement);
turn chaining stays completion-coupled via issue_next_turn.

Admission is vLLM-watermark style: a waiting request joins the node's
running batch (its full KV need is allocated) while the batch fits
under KV_HEADROOM; the prefill engine serves the batch one request at
a time. des.py admits only when the prefill engine is idle -
equivalent in the empty-queue cells where the Phase-2 DES was
validated, but under a deep backlog it caps the running set at the
prefill turnover rate. The batch definition matters because the
interference coupling
    tpot(R, N) = 10.8e-3 + 2.56e-4 * (R/N)^2  s/token, cap 0.30,
(tpot_fit.py: the per-pod form fits the 4- and 8-replica fleets with
one constant pair) was calibrated against the vLLM
num_requests_running gauge, which counts the whole admitted batch.
R is evaluated once at decode start; in-flight decodes are not
re-timed. R drifts over minutes while a decode lasts seconds to a few
minutes, so the frozen value is accurate at these time scales.

Cache state is evaluated at batch admission (vLLM ref-counts prefix
blocks when the request is allocated, so they cannot age out
afterwards). A CPU-tier hit is onboarded through a per-node restore
channel of capacity B_R tokens/s (measured: the per-pod restore rate
plateaus at 21-24k tok/s across every tier run at both fleet scales
while demand exceeds it; the raw DMA link runs at ~1.19e6 tok/s and
~2% duty, so per-transfer overhead sets the effective capacity).
Onboarding is asynchronous: the prefill engine passes over batch
entries whose restores are still in flight and serves the first
restore-complete entry. Restored bytes advance the node's HBM virtual
write clock exactly like prefill writes (they displace HBM content).
The CPU tier keeps a SEPARATE clock advancing only with newly written
tokens (uncached prefill + generation): measured offload traffic
tracks new writes, not restores - restored blocks already reside in
the tier - and a hit refreshes the tier entry (LRU touch). Sequence
touch stamps are (hbm_clock, cpu_clock, length) 3-tuples written at
decode end; cached_on is overridden accordingly.

Think times and subagent gaps cap the drawn sample at the 10.5 s
idle-gap cap (sample-level min, not a CDF truncation).

Aborted requests do not update seq.last; prefill tokens they wrote
stay on the node's virtual clock (written, then freed - they age other
entries by at most one pool traversal).

Two routing layers are provided. SessionSim routes with des.py's
idealized lexicographic rule (most cached prefix, then load; an
affinity request never diverts). RouterSessionSim - the overlay
model - implements the deployed EPP coordination layer; see its
class docstring. The fleet-size dependence of collapse probability
and the 4x stability result exist only under RouterSessionSim.

Run from docs/research/:  .venv/bin/python kv_equilibrium/des_b1.py
Writes out/des_b1_overlay.png and out/des_b1_summary.csv.
"""

import heapq
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import des
from overlay_b1_dynamics import simulate as fluid_simulate
from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

GAP_CAP = 10.5
TPOT0, TPOT_KP, TPOT_CAP = 10.8e-3, 2.56e-4, 0.30   # per-pod (R/N)^2 form
B_R = 23_000.0         # effective CPU->HBM restore capacity per node, tok/s
T_END = 180 * 60.0
T_ON, T_OFF = 62 * 60.0, 107 * 60.0
WIN = 300.0            # metrics window, s (matches the arcs CSVs)
SAMPLE_DT = 5.0        # waiting/running gauge sampling period, s
N_SEED = 5

# Effective CPU-tier capacity = TIER_EFF x the nominal RAM-derived value
# (kv-offloading-size 500 => 160 GB/pod => 1.26M tok/pod nominal).
# Calibrated on the cold-side ordering of the measured size series at
# 8x-0.022 (250 cold; 375 and 500 never cold): the DES cold/congested
# transition spans (0.42, 0.63)M tok/pod effective, so eff(250) <=
# 0.42M and eff(375) >= 0.63M pin TIER_EFF ~ 2/3 from both sides.
# Consistent with the upper range of the congested-state miss-share
# window ratio (~100 s effective vs ~160 s modeled). Candidate
# physical causes (undiscriminated): kv-offloading-size RAM units /
# allocator overhead, non-LRU eviction, per-pod imbalance. The model
# has NO heal branch at 0.022 at any capacity (0/30 sweep runs) where
# measurement heals 4/9 draws at sizes 375-500 - the capacity scale
# is calibrated on the cold side only; see overlay-findings.md.
TIER_EFF = 0.67
C_CPU_500 = TIER_EFF * 1.26e6   # kv-offloading-size 500, tok/pod effective
C_CPU_375 = TIER_EFF * 0.945e6  # kv-offloading-size 375
C_CPU_250 = TIER_EFF * 0.63e6   # kv-offloading-size 250

ARMS = [
    # key, label, arc csv, replicas, base sps, surge sps, c_cpu per replica
    ("b1a2", "0.022 sps (b1a2: relapse)", "ppc-b1a2-base", 8, 0.022, 0.25, 0.0),
    ("b1c", "0.017 sps (b1c: recovery)", "ppc-b1c-base", 8, 0.017, 0.25, 0.0),
    ("b1b", "0.012 sps (b1b: recovery)", "ppc-b1b-base", 8, 0.012, 0.25, 0.0),
    ("b2a", "0.011 sps + CPU tier (B2a)", "cpuofl-b2a-base", 4, 0.011,
     0.125, C_CPU_500),
]


class CappedSampler(des.Sampler):
    def think(self):
        return min(super().think(), GAP_CAP)

    def sub_gap(self):
        return min(super().sub_gap(), GAP_CAP)


class SessionSim(des.Sim):
    """Open-loop session arrivals with surge cancellation and tpot(R)."""

    def __init__(self, n_nodes, lam_base, lam_surge, c_cpu, seed,
                 t_end=T_END):
        # des.py reads these module globals at call time.
        des.N_NODES = n_nodes
        des.P_TPT = 17_000.0
        des.C_HBM = 6486 * 256.0
        des.TIMEOUT = 1e9          # the measured instrument never sheds
        des.KV_HEADROOM = 0.92
        super().__init__(c_cpu=c_cpu, mode="session_poisson", seed=seed,
                         t_end=t_end)
        self.s = CappedSampler(seed)
        self.lam_base = lam_base
        self.lam_surge = lam_surge
        self.surge_seqs = set()
        self.running = {}          # req id -> (node idx, seq, kv need, stage)
        self.batch = [deque() for _ in self.nodes]   # admitted, prefill-pending
        self.rst_free = [0.0] * len(self.nodes)      # restore channel free time
        self.cpu_clock = [0.0] * len(self.nodes)     # tier LRU clock (new writes)
        self.aborted = set()
        self.req_no = 0
        self.n_sessions = [0, 0]   # base, surge spawn counts
        self.rec_surge = []        # parallel to records: surge-population flag
        nwin = int(t_end / WIN)
        self.wait_sum = np.zeros(nwin)
        self.run_sum = np.zeros(nwin)
        self.n_samp = np.zeros(nwin)
        self.comps = np.zeros(nwin)
        self.win_restored = np.zeros(nwin)

    # -- arrivals -------------------------------------------------------------

    def run(self):
        t = self.s.rng.exponential(1.0 / self.lam_base)
        while t < self.t_end:
            self.at(t, self.spawn_session, False)
            t += self.s.rng.exponential(1.0 / self.lam_base)
        t = T_ON + self.s.rng.exponential(1.0 / self.lam_surge)
        while t < T_OFF:
            self.at(t, self.spawn_session, True)
            t += self.s.rng.exponential(1.0 / self.lam_surge)
        self.at(T_OFF, self.cancel_surge)
        self.at(SAMPLE_DT, self.sample_gauges)
        while self.events:
            t, _, fn, args = heapq.heappop(self.events)
            if t > self.t_end:
                break
            self.now = t
            fn(*args)
        return self.records

    def spawn_session(self, surge):
        conv = des.Conversation()
        turns = self.s.turns_main()
        seq = des.Seq("main", self.s.sys_prompt(), turns, conv)
        conv.main = seq
        for _ in range(self.s.sub_groups()):
            at_turn = int(self.s.rng.integers(1, turns + 1))
            conv.groups_at_turn.setdefault(at_turn, []).append(
                (self.s.ln(36223, 21643, 640, 199424), self.s.turns_sub()))
        if surge:
            self.surge_seqs.add(seq)
        assert not seq.last and seq.ctx == 0.0   # first request: forced miss
        self.n_sessions[1 if surge else 0] += 1
        self.issue_next_turn(seq, True)

    def cancel_surge(self):
        for seq in self.surge_seqs:
            seq.dead = True
            seq.pending.clear()
        for node in self.nodes:
            node.queue = type(node.queue)(
                e for e in node.queue if e[0] not in self.surge_seqs)
        for rid, (ni, seq, need, stage) in list(self.running.items()):
            if seq in self.surge_seqs:
                node = self.nodes[ni]
                node.kv_used -= need
                if stage == "prefill":
                    node.busy = False
                del self.running[rid]
                if stage != "batch":   # batch entries have no scheduled event
                    self.aborted.add(rid)
        for i in range(len(self.nodes)):
            self.try_start(i)

    # -- gauges ---------------------------------------------------------------

    def sample_gauges(self):
        wi = int(self.now // WIN)
        if wi < len(self.n_samp):
            self.wait_sum[wi] += sum(len(n.queue) for n in self.nodes)
            self.run_sum[wi] += len(self.running)
            self.n_samp[wi] += 1
        self.at(self.now + SAMPLE_DT, self.sample_gauges)

    # -- service (des.py copies with the in-flight registry and tpot(R)) ------

    def cached_on(self, seq, node_idx, prefix):
        """Two-clock residency: HBM ages on the full write clock, the CPU
        tier on its own new-writes clock."""
        entry = seq.last.get(node_idx)
        if entry is None:
            return 0.0, None
        t_hbm, t_cpu, length = entry
        length = min(length, prefix)
        if length <= 0:
            return 0.0, None
        node = self.nodes[node_idx]
        if node.clock - t_hbm < node.cache_window_hbm():
            return length, "hbm"
        if self.cpu_clock[node_idx] - t_cpu < self.c_cpu:
            return length, "cpu"
        return 0.0, None

    def try_start(self, node_idx):
        node = self.nodes[node_idx]
        batch = self.batch[node_idx]
        # Watermark admission: waiting requests join the running batch,
        # allocating their full KV need, while the headroom permits (FCFS,
        # no reorder past a blocked head). Cache state is fixed here (the
        # allocated prefix blocks are ref-counted) and a CPU-tier hit
        # claims the node's restore channel FCFS.
        while node.queue:
            seq, arrival, prefix, in_tok, out_tok = node.queue[0]
            if seq.dead:
                node.queue.popleft()
                continue
            need = prefix + in_tok + out_tok
            if (node.kv_used + need > des.KV_HEADROOM * des.C_HBM
                    and node.kv_used > 0):
                break                # wait for a decode to free KV
            node.queue.popleft()
            node.kv_used += need
            self.req_no += 1
            self.running[self.req_no] = (node_idx, seq, need, "batch")
            cached, tier = self.cached_on(seq, node_idx, prefix)
            if prefix == 0.0:
                assert cached == 0.0  # new Seq: no cache entry by construction
            rst_done = self.now
            if tier == "cpu":
                rst_done = max(self.now, self.rst_free[node_idx]) \
                    + cached / B_R
                self.rst_free[node_idx] = rst_done
            batch.append((self.req_no, seq, arrival, prefix, in_tok,
                          out_tok, cached, tier, rst_done))
        if node.busy:
            return
        # Serve the first restore-complete entry; onboarding is
        # asynchronous, so the engine passes over entries whose restores
        # are still in flight.
        ready, skipped = None, []
        while batch:
            e = batch.popleft()
            if e[0] not in self.running:  # cancelled while prefill-pending
                continue
            if e[8] <= self.now:
                ready = e
                break
            skipped.append(e)
        for e in reversed(skipped):
            batch.appendleft(e)
        if ready is None:
            if skipped:
                self.at(min(e[8] for e in skipped), self.try_start, node_idx)
            return
        rid, seq, arrival, prefix, in_tok, out_tok, cached, tier, _ = ready
        prefill = prefix + in_tok - cached
        service = prefill / des.P_TPT
        node.busy = True
        self.running[rid] = (node_idx, seq, prefix + in_tok + out_tok,
                             "prefill")
        self.at(self.now + service, self.finish_prefill, rid, node_idx,
                seq, arrival, prefix, in_tok, out_tok, cached, prefill,
                tier)

    def finish_prefill(self, rid, node_idx, seq, arrival, prefix, in_tok,
                       out_tok, cached, prefill, tier):
        if rid in self.aborted:
            self.aborted.discard(rid)
            return
        node = self.nodes[node_idx]
        node.busy = False
        node.clock += prefill + (cached if tier == "cpu" else 0.0)
        self.cpu_clock[node_idx] += prefill      # tier ingests new writes only
        if tier == "cpu":
            wi = int(self.now // WIN)
            if wi < len(self.win_restored):
                self.win_restored[wi] += cached
        self.records.append((self.now, prefix + in_tok, cached,
                             self.now - arrival, False))
        self.rec_surge.append(seq in self.surge_seqs)
        self.running[rid] = (node_idx, seq, prefix + in_tok + out_tok,
                             "decode")
        tpot = min(TPOT0 + TPOT_KP * (len(self.running)
                                      / len(self.nodes)) ** 2, TPOT_CAP)
        self.at(self.now + out_tok * tpot, self.finish_decode, rid, node_idx,
                seq, prefix, in_tok, out_tok)
        self.try_start(node_idx)

    def finish_decode(self, rid, node_idx, seq, prefix, in_tok, out_tok):
        if rid in self.aborted:
            self.aborted.discard(rid)
            return
        del self.running[rid]
        wi = int(self.now // WIN)
        if wi < len(self.comps):
            self.comps[wi] += 1
        node = self.nodes[node_idx]
        node.kv_used -= prefix + in_tok + out_tok
        node.clock += out_tok
        self.cpu_clock[node_idx] += out_tok
        seq.last[node_idx] = (node.clock, self.cpu_clock[node_idx],
                              prefix + in_tok + out_tok)
        self.try_start(node_idx)

        seq.ctx = prefix + in_tok + out_tok
        seq.turns_left -= 1
        if seq.dead:
            return
        if seq.ctx >= des.COMPACT_TRIGGER:
            for k, (t_hbm, t_cpu, length) in seq.last.items():
                seq.last[k] = (t_hbm, t_cpu, min(length, seq.sys_len))
            seq.ctx = (des.COMPACT_POST if seq.kind == "main"
                       else seq.sys_len + des.SUB_SUMMARY)
        if seq.kind == "main":
            conv = seq.conv
            conv.turn_no += 1
            for seed_len, turns in conv.groups_at_turn.pop(conv.turn_no, []):
                g = des.Seq("sub", seed_len, turns, conv)
                if seq in self.surge_seqs:
                    self.surge_seqs.add(g)
                self.at(self.now + 0.1, self.issue_next_turn, g, True)
        gap = self.s.think() if seq.kind == "main" else self.s.sub_gap()
        self.at(self.now + gap, self.issue_next_turn, seq)

    # -- windowed metrics -----------------------------------------------------

    def windows(self):
        nwin = int(self.t_end / WIN)
        prompt = np.zeros(nwin)
        cached = np.zeros(nwin)
        for t, p, c, _, shed in self.records:
            wi = int(t // WIN)
            if wi < nwin and not shed:
                prompt[wi] += p
                cached[wi] += c
        return pd.DataFrame({
            "t_min": (np.arange(nwin) + 1) * WIN / 60.0,   # window end
            "h": np.where(prompt > 0, cached / np.maximum(prompt, 1.0),
                          np.nan),
            "wait": self.wait_sum / np.maximum(self.n_samp, 1),
            "run": self.run_sum / np.maximum(self.n_samp, 1),
            "comp_s": self.comps / WIN,
            "restore_s": self.win_restored / WIN,
            "ext_share": self.win_restored / np.maximum(cached, 1.0),
        })


class RouterSessionSim(SessionSim):
    """SessionSim with the DEPLOYED coordination layer instead of the
    idealized lexicographic router. Every constant is read from the
    deployed EPP config or plugin code; none is fitted.

      - prefix-cache-affinity-filter: endpoints whose router-visible
        cached fraction >= AFF_THRESH are sticky; candidates narrow to
        the sticky set unless the best sticky estimated TTFT exceeds
        the best non-sticky by MAX_TTFT_PENALTY_MS (TTFT estimated as
        in-flight tokens / PEAK_PT).
      - token-load-scorer: least in-flight-token endpoint among the
        candidates.
      - inflight-load-producer janitor: an entry stops counting
        JANITOR_S after dispatch if the request has not completed
        (plugin_state.go hardcodes the 5-minute staleness reap), so
        deep engine queues undercount and the TTFT gate rarely breaks
        stickiness under backlog.

    The fleet-size dependence of collapse probability is EMERGENT
    under this router: the shared load-balancing couples every pod's
    post-cancellation drain-vs-catch-up race, suppressing the
    favorable per-half fluctuations that independent shard routers
    sometimes draw, so at matched per-capacity load the collapse-
    probability curve sits left of the sharded/smaller-fleet curve
    (2026-08-15/16 ladder: DES 16x-0.017-eq 5/12 vs 8x-0.017 2/12 at
    the 300-min horizon; measured ladders show the same shift). An
    earlier explicit coordinator-saturation term (write-rate freeze,
    constant C_W) is RETIRED: EPP-side measurements show the KV-event
    queue empty, CPU uncontended, and index lookups sub-millisecond
    through reproducing 16x relapses, and at the 300-min horizon the
    freeze changed no verdict. Absolute placement retains the
    documented conservative bias (full KV reservation at admission):
    both DES curves sit left of the measured ones.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entries = {}          # route id -> (node, tokens, t_route, alive)
        self.route_no = 0
        self.routes_of = {}        # id(seq) -> route ids (janitor bookkeeping)

    def _inflight(self, i):
        dead, s = [], 0.0
        for rid, (ni, tok, t0, alive) in self.entries.items():
            if not alive or self.now - t0 >= JANITOR_S:
                dead.append(rid)
                continue
            if ni == i:
                s += tok
        for rid in dead:
            del self.entries[rid]
        return s

    def route(self, seq, prefix, in_tok, out_tok):
        need = prefix + in_tok + out_tok
        n = len(self.nodes)
        infl = [self._inflight(i) for i in range(n)]
        sticky, nonsticky = [], []
        for i in range(n):
            if (prefix > 0
                    and self.cached_on(seq, i, prefix)[0] / prefix
                    >= AFF_THRESH):
                sticky.append(i)
            else:
                nonsticky.append(i)
        cands = list(range(n))
        if sticky:
            best_s = min(infl[i] for i in sticky) / PEAK_PT * 1000.0
            best_ns = (min(infl[i] for i in nonsticky) / PEAK_PT * 1000.0
                       if nonsticky else None)
            if best_ns is None or best_s - best_ns <= MAX_TTFT_PENALTY_MS:
                cands = sticky
        best = min(cands, key=lambda i: (infl[i], self.s.rng.random()))
        self.route_no += 1
        self.entries[self.route_no] = (best, need, self.now, True)
        self.routes_of.setdefault(id(seq), []).append(self.route_no)
        self.nodes[best].queue.append((seq, self.now, prefix, in_tok, out_tok))
        self.try_start(best)

    def finish_decode(self, rid, node_idx, seq, prefix, in_tok, out_tok):
        for r in self.routes_of.get(id(seq), []):
            e = self.entries.get(r)
            if e and e[0] == node_idx and e[3]:
                self.entries[r] = (node_idx, e[1], e[2], False)
                break
        super().finish_decode(rid, node_idx, seq, prefix, in_tok, out_tok)


# Deployed coordination-layer constants (RouterSessionSim)
AFF_THRESH = 0.80              # prefix-cache-affinity-filter affinityThreshold
MAX_TTFT_PENALTY_MS = 18000.0  # filter default maxTTFTPenaltyMs
PEAK_PT = 28888.0              # peakPrefillThroughput, deployed ConfigMap
JANITOR_S = 300.0              # inflight staleness reap, plugin_state.go


def arm_seed_metrics(win):
    """End-state, in-surge peak, collapse and recovery times per run.

    t_collapse_min: end of the first window at/after surge onset with
    h < 0.15. recovery_min: minutes from surge end (107) to the end of
    the first later window with h > 0.8. Both NaN if never reached.
    """
    end = win[(win.t_min > 150) & (win.t_min <= 175)]
    surge = win[(win.t_min >= 65) & (win.t_min <= 110)]
    coll = win[(win.t_min >= 65) & (win.h < 0.15)]
    rec = win[(win.t_min > 110) & (win.h > 0.8)]
    return {
        "end_h": end.h.mean(),
        "end_wait": end.wait.mean(),
        "peak_wait_surge": surge.wait.max(),
        "t_collapse_min": coll.t_min.iloc[0] if len(coll) else np.nan,
        "recovery_min": rec.t_min.iloc[0] - 107.0 if len(rec) else np.nan,
    }


def run_arm(key, n, lam_base, lam_surge, ccpu, seed, cls=None):
    t0 = time.perf_counter()
    sim = (cls or RouterSessionSim)(n, lam_base, lam_surge, ccpu, seed)
    sim.run()
    win = sim.windows()
    warm = [r for r in sim.records if r[0] < T_ON]
    base_recs = sum(1 for f in sim.rec_surge if not f)
    warm_win = win[(win.t_min >= 30) & (win.t_min <= 60)]
    print(f"  {key} seed {seed}: {time.perf_counter() - t0:5.1f}s wall, "
          f"{len(sim.records)} reqs; warm {len(warm) / T_ON:.2f} req/s, "
          f"h {warm_win.h.mean():.1%}; req/session "
          f"{base_recs / max(sim.n_sessions[0], 1):.0f} "
          f"({sim.n_sessions[0]} base / {sim.n_sessions[1]} surge sessions)")
    return win


def main():
    OUT.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 4, figsize=(16, 6.4), dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)
    summary = []
    for col, (key, label, csv, n, lb, ls, ccpu) in enumerate(ARMS):
        print(f"{label}")
        wins = [run_arm(key, n, lb, ls, ccpu, seed)
                for seed in range(1, N_SEED + 1)]
        for seed, win in zip(range(1, N_SEED + 1), wins):
            summary.append({"arm": key, "seed": seed,
                            **arm_seed_metrics(win)})
        fl = fluid_simulate(n, lb, (T_ON, T_OFF, ls), 180, ccpu)
        meas = pd.read_csv(ARCS / f"{csv}.csv")
        t_min = wins[0].t_min.values
        h = np.vstack([w.h.values for w in wins])
        wait = np.vstack([w.wait.values for w in wins])

        axh, axw = axes[0][col], axes[1][col]
        axh.plot(meas.t_min, meas.h, color=SERIES[0], lw=1.8,
                 label="measured")
        axh.plot(fl.t_min, fl.h, color=SERIES[1], lw=1.4, ls=(0, (4, 2)),
                 label="fluid")
        axh.fill_between(t_min, np.nanmin(h, axis=0), np.nanmax(h, axis=0),
                         color=wash(SERIES[2], 0.35), lw=0,
                         label="DES min-max")
        axh.plot(t_min, np.nanmean(h, axis=0), color=SERIES[2], lw=1.6,
                 label="DES mean")
        axh.set_ylim(0, 1.03)
        axh.set_title(label, fontsize=9.5)
        axw.plot(meas.t_min, meas.wait, color=SERIES[0], lw=1.8)
        axw.plot(fl.t_min, fl.wait, color=SERIES[1], lw=1.4, ls=(0, (4, 2)))
        axw.fill_between(t_min, wait.min(axis=0), wait.max(axis=0),
                         color=wash(SERIES[2], 0.35), lw=0)
        axw.plot(t_min, wait.mean(axis=0), color=SERIES[2], lw=1.6)
        axw.set_yscale("symlog", linthresh=10)
        axw.set_xlabel("minutes", fontsize=9)
        for ax in (axh, axw):
            style_axes(ax)
            ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.axvspan(T_ON / 60, T_OFF / 60, color=wash("#d03b3b", 0.10),
                       zorder=0)

        end_rows = [r for r in summary if r["arm"] == key]
        end_m = meas[(meas.t_min > 150) & (meas.t_min <= 175)]
        end_f = fl[(fl.t_min > 150) & (fl.t_min <= 175)]
        eh = [r["end_h"] for r in end_rows]
        ew = [r["end_wait"] for r in end_rows]
        print(f"  end state (150-175 min): DES h "
              f"{np.mean(eh):5.1%} [{np.min(eh):5.1%}-{np.max(eh):5.1%}] "
              f"vs fluid {end_f.h.mean():5.1%} vs meas {end_m.h.mean():5.1%}"
              f"; wait {np.mean(ew):5.0f} [{np.min(ew):.0f}-{np.max(ew):.0f}]"
              f" vs fluid {end_f.wait.mean():4.0f} vs meas "
              f"{end_m.wait.mean():4.0f}")

    axes[0][0].set_ylabel("token hit rate", fontsize=9)
    axes[1][0].set_ylabel("waiting (symlog)", fontsize=9)
    axes[0][0].legend(fontsize=8, frameon=False, loc="lower left",
                      labelcolor=INK2)
    fig.suptitle("DES vs fluid vs measured arcs "
                 f"(45-min surge, cancellation at surge end, "
                 f"{N_SEED} seeds/arm)", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "des_b1_overlay.png", facecolor=PAGE)
    pd.DataFrame(summary).to_csv(OUT / "des_b1_summary.csv", index=False,
                                 float_format="%.4f")
    print("wrote out/des_b1_overlay.png, out/des_b1_summary.csv")


if __name__ == "__main__":
    main()
