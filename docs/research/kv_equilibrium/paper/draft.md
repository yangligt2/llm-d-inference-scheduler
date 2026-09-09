# Metastable KV-cache equilibria in multi-replica LLM serving

Draft conventions. Internal evidence markers are retained for
auditability and are removed at camera-ready: [R<n>] refers to result
n of the campaign's research-status register (research-status.md);
[C<nn>] refers to a row of the claims map (paper/claims-map.md);
(path) names a data or analysis artifact. Literature citations use
[bibkey] and resolve in the References section. Figures are numbered
in order of appearance; image paths are under kv_equilibrium/out/,
with the composite paper figures (1-3, 7, 9) in out/paper/ and
generator scripts kv_equilibrium/fig_*.py.

Notation, defined once at first use and used throughout: h is the
prefix-cache hit rate (Section 3.1); lambda_s is the session arrival
rate in sessions per second, abbreviated sps (Section 3.2); N is the
replica count of the fleet a single router instance spans, and
N-replica fleets are written Nx (Section 3.1); kv115 is the
fleet-mean KV occupancy over the [115, 120)-min window (Section 4.5);
B_r is the effective per-replica restore rate, N*B_r its fleet
aggregate (Section 5.1); the per-8x-equivalent rate is lambda_s x 8/N
(Section 4.5).

## Abstract

Multi-replica LLM serving with prefix caching contains a feedback
loop: a cache miss forces re-prefill of the session's full context,
and the resulting KV writes evict other sessions' prefixes, so the
cache write rate depends on the hit rate itself. We show that this
feedback produces metastable failures. Under agentic trace replay on
TP4 GB200 fleets of 4 to 16 replicas serving Qwen3-Coder-480B FP8,
an eviction-scale load surge can push a fleet into a cold absorbing
state in which the hit rate falls from roughly 0.94 to 0.02-0.03,
median TTFT rises to roughly 240 seconds, and the fleet shows no
spontaneous recovery over horizons of up to 300 minutes. The cold
state is sustained by the same base load the fleet served warm
before the surge, and it exhibits hysteresis: recovery requires
dropping demand well below the load the warm fleet handles
comfortably.

The transition into collapse is probabilistic rather than sharp.
Across repeated runs of an identical perturbation, low base rates
always recover and high rates always relapse, while intermediate
rates split between clean recovery, fast relapse, and a delayed
collapse that only 300-minute horizons reveal. Adding a host-RAM KV
tier transforms the failure instead of eliminating it. At
supercritical rates the tiered fleet enters a third regime,
restore-bound congestion, in which the hit rate stays high but most
hits are served through a saturated host-to-device restore channel
and the queue diverges slowly; tier capacity determines whether this
regime persists, falls through to cold collapse, or heals. Collapse
probability further depends on router span. At matched per-replica
load, a single 16-replica router shifts the collapse boundary to
lower rates and every observed 16-replica collapse is fleet-total,
whereas independent 8-replica shard routers contain every collapse
inside one shard. A router configuration without prefix affinity ran
warm at roughly half the baseline hit rate and collapsed with no
recovery phase, indicating that affinity carries both the warm-state
margin and the recovery path.

Finally, we present a fluid model and a discrete-event simulation
(DES) sharing one calibration in which every constant is measured or
read from deployed configuration, with a single fitted parameter,
the effective tier capacity. The model reproduces the structure of
the probability band, all four discriminators of the congested
regime, and the direction of the router-span shift emergently, with
no replica-count term. It does not reproduce the measured self-heals
of the tiered fleet, which we report as an open problem in modeling
concurrent KV restore channels.

## 1. Introduction

Prefix caching couples an LLM serving fleet's service capacity to
its own cache state. A request whose prefix is cached prefills only
the new tokens. A request whose prefix was evicted re-prefills the
full context, consuming prefill capacity and writing the full
context's KV blocks back into the pool, which evicts other sessions'
prefixes in turn. The effective service rate is therefore a function
of the hit rate, and the hit rate is a function of the eviction
pressure that the service process itself generates. Feedback loops
of this shape are the defining structure of metastable failures in
distributed systems [bronson2021metastable, huang2022wild]: a
trigger displaces the system into a degraded state, and a sustaining
effect keeps it there after the trigger is gone.

This paper measures that failure at multi-replica scale and models
it. On 8-replica TP4 GB200 fleets serving a 480B-parameter model
under open-loop agentic trace replay, an eviction-scale surge
overlay at base rate 0.022 sps drives the fleet into a cold state
that persists for as long as we observe it: h falls to 0.016-0.030
from 0.94 warm, TTFT p50 rises to 240 s, and no recovery occurs over
73 to 195 post-surge minutes across three runs, sustained by the
same base load the fleet served warm before the surge (Section 4.1)
[C01]. The identical perturbation applied across base rates yields a
probability band rather than a threshold: 0.017 sps always recovers,
0.022 always relapses, and 0.020 splits across three outcome
classes, including two runs that collapse organically near minute
240 with no new perturbation. Benchmark horizons shorter than
roughly 300 minutes therefore overstate stability at boundary
operating points [C02][C05]. The cold state also exhibits
hysteresis: the fleet cannot re-warm from cold at a load it serves
comfortably warm, and recovery requires dropping demand below the
band's lower edge [C06]. This combination of an absorbing degraded
state, probabilistic entry, and hysteretic exit is the
metastable-failure signature, here with full-context re-prefill as
the sustaining effect.

Two system parameters reshape the failure in ways that are, to our
knowledge, unmeasured elsewhere. First, a host-RAM KV tier does not
remove the failure; it transforms it into a third regime,
restore-bound congestion, in which the fleet holds a high hit rate
while the CPU-to-GPU restore channel pins near its congested-state
throughput and the queue diverges slowly (Section 5) [C10]. Tier
capacity, the one parameter the tier series varies, determines
whether that regime persists, falls through to cold collapse, or
heals (Section 5.4) [C13]; restore bandwidth was not varied, and its
effect on persistence is unmeasured. In one matched same-day pair at
the 0.020 boundary, the tier converted a collapsing operating point
into a complete self-heal [C12]. Second, collapse probability
depends on the number of replicas a single router instance spans, at
fixed per-replica load and fixed per-pod physics. The 16x collapse
curve sits left of the 8x curve: the mixed-outcome point moves from
0.020 to 0.0185 in per-8x-equivalent rate, roughly 7.5%, although
the edge brackets bound the shift only loosely (0 to ~16%). Every
measured 16x collapse is fleet-total, while independent 8x shard
routers contained every collapse inside the failing 8-pod bulkhead
(Section 6) [C15][C16][C18]. In one measured run (n=1), a router
configuration carrying no affinity signal ran warm at h 0.53 versus
0.94 and collapsed after the surge with no recovery phase [C22]:
routing affinity carries both the warm margin and the recovery path.

We accompany the measurements with a fluid model and a
discrete-event simulation (DES) sharing one calibration in which
every constant is measured or read from deployed configuration
except the effective tier capacity, a single fitted scale (Section
7) [C25]. The DES implements the deployed router algorithm with no
coordinator term and no N-dependent term. It reproduces the
no-offload band, all four congested-regime discriminators in 5 of 5
seeds, and the direction of the fleet-size shift emergently [C26].
Both model collapse curves sit left of the measured ones, a
documented reservation bias, so the model's quantitative claim is
the shift and the outcome-class structure, never absolute collapse
probabilities [C27]. The model's heal branch is a documented
failure: it produces zero heals where the hardware healed four
times at the same operating point. We report the failure, four
screened candidate mechanisms, and the surviving suspect, rather
than tuning the discrepancy away (Sections 7.6-7.7) [C30-C32].

Contributions:

- Measured absorbing collapse in multi-replica prefix-cached serving
  (fleets of up to 16 replicas), with a collapse-probability band,
  three outcome classes, horizon dependence, and hysteresis
  (Section 4) [C01-C07].
- A drain-depth separatrix: post-cancellation KV occupancy (kv115)
  separates fast relapse from non-fast outcomes in all 8 runs at the
  boundary point and adds signal beyond rate over 21 runs, presented
  as a mediating observable with stated confounds (Section 4.5)
  [C08-C09].
- The CPU-tier third regime, restore-bound congestion, and a
  tier-size series showing that capacity sets regime persistence,
  with the pinned restore channel setting congested-state throughput
  (restore bandwidth itself was not varied) (Section 5) [C10-C14].
- Router-span dependence of collapse probability, with config
  independence, refutation of load-imbalance and (for the measured
  EPP) coordinator-saturation mechanisms, an affinity-necessity
  ablation, shard containment, and measured per-pod scatter
  signatures (Section 6) [C15-C24].
- A calibrated fluid+DES model with a deployed-router layer, the
  emergently reproduced span-shift direction, executed falsifiers
  reported regardless of outcome, and documented failures
  (Section 7) [C25-C32].

All results come from one stack: one model, one corpus family, one
Endpoint Picker implementation, GB200 TP4 fleets. No claim transfers
beyond it (Section 9).

Figure 2, the measured multi-trajectory composite of Section 4.1,
is measured data, not model output.

## 2. Background and related work

