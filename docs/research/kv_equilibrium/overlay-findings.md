# Model overlay findings: fluid/DES vs GB200 measured arcs

Date: 2026-08-10. Inputs: out/arcs/*.csv (extract_arcs.py, 18 runs),
fluid_model.py Phase-1 machinery. New code: overlay_fixedpoint.py,
overlay_b1_dynamics.py. Outputs: out/gb200_band.csv,
out/overlay_b1_dynamics.png, out/overlay_b1_summary.csv.

## Calibration (all constants measured on this fleet)

    POOL       6486 blocks x 256 tok per TP4 replica (13.28M fleet at 8)
    P_TPT      17k tok/s/replica (saturated uncached plateaus, 131-138k fleet)
    tpot(N)    9.6 ms + 3.8e-6 * N^2 (fit: 10 ms @ ~10 running,
               21.5 ms @ ~56, 84 ms @ ~147; cap 0.3 s)
    gap CDF    corpus think mix truncated at the 10.5 s idle-gap cap
    KV/token   127 KB (fp8, 62 layers, 8 KV heads, 128 dim) - validated
               against the HBM pool byte size; CPU tier 160 GB/pod
               = 1.26M tok/pod
    E[req/session] 174; subagent rate ratio 1.057 (corpus)

## Result 1: the static fixed point matches the warm branch only

With GB200 constants and capped gap CDFs, the Phase-1 fixed point
reproduces every warm cell within 1-3 h-points (measured 93.6-95.1% vs
the 96.3% structural ceiling; the deficit is the salt-marker cost plus
routing imperfection) and ranks/approximates T correctly across six
cells (T_meas 278-1300 s vs T_model 366-1518 s). It finds NO cold
equilibrium at the measured achieved rates and no bistable band up to
6 rps: with a constant tpot, running residency never pins the pool.
The measured absorbing state is therefore NOT a static open-loop
bistability at achieved request rates - it requires the two dynamic
ingredients below. This reframes the Phase-1 story for this fleet: the
band is a property of the demand process and the interference coupling,
not of the request-rate plane alone.

## Result 2: session-reservoir dynamics reproduce the full trichotomy

overlay_b1_dynamics.py adds exactly two ingredients to the fluid
machinery:

1. tpot(N_run) interference (measured fit above): slow decode holds
   requests in the running set, which pins the pool, which collapses
   the retention window below the gap cap.
2. Elastic session demand: in-system sessions defer during collapse
   (completion-coupled turn release), accumulate as a reservoir, and
   drain as catch-up; surge populations are cancelled at surge end,
   matching the instrument.

One parameterization, four protocol simulations (surge window shaded,
cancellation at surge end), vs measured:

    arm                     in-surge sat.   post-surge outcome (model vs meas)
    0.022 sps               yes (wait ~600) RELAPSE: base catch-up re-pins,
                                            queue regrows (35 vs 79 at 175 min,
                                            same shape); h floor 0.3 vs 3-12%
    0.017 sps               yes             recovery (h 96.3 vs 92.0%)
    0.012 sps               yes             recovery (h 96.3 vs 94.5%)
    0.011 + CPU tier (4x)   yes             recovery, no relapse (96.3 vs 93.5%)

The waiting-queue trajectories match quantitatively in all four arms,
including the 0.022 arm's post-cancellation re-growth - the signature
of the reservoir-driven relapse - and the in-surge saturation of the
recovering controls (model ~570-600 vs measured 675-745 peak).

## Refinement round (same day): per-population class terms

Two changes after the first pass, both calibration-principled:

1. First-request split: arriving (salted) sessions enqueue a forced
   full-miss first request (U_FIRST = system prompt + first input,
   ~51.6k tokens) as an explicit queue class per population, instead of
   the corpus-mean 1.6% first-turn fraction. This moves the model's
   in-surge h collapse from ~15 min late to surge onset, matching the
   measured erosion.
2. E_REQ_SESSION corrected from the corpus mean (174) to the measured
   realized value in the 3 h windows (118 = 28366 records/240 sessions,
   b1a): finite windows truncate traces, and the corpus mean inflates
   every arm's demand ~40%. With the corpus value the model relapses at
   0.017; with the measured value the boundary sits between 0.017 and
   0.022, matching the experiments. Report realized session length with
   any lambda_s-denominated claim.

After refinement, end states: 0.022 relapse (model h 0.3% / wait
regrowth vs measured 8.2% / 79); 0.017 recovery (88.3 vs 92.0%) with a
marginal late queue re-growth - the model places 0.017 just inside its
boundary, slightly conservative vs the clean measured recovery; 0.012
recovery (89.5 vs 94.5%); tier recovery (96.3 vs 93.5%).

## Model predictions for the next capacity window (falsifiable)

out/model_relapse_search.csv; 4-replica geometry, 0.125 sps x 2700 s
surge, refined model:

1. The missing same-geometry control - 4-replica NO-OFFLOAD at 0.011
   sps - RELAPSES. If confirmed, B2a's recovery is attributed to the
   tier with no scaling assumption left.
2. No-offload relapse edge: lambda_s in (0.008, 0.010) sps, which
   scales to (0.016, 0.020) on 8 replicas - consistent with the
   measured (0.017, 0.022) bracket.
3. The tier shows NO relapse up to 0.032 sps (>3.2x the no-offload
   edge); overload instead surfaces as warm queueing (h stays ~96%,
   queue grows). The tier converts the failure mode from cache collapse
   to plain capacity queueing. Caveat: the model tier is ideal (no
   overflow/restore-bandwidth limit), so 3.2x is optimistic; the real
   tier thrashed late-surge in B2a.

## Known model limitations (documented, not fitted away)

- h transitions are square: the capped gap CDF is a step at 10.5 s, so
  coverage crossing the cap flips the fleet at once; measured h erodes
  over ~10 min because per-session effective waits are heterogeneous.
- The b1a2 draw's 15-min warm interlude before relapse is not
  reproduced (the model relapses without an interlude); the b1a2-rep
  draw matched the model's no-interlude shape - the interlude is
  within draw variance of reservoir size.
- The CPU tier is an ideal coverage window (no capacity overflow, no
  restore-bandwidth limit), so the model misses the measured late-surge
  tier thrash (measured ext_hit fell to 1-2% before recovery). The
  validated claim is the recovery side: restore-instead-of-reprefill
  drains the reservoir inside headroom, deleting the relapse.

## Paper implications

- The overlay figure (out/overlay_b1_dynamics.png) is the
  model-validation exhibit: measured trichotomy + tier deletion,
  reproduced by a fluid model whose every constant is independently
  measured (no free parameters fitted to the arcs beyond the tpot
  interference curve, which comes from separate closed-loop cells).
- The fixed-point negative result (Result 1) is itself a contribution:
  absorbing collapse on this class of fleet requires interference
  coupling plus demand elasticity structure; static capacity planning
  (the request-rate band alone) would MISS this failure mode at these
  request rates.
- Next modeling steps: per-population class terms (surge cold
  composition), finite tier capacity/bandwidth (turns the tier verdict
  into a sizing rule), DES replication of the four protocols with
  des.py's replay driver for variance bars.

## DES replication

Code: des_b1.py (subclasses des.py, which stays untouched). Outputs:
out/des_b1_overlay.png, out/des_b1_summary.csv. 5 seeds per arm, 180
min simulated, 16-25k requests and < 0.5 s wall per run. Protocols,
constants, and cancellation semantics exactly as in
handoff-des-replication.md: session-Poisson base from t=0, surge
population in [62, 107) min cancelled at surge end (queued requests
removed, in-flight requests aborted with their KV freed), tpot(R)
interference at decode start, think samples capped at 10.5 s,
shedding disabled.

One adaptation beyond the handoff task list was required: admission
semantics. des.py admits a request (allocating its KV) only when the
node's prefill engine is idle, which under a deep backlog caps the
running set at the prefill turnover rate; post-cancellation R
equilibrates near 90, tpot(R) stays ~40 ms, and every b1a2 seed
recovers. The tpot(R) curve is calibrated against the vLLM
num_requests_running gauge, which counts the whole admitted batch
including requests still waiting for prefill chunks - and those
requests hold KV blocks. des_b1 therefore admits watermark-style:
waiting requests join the node's running batch (full KV need
allocated) while the batch fits under KV_HEADROOM; the prefill engine
itself stays serialized. The two semantics coincide in the
empty-queue closed-loop cells where des.py was validated; they
diverge exactly in the backlog-drain regime that decides the relapse.

Per-arm verdict (end state = 150-175 min window; per-seed rows in
out/des_b1_summary.csv):

    arm    DES outcome     end h DES [min-max]  fluid   meas    end wait DES [min-max]  fluid  meas
    b1a2   RELAPSE 5/5     10.5% [0.0-22.8]     0.3%    8.2%    67 [40-89] growing      20     79
    b1c    recovery 4/5    78.3% [6.0-96.9]     88.3%   92.0%   6 [0-28]                4      1
    b1b    recovery 5/5    96.6% [96.2-96.9]    89.5%   94.5%   0                       0      0
    b2a    recovery 5/5    96.8% [96.1-97.2]    96.3%   93.5%   0                       3      0

In-surge peak wait 620-787 on the 8-replica arms (measured 675-790),
316-493 on b2a (measured 399); time-to-collapse 75-85 min in every
run. The DES end states bracket the measured values in all four arms
and sit closer to them than the fluid model does on the relapse arm
(h floor and wait level both).

The three deliverables the DES was commissioned for:

1. Variance bars: the overlay shades min-max across seeds per arm.
2. Smooth h transitions: confirmed. Relapsing seeds erode over 20-40
   min (example seed 2: 0.94, 0.87, 0.82, 0.76, 0.65, 0.42, 0.18, 0)
   where the fluid transition is square; in-surge erosion spans 2-3
   windows, matching the measured 10-15 min.
3. Boundary check: DES relapses 5/5 at 0.022 and 1/5 at 0.017, i.e.
   it places 0.017 on the boundary and the edge inside (0.017,
   0.022) - agreeing with the measurements and slightly less
   conservative than the fluid model, which puts 0.017 just inside
   its relapse region.

Both watch items from the handoff resolve:

- b1c boundary variance: present. Seed 2 relapses (end h 6.0%, wait
  28 and growing); the other four recover to 95-97%. The measured
  b1c recovery-with-grazing is one draw from a bimodal outcome
  distribution.
- b1a2 interlude: present in every seed. All five relapsing runs show
  a post-cancellation warm window (first window after surge end has
  h > 0.8, at +8 min) lasting 1-5 windows (5-25 min) before erosion
  resumes. The measured pair - 15-min interlude in the first draw,
  single partial-recovery window in the replicate - sits inside this
  spread. The interlude is draw variance, closing the fluid-model gap
  documented above.

Sanity gates: warm h 95.1-97.2% (target 92-96); collapsed h 0.0%;
warm realized request rates across seeds 1.33-2.35 (b1a2), 1.22-2.26
(b1c), 0.87-2.30 (b1b) - each spread straddles its measured draw
(targets 1.6-2.4, 2.0-2.3, 1.1-1.4, themselves n=1-2 draws);
realized requests/session 90-154 in the recovering arms (target
100-130) and 53-83 in relapsing runs, where the absorbed fleet
starves session progress - a consequence of the relapse, not of the
window logic. The first-request salting assertion (new Seq has no
cache entry) held across all 20 runs.

DES-specific limitations:

- Full KV need is reserved at batch admission (des.py convention);
  vLLM allocates blocks progressively during chunked prefill. This
  overstates running-set residency during backlog drains, which may
  make the DES boundary marginally conservative.
- tpot(R) is frozen at decode start; in-flight decodes are not
  re-timed as R moves.
- No preemption/recompute path (the measured collapses show nonzero
  preemption counts); preemption wastes work the DES does not model.
- Aborted surge requests leave their written prefill tokens on the
  virtual clock (they age other entries by at most one pool
  traversal).
- Relapsed end-state h floors at exactly 0 in most seeds vs the
  measured 3-12% residual; the real fleet retains a trickle of
  intra-window reuse the DES evicts.

## Restore-bound congestion model (2026-08-11)

Inputs: the three tier runs (cpuofl-a1-tier022, cpuofl-a1rep,
cpuofl-lh-tier), the long-horizon pair (ppc-lh-noofl), the bimodality
draws (ppc-bimod2/3), and the refreshed out/arcs/*.csv with offload
counters. New code: tpot_fit.py, overlay_restore.py; extended:
extract_arcs.py, overlay_b1_dynamics.py, des_b1.py. Outputs:
out/tpot_fit.{png,csv}, out/overlay_restore.png,
out/overlay_restore_summary.csv, out/restore_boundary.csv.

### Calibration provenance (all from measured counters)

Offload counter semantics (extract_arcs.py): the
vllm:kv_offload_total_{bytes,time} counters carry a transfer_type
label - CPU_to_GPU is the restore/onboard direction, GPU_to_CPU the
offload direction; both are present. total_time is SECONDS
(bytes/time gives 151.5 GB/s active bandwidth, a plausible C2C rate;
ms would imply 151 TB/s). external_prefix_cache_queries/hits are
TOKEN counts: windowed CPU_to_GPU bytes / 127 KB equals the windowed
ext-hit token rate to <1% in every tier run, and queries track
prompt_tokens.

    B_r      23k tok/s/replica EFFECTIVE restore capacity. The
             per-pod restore rate plateaus at 21.4-24.0k tok/s across
             all four tier runs at BOTH fleet scales while demand
             exceeds it (early-surge ext queries ~2x hits). The raw
             DMA link runs at 151.5 GB/s = 1.19e6 tok/s at ~2% duty:
             per-transfer overhead binds, not the link. des.py's
             RESTORE_TPS = 1e6 placeholder was ~52x high.
    r_tok    150-192k tok/s fleet restore rate in the 8x congested
             state = 0.81-1.04 of N*B_r - the channel is pinned.
    tier ingest  measured offload rate 50-78k tok/s tracks uncached
             prefill + generation, NOT restores: the tier ingests new
             writes only, and restored blocks stay tier-resident.

### tpot re-fit: interference is per-pod (scale-question discriminator)

tpot_fit.py pools per-window (R_fleet, tpot_p50) points from every
arc (552 windows; 35 at 4x) and fits both forms:

    A: tpot = 12.2 ms + 3.98e-6 * R_fleet^2        (fleet form)
    B: tpot = 10.8 ms + 2.56e-4 * (R_fleet/N)^2    (per-pod form)

On the discriminating high-R 4x windows (b2a in-surge saturation,
R 67-78, measured tpot p50 81 ms mean) form A predicts 33 ms (2.4x
under) and form B 96 ms (19% over); 4x RMSE 27.4 vs 18.6 ms. At 8
replicas the two forms coincide and form B reduces to the original
calibration (fleet-equivalent 10.8 ms + 4.0e-6 R^2 vs 9.6 + 3.8e-6).
Verdict: adopt form B. The fleet-R fit was a calibration artifact;
the earlier B2a fluid/DES runs under-priced 4x interference ~3x at
saturation. Consequence for the scale question: with per-pod
interference every per-pod-homogeneous model is exactly
scale-invariant at equal per-capacity load, so interference CANNOT
explain the 4x-vs-8x outcome difference (the fleet-R form would
have; it is falsified).

### Model extensions

Fluid (overlay_b1_dynamics.py): restores are a contended fleet
channel of capacity N*B_r; the backlog gates the prefill-completion
frontier while saturated, enters wq as a third max() term (the
channels serve different requests concurrently, so a new arrival's
wait is the bottleneck backlog, not the sum), and achieved restore
traffic advances the HBM write clock via w_hbm. The CPU window
churns at w_new (measured tier ingest) with hit-refresh. Prefill
bookkeeping uses the exact batch average Bpre/Npre so the request
and token backlogs stay consistent when the restore channel is the
binding stage.

DES (des_b1.py): cache state evaluated at batch admission (vLLM
ref-counts prefix blocks at allocation); CPU-tier hits pass through
a per-node FCFS restore channel at B_r before prefill; onboarding is
asynchronous (the engine passes over un-restored entries); two-clock
LRU - the HBM clock advances with prefill + restores + generation,
the tier clock with new writes only, both touch stamps refreshed at
decode end. A single-clock variant (tier churned by restores) was
tried first and rejected against measurement: it drives the tier to
exhaustion and a cold collapse by min 270 that the 300-min hardware
run refutes, and it contradicts the measured tier-ingest rate.

### Per-arm verdicts (5 seeds, 300 min, out/overlay_restore.png)

    arm              measured                    DES
    8x-0.022 noofl   cold absorbing: h 1.6-3%,   cold 5/5: end h 0%,
                     wait -> 289 at 1.1/min      wait 240-375
    8x-0.022 tier    restore-bound congestion:   congested 5/5: restores
                     h 70-84%, restores          pinned 153-158k, run
                     149-192k pinned, KV 93-94%, ~105, wait 161-318 at
                     run 92-126, wait 6 -> 164   270-295 min, no cold
                     (~0.8/min), no collapse     collapse
    4x-0.011 tier    clean recovery (180 min,    at the 180-min horizon:
                     wait ~0)                    4/5 mild congestion
                                                 (wait 9-47), 1/5
                                                 recovered
    8x-0.017 noofl   recovery (3/3 draws)        recovered 5/5
    8x-0.012 noofl   recovery                    recovered 5/5

DES quantitative gaps in the congested state, stated not fitted:
h 0.95 vs measured 0.70-0.85 and restore share of hits 1.0 vs
0.66-0.79 (the model tier never misses: its two-clock window is
~160-200 s vs an effective ~100 s implied by the measured miss
share - candidate causes: kv-offloading-size RAM units, non-LRU
eviction, per-pod imbalance); completion rate 1.6 vs 2.5-4.3 req/s;
wait levels ~2x hot. The regime discriminators - restore channel
pinned at capacity, queue diverging slowly and linearly, h holding
high, no cold collapse - are reproduced 5/5.

The 0.017 boundary variance moved: 0/5 relapses under the corrected
calibration (previously 1/5); the measured tally is 3/3 recoveries,
so no tension, but the DES no longer predicts a relapse tail there.

### Fluid limitation: branch selection at cancellation

The fluid reproduces the in-surge restore-bound state (channel
pinned, ext share ~1, wq_rst dominating) but flushes its ~7M-token
restore backlog at channel capacity within ~2 min of cancellation;
its post-cancel completion rate lands at 2.9 req/s, marginally above
the 2.6 req/s base demand, and it exits to the warm branch at both
scales. The DES lands at 1.6 req/s - restore-serialized, with
heterogeneous gaps and per-session turn ordering keeping the channel
saturated - and diverges, matching measurement. Both models sit near
the same critical balance (measured throughput 2.5-4.3 req/s
brackets both); the deterministic proportional-share fluid queue
picks the wrong side of it at 8x. This is structural (square
coverage step, population-mixed queue) and is documented rather than
tuned away: every constant in both layers is measured, and no fluid
constant flips this branch without violating a measurement. The DES
is the validated layer for the third regime; the fluid remains
validated for the no-offload arms, the B2a window, and the in-surge
mechanism.

### Scale question: resolved to calibration artifact + draw variance

1. The interference half is a calibration artifact: the fleet-R form
   is falsified by the 4x saturated windows (2.4x under-prediction);
   corrected models are per-capacity scale-invariant.
2. The remainder is consistent with draw variance near the boundary:
   the DES at 4x-0.011 yields mild congestion (wait 9-47 at the B2a
   horizon, 3-7x smaller queues than 8x-0.022) with recovery in 1/5
   draws; the measured clean recovery (n=1, 180 min) sits in that
   favorable tail, and a 180-min window has weak power to
   distinguish mild congestion from recovery at 4x scale.
3. Falsifiable next window: a 300-min B2a repeat ends near wait
   75-142 if the DES is right, near 0 if the 4x point is genuinely
   stable (restore_boundary.csv, lam4x rows).

### Boundary predictions for the next hardware window

restore_boundary.csv, 5 seeds per point, 300 min, classification at
270-295 min (cold: h < 0.15; recovered: wait < 15 and h > 0.9; else
congested):

    8x tier, lambda_s sweep (c_cpu 1.26M tok/replica):
        0.014  recovered 5/5
        0.017  recovered 5/5
        0.020  congested 4/5, recovered 1/5
        0.022  congested 5/5
        0.026  congested 5/5 (wait 262-465)
        0.030  congested 5/5 (wait 439-568), NO cold collapse

    recovery -> congestion boundary: lambda_s in (0.017, 0.020),
    point estimate ~0.018-0.019. The tier buys only ~10% of rate
    headroom over the no-offload relapse edge at the measured B_r -
    the earlier ideal-tier prediction of >3.2x is dead.

    congestion -> cold boundary: not found up to 0.030 sps (1.36x
    the centerpiece rate): h stays >= 0.93, restores stay pinned,
    the queue growth steepens (wait at 150-175 min: 87 -> 217) but
    the tier keeps converting collapse into linear queue growth.

    A4 / c_cpu at 0.022 (half and double the current 1.26M
    tok/replica): 0.63M congested 5/5 (end h 0.90, restores 148k);
    2.52M congested 5/5 (end h 0.95, restores 158k). The congestion
    onset does NOT move with tier size: the binding resource is the
    restore channel N*B_r, not tier capacity. Tier sizing modulates
    only the residual full-miss fraction. Implication: the A4
    hardware point measures effective tier capacity (via the miss
    share), not stability; the stability knob is restore bandwidth
    (per-transfer overhead) or admission below the boundary.

    Suggested ladder: 0.017 / 0.019 / 0.021 at 8x tier (bracket the
    onset), plus the 300-min B2a repeat for the scale tail.

## Coordination-layer refit (2026-08-14): the N-dependent term

Inputs: the per-pod spread analysis (per-pod-spread-findings.md), the
08-12/08-13 N-series arcs (cpuofl4x-falsifier, ppc-edge020-noofl,
shard-a-020, ppc-n16-inv040, ppc-n16-lh040), the deployed EPP config
(guides/agentic-serving-tp/epp-configs/precise-prefix-cache.yaml) and
plugin sources in this repository. New code: RouterSessionSim in
des_b1.py; overlay_nseries.py. Outputs: out/overlay_nseries.png,
out/overlay_nseries_summary.csv.

### What the spread data rules in and out

Load imbalance is refuted (share dispersion N-invariant); the 16x
signatures are scatter/duplication: 4-5 point fleet-wide h deficit at
re-warm, 0.15-0.20 pool excess KV at matched per-capacity state, and
a staggered per-pod pinning cascade (details in
per-pod-spread-findings.md).

### The idealized DES router carries no N-effect

The des.py router (lexicographic: most cached prefix, then load)
produces identical relapse rates at per-capacity-matched points
(3/5 at both 8x-0.020 and 16x-0.040), contradicting the measured
contrast (8x recovers 3/3; 16x relapses 2/2). Per-node tpot
evaluation (each pod's interference from its own running set rather
than the fleet mean) also does not separate the fleets. The N-effect
is not reproducible from scheduling-algorithm idealizations plus
per-pod physics.

### RouterSessionSim: the deployed coordination layer, plus its
### saturation

des_b1.RouterSessionSim replaces the idealized router with the
deployed algorithm; every scheduling constant is read from config or
plugin code, none fitted:

    prefix-cache-affinity-filter   sticky threshold 0.80; TTFT load
                                   gate 18000 ms; TTFT estimated as
                                   in-flight tokens / 28888 tok/s
                                   (deployed peakPrefillThroughput)
    token-load-scorer              least in-flight-token candidate
    inflight-load-producer         entries stop counting 300 s after
                                   dispatch without completion
                                   (plugin_state.go staleness reap),
                                   so deep engine queues undercount
                                   and the gate rarely breaks under
                                   backlog

plus ONE constant not read from config - the coordinator saturation
threshold C_W. The EPP is a single process per fleet; its KV-event
indexing, remote tokenization, and scoring work scale with
fleet-total churn while its capacity does not. While the fleet write
rate exceeds C_W tok/s the router's cache view is modeled frozen:
entries written since saturation began are invisible for routing, so
completion-coupled turns land by load on cold pods and duplicate
their prefixes (the measured scatter signature). Entries evicted
since saturation began are not modeled as false-sticky; that error
direction preserves miss locality, so the omission errs toward
scatter. C_W is bracketed by measurement, not fitted to outcomes:
the 16x catch-up fleet write rate ~195k tok/s relapsed (saturated)
while the 8x catch-up at 77-135k recovered, and two shard routers at
half the per-router volume recovered. C_W = 160e3 is the bracket
midpoint; every verdict below is unchanged across (140e3, 190e3)
(16x frozen 55-105 min depending on C_W, 8x at most 4 min).

### Verdicts (5 seeds, 300 min, out/overlay_nseries.png)

    arm              measured                    DES (RouterSessionSim)
    4x-0.011 tier    clean recovery (210 min,    1/5 recovered, 4/5 mild-to-
                     wait 0, restore share -> 0) moderate congestion at 300
                                                 min (wait 61-160); never
                                                 saturated. At the 180-min
                                                 horizon: recovered 5/5
                                                 (wait 10-62).
    8x-0.020 noofl   perturbation recovery 3/3;  1/5 clean hold; 4/5 relapse
                     organic collapse 1/2 draws  by 270-295 min; never
                     at min ~240                 saturated. Organic-collapse
                                                 phenomenology present,
                                                 rate overstated.
    16x-0.040 noofl  relapse 2/2, full absorbing cold 5/5 (end h <= 0.04,
                     tail, wait ~400 growing     wait 439-701), coordinator
                                                 saturated 209-216 min; wait
                                                 trajectory brackets the
                                                 measured arc.

The b1 validation arms under the refitted model (180 min,
out/des_b1_overlay.png): 0.022 relapse 4/5 (previously 5/5; measured
3/3 - one escaped seed is the cost of the janitor-weakened load
gate), 0.017 recovery 5/5, 0.012 recovery 5/5, B2a recovery 5/5.
The 4x falsification documented above (DES mild congestion vs
measured clean recovery at the 180-min horizon) is RESOLVED by the
deployed-router refit: the janitor-undercounted TTFT gate plus
token-load scoring keeps the 4x fleet's backlog drain warm. The
300-min 4x point remains the standing falsifiable prediction (DES
wait 52-160 vs ~0 if the point is genuinely stable at that horizon).

Structural consequence, matching the shard result: a sharded router
halves per-coordinator churn, so two 8x routers over 16 pods sit
below C_W where one 16x router saturates. The model predicts shard
draws behave as independent 8x-0.020 systems.

### Refit limitations (documented, not tuned)

- The freeze is binary (rate above/below C_W); the real index
  presumably degrades gradually. Measured 16x shows a partial re-warm
  to h 0.88 at min 115 before eroding; the frozen DES caps the
  re-warm near 0.2 and relapses without the deep interlude.
- Which coordinator resource saturates (KV-event indexing, remote
  tokenization, scoring throughput) is not identifiable from
  collected data; C_W abstracts them. The routing ablation plus an
  EPP-metrics scrape next window discriminate.
- 8x-0.020 remains over-fragile (4/5 relapse at 300 min vs measured
  1/2 organic); the full-KV-at-admission reservation bias documented
  for the DES persists.

## Tier-capacity refit (2026-08-14): TIER_EFF

Input: the 2026-08-13 same-day pair at 8x-0.022 (cpuofl-a4half-lh,
kv-offloading-size 250, cold collapse; cpuofl-a4full-lh, size 500,
healed) falsifying the capacity-indifference conclusion of the ccpu
sweep above. New constant: TIER_EFF = 0.5 in des_b1.py (effective
tier capacity = half the nominal RAM-derived value; size 500 =>
0.63M tok/pod effective, size 250 => 0.315M).

Calibration: the DES capacity sweep at 8x-0.022 (300 min, 5 seeds)
places the cold-persistence boundary near 0.3M tok/pod effective -
cold 4/5 at 0.315M, congested 5/5 at 0.63M and above. Nominal
capacities (0.63M for size 250) reproduce only congestion, never the
measured cold collapse; TIER_EFF = 0.5 aligns the pair. The same
factor is implied independently by the congested-state miss share
documented above (effective tier window ~100 s vs ~160-200 s modeled
at full capacity) - the two discrepancies collapse into one
constant. Candidate physical causes remain undiscriminated:
kv-offloading-size RAM units / allocator overhead, non-LRU eviction,
per-pod imbalance.

Verdicts (out/overlay_tiercap.png): tier-250 cold 4/5 with the DES
mean tracking the measured decay-through-congestion arc and the wait
trajectory nearly overlaying the measured one; tier-500 congested
5/5, never cold - direction and persistence boundary match the
measured pair. The heal branch stays pessimistic: measured tier-500
outcomes are {3 congested / 1 healed} and the healed draw rides the
upper edge of the DES band; the DES produces no heal at 0.022 and
still under-heals at 0.020 (measured full heal, DES congested 5/5 at
the 300-min horizon). This is the same critical-balance branch
selection documented for the fluid, now the tier model's primary
open failure. The 375/650 hardware bracket tests the implied
persistence threshold (with TIER_EFF = 0.5: 375 => 0.47M effective,
inside the cold-boundary region; 650 => 0.82M, safely congested).

The restore-boundary table above (lambda sweep, A4/c_cpu sweep) was
computed at nominal capacities with the idealized router; its
congestion-onset placement (0.017, 0.020) matched the measured
0.020-bimodal point and is retained, but its capacity-indifference
row is superseded by this refit.

## Mechanism revision (2026-08-17, after the 32-host window)

Inputs: the 19-run window ledger (lab-notebook-2026-08-15.md), the
EPP-side coordinator measurements, and two DES sweeps run with the
freeze DISABLED: the fleet-size ladder (12 seeds x 6 arms, 300 min)
and a fine tier-capacity sweep (6 seeds x 5 capacities).

### The C_W freeze term is retired

Two independent grounds. (1) Its physical reading is contradicted:
EPP metrics collected on every window run show the KV-event pool
queue empty, index admissions tracking demand with no plateau (3.3k
adm/s at 16x = exactly 2x the shard routers), CPU 1.9 of 4
uncontended cores, index lookups < 1 ms, and scheduler e2e ~0.1 ms
through three reproducing 16x relapses. Remote tokenization runs
230-270 ms/request in every run, healthy and collapsing alike.
(2) It is unnecessary: at the 300-min classification horizon the
no-freeze ladder reproduces the fleet-size shift emergently -

    arm          DES p(collapse)   measured
    8x-0.017     2/12              0/4
    8x-0.020     11/12             5/8
    8x-0.022     12/12             3/3
    16x-0.034    5/12              0/1     (0.017 per-8x-eq)
    16x-0.037    12/12             1/2     (0.0185 per-8x-eq)
    16x-0.040    11/12             4/4     (0.020 per-8x-eq)

At matched per-capacity points the 16x curve sits LEFT of the 8x
curve (0.42 vs 0.17 at the 0.017-equivalent) with no coordinator
term: the shared router's load balancing couples every pod's
post-cancellation drain-vs-catch-up race, suppressing the favorable
fluctuations that independent shard routers sometimes draw. The
freeze changed no verdict at this horizon (16x-0.040: 11/12 without
vs 5/5 with); its earlier justification came from a 180-min-horizon
comparison that misses late collapses. Both DES curves sit left of
the measured ones - the documented full-KV-reservation bias - so
the model's quantitative claim is the SHIFT and the outcome-class
structure, not absolute placement.

### TIER_EFF re-calibrated to the cold side only: 0.5 -> 0.67

The fine capacity sweep places the DES cold/congested transition
across (0.42, 0.63)M tok/pod effective (cold 5/6 at 0.315 and 0.42,
4/6 at 0.4725, 3/6 at 0.55, 0/6 at 0.63). The measured cold-side
ordering (250 cold; 375 and 500 never cold in 8 draws) then pins
TIER_EFF ~ 2/3 from both sides: eff(250) = 0.42M must sit at or
below the transition and eff(375) = 0.63M at or above it. The
previous 0.5 estimate is excluded by the two 375 heals.

### The heal branch is a missing mechanism, not a calibration error

Zero heals in 30 sweep runs at any capacity at 8x-0.022, against 4
measured heals in 8 draws at sizes 375-500, plus the measured
full heal at 0.020 and the 300-min 4x-0.011 stability (wait 1.3
measured vs 52-160 predicted). The failure is one-sided: the DES
reproduces cold collapse, restore-bound congestion, and the
recovery arms, but cannot exit the congested state through
drain-back. Candidate mechanisms for a dedicated pass, in order of
suspicion: full-KV-at-admission reservation overstating residency
during backlog drains (the same bias behind the leftward absolute
shift); restore-channel serialization holding the channel pinned
after real fleets de-pin; tier-window churn of stale surge content
(smaller tiers evict dead prefixes faster - consistent with 375
healing 2/2 while 500 healed 2/6, though that contrast is not
significant on its own). Constraint on any fix: it must not move
the reproduced cold/congested boundary or the no-offload band.

### Model verdict tables after this revision

The b1 validation arms are unchanged in class (0.022 relapse band
bracketing the measured floor; 0.017 and 0.012 recover; B2a
recovers at its 180-min horizon with a small wait residue). The
N-series and tier figures (out/overlay_nseries.png,
out/overlay_tiercap.png) are regenerated from the revised model
with the window's measured draws overlaid; DES bands at bimodal
points span outcome classes rather than tracking single arcs.

### Heal-branch candidate screens (2026-08-25): four negatives, a
### measured channel falsifier, and a gauge-semantics correction

Screen protocol shared by all four candidates: matrix A1-A7 (A1
8x-0.022 tier-500, A2 8x-0.022 tier-250, A3 8x-0.022 no-offload,
A4 8x-0.017 no-offload, A5 4x-0.011 tier-500, A6 16x-0.040
no-offload, A7 8x-0.020 no-offload), 6 seeds, 300 min, outcome over
windows 270 <= t_min <= 295 (cold h < 0.15; recovered wait < 15 AND
h > 0.9; else congested). A draw counts as a HEAL only if recovered
AND end_kv <= 0.5 AND mean ext_share over t 270-295 <= 0.2 AND end
running <= 2x warm running. Guard constraint on every candidate:
preserve the cold/congested boundary and the no-offload band.

MEASURED FALSIFIER of the fixed-capacity restore channel. The
serial FCFS channel reads B_R = 23k tok/s/node as a hard per-node
ceiling. The measured heal arcs exceed it: 5-min fleet restore
rates of 235,284 tok/s (cpuofl-a4-375-lh, t=70) and 278,161 tok/s
(cpuofl-500-bimod6, t=70) = 1.28-1.51x N*B_R, followed by a
post-cancel restore phase at 0.14-0.56 N*B_R with wait 0.3-7 while
kv drains from 0.83-0.86 at cancellation to 0.26-0.31. The 23k
plateau (result 4's pinned
band, measured on congested draws at 0.81-1.04 N*B_R) is therefore
a congested-STATE throughput outcome, not a channel capacity.
Result 4 and result 9 in research-status.md carry this reading.

CANDIDATE 1, reservation timing (heal_variant_progressive.py):
INFORMATIVE NEGATIVE, DO-NOT-MERGE. Progressive KV allocation
(resident prefix at admission, uncached tokens at prefill
completion, output lump at decode start; deployed CHUNK_TOK 8192
and MAX_NUM_SEQS 256, both measured flags) removes the
full-KV-at-admission overstatement. Screen: A1 still 0/6 healed (6
congested); the no-offload guard arm A4 (8x-0.017, measured
recovery 4/4, unmodified DES 4/6 recovered) turns 4/6 congested,
and A2 produces a recovered draw where the guard requires >= 3/6
cold and 0 healed (A6 additionally turns 1/6 recovered where the
unmodified model is 6/6 cold). The A4 state is a NON-PHYSICAL
INTERFERENCE-LOCKED ATTRACTOR: with only next-chunk headroom
required, the variant admits a large backlog batch and the
tpot(R/N) interference term over that batch locks a congested state
that vLLM's step-budget scheduler cannot enter (c_cpu = 0, so no
restore channel is involved). Conservation verified by an
independent 60 s ledger (adversarial_check_progressive.py, A2 seeds
3 and 6, stored-row reproduction MATCH). Retained diagnostic value:
the screen's baseline window CSVs show every failing A1/A5 draw
DRAIN from wait 319-745 at t=105 to a trough of 0-31 at t=115 (9 of
11 failing draws at or below 9; the other two trough at 15 and 31)
and then RE-ENTER congestion as the restore channel ramps back to a
pinned plateau - per-draw mean 0.66-0.87 N*B_R over t 150-295 with
ext_share -> 1.0 (exemplar draws A1 s1 mean 0.81, A5 s1 windows to
0.96; the one late re-entrant, A1 s3, ramps only in the final hour)
- the heal failure is a re-entry trap, not a drain failure.
Outputs: out/heal_screen_progressive.csv, out/heal_progressive_runs/.

CANDIDATE 2, stale-content tier churn (heal_variant_stale.py):
DEFINITIVE EXCLUSION within the two-clock abstraction. The credit
variant subtracts dead-surge write tokens from the tier age of live
entries evaluated after cancellation (exact per-node ledgers, no
new constant); it is the complete-instantaneous-reclamation
bracket, while strict LRU equals the unmodified window, so the two
bracket every intermediate reclamation policy. Screen: variant
outcome tallies match baseline on every arm (A1 6/6 congested both
sides, zero heals on any tier arm; the only shift is one A2 draw
congested -> cold). The instrument run explains the null: the dead
share of the tier window is 0.59-0.93 through the surge and early
drain but the live write flux churns it out of the two-clock window
by t=120 (~13 min after cancellation); the rescuable fraction of
live tier misses peaks at 0.31 (t=110) and is 0.0 for the remaining
180 min, so the credit has nothing to act on during the congested
phase. A null on the credited bracket excludes the mechanism
entirely within this abstraction; staleness effects, if real, live
outside the two-clock window model. Outputs:
out/heal_stale_instrument.csv, out/heal_screen_stale.csv,
out/heal_stale_runs/.

GAUGE-SEMANTICS FINDING (applied in candidate 3). The tpot(R/N)
interference fit is calibrated against vllm:num_requests_running,
and the inspected scheduler (vllm main@8fe9317f2e, 2026-08-25)
EXCLUDES sequences waiting for external KV onboarding from that
gauge: on async external KV load the request enters
WAITING_FOR_REMOTE_KVS in a skipped-waiting queue with blocks
already allocated (scheduler.py:1108-1111), make_stats reports
num_running_reqs = len(self.running) with skipped-waiting as a
separate field (scheduler.py:2659-2662), the gauge is set from
num_running_reqs only while skipped-waiting is added to
vllm:num_requests_waiting (loggers.py:494, 1108-1116), and the
request joins `running` only after the transfer completes
(scheduler.py:2822-2833). Verified at that revision only; no
release tags were available in the local clone. DES consequence:
restore-in-flight entries must sit in a pending-onboard set
excluded from the R of the tpot term and from the sampled run
gauge, while holding their full KV reservation (vLLM allocates
blocks before the wait state); this DES models no max_num_seqs, so
no cap interaction exists. The correction is a semantics match to
the calibration gauge and belongs in any successor variant.

CANDIDATE 3, concurrent restore onboarding (heal_variant_serial.py,
runner heal_screen_serial_runner.py): NEGATIVE for the heal branch;
NOT MERGED - des_b1.py keeps the serial channel, with its ceiling
reading documented as falsified above. Mechanism: each tier hit
starts its transfer at admission, rst_done = max(now, link_free) +
cached/LINK_RATE + T_OVERHEAD; link_free serializes link occupancy
only (a zero-burst rate limit at LINK_RATE on restored tokens),
overhead phases overlap, so throughput scales with concurrency up
to LINK_RATE. Constants: LINK_RATE = 1.19e6 tok/s/node, MEASURED
(151.5 GB/s DMA at 127 KB/token, calibration provenance above);
T_OVERHEAD = 4.232 s/transfer, DERIVED FROM MEASURED via B_R =
S/(S/LINK_RATE + T_OVERHEAD) at the 23k plateau (~2% duty), i.e.
T_OVERHEAD = S*(1/23000 - 1/1.19e6) = S*4.264e-5, with the size
scale S = S_MEAN_RESTORE = 99,247 tok taken from the model workload
in the plateau's regime (pooled mean restore size, congested phase
t 120-295 of the six A1 baseline draws; scratch_smean.py; per-seed
means 96-110k, n=70,756) because the measured counters carry token
rates but no transfer counts. Sanity gates passed: c_cpu=0
bit-identity to the unmodified model; warm h 0.9525 on 8x-0.017
tier-500. Screen (out/heal_screen_serial.csv, deterministic): A1
0/6 healed, 6 congested; A5 6 congested, 0/6 end wait < 15; guards
A2/A3/A6/A7 pass; A4 shows 2/6 cold on a c_cpu=0 arm bit-identical
to the unmodified model - a seed-draw property, not a mechanism
effect. The congested-state pin OVERSHOOTS the measured 0.81-1.04
N*B_R band (tails A1 0.93-1.37, A5 1.10-1.47, A2 congested
0.71-1.19; 1/15 in band; peaks to 1.91), documented not tuned: the
state self-limits through KV-gated admission - a restore is
admitted only when a completion frees its reservation, so fleet
restore rate = completions/s x ~105.6k tok/admission with ~1.3
transfers in flight per node - and the overshoot traces to (a)
full-context restores on every hit (model ext_share 1.0, h ~0.94 vs
measured h 0.70-0.85, ext-hit 62-79%) and (b) the R-exclusion
raising the completion rate itself (A1 s1: 2.39/s vs 1.73/s
baseline).

RESIDUAL FAILURE MODE after candidates 1-3. The re-entry trap
survives channel replacement: every completion re-admits a
full-context restore, the restore population regenerates at exactly
the completion rate, and the congested state persists at elevated
throughput. With reservation timing, channel serialization, and
two-clock stale churn excluded, the gap sits on the restored-VOLUME
side: the model restores ~100k tokens per tier hit unconditionally
where the measured congested state runs ext-hit 62-79% at h
0.70-0.85, i.e. smaller effective restored volume per completion
(partial-context restores, or tier-content staleness of a kind the
two-clock window cannot express). Candidate 4 tests the remaining
LRU-residency abstraction before that term and retains the
pending-onboard gauge split.

CANDIDATE 4, occupancy-gated HBM eviction
(heal_variant_headroom.py, runner heal_screen_headroom_runner.py):
NEGATIVE for the heal branch; the trap survives, relocated into
restore-backlog reservations. Hypothesis: the parent LRU test
(write_clock - t_touch < C_HBM - kv_used) ages every resident entry
on every write regardless of free headroom, while the vLLM
allocator evicts cached blocks only under allocation pressure - so
DES restored content expires again with a drained pool, forcing
re-restore forever. Pre-implementation quantification
(investigate_headroom_aging.py, out/headroom_aging_a1.csv, A1
baseline seeds 1-3): the fraction of total HBM clock aging booked
at pool occupancy < 0.7 is 0.020-0.084 overall and 0.003-0.066
post-cancel (occupancy-weighted mean 0.84-0.88; 100% of aging sits
below the 0.92 watermark by construction), because the parent trap
itself pins kv at ~0.88 - headroom-absorbable aging exists mainly
in the warm phase (100% below 0.7, but ~2% of volume) and the
post-cancel drain dip. Mechanism (no new constants; corrects the
LRU abstraction only): a per-node evict_clock counts evicted
volume; at admission the allocation evicts only the overflow
max(0, kv_used + (write_clock - evict_clock) - C_HBM) oldest-first,
and an entry stamped at write-clock position t_hbm is HBM-resident
iff evict_clock < t_hbm. Serial B_R restore channel byte-for-byte
from the parent; pending-onboard gauge split applied. Sanity:
c_cpu=0 warm windows match the parent (h 0.9586 both); warm h
0.9525 on 8x-0.017 tier-500. Screen (out/heal_screen_headroom.csv,
out/heal_headroom_runs/; all arms simulated, no bit-identity
shortcut): gates A2/A3/A6/A7 PASS, A1/A4/A5 FAIL. A1 1/6 recovered
(s3: wait 3.25, ext_share 0.035, restores decayed to 0.02-0.05
N*B_R, kv settling 0.79 - the measured restore-decay arc shape, but
end_kv > 0.5 and end_run 82.9 > 2x warm, so not a heal), 5/6
re-enter: they drain (A1 s1 wait 2.8, ext 0.01 at t 120-150), the
recovered throughput refills the pool, and the trap re-forms. A5
5/6 congested, 1/6 wait < 15. A4 (c_cpu=0) 2/6 cold, identical in
count to the unmodified parent at the 300-min horizon (serial
screen A4 rows, bit-identical to parent: cold s2/s6) with two seeds
swapping outcome class (s2 cold -> recovered, s5 recovered ->
cold); A3/A6/A7 outcome tallies match the parent exactly. The
congested pin HOLDS: A1 tails 0.97-1.00 N*B_R, A5 tails 1.00,
peaks 1.00-1.01, all inside the measured 0.81-1.04 band and the
0.017 guard is no worse than the parent - the overshoot failure
mode of candidate 3 is absent. A2's two congested-classified draws
run in-band mid-phase (0.61-0.94 N*B_R, t 150-250) then decay to
0.14-0.41 at the tail as the 250-tier content ages out
(cold-transition, h falling 0.54/0.30). Residual failure mode,
quantified at the A1 s1 tail: 84 pending-onboard entries hold
0.693 of the fleet pool (full-KV reservations queued behind the
serial B_R channel) while 22 entries execute (kv 0.882) - the
backlog's held reservations keep the pool at the watermark, keep
allocation-pressure eviction active, and regenerate tier hits at
exactly the channel rate. With residency corrected, the trap is
carried by reservation-holding restore backlog, i.e. the
interaction of full-KV reservation at admission with the serial
channel, consistent with the restored-VOLUME reading above: both
candidate 3 (channel widened, reservations released fast) and
candidate 4 (channel kept, residency corrected) fail on the same
~100k-token unconditional full-context restore per tier hit.
