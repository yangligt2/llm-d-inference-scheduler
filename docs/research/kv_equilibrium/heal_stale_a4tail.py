"""Helper: A4 baseline seeds 7-12 (checks the 2/6 cold draw in seeds
1-6 against the documented 2/12 ladder rate) plus A1 drain-back
trajectory comparison. Working file for the stale-churn screen."""

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from heal_variant_stale import run_one, RUNS

if __name__ == "__main__":
    jobs = [("A4", 8, 0.017, 0.25, 0.0, s, "baseline") for s in range(7, 13)]
    with ProcessPoolExecutor(max_workers=6) as ex:
        for r in ex.map(run_one, jobs):
            print({k: r[k] for k in ("arm", "seed", "outcome", "end_h",
                                     "end_wait")})
    for f in ("A1_baseline_s3", "A1_variant_s3", "A1_baseline_s1",
              "A1_variant_s1"):
        w = pd.read_csv(RUNS / f"{f}.csv")
        sel = w[w.t_min.isin([120, 160, 200, 240, 280, 300])]
        print(f, "ext_share",
              [round(x, 2) for x in sel.ext_share],
              "wait", [round(x, 1) for x in sel.wait])
