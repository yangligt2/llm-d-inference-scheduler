# Closed-loop experiment plan (aiperf, GB200 fleet)

Scope: closed-loop concurrency mode only (open-loop fixed-schedule replay
deferred until the tool path is understood). Goal: maximum model-validation
value per GPU-hour from the claims that closed loop CAN test:

- C1 (core): h* = F(T) pointwise. T (retention window) is measurable per
  run as fleet cache tokens / measured KV write rate; F is manipulated by
  the idle-gap cap; h is now directly measured. Every run contributes one
  (T, F, h) triple; the grid tests the fixed-point law quantitatively
  without needing the band.
- C4 (closed-loop form): tiers extend the good region / move the knee,
  with per-tier hit attribution via external_prefix_cache metrics.
- Interference calibration: tpot(rho_prefill) curve for the fluid model.
- Relaxation dynamics: flush -> self-recovery time constant (closed loop
  recovers; the RATE tests the dynamic model's asymmetry).

NOT testable here (needs open loop): bistability, hysteresis, stuck
states. Do not oversell closed-loop flush results as the band.

## Standing configuration

- Fleet: 8 replicas x TP4 (32 GPUs) unless stated. Keep fixed across all
  runs for comparability. The other 32 GPUs can host a second identical
  fleet to run two experiment streams in parallel.
- Duration 60 min + grace. Discard the first 10 min for steady-state
  stats; keep them for warmup-transient analysis.
- Dataset: cc-traces weka_trace, entries scaled with concurrency
  (entries >= 4x concurrency) so request slots never starve when
  sessions park in think gaps. Monitor effective concurrency ~= target
  in-run; a run where it sags is a starved run, not a server result.
- Metrics: server scrape of the 8 pod endpoints. The 9th endpoint (the
  service address aiperf adds automatically) double-counts one pod:
  EXCLUDE it in analysis and compute fleet aggregates ourselves from the
  8 pod series. (Client total 601M vs server 682M in the first run is
  exactly this duplicate.)
- Per run, record: aiperf config, llm-d router config (scorer weights),
  vLLM launch args (pool size, offload config), git SHAs.
- Routing attribution: if the gateway can echo the destination pod in a
  response header, capture it into the JSONL. Until then, per-pod
  hit-rate variance is the affinity proxy.

## Run-analysis contract (compute for every run, 8-pod aggregates)

    h_tok        cached / queried prompt tokens, steady window
    h(t)         2-min windowed, full run
    T_meas       fleet cache tokens / measured write rate
                 (write rate = uncached prompt tokens/s + generation
                 tokens/s; cache tokens from kv_cache_memory_bytes and
                 usage, minus running-request share)
    rho_p        computed prefill tokens/s / calibrated fleet capacity
    tpot p50/p95, TTFT p50/p95/p99, queue time
    per-pod h and query share (balance / affinity proxy)
    effective concurrency (client) vs target

## Experiments, in priority order

### E0. Smoke + harness fixes (0.5 h, gate for everything)

10-min run at conc40 verifying: 8-endpoint analysis path, effective
concurrency ~= target, client/server token totals reconcile after
dedup, routing header (if implemented) lands in JSONL, entries scaling
works. Rerun after any harness change.

### E1. Concurrency sweep at fixed cap (7 h)

conc in {20, 40, 60, 80, 100, 120, 160}, gap cap 10.5 s (comparability
with the July inference-perf sweep). Expect the knee at conc ~80-120
(aiperf conc = in-flight requests; the old tool's knee was at ~90-120
achieved in-flight).

Yields: the real closed-loop l-sweep WITH hit rates; knee position vs
model; tpot(rho) interference curve; the DES/fluid overlay figure.

### E2. Gap-cap sweep - the F(t) knob (10-12 h)

cap in {10.5, 30, 60, 180, 300, uncapped} x conc {40, 100}.

This is the highest-value science per hour: it sweeps the workload's gap
CDF against a measurable retention window, tracing out h = F(T) - and it
reproduces the customer mechanism (human-tail gaps overflowing
retention) on real hardware, in closed loop.

Cautions:
- "Uncapped" in a 60-min window is effectively cap-at-window-length:
  gaps longer than the remaining window never fire, and parked sessions
  can starve the request slots. Scale entries up (>= 8x conc) for
  cap >= 180 and uncapped; if effective concurrency still sags, extend
  those two cells to 90 min rather than raising conc.
- Randomize run order across days to decorrelate from cluster state.

### E3. Tier A/B/C (9 h)

{no-offload, CPU offload, WEKA} x conc {40, 100, 160} at cap 60 s.

Cap choice matters: at cap 10.5 s the HBM retention window at healthy
load (~560 s measured in the first aiperf run) covers nearly all gaps,
so tiers would show no effect. 60 s plus high concurrency creates the
churn where tiers differentiate. Replaces the invalidated June A/B.
external_prefix_cache_queries/hits gives per-tier attribution.

### E4. Flush-recovery dynamics (4 h)

conc {40, 100} x {no-offload, WEKA}: 20 min steady -> POST
/reset_prefix_cache on all 8 pods simultaneously -> 40 min observation.

Yields: recovery time constant vs the dynamic model (coverage grows at
most 1 s/s; tier shortens re-warm via restore), warmup asymmetry, and a
full rehearsal of the flush protocol before the open-loop hysteresis
runs. Expect self-recovery in all four cells (closed loop); the value is
in the trajectory shape, not the endpoint.

### E5. Routing ablation (4 h, needs router config change only)

{prefix-affinity (current), random/round-robin} x conc {40, 100} at
cap 60 s. Yields empirical routing-accuracy effect on h and TTFT (the
paper's generalized `a` parameter, measured). Per-pod hit-rate spread
collapses under random routing - visible even without the header.

### E6. Replica geometry (6 h, opportunistic)

4 x TP8 vs 8 x TP4 on the same 32 GPUs, conc {40, 100, 160}, cap 60 s.
Same silicon, different (N, c) point: per-replica pool doubles while
replica count halves. Directly probes the model's N vs c tradeoff with
hit-rate visibility that the July TP4-vs-TP8 sweep lacked.

### E7. Repeats (2 h)

Second seed/run of two anchor cells (conc40 and conc100 at cap 10.5) for
run-to-run variance bars on every figure.

## Budget and sequencing

Single 32-GPU stream: E0 (0.5) + E1 (7) + E2 (11) + E3 (9) + E4 (4) +
E5 (4) + E6 (6) + E7 (2) ~= 43 cluster-hours ~= 5-6 working days.
With both 32-GPU fleets in parallel: ~3 days (stream A: E1 -> E3 -> E5;
stream B: E2 -> E4 -> E6 -> E7). E0 gates both.

If time-boxed, the cut line in value order: E0, E1, E2, E4, E3, E5, E7,
E6. E1+E2 alone already produce the two headline closed-loop figures
(knee validation and the h = F(T) scatter).

## Open-loop semantics: findings from the qps3 probe and the aiperf change

Probe: noofl-tp4-qps3 (rate 3.0 poisson, 60 min config, same 8xTP4 fleet).
Two rate-mode characteristics were found and their effect measured:

1. Subagent calls are not metered against the rate. Verdict: REALISTIC,
   keep. In production the exogenous rate is session/user arrivals;
   agent fan-out is a workload multiplier that bursts with its parent.
   Metering it would artificially serialize intra-conversation bursts.
   Consequence: always report measured total request rate alongside the
   configured rate (here: set 3.0, achieved ~4.5 routed).
2. When sessions are in think gaps, the tool STARTS NEW SESSIONS to hold
   the request rate at target. Verdict: NOT usable as a controlled
   instrument. Pinning the request rate by conjuring sessions creates a
   generator-side feedback: degradation stalls existing sessions -> the
   tool substitutes cold first-turn sessions (measured: first-turn
   fraction 15% -> 44%) -> cold 50k prefills with zero hit -> more
   degradation. The generator itself supplies the workload-amplification
   loop of a metastable failure (real-world analog: users abandoning
   stuck chats and opening new ones - worth one sentence in the paper,
   not an instrument).

Measured trajectory (server metrics, 8 pods, 5-min windows): hit rate
83.8% at t=300 s, 11.3% at 600 s, then pinned at 1-6% through 3600 s;
waiting queue grows ~linearly to ~3700; KV usage pinned ~95%; TTFT p50
diverges 0.5 s -> 825 s; no recovery within 50 min. Same fleet, same
corpus, closed-loop conc40: 94.4% hit, 0.54 s TTFT. This pair is the
paper's motivation exhibit (how load is offered selects the regime), and
the run documents that the bad state is absorbing under sustained rate
pressure - but it is NOT clean band evidence: the workload composition
was endogenous to the generator.

Open-loop design, corrected for the corpus shape (393 sessions, mean
174 requests/session, 6.9B input tokens; a session's main thread runs
~22 min at capped gaps, ~40+ min at 60 s caps). Naive Poisson session
admission fails: steady state needs N* = lambda_s x session_duration
active sessions, so the ramp takes one session lifetime, a 90-min run
consumes 200-400 session instances against 393 available, and every
admission is cold. Three ingredients fix it; both viable modes use them:

- Salted trace reuse: replaying a trace as a new "user" must be
  cache-unique - inject a per-instance salt at the head of the system
  prompt so all blocks diverge (equivalent of inference-perf's
  inject_random_session_id / duplicate_sessions_target). Without salt,
  corpus reuse inflates hit rates via cross-replay prefix sharing.
  This removes the 393-session ceiling entirely.
- Mid-life bootstrap: at t=0 admit N* sessions at turn offsets sampled
  uniformly over each trace, so the stationary composition (age mix,
  context-depth mix) exists immediately instead of after a lifetime.
  The trace format permits starting at any turn (each request carries
  full context). Bootstrap cohort pays one cold prefill per session:
  that IS the cold-start arm. The warm arm = same bootstrap + a 25-40
  min warm ramp before the measurement window or perturbation.
- Runs of 90 min (30-40 ramp + 50-60 measurement) for arrival-mode
  experiments; sized reuse pool >= lambda_s x duration + N*.

Mode A (likely less aiperf work - investigate first): fixed-schedule
replay, which aiperf already auto-promotes trace datasets to. The
schedule pre-generates absolute timestamps (bootstrap cohort at t=0 +
staggered session starts + intra-session gaps) and fires regardless of
system state - the pure open loop, identical semantics to the DES
replay driver. Verify: per-session ordering is enforced when a turn's
predecessor is still in flight, and salting is available.

Mode B: session_rate pacing - Poisson admission at lambda_s with the
three ingredients above; within-session turns at completion + gap;
subagents unmetered; no substitution or request-rate pinning. Semi-open;
matches the fluid model's closed-per-session / open-arrivals variant.

Either mode supports the band block. Pick whichever needs less surgery
in aiperf; Mode A is preferred if the ordering constraint already
exists, because determinism also gives run-to-run comparability for
warm/cold pairs (same schedule, different initial cache state).

Cheap closed-loop hysteresis probe (no patch needed, add to E1 if
multi-stage runs are supported): one continuous run stepping conc
20 -> 160 -> 20 in stages, checking h(l) for path dependence. The model
predicts little closed-loop hysteresis; confirming that cheaply is
itself a validation point.

## Deferred (open-loop, once session_rate mode lands)

Warm-vs-cold pairs at fixed lambda_s, rate up/down hysteresis sweep,
mid-run flush -> stuck vs recover, shed -> recover. These are the band
experiments; nothing in the closed-loop set substitutes for them.

Update 2026-08-07: session-arrival mode landed and is validated; the
open-loop band track and the E-series re-prioritization now live in
experiment-plan-band.md.
