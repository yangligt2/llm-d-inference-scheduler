"""Dry experiment: does surge-smoothing admission flip the b1a2 relapse?

Mechanism under test: a router-side deferral gate, the DES-fidelity
abstraction shared by concurrency control and async serving (store the
request durably, dispatch when the system is not busy). New-session
first requests (main conversations only; subagent seeds belong to
already-admitted sessions) are held in a fleet-level FIFO reservoir
while the fleet is busy and released paced when it is not.
Mid-conversation turns are never deferred, so admitted sessions keep
their completion-coupled cadence.

Gate signals (both router-observable):
  - fleet waiting depth  > W_HI          (busy: stop admitting sessions)
  - fleet KV occupancy   > KV_HI         (basin signal; kv115 separatrix
                                          motivates a KV-occupancy gate)
Release: every GATE_DT seconds, if waiting <= W_LO and KV <= KV_HI,
release K_REL sessions FIFO (max release rate K_REL/GATE_DT sps).
Deferred surge sessions die in the reservoir at surge cancellation,
mirroring the aiperf generator exit; they are counted as dropped.

Arms (5 seeds each, deployed-router model, 180-min horizon):
  b1a2-base   8x 0.022 no-offload, RouterSessionSim (published: relapse 4/5)
  b1a2-gate   same + deferral gate
  b1c-gate    8x 0.017 guard: recovery and warm h must be preserved

Run from docs/research/:
  .venv/bin/python kv_equilibrium/smooth_surge_dryrun.py
Writes out/smooth_surge_dryrun.csv and out/smooth_surge_dryrun.png.
"""

import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import des
from des_b1 import (RouterSessionSim, arm_seed_metrics, T_ON, T_OFF,
                    N_SEED)
from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"

GATE_DT = 5.0        # release poll period, s
W_HI = 16.0          # close gate above this fleet waiting depth (2/node at 8x)
W_LO = 8.0           # release only at/below this depth (1/node)
KV_HI = 0.85         # close gate above this fleet KV occupancy
K_REL = 1            # sessions released per poll => max 0.2 sps release rate


