# Router-span dependence

<!-- Claims: C15-C24. Sources: results 6, 10, 13-15 (research-status.md),
     per-pod-spread-findings.md. Target length 1.75 pages. -->

Collapse susceptibility depends on the number of replicas a single
router instance spans, at fixed per-replica load and fixed per-pod
physics. This section states the probabilistic result, then works
through an elimination structure: config independence, scale-invariant
per-pod physics, refutation of load imbalance and coordinator
saturation, an affinity-necessity ablation, shard containment, and the
per-pod signatures that survive elimination.

## Probabilistic left-shift of the collapse curve

At per-capacity-matched operating points the collapse-probability
curve shifts left approximately 5-10% in rate and steepens with router
span [R6]. The 16x single-router ladder: 0.034 sps recovers 1/1 (n=1,
the one measured draw), 0.037 is bimodal 1/2, 0.040 relapses 4/4; in
per-8x-equivalent rate these points sit at 0.017 / 0.0185 / 0.020. The
8x ladder at the same per-capacity points: 0.017 recovers 4/4, 0.020
collapses 5 of 8, 0.022 relapses 3/3 (n=7 draws at 16x, 15 at 8x)
[R6]. The shift magnitude is bracketed by these tallies; no fitted or
smoothed probability curve is claimed, and the 16x-0.034 anchor is a
single draw.

The 16x collapses also differ in kind, not only in rate. Every 16x
collapse is early-onset - hit-rate erosion is underway by minute
~125-155 - and fleet-total, across 5 collapses spanning days and
configurations; the organic-late class observed at 8x-0.020 (cold by
~minute 240) does not appear at 16x [R6, R10].

**Figure (to be produced): 16x-vs-8x ladder tally.** Outcome tallies
per operating point, both ladders on a shared per-8x-equivalent rate
axis; source data are the notebook ledgers consolidated in the
research-status data-sufficiency table. Caption draft: "Collapse
tallies at per-capacity-matched operating points. Bars show
recover/collapse counts per draw ledger; the 16x band edge sits left
of the 8x edge by approximately 5-10% in per-8x-equivalent rate. The
0.034 point is a single draw."

## Config independence

The 16x-0.040 relapse does not depend on the prefix-cache
implementation detail of the router. It reproduces under
precise-prefix-cache (3 draws) and under the approx baseline, which
runs no KV-event pipeline and no token-producer, in one draw under
that config (n=1) [R10]. The relapse is therefore a property of
span-coupled routing over the fleet, not of any single scoring
pipeline.

## Per-pod physics is scale-invariant

The span dependence cannot be located in the pods. The per-pod decode
interference fit tpot = 10.8 ms + 2.56e-4 (R/N)^2 holds in the per-pod
form; the alternative fleet-R form is falsified by the saturated 4x
windows (out/tpot_fit.png, out/tpot_fit.csv) [R6]. Restore bandwidth
is likewise per-replica (B_r; Section on the tier regime). With
per-pod service physics invariant in N, the N-dependence must live in
the coordination layer [R6].

Figure: out/tpot_fit.png. Caption draft: "Per-pod decode interference.
Measured tpot vs per-pod running load R/N across 4x/8x/16x windows;
the per-pod quadratic form fits all fleet sizes, while a fleet-total-R
form fails on the saturated 4x windows."

## Candidate mechanism: load imbalance - refuted

Query-share dispersion across pods is N-invariant in every phase:
warm-phase query-share CV is 0.46-0.48 at 4x, 0.34-0.51 at 8x,
0.46-0.56 at 16x; recovery-phase CV is 0.12-0.21 at 4x, 0.21 for the
recovering 8x shard draw, 0.14-0.15 at 16x (15 runs;
out/perpod/spread_summary.csv) [R10]. The recovering shard draw shows
higher share dispersion than the relapsing 16x runs at matched
relative times, the opposite ordering of what an imbalance mechanism
requires; the max-share ratio grows with N only as the expected
extreme-value bias of a maximum over N draws
(per-pod-spread-findings.md, finding 1).

## Candidate mechanism: coordinator saturation - refuted for this EPP

EPP-side resources were scraped on all 19 runs of the measurement
window and are unsaturated throughout, including through three
reproducing 16x relapses [R13]: KV-event index admissions track demand
with no plateau (16x peak 3.3k/s, exactly 2x the per-shard
1.0-1.6k/s); event-pool queue depth ~0 in every window; EPP CPU 1.9 of
4 uncontended cores (shards ~1.1); index lookups 0.4-0.9 ms; scheduler
end-to-end ~0.1 ms; remote tokenization 230-273 ms per request,
uniform across healthy and collapsing runs. This retires the
coordinator-saturation reading for this EPP implementation at these
spans; it does not by itself establish any alternative mechanism, and
no claim is made for other coordinator implementations.

