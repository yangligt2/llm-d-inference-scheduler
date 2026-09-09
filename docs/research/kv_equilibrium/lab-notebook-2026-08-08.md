# Lab notebook 2026-08-08: closed-loop E-series on precise-prefix-cache

Operator: Claude (autonomous session). Environment: experiment-env.md.
Plan being executed: experiment-plan-closed-loop.md as re-prioritized in
experiment-plan-band.md sec 3 (E2 + staircase + trimmed E1).

Standing conditions for every run today (record deviations per run):

- Fleet: no-offloading-tp4 x 8 (32 GPUs), EPP ConfigMap
  no-offloading-tp4-epp-precise-prefix-cache (KV-events token routing),
  fleet + EPP redeployed 2026-08-08 ~15:30 UTC.
- Corpus: cc-traces-weka-062126-256k (393 traces), entries 500 unless
  noted, maxContextLength 262000.
- Salted: cacheBust.target first_turn_prefix on ALL runs (new vs the
  July unsalted anchors; h is expected somewhat lower since cross-play
  prefix sharing is removed).
- Closed loop, request-level: profiling type concurrency, no timingMode
  (RateTiming concurrency_burst), duration 3600 s (smoke: 600 s), grace
  120 s, prefix caches reset before each run (-r true default).
- Analysis after each run: analyze_run_windows.py, steady window =
  minutes 10-60; report h_tok, KV%, wait, run, uncached tok/s, req/s,
  TTFT p50/p95, effective concurrency vs target.

## Today's planned sequence

| # | run name            | knob                        | duration | purpose |
|---|---------------------|-----------------------------|----------|---------|
| R0 | ppc-e0-smoke       | conc 40, cap 10.5           | 600 s    | E0 gate: harness, 8-endpoint scrape, salt visible, conc ~= target |
| R1 | ppc-e1-conc40      | conc 40, cap 10.5           | 3600 s   | E1 anchor + salted-vs-July delta |
| R2 | ppc-e1-conc100     | conc 100, cap 10.5          | 3600 s   | E1 mid; knee bracketing |
| R3 | ppc-e1-conc160     | conc 160, cap 10.5, entries 800 | 3600 s | E1 high; knee bracketing |
| R4 | ppc-e2-conc40-cap60 | conc 40, cap 60             | 3600 s   | E2: F(T) point |
| R5 | ppc-e2-conc40-cap300 | conc 40, cap 300           | 3600 s   | E2: F(T) point |
| R6 | (decided from R1-R5) | conc 80 insert, or cap uncapped, or repeat | 3600 s | adaptive |

Decision rules:

- R0 fails any gate check -> fix harness, rerun R0 before anything else.
- R2/R3: if tpot or TTFT shows the knee is already passed at conc 100,
  insert conc 80 as R6; if conc 160 still pre-knee, consider conc 220.
- R5: if effective concurrency sags below ~0.8x target (lanes parked in
  300 s gaps), note it as a starved run and extend entries, not conc.
- Each run: per-run entry below gets config, timestamps, headline
  numbers, anomalies, and the decision taken.

## Run log

### R0 ppc-e0-smoke - PASS (gate open)

- Config: bench-config-weka-e0-smoke.yaml (conc 40, cap 10.5, 600 s,
  salted). Profiling 16:30:53-16:40 UTC. 2009 records, 0 errors.
- Gate checks: 8 pod endpoints present in parquet (service excluded in
  analysis); avg client in-flight 38.7 vs target 40; salt active
  (cacheBust in config, run accepted); token totals plausible.
- Headline (2-min windows, post-warmup): h 92.5-95.3%, KV 33-38%,
  TTFT p50 0.65-0.88 s, req/s 2.7-3.4, no preemptions, wait 0.
- Salted h at conc40 ~= July unsalted 94.4%: cross-play inflation at
  conc40 is minor. TTFT slightly above July (0.54 s) - different EPP
  config (precise-prefix-cache vs approx), not comparable.
- Decision: proceed to R1.

### R1 ppc-e1-conc40 - warm, stable (E1 anchor)

- Config: bench-config-weka-e1-conc40.yaml (conc 40, cap 10.5, 3600 s,
  salted). Profiling 17:04-18:04 UTC. Exit clean.
- Steady window (min 10-60, 3-min windows): h 91.1-95.0% (mean ~93.4%),
  TTFT p50 0.73-1.00 s, p95 2.0-5.7 s, req/s 2.8-4.1, wait 0-1,
  preemptions 0.
- Context-deepening drift across the hour: server running 44 -> 78,
  KV 33 -> 62%, uncached tok/s ~18k -> ~24k. The request-level closed
  loop holds ~40 client in-flight while per-request KV residency grows
  as lanes advance into deeper turns. Not a failure mode (h and TTFT
  flat); it means single-hour closed-loop cells are quasi-stationary,
  and cross-cell comparisons should use the same steady window.
- Anchor comparison: salted + precise-prefix-cache h ~93.4% vs July
  unsalted approx-routing 94.4% (30 min). Consistent; no red flags.
