# Band experiment plan: two-generator bursts and session arrivals

Status as of 2026-08-07. Companion to experiment-plan-closed-loop.md (the
E-series). This file covers the open-loop hysteresis/band track after the
Aug 3-7 runs and lists the next experiments in value order.

## 1. What the Aug 3-7 runs established

All runs: 8xTP4 fleet, no-offload, weka 256k corpus, gap cap 10.5 s.
Analysis: fleet aggregates over the 8 pod endpoints, service endpoint
excluded; h = prompt_tokens_cached / prompt_tokens.

### 1a. Two-generator burst at root 1.0 qps: hysteresis, replicated (n=2)

Design: base generator, request-metered Poisson root 1.0 qps, 5400 s.
At t ~ +47 min, an identical second generator runs for 900 s, then
terminates (grace 120 s). Post-burst, the base generator continues alone
at the identical offered process as pre-burst.

    run pair                     warm (pre-burst)      collapsed (post-burst, ~25-30 min observed)
    baseline-kvm-qps10-0807      h 93-96%, TTFT p50    h 4-9%, TTFT p50 60-190 s, wait 140-380,
                                 0.5-0.7 s, KV 20-30%  KV pinned 93-94%, uncached ~120k tok/s
    baseline-kvm-qps10-0806      same                  same (h 5-8%, TTFT p50 68-166 s)

Tip occurs DURING the burst, 6-9 min after burst start, at KV ~92-93%
(0807: h 81% at KV 69%, then h 19% at KV 92.9%), matching the
rateseries10 tip point and the free-pool retention mechanism (T crosses
the gap cap when running residency crowds out the pool).

Why this improves on rateseries10 as the hysteresis exhibit:

- The perturbation is an exogenous, independent process (a second tenant
  arriving and leaving), not a rate step inside one generator. The
  original worry about rate-series bursts - the surge minting new
  sessions whose subagent fan-out is not metered - no longer contaminates
  the comparison, because pre-burst and post-burst load come from the
  SAME generator with the same session population dynamics.
- Within one run: identical offered load before and after, h 95% vs 5-8%,
  TTFT p50 0.6 s vs 60-190 s, no recovery in ~25-30 min. First-turn
  fraction stays <= 14% post-collapse (vs 44% in the qps3 probe), so the
  substitution amplification is bounded, though not zero (request-metered
  mode still holds root rate by substitution).
- Replicated on consecutive days.

### 1b. Root 0.9 qps burst: absorbed, full recovery

baseline-qps09-0806 + burst: burst 600 s at t ~ +32 min. KV peaks 63%,
h dips to 87.8%, recovers to 98% within ~4 min of burst end, TTFT p50
never exceeds 0.76 s. The fleet absorbed a doubled offered load for
10 min without tipping.

CONFOUNDS - the 0.9 vs 1.0 contrast is NOT yet a clean threshold
statement:

1. Burst duration differs: 600 s (qps09) vs 900 s (qps10). At burst end
   the qps09 KV trajectory was still rising (36 -> 51 -> 63% per 3-min
   window). A 900 s burst at 0.9 might still have tipped. The pair
   currently brackets perturbation ENERGY (rate x duration), not rate.
2. The burst generators are unsalted (no cacheBust in the qps09/qps10
   configs): the burst samples the same 500 traces as the base, so its
   first turns can hit base-generator prefixes. The burst is warmer than
   a real user surge; measured tip thresholds are optimistic.
3. Run-tag naming implies possibly different EPP/scorer configs across
   pairs (baseline-kvm-qps10 vs baseline-qps09 vs token-aware-*). Router
   config per run is not recorded in the report dirs. Must be confirmed
   and recorded going forward (the closed-loop plan already requires
   this).

### 1c. Session-arrival mode (sps0086): instrument validated, load too low

Two overlapping runs at lambda_s = 0.0086 sessions/s (Poisson, salted via
cacheBust first_turn_prefix, agentic_replay timing). Full analysis in
llm-d guides/subslicing/aiperf/report-sps0086-overlap.md: arrival process
passes KS/dispersion/autocorrelation tests including superposition during
the overlap; accounting clean (0 rejections); no degradation.

Diagnosis: realized load, not mode failure. Solo realized 0.77-0.93
completed req/s (window truncation cuts ~174 req/session to ~100);
overlap total 1.72 req/s; KV peak 23%. The warm ceiling is 2.7-2.9 req/s
and collapse runs sit at ~4+ req/s offered. The overlap tested a point
far below the band, and the surge shape is also weak: a fresh
session-arrival generator ramps over a session lifetime (~20 min), so a
short overlap adds far less instantaneous load than a request-metered
burst. The overlap report's "session-open rate is the discriminating
variable" conclusion is mechanistically supported by the rateseries
comparison, but the overlap itself was not a load-matched test of it.

