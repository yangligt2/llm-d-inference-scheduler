# Lab notebook 2026-08-30/31: cross-stack window (Dynamo, SGLang)

Purpose: reproduce the two no-offload collapse protocols
(experiment-env.md, collapse reproduction section) on two non-vLLM
stacks. P1 = no-cancel flash crowd (base 0.017 sps 300 min + cohort
132 at 0.22 sps, never cancelled, surge at base t+62). P2 = cancel
protocol at 0.022 (base 0.022 sps 300 min + 0.25 sps x 2700 s
cancelled surge at t+62). Operator: Claude (autonomous session).

## Stacks

- Dynamo (ns yangligt-dynamo-nool): dynamo-frontend
  (--router-mode=kv, svc port 80 -> 8000) + 8x dynamo-vllm-worker
  (vllm-runtime 1.4.0, TP4, same model/args family as the reference
  fleet: Qwen3-Coder-480B-A35B-Instruct-FP8, block 256, fp8 KV,
  max-model-len 262144, kv-events on). Workers expose the full
  vllm:* metric set on :9090 (DYN_SYSTEM_PORT); an InferencePool
  named dynamo-frontend (selector app=dynamo-vllm-worker, targetPort
  9090) was created so bench.sh resolves worker metrics. Cache
  reset: dyn://dynamo.backend.clear_kv_blocks via the runtime client
  exec'd in a worker pod (stack-cache-reset.sh dynamo), then a
  frontend bounce (KV-router index state).
- SGLang (ns yangligt-shard-b): 8x no-offloading-tp4-sglang
  (sglang v0.5.13.post1, TP4, page 64, fp8_e4m3 KV, context 262144,
  --enable-cache-report, kv-events to the llm-d EPP) behind the
  existing EPP + Envoy mounting no-offloading-tp4-epp-
  precise-prefix-cache. EPP KV-block index confirmed ingesting
  SGLang events (admissions 2.9k -> 3.0M over the smoke). Cache
  reset: POST /flush_cache per pod + EPP bounce.
- Analysis: analyze_crossstack.py (this directory). h mapping:
  dynamo = vllm:prompt_tokens_cached / vllm:prompt_tokens (worker
  :9090 counters); sglang = sglang:cached_tokens /
  sglang:prompt_tokens. KV = kv_cache_usage_perc / token_usage;
  queue = num_requests_waiting / num_queue_reqs.
- Load generator: unchanged aiperf configs from the vLLM window
  (bench-config-weka-nc-*, -lh-sps022-300m, -b1-surge-sps025-45min);
  only -s (service) differs per stack.

## Smoke gates (both PASS)

    dyn-smoke-0830  conc40 600 s: 1876 records, 2.60 req/s, TTFT p50
                    0.64 s, steady 2-min h 0.78-0.80
    sg-smoke-0830   conc40 600 s: 2086 records, 2.86 req/s, TTFT p50
                    0.84 s, steady 2-min h 0.90-0.98

Dynamo's KV-router runs warm h ~0.79 vs 0.93-0.94 for the EPP
precise config at the same load - a routing-quality difference of
the stack, recorded as a first-class factor for cross-stack
comparisons.

## P1 verdicts (no-cancel flash crowd, cohort 132)

analyze_crossstack.py summaries (300 s windows; end = last-25-min
mean; end-kv from the last loaded windows, the teardown window is
excluded by reading the table):

| run | stack | perturbation | warm req/s | warm h | kv peak 62-115 | end h | end wait (peak) | end TTFT p50 | verdict |
|-----|-------|--------------|-----------|--------|----------------|-------|------------------|--------------|---------|
| dyn-nc2-base017 | dynamo | nocancel c132 | 1.70 | 0.86 | 0.955 | 0.015 | 215 (312) | 216 s | COLLAPSE, absorbing |
| sg-nc2-base017  | sglang | nocancel c132 | 1.21 | 0.93 | 0.956 | 0.031 | 223 (328) | 209 s | COLLAPSE, absorbing |
| dyn-nc-base017  | dynamo | none (control) | 1.83 | 0.86 | 0.25 | 0.61 | 1 (4) | 1.7 s | WARM (see note) |
| sg-nc-base017   | sglang | none (control) | 1.71 | 0.94 | 0.24 | 0.94 | 0 (3) | 1.1 s | WARM |

- Surge accounting exact on both stacks: generated=132 admitted=132
  rejected=0. Surge timing t+62.0 min (offset 3723 s) on both.
- Collapse onset within one window of injection end on both stacks;
  queue growth monotone post-onset (dynamo 99 -> 234 -> 281 at
  t+105/180/224; sglang 90 -> 200 -> 243), KV pinned 0.88-0.99
  fleet-wide, end throughput ~1 req/s.
- The signatures sit inside the reference vLLM class bounds
  (nc-a/nc-c/sb1/sb4: end h 0.02-0.03, KV 0.91-0.92, wait 253-340
  rising, TTFT p50 130-260 s). The no-cancel c132 collapse is now
  reproduced on three serving stacks (vllm/llm-d 4/4, dynamo 1/1,
  sglang 1/1) at the same operating point.
- Dynamo control note: the no-surge control stays warm-serving
  (wait <= 4, TTFT p50 1.7 s) but its h decays to ~0.61 late in the
  300-min horizon as context deepens - the KV-router's affinity
  quality degrades with load depth. Not a collapse; flagged for the
  router-span/affinity discussion.
