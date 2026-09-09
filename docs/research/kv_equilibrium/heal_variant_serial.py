"""Heal-branch candidate: concurrent restore onboarding with a link
rate limit, replacing the per-node serial FCFS restore channel.

Motivation (adversarial judgment on the progressive screen): the DES
failing arms A1/A5 DRAIN their queues by t=115-120 and then RE-ENTER
congestion while the serial restore channel stays pinned at
0.81-0.96 N*B_R with ext_share 1.0 - a re-entry trap. The serial
channel itself is falsified by measurement: the measured heal arcs
sustain 5-min fleet restore rates of 235,284 tok/s (cpuofl-a4-375-lh,
t=70) and 278,161 tok/s (cpuofl-500-bimod6, t=70), 1.28-1.51x the
modeled hard ceiling N*B_R (B_R = 23k tok/s/node), then run their
post-cancel restore phase at 0.14-0.56 N*B_R with wait 0.3-7 while kv
drains 0.83 -> 0.26-0.31. The 23k plateau (research-status result 4)
is a congested-STATE throughput outcome, not a channel capacity.

Mechanism. A CPU-tier hit admitted to the batch starts its restore
transfer immediately; transfers run CONCURRENTLY. Per-transfer
completion time:

    rst_done = link_grant_end + T_OVERHEAD
    link_grant_end = max(now, link_free) + cached / LINK_RATE

link_free is a per-node clock that serializes LINK OCCUPANCY only: a
zero-burst rate limit at LINK_RATE on restored tokens over any
horizon (the "token-bucket or equivalent" enforcement; overhead
phases overlap freely, link phases cannot). With k transfers in
flight the per-node onboard rate is ~ k * S / (S/LINK_RATE +
T_OVERHEAD), capped at LINK_RATE - concurrency, not a fixed 23k
ceiling, sets throughput.

Constants:
    LINK_RATE  = 1.19e6 tok/s/node. MEASURED: the raw DMA rate from
                 the vllm:kv_offload_total_{bytes,time} counters,
                 151.5 GB/s active bandwidth at 127 KB/token
                 (des_b1.py docstring; overlay-findings.md
                 calibration provenance).
    T_OVERHEAD = 4.232 s/transfer. DERIVED FROM MEASURED, derivation:
                 the measured effective plateau B_R = 23k tok/s/node
                 holds while demand exceeds the channel, at ~2% link
                 duty (23000 / 1.19e6 = 1.93%), so per-transfer
                 overhead binds. For a saturated serial channel
                 moving transfers of mean size S,
                     B_R = S / (S/LINK_RATE + T_OVERHEAD)
                     =>  T_OVERHEAD = S * (1/B_R - 1/LINK_RATE).
                 The measured counters carry token rates but no
                 transfer counts, so the size scale S is taken from
                 the model workload in the same regime the plateau
                 was measured in: S_MEAN_RESTORE = 99,247 tokens,
                 the pooled mean CPU-tier restore size over the
                 congested phase (t 120-295 min) of the six A1
                 baseline draws (RouterSessionSim, 8x 0.022
                 tier-500; scratch_smean.py; per-seed means
                 96-110k, n = 70,756). A serial channel at
                 S_MEAN_RESTORE then reproduces exactly 23k tok/s;
                 1/B_R - 1/LINK_RATE = 4.264e-5 s/token gives
                 T_OVERHEAD = 4.232 s.

Gauge-semantics decision (APPLIED): the tpot(R/N) interference fit
was calibrated against vllm:num_requests_running, and the inspected
scheduler (vllm main@2026-08-25, scheduler.py:1108-1111, 2659-2662;
loggers.py:494, 1108-1116) EXCLUDES sequences in
WAITING_FOR_REMOTE_KVS from that gauge: they sit in a skipped-waiting
queue with blocks already allocated, and enter `running` only after
the transfer completes. Accordingly restore-in-flight entries live in
a per-node pending-onboard set that (a) is excluded from the R used
by the tpot term and from the sampled `run` gauge, (b) still holds
its full KV reservation (vLLM allocates blocks before entering
WAITING_FOR_REMOTE_KVS), and (c) faces no running-cap interaction
(this DES models no max_num_seqs). An entry leaves pending-onboard
exactly at its rst_done and starts contributing to interference from
then on.

Everything else is the parent RouterSessionSim: watermark admission
with full-KV reservation, FCFS no-reorder queues, serial prefill
engine, two-clock LRU, deployed-EPP routing. Restored bytes advance
the HBM write clock at prefill completion, as in the parent.

Added observables (windows() columns):
    kv            fleet KV occupancy gauge, sampled with the other
                  gauges: sum(node.kv_used) / (N * C_HBM).
    restore_tok_s fleet restore tok/s credited at TRANSFER COMPLETION
                  (rst_done), the counterpart of the measured
                  CPU_to_GPU byte counters. The parent's restore_s
                  (credited at prefill completion) is retained
                  unchanged.

Congested-state self-limit and pin overshoot (documented, not tuned).
The rate limit alone would allow LINK_RATE = 51.7x B_R per node; the
congested state self-limits far below that because admission is
KV-gated: with the pool full (kv gauge ~0.87) a restore is admitted
only when a completion frees its full-need reservation, so the fleet
restore rate equals completions/s x mean restored tokens per
admission. A1 seed 1 tail (t 270-295): 2.39 comp/s x 105.6k tok =
252k tok/s = 1.37 N*B_R, with ~1.3 transfers in flight per node
(2.39/8 admissions/s x ~4.3 s transfer time) - concurrency ~1, set by
the admission gate, not by the channel. The level OVERSHOOTS the
measured congested-draw band 0.81-1.04 N*B_R (screen tails: A1
0.93-1.37, A5 1.10-1.47, A2 congested draws 0.71-1.19) for two
identified reasons: (1) the model restores the FULL cached context on
every tier hit (congested ext_share 1.0, h ~0.94, ~100k tok/restore)
where the measured congested state runs h 0.70-0.85 with ext-hit
62-79% of hits, i.e. smaller effective restored volume per
completion; (2) excluding pending-onboard entries from R raises the
completion rate itself (A1 s1 run gauge 84 vs 108, comp 2.39/s vs
1.73/s baseline). The re-entry trap SURVIVES this mechanism: every
completion re-admits a full-context restore, so the restore
population regenerates at exactly the completion rate and the
congested state persists at elevated throughput (A1 0/6 healed, all
congested; A5 0/6 end wait < 15). This is a documented negative for
the concurrent-restore-alone heal hypothesis; the residual gap points
at the restored-volume side (partial-context restores / tier content
staleness), not the channel model.

Conservation: _ledger_check() (run at surge cancellation and end of
run) asserts per-node kv_used equals the sum of held reservations
over running entries, every pending-onboard rid is a live running
entry, and restore tokens balance:
    admitted == completed + cancelled + in-flight.
Cancellation paths: a surge entry cancelled while its transfer is in
flight moves its tokens to the cancelled bucket and its rst_done
event becomes a no-op; entries cancelled after transfer completion
are already in the completed bucket.

Modes (run from kv_equilibrium/):
    ../.venv/bin/python -u heal_variant_serial.py sanity
        gate 1: 8x-0.017 c_cpu=0 seed 1, variant windows bit-identical
                to unmodified RouterSessionSim (restore path
                unreachable);
        gate 2: 8x-0.017 C_CPU_500 seed 1, warm h in 0.92-0.96;
        gate 3: A1 (8x-0.022 tier-500) seed 1, variant vs baseline
                trajectory and fleet restore rates.
The full screen matrix lives in heal_screen_serial_runner.py.
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
RUNS = OUT / "heal_serial_runs"
T_END = 300 * 60.0

LINK_RATE = 1.19e6        # tok/s/node, measured raw DMA rate
S_MEAN_RESTORE = 99_247.0  # tokens, model congested-phase mean (docstring)
T_OVERHEAD = S_MEAN_RESTORE * (1.0 / B_R - 1.0 / LINK_RATE)  # 4.232 s


class ConcurrentRestoreSim(RouterSessionSim):
    """RouterSessionSim with concurrent restore onboarding (module
    docstring). Overrides: try_start (restore completion times and
    pending-onboard bookkeeping), finish_prefill (R excludes
    pending-onboard), sample_gauges (kv gauge, run gauge semantics),
    cancel_surge and run (ledger), windows (added columns)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        n = len(self.nodes)
        self.link_free = [0.0] * n     # link-occupancy rate limiter
        self.pending_onboard = {}      # rid -> cached tokens in flight
        nwin = int(self.t_end / WIN)
        self.kv_sum = np.zeros(nwin)
        self.win_restore_tok = np.zeros(nwin)
        self.rst_admitted = 0.0        # restore token ledger
        self.rst_completed = 0.0
        self.rst_cancelled = 0.0

    # -- conservation ledger ---------------------------------------------------

    def _ledger_check(self):
        held = [0.0] * len(self.nodes)
        for ni, _seq, need, _stage in self.running.values():
            held[ni] += need
        for i, node in enumerate(self.nodes):
            assert abs(node.kv_used - held[i]) <= 1e-6 * max(held[i], 1.0), \
                ("kv mismatch", self.now, i, node.kv_used, held[i])
        for rid in self.pending_onboard:
            assert rid in self.running, ("orphan pending rid", rid)
        inflight = sum(self.pending_onboard.values())
        bal = self.rst_completed + self.rst_cancelled + inflight
        assert abs(self.rst_admitted - bal) <= 1e-6 * max(bal, 1.0), \
            ("restore ledger", self.rst_admitted, self.rst_completed,
             self.rst_cancelled, inflight)

    # -- restore transfer lifecycle ---------------------------------------------

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

    # -- admission and prefill service (parent copy; restore timing and
    # -- R-count semantics changed) ----------------------------------------------

    def try_start(self, node_idx):
        node = self.nodes[node_idx]
        batch = self.batch[node_idx]
        # Watermark admission as in the parent; a CPU-tier hit starts
        # its transfer immediately (concurrent onboarding, link
        # occupancy serialized) and enters pending-onboard.
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
                assert cached == 0.0  # new Seq: no cache entry
            rst_done = self.now
            if tier == "cpu":
                grant = max(self.now, self.link_free[node_idx]) \
                    + cached / LINK_RATE
                self.link_free[node_idx] = grant
                rst_done = grant + T_OVERHEAD
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

    # -- gauges -------------------------------------------------------------------

    def sample_gauges(self):
        wi = int(self.now // WIN)
        if wi < len(self.n_samp):
            self.wait_sum[wi] += sum(len(n.queue) for n in self.nodes)
            self.run_sum[wi] += (len(self.running)
                                 - len(self.pending_onboard))
            self.kv_sum[wi] += (sum(n.kv_used for n in self.nodes)
                                / (len(self.nodes) * des.C_HBM))
            self.n_samp[wi] += 1
        self.at(self.now + SAMPLE_DT, self.sample_gauges)

    def windows(self):
        win = super().windows()
        win["kv"] = self.kv_sum / np.maximum(self.n_samp, 1)
        win["restore_tok_s"] = self.win_restore_tok / WIN
        return win

    def run(self):
        recs = super().run()
        self._ledger_check()
        return recs


# -- classification (canonical) and per-run metrics ------------------------------


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
    has_rt = "restore_tok_s" in win.columns
    end_kv = end["kv"].mean() if "kv" in win.columns else np.nan
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
        "peak_restore_tok_s": (round(float(win.restore_tok_s.max()), 0)
                               if has_rt else np.nan),
        "tail_restore_tok_s": (round(float(end.restore_tok_s.mean()), 0)
                               if has_rt else np.nan),
        "warm_h": round(float(warm.h.mean()), 4),
    }


