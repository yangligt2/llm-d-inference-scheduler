# KV cache equilibrium: Phase 1 fluid model

Companion code for ../kv-cache-equilibrium-model.md (Phase 1 of the plan).
Research-only; not part of the router build.

## Run

    cd docs/research
    python3 -m venv .venv && .venv/bin/pip install --index-url https://pypi.org/simple/ numpy matplotlib
    .venv/bin/python kv_equilibrium/fluid_model.py        # customer case + routing-accuracy sweep
    .venv/bin/python kv_equilibrium/phase_diagram.py      # full sweeps, ~5 min, writes out/*.png

Partial reruns: `phase_diagram.py fixedpoint` or `phase_diagram.py openloop`.

## Model

- Two workload classes (main conversation, subagent) derived from the
  trace-calibrated spec via a deterministic walk over the compaction sawtooth.
  Functionals: forced-miss fractions (first turn, post-compaction), mean
  normal-turn prefix, per-turn input/output deltas, gap CDFs.
- Fixed point on (T_hbm, T_tot, TTFT): Che retention windows with the
  miss-write feedback, CPU tier as a second window, CPU-to-HBM restore traffic
  added to HBM churn, running-request KV subtracted from the pool.
- Arrivals: closed loop (lambda = l / E[cycle]) or open loop (fixed rps).
- Queueing: per-node M/G/1 for prefill; M/M/m (Sakasegawa) for KV residency
  slots, m = fleet pool / mean per-request KV.
- Bistability detected by seeding the solver from h=1 and from h=0.

## Key Phase 1 results (N=16, B200 constants, CC-trace workload)

1. Structural hit ceiling 96.3% token-weighted. Forced misses (first turns,
   compaction resets, subagent seeds) cost only ~4%; the agentic gap mass
   (~78% of turns within seconds) hits under almost any retention window.
2. Customer point (c=0.95M, ~10 rps): with CPU tier and perfect routing,
   monostable good: h_tok 96%, TTFT ~4.5 s, binding constraint is KV
   residency of RUNNING requests (rho_kv ~0.98), not cache retention.
   HBM-only: degraded (h 89%, TTFT ~12 s).
3. Routing accuracy, not capacity, reproduces the escalation: scaling all hit
   probabilities by a gives h_tok 48% at a=0.5, with closed-loop throughput
   collapse. Between a=1.0 and a=0.9, prefill utilization jumps 0.31 -> 0.91:
   a 10% misroute rate sits on the saturation cliff at this scale.
4. Closed-loop workloads self-stabilize: the fixed-point map bends downward
   (higher hit -> faster cycle -> more churn), so bistability is nearly absent
   in the (c, l) plane. The open-loop plane (fixed offered rps: benchmarks,
   rate-limited producers) shows a wide diagonal bistable band in HBM-only,
   and the customer point (10 rps, 0.95M) lands exactly on it. Adding the
   5.7M-token CPU tier erases the band at that operating point.
5. c_crit scales ~linearly with sessions (closed loop, region "good"):
   l=100 -> 0.29M, l=200 -> 0.55M, l=400 -> 1.15M (0.96M with CPU tier),
   l=800 -> 3.18M (2.01M); l>=1600 has no good c at N=16 (prefill/decode
   bound, not cache bound).

## Outputs

- out/phase_diagram.png       closed-loop (c, l) regions, HBM-only vs +CPU
- out/phase_diagram_open.png  open-loop (c, offered rps) regions; the
                              bistable band lives here
- out/fixed_point.png         one-step map Phi(u); crossings = equilibria
- out/hysteresis.png          warm-started continuation over offered rps:
                              HBM-only collapses at ~10.8 rps on the way up
                              and recovers only below ~8.0 rps on the way
                              down; the CPU tier shows no loop at all
- out/disruption.png          fluid trajectory (dynamics.py) at 9 rps with a
                              30 s admission timeout: a 2-minute 2x burst
                              knocks HBM-only into the bad state, which
                              persists for 11 minutes at the pre-burst load
                              (with relaxation-oscillation recovery attempts);
                              a deliberate shed to 1 rps for 3 minutes walks
                              it back to the good state. The CPU tier absorbs
                              the same burst and self-recovers in ~2.5 min.

