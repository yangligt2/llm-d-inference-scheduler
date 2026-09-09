"""Screen runner for the concurrent-restore variant (heal_variant_serial).

Matrix (300 min, seeds 1-6):
    A1  8x 0.022 s0.25  C_CPU_500      A5  4x 0.011 s0.125 C_CPU_500
    A2  8x 0.022 s0.25  C_CPU_250      A6 16x 0.040 s0.50  c_cpu=0
    A3  8x 0.022 s0.25  c_cpu=0        A7  8x 0.020 s0.25  c_cpu=0
    A4  8x 0.017 s0.25  c_cpu=0

Tier arms (A1, A2, A5) simulate the variant on all six seeds. On the
c_cpu=0 arms the restore path is unreachable, so the variant is the
unmodified RouterSessionSim; the runner VERIFIES bit-identity of the
shared window columns on 2 seeds per arm, then simulates A3/A4/A6
with the variant class (identical dynamics, kv gauge available;
out/heal_screen_progressive.csv carries no baseline rows for these
arms) and REUSES the stored deterministic A7 baseline rows and
windows. Reused A7 rows carry the stored end-of-run instantaneous
end_kv (the windowed kv gauge does not exist in the stored windows);
source column = reused_progressive_baseline.

Prints one line per completed run, writes out/heal_screen_serial.csv,
prints gate tallies, the congested-draw restore-rate pin ratios
(measured band 0.81-1.04 N*B_R, research-status result 4), and DONE.

Run from kv_equilibrium/ (stall-safe; ~1-2 min at 6 workers):
    ../.venv/bin/python -u heal_screen_serial_runner.py [workers]
"""

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from des_b1 import B_R, C_CPU_250, C_CPU_500
from heal_variant_serial import run_one, windows_identical

OUT = Path(__file__).parent / "out"
SEEDS = range(1, 7)

ARMS = {
    "A1": (8, 0.022, 0.25, C_CPU_500),
    "A2": (8, 0.022, 0.25, C_CPU_250),
    "A3": (8, 0.022, 0.25, 0.0),
    "A4": (8, 0.017, 0.25, 0.0),
    "A5": (4, 0.011, 0.125, C_CPU_500),
    "A6": (16, 0.040, 0.50, 0.0),
    "A7": (8, 0.020, 0.25, 0.0),
}
TIER_ARMS = ["A1", "A2", "A5"]
ZERO_SIM_ARMS = ["A3", "A4", "A6"]      # c_cpu=0, no stored baseline rows
ZERO_REUSE_ARMS = ["A7"]                # stored baseline rows reused
IDENT_SEEDS = (1, 2)

GATES = {
    "A1": ">=1 healed AND 0 cold",
    "A2": ">=3/6 cold AND 0 healed",
    "A3": ">=5/6 cold",
    "A4": "<=1/6 cold AND recovered draws end_wait < 15",
    "A5": ">=3/6 end_wait < 15",
    "A6": ">=5/6 cold",
    "A7": "2-5/6 cold",
}


def work(job):
    kind, arm, seed = job
    n, lb, ls, ccpu = ARMS[arm]
    if kind == "row":
        row, _ = run_one(arm, n, lb, ls, ccpu, seed, "variant")
        row["source"] = "sim"
        return job, row
    # kind == "ident": variant vs unmodified RouterSessionSim
    _, wv = run_one(arm, n, lb, ls, ccpu, seed, "variant", save=False)
    _, wb = run_one(arm, n, lb, ls, ccpu, seed, "baseline", save=False)
    return job, {"identical": windows_identical(wv, wb)}


