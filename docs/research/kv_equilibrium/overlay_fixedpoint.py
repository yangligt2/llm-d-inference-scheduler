"""Fluid fixed-point overlay against the GB200 measured cells (2026-08-08/09).

Parameterizes fluid_model.System for the 8xTP4 GB200 fleet, injects
gap CDFs truncated at the run's traceIdleGapCapSeconds (10.5 s for every
overlaid run), sweeps the open-loop band, and prints model-vs-measured
for the steady cells from out/arcs/*.csv.

Measured provenance of the constants:
  POOL   6486 blocks x 256 tok x 8 pods (vllm log / kv_cache_memory)
  P_TPT  saturated fleet uncached throughput 131-138k tok/s during
         collapse plateaus (b1a2/b1b/rep arcs) -> 17k tok/s/replica
  TPOT   12.9-21.5 ms p50 measured at light-warm cells -> 0.015 s mid
  Gap cap 10.5 s in every overlaid run's dataset config.

Run: .venv/bin/python kv_equilibrium/overlay_fixedpoint.py
"""

import math
from pathlib import Path

import pandas as pd

import fluid_model as fm
from fluid_model import System, solve

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

GAP_CAP = 10.5
N_REPLICAS = 8
C_HBM = 6486 * 256.0          # per-replica pool, tokens
P_TPT = 17_000.0              # per-replica prefill tokens/s (saturated measured)
TPOT = 0.015
D_TPT = 2_000.0               # decode cap per replica; never binding here

# --- capped gap CDFs: gap' = min(gap, cap) --------------------------------
_orig_main, _orig_sub = fm.gap_cdf_main, fm.gap_cdf_sub


def _capped(cdf, cap):
    def f(t: float) -> float:
        if t <= 0:
            return 0.0
        return 1.0 if t >= cap else cdf(t)
    return f


def set_gap_cap(cap: float | None):
    """Monkeypatch fluid_model's module-level gap CDFs (solve() reads them
    at call time). None restores the uncapped corpus CDFs."""
    if cap is None:
        fm.gap_cdf_main, fm.gap_cdf_sub = _orig_main, _orig_sub
    else:
        fm.gap_cdf_main = _capped(_orig_main, cap)
        fm.gap_cdf_sub = _capped(_orig_sub, cap)


def gb200(rps: float) -> System:
    return System(n_nodes=N_REPLICAS, c_hbm=C_HBM, c_cpu=0.0, p_tpt=P_TPT,
                  d_tpt=D_TPT, tpot=TPOT, open_loop_rps=rps)


# --- measured steady cells: (arc csv, window minutes, label) ---------------
CELLS = [
    ("ppc-e1-conc40",        (10, 60),  "E1 conc40 warm"),
    ("ppc-e7-conc40-120min", (70, 120), "E7 conc40 stationary hour 2"),
    ("ppc-e2-conc40-cap60",  (10, 60),  "E2 cap60 warm"),
    ("ppc-b1a-base",         (20, 60),  "b1a base solo warm"),
    ("ppc-b1b-base",         (20, 60),  "b1b base solo warm"),
    ("ppc-b1c-base",         (20, 60),  "b1c base solo warm"),
    ("ppc-e1-conc100",       (30, 55),  "E1 conc100 collapsed plateau"),
    ("ppc-b1a2-base",        (130, 175), "b1a2 post-relapse plateau"),
    ("ppc-b1a2-rep-base",    (130, 175), "b1a2-rep post-relapse plateau"),
]


def measured(csv: str, lo: float, hi: float):
    df = pd.read_csv(ARCS / f"{csv}.csv")
    w = df[(df.t_min >= lo) & (df.t_min < hi)]
    return (w.req_s.mean(), w.h.mean(), w.T_meas.median(), w.kv.mean(),
            w.ttft_p50.median())


def main():
    set_gap_cap(GAP_CAP)

    print("== open-loop band sweep, GB200 8xTP4, gap cap 10.5 s ==")
    rows = []
    for r in [x / 10.0 for x in range(5, 61, 1)]:
        hi = solve(gb200(r), seed_hit=1.0)
        lo = solve(gb200(r), seed_hit=0.0)
        rows.append((r, hi.h_tok, lo.h_tok, hi.t_hbm, lo.t_hbm,
                     hi.rho_prefill, lo.rho_prefill))
    band = pd.DataFrame(rows, columns=["rps", "h_hi", "h_lo", "T_hi", "T_lo",
                                       "rho_hi", "rho_lo"])
    band.to_csv(OUT / "gb200_band.csv", index=False, float_format="%.4f")
    bist = band[band.h_hi - band.h_lo > 0.05]
    if len(bist):
        print(f"  bistable band (h_hi - h_lo > 5pts): "
              f"rps [{bist.rps.min():.1f}, {bist.rps.max():.1f}]")
    else:
        print("  no bistable band in sweep range")
    up = band[band.h_hi < 0.5]
    print(f"  warm-branch collapse point: rps ~{up.rps.min():.1f}"
          if len(up) else "  warm branch survives to 6.0 rps")

    print("\n== model vs measured, steady cells (seeded per branch) ==")
    hdr = (f"{'cell':<32} {'rps':>5} | {'h meas':>7} {'h model':>8} | "
           f"{'T meas':>7} {'T model':>8} | {'rho_p':>5} {'ttft50':>7}")
    print(hdr)
    print("-" * len(hdr))
    for csv, (lo_m, hi_m), label in CELLS:
        rps, h_m, t_m, kv_m, ttft_m = measured(csv, lo_m, hi_m)
        warm = h_m > 0.5
        m = solve(gb200(rps), seed_hit=1.0 if warm else 0.0)
        print(f"{label:<32} {rps:5.2f} | {h_m:7.1%} {m.h_tok:8.1%} | "
              f"{t_m:7.0f} {m.t_hbm:8.0f} | {m.rho_prefill:5.2f} {ttft_m:7.2f}")

    set_gap_cap(None)


if __name__ == "__main__":
    main()
