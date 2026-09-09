"""Band tally figure (paper 4.2): outcome counts per base rate.

Stacked draw counts by outcome class for the identical perturbation
on the 8x no-offload fleet, from the notebook ledgers
(research-status.md result 2; draft.md 4.2 table):

    0.012  2 draws   clean recovery x2
    0.017  4 draws   clean recovery x4
    0.020  8 draws   clean x3, organic-late collapse x2, fast relapse x3
    0.022  3 draws   fast relapse x3 (absorbing)

Class colors are fixed per outcome class and shared with the arcs
composite (fig_arcs_composite.py): clean recovery = SERIES[0],
fast/absorbing relapse = SERIES[1], organic-late collapse = SERIES[2].

Run from kv_equilibrium/:  ../.venv/bin/python fig_band_tally.py
Writes out/paper/fig_band_tally.png.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes

OUT = Path(__file__).parent / "out" / "paper"
OUT.mkdir(parents=True, exist_ok=True)

RATES = ["0.012", "0.017", "0.020", "0.022"]
# per rate: (clean recovery, organic-late collapse, fast relapse)
TALLY = {
    "0.012": (2, 0, 0),
    "0.017": (4, 0, 0),
    "0.020": (3, 2, 3),
    "0.022": (0, 0, 3),
}
CLASSES = ["clean recovery", "organic-late collapse", "fast relapse"]
COLORS = [SERIES[0], SERIES[2], SERIES[1]]

assert sum(sum(v) for v in TALLY.values()) == 17

fig, ax = plt.subplots(figsize=(5.6, 3.8), dpi=150)
fig.patch.set_facecolor(PAGE)
ax.set_facecolor(PAGE)

xs = range(len(RATES))
width = 0.55
for x, rate in zip(xs, RATES):
    counts = TALLY[rate]
    bottom = 0
    for count, color in zip(counts, COLORS):
        if count == 0:
            continue
        ax.bar(x, count, width, bottom=bottom, color=color,
               edgecolor=PAGE, linewidth=1.5, zorder=3)
        ax.text(x, bottom + count / 2, str(count), ha="center",
                va="center", fontsize=9, color=PAGE, zorder=4)
        bottom += count
    ax.text(x, bottom + 0.18, f"n={bottom}", ha="center", va="bottom",
            fontsize=8.5, color=INK2)

# legend proxies keep the fixed class-to-color mapping explicit
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in COLORS]
ax.legend(handles, CLASSES, fontsize=8, frameon=False, loc="upper left",
          labelcolor=INK2)

# hard-relapse edge sits between the 0.020 and 0.022 columns
ax.axvline(2.5, color=MUTED, linewidth=0.8, linestyle=(0, (4, 3)))
ax.text(2.55, 6.0, "hard-relapse edge\nin (0.020, 0.022]", ha="left",
        va="center", fontsize=7.5, color=MUTED)

ax.set_xticks(list(xs))
ax.set_xticklabels(RATES)
ax.set_xlabel("base rate (sps)", fontsize=9)
ax.set_ylabel("draws", fontsize=9)
ax.set_ylim(0, 9)
ax.set_yticks(range(0, 9))
style_axes(ax)
ax.grid(True, axis="y", color=GRID, lw=0.6, alpha=0.7)
ax.set_axisbelow(True)
ax.set_title("Outcome tallies, identical perturbation, 8x no-offload "
             "(n=17)", fontsize=10.5, color=INK)

fig.tight_layout()
fig.savefig(OUT / "fig_band_tally.png", facecolor=PAGE)
print(OUT / "fig_band_tally.png")
