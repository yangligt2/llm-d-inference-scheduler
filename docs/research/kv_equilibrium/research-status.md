# Research status: KV-cache equilibrium and metastable serving failures

Consolidated state as of 2026-08-25 (includes the 2026-08-15/16
32-host window: 19 protocol runs, zero losses; the 2026-08-17
model revision; the 2026-08-25 separatrix fit; and the 2026-08-25
heal-branch candidate screens). This is the single catch-up document: a fresh
session needs this file, session-handoff.md (navigation + pending
work), experiment-env.md (operations), and the lab notebooks. The
auto-memory file mirrors the highlights.

## Source pointers for the latest window and model revision

The run-by-run record of the 2026-08-15/16 window is
lab-notebook-2026-08-15.md; the model revision (C_W retirement,
emergent fleet-size shift, TIER_EFF recalibration, heal-branch
diagnosis) is overlay-findings.md, mechanism-revision section. Both
are folded into the numbered results below, which are canonical:
results 2, 3, 4, 6, 9, 10, 11 carry the window's revisions; results
13-15 state its new claims.

## Established results (evidence grade in brackets)

1. ABSORBING COLLAPSE, no-offload. After an eviction-scale surge
   (0.25 sps x 2700 s on 8xTP4), base 0.022 sps relapses into a cold
   absorbing state: h 1.6-3.0%, TTFT p50 to 240 s, queue growth
   ~1.1/min to wait 289, throughput 1.2-1.4 req/s, zero recovery over
   195 post-surge minutes. [n=3 (b1a2, b1a2-rep, ppc-lh-noofl), one
   300-min horizon; lab-notebook-2026-08-08 (B1 block), 08-11]
2. COLLAPSE-PROBABILITY BAND, 8x no-offload. Identical perturbation
   at four base rates, all draws: 0.012 recovers 2/2; 0.017 recovers
   4/4 (150-180-min horizons; grazing spread, post-surge KV 40-78%
   across draws); 0.020 is bimodal over 8 draws with three outcome
   classes - clean x3, organic-late collapse x2 (cold by ~min 240),
   fast relapse x3 (onset min ~130-150) - collapse 5/8 by 300 min;
   0.022 relapses 3/3. Hard-relapse edge in (0.020, 0.022). Threshold
   structure: perturbation duration vs prefix-eviction time (900 s
   pin recovers, 2700 s relapses at 0.022) AND arrival flux vs drain
   headroom (b1c sustained 4.9 req/s catch-up warm while b1a2
   re-tipped at 4.8; the discriminator is lambda_s, not the
   instantaneous catch-up rate). Realized req/s varies ~+-0.4 between
   draws at fixed lambda_s and does not order outcomes within the
   0.020 ledger (a fast relapse at realized 1.62 vs a clean draw at
   1.78). [notebooks 08-08..08-15]
3. HORIZON-DEPENDENT STABILITY. 8x-0.020 no-offload survives the
   perturbation but ORGANICALLY collapses at ~min 240 in 2 of 8
   draws (no new perturbation; deepening sessions walk KV into the
   pin; per-pod pinning is near-synchronous, 2/8 -> 8/8 within one
   5-min window). Visible only at 300 min; 60-180-min runs overstate
   stability. [n=2 of 8 draws; 08-12, 08-15 (S3)]
4. THIRD REGIME, tier fleets: restore-bound congestion. 8x tier-500
   at 0.022: h 70-85%, ext_hit 62-79% (most hits are CPU restores),
   fleet restore rate pinned at 150-192k tok/s = 0.81-1.04 of N*B_r,
   KV 93-94%, throughput ~2.2x and TTFT ~4x better than cold
   collapse, queue slowly diverging (~0.8/min over 195 min). The
   tier TRANSFORMS the failure there, does not delete it. The pinned
   band is a congested-STATE throughput outcome, not a channel
   capacity: the measured heal arcs sustain 5-min fleet restore
   rates of 235,284 tok/s (cpuofl-a4-375-lh, t=70) and 278,161 tok/s
   (cpuofl-500-bimod6, t=70) = 1.28-1.51x N*B_r, then run their
   post-cancel restore phase at 0.14-0.56 N*B_r with wait 0.3-7
   while KV drains from 0.83-0.86 at cancellation to 0.26-0.31. [n=4
   congested draws (a1, a1rep, lh-tier, bimod5) incl. two 300-min;
   08-10-pm, 08-11, 08-15]
