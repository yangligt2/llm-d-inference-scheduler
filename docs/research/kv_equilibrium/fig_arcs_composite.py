"""Figure 1: measured multi-arc composite, one arc per regime class.

Five measured runs from out/arcs/ (5-min windows, per-pod scrapes;
no model output):

    warm recovery            ppc-bimod4-017      8x-0.017 no-offload
    absorbing relapse        ppc-lh-noofl        8x-0.022 no-offload
    organic-late collapse    ppc-edge020-noofl   8x-0.020 no-offload
    restore-bound congestion cpuofl-500-bimod5   8x-0.022 tier-500
    tier full heal           cpuofl-a4-375-lh    8x-0.022 tier-375

Colors are fixed per run entity. SERIES from phase_diagram supplies
slots 1-3; slots 4-5 extend the palette with a violet and a rose
chosen for contrast against SERIES and against the surge-window red
wash. For the congestion arc, ext_hit is drawn as a dashed line in
the same entity color.

Run from kv_equilibrium/:  ../.venv/bin/python fig_arcs_composite.py
Writes out/paper/fig_arcs_composite.png.
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

SERIES5 = SERIES + ["#8a5bc7", "#c94f7c"]  # slots 4-5: violet, rose
T_ON_MIN, T_OFF_MIN = 62.0, 107.0          # surge overlay window

ARCS_SPEC = [
    # run csv, label, fixed color
    ("ppc-bimod4-017", "warm recovery (8x-0.017 no-offl)", SERIES5[0]),
    ("ppc-lh-noofl", "absorbing relapse (8x-0.022 no-offl)", SERIES5[1]),
    ("ppc-edge020-noofl", "organic-late collapse (8x-0.020 no-offl)",
     SERIES5[2]),
    ("cpuofl-500-bimod5", "restore-bound congestion (8x-0.022 tier-500)",
     SERIES5[3]),
    ("cpuofl-a4-375-lh", "tier full heal (8x-0.022 tier-375)", SERIES5[4]),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig, (axh, axw) = plt.subplots(2, 1, figsize=(8.4, 6.8), dpi=150,
                                   sharex=True)
    fig.patch.set_facecolor(PAGE)

    for csv, label, color in ARCS_SPEC:
        d = pd.read_csv(ARCS / f"{csv}.csv")
        axh.plot(d.t_min, d.h, color=color, lw=1.8)
        axw.plot(d.t_min, d.wait, color=color, lw=1.8, label=label)
        if csv == "cpuofl-500-bimod5":
            axh.plot(d.t_min, d.ext_h, color=color, lw=1.2,
                     ls=(0, (4, 2)))
            axw.plot([], [], color=color, lw=1.2, ls=(0, (4, 2)),
                     label="ext_hit (tier-500 arc, top panel)")

    axh.set_ylim(0, 1.03)
    axh.set_ylabel("token hit rate", fontsize=9)
    axw.set_yscale("symlog", linthresh=10)
    axw.set_ylim(-3, 1200)
    axw.set_ylabel("waiting (symlog)", fontsize=9)
    axw.set_xlabel("minutes", fontsize=9)
    axw.set_xlim(0, 302)

    for ax in (axh, axw):
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axvspan(T_ON_MIN, T_OFF_MIN, color=wash("#d03b3b", 0.10),
                   zorder=0)
    handles, labels = axw.get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, frameon=False, ncol=2,
               loc="lower center", labelcolor=INK2,
               bbox_to_anchor=(0.5, 0.0))
    fig.suptitle("Measured arcs, one per regime class "
                 "(5-min windows, per-pod scrapes)", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    fig.savefig(OUT / "fig_arcs_composite.png", facecolor=PAGE)
    print(f"wrote {OUT / 'fig_arcs_composite.png'}")


if __name__ == "__main__":
    main()
