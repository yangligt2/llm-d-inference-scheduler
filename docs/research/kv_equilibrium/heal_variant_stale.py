"""Heal-branch candidate: stale-content churn credit on the CPU-tier clock.

Hypothesis (measured tier-size series at 8x-0.022: 250 cold 1/1, 375
healed 2/2, 500 healed 2/6): after surge cancellation the tier holds
dead surge-session content; a real tier reclaims it as live traffic
writes, so restores increasingly serve live state and drain-back
completes. The des_b1 two-clock tier window may keep dead content
priced against live entries.

Accounting, derived from the two-clock design (des_b1.py docstring):
the tier clock advances with new writes only, and an entry is
tier-resident iff fewer than c_cpu write tokens have passed since its
last touch. The window therefore prices every written token as
durable displacement of live coverage. Tokens written by a cancelled
session can never be re-touched: they carry no future reuse value,
and a tier that reclaims dead content (block free on session abort,
or any eviction policy that prefers never-again-touched content)
returns their bytes to live coverage. The variant credits the tier
clock for exactly those bytes: for a LIVE sequence evaluated after
cancellation, tier age = (cpu_clock - t_cpu) minus the dead-session
write tokens that landed in (t_cpu, cpu_clock]. Dead writes are
recorded exactly (per-node stamp/cumsum ledgers), so NO new constant
is introduced, fitted or otherwise.

Bracketing caveat, stated not hidden: a strict LRU with no dead-
content preference keeps dead bytes above any entry touched before
them until that entry itself is evicted - i.e. strict LRU equals the
UNMODIFIED window model. The credit variant is the opposite bracket:
reclamation is complete and instantaneous at cancellation. The two
bracket every intermediate reclamation policy, so a null result on
the credited side excludes the stale-churn mechanism entirely.

Modes:
    instrument  one congested baseline run (n=8, 0.022, C_CPU_500,
                seed 1, 300 min), CREDIT off: measures the surge/dead
                share of the tier window over time and the fraction
                of live tier misses that the credit would rescue.
                Writes out/heal_stale_instrument.csv.
    screen      full screen matrix A1-A7, 6 seeds, 300 min, variant
                vs unmodified RouterSessionSim baselines on A1/A5/A7.
                Writes out/heal_screen_stale.csv and per-run windows
                under out/heal_stale_runs/.

Run from kv_equilibrium/:  ../.venv/bin/python heal_variant_stale.py {instrument,screen}
"""

import sys
import time
from bisect import bisect_right
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from des_b1 import (RouterSessionSim, WIN, T_OFF,
                    C_CPU_250, C_CPU_500)

OUT = Path(__file__).parent / "out"
RUNS = OUT / "heal_stale_runs"
T_END = 300 * 60.0
SEEDS = range(1, 7)

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