## 2. Next experiments, in value order

### B1. Session-arrival band pair (the definitive experiment; ~10 h)

The band claim in fully exogenous units, with zero generator feedback:
no request-rate pinning, no substitution, salted replays, validated
Poisson arrivals. Design:

- Base: lambda_s tuned so realized total is ~2.3 req/s (inside the
  predicted band [~1.6, ~2.9]). Start from 0.022 sps (0.0086 realized
  0.85 req/s; the overlap report's truncation-corrected scaling gives
  0.021-0.025 for 2.3). Duration 10800 s; ramp to N* ~ 29 in-system
  sessions takes ~20-30 min, leaving 2+ h of steady window.
- Surge: second job with lambda_s = 0.15 sps for 600 s (~90 cold session
  opens; rateseries10 collapse minted opens at 0.22/s). Session OPENS are
  the mechanism carrier - each open is a cold ~50k prefill - so the surge
  is specified in opens/s, not req/s.
- Arm 2 (control): identical surge on a base of lambda_s ~ 0.012
  (realized ~1.2 req/s, below the cold-branch capacity ~1.6).

Predictions: arm 1 tips and does NOT recover (base demand 2.3 > cold
capacity 1.6; waiting sessions accumulate - the honest open-loop
divergence); arm 2 tips or dips but RECOVERS (demand below cold
capacity). Same surge, two base rates, opposite outcomes = band
membership demonstrated with an instrument that has no endogenous
amplification. This is the publication centerpiece; the qps10 pairs
become the motivating exhibit and B1 the controlled one.

Tuning gate: read the phase-end "Session arrivals:" accounting and the
realized req/s after the first base run; adjust lambda_s before arm 2.

### B2. Tier mitigation under the same burst (measure -> model -> mitigate; ~4 h + stack switch)

Repeat the exact qps10 two-generator pattern on the CPU-offload stack
(and WEKA if cheap). Prediction from the fluid/DES models: the offload
tier deletes the absorbing equilibrium - the burst dips h but the fleet
recovers after the burst leaves. One run pair per tier. This is the
mitigation pillar for the OSDI framing and reuses a proven protocol.

### B3. Matched controls for the threshold statement (~4 h)

- qps09 burst rerun at 900 s (removes the duration confound).
- qps10 burst rerun with cacheBust salting on the burst generator
  (removes the warm-burst confound; expect tip at same or earlier time).
Optionally a 0.95 base point if both controls keep the 0.9/1.0 contrast.
Confirm EPP/scorer config parity with the 1.0 pair before running;
record scorer config in every run note from now on.

### B4. Post-collapse descending staircase in session units (~3 h)

After a B1 arm-1 collapse, terminate the base job and restart at
descending lambda_s (0.016, 0.012, 0.008 for ~25 min each): the lowest
lambda_s at which the fleet stays collapsed measures r_low in
sessions/s. Replaces the request-metered R3 staircase, which the
subagent-cascade shed failure showed is not interpretable.

### B5. Not needed / absorbed

- R1/R2 drain-and-ramp (request-metered): superseded by B1/B4; the
  request-metered generator's substitution behavior makes its shed and
  recovery phases uninterpretable (exp5/sec 8c findings).
- Further sps0086-rate replicates below the band: instrument is
  validated; no new information.

## 3. Closed-loop E-series disposition

The closed-loop plan retains value, re-prioritized:

- KEEP E2 (gap-cap sweep): still the only clean h = F(T) quantitative
  test; open-loop runs conflate retention with load growth. This is the
  model-calibration backbone and is not substituted by any band run.
- KEEP the conc staircase probe (20 -> 160 -> 20 in one run): the fluid
  model's discriminating prediction is that closed-loop arrivals suppress
  bistability. Demonstrating path-independence in closed loop on the same
  fleet where B1 shows open-loop hysteresis is the identification
  argument against "the hysteresis is a generator artifact".
- KEEP a trimmed E1 (conc {40, 80, 120, 160}): tpot(rho) interference
  calibration for the fluid/DES overlay figure.
- E4 (flush-recovery): optional; B1/B2 already exercise the recovery
  dynamics with a more realistic perturbation.
- E3 (tiers, closed loop): demoted; B2 answers the tier question in the
  regime that matters. Keep only if E2 shows tier-dependent F(T) shape.
- E5 (routing ablation), E6 (geometry), E7 (repeats): opportunistic.

Publication answer: closed-loop experiments are part of the
identification strategy, not optional extras - reviewers will ask
whether the hysteresis is manufactured by the load generator, and the
answer is the pair (closed-loop stable at matched throughput, open-loop
bistable with a validated exogenous arrival process). The full 43-hour
E-series is not required; E2 + staircase + trimmed E1 (~15 h) covers the
publication need.
