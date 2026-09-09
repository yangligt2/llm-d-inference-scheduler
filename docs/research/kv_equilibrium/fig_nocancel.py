"""Figure: never-cancelled flash-crowd block (window 2026-08-27/28).

Four measured runs from out/arcs/, all base 0.017 sessions/s, surge
cohorts injected at t=62 min and never cancelled:

    entrapped, cohort 132     nc-a-base017    8x no-offload
    absorbed, cohort 66       nc-d-base017    8x no-offload
    no-surge control          nc-b-base017    8x no-offload
    tier digestion, cohort 132  tb1r-base017  8x tier-500

Colors are fixed per run entity (SERIES slots 1-3 + violet slot 4,
matching fig_arcs_composite). The tier arc carries ext_hit as a
dashed line in the same entity color. The surge overlay marks the
~10-min injection window only; the cohort itself persists.

Run from kv_equilibrium/:  ../.venv/bin/python fig_nocancel.py
Writes out/paper/fig_nocancel.png.
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

SERIES4 = SERIES + ["#8a5bc7"]             # slot 4: violet
T_ON_MIN, T_INJ_END_MIN = 62.0, 72.0       # ~600 s injection window

ARCS_SPEC = [
    ("nc-b-base017", "no-surge control (no-offl)", SERIES4[0]),
    ("nc-a-base017", "cohort 132: entrapped (no-offl)", SERIES4[1]),
    ("nc-d-base017", "cohort 66: absorbed (no-offl)", SERIES4[2]),
    ("tb1r-base017", "cohort 132: digested (tier-500)", SERIES4[3]),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig, (axh, axw) = plt.subplots(2, 1, figsize=(8.4, 6.4), dpi=150,
                                   sharex=True)
    fig.patch.set_facecolor(PAGE)

    for csv, label, color in ARCS_SPEC:
        d = pd.read_csv(ARCS / f"{csv}.csv")
        axh.plot(d.t_min, d.h, color=color, lw=1.8)
        axw.plot(d.t_min, d.wait, color=color, lw=1.8, label=label)
        if csv == "tb1r-base017":
            axh.plot(d.t_min, d.ext_h, color=color, lw=1.2,
                     ls=(0, (4, 2)))
            axw.plot([], [], color=color, lw=1.2, ls=(0, (4, 2)),
                     label="ext_hit (tier arc, top panel)")

    axh.set_ylim(0, 1.03)
    axh.set_ylabel("token hit rate", fontsize=9)
    axw.set_yscale("symlog", linthresh=10)
    axw.set_ylim(-3, 700)
    axw.set_ylabel("waiting (symlog)", fontsize=9)
    axw.set_xlabel("minutes", fontsize=9)
    axw.set_xlim(0, 302)

    for ax in (axh, axw):
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axvspan(T_ON_MIN, T_INJ_END_MIN, color=wash("#d03b3b", 0.10),
                   zorder=0)
    handles, labels = axw.get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, frameon=False, ncol=2,
               loc="lower center", labelcolor=INK2,
               bbox_to_anchor=(0.5, 0.0))
    fig.suptitle("Never-cancelled flash crowds at base 0.017 sessions/s "
                 "(injection window shaded; cohorts persist)",
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    fig.savefig(OUT / "fig_nocancel.png", facecolor=PAGE)
    print(f"wrote {OUT / 'fig_nocancel.png'}")


if __name__ == "__main__":
    main()
