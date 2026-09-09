"""tpot interference form discrimination: fleet-R vs per-pod-R.

The interference fit tpot(R) = 9.6e-3 + 3.8e-6 R^2 uses the FLEET
running count and was calibrated only on 8-replica closed-loop cells,
so it is not scale-invariant: at equal per-pod load it assigns 4x the
interference to an 8-replica fleet vs a 4-replica one. The 4-replica
cpuofl-b2a arc provides independent (running, tpot) windows. This
script pools per-window (N_replicas, R_fleet, tpot_p50) points from
every extracted arc and least-squares fits both forms:

    A: tpot = a + b  * R_fleet^2
    B: tpot = a + b' * (R_fleet / N)^2

reporting per-fleet RMSE for each. Windows need >= MIN_REQ_S client
completions for a stable p50.

Run from docs/research/:  .venv/bin/python kv_equilibrium/tpot_fit.py
Writes out/tpot_fit.csv and out/tpot_fit.png.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

MIN_REQ_S = 0.05         # >= 15 completions per 300 s window; the
                         # saturated (high-R) windows complete few
                         # requests and carry the discrimination signal
TPOT_CAP = 0.30

RUNS_4X = ["cpuofl-b2a-base"]
RUNS_8X = ["ppc-b1a-base", "ppc-b1a2-base", "ppc-b1a2-rep-base",
           "ppc-b1b-base", "ppc-b1b-rep-base", "ppc-b1c-base",
           "ppc-bimod2", "ppc-bimod3", "ppc-lh-noofl",
           "cpuofl-a1-tier022", "cpuofl-a1rep", "cpuofl-lh-tier",
           "ppc-e1-conc40", "ppc-e1-conc60", "ppc-e1-conc80",
           "ppc-e1-conc100", "ppc-e7-conc40-120min"]


def points():
    rows = []
    for n, runs in ((4, RUNS_4X), (8, RUNS_8X)):
        for run in runs:
            a = pd.read_csv(ARCS / f"{run}.csv")
            a = a[(a.req_s >= MIN_REQ_S) & a.tpot_p50.notna()
                  & (a.tpot_p50 < TPOT_CAP) & (a["run"] > 0)]
            for _, r in a.iterrows():
                rows.append((run, n, r["run"], r.tpot_p50))
    return pd.DataFrame(rows, columns=["run", "n", "R", "tpot"])


def fit(x2, y):
    A = np.vstack([np.ones_like(x2), x2]).T
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    return a, b


def main():
    df = points()
    xA = df.R.values ** 2
    xB = (df.R.values / df.n.values) ** 2
    y = df.tpot.values
    aA, bA = fit(xA, y)
    aB, bB = fit(xB, y)
    df["predA"] = aA + bA * xA
    df["predB"] = aB + bB * xB

    print(f"n points: {len(df)} ({(df.n == 4).sum()} at 4x, "
          f"{(df.n == 8).sum()} at 8x)")
    print(f"form A (fleet-R):   tpot = {aA * 1e3:.2f} ms + "
          f"{bA:.3e} * R^2")
    print(f"form B (per-pod-R): tpot = {aB * 1e3:.2f} ms + "
          f"{bB:.3e} * (R/N)^2")
    for n in (4, 8):
        s = df[df.n == n]
        ra = np.sqrt(((s.tpot - s.predA) ** 2).mean()) * 1e3
        rb = np.sqrt(((s.tpot - s.predB) ** 2).mean()) * 1e3
        print(f"  {n}x fleet ({len(s):3d} windows): RMSE A {ra:6.2f} ms, "
              f"RMSE B {rb:6.2f} ms")
    ra = np.sqrt(((df.tpot - df.predA) ** 2).mean()) * 1e3
    rb = np.sqrt(((df.tpot - df.predB) ** 2).mean()) * 1e3
    print(f"  pooled: RMSE A {ra:6.2f} ms, RMSE B {rb:6.2f} ms")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150, sharey=True)
    fig.patch.set_facecolor(PAGE)
    for ax, (xcol, title, a, b) in zip(axes, [
            (df.R, "form A: fleet R", aA, bA),
            (df.R / df.n, "form B: per-pod R", aB, bB)]):
        for n, color, mk in ((8, SERIES[0], "o"), (4, SERIES[1], "s")):
            s = df[df.n == n]
            x = s.R if title.startswith("form A") else s.R / s.n
            ax.scatter(x, s.tpot * 1e3, s=14, color=color, marker=mk,
                       alpha=0.6, label=f"{n} replicas")
        xs = np.linspace(0, xcol.max() * 1.05, 200)
        ax.plot(xs, (a + b * xs ** 2) * 1e3, color=INK, lw=1.4,
                ls=(0, (4, 2)), label="fit")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("running requests", fontsize=9)
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("tpot p50, ms", fontsize=9)
    axes[0].legend(fontsize=8, frameon=False, labelcolor=INK2)
    fig.suptitle("tpot interference: fleet-R vs per-pod-R forms",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "tpot_fit.png", facecolor=PAGE)
    df.to_csv(OUT / "tpot_fit.csv", index=False, float_format="%.5f")
    print("wrote out/tpot_fit.png, out/tpot_fit.csv")


if __name__ == "__main__":
    main()
