# Sections 4-5 draft: measurement methodology and collapse phenomenology

Claim coverage: C01-C09, C33-C35 (supporting C04, C07 context).
Citations: [R<n>] = research-status.md result n; (path) = named
artifact. Figure paths under kv_equilibrium/out/ unless marked
TO PRODUCE.

## 4. Measurement methodology

### 4.1 Stack and instrumentation

All measurements run on TP4 GB200 fleets of 4, 8, or 16 replicas
serving Qwen3-Coder-480B-A35B-Instruct-FP8 under vLLM with block
size 256; each replica holds a KV pool of 6486 x 256-token blocks
(13.28M tokens at 8 replicas) (experiment-env.md). Requests reach
the fleet through an Envoy front end and an Endpoint Picker (EPP);
the EPP plugin configuration is a first-class experimental factor,
selected per run among a precise prefix-cache config (KV-event
token-based affinity; the baseline for the 2026-08-08+ series), an
approximate-prefix config with no KV-event pipeline, and a load-only
config (queue and kv-utilization scorers, no affinity signal)
(experiment-env.md). Server state is scraped from the per-pod
metrics endpoints at 5 s cadence; fleet aggregates use the pod
endpoints only, excluding the service endpoint, which round-robins
pods [C34]. Hit rate h is computed as windowed counter diffs of
vllm:prompt_tokens_cached over vllm:prompt_tokens; the
prefix_cache_queries/hits pair is not used because it re-counts
under pressure (experiment-env.md). Arc time series are 5-minute
windows anchored to wall clock so concurrent runs align
(analyze_run_windows.py); window labels give the window start. One
gauge-semantics caveat applies throughout: the
vllm:num_requests_running gauge excludes requests in
WAITING_FOR_REMOTE_KVS, so server-side running counts do not equal
client-side load during restore phases [R9].

### 4.2 Workload

The primary corpus is a 393-trace agentic replay set (062126: 68266
requests, mean ~174 requests per trace); inter-request idle gaps
are capped at 10.5 s, the corpus p90 (experiment-env.md). Surge
traffic replays a disjoint 232-trace corpus (061526) so burst and
base load share no trace identity. Every replay instance is salted
on its first-turn prefix (cacheBust); without salting, cross-play
prefix sharing inflates h (experiment-env.md).

Arrival semantics are load-bearing. Open-loop experiments use
Poisson session arrivals at rate lambda_s with concurrency as an
admission ceiling; requests within a session remain
completion-ordered. Closed-loop experiments meter a fixed credit of
in-flight work; the measured credit multiplier is ~1.45x configured
concurrency on this corpus (configured 40 -> achieved ~56 in-flight,
100 -> ~147), so all load-axis statements use achieved in-flight
[R8]. Request-metered rate mode is excluded from collapse
experiments: it re-issues work independently of completions and is
a built-in retry storm, whereas completion-coupled session arrivals
defer rather than storm; open-loop collapse experiments therefore
pin demand at the session level [R7][C33].

### 4.3 Perturbation protocol

Each collapse experiment resets every pod's prefix cache, runs base
load at lambda_s, and at t ~ +62 min launches a surge overlay
without cache reset: 0.25 sessions/s for 2700 s (the standard dose;
a 900 s variant probes the duration axis), with nominal cancellation
at t ~ +107 min (lab-notebook-2026-08-08). The surge generator
cancels its entire session population on exit, so all post-cancel
dynamics are sustained by the base load alone
(lab-notebook-2026-08-08). Horizons run 150-300 min; Section 5.3
shows why the long horizon is not optional. Closed-loop states are
held 65 min before being read as stationary [R8].

