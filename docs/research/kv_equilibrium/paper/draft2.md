# Metastable Prefix-Cache Collapse in Agentic LLM Serving

Draft 2 (2026-08-26). Full rewrite of draft.md: theory added as
Section 3, evidence grading made explicit (Section 4.5, Appendix A),
agentic framing in title/abstract/introduction, laboratory
terminology replaced throughout. Quantitative claims are carried over
from draft.md unchanged and remain audited against
research-status.md and paper/claims-map.md. Internal evidence markers
[R<n>] (research-status result) and [C<nn>] (claims-map row) are
retained for auditability and are removed at camera-ready. Literature
citations use [bibkey] and resolve in References. Figure images live
under kv_equilibrium/out/ (composites under out/paper/, generators
kv_equilibrium/fig_*.py, fig_theory.py, and mitigation.py).

Terminology used throughout, defined once here and in the text at
first use. h: prefix-cache hit rate (token-weighted unless stated).
lambda_s: session arrival rate in sessions/s; lambda_r = lambda_s *
E_req: request rate. N: replica count spanned by one router instance;
operating points are written (N, lambda_s). Capacity-normalized rate:
lambda_8 = lambda_s * 8 / N, the rate normalized to the 8-replica
reference fleet. D: drain depth, the fleet-mean KV-pool occupancy
over minutes 115-120 of the protocol (defined in Section 5.5).
Untiered: no host-memory KV tier. Tier sizes are configured units
250/375/500 with effective capacities 0.42/0.63/0.84M tokens per
replica (Section 8.2). Outcome classes: recovery, immediate collapse
(onset during or just after the post-surge drain), delayed collapse
(onset near minute 240 with no new perturbation), and complete
recovery of a tiered fleet. Former internal terms map as: "draw" ->
run; "arc" -> trajectory; "arm" -> configuration; "kv115" -> drain
depth D; "8x-0.020" -> (N=8, lambda_s=0.020); "organic" -> delayed;
"heal" -> complete recovery.

## Abstract

Agentic workloads change the physics of LLM serving. Coding agents
carry contexts of 50k-250k tokens dominated by a shared growing
prefix, issue their next request the moment the previous one returns,
and defer rather than abandon under slowdown. For such workloads the
prefix cache is not a latency optimization but a state variable the
fleet's capacity depends on: a request whose prefix is cached
prefills only its increment, while a miss re-prefills the full
context and writes it back into the same finite pool it missed in,
evicting other sessions' prefixes. On the trace-calibrated workload
of this paper one miss writes as much cache as twenty-two hits.

We show that this feedback makes multi-replica serving metastable,
by measurement, theory, and calibrated simulation. Replaying agentic
coding traces on TP4 GB200 fleets of 4-16 replicas serving
Qwen3-Coder-480B FP8, a transient load surge drives the fleet into a
cold absorbing state: hit rate 0.94 to 0.02-0.03, median TTFT near
240 s, no recovery over horizons up to 300 minutes, sustained by the
same base load the fleet previously served warm - and recovery
requires shedding demand well below that load (hysteresis). The
perturbation needs no operator eviction: a never-cancelled flash
crowd whose injected cohort reaches two to four times the standing
session population reliably collapses the fleet, at a base rate that
recovers from a five-fold larger cancelled surge, and the runs that
recover serve the identical cohort to completion - collapse is basin
selection, not overload. The transition is probabilistic: across repeated identical
runs, intermediate rates split between recovery, immediate collapse,
and a delayed collapse that only 300-minute horizons reveal. A host-memory
KV tier transforms the failure rather than removing it, producing a
third regime in which hit rate stays high while a saturated restore
channel bounds throughput and the queue slowly diverges; tier
capacity determines whether this regime persists, falls through to
cold collapse, or fully recovers. Collapse probability also grows
with router span: at matched per-replica load a single 16-replica
router shifts the collapse boundary to lower rates, and every
16-replica collapse is fleet-total while independent 8-replica
routers contain every collapse inside one shard. A first-order
theory - a retention fixed point closed by an occupancy-and-queueing
feedback - locates the band, the minimum tier capacity, and the
restore-bound throughput, each within tens of percent of
measurement, and a fluid model plus discrete-event simulation
sharing one measured calibration (one fitted constant) reproduce the
band, the congested-regime discriminators, and the direction of the
span shift emergently. The theory also implies a mitigation:
basin-aware deferral of new sessions, the admission abstraction of
asynchronous serving. In the calibrated model it converts the
deterministic-collapse point into recovery in 4 of 5 seeds while
serving strictly more requests than the uncontrolled fleet, and
under a persistent surge it is the only controller of four screened
that holds the fleet warm - AIMD concurrency control and
delay-based early rejection act on signals that fire only after the
basin boundary is crossed. The collapse band itself reproduces
under emulations of two third-party routing policies, so the
failure belongs to the affinity-load feedback family, not one
implementation. We report the model's failure to reproduce
tiered-fleet complete recoveries as an open problem.

## 1. Introduction

Serving is entering an agentic regime. A coding agent's request
stream is unlike chat traffic in three ways that matter for the
serving substrate. First, its context is large and grows: on the
393-session corpus used throughout this paper, sessions open with a
~52k-token system prompt, add a few thousand tokens per tool-call
turn, and run to a 249k-token compaction ceiling, for a mean
re-prefilled context of ~117k tokens. Second, its arrival process is
completion-coupled at machine pace: 78% of turns arrive within
seconds of the previous turn's completion, because a tool loop
resumes the moment its result returns. Third, its demand does not
yield: an agent whose request is delayed does not leave; it waits
and retries, so slowdown converts offered load into a deferred
reservoir rather than into abandonment. Under this regime the prefix
cache stops being an optimization. With a warm cache a turn prefills
only its few-thousand-token increment; with a cold one it re-prefills
the full context, a factor-of-27 difference in service demand on this
workload. The cache is therefore a state variable that sets fleet
capacity, and its dynamics deserve the same stability analysis given
to queues.

Those dynamics contain a feedback loop. A miss re-prefills the full
context and writes the resulting KV blocks back into the same finite
pool it missed in, evicting other sessions' prefixes; on this
workload the write amplification - cache written by a miss versus by
a hit - is 22.6. The effective service rate is thus a function of the
hit rate, and the hit rate is a function of the eviction pressure the
service process itself generates. Feedback of this shape is the
defining structure of metastable failures in distributed systems
[bronson2021metastable, huang2022wild]: a trigger displaces the
system into a degraded state, and a sustaining effect keeps it there
after the trigger is gone.

This paper measures that failure at multi-replica scale, derives its
structure, and models it quantitatively. On 8-replica TP4 GB200
fleets serving a 480B-parameter model under open-loop agentic trace
replay, a 45-minute load surge at base rate lambda_s = 0.022
sessions/s drives the fleet into a cold state that persists as long
as we observe it: h falls to 0.016-0.030 from 0.94 warm, TTFT p50
rises to 240 s, and no recovery occurs over 73 to 195 post-surge
minutes across three runs, sustained by the same base load the fleet
served warm before the surge (Section 5.1) [C01]. The identical
perturbation applied across base rates yields a probability band
rather than a threshold: 0.017 sessions/s always recovers, 0.022
always collapses, and 0.020 splits across three outcome classes,
including two runs that collapse near minute 240 with no new
perturbation - so benchmark horizons shorter than roughly 300
minutes overstate stability at boundary operating points [C02][C05].
The cold state exhibits hysteresis: the fleet cannot re-warm from
cold at a load it serves comfortably warm, and recovery requires
shedding demand below the band's lower edge [C06]. An absorbing
degraded state, probabilistic entry, and hysteretic exit are the
metastable-failure signature, here with full-context re-prefill as
the sustaining effect - and the deferred-reservoir demand that makes
the state reachable is precisely the agentic arrival structure
(Section 5.4).

Two system parameters reshape the failure in ways that are, to our
knowledge, unmeasured elsewhere. First, a host-memory KV tier does
not remove the failure; it transforms it into a third regime,
restore-bound congestion, in which the fleet holds a high hit rate
while the host-to-device restore channel pins near its
congested-state throughput and the queue diverges slowly (Section 6)
[C10]. Tier capacity - the one parameter the tier series varies -
determines whether that regime persists, falls through to cold
collapse, or completely recovers (Section 6.4) [C13]; restore
bandwidth was not varied, and its effect on persistence is
unmeasured. In one matched same-day pair at the 0.020 boundary, the
tier converted a collapsing operating point into a complete
self-recovery [C12]. Second, collapse probability depends on the
number of replicas a single router instance spans, at fixed
per-replica load and fixed per-replica physics. The 16-replica
collapse curve sits left of the 8-replica curve: the mixed-outcome
point moves from 0.020 to 0.0185 in capacity-normalized rate,
roughly 7.5%, though the edge brackets bound the shift only loosely
(0 to ~16%). Every measured 16-replica collapse is fleet-total,
while independent 8-replica shard routers contained every collapse
inside the failing 8-replica partition (Section 7) [C15][C16][C18].
In one measured run (n=1), a router configuration carrying no
affinity signal ran warm at h 0.53 versus 0.94 and collapsed after
the surge with no recovery phase [C22]: routing affinity carries
both the warm margin and the recovery path.

The measurements are organized by a first-order theory (Section 3).
The classical characteristic-time analysis of LRU caches, closed
with the miss-write feedback, yields a retention fixed point whose
write amplification (22.6 here) is the feedback strength; a second
feedback through pool occupancy and queueing delay creates the cold
branch under this workload's reuse gaps; and the resulting
closed-form estimates land within tens of percent of measurement:
the cold-state service bound within ~15% of the measured cold
throughput, the minimum-tier-capacity rule bracketing the measured
persistence boundary, and the restore-channel bound matching the
measured congested throughput. The theory also explains why outcomes
inside the band are frequencies rather than responses: both branches
are locally stable there, and entry is decided by fluctuations
relative to a separatrix whose empirical coordinate - the
post-perturbation drain depth D - we measure directly (Section 5.5).

We accompany the theory with a fluid model and a discrete-event
simulation (DES) sharing one calibration in which every constant is
measured or read from deployed configuration except a single fitted
scale, the effective tier capacity (Section 8) [C25]. The DES
implements the deployed router algorithm with no coordinator term
and no replica-count term. It reproduces the band, all four
congested-regime discriminators in 5 of 5 seeds, and the direction
of the span shift emergently [C26]. Both model collapse curves sit
left of the measured ones, a documented reservation bias, so the
model's quantitative claim is the shift and the outcome-class
structure, never absolute collapse probabilities [C27]. The model's
recovery branch is a documented failure: it produces zero complete
recoveries where the hardware produced four at the same operating
point. We report the failure, four screened candidate mechanisms,
and the surviving suspect, rather than tuning the discrepancy away
(Section 8.6) [C30-C32].

Contributions:

- A first-order theory of prefix-cache metastability: the retention
  fixed point with miss-write amplification, the occupancy-queueing
  feedback that creates the cold branch, closed-form break-point and
  minimum-tier-capacity estimates each anchored to a measured
  quantity, and the dimensionless groups that organize the regimes
  (Section 3).
- Measured absorbing collapse in multi-replica prefix-cached serving
  (fleets up to 16 replicas), with a collapse-probability band,
  three outcome classes, horizon dependence, and hysteresis
  (Section 5) [C01-C07]; plus a never-cancelled flash-crowd protocol
  with a measured collapse boundary in injected-cohort units and a
  basin-selection demonstration - the collapse-inducing workload is
  fully served in the runs that recover (Section 5.6) [C36-C38].
- A drain-depth separatrix: post-perturbation KV occupancy D
  separates immediate collapse from other outcomes in all 8 runs at
  the boundary point and adds signal beyond rate over 21 runs,
  presented as a mediating observable with stated confounds
  (Section 5.5) [C08-C09].
- The host-tier third regime, restore-bound congestion, and a
  tier-size series showing that capacity sets regime persistence
  while the pinned restore channel sets congested-state throughput;
  in one run the tier serves to completion the flash crowd that
  collapses the untiered fleet, sustaining the restore channel at
  1.75x its congested-state level for two hours (Section 6) [C10-C14]
  [C39-C40].
- Router-span dependence of collapse probability, with config
  independence, refutation of load-imbalance and (for the measured
  router) coordinator-saturation mechanisms, an affinity-necessity
  ablation, shard containment, and per-replica scatter signatures
  (Section 7) [C15-C24].
- A calibrated fluid+DES model with a deployed-router layer, the
  emergently reproduced span-shift direction, executed falsifiers
  reported regardless of outcome, and documented failures
  (Section 8) [C25-C32].
- A model-level mitigation screen: basin-aware admission deferral,
  derived from the separatrix, prevents collapse in both protocols
  and dominates AIMD and early-rejection baselines under a
  persistent surge; plus router-policy emulations showing the
  collapse band is a property of the affinity-load feedback family
  (Section 9).

Every claim in the paper carries an evidence grade (Section 4.5;
Appendix A gives the full register): measured facts, outcome
frequencies with their counts, model-supported statements, and open
problems are typographically and rhetorically separated, and no
single-run observation supports a probability, threshold, or trend.
All measurements come from one stack - one model, one corpus family,
one router implementation, GB200 TP4 fleets - and numeric thresholds
are scoped to it. The mechanism itself requires only an LRU prefix
cache, full-context re-prefill on miss, and demand that defers
rather than abandons (Section 3), and we state which conclusions
rest on the mechanism versus on the stack (Section 11).

## 2. Background and related work

