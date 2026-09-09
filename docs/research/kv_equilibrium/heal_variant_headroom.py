"""Heal-branch candidate: occupancy-gated HBM eviction (the
restored-volume / residency correction).

Hypothesis (round 4). The parent two-clock LRU tests HBM residency as
    write_clock - t_touch < C_HBM - kv_used,
so every write ages every resident entry REGARDLESS of free headroom:
after enough cumulative writes, entries expire even when the pool has
drained. The inspected vLLM allocator evicts cached blocks only under
allocation pressure - writes land in free blocks first, and content
freed by completions stays resident until an allocation actually needs
its blocks. Consequence in the parent DES: post-cancel restored
content expires again with a half-empty pool, forcing re-restore
forever (the re-entry trap); measured fleets keep restored content
resident once headroom exists and the restore volume decays
(out/arcs/cpuofl-a4-375-lh.csv, cpuofl-500-bimod6.csv).

Mechanism (no new constants; corrects the LRU abstraction only).
Each node carries a second monotone counter evict_clock, the
cumulative volume of cached tokens actually evicted. Written volume
is credited to node.clock (the write clock) exactly as in the parent;
resident cached volume is write_clock - evict_clock. At admission,
after reserving `need`, the allocation evicts only the overflow
    over = max(0, kv_used + (write_clock - evict_clock) - C_HBM)
oldest-first, so evict_clock += over (clamped to the resident
volume). Content is evicted in write order, therefore an entry
stamped at write-clock position t_hbm is gone exactly when
evict_clock >= t_hbm; the HBM residency test becomes
    evict_clock < t_hbm.
When kv_used + resident <= C_HBM no eviction occurs and nothing ages,
matching allocator behavior with free headroom. Under a full pool
every write forces equal eviction and the dynamics recover the parent
LRU. The parent's known conservatisms are retained unchanged: full
KV reservation at admission, in-flight writes double-counted against
kv_used during the request, stale duplicate volume from re-touched
entries left in write-clock space. cancel_surge frees reservations
without touching either clock, as in the parent.

The CPU tier clock is NOT gated: c_cpu is a fixed capacity window and
the congested tier runs full (the regime the tier constants were
calibrated in); gating it would need a tier occupancy model outside
this correction's scope.

Restore channel: the parent per-node serial FCFS channel at B_R,
byte-for-byte (its deficiency is a separately documented negative in
heal_variant_serial.py; this variant isolates the residency
correction).

Gauge semantics (APPLIED, as in heal_variant_serial): vLLM's
num_requests_running excludes WAITING_FOR_REMOTE_KVS entries
(scheduler.py:1108-1111, 2659-2662; loggers.py:494, 1108-1116), so
restore-in-flight entries live in a pending-onboard set excluded from
the R used by the tpot term and from the sampled `run` gauge, while
holding their full KV reservation.

Added observables (windows() columns): kv (fleet KV occupancy gauge),
restore_tok_s (fleet restore tok/s credited at transfer completion),
resident (fleet HBM resident-cached fraction gauge,
sum(write_clock - evict_clock) / (N * C_HBM); raw resident volume
including the in-flight double count, diagnostic only).

Conservation: _ledger_check() asserts per-node kv_used equals the sum
of held reservations, every pending-onboard rid is live, restore
tokens balance (admitted == completed + cancelled + in-flight), and
evict_clock <= write_clock per node.

Modes (run from kv_equilibrium/):
    ../.venv/bin/python -u heal_variant_headroom.py sanity
        gate 1: full-pool limit - 8x 0.022 c_cpu=0 seed 1: warm-phase
                windows near-parent (gating binds only when headroom
                exists; congested phase MAY diverge - report, no gate);
        gate 2: 8x 0.017 C_CPU_500 seed 1, warm h in 0.92-0.96;
        gate 3: A1 seed 1 variant vs baseline trajectory, phase
                restore rates and kv/resident gauges.
The full screen matrix lives in heal_screen_headroom_runner.py.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import des
from des_b1 import (RouterSessionSim, B_R, C_CPU_250, C_CPU_500,
                    TPOT0, TPOT_KP, TPOT_CAP, WIN, SAMPLE_DT)

OUT = Path(__file__).parent / "out"
RUNS = OUT / "heal_headroom_runs"
T_END = 300 * 60.0


class HeadroomGatedSim(RouterSessionSim):
    """RouterSessionSim with occupancy-gated HBM eviction (module
    docstring). Overrides: cached_on (evict-clock residency test),
    try_start (admission eviction overflow; serial restore channel
    unchanged; pending-onboard bookkeeping), finish_prefill (R
    excludes pending-onboard), sample_gauges (kv/resident gauges, run
    gauge semantics), cancel_surge and run (ledger), windows."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        n = len(self.nodes)
        self.evict_clock = [0.0] * n
        self.pending_onboard = {}      # rid -> cached tokens in flight
        nwin = int(self.t_end / WIN)
        self.kv_sum = np.zeros(nwin)
        self.res_sum = np.zeros(nwin)
        self.win_restore_tok = np.zeros(nwin)
        self.rst_admitted = 0.0        # restore token ledger
        self.rst_completed = 0.0
        self.rst_cancelled = 0.0

    # -- conservation ledger --------------------------------------------------

    def _ledger_check(self):
        held = [0.0] * len(self.nodes)
        for ni, _seq, need, _stage in self.running.values():
            held[ni] += need
        for i, node in enumerate(self.nodes):
            assert abs(node.kv_used - held[i]) <= 1e-6 * max(held[i], 1.0), \
                ("kv mismatch", self.now, i, node.kv_used, held[i])
            assert self.evict_clock[i] <= node.clock + 1e-6, \
                ("evict > write clock", i, self.evict_clock[i], node.clock)
        for rid in self.pending_onboard:
            assert rid in self.running, ("orphan pending rid", rid)
        inflight = sum(self.pending_onboard.values())
        bal = self.rst_completed + self.rst_cancelled + inflight
        assert abs(self.rst_admitted - bal) <= 1e-6 * max(bal, 1.0), \
            ("restore ledger", self.rst_admitted, self.rst_completed,
             self.rst_cancelled, inflight)

    # -- occupancy-gated residency ---------------------------------------------

    def cached_on(self, seq, node_idx, prefix):
        entry = seq.last.get(node_idx)
        if entry is None:
            return 0.0, None
        t_hbm, t_cpu, length = entry
        length = min(length, prefix)
        if length <= 0:
            return 0.0, None
        if self.evict_clock[node_idx] < t_hbm:
            return length, "hbm"
        if self.cpu_clock[node_idx] - t_cpu < self.c_cpu:
            return length, "cpu"
        return 0.0, None

    def _evict_for(self, node_idx):
        node = self.nodes[node_idx]
        resident = node.clock - self.evict_clock[node_idx]
        over = node.kv_used + resident - des.C_HBM
        if over > 0:
            self.evict_clock[node_idx] += min(over, resident)

    # -- restore transfer lifecycle ----------------------------------------------

    def _onboard_done(self, rid):
        cached = self.pending_onboard.pop(rid, None)
        if cached is None:
            return                     # cancelled, or already credited
        self._credit_restore(cached)

    def _credit_restore(self, cached):
        self.rst_completed += cached
        wi = int(self.now // WIN)
        if wi < len(self.win_restore_tok):
            self.win_restore_tok[wi] += cached

    def cancel_surge(self):
        for rid, (_ni, seq, _need, _stage) in self.running.items():
            if seq in self.surge_seqs and rid in self.pending_onboard:
                self.rst_cancelled += self.pending_onboard.pop(rid)
        super().cancel_surge()
        self._ledger_check()

    # -- admission and prefill service (parent copy; eviction overflow at
    # -- admission, pending-onboard set, R-count semantics changed) ---------------

    def try_start(self, node_idx):
        node = self.nodes[node_idx]
        batch = self.batch[node_idx]
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
            self._evict_for(node_idx)   # allocation-pressure eviction
            self.req_no += 1
            self.running[self.req_no] = (node_idx, seq, need, "batch")
            cached, tier = self.cached_on(seq, node_idx, prefix)
            if prefix == 0.0:
                assert cached == 0.0  # new Seq: no cache entry
            rst_done = self.now
            if tier == "cpu":
                rst_done = max(self.now, self.rst_free[node_idx]) \
                    + cached / B_R
                self.rst_free[node_idx] = rst_done
                self.pending_onboard[self.req_no] = cached
                self.rst_admitted += cached
                self.at(rst_done, self._onboard_done, self.req_no)
            batch.append((self.req_no, seq, arrival, prefix, in_tok,
                          out_tok, cached, tier, rst_done))
        if node.busy:
            return
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
        # Same-timestamp race: served exactly at rst_done before the
        # _onboard_done event fires - credit the completion here.
        if rid in self.pending_onboard:
            self._credit_restore(self.pending_onboard.pop(rid))
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
        self.cpu_clock[node_idx] += prefill    # tier ingests new writes only
        if tier == "cpu":
            wi = int(self.now // WIN)
            if wi < len(self.win_restored):
                self.win_restored[wi] += cached
        self.records.append((self.now, prefix + in_tok, cached,
                             self.now - arrival, False))
        self.rec_surge.append(seq in self.surge_seqs)
        self.running[rid] = (node_idx, seq, prefix + in_tok + out_tok,
                             "decode")
        # Gauge semantics: pending-onboard entries are outside vLLM's
        # execution batch and do not contribute decode interference.
        r_eff = len(self.running) - len(self.pending_onboard)
        tpot = min(TPOT0 + TPOT_KP * (r_eff / len(self.nodes)) ** 2,
                   TPOT_CAP)
        self.at(self.now + out_tok * tpot, self.finish_decode, rid, node_idx,
                seq, prefix, in_tok, out_tok)
        self.try_start(node_idx)

    # -- gauges ---------------------------------------------------------------------

    def sample_gauges(self):
        wi = int(self.now // WIN)
        if wi < len(self.n_samp):
            self.wait_sum[wi] += sum(len(n.queue) for n in self.nodes)
            self.run_sum[wi] += (len(self.running)
                                 - len(self.pending_onboard))
            n, chbm = len(self.nodes), des.C_HBM
            self.kv_sum[wi] += sum(nd.kv_used for nd in self.nodes) \
                / (n * chbm)
            self.res_sum[wi] += sum(nd.clock - ec for nd, ec in
                                    zip(self.nodes, self.evict_clock)) \
                / (n * chbm)
            self.n_samp[wi] += 1
        self.at(self.now + SAMPLE_DT, self.sample_gauges)

    def windows(self):
        win = super().windows()
        ns = np.maximum(self.n_samp, 1)
        win["kv"] = self.kv_sum / ns
        win["resident"] = self.res_sum / ns
        win["restore_tok_s"] = self.win_restore_tok / WIN
        return win

    def run(self):
        recs = super().run()
        self._ledger_check()
        return recs


# -- classification (canonical) and per-run metrics --------------------------------


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


def row_metrics(win, outcome, h, wait):
    """Per-run record columns. Heal phenomenology (stricter than
    recovered): recovered AND end_kv <= 0.5 AND mean ext_share
    270-295 <= 0.2 AND end running <= 2x warm running."""
    end = win[(win.t_min >= 270) & (win.t_min <= 295)]
    warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
    end_kv = end["kv"].mean()
    ext = end.ext_share.mean()
    end_run, warm_run = end["run"].mean(), warm["run"].mean()
    healed = (outcome == "recovered" and end_kv <= 0.5 and ext <= 0.2
              and end_run <= 2.0 * warm_run)
    return {
        "outcome": outcome, "healed": bool(healed),
        "end_h": round(h, 4), "end_wait": round(wait, 2),
        "end_kv": round(float(end_kv), 4) if np.isfinite(end_kv) else np.nan,
        "ext_share_270_295": round(float(ext), 4),
        "end_run": round(float(end_run), 1),
        "warm_run": round(float(warm_run), 1),
        "end_resident": (round(float(end["resident"].mean()), 4)
                         if "resident" in win.columns else np.nan),
        "peak_restore_tok_s": round(float(win.restore_tok_s.max()), 0),
        "tail_restore_tok_s": round(float(end.restore_tok_s.mean()), 0),
        "warm_h": round(float(warm.h.mean()), 4),
    }


def run_one(arm, n, lb, ls, ccpu, seed, model="variant", save=True):
    cls = {"variant": HeadroomGatedSim,
           "baseline": RouterSessionSim}[model]
    t0 = time.perf_counter()
    sim = cls(n, lb, ls, ccpu, seed, t_end=T_END)
    sim.run()
    win = sim.windows()
    if model == "baseline":            # classification columns for parity
        win["kv"] = np.nan
        win["restore_tok_s"] = np.nan
    outcome, h, wait = classify(win)
    row = {"arm": arm, "model": model, "seed": seed,
           **row_metrics(win, outcome, h, wait),
           "warm_req_s": round(len([r for r in sim.records
                                    if r[0] < 62 * 60.0]) / (62 * 60.0), 3),
           "wall_s": round(time.perf_counter() - t0, 1)}
    if save:
        RUNS.mkdir(parents=True, exist_ok=True)
        win.to_csv(RUNS / f"{arm}_{model}_s{seed}.csv", index=False,
                   float_format="%.4f")
    return row, win


def sanity():
    # gate 1: c_cpu=0, warm phase near-parent (no headroom pressure
    # difference before the surge fills the pool)
    rv, wv = run_one("G1", 8, 0.022, 0.25, 0.0, 1, "variant", save=False)
    rb, wb = run_one("G1", 8, 0.022, 0.25, 0.0, 1, "baseline", save=False)
    for w, tag in ((wv, "variant"), (wb, "baseline")):
        warm = w[(w.t_min >= 30) & (w.t_min <= 60)]
        print(f"gate 1 {tag}: warm h {warm.h.mean():.4f} "
              f"wait {warm.wait.mean():.1f}; outcome tail "
              f"h {w[(w.t_min >= 270) & (w.t_min <= 295)].h.mean():.3f}")
    # gate 2: warm h with the tier
    r2, _ = run_one("G2", 8, 0.017, 0.25, C_CPU_500, 1, "variant",
                    save=False)
    ok2 = 0.92 <= r2["warm_h"] <= 0.96
    print(f"gate 2 (warm h 0.92-0.96 with C_CPU_500): "
          f"{'PASS' if ok2 else 'FAIL'} ({r2['warm_h']})")
    # gate 3: A1 seed 1, variant vs baseline
    for model in ("baseline", "variant"):
        r, w = run_one("A1", 8, 0.022, 0.25, C_CPU_500, 1, model)
        print(f"gate 3 A1 s1 {model}: {r}")
        if model == "variant":
            for lo, hi in ((107, 120), (120, 150), (150, 200), (270, 295)):
                sel = w[(w.t_min > lo) & (w.t_min <= hi)]
                print(f"  t {lo}-{hi}: h {sel.h.mean():.3f} "
                      f"wait {sel.wait.mean():.1f} kv {sel.kv.mean():.3f} "
                      f"resident {sel.resident.mean():.3f} "
                      f"restore {sel.restore_tok_s.mean():.0f} tok/s "
                      f"(x N*B_R {sel.restore_tok_s.mean() / (8 * B_R):.2f})")
    print("DONE")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    if mode == "sanity":
        sanity()
    else:
        raise SystemExit("modes: sanity (screen: heal_screen_headroom_runner.py)")