class SmoothedRouterSim(RouterSessionSim):
    """RouterSessionSim plus the fleet-level session-admission gate."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deferq = deque()          # (seq, t_deferred, surge_flag)
        self.n_defer = [0, 0]          # base, surge deferral counts
        self.n_drop = 0                # died (cancelled) in the reservoir
        self.rel_delay = []            # deferral delay of released sessions
        self.at(GATE_DT, self.gate_tick)

    def _fleet_wait(self):
        return sum(len(n.queue) for n in self.nodes)

    def _fleet_kv(self):
        return (sum(n.kv_used for n in self.nodes)
                / (len(self.nodes) * des.C_HBM))

    def gate_closed(self):
        return self._fleet_wait() > W_HI or self._fleet_kv() > KV_HI

    def issue_next_turn(self, seq, first=False):
        if first and seq.kind == "main" and not seq.dead \
                and self.gate_closed():
            surge = seq in self.surge_seqs
            self.n_defer[1 if surge else 0] += 1
            self.deferq.append((seq, self.now, surge))
            return
        super().issue_next_turn(seq, first)

    def gate_tick(self):
        released = 0
        while (self.deferq and released < K_REL
               and self._fleet_wait() <= W_LO
               and self._fleet_kv() <= KV_HI):
            seq, t0, _ = self.deferq.popleft()
            if seq.dead:
                self.n_drop += 1
                continue
            self.rel_delay.append(self.now - t0)
            super().issue_next_turn(seq, True)
            released += 1
        self.at(self.now + GATE_DT, self.gate_tick)


ARMS = [
    ("b1a2-base", "8x 0.022 baseline", RouterSessionSim, 8, 0.022, 0.25),
    ("b1a2-gate", "8x 0.022 + gate", SmoothedRouterSim, 8, 0.022, 0.25),
    ("b1c-gate", "8x 0.017 + gate (guard)", SmoothedRouterSim, 8, 0.017,
     0.25),
]


def run_arm(key, cls, n, lam_base, lam_surge, seed):
    t0 = time.perf_counter()
    sim = cls(n, lam_base, lam_surge, 0.0, seed)
    sim.run()
    win = sim.windows()
    m = arm_seed_metrics(win)
    warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
    m.update(arm=key, seed=seed,
             warm_h=warm.h.mean(),
             comps_total=int(sim.comps.sum()),
             base_sessions=sim.n_sessions[0],
             surge_sessions=sim.n_sessions[1])
    if isinstance(sim, SmoothedRouterSim):
        d = np.array(sim.rel_delay) if sim.rel_delay else np.array([np.nan])
        m.update(defer_base=sim.n_defer[0], defer_surge=sim.n_defer[1],
                 dropped=sim.n_drop, still_deferred=len(sim.deferq),
                 rel_delay_p50_min=np.nanpercentile(d, 50) / 60.0,
                 rel_delay_max_min=np.nanmax(d) / 60.0)
    else:
        m.update(defer_base=0, defer_surge=0, dropped=0, still_deferred=0,
                 rel_delay_p50_min=np.nan, rel_delay_max_min=np.nan)
    print(f"  {key} seed {seed}: {time.perf_counter() - t0:5.1f}s wall; "
          f"warm h {m['warm_h']:.1%}, end h {m['end_h']:.1%}, "
          f"end wait {m['end_wait']:.0f}, comps {m['comps_total']}, "
          f"defer b/s {m['defer_base']}/{m['defer_surge']}, "
          f"dropped {m['dropped']}, backlog {m['still_deferred']}")
    return m, win


def main():
    OUT.mkdir(exist_ok=True)
    rows, wins = [], {}
    for key, label, cls, n, lb, ls in ARMS:
        print(label)
        wins[key] = []
        for seed in range(1, N_SEED + 1):
            m, win = run_arm(key, cls, n, lb, ls, seed)
            rows.append(m)
            wins[key].append(win)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "smooth_surge_dryrun.csv", index=False,
              float_format="%.4f")

    # Outcome tally: cold iff end-state h < 0.15 (paper criterion).
    print("\noutcome tally (end 150-175 min, cold iff h < 0.15):")
    for key, _, _, _, _, _ in ARMS:
        sub = df[df.arm == key]
        cold = int((sub.end_h < 0.15).sum())
        print(f"  {key}: cold {cold}/{len(sub)}; "
              f"end h {sub.end_h.min():.2f}-{sub.end_h.max():.2f}; "
              f"end wait {sub.end_wait.min():.0f}-{sub.end_wait.max():.0f}; "
              f"comps {sub.comps_total.min()}-{sub.comps_total.max()}")

    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2), dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)
    panels = [("b1a2-base", "0.022 baseline (relapse arm)"),
              ("b1a2-gate", "0.022 + deferral gate")]
    for col, (key, title) in enumerate(panels):
        t = wins[key][0].t_min.values
        h = np.vstack([w.h.values for w in wins[key]])
        wait = np.vstack([w.wait.values for w in wins[key]])
        axh, axw = axes[0][col], axes[1][col]
        axh.fill_between(t, np.nanmin(h, axis=0), np.nanmax(h, axis=0),
                         color=wash(SERIES[2], 0.35), lw=0)
        axh.plot(t, np.nanmean(h, axis=0), color=SERIES[2], lw=1.6)
        axh.set_ylim(0, 1.03)
        axh.set_title(title, fontsize=10)
        axw.fill_between(t, wait.min(axis=0), wait.max(axis=0),
                         color=wash(SERIES[2], 0.35), lw=0)
        axw.plot(t, wait.mean(axis=0), color=SERIES[2], lw=1.6)
        axw.set_yscale("symlog", linthresh=10)
        axw.set_xlabel("minutes", fontsize=9)
        for ax in (axh, axw):
            style_axes(ax)
            ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.axvspan(T_ON / 60, T_OFF / 60, color=wash("#d03b3b", 0.10),
                       zorder=0)
    axes[0][0].set_ylabel("token hit rate", fontsize=9)
    axes[1][0].set_ylabel("waiting (symlog)", fontsize=9)
    fig.suptitle("Surge-smoothing deferral gate at the 8x-0.022 relapse "
                 f"point (DES, {N_SEED} seeds, min-max band)",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "smooth_surge_dryrun.png", facecolor=PAGE)
    print("wrote out/smooth_surge_dryrun.csv, out/smooth_surge_dryrun.png")


if __name__ == "__main__":
    main()