- Decision: proceed to R2 (conc 100) as planned.

### R2 ppc-e1-conc100 - COLLAPSED to a stable degraded equilibrium

- Config: bench-config-weka-e1-conc100.yaml (conc 100, cap 10.5, 3600 s,
  salted). Profiling 18:11-19:11 UTC. Exit clean, 8553 records.
- Trajectory (3-min windows): starts warm (h 89.1%, KV 67% at min 3),
  degrades monotonically as in-flight ramps with subagent fan-out and
  context depth: h 61% at min 12, 17% at min 18, then 3-20% for the
  rest of the hour. KV pins at 91.5-93.5%. TTFT p50 rises to 40-64 s.
  Completed req/s falls 6.2 -> 1.2-1.5, BELOW the conc40 run's ~3.2.
- Character of the degraded state: STATIONARY, not divergent. Waiting
  bounded at 44-72 (vs open-loop linear growth to thousands),
  preemptions 1-9 per window, first-turn share ~1% (no session
  substitution in closed loop). This is the closed-loop degraded
  equilibrium the fluid model predicts: self-throttling load, no
  runaway queue, but throughput below the warm branch at lower N.
- KEY MEASUREMENT - effective in-flight vs configured concurrency:
  client avg in-flight 147.5 at conc=100; 56.4 at conc=40 (R1). The
  concurrency credit meters main-turn lanes; subagent fan-out is
  unmetered on top (~1.45x multiplier on this corpus). All knee
  statements must use ACHIEVED in-flight, not the config value.
  Consistent with the July inference-perf knee at ~90-120 achieved
  in-flight: 56 healthy, 147 collapsed.
- tpot steady: conc40 p50 21.5 ms / p95 40.3 ms; conc100 p50 84.2 ms /
  p95 189.6 ms (rho_prefill near saturation, uncached ~105k tok/s).
