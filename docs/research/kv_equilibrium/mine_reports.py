"""Mine existing inference-perf reports into one table for model validation.

Walks REPORTS_ROOT, parses each run's config.yaml + summary_lifecycle_metrics
.json, and emits a CSV plus a readable table. Derived columns:

  inflight   rps * mean request latency (Little's law) - the ACHIEVED
             concurrency; compare with the configured target to detect the
             pre-2026-07-17 load-generator bottleneck (true concurrency
             capped around 40-80 regardless of target).
  valid      run date >= 2026-07-17 (generator fix). Earlier runs are kept
             but flagged; their in-flight column shows whether the cap bit.

Usage: .venv/bin/python kv_equilibrium/mine_reports.py [out.csv]
"""

import csv
import json
import re
import sys
from pathlib import Path

import yaml

REPORTS_ROOT = Path("/Users/yangligt/workplaces/llm-d/guides/subslicing/inf-perf/reports")
FIX_DATE = "20260717"


def pick(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def parse_run(run_dir: Path):
    summ_p = run_dir / "summary_lifecycle_metrics.json"
    conf_p = run_dir / "config.yaml"
    if not summ_p.exists() or not conf_p.exists():
        return None
    try:
        summ = json.loads(summ_p.read_text())
        conf = yaml.safe_load(conf_p.read_text())
    except Exception as e:
        return {"report": run_dir.parent.name, "run": run_dir.name, "error": str(e)}

    m = re.search(r"(20\d{6})-(\d{6})", run_dir.name)
    date = m.group(1) if m else ""

    stages = pick(conf, "load", "stages", default=[]) or []
    st = stages[0] if stages else {}
    load_type = pick(conf, "load", "type")
    data_type = pick(conf, "data", "type")

    s = summ.get("successes", {})
    lat = s.get("latency", {})
    thr = s.get("throughput", {})
    sched = pick(summ, "load_summary", "schedule_delay", default={}) or {}

    rps = pick(thr, "requests_per_sec")
    lat_mean = pick(lat, "request_latency", "mean")
    row = {
        "report": run_dir.parent.name,
        "run": run_dir.name,
        "date": date,
        "valid_gen": bool(date and date >= FIX_DATE),
        "load_type": load_type,
        "data_type": data_type,
        "conc_target": st.get("concurrent_sessions") or st.get("concurrency_level"),
        "num_sessions": st.get("num_sessions") or st.get("num_requests"),
        "duration_s": summ.get("benchmark_time_seconds"),
        "requests": s.get("count"),
        "rps": rps,
        "in_tok_s": pick(thr, "input_tokens_per_sec"),
        "out_tok_s": pick(thr, "output_tokens_per_sec"),
        "prompt_mean": pick(s, "prompt_tokens", "mean"),
        "prompt_p95": pick(s, "prompt_tokens", "p95"),
        "cached_total": pick(s, "prompt_tokens", "cached"),
        "output_mean": pick(s, "output_tokens", "mean"),
        "ttft_mean": pick(lat, "time_to_first_token", "mean"),
        "ttft_p50": pick(lat, "time_to_first_token", "median"),
        "ttft_p95": pick(lat, "time_to_first_token", "p95"),
        "ttft_p99": pick(lat, "time_to_first_token", "p99"),
        "tpot_p50": pick(lat, "time_per_output_token", "median"),
        "tpot_p95": pick(lat, "time_per_output_token", "p95"),
        "req_lat_mean": lat_mean,
        "sched_delay_mean": sched.get("mean"),
        "sched_delay_p95": sched.get("p95"),
        "inflight": (rps * lat_mean) if (rps and lat_mean) else None,
    }
    return row


def main():
    rows = []
    for report_dir in sorted(REPORTS_ROOT.iterdir()):
        if not report_dir.is_dir():
            continue
        for run_dir in sorted(report_dir.iterdir()):
            if run_dir.is_dir():
                row = parse_run(run_dir)
                if row:
                    rows.append(row)

    out = sys.argv[1] if len(sys.argv) > 1 else "kv_equilibrium/out/reports_mined.csv"
    cols = list(rows[0].keys()) if rows else []
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} runs -> {out}\n")

    def fnum(v, fmt):
        return format(v, fmt) if isinstance(v, (int, float)) else "-"

    hdr = (f"{'report':<42} {'date':>8} {'ok':>2} {'tgt':>4} {'infl':>5} "
           f"{'rps':>5} {'in_tok/s':>9} {'prompt':>7} {'ttft50':>7} "
           f"{'ttft95':>7} {'tpot50':>7} {'sched95':>8}")
    print(hdr)
    for r in rows:
        if "error" in r:
            print(f"{r['report']:<42} ERROR {r['error'][:60]}")
            continue
        print(f"{r['report']:<42} {r['date']:>8} "
              f"{'y' if r['valid_gen'] else 'N':>2} "
              f"{str(r['conc_target'] or '-'):>4} {fnum(r['inflight'], '5.0f'):>5} "
              f"{fnum(r['rps'], '5.2f'):>5} {fnum(r['in_tok_s'], '9.0f'):>9} "
              f"{fnum(r['prompt_mean'], '7.0f'):>7} {fnum(r['ttft_p50'], '7.2f'):>7} "
              f"{fnum(r['ttft_p95'], '7.1f'):>7} {fnum(r['tpot_p50'], '7.3f'):>7} "
              f"{fnum(r['sched_delay_p95'], '8.0f'):>8}")


if __name__ == "__main__":
    main()
