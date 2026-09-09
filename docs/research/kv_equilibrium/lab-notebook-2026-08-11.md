# Lab notebook 2026-08-11: long-horizon pair (6.5-hour window)

Window: 12:25-19:00 PDT, 16 hosts, two 8-replica fleets (scaled up
12:25, ready ~12:50). Only one run fits per fleet, so the slot goes to
the single most valuable pair from the open-questions list
(lab-notebook-2026-08-10-pm.md window summary): the SYMMETRIC
LONG-HORIZON PAIR at the centerpiece operating point.

    run             fleet            protocol
    ppc-lh-noofl    igw 8x no-offl   base 0.022 sps x 18000 s (300 min),
                                     surge 0.25 x 2700 s at t ~ +62 min
    cpuofl-lh-tier  yangligt 8x ofl  identical

Questions answered:

1. No-offload arm (B3 of the completion plan): is the relapsed state
   absorbing over 195 min post-surge (vs 75 min observed so far)?
   Prediction: yes - queue grows to generator limits, no recovery.
2. Tier arm: the third regime's fate - absorbing congestion,
   metastable plateau, or slow recovery? Draw 1 showed slow divergence
   (waiting 33 -> 58 over min 150-175) but was truncated; the repeat
   ended before the tail. 195 min post-surge settles it.
3. Together: the paper's side-by-side exhibit - cold absorbing
   collapse vs restore-bound congestion, same operating point, same
   perturbation, same horizon.

Deferred to next window: 0.017 bimodality draw 4+, B2a 4x repeat
(scale question), A4 tier-size point (RAM-unit check first), A2 4x
no-offload control.

Standing practice: both vllm deployments scale to 0 at window end
(EPPs stay).

Timing: profiling ~12:55 -> 17:55, grace + records + collect ~18:15,
margin ~45 min to the 19:00 cutoff. Nothing else launches.

## Run log

### ppc-lh-noofl - ABSORBING CONFIRMED over 195 min post-surge

Profiling 19:38-00:38 UTC. Warm base h 86-96% to min 60; surge
saturates (wait 788); post-cancel interlude (min 110: h 70.4%, wait
26 - the DES-predicted warm window); relapse completes by min 150.
Then 150 -> 300 min: h pinned 1.6-3.0%, KV 92%, waiting grows
MONOTONICALLY 77 -> 289 (~1.1/min), TTFT p50 to 240 s, throughput
1.2-1.4 req/s. No recovery attempt visible anywhere in 195 min of
constant exogenous arrivals. Relapse at 0.022: n=3, longest horizon.

### cpuofl-lh-tier - THIRD REGIME: SLOWLY DIVERGING, NOT STABILIZING

Profiling 19:38-00:38 UTC, identical protocol. Same in-surge
saturation (wait 798, tier exhausts: ext 1-2%). Post-cancel recovery
(min 110-120: h 85-86%), then restore-bound congestion for the entire
remaining 180 min: h holds 70-84% (never collapses), ext_hit pinned
68-79% (most hits are CPU restores), KV 93-94%, throughput 2.5-4.3
req/s, and waiting climbs 6 -> 164 with TTFT p50 1.5 -> 60 s. A
partial stabilization (min 150-170: wait 15-17) precedes resumed
growth - metastable-looking plateau, then divergence.

### Window verdict - the paper's mitigation figure

Same operating point (0.022 sps), same perturbation, same 195-min
horizon, side by side:

                     no-offload            CPU tier
    end-state h      1.6-3.0%              70-84%
    hits source      (cold re-prefill)     68-79% CPU restores
    throughput       1.2-1.4 req/s         2.5-4.3 req/s (~2.2x)
    TTFT p50         240 s                 ~60 s (~4x better)
    queue growth     +289 (1.1/min)        +164 (0.8/min), slower
    character        cold absorbing        restore-bound congestion,
                     collapse              slowly diverging

The tier does NOT restore stability at this operating point - both
arms diverge - but it transforms the failure mode: 2.2x throughput,
4x latency, h at 75% instead of 2%. The tier's stability boundary
lies below 0.022 sps at 8x (B2a recovered at the 4x-scaled
equivalent; the scale question stands). Sizing/boundary mapping (A4 +
tier ladder) is the remaining hardware work for the mitigation
chapter, plus restore-bandwidth modeling on the theory side.

Fleets scaled to 0 at 17:55 PDT (verified 0/0; EPPs up; no jobs).
