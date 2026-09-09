# Lab notebook 2026-08-27: no-cancel surge window (32 GPUs)

Plan: experiment-plan-nocancel-window.md. HARD DEADLINE (user,
18:49 PDT): 2026-08-28 23:00 PDT. t15-scaledown CronJobs in all five
namespaces armed at 2026-08-29 05:45 UTC = 08-28 22:45 PDT
(reclaim-minus-15). Earlier interim backstop (08-29 19:00 UTC) is
superseded.

## Bring-up (16:25-16:45 PDT)

- Namespaces as left 08-16: EPPs up, vllm at 0. shard-a EPP mounts
  no-offloading-tp4-epp-precise-prefix-cache (verified via volumes);
  bench-assets ROX Bound.
- shard-a no-offloading-tp4-vllm scaled 0 -> 8; ready 8/8 in ~13 min.
- New configs (guides/subslicing/aiperf/): nc-base-sps017-300m (lh
  clone, rate 0.017), nc-surge-sps022-c132 / -sps011-c66 /
  -sps110-c132 (061526 corpus, `sessions` cohort cap, duration
  backstop 13800 s), nc-smoke (rate 0.2, sessions 3, 3600 s).
  Schema-validated offline against aiperf AIPerfConfig: profiling
  phase resolves duration+sessions+session_arrival together.
- No-cancel instrument: profiling-phase `sessions` cap;
  SessionCountStopCondition blocks new sessions at the cap while
  turns of started sessions continue
  (aiperf timing/phase/stop_conditions.py:152-193).
- Driver: runs-nocancel-0827.sh (nohup) chains NC-A..NC-E, surge at
  base t+62 via sleep 3720 subshell, scales fleet to 0 at end.

## Runs

- nc-smoke-0827 (16:45 PDT / 23:45 UTC): instrument gate PASSED.
  Accounting line: "generated=3 admitted=3 rejected_overload=0" - the
  arrival generator itself stops at the `sessions` cap (rate 0.2 x
  864 s of root sending would be ~170 unconstrained). Root sending
  complete at +864 s: "sent=190 ... sessions: sent=3" - turn chaining
  continued 14+ min after arrivals stopped. Tail: subagent (DAG
  child) branches kept dispatching after root completion (children
  exempt from the session cap = whole trees run to completion,
  correct no-cancel semantics); phase closed via the credits-returned
  timeout at the 3600 s duration backstop, full export, collected to
  reports/nc-smoke-0827/. CALIBRATION: a 3-session tree tail exceeds
  60 min; surge jobs in real runs will normally exit via their
  13800 s backstop, which is why the backstop exists (aiperf exports
  only at job end).
- OPERATIONAL INCIDENT (17:53 PDT): driver double-launch (first
  nohup's log redirect appeared to fail, relaunched, then found both
  alive). Both killed, orphaned aiperf-nc-a-base017 job + configmap
  deleted, single driver relaunched clean. Lesson: after a nohup
  launch whose log is missing, check pgrep BEFORE relaunching.
- Driver up (pid 71159, log reports/nocancel-driver-0827.log).
  NC-A base nc-a-base017 profiling from 00:58:49 UTC (17:58 PDT),
  rate 0.017, 18000 s. Surge nc-a-surge022c132 launched 18:58:23 PDT,
  profiling 02:00:11 UTC = base t+61.4 min, "target: 13800.0s
  duration, 132 sessions", rate 0.22. Sequence NC-A -> NC-B (control)
  -> NC-C -> NC-D; NC-E slot is PREEMPTED by the tier arm (below).

## Tier arm (user request 18:49 PDT): no-cancel surge with CPU offload

- Purpose: same no-cancel perturbation on the offload stack;
  expectation from cancellation-protocol history = tier transforms or
  deletes the collapse (B2 4x clean recovery; A1 8x-0.022
  restore-bound congestion; measured tier never cold except size
  250). DES prediction ON RECORD as discriminator (deployed-router
  DES, c_cpu 0.844M eff/pod, base 0.017, nocancel 0.22 x 600 s cohort
  ~135, 10 seeds): cold 7/10, congested 3/10 - the DES tier side is
  documented pessimistic (no heal branch; restore channel binds), so
  hardware recovery would confirm that bias, hardware cold would be a
  NEW finding (tier fails against no-cancel flash crowds).
  Rows in out/nocancel_surge_sweep.csv (c_cpu column added).
