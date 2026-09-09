# Section 3. A theory of prefix-cache metastability

Status: new section for the manuscript (paper/draft2.md integrates it
as Section 3). Standalone here for review. Every numeric value is
computed from the calibrated workload functionals (fluid_model.py,
gap cap 10.5 s via overlay_fixedpoint.set_gap_cap) and the measured
constants of the Section 7 calibration table; the derivation commands
are reproducible from fig_theory.py and the inline expressions below.
Figures referenced: out/paper/fig_fixed_point.png,
out/paper/fig_hysteresis.png, out/paper/fig_phase_diagram.png
(generator fig_theory.py).

Markers: [R<n>], [C<nn>] as in the manuscript. Claims in this section
are model constructions unless tied to a measured anchor, and each
anchor names its measurement.

---

## 3. A theory of prefix-cache metastability

This section derives the failure structure that Sections 5-7 measure.
The derivation proceeds in three steps: a retention fixed point that
couples the cache hit rate to the cache write rate (Section 3.1); an
occupancy-and-queueing feedback that creates the cold branch under
the workload's actual reuse-gap distribution (Section 3.2); and
first-order break-point and sizing estimates, including the minimum
host-tier capacity, each checked against a measured quantity
(Sections 3.3-3.4). Section 3.5 collects the dimensionless groups
that organize the regimes. The theory is deliberately first-order: it
predicts the existence, location, and scaling of the regimes, and the
calibrated simulation of Section 8 carries the quantitative claims.

Notation. N replicas each hold an HBM KV pool of C tokens under LRU
block eviction (fleet pool S = N * C) and an optional host-memory
tier of C_cpu tokens per replica; p is the per-replica prefill rate
(tokens/s) and B_r the effective per-replica tier-to-HBM restore rate
(tokens/s). Sessions arrive at rate lambda_s (sessions/s) and issue
E_req requests over their lifetime, giving a long-run request rate
lambda_r = lambda_s * E_req. A request whose context is c tokens
prefills only its new input delta on a hit and c + delta on a miss;
either way it appends its output o to the cache. F(t) is the
reuse-gap distribution: the probability that a session's next request
arrives within t seconds of the previous one becoming reusable.
Calibrated values for the measured stack (N = 8, C = 1.66M tokens,
S = 13.28M, p = 17k tokens/s, E_req = 118, gap cap 10.5 s):

    E[write | miss]   w_miss  = 117.8k tokens/request
    E[write | hit]    w_hit   =   5.2k tokens/request
    E[prefill | miss] c_miss  = 116.9k tokens/request

### 3.1 The retention fixed point

An LRU cache under aggregate write rate W retains an entry for the
characteristic time T = S / W: new writes traverse the pool in T
seconds, and an entry survives if it is touched again within that
window [che2002hierarchical, fricker2012versatile]. In a prefix
cache, W is not exogenous. A request that misses re-prefills its full
context and writes it back into the pool; a request that hits writes
only its increment. At hit rate h,

    W(h) = lambda_r * [ (1 - h) * w_miss + h * w_hit ],        (1)

and the hit rate is in turn set by whether entries survive their
reuse gaps:

    h* = F( S / W(h*) ).                                       (2)

Equation (2) is the classical characteristic-time fixed point with
one addition outside its assumptions: the write rate depends on the
hit rate it produces. The strength of the coupling is the write
amplification

    A = w_miss / w_hit = 22.6                                  (3)

for this workload: one miss evicts as much cache as twenty-two hits.
(The agentic corpus drives A through its context lengths: the mean
re-prefilled context is 117k tokens against a mean per-turn increment
of ~5k.) Because W falls as h rises, the map Phi(h) = F(S / W(h)) is
increasing, and an increasing map can cross the identity more than
once: a warm fixed point (high h, low write pressure, long retention)
and a cold one (low h, miss writes flooding the pool, retention too
short to hit) can coexist at the same offered load, separated by an
unstable crossing. The boundary of coexistence is the tangency
(saddle-node) condition Phi(h) = h, Phi'(h) = 1. For a two-point
reuse-gap mixture in which a fraction x of requests return after
gaps longer than y and the rest return quickly, the warm point
h = 1 - x exists iff the pool covers the long gap at the warm write
rate:

    S  >=  lambda_r * y * [ x * w_miss + (1 - x) * w_hit ],    (4)

