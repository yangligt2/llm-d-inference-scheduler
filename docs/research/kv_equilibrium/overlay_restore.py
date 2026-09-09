"""Restore-bound congestion overlay and stability-boundary sweep.

Overlays the extended DES (des_b1.py: per-node restore channel at B_R,
per-pod tpot, two-clock tier LRU) and the extended fluid model against
the measured tier runs and the long-horizon pair:

    col 1  8x 0.022 no-offload    ppc-lh-noofl (300 min) + ppc-b1a2-base
    col 2  8x 0.022 + CPU tier    cpuofl-lh-tier (300 min),
                                  cpuofl-a1-tier022, cpuofl-a1rep
    col 3  4x 0.011 + CPU tier    cpuofl-b2a-base (180 min)

Rows: token hit rate, waiting queue, fleet restore rate (with the
N * B_R capacity line). 5 seeds per DES arm.

The sweep then maps the 8x tier fleet's stability boundary in lambda_s
(recovery -> congestion -> cold collapse, if present), the A4
prediction (congestion onset vs c_cpu at half and double the current
1.26M tok/replica), and the 4x per-capacity points for the scale
question. Classification uses the 270-295 min window: cold if
h < 0.15; recovered if wait < 15 and h > 0.9; congested otherwise.

Run from docs/research/:  .venv/bin/python kv_equilibrium/overlay_restore.py
Writes out/overlay_restore.png, out/overlay_restore_summary.csv,
out/restore_boundary.csv.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from des_b1 import SessionSim, B_R, T_ON, T_OFF, N_SEED
from overlay_b1_dynamics import simulate as fluid_simulate
from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

COLS = [
    ("noofl022", "0.022 sps no-offload (lh pair)",
     ["ppc-lh-noofl", "ppc-b1a2-base"], 8, 0.022, 0.25, 0.0, 300),
    ("tier022", "0.022 sps + tier, 8x (third regime)",
     ["cpuofl-lh-tier", "cpuofl-a1-tier022", "cpuofl-a1rep"],
     8, 0.022, 0.25, 1.26e6, 300),
    ("tier011", "0.011 sps + tier, 4x (B2a)",
     ["cpuofl-b2a-base"], 4, 0.011, 0.125, 1.26e6, 180),
]

SWEEP_8X = [0.014, 0.017, 0.020, 0.022, 0.026, 0.030]
SWEEP_CCPU = [0.63e6, 2.52e6]          # at 0.022; 1.26e6 is the tier022 arm
SWEEP_4X = [0.011, 0.013, 0.015]       # per-capacity 2x = 0.022, 0.026, 0.030


def run_des(n, lam, surge, ccpu, seed, t_end_min):
    sim = SessionSim(n, lam, surge, ccpu, seed, t_end=t_end_min * 60.0)
    sim.run()
    return sim.windows()


def classify(win):
    end = win[(win.t_min > 270) & (win.t_min <= 295)]
    if not len(end):
        end = win[(win.t_min > 150) & (win.t_min <= 175)]
    h, wait = end.h.mean(), end.wait.mean()
    rst = end.restore_s.mean()
    if h < 0.15:
        verdict = "cold"
    elif wait < 15 and h > 0.9:
        verdict = "recovered"
    else:
        verdict = "congested"
    return verdict, h, wait, rst


def main():
    t0 = time.perf_counter()
    fig, axes = plt.subplots(3, 3, figsize=(13, 9), dpi=150, sharex="col")
    fig.patch.set_facecolor(PAGE)
    summary = []
    for col, (key, label, meas_csvs, n, lam, ls, ccpu, tmin) in enumerate(COLS):
        wins = [run_des(n, lam, ls, ccpu, seed, tmin)
                for seed in range(1, N_SEED + 1)]
        fl = fluid_simulate(n, lam, (T_ON, T_OFF, ls), tmin, ccpu)
        t = wins[0].t_min.values
        h = np.vstack([w.h.values for w in wins])
        wait = np.vstack([w.wait.values for w in wins])
        rst = np.vstack([w.restore_s.values for w in wins])

        axh, axw, axr = axes[0][col], axes[1][col], axes[2][col]
        for i, csv in enumerate(meas_csvs):
            m = pd.read_csv(ARCS / f"{csv}.csv")
            lw, alpha = (1.8, 1.0) if i == 0 else (1.1, 0.55)
            axh.plot(m.t_min, m.h, color=SERIES[0], lw=lw, alpha=alpha,
                     label="measured" if i == 0 else None)
            axw.plot(m.t_min, m.wait, color=SERIES[0], lw=lw, alpha=alpha)
            if m.restore_s.notna().any():
                axr.plot(m.t_min, m.restore_s, color=SERIES[0], lw=lw,
                         alpha=alpha)
        axh.plot(fl.t_min, fl.h, color=SERIES[1], lw=1.3, ls=(0, (4, 2)),
                 label="fluid")
        axw.plot(fl.t_min, fl.wait, color=SERIES[1], lw=1.3, ls=(0, (4, 2)))
        axr.plot(fl.t_min, fl.restore_s, color=SERIES[1], lw=1.3,
                 ls=(0, (4, 2)))
        axh.fill_between(t, np.nanmin(h, 0), np.nanmax(h, 0),
                         color=wash(SERIES[2], 0.35), lw=0,
                         label="DES min-max")
        axh.plot(t, np.nanmean(h, 0), color=SERIES[2], lw=1.5,
                 label="DES mean")
        axw.fill_between(t, wait.min(0), wait.max(0),
                         color=wash(SERIES[2], 0.35), lw=0)
        axw.plot(t, wait.mean(0), color=SERIES[2], lw=1.5)
        axr.fill_between(t, rst.min(0), rst.max(0),
                         color=wash(SERIES[2], 0.35), lw=0)
        axr.plot(t, rst.mean(0), color=SERIES[2], lw=1.5)
        if ccpu > 0:
            axr.axhline(n * B_R, color=MUTED, lw=1.0, ls=":",
                        label=f"N x B_r = {n * B_R / 1e3:.0f}k")
            axr.legend(fontsize=7.5, frameon=False, labelcolor=INK2)
        axh.set_ylim(0, 1.03)
        axh.set_title(label, fontsize=9.5)
        axw.set_yscale("symlog", linthresh=10)
        axr.set_xlabel("minutes", fontsize=9)
        for ax in (axh, axw, axr):
            style_axes(ax)
            ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.axvspan(T_ON / 60, T_OFF / 60, color=wash("#d03b3b", 0.10),
                       zorder=0)
        for seed, w in zip(range(1, N_SEED + 1), wins):
            verdict, eh, ew, er = classify(w)
            summary.append({"arm": key, "seed": seed, "verdict": verdict,
                            "end_h": eh, "end_wait": ew, "end_restore_s": er})
        vs = [r["verdict"] for r in summary if r["arm"] == key]
        print(f"  {label}: " + ", ".join(f"{v}:{vs.count(v)}"
                                         for v in dict.fromkeys(vs)))
    axes[0][0].set_ylabel("token hit rate", fontsize=9)
    axes[1][0].set_ylabel("waiting (symlog)", fontsize=9)
    axes[2][0].set_ylabel("restore tok/s", fontsize=9)
    axes[0][0].legend(fontsize=8, frameon=False, loc="lower left",
                      labelcolor=INK2)
    fig.suptitle("Restore-bound congestion: DES / fluid vs measured "
                 f"({N_SEED} seeds, B_r = {B_R / 1e3:.0f}k tok/s/replica)",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "overlay_restore.png", facecolor=PAGE)
    pd.DataFrame(summary).to_csv(OUT / "overlay_restore_summary.csv",
                                 index=False, float_format="%.4f")
    print(f"figure done ({time.perf_counter() - t0:.0f}s); sweeping")

    rows = []
    def sweep(tag, n, lam, ls, ccpu):
        for seed in range(1, N_SEED + 1):
            win = run_des(n, lam, ls, ccpu, seed, 300)
            verdict, eh, ew, er = classify(win)
            mid = win[(win.t_min > 150) & (win.t_min <= 175)]
            rows.append({"sweep": tag, "n": n, "lam": lam, "c_cpu": ccpu,
                         "seed": seed, "verdict": verdict, "end_h": eh,
                         "end_wait": ew, "end_restore_s": er,
                         "wait_150_175": mid.wait.mean()})
        vs = [r["verdict"] for r in rows
              if (r["sweep"], r["lam"], r["c_cpu"]) == (tag, lam, ccpu)]
        print(f"  {tag} lam={lam:.3f} c_cpu={ccpu / 1e6:.2f}M: "
              + ", ".join(f"{v}:{vs.count(v)}" for v in dict.fromkeys(vs)))

    for lam in SWEEP_8X:
        sweep("lam8x", 8, lam, 0.25, 1.26e6)
    for cc in SWEEP_CCPU:
        sweep("ccpu", 8, 0.022, 0.25, cc)
    for lam in SWEEP_4X:
        sweep("lam4x", 4, lam, 0.125, 1.26e6)
    pd.DataFrame(rows).to_csv(OUT / "restore_boundary.csv", index=False,
                              float_format="%.4f")
    print(f"wrote out/overlay_restore.png, out/overlay_restore_summary.csv, "
          f"out/restore_boundary.csv ({time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
