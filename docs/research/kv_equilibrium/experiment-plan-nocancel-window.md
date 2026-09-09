# Experiment plan: no-cancellation surge validation (window 2026-08-27, 32 GPUs)

Objective: hardware validation of the no-cancellation flash-crowd
protocol screened in DES (nocancel_surge_sweep.py, 2026-08-27). The
cancellation protocol remains the paper's hysteresis identification
instrument; this arm covers realism (no operator removes the surge
population) and removes the cancellation caveat from Section 9's
persistent-surge discussion.

## DES basis (deployed-router DES, N=8, untiered, 300 min)

- Controlling coordinate is injected cohort size (rate x duration in
  sessions), not the rate ratio; matched-cohort cells at 1/5/10/20-min
  injections give near-identical verdicts.
- Base 0.022 is unusable in-model for attribution: the no-surge
  control goes cold organically 3/10 (+1 congested) at 300 min (known
  DES leftward placement bias).
- Base 0.017 (no-surge control warm 10/10): cohort ~20 absorbed
  10/10, ~32 cold 1/10, ~49 cold 5/10, ~67+ cold 10/10.
- Boundary-cohort recovered seeds drain fully (wait -> 0): the same
  finite work is servable; collapse is basin selection, not overload.
- Hardware margin: the DES sits left of measurement (full-KV
  reservation at admission), so the headline run uses cohort ~132 =
  2x the DES 50 percent point.

## Instrument: no-cancel surge via aiperf session cap

The cancel protocol's caveat comes from the surge generator killing
its session population at `duration` end. The no-cancel variant uses
the aiperf profiling-phase `sessions` cap instead:

- `SessionCountStopCondition.can_start_new_session()` blocks NEW
  sessions once `sessions` are started, while `can_send_any_turn()`
  keeps issuing turns of already-started sessions
  (aiperf src/aiperf/timing/phase/stop_conditions.py:152-193).
- Surge config: `sessionArrival.rate` sets the injection flux, the
  `sessions` cap sets the cohort; expected injection window =
  sessions/rate. A late `duration` backstop (13800 s = 230 min,
  ending at base t ~ 292 min) forces export if the cohort never
  drains (collapse case); in the recovery case the job exits at
  cohort drain, well before the backstop. aiperf exports artifacts
  only at job end, so the backstop protects data, and any cohort
  truncation it causes lands in the last ~3 min of the 270-295
  verdict window.
- SMOKE GATE before the first real run: 3-session no-cancel job must
  show (a) arrivals stop at the cap despite rate x duration >> cap,
  (b) the job serves all turns of the started sessions and exits
  before the duration backstop, (c) artifacts export.

## Fleet

CAPACITY CORRECTION (user, 19:10 PDT): the window is 32 NODES (128
GPUs), not 32 GPUs. Four fleets run concurrently (28 nodes):
shard-a 8x noofl, shard-b 8x noofl, tier-b 8x cpu-offload (size 500),
tier-a 4x cpu-offload. ns16 (16 nodes) stays down (would exceed the
allocation alongside the others). Both shard EPPs mount
no-offloading-tp4-epp-precise-prefix-cache (verified 2026-08-27);
tier EPPs mount cpu-offloading-tp4-epp (same precise family, A1
confound note). bench-assets ROX PVCs Bound in all four.

All runs: 062126 base corpus, 061526 surge corpus, salted
(cacheBust first_turn_prefix), gap cap 10.5 s, base duration 18000 s
(300 min), EPP :9090 scraped, realized rates reported from the
phase-end session-accounting log line.

## Run matrix (priority order)

| Run | Base | Surge (t+62 min) | Cohort | Prediction / verdict criterion |
|-----|------|------------------|--------|--------------------------------|
| NC-S smoke | none | rate 0.2, sessions 3, dur 3600 s | 3 | instrument gate (a)-(c) above |
| NC-A headline | 0.017 | rate 0.22, sessions 132 | ~132 | collapse: h < 0.15 and wait growing at 270-295 min |
| NC-B control | 0.017 | none | 0 | warm: h > 0.9, wait ~ 0 throughout; closes organic-collapse attribution |
| NC-C replicate | 0.017 | rate 0.22, sessions 132 | ~132 | NC-A n=2 |
| NC-D boundary | 0.017 | rate 0.11, sessions 66 | ~66 | DES-certain cohort with no hardware margin; measures the hardware-vs-DES boundary offset (recovery here + collapse at 132 brackets it) |
| NC-E duration-insensitivity (optional) | 0.017 | rate 1.10, sessions 132 (~2 min injection) | ~132 | same verdict as NC-A = injection-duration insensitivity on hardware; the Little's-law flash-crowd framing (concurrent population ~2x within ~2 min) |

Base concurrency reference: ~0.017 sps x ~22-40 min session lifetime
= ~22-41 concurrent sessions; cohort 132 is a ~3-6x population step,
cohort 66 is ~1.6-3x.

Parallel-fleet additions (post capacity correction; all bases 0.017 x
300 min unless noted, surge at t+62):

| Fleet | Slot | Surge | Purpose |
|-------|------|-------|---------|
| shard-b | sb1 | 0.22 c132 no-cancel | NC-A draw n+1 (cross-fleet) |
| shard-b | sb2 | 0.11 c66 no-cancel | boundary draw n+1 |
| shard-b | sb3 | 0.33 c198 no-cancel | margin point between 132 and 264 |
| shard-b | sb4 | 0.22 c132 no-cancel | NC-A draw n+2 |
| tier-b | tb1 | 0.22 c132 no-cancel | TIER PAIR vs NC-A (user request). Measured-precedent prediction: recovery or restore-bound congestion, not cold (B2/A1 under cancellation). DES on record predicts 7/10 cold 3/10 congested (tier side documented pessimistic) - discriminator |
| tier-b | tb2 | none | tier no-surge control |
| tier-b | tb3 | 0.22 c132 no-cancel | tier pair replicate |
| tier-b | tb4 | 0.44 c264 no-cancel | tier robustness probe |
| tier-a | ta1/ta2 | base 0.011, surge 0.125 x 2700 s CANCELLED | B2a 300-min repeat x2 (queued restore-model falsifier: DES predicts end wait 75-142; wait ~0 falsifies DES at 4x) |

Slot cost ~5.5 h. Slot-start guard in every fleet driver: no new slot
after 2026-08-28 16:55 PDT, so the last export lands before the
22:45 PDT scale-down.

## Schedule and safety

- t15-scaledown CronJobs exist in all five namespaces (armed 08-15,
  schedule stale). Re-armed at window start to a conservative
  backstop (2026-08-29 19:00 UTC); MUST be tightened to
  reclaim-minus-15-min as soon as the reclaim deadline is known.
- Driver script (nohup, detached; survives session end) chains the
  runs and fires each surge at base t+62 min with `-r false`.
- Export margin rule: no data exists until export completes; the
  duration backstop on surge jobs and the 300-min base duration keep
  every export inside the window.

## Caveats carried into analysis

- Realized base rate varies between draws (b1c drew 2.3 req/s at
  0.017); report realized rates alongside nominal.
- The 270-295 min verdict window overlaps the surge-job duration
  backstop by ~3 min in the collapse case (starved-session removal at
  t ~ 292 min; no measurable effect expected, note in the run log).
- NC-D recovery + NC-A collapse would bracket the hardware boundary
  in (66, 132) sessions at 0.017; a single NC-D collapse instead
  lower-bounds it below 66 and strengthens the realism claim.