which inverts to a closed-form collapse edge in load,
lambda_up = S / (y * [x * w_miss + (1 - x) * w_hit]), and to the
matching recovery edge with w_miss evaluated at the cold mix. Whether
retention feedback alone produces coexistence depends on where
S / W(0) lands in F. It must land inside F's central mass: in an
earlier capacity-starved production case (8-replica, 0.95M-token
pools, 130k-token mean contexts, ~10 requests/s), S / W(0) = 11.6 s
against think times of tens of seconds, and equations (1)-(4) alone
give a bistable band. On the measured stack of this paper the pools
are larger and the protocol caps reuse gaps at 10.5 s (Section 4.2),
so S / W(0) = 43-80 s at the studied loads sits far above every gap:
equation (2) then has a single warm solution at every studied rate,
and no static retention argument can produce the cold state that
Section 5 measures. The cold state requires a second feedback.

### 3.2 The occupancy-queueing feedback and the cold branch

Two mechanisms tie the cache to the request queue. First, running
requests occupy the pool: an admitted request reserves its full KV
need until completion, and admission fills the pool to a watermark
theta (0.92 in the measured engine) whenever work is waiting. The
cache lives only in the remainder, so the retention window under a
backlog is

    T_eff = S * (1 - occ) / W(h),                              (5)

with occ -> theta when a queue exists. Second, a queued request's
prefix must survive its reuse gap plus its waiting time w, so the
survival probability is F(T_eff - w), not F(T_eff). Both corrections
vanish in light traffic and both bite simultaneously under a backlog:
occupancy multiplies the window in (5) by (1 - theta) = 0.08, and
waiting subtracts minutes from a window measured in seconds. The
service side closes the loop. With the prefill engine as the
bottleneck, the fleet's service rate at hit rate h is

    mu(h) = N * p / E[prefill per request at h],               (6)

which spans a factor of ~27 between the branches: mu(warm) ~ 31
requests/s against mu(0) = N * p / c_miss = 1.16 requests/s. The
measured cold-state throughput is 1.2-1.4 requests/s [R1][C01],
within ~15% of the mu(0) estimate; the small excess is the measured
2-3% residual hit rate. A backlog therefore sustains itself whenever
the flux draining into the fleet exceeds mu(0) while prefixes are
cold: misses hold the pool pinned and the waits long, which holds the
hit rate near zero, which holds the service rate at mu(0).

Figure 3a shows the resulting structure as a one-step map
conditioned on backlog depth Q at the reference operating point
(N = 8, lambda_s = 0.022): with Q = 0 the map is monostable warm
(the static result of Section 3.1); at moderate Q the map folds and
two stable crossings coexist; deeper backlogs push the escape
threshold - the hit rate a fleet must already have for its cache to
outrun the queue - toward 1. Figure 3b integrates the joint dynamics
of (h, Q) through the post-perturbation drain window and colors the
two basins: the boundary between them is the separatrix of the
drain-versus-rewarm race. This is the theoretical object that the
drain-depth observable of Section 5.5 estimates empirically: KV
occupancy measured just after the perturbation ends is a proxy for
which side of the separatrix the trajectory is on.

The demand side determines whether the cold branch is reachable at
all. Requests within a session are completion-coupled: a session
issues its next turn only after the previous one returns, so
in-flight demand defers under slowdown instead of accumulating
[R7][C33]. A closed population therefore self-stabilizes (Section
5.4). What makes the cold branch reachable is a demand reservoir
that does not yield: sessions arriving as an exogenous stream park
their next turns while the fleet is slow and release them as
catch-up flux when service resumes. Agentic workloads realize
exactly this structure - tool loops resume the moment their previous
call returns, and clients retry rather than abandon - which is why
the open-loop session-arrival protocol of Section 4, and not a
classical closed-loop benchmark, exposes the failure.

