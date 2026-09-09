# Mining the existing inference-perf reports: findings

Source: 96 runs under llm-d/guides/subslicing/inf-perf/reports/, extracted
by mine_reports.py into out/reports_mined.csv. Run from docs/research:

    .venv/bin/python kv_equilibrium/mine_reports.py

## 1. Validity: use achieved concurrency, not the fix date

Little's law (inflight = rps x mean request latency) vs the configured
target separates generator-capped runs unambiguously:

- All June runs (tp8/tp16/tp32, offloading A/B) and the pre-0717 weka
  runs: inflight 12-65 regardless of target. Capped.
- The 0717-dated weka runs (conv160-conc80 through conv320-conc320) are
  ALSO still capped (inflight 14-22 at targets up to 320): the fix
  apparently deployed mid-0718 - gb200-weka-tp8-conv320-conc320-run4
  (0718) is capped at 19, run5 (0718) achieves 326.
- Everything dated 0720-0727 achieves inflight ~= target.

Rule adopted: a run is load-valid iff inflight/target >= 0.6. That yields
one clean, internally consistent dataset: the 0720-0721 weka conv sweeps
(TP4 conv20-conv240, TP8 conv20-conv240) plus the 0727 synthetic 8k1k
calibration runs. The June offloading A/B (the only existing tier
comparison) is unusable and must be re-run.

