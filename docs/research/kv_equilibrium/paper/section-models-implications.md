# 8. Models: fluid and DES

## 8.1 Construction

Two model layers share one calibration. The fluid model
(fluid_model.py, overlay_b1_dynamics.py) evolves a session reservoir
with completion-coupled turn release, per-pod tpot interference, and
a contended fleet restore channel: restores form a third max() term
in the waiting-time expression (the prefill and restore channels
serve different requests concurrently, so an arrival waits on the
bottleneck backlog, not the sum), achieved restore traffic advances
the HBM write clock, and the CPU tier churns at the measured
tier-ingest rate with hit-refresh [R9]. Arriving (salted) sessions
enqueue a forced full-miss first request as an explicit queue class;
surge populations are cancelled at surge end, matching the
instrument.

The DES (des_b1.py, subclassing des.py) adds discrete structure the
fluid cannot carry: watermark admission (waiting requests join a
node's batch, full KV need reserved, while the batch fits under the
KV headroom; the prefill engine stays serialized), a two-clock LRU
(the HBM clock advances with prefill, restores, and generation; the
tier clock with new writes only; touch stamps refreshed at decode
end), and a per-node FCFS restore channel at B_r through which
CPU-tier hits pass before prefill, with asynchronous onboarding
[R9]. A single-clock tier variant (tier churned by restores) was
rejected against measurement: it drives the tier to exhaustion and a
cold collapse by min 270 that the 300-min hardware run refutes, and
it contradicts the measured tier-ingest rate
(overlay-findings.md).

The deployed-router layer, RouterSessionSim, replaces the idealized
lexicographic router with the shipped EPP algorithm; every
scheduling constant is read from the deployed config or plugin code,
none fitted: prefix-affinity sticky threshold 0.80; TTFT load gate
18000 ms with TTFT estimated as in-flight tokens over the deployed
peakPrefillThroughput of 28888 tok/s; token-load scoring
(least-in-flight-token candidate); and the 300 s in-flight staleness
reap, under which deep engine queues undercount and the gate rarely
breaks under backlog [R9]. The model contains no coordinator term.
An earlier coordinator-saturation freeze (C_W) is retired on two
independent grounds: the EPP-side measurements contradict its
physical reading (event-pool queue empty, index admissions tracking
demand with no plateau, 1.9 of 4 cores, lookups under 1 ms through
three reproducing 16x relapses [R13]), and it is unnecessary - at
the 300-min classification horizon no verdict changes without it
[R9]. The idealized router is itself a negative control: it
produces identical relapse rates at per-capacity-matched points
(3/5 at both 8x-0.020 and 16x-0.040), so the measured span
dependence is not reproducible from scheduling-algorithm
idealizations plus per-pod physics (overlay-findings.md).

## 8.2 Calibration

Every constant and its provenance; TIER_EFF is the single fitted
value.