Metastable failures. Bronson et al. [bronson2021metastable] define
the class through its three elements: a trigger, a sustaining
effect, and a degraded stable state. Huang et al. [huang2022wild]
study occurrences in production, including a look-aside-cache
reproduction in which a cache-hit-rate drop sustains overload.
Farahbakhsh et al. give the most compact statement of the prediction
agenda, a model sketch for whether a given request-response
structure admits metastable states [farahbakhsh2025modeling], with a
causal characterization in [farahbakhsh2026characterizing]. These
works establish the class and the agenda. This paper exhibits a
specific new sustaining mechanism, hit-rate-dependent KV write
amplification through full-context re-prefill, with a measured
probability band, measured dependence on tier capacity and router
span, and a calibrated model of the mechanism. The mechanism differs
from the look-aside instance in where the amplification lands.
There, misses amplify load onto a backing service behind the cache.
Here, a miss writes its full re-prefilled context back into the same
finite pool it missed in, evicting other sessions' prefixes: write
amplification into the cache's own capacity. Metronome
[meng2026metronome] applies the metastable label to LLM KV memory.
In its setting, full-duplex sessions pin monotonically growing
per-session KV state, and a linear open-loop fill model predicts an
abrupt stall that latency telemetry does not anticipate. That model
has one absorbing state and no feedback, hit rate, hysteresis, or
recovery structure, and its label rests on run-to-run outcome
variance. Its 14-of-20-versus-6-of-20 outcome split under identical
conditions independently corroborates outcome bimodality at fixed
operating points. The metastability here is of the Bronson kind: a
sustaining loop, demonstrated by hysteresis.

Bifurcation treatments of AI serving loops. van Rooyen
[vanrooyen2026collapse] develops first-order collapse, closed-form
spinodals, cusp-organized bistability, and hysteretic recovery for
the operating loop of an AI system under congestion-dependent
feedback, with an instrumented experiment. This is the closest
published vocabulary match to the equilibrium structure reported
here, but the physical feedback differs: there, uncertified output
re-enters the loop as added load, a retry-type amplification,
whereas here the feedback channel is the cache state itself, through
full-context re-prefill on miss. On abstract-level review (the
full-text review is pending before submission, Section 9), that work
carries no cache state variable, no phase boundary in (capacity,
load), no workload calibration, and no serving-system validation of
a cache mechanism. The two are complementary instantiations of the
same fold/hysteresis mathematics; our contribution is the
cache-feedback instantiation with measured-constant calibration and
multi-replica validation.

Queueing stability for LLM inference. Nie et al. [nie2026queueing]
give a queueing-theoretic stability framework for LLM inference
under KV memory constraints. Dai et al. [dai2025throughput] prove
throughput-optimality of work-conserving schedulers in a fluid-limit
framework covering agentic workloads. Dong and Cao [dong2026flow]
derive stability conditions for admission-budgeted scheduling that
prevents KV-utilization surges. In all of these the service rate is
cache-independent and memory enters as a constraint. With hit-rate
feedback the effective service rate is state-dependent, and the
stability region acquires a bistable band that work-conservation
arguments do not see. Our closed-loop measurements (Section 4.4)
locate the arrival semantics under which the constraint-style
analyses apply. Ao et al. analyze service-induced congestion in
memory-constrained serving [ao2026congestion], in a research line
with fluid-guided scheduling under endogenous per-request memory
growth [ao2025fluid]; published summaries surface
multiple-equilibria and limit-cycle language for its
admission/eviction dynamics. On abstract-level review its mechanism
is memory growth during service, not prefix-cache feedback; the
full-text review is pending before submission (Section 9).

Cache-aware routing. DualMap [yuan2026dualmap] engineers the
affinity-versus-load trade-off with dual-hash power-of-two-choices
mapping and SLO-triggered fallback. Continuum [li2025continuum] pins
KV across tool-call gaps with a TTL. CacheScout
[zhang2026cachescout] learns agent execution transitions to guide
eviction and prefetch. These works optimize the trade-off's
performance. We show the trade-off has a stability dimension: the
affinity term is what keeps the fleet on the warm branch and carries
the recovery path (Section 6, one measured run), and the span of the
balancer sets collapse probability and blast radius, quantities
absent from their evaluations.

Tiered KV caches and restore bandwidth. Mooncake [qin2025mooncake]
trades storage for computation in a KVCache-centric architecture and
motivates early rejection under overload. CacheFlow
[nian2026cacheflow] identifies KV restoration as a dominant
bottleneck and parallelizes it across tokens, layers, and GPUs.
Kareto [zheng2026kareto] treats tier sizing as a multi-objective
steady-state optimization. Restore-bandwidth optimization and tier
sizing therefore exist as engineering problems. Unclaimed in this
literature is the persistent congested serving regime pinned at
restore throughput, with persistence set by tier capacity (Sections
5.1, 5.4), and the stability discontinuity in tier sizing, the
fall-through to cold collapse at insufficient capacity, which a
steady-state Pareto analysis cannot expose.

Classical cache theory. The characteristic-time frame of Che et al.
[che2002hierarchical], with the validity analysis of Fricker,
Robert, and Roberts [fricker2012versatile], describes an LRU cache
whose retention window is set by the aggregate write rate. The
prefix cache fits this frame with one addition outside its
assumptions: the write rate depends on the hit rate, because misses
write full contexts. The equilibrium analysis of this paper is the
characteristic-time fixed point with that feedback closed. Multiple
cache steady states are themselves classical. Rosensweig et al.
[rosensweig2013steady] show cache networks can be non-ergodic, with
the steady state depending on initial content placement. That
multiplicity is combinatorial, arising from placement dependencies
across an interconnected topology at fixed demand, with no load
parameter, no capacity-load boundary, and no hysteresis sweep. The
multiplicity here comes from a scalar write-rate feedback within a
single tier, which yields a load-parameterized bistable band and a
hysteresis loop. Denning's thrashing analysis
[denning1968thrashing], with its multiprogramming-level control, is
the classical ancestor of the operational response to such regimes;
the difference here is a measured probability band, hysteresis, and
coordination-layer dependence rather than a qualitative regime.

Observation base. CONCUR [chen2026concur] is the closest published
statement of the phenomenon: in agentic batch inference, KV usage
pins at 80-100% while the prefix-cache hit rate collapses and stays
low for most of execution (its Figure 3, from a large-scale
deployment), with a measured hit-rate knee against concurrency
(Table 2: 80.4/77.7/35.4% at batch 16/32/40), mitigated by an AIMD
admission controller keyed on cache usage and hit rate. It stops at
the observation and a preventive fixed-constant heuristic. Hit rate
is a measured signal there, never a modeled state variable; no
absorbing state, hysteresis, probability band, or recovery semantics
is measured or claimed; and its mechanism attribution is exogenous,
agents paused for tool calls losing LRU recency, not the miss-write
amplification that closes the loop here. TraceLab [zhu2026tracelab]
characterizes coding-agent traffic on a public corpus, including a
retention-window-to-hit-rate sweep and the finding that idle gaps
beyond ~5 min drive most misses, the gap structure the corpus gap
cap of Section 3.2 controls. Yuan et al. [yuan2026agentic]
characterize agentic workloads and, per abstract-level review
(full-text verification precedes submission), warn of a thrashing
regime once aggregate agent context exceeds GPU memory. Ranganathan
et al. [ranganathan2025incidents] taxonomize 156 high-severity
production LLM inference incidents. Nixon et al.
[nixon2026yearserving] release a year-long production serving
trace. The phenomenon class is widely observed and, prior to this
work, unmodeled for the prefix-cache feedback channel.

## 3. Measurement methodology

### 3.1 Stack and instrumentation

All measurements run on TP4 GB200 fleets of 4, 8, or 16 replicas
serving Qwen3-Coder-480B-A35B-Instruct-FP8 under vLLM with block
size 256; each replica holds a KV pool of 6486 x 256-token blocks
(13.28M tokens at 8 replicas) (experiment-env.md). Requests reach
the fleet through an Envoy front end and an Endpoint Picker (EPP).
The EPP plugin configuration is a first-class experimental factor,
selected per run among three configurations: a precise prefix-cache
config (KV-event token-based affinity; the baseline for the
2026-08-08+ series), an approximate-prefix config with no KV-event
pipeline, and a load-only config (queue and kv-utilization scorers,
no affinity signal) (experiment-env.md).

Server state is scraped from the per-pod metrics endpoints at 5 s
cadence. Fleet aggregates use the pod endpoints only, excluding the
service endpoint, which round-robins pods [C34]. Hit rate h is
computed as windowed counter diffs of vllm:prompt_tokens_cached over
vllm:prompt_tokens; the prefix_cache_queries/hits pair is not used
because it re-counts under pressure (experiment-env.md). On tier
fleets, ext_hit is the external (CPU-tier) hit token fraction,
vllm:external_prefix_cache_hits over external_prefix_cache_queries
(token counters; queries track prompt tokens), and the restore share
of hits, the model ext_share analogue, is the fraction of hit tokens
served from the tier (overlay-findings.md). Run labels (b1a2, b1c,
B2a, bimod5, ...) are internal run identifiers. Time series
are aggregated into 5-minute windows anchored to wall clock so
concurrent runs align (analyze_run_windows.py); window labels give
the window start. One gauge-semantics caveat applies throughout: the
vllm:num_requests_running gauge excludes requests in
WAITING_FOR_REMOTE_KVS, so server-side running counts do not equal
client-side load during restore phases [R9].

### 3.2 Workload

The primary corpus is a 393-trace agentic replay set (062126: 68266
requests, mean ~174 requests per trace); inter-request idle gaps are
capped at 10.5 s, the corpus p90 (experiment-env.md). Surge traffic
replays a disjoint 232-trace corpus (061526) so burst and base load
share no trace identity. Every replay instance is salted on its
first-turn prefix (cacheBust); without salting, prefix sharing
across replay instances inflates h (experiment-env.md).

Arrival semantics determine whether collapse is reachable, so we
state them precisely. Open-loop experiments use Poisson session
arrivals at rate lambda_s (sessions per second, sps) with
concurrency as an admission ceiling; requests within a session
remain completion-ordered. Closed-loop experiments meter a fixed
credit of in-flight work. The measured credit multiplier is ~1.45x
configured concurrency on this corpus (configured 40 -> achieved ~56
in-flight, 100 -> ~147), so all load-axis statements use achieved
in-flight [R8]. Request-metered rate mode is excluded from collapse
experiments: it re-issues work independently of completions, which
makes it a built-in retry storm, whereas completion-coupled session
arrivals defer rather than storm. Open-loop collapse experiments
therefore pin demand at the session level [R7][C33].

