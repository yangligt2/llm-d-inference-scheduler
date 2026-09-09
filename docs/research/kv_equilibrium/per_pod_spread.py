"""Per-pod hit-rate and query-share spread across fleet sizes.

Open question 1 (research-status.md): does the N-dependent fragility
come from affinity degradation (per-pod h falls with N, load stays
balanced) or load imbalance (query share concentrates, hot pods pin
first)? Both leave distinct per-endpoint signatures in the collected
parquets.

Per (run, window, pod), from windowed counter diffs:

    h_i      prompt_tokens_cached / prompt_tokens
    s_i      pod share of fleet prompt_tokens (query share)
    kv_i     kv_cache_usage_perc window mean

Per (run, window) spread metrics:

    h_fleet      fleet h (token-weighted)
    h_mean/std   unweighted across pods
    h_minmax     max_i h_i - min_i h_i
    share_cv     std(s_i) / mean(s_i) = N * std(s_i); 0 = perfectly
                 balanced, N-comparable
    share_maxr   max_i s_i / mean share (= N * max s_i)
    kv_std       std(kv_i)
    corr_sh      Pearson corr(s_i, h_i) across pods (negative =
                 hot pods run colder)

Outputs: out/perpod/<run>.csv (per-window metrics) and
out/perpod/spread_summary.csv (per run x phase medians). Phases are
anchored on the standard protocol (surge at base t ~ +62..64 min,
2700 s): warm [10,60), surge [65,105), recovery [110,180),
late [180,300).

Usage: .venv/bin/python kv_equilibrium/per_pod_spread.py [WIN_SECONDS]
"""

import sys
from pathlib import Path

import pandas as pd

from extract_arcs import REPORTS, is_pod_endpoint

OUT = Path(__file__).parent / "out" / "perpod"
WIN = int(sys.argv[1]) if len(sys.argv) > 1 else 300

# run -> (N, class label) for the N-comparison and supporting sets
RUNS = {
    # 4x tier (per-capacity-matched 0.011)
    "cpuofl-b2a-base": (4, "4x-tier-0.011"),
    "cpuofl4x-falsifier": (4, "4x-tier-0.011"),
    # 8x no-offload
    "ppc-b1c-base": (8, "8x-noofl-0.017"),
    "ppc-edge020-noofl": (8, "8x-noofl-0.020"),
    "shard-a-020": (8, "8x-shard-0.020"),
    "ppc-lh-noofl": (8, "8x-noofl-0.022"),
    "ppc-b1a2-base": (8, "8x-noofl-0.022"),
    "ppc-b1a2-rep-base": (8, "8x-noofl-0.022"),
    # 8x tier
    "cpuofl-edge020-tier": (8, "8x-tier-0.020"),
    "cpuofl-a1-tier022": (8, "8x-tier-0.022"),
    "cpuofl-lh-tier": (8, "8x-tier-0.022"),
    "cpuofl-a4half-lh": (8, "8x-tier250-0.022"),
    "cpuofl-a4full-lh": (8, "8x-tier500-0.022"),
    # 16x no-offload (per-capacity-matched 0.040)
    "ppc-n16-inv040": (16, "16x-noofl-0.040"),
    "ppc-n16-lh040": (16, "16x-noofl-0.040"),
}

PHASES = [("warm", 10, 60), ("surge", 65, 105),
          ("recovery", 110, 180), ("late", 180, 300)]

COUNTERS = ["vllm:prompt_tokens", "vllm:prompt_tokens_cached"]
GAUGE_KV = "vllm:kv_cache_usage_perc"


def per_pod_windows(run: str) -> pd.DataFrame | None:
    dirs = [d for d in (REPORTS / run).glob("*/") if d.name != "lost+found"]
    if not dirs:
        print(f"  {run}: MISSING")
        return None
    df = pd.read_parquet(dirs[0] / "server_metrics_export.parquet",
                         columns=["endpoint_url", "metric_name",
                                  "timestamp_ns", "value"])
    df = df[df.endpoint_url.map(is_pod_endpoint)
            & df.metric_name.isin(COUNTERS + [GAUGE_KV])].copy()
    t0 = df.timestamp_ns.min()
    df["w"] = ((df.timestamp_ns - t0) / 1e9 // WIN).astype(int)

    def pod_diff(metric):
        last = (df[df.metric_name == metric]
                .groupby(["endpoint_url", "w"]).value.last().unstack(0))
        return last.ffill().diff()

    prompt = pod_diff("vllm:prompt_tokens")
    cached = pod_diff("vllm:prompt_tokens_cached")
    kv = (df[df.metric_name == GAUGE_KV]
          .groupby(["endpoint_url", "w"]).value.mean().unstack(0))

    n = prompt.shape[1]
    h_i = cached / prompt              # NaN where a pod saw no queries
    tot = prompt.sum(axis=1)
    s_i = prompt.div(tot, axis=0)

    out = pd.DataFrame({
        "t_min": prompt.index * WIN / 60.0,
        "n_pods": n,
        "h_fleet": cached.sum(axis=1) / tot,
        "h_mean": h_i.mean(axis=1),
        "h_std": h_i.std(axis=1),
        "h_minmax": h_i.max(axis=1) - h_i.min(axis=1),
        "share_cv": s_i.std(axis=1) * n,
        "share_maxr": s_i.max(axis=1) * n,
        "kv_mean": kv.mean(axis=1),
        "kv_std": kv.std(axis=1),
        "corr_sh": pd.concat([s_i, h_i], axis=1, keys=["s", "h"])
                     .apply(lambda r: r["s"].corr(r["h"]), axis=1),
    })
    return out.iloc[1:]  # first window has no counter diff


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for run, (n, label) in RUNS.items():
        w = per_pod_windows(run)
        if w is None:
            continue
        w.to_csv(OUT / f"{run}.csv", index=False, float_format="%.4f")
        for phase, lo, hi in PHASES:
            p = w[(w.t_min >= lo) & (w.t_min < hi)]
            if p.empty:
                continue
            summary.append({
                "run": run, "N": n, "label": label, "phase": phase,
                "windows": len(p),
                **{c: p[c].median() for c in
                   ["h_fleet", "h_mean", "h_std", "h_minmax",
                    "share_cv", "share_maxr", "kv_mean", "kv_std",
                    "corr_sh"]},
            })
        print(f"  {run}: {len(w)} windows")
    s = pd.DataFrame(summary)
    s.to_csv(OUT / "spread_summary.csv", index=False, float_format="%.4f")
    for phase, _, _ in PHASES:
        p = s[s.phase == phase].sort_values(["N", "label", "run"])
        print(f"\n== {phase} ==")
        print(p[["run", "N", "label", "h_fleet", "h_std", "h_minmax",
                 "share_cv", "share_maxr", "kv_std", "corr_sh"]]
              .to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