- Fleet: yangligt-tier-b 8x TP4 cpu-offload (kv-offloading-size 500),
  EPP ConfigMap cpu-offloading-tp4-epp (precise family). bench-assets
  Bound. Same 32-GPU footprint as shard-a, so it REPLACES NC-E.
- Supervisor tier-phase-0828.sh (nohup pid 84826, log
  reports/tier-phase-0828.log): waits for the NC-E launch line in the
  driver log (or driver exit, or force deadline 08-28 18:20 PDT),
  kills the driver, deletes NC-E remnants, scales shard-a 0 /
  tier-b 8, then runs tb-nc-base017 + tb-nc-surge022c132 (surge at
  t+62, -r false) and scales tier-b to 0. Horizon degrades by wall
  clock so export beats the 22:45 PDT backstop: 300 min if base
  starts by 16:55 PDT, else 240 min (by 18:10), else 180 min (by
  19:40), else abort. Insurance configs: nc-base-sps017-240m/-180m,
  nc-surge-sps022-c132-b240/-b180 (surge duration backstops 10200 /
  6600 s).
- Expected timeline: NC-E trigger ~15:15 PDT 08-28 -> tier-b ready
  ~15:55 -> 300-min horizon, export ~21:30 PDT.

## CAPACITY CORRECTION (user, 19:10 PDT): 32 NODES, not 32 GPUs

- 128 GPUs total; four fleets concurrent (28 nodes): shard-a (NC
  sequence untouched, NC-E restored - no preemption needed), shard-b
  8x noofl, tier-b 8x offload, tier-a 4x offload. ns16 stays down.
- tier-phase-0828.sh supervisor KILLED (wrong premise, never fired).
- New drivers (nohup; logs reports/fleet-driver-*.log): tier-b pid
  9052 (tb1 tier pair c132 / tb2 control / tb3 replicate / tb4 c264
  probe), shard-b pid 9053 (sb1 c132 / sb2 c66 / sb3 c198 / sb4
  c132), tier-a pid 9054 (ta1/ta2 = B2a 300-min repeat x2, CANCEL
  protocol, restore-model falsifier). Slot-start guard 16:55 PDT
  08-28 in all three; each driver scales its fleet to 0 at end.
- New configs: nc-surge-sps033-c198, nc-surge-sps044-c264.
- Bring-up: shard-b + tier-a clean; tier-b pod 9c7px CrashLoopBackOff
  with gcsfuse "Transport endpoint is not connected" on the model
  path - pod bounce fixed it (known drill). Launch times: sb1/ta1
  bases ~20:34 PDT, tb1 base ~21:15 PDT.
- Slot-1 verdict availability: sb1/ta1 ~02:00, tb1 ~02:45 PDT 08-28.

## Status 08-28 08:30-09:00 PDT

VERDICTS (analyze_run_windows, 300 s windows; cohorts realized
exactly per accounting lines):
- nc-a-base017 + surge c132 NO-CANCEL: COLLAPSE. Warm h 92-96 to
  t=60; tips in the surge window (t=75: h 15, KV 93, TTFT50 41 s);
  absorbing tail to t=300 (KV 91-92, wait 250-340, req/s ~1,
  TTFT50 130-260 s). h_tok windows noisy under pressure
  (counter-diff artifact, known).
- nc-b-base017 CONTROL: WARM throughout (h ~96, wait 0, KV 13-27
  at tail). Attribution clean.
- sb1 (shard-b, c132 no-cancel): COLLAPSE, same signature ->
  cohort-132 collapse n=2 across two fleets.
- sb2 (shard-b, c66 no-cancel): RECOVERED (h 90-100, wait 0, KV
  draining 62->26, catch-up 2-3 req/s warm).
- HARDWARE BOUNDARY BRACKETED: (66, 132] sessions at 0.017
  no-cancel; DES certain-collapse at ~67 => measured boundary right
  of DES, offset < 2x (left-bias consistent, B1-era).
In flight: nc-c (shard-a replicate, surge live), sb3 (c198).
Queued: nc-d, nc-e, sb4.

