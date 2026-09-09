# Section 9. Mitigation: reservoir smoothing at admission

Status: new section for the manuscript (integrated into
paper/draft2.md as Section 9). Standalone here for review. Every
number comes from out/mitigation_screen.csv and
out/router_family.csv (generator mitigation.py, deployed-router DES,
300-min horizon); figures out/paper/fig_mitigation.png and
out/paper/fig_router_family.png. All results in this section are
model output on the calibrated DES of Section 8, with its documented
reservation bias; no controller has been validated on hardware.

---

## 9. Mitigation: reservoir smoothing at admission

The theory locates the point of control. Collapse entry is a race in
the (hit rate, backlog) plane (Section 3.2), and the one input a
serving platform controls without touching the engine is which
requests join the backlog. This section screens four admission
controllers in the calibrated deployed-router model at the
deterministic-collapse point (N=8, lambda_s=0.022, untiered), under
two protocols, against the uncontrolled baseline; it then tests
whether the failure the controllers guard against is specific to the
deployed router's policy at all.

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
sessions are never cancelled. The distinction is load-bearing for
evaluation. Under the standard protocol, work a controller defers
past the cancellation point is work it never has to do, so any
mechanism that delays surge admission looks good. Under the
persistent variant the deferred work is real: offered work exceeds
the horizon's total service capacity by construction, and the honest
metrics are served volume, end-state class, and the delay imposed on
deferred sessions - the regime an asynchronous-serving deployment
actually faces. Aqua's argument that admission control trades away
burst responsiveness [aqua2025] applies to rejection; deferral pays
in queueing delay on a durable queue instead of in lost work, and
the persistent-surge protocol prices that delay explicitly.

### 9.3 Results

![Figure 16](../out/paper/fig_mitigation.png)

Figure 16. Admission controllers at (N=8, 0.022, untiered), standard
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
572-643 sessions per run. At this protocol's face value AIMD is the
best controller.

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
uncontrolled (its known leftward bias, Section 8.4), checks
no-harm: the deferral gate recovers 3/3 with warm hit rate
unchanged; aimd-pub recovers 3/3; aimd-tuned degrades 2 of 3 runs
(end h 0.77-0.79 with a standing reservoir) - re-scaled constants
that help at the collapse point throttle a healthy one; and
rejection recovers 3/3 at the cost of 514-609 permanent rejections
at an operating point that mostly recovers on its own. Rejection
converts risk into certain loss; deferral converts it into delay.

### 9.4 The band is not the router's

![Figure 17](../out/paper/fig_router_family.png)

Figure 17. The standard perturbation under three routing policies
(N=8, untiered, 3 seeds per point, 300 min; model output): the
deployed EPP policy, an emulation of the SGLang cache-aware
threshold-switch policy (imbalance gate at 32 absolute / 1.0001
relative, prefix-match threshold 0.5), and an emulation of the
AIBrix prefix-aware policy (imbalance gate at 8 running requests,
least-loaded among matching replicas). Emulations use engine-truth
match state, the policies' best case.

All three policies produce the same band structure: recovery
dominates at 0.017, mixed outcomes at 0.020, and collapse at 0.022
(the deployed policy and the SGLang emulation show identical
tallies; the AIBrix emulation recovers one of three runs at 0.022).
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
