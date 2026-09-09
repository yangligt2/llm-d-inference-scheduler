# Verdict: GO, with mandatory repositioning

Gating memo for the cluster experiment investment. Evidence and full
citations in threat-matrix.md and related-work.bib.

## Recommendation

**GO.** No paper found preempts C1+C2. Proceed with Phase 3 cluster
experiments.

Two conditions attach:

1. The framing of the contribution must change before any writing starts
   (section "Required repositioning" below). Concurrent work has taken
   two positions the current draft implicitly claims.
2. arXiv:2606.15555 must be read end to end before submission. It is 101
   pages and was assessed from the abstract plus targeted queries. It is
   the only outstanding item that could still move the verdict.

## What was searched

Passes 1 to 3 of related-work-sweep.md across areas A to G: forward and
backward citation chasing on the metastable-failure and LLM-queueing
seeds, program scans of OSDI'26, SIGMETRICS'26, NSDI'26, EuroSys'26,
ASPLOS'26, FAST'25, FAST'26, ATC'24 and ATC'25, the eleven mandated
keyword queries, and arXiv API sweeps to July 2026 including the Chinese
serving ecosystems. Coverage gaps are listed in threat-matrix.md
section 6; the material one is that the Semantic Scholar citation graph
was unavailable (HTTP 429) so forward citations were keyword-driven.

Search saturation was reached: the terminal sweeps crossing prefix and KV
cache against the full instability vocabulary returned only papers
already classified.

## Top five closest works and why none preempts C1+C2

**1. CONCUR, arXiv:2601.22705 (Jan 2026). REFRAME.** The closest work,
and the only one that publishes the phenomenon. It measures prefix-cache
hit rate collapsing to 35% at batch 40 while KV usage stays pinned at
80-100%, names it middle-phase thrashing, and controls it with AIMD over
agent admission. It does not preempt C1 or C2 because hit rate is a
telemetry signal, not a state variable: the paper contains no model, no
fixed point, no stability derivation, no bistability, no hysteresis, and
no load-reduction experiment, so it cannot say where the collapse
threshold lies or whether the state is reversible. Its controller
constants are fixed across all models and workloads, and the sensitivity
study shows U_low is brittle, which is what a hard-coded proxy for a
moving basin edge looks like.

**2. Service-Induced Congestion, arXiv:2606.15555 (Jun 2026). REFRAME.**
The strongest analytical adjacency. It proves that memory-constrained LLM
serving has an unstable eviction-free fixed point and converges almost
everywhere to a worst-case limit cycle costing up to 50% throughput. It
does not preempt C1 or C2 because its state is the aggregate KV footprint
of running requests, growing one token per decode step; prefix caching,
reuse, and hit rate never appear. Its multiplicity is fixed-point versus
limit-cycle driven by arithmetic synchronization of decode lengths, not
saddle-node bistability, and it claims no hysteresis or path dependence.

**3. TraceLab, arXiv:2606.30560 (Jun 2026). REFRAME, C5 only.** A public
4,265-session coding-agent trace with 95.7% overall prefix hit rate and
an idle-gap miss analysis. No threat to C1+C2: no hit-rate time series,
no load or concurrency dependence, no eviction-under-pressure analysis.
It does erode C5, and its retention-window sweep is the exogenous-window
special case of our Che window, which must be acknowledged explicitly.

**4. Metronome, arXiv:2607.02640 (Jul 2026). CITE-DIFF.** The only work
that applies metastability vocabulary to LLM KV memory, so it is a
vocabulary collision that a reviewer will find. It does not preempt C1 or
C2: the full text contains no occurrence of hysteresis, bistable,
multiple equilibria, basin, or cache hit rate, and its model is a linear
open-loop fill rho(t) = rho_0 + N r t with a single absorbing state and
no feedback term. Its metastability claim rests on run-to-run outcome
variance in a timing race, and the stall it describes never recovers.

