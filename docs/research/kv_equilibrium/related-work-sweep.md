# Related-work sweep: instructions

Purpose: establish, before we invest cluster time, whether any prior or
concurrent work already makes our claims, and produce the related-work
section's raw material. This is the project's only existential risk, so the
sweep optimizes for recall on threats first, citation coverage second.

Companion context: ../kv-cache-equilibrium-model.md (the model and results),
README.md in this directory (Phase 1/2 artifacts).

## 1. The claims we need to defend

Judge every paper against these. "Same phenomenon" means overlap on C1+C2
specifically; the rest are secondary contributions.

- C1. Prefix-cache hit rate in LLM serving is an ENDOGENOUS fixed point:
  Che-style characteristic time where the cache write rate depends on the
  hit rate itself, because a miss re-prefills the full context (~65x the
  KV write volume of a hit).
- C2. This feedback creates bistability and hysteresis (a metastable
  failure) with a COMPUTABLE phase boundary in (cache capacity, load), and
  band edges predictable from measurable workload functionals (gap CDF,
  context trajectory, forced-miss fractions).
- C3. Open-loop arrivals (fixed offered rate: benchmarks, ingress-driven
  traffic) and closed-loop arrivals (completion-gated turns) have different
  failure physics; the closed loop self-stabilizes and largely removes the
  bistable region.
- C4. A second cache tier (CPU) removes the bad equilibrium rather than
  merely raising the hit rate; a near-unbounded third tier (storage)
  converts the capacity cliff into a restore-bandwidth cliff.
- C5. Agentic-workload characterization from real traces: subagent
  fan-out, compaction as a renewal process, bimodal (zero + heavy-tail)
  think time, and their consequences for cache dynamics.
- C6. Design rules derived from the model: c_crit(l) sizing, basin-aware
  admission control, recovery by shedding below the band's lower edge.

## 2. Verdict taxonomy

Assign exactly one verdict per relevant paper:

- KILL: models LLM prefix/KV cache hit rate with hit-rate-dependent
  feedback AND derives or demonstrates multiple equilibria / hysteresis
  (C1+C2), with validation. Project must stop and re-scope.
- REFRAME: partial overlap that forces repositioning but not abandonment.
  Examples: an empirical paper showing hit-rate collapse + hysteresis in
  LLM serving without a predictive model (we become the model paper); an
  analytical bistability result for LLM caches without workload
  calibration or system validation (we become the measurement +
  calibrated-prediction paper); a paper claiming C4's tier result.
- CITE-DIFF: must cite and explicitly differentiate in one paragraph.
  Examples: general cache metastability (non-LLM), LLM queueing stability
  treating memory as a constraint rather than feedback state, early
  rejection as an engineering practice (Mooncake).
- BACKGROUND: cite in passing or omit.

For anything at or above CITE-DIFF, record: full citation, one-sentence
summary of THEIR claim, the C1-C6 overlap (list which), verdict, and a
2-3 sentence differentiation draft written from our side.

## 3. Areas, seeds, and what to look for

### A. Metastable failures (systems)

Seeds: Bronson et al., HotOS'21 "Metastable Failures in Distributed
Systems"; Huang et al., OSDI'22 "Metastable Failures in the Wild";
"Characterizing Metastable Faults and Failures" (arXiv:2606.00942);
"Formal Analysis of Metastable Failures in Software Systems"
(arXiv:2510.03551, CTMC-based); the HotOS'25 congestive-collapse paper.

