"""Scratch: congested-state mean restore transfer size, A1 baseline.

Instruments RouterSessionSim (unmodified dynamics; recording only) to
collect the cached-token size of every CPU-tier restore completing in
t in [120, 295] min, the phase where the modeled per-node restore rate
sits at the pinned plateau. Pooled mean feeds the T_OVERHEAD
derivation in heal_variant_serial.py.
"""

import numpy as np

from des_b1 import RouterSessionSim, C_CPU_500

T_END = 300 * 60.0
LO, HI = 120 * 60.0, 295 * 60.0


class Probe(RouterSessionSim):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sizes = []

    def finish_prefill(self, rid, node_idx, seq, arrival, prefix, in_tok,
                       out_tok, cached, prefill, tier):
        if (tier == "cpu" and rid not in self.aborted
                and LO <= self.now <= HI):
            self.sizes.append(cached)
        super().finish_prefill(rid, node_idx, seq, arrival, prefix, in_tok,
                               out_tok, cached, prefill, tier)


pooled = []
for seed in range(1, 7):
    sim = Probe(8, 0.022, 0.25, C_CPU_500, seed, t_end=T_END)
    sim.run()
    s = np.array(sim.sizes)
    pooled.append(s)
    print(f"seed {seed}: n={len(s)} mean={s.mean():.0f} "
          f"median={np.median(s):.0f} p90={np.percentile(s, 90):.0f}",
          flush=True)
allv = np.concatenate(pooled)
print(f"POOLED n={len(allv)} mean={allv.mean():.1f} "
      f"median={np.median(allv):.1f}")
print("DONE")
