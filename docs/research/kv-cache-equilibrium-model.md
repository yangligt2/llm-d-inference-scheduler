# KV cache equilibrium model: hit rate, retention, and bistability

Status: research note, not committed. Working doc for the cache-capacity /
routing analysis started from a customer escalation (50% hit rate, TTFT > 6s
at 10 QPS with ~130k mean context on GLM-5.2 FP8 / 8x B200 nodes).

## 1. Concrete case that motivated this

- 10 QPS aggregate, mean input 130k tokens (p95 250k), ~800 output tokens.
- TP8 on 8x B200 (180 GB); MLA KV replicated across ranks, ~54 KB/token FP8.
- Per-node HBM KV pool at mem-fraction 0.80: ~0.95M tokens (~7-8 resident
  130k sessions). At 0.87: ~1.17M tokens.
- CPU offload tier: 2.4 TB pinned host RAM -> ~5.7M tokens/node.
- Prefill ~10k tokens/s/node (130k in ~13 s). TPOT ~12 ms.
- Customer runs prefix-aware (approximate) + queue-depth-aware routing.

Findings from the first analysis:

- The approximate prefix producer simulates a per-server GPU-only LRU
  (pkg/epp/framework/plugins/requestcontrol/dataproducer/approximateprefix).
  Under heavy eviction it produces false positives (routes to a loaded pod
  whose blocks are gone: queue wait + full prefill = the observed TTFT
  signature) and false negatives (CPU tier invisible).
- The precise producer indexes real BlockStored/BlockRemoved events including
  vLLM's OffloadingConnector (pkg/kvevents/event_dedup_filter.go), so both
  tiers are routable and eviction is ground truth.
- Precise scoring supplies the correct signal, but placement is still a
  weighted sum against the queue scorer; weights must let a ~1.0 prefix score
  dominate several requests of queue depth (misroute cost ~13 s prefill vs
  ~5 s queue wait).
- Routing accuracy is only half the problem; cache retention is the other
  half. Same symptoms, different fixes.

## 2. Fixed-point model (Che approximation + write-rate feedback)

Definitions (fleet-wide; N nodes cancel into total capacity):

- lambda: aggregate request rate (req/s)
- C + O: KV tokens written by a missed turn (full context + output)
- Delta: KV tokens written by a hit turn (input delta + output)
- S_tot = N * S_node: fleet cache capacity in tokens
  (per node: 0.95M HBM-only, 6.65M HBM+CPU for the case above)
- F(t): gap CDF - fraction of requests whose same-session predecessor
  completed <= t seconds ago; first turns count as gap = infinity

Equations:

    W(h)  = lambda * [ (1-h)(C+O) + h*Delta ]     aggregate KV write rate
    T(h)  = S_tot / W(h)                          LRU retention window (Che)
    h*    = F( T(h*) )                            equilibrium hit rate

The novelty vs classical LRU analysis: a miss writes ~65x more KV than a hit
(full-context re-prefill), so h feeds back into the retention window that
determines h. Phi(h) = F(T(h)) is monotone increasing, so multiple fixed
points (bistability) are possible.

### Closed form for a threshold workload

If fraction x of requests have gap > y and the rest have gap <= y, then
h = 1-x is an equilibrium iff

    N * S_node >= lambda * y * [ x(C+O) + (1-x)Delta ]

Max sustainable gap at h = 1-x:

    y*(x) = N * S_node / ( lambda * [ x(C+O) + (1-x)Delta ] )

Numbers for N=16, lambda=10, C+O=131k, Delta=2k:

    x     W(1-x)      y* HBM-only (15.2M)   y* HBM+CPU (106.4M)
    0.1   149k tok/s  102 s                 715 s (~12 min)
    0.2   278k tok/s  55 s                  383 s (~6.4 min)
    0.3   406k tok/s  37 s                  262 s (~4.4 min)
    0.5   664k tok/s  23 s                  160 s (~2.7 min)

### Equilibrium structure