5. TIER FULL HEAL AT THE BOUNDARY. 8x tier at 0.020: digests the
   surge through a bounded restore phase (ext_hit 42-73% for ~2 h,
   wait 1-9), restore share decays 64 -> 0%, KV drains to 5% -
   complete self-heal - while the same-day no-offload draw at the
   same point collapsed organically (result 3). The tier's strongest
   value statement. [n=1 each side, 300-min pair; 08-12]
6. FLEET-SIZE (ROUTER-SPAN) DEPENDENCE, quantified and
   probabilistic. At per-capacity-matched points the
   collapse-probability curve shifts left ~5-10% in rate and
   steepens with router span. 16x single-router ladder: 0.034
   recovers 1/1, 0.037 bimodal 1/2, 0.040 relapses 4/4 (one draw
   135-min truncated, one under the approx config) - per-8x-eq
   0.017 / 0.0185 / 0.020 - vs the 8x ladder 0.017 recover 4/4,
   0.020 collapse 5/8, 0.022 relapse 3/3. Every 16x collapse is
   early-onset (erosion underway by min ~125-155; no organic-late
   class) and fleet-total. 4x-0.011 tier is
   stable 3/3 incl. a 300-min draw (end wait 1.3). Per-pod physics
   is measured scale-invariant (per-pod tpot form, per-replica B_r),
   so the dependence lives in the coordination layer (result 10);
   the DES reproduces the shift emergently (result 9). [08-12,
   08-13, 08-15]
7. DEMAND ELASTICITY SCOPING. Completion-coupled session arrivals
   defer rather than storm; absorbing collapse requires either
   demand inelasticity (request-pinned generators) or a
   deferred-reservoir whose refill outpaces drain (results 1-2).
   Request-metered rate mode is a built-in retry storm
   (methodology finding). [07-31..08-09]
8. CLOSED-LOOP BLOCK. Boundary at achieved in-flight ~73 warm /
   ~103+ degraded; degraded states stationary; unique equilibrium
   per N (recovery-on-N-drop); F(T) flat segment with cap/T
   co-movement (falling segment unreachable statically); 65-min
   stationarity time; aiperf concurrency credit ~1.45x in-flight
   multiplier. [08-08/09]