- Decision: conc160 (R3) cancelled mid-run and cleaned - a second
  deep-collapse point is low information. Replaced with conc60 and
  conc80 to localize the knee between in-flight 56 and 147. E2 cap
  points follow. Warm-start-vs-cold-start conc100 (closed-loop path
  dependence, the model's discriminating prediction) queued as the
  next-day candidate.

### R3' ppc-e1-conc60 - warm 45 min, then TIPS in-run

- Config: bench-config-weka-e1-conc60.yaml (conc 60, cap 10.5, 3600 s,
  salted). Profiling 19:21-20:21 UTC. 12249 records, avg in-flight
  102.9 (1.7x config; grows through the run).
- Trajectory: h 91-95% for 42 min (KV climbing 44 -> 85%), tip at min
  45-48 (h 67 -> 35%, KV crosses 91%), h 8-19% by min 54-60, TTFT p50
  27-30 s at the end. Same KV ~91-93% tip point as conc100 and the
  open-loop runs.
- Reading: within-run load is not stationary - server running grows
  62 -> 168 over the hour because surviving lanes concentrate in long,
  deep-context traces (length-biased survival) and fan-out intensifies.
  Time-to-tip(N): conc100 ~15 min, conc60 ~45 min, conc40 no tip in
  60 min (KV reached 62%). The closed-loop "knee" is therefore
  duration-conditional; the stationary boundary in achieved-in-flight
  terms sits near ~70-100.
- tpot steady (pre+post tip mixed): p50 30.0 ms, p95 141.2 ms.
- Caveats for later cells: conc40 stability beyond 60 min is unverified
  (KV was still drifting up at cutoff); consider a 120-min conc40 run
  to establish stationarity before fitting h* = F(T) points.
- Decision: keep conc80 (in flight) for a third time-to-tip point,
  then E2 cap60 and cap300 at conc40 as planned.

### R4' ppc-e1-conc80 - gradual slide from min 15, degraded by min 36

- Config: bench-config-weka-e1-conc80.yaml (conc 80, cap 10.5, 3600 s,
  salted). Profiling 20:29-21:29 UTC. 9972 records, avg in-flight 123.7.
- Trajectory: KV crosses 89-90% at min 18; h erodes gradually
  85 -> 69 -> 49 -> 21% between min 15 and 36 (no sharp cliff), then
  fluctuates 12-31% with TTFT p50 13-33 s. Waiting bounded <= 46.
- The E1 closed-loop sweep (all cap 10.5, salted, precise routing):

      conc  in-flight  outcome              tip time  steady tpot p50
      40    56         warm through 60 min  none      21.5 ms
      60    103        warm 45 min, tips    ~45 min   30.0 ms (mixed)
      80    124        slides from min 15   ~20-30 m  50.0 ms (mixed)
      100   147        collapses            ~15 min   84.2 ms (mixed)

  Tip sharpness decreases as N grows toward the boundary from above:
  conc100 falls off a cliff, conc80 slides. All degraded states are
  stationary (bounded queue, no substitution).
- Decision: R5 = cap60 at conc40 (launched). R6 slot leaning cap300:
  R2 already demonstrates warm-phase unsustainability at N=100 (it
  passed through h 89% before collapsing), so the warm-start variant
  is redundant; the F(T) signal point is worth more. Confirm after R5.

### R5 ppc-e2-conc40-cap60 - warm; h unchanged vs cap 10.5 (F(T) control point)

- Config: bench-config-weka-e2-conc40-cap60.yaml (conc 40, cap 60,
  3600 s, salted). Profiling 21:37-22:37 UTC. 10051 records.
- Steady window: h 90.6-96.0% (mean ~93.8 vs 93.4 at cap 10.5), TTFT
  p50 0.6-1.1 s, wait 0-1, preemptions 0. tpot p50 17.4 ms.
- F(T) reading: at conc40 the measured retention window (free pool /
  write rate ~ 500 s) covers 60 s gaps entirely, so h does not move.
  This is the predicted flat segment of h = F(T), a control point.
- Load-axis side effect (record for the fit): raising the cap parks
  sessions longer, so effective in-flight DROPS (38.8 vs 56.4 at cap
  10.5) and KV residency drops (30-45% vs 33-62%). The cap is not a
  pure F knob at fixed load; each run must contribute its own measured
  (T, F, h) triple rather than assuming constant T across caps.
- Decision: R6 = cap300 (launched). Uncapped cell deferred to next
  session (needs >= 90 min duration and starvation monitoring per the
  plan).

### R6 ppc-e2-conc40-cap300 - warm, STARVED (effective conc 0.53x)

- Config: bench-config-weka-e2-conc40-cap300.yaml (conc 40, cap 300,
  3600 s, salted). Profiling 22:45-23:45 UTC. 6845 records.
- h 90.8-98.1% (mean ~94.2), TTFT p50 0.6-1.1 s, tpot p50 12.9 ms,
  KV 12-30%, avg in-flight 21.3 vs target 40 (0.53x): a starved run
  per the plan criterion - parked sessions leave credits undispatched.
- F(T) reading: still the flat segment, and genuinely so - measured T
  at this (lighter) load is ~900 s (free pool ~11M tok / write ~12k
  tok/s), above the 300 s cap. Valid pointwise (T, F, h) triple; the h
  drop should appear only when gaps exceed T, i.e. the uncapped cell.
- Decision: launch R7 uncapped (7200 s, entries 1000) as the overnight
  cell; expect further load lightening, watch for the h drop as the
  gap CDF tail overflows T.

### R7 ppc-e2-conc40-uncapped - h stays high; cap knob and T co-move

- Config: bench-config-weka-e2-conc40-uncapped.yaml (conc 40, no gap
  cap, 7200 s, entries 1000, salted). Profiling 23:53-01:53 UTC.
  7478 records.
- h 90.3-97.7% (mean ~93.7) across all 2 h. Severely starved as
  expected: avg in-flight 9.6 (0.24x target), req/s 0.4-2.0, KV 3-14%,
  tpot p50 10.0 ms (near-idle decode).
- KEY NEGATIVE RESULT for the E2 design: uncapping the gaps does NOT
  produce the h = F(T) falling segment, because the load lightens as
  sessions park, the free pool grows, and T stretches to ~2500 s -
  which then covers even the uncapped gap tail. The cap (F knob) and
  the retention window T are not independent in closed loop: T
  co-moves to defeat the sweep. All four cap cells {10.5, 60, 300,
  uncapped} landed on the flat segment (h ~93-94%) at T {~500, ~500,
  ~900, ~2500} s.
- Consequence: the falling segment of F(T) is reachable only where T
  shrinks to gap scale, i.e. near the collapse boundary (the conc60
  run crossed it dynamically at min 45 when KV hit ~90%). Pointwise
  steady measurement there is intrinsically unstable. The h* = F(T)
  quantitative validation should therefore lean on (a) the flat-
  segment cells (4 triples, all consistent), (b) the dynamic
  trajectories through the transition (conc60/80 tips, where h(t) and
  T(t) can be cross-plotted per 3-min window), and (c) the model/DES
  overlay - rather than more closed-loop cap cells.
- The ~6% miss at any T (h ceiling ~94%) is the cold first-turn +
  salt-marker share, not gap overflow; treat it as the F asymptote.

### R8 recovery-on-N-drop pair (phase A collapse -> phase B N=40, no reset)

- Design: ppc-rec-conc100 (conc 100, 1500 s, cold start) collapses the
  fleet; ppc-rec-conc40 (conc 40, 2700 s) launched with -r false
  3.5 min after phase A's job end (bench.sh run + kubectl wait handoff;
  fleet drains running/waiting in the gap but cache contents persist).
  Discriminating prediction: closed loop has a unique equilibrium per
  N, so phase B should return to the warm branch (h ~93%) despite
  starting from the degraded cache state; the open-loop qps10 pairs at
  constant offered rate did NOT recover.
- Phase A (02:03-02:28 UTC): replicates R2 almost exactly (h 88.7 ->
  16.8%, KV 93.5%, TTFT p50 21 s by min 24; per-window trajectory
  within ~2 pts of R2). conc100 collapse is now n=2 same-day.