### 3.3 Break-point estimates

The two feedbacks yield first-order brackets for the collapse band
measured in Section 5.2.

Cold-branch feasibility (necessary condition). A sustained cold
state requires the deferred flux to exceed the cold service rate:
lambda_r > mu(0), i.e.

    lambda_s  >  N * p / (c_miss * E_req)  =  0.0098 /s.       (7)

Below this rate the backlog drains even with every request missing,
and recovery is unconditional. The measured protocol recovers 2/2 at
lambda_s = 0.012 and 4/4 at 0.017 [C02]: both sit above bound (7),
consistent with (7) being necessary rather than sufficient - between
the bound and the measured entrapment edge at 0.020-0.022, the
deferred flux is partly completion-coupled (the reservoir drains
serially), so the effective flux against mu(0) is below lambda_r and
the race of Figure 3b is winnable. The gap between bound (7) and the
measured edge is the elasticity margin of the workload.

Warm-branch feasibility. The warm branch persists while warm-state
prefill demand fits: lambda_r * E[prefill | warm] < N * p, which
holds up to roughly ten times the studied loads (utilization 0.08 at
lambda_s = 0.022). The warm branch is therefore not destroyed by
load anywhere near the band - it is abandoned. Entry into the cold
basin at the studied rates is fluctuation-driven: an eviction-scale
perturbation (Section 4.3), or the slow occupancy growth of
deepening sessions, carries the state across the separatrix, which
is why outcomes at fixed operating points are frequencies rather
than deterministic responses [C02][C05], and why the coexistence
region appears as hysteresis rather than as a capacity wall
(Figure 4).

Perturbation scale. A surge at write rate W_s evicts parked prefixes
on the pool-traversal timescale S * (1 - occ) / W_s; at the measured
saturated write rate this is under two minutes, so both surge
durations in the protocol (900 s and 2700 s) fully evict the pool
several times over. What the longer surge changes is the reservoir:
deferred sessions accumulate for six times longer, and the
post-cancellation race begins from a deeper Q. The measured duration
contrast (900 s recovers, 2700 s entraps, at the same rate) [C03] is
therefore a reservoir-depth effect, not an eviction-completeness
effect, consistent with the basin geometry of Figure 3b in which
deeper Q requires higher surviving hit rate to escape.

Asymmetry of the two transitions. Collapse is fast because eviction
runs on the pool-overwrite timescale (minutes under a surge);
recovery is slow because cache coverage can grow no faster than real
time - content only becomes T seconds old after T seconds - while
every miss along the way regenerates eviction pressure. The
hysteresis of Section 5.3 is this asymmetry read at steady state.

### 3.4 The host tier: capacity sets the regime, restore bandwidth sets its throughput

A host-memory tier of C_cpu tokens per replica extends retention.
The tier ingests only new writes (restored blocks already reside
there; measured, Section 6.1), so its window adds to (5):

    T_tot = T_eff + N * C_cpu / W_new,                         (8)

with W_new the new-write rate. The naive sizing rule - delete the
cold branch by making T_tot(h = 0) exceed the reuse gaps - is
necessary but far from the operative constraint, because a tiered
fleet under overload never reaches h = 0: it settles into the
congested regime of Section 6, serving hits through the restore
channel. Two separate quantities govern that regime.

Tier capacity sets persistence. Under congestion the parked working
set recirculates: each live session is touched once per
recirculation time t_rec ~ L / mu_c, where L is the live-session
count and mu_c the congested completion rate. A session's tier entry
survives to its next touch iff the tier window exceeds t_rec, giving
the minimum capacity

    C_cpu*  ~  W_new * t_rec / N.                              (9)