Metastable failures. Bronson et al. [bronson2021metastable] define
the class through its three elements: a trigger, a sustaining
effect, and a degraded stable state. Huang et al. [huang2022wild]
study production occurrences, including a look-aside-cache
reproduction in which a cache-hit-rate drop sustains overload.
Farahbakhsh et al. state the prediction agenda - a model sketch for
whether a given request-response structure admits metastable states
[farahbakhsh2025modeling], with a causal characterization in
[farahbakhsh2026characterizing]. These works establish the class and
the agenda. This paper exhibits a new sustaining mechanism,
hit-rate-dependent KV write amplification through full-context
re-prefill, with a measured probability band, measured dependence on
tier capacity and router span, and a calibrated model. The mechanism
differs from the look-aside instance in where the amplification
lands: there, misses amplify load onto a backing service behind the
cache; here, a miss writes its re-prefilled context back into the
same finite pool it missed in - write amplification into the cache's
own capacity. Metronome [meng2026metronome] applies the metastable
label to LLM KV memory in a setting where full-duplex sessions pin
monotonically growing per-session state and a linear open-loop fill
model predicts an abrupt stall; that model has one absorbing state
and no feedback, hit-rate, hysteresis, or recovery structure. Its
14-of-20 versus 6-of-20 outcome split under identical conditions
independently corroborates outcome bimodality at fixed operating
points. The metastability here is of the Bronson kind: a sustaining
loop, demonstrated by hysteresis.

Bifurcation treatments of AI serving loops. van Rooyen
[vanrooyen2026collapse] develops first-order collapse, closed-form
spinodals, cusp-organized bistability, and hysteretic recovery for
an AI system's operating loop under congestion-dependent feedback.
This is the closest published vocabulary match to the equilibrium
structure here, but the physical feedback differs: there,
uncertified output re-enters the loop as added load (retry-type
amplification); here the feedback channel is the cache state itself.
On abstract-level review (full-text review precedes submission,
Section 11), that work carries no cache state variable, no phase
boundary in (capacity, load), no workload calibration, and no
serving-system validation of a cache mechanism. The two are
complementary instantiations of the same fold-and-hysteresis
mathematics; ours is the cache-feedback instantiation with
measured-constant calibration and multi-replica validation.

Queueing stability for LLM inference. Nie et al. [nie2026queueing]
give a queueing-theoretic stability framework for LLM inference
under KV memory constraints; Dai et al. [dai2025throughput] prove
throughput-optimality of work-conserving schedulers in a fluid-limit
framework covering agentic workloads; Dong and Cao [dong2026flow]
derive stability conditions for admission-budgeted scheduling. In
all of these the service rate is cache-independent and memory enters
as a constraint. With hit-rate feedback the effective service rate
is state-dependent, and the stability region acquires a coexistence
band that work-conservation arguments do not see. Our closed-loop
measurements (Section 5.4) locate the arrival semantics under which
the constraint-style analyses apply. Ao et al. analyze
service-induced congestion in memory-constrained serving
[ao2026congestion], in a line with fluid-guided scheduling under
endogenous per-request memory growth [ao2025fluid]; its mechanism is
memory growth during service, not prefix-cache feedback (full-text
review pending, Section 11).

Cache-aware routing. DualMap [yuan2026dualmap] engineers the
affinity-versus-load trade-off with dual-hash power-of-two-choices
mapping and SLO-triggered fallback. Continuum [li2025continuum] pins
KV across tool-call gaps with a TTL. CacheScout
[zhang2026cachescout] learns agent execution transitions to guide
eviction and prefetch. These works optimize the trade-off's
performance. We show the trade-off has a stability dimension: the
affinity term keeps the fleet on the warm branch and carries the
recovery path (Section 7.6, one measured run), and the span of the
balancer sets collapse probability and blast radius - quantities
absent from their evaluations.

Tiered KV caches and restore bandwidth. Mooncake [qin2025mooncake]
trades storage for computation in a KVCache-centric architecture and
motivates early rejection under overload. CacheFlow
[nian2026cacheflow] identifies KV restoration as a dominant
bottleneck and parallelizes it. Kareto [zheng2026kareto] treats tier
sizing as a multi-objective steady-state optimization. Unclaimed in
this literature is the persistent congested serving regime pinned at
restore throughput, with persistence set by tier capacity (Sections
6.1, 6.4), and the stability discontinuity in tier sizing - the
fall-through to cold collapse at insufficient capacity - which a
steady-state Pareto analysis cannot expose.

Classical cache theory. The characteristic-time frame of Che et al.
[che2002hierarchical], with the validity analysis of Fricker, Robert,
and Roberts [fricker2012versatile], describes an LRU cache whose
retention window is set by the aggregate write rate. The prefix
cache fits this frame with one addition outside its assumptions: the
write rate depends on the hit rate, because misses write full
contexts (Section 3.1). Multiple cache steady states are themselves
classical: Rosensweig et al. [rosensweig2013steady] show cache
networks can be non-ergodic, with the steady state depending on
initial placement. That multiplicity is combinatorial, arising from
placement dependencies across a topology at fixed demand, with no
load parameter, no capacity-load boundary, and no hysteresis sweep;
the multiplicity here comes from a scalar write-rate feedback within
a single tier, yielding a load-parameterized coexistence band and a
hysteresis loop. Denning's thrashing analysis [denning1968thrashing],
with its multiprogramming-level control, is the classical ancestor
of the operational response to such regimes; the differences here
are a measured probability band, hysteresis, and coordination-layer
dependence rather than a qualitative regime.

Observation base. CONCUR [chen2026concur] is the closest published
statement of the phenomenon: in agentic batch inference, KV usage
pins at 80-100% while the prefix-cache hit rate collapses and stays
low for most of execution (its Figure 3, from a large-scale
deployment), with a measured hit-rate knee against concurrency,
mitigated by an AIMD admission controller keyed on cache usage and
hit rate. It stops at the observation and a preventive
fixed-constant heuristic: hit rate is a measured signal there, never
a modeled state variable; no absorbing state, hysteresis,
probability band, or recovery semantics is measured or claimed; and
its mechanism attribution is exogenous (agents paused for tool calls
losing LRU recency), not the miss-write amplification that closes
the loop here. TraceLab [zhu2026tracelab] characterizes coding-agent
traffic on a public corpus, including a retention-window-to-hit-rate
sweep and the finding that idle gaps beyond ~5 minutes drive most
misses - the gap structure our protocol's gap cap controls
(Section 4.2). Yuan et al. [yuan2026agentic] characterize agentic
workloads and, per abstract-level review, warn of a thrashing regime
once aggregate agent context exceeds GPU memory. Ranganathan et al.
[ranganathan2025incidents] taxonomize 156 high-severity production
LLM inference incidents; Nixon et al. [nixon2026yearserving] release
a year-long production serving trace. The phenomenon class is widely
observed and, prior to this work, unmodeled for the prefix-cache
feedback channel.

## 3. A theory of prefix-cache metastability

This section derives the failure structure that Sections 5-7
measure: a retention fixed point coupling hit rate to write rate
(3.1), the occupancy-and-queueing feedback that creates the cold
branch under this workload's reuse gaps (3.2), first-order
break-point and tier-sizing estimates, each checked against a
measured quantity (3.3-3.4), and the dimensionless groups that
organize the regimes (3.5). The theory is deliberately first-order:
it predicts the existence, location, and scaling of the regimes; the
calibrated simulation of Section 8 carries the quantitative claims.

Notation. N replicas each hold an HBM KV pool of C tokens under LRU
block eviction (fleet pool S = N * C) and optionally a host-memory
tier of C_cpu tokens per replica; p is the per-replica prefill rate
and B_r the effective per-replica restore rate (tokens/s). Sessions
arrive at rate lambda_s and issue E_req requests over their
lifetime, so the long-run request rate is lambda_r = lambda_s *
E_req. A request with context c prefills its new input delta on a
hit and c + delta on a miss, and appends its output to the cache
either way. F(t) is the reuse-gap distribution: the probability that
a session's next request arrives within t seconds of its predecessor
becoming reusable. Calibrated values for the measured stack (N = 8,
C = 1.66M tokens, S = 13.28M, p = 17k tokens/s, E_req = 118, reuse
gaps capped at 10.5 s by the protocol): mean write per miss
w_miss = 117.8k tokens, mean write per hit w_hit = 5.2k, mean
prefill per miss c_miss = 116.9k (workload functionals derived from
the trace-calibrated spec; Section 8.2).

### 3.1 The retention fixed point

An LRU cache under aggregate write rate W retains an entry for the
characteristic time T = S / W: new writes traverse the pool in T
seconds, and an entry survives if touched again within that window
[che2002hierarchical, fricker2012versatile]. In a prefix cache, W is
not exogenous. At hit rate h,

    W(h) = lambda_r * [ (1 - h) * w_miss + h * w_hit ],        (1)

and the hit rate is set by whether entries survive their reuse gaps:

    h* = F( S / W(h*) ).                                       (2)

Equation (2) is the classical characteristic-time fixed point with
one addition outside its assumptions: the write rate depends on the
hit rate it produces. The coupling strength is the write
amplification

    A = w_miss / w_hit = 22.6:                                 (3)

one miss evicts as much cache as twenty-two hits. Because W falls as
h rises, the map Phi(h) = F(S / W(h)) is increasing, and an
increasing map can cross the identity more than once: a warm fixed
point (high h, low write pressure, long retention) and a cold one
(miss writes flooding the pool, retention too short to hit) can
coexist at the same offered load, separated by an unstable crossing.
Coexistence appears and disappears at the tangency (saddle-node)
condition Phi(h) = h, Phi'(h) = 1. For a two-point reuse-gap mixture
in which a fraction x of requests return after gaps longer than y
and the rest return quickly, the warm point h = 1 - x exists iff the
pool covers the long gap at the warm write rate,

    S >= lambda_r * y * [ x * w_miss + (1 - x) * w_hit ],      (4)

which inverts to a closed-form collapse edge in load and a matching
recovery edge with the write mix evaluated on the cold branch.
Whether retention feedback alone produces coexistence depends on
where S / W(0) lands in F: it must land inside F's central mass. In
a capacity-starved production configuration we analyzed before this
campaign (8 replicas, 0.95M-token pools, 130k-token mean contexts,
~10 requests/s), S / W(0) = 11.6 s against think times of tens of
seconds, and (1)-(4) alone give a coexistence band. On the measured
stack of this paper the pools are larger and the protocol caps reuse
gaps at 10.5 s, so S / W(0) = 43-80 s at the studied loads sits far
above every gap: equation (2) then has a single warm solution at
every studied rate, and no static retention argument can produce the
cold state that Section 5 measures. That state requires a second
feedback.

### 3.2 The occupancy-queueing feedback and the cold branch

Two mechanisms tie the cache to the request queue. First, running
requests occupy the pool: an admitted request reserves its KV need
until completion, and admission fills the pool to a watermark theta
(0.92 in the measured engine) whenever work is waiting. The cache
lives in the remainder, so under a backlog the retention window is

    T_eff = S * (1 - occ) / W(h),   occ -> theta,              (5)

a 12.5x contraction at the watermark. Second, a queued request's
prefix must survive its reuse gap plus its waiting time w, so the
survival probability is F(T_eff - w). Both corrections vanish in
light traffic and become significant together under a backlog. The service side
closes the loop: with the prefill engine as bottleneck, the fleet
serves at

    mu(h) = N * p / E[prefill per request at h],               (6)

which spans a factor of ~27 between branches: mu(warm) ~ 31
requests/s versus mu(0) = N * p / c_miss = 1.16 requests/s. The
measured cold-state throughput is 1.2-1.4 requests/s [R1][C01],
within ~15% of the mu(0) estimate (the small excess is the measured
2-3% residual hit rate). A backlog therefore sustains itself
whenever flux into the fleet exceeds mu(0) while prefixes are cold:
misses hold the pool pinned and the waits long, which holds the hit
rate near zero, which holds the service rate at mu(0).

Figure 1a shows the structure as a one-step hit-rate map conditioned
on backlog depth Q at the reference operating point (N = 8,
lambda_s = 0.022): with Q = 0 the map is monostable warm (the static
result of 3.1); at moderate Q it folds and two stable crossings
coexist; deeper backlogs push the escape threshold - the hit rate a
fleet must already hold for its cache to outrun its queue - toward
one. Figure 1b integrates the joint (h, Q) dynamics through the
post-perturbation drain window and colors the basins of attraction.
The basin boundary is the separatrix of the drain-versus-rewarm
race; the drain-depth observable of Section 5.5 is its empirical
coordinate, KV occupancy read just after the perturbation ends
telling which side of the boundary the trajectory is on.

![Figure 1](../out/paper/fig_fixed_point.png)

Figure 1. Theory constructions at (N=8, lambda_s=0.022), workload
functionals and constants from the Section 8 calibration; model
output, no measured data. (a) The one-step hit-rate map Phi(u | Q)
conditioned on backlog depth: monostable warm at Q = 0, folded
(bistable) at Q = 60, escape threshold near one at Q = 150. (b)
Basins of attraction of the joint (hit rate, backlog) dynamics
during the post-perturbation drain window; the basin boundary is the
separatrix that the drain-depth observable of Section 5.5 estimates.
Time normalization is qualitative (fixed hit-rate relaxation
constant); the figure shows equilibrium and basin structure, not
calibrated transit times.

The demand side determines whether the cold branch is reachable.
Requests within a session are completion-coupled - a session issues
its next turn only after the previous returns - so in-flight demand
defers under slowdown instead of accumulating [R7][C33], and a
closed population self-stabilizes (Section 5.4). What makes the cold
branch reachable is a demand reservoir that does not yield: sessions
arriving as an exogenous stream park their next turns while the
fleet is slow and release them as catch-up flux when service
resumes. Agentic workloads realize exactly this structure, which is
why the open-loop session-arrival protocol of Section 4 - and not a
classical closed-loop benchmark - exposes the failure.

### 3.3 Break-point estimates

Cold-branch feasibility (necessary condition). A sustained cold
state requires deferred flux above the cold service rate,
lambda_r > mu(0):

    lambda_s > N * p / (c_miss * E_req) = 0.0098 sessions/s.   (7)