| Constant | Value | Source |
|----------|-------|--------|
| P_TPT | 17k tok/s/replica | measured saturated uncached plateaus, 131-138k tok/s fleet [R9] |
| HBM pool | 6486 blocks x 256 tok per TP4 replica | engine config; byte size cross-checked against KV/token [R9] |
| tpot(R, N) | 10.8 ms + 2.56e-4 (R/N)^2 | fit over 552 measured windows (out/tpot_fit.png, out/tpot_fit.csv); per-pod form selected because the fleet-R form under-predicts the saturated 4x windows 2.4x (RMSE 27.4 vs 18.6 ms) [R9] |
| B_r | 23k tok/s/replica effective | measured per-pod restore plateau, 21.4-24.0k across four tier runs at both fleet scales [R4]; a congested-state throughput calibration, not a channel ceiling (Sec. 8.5) |
| DMA link | 151.5 GB/s = 1.19e6 tok/s/node | measured from offload counters (bytes/time); B_r runs the link at ~2% duty, so per-transfer overhead binds [R4] |
| KV/token | 127 KB (fp8, 62 layers, 8 KV heads, 128 dim) | validated against the HBM pool byte size; windowed CPU-to-GPU bytes / 127 KB matches the windowed ext-hit token rate to under 1% in every tier run [R9] |
| E[req/session] | 118 realized | 28366 records / 240 sessions in the 3 h windows; the corpus mean of 174 inflates every arm's demand ~40% and moves the model boundary off the measured bracket (overlay-findings.md) |
| Think-gap CDF | corpus mix, truncated at 10.5 s | corpus p90 gap cap, an experiment-protocol constant [R9] |
| First-request size | ~51.6k tokens | system prompt plus first input; forced full miss per arriving salted session (overlay-findings.md) |
| Router constants | 0.80 / 18000 ms / 28888 tok/s / 300 s | read from the deployed EPP config and plugin sources; none fitted [R9] |
| Tier capacity | 160 GB/pod = 1.26M tok/pod nominal | RAM-derived; scaled by TIER_EFF |
| TIER_EFF | 0.67 (FITTED) | cold-side ordering of the tier ledger: eff(250) = 0.42M tok/pod must sit at or below the DES cold/congested transition and eff(375) = 0.63M at or above it, with the in-model transition spanning (0.42, 0.63)M; the congested-state miss share independently implies an effective window below nominal [R9] |

## 8.3 Validation set

Figure (out/overlay_b1_dynamics.png). Caption draft: Fluid overlay
on the four b1 protocol arms (0.022, 0.017, 0.012 sps no-offload;
0.011 sps with tier at 4x); surge window shaded; model curves
labeled as model output. The waiting-queue trajectories match in
all four arms, including the post-cancellation re-growth on the
relapse arm.

Figure (out/des_b1_overlay.png). Caption draft: DES validation arms,
5 seeds each, min-max shading; end states bracket the measured
values in all four arms and sit closer than the fluid on the relapse
arm.

Figure (out/overlay_nseries.png). Caption draft: DES fleet-size
ladder (12 seeds x 6 arms, 300 min, no coordinator term) with
measured draws overlaid; the 16x collapse curve sits left of the 8x
curve at matched per-capacity rate. Model output; absolute placement
carries the documented reservation bias.

The model reproduces, in order of evidential weight [R9]:

- The no-offload band and outcome classes (results 1-2): relapse at
  0.022, recovery at 0.017 and 0.012, the B2a tier recovery at its
  180-min horizon, with in-surge peak waits 620-787 on the 8-replica
  arms against measured 675-790, smooth 20-40 min h erosion where
  the fluid transition is square, and the post-cancellation warm
  interlude present in every relapsing seed (the measured
  15-min-interlude/no-interlude pair sits inside the seed spread).
- The third regime, 5/5 discriminators: restore channel pinned near
  N*B_r, linear slow queue divergence, h holding high, no cold
  collapse, at 8x-0.022 tier [R4][R9]. Quantitative gaps are stated,
  not fitted: model h 0.95 vs measured 0.70-0.85, restore share 1.0
  vs 0.66-0.79, completion rate 1.6 vs 2.5-4.3 req/s.
- The tier-250 fall-through in direction and persistence boundary:
  tier-250 cold 4/5 with the DES mean tracking the measured
  decay-through-congestion arc, tier-500 congested 5/5 and never
  cold [R11][R9] (figure out/overlay_tiercap.png if not consumed by
  Section 6; caption draft: DES tier-capacity pair at 8x-0.022,
  sizes 250 and 500, measured arcs overlaid; model bands span
  outcome classes at bimodal points).
- The fleet-size shift, emergent: with no N-dependent term, DES
  p(collapse) at 300 min is 8x 0.017/0.020/0.022 = 2/12, 11/12,
  12/12 vs per-capacity-matched 16x 0.034/0.037/0.040 = 5/12,
  12/12, 11/12 - 0.42 vs 0.17 at the 0.017-equivalent [R9]. The
  shift arises because the shared router's load balancing couples
  every pod's post-cancellation drain-vs-catch-up race, suppressing
  the favorable fluctuations that independent shard routers
  sometimes draw; the model predicts shard draws behave as
  independent 8x systems, matching the measured containment [R10].

