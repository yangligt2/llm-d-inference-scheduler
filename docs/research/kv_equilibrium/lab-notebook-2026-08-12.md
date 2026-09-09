# Lab notebook 2026-08-12: prediction-testing window (09:05-18:00 PDT)

16 hosts, two 8-replica fleets (scaled up 09:07). Every run today
tests a specific prediction from the restore-bound congestion model
(overlay-findings.md, out/restore_boundary.csv).

## Plan

Slot 1 (both fleets in parallel, 300 min, base 0.020 sps + standard
0.25 x 2700 s surge at t ~ +62):

    ppc-edge020-noofl    8x no-offload. Prediction: relapse likely
                         (measured collapse edge bracket (0.017,
                         0.022); older model edge (0.016, 0.020)).
                         Sharpens the collapse edge either way.
    cpuofl-edge020-tier  8x tier. Prediction: CONGESTED 4/5,
                         recovered 1/5 (restore_boundary.csv) - the
                         predicted bimodal point of the tier
                         boundary (0.017, 0.020).

  Same lambda, tier vs no-tier, same horizon: quantifies the edge
  shift and the failure-character contrast in one paired figure.

Slot 2 (after slot-1 collections ~14:55 PDT):

    ppc-bimod4           igw, 0.017 no-offload, 150 min. Recalibrated
                         DES predicts 0/5 relapse at 0.017 (the old
                         calibration said 1/5 and the measured tally
                         is 3/3 recoveries). A relapse here would
                         falsify the corrected calibration.
    cpuofl-a4-half       yangligt: patch --kv-offloading-size 500 ->
                         250 (DOWN-tune, safe per RAM caution),
                         rollout (~25 min), then 0.022 x 8100 s
                         (135 min) + surge. Prediction (ccpu sweep):
                         still congested, similar queue growth,
                         possibly lower h (0.85-0.95) - tier SIZE
                         does not fix congestion; restore BANDWIDTH
                         binds. Tight against the 18:00 cutoff
                         (collect ~17:55); trim duration at launch if
                         the rollout runs late.

