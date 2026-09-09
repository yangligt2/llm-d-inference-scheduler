"""Heal-branch candidate: progressive KV allocation at the admission gate.

Hypothesis (overlay-findings.md, mechanism-revision section): the DES
reserves a request's FULL KV need (prefix + input + output) at batch
admission, while vLLM allocates blocks progressively during chunked
prefill and decode. The reservation overstates running-set residency
exactly during backlog drains - suspect #1 for the missing heal branch
(0/30 DES heals at 8x-0.022 tier vs 4/9 measured) and for the absolute
leftward bias of the collapse-probability curves.

Accounting in this variant:
  - admission: a request joins the running batch allocating only its
    resident cached prefix (HBM hits are ref-count pinned at
    allocation; a tier hit's restored bytes land in HBM, allocated
    here as well). Admission requires headroom for that prefix plus
    the next prefill chunk, a running-batch slot, and prefill-budget
    pacing:
        node.kv_used + cached + min(CHUNK_TOK, prefill)
            <= KV_HEADROOM * C_HBM        (kv_used == 0 escape kept)
        per-node running count < MAX_NUM_SEQS
        for a miss or HBM hit: the prefill feeder slot is free
    The feeder slot models vLLM step-budget pacing: a new sequence is
    scheduled only when the per-step token budget is not consumed by
    an in-progress chunked prefill, so with long prompts admission
    serializes behind the prefill engine (at most one admitted,
    not-yet-served prefill per node; the entry being served has left
    the batch deque, giving one slot of lookahead). Restore-admitted
    entries do not hold the slot: their blocks are allocated but they
    consume no prefill budget while the load is in flight (vLLM
    WAITING_FOR_REMOTE_KVS). This is a structural constraint with no
    numeric constant; without it the variant admits the entire
    backlog (next-chunk need is 0.5% of the pool), the tpot gauge
    counts it, and the model manufactures an interference-driven
    congested state that vLLM's scheduler cannot enter.
  - prefill completion: the uncached tokens (prefill) allocate.
  - decode start: the output tokens allocate as one lump (decode-start
    accrual, matching the point where the unmodified model's
    reservation becomes physical).
  - decode end / surge cancellation: the held amount is released.
The running-dict third element stores the CURRENTLY HELD amount
(cached during the batch and prefill stages, the full need during
decode), so the parent cancel_surge subtraction balances unchanged.
The tpot interference gauge counts the admitted batch, unchanged.

Constants, both measured deployed vLLM flags of the B1/B2 TP4 fleets
(llm-d guides/agentic-serving-tp/{no-,cpu-}offloading-tp4.yaml), not
fitted:
    CHUNK_TOK    = 8192   --max-num-batched-tokens (per-step prefill
                          chunk budget = next-chunk block need)
    MAX_NUM_SEQS = 256    --max-num-seqs (running-batch size cap)

Deviations from vLLM, stated explicitly:
  1. No preemption. Allocations after admission proceed regardless of
     headroom, so kv_used can transiently exceed the watermark (and
     C_HBM); cache_window_hbm clamps at zero. vLLM would preempt or
     recompute instead.
  2. Prefill allocation lands at prefill completion in one step, not
     per chunk (the per-node prefill engine is serialized): occupancy
     is UNDERSTATED by at most one in-flight prefill per node.
  3. Restored bytes allocate at admission, not as the restore channel
     onboards them: OVERSTATED by at most the in-flight restores.
  4. Output tokens allocate at decode start, not per generated token:
     OVERSTATED by the undecoded remainder of in-flight decodes (the
     unmodified model shares this deviation).
  5. Feeder pacing is FCFS at the node queue head: a budget-blocked
     miss also delays restore-hit admissions behind it (the parent
     shares the no-reorder-past-a-blocked-head structure), and
     restore-completed entries waiting for the engine do not block
     new admissions where vLLM's shared budget would.

Conservation: _ledger_check asserts node.kv_used == sum of held over
running entries (and the running-count cache) at surge cancellation
and at end of run; the sanity mode additionally reports the end-of-run
kv fraction (a recovered draw drains to ~0 on the idle tail).

Modes:
    sanity   one 8x-0.017 no-offload run (seed 1, 300 min), variant vs
             unmodified baseline: warm-phase h gate 0.92-0.96, realized
             warm req/s vs baseline, ledger check, end kv fraction.
    screen   full screen matrix A1-A7, 6 seeds, 300 min, variant plus
             unmodified RouterSessionSim baselines on A1/A5/A7. Writes
             out/heal_screen_progressive.csv and per-run windows under
             out/heal_progressive_runs/.

Run from kv_equilibrium/:
    ../.venv/bin/python heal_variant_progressive.py {sanity,screen}
"""

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import des
from des_b1 import RouterSessionSim, B_R, C_CPU_250, C_CPU_500

