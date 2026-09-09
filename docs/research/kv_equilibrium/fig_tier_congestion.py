"""Figure: CPU-offload tier under the cancelled surge at 0.022 sps -
recovery into restore-bound congestion, heal arms excluded.

Same perturbation as the no-offload relapse (base 0.022 sessions/s,
0.25 sessions/s x 2700 s from t=62, cancelled at t=107), 8x TP4 with
--kv-offloading-size=500. The four measured congested draws are
plotted against the no-offload relapse at the same operating point.

    cpuofl-a1-tier022   180 min   congested
    cpuofl-a1rep        150 min   congested
    cpuofl-lh-tier      300 min   congested, slowly diverging
    cpuofl-500-bimod5   300 min   congested
    ppc-lh-noofl        300 min   no-offload relapse (reference)

Rows: token hit rate (tier draws also carry the CPU-restore share of
hits as a dashed line in the entity color), TTFT p50 (log), completed
throughput, waiting queue (symlog). The tier draws settle into a
distinct third state: h 0.70-0.85, TTFT p50 tens of seconds, ~2x the
cold throughput, queue growing slowly - degraded, not cold.

Run from kv_equilibrium/:  ../.venv/bin/python fig_tier_congestion.py
Writes out/paper/fig_tier_congestion.png.
"""

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

HERE = Path(__file__).parent
ARCS = HERE / "out" / "arcs"
OUT = HERE / "out" / "paper"

SERIES4 = SERIES + ["#8a5bc7"]
SURGE_RED = "#d03b3b"
REF_INK = "#52514e"
SURGE = (62.0, 107.0)

TIER = [
    ("cpuofl-a1-tier022", "tier-500 draw 1 (180 min)", SERIES4[0]),
    ("cpuofl-a1rep", "tier-500 draw 2 (150 min)", SERIES4[1]),
    ("cpuofl-lh-tier", "tier-500 draw 3 (300 min)", SERIES4[2]),
    ("cpuofl-500-bimod5", "tier-500 draw 4 (300 min)", SERIES4[3]),
]
REF = ("ppc-lh-noofl", "no-offload relapse (reference)")


def load(csv):
    # The final window is partial (job ends inside it); drop it.
    return pd.read_csv(ARCS / f"{csv}.csv").iloc[:-1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig, (axh, axt, axr, axw) = plt.subplots(4, 1, figsize=(8.6, 10.2),
                                             dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)

    r = load(REF[0])
    axh.plot(r.t_min, r.h, color=REF_INK, lw=1.5)
    axt.plot(r.t_min, r.ttft_p50, color=REF_INK, lw=1.5)
    axr.plot(r.t_min, r.req_s, color=REF_INK, lw=1.5)
    axw.plot(r.t_min, r["wait"], color=REF_INK, lw=1.5, label=REF[1])

    for csv, label, color in TIER:
        d = load(csv)
        axh.plot(d.t_min, d.h, color=color, lw=1.8)
        axh.plot(d.t_min, d.ext_h, color=color, lw=1.1, ls=(0, (4, 2)))
        axt.plot(d.t_min, d.ttft_p50, color=color, lw=1.8)
        axr.plot(d.t_min, d.req_s, color=color, lw=1.8)
        axw.plot(d.t_min, d["wait"], color=color, lw=1.8, label=label)
    axw.plot([], [], color=INK2, lw=1.1, ls=(0, (4, 2)),
             label="CPU-restore share of hits (tier draws, top panel)")

    axh.set_ylim(0, 1.03)
    axh.set_ylabel("token hit rate", fontsize=9, color=INK2)
    axt.set_yscale("log")
    axt.set_ylim(0.3, 500)
    axt.set_ylabel("TTFT p50, s (log)", fontsize=9, color=INK2)
    axr.set_ylim(0, 5.2)
    axr.set_ylabel("completed req/s", fontsize=9, color=INK2)
    axw.set_yscale("symlog", linthresh=10)
    axw.set_ylim(-3, 1000)
    axw.set_ylabel("waiting requests (symlog)", fontsize=9, color=INK2)
    axw.set_xlabel("minutes from base start", fontsize=9, color=INK2)
    axw.set_xlim(0, 302)

    for ax in (axh, axt, axr, axw):
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axvspan(*SURGE, color=wash(SURGE_RED, 0.10), zorder=0)
        ax.tick_params(labelsize=8, colors=INK2)

    axw.legend(fontsize=8, frameon=False, loc="upper center",
               bbox_to_anchor=(0.5, -0.22), ncol=2, labelcolor=INK2)
    fig.suptitle("CPU-offload tier under the cancelled surge at 0.022 sps: "
                 "recovery into restore-bound congestion\n"
                 "(8x TP4, kv-offloading-size 500; surge window shaded; "
                 "no-offload relapse at the same point for reference)",
                 fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0.02, 1, 0.955))
    fig.savefig(OUT / "fig_tier_congestion.png", facecolor=PAGE)
    print(f"wrote {OUT / 'fig_tier_congestion.png'}")


if __name__ == "__main__":
    main()