## INCIDENT: tier vllm deployments deleted externally

- Both cpu-offloading-tp4-vllm DEPLOYMENT OBJECTS (tier-a, tier-b)
  deleted from the API ~22:18 PDT 08-27 (tier-b EPP logged all 8
  endpoint deletions at 05:18:22 UTC in one sweep; tier-a same
  outcome, exact time not in EPP log tail). ta1/tb1 runs died ~1 h
  into 5 h bases: LOST (no end-of-run export; per-run reports PVCs
  retain partial jsonl only). NOT our tooling: fleet drivers only
  scale; the killed supervisor never fired; t15 CronJobs last fired
  08-16. Same signature as ns16's vllm deployment, found already
  missing at window start. EPPs/Services/SAs/pools untouched.
  ACTOR UNKNOWN - check GCP audit logs / cluster admins.
- Cleanup: tier drivers + dead-job pollers killed; shard fleets
  unaffected and verified healthy.
- Recreation APPROVED by user 09:30 PDT and applied: both
  deployments recreated from the staged manifests, all 12 pods
  scheduled. v2 driver bug on first launch (awk preamble cut matched
  the run_pair() DEFINITION, so the functionless scripts fell
  through and scaled the fresh fleets to 0) - fixed the cut pattern
  (/^run_pair / call lines only), rescaled, relaunched. tb1r base
  profiling from 09:48:55, ta1r from 09:49:56 PDT; surges at ~10:51.
  Timeline: tb1r/ta1r done ~15:40; tb2r/ta2r (240 m) done ~20:00,
  inside the 22:45 backstop.
- 09:55 PDT rollover check: nc-c base done rc=0 (verdict pending
  analysis), nc-d launched; sb3 (c198) in flight on shard-b.

## Window results (analyzed 2026-08-29; arcs refreshed)

All drivers completed and scaled their fleets to 0 before the 22:45
PDT backstop; 13 base runs + 10 surge jobs + smoke collected, zero
data losses after the tier recreation. extract_arcs.py RUNS extended
with the 13 bases; out/arcs refreshed (300 s windows). One failure:
the nc-e surge job was never created (kubectl API-server dial
timeout at job creation, 16:18 PDT; bench.sh does not propagate the
error, rc=0) - nc-e ran as a second no-surge control and the 2-min-
injection variant (1.1 sps x 120 s) has NO hardware data.

Arrival accounting exact in all 10 launched surges
(generated=admitted=cap, 0 rejections) and all bases (280-319
sessions at 0.017).

### Consolidated verdicts (from out/arcs; end = last-25-min mean)

| run | fleet | perturbation | warm req/s | kv peak 62-115 | end h | end kv | end wait (peak) | verdict |
|-----|-------|--------------|-----------|----------------|-------|--------|------------------|---------|
| nc-a | 8x noofl | nocancel c132 (0.22x~600s) | 1.75 | 0.94 | 0.03 | 0.92 | 279 (306) | COLLAPSE, onset t=75 |
| nc-c | 8x noofl | nocancel c132 | 1.90 | 0.94 | 0.03 | 0.92 | 295 (324) | COLLAPSE, t=75 |
| sb1 | 8x noofl (shard-b) | nocancel c132 | 1.73 | 0.94 | 0.02 | 0.91 | 253 (286) | COLLAPSE, t=70 |
| sb4 | 8x noofl (shard-b) | nocancel c132 | 1.21 | 0.94 | 0.02 | 0.91 | 296 (328) | COLLAPSE, t=70 |
| sb3 | 8x noofl (shard-b) | nocancel c198 (0.33) | 1.86 | 0.95 | 0.05 | 0.91 | 435 (491) | COLLAPSE, t=70 |
| nc-d | 8x noofl | nocancel c66 (0.11) | 1.67 | 0.64 | 0.95 | 0.39 | 0 (2) | RECOVERED (no pin) |
| sb2 | 8x noofl (shard-b) | nocancel c66 | 1.94 | 0.75 | 0.95 | 0.43 | 0 (2) | RECOVERED |
| nc-b | 8x noofl | none (control) | 1.88 | 0.40 | 0.96 | 0.19 | 0 (1) | WARM |
| nc-e | 8x noofl | none (surge failed) | 1.64 | 0.23 | 0.93 | 0.49 | 1 (3) | WARM |
| tb1r | 8x tier-500 | nocancel c132 | 2.10 | 0.96 | 0.96 | 0.37 | 0 (87) | DIGESTED, drained t=180 |
| tb2r | 8x tier-500 | none (240 min) | 1.66 | 0.22 | 0.95 | 0.37 | 0 (1) | WARM |
| ta1r | 4x tier-500 | B2a 0.011 + 0.125x2700 CANCEL | 0.78 | 0.96 | 0.94 | 0.64 | 0 (347) | RECOVERED t=115 |
| ta2r | 4x tier-500 | B2a (240 min) | 1.40 | 0.96 | 0.93 | 0.55 | 0 (395) | RECOVERED t=115 |