- Phase B: profiling ~02:34-03:19 UTC. RECOVERY CONFIRMED, immediate:
  h 90.6% in the first 3-min window, 93-95% thereafter; TTFT p50
  0.74-0.96 s throughout; KV rebuilds 32 -> 56%; in-flight 52.5; tpot
  p50 20.6 ms. Per-window trajectory indistinguishable from R1's
  cold-start conc40 (first window 91.0% there).
- Verdict: closed loop shows NO path dependence at N=40 - the warm
  branch is re-entered immediately after a full collapse, while the
  open-loop qps10 pairs at constant offered rate stayed collapsed for
  25-30+ min. Loop discipline, not cache contents, determines whether
  the degraded state is absorbing. This completes the identification
  argument (generator-artifact objection) with same-fleet data.
- Caveats to state alongside the claim: (1) the 3.5-min handoff gap
  let the server drain running/waiting before phase B, so this tests
  equilibrium selection at N=40, not a no-gap concurrency step (aiperf
  has no in-run concurrency schedule); (2) cache-bust salts are
  per-benchmark-ID, so phase B could not reuse phase A's cache entries
  either way - the warm start is self-generated, which is exactly the
  point: at N=40 the fleet rebuilds warm in minutes; under open-loop
  pressure it cannot.

## Day summary (2026-08-08)

Seven runs, all clean, one cancelled by design (conc160). All under
EPP precise-prefix-cache, corpus 062126, salted, request-level closed
loop.

    run        knob            outcome
    R0 smoke   conc40 10 min   gate PASS
    R1         conc40 cap10.5  warm 60 min: h 93.4%, tpot 21.5 ms,
                               in-flight 56; KV drifts 33 -> 62%
    R2         conc100         collapses ~min 15; stationary degraded
                               state (h 3-20%, TTFT p50 40-64 s,
                               bounded queue); in-flight 147
    R3'        conc60          warm 45 min, tips; in-flight 103
    R4'        conc80          slides min 15-36; in-flight 124
    R5         conc40 cap60    warm, h 93.8% (F(T) flat, control)
    R6         conc40 cap300   warm, h 94.2%, starved (0.53x target)
    R7         conc40 uncapped launched, 120 min (overnight)

Scientific take-aways:

1. Closed-loop collapse boundary measured: warm at in-flight ~56,
   degraded at ~103+ (tip within the hour). Same KV ~90-93% tip
   threshold as all open-loop collapses - one mechanism across both
   loop disciplines.
2. Closed-loop degraded states are STATIONARY (bounded queue, no
   substitution, throughput self-throttles to ~1.4 req/s). Contrast
   with open-loop divergence (queue -> thousands) is the paper's
   loop-discipline figure, now measured on the same fleet same day.
3. Time-to-tip decreases in N (100: ~15 min, 80: ~20-30, 60: ~45,
   40: none in 60 min) and tip sharpness increases with N. Within-run
   load is quasi-stationary at best: lanes concentrate in long traces
   (length-biased survival), so KV residency ramps for ~45+ min.
4. tpot(load) calibration points: 12.9 / 17.4 / 21.5 / 30 / 50 / 84 ms
   p50 across the day's cells.
5. Subagent fan-out makes achieved in-flight ~1.4-1.5x configured
   concurrency at cap 10.5; the multiplier itself depends on the cap
   (38.8 at cap60, 21.3 at cap300) - always report achieved.
6. h = F(T) flat segment confirmed at conc40 for caps {10.5, 60, 300}
   (h ~93-94% throughout, T measured 500-900 s > cap). The signal
   point must come from the uncapped cell (R7) where the gap tail
   overflows T.

## Next-session queue (value order)

1. Analyze R7 (uncapped). If starved even at entries 1000, extend to
   entries 2000 rather than raising conc. [DONE - see R7 entry]
2. Recovery-on-N-drop test. [DONE - see R8 entry]
3. 120-min conc40 stationarity check. [DONE - see R9 entry]
4. Then switch to the B-series (experiment-plan-band.md): B1
   session-arrival band pair. [STARTED - see B1 entries]

### R9 ppc-e7-conc40-120min - conc40 is stationary-warm; drift SATURATES

- Config: bench-config-weka-e7-conc40-120min.yaml (conc 40, cap 10.5,
  7200 s, salted). Profiling 03:26-05:26 UTC. 25507 records, avg
  in-flight 73.0 over the full 2 h.
- KV climbs 37 -> 79% by min 65, then plateaus at 71-77% for the whole
  second hour; running plateaus ~75-90; h 88-93% in hour 2 (vs 93-95%
  in hour 1); TTFT p50 <= 1.13 s; preemptions 0-3/window.
- Reading: the length-biased deepening drift saturates at ~65 min. The
  conc40 stationary point (KV ~75%) is BELOW the ~90-93% tip
  threshold; conc60's stationary point lies beyond it (it tipped at
  min 45 while still ramping). 60-min cells understate steady load by
  ~30% at conc40 (in-flight 56 -> 73); future closed-loop cells that
  matter should run >= 90 min.
