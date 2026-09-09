"""Perturbation-protocol timeline schematic (paper Section 3.3).

Schematic, no data series. All numbers are the protocol constants:
reset at t=0; base Poisson session arrivals at lambda_s from t=0;
surge overlay 0.25 sps x 2700 s over [62, 107) min (T_ON/T_OFF in
des_b1.py); surge population cancelled at t=107; warm read window
[30, 60] (separatrix_fit.py WARM_LO/WARM_HI); kv115 drain-depth read
window [115, 120), opening 8 min after cancellation
(separatrix-findings.md); outcome classification window [270, 295]
(mean h < 0.15 -> cold; separatrix-findings.md).

Run from docs/research/kv_equilibrium/:
    ../.venv/bin/python fig_protocol.py
Writes out/paper/fig_protocol.png.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out" / "paper"
OUT.mkdir(parents=True, exist_ok=True)

SURGE_RED = "#d03b3b"
T_ON, T_OFF = 62, 107
WARM = (30, 60)
DRAIN = (107, 120)
KV115 = (115, 120)
CLASSIFY = (270, 295)

fig, ax = plt.subplots(figsize=(9.6, 3.4), dpi=150)
fig.patch.set_facecolor(PAGE)
style_axes(ax)
ax.grid(True, axis="x", color=GRID, lw=0.6, alpha=0.7)
ax.set_axisbelow(True)

# Standard surge-window shading, full height.
ax.axvspan(T_ON, T_OFF, color=wash(SURGE_RED, 0.10), zorder=0)

# Lane bars. y in axis units 0..1; y-axis carries no quantity.
BAR_H = 0.085


def lane(y0, x0, x1, face, edge):
    ax.add_patch(Rectangle((x0, y0), x1 - x0, BAR_H, facecolor=face,
                           edgecolor=edge, lw=1.0, zorder=3))


# Base session arrivals: t=0 to horizon end.
Y_BASE = 0.84
lane(Y_BASE, 0, 300, wash(SERIES[0], 0.35), SERIES[0])
ax.text(150, Y_BASE + BAR_H + 0.030,
        "base session arrivals, Poisson at lambda_s, t=0 to end of horizon (150-300 min)",
        ha="center", fontsize=8.5, color=INK2)

# Surge overlay: [62, 107).
Y_SURGE = 0.62
lane(Y_SURGE, T_ON, T_OFF, wash(SURGE_RED, 0.35), SURGE_RED)
ax.text((T_ON + T_OFF) / 2, Y_SURGE + BAR_H + 0.030,
        "surge overlay 0.25 sps x 2700 s\n(disjoint corpus, no cache reset)",
        ha="center", fontsize=8.5, color=INK2)

# Reset marker at t=0.
ax.axvline(0, color=INK2, lw=1.2, zorder=2)
ax.annotate("prefix cache reset\n(all pods), t=0", xy=(0, 0.52),
            xytext=(12, 0.49), fontsize=8.5, color=INK2,
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))

# Cancellation marker at t=107; capped below the base-arrivals text.
ax.axvline(T_OFF, ymax=0.90 / 1.04, color=SURGE_RED, lw=1.2,
           ls=(0, (4, 3)), zorder=2)
ax.annotate("surge population\ncancelled, t=107", xy=(T_OFF, 0.58),
            xytext=(128, 0.60), fontsize=8.5, color=INK2,
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))

# Read/observation windows, lower lanes.
Y_WIN = 0.30
lane(Y_WIN, *WARM, wash(SERIES[2], 0.35), SERIES[2])
ax.text(sum(WARM) / 2, Y_WIN - 0.13, "warm read\n[30, 60]",
        ha="center", fontsize=8, color=INK2)

lane(Y_WIN, *DRAIN, wash(SERIES[1], 0.30), SERIES[1])
ax.text(sum(DRAIN) / 2 + 20, Y_WIN - 0.13,
        "post-cancel drain vs catch-up race\n[107, ~120)",
        ha="center", fontsize=8, color=INK2)

lane(Y_WIN, *CLASSIFY, wash(SERIES[2], 0.35), SERIES[2])
ax.text(298, Y_WIN - 0.13,
        "outcome classification [270, 295],\ncold if mean h < 0.15",
        ha="right", fontsize=8, color=INK2)

# kv115 separatrix read point: window [115, 120), marker at its opening.
Y_KV = Y_WIN + BAR_H + 0.02
lane(Y_KV, *KV115, wash(INK, 0.20), INK)
ax.plot([115], [Y_KV + BAR_H / 2], marker="o", ms=5, mfc=INK, mec=INK,
        zorder=4)
ax.annotate("kv115 read: fleet-mean KV over [115, 120),\nopens 8 min after cancellation",
            xy=(120, Y_KV + BAR_H / 2), xytext=(158, 0.05),
            fontsize=8.5, color=INK, ha="left",
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))

ax.set_xlim(-6, 306)
ax.set_ylim(0, 1.04)
ax.set_xticks([0, 60, 120, 180, 240, 300])
ax.set_yticks([])
ax.spines["left"].set_visible(False)
ax.set_xlabel("minutes since run start", fontsize=9)
ax.set_title("Perturbation protocol timeline (schematic)", fontsize=11)

handles = [
    Patch(facecolor=wash(SERIES[0], 0.35), edgecolor=SERIES[0],
          label="base load"),
    Patch(facecolor=wash(SURGE_RED, 0.35), edgecolor=SURGE_RED,
          label="surge overlay [62, 107)"),
    Patch(facecolor=wash(SERIES[1], 0.30), edgecolor=SERIES[1],
          label="drain vs catch-up race [107, ~120)"),
    Patch(facecolor=wash(INK, 0.20), edgecolor=INK,
          label="kv115 window [115, 120)"),
    Patch(facecolor=wash(SERIES[2], 0.35), edgecolor=SERIES[2],
          label="read windows [30, 60] and [270, 295]"),
]
ax.legend(handles=handles, fontsize=8, frameon=False, loc="center",
          bbox_to_anchor=(0.75, 0.62), labelcolor=INK2)

fig.tight_layout()
fig.savefig(OUT / "fig_protocol.png", facecolor=PAGE)
print(OUT / "fig_protocol.png")