9. MODELS. Fluid (session reservoir + per-pod tpot interference +
   contended restore channel; overlay_b1_dynamics.py) and DES
   (des_b1.py: watermark admission, two-clock LRU, per-node FCFS
   restore channel; RouterSessionSim carries the deployed EPP
   algorithm read from config and plugin code - prefix-affinity
   sticky threshold 0.80, TTFT load gate 18000 ms at
   peakPrefillThroughput 28888 tok/s, token-load scoring, 300 s
   in-flight staleness reap - with no coordinator term). Calibration
   all measured: P_TPT 17k tok/s/replica; pool 6486 x 256-tok
   blocks/replica; tpot = 10.8 ms + 2.56e-4 (R/N)^2 (PER-POD form -
   the fleet-R form is falsified by the saturated 4x windows);
   restore B_r 23k tok/s/replica effective, a congested-state
   throughput calibration (151.5 GB/s = 1.19e6 tok/s raw DMA link at
   ~2% duty; per-transfer overhead binds) - reading B_r as a hard
   per-node channel ceiling is falsified by the measured heal arcs
   (result 4: 1.28-1.51x N*B_r sustained), and the serial FCFS
   restore channel that encodes that ceiling stands as a documented
   deficiency of the model (the concurrent-restore replacement
   screens negative on the heal branch and is not merged;
   overlay-findings.md, 2026-08-25 subsection); KV/token 127 KB fp8;
   E[req/session] 118 realized (corpus 174 inflates demand ~40%).
   One fitted constant, declared: TIER_EFF = 0.67 (effective
   fraction of nominal tier capacity), calibrated to the measured
   cold-side ordering of the tier ledger - eff(250) = 0.42M tok/pod
   at or below the DES cold/congested transition, eff(375) = 0.63M
   at or above it (in-model transition spans (0.42, 0.63)M); the
   congested-state miss share independently implies an effective
   window below nominal. Validated: results 1-2 and the no-offload
   band; the third-regime discriminators 5/5 (restore channel
   pinned, linear queue divergence, h high, no cold collapse); the
   tier-250 fall-through in direction and persistence boundary; and
   the fleet-size shift EMERGENT from the deployed-router coupling
   at the 300-min horizon - DES p(collapse) 8x
   0.017/0.020/0.022 = 2/12, 11/12, 12/12 and 16x
   0.034/0.037/0.040 = 5/12, 12/12, 11/12, the 16x curve left of
   the 8x curve at matched per-capacity rate (0.42 vs 0.17 at the
   0.017-equivalent). Both DES curves sit left of the measured ones
   (the documented full-KV-at-admission reservation bias), so the
   model's quantitative claim is the shift and the outcome-class
   structure, not absolute placement. The C_W coordinator-saturation
   freeze is RETIRED: contradicted by the EPP measurements (result
   13) and unnecessary (no verdict changes without it at the
   300-min horizon). Documented failures, not tuned away: the heal
   branch - zero DES heals in 30 sweep runs at 8x-0.022 at any
   capacity vs 4 measured heals in 8 draws at sizes 375-500, the
   missed 0.020 tier full heal, and the falsified 4x-0.011 300-min
   prediction (wait 52-160 vs measured 1.3) - and fluid branch
   selection at 8x cancellation (exits to the warm branch at the
   critical balance). Heal-branch candidate screens (four
   negatives, 2026-08-25 subsection of overlay-findings.md):
   reservation timing (heal_variant_progressive.py, informative
   negative, do-not-merge), stale-content tier churn
   (heal_variant_stale.py, definitive exclusion within the two-clock
   abstraction), restore-channel serialization
   (heal_variant_serial.py, concurrent restore, negative - the
   re-entry trap survives), and occupancy-gated HBM eviction
   (heal_variant_headroom.py, allocation-pressure-only eviction,
   negative - the trap relocates into restore-backlog reservations:
   at the A1 s1 tail 84 pending-onboard entries hold 0.693 of the
   fleet pool behind the serial channel; the congested pin stays in
   the measured 0.81-1.04 N*B_r band and A1 produces its first
   recovered draw, 1/6, not a heal). Surviving suspect: the
   ~100k-token unconditional full-context restore per tier hit
   interacting with full-KV reservation at admission (open question
   2). [overlay-findings.md, all sections incl. the 2026-08-17
   mechanism revision and the 2026-08-25 heal-branch screens]

10. COORDINATION-LAYER MECHANISM: router-span coupling with shard
    containment. The 16x-0.040 relapse is CONFIG-INDEPENDENT: 3
    draws under precise-prefix-cache plus 1 under the approx
    baseline (no KV-event pipeline, no token-producer). Independent
    8x shard routers over the same pod type at matched per-capacity
    load: every shard collapse (4 across the window, incl. the
    load-only ablation) stayed inside its own 8-pod bulkhead, the
    sibling shard serving untouched in the concurrent mixed pairs
    (a2/b2, a3/b4); every 16x collapse (5 across days and configs)
    was fleet-total. Load imbalance is refuted as the mechanism
    (query-share CV is N-invariant in every phase); the 16x
    signatures are prefix scatter/duplication: warm per-pod h
    dispersion ~2x at 16x at equal fleet h, 0.15-0.20 pool excess KV
    plus ~1.7x per-capacity miss-write flux at the matched re-warm
    state, and a staggered per-pod pinning cascade (3/16 -> 11/16 ->
    14/16 -> 16/16 across four 5-min windows) vs the
    near-synchronous 8x organic pin. With coordinator resources
    measured unsaturated (result 13), the surviving mechanism
    reading is span coupling of the post-cancellation
    drain-vs-catch-up race: a collapse seeds locally and the shared
    load balancer spreads the cold catch-up flux onto warm pods,
    while sharding contains it - reproduced emergently by the DES
    (result 9). [08-12, 08-13, 08-15; per-pod-spread-findings.md]