- This closes the closed-loop block. Boundary summary: stationary-warm
  at achieved in-flight ~73 (conc40), degraded at ~103+ (conc60+);
  unique equilibrium per N (R8); F(T) flat segment + co-movement (R7).

## B-series start (evening 2026-08-08 PDT): B1 arm 1

### B1a ppc-b1a-base + ppc-b1a-surge - IN FLIGHT

- Base: bench-config-weka-b1-base-sps022.yaml - session arrivals,
  lambda_s 0.022 sps Poisson, 10800 s, corpus 062126, salted,
  admission ceiling 1024. Launched ~05:35 UTC (lifecycle, cold start).
  Target realized load ~2.3 req/s (inside the predicted open-loop band
  [~1.6, ~2.9]).
- Surge: bench-config-weka-b1-surge-sps015.yaml - 0.15 sps x 600 s
  (~90 cold session opens at 0.15 opens/s, vs 0.22 opens/s minted by
  the rateseries collapse), corpus 061526 for clean attribution,
  launched with -r false at t ~ +77 min via scheduled overlay.
- Prediction (experiment-plan-band.md B1): tip during/after surge and
  NO recovery (base demand ~2.3 req/s > cold capacity ~1.6); waiting
  sessions accumulate - honest open-loop divergence with zero
  generator feedback. Arm 2 control (0.012 sps base, same surge,
  predict recovery) queued next.
- Decision rule if arm 1 does NOT tip: raise surge to 0.25 sps x 900 s
  before concluding; if it still does not tip, the band's lower edge
  in session units is above 0.022 sps and the base rate moves up.
- Surge 1 result: ran 06:57-07:07 UTC, 89 sessions admitted, 1401
  requests, ABSORBED - fleet sampled 1 min after surge end showed
  waiting 0 on all pods, KV 8-52%, running ~2-7/pod. No tip.
- Surge 2 (decision rule applied): ppc-b1a-surge2, 0.25 sps x 900 s
  (bench-config-weka-b1-surge-sps025.yaml, 061526 corpus, -r false),
  launched 07:09 UTC at base t ~ +92 min; ~70 min of base window
  remains after surge2 ends.

### B1a full-arc verdict: surge2 TIPS the fleet; base RECOVERS in < 5 min

- Base accounting: 240 sessions generated/admitted, 0 rejections,
  28366 records. Realized base rate 2.3-2.4 req/s at steady (min
  30-60) - the lambda_s = 0.022 calibration hit the target.
- Arc (5-min windows, base parquet, fleet-wide): base solo warm h
  93-95.6%; surge1 (min ~80-90) absorbed, h dip to 84.6, KV peak 65%;
  surge2 (min ~93-108) TIPS: h 6.9 -> 3.5%, KV 94%, waiting 165, TTFT
  p50 77 s, base completed rate 0.5 req/s. Within ONE window of surge2
  ending (min 110): h 90.2%, KV 43.7%, waiting 1, TTFT p50 0.74 s.
  Base then runs warm to the end (min 110-180: h 85-95%, req/s
  3.2-4.5 catch-up, KV drifting to 76%, TTFT p50 <= 1.0 s).
- PREDICTION FALSIFIED (no-recovery half): at realized 2.3-3.5 req/s,
  the session-coupled base recovered instantly after the perturbation
  ended. Mechanism: completion-coupled sessions cannot storm. During
  collapse, existing sessions stall and DEFER demand (0.5 req/s
  observed); on release, deferred turns resume serially, so the
  re-warm proceeds inside cold capacity as an orderly queue instead of
  a retry flood. Absorbing collapse evidently requires demand
  INELASTICITY (request-pinned arrivals with substitution - what the
  qps10 pairs and real users-with-retries provide), not just load
  above the band's lower edge. This is a paper-grade scoping result
  for the bistability claim: the band lives on the demand-elasticity
  axis as much as the load axis.
- Instrument caveats: (1) the surge generator CANCELS its entire
  session population on exit (real surge users would persist and
  continue conversations) - aiperf sessionArrival has no rate series
  (verified in src/aiperf/config/session_arrival.py), so a
  single-generator staged run cannot remove this; (2) despite ~8x
  cache turnover during the 15-min pin, the resumed base h was 90%+
  immediately - resumption re-prefills are absorbed within windows
  (first-miss share small vs ongoing turn traffic).

### B1a2 (running): 45-min surge - eviction-time hysteresis condition

- Design: base 0.022 sps 3 h (ppc-b1a2-base, launched ~08:55 UTC) +
  surge 0.25 sps x 2700 s at t ~ +62 min (ppc-b1a2-surge). A 45-min
  pin turns the cache over ~20x (all parked base prefixes evicted) and
  accumulates ~60 in-collapse base arrivals + ~40 stalled deep
  sessions whose catch-up is then COLD.
- Discriminates: (a) quick recovery again -> session-coupled demand at
  0.022 sps is unconditionally stable; hysteresis claim must be scoped
  to inelastic demand; (b) stalled/slow recovery -> session-mode
  absorbing state exists, with eviction time as the threshold
  mechanism (collapse duration > prefix-eviction time makes catch-up
  cold and self-sustaining).