## 8.4 Known biases

Full KV need is reserved at batch admission (vLLM allocates blocks
progressively during chunked prefill), which overstates running-set
residency during backlog drains. Both DES collapse curves sit left
of the measured ones as a consequence; the model's quantitative
claim is the shift and the outcome-class structure, never absolute
collapse probabilities [R9]. Further documented DES limitations:
tpot is frozen at decode start; no preemption/recompute path;
relapsed h floors at 0 vs the measured 3-12% residual
(overlay-findings.md).

## 8.5 Executed falsifiers

Predictions were registered before hardware windows and are reported
regardless of outcome.

- 4x-0.011 tier at 300 min: predicted wait 52-160; measured 1.3,
  stable 3/3, of which one draw ran the 300-min horizon. The
  prediction is falsified; the miss is assigned to the heal branch
  (Sec. 8.6) [R9].
- Tier 375/650 bracket, registered under the prior TIER_EFF = 0.5
  (375 inside the predicted cold-boundary region): 375 healed 2/2,
  excluding 0.5 and forcing the recalibration to 0.67; the 650 arm
  was not executable (boot failure on gcsfuse sidecar OOM, bounding
  the size series at (500, 650) on these hosts) [R11][R9].
- 16x per-capacity edge points: the ladder's left shift is confirmed
  in direction by the measured 16x tallies (0.034 recovered 1/1 -
  n=1 - 0.037 bimodal 1/2, 0.040 relapse 4/4) [R6]; absolute DES
  rates at the edge over-predict collapse (5/12 at 0.034 vs the one
  measured recovery), consistent with the reservation bias.
- The fleet-R interference form: falsified by the saturated 4x
  windows (predicted 33 ms vs measured 81 ms mean tpot); the
  per-pod form replaced it (out/tpot_fit.csv) [R6][R9].
- The B_r ceiling reading: the serial FCFS channel encodes B_r as a
  hard per-node cap; measured heal arcs sustain 5-min fleet restore
  rates of 235,284 and 278,161 tok/s (1.28-1.51x N*B_r, two arcs),
  then run post-cancel restore at 0.14-0.56 N*B_r [R4]. The 23k
  plateau is a congested-state throughput outcome. The serial
  channel stands as a documented deficiency: its concurrent-restore
  replacement screens negative on the heal branch and is not merged
  (Sec. 8.7).

## 8.6 Documented failures

The heal branch is the model's primary open failure: zero DES heals
in 30 sweep runs at 8x-0.022 at any tier capacity vs 4 measured
heals in 8 draws at sizes 375-500; the missed full heal at the
0.020 boundary (one matched pair measured); and the falsified
4x-0.011 300-min prediction above [R9]. The failure is one-sided -
the DES reproduces cold collapse, restore-bound congestion, and the
recovery arms, but cannot exit the congested state through
drain-back. The fluid layer carries a second documented failure:
branch selection at 8x cancellation. It reproduces the in-surge
restore-bound state but flushes its restore backlog within ~2 min of
cancellation and exits to the warm branch at both scales; the DES,
restore-serialized with heterogeneous gaps, diverges, matching
measurement. Both layers sit near the same critical balance
(measured throughput 2.5-4.3 req/s brackets both); no fluid constant
flips the branch without violating a measurement, so the DES is the
validated layer for the third regime (overlay-findings.md).

## 8.7 Heal-branch candidate screens

Four candidate mechanisms were screened on a shared protocol: arms
A1-A7 spanning tier, no-offload, capacity, and span variants, 6
seeds, 300 min, with a guard constraint that any candidate preserve
the cold/congested boundary and the no-offload band; a draw counts
as a heal only under joint end-state criteria (recovered wait and h,
drained KV, ext-share and running-set bounds)
(overlay-findings.md, 2026-08-25 subsection). All four screens are
negative; none is merged.