11. TIER CAPACITY BINDS; the size ledger at 8x-0.022 is a bimodal
    band. Same-protocol draws: size 250 enters restore-bound
    congestion then falls THROUGH it to cold collapse (ext_hit ->
    1% as the working set outgrows the tier; 1/1); 375 heals 2/2
    (one hot draw, realized 2.02); 500 {4 congested, 2 healed} of 6.
    Refined mechanism: restore bandwidth sets congested throughput;
    tier capacity sets regime persistence. A mild size effect
    across 375-500 (2/2 vs 2/6 heals) is suggested but unproven,
    and realized rate does not order outcomes across the ledger.
    kv-offloading-size is RAM-backed at GB scale; 650 does not boot
    on these hosts (gcsfuse sidecar OOM; boot envelope ends in
    (500, 650)). [08-13, 08-15]
12. Methodology: aiperf artifacts exist ONLY after end-of-run export
    (a hung export = zero data on disk; observed once in ~40 runs
    through 08-13, zero in the 19-run 08-15/16 window); and capacity
    reclaim destroys un-scaled fleets - see the hard T-15
    scale-down rule in experiment-env.md.
13. COORDINATOR RESOURCES MEASURED UNSATURATED DURING RELAPSE. EPP
    metrics scraped on all 19 window runs: KV-event index admissions
    track demand with no plateau (16x peak 3.3k/s = exactly 2x the
    per-shard 1.0-1.6k/s), event-pool queue depth ~0 in every window
    incl. through three reproducing 16x relapses, EPP CPU 1.9 of 4
    uncontended cores (shards ~1.1), index lookups 0.4-0.9 ms,
    scheduler e2e ~0.1 ms, remote tokenization 230-273 ms/request
    uniformly across healthy and collapsing runs. The literal
    coordinator-saturation reading (the retired C_W term, result 9)
    is unsupported. [19 runs; 08-15]
14. AFFINITY NECESSITY MEASURED. A load-only EPP config (queue +
    kv-utilization scorers only, no affinity signal) at 8x-0.020:
    warm h 0.53 vs 0.94 under precise-prefix-cache, TTFT p50 2-4 s
    and wait 3-6 pre-surge, then unconditional absorbing collapse
    after the surge (cold by t=150, no recovery phase, end wait 215,
    TTFT p50 177 s). Routing affinity carries both the warm margin
    and any recovery at boundary points (the customer-escalation
    claim, directly measured). [n=1; 08-15 (S2)]
15. DRAIN-DEPTH COVARIATE. Post-cancel KV occupancy at t=115
    separates fast relapse from survival in all 8 draws at 8x-0.020
    (fast >= 0.73, non-fast <= 0.66; threshold ~0.7). The threshold
    moves with rate and N: 16x-0.034 survived kv 0.74; 16x-0.037-r2
    relapsed from 0.65. A mediating observable for the
    drain-vs-catch-up race, not a universal law. The quantitative
    fit (Firth logistic over 21 draws: kv115 adds signal beyond
    rate, LR p ~ 0.044, within-8x-0.020 permutation p = 0.018;
    p=0.5 threshold 0.79 / 0.69 / 0.63 at per-8x-eq rates 0.017 /
    0.020 / 0.022; kv115 orders collapse onset, rank corr -0.99)
    and its DES comparison are canonical in separatrix-findings.md.
    [8x-0.020 8/8 plus the 16x ladder points; 08-15;
    separatrix-findings.md]

