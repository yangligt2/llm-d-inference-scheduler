"""N-series and tier-capacity overlays: RouterSessionSim vs measured arcs.

Two figures, 300-min horizon, 5 seeds per arm:

out/overlay_nseries.png - the coordination-layer contrast at
per-capacity-matched points (research-status headline A):
    4x-0.011 tier      measured cpuofl4x-falsifier (210 min) and
                       cpuofl4x-falsifier-300m
    8x-0.020 no-offl   measured draws spanning the three outcome
                       classes (clean / organic-late / fast relapse)
    16x-0.040 no-offl  measured ppc-n16-lh040 and -r2
The DES fleet-size separation is emergent from the deployed router
coupling (RouterSessionSim docstring); measured and DES outcome
distributions are both bimodal at 8x-0.020, so the bands span
classes rather than tracking one arc.

out/overlay_tiercap.png - the tier-capacity series at 8x-0.022:
sizes 250 (measured cold), 375 (measured healed 2/2), 500 (measured
2 healed / 4 congested). DES capacities are TIER_EFF-scaled; the
DES carries the cold boundary but has no heal branch (documented in
overlay-findings.md).

Run from docs/research/:  .venv/bin/python kv_equilibrium/overlay_nseries.py
Also writes out/overlay_nseries_summary.csv.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from des_b1 import (RouterSessionSim, C_CPU_250, C_CPU_375, C_CPU_500,
                    T_ON, T_OFF, N_SEED)
from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"
T_END = 300 * 60.0

NSERIES = [
    # label, [measured csvs], replicas, base sps, surge sps, c_cpu/replica
    ("4x-0.011 + tier (falsifier)",
     ["cpuofl4x-falsifier-300m", "cpuofl4x-falsifier"], 4, 0.011,
     0.125, C_CPU_500),
    ("8x-0.020 no-offload",
     ["ppc-shard-a2-020", "ppc-edge020-noofl", "ppc-shard-b2-020"], 8, 0.020,
     0.25, 0.0),
    ("16x-0.040 no-offload", ["ppc-n16-lh040", "ppc-n16-lh040-r2"], 16,
     0.040, 0.50, 0.0),
]

TIERCAP = [
    ("8x-0.022 tier 250", ["cpuofl-a4half-lh"], 8, 0.022, 0.25, C_CPU_250),
    ("8x-0.022 tier 375", ["cpuofl-a4-375-lh", "cpuofl-a4-375-r2"], 8,
     0.022, 0.25, C_CPU_375),
    ("8x-0.022 tier 500", ["cpuofl-a4full-lh", "cpuofl-500-bimod5"], 8,
     0.022, 0.25, C_CPU_500),
]


def run_seeds(n, lb, ls, ccpu):
    wins = []
    for seed in range(1, N_SEED + 1):
        sim = RouterSessionSim(n, lb, ls, ccpu, seed, t_end=T_END)
        sim.run()
        wins.append(sim.windows())
    return wins


def overlay(arms, fname, title):
    fig, axes = plt.subplots(2, len(arms), figsize=(4.2 * len(arms), 6.4),
                             dpi=150, sharex=True, squeeze=False)
    fig.patch.set_facecolor(PAGE)
    summary = []
    for col, (label, csvs, n, lb, ls, ccpu) in enumerate(arms):
        wins = run_seeds(n, lb, ls, ccpu)
        t_min = wins[0].t_min.values
        h = np.vstack([w.h.values for w in wins])
        wait = np.vstack([w.wait.values for w in wins])
        axh, axw = axes[0][col], axes[1][col]
        for k, csv in enumerate(csvs):
            meas = pd.read_csv(ARCS / f"{csv}.csv")
            axh.plot(meas.t_min, meas.h, color=SERIES[0], lw=1.8,
                     alpha=1.0 if k == 0 else 0.55,
                     label="measured" if k == 0 else f"measured ({csv})")
            axw.plot(meas.t_min, meas.wait, color=SERIES[0], lw=1.8,
                     alpha=1.0 if k == 0 else 0.55)
        axh.fill_between(t_min, np.nanmin(h, axis=0), np.nanmax(h, axis=0),
                         color=wash(SERIES[2], 0.35), lw=0,
                         label="DES min-max")
        axh.plot(t_min, np.nanmean(h, axis=0), color=SERIES[2], lw=1.6,
                 label="DES mean")
        axh.set_ylim(0, 1.03)
        axh.set_title(label, fontsize=9.5)
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
        for seed0, w in enumerate(wins):
            end = w[(w.t_min >= 270) & (w.t_min <= 295)]
            summary.append({"figure": fname, "arm": label, "seed": seed0 + 1,
                            "end_h": end.h.mean(), "end_wait": end.wait.mean()})
    axes[0][0].set_ylabel("token hit rate", fontsize=9)
    axes[1][0].set_ylabel("waiting (symlog)", fontsize=9)
    axes[0][0].legend(fontsize=8, frameon=False, loc="lower left",
                      labelcolor=INK2)
    fig.suptitle(title, fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / fname, facecolor=PAGE)
    return summary


def main():
    rows = []
    rows += overlay(NSERIES, "overlay_nseries.png",
                    "Fleet-size series at per-capacity-matched load: "
                    f"DES with deployed coordination layer ({N_SEED} seeds)")
    rows += overlay(TIERCAP, "overlay_tiercap.png",
                    "Tier-capacity series at 8x-0.022, sizes 250/375/500 "
                    f"({N_SEED} seeds)")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "overlay_nseries_summary.csv", index=False,
              float_format="%.4f")
    for _, r in df.iterrows():
        print(f"  {r['arm']:<28} seed {r.seed}: end_h {r.end_h:5.2f} "
              f"end_wait {r.end_wait:6.0f}")
    print("wrote out/overlay_nseries.png, out/overlay_tiercap.png, "
          "out/overlay_nseries_summary.csv")


if __name__ == "__main__":
    main()