Consequence for the caveat question ("does the bug affect non-weka
runs?"): yes, every pre-fix run shows the cap, including non-weka. Some
of those may ALSO be server-saturated (tp8 single-replica at conc40 shows
inflight ~17 with 60 s latencies, which could be genuine), but they
cannot be disentangled - treat all pre-0718 data as anecdotal only.

## 2. The valid TP4 conv sweep is a real-hardware closed-loop l-sweep

gb200-weka-tp4 (fleet: multiple TP4 replicas behind llm-d; peak input
throughput / single-replica max-prefill ~= 264k / 19.6k ~= 13.5 suggests
~16 replicas = 64 GPUs, N=16 as in the model):

    conv   inflight  in_tok/s   ttft_p50   ttft_p95   tpot_p50  prompt_mean
     20       14      129k       0.56       2.0       0.011      107k
     40       28      180k       0.59       3.3       0.015      101k
     60       52      237k       0.59       3.8       0.019       98k
     80       77      259k       0.59       5.7       0.024       91k
    100       90      264k       0.63       7.2       0.027       93k
    120      120      202k       1.05      21.0       0.039       80k
    140      173      145k      14.5       44.7       0.077       68k
    160      196      141k      20.3       53.6       0.079       64k
    180      204      140k      30.4       67.1       0.094       65k
    200      244      136k      38.7       81.1       0.098       60k
    220      249      132k      46.7       94.0       0.101       61k
    240      272      126k      53.9      103.3       0.108       60k

Textbook saturation knee at conv ~100-120: throughput peaks at 264k tok/s
then FALLS 50% while TTFT p50 inflates 0.6 s -> 54 s. TP8 (8 replicas x
TP8, same 64 GPUs) peaks higher and later: 308k at conv140, knee at
conv ~200-220 - a replica-count / per-replica-capacity tradeoff that is
itself paper material (same silicon, different (N, c) point).

Measurement bias to fix in future runs: prompt_mean drops from ~100k to
60k past the knee because 1800 s stages end before slow sessions reach
deep turns - the surviving request mix shifts young. Equilibrium
measurements need longer stages or session-cohort accounting.

## 3. Calibration constants extracted (GQA / Qwen3-Coder-480B FP8, GB200)

- Per-TP4-replica prefill throughput: 19.6k tok/s saturated
  (gb200-tp4-8k1k-max-prefill-2); 13.3k in the unsaturated run. Fleet
  effective ~264k/16 = 16.5k per replica under mixed load.
- TPOT floor: 0.010-0.012 s (matches the model's 0.012 assumption).
- Prefill/decode interference, previously an unmodeled caveat, is now a
  measured curve: tpot_p50 0.011 (idle) -> 0.027 (conv100) -> 0.039
  (conv120) -> 0.108 (conv240). ~8-10x TPOT inflation at saturation.
  The fluid model holds TPOT fixed; adding tpot(rho) from this curve is
  a required correction before quantitative overlay (the model currently
  overpredicts closed-loop throughput ~4x at conv120 because decode time
  dominates the session cycle once interference kicks in).
- Think-gap regime: trace_idle_gap_cap_seconds = 10.5 in all replay
  configs. The replayed gap CDF is all-agentic (every gap <= 10.5 s);
  the human tail that creates the bistable band in the model is REMOVED
  by this replay setting. Existing runs therefore cannot exhibit the
  band even in open loop - the cap is a first-class experimental knob,
  not a detail.

## 4. Blind spots confirmed

- prompt_tokens.cached = 0 in every summary: no cache-hit observability
  anywhere in the dataset. All hit-rate inference is indirect.
- No open-loop (session_rate) runs; all closed-loop concurrency.
- No warm-vs-cold pairs; every run starts cold.
- No router decision logs, so per-session replica affinity (routing
  accuracy `a`) is unmeasured.
- schedule_delay p95 ~= 1650 s in ALL weka runs regardless of load
  (even conv20 with 0.56 s TTFT) - it measures replay lateness vs the
  nominal trace clock, not backlog. Not usable as a congestion metric.

## 5. Experiment plan derived from the gaps

P0 - observability, before any GPU spend:
  a. Capture cached tokens per request (vLLM server usage field /
     prefix-cache metrics scrape) + KV usage, preemption count, offload
     tier hit/miss (connector metrics). Gate: a rerun of one conv120
     point shows per-request cached tokens in the report.
  b. Log routing decisions (replica per request) to measure session
     affinity and empirical routing accuracy.
  c. Add an achieved-concurrency assertion to the harness so a future
     generator regression is caught in-run (Little check vs target).

P1 - clean baselines (modest GPU):
  d. Re-run the tier A/B invalidated in June: {HBM-only, +CPU offload,
     +WEKA} x conv {60, 120, 180} x 2 seeds, cache metrics on. This is
     the real-hardware C4 evidence (tier deletes the bad equilibrium -
     here in its closed-loop form: tier extends the knee).
  e. One repeat TP4 conv sweep pass with cache metrics enabled (the
     0720-0721 sweep is load-valid but hit-rate blind).

P2 - the band (core new evidence, open loop):
  f. session_rate mode (Poisson session arrivals, no concurrency cap),
     rate sweep bracketing fleet capacity (~2.5-3 rps at current mix),
     warm-start vs cold-start pairs at each rate -> hysteresis loop on
     real hardware.
  g. Flush protocol: vLLM /reset_prefix_cache (or rolling restart) mid-
     run at fixed rate; observe stuck vs self-recovery; repeat per tier.
  h. Shed-recover: gate ingress to ~10-20% for 3-5 min after a stuck
     state; verify recovery and restore. This doubles as mitigation
     prototype v0.

P3 - model-driven knobs:
  i. Gap-cap sensitivity: rerun key open-loop points with
     trace_idle_gap_cap_seconds in {10.5, 60, 300, uncapped}. The gap
     CDF is the theory's primary workload variable; the cap is the lever
     that turns the band on and off. Prediction to test: band appears as
     the cap grows past the retention window.
  j. Routing ablation: random vs prefix-affinity routing at fixed load
     (empirical `a`; predicted basin shift).
  k. Interference refinement: extend the 8k1k qps sweeps to map
     tpot(prefill load) for the model correction.

Suggested order: a-c (days, no GPUs) -> e+f in one cluster session ->
g/h -> d -> i/j. P2f-h at 3 rates x 2 starts x ~40 min each fits in
roughly two cluster-days.

## 7. Open-loop qps sweep (2026-07-31): the tip captured end to end

Runs: noofl-tp4-qps{05,10,15,20}, root rate = main-session credits/s
(subagents unmetered; total request rate ~2.2x root). Summary: 0.5 and
1.0 clean full-hour steady states; 1.5 tips at ~35 min; 2.0 tips fast;
completion ceiling 2.7-2.9 req/s.

qps15 anatomy (3-min windows; hit rate from prompt_tokens_cached /
prompt_tokens, the execution-level truth):

- Phase 1, 0-24 min: h 91-94%, KV 30-43%, wait ~0, computed prefill
  ~25k tok/s (~16% of fleet capacity), first-turn share 6-10%.
- Phase 2, 24-39 min: working set outgrows the pool as sessions deepen
  and population ramps: KV 55 -> 92%, h erodes 93 -> 51%, computed
  prefill 37k -> 360k tok/s. CONFOUND CHECK: first-turn share stays
  <= 10% until h is already below ~75% - the onset is organic; the
  generator's session substitution (first-turn 24 -> 42%) only
  amplifies the collapse already in progress.
- Phase 3, 39-60 min: absorbed bad state: h 3-8%, KV pinned 92-96%,
  prefill compute saturated (~120k tok/s, essentially all uncached),
  waiting queue +0.42 req/s linear to ~600, preemptions ongoing, TTFT
  p50 ~400 s. No recovery in 22 min at constant offered rate.

Metric hygiene: vllm:prefix_cache_queries/hits gave h ~0.4% post-
collapse vs 3-8% from prompt_tokens_cached - queries are re-counted for
waiting/preempted requests under pressure. Use prompt_tokens_cached
for hit rate; treat query counters as scheduler-pressure signals.

Capacity anchors: warm ceiling ~2.7-2.9 req/s total (KV-slot bound);
cold capacity ~1.6 req/s total (prefill bound: 157k / ~100k mean
prompt). qps10 (total ~2.3 req/s) sits BETWEEN them: stable warm for a
full hour (TTFT p50 0.5 s flat), but a collapsed system at the same
rate demands ~218k > 157k tok/s and cannot recover. qps10 is therefore
predicted BISTABLE - the band on real hardware is approximately total
1.6-2.9 req/s (root ~0.7-1.35).

THE decisive experiment (no new tooling needed): tip-and-drop.
Run A (in hand): qps10 baseline, warm, stable hour. Run B: 10-15 min at
root 2.0 (fast tip), then drop to root 1.0 for 45+ min - via staged
rates if aiperf supports phases, else back-to-back invocations with no
drain gap. Prediction: stays collapsed (h < 10%, TTFT p50 > 100 s) at
the exact rate Run A served at 0.5 s / 92%. That pair is unconfounded
real-hardware hysteresis - the paper's centerpiece. Add Run C
(recovery): after B's stuck hour, drop to root 0.3 for ~10 min, then
back to 1.0 - predicted to recover and hold (shed-recover mitigation
demonstrated on hardware).

## 6b. aiperf assessment (2026-07-30): P0 observability is essentially closed

First aiperf run examined: aiperf/reports/noofl-tp4-conc40 (8 replicas x
TP4 on 32 GB200 GPUs, no offload, weka_trace dataset, concurrency=40,
30 min, 6028 requests).

What aiperf provides that inference-perf did not:
- Per-pod vLLM metrics WITH 5 s time series (384 slices/run):
  prefix_cache_queries/hits, prompt_tokens_cached, external_prefix_cache_*
  (offload tier attribution), kv_cache_usage_perc, num_preemptions,
  request_queue_time, num_requests_running/waiting. The central
  observable h(t) per pod is now first-class. P0a: DONE.
- Per-request JSONL: conversation_id, turn_index, source_kind
  (weka_main 3103 / weka_subagent 2229 / weka_flat 696), ns timestamps
  (credit/start/ack/end), TTFT, server token counts, cancellation flags.
  Session gap structure verified: 94% of inter-turn gaps within the
  10.5 s cap, median 1.2 s, no ordering violations - concurrency mode
  honors trace think gaps.
- /reset_prefix_cache handler confirmed live on every pod (flush
  protocol is one POST away).

Measured in this run (first direct hit-rate measurement of the project):
fleet token hit rate 94.4% (per pod 93.6-96.2%), warmup transient
83% -> ~96% over the first ~4 min visible in the time series; KV usage
~40%; zero preemptions; TTFT p50 0.54 s. Healthy good-equilibrium point;
computed (uncached) prefill ~17.5k tok/s vs ~157k fleet capacity.

Ninth scrape endpoint explained: 10.0.44.19 (no port) is the service
address aiperf adds automatically; it double-counts one pod (server
prompt-token total 681.7M vs client 601M; 681.7M x (1 - 0.118) = 601.3M
exactly). Analysis rule: exclude the service endpoint and compute fleet
aggregates from the 8 pod endpoints directly. Ratios (hit rate) are
unaffected either way.

Load semantics: aiperf concurrency=40 maintains ~40+ requests in flight
(effective concurrency avg 46.5) vs inference-perf's 40 sessions with
idle gaps - hence "behaves like conc > 80 of the old tool". For model
mapping this is a closed loop over request slots, not sessions.

Remaining gaps before the band experiments:
1. Routing attribution: which pod served each request is not in the
   client records. Needed for affinity / routing-accuracy measurement
   (P0b). Capture the EPP/gateway routing response header into the
   JSONL, or accept coarse per-pod inference from server time series.
2. Open loop: this run is concurrency mode; the config comment says
   trace datasets auto-promote to fixed-schedule replay (absolute
   timestamps = true open loop) unless overridden. Confirm and use that
   mode for warm/cold, flush, and shed runs.
3. RETRACTED (grouping artifact): an earlier claim that the median
   in-window sequence was 1 turn came from grouping by source_outer_idx,
   which increments per turn for weka_main and fragments conversations.
   Correct grouping (conversation_id x source_kind): 99 main
   conversations in-window with p50 28 turns (p90 55, max 138). The
   30-min window's depth mix is healthy; 60-min runs are still preferred
   for steady-state windows.
4. The 10.5 s gap cap still removes the human tail (P3i unchanged: the
   cap sweep is what turns the band on).

## 8. rateseries10 (2026-07-31): hysteresis measured in one run; shed fails via subagent cascade

Run: noofl-tp4-rateseries10 (8xTP4, entries 500, gap cap 10.5 s, server
metrics on all 8 pods, service endpoint excluded). Schedule: 45 min at
root 1.0 -> 10 min at 2.0 -> 45 min at 1.0 -> 15 min at 0.1 -> 45 min at
1.0. 21,759 requests, 46 errors, 0 client cancellations.

Per-phase (client arrivals by credit time; completions by end time;
server h_tok = prompt_tokens_cached/prompt_tokens, 3-min windows):

    phase       arr_tot/s  main/s  first%  compl/s  h_tok    KV%   wait      TTFT p50
    1.0 base    2.38       1.052    3.1    2.36     93-97%   16-31    0      0.55 s
    2.0 tip     4.06       1.975   11.1    3.70     91->11%  42->93   46     0.64 s
    1.0 hyst    2.32       1.047   11.7    2.10     5-9%     93-94    92->678  174 s
    0.1 shed    2.05       0.118    0.0    2.55     7->20%   93-94    660->240  103 s
    1.0 rec     1.79       0.820   11.6    1.88     5-12%    93-95    433->935  401 s

### 8a. The hysteresis pair is in hand

Base and hyst phases have identical offered load (1.05 main/s, 2.3-2.4
total/s) and near-identical composition (first-turn 3.1% vs 11.7% - no
substitution flood). Warm branch: h 95%, TTFT p50 0.55 s, queue empty.
Collapsed branch: h 5-9%, TTFT p50 174 s and rising, queue +0.22 req/s
unbounded, for the full 45 min. Single run, same fleet, same rate. This
is the unconfounded hardware hysteresis exhibit.

### 8b. Mechanism, measured: running-residency crowd-out sets T

Pool: 6486 blocks x 256 tok = 1.66M tok/pod, 13.28M fleet.
kv_cache_usage_perc counts allocated blocks (running residency); prefix
cache lives in freed blocks. Warm: ~27 running x ~100k = 2.7M (20-25%
usage, matches); free pool 10.6M / write rate ~13k tok/s -> retention
T ~ 790 s >> 10.5 s gap cap -> h at ceiling. Collapsed: ~190 running x
~65k = 12.4M (93-94% usage, matches); free pool ~0.9M / write ~120k
tok/s -> T ~ 7 s < 10.5 s cap -> h ~ 0. The tip occurred at KV 92.9%,
exactly where free-pool T crosses the gap cap. With cap 10.5 s the
h = F(T) law is a step at T = 10.5 s and the run walked through it in
both directions of the state space (never back up the rate axis).
Prediction for E2: larger gap caps tip at lower KV usage.

### 8c. Why the 0.1 shed failed - three compounding mechanisms

1. Subagent cascade nullifies root shed: root admission cut 10x, but
   completing backlogged mains spawn unmetered subagent groups; total
   arrivals fell only 2.32 -> 2.05/s (94% subagents). Net drain 0.50
   req/s against a backlog of ~850 in flight (660 waiting + ~190
   running): full drain needs ~30 min, shed lasted 15.
2. KV never unpins during a partial drain: running residency alone is
   ~93% of pool, so T stays ~seconds, every arrival is a full
   re-prefill, and h recovers only to 20% (the drained fraction).
3. On rate resume the backlog rebuilds immediately (wait 281 -> 935)
   and the system settles into a degraded quasi-steady state: h 5-8%,
   completions 1.88/s, uncached 118k tok/s (10x the warm prefill work
   for the same logical workload), deep-context requests starving
   (completed-request p50 prompt drops to ~50k vs 84k warm).

Generator note: in the rec phase the tool achieved only 0.82 main/s of
the 1.0 target despite substitution (3084 conversation instances from
393 traces - unsalted reuse, ~7.8x each). Once all sessions are stuck,
the open-loop generator degenerates to completion-coupled (closed-loop)
exactly when the open-loop property matters most. Raise entries and
check credit-cancel stats in future runs; salting remains open for
cross-replay prefix sharing (did not rescue h here - pool was pinned -
but biases warm-phase h upward by an unmeasured amount).

### 8d. Next runs: R1 drain-and-ramp, R2 drain-and-jump

Recovery requires (i) a true drain - root ~0 so the subagent cascade
terminates - until waiting = 0, running < ~15, KV < 40%; then (ii)
re-entry below cold capacity while sessions pay one re-prefill each.

R1 (mitigation demo, 160 min):
      - { timeS: 0,    qps: 1.0 }
      - { timeS: 1800, qps: 1.0 }   # warm 30 min
      - { timeS: 1801, qps: 2.0 }
      - { timeS: 2400, qps: 2.0 }   # tip 10 min (proven sufficient)
      - { timeS: 2401, qps: 1.0 }
      - { timeS: 4200, qps: 1.0 }   # hysteresis confirm 30 min
      - { timeS: 4201, qps: 0.01 }
      - { timeS: 5400, qps: 0.01 }  # TRUE drain 20 min
      - { timeS: 5401, qps: 0.3 }
      - { timeS: 6000, qps: 0.3 }   # rebuild below cold capacity
      - { timeS: 6001, qps: 0.6 }
      - { timeS: 6600, qps: 0.6 }   # ramp
      - { timeS: 6601, qps: 1.0 }
      - { timeS: 9600, qps: 1.0 }   # hold 50 min
    entries: 1500. Success: drain phase reaches waiting=0/KV<40%;
    hold phase h >= 90%, TTFT p50 < 1 s, queue empty.

R2 (control, 140 min): identical through the drain, then jump straight
    to 1.0 for 50 min. Fluid model predicts re-collapse (1.0 root =
    2.3 total sits inside the band; cold start inside the band falls to
    the bad branch). If it re-collapses, the staged ramp is proven
    necessary and the basin geometry is measured; if it recovers, drain
    alone suffices. Either outcome is a result.

Production translation (paper's mitigation section): root-rate shedding
is not available in production and this run shows even 10x shed fails
in 15 min. The implementable levers are (a) admission control capping
total in-flight KV demand so running residency never pins the pool
(basin-aware admission: never tip), and (b) an offload tier that keeps
evicted contexts restorable, raising degraded-branch capacity above the
offered rate so the bad equilibrium disappears (self-recovery).

### 8e. Band width from existing data: root 0.7-0.9 assessment

Direct observation: the rec phase achieved root 0.82 main/s (generator
starvation below its 1.0 target) and collapse persisted the full 45 min
(h 5-12%, KV 93-95%, queue stable ~850-935, no recovery trend). Demand
is monotone in rate, so collapse at 0.82 implies collapse at every
higher rate: root 0.85-0.9 in-band needs no further runs. Warm-branch
stability at 0.7-0.9 follows from the 1.0 warm phase (20-30% KV, empty
queue) with monotone headroom.

Token balance for lower rates. Constants (measured): total/main 2.25,
logical mean prompt ~100k (base-phase arrivals, queue empty so
unbiased), residual collapsed h 6%, collapsed uncached prefill capacity
113-122k tok/s (constant across hyst/shed/rec, 137-200 running).
Uncached demand = 209k x r:

    root r   demand    vs ~118k    verdict
    0.5      105k      -11%        drains -> recovers (outside)
    0.6      125k      +6%         marginal (lower edge)
    0.7      146k      +24%        in band (calculated)
    0.8      167k      +42%        in band
    0.9      188k      +59%        in band (direct via 0.82)

Endogenous-composition caveat: collapsed-state arrival mix is shallow
(mean isl 60-69k; deep sessions stall so their turns stop arriving).
Under that mix the balance point is ~0.88, and rec at 0.82 sat exactly
on it (arrivals 123k tok/s vs completions 129k - hence the queue
plateau). The 0.7 verdict rests on demand conservation: deferred deep
turns are postponed, not deleted; any drain lets deep sessions resume,
the mix deepens toward 128k mains, demand rises above capacity, and the
drain stops. Composition shift stabilizes the degraded state. This is a
model argument; 0.7 is calculated, not measured.

Band estimate: root [~0.6, ~1.25], total [1.3, 2.9] req/s, width ratio
> 2x (fluid B200 band was 1.35x). Report in total req/s or normalized
prefill load; the root/total ratio is workload-specific.

R3 - descending staircase (~3 h), measures r_low directly:
    15 min @ 1.0 (warm sanity) -> 10 min @ 2.0 (tip) ->
    15 min @ 1.0 (collapse confirm) ->
    25 min each @ 0.8, 0.7, 0.6, 0.5, 0.4 ->
    after recovery onset, 20 min @ 1.0 (warm branch must hold; closes
    the hysteresis loop in one run).
Judge each step by last-10-min trends (waiting slope, KV%, h), not
levels - the carried backlog biases levels toward collapse. entries
1500. Near the edge relaxation is slow: a marginal step yields a
bracket, not a point. Bonus: if 0.5 self-recovers, shed depth alone
(without the R1 drain-to-zero) is a viable mitigation lever.
