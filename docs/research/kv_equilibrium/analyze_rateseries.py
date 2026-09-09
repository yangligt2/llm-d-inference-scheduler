"""Windowed analysis of the rateseries10 staged open-loop run.

Rate schedule (config): 0-2700 qps1.0 | 2700-3300 qps2.0 | 3300-6000 qps1.0
| 6000-6900 qps0.1 | 6900-9600 qps1.0. Root rate only; subagents unmetered.

Server metrics: 8 pod endpoints (service endpoint 10.0.44.19 excluded).
Counters are cumulative; per-window rates come from first/last sample diffs.

Usage: .venv/bin/python kv_equilibrium/analyze_rateseries.py <run_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RUN = Path(sys.argv[1])
SERVICE_EP = "http://10.0.44.19/metrics"
WIN = 180  # seconds

COUNTERS = [
    "vllm:prompt_tokens",
    "vllm:prompt_tokens_cached",
    "vllm:generation_tokens",
    "vllm:num_preemptions",
]
GAUGES = [
    "vllm:kv_cache_usage_perc",
    "vllm:num_requests_waiting",
    "vllm:num_requests_running",
]

PHASES = [(0, 2700, "1.0 base"), (2700, 3300, "2.0 TIP"),
          (3300, 6000, "1.0 hyst"), (6000, 6900, "0.1 shed"),
          (6900, 9600, "1.0 rec")]


def main():
    df = pd.read_parquet(
        RUN / "server_metrics_export.parquet",
        columns=["endpoint_url", "metric_name", "timestamp_ns", "value"],
    )
    df = df[df.endpoint_url != SERVICE_EP]
    df = df[df.metric_name.isin(COUNTERS + GAUGES)].copy()
    t0 = df.timestamp_ns.min()
    df["t"] = (df.timestamp_ns - t0) / 1e9
    df["w"] = (df.t // WIN).astype(int)

    # counters: per-endpoint per-window last value -> fleet sum -> diff
    rows = {}
    for m in COUNTERS:
        sub = df[df.metric_name == m]
        last = sub.groupby(["endpoint_url", "w"]).value.last().unstack(0)
        last = last.ffill().sum(axis=1)
        rows[m] = last.diff()
    for m in GAUGES:
        sub = df[df.metric_name == m]
        per_ep = sub.groupby(["endpoint_url", "w"]).value.mean().unstack(0)
        rows[m] = per_ep.mean(axis=1) if m == "vllm:kv_cache_usage_perc" \
            else per_ep.sum(axis=1)

    out = pd.DataFrame(rows)
    out["t_min"] = out.index * WIN / 60
    out["h_tok"] = out["vllm:prompt_tokens_cached"] / out["vllm:prompt_tokens"]
    out["uncached_tok_s"] = (out["vllm:prompt_tokens"]
                             - out["vllm:prompt_tokens_cached"]) / WIN
    out["prompt_tok_s"] = out["vllm:prompt_tokens"] / WIN

    def phase_of(tmin):
        for lo, hi, name in PHASES:
            if lo <= tmin * 60 < hi:
                return name
        return "post"

    out["phase"] = out.t_min.map(phase_of)

    hdr = (f"{'t_min':>6} {'phase':<9} {'h_tok':>6} {'kv%':>5} {'wait':>6} "
           f"{'run':>5} {'preempt':>7} {'prompt/s':>9} {'uncach/s':>9}")
    print(hdr)
    prev_phase = None
    for w, r in out.iterrows():
        if w == out.index.min():
            continue
        if r.phase != prev_phase:
            print("-" * len(hdr))
            prev_phase = r.phase
        print(f"{r.t_min:6.0f} {r.phase:<9} "
              f"{r.h_tok:6.1%} {r['vllm:kv_cache_usage_perc']*100:5.1f} "
              f"{r['vllm:num_requests_waiting']:6.0f} "
              f"{r['vllm:num_requests_running']:5.0f} "
              f"{r['vllm:num_preemptions']:7.0f} "
              f"{r.prompt_tok_s:9.0f} {r.uncached_tok_s:9.0f}")


if __name__ == "__main__":
    main()
