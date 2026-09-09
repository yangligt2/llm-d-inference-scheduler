"""No-cancellation surge boundary sweep on the deployed-router DES.

Protocol: RouterSessionSim (N=8, lambda_s=0.022, untiered, 300 min
horizon) with cancel_surge disabled - surge arrivals stop at
T_ON + duration but already-arrived surge sessions persist and run to
natural completion (completion-coupled turn chaining). This is the
"real world" perturbation: a transient flash crowd whose members are
never evicted by the operator.

Sweep axes: surge session-arrival rate x injection duration. The
injected cohort size (rate x duration, sessions) is recorded per cell
because under no-cancellation the cohort itself sustains the overload
after arrivals stop; the two axes are expected to collapse onto the
cohort-size coordinate except where the injection is slow enough for
service to drain it concurrently.

Outcome classification is mitigation.classify on the 270-295 min
window (cold / congested / degraded / recovered).

Run from docs/research/:
  .venv/bin/python kv_equilibrium/nocancel_surge_sweep.py
Writes kv_equilibrium/out/nocancel_surge_sweep.csv.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import des_b1
from des_b1 import RouterSessionSim
from mitigation import end_metrics, classify

OUT = Path(__file__).parent / "out"

N = 8
BASE = 0.022                       # overridable via argv[3]
T_END = 300 * 60.0
T_ON = 62 * 60.0
SEEDS = (1, 2, 3)

NoCancelSim = type("RouterSessionSimNoCancel", (RouterSessionSim,),
                   {"cancel_surge": lambda self: None})

# (surge sps, injection duration s). Expected cohort = rate x duration.
# Rates as multiples of base 0.022: 3x, 5x, 10x, 25x, 50x, 100x.
CELLS = [
    (0.066, 900), (0.066, 1800), (0.066, 2700),
    (0.110, 300), (0.110, 900), (0.110, 1800), (0.110, 2700),
    (0.220, 300), (0.220, 900), (0.220, 1800),
    (0.550, 60), (0.550, 300), (0.550, 900),
    (1.100, 60), (1.100, 300),
    (2.200, 60),
]


def run_cell(lam_s, dur, seed, base=BASE, ccpu=0.0):
    t0 = time.perf_counter()
    des_b1.T_ON = T_ON
    des_b1.T_OFF = T_ON + dur
    sim = NoCancelSim(N, base, lam_s, ccpu, seed, t_end=T_END)
    sim.run()
    win = sim.windows()
    m = end_metrics(win)
    m["outcome"] = classify(m)
    t_off_min = (T_ON + dur) / 60.0
    post = win[win.t_min > t_off_min]
    rec = post[(post.h > 0.8) & (post.wait < 30)]
    surge_served = sum(1 for f in sim.rec_surge if f)
    m.update(
        base=base, c_cpu=ccpu, lam_surge=lam_s, dur_min=dur / 60.0,
        cohort=sim.n_sessions[1], seed=seed,
        peak_wait=win.wait.max(),
        t_rec_min=(rec.t_min.iloc[0] - t_off_min) if len(rec) else np.nan,
        served=len(sim.records),
        served_base=len(sim.records) - surge_served,
        served_surge=surge_served,
    )
    print(f"  {lam_s:5.3f} sps x {dur/60:4.0f} min seed {seed}: "
          f"{time.perf_counter()-t0:5.1f}s wall; cohort {m['cohort']:4d}; "
          f"warm h {m['warm_h']:.2f} end h {m['end_h']:.2f} "
          f"wait {m['end_wait']:6.0f} peak {m['peak_wait']:6.0f} "
          f"-> {m['outcome']}", flush=True)
    return m


def main():
    OUT.mkdir(exist_ok=True)
    seeds = SEEDS
    cells = CELLS
    base = BASE
    ccpu = 0.0
    if len(sys.argv) > 1:      # refine: "rate:dur,rate:dur seeds base c_cpu"
        cells = [tuple(float(x) for x in c.split(":"))
                 for c in sys.argv[1].split(",")]
        if len(sys.argv) > 2:
            seeds = tuple(range(1, int(sys.argv[2]) + 1))
        if len(sys.argv) > 3:
            base = float(sys.argv[3])
        if len(sys.argv) > 4:
            ccpu = float(sys.argv[4])
    rows = []
    for lam_s, dur in cells:
        print(f"cell base {base:.3f} c_cpu {ccpu:.0f} + {lam_s:.3f} sps x "
              f"{dur/60:.0f} min (expected cohort {lam_s*dur:.0f})",
              flush=True)
        for seed in seeds:
            rows.append(run_cell(lam_s, dur, seed, base, ccpu))
    df = pd.DataFrame(rows)
    path = OUT / "nocancel_surge_sweep.csv"
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False,
              float_format="%.4f")
    print("=== tally (outcome counts per cell) ===")
    for (lam_s, dur), cell in df.groupby(["lam_surge", "dur_min"]):
        tally = {o: int((cell.outcome == o).sum())
                 for o in ("cold", "congested", "degraded", "recovered")
                 if (cell.outcome == o).sum()}
        print(f"  {lam_s:5.3f} sps x {dur:4.0f} min "
              f"(cohort ~{cell.cohort.mean():.0f}): {tally}")
    print(f"appended {len(df)} rows to {path}")


if __name__ == "__main__":
    main()
