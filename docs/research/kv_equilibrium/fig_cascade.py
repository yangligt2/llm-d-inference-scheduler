"""Pinning-cascade figure (paper section 6.8, finding 3).

Per-pod dynamics through the post-cancel window (t 100-180 min) for
the 16x relapse (ppc-n16-lh040) vs the 8x clean shard draw
(shard-a-020), recomputed from the raw server_metrics_export parquets
with 300 s windows (same extraction as per_pod_spread.py):

  (a) count of pods with kv gauge (vllm:kv_cache_usage_perc window
      mean) > 0.85 vs time; the 16x cascade is 1 -> 3 -> 11 -> 14 ->
      16 of 16 across t = 110..130, the 8x draw stays at 0-3 pods.
  (b) per-pod h median with p25-p75 band; per-pod h_i is the windowed
      diff of vllm:prompt_tokens_cached / vllm:prompt_tokens.

Run from kv_equilibrium/:  ../.venv/bin/python fig_cascade.py
Writes out/paper/fig_cascade.png.
"""

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from extract_arcs import REPORTS, is_pod_endpoint
from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out" / "paper"
WIN = 300
KV_PIN = 0.85
T_LO, T_HI = 100, 180
T_ON, T_OFF = 62.0, 107.0  # surge window, minutes (des_b1.py)

RUNS = [  # run, N, label, fixed color per entity (8x blue / 16x orange,
    # matching fig_ladder_tally.py)
    ("ppc-n16-lh040", 16, "16x relapse (ppc-n16-lh040)", SERIES[1]),
    ("shard-a-020", 8, "8x clean (shard-a-020)", SERIES[0]),
]

METRICS = ["vllm:prompt_tokens", "vllm:prompt_tokens_cached",
           "vllm:kv_cache_usage_perc"]


def per_pod(run: str) -> pd.DataFrame:
    d = [p for p in (REPORTS / run).glob("*/") if p.name != "lost+found"][0]
    df = pd.read_parquet(d / "server_metrics_export.parquet",
                         columns=["endpoint_url", "metric_name",
                                  "timestamp_ns", "value"])
    df = df[df.endpoint_url.map(is_pod_endpoint)
            & df.metric_name.isin(METRICS)].copy()
    t0 = df.timestamp_ns.min()
    df["w"] = ((df.timestamp_ns - t0) / 1e9 // WIN).astype(int)

    def pod_diff(metric):
        last = (df[df.metric_name == metric]
                .groupby(["endpoint_url", "w"]).value.last().unstack(0))
        return last.ffill().diff()

    prompt = pod_diff("vllm:prompt_tokens")
    cached = pod_diff("vllm:prompt_tokens_cached")
    kv = (df[df.metric_name == "vllm:kv_cache_usage_perc"]
          .groupby(["endpoint_url", "w"]).value.mean().unstack(0))
    h = cached / prompt
    out = pd.DataFrame({
        "t_min": prompt.index * WIN / 60.0,
        "n_pinned": (kv > KV_PIN).sum(axis=1).reindex(prompt.index),
        "h_med": h.median(axis=1),
        "h_p25": h.quantile(0.25, axis=1),
        "h_p75": h.quantile(0.75, axis=1),
    }).iloc[1:]  # first window has no counter diff
    return out[(out.t_min >= T_LO) & (out.t_min <= T_HI)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig, (ax_n, ax_h) = plt.subplots(2, 1, figsize=(6.6, 6.4), dpi=150,
                                     sharex=True)
    fig.patch.set_facecolor(PAGE)
    for run, n, label, color in RUNS:
        w = per_pod(run)
        ax_n.plot(w.t_min, w.n_pinned, color=color, lw=1.8,
                  drawstyle="steps-mid", label=label)
        ax_n.axhline(n, color=MUTED, lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax_h.fill_between(w.t_min, w.h_p25, w.h_p75,
                          color=wash(color, 0.30), lw=0)
        ax_h.plot(w.t_min, w.h_med, color=color, lw=1.8, label=label)
        print(f"  {run}: pinned counts "
              f"{dict(zip(w.t_min.astype(int), w.n_pinned.astype(int)))}")
    ax_n.text(T_HI - 1, 16.4, "16 of 16", color=MUTED, fontsize=8, ha="right")
    ax_n.text(T_HI - 1, 8.4, "8 of 8", color=MUTED, fontsize=8, ha="right")
    ax_n.set_ylabel(f"pods with kv > {KV_PIN}", fontsize=9)
    ax_n.set_ylim(-0.6, 17.5)
    ax_n.set_title("(a) pinned-pod count: staggered 16x cascade vs "
                   "0-3 transient at 8x", fontsize=9.5, loc="left")
    ax_h.set_ylabel("per-pod token hit rate", fontsize=9)
    ax_h.set_ylim(0, 1.03)
    ax_h.set_xlabel("minutes", fontsize=9)
    ax_h.set_title("(b) per-pod h median, p25-p75 band", fontsize=9.5,
                   loc="left")
    for ax in (ax_n, ax_h):
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.set_xlim(T_LO, T_HI)
        ax.axvspan(T_ON, T_OFF, color=wash("#d03b3b", 0.10), zorder=0)
    ax_h.legend(fontsize=8, frameon=False, loc="center right",
                labelcolor=INK2)
    fig.suptitle("Post-cancel pinning cascade: 16x relapse vs 8x clean "
                 "recovery (300 s windows)", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig_cascade.png", facecolor=PAGE)
    print(f"wrote {OUT / 'fig_cascade.png'}")


if __name__ == "__main__":
    main()