- Bistability: h=0.9 (retention ~12 min) and h=0.5 (retention ~2.7 min) can
  both be stable if the workload has gap mass between the two windows. Which
  basin you land in depends on history (warm benchmark vs burst-perturbed
  production), i.e. hysteresis. This is the same mechanism as metastable
  failures in distributed systems.
- Collapse floor at h=0: W = lambda*(C+O) = 1.31M tok/s.
  HBM-only: T(0) = 11.6 s -> if think time > 12 s, h=0 is absorbing (death
  spiral, no self-recovery). HBM+CPU: T(0) = 81 s -> turns returning inside
  81 s hit even from total collapse, so the system self-recovers. At these
  parameters the CPU tier's main job is deleting the bad equilibrium.
- Prefill feasibility overlay: h >= 1 - N*p_tpt/(lambda*C). For N=16 and
  p_tpt=10k tok/s: h >= 0.88. Equilibria below that are infeasible (unbounded
  queues; TTFT dominated by queue wait). Sizing N for the low equilibrium
  also multiplies S_tot, which raises the equilibrium h; solve jointly.
- Solve by iterating h <- F(T(h)) from h=1 (converges to highest fixed point)
  and from h=0 (lowest); differing limits = bistable region.

## 3. Abstracted problem

Given prefill max throughput p_tpt, decode max throughput d_tpt, N nodes,
per-node KV pool c (HBM, optionally + CPU tier), a traffic pattern, a think
time distribution, and l concurrent sessions: predict hit rate, achieved
RPS, TTFT, TPOT; find c_crit(l) below which the system enters (or can be
trapped in) the bad equilibrium.

Key dimensionless ratios the answer should collapse to:

- working-set pressure: N*c / (l * E[context]) - above ~1 LRU churn never
  bites and there is no bistability
- gap-to-retention: T(h) vs gap distribution quantiles
- prefill utilization: lambda*(1-h)*E[C] / (N * p_tpt); decode utilization
- The bistable boundary is a saddle-node bifurcation: Phi(h)=h, Phi'(h)=1.

Related work: Che's characteristic-time approximation (LRU/CDN literature);
metastable failures (Bronson et al.); LLM serving simulators (Vidur etc.)
model scheduling latency, not cache equilibrium dynamics - this angle appears
unexplored.

## 4. Solution plan

Phase 1 - fluid fixed-point model (fast, hypothesis generator):
- Derive F(t), E[C] trajectory, Delta, class rates from the workload spec.
- Add: CPU tier as second characteristic time; closed-loop arrival coupling
  (lambda = sum_i l_i / E[cycle_i], cycle = TTFT + decode + think);
  M/G/1-style queue wait for TTFT; prefill/decode feasibility overlay.
- Output: equilibria + stability, (c, l) phase diagram, c_crit(l) locus.

Phase 2 - discrete event simulation (validation + latency distributions):
- Lightweight custom simulator (SimPy-style, ~500-800 lines Python), NOT an
  engine-fidelity fork. Calibrate p_tpt, d_tpt, chunked-prefill interference
  factor from a few real single-node benchmarks.
- Virtual write clock trick makes LRU exact and O(1) per request: each node
  keeps a monotone counter of KV tokens written; each session stores the
  counter at last touch. Prefix resident in HBM iff clock - last_touch < c;
  in CPU tier iff < c + c_cpu. No block bookkeeping.
- Pluggable router: perfect-affinity / precise-scorer / approximate-scorer /
  weighted queue mix. CPU restore bandwidth budget.
- Experiments: c and l sweeps vs fluid prediction; hysteresis (2x burst for
  60 s, does h return); routing-policy comparison inside the bistable region
  (this closes the loop on the token-aware-routing question).

Phase 3 - analytical tightening:
- Closed-form c_crit under threshold-gap model; tangency asymptotics under
  lognormal F; error bounds via Che approximation literature.

Scope warning: resist engine fidelity (block sizes, scheduler ticks, kernel
timings). The phenomenon lives at write rates, capacities, gap distributions.

## 5. Calibrated workload model (real traces)