### 3.3 Perturbation protocol

Each collapse experiment resets every pod's prefix cache, runs base
load at lambda_s, and at t ~ +62 min launches a surge overlay
without cache reset: 0.25 sps for 2700 s (the standard surge; a
900 s variant probes the duration axis), with nominal cancellation at
t ~ +107 min (lab-notebook-2026-08-08). The surge generator cancels
its entire session population on exit, so all post-cancel dynamics
are sustained by the base load alone (lab-notebook-2026-08-08).
Horizons run 150-300 min; Section 4.3 shows why the long horizon is
necessary. Closed-loop states are held 65 min before being read as
stationary [R8].

![Figure 1](../out/paper/fig_protocol.png)

Figure 1. Perturbation protocol timeline. Prefix-cache reset on all
pods at t=0; base Poisson session arrivals at lambda_s sustained to
the end of the 150-300 min horizon; eviction-scale surge overlay
(0.25 sps x 2700 s, disjoint corpus, no cache reset) over [62, 107)
min, with the surge population cancelled at t=107 so the post-cancel
drain-vs-catch-up race over [107, ~120) min is base-sustained. The
warm state is read over [30, 60] min, kv115 (Section 4.5) over
[115, 120) min, and end-state outcomes are classified over
[270, 295] min (cold if mean h < 0.15).

### 3.4 Comparability, run-to-run variance, and artifact rules

Five factors are recorded per run and held fixed within any
comparison: router config (EPP ConfigMap), corpus, gap cap, salt,
and duration [C34]. The July/early-August reference series ran under
different EPP configs and unsalted generators and is excluded from
all fits (experiment-env.md). Realized request rate varies ~+-0.4
req/s between runs at fixed lambda_s and does not order outcomes in
the series where this was checked (the 8x-0.020 and tier series)
[R2][C04]. Consequently, every probabilistic statement in this paper
is an outcome count over repeated runs, never a response inferred
from any single run. Runs are treated as statistically independent:
every run starts from a per-pod cache reset, and the namespace-split
check (shard-a vs shard-b outcomes, contradicted by
ppc-shard-a3-020) supports run-to-run variance over a fixed
namespace effect. Two dependence structures remain and are
carried as confounds (Section 9): shard runs executed pairwise in
shared windows over the shard-a/shard-b namespaces, and the b1a2 and
lh040 pairs are same-config replicates across days
(separatrix-findings.md).

Two artifact-existence rules make absent data auditable rather than
silently missing. First, aiperf artifacts exist only after
end-of-run export (one hung export in ~40 runs through 08-13, zero
in the 19-run 08-15/16 window). Second, capacity reclaim destroys
un-scaled fleets, so an unconditional scale-down is scheduled at
window start for T-15 min [R12][C35].

## 4. Collapse phenomenology (no-offload)

### 4.1 Anatomy of an absorbing collapse

After the standard surge on an 8-replica no-offload fleet at base
rate 0.022 sps, the system does not return to its pre-surge
operating point. It enters a cold state with hit rate h 0.016-0.030
(pre-surge warm h ~0.94), TTFT p50 rising to 240 s, queue growth
~1.1 requests/min to a waiting depth of 289, and throughput pinned
at 1.2-1.4 req/s. No recovery occurs over the observed post-surge
horizons (n=3 runs: b1a2, b1a2-rep, ppc-lh-noofl; ~73 post-surge
minutes on the two 180-min horizons, 195 on the one 300-min horizon)
[R1][C01]. The state is self-sustaining: the surge process no longer
exists after cancellation, and the base load that the same fleet
served warm before the surge maintains the collapse indefinitely on
the measured horizon.

The mechanism visible in the measured trajectories is a
drain-vs-catch-up race. The surge evicts the base sessions'
prefixes. After cancellation, the deferred base reservoir drains
back as catch-up flux. If that flux exceeds the cold-branch service
capacity before prefixes re-warm, misses regenerate the eviction
pressure and the fleet locks into the cold state [R1][R2].

![Figure 2](../out/paper/fig_arcs_composite.png)

Figure 2. Measured trajectories, one per regime class, under the
identical eviction-scale surge (shaded, t=62-107 min); all curves
are 5-min windows from per-pod scrapes, no model output. Warm
recovery at 8x-0.017 (h returns to ~0.95, wait ~0); absorbing
relapse at 8x-0.022 no-offload (h 0.013-0.030 after min 200, wait
climbing ~1.4/min to ~290 by min 290); organic-late collapse at
8x-0.020 no-offload (warm until h falls from 0.89 at min 240 to 0.05
by min 280); restore-bound congestion at 8x-0.022 tier-500 (h
0.65-0.77 with ext_hit 0.62-0.75, dashed, and linear wait divergence
~0.8/min); tier full heal at 8x-0.022 tier-375 (h 0.97, wait ~0 at
min 300).

### 4.2 The collapse-probability band

The identical perturbation applied across base rates yields a
probability band, not a threshold line. Outcome counts over 17 runs
[R2][C02]:

    base rate (sps)  runs   outcome
    0.012            2      recovers 2/2
    0.017            4      recovers 4/4 (150-180-min horizons;
                            post-surge KV 40-78% across runs)
    0.020            8      three outcome classes: clean survival
                            x3, organic-late collapse x2 (cold by
                            ~min 240), fast relapse x3 (onset min
                            ~130-150); collapse 5/8 by 300 min
    0.022            3      relapses 3/3

All three 0.022 runs relapsed; up to these n, the counts place the
hard-relapse edge in (0.020, 0.022]. These are outcome counts; no
continuous p(collapse | rate) curve is fitted to them. Among the
0.020 runs, realized request rate does not order outcomes: a fast
relapse occurred at realized 1.62 req/s while a clean run held at
1.78 [R2][C04].

![Figure 3](../out/paper/fig_band_tally.png)

Figure 3. Outcome counts under the identical perturbation on the 8x
no-offload fleet at four base rates (n=17 runs): 0.012 recovers 2/2
and 0.017 recovers 4/4 (clean recovery); 0.020 is bimodal over 8
runs with clean survival x3, organic-late collapse x2 (cold by ~min
240), and fast relapse x3 (onset min ~130-150), collapse 5/8 by 300
min; 0.022 relapses 3/3, placing the hard-relapse edge in
(0.020, 0.022].

Two threshold axes are each indicated by one measured contrast pair
[R2][C03]. On the duration axis, at 0.022 the 900 s surge recovered
while the 2700 s surge relapsed, consistent with the surge needing
to outlast the prefix-eviction time; a single 900 s recovery is also
consistent with chance under any relapse probability materially
below one. On the flux axis, run b1c (0.017) served 4.9 req/s of
post-cancel catch-up traffic and stayed warm, while b1a2 (0.022)
re-entered collapse at 4.8. The instantaneous catch-up rate
therefore does not discriminate outcomes; the sustained arrival flux
lambda_s against drain headroom does, consistent with the band
counts (the pair differs in lambda_s). No response curve is claimed
on either axis.

### 4.3 Horizon dependence and the organic-late class

Surviving the perturbation does not imply long-term stability. At
8x-0.020, 2 of 8 runs that survived the surge and re-warmed
collapsed organically at ~min 240, with no new perturbation: session
deepening gradually raises KV occupancy until it pins, and per-pod
pinning is near-synchronous (2/8 pods to 8/8 within one 5-min
window) [R3][C05]. This class is visible only at the 300-min horizon;
60-180-min runs overstate stability at this operating point. The
0.017 row of the band table carries the corresponding caveat: its
150-180-min horizons would not see an organic tail if one exists
(separatrix-findings.md).

### 4.4 Irreversibility and the closed-loop contrast

The cold state exhibits hysteresis. The same fleet that serves the
base load warm cannot re-warm from cold at that load, and recovery
requires dropping demand below the band's lower edge; in the
closed-loop experiments, each in-flight level has a unique
equilibrium and recovery occurs when the in-flight credit is lowered
[R1][R8][C06]. The collapse is therefore a
bistable-band phenomenon, not a capacity shortfall: the warm and
cold branches coexist at the same demand.

Closed-loop (completion-gated) arrivals self-stabilize instead of
collapsing. The measured boundary sits at achieved in-flight ~73
warm versus ~103+ degraded; degraded states are stationary rather
than absorbing; and the throughput function F(T) shows a flat
segment with cap/T co-movement [R8][C07]. The falling segment of
F(T) is unreachable statically and was not observed. Absorbing
collapse requires demand that does not yield to backpressure, either
inelastic request-pinned generation or a deferred session reservoir
whose refill outpaces its drain [R7][C07]. The open-loop
session-arrival protocol of Section 3 realizes the second condition,
which is also the condition agentic workloads realize.

### 4.5 The drain-depth separatrix

The post-cancel race of Section 4.1 has a measurable state variable:
fleet-mean KV occupancy in the [115, 120)-min window (kv115), which
opens 8 min after nominal surge cancellation
(separatrix-findings.md). At 8x-0.020, kv115 separates fast relapse
from non-fast outcomes in all 8 runs (two of the five non-fast runs
later collapse organically): fast minimum 0.735, non-fast maximum
0.663 [R15][C08]. A shallow drain means the catch-up flux
re-inflated KV before prefixes re-warmed; the race is already lost
when the window closes. The kv115 reading precedes erosion onset in
20 of 21 fitted runs, and kv110 does not separate (one survivor read
0.674
mid-drain), so t=115 is the earliest clean read point
(separatrix-findings.md).