At the measured congested point (W_new = 50-78k tokens/s ingest
[R4], mu_c = 2.5-4.3 requests/s serving a live population of ~200
sessions, t_rec ~ 50-90 s), rule (9) gives 0.4-0.7M tokens per
replica - bracketing exactly the measured persistence boundary: the
0.42M-effective tier loses its external hits and falls through to
cold, while 0.63M and 0.84M persist indefinitely [C13]. Below C_cpu*
the tier only delays collapse; above it the tier converts collapse
into congestion.

Restore bandwidth sets congested throughput. Every completion in the
congested regime re-onboards most of a context through the restore
channel, so completions are bounded by

    mu_restore = N * B_r / (h_ext * c_miss)  ~  2.2/s          (10)

at the measured h_ext ~ 0.7 and B_r = 23k tokens/s - against a
demand of 2.6 requests/s at lambda_s = 0.022. The regime therefore
runs with its restore channel pinned (measured: 0.81-1.04 of N * B_r
[C10]) and its queue diverging slowly (measured: ~0.8 requests/min),
exactly the discriminators of Section 6.1. B_r here is the measured
congested-state throughput of the channel, not a hardware ceiling;
the two measured complete recoveries sustained 1.28-1.51x this rate
during their escape (Section 6.2) [C11], and the distinction matters
for the model failure documented in Section 8.

The design consequence is a trade, not a fix: a sufficiently large
tier deletes the cold absorbing state (the capacity cliff), and in
exchange the overloaded fleet occupies a congested state whose
throughput is set by restore bandwidth (a bandwidth cliff). Sizing
the tier by rule (9) without provisioning B_r converts one failure
mode into another - the central operational finding of Section 6.

### 3.5 Dimensionless structure

Five ratios organize the regimes; the measured stack's values at the
reference operating point (N = 8, lambda_s = 0.022, no tier unless
stated):

    A       = w_miss / w_hit                    22.6
    Lambda  = lambda_r * c_miss / (N * p)        2.2
    G       = S * (1 - theta) / (W(0) * g)       ~0.4
    Kappa   = N * C_cpu / (W_new * t_rec)        0.7-2.0 (sizes 250-500)
    Rho_r   = lambda_r * h_ext * c_miss / (N * B_r)   ~1.2

A is the feedback strength: A ~ 1 is a classical cache, A >> 1 makes
the write rate a state variable. Lambda is the cold-branch load
ratio: Lambda < 1 forbids a sustained cold state (bound (7));
Lambda > 1 makes the cold branch feasible and the outcome
race-decided. G compares the pinned-pool retention window to the
reuse-gap scale g: G < 1 means a backlogged fleet cannot hit, which
is what arms the cold branch; the same fleet at h = 0 with the
backlog drained has G ~ 1.7, which is why a cold but idle fleet
re-warms. Kappa is the tier
persistence ratio of rule (9): the measured fall-through sits at
Kappa < 1, the persistent congested regime at Kappa > 1. Rho_r is
the restore-channel load: Rho_r >= 1 pins the channel and the
congested queue diverges; Rho_r < 1 leaves escape headroom. The
router-span dependence of Section 7 is not captured by any of these
ratios - it is a property of how one balancer couples N replicas'
races (Section 7.8) - and the theory's honest scope is: existence,
location, and scaling of the regimes at fixed span.

### 3.6 What the theory does not claim

The constructions above are mean-field and first-order. They do not
predict the collapse probability inside the band (outcomes there are
fluctuation-decided; the calibrated simulation of Section 8 carries
those claims, with its documented biases), the magnitude of the
router-span shift (Section 8 reproduces its direction emergently),
the timing of delayed collapses, or the escape dynamics of the
congested regime (the model's documented recovery-branch failure,
Section 8.6). Each formula's measured anchor - mu(0) against the
cold throughput, rule (9) against the tier-size boundary, bound (10)
against the pinned restore band - is a consistency check at one
operating point, not a validated response surface.