def run_one(arm, n, lb, ls, ccpu, seed, model, save=True):
    cls = {"variant": ConcurrentRestoreSim,
           "baseline": RouterSessionSim}[model]
    t0 = time.perf_counter()
    sim = cls(n, lb, ls, ccpu, seed, t_end=T_END)
    sim.run()
    win = sim.windows()
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


SHARED_COLS = ["t_min", "h", "wait", "run", "comp_s", "restore_s",
               "ext_share"]


def windows_identical(wa, wb):
    a, b = wa[SHARED_COLS].to_numpy(), wb[SHARED_COLS].to_numpy()
    return a.shape == b.shape and np.array_equal(a, b, equal_nan=True)


def sanity():
    print(f"T_OVERHEAD = {T_OVERHEAD:.3f} s "
          f"(= {S_MEAN_RESTORE:.0f} * (1/{B_R:.0f} - 1/{LINK_RATE:.0f}))")
    # gate 1: restore path unreachable -> bit-identical windows
    rv, wv = run_one("G1", 8, 0.017, 0.25, 0.0, 1, "variant", save=False)
    rb, wb = run_one("G1", 8, 0.017, 0.25, 0.0, 1, "baseline", save=False)
    ident = windows_identical(wv, wb)
    print(f"gate 1 (c_cpu=0 bit-identity): {'PASS' if ident else 'FAIL'}")
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
                      f"restore {sel.restore_tok_s.mean():.0f} tok/s "
                      f"(x N*B_R {sel.restore_tok_s.mean() / (8 * B_R):.2f})"
                      f" peak-in-phase {sel.restore_tok_s.max():.0f}")
    print("DONE")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    if mode == "sanity":
        sanity()
    else:
        raise SystemExit("modes: sanity (screen: heal_screen_serial_runner.py)")
