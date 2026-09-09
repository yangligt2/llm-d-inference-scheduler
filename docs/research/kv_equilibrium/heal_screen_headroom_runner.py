"""Screen runner for the occupancy-gated eviction variant
(heal_variant_headroom).

Matrix (300 min, seeds 1-6):
    A1  8x 0.022 s0.25  C_CPU_500      A5  4x 0.011 s0.125 C_CPU_500
    A2  8x 0.022 s0.25  C_CPU_250      A6 16x 0.040 s0.50  c_cpu=0
    A3  8x 0.022 s0.25  c_cpu=0        A7  8x 0.020 s0.25  c_cpu=0
    A4  8x 0.017 s0.25  c_cpu=0

The occupancy-gated eviction clock changes HBM residency on the
c_cpu=0 arms too, so ALL arms simulate the variant on all six seeds
(no bit-identity shortcut, no baseline-row reuse).

Prints one line per completed run, writes out/heal_screen_headroom.csv
(per-run outcome, healed flag, end_h, end_wait, end_kv, ext_share
tail, end/warm running, resident gauge, restore rates), prints gate
tallies and the congested-draw restore-rate pin ratios (measured band
0.81-1.04 N*B_R, research-status result 4), then DONE.

Run from kv_equilibrium/:
    ../.venv/bin/python -u heal_screen_headroom_runner.py [workers]
"""

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from des_b1 import B_R, C_CPU_250, C_CPU_500
from heal_variant_headroom import run_one

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
    arm, seed = job
    n, lb, ls, ccpu = ARMS[arm]
    row, _ = run_one(arm, n, lb, ls, ccpu, seed, "variant")
    return job, row


def main(workers):
    jobs = [(arm, seed) for arm in ARMS for seed in SEEDS]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for f in as_completed(futs):
            (arm, seed), row = f.result()
            rows.append(row)
            print(f"sim {arm} s{seed}: outcome={row['outcome']} "
                  f"healed={row['healed']} end_wait={row['end_wait']} "
                  f"end_kv={row['end_kv']} ext={row['ext_share_270_295']} "
                  f"end_run={row['end_run']} "
                  f"tail_restore={row['tail_restore_tok_s']}", flush=True)
    df = pd.DataFrame(rows).sort_values(["arm", "seed"]).reset_index(
        drop=True)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "heal_screen_headroom.csv", index=False)

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
    cong = df[(df.outcome == "congested") & df.arm.isin(TIER_ARMS)]
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
    print("\nwrote out/heal_screen_headroom.csv")
    print("DONE")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