[FIGURE TO PRODUCE: protocol timeline diagram - reset, base phase,
surge overlay window t+62 to t+107, post-cancel observation horizon
with the kv115 read point marked. Caption draft: "Perturbation
protocol. Base session arrivals at lambda_s; eviction-scale surge
overlay (0.25 sps x 2700 s) from a disjoint corpus; the surge
population is cancelled at exit, so the post-cancel race is
base-sustained. The t=115 window is the drain-depth read point of
Section 5.5."]

### 4.4 Comparability, draw variance, and artifact rules

Five factors are recorded per run and held fixed within any
comparison: router config (EPP ConfigMap), corpus, gap cap, salt,
and duration [C34]. The July/early-August reference series ran
under different EPP configs and unsalted generators and is
quarantined from all fits (experiment-env.md). Realized request
rate varies ~+-0.4 req/s between draws at fixed lambda_s and does
not order outcomes within any ledger [R2][C04]; consequently every
probabilistic statement in this paper is an outcome tally over
repeated draws, never a dose-response reading of single runs.
Two artifact-existence rules make absent data auditable rather than
silently missing: aiperf artifacts exist only after end-of-run
export (one hung export in ~40 runs through 08-13, zero in the
19-run 08-15/16 window), and capacity reclaim destroys un-scaled
fleets, so an unconditional scale-down is scheduled at window start
for T-15 min [R12][C35].

## 5. Collapse phenomenology (no-offload)

### 5.1 Anatomy of an absorbing collapse

After the standard surge on an 8-replica no-offload fleet at base
rate 0.022 sps, the system does not return to its pre-surge
operating point. It enters a cold state with hit rate h 1.6-3.0%
(pre-surge warm h ~0.94), TTFT p50 rising to 240 s, queue growth
~1.1 requests/min to a waiting depth of 289, and throughput pinned
at 1.2-1.4 req/s, with zero recovery over 195 post-surge minutes
(n=3 draws: b1a2, b1a2-rep, ppc-lh-noofl; one draw ran the full
300-min horizon) [R1][C01]. The state is self-sustaining: the surge
process no longer exists after cancellation, and the base load that
the same fleet served warm before the surge maintains the collapse
indefinitely on the measured horizon. The mechanism visible in the
arcs is a drain-vs-catch-up race: the surge evicts the base
sessions' prefixes; after cancellation the deferred base reservoir
drains back as catch-up flux; if that flux exceeds the cold-branch
service capacity before prefixes re-warm, misses regenerate the
eviction pressure and the fleet locks cold [R1][R2].

[FIGURE TO PRODUCE: measured multi-arc composite from out/arcs/*.csv
- h, TTFT p50, and waiting depth vs time for one collapsing and one
recovering draw at adjacent rates. Caption draft: "Measured arcs of
one absorbing collapse (8x-0.022) and one recovery (8x-0.017) under
the identical perturbation. All curves are 5-min windows from
per-pod scrapes; no model output appears in this figure."]

### 5.2 The collapse-probability band

The identical perturbation applied across base rates yields a
probability band, not a threshold line. Outcome tallies over 17
draws [R2][C02]:

    base rate (sps)  draws  outcome
    0.012            2      recovers 2/2
    0.017            4      recovers 4/4 (150-180-min horizons;
                            post-surge KV 40-78% across draws)
    0.020            8      collapses 5/8 by 300 min; three classes:
                            clean x3, organic-late x2 (cold by ~min
                            240), fast relapse x3 (onset min ~130-150)
    0.022            3      relapses 3/3

The hard-relapse edge lies in (0.020, 0.022). These are tallies; no
continuous p(collapse | rate) curve is fitted to them. Within the
0.020 ledger, realized request rate does not order outcomes: a fast
relapse occurred at realized 1.62 req/s while a clean draw ran at
1.78 [R2][C04].

[FIGURE TO PRODUCE: band tally figure from the notebook ledgers -
outcome counts per rate with the three 0.020 outcome classes
distinguished. Caption draft: "Outcome tallies under the identical
perturbation at four base rates (n=17). The 0.020 point is bimodal
with three outcome classes; the hard-relapse edge lies in
(0.020, 0.022)."]

Collapse is thresholded on two axes, each established by one
measured contrast pair [R2][C03]. Duration axis: at 0.022, a 900 s
surge pin recovers while the 2700 s pin relapses - the surge must
outlast the prefix-eviction time (one contrast pair). Flux axis:
draw b1c held 4.9 req/s of post-cancel catch-up warm while b1a2
re-tipped at 4.8 - the discriminator is the sustained arrival flux
lambda_s against drain headroom, not the instantaneous catch-up
rate (one contrast pair). No dose-response curve is claimed on
either axis.

### 5.3 Horizon dependence and the organic-late class

Surviving the perturbation is not surviving. At 8x-0.020, 2 of 8
draws that rode out the surge and re-warmed collapsed organically
at ~min 240, with no new perturbation: session deepening walks KV
occupancy into the pin, and per-pod pinning is near-synchronous
(2/8 pods to 8/8 within one 5-min window) [R3][C05]. This class is
visible only at the 300-min horizon; 60-180-min runs overstate
stability at this operating point. The 0.017 row of the band table
carries the corresponding caveat: its 150-180-min horizons would
not see an organic tail if one exists (separatrix-findings.md).

### 5.4 Irreversibility and the closed-loop contrast

The cold state exhibits hysteresis: the same fleet that serves the
base load warm cannot re-warm from cold at that load, and recovery
requires dropping demand below the band's lower edge; in the
closed-loop block, each in-flight level has a unique equilibrium
and recovery occurs on N-drop [R1][R8][C06]. The collapse is
therefore a bistable-band phenomenon, not a capacity shortfall: the
warm and cold branches coexist at the same demand.

Closed-loop (completion-gated) arrivals self-stabilize instead of
collapsing. The measured boundary sits at achieved in-flight ~73
warm versus ~103+ degraded; degraded states are stationary rather
than absorbing; and the throughput function F(T) shows a flat
segment with cap/T co-movement [R8][C07]. The falling segment of
F(T) is unreachable statically and was not observed. Absorbing
collapse requires demand that does not yield to backpressure:
either inelastic request-pinned generation or a deferred session
reservoir whose refill outpaces its drain [R7][C07]. The open-loop
session-arrival protocol of Section 4 realizes the second
condition, which is also the condition agentic workloads realize.

### 5.5 The drain-depth separatrix

The post-cancel race of Section 5.1 has a measurable state
variable: fleet-mean KV occupancy in the [115, 120)-min window
(kv115), which opens 8 min after nominal surge cancellation
(separatrix-findings.md). At 8x-0.020, kv115 separates fast relapse
from survival in all 8 draws: fast >= 0.73, non-fast <= 0.66
[R15][C08]. A shallow drain means the catch-up flux re-inflated KV
before prefixes re-warmed; the race is already lost when the
window closes. The reading precedes erosion onset in 20 of 21
fitted draws, and kv110 does not separate (one survivor read 0.674
mid-drain), so t=115 is the earliest clean read point
(separatrix-findings.md).

Across the 21 standard-dose fitted draws (10 events), a
Firth-penalized logistic fit of p(fast | kv115, rate) gives kv115
signal beyond rate (penalized LR p ~ 0.044); within the 8x-0.020
stratum the three fast draws hold exactly the three highest kv115
values (exact permutation p = 1/56 = 0.018) [R15][C08]
(out/separatrix_draws.csv, separatrix_fit.py). The fitted p=0.5
thresholds are kv115* = 0.786, 0.693, 0.630 at per-8x-equivalent
rates 0.017, 0.020, 0.022; the 0.020 value sits inside the
empirical separation interval (0.683, 0.735). At n=21 the threshold
direction and location are established, the steepness is not (the
kv115 coefficient's Wald 95% interval spans roughly (1, 39))
(separatrix-findings.md). kv115 also orders the collapse-onset
spectrum: among the 12 fitted collapsing draws the rank correlation
between kv115 and onset time is -0.99 - shallower drains collapse
earlier [R15][C08]. The covariate was articulated mid-campaign, so
these p-values are not from a pre-registered test; the three
8x-0.020 draws measured after articulation landed on the
hypothesized sides of the threshold (separatrix-findings.md).

Two scope limits bound the claim. First, the threshold moves with
rate and fleet size: at 16x, the 0.034 point survived kv115 = 0.74
and a 0.037 draw relapsed from 0.65 - each a single-draw point
observation (n=1 each) [R15][C09]. Second, kv115 does not predict
the organic-late class: those draws win the drain race from deep
drains (kv115 0.616 and 0.663) and collapse ~2 h later by a
distinct mechanism [R15][C09]. kv115 is a mediating observable of
the drain-vs-catch-up race, not a universal law or control input;
in the logistic ladder it is confounded with the N=16 indicator at
n=21, because every 16x draw at the 0.020-equivalent point both
drained shallow and relapsed - the mediation reading rests on the
within-stratum permutation test and the model comparison of
Section 8 (separatrix-findings.md) [C08].

Figure (out/separatrix_fit.png). Caption draft: "Drain-depth
separatrix. kv115 (fleet-mean KV occupancy over the [115, 120)-min
window) vs per-8x-equivalent rate for the 21 fitted draws, marked
by outcome class; the line is the Firth-penalized p(fast) = 0.5
contour (kv115* = 0.786/0.693/0.630 at 0.017/0.020/0.022). The two
organic-late draws sit at the deep end and are not predicted by
kv115; the 16x points illustrate the threshold's N-dependence."
