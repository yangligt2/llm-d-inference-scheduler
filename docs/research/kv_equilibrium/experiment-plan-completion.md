# Completion plan: remaining experiments for the paper

Status basis (2026-08-10): E-series closed-loop block done; B1
session-arrival hysteresis block done (relapse n=2 at 0.022 sps,
recovery n=2 at 0.012, n=1 at 0.017, edge in (0.017, 0.022), 8xTP4);
B2a tier validation done at 4xTP4 (n=1, scaling caveat); fluid + DES
overlays done with three falsifiable predictions
(overlay-findings.md). What follows is everything still needed, in
value order, with predictions and costs. Runs are ~3.25 h each
(lifecycle + scheduled surge) unless noted.

## Fleet decision

Primary fleets at 8 replicas (resume original geometry): every new run
that pairs against the B1 centerpiece must be same-geometry. The 4x
geometry is retained ONLY for the N-scaling tests (A2, C1), where the
geometry change is the object of study. Suggested allocation at 16+
servers: 8x no-offload (track B) + 8x cpu-offload (track A) in
parallel; a third 4x no-offload fleet if 4+ spare servers exist
(tracks A2/C1). EPP precise-prefix-cache everywhere except C2.

## Track A - mitigation completion (8x cpu-offload fleet)

A1. Tier arm at the centerpiece geometry (TOP PRIORITY). 8x
    cpu-offload, exact b1a2 protocol: base 0.022 sps 3 h + surge 0.25
    x 2700 s at t+62, salted, cap 10.5. Two draws. Prediction (fluid,
    DES, and B2a): recovery, no relapse; in-surge tier thrash then
    restore-driven catch-up (ext_hit signature). Pairs with the
    measured n=2 no-offload relapse with NO scaling assumption. This
    closes the mitigation pillar. 6.5 h.

A2. B2a's own missing control. 4x NO-offload, base 0.011 + surge
    0.125 x 2700. Model+DES prediction: RELAPSE. Confirms B2a's
    recovery was the tier, and tests the model's N-scaling in the
    same stroke. 3.25 h. (Needs the 4x no-offload fleet or a
    temporary stack swap.)

A3. Tier relapse-search (how far the tier moves the edge). 8x
    cpu-offload, ladder base 0.033, 0.044, 0.055 sps (1.5x / 2x /
    2.5x the no-offload edge), same surge; bisect after first
    relapse. Model (ideal tier) says no relapse through ~2.9x and
    overload surfaces as warm queueing; the real tier thrashed
    in-surge, so the measured edge shift is THE number for the sizing
    story. ~10 h.

A4. Tier-size point for the sizing rule. Redeploy offload stack with
    --kv-offloading-size at half the current value (80 GB-equivalent),
    rerun the first relapsing ladder point from A3. Prediction: edge
    shift scales roughly with tier capacity. 2 runs + redeploy. ~7 h.

## Track B - boundary characterization (8x no-offload fleet)

B1. Boundary bimodality (DES-motivated, publishable on its own).
    Four additional draws at 0.017 (existing: one recovered-grazing
    draw). DES predicts a mixed outcome set (~1-2 of 5 relapse).
    Demonstrating stochastic OUTCOME at fixed operating point is the
    sharpest form of the capacity-planning warning. 13 h.

B2. Recovery edge in session units (hysteresis loop closure). After
    a relapse (reuse any relapsing B1 draw, or run a fresh 0.022
    relapse): kill the base generator, immediately restart with
    -r false at 0.012 (predict recovery) and, second draw, at 0.017
    (prediction uncertain - measures whether the recovery edge sits
    below the collapse edge, i.e. the hysteresis width in exogenous
    units). 2 runs, ~8 h.

B3. Long-horizon absorbing check. One b1a2-protocol run with the base
    extended to 300 min (75 -> 195 min of post-surge observation).
    Prediction: no recovery; queue grows to generator limits.
    Forecloses the "would it eventually recover?" review question.
    ~5.5 h.

## Track C - secondary model tests (optional, cut first)

C1. N-scaling edge pair. 4x no-offload at 0.008 (predict recover) and
    0.010 (predict relapse) - the model's sharpest falsifiable pair;
    with A2 it maps the 4x edge. 6.5 h.

C2. Routing ablation at the band. Rerun 0.017 and 0.022 arms under
    the approx-prefix EPP config (no KV events). The customer
    escalation was routing-accuracy-driven; the model says lower
    effective affinity shrinks the warm ceiling and moves the edge
    down. Connects the band story to the original escalation. 2-4
    runs + EPP swaps. ~13 h.

## Explicitly NOT needed (already answered)

- More E-series cells (boundary, stationarity, F(T) flat segment, cap
  co-movement: done; falling segment shown unreachable statically).
- More request-metered qps pairs (superseded as centerpiece; kept as
  motivation exhibit).
- sps-mode validation or Poisson checks (done, n=4 runs).
- Closed-loop recovery-on-N-drop (done, R8).
- E4 flush-recovery and E6 geometry sweeps from the old closed-loop
  plan (dynamics covered by B1/B2 arcs; geometry covered by A2/C1).

## Budget

Track A: ~27 h fleet time; Track B: ~27 h. In parallel on two 8x
fleets: ~2.5-3 days. C1 on a spare 4x fleet overlaps freely; C2 adds
a day if taken. Cut line if time-boxed: A1, B1, A3, B2, A2, B3, A4,
C1, C2.
