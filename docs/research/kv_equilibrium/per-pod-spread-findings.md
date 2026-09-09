# Per-pod spread analysis: routing-quality signatures vs fleet size

Date: 2026-08-14. Inputs: per-endpoint counters from the collected
parquets (per_pod_spread.py), 15 runs spanning 4x/8x/16x fleets and
the shard draw. Outputs: out/perpod/<run>.csv (per-window per-pod
metrics), out/perpod/spread_summary.csv (per run x phase medians).
This is the GPU-free first cut of open question 1 (which coordination
property drives the N-dependent fragility).

Metrics per (run, window): fleet h; unweighted per-pod h mean/std/
max-min; query-share CV (N * std of per-pod prompt-token shares) and
max-share ratio; per-pod KV-usage std; Pearson corr(share_i, h_i).
Phases: warm [10,60), surge [65,105), recovery [110,180),
late [180,300) minutes.

## Findings

1. LOAD IMBALANCE REFUTED as the N-mechanism. Query-share CV does not
   grow with N in any phase (warm: 4x 0.46-0.48, 8x 0.34-0.51, 16x
   0.46-0.56; recovery: 4x 0.12-0.21, 8x recovering 0.21, 16x
   0.14-0.15). The recovering shard draw shows HIGHER share dispersion
   than the relapsing 16x runs at matched relative times. The
   max-share ratio grows with N only as the expected extreme-value
   bias of max over N draws.

2. PER-POD HIT DISPERSION GROWS WITH N at equal fleet h. Warm fleet h
   is 0.94 at every N (no static affinity degradation), but warm
   per-pod h std roughly doubles from 4x/8x (~0.032) to 16x
   (0.044-0.067). corr(share, h) is strongly positive everywhere
   (0.57-0.86): busier pods run warmer. The dispersion is a
   coordination signature, not a load-balance defect.

3. THE 16x RELAPSE IS A STAGGERED CASCADE, NOT A UNIFORM DECAY. At
   t=110 both the 16x fleet and the 8x draws unpin (kv > 0.85 on
   1/16 vs 0/8 pods) and re-warm to per-pod h medians 0.64-0.68.
   The 16x then re-pins pod by pod - 3/16 at t=115, 11/16 at t=120,
   14/16 at t=125, 16/16 at t=130 - with per-pod h spreading to
   0.10-0.67 before fleet-wide erosion. The 8x organic collapse
   (ppc-edge020-noofl, t=245) pins 2/8 -> 8/8 within one window:
   near-synchronous, unlike the 16x cascade.

4. EXCESS KV OCCUPANCY AT MATCHED STATE (the duplication signature).
   At the matched re-warm window (t=115), per-8x-equivalent:

       arc                h      kv     uncached tok/s
       shard-a-020        0.92   0.61   24.2k
       ppc-edge020-noofl  0.93   0.62   24.5k
       ppc-n16-lh040      0.88   0.80   44.1k

   The 16x fleet carries the same per-capacity session state in
   ~0.15-0.20 more of its pool and sustains ~1.7x the per-capacity
   miss-write flux, with a 4-5 point h deficit spread across the
   whole fleet (per-pod p25-max 0.87-0.92 vs 0.91-0.95). Retention
   T_meas: 58 s vs ~190 s. The excess occupancy plus flux deficit
   closes the miss-write feedback loop that re-pins the 16x fleet.

## Interpretation

The signatures fit prefix scatter/duplication during the post-cancel
backlog drain: completion-coupled turns issued during the drain land
by load on pods that lack the session prefix, rewrite it there
(duplicate copies inflate kv at matched state), and lower fleet h
until affinity re-establishes. Static affinity quality and static
load balance are both N-invariant; what differs at 16x is the
coordination layer's behavior under churn. The client records carry
no serving-pod identity, so session-to-pod scatter is not directly
measurable from the collected data; the routing ablation and an
EPP-metrics scrape (next window) discriminate the specific property.
The single-coordinator saturation reading and the model term built on
it are in overlay-findings.md (coordination-layer section).