- The controls were produced by the v1 timing incident (below):
  their surges fired after base end and were discarded, leaving
  clean no-surge bases.

## P2 verdicts (cancel protocol at 0.022)

Completed 2026-08-31 after two invalid slots (incident log below).
Same analyzer and conventions as P1. Surge accounting exact: dynamo
681 sessions admitted, sglang 646 (reference arms 647-714), zero
rejections, surges at t+62, cancellation at surge job exit t+107.

| run | stack | warm req/s | warm h | in-surge wait peak | post-cancel interlude | relapse complete | end h | end wait (slope) | end TTFT p50 | verdict |
|-----|-------|-----------|--------|--------------------|-----------------------|------------------|-------|------------------|--------------|---------|
| dyn-cx2-base022 | dynamo | 2.10 | 0.84 | 834 | t+125: h 0.64, wait 1 | ~t+175 | 0.018 | 269 (~1.5/min) | 183 s | RELAPSE -> ABSORBING |
| sg-cx2-base022  | sglang | 1.96 | 0.94 | 756 | t+140-155: h 0.33-0.66, wait 13-21 | ~t+185 | 0.014 | 202 (~1.3/min) | 166 s | RELAPSE -> ABSORBING |

- Both arcs show the reference structure: saturation, a partial
  post-cancellation recovery window, monotone relapse with KV
  re-pinned 0.89-0.96, then a linearly growing queue and ~1.1-1.3
  req/s cold throughput to run end. The sglang draw shows the
  recover/relapse oscillation (h 0.66 -> 0.34 -> 0.46 -> 0.33)
  before entrapment.
- Reference class (b1a2, b1a2-rep, ppc-lh-noofl): relapse complete
  by ~t+150, queue +~1.1/min, end h 0.016-0.030, TTFT p50 to 240 s.
  The cancel-protocol relapse at 0.022 is now 3/3 on vllm/llm-d,
  1/1 on dynamo, 1/1 on sglang.
- Cross-stack tally after this window: BOTH collapse protocols
  (no-cancel c132 at 0.017; cancel 0.25x2700 at 0.022) reproduce on
  all three serving stacks; each stack also has a clean no-surge
  300-min control.

## Incident log: the P2 slots (external capacity enforcement)

Two independent failures consumed the first P2 slots:

1. v1 timing incident: the operator machine slept ~4.5 h, freezing
   the drivers' local `sleep 3720`; P1 surges fired at base t+5h03.
   Fix: absolute-deadline surge timing + 600 s lateness gate + pair
   retry + caffeinate (run-newstack-0830.sh v2). The P1 retry then
   ran with exact timing.
2. External GPU reclaim: between ~05:15 and 06:40 UTC 08-31
   (Sat ~22:15-23:40 PDT) every GPU deployment in the project
   namespaces was scaled to replicas=0 mid-P2 (sglang fleet, dynamo
   workers; CPU components untouched, no objects deleted). The
   SGLang P2 surge logged 73,546/73,546 failed requests against the
   empty fleet; all four P2 runs were discarded. A scale-up to 8/8
   at 08:30 UTC was reverted to 0 by the external actor within ~2
   minutes of the fleet reaching ready (fleet guard caught it at
   08:40:19). Actor unknown - same class as the 2026-08-27
   deployment deletions; no managed-by fingerprint on the
   deployments; GCP audit logs needed for attribution. Driver v3
   adds the fleet guard (abort within 60 s of a scale-down, exit
   code 3, no retry loop against the enforcer).

3. Second sglang-only reclaim: after the user granted 16-node
   capacity (until 23:59 PDT 08-31) and both fleets were rescaled,
   the shard-b sglang deployment was re-zeroed a third time at
   ~16:40 UTC, 96 min into its first P2 attempt (fleet guard
   aborted; dynamo untouched from 13:35 onward). The immediate
   retry (fleet up 17:20, base 17:25) ran to completion
   undisturbed. Enforcement pattern: shard-b was hit 3x on 08-31
   (05:15-06:40, 08:40, 16:40); actor still unattributed.

State at window end (22:50 UTC 08-31): both fleets scaled to 0 by
the drivers' operator after collection, EPP/frontend/etcd/nats up,
no aiperf jobs or PVCs left behind. A local T-15 backstop (scale
both to 0 at 06:44 UTC 09-01) remained armed; in-cluster T-15
CronJob rearming was blocked by the operator harness permission
layer this window (manifests staged at /tmp/t15-0831/).

## Instrument notes for future cross-stack windows

- bench.sh -s accepts any Service; metrics/reset resolve through an
  InferencePool named <svc minus -epp> - create a metrics-only pool
  for stacks without one (done for dynamo, targetPort 9090).
- bench.sh -r true is vLLM-only (exec -c vllm, /reset_prefix_cache);
  always -r false on these stacks + stack-cache-reset.sh.
- aiperf's server-metrics collector is name-agnostic (generic
  Prometheus parser): sglang:* and worker vllm:*-on-9090 series land
  in the parquet; histograms land in sum/count columns, counters
  lose the _total suffix.
- kubectl cp collect can abort mid-stream after a completed job;
  artifacts persist on the per-run PVC and a collect retry recovers
  them (ensure_collected in the driver).
- sglang /flush_cache fails transiently while aborted requests
  drain; the reset script retries per pod (4 x 45 s).
