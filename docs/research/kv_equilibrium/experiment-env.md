# Experiment environment reference

HARD RULE (added 2026-08-13 after losing all five namespaces to
capacity reclaim): at WINDOW START, schedule a background task that
scales every vllm deployment to 0 at T-minus-15-minutes
unconditionally. Collection must beat that deadline; a run that
cannot collect in time is a lost run, but the fleets and namespaces
survive. Never leave scale-down as a post-collection step.

Operational facts for running KV-equilibrium experiments. Updated
2026-08-08.

## Cluster and fleet

- kubectl context: gke_supercomputer-testing_us-central1_a4x-baker
  (already the current context). Namespace: igw-llm-d.
- Capacity: 8 servers x 4 GB200 = 32 GPUs. One 8-replica TP4 fleet fills
  the whole allocation; no second parallel stream (the closed-loop plan's
  two-stream option does not apply here).
- Serving stack: deployment no-offloading-tp4-vllm (8 pods, TP4,
  Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8, vLLM block size 256) behind
  EPP no-offloading-tp4-epp + Envoy. Model pool per pod: 6486 blocks x
  256 tok; fleet 13.28M tokens.
- EPP plugin config is selected by which ConfigMap the EPP deployment
  mounts as plugins-config-volume. Available ConfigMaps (namespace
  igw-llm-d), which also decode the historical run-tag prefixes:
    no-offloading-tp4-epp                       approximate prefix + queue
                                                (original; July runs)
    no-offloading-tp4-epp-baseline              "baseline-*" runs
    no-offloading-tp4-epp-precise-prefix-cache  KV-events token-based
                                                precise routing ("kvm")
    ...-flow-control[, -utilization]            flow-control variants
  LIVE since 2026-08-08 ~15:30 UTC: precise-prefix-cache (fleet and EPP
  redeployed together). Record the mounted ConfigMap in every run note:
    kubectl get deploy no-offloading-tp4-epp -n igw-llm-d \
      -o jsonpath='{.spec.template.spec.volumes}'
- Backend prefix-cache reset: POST /reset_prefix_cache, exec'd inside
  each pod (bench.sh does this automatically unless -r false).

## Load generator