Across the 21 fitted standard-surge runs (10 events; ppc-n16-inv040
is excluded because its surge backlog was still pinned at t=115 and
its horizon ends at 135 min), a Firth-penalized logistic fit of
p(fast | kv115, rate) gives kv115 signal beyond rate (penalized LR
p ~ 0.044). The exact stratified permutation test over the two
mixed-outcome strata gives one-sided p = 3/112 = 0.027. The signal
is 8x-borne: within the 8x-0.020 stratum the three fast runs hold
exactly the three highest kv115 values (p = 1/56 = 0.018), while the
16x-0.037 stratum (n=2) is anti-aligned (collapser 0.650 below
survivor 0.734) [R15][C08] (out/separatrix_draws.csv,
separatrix_fit.py). The within-stratum test treats the two
dedicated-fleet (non-shard) runs and the six shard runs as
exchangeable; the two organic-late runs are exactly the two
dedicated-fleet runs, and the conservative shard-only form of the
test gives p = 1/20 (separatrix-findings.md). Rates are compared
across fleet sizes as per-8x-equivalent rates (lambda_s x 8/N). The
fitted p=0.5 thresholds are kv115* = 0.79, 0.69, 0.63 at
per-8x-equivalent rates 0.017, 0.020, 0.022; the 0.020 value sits
inside both the within-stratum separation interval (0.663, 0.735)
and the pooled-8x interval across all three rates (0.683, 0.735).
At n=21 the threshold direction and location are established, the
steepness is not (the kv115 coefficient's Wald 95% interval spans
roughly (1, 39)) (separatrix-findings.md). kv115 also orders the
collapse-onset spectrum. Among the 12 fitted collapsing runs, pooled
across both fleet sizes, all three rates, and both collapse classes,
all of which co-vary with kv115 and onset, the rank correlation
between kv115 and onset time is -0.99: shallower drains collapse
earlier. Within-class ordering is not separately quantified
[R15][C08]. The covariate was identified mid-campaign, so these
p-values are not from a pre-registered test; the three 8x-0.020 runs
measured after it was identified landed on the hypothesized sides of
the threshold (separatrix-findings.md).

Two scope limits bound the claim. First, the threshold moves with
rate and fleet size: at 16x, the 0.034 point survived kv115 = 0.74
and a 0.037 run relapsed from 0.65, each a single-run point
observation (n=1 each) [R15][C09]. Second, kv115 does not predict
the organic-late class: those runs win the drain race from deep
drains (kv115 0.616 and 0.663) and collapse ~2 h later by a distinct
mechanism [R15][C09]. kv115 is a mediating observable of the
drain-vs-catch-up race, not a universal law or control input. In the
pooled logistic fit it is confounded with the N=16 indicator at
n=21, because every 16x run at the 0.020-equivalent point both
drained shallow and relapsed; the mediation interpretation rests on
the within-stratum permutation test and the model comparison of
Section 7 (separatrix-findings.md) [C08].

![Figure 4](../out/separatrix_fit.png)

Figure 4. Drain-depth separatrix. kv115 (fleet-mean KV occupancy
over the [115, 120)-min window) vs per-8x-equivalent rate for the 21
fitted runs, marked by outcome class; the line is the
Firth-penalized p(fast) = 0.5 contour (kv115* = 0.79/0.69/0.63 at
0.017/0.020/0.022). The two organic-late runs sit at the deep end
and are not predicted by kv115; the 16x points illustrate the
threshold's N-dependence.

## 5. The CPU-tier third regime and the size series

Adding a host-RAM KV tier (vLLM CPU offloading,
`kv-offloading-size`, a per-pod size setting; unit accounting in
Sections 5.5 and 7.2) to the 8x fleet does not remove the collapse
failure at supercritical rates. It transforms the failure into a
third regime, restore-bound congestion, whose persistence is set by
tier capacity [R4][R11]. This section characterizes the regime,
reports the measured falsifier of the fixed-restore-ceiling
interpretation, presents the one matched boundary pair, and gives
the tier-size results.

### 5.1 Restore-bound congestion at 8x-0.022

Under the standard perturbation at base rate 0.022 sps, the rate at
which the no-offload fleet relapses 3/3 into the cold absorbing
state [R2], an 8x tier-500 fleet enters a distinct degraded state in
4 of 6 runs (Section 5.4 gives the complete outcome counts). Four
discriminators
separate it from cold collapse, jointly present in all 4 congested
runs (a1, a1rep, lh-tier, bimod5; two at the 300-min horizon) [R4]:

- Hit rate stays high: h 0.70-0.85, with ext_hit 0.62-0.79 and
  restore share of hits 0.66-0.79 (both defined in Section 3.1).
  Most hits are CPU-tier restores, not HBM-resident prefixes.
- The fleet restore rate is pinned at 150-192k tok/s, which is
  0.81-1.04 of N*B_r for the effective per-replica restore rate
  B_r = 23k tok/s (calibration provenance in Section 7's constants
  table; per-pod plateau 21.4-24.0k tok/s across all four tier runs
  at both fleet scales while demand exceeds it).
- KV occupancy holds at 93-94%; the tier ingests new writes only
  (measured offload rate 50-78k tok/s tracks uncached prefill plus
  generation; restored blocks stay tier-resident)
  (overlay-findings.md, restore-model calibration).
- The queue diverges slowly and linearly, ~0.8/min over 195 min,
  with no transition to the cold state.

Against the cold absorbing state at the same operating point
(Section 4.1), the congested state delivers ~2.2x the throughput and
~4x better TTFT [R4]. The failure is not removed: the queue still
diverges, and the state persisted through both 300-min congested
runs [R4].

![Figure 5](../out/overlay_restore.png)

Figure 5. Restore-bound congestion at 8x-0.022, tier-500: measured
trajectories (h, fleet restore rate, wait) against DES bands (5
seeds, 300 min). DES curves are model output (Section 7); the four
regime discriminators, a pinned restore channel, linear queue
divergence, high h, and no cold collapse, are reproduced in 5 of 5
seeds. Model quantitative gaps (h 0.95 vs measured 0.70-0.85;
restore share of hits 1.0 vs 0.66-0.79) are stated in Section 7.

### 5.2 The pinned band is a state outcome, not a channel capacity

The interpretation of B_r as a hard per-node restore ceiling is
falsified by measurement. The two measured heal runs sustain 5-min
fleet restore
rates of 235,284 tok/s (cpuofl-a4-375-lh, t=70) and 278,161 tok/s
(cpuofl-500-bimod6, t=70), which is 1.28-1.51x N*B_r, and then run
their post-cancel restore phase at 0.14-0.56 N*B_r with wait 0.3-7
while KV drains from 0.83-0.86 at cancellation to 0.26-0.31 [R4].
Both measured values are reported; at n=2, no distribution is
claimed. The 150-192k tok/s band of Section 5.1 is
therefore a congested-state throughput outcome. The raw DMA link
runs at 151.5 GB/s = 1.19e6 tok/s per node at ~2% duty in the
congested state, so per-transfer overhead, not the link, binds there
(overlay-findings.md, calibration provenance). The serial FCFS
restore channel in the DES encodes this falsified ceiling
interpretation and stands as a documented model deficiency; its
concurrent-restore replacement fails the heal-branch screen and is
not adopted (Section 7) [R9].

### 5.3 Full heal at the boundary: one matched pair

At base 0.020, inside the no-offload probability band [R2], the one
measured 8x tier run fully absorbs the surge: ext_hit 0.42-0.73
for ~2 h with wait 1-9, restore share of hits decaying 0.64 to 0, KV
draining to 0.05, and a complete self-heal by the end of the 300-min
horizon [R5]. The same-day no-offload run at the same operating
point collapsed organically at ~min 240 [R3][R5]. This is one
matched same-day pair, n=1 per side. It demonstrates that the tier
can convert a collapsing boundary point into a full heal in at least
one run, and it supports no heal-probability claim at 0.020.

### 5.4 The size series: capacity sets persistence

Same-protocol runs at 8x-0.022 across `kv-offloading-size` values
250, 375, 500 (lab-notebook-2026-08-13/15) [R11]:

    size   outcome count         note
    250    cold collapse 1/1     enters congestion, then falls
                                 through it: ext_hit decays to 0.01
                                 as the working set outgrows the
                                 tier; the one 250 run
    375    healed 2/2            one run at elevated rate,
                                 realized 2.02 req/s
    500    4 congested,          congested runs include the two
           2 healed, of 6        300-min horizons of Section 5.1

The series separates two mechanisms. Tier capacity, the varied
parameter, sets regime persistence: a tier too small to hold the
live working set loses ext_hit and falls through congestion into the
cold state [R11]. The congested-state throughput level is the pinned
restore band of Sections 5.1-5.2. Restore bandwidth itself was not
varied, so its effect on persistence is unmeasured. The 375-vs-500
contrast (2/2 vs 2/6 heals) suggests a mild size effect but leaves
it unproven at these counts. Realized request rate does not order
outcomes across the series: the elevated-rate 375 heal ran at
realized 2.02 against a congested 500 run at warm realized 2.16, and
heals otherwise ran near 1.6 (lab-notebook-2026-08-15.md, S5/S6
verdicts) [R11].

![Figure 6](../out/overlay_tiercap.png)

Figure 6. Tier-capacity pair at 8x-0.022: measured size-250 and
size-500 trajectories with DES capacity-sweep bands (model output,
Section 7). The DES reproduces the direction and the
cold-persistence boundary of the pair, 250 falling through to cold
and 500 staying congested, but produces no heals at this rate; the
heal branch is a documented model failure (Section 7).

### 5.5 Tier-size boot limit

`kv-offloading-size` is RAM-backed at GB scale; the configured
unit-to-byte mapping is unconfirmed (Sections 7.2, 9). Size 650 does
not boot on these hosts: all 8 pods crash-loop with the gcsfuse
sidecar OOM-killed (pod memory request 620Gi against ~858Gi node
allocatable; the pinned tier plus the sidecar's uncapped file cache
does not fit) (lab-notebook-2026-08-15.md, S3 infra note) [R11]. The
executable size series therefore ends in (500, 650), scoped to these
hosts [R11], and no statement is made about sizes above 500.