Fitted to cc-traces-weka-062126-256k, 393 conversations. Convention: every
lognormal's mean/std_dev are ARITHMETIC moments implied by the log-space MLE
fit - moment-match back to (mu, sigma) when sampling.

```yaml
shared_system_prompt_len: 0        # corpus encodes no cross-conversation
                                   # sharing (hash ids are trace-local); ~3000
                                   # as prior knowledge about Claude Code

dynamic_system_prompt_len:         # KS D=0.063 (single lognormal: 0.219)
  type: lognormal_mixture
  min: 640
  max: 162624
  components:
    - weight: 0.87                 # fully loaded system prompts (tools, CLAUDE.md)
      mean: 52858
      std_dev: 18110
    - weight: 0.13                 # bare/lightweight sessions
      mean: 23285
      std_dev: 48078
  # simplest acceptable single dist: truncated normal(48967, 23198), D=0.109

turns_per_conversation:            # KS D=0.058
  type: lognormal
  min: 1
  max: 1495
  mean: 64
  std_dev: 66

input_tokens_per_turn:             # KS D=0.013 (single lognormal: 0.068)
  type: lognormal_mixture
  min: 1
  max: 197760
  components:
    - weight: 0.85                 # organic turns: user prompts + tool results
      mean: 2882
      std_dev: 11880
    - weight: 0.15                 # narrow spike at ~1.2k: fixed-size payloads
      mean: 1199
      std_dev: 261
  # single fallback: lognormal mean 2297, std_dev 5909 (D=0.050)

output_tokens_per_turn:            # KS D=0.037
  type: lognormal
  min: 2
  max: 40339
  mean: 1258
  std_dev: 2977

max_model_len: 256000

inter_turn_think_time:             # next request = prev completion + think
  zero_fraction: 0.356
  positive:                        # KS D=0.017 (single lognormal: 0.191)
    type: lognormal_mixture
    components:
      - weight: 0.66               # agentic pace (tool loop)
        mean: 2
        std_dev: 1
      - weight: 0.34               # human pace + idle tail (up to days)
        mean: 263
        std_dev: 7462

compaction:                        # without this, 66-turn conversations overflow
  trigger_context_len: 249000      # p50 of context right before compaction
  post_compaction_context: 73800   # = system prompt + summary; summary alone:
  summary_len_mean: 28800          #   p50 22400

subagents:                         # ~58% of all requests
  conversation_has_subagents: 0.445
  groups_per_conversation:         # given >= 1; runs concurrently with main
    type: lognormal
    min: 1
    max: 153
    mean: 8
    std_dev: 13
  turns_per_group:
    type: lognormal
    min: 1
    max: 642
    mean: 19
    std_dev: 24
  seed_prompt_len:                 # subagent system prompt + task description
    type: lognormal
    min: 640
    max: 199424
    mean: 36223
    std_dev: 21643
  input_tokens_per_turn: { type: lognormal, min: 1, max: 161950, mean: 3043, std_dev: 11850 }
  output_tokens_per_turn: { type: lognormal, min: 2, max: 59903, mean: 537, std_dev: 762 }
```

### How the calibrated spec maps into the model

The fluid model consumes the spec only through a few functionals, so realism
lands mostly in the DES sampler, not the math:

- Mixtures: pass through untouched (they only change how F and moments are
  computed).
- Bimodal think time: 0.356 zero + 0.644*0.66 agentic ~= 78% of main-thread
  turns arrive within seconds -> near-guaranteed hits under any sane
  retention window IF routing keeps the session home. The ~22% human-pace
  tail (mean 263 s, std 7462 s) carries the entire capacity sensitivity.
  The trace validates the two-point threshold model rather than breaking it.
- Zero think time makes the workload closed-loop: arrival rate is endogenous
  (lambda = l / E[cycle]). One extra fixed-point variable; self-throttling.
- Compaction: replaces the ill-defined max_model_len truncation policy with a
  renewal process. Context is a sawtooth: grow from ~74k (or initial ~53k) by
  ~3-4k/turn to 249k, reset with a forced full miss. ~45-50 turns per cycle
  -> ~2% forced misses. Gives a well-defined stationary E[C] and E[write per
  miss].