Below bound (7) the backlog drains even with every request missing
and recovery is unconditional. The measured protocol recovers 2/2 at
0.012 and 4/4 at 0.017 [C02], both above the bound - consistent with
(7) being necessary rather than sufficient: between the bound and
the measured collapse edge at 0.020-0.022, the reservoir drains
partly serially (completion-coupled), so the effective flux against
mu(0) sits below lambda_r and the race of Figure 1b is winnable. The
gap between bound (7) and the measured edge is the workload's
elasticity margin.

Warm-branch feasibility. The warm branch persists while warm-state
prefill demand fits, which holds to roughly ten times the studied
loads (prefill utilization 0.08 at lambda_s = 0.022). The warm
branch near the band is therefore not destroyed by load; it is
abandoned. Entry at the studied rates is fluctuation-driven - an
eviction-scale perturbation (Section 4.3), or the slow occupancy
growth of deepening sessions, carries the state across the
separatrix - which is why outcomes at fixed operating points are
frequencies rather than deterministic responses [C02][C05], and why
the coexistence region manifests as hysteresis rather than as a
capacity wall.

Perturbation scale. A surge writing at rate W_s evicts parked
prefixes on the pool-traversal timescale S * (1 - occ) / W_s - under
two minutes at the measured saturated write rate - so both protocol
surge durations (900 s and 2700 s) evict the pool several times
over. What the longer surge changes is the reservoir: deferred
sessions accumulate six times longer and the post-cancellation race
begins from deeper Q. The measured duration contrast (900 s
recovers, 2700 s collapses, same rate) [C03] is a reservoir-depth
effect, not an eviction-completeness effect, consistent with the
basin geometry of Figure 1b.

Asymmetry of the transitions. Collapse is fast because eviction runs
on the pool-overwrite timescale (minutes under a surge); recovery is
slow because cache coverage grows no faster than real time - content
only becomes T seconds old after T seconds - while every miss along
the way regenerates eviction pressure. The hysteresis of Section 5.3
is this asymmetry read at steady state.

### 3.4 The host tier: capacity sets the regime, restore bandwidth its throughput

A host-memory tier of C_cpu tokens per replica extends retention.
The tier ingests only new writes (restored blocks already reside
there; measured, Section 6.1), so its window adds to (5):

    T_tot = T_eff + N * C_cpu / W_new,                         (8)

with W_new the new-write rate. The naive sizing rule - delete the
cold branch by making T_tot(h=0) exceed the reuse gaps - is
necessary but not the operative constraint, because a tiered fleet
under overload never reaches h = 0: it settles into the congested
regime of Section 6, serving hits through the restore channel. Two
separate quantities govern that regime.

Tier capacity sets persistence. Under congestion the parked working
set recirculates: each live session is touched once per
recirculation time t_rec ~ L / mu_c, with L the live-session count
and mu_c the congested completion rate. A session's tier entry
survives to its next touch iff the tier window exceeds t_rec, giving
the minimum capacity

    C_cpu* ~ W_new * t_rec / N.                                (9)

At the measured congested point (tier ingest W_new = 50-78k
tokens/s [R4]; mu_c = 2.5-4.3 requests/s over a live population near
200 sessions, so t_rec ~ 50-90 s), rule (9) gives 0.4-0.7M tokens
per replica - bracketing the measured persistence boundary: the
0.42M-effective tier loses its external hits and falls through to
cold collapse, while 0.63M and 0.84M persist [C13]. Below C_cpu* the
tier only delays collapse; above it, the tier converts collapse into
congestion.

Restore bandwidth sets congested throughput. Every completion in the
congested regime re-onboards most of a context through the restore
channel, bounding completions at

    mu_restore = N * B_r / (h_ext * c_miss) ~ 2.2 requests/s   (10)

at the measured tier-hit share h_ext ~ 0.7 and B_r = 23k tokens/s,
against demand of 2.6 requests/s at lambda_s = 0.022. The regime
therefore runs with its restore channel pinned (measured: 0.81-1.04
of N * B_r [C10]) and its queue diverging slowly (measured:
~0.8/min) - the discriminators of Section 6.1. B_r is the measured
congested-state channel throughput, not a hardware ceiling: the two
measured complete recoveries sustained 1.28-1.51x this rate during
escape [C11], a distinction that matters for the model failure of
Section 8.6.

The design consequence is a trade, not a fix: a tier above C_cpu*
deletes the cold absorbing state (a capacity cliff) and in exchange
the overloaded fleet occupies a congested state whose throughput is
set by restore bandwidth (a bandwidth cliff). Sizing the tier by (9)
without provisioning B_r converts one failure mode into another -
the central operational finding of Section 6.

### 3.5 Dimensionless structure

Five ratios organize the regimes; values at the reference operating
point (N = 8, lambda_s = 0.022, untiered unless stated):

    A      = w_miss / w_hit                          22.6
    Lambda = lambda_r * c_miss / (N * p)              2.2
    G      = S * (1 - theta) / (W(0) * g)            ~0.4
    Kappa  = N * C_cpu / (W_new * t_rec)             0.7-2.0 (sizes 250-500)
    Rho_r  = lambda_r * h_ext * c_miss / (N * B_r)   ~1.2

A is the feedback strength: A ~ 1 is a classical cache; A >> 1 makes
the write rate a state variable. Lambda is the cold-branch load
ratio: Lambda < 1 forbids a sustained cold state (bound (7));
Lambda > 1 makes it feasible and the outcome race-decided. G
compares the pinned-pool retention window to the reuse-gap scale g:
G < 1 means a backlogged fleet cannot hit, which enables the cold
branch; the same fleet at h = 0 with its backlog drained has
G ~ 1.7, which is why a cold but idle fleet re-warms. Kappa is the
tier-persistence ratio of rule (9): the measured fall-through sits
at Kappa < 1, the persistent congested regime at Kappa > 1. Rho_r is
the restore-channel load: Rho_r >= 1 pins the channel and the
congested queue diverges. The router-span dependence of Section 7 is
deliberately absent from these ratios - it is a property of how one
balancer couples N replicas' drain races (Section 7.8) - and the
theory's scope is the existence, location, and scaling of the
regimes at fixed span.

### 3.6 What the theory does not claim