## 6. Router-span dependence

Collapse susceptibility depends on the number of replicas a single
router instance spans, at fixed per-replica load and fixed per-pod
physics. This section states the probabilistic result, then works
through an elimination structure: config independence,
scale-invariant per-pod physics, refutation of load imbalance and
(for the measured EPP) coordinator saturation, an affinity-necessity
ablation, shard containment, and the per-pod signatures that survive
elimination.

### 6.1 Probabilistic left-shift of the collapse curve

At per-capacity-matched operating points the collapse-probability
curve shifts left with router span [R6]. The 16x single-router
sweep: 0.034 sps recovers 1/1 (n=1, the one measured run), 0.037
splits 1/2, 0.040 relapses 4/4 (one run truncated at 135 min with
its surge backlog still pinned, classified as collapsed at
truncation and excluded from the Section 4.5 fit, whose fast count
is therefore 3/3; one run under the approx config, Section 6.2). In
per-8x-equivalent rate these points sit at 0.017 / 0.0185 / 0.020.
The 8x sweep at the same per-capacity points: 0.017 recovers
4/4, 0.020 collapses 5 of 8, 0.022 relapses 3/3 (n=7 runs at 16x, 15
at 8x) [R6]. The mixed-outcome point moves from 0.020 (8x, 5/8) to
0.0185 (16x-0.037, split 1/2), a ~7.5% shift in rate; the edge
brackets bound the shift only loosely (0 to ~16%). The counts
bracket the shift but do not establish it statistically at these n
(16x-0.040 4/4 vs 8x-0.020 5/8; the 16x-0.034 anchor is a single
run), and an apparent steepening rests on the n=2 0.037 point; no
fitted or smoothed probability curve is claimed.

The 16x collapses also differ in kind, not only in rate. Every 16x
collapse is early-onset, with hit-rate erosion underway by minute
~125-155, and fleet-total, across 5 collapses spanning days and
configurations. The organic-late class of Section 4.3 does not
appear at 16x [R6][R10].

![Figure 7](../out/paper/fig_ladder_tally.png)

Figure 7. Collapse fraction per operating point on a shared
per-8x-equivalent rate axis, from the run records: 8x sweep 0/4 at
0.017, 5/8 at 0.020, 3/3 at 0.022 (n=15); 16x single-router sweep
0/1 at 0.034, 1/2 at 0.037, 4/4 at 0.040 (n=7; the 0.040 count
includes the 135-min truncated run, excluded from the Section 4.5
fit), plotted at 0.017 / 0.0185 / 0.020 per-8x-equivalent. The
mixed-outcome point moves from 0.020 (8x) to 0.0185 (16x), a ~7.5%
leftward shift; the 0.034 anchor is a single run. Dashed segments
are visual guides, not fitted probability curves.

### 6.2 Config independence

The 16x-0.040 relapse does not depend on the prefix-cache
implementation detail of the router. It reproduces under
precise-prefix-cache (3 runs) and under the approx baseline, which
runs no KV-event pipeline and no token-producer, in one run under
that config (n=1) [R10]. The relapse is therefore a property of
span-coupled routing over the fleet, not of any single scoring
pipeline.

### 6.3 Per-pod physics is scale-invariant

The span dependence cannot be located in the pods. The per-pod
decode interference fit tpot = 10.8 ms + 2.56e-4 (R/N)^2 holds in
the per-pod form; the alternative fleet-R form is falsified by the
saturated 4x windows (Figure 8, out/tpot_fit.csv) [R6].
Restore bandwidth is likewise per-replica (B_r; Section 5). With
per-pod service physics invariant in N, the N-dependence must live
in the coordination layer [R6].

![Figure 8](../out/tpot_fit.png)

Figure 8. Per-pod decode interference. Measured tpot vs per-pod
running load R/N across 4x/8x/16x windows; the per-pod quadratic
form fits all fleet sizes, while a fleet-total-R form fails on the
saturated 4x windows.

### 6.4 Candidate mechanism: load imbalance - refuted

Query-share dispersion across pods is N-invariant in every phase.
Warm-phase query-share CV is 0.46-0.48 at 4x, 0.34-0.51 at 8x,
0.46-0.56 at 16x; recovery-phase CV is 0.12-0.21 at 4x, 0.21 for the
recovering 8x shard run, 0.14-0.15 at 16x (15 runs;
out/perpod/spread_summary.csv) [R10]. The recovering shard run shows
higher share dispersion than the relapsing 16x runs at matched
relative times, the opposite ordering of what an imbalance mechanism
requires. The max-share ratio grows with N only as the expected
extreme-value bias of a maximum over N samples
(per-pod-spread-findings.md, finding 1).

### 6.5 Candidate mechanism: coordinator saturation - refuted for this EPP

EPP-side resources were scraped on all 19 runs of the measurement
window and are unsaturated throughout, including through three
reproducing 16x relapses [R13]. KV-event index admissions track
demand with no plateau (16x peak 3.3k/s, ~2x the per-shard
1.0-1.6k/s); event-pool queue depth is ~0 in every window; EPP CPU
uses 1.9 of 4 uncontended cores (shards ~1.1); index lookups take
0.4-0.9 ms; the scheduler runs ~0.1 ms end-to-end; remote
tokenization takes 230-273 ms per request, uniform across healthy
and collapsing runs. This rules out coordinator saturation for this
EPP implementation at these spans. It does not by itself
establish any alternative mechanism, and no claim is made for other
coordinator implementations.

### 6.6 Affinity necessity ablation

A load-only EPP configuration (queue and kv-utilization scorers
only, no affinity signal) at 8x-0.020 measures what routing affinity
carries [R14]. In the one measured run (n=1): warm h 0.53 versus
0.94 under precise-prefix-cache, with TTFT p50 2-4 s and wait 3-6
pre-surge, a degraded but serving warm state, followed by absorbing
collapse after the surge, cold by t=150 with no recovery phase, end
wait 215, TTFT p50 177 s. The necessity claim rests on the size of
the warm-margin loss and the absence of any recovery phase in this
run, not on an outcome frequency. In this run, affinity carried both
the warm hit-rate margin and the recovery path at a boundary point.

### 6.7 Shard containment

Two independent 8x routers over the same pod type at matched
per-capacity load bound the blast radius [R10]. Across 6 shard runs
in the window, every shard collapse (4, including the load-only
ablation) stayed inside its own 8-pod bulkhead; in both concurrent
mixed pairs (a2/b2, a3/b4) the sibling shard served untouched while
its partner collapsed. Every 16x single-router collapse (5, across
days and configs) was fleet-total. Containment is therefore a
measured property of the router span boundary, in the same fleet, at
the same per-capacity load.

### 6.8 Per-pod signatures: scatter and duplication