- Subagents: second workload class (own prefix trajectory ~36k seed, ~19
  agentic turns, short-lived, high locality). Multi-class Che: shared T,
  W = sum over classes; h_i = F_i(T). Adds bookkeeping, not mechanism. Main
  effect: ~doubles request volume and adds distinct-prefix churn, shrinking T
  for everyone; also adds within-conversation concurrency bursts.
- Structural hit ceiling from forced misses: first turns (~1/64), compaction
  resets (~2%), subagent seeds (~1/19 of subagent turns), human-pace gaps
  beyond T. Ceiling lands around h ~= 0.85-0.9; observed 50% would sit far
  below it, consistent with the bad-equilibrium hypothesis.

## 6. Phase 1 results

Implementation and figures: kv_equilibrium/ (README.md there has run
instructions and the full result list). Headlines, all at N=16 with the
B200 constants and the calibrated CC-trace workload:

- Structural token-hit ceiling 96.3%; the agentic gap mass makes the
  workload cache-friendly under perfect routing.
- Customer operating point with CPU tier: monostable good (h_tok 96%,
  TTFT ~4.5 s); the binding constraint is running-request KV residency
  (rho_kv ~0.98), not cache retention. HBM-only: degraded.
- Routing accuracy a=0.5 reproduces the escalation (h_tok 48%); the
  prefill-saturation cliff sits between a=1.0 and a=0.9.
- Closed-loop arrivals bend the fixed-point map downward and suppress
  bistability; the bistable band lives in the OPEN-LOOP plane (fixed
  offered rps), where the customer point (10 rps, 0.95M tokens) lands
  exactly on it in HBM-only, and the CPU tier erases it. Benchmarks and
  rate-limited producers run open loop; production chat traffic is closed
  loop. The two regimes have different failure physics.
- c_crit(l) is ~linear: 0.29M at l=100 up to 3.18M at l=800; no good c
  exists at l>=1600 (compute bound, not cache bound).
- Hysteresis quantified (open loop, c=0.95M, HBM-only): collapse at
  ~10.8 rps sweeping up, recovery only below ~8.0 rps sweeping down.
  Trajectory demo (kv_equilibrium/dynamics.py): a 2-minute 2x burst at
  9 rps leaves the system stuck in the bad state indefinitely at the
  pre-burst load; a 3-minute shed below the band's lower edge restores it.
  The CPU tier absorbs the same burst and self-recovers.
- Novelty positioning: cache metastability is known in general systems
  (Bronson HotOS'21, Huang OSDI'22); LLM queueing-stability work treats
  memory as a constraint, not feedback state. New here: prefix-cache hit
  rate as an endogenous fixed point with miss-write amplification, the
  computable (capacity, load) phase boundary, open- vs closed-loop
  stabilization, and the CPU tier deleting the bad equilibrium.

## 7. Phase 2 results (DES validation)

kv_equilibrium/des.py + des_validate.py: independent discrete event
simulation (virtual write-clock LRU, real queues, affinity routing, replay
and closed-loop drivers). Findings:

- Customer point matches the fluid model closely (+CPU: h 95.8% vs 96.0%,
  TTFT 4.3 vs 4.5 s; HBM-only: 91.4% vs 88.6%).
- The bistable band is confirmed by cache-flush experiments: HBM-only
  self-recovers at <= 8 rps, stays degraded at 9, loses the warm branch at
  >= 10. DES band ~ [8.5, 9.5] vs fluid [8.0, 10.8]: workload burstiness
  (subagent fan-outs) and head-of-line blocking weaken the warm branch
  relative to the mean-field prediction.
- The CPU tier deletes the bad equilibrium in the DES exactly as in the
  fluid model, and its slot-saturation onset (~10 rps) lands where the
  fluid rho_kv constraint predicted.

## 8. Publication plan (revised 2026-07-29: 64x GB200 available)