1. Reservation timing (heal_variant_progressive.py): progressive KV
   allocation removing the full-KV-at-admission overstatement.
   Informative negative, do-not-merge: A1 remains 0/6 healed, and
   the variant manufactures a non-physical interference-locked
   congested state in the no-offload guard arm A4 (measured recovery
   4/4; variant 4/6 congested with no restore channel involved) that
   vLLM's step-budget scheduler cannot enter. Conservation was
   verified by an independent ledger
   (adversarial_check_progressive.py). The screen's retained value
   is diagnostic: every failing A1/A5 baseline draw drains from wait
   319-745 at t=105 to a trough of 0-31 at t=115 (9 of 11 at or
   below 9), then re-enters congestion
   (out/heal_screen_progressive.csv, out/heal_progressive_runs/).
2. Stale-content tier churn (heal_variant_stale.py): a credit
   bracket subtracting dead-surge write tokens from tier ages -
   the complete-instantaneous-reclamation bound, bracketing every
   intermediate policy against strict LRU. Null: outcome tallies
   match baseline on every arm; the instrument run shows the live
   write flux churns dead content out of the two-clock window by
   ~13 min after cancellation and the rescuable fraction of live
   tier misses is 0.0 for the remaining 180 min. Definitive
   exclusion within the two-clock abstraction; staleness effects,
   if real, live outside that window model
   (out/heal_stale_instrument.csv, out/heal_screen_stale.csv).
3. Restore-channel serialization (heal_variant_serial.py):
   concurrent onboarding at the measured 1.19e6 tok/s link with
   per-transfer overhead 4.232 s derived from the measured B_r
   plateau via B_r = S/(S/LINK_RATE + T_OVERHEAD) at the model's
   pooled mean restore size of 99,247 tok (the measured counters
   carry token rates but no transfer counts). Negative: A1 0/6
   healed; failing arms still re-enter congestion, and the
   congested-state pin overshoots the measured 0.81-1.04 N*B_r band
   (1 of 15 congested draws in band, peaks to 1.91)
   (out/heal_screen_serial.csv).
4. Occupancy-gated HBM eviction (heal_variant_headroom.py):
   allocation-pressure-only eviction replacing the unconditional
   LRU aging clock, zero new constants, pre-quantified as a small
   correction (2.0-8.4% of A1 clock aging occurs below occupancy
   0.7, because the trap itself pins KV near 0.88;
   out/headroom_aging_a1.csv). Negative: guard arms A2/A3/A6/A7
   pass, screen arms A1/A4/A5 fail. A1 yields its first recovered
   draw (1/6, showing the measured restore-decay arc shape) but it
   fails the heal criteria (end KV 0.79, end running 82.9); 5/6
   drain and re-enter. The congested pin now sits inside the
   measured band (tails 0.97-1.00 N*B_r), and the trap relocates:
   at the A1 s1 tail, 84 pending-onboard entries hold 0.693 of the
   fleet pool as full-KV reservations queued behind the serial
   channel while 22 execute (out/heal_screen_headroom.csv,
   out/heal_headroom_runs/).

The screens jointly sharpen the failure to a re-entry trap: failing
arms drain to near-empty queues, then every completion re-admits a
full-context restore (model ext-share 1.0, h ~0.94, ~100k tok per
restore) where the measured congested state runs h 0.70-0.85 with
ext-hit 62-79%. Candidates 3 and 4 bound the trap's carrier - with
the channel widened it pins via elevated restore throughput; with
residency corrected it pins via reservation-holding backlog - so
the surviving suspect is restored volume per tier hit interacting
with full-KV reservation at admission (partial-context restores, or
tier-content staleness outside the two-clock window model), not
channel capacity, reservation timing, or residency semantics [R9].
This is presented as diagnosis of an open failure, not a result. A
gauge-semantics correction applies to any successor variant: the
inspected vLLM scheduler excludes WAITING_FOR_REMOTE_KVS sequences
from vllm:num_requests_running, so restore-in-flight entries must
not feed the tpot(R/N) term while still holding their reservations
(overlay-findings.md).

