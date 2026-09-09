"""Round-4 investigation: quantify HBM virtual-clock aging that free
headroom should have absorbed.

The two-clock LRU advances node.clock by every write regardless of
pool occupancy; a real allocator evicts only when allocation demand
exceeds free blocks. This script instruments RouterSessionSim (A1:
8x 0.022 s0.25 C_CPU_500, 300 min) and buckets every clock advance by
the instantaneous pool occupancy kv_used / C_HBM at write time and by
run phase (warm < 62 min, surge 62-107, post-cancel > 107).

Aging booked while occupancy < threshold is eviction pressure a real
fleet would have absorbed into free blocks (no resident entry ages).
Writes out/headroom_aging_a1.csv and prints per-seed totals.

Run from kv_equilibrium/:
    ../.venv/bin/python -u investigate_headroom_aging.py
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd

import des
from des_b1 import RouterSessionSim, C_CPU_500, T_ON, T_OFF

OUT = Path(__file__).parent / "out"
T_END = 300 * 60.0
THRESH = (0.5, 0.7, 0.92)
SEEDS = (1, 2, 3)


class AgingProbe(RouterSessionSim):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # rows: (t, occupancy_at_write, tokens)
        self.aging = []

    def _record(self, node, w):
        if w > 0:
            self.aging.append((self.now, node.kv_used / des.C_HBM, w))

    def finish_prefill(self, rid, node_idx, seq, arrival, prefix, in_tok,
                       out_tok, cached, prefill, tier):
        if rid not in self.aborted:
            self._record(self.nodes[node_idx],
                         prefill + (cached if tier == "cpu" else 0.0))
        super().finish_prefill(rid, node_idx, seq, arrival, prefix,
                               in_tok, out_tok, cached, prefill, tier)

    def finish_decode(self, rid, node_idx, seq, prefix, in_tok, out_tok):
        if rid not in self.aborted:
            self._record(self.nodes[node_idx], out_tok)
        super().finish_decode(rid, node_idx, seq, prefix, in_tok, out_tok)


def main():
    rows = []
    for seed in SEEDS:
        t0 = time.perf_counter()
        sim = AgingProbe(8, 0.022, 0.25, C_CPU_500, seed, t_end=T_END)
        sim.run()
        a = np.array(sim.aging)
        t, occ, w = a[:, 0], a[:, 1], a[:, 2]
        phases = {"warm": t < T_ON,
                  "surge": (t >= T_ON) & (t < T_OFF),
                  "postcancel": t >= T_OFF,
                  "all": np.ones_like(t, dtype=bool)}
        for pname, pm in phases.items():
            tot = w[pm].sum()
            row = {"seed": seed, "phase": pname, "total_tok": tot,
                   "mean_occ_wtd": float((occ[pm] * w[pm]).sum()
                                         / max(tot, 1.0))}
            for th in THRESH:
                row[f"frac_below_{th}"] = float(
                    w[pm & (occ < th)].sum() / max(tot, 1.0))
            rows.append(row)
        print(f"seed {seed}: {time.perf_counter() - t0:.0f}s wall, "
              f"{len(a)} advances, total {w.sum():.3e} tok "
              f"(= {w.sum() / des.C_HBM:.1f} pool traversals/node-fleet)")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "headroom_aging_a1.csv", index=False,
              float_format="%.4f")
    print(df.to_string(index=False))
    print("DONE")


if __name__ == "__main__":
    main()