### B1a2 verdict: RELAPSE INTO ABSORBING STATE - session-mode hysteresis measured

- Base accounting: realized ~1.6 req/s solo (min 0-55, h 92-97%) -
  lower than B1a's 2.3 (run-to-run variance in Poisson trace draws;
  note the arms are not load-matched, which STRENGTHENS the contrast:
  the weaker base failed to recover).
- Surge phase (min 60-105): full saturation - h 1-3%, KV 94%, waiting
  grows to 776, TTFT p50 to 313 s, base completions 0.21-0.34 req/s
  (deferral), surge admitted 696 sessions.
- Surge exit (min 105): grace cancels the surge population; waiting
  776 -> 0; min 110-125 the base RECOVERS to h 90-92%, TTFT p50
  0.8-1.1 s, while running catch-up at 3.3-4.8 req/s.
- RELAPSE (min 125-180): the catch-up load itself re-tips the fleet at
  KV ~88-90% (min ~130): h 90 -> 72 -> 53 -> 20 -> 3-12%, KV re-pins
  91-92%, waiting grows to 131 by min 175, TTFT p50 82 s. Second
  collapse is 100% base-sustained (no surge process exists after min
  105). Run ends at 180 min still collapsed with a growing queue.
- Mechanism, refined vs B1a: the 45-min pin (~20x cache turnover)
  evicted all parked base prefixes AND accumulated a deferred-demand
  reservoir (stalled deep sessions + ~60 in-collapse arrivals). The
  reservoir drains as a catch-up surge that exceeds the warm ceiling,
  re-tips, defers again - recover/relapse oscillation contracting into
  the absorbing state as the backlog compounds. B1a's 15-min reservoir
  fit inside capacity headroom; B1a2's did not.
- Paper framing: with a validated exogenous session-arrival process
  and zero generator feedback, the SAME base process is warm-stable
  for an hour, then permanently degraded after a transient exogenous
  overload whose population was fully removed. This is the hysteresis
  demonstration in the clean instrument. Threshold structure:
  perturbation duration vs prefix-eviction time (and reservoir size vs
  capacity headroom), not merely rate-above-band.
- Arm 2 control launched (ppc-b1b-base, 0.012 sps, 3 h + same 45-min
  0.25 sps surge at t ~ +62): predict recovery WITHOUT relapse
  (catch-up demand below cold capacity). Opposite outcomes at the two
  base rates bracket the band lower edge in session units.

### B1b verdict: PREDICTION CONFIRMED - recovery without relapse

- Base: 0.012 sps, realized ~1.4 req/s solo (min 0-55, h 88-96%).
  Surge: 653 sessions, 13:08-13:53 UTC.
- In-surge state is statistically the same as b1a2's (h 1.4-2.5%, KV
  94%, waiting to 675, TTFT p50 to 295 s, base deferred to 0.14
  req/s) - the perturbation saturates the fleet identically in both
  arms.
- Post-surge: h 95.3% ONE window after surge exit (min 110), waiting
  0 for the entire remaining 70 min, catch-up 2.0-3.2 req/s runs warm
  (KV <= 33%), decays to baseline by min 170. No relapse.
- THE PAIR: identical 45-min 0.25 sps perturbation, identical
  saturated state at perturbation end; base 0.022 sps relapses into a
  base-sustained absorbing collapse, base 0.012 sps recovers and
  stays warm. Band lower edge in exogenous session units is inside
  (0.012, 0.022) sps for eviction-scale perturbations on this fleet.
  Re-tip threshold in catch-up terms: B1b's 3.2 req/s absorbed vs
  b1a2's 3.3-4.8 re-tipped - consistent with the warm ceiling.
- Replication of the relapse arm launched (ppc-b1a2-rep-base + 45-min
  surge at t ~ +62), since the centerpiece is n=1 and realized rate
  varies between draws.

### ppc-b1a2-rep: relapse REPLICATED (n=2)

- Base realized ~1.9-2.3 req/s solo (h 91-96%). Surge (647 sessions,
  min 60-105): identical saturation (h 0.9-6%, waiting 745).
- Post-surge: single partial-recovery window (min 110: h 79.9%,
  catch-up 4.8 req/s), then immediate re-tip - h declines
  monotonically 43 -> 20 -> 10 -> 3.5% over 70 min, KV pinned 92-93%,
  waiting grows to 114 at run end. Stronger than the first
  observation (no 15-min warm interlude; this draw's reservoir was
  larger). Live 3-min samples in /tmp/b1a2rep-post-surge-samples.txt.

## B1 block summary (2026-08-09)