# 9. Operational implications

Each statement below restates a measured result; no controller or
admission policy was built or tested, and no threshold transfers
beyond the measured stack.

- Horizon rule. Benchmarks shorter than ~300 min overstate
  stability at boundary operating points: 2 of 8 surviving draws at
  8x-0.020 collapsed organically near min 240, past every 60-180
  min window [R3].
- Affinity is load-bearing for stability. In the one measured draw
  (n=1), a load-only router config (queue and kv-utilization
  scorers, no affinity signal) ran warm at h 0.53 vs 0.94 and
  collapsed unconditionally after the surge with no recovery phase
  [R14]. Changes that degrade affinity are stability changes, not
  latency changes; the necessity claim rests on the size of the
  degradation and the absence of any recovery phase, not on a
  frequency.
- Router span is a blast-radius parameter. Every measured 16x
  collapse was fleet-total (5 collapses across days and configs);
  independent 8x shard routers contained every collapse inside the
  failing 8-pod bulkhead, sibling shards untouched in both
  concurrent mixed pairs [R10]. Sharding is a measured containment
  boundary.
- Drain-depth observables are early-warning candidates. Post-cancel
  fleet KV occupancy at t=115 separates fast relapse from survival
  in all 8 draws at 8x-0.020 and adds signal beyond rate over 21
  draws [R15]. kv115 is a mediating observable, not a universal
  law; its threshold moves with rate and N, and it does not predict
  the organic-late class.
- Tier sizing is a persistence decision, not only a hit-rate
  decision. At 8x-0.022, size 250 falls through congestion to cold
  collapse (the one 250 draw, n=1) while 375 and 500 never go cold
  in 8 draws; capacity sets regime persistence and restore
  bandwidth sets congested throughput [R11].
- Reproduction methodology. aiperf artifacts exist only after
  end-of-run export, and capacity reclaim destroys un-scaled fleets;
  the hard T-15 scale-down rule and the artifact-existence rule make
  absent runs auditable rather than silently missing [R12].

# 10. Limitations and future work

Scope. All results come from one stack: one model
(Qwen3-Coder-480B FP8), one corpus family, one EPP implementation,
GB200 TP4 fleets at N in {4, 8, 16}. No claim transfers to other
models, corpora, or hardware.

Single-draw points. The following rest on n=1 and are never the
sole support for a probability, threshold, or trend: both sides of
the 0.020 tier/no-offload matched pair [R5]; the tier-250
fall-through [R11]; 16x-0.034 [R6]; the approx-config 16x relapse
point [R10]; the load-only ablation [R14]; the 4x-0.011 300-min
falsifier horizon [R9]. The two collapse-threshold axes each rest
on one measured contrast pair [R2], and the B_r-ceiling falsifier
on two heal arcs [R4].

Confounding. kv115 and the 16x configuration are confounded at
n=21: every fast-relapse draw above the pooled threshold region is
also a 16x draw, so the fitted separatrix cannot separate a span
effect from a drain-depth effect at this sample size [R15].

Model gaps. The DES misses the organic-late onset class: its onsets
form a 135-205 min continuum where the measured onsets are bimodal
[R15]. The heal branch is the primary modeling front: four
candidate mechanisms are screened out, the failure is sharpened to
a re-entry trap, and the surviving suspect is restored volume per
tier hit interacting with full-KV reservation at admission [R9].
The serial restore channel remains a documented deficiency whose
ceiling reading is falsified by measurement [R4].

Statistics that would tighten with hardware: 16x-0.034 (n=1) and
0.037 (n=2), tier-375 (n=2) with realized-rate covariates, and the
8x-0.022 organic-vs-fast class split; none block the present
claims. The tier boot envelope question stands: confirming the RAM
accounting and whether a ~600 tier boots, before any larger-tier
experiment [R11]. Five related-work full-text reads remain owed
before submission (related-work-sweep.md).
