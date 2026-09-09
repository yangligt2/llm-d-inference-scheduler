# Threat matrix

Output of the sweep specified in related-work-sweep.md. Sorted by threat
level. Claims C1-C6 are defined in that document. Bibtex keys refer to
related-work.bib.

Result: no KILL. Three REFRAME, the rest CITE-DIFF or BACKGROUND.

## 1. Summary table

| # | Paper | Verdict | Overlap | Threat to C1+C2 |
|---|---|---|---|---|
| 1 | CONCUR, arXiv:2601.22705 (Jan 2026) | REFRAME | C1 (empirical), C6b | Preempts the observation, not the model |
| 2 | Service-Induced Congestion, arXiv:2606.15555 (Jun 2026) | REFRAME | C2 (analytical, different state), C3, C6 | Preempts "first instability analysis of LLM serving memory dynamics" |
| 3 | TraceLab, arXiv:2606.30560 (Jun 2026) | REFRAME | C5 | None; erodes C5 |
| 4 | Metronome, arXiv:2607.02640 (Jul 2026) | CITE-DIFF | C2 (vocabulary only) | Vocabulary collision on "metastable" in LLM serving |
| 5 | Rosensweig et al., INFOCOM'13 | CITE-DIFF | C2 (general caches) | Prior art for multiple cache steady states |
| 6 | Nie, Si, Zhou, arXiv:2605.04595 (ICML'26) | CITE-DIFF | C2 (stability condition, memory as constraint) | Low |
| 7 | Ao et al., arXiv:2504.11320 | CITE-DIFF | C3, C6b | Low |
| 8 | Huang et al., OSDI'22 | CITE-DIFF | C2 (class definition) | Reviewer will ask "how is this different" |
| 9 | Bronson et al., HotOS'21 | CITE-DIFF | C2 (class definition) | Framing dependency |
| 10 | Farahbakhsh et al., arXiv:2606.00942 | CITE-DIFF | C2 (predictive method) | Low |
| 11 | Alvaro et al., arXiv:2510.03551 | CITE-DIFF | C2 (formal method) | Low |
| 12 | KVCache Cache in the Wild, ATC'25 | CITE-DIFF | C5, C1 (measurement) | Low |
| 13 | UniCache, SIGMETRICS'26 | CITE-DIFF | C1 (eviction policy) | Low |
| 14 | Mooncake, FAST'25 | CITE-DIFF | C6b | Low; supports motivation |
| 15 | Che et al. 2002; Fricker et al. 2012 | CITE-DIFF | C1 (method basis) | None; we build on it |
| 16 | Denning 1968 | CITE-DIFF | C2, C6b (analogy) | Reviewer analogy to defuse |
| 17 | Keepalive Economics, arXiv:2607.19214 | CITE-DIFF | C5, C6 | None |
| 18 | IMPRESS FAST'25; LMCache; CachedAttention | CITE-DIFF | C4 (mechanism) | None |
| 19 | QLM SoCC'24 | CITE-DIFF | C6b | None |
| 20 | Mitzenmacher and Shahout 2025 | CITE-DIFF | C2 (survey framing) | None |

## 2. REFRAME entries

### 2.1 CONCUR (arXiv:2601.22705)

`chen2026concur`. Chen, Ye, Tang, Sun, Tian, Wang, Li, Wen, Han, Zhang.
"CONCUR: High-Throughput Agentic Batch Inference of LLM via
Congestion-Based Concurrency Control." arXiv:2601.22705 [cs.DC],
30 Jan 2026.

**Their claim.** Agentic batch inference exhibits "middle-phase
thrashing", a regime occupying over 90% of execution time in which KV
cache usage sits at 80-100% while the prefix cache hit rate collapses and
recomputation consumes 49.1% of end-to-end latency; an AIMD-style
admission controller over active agent count, keyed on cache usage and
hit rate, restores hit rate and raises throughput up to 4.09x.

**Overlap.** C1 (empirical only), C6b.

**Verdict.** REFRAME. This is the closest published statement of the
phenomenon. Read of the full text establishes the limits: cache hit rate
is a measured signal, never a modeled state variable; there is no fixed
point, equilibrium, stability derivation, bistability, hysteresis, or
load-up/load-down asymmetry anywhere in the paper; hit rate versus
concurrency exists only as three table points per system (DeepSeek-V3,
batch 16/32/40: 80.4 / 77.7 / 35.4 percent) with no knee estimated; and
no experiment reduces load after collapse, so irreversibility is neither
measured nor claimed. The controller is preventive, with fixed constants
(alpha=2, beta=0.5, U_low=0.2, U_high=0.5, H_thresh=0.2) held across all
models and workloads and no basin or recovery semantics. Their mechanism
also differs from ours: they attribute the collapse to agents paused for
tool calls losing LRU recency, an exogenous-gap effect, not to the
miss-write amplification that closes our feedback loop.

**Differentiation draft.** CONCUR reports the phenomenon we model:
prefix-cache hit rate collapsing while memory remains fully occupied, and
throughput falling as concurrency rises. It stops at the empirical
observation and an AIMD heuristic over agent admission, with fixed
thresholds tuned once and no account of why the collapse occurs, at what
capacity and load it begins, or whether it is reversible. We supply the
missing model: hit rate as the endogenous fixed point of a Che
characteristic-time recursion in which the cache write rate is itself a
function of the hit rate, from which the collapse boundary in (capacity,
load) and the hysteresis loop follow analytically and are then confirmed
in discrete-event simulation. Their fixed U_low is brittle precisely
because it is a proxy for a basin edge that moves with workload and
capacity; our c_crit(l) predicts where that edge sits.

### 2.2 Service-Induced Congestion (arXiv:2606.15555)

`ao2026congestion`. Ao, Dong, Luo, Simchi-Levi. "Service-Induced
Congestion in Memory-Constrained LLM Serving." arXiv:2606.15555
[math.OC], 14 Jun 2026, 101 pages.

**Their claim.** In a discrete-time dynamical model of continuous
batching, serving endogenously grows aggregate KV memory until eviction
is forced; under saturated input the eviction-free fixed point is
unstable for homogeneous workloads and trajectories converge outside a
measure-zero set to a unique worst-case limit cycle costing up to 50%
throughput, with a two-class stability criterion and a coprime-decode-
length condition separating stable from synchronized-unstable regimes.

**Overlap.** C2 (multiple attractors in LLM serving, analytically
derived), C3 (arrival regime matters), C6.

**Verdict.** REFRAME. This is the strongest analytical adjacency and the
main reason the paper's framing must change: we can no longer present
"dynamical instability in LLM serving memory" as new territory. It does
not reach C1. The state variable is the aggregate KV footprint of
in-flight requests, which grows one token per decode step per request;
prefix caching, cache reuse, and hit rate do not appear anywhere. The
multiplicity is fixed-point versus limit-cycle coexistence driven by
arithmetic synchronization of decode lengths, not saddle-node
bistability, and no hysteresis, path dependence, or load-sweep asymmetry
is claimed. Note the same group's `ao2025fluid` (arXiv:2504.11320) is the
antecedent and should be cited together.

**Differentiation draft.** Ao et al. establish that memory-constrained
LLM serving is a dynamical system with non-trivial attractors, and their
instability arises from the KV footprint of running requests growing one
token at a time until eviction forces recomputation. Our feedback runs
through a different resource and a different loop: the reuse cache, where
a miss re-prefills the full context and writes roughly 65 times the KV
volume of a hit, so the cache write rate is a decreasing function of the
hit rate it determines. The resulting structure is also different in
kind. Theirs is a limit cycle whose stability turns on arithmetic
relations between decode lengths; ours is a saddle-node bifurcation
producing two stable branches, a computable boundary in (capacity, load),
and a measured hysteresis loop, none of which appear in their analysis
because their model contains no cache reuse term.

### 2.3 TraceLab (arXiv:2606.30560)

`zhu2026tracelab`. Zhu, Jacob, Ma, Pan, Wang, Krishnamurthy, Kasikci.
"TraceLab: Characterizing Coding Agent Workloads for LLM Serving."
arXiv:2606.30560 [cs.LG], 29 Jun 2026.

**Their claim.** A trace of 4,265 Claude Code and Codex sessions
(357,161 LLM steps, 432,510 tool calls, Sep 2025 to Jun 2026) shows long
autonomous loops, long inputs with short outputs, heavy-tailed tool
latency, and high but imperfect prefix cache hit rates (95.7% overall,
84.4% on user-initiated steps), with idle gaps beyond five minutes
driving most misses.

**Overlap.** C5.

**Verdict.** REFRAME, scoped to C5 only; no threat to C1+C2. C5 as
originally written claimed the agentic characterization itself. TraceLab
publishes an overlapping characterization first, on a larger and public
corpus, and its Figure 12 eviction-timeout sweep is a retention-window to
hit-rate curve, that is, the exogenous-window special case of our Che
window. Two substantive differences preserve a narrower C5. First, their
population shows minimal fan-out (1.2 tool calls per step, P99 4, no
subagent analysis) and compaction in 9.7% of sessions, whereas our
calibration trace has subagents in 44.5% of conversations carrying about
58% of requests and compaction as a recurring sawtooth; the two traces
describe different tenant mixes and should be presented as complementary.
Second, TraceLab reports no hit-rate time series, no load or concurrency
dependence, and no discussion of eviction under memory pressure, so it
contains no instability evidence.

**Differentiation draft.** TraceLab characterizes coding-agent traffic
and quantifies the cache-relevant structure of it, including the
retention window needed to capture human think-time gaps. We use trace
characterization differently: not as the contribution but as the input
functionals (gap CDF, forced-miss fractions, context trajectory,
per-class request mix) that parameterize a cache-dynamics model and make
its phase boundary predictable for a given deployment. Their
eviction-timeout sweep holds the retention window fixed and exogenous;
the point of our model is that in a capacity-bounded fleet the window is
endogenous, set by a write rate that the hit rate itself controls, which
is what admits two stable operating points at one offered load.

## 3. CITE-DIFF entries

### 3.1 Metronome (arXiv:2607.02640)

`meng2026metronome`. Meng, Li. arXiv:2607.02640 [cs.SD], 2 Jul 2026.
The only work found that applies metastability vocabulary to LLM KV
memory.

**Their claim.** Full-duplex real-time interaction models pin a
monotonically growing per-session KV state, so sustained load produces an
abrupt stall that latency and deadline-miss telemetry do not predict;
capping resident state per session eliminates it (0 of 20 runs versus 14
of 20) and makes latency a usable admission signal.

**Overlap.** C2, vocabulary only.

**Verdict.** CITE-DIFF. Full-text check: no occurrence of hysteresis,
bistable, multiple equilibria, basin, or cache hit rate. Their model is
Equation 1, rho(t) = rho_0 + N r t with t_sat = (1 - rho_0)/(N r), a
linear open-loop fill with r fitted from early trace data and no
dependence on occupancy, latency, or admitted concurrency. It has one
absorbing state and structurally cannot express two branches or recovery.
The stall is described as permanent under open-loop audio, and no
trigger-removal or load-reduction experiment is run. The "metastable"
label rests on run-to-run outcome variance, that is, variance in r
shifting t_sat across the session-length threshold.

**Differentiation draft.** Metronome names a KV-memory collapse in
real-time interaction serving metastable on the basis of run-to-run
outcome variance, and fixes it by bounding per-session residency. The
underlying model is a linear open-loop fill to an absorbing saturation
point, with no reuse, no hit rate, and no feedback term, so it predicts a
collapse time rather than a collapse boundary. Our system is metastable
in the Bronson sense: a sustaining feedback loop through the reuse cache
holds the degraded state after the trigger is removed, which we
demonstrate as a hysteresis loop with distinct collapse and recovery
loads and confirm by shedding below the lower band edge to walk the
system back.

### 3.2 Rosensweig, Menasche, Kurose (INFOCOM'13)

`rosensweig2013steady`. The classical precedent a reviewer is most likely
to raise against C2's novelty.

**Their claim.** Certain cache networks are non-ergodic, so the
steady-state cache configuration depends on the initial state; three
independently sufficient conditions (topology, admission control,
replacement policy) guarantee a single ergodic component.

**Overlap.** C2, in general caches.

**Verdict.** CITE-DIFF, and cite pre-emptively. Multiple steady states in
a caching system are not new in the abstract. Their multiplicity is a
combinatorial property of content placement across interconnected caches
under request forwarding; there is no load parameter, no capacity-load
phase boundary, no amplification mechanism, and no hysteresis sweep.

**Differentiation draft.** Non-uniqueness of cache steady state is known
for cache networks, where Rosensweig et al. show that interconnected
caches can be non-ergodic and give sufficient conditions for a single
ergodic component. Their multiplicity comes from content placement
dependencies across a topology at fixed demand. Ours comes from a scalar
feedback within a single logical cache tier: the write rate is an affine
decreasing function of the hit rate because misses re-prefill full
contexts, which produces a one-dimensional map with a saddle-node
bifurcation, hence a boundary in (capacity, load) and a hysteresis loop
that a placement-multiplicity result does not predict.

### 3.3 Nie, Si, Zhou (arXiv:2605.04595, ICML 2026)

**Their claim.** A queueing model incorporating compute and GPU memory
limits yields stability and instability conditions for LLM inference that
size clusters from arrival rates, matching production GPU measurements
within about 10%.

**Overlap.** C2, with memory as a constraint.

**Verdict.** CITE-DIFF, exactly as anticipated. Memory bounds the
admissible batch; it is not a state with its own feedback, and no cache
hit rate enters the stability condition.

**Differentiation draft.** Nie et al. derive stability conditions in
which GPU memory is a capacity constraint on concurrency. In our setting
the cache is not a constraint but a state variable with feedback: its
occupancy determines the hit rate, the hit rate determines the write
rate, and the write rate determines the retention window that sets the
hit rate. A constraint yields a single stability threshold in arrival
rate; a feedback loop of this sign yields a region of load where two
stable hit rates coexist, which is what we compute and measure.

### 3.4 Ao, Luo, Simchi-Levi, Wang (arXiv:2504.11320)

Fluid-limit online scheduling with endogenous memory growth; threshold
admission rules widen the stability region. CITE-DIFF, overlaps C3 and
C6b. Cite jointly with `ao2026congestion` as the same research line. Our
difference is the one stated in 2.2: their endogenous quantity is
per-request KV growth, not cache reuse.

### 3.5 Metastable failure literature (A)

`bronson2021metastable`, `huang2022wild`, `farahbakhsh2026characterizing`,
`alvaro2025formal`, `isaacs2025analyzing`. All CITE-DIFF; they define the
class, and our contribution is an instance plus a predictive model.
Huang et al. matter most because they reproduce a look-aside-cache
hit-rate collapse, which is the nearest existing demonstration.

**Differentiation draft.** The metastable-failure literature defines the
class and catalogs instances, including a look-aside cache whose hit rate
collapses and stays collapsed after the trigger clears. That work
demonstrates existence and provides taxonomy; it does not predict, for a
given deployment, where the vulnerable region begins. We give a closed-
form boundary for one instance in which the amplification factor is
unusually large and directly measurable: a prefix-cache miss re-prefills
the entire context, writing roughly 65 times the KV volume of a hit, so
the sustaining effect is quantified from workload functionals rather than
inferred after an incident. Farahbakhsh et al. argue prior work described
symptoms rather than causes and call for prediction; our fixed point is a
worked example of the prediction they ask for.

### 3.6 Production and system measurements (C, F, G)

- `wang2025kvcachewild` (ATC'25). Two weeks of Aliyun Tongyi traces:
  ideal hit rates 62% and 54%, 10% of KV blocks serve 77% of reuses,
  single-turn reuse as important as multi-turn, cross-user hits rare,
  KV lifespan ephemeral. CITE-DIFF for C5 and as an independent
  measurement of the reuse structure our model assumes. No load
  dependence or instability reported.
- `ouyang2026unicache` (SIGMETRICS'26). Trace-driven prefix-cache
  simulator over vLLM; session versus structural reuse; a unified
  eviction policy raising hit rate up to 17.32%. CITE-DIFF: eviction
  policy at fixed capacity, no dynamics.
- `qin2025mooncake` (FAST'25). Early rejection under overload.
  CITE-DIFF and useful: the practitioner mitigation our model explains.
- `zheng2024sglang`, `srivatsa2024preble`, `gao2024cachedattention`,
  `liu2024cachegen`, `liu2025lmcache`, `chen2025impress`. CITE-DIFF for
  C4 mechanism; all treat tiering as a mechanism, none analyzes tier
  sizing or restore bandwidth as the binding constraint.
- `zhu2025prefixprefill` (IEEE Cloud 2025), `khailo2026keepalive`
  (arXiv:2607.19214). CITE-DIFF for C5 and C6. The latter is a
  client-side keepalive cost analysis over commercial APIs; it observes
  that under a saturated tier billed per read, "LRU eviction has nothing
  to rank", which is an externality argument adjacent to our
  capacity-cliff result but contains no capacity model.
- `patke2024qlm` (SoCC'24). CITE-DIFF for C6b: queue management and
  request eviction driven by SLO estimates, not cache state.
- `che2002hierarchical`, `fricker2012versatile`. CITE-DIFF as the method
  basis. State plainly that the Che approximation is theirs and that the
  extension is making T depend on a write rate that depends on the hit
  rate.
- `denning1968thrashing`. CITE-DIFF. A reviewer will call this
  thrashing; answer that Denning's multiprogramming-level control is the
  correct ancestor for C6b and that the difference is a quantified,
  workload-calibrated boundary rather than a qualitative regime.
- `mitzenmacher2025queueing`. CITE-DIFF as the survey placing the open
  problems.

## 4. BACKGROUND (cite in passing or omit)

Splitwise and the Azure LLM inference traces; BurstGPT; Andes
(arXiv:2404.16283); LAWS (arXiv:2605.04069, fleet-learning convergence
and monotone hit-rate theorems, adjacent vocabulary only); BanaServe
(arXiv:2510.13223, notes that high-hit-rate prefill nodes attract
disproportionate load, a routing-imbalance observation); DLPM
(arXiv:2501.14312); Bidaw, SolidAttention, CacheSlide (FAST'26 two-tier
KV storage); "Comparative Characterization of KV Cache Management
Strategies" (arXiv:2604.05012); KV-cache compression literature
generally.

## 5. Section 6 reviewer ammunition

Prior observations of LLM cache hit-rate instability, collected but not
acted on.

1. CONCUR Figure 3, from an unspecified large-scale deployment: KV usage
   pinned at 80-100% while hit rate drops precipitously and stays low for
   over 90% of execution time. The single strongest published artifact
   for the motivation section.
2. CONCUR Table 2: hit rate 80.4 / 77.7 / 35.4 percent at batch 16 / 32 /
   40 on DeepSeek-V3 under SGLang. A collapse knee measured by someone
   else, on different hardware, with a different serving stack.
3. CONCUR's stated reason request-level admission fails: it delays agents
   "until cached state has already been evicted". This is a path-
   dependence statement from practitioners who were not looking for one.
4. Metronome: collapse invisible to latency and deadline-miss telemetry;
   14 of 20 identical five-minute runs collapse and 6 survive. Outcome
   bimodality under identical conditions, independently observed.
5. TraceLab Figure 11: beyond about five minutes of idle gap, low-hit-rate
   steps appear; after one hour nearly all steps miss. Establishes that
   the retention window is the operative variable in agentic traffic.
6. KVCache Cache in the Wild: production ideal hit rates of 62% and 54%,
   well below synthetic-benchmark expectations, at a large cloud provider.
7. Mooncake's early-rejection design and its stated overload behavior:
   the deployed mitigation, shipped without a model of what it prevents.
8. Keepalive Economics: a saturated per-read-billed cache tier leaves
   "LRU eviction nothing to rank", plus the observation that unilateral
   keepalive is individually rational, that is, a commons pressure that
   pushes deployments toward the saturated regime.
9. Chinese-language practitioner writing in the Mooncake and DeepSeek
   serving ecosystems describes the C1 loop verbatim as an avalanche
   chain: misses force re-prefill, re-prefill evicts more prefixes, hit
   rate falls further. Retain the source and translation for the
   motivation section.

Not yet done, and cheap: direct issue-tracker search on vLLM, SGLang,
Dynamo, and LMCache for "prefix cache" with hit rate plus slow, degraded,
or evict. Several llm-d blog posts (the KV-cache and predicted-latency
posts) were identified but not read.

## 6. Coverage and residual risk

- Semantic Scholar Graph API returned HTTP 429 throughout, so forward
  citations of the Area A and B seeds were obtained by keyword search
  rather than from the citation graph. This is the weakest part of Pass 1
  and should be redone when the API is available.
- Fully read: CONCUR, TraceLab, Metronome (HTML full text). Abstract plus
  targeted queries only: arXiv:2606.15555 (101 pages), arXiv:2605.04595,
  arXiv:2504.11320. The three unread bodies are the largest residual
  risk; arXiv:2606.15555 in particular should be read end to end before
  submission, since 101 pages can hide a hysteresis section.
- Venue programs scanned: OSDI'26, SIGMETRICS'26, NSDI'26, EuroSys'26,
  ASPLOS'26, FAST'25, FAST'26 (partial, spring list only), ATC'24,
  ATC'25. Not individually scanned: SOSP'25, ATC'26, MLSys'26, SoCC'25,
  Performance, HotStorage'26, HotNets.
- usenix.org returns HTTP 403 to direct fetches; program scans there
  required search-engine indirection and are correspondingly incomplete.
- Search saturation reached: the final arXiv API sweeps on
  ("prefix cache" OR "KV cache") crossed with (fixed point OR equilibrium
  OR phase transition OR critical capacity OR characteristic time), and
  on KV cache crossed with (hysteresis OR bistable OR metastable OR
  multiple equilibria), returned only the papers already classified here.
  No abstract in the prefix-cache hit-rate corpus uses equilibrium, fixed
  point, bistability, hysteresis, collapse, stability analysis, or phase
  boundary.