Instrument: exogenous Poisson session arrivals (validated), salted
replays, two-generator perturbation (surge population cancelled at
exit - documented caveat), EPP precise-prefix-cache, 8xTP4.

    arm         base sps (realized req/s)  surge          post-surge outcome
    b1a         0.022 (2.3-2.4)            0.15 x 600 s   absorbed, no tip
    b1a         same run                   0.25 x 900 s   TIP -> recovery < 5 min
    b1a2        0.022 (~1.6)               0.25 x 2700 s  recovery 15 min -> RELAPSE -> absorbing
    b1a2-rep    0.022 (~2.0)               0.25 x 2700 s  partial recovery 1 window -> RELAPSE -> absorbing
    b1b         0.012 (~1.4)               0.25 x 2700 s  clean recovery, no relapse
    b1c         0.017 (~2.3)               0.25 x 2700 s  RECOVERED - h 89-95% final 70 min, catch-up 3.3-4.9 req/s warm at KV 55-72%
    b1b-rep     0.012 (~1.1)               0.25 x 2700 s  RECOVERED - h 94.7% one window post-surge, wait 0 for final 70 min (control n=2 CONFIRMED)

Claims supported:

1. Hysteresis in the clean instrument (n=2): the same exogenous
   session process runs warm for an hour, then is permanently
   degraded after a transient overload whose population was removed.
2. Controls at 0.012 and 0.017 sps: identical perturbation, identical
   saturated state, clean recovery. Band lower edge in session units
   inside (0.017, 0.022) sps. Do NOT narrow further: realized req/s
   varies ~+-0.4 between draws at fixed lambda_s (b1a 2.3 vs b1a2 1.6
   at 0.022; b1c 2.3 at 0.017), which exceeds the increment.
3. Threshold structure: perturbation duration must exceed the
   prefix-eviction scale (900 s pin recovers, 2700 s pin relapses at
   0.022), AND the reservoir REFILL rate (arrival flux) must exceed
   the drain headroom. The discriminator is lambda_s, not the
   instantaneous catch-up rate: b1c sustained 4.9 req/s catch-up warm
   while b1a2 re-tipped at 4.8 - the difference is the 0.017 vs 0.022
   sps flux refilling the reservoir behind the drain. (This corrects
   the earlier "re-tip threshold ~3.2-3.3 req/s catch-up" phrasing.)
4. Demand-elasticity scoping: completion-coupled sessions defer
   rather than storm; the relapse is driven by reservoir drainage,
   not per-request retries. Inelastic (request-pinned) arrivals reach
   the absorbing state directly (qps10 pairs); elastic arrivals reach
   it via recover/relapse once the reservoir is large enough.

Remaining for the B-block: b1c edge point (in flight); B2 tier
mitigation (same protocol on CPU-offload stack) - BLOCKED on user
decision to redeploy the serving stack; optional second control
replicate; B3 request-mode matched controls demoted (B1 supersedes
the qps pairs as centerpiece).

## B2 tier arm (2026-08-09, second fleet in namespace yangligt)

User provisioned a SEPARATE 4-server fleet: cpu-offloading-tp4 x 4
replicas (16 GPUs) in namespace yangligt, vLLM args identical to the
no-offload stack plus --kv-offloading-backend=native
--kv-offloading-size=500, --kv-cache-dtype=fp8, block 256; EPP
ConfigMap cpu-offloading-tp4-epp. Runs in PARALLEL with igw-llm-d.

- Scaling: fleet is 0.5x B1's, so rates scale by 0.5 - base 0.011
  sps, surge 0.125 sps x 2700 s. The no-offload reference is the B1
  relapse pair under a linear-scaling assumption (capacity and pool
  are per-replica); CAVEAT: no same-geometry no-offload control
  exists. If B2 recovers where scaled-B1 relapsed, the clean follow-up
  is the same pair on this 4-replica fleet with offloading disabled.
- Infra fix (recorded): the user-created bench-assets-seed PVC
  provisioned its disk in us-central1-b (seed pod scheduled on a -b
  node) while GPU nodes are in us-central1-a; GCE PD clones must stay
  in the source zone, so the ROX bench-assets clone was infeasible.
  Deleted both PVCs, recreated the seed with nodeSelector
  topology.kubernetes.io/zone=us-central1-a (patched manifest at
  /tmp/bench-assets-seed-zonea.yaml), re-seeded 925M datasets + 16M
  tokenizer, recreated the clone. Consider adding the nodeSelector to
  bench-assets-seed.yaml permanently.
- cpuofl-b2a-base launched ~22:13 UTC (0.011 sps, 3 h, salted, cap
  10.5); surge fired t ~ +62 min (348 sessions, done 00:14 UTC).
  Prediction (fluid/DES): the offload tier absorbs the eviction-time
  perturbation - parked prefixes survive in the CPU tier, catch-up is
  warm (restored, not re-prefilled), no relapse. Tier attribution via
  external_prefix_cache_queries/hits in the server metrics.

## Capacity deadline + run audit (2026-08-10 00:20 UTC)

Both namespaces (12 nodes) are reclaimed at 02:00 UTC (19:00 PDT
2026-08-09). NO new jobs after this point. In-flight at audit time,
both projected to collect before the deadline:

- ppc-b1b-rep-base (igw-llm-d): collect ~00:55 UTC.
- cpuofl-b2a-base (yangligt): collect ~01:30-01:40 UTC (tight,
  lifecycle auto-collects on 60 s poll).