### Headline findings

1. NO-CANCEL COLLAPSE BOUNDARY (8x noofl, 0.017): cohort 132 = 4/4
   collapse across two fleets and realized warm rates 1.21-1.90
   req/s; cohort 198 = 1/1 (hardest tail, end wait 435); cohort 66 =
   2/2 recovered; controls 2/2 warm. Boundary in injected-cohort
   units: (66, 132]. Onset is within one window of injection end
   (t=70-75); every collapse tail is absorbing (wait still rising at
   t=295; cold cache window T_meas median 9-10 s vs warm 315-1102 s).
2. COHORT 66 IS ABSORBED WITHOUT PINNING: KV peaks 0.64-0.75, wait
   peak <= 2 - the bracket conflates the pin threshold and the
   entrapment threshold; a ~100-cohort point would separate them.
3. PERSISTENCE VS MAGNITUDE: the same base rate digests a CANCELLED
   675-session surge (0.25x2700, 4/4 recoveries, B1-era) but is
   entrapped by a never-cancelled 132-session cohort (~3.7x the
   standing ~36-session population; injected in ~10 min). Caveat:
   cross-protocol contrast, injection shapes differ - a same-
   injection cancel arm (0.22x600 cancelled at end) is the missing
   controlled pair.
4. TIER DELETES THE NO-CANCEL COLLAPSE (n=1): tb1r under the
   identical c132 perturbation holds h >= 0.86 THROUGHOUT, wait
   peaks 87 (vs 286-491 untiered), ext_h 0.72-0.93 through t=60-180
   (hits are CPU restores), reservoir drains by t=180, end warm
   (h 0.96, wait 0, KV 0.37). Refutes the on-record DES prediction
   (7/10 cold) - tier-side pessimism confirmed on a pre-registered
   discriminator.
5. SUSTAINED RESTORE ABOVE THE EFFECTIVE CEILING: tb1r fleet restore
   p50 322-324k tok/s across BOTH the surge and recovery phases
   (~2 h) = 1.75x N*B_r, peak 381k = 2.07x. Extends the C11/C29
   falsifier from 5-min transients (1.28-1.51x) to sustained
   operation; B_r as a hard channel ceiling is dead.
6. 4x FALSIFIER REPLICATED: ta1r (300 min) and ta2r (240 min) both
   end wait 0 vs DES-predicted 75-142; in-surge saturation (wait
   347/395, h min 0.03-0.04) with one-window post-cancel recovery,
   restore transients 1.59-1.67x N*B_r. 4x-0.011 tier stability now
   5/5 including two 300-min draws.
7. INSTRUMENT: session-count-capped open-loop arrivals realize
   exact never-cancelled cohorts (10/10 surge jobs
   generated=admitted=cap, 0 rejections); smoke gate documented the
   semantics (cap blocks new sessions, started trees run to
   completion).

### Gaps carried forward

- nc-e injection-duration insensitivity (c132 in ~2 min): NO
  hardware data (surge job creation failed); DES-only support
  (matched-cohort cells at 1-20 min injections agree in-model).
- Tier no-cancel is single-draw; tb3 replicate and tb4 c264 probe
  were dropped with the window. Next window: replicate + c264.
- Boundary bracket (66, 132] is wide and conflates pin vs
  entrapment; add ~c100.
- Controlled persistence pair (same injection, cancel-at-end arm).