def reused_rows():
    stored = pd.read_csv(OUT / "heal_screen_progressive.csv")
    rows = []
    for arm in ZERO_REUSE_ARMS:
        n = ARMS[arm][0]
        sel = stored[(stored.arm == arm) & (stored.model == "baseline")]
        for _, s in sel.iterrows():
            win = pd.read_csv(OUT / "heal_progressive_runs"
                              / f"{arm}_baseline_s{int(s.seed)}.csv")
            end = win[(win.t_min >= 270) & (win.t_min <= 295)]
            warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
            healed = (s.outcome == "recovered" and s.end_kv <= 0.5
                      and end.ext_share.mean() <= 0.2
                      and end["run"].mean() <= 2.0 * warm["run"].mean())
            rows.append({
                "arm": arm, "model": "variant", "seed": int(s.seed),
                "outcome": s.outcome, "healed": bool(healed),
                "end_h": s.end_h, "end_wait": s.end_wait,
                "end_kv": s.end_kv,   # stored end-of-run instantaneous
                "ext_share_270_295": round(float(end.ext_share.mean()), 4),
                "end_run": round(float(end["run"].mean()), 1),
                "warm_run": round(float(warm["run"].mean()), 1),
                "peak_restore_tok_s": 0.0, "tail_restore_tok_s": 0.0,
                "warm_h": s.warm_h, "warm_req_s": s.warm_req_s,
                "wall_s": 0.0, "source": "reused_progressive_baseline"})
            print(f"reused  {arm} s{int(s.seed)}: outcome={s.outcome} "
                  f"end_wait={s.end_wait}", flush=True)
    return rows


def main(workers):
    jobs = [("row", arm, seed)
            for arm in TIER_ARMS + ZERO_SIM_ARMS for seed in SEEDS]
    jobs += [("ident", arm, seed)
             for arm in ZERO_SIM_ARMS + ZERO_REUSE_ARMS
             for seed in IDENT_SEEDS]
    rows, ident_fail = [], []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for f in as_completed(futs):
            job, res = f.result()
            kind, arm, seed = job
            if kind == "row":
                rows.append(res)
                print(f"sim     {arm} s{seed}: outcome={res['outcome']} "
                      f"healed={res['healed']} end_wait={res['end_wait']} "
                      f"end_kv={res['end_kv']} "
                      f"tail_restore={res['tail_restore_tok_s']}",
                      flush=True)
            else:
                ok = res["identical"]
                if not ok:
                    ident_fail.append((arm, seed))
                print(f"ident   {arm} s{seed}: "
                      f"{'PASS' if ok else 'FAIL'}", flush=True)
    rows += reused_rows()
    df = pd.DataFrame(rows).sort_values(["arm", "seed"]).reset_index(
        drop=True)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "heal_screen_serial.csv", index=False)

    print("\nbit-identity (c_cpu=0, 2 seeds/arm):",
          "ALL PASS" if not ident_fail else f"FAIL {ident_fail}")
    print("\noutcome tally:")
    print(df.groupby("arm").outcome.value_counts().unstack(fill_value=0)
          .to_string())
    print("\ngate check:")
    for arm in ARMS:
        d = df[df.arm == arm]
        cold = (d.outcome == "cold").sum()
        healed = d.healed.sum()
        rec = d[d.outcome == "recovered"]
        w15 = (d.end_wait < 15).sum()
        ok = {"A1": healed >= 1 and cold == 0,
              "A2": cold >= 3 and healed == 0,
              "A3": cold >= 5,
              "A4": cold <= 1 and bool((rec.end_wait < 15).all()),
              "A5": w15 >= 3,
              "A6": cold >= 5,
              "A7": 2 <= cold <= 5}[arm]
        print(f"  {arm}: {'PASS' if ok else 'FAIL'}  "
              f"[cold={cold} congested={(d.outcome == 'congested').sum()} "
              f"recovered={(d.outcome == 'recovered').sum()} "
              f"healed={healed} wait<15={w15}]  gate: {GATES[arm]}")
    cong = df[(df.outcome == "congested") & (df.source == "sim")
              & df.arm.isin(TIER_ARMS)]
    if len(cong):
        print("\ncongested-draw restore pin (measured band 0.81-1.04"
              " N*B_R):")
        for _, r in cong.iterrows():
            nb = ARMS[r.arm][0] * B_R
            print(f"  {r.arm} s{int(r.seed)}: tail "
                  f"{r.tail_restore_tok_s:.0f} tok/s = "
                  f"{r.tail_restore_tok_s / nb:.2f} N*B_R; peak "
                  f"{r.peak_restore_tok_s:.0f} = "
                  f"{r.peak_restore_tok_s / nb:.2f} N*B_R")
    print("\nwrote out/heal_screen_serial.csv")
    print("DONE")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
