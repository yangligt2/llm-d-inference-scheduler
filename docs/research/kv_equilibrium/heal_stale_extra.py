"""Helper: baseline runs for the remaining guard arms (A2/A3/A4/A6),
merged into out/heal_screen_stale.csv. Working file for the stale-churn
screen; see heal_variant_stale.py."""

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from heal_variant_stale import run_one, ARMS, SEEDS

if __name__ == "__main__":
    extra = [(k, n, lb, ls, c, s, "baseline")
             for k, n, lb, ls, c in ARMS if k in {"A2", "A3", "A4", "A6"}
             for s in SEEDS]
    with ProcessPoolExecutor(max_workers=10) as ex:
        rows = list(ex.map(run_one, extra))
    df = pd.concat([pd.read_csv("out/heal_screen_stale.csv"),
                    pd.DataFrame(rows)])
    df = df.sort_values(["arm", "model", "seed"])
    df.to_csv("out/heal_screen_stale.csv", index=False)
    print(df.to_string(index=False))