Look for: ANY forward citation of these that mentions LLM, inference,
KV cache, GPU serving, or model serving. This is the highest-yield threat
channel: someone applying the metastability frame to LLM serving. Also
note their look-aside-cache reproduction (OSDI'22) since reviewers will
ask "how is this different" - answer: they demonstrate the class, we give
a predictive, workload-calibrated model and boundary for a new instance
with much stronger amplification (full-context re-prefill).

### B. LLM serving queueing and stability theory

Seeds: "A Queueing-Theoretic Framework for Stability Analysis of LLM
Inference with KV Cache Memory Constraints" (arXiv:2605.04595) and its
reference tree (Li et al. 2025, Jaillet et al. 2025); Mitzenmacher &
Shahout, "Queueing, Predictions, and LLMs" (Stochastic Systems 2025);
Yang/Jiao/Xu WiOpt'24.

Look for: any model where the PREFIX CACHE HIT RATE is a state variable
or appears in the stability condition. Memory-as-constraint is CITE-DIFF;
hit-rate-as-feedback is REFRAME or KILL. Read stability/instability
theorem statements, not just abstracts: a "throughput collapse" theorem
with cache dependence is a threat even if the word metastable never
appears. Alternative vocabularies: "bistable", "hysteresis", "multiple
equilibria", "congestion collapse", "capacity drop".

### C. Prefix/KV cache serving systems

Seeds: Mooncake (FAST'25; note its early-rejection/overload section
carefully - it is the practitioner mitigation our model explains);
SGLang RadixAttention; Preble; MemServe; CacheGen; AttentionStore /
CachedAttention (ATC'24); LMCache tech report; NVIDIA Dynamo docs; vLLM
production-stack docs; llm-d blogs (including "KV-Cache Wins You Can
See" and the predicted-latency post, which already observes hit-rate
instability anecdotally).

Look for: sections on eviction dynamics under load, hit-rate collapse,
admission control justification, warm-up behavior, or "do not benchmark
cold" advice. Systems papers bury the phenomenon in evaluation
subsections and ablations; search PDFs for "hit rate" plots vs load or
time. Anything that SHOWS the collapse without naming it is CITE-DIFF
evidence in our favor (independent observations of the phenomenon).

### D. Classical cache theory

Seeds: Che et al. 2002 (characteristic time); Fricker/Robert/Roberts
2012 (Che approximation validity); TTL-cache line (Fofack, Towsley);
LRU fluid limits; CDN/ICN cache network stability.

Look for: (1) LRU analyses where the request or write process DEPENDS on
the hit rate (feedback). This exists in caching-network contexts
(interest re-forwarding, retry-driven load); if someone proved
bistability for a feedback-coupled LRU cache in general form, we cite it
and claim the LLM instantiation + calibration + system validation. That
is REFRAME-lite, manageable, but we must know about it before a reviewer
does. (2) "Cache thrashing" bistability in CPU-cache or database buffer
literature. Also search industry vocabulary: "cache avalanche", "cache
stampede", "thundering herd", "dogpile effect" - the Redis/CDN world has
named adjacent phenomena and academic work sometimes adopts those names.

### E. Admission control and overload for LLM serving

Seeds: QLM, Andes, SLO-aware serving papers 2024-2026; any "early
rejection", "request dropping", "goodput" paper for LLM inference.

Look for: admission policies keyed to cache or memory state, and any
recovery-after-overload analysis. If someone already built basin-aware
admission (even under another name), C6a needs repositioning.

### F. Workload characterization

Seeds: BurstGPT; Azure LLM inference trace papers; Mooncake trace
analysis (IEEE Cloud 2025 "prefix prefill" paper); any 2025-2026 "agentic
workload" or "coding agent traffic" characterization.

Look for: multi-turn gap distributions, session structure, compaction,
subagent concurrency. Overlap here only affects C5's novelty margin.

### G. Multi-tier KV offload

Seeds: LMCache, IMPRESS, storage-tier KV papers in FAST/ATC/HotStorage
2025-2026, WEKA/VAST vendor whitepapers.

Look for: any analysis (not just measurement) of tier sizing or of
offload bandwidth as the binding constraint (C4's bandwidth-cliff
extension). Vendor whitepapers count as prior observations even if not
peer reviewed.

## 4. Method

Pass 1 - citation chasing (highest recall for threats, ~1 day):
forward-citations ("cited by") of the Area A and B seeds via Semantic
Scholar / Google Scholar, filtered by LLM/serving keywords. Backward
chase the related-work sections of arXiv:2605.04595 and Mooncake.

Pass 2 - venue program scan (~1 day): titles+abstracts of every paper in
OSDI, SOSP, NSDI, ATC, EuroSys, FAST, ASPLOS, MLSys, SIGMETRICS,
Performance, SoCC, HotOS, HotStorage, HotNets from 2024-07 through the
latest 2026 program, plus accepted-paper lists of venues whose
proceedings are not yet out. This catches concurrent work that keyword
search misses because of vocabulary drift.

Pass 3 - keyword search (~1 day), arXiv (cs.DC, cs.PF, cs.OS, cs.LG) +
Scholar. Run at minimum:

    "prefix cache" hit rate model LLM
    KV cache eviction bistable OR hysteresis OR metastable
    LLM serving "cache hit" feedback equilibrium
    LLM inference stability queueing "KV cache"
    "characteristic time" OR "Che approximation" LLM
    cache "hit ratio" collapse serving
    agentic workload trace characterization serving
    KV cache offloading CPU storage tier analysis
    "early rejection" OR "admission control" LLM overload
    warm cold start hysteresis inference serving
    cache avalanche OR stampede LLM

Also search Chinese-language engineering blogs / arXiv authors from the
Mooncake, DeepSeek, Qwen serving ecosystems (the practitioners most
likely to have hit this in production); machine translation is fine.

Pass 4 - ongoing monitoring until submission: weekly arXiv alert on the
Pass 3 queries; re-scan each newly released venue program. Assign an
owner; 30 min/week.

## 5. Deliverables

In this directory:

1. related-work.bib - every CITE-DIFF+ paper, bibtex.
2. threat-matrix.md - one row per paper: citation, their claim (one
   sentence), C1-C6 overlap, verdict, differentiation draft. Sorted by
   threat level.
3. verdict.md - a one-page memo: GO / REFRAME / STOP recommendation with
   the top-5 closest works and why none (or which) of them preempts
   C1+C2. This memo gates the cluster experiment investment.

Timebox: 3-5 focused days for passes 1-3. If a KILL candidate appears,
stop the sweep and escalate immediately with the paper attached; do not
finish the remaining passes first.

## 6. Calibration for the reviewer's eye

While sweeping, collect (do not act on) reviewer ammunition: every prior
observation of LLM cache hit-rate instability, however anecdotal (blog
posts, GitHub issues on vLLM/SGLang prefix cache behavior under load,
incident writeups). These strengthen the motivation section ("widely
observed, never modeled") and preempt the "is this real" review question.
GitHub issue trackers of vLLM, SGLang, Dynamo, and LMCache are in scope:
search "prefix cache" + "hit rate" + slow/degraded/evict.

---

# Refresh 2026-08-25 (web sweep; supplements threat-matrix.md)

Scope: keyword passes over 2025-2026 material in areas A-G plus the
routing/offload system surface (llm-d, SGLang router, Dynamo, Mooncake,
LMCache successors). Method: web search plus abstract-level fetch of
every candidate; full texts not read except where noted. The Semantic
Scholar forward-citation redo (coverage note, section 6 above) remains
pending. All verdicts below are provisional pending threat-matrix.md
integration.

## Scoop-risk assessment (read first)

No KILL candidate. Three items sit closest to the core claims and are
flagged for full-text reads before submission:

1. van Rooyen, arXiv:2606.24861 (v3 2026-08-17). Claims first-order
   collapse, closed-form spinodals, cusp-organized bistability, and
   hysteretic recovery for "AI operating loops" under congestion-
   dependent feedback, with an instrumented real-workload experiment.
   This is the closest published vocabulary match to C2 (fold,
   spinodal, hysteresis, irreversibility threshold). The feedback
   channel is uncertified-output-onto-load (retry-like), NOT a cache
   state variable; there is no prefix cache, no (capacity, load) phase
   boundary, no workload calibration, and no serving-system validation
   of a cache mechanism. Verdict CITE-DIFF, but the differentiation
   paragraph must be explicit: same bifurcation structure, different
   physical feedback (retry amplification vs full-context re-prefill),
   and our boundary is computed from measured workload functionals.
   Watch this author for follow-ups; the paper is being revised
   actively (v1 June, v3 August 2026).
2. Ao et al., arXiv:2606.15555 (already REFRAME, threat-matrix 2.2).
   Current web summaries surface "multiple equilibria" and "periodic
   limit-cycle behavior" language for its admission/eviction dynamics.
   This raises the priority of the standing instruction to read all
   101 pages end to end; if its multiple-equilibria result extends to
   a cache-hit-rate state variable the verdict moves toward the KILL
   boundary. Nothing seen contradicts the standing assessment
   (memory-growth-during-service mechanism, not prefix-cache
   feedback), but the check is now mandatory, not optional.
3. Router-span dependence of collapse probability (headline result A):
   NO overlapping work found. The affinity-vs-load tension is treated
   as a scheduler design problem (DualMap, SkyLB, Ray P2C fallback,
   llm-d token-aware default); no paper quantifies collapse
   probability as a function of router span / fleet size at matched
   per-capacity load. The restore-bound congestion regime (result 4)
   is likewise unclaimed: CacheFlow declares KV restoration "a
   dominant bottleneck" and optimizes it, and practitioner writing
   gives load-vs-recompute crossover points, but no one identifies a
   persistent congested serving regime bounded by restore bandwidth.

Additionally, the motivation-side observation base keeps growing
(items 12-14 below add a named thrashing regime, a year-long
production trace, and a 156-incident taxonomy); the "widely observed,
never modeled" framing is strengthened, and the C1+C2 window remains
open as of this sweep.

## New items (citation, relevance, positioning)

### A. Metastable failures

1. Farahbakhsh, Haeberlen, Lu, Alvisi, van Renesse, Cohen. "Modeling
   Metastability." HotNets '25, College Park, MD, November 2025. DOI
   10.1145/3772356.3772426. [farahbakhsh2025modeling]
   Six-page model sketch explaining how metastability arises and
   predicting the presence or absence of metastable states in a given
   system; precursor of the group's arXiv:2606.00942 causal
   characterization (already in the bib). Relevant as the most compact
   citable statement of the predict-metastability agenda from the
   Cornell/UPenn group.
   Positioning: they predict whether generic request-response
   structures admit metastable states; we exhibit a specific new
   sustaining mechanism (hit-rate-dependent KV write amplification)
   with a calibrated, measured phase boundary.
2. van Rooyen. "First-Order Recoverability Collapse in Self-
   Referential Information Decoders." arXiv:2606.24861,
   cond-mat.stat-mech, 2026 (v3 2026-08-17). [vanrooyen2026collapse]
   See scoop item 1 above for content and threat analysis.
   Positioning: same fold/hysteresis mathematics applied to a
   retry-type feedback; our contribution is the cache-feedback
   instantiation, the measured-constant calibration, and the
   fleet-scale system validation, none of which appear there.
3. Tavori, Bremler-Barr, Levy, Lavi. "RetryGuard: Preventing
   Self-Inflicted and Attack-Driven Retry Storms in Cloud
   Applications." arXiv:2511.23278, cs.NI, 2025 (v2 2026-08-18).
   [tavori2025retryguard]
   Distributed retry-policy coordination across microservices, built
   on an analytical model of retries/throughput/delay/cost; large
   reductions in storm size vs backoff and retry budgets. The current
   state of the art for suppressing the retry sustaining effect.
   Positioning: retry storms are the canonical metastable sustaining
   effect and have dedicated mitigations; the KV-cache sustaining
   effect we model operates without any retries and is untouched by
   retry-side controls.
4. Pandey, Singh. "FailureAtlas: A Taxonomy of Failure Modes in
   Multi-Provider LLM Serving Infrastructure." arXiv:2607.17525,
   cs.LG, 2026. [pandey2026failureatlas]
   Two-axis taxonomy (origin layer x loud/silent) of LLM gateway
   failures; a search-pass summary attributes to the body a
   retry-storm case study (synchronized agent retries saturating a
   provider rate limit). VERIFY the retry-storm section against the
   full text before citing it for that claim; the abstract does not
   mention it.
   Positioning: taxonomy-level evidence that metastable patterns
   occur in LLM serving infrastructure; no dynamics, no model.
5. Cao, Han, Zhang, Ren, Li, Lee. "LUMEN: Coordinated Failure
   Recovery for Distributed LLM Serving." arXiv:2606.17787, cs.DC,
   2026. [cao2026lumen]
   Treats post-failure recovery as a load-aware coordination problem:
   surviving workers absorb redirected traffic while re-running
   interrupted requests, an overload-cascade risk window. Adjacent to
   our recovery discussion (C6c): they coordinate capacity
   restoration after worker loss; we show that even with full
   capacity present, recovery can be blocked by the cache equilibrium
   and requires shedding below the band edge.
6. Ranganathan, Zhang, Wu. "Enhancing reliability in AI inference
   services: An empirical study on real production incidents."
   arXiv:2511.07424, cs.DC, 2025. [ranganathan2025incidents]
   156 high-severity production LLM inference incidents; ~60% engine
   failures, timeouts dominant. Motivation-section ammunition: the
   incident base against which "which of these are metastable"
   becomes an askable question.
   Positioning: incident taxonomy without mechanism; we supply the
   mechanism and boundary for the cache-collapse subclass.

### B. LLM serving queueing and stability

7. Dai, Deng, Li, Peng. "Throughput-Optimal Scheduling Algorithms for
   LLM Inference and AI Agents." arXiv:2504.07347, stat.ML, 2025
   (v3 2026-05-18). [dai2025throughput]
   Fluid-limit framework for multi-class batched processing networks;
   proves work-conserving schedulers are throughput-optimal for LLM
   inference and agent DAG/fork-join workloads, and identifies
   non-maximally-stable production engines. Part of the area-B
   reference tree already named in the sweep seeds; promoted to a bib
   entry because its stability theorems are the natural "classical"
   baseline our feedback mechanism escapes.
   Positioning: their stability region is defined by compute/memory
   service capacity with cache-independent service rates; with
   hit-rate feedback the effective service rate is state-dependent
   and the stability region acquires a bistable band that
   work-conservation arguments do not see.
8. Dong, Cao. "Flow-Controlled Scheduling for LLM Inference with
   Provable Stability Guarantees." arXiv:2604.11001, cs.LG, 2026.
   [dong2026flow]
   Activation-rate control (budgeted admission to the active set)
   with necessary and sufficient stability conditions; prevents
   KV-utilization surges. Closest engineering relative of basin-aware
   admission (C6b).
   Positioning: their controller stabilizes memory occupancy of the
   ACTIVE set; basin-aware admission conditions on the cache
   hit-rate state and its basin boundary, a quantity absent from
   their model - the two are complementary, not competing.

### C. Cache-aware routing and prefix-affinity scheduling

9. Yuan, Zuo, Wang, Chen, Tan, Zhou Yu. "DualMap: Enabling Both Cache
   Affinity and Load Balancing for Distributed LLM Serving."
   arXiv:2602.06502, cs.DC, 2026. [yuan2026dualmap]
   Dual-hash power-of-two-choices request mapping with SLO-triggered
   fallback to load-aware routing, hotspot rebalancing constrained to
   the prefix-bound candidate pair, and hash-ring elasticity; up to
   2.25x effective capacity at matched TTFT SLO on vLLM. The clearest
   2026 statement of the affinity-vs-load design tension our
   ablations measure (headline result C: affinity carries the warm
   margin; load-only collapses).
   Positioning: DualMap engineers the affinity/load trade-off; we
   show the trade-off has a stability dimension - the affinity term
   is what keeps the fleet on the warm branch, and the span of the
   balancer sets the collapse probability, neither of which appears
   in their evaluation.
10. Li, He, Mang, Zhang, Mao, Chen, Zhou, Cheung, Gonzalez, Stoica.
    "Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling
    with KV Cache Time-to-Live." arXiv:2511.02230, cs.OS, 2025
    (v6 2026-05-25). [li2025continuum]
    Pins KV during tool-call gaps with a TTL, overriding
    end-of-turn eviction; >8x JCT improvement on real agent
    workloads. Direct evidence that turn-boundary eviction of live
    session state is the operative failure in agentic serving (our
    session-reservoir mechanism at single-engine scale).
    Positioning: TTL pinning is a per-engine retention heuristic; our
    model gives the fleet-level consequence of losing that retention
    race (the bistable band) and the sizing rule that removes it.
11. Zhang, Kim, Feng, Du, Liu, Zhong, Ching, Jiang, Hu. "Learning
    Agent Execution for KV-Cache Management in Agentic Serving."
    arXiv:2608.14624, cs.AI, 2026. [zhang2026cachescout]
    CacheScout: online-learned agent execution transitions guide
    eviction and prefetch; +10-18 pp hit rate, up to 57% higher peak
    throughput. Evidence that recency-based eviction misprices agent
    contexts (C5-adjacent).
    Positioning: smarter eviction moves the band edges; it does not
    remove the feedback loop, and our boundary computation applies to
    any eviction policy through its induced retention window.
12. Ma, Eitzinger, Koestler. "Leyline: KV Cache Directives for
    Agentic Inference." arXiv:2606.01065, cs.DC, 2026. [ma2026leyline]
    Agent-declared cache editing (splice/remove spans with RoPE
    correction) replacing reactive eviction. Relevant to C5's
    compaction-as-renewal characterization: compaction becomes an
    explicit cache operation rather than a forced full re-prefill.
    Positioning: cache directives change the miss cost of compaction
    events; in our model that rescales the write-amplification
    constant, and the bistability survives wherever the miss/hit
    write ratio stays large.

### F. Workload characterization

13. Yuan, Nayak, Kundu, Talati. "Agentic AI Workload
    Characteristics." arXiv:2605.26297, cs.DC, 2026.
    [yuan2026agentic]
    ReAct-agent characterization across Gemma/Qwen on five
    benchmarks: with context caching, 84.6-99.5% hit ratios and
    decode dominance (91-98.6% of LLM time); body text (per the
    search pass; verify) warns of a thrashing regime once aggregate
    agent context exceeds GPU memory, with recompute-or-restore from
    slower tiers. The named-regime warning is motivation ammunition
    of the first rank.
    Positioning: they observe that the thrashing regime exists; we
    model when it is entered, why it is absorbing, and where its
    boundary lies.
14. Nixon, Durbin, Standhartinger, Gunawi, Yang. "A Year in LLM
    Serving: Workload Evolution, Caching and Load-Balancing."
    arXiv:2608.13573, cs.AI, 2026. [nixon2026yearserving]
    Year-long production trace from the Chutes platform, many models
    and users, trace to be released. Longitudinal grounding for gap
    CDFs and session structure (C5) beyond BurstGPT/Azure/Mooncake
    windows; caching and load-balancing analyses in the body were not
    reviewed at abstract level - read before citing specifics.
    Positioning: trace paper; our workload functionals can be
    re-derived from their release as an external validity check.

### G. KV offload, tiering, restore bandwidth

15. Nian, Fang, Feng, Wu, Lai. "CacheFlow: Efficient LLM Serving with
    3D-Parallel KV Cache Restoration." arXiv:2604.25080, cs.DC, 2026.
    [nian2026cacheflow]
    Declares KV restoration a dominant bottleneck for long-context /
    multi-turn / agentic serving and parallelizes it across tokens,
    layers, and GPUs with a batch-aware scheduler overlapping
    recompute and I/O; evaluated at 80/40/10 Gbps restore paths;
    10-62% TTFT reduction. The strongest independent confirmation
    that restore bandwidth is the binding resource in tiered serving.
    Positioning: CacheFlow raises effective restore bandwidth per
    request; we show restore bandwidth bounds a fleet-level congested
    REGIME (throughput plateau, slowly diverging queue) and that tier
    capacity, not restore speed, sets the regime's persistence -
    faster restoration moves our boundary but does not remove the
    regime.
16. Zheng et al. (20 authors, Alibaba). "Adaptive Multi-Objective
    Tiered Storage Configuration for KV Cache in LLM Service."
    arXiv:2603.08739, cs.AR, 2026. [zheng2026kareto]
    Kareto: tier sizing/placement as multi-objective optimization
    (cost, throughput, latency) with Pareto-front pruning and
    adaptive eviction-aware tuning. First systematic treatment of
    tier SIZING as a first-class decision variable (C4/C6a
    adjacency).
    Positioning: their objective is steady-state cost/performance; we
    show tier sizing has a stability discontinuity (the cold-collapse
    cliff at insufficient capacity, measured tier-250 vs 375/500)
    that a steady-state Pareto analysis cannot expose.
17. Ray, Feamster, Jiang. "An Internet for the KV Cache: Rethinking
    Classical Infrastructure Boundaries in the LLM Inference Age."
    arXiv:2608.01526, cs.NI, 2026. [ray2026internet]
    Position paper: decouple compute from KV storage; a control plane
    with lookup, transfer-deadline, and bandwidth estimation treating
    cached contexts as a content-distribution system. Signals where
    the LMCache group is heading (global cache fabrics).
    Positioning: a global cache fabric enlarges the tier and couples
    more routers to shared state; our span-coupling result says
    exactly this coupling widens the blast radius of the bad
    equilibrium, a stability cost absent from their vision statement.

## Checked and left as BACKGROUND (no bib entries)

- Surveys: "From Tensor Buffer to Distributed Memory Hierarchy"
  (arXiv:2607.02574); "KV Cache Optimization Strategies"
  (arXiv:2603.20397); Awesome-KV-Cache-Optimization (ACL 2026 survey
  repo).
- Routing variants without stability content: SkyLB
  (arXiv:2505.24095), k-LPM (arXiv:2502.04677), decentralized P2P
  prefix routing (arXiv:2606.17059), Ray Serve
  PrefixCacheAffinityRouter docs. DLPM and BanaServe were already
  BACKGROUND; BanaServe has a 2026 journal version (Software:
  Practice and Experience, DOI 10.1002/spe.70054).
- Edge/analytic: "Spatial Prefix Caching for Wireless Edge LLM
  Inference" (arXiv:2608.01126) - abstract checked directly: static
  stochastic-geometry fixed point, no feedback dynamics, no collapse
  claim despite search-snippet wording.
- Offload systems without regime analysis: AdaptCache
  (arXiv:2509.00105), KVServe (arXiv:2605.13734), SAC
  (arXiv:2606.19746), CrossPool (arXiv:2606.24506), MTDS (Springer
  2026), TraCT (CXL), FlexKV (Tencent/NVIDIA).
- Reliability: KevlarFlow (arXiv:2601.22438), GRIEF fuzzer
  (arXiv:2605.11202).
- Ecosystem facts for the motivation section: Mooncake extended
  journal version exists (ACM ToS, DOI 10.1145/3773772; consider
  citing alongside the FAST'25 paper); Mooncake Store is vLLM's
  featured distributed KV engine (2026-05); NVIDIA Dynamo 1.0 with
  LMCache integration; Dynamo KV Router docs describe
  cost-function-tunable affinity/load balance; llm-d changed its
  default to token-aware routing with a calibrated saturation
  release - the deployed mitigations our model explains.

## Residual gaps after this refresh

- Semantic Scholar forward-citation chase of areas A and B: still not
  done (API availability); keyword recall only.
- Full-text reads owed: arXiv:2606.15555 (mandatory, see scoop item
  2), arXiv:2606.24861, FailureAtlas body (retry-storm claim),
  arXiv:2608.13573 caching/load-balancing chapters, arXiv:2605.26297
  thrashing passage.
- Venue programs not covered by this refresh: SOSP'26 accepted list,
  MLSys'26, HotStorage'26, HotNets'26 CFP-stage material.