**5. Rosensweig, Menasche, Kurose, INFOCOM'13. CITE-DIFF.** The classical
precedent for multiple cache steady states: cache networks can be
non-ergodic, so the steady state depends on initial conditions. It does
not preempt C2 because the multiplicity is combinatorial placement across
a topology at fixed demand, with no load parameter, no capacity-load
boundary, no amplification mechanism, and no hysteresis. Cite it
pre-emptively rather than be caught with it.

## What remains uniquely ours

- **C1 intact.** No work models LLM prefix-cache hit rate as an
  endogenous fixed point in which the cache write rate depends on the hit
  rate through full-context re-prefill. The 65x miss-write amplification
  is unclaimed. Confirmed by exhaustion: no abstract in the prefix-cache
  hit-rate corpus uses equilibrium, fixed point, bistability, hysteresis,
  stability analysis, or phase boundary.
- **C2 intact.** No computable (capacity, load) phase boundary and no
  hysteresis loop for LLM prefix caching exists in the literature. The
  three instability results found (arXiv:2606.15555 limit cycles,
  arXiv:2607.02640 absorbing saturation, arXiv:2605.04595 stability
  threshold) each concern a different state variable and none produces
  two stable branches at one load.
- **C3 intact.** The open-loop versus closed-loop arrival distinction was
  not found anywhere in the LLM serving literature. arXiv:2606.15555
  works exclusively in a saturated-input regime, which is the open-loop
  extreme, and does not compare.
- **C4 intact.** No analysis of tier sizing or of restore bandwidth as
  the binding constraint. Every multi-tier paper found (IMPRESS, LMCache,
  CachedAttention, CacheGen, the FAST'26 two-tier storage papers) treats
  tiering as a mechanism and measures latency, not as a structural change
  to the set of equilibria.
- **C5 narrowed.** TraceLab and the ATC'25 Aliyun characterization now
  own the general agentic and production characterization. Retained:
  heavy subagent fan-out (44.5% of conversations, about 58% of requests,
  versus TraceLab's 1.2 tool calls per step), compaction as a recurring
  renewal process, and the mapping of these functionals into cache
  dynamics.
- **C6 partially contested.** CONCUR ships cache-signal-keyed admission
  control first. Retained: that the correct threshold is a basin edge
  computable from c_crit(l), and recovery by shedding below the band's
  lower edge, which no work found attempts.

## Required repositioning

Two claims in the current draft and README are now unavailable and must
be rewritten before submission.

1. **Not "we observe hit-rate collapse."** CONCUR published it in
   January 2026. The observation is now shared and should be cited as
   independent confirmation, which strengthens rather than weakens the
   motivation. Position as: the phenomenon is reported and mitigated by
   heuristic; it has never been explained or bounded.

2. **Not "first dynamical analysis of LLM serving instability."**
   arXiv:2606.15555 and arXiv:2504.11320 hold that ground for
   memory-occupancy dynamics. Position as: instability analyses of LLM
   serving exist for the memory footprint of running requests; the reuse
   cache is a distinct feedback path with a different loop gain and a
   different bifurcation type, and it is the one that produces two stable
   operating points at a single offered load.

The defensible one-sentence claim is: prefix-cache hit rate in LLM
serving is an endogenous fixed point whose miss-write amplification
creates a bistable region with a computable boundary, which we predict
from workload functionals, confirm in discrete-event simulation, and use
to derive sizing, admission, and recovery rules.

Also update the "Positioning vs prior work" paragraph in README.md: it
currently cites only Bronson, Huang, arXiv:2605.04595, and Mitzenmacher
and Shahout, and predates the three REFRAME papers.

## Pass 4 monitoring

Weekly, 30 minutes, until submission. The arXiv Atom API
(export.arxiv.org/api/query) is the working mechanism; the arXiv listing
pages return 404 and usenix.org returns 403 to direct fetches. Watch in
priority order: the Ao and Simchi-Levi line for a cache-reuse extension,
the CONCUR authors for a follow-up that adds a model, and SOSP'26 and
NSDI'27 accepted-paper lists as they appear. Re-run the Semantic Scholar
forward-citation queries on the Area A and B seeds once the rate limit
clears.