Three measured signatures separate 16x from 8x at matched fleet
state (per-pod-spread-findings.md, findings 2-4; out/perpod/*.csv)
[R10]:

1. Hit-rate dispersion at equal fleet h. Warm fleet h is 0.94 at
   every N, but warm per-pod h standard deviation rises 1.4-2.1x,
   from ~0.032 at 4x/8x to 0.044-0.067 at 16x; corr(share_i, h_i) is
   0.57-0.86 everywhere - busier pods run warmer - so the dispersion
   is a coordination signature, not a load-balance defect.
2. Excess KV occupancy and miss-write flux at matched re-warm state.
   At the matched t=115 window the 16x fleet (ppc-n16-lh040: h 0.88,
   kv 0.80, uncached 44.1k tok/s per-8x-equivalent) carries the same
   per-capacity session state in 0.15-0.20 more of its pool and
   sustains ~1.7x the per-capacity miss-write flux relative to the
   8x trajectories (shard-a-020: 0.92 / 0.61 / 24.2k;
   ppc-edge020-noofl: 0.93 / 0.62 / 24.5k), with a 4-5 point h
   deficit spread across the whole fleet (per-pod p25-max 0.87-0.92
   vs 0.91-0.95) and measured retention time 58 s versus ~190 s.
3. Staggered pinning cascade. The 16x relapse re-pins pod by pod -
   3/16 at t=115, 11/16 at t=120, 14/16 at t=125, 16/16 at t=130 -
   with per-pod h spreading to 0.10-0.67 before fleet-wide erosion,
   whereas the 8x organic collapse pins near-synchronously, 2/8 to
   8/8 within one 5-min window.

These observables are directly measured; their interpretation as
prefix scatter/duplication is a mechanism inference, supported
jointly with the ablation and coordinator evidence above. Client
records carry no serving-pod identity, so session-to-pod scatter
itself is not directly observable in the collected data.

![Figure 9](../out/paper/fig_cascade.png)

Figure 9. Per-pod dynamics through the post-cancel window (300 s
windows from raw per-pod counters). (a) Count of pods with KV gauge
> 0.85: the 16x relapse re-pins in a staggered cascade, 1/16 at
t=110, 3/16 at t=115, 11/16 at t=120, 14/16 at t=125, 16/16 at
t=130, while an 8x clean run at the matched per-8x-equivalent rate
never exceeds 3/8 transiently pinned pods over the post-cancel
windows t=110-180 (both fleets are fully pinned in the surge-tail
windows t=100-105). (b) Per-pod h median with p25-p75 band: both
fleets re-warm to comparable per-pod h by t=115 (16x median 0.88 vs
8x 0.92), then the 16x fleet erodes with widening dispersion
(per-pod h min-max 0.10-0.67 at t=135) while the 8x fleet holds
h ~0.90-0.94.

### 6.9 Surviving mechanism

With load imbalance refuted by the N-invariant share dispersion and
coordinator saturation excluded by direct measurement, the surviving
explanation is span coupling of the post-cancellation
drain-vs-catch-up race. A collapse seeds locally, and the shared balancer spreads cold
catch-up flux - full-context re-prefills for sessions whose prefixes
were evicted elsewhere - onto still-warm pods, duplicating prefixes
and eroding fleet h, while independent shards contain the same seed
inside one bulkhead [R10]. This is an elimination-plus-reproduction
argument, not a direct observation of scatter, and its two elements
carry different support. The duplication element rests on the
measured per-pod signatures of Section 6.8 jointly with the ablation
and coordinator evidence. The span-coupling element is additionally
reproduced by the discrete-event model, which carries the deployed
router algorithm and no N-dependent term and shifts the collapse
curve left emergently (Section 7) [R9]; whether the model's 16x
collapses also exhibit the Section 6.8 per-pod signatures has not
been checked (Section 9). The containment contrast itself is
demonstrated directly by the shard measurements.

## 7. Models: fluid and DES

### 7.1 Construction

Two model layers share one calibration. The fluid model
(fluid_model.py, overlay_b1_dynamics.py) evolves a session reservoir
with completion-coupled turn release, per-pod tpot interference, and
a contended fleet restore channel. Restores form a third max() term
in the waiting-time expression (the prefill and restore channels
serve different requests concurrently, so an arrival waits on the
bottleneck backlog, not the sum), achieved restore traffic advances
the HBM write clock, and the CPU tier churns at the measured
tier-ingest rate with hit-refresh [R9]. Arriving (salted) sessions
enqueue a forced full-miss first request as an explicit queue class.
Surge populations are cancelled at surge end, matching the
experimental protocol.

The DES (des_b1.py, subclassing des.py) adds discrete structure the
fluid cannot carry: watermark admission (waiting requests join a
node's batch, full KV need reserved, while the batch fits under the
KV headroom; the prefill engine stays serialized), a two-clock LRU
(the HBM clock advances with prefill, restores, and generation; the
tier clock with new writes only; touch stamps refreshed at decode
end), and a per-node FCFS restore channel at B_r through which
CPU-tier hits pass before prefill, with asynchronous onboarding
[R9]. A single-clock tier variant (tier churned by restores) was
rejected against measurement: it drives the tier to exhaustion and a
cold collapse by min 270 that the 300-min hardware run refutes, and
it contradicts the measured tier-ingest rate (overlay-findings.md).

The deployed-router layer, RouterSessionSim, replaces the idealized
lexicographic router with the deployed EPP algorithm. Every
scheduling constant is read from the deployed config or plugin code,
none fitted: prefix-affinity sticky threshold 0.80; TTFT load gate
18000 ms with TTFT estimated as in-flight tokens over the deployed
peakPrefillThroughput of 28888 tok/s; token-load scoring
(least-in-flight-token candidate); and the 300 s in-flight staleness
reap, under which deep engine queues undercount and the gate rarely
triggers under backlog [R9]. The model contains no coordinator term.
A coordinator-saturation freeze term (C_W) is rejected on two
independent grounds: the EPP-side measurements of Section 6.5
contradict its physical interpretation [R13], and it is unnecessary,
since at the 300-min classification horizon no outcome
classification changes without it [R9]. The idealized router is itself a negative control: it produces
identical relapse rates at per-capacity-matched points (3/5 at both
8x-0.020 and 16x-0.040), so the measured span dependence is not
reproducible from scheduling-algorithm idealizations plus per-pod
physics (overlay-findings.md).

### 7.2 Calibration

Every constant and its provenance. The single fitted quantity is the
effective tier capacity: an assumed size-linear nominal times the
fitted TIER_EFF.

| Constant | Value | Source |
|----------|-------|--------|
| P_TPT | 17k tok/s/replica | measured saturated uncached plateaus, 131-138k tok/s fleet [R9] |
| HBM pool | 6486 blocks x 256 tok per TP4 replica | engine config; byte size cross-checked against KV/token [R9] |
| tpot(R, N) | 10.8 ms + 2.56e-4 (R/N)^2 | fit over 552 measured windows (Figure 8, out/tpot_fit.csv); per-pod form selected because the fleet-R form under-predicts the saturated 4x windows 2.4x (RMSE 27.4 vs 18.6 ms) [R9] |
| B_r | 23k tok/s/replica effective | measured per-pod restore plateau, 21.4-24.0k across four tier runs at both fleet scales [R4]; a congested-state throughput calibration, not a channel ceiling (Sec. 7.5) |
| DMA link | 151.5 GB/s = 1.19e6 tok/s/node | measured from offload counters (bytes/time); B_r runs the link at ~2% duty, so per-transfer overhead binds [R4] |
| KV/token | 127 KB (fp8, 62 layers, 8 KV heads, 128 dim) | validated against the HBM pool byte size; windowed CPU-to-GPU bytes / 127 KB matches the windowed ext_hit token rate to under 1% in every tier run [R9] |
| E[req/session] | 118 realized | 28366 records / 240 sessions in the 3 h windows; the corpus mean of 174 inflates every configuration's demand ~40% and moves the model boundary off the measured bracket (overlay-findings.md) |
| Think-gap CDF | corpus mix, truncated at 10.5 s | corpus p90 gap cap, an experiment-protocol constant [R9] |
| First-request size | ~51.6k tokens | system prompt plus first input; forced full miss per arriving salted session (overlay-findings.md) |
| Router constants | 0.80 / 18000 ms / 28888 tok/s / 300 s | read from the deployed EPP config and plugin sources; none fitted [R9] |
| Tier nominal capacity | 2520 tok/pod per size unit: size 500 = 1.26M tok/pod, 375 = 0.945M, 250 = 0.63M | ASSUMED size-linear mapping, anchored at size 500 to the 160 GB/pod host-RAM headroom figure at 127 KB/token; the configured-unit-to-byte semantics of `kv-offloading-size` are unconfirmed (Sec. 5.5, Sec. 9) |
| TIER_EFF | 0.67 (FITTED) | cold-side ordering of the tier-size series: eff(250) = 0.42M tok/pod must sit at or below the DES cold/congested transition and eff(375) = 0.63M at or above it, with the in-model transition spanning (0.42, 0.63)M; the congested-state miss share independently implies an effective window below nominal [R9]. Because the nominal is assumed, the product TIER_EFF x nominal (0.42/0.63/0.84M tok/pod at sizes 250/375/500) is in substance a single fitted effective-capacity scale |

### 7.3 Validation set

![Figure 10](../out/overlay_b1_dynamics.png)

Figure 10. Fluid overlay on the four b1 protocol configurations
(0.022, 0.017, 0.012 sps no-offload; 0.011 sps with tier at 4x);
surge window shaded; model curves labeled as model output. The
waiting-queue trajectories match in all four configurations,
including the post-cancellation re-growth in the relapse
configuration.

![Figure 11](../out/des_b1_overlay.png)

Figure 11. DES validation configurations, 5 seeds each, min-max
shading; deployed-router model outcomes: 0.022 relapse 4/5 (measured
3/3), 0.017 and 0.012 recovery 5/5, B2a recovery 5/5.

![Figure 12](../out/overlay_nseries.png)

Figure 12. DES fleet-size sweep (12 seeds x 6 configurations, 300
min, no coordinator term) with measured runs overlaid; the 16x
collapse curve sits left of the 8x curve at matched per-capacity
rate. Model output; absolute placement carries the documented
reservation bias.

The model reproduces, in order of evidential weight [R9]:

- The no-offload band and outcome classes (results 1-2). Under the
  deployed-router model: relapse at 0.022 in 4/5 seeds (one seed
  escapes; measured 3/3), recovery 5/5 at 0.017 and 0.012, and
  the B2a tier recovery (run b2a, 4x-0.011 tier) 5/5 at its 180-min
  horizon. The idealized-router DES revision (overlay-findings.md,
  DES replication section) additionally matched the in-surge peak
  waits (620-787 on the 8-replica configurations against measured
  675-790),
  showed smooth 20-40 min h erosion where the fluid transition is
  square, and produced the post-cancellation warm interlude in every
  relapsing seed (the measured 15-min-interlude/no-interlude pair
  sits inside the seed spread). Those three figures are quoted from
  that revision and are not restated under the refit.
- The third regime, with all four discriminators reproduced in 5/5
  seeds: restore channel pinned near N*B_r, linear slow queue
  divergence, h holding high, no cold collapse, at 8x-0.022 tier
  [R4][R9] (Figure 5). Quantitative gaps are stated,
  not fitted: model h 0.95 vs measured 0.70-0.85, restore share 1.0
  vs 0.66-0.79, completion rate 1.6 vs 2.5-4.3 req/s.
- The tier-250 fall-through in direction and persistence boundary.
  This is calibration-constrained, not independent validation:
  TIER_EFF is fitted to exactly this cold-side ordering (Section
  7.2), so only the trajectory shape and the seed structure are
  non-fitted. Under the final calibration, the fine capacity sweep
  gives cold 5/6 at eff(250) = 0.42M tok/pod and tier-500 runs
  congested 6/6 (heal-screen baseline A1), never cold, with the DES
  mean tracking the measured decay-through-congestion trajectory at
  250 [R11][R9] (Figure 6).
- The fleet-size shift, emergent in direction. With no N-dependent
  term, DES p(collapse) at 300 min (12 seeds per configuration) is 8x
  0.017/0.020/0.022 = 2/12, 11/12, 12/12 and 16x 0.034/0.037/0.040 =
  5/12, 12/12, 11/12; in per-8x-equivalent rate the 16x points sit
  at 0.017/0.0185/0.020, so the per-capacity-matched pairs are
  16x-0.034 vs 8x-0.017 and 16x-0.040 vs 8x-0.020 (16x-0.037 and
  8x-0.022 have no matched counterpart). The shift is visible at the
  0.017-equivalent point (5/12 vs 2/12), a single seed-level
  contrast that does not reach significance at 12 seeds per configuration
  (one-sided exact p ~ 0.19); the upper matched pair is
  ceiling-saturated (11/12 vs 11/12) and carries no shift
  information. The direction matches the measured sweep [R9]. The
  shift arises from the deployed router's affinity/load arbitration
  coupling every pod's post-cancellation drain-vs-catch-up race,
  suppressing the favorable fluctuations that independent shard
  routers sometimes benefit from. The idealized router, equally
  fleet-spanning and load-balancing, produces no shift (Section
  7.1), so a shared span alone does not produce it, and which
  deployed feature (sticky threshold, TTFT gate under the staleness
  reap, token-load scoring) drives the shift is not isolated
  (Section 9).
  The model predicts shard runs behave as independent 8x systems,
  matching the measured containment [R10].

### 7.4 Known biases

Full KV need is reserved at batch admission (vLLM allocates blocks
progressively during chunked prefill), which overstates running-set
residency during backlog drains. Both DES collapse curves sit left
of the measured ones as a consequence; the model's quantitative
claim is the shift and the outcome-class structure, never absolute
collapse probabilities [R9]. Further documented DES limitations:
tpot is frozen at decode start; there is no preemption/recompute
path; relapsed h floors at 0 in most seeds vs the measured 3-12%
residual (overlay-findings.md).

### 7.5 Executed falsifiers

Predictions were registered before hardware windows and are reported
regardless of outcome.

- 4x-0.011 tier at 300 min: predicted wait 52-160; measured 1.3,
  stable 3/3, of which one run covered the 300-min horizon. The
  prediction is falsified; the miss is assigned to the heal branch
  (Sec. 7.6) [R9].
- Tier 375/650 bracket, registered under the prior TIER_EFF = 0.5
  (375 inside the predicted cold-boundary region): 375 healed 2/2,
  excluding 0.5 and forcing the recalibration to 0.67; the size-650
  configuration was not executable (boot failure, Section 5.5)
  [R11][R9].
- 16x per-capacity edge points: the sweep's left shift is confirmed
  in direction by the measured 16x counts (Section 6.1; the 0.034
  recovery is n=1). The DES collapses 5/12 at 0.034 where the one
  measured run recovered; an n=1 measurement is uninformative about
  that rate (a recovery run has probability 7/12 under the model's
  seed counts), and the leftward-bias interpretation rests on the
  documented reservation bias (Section 7.4), not on this run.
- The fleet-R interference form: registered and falsified by the
  saturated 4x windows (predicted 33 ms vs measured 81 ms mean
  tpot); the per-pod form replaced it (out/tpot_fit.csv, Section
  6.3) [R6][R9].
- The B_r ceiling interpretation: the serial FCFS channel encodes
  B_r as a hard per-node cap; the two measured heal runs falsify it
  (Section 5.2). The 23k plateau is a congested-state throughput
  outcome. The serial channel stands as a documented deficiency: its
  concurrent-restore replacement fails the heal-branch screen and is
  not adopted (Sec. 7.7).

### 7.6 Documented failures

The heal branch is the model's primary open failure: zero DES heals
in 30 sweep runs at 8x-0.022 at any tier capacity, against 4
measured heals in 8 runs at sizes 375-500; the missed full heal at
the 0.020 boundary (one matched pair measured); and the falsified
4x-0.011 300-min prediction above [R9]. The failure is one-sided.
The DES reproduces cold collapse, restore-bound congestion, and the
measured recoveries, but cannot exit the congested state through
drain-back. The fluid layer carries a second documented failure:
branch selection at 8x cancellation. It reproduces the in-surge
restore-bound state but flushes its restore backlog within ~2 min of
cancellation and exits to the warm branch at both scales; the DES,
restore-serialized with heterogeneous gaps, diverges, matching
measurement. Both layers sit near the same critical balance
(measured throughput 2.5-4.3 req/s brackets both); no fluid constant
flips the branch without violating a measurement, so the DES is the
validated layer for the third regime (overlay-findings.md).

### 7.7 Heal-branch candidate screens

Four candidate mechanisms were screened on a shared protocol:
configurations A1-A7 spanning tier, no-offload, capacity, and span
variants, 6 seeds, 300 min, with the guard constraint that any
candidate preserve the cold/congested boundary and the no-offload
band. A run counts as a heal only under joint end-state criteria
(recovered wait and h, drained KV, ext_share and running-set bounds)
(overlay-findings.md, 2026-08-25 subsection). All four screens are
negative; none of the variants is adopted.

1. Reservation timing (heal_variant_progressive.py): progressive KV
   allocation removing the full-KV-at-admission overstatement. An
   informative negative; the variant is not adopted. A1 remains 0/6
   healed, and the variant produces a non-physical
   interference-locked congested state in the no-offload guard
   configuration A4 (measured recovery 4/4; variant 4/6 congested
   with no restore channel involved) that vLLM's step-budget
   scheduler cannot enter. Conservation was verified by an
   independent accounting check
   (adversarial_check_progressive.py). The screen's retained value
   is diagnostic: every failing A1/A5 baseline run drains from wait
   319-745 at t=105 to a trough of 0-31 at t=115 (9 of 11 at or
   below 9), then re-enters congestion
   (out/heal_screen_progressive.csv, out/heal_progressive_runs/).
2. Stale-content tier churn (heal_variant_stale.py): a credit
   bracket subtracting dead-surge write tokens from tier ages, the
   complete-instantaneous-reclamation bound, bracketing every
   intermediate policy against strict LRU. The result is null:
   outcome counts match the baseline in every configuration; the
   instrumented run shows the live
   write flux churns dead content out of the two-clock window by
   ~13 min after cancellation and the rescuable fraction of live
   tier misses is 0.0 for the remaining 180 min. Definitive
   exclusion within the two-clock abstraction; staleness effects, if
   real, live outside that window model
   (out/heal_stale_instrument.csv, out/heal_screen_stale.csv).
3. Restore-channel serialization (heal_variant_serial.py):
   concurrent onboarding at the measured 1.19e6 tok/s link with
   per-transfer overhead 4.232 s derived from the measured B_r
   plateau via B_r = S/(S/LINK_RATE + T_OVERHEAD) at the model's
   pooled mean restore size of 99,247 tok (the measured counters
   carry token rates but no transfer counts). The result is
   negative: A1 remains 0/6 healed, failing configurations still
   re-enter congestion, and the congested-state pin overshoots the
   measured 0.81-1.04 N*B_r band (1 of 15 congested runs in band,
   peaks to 1.91) (out/heal_screen_serial.csv).
4. Occupancy-gated HBM eviction (heal_variant_headroom.py):
   allocation-pressure-only eviction replacing the unconditional LRU
   aging clock, zero new constants, pre-quantified as a small
   correction (2.0-8.4% of A1 clock aging occurs below occupancy
   0.7, because the trap itself pins KV near 0.88;
   out/headroom_aging_a1.csv). The result is negative: guard
   configurations A2/A3/A6/A7 pass; guard configuration A4 preserves
   the parent outcome count (2/6 cold) with two seeds swapping class
   (s2 cold to recovered, s5 recovered to cold); the screened
   configurations A1/A5 fail. A1 yields one
   recovered run (1/6, showing the measured restore-decay trajectory
   shape) but it fails the heal criteria (end KV 0.79, end running
   82.9); 5/6 drain and re-enter. The congested pin sits inside the
   measured band (tails 0.97-1.00 N*B_r), unlike candidate 3's
   overshoot, and the trap relocates: at the A1 s1 tail, 84
   pending-onboard entries hold 0.693 of the fleet pool as full-KV
   reservations queued behind the serial channel while 22 execute
   (out/heal_screen_headroom.csv, out/heal_headroom_runs/).

The screens jointly sharpen the failure to a re-entry trap: failing
configurations drain to near-empty queues, then every completion
re-admits a full-context restore (model ext_share 1.0, h ~0.94, ~100k tok per
restore) where the measured congested state runs h 0.70-0.85 with
ext_hit 0.62-0.79. Candidates 3 and 4 bound the trap's carrier: with
the channel widened it pins via elevated restore throughput, and
with residency corrected it pins via reservation-holding backlog.
The surviving suspect is therefore restored volume per tier hit
interacting with full-KV reservation at admission (partial-context
restores, or tier-content staleness outside the two-clock window
model), not channel capacity, reservation timing, or residency
semantics [R9]. We present this as a diagnosis of an open model
failure, not a result. The gauge-semantics caveat of Section 3.1
(WAITING_FOR_REMOTE_KVS sequences are excluded from
vllm:num_requests_running) applies to any successor variant:
restore-in-flight entries must not feed the tpot(R/N) term while
still holding their reservations (overlay-findings.md).

## 8. Operational implications

Each statement below restates a measured result; no controller or
admission policy was built or tested, and no threshold transfers
beyond the measured stack.

- Horizon rule. Benchmarks shorter than ~300 min overstate stability
  at boundary operating points: 2 of 8 surviving runs at 8x-0.020
  collapsed organically near min 240, past every 60-180 min window
  (Section 4.3) [R3].
- Routing affinity is a stability parameter, not a latency
  parameter. In the one measured run (n=1), the load-only router
  config ran warm at h 0.53 vs 0.94 and collapsed after the surge
  with no recovery phase (Section 6.6) [R14]. The necessity claim
  rests on the size of the degradation and the absence of any
  recovery phase, not on a frequency.
- Router span is a blast-radius parameter. Every measured 16x
  collapse was fleet-total; independent 8x shard routers contained
  every collapse inside the failing 8-pod bulkhead (Section 6.7)
  [R10]. Sharding is a measured containment boundary.
- Drain-depth observables are early-warning candidates. kv115
  separates fast relapse from non-fast outcomes in all 8 runs at
  8x-0.020 and adds signal beyond rate over 21 runs (Section 4.5)
  [R15]. kv115 is a mediating observable, not a universal law; its
  threshold moves with rate and N, and it does not predict the
  organic-late class. Unlike a fixed-constant admission threshold
  (CONCUR's U_low/H_thresh [chen2026concur]), deployment use would
  require local (rate, N) calibration.
- Tier sizing is a persistence decision, not only a hit-rate
  decision. At 8x-0.022, size 250 falls through congestion to cold
  collapse (the one 250 run, n=1) while 375 and 500 never go cold in
  8 runs (Section 5.4); capacity sets regime persistence, and the
  pinned restore channel sets the congested-state throughput level
  (restore bandwidth itself was not varied) [R11].

## 9. Limitations and future work

Scope. All results come from one stack: one model (Qwen3-Coder-480B
FP8), one corpus family, one EPP implementation, GB200 TP4 fleets at
N in {4, 8, 16}. No claim transfers to other models, corpora, or
hardware.

Single-run points. The following rest on n=1 and are never the sole
support for a probability, threshold, or trend: both sides of the
0.020 tier/no-offload matched pair [R5]; the tier-250 fall-through
[R11]; 16x-0.034 [R6]; the approx-config 16x relapse point [R10];
the load-only ablation [R14]; the 4x-0.011 300-min falsifier horizon
[R9]. The two collapse-threshold axes each rest on one measured
contrast pair [R2], and the B_r-ceiling falsifier on two heal runs
[R4].

Confounding. kv115 and the 16x configuration are confounded at
n=21: every fast-relapse run above the pooled threshold region is
also a 16x run, so the fitted separatrix cannot separate a span
effect from a drain-depth effect at this sample size [R15].

Run dependence. Shard runs executed pairwise in shared windows over
the shard-a/shard-b namespaces, the b1a2 and lh040 pairs are
same-config replicates across days, and all outcome counts treat
runs as independent (Section 3.4). The two organic-late runs are
exactly the two dedicated-fleet (non-shard) runs, so dedicated and
shard runs may not be exchangeable units; the conservative
shard-only permutation form is p = 1/20 (Section 4.5).

Model gaps. The DES misses the organic-late onset class: its onsets
form a 135-205 min continuum where the measured onsets are bimodal
[R15]. Which deployed-router feature carries the emergent span shift
(sticky threshold, TTFT gate under the staleness reap, token-load
scoring) is not isolated, and whether the DES 16x collapses exhibit
the measured per-pod signatures of Section 6.8 is unchecked. The
heal branch is the primary modeling front: four candidate mechanisms
are screened out, the failure is sharpened to a re-entry trap, and
the surviving suspect is restored volume per tier hit interacting
with full-KV reservation at admission [R9]. The serial restore
channel remains a documented deficiency whose ceiling interpretation
is falsified by measurement [R4].

Statistics that would tighten with hardware: 16x-0.034 (n=1) and
0.037 (n=2), tier-375 (n=2) with realized-rate covariates, and the
8x-0.022 organic-vs-fast class split; none block the present claims.
The tier boot limit question stands: confirming the RAM accounting
and the configured-unit-to-byte mapping behind the nominal tier
capacities (Section 7.2), and whether a ~600 tier boots, before any
larger-tier experiment [R11]. Five related-work full-text reviews
remain outstanding before submission (related-work-sweep.md): arXiv:2606.15555 [ao2026congestion],
arXiv:2606.24861 [vanrooyen2026collapse], the arXiv:2607.17525
retry-storm section [pandey2026failureatlas], the arXiv:2608.13573
caching and load-balancing chapters [nixon2026yearserving], and the
arXiv:2605.26297 thrashing passage [yuan2026agentic].

## References

- [ao2025fluid] R. Ao, G. Luo, D. Simchi-Levi, X. Wang. Optimizing
  LLM Inference: Fluid-Guided Online Scheduling with Memory
  Constraints. arXiv:2504.11320, 2025.
- [ao2026congestion] R. Ao, J. Dong, G. Luo, D. Simchi-Levi.
  Service-Induced Congestion in Memory-Constrained LLM Serving.
  arXiv:2606.15555, 2026.
- [bronson2021metastable] N. Bronson, A. Aghayev, A. Charapko,
  T. Zhu. Metastable Failures in Distributed Systems. HotOS '21,
  pp. 221-227, ACM, 2021.
- [che2002hierarchical] H. Che, Y. Tung, Z. Wang. Hierarchical Web
  Caching Systems: Modeling, Design and Experimental Results. IEEE
  JSAC 20(7), pp. 1305-1314, 2002.
- [chen2026concur] Q. Chen, Z. Ye, T. Tang, P. Sun, B. Tian,
  G. Wang, S. Li, Y. Wen, Z. Han, T. Zhang. CONCUR:
  High-Throughput Agentic Batch Inference of LLM via
  Congestion-Based Concurrency Control. arXiv:2601.22705, 2026.
- [dai2025throughput] J. G. Dai, T. Deng, Y. Li, T. Peng.
  Throughput-Optimal Scheduling Algorithms for LLM Inference and AI
  Agents. arXiv:2504.07347, 2025.
- [denning1968thrashing] P. J. Denning. Thrashing: Its Causes and
  Prevention. AFIPS Fall Joint Computer Conference, pp. 915-922,
  1968.
- [dong2026flow] Z. Dong, J. Cao. Flow-Controlled Scheduling for LLM
  Inference with Provable Stability Guarantees. arXiv:2604.11001,
  2026.
- [farahbakhsh2025modeling] A. Farahbakhsh, A. Haeberlen, Q. Lu,
  L. Alvisi, R. Van Renesse, S. Cohen. Modeling Metastability.
  HotNets '25, ACM, 2025.
- [farahbakhsh2026characterizing] A. Farahbakhsh, Q. Lu, L. Alvisi,
  A. Haeberlen, R. Van Renesse. Characterizing Metastable Faults and
  Failures. arXiv:2606.00942, 2026.
- [fricker2012versatile] C. Fricker, P. Robert, J. Roberts. A
  Versatile and Accurate Approximation for LRU Cache Performance.
  ITC 24, 2012.
- [huang2022wild] L. Huang, M. Magnusson, A. B. Muralikrishna,
  S. Estyak, R. Isaacs, A. Aghayev, T. Zhu, A. Charapko. Metastable
  Failures in the Wild. OSDI '22, pp. 73-90, USENIX, 2022.
- [li2025continuum] H. Li, R. He, Q. Mang, Q. Zhang, H. Mao,
  X. Chen, H. Zhou, A. Cheung, J. Gonzalez, I. Stoica. Continuum:
  Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache
  Time-to-Live. arXiv:2511.02230, 2025.
- [meng2026metronome] J. Meng, B. Li. Metronome: Bound the Cache,
  Keep the Beat for Real-Time Interaction Model Serving.
  arXiv:2607.02640, 2026.
- [nian2026cacheflow] S. Nian, J. Fang, Q. Feng, Z. Wu, F. Lai.
  CacheFlow: Efficient LLM Serving with 3D-Parallel KV Cache
  Restoration. arXiv:2604.25080, 2026.
- [nie2026queueing] C. Nie, N. Si, Z. Zhou. A Queueing-Theoretic
  Framework for Stability Analysis of LLM Inference with KV Cache
  Memory Constraints. arXiv:2605.04595, 2026.
- [nixon2026yearserving] W. Nixon, J. Durbin, F. Standhartinger,
  H. S. Gunawi, J. Yang. A Year in LLM Serving: Workload Evolution,
  Caching and Load-Balancing. arXiv:2608.13573, 2026.
- [pandey2026failureatlas] V. Pandey, G. Singh. FailureAtlas: A
  Taxonomy of Failure Modes in Multi-Provider LLM Serving
  Infrastructure. arXiv:2607.17525, 2026.
- [qin2025mooncake] R. Qin, Z. Li, W. He, M. Zhang, Y. Wu, W. Zheng,
  X. Xu. Mooncake: Trading More Storage for Less Computation: A
  KVCache-centric Architecture for Serving LLM Chatbot. FAST '25,
  USENIX, 2025.
- [ranganathan2025incidents] B. Ranganathan, M. Zhang, K. Wu.
  Enhancing Reliability in AI Inference Services: An Empirical Study
  on Real Production Incidents. arXiv:2511.07424, 2025.
- [rosensweig2013steady] E. J. Rosensweig, D. S. Menasche,
  J. Kurose. On the Steady-State of Cache Networks. IEEE INFOCOM,
  pp. 863-871, 2013.
- [vanrooyen2026collapse] P. van Rooyen. First-Order Recoverability
  Collapse in Self-Referential Information Decoders: The Operating
  Loop of an AI System as a Driven Nonequilibrium Steady State.
  arXiv:2606.24861, 2026 (v3 2026-08-17).
- [yuan2026agentic] Y. Yuan, A. Nayak, S. Kundu, N. Talati. Agentic
  AI Workload Characteristics. arXiv:2605.26297, 2026.
- [yuan2026dualmap] Y. Yuan, P. Zuo, B. Wang, Z. Chen, Z. Tan,
  Z. Yu. DualMap: Enabling Both Cache Affinity and Load Balancing
  for Distributed LLM Serving. arXiv:2602.06502, 2026.
- [zhang2026cachescout] R. Zhang, C. Kim, S. Feng, K. Du, Y. Liu,
  Y. Zhong, C.-W. Ching, J. Jiang, L. Hu. Learning Agent Execution
  for KV-Cache Management in Agentic Serving (CacheScout).
  arXiv:2608.14624, 2026.
- [zheng2026kareto] X. Zheng et al. (Alibaba). Adaptive
  Multi-Objective Tiered Storage Configuration for KV Cache in LLM
  Service (Kareto). arXiv:2603.08739, 2026.
- [zhu2026tracelab] K. Zhu, M. Jacob, C. Ma, Y. Pan, S. Wang,
  A. Krishnamurthy, B. Kasikci. TraceLab: Characterizing Coding
  Agent Workloads for LLM Serving. arXiv:2606.30560, 2026.
