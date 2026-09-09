# 6. The CPU-tier third regime and the size series

Adding a host-RAM KV tier (vLLM CPU offloading, `kv-offloading-size`
in GB per pod) to the 8x fleet does not delete the collapse failure
at supercritical rates; it transforms it into a third regime,
restore-bound congestion, whose persistence is set by tier capacity
[R4][R11]. This section characterizes the regime, reports the
measured falsifier of the fixed-restore-ceiling reading, presents
the one matched boundary pair, and gives the tier-size ledger.

## 6.1 Restore-bound congestion at 8x-0.022

Under the standard perturbation at base rate 0.022 sps - the rate at
which the no-offload fleet relapses 3/3 into the cold absorbing
state [R2] - an 8x tier-500 fleet enters a distinct degraded state
in 4 of 6 draws (Section 6.4 gives the full ledger).
Four discriminators separate it from cold collapse, jointly present
in all 4 congested draws (a1, a1rep, lh-tier, bimod5; two at the
300-min horizon) [R4]:

- Hit rate stays high: h 70-85%, with ext_hit 62-79% - most hits are
  CPU-tier restores, not HBM-resident prefixes.
- The fleet restore rate is pinned at 150-192k tok/s, which is
  0.81-1.04 of N*B_r for the effective per-replica restore rate
  B_r = 23k tok/s (calibration provenance in Section 8's constants
  table; per-pod plateau 21.4-24.0k tok/s across all four tier runs
  at both fleet scales while demand exceeds it).
- KV occupancy holds at 93-94%; the tier ingests new writes only
  (measured offload rate 50-78k tok/s tracks uncached prefill plus
  generation; restored blocks stay tier-resident)
  (overlay-findings.md, restore-model calibration).
- The queue diverges slowly and linearly, ~0.8/min over 195 min,
  with no transition to the cold state.

Against the cold absorbing state at the same operating point (h
1.6-3.0%, TTFT p50 to 240 s, queue +~1.1/min, throughput 1.2-1.4
req/s [R1]), the congested state delivers ~2.2x the throughput and
~4x better TTFT [R4]. The failure is not removed: the queue still
diverges, and the state persisted through both 300-min congested
draws [R4].

Figure: out/overlay_restore.png. Caption draft: "Restore-bound
congestion at 8x-0.022, tier-500: measured arcs (h, fleet restore
rate, wait) against DES bands (5 seeds, 300 min). DES curves are
model output (Section 8); the four regime discriminators - pinned
restore channel, linear queue divergence, high h, no cold collapse -
are reproduced 5/5. Model quantitative gaps (h 0.95 vs measured
0.70-0.85; restore share of hits 1.0 vs 0.66-0.79) are stated in
Section 8." (If Section 8 consumes this figure, the forward
reference here becomes a figure citation.)

## 6.2 The pinned band is a state outcome, not a channel capacity

Reading B_r as a hard per-node restore ceiling is falsified by
measurement. The two measured heal arcs sustain 5-min fleet restore
rates of 235,284 tok/s (cpuofl-a4-375-lh, t=70) and 278,161 tok/s
(cpuofl-500-bimod6, t=70) - 1.28-1.51x N*B_r - and then run their
post-cancel restore phase at 0.14-0.56 N*B_r with wait 0.3-7 while
KV drains from 0.83-0.86 at cancellation to 0.26-0.31 [R4]. Two
arcs; both values are reported and no distribution is claimed. The
150-192k tok/s band of Section 6.1 is therefore a congested-state
throughput outcome. The raw DMA link runs at 151.5 GB/s = 1.19e6
tok/s per node at ~2% duty in the congested state, so per-transfer
overhead, not the link, binds there (overlay-findings.md,
calibration provenance). The serial FCFS restore channel in the DES
encodes the falsified ceiling reading and stands as a documented
model deficiency; its concurrent-restore replacement screens
negative on the heal branch and is not merged (Section 8) [R9].

## 6.3 Full heal at the boundary: one matched pair

At base 0.020 - inside the no-offload probability band [R2] - the
one measured 8x tier draw digests the surge completely: ext_hit
42-73% for ~2 h with wait 1-9, restore share of hits decaying 64%
to 0%, KV draining to 5%, a complete self-heal by end of the
300-min horizon [R5]. The same-day no-offload draw at the same
operating point collapsed organically at ~min 240 [R3][R5]. This is
one matched same-day pair, n=1 per side; it demonstrates that the
tier can convert a collapsing boundary point into a full heal in at
least one draw, and it supports no heal-probability claim at 0.020.

## 6.4 The size series: capacity sets persistence

Same-protocol draws at 8x-0.022 across `kv-offloading-size` values
250, 375, 500 (lab-notebook-2026-08-13/15) [R11]:

    size   outcome tally         note
    250    cold collapse 1/1     enters congestion, then falls
                                 through it: ext_hit decays to 1%
                                 as the working set outgrows the
                                 tier; the one 250 draw
    375    healed 2/2            one draw hot, realized 2.02 req/s
    500    4 congested,          congested draws include the two
           2 healed, of 6        300-min horizons of Section 6.1

The refined mechanism split: restore bandwidth sets congested-state
throughput (the pinned band, Section 6.1-6.2), while tier capacity
sets regime persistence - a tier too small to hold the live working
set loses ext_hit and falls through congestion into the cold state
[R11]. The 375-vs-500 contrast (2/2 vs 2/6 heals) suggests a mild
size effect but leaves it unproven at these tallies; realized
request rate does not order outcomes across the ledger (the hot
375 heal at realized 2.02 against a congested 500 draw at warm
realized 2.16; heals otherwise ran near 1.6)
(lab-notebook-2026-08-15.md, S5/S6 verdicts) [R11].

Figure: out/overlay_tiercap.png. Caption draft: "Tier-capacity pair
at 8x-0.022: measured size-250 and size-500 arcs with DES
capacity-sweep bands (model output, Section 8). The DES reproduces
the direction and the cold-persistence boundary of the pair - 250
falls through to cold, 500 stays congested - but produces no heals
at this rate; the heal branch is a documented model failure
(Section 8)."

## 6.5 Boot envelope

`kv-offloading-size` is RAM-backed at GB scale. Size 650 does not
boot on these hosts: all 8 pods crash-loop with the gcsfuse sidecar
OOM-killed (pod memory request 620Gi against ~858Gi node
allocatable; the pinned tier plus the sidecar's uncapped file cache
does not fit) (lab-notebook-2026-08-15.md, S3 infra note) [R11].
The executable size series therefore ends in (500, 650), scoped to
these hosts [R11], and no statement is made about sizes above 500.