Hardware: 16 GB200 nodes (64 GPUs) in one domain. Existing data: ~94
inference-perf runs at llm-d/guides/subslicing/inf-perf/reports/ replaying
the SAME cc-traces corpus (weka_trace_replay) with Qwen3-Coder-480B-A35B
FP8, TP4/TP8, 1-2+ replicas, concurrency sweeps conv20-conv220, three tier
configurations (HBM-only, CPU offloading, WEKA storage tier). Example
(weka tp4 conv120): 4851 reqs / 1914 s, mean prompt 80k, mean output 856,
input throughput 202k tok/s, TTFT mean 4.7 s p95 21 s, schedule_delay
p95 1660 s (closed-loop backlog).

Primary target: OSDI '27 (deadline ~Dec 2026), measure -> model -> mitigate:
1. Measure: metastability on real GB200 fleet with real agentic traces.
2. Model: phase boundary; dimensionless design rule; 3-tier extension
   (HBM/CPU/storage) where the storage tier converts the capacity cliff
   into a restore-BANDWIDTH cliff - new physics vs the 2-tier model.
3. Mitigate (implemented in llm-d, framed generally):
   a. basin-aware admission control (principled Mooncake early-reject),
   b. automatic recovery controller (detect bad basin -> staged shed),
   c. tier sizing rule from c_crit(l) that deletes the bad equilibrium.

Portfolio hedge (nothing wasted on rejection or a missed gate):
- Gate ~mid-Oct 2026: real-cluster bistability shown AND mitigation
  prototype improving recovery? -> OSDI Dec. Else -> SIGMETRICS winter
  deadline (~Feb 2027) with the measurement+model paper (everything
  except the mitigation section carries over verbatim).
- Resubmission ladder: OSDI Dec'26 -> SIGMETRICS Feb'27 -> SOSP ~Apr'27
  -> MLSys fall'27. Trace characterization can stand alone (IISWC-class)
  if the main paper needs splitting.
- Skip fall'26 deadlines: too soon to include real-cluster band evidence.

Work items:
1. NOW, zero GPU time: mine the 94 existing runs - calibrate p_tpt, TPOT,
   prefill/decode interference; validate the model's closed-loop l-sweep
   predictions against conv20-conv220 x {no-offload, CPU, WEKA}. This is
   the (c, l) plane's real-world cut, already measured.
2. Harness gap: cached-token observability (summary reports show
   prompt_tokens.cached = 0 - not captured). Scrape vLLM prefix-cache
   hit metrics per run before any new experiments.
3. New cluster experiments (the band lives in open loop; existing runs
   are all closed-loop concurrency): session_rate mode sweeps, warm-vs-
   cold starts at the same rate, mid-run cache flush, shed-recover.
   16 replicas x TP4 matches the model's N=16 exactly.
4. Model constant swap: Qwen3-Coder is GQA (KV sharded across TP ranks),
   not MLA (replicated) - different KV/token constant, and a generality
   win: two attention architectures in one study.
5. Phase 3 analytics: closed-form c_crit, tangency condition, band-width
   asymptotics, dimensionless collapse figure; add restore-bandwidth
   ceiling for the 3-tier extension.
6. Second public-trace calibration (Mooncake / Azure LLM traces) +
   clearance for the internal trace's fitted distributions.
7. Thorough related-work sweep: full instructions in
   kv_equilibrium/related-work-sweep.md (claims C1-C6, verdict taxonomy,
   seed papers per area, 4-pass method, deliverables incl. go/no-go
   memo). Framing: first predictive, workload-calibrated instance in LLM
   serving, NOT discovery of metastability.
8. DES hygiene: multi-seed CIs, burstiness ablation.

Dropped: precise-vs-approximate llm-d scorer comparison (repo engineering,
not paper material). The generalized routing-accuracy parameter `a` stays.

## 9. Open questions

- Does the customer's fleet size satisfy the prefill feasibility line at the
  target h?
- Measure the customer's actual F(t) and locate their equilibria.
- Subagent turn think time not separately fitted (assumed agentic pace).
- Cross-conversation sharing set to 0 (conservative); real Claude Code shares
  ~3k system prompt.
- CPU restore bandwidth as a potential bottleneck when the CPU tier becomes
  the effective prefix store.