Audit of all 24 collected report sets (ppc-*, cpuofl-*): every one has
profile_export_aiperf.json + server_metrics_export.parquet and a log
ending in normal export. No run is invalidated by errors: the ERROR
lines are (a) per-request aiohttp TimeoutError during collapse phases
(8-13 per run out of thousands of requests - requests exceeding the
1200 s client timeout, which is the measured phenomenon, not an
instrument fault) and (b) one end-of-run "cancelled credits" cleanup
warning per collapse run. NOT-useful set: ppc-e1-conc160 only
(cancelled by design mid-run, no data collected, resources cleaned);
plus the first cpuofl-b2a-base attempt (never started - PVC zone
infeasibility, cleaned, no artifacts).

Post-capacity gap (for the record): no same-geometry no-offload
control for B2 exists (4-replica no-offload pair). If B2a recovers,
that control is the first run to schedule when capacity returns.

### B2a verdict: OFFLOAD TIER DELETES THE RELAPSE - mechanism tier-attributed

Full arc (5-min windows, 4 pod endpoints, service 10.0.47.15
excluded; ext_hit = external_prefix_cache_hits/queries):

- Base solo (min 0-60): warm, h 89-97%, realized 1.0-1.2 req/s (on 4
  replicas = scaled equivalent of 2.0-2.4 on 8, i.e. inside the B1
  relapse arms' realized range 1.6-2.4), KV 8-30%, ext_hit ~0-3%
  (tier idle).
- Surge (min 65-105): saturation deeper per-capacity than the B1
  relapse arms (waiting to 399 on the half fleet vs 745-776 on the
  full fleet; TTFT p50 to 347 s; h to 2.6%). Early surge (min 70-80):
  ext_hit 67-69% at 38-39M queries/window - HBM-evicted prefixes are
  being served from the CPU tier at scale. Late surge: even the CPU
  tier thrashes (ext_hit 1-2%) as the 348 cold surge sessions'
  footprint dominates.
- Post-surge: recovery in ONE window (h 87.5% at min 110, 96.6% at
  min 115, waiting 0 from min 115 to the end, catch-up 1.3-1.9
  req/s). MECHANISM SIGNATURE: ext_hit 13-43% through the catch-up
  window (min 110-130) - the deferred base sessions' prefixes are
  RESTORED from CPU, not re-prefilled - then decays to ~0-7% as the
  working set re-settles into HBM. No relapse at any point.
- Verdict: at the scaled relapse-arm operating point and under a
  per-capacity HARSHER perturbation, the CPU tier converts the B1a2
  relapse mechanism (eviction -> cold catch-up -> re-tip) into
  demotion -> warm restore -> drained reservoir. The absorbing state
  is deleted, and external_prefix_cache metrics attribute the
  recovery to the tier directly.
- Standing caveat: no same-geometry no-offload control (linear
  scaling assumption documented above); first run when capacity
  returns.

## Session wrap-up (2026-08-08 -> 2026-08-10, capacity released 02:00 UTC)

Three blocks completed on 2 fleets, 26 usable report sets, all
analyzed and logged above:

1. Closed-loop E-series (R0-R9): boundary at achieved in-flight
   ~73/~103; stationary degraded states; unique equilibrium per N
   (recovery-on-N-drop); F(T) flat segment + cap/T co-movement; 65-min
   stationarity time; tpot(load) calibration 10-84 ms.
2. B1 session-arrival band block: hysteresis pair n=2 per arm -
   relapse-to-absorbing at 0.022 sps vs clean recovery at 0.012 and
   0.017 sps under identical 45-min perturbations; band edge in
   (0.017, 0.022) sps; threshold = perturbation duration vs
   prefix-eviction time + arrival flux vs drain headroom;
   demand-elasticity scoping (deferral vs storm).
3. B2 tier arm: offload deletes the relapse, tier-attributed.

Measure -> model -> mitigate is now demonstrated end-to-end on real
hardware with a validated exogenous-arrival instrument.

Queue for next capacity window: (1) 4-replica no-offload control for
B2; (2) B2 relapse-search on offload (raise lambda_s until the offload
fleet relapses -> measures how far the tier moves the band edge); (3)
DES/fluid overlay fits vs the measured arcs (analysis only, no GPUs
needed - can start now).

## Model overlays DONE (2026-08-10, analysis only)

Full write-up: overlay-findings.md. Artifacts: extract_arcs.py ->
out/arcs/*.csv (18 runs); overlay_fixedpoint.py -> out/gb200_band.csv;
overlay_b1_dynamics.py -> out/overlay_b1_dynamics.png + summary CSV.

Headlines: (1) static fixed point matches the warm branch (h within
1-3 pts, T ranked correctly across six cells) but has NO cold
equilibrium at achieved rates - the measured absorbing state requires
dynamics; (2) adding measured tpot(N) interference + elastic session
demand (reservoir with surge cancellation) reproduces the full
measured trichotomy AND the tier deletion in one parameterization,
with quantitatively matching queue trajectories including the 0.022
arm's post-cancellation queue regrowth. Every constant independently
measured; limitations documented in the findings file.