## Data sufficiency and consolidation state (2026-08-17)

The measurement campaign is COMPLETE for the paper's claim set; the
remaining work is consolidation of the models and text, all
GPU-free. Evidence per claim family:

    8x band probability curve    0.012 x2, 0.017 x4 (0 collapse),
                                 0.020 x8 (5 collapse, 3 outcome
                                 classes), 0.022 x3 (3 collapse)
    16x ladder                   0.034 x1 (0), 0.037 x2 (1),
                                 0.040 x4 (4; 1 under approx config)
    Coordinator resources        EPP metrics on all 19 window runs;
                                 unsaturated during 3 relapses
    Routing ablations            approx x1 (relapse), load-only x1
                                 (warm-degraded + collapse)
    Shard containment            6 shard draws in the window (4
                                 collapses, each confined to its
                                 8-pod bulkhead; sibling untouched
                                 in the 2 concurrent mixed pairs
                                 a2/b2, a3/b4)
    Tier ledger (8x-0.022)       250 x1 cold, 375 x2 healed,
                                 500 x6 (2 healed; tally spans the
                                 08-10..08-16 windows)
    Model falsifiers             4x-0.011 300-min (stable), 375/650
                                 bracket (375 ran; 650 infra-bound),
                                 16x edge points
    Third regime / hysteresis /  unchanged from results 1-8,
    closed-loop / elasticity     evidence grades stand

Single-draw points (16x-0.034, approx-16x, tier-250) are reported
with their n. No further hardware is required for the core claims;
optional tightening targets are listed in question 4 below.

## Sharpest open questions, ranked (post-08-17 model revision)

1. RESOLVED (2026-08-17): the C_W freeze is retired and the
   fleet-size shift is EMERGENT in the DES from the deployed-router
   coupling at the 300-min horizon (no-freeze ladder: 16x-0.017-eq
   5/12 vs 8x-0.017 2/12; both curves left of measured by the
   documented reservation bias). des_b1.py and overlay-findings.md
   (mechanism-revision section) carry the details. TIER_EFF
   recalibrated 0.5 -> 0.67 on the cold-side ordering.
2. MODELING (primary open front): the heal branch. Zero DES heals
   at 8x-0.022 across 30 runs at any capacity vs 4/8 measured, plus
   the 4x 300-min stability miss. The 2026-08-25 candidate screens
   (overlay-findings.md, heal-branch subsection) exclude four
   suspects: reservation timing (progressive allocation -
   informative negative, manufactures a non-physical
   interference-locked congested state in no-offload guard arms,
   do-not-merge), stale-content tier churn (credit bracket null;
   definitive exclusion within the two-clock abstraction),
   restore-channel serialization (concurrent restore at the measured
   1.19e6 tok/s link with derived 4.232 s/transfer overhead - the
   failing arms still re-enter congestion), and occupancy-gated HBM
   eviction (allocation-pressure-only eviction replacing the
   unconditional LRU clock; zero new constants; pre-quantified as
   small - only 2.0-8.4% of A1 clock aging occurs below occupancy
   0.7 because the trap itself pins kv at ~0.88 - and screened
   negative: A1 5/6 re-enter after draining to wait 2.8, the one
   recovered draw shows the measured restore-decay arc shape but
   end_kv 0.79 and end running 82.9 disqualify a heal). The screens
   sharpen the failure mode to a RE-ENTRY TRAP: the failing DES arms
   (8x-0.022 tier-500, 4x-0.011 tier-500) drain to wait troughs of
   0-31 at t=115 (9 of 11 failing draws at or below 9)
   and re-enter congestion as every completion re-admits a
   FULL-CONTEXT restore (model ext_share 1.0, h ~0.94, ~100k
   tok/restore) where the measured congested state runs h 0.70-0.85
   with ext-hit 62-79%. Candidates 3 and 4 bound the trap's carrier:
   with the channel widened (reservations released fast) the state
   pins via elevated restore throughput; with residency corrected
   (channel kept) it pins via reservation-holding backlog (A1 s1
   tail: 84 pending-onboard entries holding 0.693 of the fleet pool
   while 22 execute at kv 0.882). Both routes fail on the same term:
   the residual gap is restored VOLUME per tier hit interacting with
   full-KV reservation at admission (partial-context restores /
   tier-content staleness outside the two-clock window model), not
   channel capacity, not reservation timing, not residency
   semantics. The gauge-semantics correction (vLLM
   vllm:num_requests_running excludes WAITING_FOR_REMOTE_KVS;
   restore-in-flight entries must not feed the tpot(R/N) term)
   belongs in any successor variant. Any fix must preserve the
   cold/congested boundary and the no-offload band. This is the one
   substantive modeling task left before the paper's model section
   is honest and complete.