- aiperf source: /Users/yangligt/workplaces/perf_compare/aiperf
  (docs/tutorials/weka-trace.md, docs/benchmark-modes/*.md are the
  relevant references).
- Timing modes used here:
  - Closed loop, request-level: profiling type: concurrency (no
    timingMode key) = RateTiming concurrency_burst; N REQUESTS in
    flight, BranchOrchestrator preserves per-session ordering. This is
    what the July conc40 anchor used. MEASURED (2026-08-08): the credit
    meters main-turn lanes only; subagent fan-out is unmetered on top,
    so achieved client in-flight ~= 1.4-1.5x the configured concurrency
    on the 062126 corpus (conc 40 -> 56 in-flight, conc 100 -> 147).
    Use achieved in-flight for any load-axis statement.
  - Closed loop, session lanes: type: concurrency +
    timingMode: agentic_replay (no sessionArrival) = N trajectory lanes,
    drained lane recycles.
  - Open loop, session arrivals: agentic_replay + sessionArrival
    (rate, pattern) = Poisson session admission; concurrency becomes an
    admission ceiling (see bench-config-weka-sps0086.yaml).
- cacheBust (dataset.cacheBust.target: first_turn_prefix) salts each
  replay instance; valid with chat endpoint under ANY timing mode
  (validator restricts endpoint type only). Use it everywhere replays
  can repeat a trace; without it cross-play prefix sharing inflates h.
- Gap cap: dataset.traceIdleGapCapSeconds (10.5 = corpus p90). Omit the
  key for uncapped.

## Traces (in the shared assets PVC, mounted at /assets)

- /assets/datasets/cc-traces-weka-062126-256k/traces - 393 files, 544M.
  Corpus stats: 68266 requests, mean ~174 req/trace, main thread ~22 min
  at 10.5 s cap. Use for primary/normal traffic.
- /assets/datasets/cc-traces-weka-061526-256k/traces - 232 files, 382M.
  Use for burst/overlay traffic when the burst must not share trace
  identity with the base load (belt-and-suspenders on top of cacheBust).

## Harness (bench.sh)

Location: /Users/yangligt/workplaces/llm-d/guides/subslicing/aiperf/.
Run from that directory.

    ./bench.sh lifecycle -n <run-name> -c <config.yaml> \
        -N igw-llm-d -s no-offloading-tp4-epp -o ./reports

- lifecycle = reset caches -> launch Job -> poll -> collect -> clean.
- -r false skips the prefix-cache reset (REQUIRED for overlay/burst jobs
  launched while a base run is in flight).
- Run names: lowercase alphanumeric + '-' (k8s name rules).
- Placeholders ${SVC_IP}, ${SERVER_METRICS_URLS},
  ${SERVER_METRICS_ENABLED} are rendered at launch; ${RUN_TAG:manual}
  resolves to the run name inside the Job.
- Reports land in ./reports/<run-name>/qwen3coder-weka1-<run-name>/:
  profile_export.jsonl (per-request), profile_export_aiperf.json
  (summary), server_metrics_export.parquet (5 s per-pod scrapes),
  logs/aiperf.log (session accounting, phase timestamps).

## Analysis conventions

- Fleet aggregates from the 8 pod endpoints only; EXCLUDE the service
  endpoint http://10.0.44.19/metrics (aiperf auto-adds it; it
  round-robins pods). The "Discovered 1 endpoints" log line refers to
  auto-discovery only; the 8 pod URLs arrive via config and are present
  in the parquet.
- h = vllm:prompt_tokens_cached / vllm:prompt_tokens (windowed counter
  diffs). Do not use prefix_cache_queries/hits for h (re-counts under
  pressure).
- Windowed analyzer: kv_equilibrium/analyze_run_windows.py <run_dir>
  [window_s]. Wall-clock anchored so concurrent runs can be aligned.
- Python env: docs/research/.venv (pandas + pyarrow).
- Known reference points (this fleet, 062126 corpus, cap 10.5, approx
  routing unless noted): warm ceiling 2.7-2.9 req/s total; cold branch
  capacity ~1.6 req/s; collapse tip at KV ~92-93%; warm closed-loop
  conc40 h ~94%, TTFT p50 ~0.54 s.

## Collapse reproduction protocols (minimum dose, highest reliability)

Canonical recipes for demonstrating collapse / performance
degradation, selected from the measured ledger (lab notebooks
2026-08-08 .. 2026-08-27) by the criterion: 100% collapse tally at
the smallest perturbation. Intended for replication on new serving
stacks (NVIDIA Dynamo, SGLang); recovery demonstration is out of
scope. All times below are relative to base profiling start (T+0).
All runs: salted (cacheBust first_turn_prefix), gap cap 10.5, corpus
062126 for base and 061526 for surge, bench.sh lifecycle from the
harness directory, prefix caches reset before the base only.

### No-offload, PRIMARY: no-cancel flash crowd (4/4 collapse)

Tally: 4/4 absorbing collapse (nc-a, nc-c, sb1, sb4; 2026-08-27/28)
across two independent 8x fleets, warm realized 1.21-1.90 req/s.
Smallest perturbation with a 100% tally: 132 never-cancelled
sessions vs 675 cancelled sessions in the cancel protocol. Cohort 66
recovers 2/2 (never pins, KV peak 0.64-0.75); the boundary in
cohort units is (66, 132]. Do not shrink the cohort below 132.
Cross-stack (2026-08-30/31, lab-notebook-2026-08-30): NVIDIA Dynamo
1/1 (dyn-nc2-base017), SGLang 1/1 (sg-nc2-base017), same configs,
same onset window, end h 0.015-0.031, queue rising at t+295.

1. Prep: 8x TP4 no-offload fleet, EPP precise-prefix-cache mounted
   (verify per the ConfigMap check above).
2. T+0: launch base
       ./bench.sh lifecycle -n <tag>-base \
           -c bench-config-weka-nc-base-sps017-300m.yaml \
           -N <ns> -s <epp-svc> -o ./reports
   (0.017 sps Poisson session arrivals, 18000 s = 300 min.)
3. T+62 min: launch surge, -r false (never reset mid-run)
       ./bench.sh lifecycle -n <tag>-surge \
           -c bench-config-weka-nc-surge-sps022-c132.yaml \
           -N <ns> -s <epp-svc> -o ./reports -r false
   (0.22 sps arrivals, `sessions` cap 132, 061526 corpus. Injection
   completes in ~10 min; the cap blocks new sessions while started
   session trees run to completion - no cancellation. The surge job
   exits via its 13800 s duration backstop; do not kill it early.)
4. Expected outcome: collapse onset T+70-75 (within one 5-min window
   of injection end); absorbing tail through T+300: h 0.02-0.03, KV
   pinned 0.91-0.92, waiting 250-340 and still rising, TTFT p50
   130-260 s, completed throughput ~1 req/s. A no-surge control at
   the same base (nc-b, nc-e) stays warm 2/2.

### No-offload, alternative: cancel protocol at 0.022 (3/3 relapse)

Tally: 3/3 relapse into the absorbing state (b1a2, b1a2-rep,
ppc-lh-noofl), one draw with a 300-min horizon. Perturbation is ~5x
the no-cancel dose; use only when the cancel semantics are wanted.

1. T+0: base bench-config-weka-lh-sps022-300m.yaml (0.022 sps,
   18000 s; the 3-h variant is bench-config-weka-b1-base-sps022.yaml).
2. T+62 min: surge bench-config-weka-b1-surge-sps025-45min.yaml with
   -r false (0.25 sps x 2700 s, ~650-714 sessions). The generator
   cancels its whole session population at job exit (T+107).
3. Expected: post-cancel partial recovery for 1-3 windows, relapse
   completing by ~T+150, absorbing tail (h 1.6-3.0%, KV 92%, queue
   +~1.1/min) with zero recovery over 195 post-surge minutes.
   At 0.020 the same protocol collapses only 5/8; at 0.017 it
   recovers 4/4 - do not lower the base rate.
   Cross-stack (2026-08-31): Dynamo 1/1 (dyn-cx2-base022, relapse
   complete ~t+175), SGLang 1/1 (sg-cx2-base022, ~t+185), both
   absorbing to t+300 with queue +1.3-1.5/min.

### No-offload, smoke: closed-loop conc 100 (2/2, no surge)

bench-config-weka-e1-conc100.yaml (request-level closed loop,
conc 100, 3600 s) degrades 2/2 by ~T+15 min: h falls to 3-20%, KV
pins 91.5-93.5%, TTFT p50 40-64 s, throughput 1.2-1.5 req/s. The
degraded state is STATIONARY (bounded queue, self-throttling), not
absorbing - suitable as a first cross-stack smoke test of the
KV-pin mechanism, not as the headline collapse demonstration.

### With offload (CPU tier): no 100% protocol at n>=2 exists

Measured ledger at 8x tier fleets (--kv-offloading-backend=native):

    tier 500, 0.022 + 0.25x2700 cancel   congested 4/6, healed 2/6
                                         (all 4 congested draws ran
                                         warm >= 1.9 req/s; both
                                         heals ran ~1.6-1.7)
    tier 500, no-cancel c132             DIGESTED 1/1 (tb1r) - the
                                         tier deletes the no-cancel
                                         collapse; do not use
    tier 375, 0.022 + 0.25x2700 cancel   healed 2/2 - do not use
    tier 250, 0.022 + 0.25x2700 cancel   cold collapse 1/1
                                         (cpuofl-a4half-lh, 08-13)

Recommended recipe (tier 250, the only tier configuration observed
to reach the cold absorbing state; SINGLE DRAW - run a confirmation
draw on the llm-d stack before treating it as deterministic):

1. Prep: 8x TP4 fleet with --kv-offloading-size=250 (GB-scale,
   RAM-backed; boot envelope on these hosts ends in (500, 650)).
2. T+0: base bench-config-weka-lh-sps022-300m.yaml (0.022 sps,
   300 min). The 300-min horizon is REQUIRED: the 135-min truncated
   draw (08-12) was inconclusive because the collapse expresses
   after T+180.
3. T+62 min: surge bench-config-weka-b1-surge-sps025-45min.yaml,
   -r false (cancelled at exit, T+107).
4. Expected: restore-bound congestion T+120-170 (h 62-79%, ext_hit
   58-68%), then degradation through it T+180-300: h to 3-7%,
   ext_hit to ~1% (working set no longer fits the tier), KV pinned
   92%, waiting ~276 at run end.

If only degradation (not cold collapse) is required, tier 500 at
0.022 + 0.25x2700 yields restore-bound congestion (h 70-85%, KV
93-94%, queue +~0.8/min) in 4/6 draws, biased toward hot draws.

### Non-vLLM stacks (Dynamo, SGLang): measured mappings

Both protocols above reproduce on NVIDIA Dynamo and SGLang with the
aiperf configs unchanged; only the target Service differs. Driver:
guides/subslicing/aiperf/run-newstack-0830.sh <dynamo|sglang> [p1|p2]
(absolute-deadline surge timing, 600 s lateness gate, fleet guard).
Analyzer: kv_equilibrium/analyze_crossstack.py <run_dir> <stack>.

- Dynamo (ns yangligt-dynamo-nool): Service dynamo-frontend
  (--router-mode=kv), 8x dynamo-vllm-worker TP4 (vllm-runtime 1.4.0,
  same model/args family as the reference fleet). Workers expose the
  full vllm:* series on :9090 (DYN_SYSTEM_PORT); InferencePool
  dynamo-frontend (selector app=dynamo-vllm-worker, targetPort 9090)
  exists so bench.sh resolves worker metrics. h and KV use the same
  vllm counters as the reference fleet. Cache reset:
  stack-cache-reset.sh dynamo (dyn://dynamo.backend.clear_kv_blocks
  on every worker via the runtime client, then a frontend bounce).
  Warm h is structurally lower than EPP precise routing (0.84-0.86
  vs 0.93-0.94 at matched load) and the no-surge control decays to
  h ~0.61 over 300 min while serving warm - record as a routing-
  quality covariate.
- SGLang (ns yangligt-shard-b): 8x no-offloading-tp4-sglang TP4
  (v0.5.13.post1, page 64, --enable-cache-report, kv-events to the
  EPP) behind the llm-d EPP with no-offloading-tp4-epp-precise-
  prefix-cache. h = sglang:cached_tokens / sglang:prompt_tokens
  (counter diffs; the parquet strips _total), KV =
  sglang:token_usage, queue = sglang:num_queue_reqs. Cache reset:
  stack-cache-reset.sh sglang (POST /flush_cache per pod, retried
  while aborted requests drain, then an EPP bounce). Warm h matches
  the reference fleet (0.93-0.94).
- Always launch with -r false on these stacks (bench.sh's reset is
  vLLM-only: exec -c vllm + /reset_prefix_cache).
- Stack-independent collapse verdict (no engine counters needed):
  TTFT p50 above 100 s sustained, completed throughput pinned near
  the cold-branch capacity (~1-1.3 req/s here), waiting queue
  growing monotonically for 60+ min after the perturbation ends, KV
  occupancy pinned >= 0.90.
- Rate scaling for other fleet sizes: base and surge rates scale
  linearly with fleet capacity at fixed per-replica capacity (4x:
  0.011 + 0.125x2700; 16x: 0.040 + 0.50x2700). The no-cancel cohort
  boundary (66, 132] is measured at this pool size; on a different
  pool, size the cohort so its KV footprint exceeds the fleet pool
  and keep base arrivals at or above the cold-branch capacity.

## Cross-run comparability rules

- Router config (EPP ConfigMap), corpus, gap cap, salt, and duration are
  first-class factors: record all five in the lab notebook per run.
- July/early-Aug reference numbers were measured under different EPP
  configs (approx routing, baseline, kvm) and unsalted generators; do
  not mix them into fits with the 2026-08-08+ precise-prefix-cache
  salted series.
