"""Extract windowed fleet arcs from aiperf server parquets into CSVs.

One CSV per run under kv_equilibrium/out/arcs/. Columns:

    t_min        window start, minutes from first sample
    clock_utc    wall-clock window start (HH:MM)
    h            prompt_tokens_cached / prompt_tokens (fleet, window diff)
    ext_h        external_prefix_cache hits/queries (offload runs; NaN else)
    kv           kv_cache_usage_perc, fleet mean (running-residency share)
    wait, run    fleet sums of waiting / running gauges
    preempt      preemption count in window
    uncached_s   (prompt - cached) tokens/s
    gen_s        generation tokens/s
    write_s      uncached_s + gen_s (KV write rate)
    T_meas       free-pool retention window, s:
                 POOL_TOKENS * (1 - kv) / write_s
    req_s        client request starts/s (profiling, non-cancelled)
    ttft_p50/p95 client TTFT quantiles, s
    tpot_p50     client (request_latency - ttft)/(output_tokens - 1)
                 window median, s/token

Offload runs additionally carry (NaN elsewhere), from the
vllm:kv_offload_total_{bytes,time} counters split by the
transfer_type label (CPU_to_GPU = restore/onboard, GPU_to_CPU =
offload). total_bytes is bytes; total_time is cumulative transfer
busy time in SECONDS (validated: bytes/time gives ~151 GB/s, a
plausible C2C rate; ms would give an impossible 151 TB/s).
Token conversion uses the validated 127 KB/token fp8 KV constant.
external_prefix_cache_queries/hits are TOKEN counts (validated:
restore_s == window ext-hit token rate to <1% in the tier runs;
queries track prompt_tokens).

    restore_s    CPU->GPU restored tokens/s (fleet)
    restore_util mean per-pod restore-channel busy fraction
    restore_bw   achieved bytes/time while transferring, GB/s
    offload_s    GPU->CPU offloaded tokens/s (fleet)
    offload_util mean per-pod offload-channel busy fraction

Fleet aggregates use backend pod endpoints only; the per-namespace
service endpoints (added by aiperf discovery) are excluded.

Usage: .venv/bin/python kv_equilibrium/extract_arcs.py [WIN_SECONDS]
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

REPORTS = Path("/Users/yangligt/workplaces/llm-d/guides/subslicing/aiperf/reports")
OUT = Path(__file__).parent / "out" / "arcs"
WIN = int(sys.argv[1]) if len(sys.argv) > 1 else 300


def is_pod_endpoint(url: str) -> bool:
    # Backend pods serve metrics on :8000; per-namespace service
    # endpoints (added by aiperf discovery) are portless.
    return ":8000/" in url


# run name -> pool tokens fleet-wide (6486 blocks x 256 tok per TP4 replica)
POOL_4X = 4 * 6486 * 256
POOL_8X = 8 * 6486 * 256
POOL_16X = 16 * 6486 * 256
RUNS = {
    # closed-loop E-series
    "ppc-e0-smoke": POOL_8X, "ppc-e1-conc40": POOL_8X, "ppc-e1-conc60": POOL_8X,
    "ppc-e1-conc80": POOL_8X, "ppc-e1-conc100": POOL_8X,
    "ppc-e2-conc40-cap60": POOL_8X, "ppc-e2-conc40-cap300": POOL_8X,
    "ppc-e2-conc40-uncapped": POOL_8X, "ppc-e7-conc40-120min": POOL_8X,
    "ppc-rec-conc100": POOL_8X, "ppc-rec-conc40": POOL_8X,
    # B1 session-arrival arms (base runs carry the full fleet arc)
    "ppc-b1a-base": POOL_8X, "ppc-b1a2-base": POOL_8X,
    "ppc-b1a2-rep-base": POOL_8X, "ppc-b1b-base": POOL_8X,
    "ppc-b1b-rep-base": POOL_8X, "ppc-b1c-base": POOL_8X,
    # B2 offload arm (4x fleet)
    "cpuofl-b2a-base": POOL_4X,
    # 0.017 bimodality draws 2-3 (8x no-offload)
    "ppc-bimod2": POOL_8X, "ppc-bimod3": POOL_8X,
    # A1 tier arms and long-horizon pair (yangligt scaled to 8x 2026-08-10)
    "cpuofl-a1-tier022": POOL_8X, "cpuofl-a1rep": POOL_8X,
    "ppc-lh-noofl": POOL_8X, "cpuofl-lh-tier": POOL_8X,
    # 2026-08-12 window: 0.020 edge pair, 4x falsifier, A4 half (135-min
    # truncated), 16x invariance point (135-min truncated)
    "ppc-edge020-noofl": POOL_8X, "cpuofl-edge020-tier": POOL_8X,
    "cpuofl4x-falsifier": POOL_4X, "cpuofl-a4half": POOL_8X,
    "ppc-n16-inv040": POOL_16X,
    # 2026-08-13 window: 16x long-horizon, shard-a, tier size pair
    "ppc-n16-lh040": POOL_16X, "shard-a-020": POOL_8X,
    "cpuofl-a4half-lh": POOL_8X, "cpuofl-a4full-lh": POOL_8X,
    # 2026-08-15 window S1: 16x repeat + second shard draw
    "ppc-n16-lh040-r2": POOL_16X,
    "ppc-shard-a2-020": POOL_8X, "ppc-shard-b2-020": POOL_8X,
    # 2026-08-15 window S2: routing ablation (apx = baseline/approx
    # EPP config, lo = load-only) + precise draw
    "apx-n16-lh040": POOL_16X, "lo-shard-a-020": POOL_8X,
    "ppc-shard-b3-020": POOL_8X,
    # 2026-08-15 window S3: tier bracket + boundary draws
    "cpuofl-a4-375-lh": POOL_8X, "cpuofl-500-bimod5": POOL_8X,
    "ppc-edge020-r2": POOL_8X, "ppc-bimod4-017": POOL_8X,
    # 2026-08-15 window S4+
    "ppc-shard-a3-020": POOL_8X,
    "ppc-n16-edge034": POOL_16X, "cpuofl4x-falsifier-300m": POOL_4X,
    "ppc-shard-b4-020": POOL_8X,
    # 2026-08-15/16 window S5
    "ppc-n16-edge037": POOL_16X, "cpuofl-a4-375-r2": POOL_8X,
    # 2026-08-16 window S6
    "ppc-n16-edge037-r2": POOL_16X, "cpuofl-500-bimod6": POOL_8X,
    # 2026-08-27/28 window: no-cancel flash-crowd block (base 0.017,
    # surge sessions-cap cohorts; nc-e surge FAILED to launch so nc-e
    # is a second no-surge control), tier no-cancel pair + control,
    # B2a 300/240-min repeats (cancel protocol)
    "nc-a-base017": POOL_8X, "nc-b-base017": POOL_8X,
    "nc-c-base017": POOL_8X, "nc-d-base017": POOL_8X,
    "nc-e-base017": POOL_8X,
    "sb1-base017": POOL_8X, "sb2-base017": POOL_8X,
    "sb3-base017": POOL_8X, "sb4-base017": POOL_8X,
    "tb1r-base017": POOL_8X, "tb2r-ctrl017": POOL_8X,
    "ta1r-b2a-base011": POOL_4X, "ta2r-b2a-base011": POOL_4X,
}

KV_B_TOK = 127e3          # bytes/token, fp8 KV (validated vs pool byte size)
OFFLOAD_COUNTERS = ["vllm:kv_offload_total_bytes", "vllm:kv_offload_total_time"]

COUNTERS = ["vllm:prompt_tokens", "vllm:prompt_tokens_cached",
            "vllm:generation_tokens", "vllm:num_preemptions",
            "vllm:external_prefix_cache_queries",
            "vllm:external_prefix_cache_hits"]
GAUGES = ["vllm:kv_cache_usage_perc", "vllm:num_requests_waiting",
          "vllm:num_requests_running"]


def extract(run: str, pool: float) -> pd.DataFrame | None:
    dirs = [d for d in (REPORTS / run).glob("*/") if d.name != "lost+found"]
    if not dirs:
        print(f"  {run}: MISSING")
        return None
    sub = dirs[0]
    import pyarrow.parquet as pq
    schema_names = pq.ParquetFile(sub / "server_metrics_export.parquet").schema_arrow.names
    cols = ["endpoint_url", "metric_name", "timestamp_ns", "value"]
    has_xfer = "transfer_type" in schema_names
    if has_xfer:
        cols.append("transfer_type")
    df = pd.read_parquet(sub / "server_metrics_export.parquet", columns=cols)
    df = df[df.endpoint_url.map(is_pod_endpoint)
            & df.metric_name.isin(COUNTERS + GAUGES + OFFLOAD_COUNTERS)].copy()
    n_pods = df.endpoint_url.nunique()
    t0 = df.timestamp_ns.min()
    df["w"] = ((df.timestamp_ns - t0) / 1e9 // WIN).astype(int)

    def counter_diff(s):
        last = s.groupby(["endpoint_url", "w"]).value.last().unstack(0)
        return last.ffill().sum(axis=1).diff()

    rows = {}
    for m in COUNTERS:
        s = df[df.metric_name == m]
        if s.empty:
            continue
        rows[m] = counter_diff(s)
    for m in GAUGES:
        per = df[df.metric_name == m].groupby(["endpoint_url", "w"]).value.mean().unstack(0)
        rows[m] = per.mean(axis=1) if m == "vllm:kv_cache_usage_perc" else per.sum(axis=1)
    if has_xfer:
        for direction, tag in (("CPU_to_GPU", "restore"), ("GPU_to_CPU", "offload")):
            sb = df[(df.metric_name == "vllm:kv_offload_total_bytes")
                    & (df.transfer_type == direction)]
            st = df[(df.metric_name == "vllm:kv_offload_total_time")
                    & (df.transfer_type == direction)]
            if sb.empty:
                continue
            b, t = counter_diff(sb), counter_diff(st)
            rows[f"{tag}_s"] = b / KV_B_TOK / WIN
            rows[f"{tag}_util"] = t / WIN / n_pods
            if tag == "restore":
                rows["restore_bw"] = b / t.replace(0, float("nan")) / 1e9
    out = pd.DataFrame(rows)

    recs = []
    with open(sub / "profile_export.jsonl") as f:
        for line in f:
            d = json.loads(line)
            md, mt = d["metadata"], d["metrics"]
            if md.get("phase_kind") != "profiling" or md.get("was_cancelled"):
                continue
            if "time_to_first_token" not in mt:
                continue
            lat = mt.get("request_latency", {}).get("value", float("nan"))
            otok = mt.get("output_token_count", {}).get("value", 0)
            ttft = mt["time_to_first_token"]["value"]
            tpot = (lat - ttft) / (otok - 1) if otok and otok > 1 else float("nan")
            recs.append((md["request_start_ns"], ttft, tpot))
    cl = pd.DataFrame(recs, columns=["ts", "ttft", "tpot"])
    cl["w"] = ((cl.ts - t0) / 1e9 // WIN).astype(int)
    g = cl.groupby("w")
    out["req_s"] = g.size() / WIN
    out["ttft_p50"] = g.ttft.median() / 1000
    out["ttft_p95"] = g.ttft.quantile(.95) / 1000
    out["tpot_p50"] = g.tpot.median() / 1000

    out["t_min"] = out.index * WIN / 60.0
    out["clock_utc"] = [datetime.fromtimestamp(t0 / 1e9 + w * WIN, tz=timezone.utc)
                        .strftime("%H:%M") for w in out.index]
    out["h"] = out["vllm:prompt_tokens_cached"] / out["vllm:prompt_tokens"]
    if "vllm:external_prefix_cache_queries" in out:
        out["ext_h"] = (out["vllm:external_prefix_cache_hits"]
                        / out["vllm:external_prefix_cache_queries"])
    else:
        out["ext_h"] = float("nan")
    out["uncached_s"] = (out["vllm:prompt_tokens"] - out["vllm:prompt_tokens_cached"]) / WIN
    out["gen_s"] = out["vllm:generation_tokens"] / WIN
    out["write_s"] = out["uncached_s"] + out["gen_s"]
    out["kv"] = out["vllm:kv_cache_usage_perc"]
    out["T_meas"] = pool * (1.0 - out["kv"]) / out["write_s"]
    out = out.rename(columns={"vllm:num_requests_waiting": "wait",
                              "vllm:num_requests_running": "run",
                              "vllm:num_preemptions": "preempt"})
    cols = ["t_min", "clock_utc", "h", "ext_h", "kv", "wait", "run", "preempt",
            "uncached_s", "gen_s", "write_s", "T_meas", "req_s",
            "ttft_p50", "ttft_p95", "tpot_p50"]
    for c in ["restore_s", "restore_util", "restore_bw", "offload_s",
              "offload_util"]:
        if c not in out:
            out[c] = float("nan")
        cols.append(c)
    return out[cols].iloc[1:]  # first window has no counter diff


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for run, pool in RUNS.items():
        arc = extract(run, pool)
        if arc is None:
            continue
        arc.to_csv(OUT / f"{run}.csv", index=False, float_format="%.4f")
        steady = arc[arc.t_min >= 10]
        print(f"  {run}: {len(arc)} windows, h[10m+] {steady.h.min():.1%}-{steady.h.max():.1%}, "
              f"T_meas med {steady.T_meas.median():7.0f}s")


if __name__ == "__main__":
    main()