3. RESOLVED (2026-08-25): separatrix-findings.md fits p(fast | kv115,
   rate) over the 21 standard-dose no-offload draws and runs the DES
   gauge comparison; result 15 carries the headline numbers. Residual
   limits stated there: the kv115/N16 confounding at n=21, and the
   DES's missing organic-late onset class (its onsets are a 135-205
   min continuum where the measured ones are bimodal).
4. Statistics to tighten if hardware idles again: 16x-0.034 (n=1)
   and 0.037 (n=2); tier 375 (n=2) with realized-rate covariates;
   8x-0.022 organic-vs-fast class split. None block the paper.
5. The kv-offloading-size units/envelope question: confirm the RAM
   accounting (620Gi request + tier size + gcsfuse cache vs 858Gi
   allocatable) and whether ~600 boots, before any future
   large-tier experiment.

## Artifact map

    experiment-env.md            operations runbook (fleets, bench.sh,
                                 gates, pitfalls) - keep current
    lab-notebook-2026-08-*.md    per-window runs, verdicts, decisions
                                 (08-08, 08-10-pm, 08-11, 08-12,
                                 08-13, 08-15)
    overlay-findings.md          model results, calibration, DES,
                                 refits, 2026-08-17 mechanism revision
    per-pod-spread-findings.md   per-endpoint spread analysis (result
                                 10 signatures)
    per_pod_spread.py            per-endpoint extraction + spread metrics
    overlay_nseries.py           N-series overlay driver (RouterSessionSim)
    separatrix-findings.md       drain-depth separatrix fit write-up
                                 (result 15; resolves question 3)
    separatrix_fit.py            separatrix fit + DES gauge sweep;
                                 outputs out/separatrix_draws.csv,
                                 out/separatrix_des.csv,
                                 out/separatrix_fit.png
    heal_variant_progressive.py  heal-branch candidate: progressive
                                 KV allocation (documented NEGATIVE,
                                 do-not-merge; open q2); outputs
                                 out/heal_screen_progressive.csv,
                                 out/heal_progressive_runs/
    adversarial_check_progressive.py  independent-ledger recheck of
                                 the progressive screen (A2 seeds)
    heal_variant_stale.py        heal-branch candidate: stale-content
                                 tier-churn credit (documented
                                 NEGATIVE, definitive within the
                                 two-clock abstraction; open q2);
                                 outputs out/heal_stale_instrument.csv,
                                 out/heal_screen_stale.csv,
                                 out/heal_stale_runs/
    heal_stale_a4tail.py /       stale-churn screen helpers (extra
    heal_stale_extra.py          baseline seeds, guard-arm baselines)
    heal_variant_serial.py       heal-branch candidate: concurrent
                                 restore onboarding replacing the
                                 serial FCFS channel (documented
                                 NEGATIVE for the heal branch; carries
                                 the gauge-semantics correction and
                                 the LINK_RATE/T_OVERHEAD derivation)
    heal_screen_serial_runner.py stall-safe screen runner; outputs
                                 out/heal_screen_serial.csv,
                                 out/heal_serial_runs/
    heal_variant_headroom.py     heal-branch candidate: occupancy-gated
                                 HBM eviction (allocation-pressure
                                 evict_clock replacing the unconditional
                                 LRU clock; documented NEGATIVE for the
                                 heal branch; retains the serial channel
                                 and the pending-onboard gauge split)
    heal_screen_headroom_runner.py  screen runner; outputs
                                 out/heal_screen_headroom.csv,
                                 out/heal_headroom_runs/
    investigate_headroom_aging.py  pre-implementation quantification of
                                 headroom-absorbed clock aging; output
                                 out/headroom_aging_a1.csv
    scratch_smean.py             S_MEAN_RESTORE calibration input for
                                 the T_OVERHEAD derivation
    paper/draft.md               full manuscript draft (abstract,
                                 sections 1-9, references; internal
                                 [R<n>]/[C<nn>] evidence markers;
                                 quantitative claims audited against
                                 this file, the claims map, and the
                                 named artifacts on 2026-08-25)
    paper/claims-map.md          claim register C01-C35 with evidence,
                                 strength class, and hedge rules
    paper/outline.md             section plan mapping claims to
                                 sections
    paper/section-*.md           superseded section drafts folded
                                 into draft.md
    experiment-plan-next-window.md  hardware queue for the next window
    experiment-plan-completion.md  pre-08-12 completion plan (partly done)
    namespace-request-4x-tier.md yangligt-4x blueprint (executed)
    namespace-request-shards.md  shard-namespace blueprint (executed)
    handoff-*.md                 executed GPU-free work orders
    out/arcs/*.csv               windowed measured arcs (extract_arcs.py;
                                 51 runs incl. the 08-15/16 window)
    out/perpod/*.csv             per-pod windows (15 runs) +
                                 spread_summary.csv
    out/overlay_nseries.png      N-series DES overlay (RouterSessionSim)
    out/overlay_tiercap.png      tier-capacity pair overlay
    out/des_b1_overlay.png       b1 validation-arm DES overlay
    out/overlay_b1_dynamics.png  fluid overlay, b1 arms
    out/overlay_restore.png      restore-model overlay
    out/tpot_fit.png / .csv      tpot interference fit (per-pod form)
    out/restore_boundary.csv     model boundary predictions (nominal
                                 capacities; capacity-indifference row
                                 superseded by the TIER_EFF refit)
    des_b1.py / overlay_*.py / tpot_fit.py / fluid_model.py / des.py
    reports (llm-d repo):        guides/subslicing/aiperf/reports/<run>/

## Standing operational facts

Namespace state: the 2026-08-13 capacity reclaim destroyed all five
then-existing namespaces including the shared igw-llm-d (not among
the 08-15/16 rebuilds - flag its loss to its owners before
rebuilding under that name). The 2026-08-15/16 window ran on five
namespaces rebuilt from the blueprints (yangligt-ns16, -shard-a/-b,
-tier-a/-b); all fleets scaled to 0 by 09:40 PDT 08-16 ahead of the
16:45 reclaim deadline. [UNVERIFIED: no source records whether
those five namespaces survived the 2026-08-16 reclaim; verify
cluster state before planning a window.] Rebuild path if needed:
namespace-request-4x-tier.md
(tier stack blueprint) and namespace-request-shards.md (no-offload
stack blueprint); every namespace needs the GCS bucket principalSet
IAM grant (user/admin action; a pod bounce may be needed after
propagation) and the zone-pinned bench-assets seed. Tier stacks
default --kv-offloading-size=500; the boot envelope ends in
(500, 650). Gate launches on readyReplicas polls, never `kubectl
rollout status` (stale progress-deadline poisons it). Surge chains
key on the base JOB's existence. HARD RULE: schedule the
unconditional T-15-min scale-down at window START
(experiment-env.md). aiperf data exists only after end-of-run
export - leave export margin before deadlines.
