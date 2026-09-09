# Paper outline: metastable KV-cache equilibria in fleet-scale LLM serving

Venue-neutral systems-conference format, ~12-13 pages body plus
references. Claim IDs refer to paper/claims-map.md. Figure files
verified present in kv_equilibrium/out/ (ls 2026-08-25):
des_b1_overlay.png, des_band.png, des_trajectory.png, disruption.png,
fixed_point.png, hysteresis.png, overlay_b1_dynamics.png,
overlay_nseries.png, overlay_restore.png, overlay_tiercap.png,
phase_diagram.png, phase_diagram_open.png, separatrix_fit.png,
tpot_fit.png. Figures fixed_point.png, hysteresis.png,
phase_diagram.png, phase_diagram_open.png, des_band.png,
des_trajectory.png, disruption.png are model-generated illustrations
(dynamics.py, phase_diagram.py, des.py lineage); regenerate from
current model code before inclusion and label as model output, not
measurement. Framing is pure research throughout: mechanism,
measurement, model; no customer or vendor narrative anywhere.

## 1. Abstract (~250 words)

- Claims: compressed C01, C02, C10, C12 (hedged as one pair), C15,
  C22 (hedged n=1), C26.
- Figures: none.
- Content order: phenomenon (absorbing collapse with a probability
  band), the tier's regime transformation, the router-span
  dependence, the calibrated model with the emergent span shift, the
  documented heal-branch failure (one sentence - the paper reports
  its model's failures).
- Must NOT claim: universality beyond the measured stack (one model,
  one corpus family, GB200 TP4 fleets); any smoothed collapse
  probability; that the tier removes the failure; that scatter was
  directly observed.

## 2. Introduction (~1.25 pages)

- Claims: C01, C02, C06 (motivating statement), C10, C15, C22
  (headline preview with n), C25-C27 (model preview), contribution
  list mapping to sections.
- Figures: disruption.png or a measured-arc composite as Figure 1
  (a single collapse trajectory: h, TTFT, queue vs time); if
  disruption.png is model-generated, replace with a measured arc
  plot built from out/arcs/*.csv - do not open the paper with a
  model figure presented as data.
- Contribution bullets: (i) measured absorbing collapse + band +
  horizon dependence; (ii) drain-depth separatrix; (iii) third
  regime and tier size series; (iv) router-span dependence with
  ablations, EPP-side measurements, shard containment; (v)
  calibrated fluid+DES with deployed-router layer, emergent span
  shift, executed falsifiers, documented failures.
- Must NOT claim: novelty assertions that related-work items
  contradict (CacheFlow already names restore as a bottleneck - our
  claim is the persistent regime, C10); "first" claims for
  metastability in serving generally (Bronson/Huang own the class);
  any mechanism statement for span dependence stronger than C23's
  elimination framing.

## 3. Background and related work (~1 page)

- Claims: none new; differentiation paragraphs positioning C01+C02,
  C10, C15 against prior work.
- Source: related-work-sweep.md (2026-08-25 refresh) +
  related-work.bib + threat-matrix.md.
- Structure: (a) metastable failures class (Bronson HotOS'21, Huang
  OSDI'22, farahbakhsh2025modeling, arXiv:2606.00942) - they
  establish the class and prediction agenda; we exhibit a new
  sustaining mechanism (hit-rate-dependent KV write amplification)
  with a calibrated measured boundary. (b) CITE-DIFF paragraph for
  van Rooyen arXiv:2606.24861 [vanrooyen2026collapse] - explicit
  differentiation required: same fold/spinodal/hysteresis
  mathematics, different physical feedback (uncertified-output/retry
  amplification vs full-context re-prefill); no cache state
  variable, no (capacity, load) boundary, no workload calibration,
  no serving-system validation there. (c) LLM queueing stability
  (arXiv:2605.04595, dai2025throughput, dong2026flow):
  memory-as-constraint with cache-independent service rates; with
  hit-rate feedback the service rate is state-dependent and the
  stability region acquires a bistable band. (d) Cache-aware routing
  (DualMap, Continuum, CacheScout): they engineer the affinity/load
  trade-off; we show it has a stability dimension (C22, C15). (e)
  Tiered KV (Mooncake FAST'25 + ToS version, CacheFlow, Kareto):
  restore-bandwidth optimization and tier sizing exist; the
  congested regime bounded by restore bandwidth with capacity-set
  persistence (C10, C13) is unclaimed. (f) Classical cache theory
  (Che 2002, Fricker/Robert/Roberts) for the characteristic-time
  frame. (g) Motivation base: yuan2026agentic thrashing warning,
  ranganathan2025incidents, nixon2026yearserving - observed, never
  modeled.
- Figures: none.
- Must NOT claim: verdicts beyond the sweep's provisional ones;
  content from the five full-text reads still owed (arXiv:2606.15555
  mandatory, FailureAtlas retry-storm section, 2608.13573 caching
  chapters, 2605.26297 thrashing passage, 2606.24861) - those reads
  gate submission; the Semantic Scholar forward-citation chase is a
  documented residual gap.

## 4. Measurement methodology (~1.25 pages)

- Claims: C33, C34, C35; instrument-validation facts from
  experiment-env.md (aiperf concurrency credit ~1.45x in-flight,
  cacheBust salting, h from prompt_tokens_cached counter diffs,
  pod-endpoint-only aggregation, windowed analyzer wall-clock
  alignment).
- Content: stack description (8/16/4-replica TP4 GB200 fleets,
  Qwen3-Coder-480B FP8, vLLM block 256, EPP configs as first-class
  factors); trace corpus (062126, 68266 requests, mean 174
  req/trace, gap cap 10.5 s = p90); protocol (reset, base load,
  eviction-scale surge overlay, 150-300-min horizons); open-loop
  session arrivals vs closed-loop credit modes and why
  request-metered rate is excluded (C33); comparability rules - the
  five recorded factors, the July/pre-08-08 series quarantined from
  fits (C34); draw-variance guard: realized req/s +-0.4 at fixed
  lambda_s, hence outcome tallies over draws rather than single-run
  dose-response (C04, C34); artifact-existence rule (C35);
  65-min stationarity time for closed-loop states (C07 support).
- Figures: none (a protocol timeline diagram may be drawn fresh; no
  existing PNG covers it).
- Must NOT claim: comparability across router configs or unsalted
  runs; any number from the July/early-Aug reference series inside
  a fit; that server-side gauges equal client-side load (the
  vllm:num_requests_running gauge excludes WAITING_FOR_REMOTE_KVS -
  gauge-semantics note, C32).

## 5. Collapse phenomenology (no-offload) (~2 pages)

- Claims: C01 (absorbing state), C02 (band, three outcome classes),
  C03 (two threshold axes, hedged per claims-map), C04 (draw
  variance), C05 (horizon dependence, organic-late class), C06
  (hysteresis, recovery-on-N-drop), C07 (closed-loop
  self-stabilization boundary), C08 (separatrix fit), C09 (threshold
  mobility + organic-late non-prediction).
- Figures: separatrix_fit.png (verified); a band/tally figure and a
  measured multi-arc overlay built from out/arcs/*.csv (to be
  produced); hysteresis.png only as a model schematic in a later
  section - not here.
- Narrative order: single-draw anatomy (C01) -> outcome ledger
  across rates (C02, C04) -> horizon dependence and the two collapse
  classes (C05) -> irreversibility (C06) and the closed-loop
  contrast (C07) -> the drain-depth separatrix as the quantitative
  organizer (C08, C09).
- Target length: 2 pages incl. figures.
- Must NOT claim: a fitted continuous p(collapse|rate) curve
  (tallies only); that kv115 is causal or universal (mediating
  observable; kv115/N16 confounded at n=21); that the organic-late
  mechanism is explained (kv115 does not predict it); recovery
  prescriptions (deferred to Section 10).

## 6. The CPU-tier third regime and the size series (~1.25 pages)

- Claims: C10 (restore-bound congestion), C11 (band is a state
  outcome, not channel capacity), C12 (boundary full heal, one
  matched pair), C13 (capacity sets persistence; 250/375/500
  ledger), C14 (boot envelope).
- Figures: overlay_tiercap.png (verified; tier-capacity pair
  overlay); overlay_restore.png (verified; restore-model overlay -
  place here or in Section 8 depending on whether the model has been
  introduced; if used here, caption must mark model curves).
- Narrative: regime discriminators (pinned restore rate, linear
  queue divergence, high h, no cold collapse) -> throughput/latency
  comparison vs cold collapse -> heal arcs exceeding N*B_r (C11) ->
  the 0.020 matched pair (C12, hedged) -> size ledger and the
  fall-through at 250 (C13) -> envelope limits (C14).
- Target length: 1.25 pages.
- Must NOT claim: that the tier removes the failure (it transforms
  it, C10); a heal probability at 0.020 (n=1 per side); a proven
  375-vs-500 size effect ("suggested but unproven" in substance);
  B_r as a hard per-node ceiling (falsified, C29); anything about
  sizes above 500 (unbootable, C14).

## 7. Router-span dependence (~1.75 pages)

- Claims: C15 (probabilistic left-shift, tallies), C16 (early-onset,
  fleet-total), C17 (config independence, approx n=1), C18 (shard
  containment), C19 (load imbalance refuted), C20 (scatter
  signatures), C21 (coordinator unsaturated), C22 (affinity
  necessity, n=1), C23 (surviving mechanism reading), C24 (per-pod
  scale invariance).
- Figures: tpot_fit.png (verified; per-pod interference form, C24 -
  may alternatively live in Section 8's calibration table); a
  16x-vs-8x ladder tally figure and the staggered-cascade pin-count
  plot from out/perpod/*.csv (to be produced; no existing PNG covers
  findings 2-4 of per-pod-spread-findings.md).
- Narrative order (elimination structure): the reframed
  probabilistic result (C15, C16) -> config independence (C17) ->
  scale-invariant per-pod physics localizes the effect in the
  coordination layer (C24) -> candidate mechanisms and their
  measurements: load imbalance refuted (C19), coordinator saturation
  refuted (C21) -> affinity necessity ablation (C22) -> shard
  containment (C18) -> scatter signatures (C20) -> surviving reading
  + DES emergent reproduction forward-reference (C23).
- Target length: 1.75 pages.
- Must NOT claim: direct observation of session-to-pod scatter
  (client records carry no serving-pod identity); a deterministic
  span law (the reframe is probabilistic; 16x-0.034 is n=1); that
  coordinator saturation is refuted for all coordinators (measured
  for this EPP at these spans); sharding as a recommendation here
  (Section 10 owns implications).

## 8. Models: fluid and DES (~2 pages)

- Claims: C25 (construction + calibration provenance, constants
  table with the single fitted TIER_EFF declared), C26 (validation
  set incl. emergent fleet-size shift), C27 (reservation bias; shift
  and class structure, not placement), C28 (C_W retirement), C29
  (B_r ceiling falsified; serial channel a documented deficiency),
  C30 (heal-branch failure + executed falsifiers 4x-0.011, 375/650
  bracket, 16x edge points), C31 (three exclusions), C32 (re-entry
  trap, surviving suspect, open).
- Figures: overlay_b1_dynamics.png (verified; fluid overlay, b1
  arms), des_b1_overlay.png (verified; DES validation arms),
  overlay_nseries.png (verified; N-series DES overlay - the emergent
  shift figure), overlay_tiercap.png if not consumed by Section 6;
  optional model schematics fixed_point.png / hysteresis.png /
  phase_diagram.png (regenerate + label as model output).
- Structure: (a) model construction: fluid, then DES with the
  deployed-router layer (RouterSessionSim reads the shipped EPP
  config and plugin logic: sticky threshold 0.80, TTFT gate 18000 ms
  at 28888 tok/s peak prefill, token-load scoring, 300 s staleness
  reap; no coordinator term); (b) calibration table, all constants
  with sources, TIER_EFF = 0.67 flagged as the one fitted value;
  (c) validation: band, third-regime discriminators 5/5, tier-250
  direction, emergent N-shift with tallies; (d) known biases:
  reservation bias (C27); (e) falsifiers executed (C30 list),
  reported with outcomes regardless of direction; (f) documented
  failures: heal branch (C30), fluid branch selection at 8x
  cancellation; (g) exclusion screens (C31) and the re-entry-trap
  diagnosis with the surviving suspect (C32).
- Target length: 2 pages.
- Must NOT claim: absolute DES collapse probabilities as predictions
  (C27); any heal-branch capability (zero DES heals - the model
  section is honest about this by construction); the excluded
  mechanisms as explanations; the stale exclusion beyond the
  two-clock abstraction; the progressive negative as definitive;
  C_W or any coordinator-saturation term (retired, C28).

## 9. Operational implications (~0.75 page)

- Claims: derived restatements only - no new evidence. Horizon rule
  (benchmarks shorter than ~300 min overstate stability at boundary
  points, from C05); affinity is load-bearing for stability, so
  affinity-degrading changes are stability changes, not latency
  changes (C22, n=1 hedge repeated); router span is a blast-radius
  parameter and sharding is a measured containment boundary (C18);
  kv115-style drain-depth observables are candidate early-warning
  signals (C08, mediating-observable hedge); tier sizing is a
  persistence decision, not only a hit-rate decision (C13); the
  T-15/export methodology rules generalize to anyone reproducing
  these experiments (C35).
- Figures: none.
- Target length: 0.75 page.
- Must NOT claim: a deployable controller or admission policy (none
  was built or tested); thresholds transferred to other models,
  corpora, or hardware; SLO or cost framing; any vendor guidance -
  the section states measured consequences, research register only.

## 10. Limitations and future work (~0.5 page)

- Claims: none new; scope statements. Single stack (one model, one
  corpus family, one EPP implementation, GB200 TP4); single-draw
  points enumerated (claims-map single-draw register); kv115/N16
  confounding at n=21; DES missing the organic-late onset class
  (continuum 135-205 min vs measured bimodal onsets); the open heal
  branch with the surviving suspect (restored volume per tier hit)
  as the primary modeling front (C32); statistics that would
  tighten with hardware (16x-0.034, 0.037, tier-375, 0.022 class
  split - research-status question 4); tier envelope question
  (RAM accounting, ~600 boot); related-work full-text reads owed
  before submission.
- Figures: none.
- Target length: 0.5 page.
- Must NOT claim: that any listed limitation is resolved; future
  work phrased as commitments.

## Length budget (body ~12.5 pages)

    Abstract                 0.25
    Introduction             1.25
    Related work             1.0
    Methodology              1.25
    Phenomenology            2.0
    Tier regime              1.25
    Router span              1.75
    Models                   2.0
    Implications             0.75
    Limitations              0.5
    Figures/tables slack     0.5

## Figures to produce (not yet in out/)

    measured collapse-arc composite (Section 2/5)  from out/arcs/*.csv
    band tally figure (Section 5)                  from notebook ledgers
    16x/8x ladder tally + cascade pin-count plot   from out/perpod/*.csv
    protocol timeline (Section 4)                  new diagram
