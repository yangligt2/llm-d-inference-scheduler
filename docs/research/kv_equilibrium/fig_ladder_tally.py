"""16x-vs-8x ladder tally (draft Section 6.1, research-status result 6).

Collapse fraction per operating point on a shared per-8x-equivalent
rate axis. Tallies from the notebook ledgers consolidated in the
research-status data-sufficiency table:
    8x:  0.017 -> 0/4, 0.020 -> 5/8, 0.022 -> 3/3
    16x: 0.034 -> 0/1, 0.037 -> 1/2, 0.040 -> 4/4
        (per-8x-equivalent 0.017 / 0.0185 / 0.020; the 0.040 tally
        counts the 135-min truncated draw, per the draft; the
        Section 4.5 fit excludes it)
Points only, dashed guide lines; no fitted or smoothed curve.

Run from docs/research/kv_equilibrium/:
    ../.venv/bin/python fig_ladder_tally.py
Writes out/paper/fig_ladder_tally.png.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes

OUT = Path(__file__).parent / "out" / "paper"

# (per-8x-eq rate, collapses, draws, native-rate label or None)
LADDER_8X = [(0.017, 0, 4, None), (0.020, 5, 8, None), (0.022, 3, 3, None)]
LADDER_16X = [(0.017, 0, 1, "0.034"), (0.0185, 1, 2, "0.037"),
              (0.020, 4, 4, "0.040")]


def main():
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=150)
    fig.patch.set_facecolor(PAGE)

    for (pts, color, marker, label, open_face, dy) in [
            (LADDER_8X, SERIES[0], "o", "8x ladder (rate as run)",
             False, -0.085),
            (LADDER_16X, SERIES[1], "s", "16x ladder (rate / 2)",
             True, 0.065)]:
        x = [p[0] for p in pts]
        y = [p[1] / p[2] for p in pts]
        ax.plot(x, y, color=color, lw=1.0, ls=(0, (4, 3)), alpha=0.55,
                zorder=2)
        ax.plot(x, y, color=color, marker=marker, ls="none", ms=7.5,
                markerfacecolor="none" if open_face else color,
                markeredgewidth=1.6, label=label, zorder=3)
        for xi, c, n, native in pts:
            ax.annotate(f"{c}/{n}", (xi, c / n),
                        xytext=(0, 16 if dy > 0 else -16),
                        textcoords="offset points", ha="center",
                        va="bottom" if dy > 0 else "top",
                        fontsize=9, color=INK2)
            if native:
                ax.annotate(f"({native})", (xi, c / n),
                            xytext=(0, 28), textcoords="offset points",
                            ha="center", va="bottom",
                            fontsize=7.5, color=MUTED)

    # Mixed-outcome point shift 0.020 (8x, 5/8) -> 0.0185 (16x, 1/2).
    for xv in (0.0185, 0.020):
        ax.axvline(xv, color=MUTED, lw=0.7, ls=(0, (2, 3)), zorder=1)
    ax.annotate("", xy=(0.0185, 0.47), xytext=(0.020, 0.47),
                arrowprops=dict(arrowstyle="->", color=INK2, lw=1.0))
    ax.text(0.01925, 0.395, "mixed point\n0.020 -> 0.0185\n(~7.5%)",
            ha="center", va="top", fontsize=8, color=INK2)

    ax.set_xlim(0.0162, 0.0228)
    ax.set_ylim(-0.14, 1.2)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticks([0.017, 0.0185, 0.020, 0.022])
    ax.set_xlabel("per-8x-equivalent rate (sessions/s per pod, x8)",
                  fontsize=9)
    ax.set_ylabel("collapse fraction (collapses / draws)", fontsize=9)
    style_axes(ax)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8.5, frameon=False, loc="upper left",
              labelcolor=INK2)
    ax.set_title("Collapse tallies at per-capacity-matched operating "
                 "points", fontsize=11, color=INK)

    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / "fig_ladder_tally.png", facecolor=PAGE)
    print(f"wrote {OUT / 'fig_ladder_tally.png'}")


if __name__ == "__main__":
    main()