The constructions are mean-field and first-order. They do not
predict collapse probability inside the band (outcomes there are
fluctuation-decided; the calibrated simulation of Section 8 carries
those claims, with documented biases), the magnitude of the span
shift (Section 8 reproduces its direction emergently), the timing of
delayed collapses, or the escape dynamics of the congested regime
(the model's documented recovery-branch failure, Section 8.6). Each
formula's anchor - mu(0) against the measured cold throughput, rule
(9) against the measured tier-size boundary, bound (10) against the
measured restore pin - is a consistency check at one operating
point, not a validated response surface.

## 4. Measurement methodology

### 4.1 Stack and instrumentation

All measurements run on TP4 GB200 fleets of 4, 8, or 16 replicas
serving Qwen3-Coder-480B-A35B-Instruct-FP8 under vLLM with block
size 256; each replica holds a KV pool of 6486 x 256-token blocks
(13.28M tokens at 8 replicas) (experiment-env.md). Requests reach
the fleet through an Envoy front end and an Endpoint Picker (EPP)
router. The router plugin configuration is a first-class
experimental factor, selected per run among three configurations: a
precise prefix-cache configuration (KV-event token-based affinity;
the baseline for the main series), an approximate-prefix
configuration with no KV-event pipeline, and a load-only
configuration (queue and KV-utilization scorers, no affinity signal)
(experiment-env.md).

Server state is scraped from per-replica metrics endpoints at 5 s
cadence, and fleet aggregates use replica endpoints only (the
service endpoint round-robins replicas) [C34]. Hit rate h is
computed as windowed counter differences of
vllm:prompt_tokens_cached over vllm:prompt_tokens; the
prefix_cache_queries/hits pair is not used because it re-counts
under pressure (experiment-env.md). On tiered fleets, the tier hit
fraction h_ext is the external (host-tier) hit-token fraction,
vllm:external_prefix_cache_hits over external_prefix_cache_queries
(token counters), and the restore share of hits is the fraction of
hit tokens served from the tier (overlay-findings.md). Time series
are aggregated into 5-minute windows anchored to wall clock so
concurrent runs align (analyze_run_windows.py). One gauge-semantics
caveat applies throughout: the vllm:num_requests_running gauge
excludes requests in WAITING_FOR_REMOTE_KVS, so server-side running
counts do not equal client-side load during restore phases [R9].

### 4.2 Workload

The primary corpus is a 393-session agentic coding replay set
(68,266 requests, mean ~174 requests per session), collected from
real coding-agent traffic and replayed with per-instance prefix
salting so replay instances share no cache (unsalted replays inflate
h) (experiment-env.md). The corpus exhibits the agentic structure of
Section 1: ~52k-token opening system prompts, few-thousand-token
per-turn increments, growth to a 249k compaction ceiling, bimodal
think times (78% of turns within seconds; a long human-pace tail),
and subagent fan-out in 44% of sessions. Inter-request idle gaps are
capped at 10.5 s, the corpus p90, making the replay a machine-pace
workload; the cap is an experimental control for the reuse-gap
distribution F (Sections 3.1, 10). Surge traffic replays a disjoint
232-session corpus so burst and base load share no session identity.

Arrival semantics determine whether collapse is reachable, so we
state them precisely. Open-loop experiments use Poisson session
arrivals at rate lambda_s with concurrency as an admission ceiling;
requests within a session remain completion-ordered. Closed-loop
experiments meter a fixed credit of in-flight work; the measured
credit multiplier is ~1.45x configured concurrency on this corpus,
so all load-axis statements use achieved in-flight [R8].
Request-metered rate mode is excluded from collapse experiments: it
re-issues work independently of completions, a built-in retry storm,
whereas completion-coupled session arrivals defer rather than storm.
Open-loop collapse experiments therefore pin demand at the session
level [R7][C33].

### 4.3 Perturbation protocol

Each collapse experiment resets every replica's prefix cache, runs
base load at lambda_s, and at t ~ +62 min launches a surge overlay
without cache reset: 0.25 sessions/s for 2700 s (the standard surge;
a 900 s variant probes the duration axis), with cancellation at
t ~ +107 min. The surge generator cancels its entire session
population on exit, so all post-cancellation dynamics are sustained
by the base load alone. Horizons run 150-300 min; Section 5.3 shows
why the long horizon is necessary. Closed-loop states are held 65
min before being read as stationary [R8].

A second perturbation variant removes the cancellation: the surge
generator carries a session-count cap instead of a stop time, so
arrivals cease once the cap is reached while every started session
and its subagent tree runs to natural completion [C38]. The
perturbation unit is then the injected cohort of cap sessions,
realized exactly in every run (sessions generated = admitted = cap,
with zero admission rejections across all ten surge injections). The
cohort is injected over ~600 s at 0.11-0.33 sessions/s; a late
export deadline bounds the surge generator's wall-clock time and
does not affect the classification windows. This variant models a
flash crowd that no operator evicts - the persistent-surge family of
Section 9.2 - and its outcomes are classified over the same base-run
windows as the cancellation protocol (Section 5.6).

![Figure 2](../out/paper/fig_protocol.png)

Figure 2. Perturbation protocol timeline. Prefix-cache reset on all
replicas at t=0; base Poisson session arrivals at lambda_s sustained
to the end of the 150-300 min horizon; eviction-scale surge overlay
(0.25 sessions/s x 2700 s, disjoint corpus, no cache reset) over
[62, 107) min, with the surge population cancelled at t=107 so the
post-cancellation drain-versus-catch-up race over [107, ~120) min is
base-sustained. The warm state is read over [30, 60] min, the drain
depth D (Section 5.5) over [115, 120) min, and end-state outcomes
are classified over [270, 295] min (cold if mean h < 0.15).

### 4.4 Comparability and run-to-run variance

Five factors are recorded per run and held fixed within any
comparison: router configuration, corpus, gap cap, salt, and
duration [C34]; run identifiers and per-run configurations are
recorded in the artifact register. An early reference series that ran
under different router configurations and unsalted generators is
excluded from all fits. Realized request rate varies ~+-0.4
requests/s between runs at fixed lambda_s and does not order
outcomes in the series where this was checked [R2][C04];
consequently every probabilistic statement in this paper is an
outcome count over repeated runs, never a response inferred from a
single run. Runs are treated as statistically independent: every run
starts from a cache reset, and a namespace-split check across the
two shard environments supports run-to-run variance over a fixed
environment effect. Two dependence structures remain and are carried
as confounds (Section 11): shard runs executed pairwise in shared
windows, and two same-configuration replicate pairs across days.

Two artifact-existence rules make absent data auditable rather than
silently missing: load-generator artifacts exist only after
end-of-run export (one hung export in ~40 runs through the
mid-campaign window, zero in the final 19-run window), and capacity
reclaim destroys un-scaled fleets, so an unconditional scale-down is
scheduled at window start [R12][C35].

### 4.5 Evidence grading

Every claim in this paper carries one of four grades, and the full
register appears in Appendix A. Demonstrated: direct measurement,
replicated or internally cross-checked; stated as fact with n
reported. Outcome frequency (n): a count over n repeated runs;
stated as the count, never as a fitted probability. Model-supported:
holds in the calibrated fluid/DES models; attributed to the model
with its validation scope. Open: a documented failure or unresolved
question, reported as such. Single-run observations are flagged
inline (n=1) and never support a probability, threshold, or trend on
their own. We regard the grading itself as methodology: metastable
phenomena produce run-to-run outcome variance at fixed operating
points (Section 5.2), and ungraded reporting of single runs is how
such phenomena are mis-measured.

## 5. Collapse phenomenology (untiered fleets)

### 5.1 Anatomy of an absorbing collapse

After the standard surge on an 8-replica untiered fleet at base rate
0.022 sessions/s, the system does not return to its pre-surge
operating point. It enters a cold state with hit rate h 0.016-0.030
(pre-surge warm h ~0.94), TTFT p50 rising to 240 s, queue growth
~1.1 requests/min to a waiting depth of 289, and throughput pinned
at 1.2-1.4 requests/s - the cold-branch service bound mu(0) of
Section 3.2. No recovery occurs over the observed post-surge
horizons (n=3 runs; ~73 post-surge minutes on the two 180-min
horizons, 195 on the 300-min horizon) [R1][C01]. The state is
self-sustaining: the surge process no longer exists after
cancellation, and the base load that the same fleet served warm
before the surge maintains the collapse indefinitely on the measured
horizon.

The mechanism visible in the measured trajectories is the
drain-versus-catch-up race of Section 3.2. The surge evicts the base
sessions' prefixes. After cancellation, the deferred base reservoir
drains back as catch-up flux; if that flux exceeds the cold-branch
service capacity before prefixes re-warm, misses regenerate the
eviction pressure and the fleet locks into the cold state [R1][R2].

![Figure 3](../out/paper/fig_arcs_composite.png)

Figure 3. Measured trajectories, one per regime class, under the
identical eviction-scale surge (shaded, t=62-107 min); all curves
are 5-min windows from per-replica scrapes, no model output. Warm
recovery at (N=8, 0.017): h returns to ~0.95, waiting ~0. Absorbing
collapse at (N=8, 0.022) untiered: h 0.013-0.030 after minute 200,
waiting climbing ~1.4/min to ~290 by minute 290. Delayed collapse at
(N=8, 0.020) untiered: warm until h falls from 0.89 at minute 240 to
0.05 by minute 280. Restore-bound congestion at (N=8, 0.022) with
the size-500 tier: h 0.65-0.77 with tier-hit fraction 0.62-0.75
(dashed) and linear waiting growth ~0.8/min. Complete recovery at
(N=8, 0.022) with the size-375 tier: h 0.97, waiting ~0 at minute
300.

### 5.2 The collapse-probability band

The identical perturbation applied across base rates yields a
probability band, not a threshold line. Outcome counts over 17 runs
[R2][C02]:

    lambda_s (sessions/s)  runs  outcome
    0.012                  2     recovers 2/2
    0.017                  4     recovers 4/4 (150-180-min horizons;
                                 post-surge KV occupancy 0.40-0.78
                                 across runs)
    0.020                  8     three outcome classes: recovery x3,
                                 delayed collapse x2 (cold by ~min
                                 240), immediate collapse x3 (onset
                                 min ~130-150); collapse 5/8 by
                                 300 min
    0.022                  3     collapses 3/3

Up to these n, the counts place the deterministic-collapse edge in
(0.020, 0.022]. These are outcome counts; no continuous
p(collapse | rate) curve is fitted to them. Among the 0.020 runs,
realized request rate does not order outcomes: one immediate
collapse occurred at realized 1.62 requests/s while one recovery
held at 1.78 [R2][C04]. The band sits where Section 3.3 places it:
above the cold-feasibility bound (7) at 0.0098 sessions/s, well
below the warm-capacity limit, in the region where both branches are
locally stable and entry is fluctuation-decided.

![Figure 4](../out/paper/fig_band_tally.png)

Figure 4. Outcome counts under the identical perturbation on the
8-replica untiered fleet at four base rates (n=17 runs): 0.012
recovers 2/2 and 0.017 recovers 4/4; 0.020 is bimodal over 8 runs
with recovery x3, delayed collapse x2, and immediate collapse x3
(collapse 5/8 by 300 min); 0.022 collapses 3/3, placing the
deterministic-collapse edge in (0.020, 0.022].

Two threshold axes are each indicated by one measured contrast pair
[R2][C03]. On the duration axis, at 0.022 the 900 s surge recovered
while the 2700 s surge collapsed - consistent with the
reservoir-depth reading of Section 3.3 (both surges fully evict the
pool; the longer one accumulates a six-fold deeper deferred
reservoir); a single 900 s recovery is also consistent with chance
under any collapse probability materially below one. On the flux
axis, a rate-0.017 run served 4.9 requests/s of post-cancellation
catch-up traffic and stayed warm, while a rate-0.022 run re-entered
collapse at 4.8: the instantaneous catch-up rate does not
discriminate outcomes; the sustained arrival flux lambda_s against
drain headroom does. No response curve is claimed on either axis.

### 5.3 Horizon dependence, delayed collapse, and hysteresis

Surviving the perturbation does not imply long-term stability. At
(N=8, 0.020), 2 of 8 runs that survived the surge and re-warmed
collapsed near minute 240 with no new perturbation: session
deepening gradually raises KV occupancy until it pins, and
per-replica pinning is near-synchronous (2 of 8 replicas to 8 of 8
within one 5-min window) [R3][C05]. This delayed class is visible
only at the 300-min horizon; 60-180-min runs overstate stability at
this operating point, and the 0.017 row of the band table carries
the corresponding caveat (its 150-180-min horizons would not see a
delayed tail if one exists). In the theory's terms, the warm
equilibrium at this operating point sits close enough to the
separatrix that endogenous occupancy drift can cross it without any
exogenous trigger.

The cold state exhibits hysteresis. The same fleet that serves the
base load warm cannot re-warm from cold at that load, and recovery
requires dropping demand below the band's lower edge; in the
closed-loop experiments, each in-flight level has a unique
equilibrium and recovery occurs when the in-flight credit is lowered
[R1][R8][C06]. The collapse is therefore a coexistence-band
phenomenon, not a capacity shortfall: the warm and cold branches
coexist at the same demand, as the theory's asymmetry argument
predicts (Section 3.3) - eviction runs on the pool-overwrite
timescale while re-warming runs on real time.

### 5.4 The closed-loop contrast

Closed-loop (completion-gated) arrivals self-stabilize instead of
collapsing. The measured boundary sits at achieved in-flight ~73
warm versus ~103+ degraded; degraded states are stationary rather
than absorbing; and the throughput function shows a flat segment
with cap-and-window co-movement (its falling segment is unreachable
statically and was not observed) [R8][C07]. Absorbing collapse
requires demand that does not yield to backpressure: either
inelastic request-pinned generation or a deferred session reservoir
whose refill outpaces its drain [R7][C07]. The open-loop
session-arrival protocol realizes the second condition - which is
also the condition agentic workloads realize in production. This
contrast locates the boundary between the queueing-stability
literature's assumptions (Section 2) and the regime where the
prefix-cache feedback dominates.

### 5.5 The drain-depth separatrix

The post-cancellation race has a measurable state variable: the
drain depth D, the fleet-mean KV-pool occupancy over minutes 115-120
of the protocol, the five-minute window opening eight minutes after
surge cancellation (separatrix-findings.md). D is the empirical
coordinate of the separatrix of Section 3.2 (Figure 1b): a shallow
drain (high D) means catch-up flux re-inflated the pool before
prefixes re-warmed, and the race is already lost when the window
closes.

At (N=8, 0.020), D separates immediate collapse from all other
outcomes in all 8 runs (two of the five non-immediate runs later
collapse via the delayed mechanism): immediate-collapse minimum
0.735, other-outcome maximum 0.663 [R15][C08]. The D reading
precedes erosion onset in 20 of 21 fitted runs, and the same
occupancy read five minutes earlier does not separate (one survivor
read 0.674 mid-drain), so minute 115 is the earliest clean read
point.

Across the 21 fitted standard-surge runs (10 collapse events; one
16-replica run is excluded because its surge backlog was still
pinned at the read point and its horizon ends at 135 min), a
Firth-penalized logistic fit of p(immediate | D, rate) gives D
signal beyond rate (penalized likelihood-ratio p ~ 0.044). The exact
stratified permutation test over the two mixed-outcome strata gives
one-sided p = 3/112 = 0.027. The signal is borne by the 8-replica
stratum: within (N=8, 0.020) the three immediate collapses hold
exactly the three highest D values (p = 1/56 = 0.018), while the
n=2 16-replica stratum at 0.037 is anti-aligned (the collapsing run
drained deeper than the surviving one) [R15][C08]
(out/separatrix_draws.csv, separatrix_fit.py). The within-stratum
test treats the two dedicated-fleet runs and the six shard runs as
exchangeable; the two delayed collapses are exactly the two
dedicated-fleet runs, and the conservative shard-only form gives
p = 1/20. The fitted p=0.5 thresholds are D* = 0.79, 0.69, 0.63 at
capacity-normalized rates 0.017, 0.020, 0.022; the 0.020 value sits
inside both the within-stratum separation interval (0.663, 0.735)
and the pooled 8-replica interval across all three rates. At n=21
the threshold's direction and location are established, its
steepness is not (the D coefficient's Wald 95% interval spans
roughly (1, 39)). D also orders the collapse-onset spectrum: among
the 12 fitted collapsing runs, pooled across fleet sizes, rates, and
collapse classes (all of which co-vary with D and onset), the rank
correlation between D and onset time is -0.99 - shallower drains
collapse earlier. The covariate was identified mid-campaign, so
these p-values are not from a pre-registered test; the three runs
measured after identification landed on the hypothesized sides of
the threshold.

Two scope limits bound the claim. First, the threshold moves with
rate and fleet size: at N=16, the 0.034 point survived D = 0.74 and
a 0.037 run collapsed from 0.65, each a single-run point observation
[R15][C09] - as expected if D is one coordinate of a separatrix that
also depends on rate and span, not a universal constant. Second, D
does not predict the delayed class: those runs win the drain race
from deep drains (D 0.616 and 0.663) and collapse ~2 h later by the
distinct occupancy-drift mechanism of Section 5.3 [R15][C09]. D is a
mediating observable of the drain race, not a control law. In the
pooled fit it is confounded with the N=16 indicator at n=21, because
every 16-replica run at the 0.020-equivalent point both drained
shallow and collapsed; the mediation interpretation rests on the
within-stratum permutation test and the model comparison of
Section 8 [C08].

![Figure 5](../out/separatrix_fit.png)

Figure 5. Drain-depth separatrix. D (fleet-mean KV occupancy,
minutes 115-120) versus capacity-normalized rate for the 21 fitted
runs, marked by outcome class; the line is the Firth-penalized
p(immediate) = 0.5 contour (D* = 0.79/0.69/0.63 at
0.017/0.020/0.022). The two delayed collapses sit at the deep end
and are not predicted by D; the 16-replica points illustrate the
threshold's span dependence.

### 5.6 Never-cancelled flash crowds

The cancellation protocol isolates hysteresis: it makes the pre- and
post-perturbation offered load exactly identical, so any persistent
degradation is attributable to system state. Its cost is realism:
in production, no operator evicts a surge population. The session-count-capped
variant of Section 4.3 removes the cancellation: a finite cohort of
new sessions arrives over ~10 minutes and runs to natural
completion. Nine runs at base 0.017 sessions/s on 8-replica
untiered fleets - a rate that recovers 4/4 from the cancelled
eviction-scale surge [C02] - map the outcome in cohort units [C36]:

    cohort   0 (control)   warm 2/2 (h ~0.96, waiting 0, 300 min)
    cohort  66             fully served 2/2; KV peaks 0.64-0.75,
                           pool never pins
    cohort 132             collapse 4/4, across two fleets
    cohort 198             collapse 1/1 (single run)

Every cohort-132 collapse begins within one 5-minute window of the
end of injection (t = 70-75 min) and remains absorbing through the
300-min horizon: end h 0.02-0.03,
KV 0.91-0.92, waiting 253-296 and still rising, TTFT p50 in the
100-400 s range. The collapse boundary in injected-cohort units lies
in (66, 132], roughly 2-4x the standing session population of ~36
(lambda_s x the ~22-40 min session lifetime); realized warm request
rates spanned 1.21-1.94 requests/s across the collapsing runs
without ordering outcomes [C04]. The bracket conflates two
thresholds - the cohort-66 runs never pinned the pool, so pool-pin
onset and collapse entry are not separated by these points - and the
cohort-198 point is a single run.

Two structural facts distinguish this protocol from overload. First,
the injected work is finite and demonstrably servable: in the runs
that recover, the identical cohort is served to completion and
waiting returns to zero. A collapse therefore leaves the same
offered workload permanently unserved - basin selection, not
capacity shortfall [C37]. Second, persistence, not magnitude, is the
operative axis: the never-cancelled 132-session cohort is roughly
5x smaller than the 675-session cancelled surge population from
which this base rate recovers 4/4. The two protocols differ in
injection rate and duration as well as in cancellation, so we state
this as a contrast between protocol families, not as a controlled
pair [C37]. In the calibrated DES the outcome coordinate is the
cohort size itself: matched-cohort cells at injection windows of
1-20 minutes give near-identical outcomes (Section 8.5); the
measured series ran a single injection shape per cohort, so
injection-shape insensitivity is model-supported only.

![Figure 6](../out/paper/fig_nocancel.png)

Figure 6. Never-cancelled flash crowds at base 0.017 sessions/s.
Top: fleet token hit rate; bottom: fleet waiting (symlog). One
representative run per configuration: no-surge control, cohort 66
(fully served, pool never pins), cohort 132 (collapsed; 4/4 across
two fleets), and the same cohort-132 perturbation on the size-500
tiered fleet (served to completion; Section 6.5), whose dashed curve
is the tier-hit share of hits. The
shaded band marks the ~10-min injection window only; the cohorts
persist beyond it.

## 6. The host-memory tier: a third regime

Adding a host-memory KV tier (vLLM CPU offloading; configured sizes
250/375/500 map to effective capacities 0.42/0.63/0.84M tokens per
replica, Section 8.2) to the 8-replica fleet does not remove the
collapse failure at supercritical rates. It transforms the failure
into restore-bound congestion, whose persistence is set by tier
capacity exactly as rule (9) of Section 3.4 predicts [R4][R11].

### 6.1 Restore-bound congestion

Under the standard perturbation at 0.022 sessions/s - the rate at
which the untiered fleet collapses 3/3 - the size-500 tiered fleet
enters a distinct degraded state in 4 of 6 runs (complete counts in
Section 6.4). Four discriminators separate it from cold collapse,
jointly present in all four congested runs (two at the 300-min
horizon) [R4]:

- Hit rate stays high: h 0.70-0.85, with tier-hit fraction h_ext
  0.62-0.79 and restore share of hits 0.66-0.79. Most hits are tier
  restores, not HBM-resident prefixes.
- The fleet restore rate is pinned at 150-192k tokens/s, which is
  0.81-1.04 of N * B_r for the effective per-replica restore rate
  B_r = 23k tokens/s (calibration provenance in Section 8.2;
  per-replica plateau 21.4-24.0k across all four congested runs at
  both fleet scales while demand exceeds it) - the restore-bound
  throughput of equation (10).
- KV occupancy holds at 0.93-0.94, and the tier ingests new writes
  only (measured offload rate 50-78k tokens/s tracks uncached
  prefill plus generation; restored blocks stay tier-resident).
- The queue diverges slowly and linearly, ~0.8 requests/min over 195
  min, with no transition to the cold state.

Against the cold absorbing state at the same operating point
(Section 5.1), the congested state delivers ~2.2x the throughput and
~4x better TTFT [R4]. The failure is not removed: the queue still
diverges, and the state persisted through both 300-min congested
runs.

![Figure 7](../out/overlay_restore.png)

Figure 7. Restore-bound congestion at (N=8, 0.022), size-500 tier:
measured trajectories (h, fleet restore rate, waiting) against DES
bands (5 seeds, 300 min). DES curves are model output (Section 8);
the four regime discriminators - pinned restore channel, linear
queue divergence, high h, no cold collapse - are reproduced in 5 of
5 seeds. Model quantitative gaps (h 0.95 vs measured 0.70-0.85;
restore share 1.0 vs 0.66-0.79) are stated in Section 8.3.

### 6.2 The pinned band is a state outcome, not a channel capacity

Reading B_r as a hard per-replica restore ceiling is falsified by
measurement. The two complete-recovery runs sustained 5-minute fleet
restore rates of 235k and 278k tokens/s - 1.28-1.51x N * B_r -
during their escape, then ran their post-cancellation restore phase
at 0.14-0.56 N * B_r with waiting 0.3-7 while KV occupancy drained
from 0.83-0.86 to 0.26-0.31 [R4]. Both measured values are reported;
at n=2, no distribution is claimed. The 150-192k band of Section 6.1
is therefore a congested-state throughput outcome. The raw DMA link
runs at 151.5 GB/s = 1.19M tokens/s per replica at ~2% duty in the
congested state, so per-transfer overhead, not the link, binds
there. The serial FCFS restore channel in the DES encodes the
falsified ceiling interpretation and stands as a documented model
deficiency; its concurrent-restore replacement fails the
recovery-branch screen and is not adopted (Section 8.6) [R9].

### 6.3 Complete recovery at the boundary: one matched pair

At base rate 0.020, inside the untiered probability band, the one
measured tiered run fully absorbs the surge: tier-hit fraction
0.42-0.73 for ~2 h with waiting 1-9, restore share decaying 0.64 to
0, KV occupancy draining to 0.05, and complete recovery by the end
of the 300-min horizon [R5]. The same-day untiered run at the same
operating point collapsed via the delayed mechanism at ~minute 240
[R3][R5]. This is one matched same-day pair, n=1 per side: it
demonstrates that the tier can convert a collapsing boundary point
into a complete recovery in at least one run, and supports no
recovery-probability claim at 0.020.

### 6.4 The size series: capacity sets persistence

Same-protocol runs at (N=8, 0.022) across configured tier sizes
[R11]:

    size (effective)   outcome count      note
    250 (0.42M)        cold collapse 1/1  enters congestion, then
                                          falls through it: tier-hit
                                          fraction decays to 0.01 as
                                          the working set outgrows
                                          the tier
    375 (0.63M)        complete           one run at elevated
                       recovery 2/2       realized rate (2.02
                                          requests/s)
    500 (0.84M)        4 congested,
                       2 complete
                       recoveries, of 6

The series separates the two mechanisms of Section 3.4. Tier
capacity - the varied parameter - sets regime persistence: a tier
too small to hold the recirculating working set loses its external
hits and falls through congestion into the cold state, and the
250/375 contrast brackets the persistence boundary exactly where
rule (9) places it (0.4-0.7M tokens per replica). The
congested-state throughput level is the pinned restore band of
Sections 6.1-6.2. Restore bandwidth itself was not varied, so its
effect on persistence is unmeasured. The 375-versus-500 contrast
(2/2 vs 2/6 complete recoveries) suggests a mild size effect but
leaves it unproven at these counts. Realized request rate does not
order outcomes across the series [R11].

![Figure 8](../out/overlay_tiercap.png)

Figure 8. Tier-capacity pair at (N=8, 0.022): measured size-250 and
size-500 trajectories with DES capacity-sweep bands (model output,
Section 8). The DES reproduces the direction and the
cold-persistence boundary of the pair - 250 falling through to cold,
500 staying congested - but produces no complete recoveries at this
rate; the recovery branch is a documented model failure
(Section 8.6).

The executable size series ends at configured size 500: size 650
does not boot on these hosts (the pinned tier plus an uncapped
sidecar file cache exceeds node-allocatable memory), so no statement
is made about larger tiers [R11].

### 6.5 The tier under a never-cancelled flash crowd: one run

The flash-crowd protocol of Section 5.6 was run once on the size-500
tiered 8-replica fleet at the same base rate, with the identical
cohort-132 perturbation that collapses the untiered fleet 4/4. In this
one measured run the tier avoids collapse entirely [C39]: fleet h
never drops below 0.86, waiting peaks at 87 (versus 286-491
untiered) with TTFT p50 of 12-21 s through the congestion phase,
72-93% of hits are tier restores from injection through minute
~180, the backlog then drains completely, and the end state is warm
(h 0.96, waiting 0, KV occupancy 0.37). A no-surge tier control run
stayed warm throughout. The tiered-run trajectory appears in Figure
6; at n=1 per configuration this supports no tier flash-crowd
probability or boundary claim.

The run also extends the ceiling falsifier of Section 6.2 from
transients to sustained operation [C40]: the 5-minute fleet restore
rate holds a median of 322-324k tokens/s across both the injection
and drain phases - roughly two hours at 1.75x N * B_r, with a peak
of 381k (2.07x) - while the congested runs of Section 6.1 pin at
0.81-1.04x. The effective per-replica constant B_r is a
congested-state outcome, and a fleet draining its backlog runs the
same channel well above it for as long as the backlog lasts.

This run resolved a prediction registered before it executed: the
calibrated DES, given the same protocol and tier capacity, produced
cold collapse in 7 of 10 seeds (Section 8.5). The measured complete
recovery lands on the opposite side, consistent in sign with the
documented recovery-branch failure (Section 8.6).

## 7. Router-span dependence

Collapse susceptibility depends on the number of replicas a single
router instance spans, at fixed per-replica load and fixed
per-replica physics. This section states the probabilistic result,
then works through an elimination argument: configuration
independence, scale-invariant per-replica physics, refutation of
load imbalance and (for the measured router) coordinator saturation,
an affinity-necessity ablation, shard containment, and the
per-replica signatures that survive elimination.

### 7.1 Probabilistic left-shift of the collapse curve

At capacity-matched operating points the collapse curve shifts left
with router span [R6]. The 16-replica single-router sweep: 0.034
sessions/s recovers 1/1 (n=1), 0.037 splits 1/2, 0.040 collapses 4/4
(one run truncated at 135 min with its surge backlog still pinned,
classified as collapsed at truncation and excluded from the Section
5.5 fit; one run under the approximate-prefix configuration, Section
7.2). In capacity-normalized rate these points sit at
0.017 / 0.0185 / 0.020. The 8-replica sweep at the same normalized
points: 0.017 recovers 4/4, 0.020 collapses 5/8, 0.022 collapses 3/3
(n=7 runs at 16 replicas, 15 at 8) [R6]. The mixed-outcome point
moves from 0.020 to 0.0185, a ~7.5% shift; the edge brackets bound
the shift only loosely (0 to ~16%). The counts bracket the shift but
do not establish it statistically at these n, and any apparent
steepening rests on the n=2 point; no fitted probability curve is
claimed.

The 16-replica collapses also differ in kind. Every one is
early-onset - hit-rate erosion underway by minute ~125-155 - and
fleet-total, across 5 collapses spanning days and configurations;
the delayed class of Section 5.3 does not appear at N=16 [R6][R10].

![Figure 9](../out/paper/fig_ladder_tally.png)

Figure 9. Collapse fraction per operating point on a shared
capacity-normalized rate axis: 8-replica sweep 0/4 at 0.017, 5/8 at
0.020, 3/3 at 0.022 (n=15); 16-replica single-router sweep 0/1 at
0.034, 1/2 at 0.037, 4/4 at 0.040 (n=7), plotted at
0.017/0.0185/0.020 normalized. The mixed-outcome point moves left
~7.5%; the 0.034 anchor is a single run. Dashed segments are visual
guides, not fitted probability curves.

### 7.2 Configuration independence

The 16-replica collapse at 0.040 does not depend on the router's
prefix-index implementation. It reproduces under the precise
prefix-cache configuration (3 runs) and under the approximate
baseline, which runs no KV-event pipeline and no token producer, in
one run (n=1) [R10]. The collapse is a property of span-coupled
routing over the fleet, not of any single scoring pipeline.

### 7.3 Per-replica physics is scale-invariant

The span dependence cannot be located in the replicas. The
per-replica decode-interference fit tpot = 10.8 ms +
2.56e-4 (R/N)^2 holds in the per-replica form; the alternative
fleet-total form is falsified by the saturated 4-replica windows
(Figure 10, out/tpot_fit.csv) [R6]. Restore bandwidth is likewise
per-replica (Section 6.1). With per-replica service physics
invariant in N, the span dependence must live in the coordination
layer [R6].

![Figure 10](../out/tpot_fit.png)

Figure 10. Per-replica decode interference: measured time-per-token
versus per-replica running load across 4/8/16-replica windows. The
per-replica quadratic form fits all fleet sizes; a fleet-total form
fails on the saturated 4-replica windows.

### 7.4 Load imbalance: refuted

Query-share dispersion across replicas is invariant in N in every
phase (warm-phase coefficient of variation 0.46-0.48 at N=4,
0.34-0.51 at N=8, 0.46-0.56 at N=16; recovery-phase 0.12-0.21,
0.21, 0.14-0.15 respectively; 15 runs) [R10]. The recovering shard
run shows higher share dispersion than the collapsing 16-replica
runs at matched relative times - the opposite ordering of what an
imbalance mechanism requires - and the max-share ratio grows with N
only as the extreme-value bias of a maximum over N samples.

### 7.5 Coordinator saturation: refuted for this router

Router-side resources were scraped on all 19 runs of the final
measurement window and are unsaturated throughout, including through
three reproducing 16-replica collapses [R13]: KV-event index
admissions track demand with no plateau (16-replica peak 3.3k/s,
twice the per-shard rate), event-pool queue depth ~0 in every
window, router CPU 1.9 of 4 uncontended cores, index lookups
0.4-0.9 ms, scheduler end-to-end ~0.1 ms, and remote tokenization
230-273 ms/request uniformly across healthy and collapsing runs.
This rules out coordinator saturation for this implementation at
these spans; it does not by itself establish any alternative
mechanism, and no claim is made for other coordinators.

### 7.6 Affinity necessity

A load-only router configuration (queue and KV-utilization scorers,
no affinity signal) at (N=8, 0.020) measures what routing affinity
carries [R14]. In the one measured run (n=1): warm h 0.53 versus
0.94 under the precise configuration, TTFT p50 2-4 s pre-surge - a
degraded but serving warm state - followed by absorbing collapse
after the surge with no recovery phase (end waiting depth 215, TTFT
p50 177 s). The necessity claim rests on the size of the warm-margin
loss and the absence of any recovery phase in this run, not on an
outcome frequency. In this run, affinity carried both the warm
hit-rate margin and the recovery path.

### 7.7 Shard containment

Two independent 8-replica routers over the same replica pool at
matched capacity-normalized load bound the blast radius [R10].
Across 6 shard runs, every shard collapse (4, including the
load-only ablation) stayed inside its own 8-replica partition; in
both concurrent mixed pairs the sibling shard served untouched while
its partner collapsed. Every 16-replica single-router collapse (5,
across days and configurations) was fleet-total. Containment is a
measured property of the router-span boundary, in the same fleet, at
the same normalized load.

### 7.8 Surviving mechanism: span coupling of the drain race

Three measured signatures separate N=16 from N=8 at matched fleet
state [R10]:

1. Hit-rate dispersion at equal fleet h. Warm fleet h is 0.94 at
   every N, but warm per-replica h standard deviation rises
   1.4-2.1x (from ~0.032 at N=4/8 to 0.044-0.067 at N=16);
   busier replicas run warmer (correlation of share and h 0.57-0.86
   everywhere), so the dispersion is a coordination signature, not a
   load-balance defect.
2. Excess occupancy and miss-write flux at the matched re-warm
   state. At the drain-window read point the 16-replica fleet
   carries the same per-capacity session state in 0.15-0.20 more of
   its pool and sustains ~1.7x the per-capacity miss-write flux
   relative to the 8-replica trajectories, with a 4-5 point h
   deficit spread across the whole fleet and a measured retention
   window of 58 s versus ~190 s.
3. Staggered pinning cascade. The 16-replica collapse re-pins
   replica by replica - 3/16 at t=115, 11/16 at t=120, 14/16 at
   t=125, 16/16 at t=130 - with per-replica h spreading to
   0.10-0.67 before fleet-wide erosion, whereas the 8-replica
   delayed collapse pins near-synchronously (2/8 to 8/8 within one
   5-min window).

![Figure 11](../out/paper/fig_cascade.png)

Figure 11. Per-replica dynamics through the post-cancellation window
(300 s windows from raw per-replica counters). (a) Count of replicas
with KV occupancy > 0.85: the 16-replica collapse re-pins in a
staggered cascade while an 8-replica recovery at the matched
normalized rate never exceeds 3/8 transiently pinned replicas after
the surge tail. (b) Per-replica h median with interquartile band:
both fleets re-warm to comparable per-replica h by t=115 (16-replica
median 0.88 vs 8-replica 0.92), then the 16-replica fleet erodes
with widening dispersion while the 8-replica fleet holds h
~0.90-0.94.

With load imbalance refuted (7.4) and coordinator saturation
excluded (7.5), the surviving explanation is span coupling of the
post-cancellation drain race: a collapse seeds locally, and the
shared balancer spreads cold catch-up flux - full-context
re-prefills for sessions whose prefixes were evicted elsewhere -
onto still-warm replicas, duplicating prefixes and eroding fleet h,
while independent shards contain the same seed inside one partition
[R10]. This is an elimination-plus-reproduction argument, not a
direct observation of scatter, and its two elements carry different
support: the duplication element rests on the measured per-replica
signatures jointly with the ablation and coordinator evidence; the
span-coupling element is additionally reproduced by the DES, which
carries the deployed router algorithm, no N-dependent term, and
shifts the collapse curve left emergently (Section 8.3) [R9].
Whether the model's 16-replica collapses also exhibit the
per-replica signatures has not been checked (Section 11). The
containment contrast itself is demonstrated directly by the shard
measurements. Client records carry no serving-replica identity, so
session-to-replica scatter is not directly observable in the
collected data.

## 8. Calibrated models: fluid and discrete-event

### 8.1 Construction

Two model layers share one calibration. The fluid model evolves a
session reservoir with completion-coupled turn release, per-replica
decode interference, and a contended fleet restore channel; restores
form a third max() term in the waiting-time expression, achieved
restore traffic advances the HBM write clock, and the tier churns at
the measured ingest rate with hit-refresh [R9]. Arriving (salted)
sessions enqueue a forced full-miss first request as an explicit
queue class, and surge populations are cancelled at surge end,
matching the protocol.

The DES adds the discrete structure the fluid cannot carry:
watermark admission (waiting requests join a replica's batch, full
KV need reserved, while the batch fits under the occupancy
watermark; the prefill engine stays serialized), a two-clock LRU
(the HBM clock advances with prefill, restores, and generation; the
tier clock with new writes only; touch stamps refreshed at decode
end), and a per-replica FCFS restore channel at B_r with
asynchronous onboarding [R9]. A single-clock tier variant was
rejected against measurement: it drives the tier to exhaustion and a
cold collapse that the 300-min hardware run refutes, and it
contradicts the measured tier-ingest rate.

The deployed-router layer replaces the idealized lexicographic
router with the deployed EPP algorithm, every scheduling constant
read from deployed configuration or plugin code, none fitted:
prefix-affinity sticky threshold 0.80; TTFT load gate 18000 ms with
TTFT estimated as in-flight tokens over the deployed peak prefill
throughput of 28888 tokens/s; token-load scoring; and the 300 s
in-flight staleness reap, under which deep engine queues undercount
and the gate rarely triggers under backlog [R9]. The model contains
no coordinator term: an earlier coordinator-saturation freeze is
rejected on two independent grounds - the router-side measurements
of Section 7.5 contradict its physical interpretation, and it is
unnecessary (no outcome classification changes without it at the
300-min horizon). The idealized router serves as a negative control:
it produces identical collapse rates at capacity-matched points
(3/5 at both (N=8, 0.020) and (N=16, 0.040)), so the measured span
dependence is not reproducible from scheduling idealizations plus
per-replica physics.

### 8.2 Calibration

Every constant and its provenance; the single fitted quantity is the
effective tier capacity (an assumed size-linear nominal times the
fitted efficiency).

| Constant | Value | Source |
|----------|-------|--------|
| Prefill rate p | 17k tokens/s/replica | measured saturated uncached plateaus, 131-138k tokens/s fleet [R9] |
| HBM pool C | 6486 blocks x 256 tokens per TP4 replica | engine configuration; byte size cross-checked against KV/token [R9] |
| Decode interference | tpot = 10.8 ms + 2.56e-4 (R/N)^2 | fit over 552 measured windows (Figure 10); per-replica form selected, fleet-total form falsified on saturated 4-replica windows (RMSE 27.4 vs 18.6 ms) [R9] |
| Restore rate B_r | 23k tokens/s/replica effective | measured per-replica restore plateau, 21.4-24.0k across four congested runs at both fleet scales [R4]; a congested-state throughput calibration, not a channel ceiling (Section 8.5) |
| DMA link | 151.5 GB/s = 1.19M tokens/s/replica | measured from offload counters; B_r runs the link at ~2% duty, so per-transfer overhead binds [R4] |
| KV per token | 127 KB (fp8, 62 layers, 8 KV heads, dim 128) | validated against the pool byte size; windowed host-to-device bytes / 127 KB matches the windowed tier-hit token rate to under 1% in every tiered run [R9] |
| E_req | 118 realized requests/session | 28,366 records / 240 sessions in the 3 h windows; the corpus mean of 174 inflates demand ~40% and moves the model boundary off the measured bracket |
| Reuse-gap CDF | corpus mixture, capped at 10.5 s | the protocol gap cap, an experimental constant [R9] |
| First-request size | ~51.6k tokens | system prompt plus first input; forced full miss per arriving salted session |
| Router constants | 0.80 / 18000 ms / 28888 tokens/s / 300 s | read from deployed configuration and plugin sources; none fitted [R9] |
| Tier nominal capacity | 2520 tokens/replica per configured size unit (size 500 = 1.26M) | ASSUMED size-linear mapping anchored at size 500 to the 160 GB/replica host-RAM headroom at 127 KB/token; the configured-unit-to-byte semantics are unconfirmed (Section 11) |
| Tier efficiency | 0.67 (FITTED) | cold-side ordering of the tier-size series: effective(250) = 0.42M must sit at or below the DES cold/congested transition and effective(375) = 0.63M at or above it, the in-model transition spanning (0.42, 0.63)M; the congested-state miss share independently implies an effective window below nominal [R9]. Because the nominal is assumed, the product (0.42/0.63/0.84M at sizes 250/375/500) is in substance a single fitted effective-capacity scale |

### 8.3 Validation

![Figure 12](../out/overlay_b1_dynamics.png)

Figure 12. Fluid overlay on the four protocol configurations (0.022,
0.017, 0.012 sessions/s untiered at N=8; 0.011 with tier at N=4);
surge window shaded; model curves labeled as model output. The
waiting-queue trajectories match in all four configurations,
including the post-cancellation re-growth in the collapsing one.

![Figure 13](../out/des_b1_overlay.png)

Figure 13. DES validation configurations, 5 seeds each, min-max
shading; deployed-router outcomes: collapse 4/5 at 0.022 (measured
3/3), recovery 5/5 at 0.017 and 0.012, recovery 5/5 for the
4-replica tiered configuration.

![Figure 14](../out/overlay_nseries.png)

Figure 14. DES fleet-size sweep (12 seeds x 6 configurations, 300
min, no coordinator term) with measured runs overlaid; the
16-replica collapse curve sits left of the 8-replica curve at
matched normalized rate. Model output; absolute placement carries
the documented reservation bias.

![Figure 15](../out/paper/fig_hysteresis.png)

Figure 15. Model coexistence band (DES, deployed router, N=8,
untiered, 3 seeds per point, 300-min horizon; model output).
End-state hit rate versus session rate for the unperturbed protocol
(warm branch) and the standard-surge protocol. Between roughly 0.017
and 0.022 sessions/s the two branches coexist: unperturbed runs stay
warm where perturbed runs end cold. At higher rates the warm branch
itself decays by the delayed mechanism of Section 5.3. Placement
carries the documented leftward reservation bias (Section 8.4).

![Figure 16](../out/paper/fig_phase_diagram.png)

Figure 16. Model outcome map over (session rate, effective tier
capacity) under the standard perturbation (DES, deployed router,
N=8, 3 seeds per cell, 300-min horizon; model output). The untiered
row reproduces the probability band; the smallest tier falls through
to cold at supercritical rates; larger tiers convert collapse into
persistent congestion. The model produces no complete recoveries in
the congested cells - its documented recovery-branch failure
(Section 8.6) - so the measured complete-recovery outcomes at sizes
375-500 have no model counterpart in this map.

The model reproduces, in order of evidential weight [R9]:

- The untiered band and outcome classes. Under the deployed-router
  model: collapse at 0.022 in 4/5 seeds (measured 3/3), recovery 5/5
  at 0.017 and 0.012, and the 4-replica tiered recovery 5/5 at its
  180-min horizon. An earlier idealized-router revision additionally
  matched the in-surge peak waiting depths (620-787 modeled against
  675-790 measured on the 8-replica configurations), showed smooth
  20-40 min hit-rate erosion where the fluid transition is square,
  and produced the post-cancellation warm interlude in every
  collapsing seed (the measured interlude/no-interlude pair sits
  inside the seed spread).
- The third regime, all four discriminators in 5/5 seeds: restore
  channel pinned near N * B_r, linear slow queue divergence, high h,
  no cold collapse (Figure 7). Quantitative gaps are stated, not
  fitted: model h 0.95 vs measured 0.70-0.85, restore share 1.0 vs
  0.66-0.79, completion rate 1.6 vs 2.5-4.3 requests/s.
- The size-250 fall-through in direction and persistence boundary.
  This is calibration-constrained rather than independent
  validation - the tier efficiency is fitted to exactly this
  cold-side ordering - so only the trajectory shape and seed
  structure are non-fitted. Under the final calibration the fine
  capacity sweep gives cold 5/6 at effective 0.42M while the
  size-500 configuration runs congested 6/6, never cold, with the
  DES mean tracking the measured decay-through-congestion
  trajectory (Figure 8).
- The span shift, emergent in direction. With no N-dependent term,
  DES collapse counts at 300 min (12 seeds per configuration) are
  2/12, 11/12, 12/12 at (N=8) 0.017/0.020/0.022 and 5/12, 12/12,
  11/12 at (N=16) 0.034/0.037/0.040. The shift is visible at the
  0.017-equivalent pair (5/12 vs 2/12), a seed-level contrast that
  does not reach significance at 12 seeds (one-sided exact p ~
  0.19); the upper matched pair is ceiling-saturated and carries no
  shift information. The direction matches the measured sweep. The
  shift arises from the deployed router's affinity-load arbitration
  coupling every replica's post-cancellation drain race; the
  idealized router - equally fleet-spanning and load-balancing -
  produces no shift (Section 8.1), so a shared span alone does not
  produce it, and which deployed feature drives it is not isolated
  (Section 11). The model predicts shard routers behave as
  independent 8-replica systems, matching the measured containment
  [R10].

### 8.4 Known biases

Full KV need is reserved at batch admission (vLLM allocates blocks
progressively during chunked prefill), which overstates running-set
residency during backlog drains. Both DES collapse curves sit left
of the measured ones as a consequence; the model's quantitative
claim is the shift and the outcome-class structure, never absolute
collapse probabilities [R9]. Further documented limitations: decode
interference is frozen at decode start; there is no
preemption/recompute path; collapsed-state h floors at 0 in most
seeds versus the measured 2-12% residual.

### 8.5 Executed falsifiers

Predictions were registered before hardware windows and are reported
regardless of outcome.

- The 4-replica tiered configuration at 300 min: predicted waiting
  depth 52-160; measured 1.3, stable 3/3 (one run at the full
  horizon). Falsified; the miss is assigned to the recovery branch
  (Section 8.6) [R9].
- The tier 375/650 bracket, registered under the prior tier
  efficiency of 0.5 (which placed 375 inside the predicted cold
  region): 375 completely recovered 2/2, excluding 0.5 and forcing
  the recalibration to 0.67; the 650 configuration was not
  executable (boot failure, Section 6.4) [R11][R9].
- The 16-replica edge points: the sweep's left shift is confirmed in
  direction by the measured counts (Section 7.1; the 0.034 recovery
  is n=1). The DES collapses 5/12 at 0.034 where the one measured
  run recovered; an n=1 measurement is uninformative about that rate
  (a recovery has probability 7/12 under the model's own counts).
- The fleet-total interference form: registered and falsified by the
  saturated 4-replica windows (predicted 33 ms vs measured 81 ms
  mean time-per-token); the per-replica form replaced it
  (Section 7.3) [R6][R9].
- The B_r ceiling interpretation: encoded in the serial FCFS
  channel; falsified by the two complete-recovery runs
  (Section 6.2). The 23k plateau is a congested-state outcome. The
  serial channel stands as a documented deficiency; its
  concurrent-restore replacement fails the recovery-branch screen
  and is not adopted (Section 8.6). The tiered flash-crowd run
  extends the falsifier to sustained operation: ~2 h at 1.75x N * B_r
  (Section 6.5) [C40].
- The 4-replica tiered end state, repeated: the registered
  prediction for the two repeat runs was waiting depth
  75-142 at the horizon end; both measured 0, with in-surge
  saturation (waiting peaks 347 and 395) recovering within one
  window of cancellation. The configuration is now stable in 5 of 5
  runs including two at 300 min, and the miss remains assigned to
  the recovery branch [C30][C41].
- The tiered flash-crowd configuration: registered before execution
  as a discriminator - the DES predicted cold collapse in 7 of 10
  seeds for the never-cancelled cohort-132 perturbation on the
  size-500 tier; the one measured run served it to completion
  (Section 6.5). The prediction is resolved against the model, with
  the same sign as the recovery-branch failure [C41].
- The flash-crowd cohort boundary (untiered): the DES sweep that
  motivated the measured series places deterministic collapse at
  cohort ~67 (10/10 seeds) and the 50% point at ~49 at base 0.017,
  with matched-cohort cells insensitive to injection windows of 1-20
  minutes; the measured bracket is (66, 132] (Section 5.6). The
  model boundary sits below measurement by a factor under 2, the
  same sign and comparable magnitude as the reservation bias of
  Section 8.4, and the cohort-size coordinate itself is the design
  variable derived from the model and confirmed qualitatively by
  measurement [C41]. The model's no-perturbation control at base
  0.022 collapses by the delayed mechanism in 3 of 10 seeds at 300
  min; the measured series therefore ran at 0.017, where both the
  model control (10/10 warm) and the measured controls (2/2 warm)
  remain warm.

### 8.6 Documented failures and the recovery branch

The recovery branch is the model's primary open failure: zero
complete recoveries in 30 sweep runs at (N=8, 0.022) at any tier
capacity, against 4 measured in 8 runs at sizes 375-500; the missed
complete recovery at the 0.020 boundary; the repeatedly falsified
4-replica prediction above; and the missed flash-crowd outcome
(predicted cold in 7 of 10 seeds; the one measured run completely
recovered, Section 6.5). The failure therefore extends to the
never-cancelled protocol with the same sign [R9][C41]. The failure is one-sided: the DES reproduces
cold collapse, restore-bound congestion, and the untiered
recoveries, but cannot exit the congested state through drain-back.
The fluid layer carries a second documented failure, branch
selection at cancellation: it reproduces the in-surge restore-bound
state but flushes its restore backlog within ~2 min of cancellation
and exits to the warm branch at both scales; the DES,
restore-serialized with heterogeneous gaps, diverges - matching
measurement. Both layers sit near the same critical balance, and no
fluid constant flips the branch without violating a measurement, so
the DES is the validated layer for the third regime.

Four candidate mechanisms for the recovery-branch failure were
screened on a shared protocol (seven configurations spanning tier,
untiered, capacity, and span variants; 6 seeds; 300 min), with the
guard constraint that any candidate preserve the cold/congested
boundary and the untiered band. All four screens are negative; none
is adopted; each is summarized here with its exclusion scope, and
the artifacts carry the full protocols.

1. Reservation timing (progressive KV allocation, removing the
   full-reservation-at-admission overstatement): negative and
   informative - the screened configuration remains 0/6 recovered,
   and the variant manufactures a non-physical interference-locked
   congested state in an untiered control configuration that the
   engine's step-budget scheduler cannot enter. Its retained value
   is diagnostic: every failing baseline run drains from waiting
   depth 319-745 to a trough of 0-31, then re-enters congestion.
2. Stale-content tier churn (a credit bracket subtracting dead-surge
   write tokens from tier ages - the complete-instantaneous-
   reclamation bound): null; outcome counts match baseline in every
   configuration, and the instrumented run shows live write flux
   churns dead content out of the model's window ~13 min after
   cancellation with a rescuable live-miss fraction of 0.0
   thereafter. Definitive exclusion within the two-clock
   abstraction.
3. Restore-channel serialization (concurrent onboarding at the
   measured 1.19M tokens/s link with a derived 4.23 s per-transfer
   overhead): negative; failing configurations still re-enter
   congestion, and the congested pin overshoots the measured
   0.81-1.04 N * B_r band (peaks 1.91x).
4. Occupancy-gated HBM eviction (allocation-pressure-only eviction
   replacing the unconditional aging clock, zero new constants,
   pre-quantified as small since the trap itself pins occupancy near
   0.88): negative; control configurations pass, screened
   configurations fail 5/6, and the trap relocates - pending-restore
   entries hold 0.69 of the fleet pool as full-KV reservations
   queued behind the serial channel.

Jointly the screens sharpen the failure to a re-entry trap: failing
model runs drain to near-empty queues, then every completion
re-admits a full-context restore (model restore share 1.0, ~100k
tokens per restore) where the measured congested state runs
h 0.70-0.85 with tier-hit fraction 0.62-0.79. Candidates 3 and 4
bound the trap's carrier - with the channel widened it pins via
elevated restore throughput; with residency corrected it pins via
reservation-holding backlog - so the surviving suspect is the
restored volume per tier hit interacting with full-KV reservation at
admission (partial-context restores, or tier-content staleness
outside the two-clock window model), not channel capacity,
reservation timing, or residency semantics [R9]. We present this as
the diagnosis of an open model failure, not as a result. The
gauge-semantics caveat of Section 4.1 applies to any successor
variant: restore-in-flight entries must not feed the decode
interference term while still holding reservations.

## 9. Mitigation: reservoir smoothing at admission

The theory locates the point of control. Collapse entry is a race in
the (hit rate, backlog) plane (Section 3.2), and the one input a
serving platform controls without touching the engine is which
requests join the backlog. This section screens four admission
controllers in the calibrated deployed-router model at the
deterministic-collapse point (N=8, lambda_s=0.022, untiered), under
two protocols, against the uncontrolled baseline; it then tests
whether the failure the controllers guard against is specific to the
deployed router's policy at all. All results in this section are
model output on the DES of Section 8, with its documented
reservation bias; no controller has been validated on hardware.

### 9.1 Controllers

All four controllers act at session granularity: they gate the first
request of a new session, and turns of admitted sessions are never
deferred, preserving the completion-coupled cadence of agent loops.

- Deferral gate (defer). New sessions are held in a fleet-level FIFO
  reservoir while the fleet is near the basin boundary - waiting
  depth above W_HI = 48 or KV occupancy above 0.85 - and released at
  most one per 5 s while waiting depth is at or below W_LO = 24.
  This is the shared admission-control abstraction of asynchronous
  request processing (queue-to-durable-storage, dispatch when idle
  [llmdasync]), router-level request queueing, and concurrency
  gating; its signals, occupancy against the watermark and backlog
  depth, are the coordinates of the separatrix of Sections 3.2 and
  5.5, so the gate stops admitting before the basin boundary is
  crossed rather than after. Threshold placement matters: the
  release threshold must clear warm-state waiting (~10 at this
  rate); an earlier variant with W_LO = 8 held a persistent residual
  reservoir at steady state.
- AIMD concurrency control, published constants (aimd-pub). A
  CONCUR-style [chen2026concur] window over concurrently active
  sessions: every 5 s the window grows by 2 when fleet KV occupancy
  is below 0.2 and halves when occupancy exceeds 0.5 while the
  trailing-minute hit rate is below 0.2 (alpha=2, beta=0.5,
  U_low=0.2, U_high=0.5, H_thresh=0.2, transplanted verbatim);
  sessions beyond the window defer FIFO. This is a session-admission
  adaptation: CONCUR's mid-session pausing at tool boundaries is not
  modeled.
- AIMD, fleet-tuned constants (aimd-tuned). The same rule with the
  occupancy thresholds re-scaled to fleet warm occupancy
  (U_low=0.65, U_high=0.85, H_thresh=0.5).
- Early rejection (reject). Mooncake-style [qin2025mooncake]
  admission-time rejection: a new session is dropped permanently if
  the predicted queueing delay (queued prefill tokens over fleet
  prefill rate) exceeds 30 s. This models the rejection family with
  a prefill-bound load predictor; Mooncake's own predictor projects
  decode-stage load.

### 9.2 Protocols

The screen runs each controller under the standard perturbation
protocol of Section 4.3 and under a persistent-surge variant in
which surge arrivals stop at t=107 min but already-arrived surge
sessions are never cancelled. The distinction determines what the
evaluation measures. Under the standard protocol, work a controller
defers past the cancellation point is work it never has to do, so
any mechanism that delays surge admission scores well. Under the
persistent variant the deferred work is real: offered work exceeds
the horizon's total service capacity by construction, and the
informative metrics are served volume, end-state class, and the
delay imposed on deferred sessions - the regime an asynchronous-serving deployment
actually faces. Aqua's argument that admission control trades away
burst responsiveness [aqua2025] applies to rejection; deferral pays
in queueing delay on a durable queue instead of in lost work, and
the persistent-surge protocol quantifies that delay explicitly. The
persistent family is realized on hardware: in the measured
flash-crowd series of Section 5.6, a never-cancelled cohort well
inside total service capacity collapses the uncontrolled untiered
fleet 4/4 [C36]. The controller screen itself
remains model-level (Section 9.5).

### 9.3 Results

![Figure 17](../out/paper/fig_mitigation.png)

Figure 17. Admission controllers at (N=8, 0.022, untiered), standard
perturbation, 5 seeds, 300 min; model output. Left: outcome
fractions under the cancellation protocol and the persistent-surge
protocol. Right: requests served in 300 min, split base/surge, with
min-max whiskers.

Under the cancellation protocol every controller beats the
uncontrolled baseline (cold 5/5, 27.5-30.6k requests served): the
deferral gate ends recovered in 4 of 5 seeds (one degraded at h
0.69) serving 35.8-38.3k; both AIMD variants end recovered 5/5
serving 34.3-42.6k; early rejection ends recovered 3/5 (one
congested, one cold) serving 37.3-42.9k while permanently rejecting
572-643 sessions per run. Under this protocol alone, AIMD ranks
best.

The persistent-surge protocol reverses the ranking. The uncontrolled
fleet ends cold 5/5 with end-state waiting depth 1467-1631. The
deferral gate again ends recovered in 4 of 5 seeds (one degraded at
h 0.76), with end-state waiting 15-24, serving 31.2-36.4k requests
against the baseline's 26.0-28.7k, and holding a draining reservoir
of 714-783 sessions whose released members waited a median of
143-175 minutes - the explicit price of smoothing a sustained
overload on a durable queue. Both AIMD variants collapse in 4 of 5
seeds, ending cold with served volume at or below the uncontrolled
baseline (23.9-29.4k). Early rejection splits (2 cold, 2 degraded, 1
recovered) while rejecting 772-861 sessions per run.

The mechanism behind the reversal is the controllers' signals. The
AIMD decrease trigger - occupancy high while hit rate is low - is
the collapse signature itself: it fires only after the fleet has
crossed the basin boundary, and under a persistent reservoir the
window re-admits sessions into the trap as fast as completions free
slots. Under the cancellation protocol this reactive control is
never exposed, because the window's ordinary admission pacing
incidentally shields the fleet until the surge population is
deleted. The rejection predictor has the same defect one layer
earlier: queued-delay is a lagging proxy for cache state, so
rejection begins after eviction is underway and stops while the
drain race is still being lost. The deferral gate's occupancy and
backlog signals approximate the separatrix coordinate directly,
which is what makes it the only controller of the four that holds
the fleet on the warm side of the race in both protocols.

A guard row at (N=8, 0.017), a rate at which the model recovers 2/3
uncontrolled (its known leftward bias, Section 8.4), checks for
regressions at a stable operating point: the deferral gate recovers
3/3 with warm hit rate
unchanged; aimd-pub recovers 3/3; aimd-tuned degrades 2 of 3 runs
(end h 0.77-0.79 with a standing reservoir) - re-scaled constants
that help at the collapse point throttle a healthy one; and
rejection recovers 3/3 at the cost of 514-609 permanent rejections
at an operating point that mostly recovers on its own. Rejection
converts risk into certain loss; deferral converts it into delay.

### 9.4 The band is not the router's

![Figure 18](../out/paper/fig_router_family.png)

Figure 18. The standard perturbation under three routing policies
(N=8, untiered, 3 seeds per point, 300 min; model output): the
deployed EPP policy, an emulation of the SGLang cache-aware
threshold-switch policy [sglang2024] (imbalance gate at 32 absolute
/ 1.0001 relative, prefix-match threshold 0.5), and an emulation of
the AIBrix prefix-aware policy [aibrix2025] (imbalance gate at 8
running requests, least-loaded among matching replicas). Emulations
use engine-truth match state, the policies' best case.

All three policies produce the same band structure: recovery
dominates at 0.017, mixed outcomes at 0.020, and collapse at 0.022
(the deployed policy and the SGLang emulation show identical
outcome counts; the AIBrix emulation recovers one of three runs at
0.022).
The collapse is therefore not a defect of the deployed router's
scoring pipeline - consistent with the measured configuration
independence of Section 7.2 - but a property of the
affinity-versus-load feedback family that all production
prefix-aware routers implement. Two emulation caveats: the real
SGLang router matches on an approximate router-side radix tree
whose divergence from engine state can only widen the gap to these
best-case results, and both emulations run at a single-router span,
so they say nothing about the span dependence of Section 7.

### 9.5 Scope

Everything in this section is model output at one operating point
per claim, with the calibrated DES's documented biases (Section
8.4). The controllers act on new-session admission only; a
deployment would add priority classes (the FIFO reservoir makes
late-arriving interactive sessions queue behind deferred bulk work,
visible in the persistent-surge base-session counts) and would need
the gate thresholds set relative to measured warm-state waiting, not
as constants. The AIMD baseline inherits published constants from an
engine-scoped controller and omits mid-session pausing; the
rejection baseline uses a simpler predictor than its archetype. None
of this replaces hardware validation: the planned confirmation is
the deferral gate at the measured (N=8, 0.022) collapse point,
realized with the platform's asynchronous request processing or
flow-control gate, against the measured uncontrolled outcome of
Section 5.1.

## 10. Operational implications

Each statement below restates a measured result; the controllers of
Section 9 are model-tested only, no controller has been validated on
hardware, and no numeric threshold transfers beyond the measured
stack.

- Horizon rule. Benchmarks shorter than ~300 min overstate stability
  at boundary operating points: 2 of 8 surviving runs at
  (N=8, 0.020) collapsed by the delayed mechanism near minute 240,
  past every 60-180 min window (Section 5.3) [R3].
- Routing affinity is a stability parameter, not a latency
  parameter. In the one measured run (n=1), the load-only
  configuration ran warm at h 0.53 versus 0.94 and collapsed after
  the surge with no recovery phase (Section 7.6) [R14].
- Router span is a blast-radius parameter. Every measured 16-replica
  collapse was fleet-total; independent 8-replica shard routers
  contained every collapse inside the failing partition
  (Section 7.7) [R10]. Sharding is a measured containment boundary.
- Drain-depth observables are early-warning candidates. D separates
  immediate collapse from other outcomes in all 8 runs at the
  boundary point and adds signal beyond rate over 21 runs
  (Section 5.5) [R15]. D is a mediating observable whose threshold
  moves with rate and span and which does not predict the delayed
  class; unlike a fixed-constant admission threshold
  [chen2026concur], deployment use would require local (rate, N)
  calibration.
- Tier sizing is a persistence decision, not only a hit-rate
  decision. At (N=8, 0.022) the smallest tier falls through
  congestion to cold collapse (n=1) while the two larger sizes never
  go cold in 8 runs (Section 6.4); capacity sets regime persistence
  per rule (9), and the pinned restore channel sets congested-state
  throughput per bound (10), with restore bandwidth itself unvaried
  [R11].
- Flash crowds are sized in cohorts, not rates. A never-cancelled
  arrival burst collapses the untiered fleet once the injected
  cohort reaches 2-4x the standing session population (4/4 at the
  measured point, boundary bracket (66, 132] sessions at base
  0.017), even though the same work is fully served in the runs that
  recover (Section 5.6) [C36][C37]. The size-500 tier served the
  same cohort to completion in the one measured run (Section 6.5)
  [C39]. Peak session-open rate is the wrong alarm variable;
  cumulative never-evicted admissions relative to the standing
  population is the measured one.

One model-supported implication (Section 9, not measured): admission
control for this failure should key on basin coordinates - KV
occupancy and backlog depth - and defer rather than reject.
Controllers keyed on the collapse symptoms themselves (hit rate,
queueing delay) engaged only after the basin boundary was crossed in
the model screen, and rejection spent permanent losses at operating
points that mostly recover unaided.

## 11. Limitations and future work

Scope. All measurements come from one stack: one model
(Qwen3-Coder-480B FP8), one corpus family, one router
implementation, GB200 TP4 fleets at N in {4, 8, 16}. Numeric
thresholds do not transfer. The mechanism of Section 3 requires only
an LRU prefix cache, full-context re-prefill on miss, and
non-yielding demand, and the theory states which quantities to
re-measure elsewhere (w_miss/w_hit, E_req, F, p, B_r); reproduction
on a second stack is future work.

Gap cap. The protocol caps reuse gaps at 10.5 s, making the replay a
machine-pace workload; Section 3.1 quantifies how the cap moves the
static retention analysis. Production traffic with the human-pace
tail restores gap mass at minutes-to-hours, which enlarges the
retention-driven contribution to coexistence; the capped protocol is
therefore conservative about the phenomenon's breadth, not
generous.

Single-run observations. The following rest on n=1 and never solely
support a probability, threshold, or trend: both sides of the 0.020
tier/untiered matched pair [R5]; the size-250 fall-through [R11];
the 16-replica 0.034 point [R6]; the approximate-configuration
16-replica collapse [R10]; the load-only ablation [R14]; the tiered
flash-crowd complete recovery and its sustained 1.75x N * B_r
restore rate [C39][C40]; the cohort-198 point [C36]. The two collapse-threshold
axes each rest on one measured contrast pair [R2], and the B_r
transient falsifier on two complete-recovery runs [R4]. The
persistence-versus-magnitude statement of Section 5.6 is a
cross-protocol contrast whose controlled form - the same injection
cancelled at its end - has not been run [C37].

Flash-crowd series gaps. The cohort bracket (66, 132] is wide and
conflates the pool-pin threshold with the collapse threshold (the
cohort-66 runs never pinned); injection-shape insensitivity is
model-supported only, because the run intended to inject the
collapse-inducing cohort within ~2 minutes lost its surge generator
to an infrastructure fault and executed as an additional
unperturbed control (reported per the artifact-existence rule of
Section 4.4 [C35]).

Confounding and run dependence. D and the N=16 indicator are
confounded at n=21 (every 16-replica run at the 0.020-equivalent
point both drained shallow and collapsed), so the fitted separatrix
cannot separate a span effect from a drain-depth effect at this
sample size [R15]. Shard runs executed pairwise in shared windows;
two same-configuration replicate pairs span days; all outcome counts
treat runs as independent (Section 4.4). The two delayed collapses
are exactly the two dedicated-fleet runs, so dedicated and shard
runs may not be exchangeable; the conservative shard-only
permutation form gives p = 1/20 (Section 5.5).

Model gaps. The DES misses the delayed-collapse onset class (its
onsets form a 135-205 min continuum where the measured onsets are
bimodal) [R15]. Which deployed-router feature carries the emergent
span shift is not isolated, and whether the DES 16-replica collapses
exhibit the measured per-replica signatures of Section 7.8 is
unchecked. The recovery branch is the primary modeling front
(Section 8.6). The serial restore channel remains a documented
deficiency whose ceiling interpretation is falsified by measurement
[R4].

Mitigation scope. The Section 9 screen is model output at one
operating point per claim: no controller ran on hardware, the
deferral gate's thresholds are placements relative to this fleet's
warm state rather than transferable constants, the AIMD baseline
omits CONCUR's mid-session pausing, the rejection baseline uses a
prefill-bound delay predictor simpler than Mooncake's, and the
router-policy emulations use engine-truth match state at a
single-router span. The FIFO reservoir carries no priority classes,
so deferred bulk work delays later interactive arrivals; class-aware
release is unevaluated. Hardware validation of the deferral gate at
the measured collapse point is the planned next experiment.

Statistics that would tighten with hardware: the 16-replica 0.034
(n=1) and 0.037 (n=2) points, the size-375 tier (n=2) with
realized-rate covariates, the immediate-versus-delayed class
split at 0.022, a cohort near 100 to split the flash-crowd bracket,
a replicate of the tiered flash-crowd run together with a larger
cohort, and the same-injection cancelled variant for the persistence
contrast; none blocks the present claims. The tier
unit-semantics question stands: confirming the RAM accounting behind
the nominal tier capacities before any larger-tier experiment [R11].
Six related-work full-text reviews remain outstanding before
submission (related-work-sweep.md): [ao2026congestion],
[vanrooyen2026collapse], the retry-storm section of
[pandey2026failureatlas], the caching and load-balancing chapters of
[nixon2026yearserving], the thrashing passage of [yuan2026agentic],
and [aqua2025]; the SGLang and AIBrix policy constants of Section
9.4 are read from project documentation and source and are verified
against the released versions before submission.

## Appendix A. Claim register

Every claim, its evidence, and its grade (Section 4.5). Grades:
DEM = demonstrated; FREQ(n) = outcome frequency over n runs;
MODEL = model-supported; OPEN = open problem. Rows condense
paper/claims-map.md, which carries full evidence pointers and hedge
requirements; single-run flags are inline.

| ID | Claim | Grade |
|----|-------|-------|
| C01 | Absorbing cold state after the standard surge at (N=8, 0.022): h 0.016-0.030, TTFT p50 240 s, throughput 1.2-1.4 requests/s, zero recovery over 195 post-surge min | DEM (n=3; one 300-min horizon) |
| C02 | Collapse outcome is a probability band: 0.012 recovers 2/2, 0.017 4/4, 0.020 collapses 5/8 in three classes, 0.022 collapses 3/3 | FREQ(17) |
| C03 | Two threshold axes: surge duration (900 s recovers, 2700 s collapses) and sustained flux vs drain headroom | DEM (one contrast pair per axis) |
| C04 | Realized rate varies ~+-0.4 requests/s at fixed lambda_s and does not order outcomes | FREQ(8) |
| C05 | Delayed collapse near minute 240 in 2/8 surviving runs; sub-300-min horizons overstate stability | FREQ(8) |
| C06 | Hysteresis: no re-warm from cold at a load served comfortably warm; recovery requires shedding below the band | DEM |
| C07 | Closed-loop arrivals self-stabilize; absorbing collapse requires non-yielding demand | DEM |
| C08 | Drain depth D separates immediate collapse in 8/8 runs at the boundary and adds signal beyond rate over 21 runs (permutation p = 0.027) | FREQ(21) |
| C09 | The D threshold moves with rate and span; D does not predict the delayed class | FREQ(21); span points n=1 each |
| C10 | Third regime at (N=8, 0.022, size 500): h 0.70-0.85, restore pinned at 0.81-1.04 N*B_r, queue diverging ~0.8/min | DEM (n=4, two 300-min) |
| C11 | The pinned band is a state outcome, not a capacity: complete recoveries sustained 1.28-1.51x N*B_r | DEM (n=2) |
| C12 | At 0.020 the tier converted a collapsing point into complete recovery | FREQ(1 per side); single-run pair |
| C13 | Tier capacity sets persistence: 250 falls through 1/1, 375 recovers 2/2, 500 splits 4 congested / 2 recovered of 6 | FREQ(9); 250 single-run |
| C14 | Tier boot envelope ends in (500, 650) on these hosts | DEM |
| C15 | Collapse curve shifts left with span: mixed point 0.020 -> 0.0185 normalized (~7.5%; brackets 0-16%) | FREQ(7 at N=16, 15 at N=8); 0.034 single-run |
| C16 | Every 16-replica collapse is early-onset and fleet-total | FREQ(5) |
| C17 | The 16-replica collapse is configuration-independent | FREQ(4); approximate-config point single-run |
| C18 | Shard routers contain every collapse inside one partition | FREQ(6 shard runs, 5 fleet-total collapses) |
| C19 | Load imbalance refuted: query-share dispersion is N-invariant | DEM |
| C20 | 16-replica signatures: h dispersion, excess occupancy and miss-write flux, staggered pinning cascade | DEM (observables); mechanism reading inferred |
| C21 | Coordinator resources unsaturated through three reproducing collapses | DEM |
| C22 | Affinity necessity: load-only configuration runs warm at h 0.53 and collapses with no recovery phase | FREQ(1); single-run |
| C23 | Surviving span mechanism: coupling of the drain race, reproduced emergently by the DES | MODEL (mechanism); DEM (containment) |
| C24 | Per-replica physics is scale-invariant; span dependence lives in the coordination layer | DEM |
| C25 | One calibration, every constant measured or read from deployment, one fitted scale (effective tier capacity) | DEM (provenance) |
| C26 | Model reproduces the band, four congested discriminators 5/5, tier fall-through direction, span-shift direction (emergent) | MODEL |
| C27 | Both model curves sit left of measurement (reservation bias); no absolute probabilities claimed | MODEL |
| C28 | The coordinator-saturation term is retired: contradicted by measurement and unnecessary | DEM |
| C29 | B_r-as-ceiling is falsified; the serial restore channel is a documented deficiency | DEM (falsifier); OPEN (deficiency) |
| C30 | Recovery branch: zero model complete recoveries vs 4/8 measured; 4-replica end-state prediction falsified repeatedly (stable 5/5, two 300-min runs) | OPEN |
| C31 | Four recovery-branch candidates screened negative, each with stated exclusion scope | MODEL (exclusions) |
| C32 | The failure sharpens to a re-entry trap; surviving suspect is restored volume per tier hit under full-KV reservation | OPEN |
| C33 | Request-metered load generation is a built-in retry storm; session-level demand pinning is required | DEM |
| C34 | Comparability requires fixing router configuration, corpus, gap cap, salt, duration; h from cached-token counter differences | DEM |
| C35 | Artifact-existence rules make absent data auditable | DEM |
| C36 | Never-cancelled flash crowds at (N=8, 0.017, untiered): cohort 132 collapses the fleet 4/4 across two fleets, 198 collapses 1/1, 66 fully served 2/2 without pinning, controls warm 2/2; boundary (66, 132] cohort units ~ 2-4x the standing population | FREQ(9); cohort-198 single-run |
| C37 | Basin selection, not overload: recovering runs serve the identical cohort completely; the collapse-inducing cohort is ~5x smaller than the cancelled surge population from which the same rate recovers | DEM (cross-protocol contrast; controlled same-injection pair not run) |
| C38 | Session-count-capped arrivals realize exact never-cancelled cohorts (generated = admitted = cap, 10/10 jobs) | DEM |
| C39 | The size-500 tier serves the collapse-inducing cohort to completion: h >= 0.86 throughout, waiting peak 87 vs 286-491 untiered, drained by minute ~180, end warm | FREQ(1); single-run |
| C40 | Sustained restore above the effective ceiling: ~2 h at 1.75x N*B_r (peak 2.07x) while serving the flash-crowd backlog | DEM (one trajectory; single run) |
| C41 | Pre-registered discriminators resolved against the model: the tiered flash-crowd configuration (predicted cold 7/10; measured complete recovery) and the repeated 4-replica end-state prediction; the untiered model cohort boundary sits below the measured bracket by < 2x | MODEL / OPEN |

## References

- [aibrix2025] The AIBrix Team. AIBrix: Towards Scalable,
  Cost-Effective Large Language Model Inference Infrastructure.
  arXiv:2504.03648, 2025.
- [ao2025fluid] R. Ao, G. Luo, D. Simchi-Levi, X. Wang. Optimizing
  LLM Inference: Fluid-Guided Online Scheduling with Memory
  Constraints. arXiv:2504.11320, 2025.
- [ao2026congestion] R. Ao, J. Dong, G. Luo, D. Simchi-Levi.
  Service-Induced Congestion in Memory-Constrained LLM Serving.
  arXiv:2606.15555, 2026.
- [aqua2025] Aqua. ASPLOS '25, ACM, 2025.
  https://dl.acm.org/doi/10.1145/3676641.3715983. Cited for its
  admission-control-versus-burst-responsiveness argument; full-text
  verification pending (Section 11).
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
- [llmdasync] The llm-d project. llm-d-async: asynchronous request
  processing for llm-d. Software,
  https://github.com/llm-d/llm-d-async, 2026.
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
- [sglang2024] The SGLang team. SGL Model Gateway: cache-aware load
  balancing router. Software and documentation,
  https://docs.sglang.ai/, 2024-2026.
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