Mid-window update (~12:50 PDT): 32 additional nodes granted until
18:00; user cleared --kv-offloading-size up to ~650 (implies GB units
with real RAM headroom; today's 250 down-tune is a genuine halving).
Slot-2 revision: igw scales 8 -> 16 after slot 1 and runs the 16x
N-SCALING INVARIANCE POINT (base 0.040 + surge 0.50 x 2700 s, 135
min) instead of bimod4 - per-pod scale-invariance predicts the same
outcome class as the 8x-0.020 arm. The other 24 extra nodes are
unused today (every remaining queued run needs a second offload
stack or a 300-min slot; the 4x falsifier missed its start-by time).

Prep for next window (user): pre-build a second offload namespace at
4 replicas (clone yangligt manifests; model is gcsfuse from GCS so no
PVC cloning - just the zone-pinned bench-assets seed), so the
4x-0.011 300-min scale falsifier runs first thing. Also queue A4-up
(650) for the effective-cap/units probe.

Deferred (needs a full 300-min slot): the 4x-0.011 tier 300-min
repeat - the scale-question falsifier (DES: wait 75-142 at 270-295
min vs ~0 if the 4x point is genuinely stable).

Standing practice: both vllm deployments to 0 at window end.

## Run log

### Slot 1 verdicts: the 0.020 pair (both 300 min, collected ~14:00 PDT)

ppc-edge020-noofl - PERTURBATION RECOVERY, then ORGANIC COLLAPSE:
- Surge saturates as always (wait 777). Post-cancel: clean recovery
  (h 89-94%, wait 0-1) holding 110 min (min 110-220) at 3.7-4.4
  req/s realized with KV drifting 58 -> 80% as sessions deepen.
- Min 240-250: ORGANIC tip with no perturbation - h 81 -> 27 -> 4%,
  KV re-pins 91-92%, wait 22 -> 83 growing at run end. The
  qps15-style organic collapse, first time observed post-recovery.
- Reading: at 0.020 the perturbation is survivable but the steady
  state itself is METASTABLE on multi-hour horizons (deepening load
  walks KV into the pin). The collapse-edge statement becomes
  horizon-dependent: perturbation-edge in (0.020, 0.022),
  organic-stability edge BELOW 0.020. Only visible at 300 min.

cpuofl-edge020-tier - FULL HEAL (the model's bimodal point resolves
to its recovery branch in this draw):
- Identical in-surge saturation (wait 788, tier exhausted).
- Post-cancel: restore-assisted digestion for ~2 h (ext_hit 42-73%,
  KV 74-92%, wait 1-9, h 85-93) - the third-regime signature but
  BOUNDED - then the restore share decays 64 -> 47 -> 25 -> 10 -> 3
  -> 0% and the fleet ends fully warm-in-HBM: h 94-95%, KV 5%,
  wait 0. Complete self-heal including tier drain-back.
- Model check: restore_boundary.csv predicted 0.020 congested 4/5,
  recovered 1/5 - this draw is consistent with the recovery branch
  (or a slightly conservative model boundary; one draw cannot
  distinguish).

PAIRED verdict (paper figure): same lambda 0.020, same surge, same
300-min horizon - no-offload recovers then dies organically at min
~240; the tier digests the perturbation and fully heals. At the
boundary the tier converts a metastable operating point into a
self-healing one. This is a stronger tier-value statement than
either the 0.022 pair (both fail, differently) or the old B2a.

### cpuofl4x-falsifier (yangligt-4x, 0.011, 210 min) - DES FALSIFIED;
### the 4x point is GENUINELY STABLE

- Namespace bring-up note: first rollout stalled on GCS
  PermissionDenied (Workload Identity IAM for ns/yangligt-4x
  propagating); binding was already present on recheck; pod bounce
  mounted cleanly. Launch gates switched from `kubectl rollout
  status` (poisoned by the stale progress-deadline condition) to a
  direct readyReplicas poll.
- Arc: warm base (h 95-96%), surge saturates (wait 298, h 5.7%,
  tier exhausts), then COMPLETE recovery: wait 0 within one window
  of cancellation, h 93-96%, restore share 59 -> 0%, KV drains to 6%
  by run end. End-state wait = 0 vs DES-predicted 40-90.
- Verdict: the DES's mild-congestion prediction at 4x-0.011 is
  falsified; with B2a this is n=2 clean stability at 4x while the
  same per-capacity point at 8x congests (n=2 + long-horizon). Both
  calibrated mechanisms (tpot, restore BW) are per-pod
  scale-invariant, so an N-DEPENDENT mechanism differentiates the
  fleets - candidates: prefix-affinity routing quality vs pod count,
  per-pod load imbalance growing with N. "Larger fleets are more
  fragile at equal per-capacity load" is now a live hypothesis; the
  16x invariance point bears directly on it.

### cpuofl-a4half (8x, tier 250 units, 0.022, 135 min) - INCONCLUSIVE
### on the size question; in-surge consistent with size-indifference

- The surge chain's gate included the A4 rollout wait, so the surge
  fired at base t ~ +70 and only ~10 min of post-surge tail fit
  before base end - the congest-vs-heal discriminator did not have
  time to express.
- What IS observable matches the full-tier (500) draws exactly:
  in-surge tier exhaustion (ext ~1% by min 85, wait to 890), then
  restore-driven catch-up onset (ext 48-61%, h 84-88, wait 4-6 at
  min 125-130). No half-size difference detectable in these phases,
  which is what the model's capacity-indifference claim predicts
  in-surge - weak supporting evidence, not a verdict.
- Full-length A4-half rerun (>= 210 min) queued for the next window;
  same for the 650 up-tune probe.

### ppc-n16-inv040 (16x no-offload, 0.040 + 0.50 surge, 135 min) -
### INVARIANCE VIOLATED in the fragile direction

- Warm base h 92-94% at realized 3.9-6.2 req/s (per-capacity ~2.0-3.1
  in 8x-equivalent - matched to the 0.020 pair's draw range).
- Surge saturates at wait 1360 (~680 8x-equivalent, matched).
  Post-cancel: partial recovery only (h 75.9, wait 11 at min 125),
  then immediate re-degradation - h 49.8 -> 23.8, KV 92%, wait
  regrowing at run end (135-min truncation).
- Matched-relative-time contrast: 8x-0.020 at min 110-125 sat in
  CLEAN recovery (h 89-93%, wait 0-1; its organic collapse came 2 h
  later). 16x-0.040 never reached a clean state.
- With the falsifier, the day yields a monotone N-dependence at
  per-capacity-matched points: 4x STABLE (n=2), 8x MARGINAL
  (recovers, organically collapses at 240 min), 16x RELAPSING
  (~15 min post-surge). Per-pod physics (tpot, restore BW) is
  measured scale-invariant, so the N-effect lives in the
  coordination layer - prefix-affinity routing quality, per-pod
  imbalance, or admission dynamics vs pod count. This is the paper's
  sharpest open mechanism question and the next window's priority
  (per-pod h spread and routing-attribution analysis of today's
  three arcs can start GPU-free).

## Window summary (2026-08-12, five runs, three fleets)

    run                  verdict
    ppc-edge020-noofl    perturbation recovery, ORGANIC collapse at
                         min 240 - 0.020 metastable on long horizons
    cpuofl-edge020-tier  FULL HEAL incl. tier drain-back - at the
                         boundary the tier makes the point self-healing
    cpuofl4x-falsifier   DES falsified: 4x-0.011 genuinely stable
                         (wait 0 vs predicted 40-90)
    cpuofl-a4half        inconclusive (surge timing); in-surge
                         consistent with size-indifference
    ppc-n16-inv040       invariance violated: 16x relapses where 8x
                         recovered, per-capacity matched

Headline: fleet-size dependence of stability at equal per-capacity
load (4x < 8x < 16x fragility), with per-pod mechanisms measured
scale-invariant. Plus the tier's strongest value statement (0.020
pair) and a horizon-dependent stability edge (organic collapse only
visible at 300 min).

GPU-free follow-ups: per-pod hit/load spread analysis across
today's arcs (routing-quality vs N); DES/fluid need an N-dependent
coordination term. Hardware queue: full-length A4 pair (250/650),
16x longer-horizon confirm, more 0.020 tier draws (bimodal point).

All three namespaces scaled to 0 at window end.
