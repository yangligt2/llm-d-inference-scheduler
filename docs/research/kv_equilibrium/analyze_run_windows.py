"""Windowed fleet analysis, wall-clock anchored. Usage: analyze_runs.py <run_dir> [WIN]"""
import sys, json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

RUN = Path(sys.argv[1])
WIN = int(sys.argv[2]) if len(sys.argv) > 2 else 180
SERVICE_EP = "http://10.0.44.19/metrics"
COUNTERS = ["vllm:prompt_tokens", "vllm:prompt_tokens_cached",
            "vllm:generation_tokens", "vllm:num_preemptions"]
GAUGES = ["vllm:kv_cache_usage_perc", "vllm:num_requests_waiting",
          "vllm:num_requests_running"]

df = pd.read_parquet(RUN / "server_metrics_export.parquet",
                     columns=["endpoint_url", "metric_name", "timestamp_ns", "value"])
df = df[(df.endpoint_url != SERVICE_EP) & df.metric_name.isin(COUNTERS + GAUGES)].copy()
t0 = df.timestamp_ns.min()
df["w"] = ((df.timestamp_ns - t0) / 1e9 // WIN).astype(int)

rows = {}
for m in COUNTERS:
    last = df[df.metric_name == m].groupby(["endpoint_url", "w"]).value.last().unstack(0)
    rows[m] = last.ffill().sum(axis=1).diff()
for m in GAUGES:
    per_ep = df[df.metric_name == m].groupby(["endpoint_url", "w"]).value.mean().unstack(0)
    rows[m] = per_ep.mean(axis=1) if m == "vllm:kv_cache_usage_perc" else per_ep.sum(axis=1)
out = pd.DataFrame(rows)

# client-side TTFT + request rate per window from jsonl
recs = []
with open(RUN / "profile_export.jsonl") as f:
    for line in f:
        d = json.loads(line)
        md, mt = d["metadata"], d["metrics"]
        if md.get("phase_kind") != "profiling" or md.get("was_cancelled"):
            continue
        recs.append((md["request_start_ns"], mt.get("time_to_first_token", {}).get("value"),
                     md.get("turn_index", -1), md.get("agent_depth", 0)))
cl = pd.DataFrame(recs, columns=["ts", "ttft", "turn", "depth"])
cl["w"] = ((cl.ts - t0) / 1e9 // WIN).astype(int)
g = cl.groupby("w")
out["ttft_p50"] = g.ttft.median() / 1000
out["ttft_p95"] = g.ttft.quantile(.95) / 1000
out["req_s"] = g.size() / WIN
out["first_turn_pct"] = g.apply(lambda x: ((x.turn == 0) & (x.depth == 0)).mean() * 100)

out["h_tok"] = out["vllm:prompt_tokens_cached"] / out["vllm:prompt_tokens"]
out["uncached_s"] = (out["vllm:prompt_tokens"] - out["vllm:prompt_tokens_cached"]) / WIN
print(f"t0 = {datetime.fromtimestamp(t0/1e9, tz=timezone.utc):%H:%M:%S} UTC, window {WIN}s")
hdr = (f"{'clock':>8} {'t_min':>5} {'h_tok':>6} {'kv%':>5} {'wait':>5} {'run':>4} "
       f"{'preem':>5} {'uncach/s':>8} {'req/s':>5} {'t1%':>4} {'ttft50':>7} {'ttft95':>7}")
print(hdr)
for w, r in out.iterrows():
    if w == out.index.min():
        continue
    clock = datetime.fromtimestamp((t0/1e9 + w*WIN), tz=timezone.utc).strftime("%H:%M")
    def f(v, fmt): return fmt % v if pd.notna(v) else "  -"
    print(f"{clock:>8} {w*WIN/60:5.0f} {f(r.h_tok*100,'%6.1f')} {f(r['vllm:kv_cache_usage_perc']*100,'%5.1f')} "
          f"{f(r['vllm:num_requests_waiting'],'%5.0f')} {f(r['vllm:num_requests_running'],'%4.0f')} "
          f"{f(r['vllm:num_preemptions'],'%5.0f')} {f(r.uncached_s,'%8.0f')} "
          f"{f(r.req_s,'%5.2f')} {f(r.first_turn_pct,'%4.0f')} {f(r.ttft_p50,'%7.2f')} {f(r.ttft_p95,'%7.2f')}")