dynamics.py adds a time-domain layer on the same functionals: age-coverage
state per tier (grows at most 1 s/s - content can only age in real time -
and shrinks on the pool-overwrite timescale; this asymmetry is why collapse
is fast and recovery slow), a request backlog against the tighter of the
prefill and KV-slot bottlenecks, and hit probability F(coverage - queue wait),
since a prefix must survive think time plus queueing.

## Positioning vs prior work

Cache-driven metastable failure is documented in general distributed systems
(Bronson et al. HotOS'21; Huang et al. OSDI'22 reproduce a look-aside-cache
hit-rate collapse and catalog capacity-degradation amplification). Queueing
stability analyses for LLM serving exist (e.g. arXiv:2605.04595 KV-memory
stability; Mitzenmacher & Shahout 2025 survey) but treat the cache/memory as
a constraint, not as state with its own feedback. The contribution here is
the combination: prefix-cache hit rate as an endogenous fixed point (Che
characteristic time + the ~65x miss-write amplification specific to
full-context re-prefill), a computable phase boundary in (capacity, load),
the open-loop vs closed-loop stabilization distinction, and the CPU-tier
result (the second tier removes the bad equilibrium rather than merely
raising the hit rate).

## Phase 2: discrete event simulation (des.py, des_validate.py)

Independent rebuild of the same physics from first principles: discrete
requests, per-node FIFO prefill engines, KV residency admission, exact LRU
via the virtual write clock, affinity routing - none of the fluid closures.
Replay mode fires a pregenerated trace on schedule (true open loop; the
trace starts 12000 s before t=0 so the population age mix is stationary,
and pre-t=0 prefixes are stacked into per-node LRU order so t=0 is warm).
Closed mode keeps l conversations in flight. Run:

    .venv/bin/python kv_equilibrium/des_validate.py   # ~20 s, all experiments

Validation results (N=16, c=0.95M, seed 0):

- Customer point (closed, l=400): DES vs fluid - HBM-only h 91.4% vs 88.6%;
  +CPU h 95.8% vs 96.0%, TTFT 4.3 s vs 4.5 s. Near-exact for +CPU.
- Band (replay, full cache flush at t=2500 s): HBM-only recovers from the
  flush at <= 8 rps, stays degraded at 9 rps (70% vs 93% warm, 12% shed),
  and loses even the warm branch at >= 10 rps. DES band ~ [8.5, 9.5] vs
  fluid [8.0, 10.8]: lower edge matches; the upper edge sits lower because
  the trace's burstiness (subagent group fan-outs, lumpy conversations) and
  head-of-line blocking weaken the warm branch - a real effect the
  mean-field fluid model smooths away. Near the edges the DES wanders
  between branches (noise-induced transitions near a saddle-node).
- +CPU shows no bistability anywhere: post-flush equals warm at every load,
  degrading only via slot saturation at >= 10 rps, right where the fluid
  rho_kv constraint predicted. The CPU tier deletes the bad equilibrium in
  both models.
- out/des_band.png (DES points over fluid hysteresis curves) and
  out/des_trajectory.png (flush/shed trajectory, DES vs fluid overlay).

Modeling lesson learned the hard way: an early DES version kept the
compaction truncation as a permanent cap on cache validity, which silently
turned a quarter of main-thread turns into ~60% misses and produced a fake
collapse at 7 rps. The correct semantics: compaction clamps the entries
that exist at that moment; turns served afterwards rebuild full validity.
The same subtlety applies to any router-side prefix indexer handling
compaction events.

## Caveats (remaining, for Phase 3 / real-cluster calibration)

- Mean-path walk ignores within-class variance of context length; heavy-tail
  conversations are underweighted in prefix means.
- M/G/1 per node assumes random splitting; affinity routing is bursty per
  node, real queues are worse at equal utilization.
- Sakasegawa treats KV slots as identical servers; vLLM admission and
  preemption differ near saturation.
- Chunked-prefill interference between prefill and decode is not modeled
  (p_tpt and d_tpt independent); TPOT held fixed at 12 ms.
- CPU restore bandwidth assumed free; restore traffic only churns HBM.
- Subagent think time assumed agentic; zero cross-conversation prefix sharing.
