"""Adversarial recheck of the progressive-allocation screen, arm A2.

Reruns ProgressiveSim on A2 (n=8, 0.022, C_CPU_250) seeds 3 and 6 with
an independent continuous conservation ledger (every 60 s sim time)
and watermark-overshoot tracking, then compares against the stored
screen rows and per-run windows. Read-only with respect to the
existing variant modules; nothing in heal_variant_progressive.py is
modified. Working file for the heal-branch candidate judgment.
"""

import numpy as np
import pandas as pd

import des
from des_b1 import C_CPU_250
from heal_variant_progressive import ProgressiveSim, classify, T_END


class CheckedProgressive(ProgressiveSim):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger_checks = 0
        self.max_kv_frac = 0.0
        self.max_run_node = 0

    def _periodic(self):
        held = [0.0] * len(self.nodes)
        cnt = [0] * len(self.nodes)
        for ni, _seq, h, _stage in self.running.values():
            held[ni] += h
            cnt[ni] += 1
        for i, node in enumerate(self.nodes):
            assert abs(node.kv_used - held[i]) <= 1e-6 * max(held[i], 1.0), \
                ("kv mismatch", self.now, i, node.kv_used, held[i])
            assert cnt[i] == self.node_running[i], \
                ("count mismatch", self.now, i, cnt[i], self.node_running[i])
            assert node.kv_used >= -1e-6, ("negative kv", self.now, i)
            self.max_kv_frac = max(self.max_kv_frac,
                                   node.kv_used / des.C_HBM)
            self.max_run_node = max(self.max_run_node, cnt[i])
        self.ledger_checks += 1
        self.at(self.now + 60.0, self._periodic)

    def run(self):
        self.at(60.0, self._periodic)
        return super().run()


def main():
    stored = pd.read_csv("out/heal_screen_progressive.csv")
    for seed in (3, 6):
        sim = CheckedProgressive(8, 0.022, 0.25, C_CPU_250, seed,
                                 t_end=T_END)
        sim.run()
        win = sim.windows()
        outcome, h, wait = classify(win)
        end = win[(win.t_min >= 270) & (win.t_min <= 295)]
        row = stored[(stored.arm == "A2") & (stored.model == "variant")
                     & (stored.seed == seed)].iloc[0]
        print(f"A2 variant seed {seed}: rerun outcome={outcome} "
              f"end_h={h:.4f} end_wait={wait:.2f} "
              f"end_run={end['run'].mean():.1f} "
              f"end_restore_s={end.restore_s.mean():.0f}")
        print(f"  stored: outcome={row.outcome} end_h={row.end_h} "
              f"end_wait={row.end_wait} end_run={row.end_run}")
        print(f"  ledger checks passed: {sim.ledger_checks} "
              f"(every 60 s); max node kv/C_HBM {sim.max_kv_frac:.3f}; "
              f"max node running {sim.max_run_node}")
        match = (outcome == row.outcome
                 and abs(h - row.end_h) < 5e-4
                 and abs(wait - row.end_wait) < 0.05)
        print(f"  reproduction: {'MATCH' if match else 'MISMATCH'}")


if __name__ == "__main__":
    main()
