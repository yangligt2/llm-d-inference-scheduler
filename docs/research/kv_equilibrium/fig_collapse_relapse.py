"""Figure: the two failure trajectories under a session-rate surge,
recovery arms excluded.

Left column  - never-cancelled flash crowd (base 0.017 sessions/s,
               cohort 132 injected over ~10 min from t=62): direct
               entrapment, collapse onset within one window of
               injection end.
Right column - cancelled surge (base 0.022 sessions/s, 0.25
               sessions/s x 2700 s from t=62, population cancelled at
               t=107): partial post-cancellation recovery, then relapse
               into the same absorbing state.
Rows: token hit rate, fleet KV occupancy, waiting queue (symlog).

Two variants are written:
  fig_collapse_relapse_vllm.png   every measured vLLM/llm-d draw of
                                  each protocol (4 + 3), plus the
                                  no-surge control as a gray reference
  fig_collapse_relapse_stacks.png one draw per serving stack
                                  (vLLM/llm-d, NVIDIA Dynamo, SGLang)

Colors are fixed per entity (SERIES slots 1-3 + violet slot 4,
validated light-mode); the control is muted ink, dashed. Surge
windows are shaded (no-cancel: the injection window only, the cohort
persists; cancel: the full surge job lifetime).

Run from kv_equilibrium/:  ../.venv/bin/python fig_collapse_relapse.py
"""

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes, wash

HERE = Path(__file__).parent
ARCS = HERE / "out" / "arcs"
OUT = HERE / "out" / "paper"

SERIES4 = SERIES + ["#8a5bc7"]
SURGE_RED = "#d03b3b"

# (csv, label, color) per column; control drawn separately.
VLLM = {
    "nocancel": {
        "arcs": [("nc-a-base017", "draw 1 (fleet A)", SERIES4[0]),
                 ("nc-c-base017", "draw 2 (fleet A)", SERIES4[1]),
                 ("sb1-base017", "draw 3 (fleet B)", SERIES4[2]),
                 ("sb4-base017", "draw 4 (fleet B)", SERIES4[3])],
        "control": ("nc-b-base017", "no-surge control"),
        "surge": (62.0, 72.0),
        "title": "Never-cancelled flash crowd\nbase 0.017 sps, cohort 132 (4/4 collapse)",
    },
    "cancel": {
        "arcs": [("ppc-b1a2-base", "draw 1 (180 min)", SERIES4[0]),
                 ("ppc-b1a2-rep-base", "draw 2 (180 min)", SERIES4[1]),
                 ("ppc-lh-noofl", "draw 3 (300 min)", SERIES4[2])],
        "control": None,
        "surge": (62.0, 107.0),
        "title": "Cancelled surge\nbase 0.022 sps, 0.25 sps x 45 min (3/3 relapse)",
    },
}

STACKS = {
    "nocancel": {
        "arcs": [("nc-a-base017", "vLLM / llm-d EPP", SERIES4[0]),
                 ("dyn-nc2-base017", "NVIDIA Dynamo (KV router)", SERIES4[1]),
                 ("sg-nc2-base017", "SGLang / llm-d EPP", SERIES4[2])],
        "control": ("nc-b-base017", "no-surge control (vLLM)"),
        "surge": (62.0, 72.0),
        "title": "Never-cancelled flash crowd\nbase 0.017 sps, cohort 132",
    },
    "cancel": {
        "arcs": [("ppc-lh-noofl", "vLLM / llm-d EPP", SERIES4[0]),
                 ("dyn-cx2-base022", "NVIDIA Dynamo (KV router)", SERIES4[1]),
                 ("sg-cx2-base022", "SGLang / llm-d EPP", SERIES4[2])],
        "control": None,
        "surge": (62.0, 107.0),
        "title": "Cancelled surge\nbase 0.022 sps, 0.25 sps x 45 min",
    },
}


def load(csv):
    d = pd.read_csv(ARCS / f"{csv}.csv")
    # The final window is partial: the job ends inside it and the
    # fleet drains, so it reads as a spurious recovery. Drop it.
    return d.iloc[:-1]


def draw(spec, fname, suptitle):
    OUT.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 2, figsize=(11.0, 8.2), dpi=150,
                             sharex="col", sharey="row")
    fig.patch.set_facecolor(PAGE)

    for col, key in enumerate(("nocancel", "cancel")):
        s = spec[key]
        axh, axk, axw = axes[0, col], axes[1, col], axes[2, col]
        if s["control"]:
            c = load(s["control"][0])
            for ax, y in ((axh, c.h), (axk, c.kv), (axw, c["wait"])):
                ax.plot(c.t_min, y, color=MUTED, lw=1.3, ls=(0, (4, 2)),
                        label=s["control"][1] if ax is axw else None)
        for csv, label, color in s["arcs"]:
            d = load(csv)
            axh.plot(d.t_min, d.h, color=color, lw=1.8)
            axk.plot(d.t_min, d.kv, color=color, lw=1.8)
            axw.plot(d.t_min, d["wait"], color=color, lw=1.8, label=label)

        axh.set_title(s["title"], fontsize=10, color=INK, loc="left")
        for ax in (axh, axk, axw):
            style_axes(ax)
            ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.axvspan(*s["surge"], color=wash(SURGE_RED, 0.10), zorder=0)
            ax.tick_params(labelsize=8, colors=INK2)
        axw.set_xlabel("minutes from base start", fontsize=9, color=INK2)
        axw.set_xlim(0, 302)
        axw.legend(fontsize=8, frameon=False, loc="upper center",
                   bbox_to_anchor=(0.5, -0.26), ncol=2, labelcolor=INK2)

    axes[0, 0].set_ylim(0, 1.03)
    axes[0, 0].set_ylabel("token hit rate", fontsize=9, color=INK2)
    axes[1, 0].set_ylim(0, 1.03)
    axes[1, 0].set_ylabel("fleet KV occupancy", fontsize=9, color=INK2)
    axes[2, 0].set_yscale("symlog", linthresh=10)
    axes[2, 0].set_ylim(-3, 1000)
    axes[2, 0].set_ylabel("waiting requests (symlog)", fontsize=9,
                          color=INK2)

    fig.suptitle(suptitle, fontsize=11.5, color=INK)
    fig.tight_layout(rect=(0, 0.02, 1, 0.965))
    fig.savefig(OUT / fname, facecolor=PAGE)
    print(f"wrote {OUT / fname}")


def main():
    draw(VLLM, "fig_collapse_relapse_vllm.png",
         "Collapse and relapse under a session-rate surge "
         "(8x TP4 no-offload, vLLM / llm-d; surge window shaded)")
    draw(STACKS, "fig_collapse_relapse_stacks.png",
         "The same two trajectories on three serving stacks "
         "(8x TP4 no-offload; surge window shaded)")


if __name__ == "__main__":
    main()
