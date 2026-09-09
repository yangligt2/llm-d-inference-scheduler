#!/usr/bin/env python3
"""Windowed arc analysis for the cross-stack (Dynamo / SGLang) collapse runs.

Usage: analyze_crossstack.py <run_dir> <dynamo|sglang> [window_s]

<run_dir> is a bench.sh report directory containing one
qwen3coder-*/ artifacts folder (profile_export.jsonl +
server_metrics_export.parquet). Prints a per-window table and a
verdict summary matching the lab-notebook conventions:
h from cached/prompt token counter diffs, KV occupancy mean across
pods, waiting/running sums, client completed req/s and TTFT p50.
"""
import glob
import json
import sys

import numpy as np
import pandas as pd

STACKS = {
    "dynamo": dict(
        ep=":9090",
        prompt="vllm:prompt_tokens",
        cached="vllm:prompt_tokens_cached",
        kv="vllm:kv_cache_usage_perc",
        wait="vllm:num_requests_waiting",
        run="vllm:num_requests_running",
    ),
    "sglang": dict(
        ep=":8000",
        prompt="sglang:prompt_tokens",
        cached="sglang:cached_tokens",
        kv="sglang:token_usage",
        wait="sglang:num_queue_reqs",
        run="sglang:num_running_reqs",
    ),
}


def main():
    run_dir, stack = sys.argv[1], sys.argv[2]
    args = [a for a in sys.argv[3:] if not a.startswith("--")]
    win = int(args[0]) if args else 300
    cfg = STACKS[stack]

    art = glob.glob(f"{run_dir}/qwen3coder-*")
    if not art:
        sys.exit(f"no artifacts dir under {run_dir}")
    art = art[0]

    df = pd.read_parquet(f"{art}/server_metrics_export.parquet")
    df = df[df.endpoint_url.str.contains(cfg["ep"], regex=False)].copy()
    t0 = df.timestamp_ns.min()
    df["win"] = ((df.timestamp_ns - t0) / 1e9 // win).astype(int)

    def last_per_window(name, agg):
        g = df[df.metric_name == name]
        s = (g.sort_values("timestamp_ns")
              .groupby(["win", "endpoint_url"])["value"].last()
              .groupby("win").agg(agg))
        return s

    prompt = last_per_window(cfg["prompt"], "sum").diff()
    cached = last_per_window(cfg["cached"], "sum").diff()
    h = (cached / prompt).rename("h")
    kv = last_per_window(cfg["kv"], "mean").rename("kv")
    wait = last_per_window(cfg["wait"], "sum").rename("wait")
    run = last_per_window(cfg["run"], "sum").rename("run")

    # Client side: completed requests and TTFT per completion window.
    ends, ttfts = [], []
    with open(f"{art}/profile_export.jsonl") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = r.get("metadata", {})
            if m.get("was_cancelled"):
                continue
            end = m.get("request_end_ns")
            if end is None:
                continue
            ends.append(end)
            t = r.get("metrics", {}).get("time_to_first_token", {})
            ttfts.append(t.get("value", np.nan))
    cl = pd.DataFrame({"end": ends, "ttft": ttfts})
    cl["win"] = ((cl.end - t0) / 1e9 // win).astype(int)
    cl = cl[cl.win >= 0]
    reqs = (cl.groupby("win").size() / win).rename("req_s")
    ttft = (cl.groupby("win")["ttft"].median() / 1000).rename("ttft_p50_s")

    tab = pd.concat([h, kv, wait, run, reqs, ttft], axis=1).sort_index()
    tab.index = (tab.index * win / 60).astype(int)
    tab.index.name = "min"

    # Optional arc export in the out/arcs column convention (subset),
    # so cross-stack runs plot alongside the vLLM reference arcs.
    if "--csv" in sys.argv:
        out = pd.DataFrame({
            "t_min": tab.index.astype(float),
            "h": tab.h, "kv": tab.kv, "wait": tab["wait"], "run": tab.run,
            "req_s": tab.req_s, "ttft_p50": tab.ttft_p50_s,
        })
        name = run_dir.rstrip("/").split("/")[-1]
        dest = f"{__import__('os').path.dirname(__file__) or '.'}/out/arcs/{name}.csv"
        out.to_csv(dest, index=False, float_format="%.4f")
        print(f"wrote {dest}")
    pd.set_option("display.float_format", lambda v: f"{v:0.3f}")
    print(tab.to_string())

    # Verdict summary (lab-notebook conventions).
    mins = tab.index.to_numpy()
    warm = tab[(mins >= 10) & (mins <= 60)]
    peak_win = tab[(mins >= 62) & (mins <= 115)]
    tail = tab[mins >= mins.max() - 25]
    print("\n--- summary")
    print(f"warm req/s (min 10-60 mean):  {warm.req_s.mean():0.2f}")
    print(f"warm h (min 10-60 mean):      {warm.h.mean():0.3f}")
    print(f"kv peak (min 62-115):         {peak_win.kv.max():0.3f}")
    print(f"end h / kv (last 25 min):     {tail.h.mean():0.3f} / {tail.kv.mean():0.3f}")
    print(f"end wait (last 25 min mean):  {tail['wait'].mean():0.0f}  peak: {tab['wait'].max():0.0f}")
    print(f"end ttft p50 (last 25 min):   {tail.ttft_p50_s.mean():0.1f} s")
    print(f"end req/s (last 25 min):      {tail.req_s.mean():0.2f}")


if __name__ == "__main__":
    main()