class StaleInstrumentSim(RouterSessionSim):
    """RouterSessionSim plus an exact ledger of surge-session tier
    writes. CREDIT=False leaves the dynamics bit-identical to the
    baseline (the ledger and counters are read-only observers).

    Counter basis: tier residency is evaluated at every cached_on call
    that finds a nonzero entry and falls through the HBM window - both
    router affinity scans and admission - so counts are evaluation-
    weighted, not request-weighted; the rescuable/miss RATIO is the
    quantity of interest.
    """

    CREDIT = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        n = len(self.nodes)
        self.dead_stamp = [[] for _ in range(n)]  # cpu_clock at write end
        self.dead_cum = [[] for _ in range(n)]    # cumulative surge tokens
        self.cancelled = False
        nwin = int(self.t_end / WIN)
        self.win_hbm_hit = np.zeros(nwin)
        self.win_tier_hit = np.zeros(nwin)
        self.win_tier_miss = np.zeros(nwin)       # live entries only
        self.win_rescuable = np.zeros(nwin)       # misses the credit rescues
        self.win_rescuable_tok = np.zeros(nwin)
        self.win_deadfrac_sum = np.zeros(nwin)    # surge share of tier window
        self.win_deadfrac_n = np.zeros(nwin)

    # -- surge write ledger ---------------------------------------------------

    def _record_write(self, node_idx, seq, amount):
        if amount > 0.0 and seq in self.surge_seqs:
            st, cu = self.dead_stamp[node_idx], self.dead_cum[node_idx]
            st.append(self.cpu_clock[node_idx])
            cu.append((cu[-1] if cu else 0.0) + amount)

    def finish_prefill(self, rid, node_idx, seq, *rest):
        c0 = self.cpu_clock[node_idx]
        super().finish_prefill(rid, node_idx, seq, *rest)
        self._record_write(node_idx, seq, self.cpu_clock[node_idx] - c0)

    def finish_decode(self, rid, node_idx, seq, *rest):
        c0 = self.cpu_clock[node_idx]
        super().finish_decode(rid, node_idx, seq, *rest)
        self._record_write(node_idx, seq, self.cpu_clock[node_idx] - c0)

    def cancel_surge(self):
        self.cancelled = True
        super().cancel_surge()

    def _dead_between(self, ni, lo, hi):
        """Surge write tokens with end stamp in (lo, hi]. Stamps are
        segment endpoints of the write stream, and entry stamps are
        also endpoints, so segments never straddle lo: exact."""
        st, cu = self.dead_stamp[ni], self.dead_cum[ni]
        if not st:
            return 0.0
        a = bisect_right(st, lo)
        b = bisect_right(st, hi)
        return (cu[b - 1] if b else 0.0) - (cu[a - 1] if a else 0.0)

    # -- residency ------------------------------------------------------------

    def cached_on(self, seq, node_idx, prefix):
        entry = seq.last.get(node_idx)
        if entry is None:
            return 0.0, None
        t_hbm, t_cpu, length = entry
        length = min(length, prefix)
        if length <= 0:
            return 0.0, None
        node = self.nodes[node_idx]
        wi = int(self.now // WIN)
        count = wi < len(self.win_hbm_hit)
        if node.clock - t_hbm < node.cache_window_hbm():
            if count:
                self.win_hbm_hit[wi] += 1
            return length, "hbm"
        if self.c_cpu <= 0.0:
            return 0.0, None
        age = self.cpu_clock[node_idx] - t_cpu
        credit = 0.0
        if self.cancelled and not seq.dead:
            credit = self._dead_between(node_idx, t_cpu,
                                        self.cpu_clock[node_idx])
        if age - (credit if self.CREDIT else 0.0) < self.c_cpu:
            if count:
                self.win_tier_hit[wi] += 1
            return length, "cpu"
        if count and not seq.dead:
            self.win_tier_miss[wi] += 1
            if age - credit < self.c_cpu:      # credit would have rescued
                self.win_rescuable[wi] += 1
                self.win_rescuable_tok[wi] += length
        return 0.0, None

    # -- window occupancy sampling ---------------------------------------------

    def sample_stale(self):
        wi = int(self.now // WIN)
        if wi < len(self.win_deadfrac_sum) and self.c_cpu > 0.0:
            fr = []
            for ni in range(len(self.nodes)):
                c = self.cpu_clock[ni]
                span = min(self.c_cpu, c)
                d = self._dead_between(ni, c - span, c) if span else 0.0
                fr.append(d / self.c_cpu)
            self.win_deadfrac_sum[wi] += float(np.mean(fr))
            self.win_deadfrac_n[wi] += 1
        self.at(self.now + 60.0, self.sample_stale)

    def run(self):
        self.at(60.0, self.sample_stale)
        return super().run()

    def windows(self):
        win = super().windows()
        miss = np.maximum(self.win_tier_miss, 1)
        win["deadfrac"] = (self.win_deadfrac_sum
                           / np.maximum(self.win_deadfrac_n, 1))
        win["tier_hit"] = self.win_tier_hit
        win["tier_miss"] = self.win_tier_miss
        win["rescuable"] = self.win_rescuable
        win["rescue_frac"] = self.win_rescuable / miss
        win["rescuable_tok_s"] = self.win_rescuable_tok / WIN
        return win


class StaleCreditSim(StaleInstrumentSim):
    """The variant: dead-session tier bytes stop counting against the
    live window from cancellation (module docstring)."""

    CREDIT = True


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
    cls = {"variant": StaleCreditSim, "baseline": RouterSessionSim}[model]
    t0 = time.perf_counter()
    sim = cls(n, lb, ls, ccpu, seed, t_end=T_END)
    sim.run()
    win = sim.windows()
    outcome, h, wait = classify(win)
    warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
    RUNS.mkdir(parents=True, exist_ok=True)
    win.to_csv(RUNS / f"{key}_{model}_s{seed}.csv", index=False,
               float_format="%.4f")
    return {"arm": key, "model": model, "seed": seed, "outcome": outcome,
            "end_h": round(h, 4), "end_wait": round(wait, 2),
            "warm_h": round(warm.h.mean(), 4),
            "warm_req_s": round(len([r for r in sim.records
                                     if r[0] < 62 * 60.0]) / (62 * 60.0), 3),
            "wall_s": round(time.perf_counter() - t0, 1)}


def instrument():
    """Congested baseline draw, CREDIT off: quantify the stale share."""
    t0 = time.perf_counter()
    sim = StaleInstrumentSim(8, 0.022, 0.25, C_CPU_500, 1, t_end=T_END)
    sim.run()
    win = sim.windows()
    OUT.mkdir(exist_ok=True)
    win.to_csv(OUT / "heal_stale_instrument.csv", index=False,
               float_format="%.4f")
    print(f"wall {time.perf_counter() - t0:.0f}s; "
          f"outcome {classify(win)[0]}")
    cols = ["t_min", "h", "wait", "ext_share", "restore_s", "deadfrac",
            "tier_hit", "tier_miss", "rescuable", "rescue_frac",
            "rescuable_tok_s"]
    print(win[win.t_min % 20 == 0][cols].to_string(index=False))
    post = win[(win.t_min > 110) & (win.t_min <= 300)]
    print(f"\npost-cancel means: deadfrac {post.deadfrac.mean():.3f}, "
          f"live tier misses {post.tier_miss.sum():.0f}, "
          f"rescuable {post.rescuable.sum():.0f} "
          f"({post.rescuable.sum() / max(post.tier_miss.sum(), 1):.1%})")


def screen(workers):
    jobs = [(key, n, lb, ls, ccpu, seed, "variant")
            for key, n, lb, ls, ccpu in ARMS for seed in SEEDS]
    jobs += [(key, n, lb, ls, ccpu, seed, "baseline")
             for key, n, lb, ls, ccpu in ARMS if key in BASELINE_ARMS
             for seed in SEEDS]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(run_one, jobs):
            print(r)
            rows.append(r)
    df = pd.DataFrame(rows).sort_values(["arm", "model", "seed"])
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "heal_screen_stale.csv", index=False)
    tally = (df.groupby(["arm", "model"]).outcome
             .value_counts().unstack(fill_value=0))
    print(tally.to_string())
    print("wrote out/heal_screen_stale.csv")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "instrument"
    if mode == "instrument":
        instrument()
    else:
        screen(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