## Affinity necessity ablation

A load-only EPP configuration (queue and kv-utilization scorers only,
no affinity signal) at 8x-0.020 measures what routing affinity carries
[R14]. In the one measured draw (n=1): warm h 0.53 versus 0.94 under
precise-prefix-cache, with TTFT p50 2-4 s and wait 3-6 pre-surge - a
degraded but serving warm state - followed by unconditional absorbing
collapse after the surge, cold by t=150 with no recovery phase, end
wait 215, TTFT p50 177 s. The necessity reading rests on the size of
the warm-margin loss and the absence of any recovery phase in this
draw, not on an outcome frequency. Affinity thus carries both the warm
hit-rate margin and the recovery path at boundary points.

## Shard containment

Two independent 8x routers over the same pod type at matched
per-capacity load bound the blast radius [R10]. Across 6 shard draws
in the window, every shard collapse (4, including the load-only
ablation) stayed inside its own 8-pod bulkhead; in both concurrent
mixed pairs (a2/b2, a3/b4) the sibling shard served untouched while
its partner collapsed. Every 16x single-router collapse (5, across
days and configs) was fleet-total. Containment is therefore a measured
property of the router span boundary, in the same fleet, at the same
per-capacity load.

## Per-pod signatures: scatter and duplication

Three measured signatures separate 16x from 8x at matched fleet state
(per-pod-spread-findings.md, findings 2-4; out/perpod/*.csv) [R10]:

1. Hit-rate dispersion at equal fleet h. Warm fleet h is 0.94 at
   every N, but warm per-pod h standard deviation roughly doubles from
   ~0.032 at 4x/8x to 0.044-0.067 at 16x; corr(share_i, h_i) is
   0.57-0.86 everywhere - busier pods run warmer - so the dispersion
   is a coordination signature, not a load-balance defect.
2. Excess KV occupancy and miss-write flux at matched re-warm state.
   At the matched t=115 window the 16x fleet (ppc-n16-lh040: h 0.88,
   kv 0.80, uncached 44.1k tok/s per-8x-equivalent) carries the same
   per-capacity session state in 0.15-0.20 more of its pool and
   sustains ~1.7x the per-capacity miss-write flux relative to the 8x
   arcs (shard-a-020: 0.92 / 0.61 / 24.2k; ppc-edge020-noofl: 0.93 / 0.62 /
   24.5k), with a 4-5 point h deficit spread across the whole fleet
   (per-pod p25-max 0.87-0.92 vs 0.91-0.95) and measured retention
   time 58 s versus ~190 s.
3. Staggered pinning cascade. The 16x relapse re-pins pod by pod -
   3/16 at t=115, 11/16 at t=120, 14/16 at t=125, 16/16 at t=130 -
   with per-pod h spreading to 0.10-0.67 before fleet-wide erosion,
   whereas the 8x organic collapse pins near-synchronously, 2/8 to 8/8
   within one 5-min window.

These observables are directly measured; the reading of them as
prefix scatter/duplication is a mechanism inference, supported jointly
with the ablation and coordinator evidence above. Client records carry
no serving-pod identity, so session-to-pod scatter itself is not
directly observable in the collected data.

**Figure (to be produced): pinning-cascade plot.** Pinned-pod count vs
time for the 16x relapse and the 8x organic collapse, from
out/perpod/*.csv. Caption draft: "Per-pod KV pinning during collapse.
The 16x relapse is a staggered cascade over four 5-min windows; the
8x organic collapse pins near-synchronously within one window."

## Surviving mechanism reading

With load imbalance refuted by the N-invariant share dispersion and
coordinator saturation excluded by direct measurement, the surviving
reading is span coupling of the post-cancellation drain-vs-catch-up
race: a collapse seeds locally, and the shared balancer spreads cold
catch-up flux - full-context re-prefills for sessions whose prefixes
were evicted elsewhere - onto still-warm pods, duplicating prefixes
and eroding fleet h, while independent shards contain the same seed
inside one bulkhead [R10]. This is an elimination-plus-reproduction
argument, not a direct observation of scatter: the discrete-event
model, which carries the deployed router algorithm and no
N-dependent term, reproduces the left shift emergently (Section on
models) [R9]. The containment contrast itself is demonstrated
directly by the shard measurements.