OUT = Path(__file__).parent / "out"
RUNS = OUT / "heal_progressive_runs"
T_END = 300 * 60.0
SEEDS = range(1, 7)

CHUNK_TOK = 8192.0     # deployed --max-num-batched-tokens
MAX_NUM_SEQS = 256     # deployed --max-num-seqs

ARMS = [
    # key, n_nodes, lam_base, lam_surge, c_cpu per replica
    ("A1", 8, 0.022, 0.25, C_CPU_500),
    ("A2", 8, 0.022, 0.25, C_CPU_250),
    ("A3", 8, 0.022, 0.25, 0.0),
    ("A4", 8, 0.017, 0.25, 0.0),
    ("A5", 4, 0.011, 0.125, C_CPU_500),
    ("A6", 16, 0.040, 0.50, 0.0),
    ("A7", 8, 0.020, 0.25, 0.0),
]
BASELINE_ARMS = {"A1", "A5", "A7"}


class ProgressiveSim(RouterSessionSim):
    """RouterSessionSim with progressive KV accounting (module
    docstring). Overrides keep the parent's event structure; only the
    allocation points and the admission predicate change."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_running = [0] * len(self.nodes)
        self.feeder = [0] * len(self.nodes)   # admitted, unserved miss/hbm

    # -- conservation ledger ---------------------------------------------------

    def _ledger_check(self):
        held = [0.0] * len(self.nodes)
        cnt = [0] * len(self.nodes)
        for ni, _seq, h, _stage in self.running.values():
            held[ni] += h
            cnt[ni] += 1
        for i, node in enumerate(self.nodes):
            assert abs(node.kv_used - held[i]) <= 1e-6 * max(held[i], 1.0), \
                (i, node.kv_used, held[i])
            assert cnt[i] == self.node_running[i], \
                (i, cnt[i], self.node_running[i])
            assert self.feeder[i] == sum(1 for e in self.batch[i]
                                         if e[7] != "cpu"), \
                (i, self.feeder[i])

    # -- surge cancellation ----------------------------------------------------

    def cancel_surge(self):
        # The parent subtracts the stored third element per removed
        # entry; under this class that element is the held amount, so
        # occupancy balances. Only the running-count cache needs the
        # matching decrement, before the parent's try_start fan-out.
        for ni, seq, _held, _stage in self.running.values():
            if seq in self.surge_seqs:
                self.node_running[ni] -= 1
        super().cancel_surge()
        self._ledger_check()

    # -- admission and prefill service ------------------------------------------

    def try_start(self, node_idx):
        node = self.nodes[node_idx]
        batch = self.batch[node_idx]
        # Progressive watermark admission: allocate the resident
        # cached prefix only; require headroom for that prefix plus
        # the next prefill chunk and a running-batch slot (FCFS, no
        # reorder past a blocked head). Cache state is fixed here
        # (allocated prefix blocks are ref-counted) and a CPU-tier
        # hit claims the node's restore channel FCFS, as in the
        # parent.
        while node.queue:
            seq, arrival, prefix, in_tok, out_tok = node.queue[0]
            if seq.dead:
                node.queue.popleft()
                continue
            if self.node_running[node_idx] >= MAX_NUM_SEQS:
                break
            cached, tier = self.cached_on(seq, node_idx, prefix)
            if prefix == 0.0:
                assert cached == 0.0  # new Seq: no cache entry
            if tier != "cpu" and self.feeder[node_idx] >= 1:
                break                # prefill budget consumed (pacing)
            next_chunk = cached + min(CHUNK_TOK, prefix + in_tok - cached)
            if (node.kv_used + next_chunk > des.KV_HEADROOM * des.C_HBM
                    and node.kv_used > 0):
                break                # wait for a decode to free KV
            node.queue.popleft()
            node.kv_used += cached
            self.node_running[node_idx] += 1
            if tier != "cpu":
                self.feeder[node_idx] += 1
            self.req_no += 1
            self.running[self.req_no] = (node_idx, seq, cached, "batch")
            rst_done = self.now
            if tier == "cpu":
                rst_done = max(self.now, self.rst_free[node_idx]) \
                    + cached / B_R
                self.rst_free[node_idx] = rst_done
            batch.append((self.req_no, seq, arrival, prefix, in_tok,
                          out_tok, cached, tier, rst_done))
        if node.busy:
            return
        # Serving half: identical to the parent except the held amount
        # stays at `cached` through the prefill stage and the feeder
        # slot is released when a miss/hbm entry leaves the deque
        # (served or lazily dropped after cancellation).
        ready, skipped = None, []
        while batch:
            e = batch.popleft()
            if e[0] not in self.running:  # cancelled while prefill-pending
                if e[7] != "cpu":
                    self.feeder[node_idx] -= 1
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
        if tier != "cpu":
            self.feeder[node_idx] -= 1
        prefill = prefix + in_tok - cached
        service = prefill / des.P_TPT
        node.busy = True
        self.running[rid] = (node_idx, seq, cached, "prefill")
        self.at(self.now + service, self.finish_prefill, rid, node_idx,
                seq, arrival, prefix, in_tok, out_tok, cached, prefill,
                tier)

    # -- allocation points -------------------------------------------------------

    def finish_prefill(self, rid, node_idx, seq, arrival, prefix, in_tok,
                       out_tok, cached, prefill, tier):
        # Uncached prefill tokens allocate here; output tokens accrue
        # at decode start (same event). The parent then stores the
        # full need as the decode-stage held amount, so finish_decode
        # and cancel_surge release exactly what is held.
        if rid not in self.aborted:
            self.nodes[node_idx].kv_used += prefill + out_tok
        super().finish_prefill(rid, node_idx, seq, arrival, prefix, in_tok,
                               out_tok, cached, prefill, tier)

    def finish_decode(self, rid, node_idx, seq, prefix, in_tok, out_tok):
        if rid in self.running:      # aborted entries were removed at cancel
            self.node_running[node_idx] -= 1
        super().finish_decode(rid, node_idx, seq, prefix, in_tok, out_tok)

    def run(self):
        recs = super().run()
        self._ledger_check()
        return recs


# -- classification and screen (canonical) -------------------------------------


def classify(win):
    sel = win[(win.t_min >= 270) & (win.t_min <= 295)]
    h = sel.h.mean()
    if np.isnan(h):
        h = 0.0            # nothing completed in 270-295: cold
    wait = sel.wait.mean()
    if h < 0.15:
        return "cold", h, wait
    if wait < 15 and h > 0.9:
        return "recovered", h, wait
    return "congested", h, wait


def run_one(job):
    key, n, lb, ls, ccpu, seed, model = job
    cls = {"variant": ProgressiveSim, "baseline": RouterSessionSim}[model]
    t0 = time.perf_counter()
    sim = cls(n, lb, ls, ccpu, seed, t_end=T_END)
    sim.run()
    win = sim.windows()
    outcome, h, wait = classify(win)
    warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
    end = win[(win.t_min >= 270) & (win.t_min <= 295)]
    RUNS.mkdir(parents=True, exist_ok=True)
    win.to_csv(RUNS / f"{key}_{model}_s{seed}.csv", index=False,
               float_format="%.4f")
    return {"arm": key, "model": model, "seed": seed, "outcome": outcome,
            "end_h": round(h, 4), "end_wait": round(wait, 2),
            "end_run": round(end["run"].mean(), 1),
            "end_kv": round(float(np.mean([nd.kv_used for nd in sim.nodes]))
                            / des.C_HBM, 4),
            "warm_h": round(warm.h.mean(), 4),
            "warm_req_s": round(len([r for r in sim.records
                                     if r[0] < 62 * 60.0]) / (62 * 60.0), 3),
            "wall_s": round(time.perf_counter() - t0, 1)}


def sanity():
    rows = [run_one(("SAN", 8, 0.017, 0.25, 0.0, 1, m))
            for m in ("baseline", "variant")]
    for r in rows:
        print(r)
    v = next(r for r in rows if r["model"] == "variant")
    b = next(r for r in rows if r["model"] == "baseline")
    ok_h = 0.92 <= v["warm_h"] <= 0.96
    ok_r = abs(v["warm_req_s"] - b["warm_req_s"]) <= 0.10 * b["warm_req_s"]
    print(f"warm h gate 0.92-0.96: {'PASS' if ok_h else 'FAIL'} "
          f"({v['warm_h']:.4f}); warm req/s vs baseline +-10%: "
          f"{'PASS' if ok_r else 'FAIL'} ({v['warm_req_s']} vs "
          f"{b['warm_req_s']}); variant end kv fraction {v['end_kv']}")


def screen(workers):
    jobs = [(key, n, lb, ls, ccpu, seed, "variant")
            for key, n, lb, ls, ccpu in ARMS for seed in SEEDS]
    jobs += [(key, n, lb, ls, ccpu, seed, "baseline")
             for key, n, lb, ls, ccpu in ARMS if key in BASELINE_ARMS
             for seed in SEEDS]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(run_one, jobs):
            print(r, flush=True)
            rows.append(r)
    df = pd.DataFrame(rows).sort_values(["arm", "model", "seed"])
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "heal_screen_progressive.csv", index=False)
    tally = (df.groupby(["arm", "model"]).outcome
             .value_counts().unstack(fill_value=0))
    print(tally.to_string())
    print("wrote out/heal_screen_progressive.csv")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    if mode == "sanity":
        sanity()
    else:
        screen(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
