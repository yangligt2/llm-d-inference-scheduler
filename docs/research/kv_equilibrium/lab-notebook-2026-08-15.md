# Lab notebook 2026-08-15: 32-host x 42-h window (S1-S6 plan)

Plan: experiment-plan-next-window.md. Reclaim 2026-08-16 17:00 PDT;
unconditional scale-down armed for 16:45 PDT as in-cluster CronJobs
in all five namespaces (survives operator-machine sleep) plus a local
backstop timer. All runs 300 min, salted, cap 10.5, surge at base
t+62 min cancelled at +107, EPP metrics scraped on every run (NEW:
bench.sh appends the EPP :9090 endpoint to SERVER_METRICS_URLS;
consumers exclude non-:8000 rows from fleet aggregates).

## Bring-up (22:00-22:40 PDT 08-14)

- Five namespaces validated: yangligt-ns16 (16x noofl), -shard-a/b
  (8x noofl), -tier-a (4x tier, scaled 0 until S3), -tier-b (8x
  tier, scaled 0). All EPPs mount precise-prefix-cache; ns16 carries
  baseline; ns16 + shard-a carry the NEW load-only variant
  (queue-scorer + kv-cache-utilization-scorer only), which passed a
  live swap test on shard-a's EPP.
- bench-assets ROX clones verified in all five (both corpora +
  tokenizer); Pending status was WaitForFirstConsumer.
- Smoke run smoke-ns16-0815: full pipeline OK; parquet carries 18
  endpoints including EPP :9090 with the kv-cache index series.
- Tier fleets at kv-offloading-size=500 (patches to 375/650 at S3).

## S1 (22:40 PDT 08-14 - 05:15 PDT 08-15): replication block, all
## precise-prefix-cache

Bases created within 7 s of each other; surges fired at t+62.

### ppc-n16-lh040-r2 (16x, 0.040 + 0.50 surge) - RELAPSE (n=3)

- Warm h 92-96 at realized 3.97 req/s (1.98 per-8x-eq, in band).
- Post-cancel partial re-warm h 0.88-0.90 (t=110-125) with the
  excess-KV signature (kv 0.68 -> 0.83 while shard-a2 sat at
  0.55-0.59), collapse by t=150, absorbing tail: h 0.03, KV 92%,
  wait 376 at run end. Third consecutive 16x relapse; onset and
  shape match the two 08-12/08-13 draws.

### ppc-shard-a2-020 (8x, 0.020 + 0.25) - CLEAN RECOVERY

- Warm realized 1.78 req/s. Post-cancel h 0.92-0.94, wait 0-2, KV
  45-72% to run end. No organic collapse through min 290. Shard
  clean-recovery draws now n=2.

### ppc-shard-b2-020 (8x, 0.020 + 0.25) - RELAPSE at ~min 130-150

- Warm realized 1.62 req/s (in band; guard passes, the draw counts).
- Digested the perturbation (h 0.90-0.91, wait ~1 at t=110-115; note
  kv 0.67-0.73, shallower drain than a2), then decayed: h 0.41 at
  t=150, cold by t=200, absorbing tail wait 205 at end.
- 8x-0.020 outcome tally across all draws (edge020, shard-a,
  shard-a2, shard-b2): {clean x2, organic collapse at min 240 x1,
  relapse at min ~150 x1}. The point is BIMODAL on 300-min horizons
  with collapse probability ~2/4, closer to the refitted DES
  (4/5 collapse, bimodal) than the earlier "shards recover" reading.
  Result-10's framing shifts from binary recover-vs-relapse to
  collapse probability and onset time vs N; the 16x remains 3/3
  early-hard.

### EPP coordination-layer measurements (first light)

Per-router KV-block index rates: shards ~1.0-1.6k admissions/s (+
equal evictions); 16x peaks 3.3k adm/s at catch-up = exactly 2x
shard volume, tracking demand with no plateau. Event-pool queue
depth ~0 in every window of every run (including through the 16x
relapse). EPP CPU: 1.9 cores at 16x catch-up vs ~1.1 (shards), no
CPU limit set (request 4). Index lookup means 0.4-0.9 ms everywhere.
Scheduler e2e ~0.1 ms. Per-plugin: token-producer (remote
tokenization on serving pods) 230-273 ms per request UNIFORMLY -
slow in all runs, including the healthy shard, so not the N-
discriminator on these window means.

VERDICT: every directly measured coordinator resource is unsaturated
during a reproducing 16x relapse. The C_W term's literal reading
(event-processing capacity) is NOT supported. Live interpretations:
(a) FAULT COUPLING - a collapse seeds locally (per-draw, as in
shard-b2) and the single wide router spreads the cold catch-up flux
onto warm pods (the measured staggered 3->11->16 pinning cascade),
while sharding contains the failure to one bulkhead (shard-b2 died,
shard-a2 unaffected); (b) sub-window staleness dynamics invisible in
5-min counter diffs. S2's approx arm discriminates config-dependence:
approx routing uses neither KV events nor the token-producer.

## S2 (launched ~05:30 PDT): ablation block

    apx-n16-lh040     ns16@16x 0.040, EPP ConfigMap
                      no-offloading-tp4-epp-baseline (approx; no
                      KV-event pipeline, no token-producer)
    lo-shard-a-020    shard-a 0.020, ConfigMap ...-load-only (no
                      affinity signal at all)
    ppc-shard-b3-020  shard-b 0.020, precise (bimodality draw n=5)

Decision rules:
- apx 16x RELAPSES -> the 16x fragility is config-independent ->
  coupling/containment is the leading mechanism; S4's 16x arm goes
  to the edge bracket (0.034 precise).
- apx 16x RECOVERS -> the precise pipeline is implicated (staleness/
  quality under churn, not throughput); S4 repeats the approx draw
  for n=2 before any claim.
- lo-shard-a relapses or degrades warm (h floor well below 0.9
  pre-surge) -> affinity necessity quantified at the boundary;
  either way connects to the customer-escalation routing story.

### lo-shard-a-020 (8x, 0.020, LOAD-ONLY config) - degraded warm
### state, absorbing collapse, no recovery

- Warm h 0.53 (precise draws: 0.94) at realized 1.42 req/s; wait 3-6
  and TTFT p50 2-4 s already pre-surge - without an affinity signal
  the warm equilibrium loses most of its margin.
- Surge -> KV pins by t=115, cold by t=150, absorbing tail (end
  wait 215, TTFT p50 177 s). No recovery phase at all.
- AFFINITY NECESSITY CONFIRMED at the boundary: routing quality is
  load-bearing for both the warm margin and post-perturbation
  recovery (the customer-escalation claim, now measured directly).

### ppc-shard-b3-020 (8x, 0.020, precise) - RELAPSE at ~min 130

- Warm h 0.945 at realized 2.03 req/s (hot end, in band). Weak
  re-warm (h 0.86 at t=110, kv 0.79 -> 0.87), collapse by t=130,
  absorbing tail (end wait 207).
- 8x-0.020 precise tally across all draws (edge020, shard-a,
  shard-a2, shard-b2, shard-b3): collapse-by-300-min 3/5, clean 2/5.
  The refitted DES predicted 4/5. The strong-form binary N-claim
  (16x relapses where 8x recovers) is DEAD; the defensible form is
  collapse probability and containment: 16x 3/3 early-hard and
  always fleet-total; 8x bimodal, and in the sharded system every
  mixed outcome left one shard serving (bulkhead value statement).
- DRAIN-DEPTH COVARIATE (new, both fleet sizes): every relapsing
  draw shows shallow post-cancel KV drain (kv at t=115: b2 0.73,
  b3 0.87, 16x-r2 0.79-0.83, 16x-lh040 0.80) while every clean draw
  drained deep (a2 0.59, shard-a 0.61, edge020 0.62). The
  drain-vs-catch-up race decides the branch; N appears to shift its
  odds. Candidate paper framing: collapse probability rises with
  router span at matched per-capacity load, with drain depth as the
  measured mediating variable.
- WATCH ITEM: shard-b namespace is 2/2 relapses, shard-a 2/2 clean
  (p ~ 6% under symmetric chance). Placement check: both shards
  spread over the same zone (us-central1-b), machine type, and the
  same instance-group families with no systematic asymmetry - no
  topology explanation found; treated as draw variance unless the
  pattern extends.

### apx-n16-lh040 (16x, 0.040, BASELINE/APPROX config) - RELAPSE;
### 16x fragility is CONFIG-INDEPENDENT

- Warm h 0.95 at realized 2.20 per-8x-eq (hot end, in band). Weak
  re-warm (h 0.85 at t=110, kv 0.72 -> 0.86-0.88: the shallow-drain
  signature), collapse by t=130-150, absorbing tail (end wait 397).
- Decision rule fired: the relapse persists WITHOUT the KV-event
  pipeline and WITHOUT the token-producer. Combined with the
  unsaturated-coordinator measurements (S1), the mechanism reading
  settles on ROUTER-SPAN COUPLING: collapse seeds stochastically in
  the drain-vs-catch-up race; a wide router spreads it fleet-total
  (16x now 4/4 collapse across configs and days) while sharding
  contains it. S4's 16x arm goes to the edge bracket per plan.

## S3 (launched ~10:45-12:30 PDT): tier bracket + draws

    cpuofl-a4-375-lh   tier-a@8x size 375, 0.022 + 0.25 (cold-
                       boundary bracket; TIER_EFF predicts near the
                       cold-persistence boundary)
    cpuofl-500-bimod5  tier-b@8x size 500, 0.022 + 0.25 (bimodality
                       draw n=5; RESCOPED, see below)
    ppc-edge020-r2     ns16@8x, 0.020 + 0.25 precise (organic/
                       bimodality draw n=6)
    ppc-bimod4-017     shard-a, 0.017 + 0.25 precise, 180 min (DES
                       tail draw n=4)

- INFRA: tier-b at kv-offloading-size=650 failed to boot: all 8
  pods CrashLooped with the gcsfuse sidecar dying silently right
  after mount (external OOM kill) and vllm then failing on the dead
  mount (Errno 107). 500 boots reliably on identical pods (vllm
  memory request 620Gi, node allocatable ~858Gi; 650 GB pinned tier
  + gcsfuse unlimited file cache does not fit). Partial answer to
  the units question: the setting is RAM-backed at GB scale, and
  the practical envelope on these hosts ends between 500 and 650.
  The 650 probe is descoped this window (a ~600 attempt is possible
  as an S5 filler only after node-memory accounting during the 375
  run clears it); tier-b's slot re-scoped to the tier-500 draw.

### S3 verdicts

ppc-bimod4-017 (0.017, 180 min) - CLEAN RECOVERY (n=4, 4/4
recoveries; the recalibrated DES 0/5-relapse placement holds). Deep
drain at re-warm (kv 0.51-0.62), end h 0.93, wait ~1. Warm realized
1.28 req/s.

ppc-edge020-r2 (8x-0.020, 300 min) - perturbation recovery with
DEEP drain (kv 0.60-0.66 at t=110-115), held h 0.87-0.93 to t=150,
then ORGANIC decay: h 0.53 at t=200, cold by t=240, wait 180 at
end. Warm realized 1.65. The 0.020 ledger over 6 draws now has
three outcome classes: clean x2 (shard-a, shard-a2), organic-late
x2 (edge020, edge020-r2), fast-relapse x2 (shard-b2, shard-b3).
Covariate refinement: shallow drain at t=115 (kv >= 0.73) ->
fast relapse; deep drain -> clean or organic-late.

cpuofl-a4-375-lh (8x tier 375, 0.022) - FULL HEAL (h 0.94-0.96
throughout, ext peaks 0.76, drains back to 0.06, KV 0.25 and wait 0
at end; realized 1.61, in band). SURPRISE vs TIER_EFF = 0.5 (which
placed 375 near the cold boundary) and vs the tier-500 record
(3 congested / 1 healed): the size series 250-cold / 375-heal /
500-mostly-congested is NON-MONOTONE at n=1 -> the 0.022 tier point
is a bimodal band in which single draws cannot order sizes;
TIER_EFF = 0.5 is contradicted at 375 and needs re-examination
together with the heal-branch failure (the model currently heals
nothing at 0.022, so it cannot represent this outcome class at
all). 375 repeat queued for the next window; empirical sizing
statement stands only as: 250 falls through to cold, >= 375 does
not go cold in any observed draw.

## S4 (launched ~14:50-15:50 PDT)

    ppc-n16-edge034          ns16@16x, 0.034 + 0.50 surge, 300 min
                             (edge bracket: relapse at 0.040 is
                             4/4; 8x edge x2 = (0.040, 0.044))
    cpuofl4x-falsifier-300m  tier-a@4x size 500, 0.011 + 0.125,
                             300 min (DES predicts wait 52-160 at
                             270-295; ~0 falsifies the heal-branch
                             pessimism at 4x)
    ppc-shard-a3-020         0.020 draw n=7 (launched 13:15)
    ppc-shard-b4-020         0.020 draw n=8 (launched 15:30)

### S4 verdicts (collected 18:50-21:35)

ppc-shard-b4-020 - CLEAN (deep drain kv 0.62 at t=115; one grazing
episode at t=240 absorbed). Realized 1.94. The 0.020 ledger over 8
draws: clean x3, organic-late x2, fast x3 (collapse 5/8 by 300 min;
the refitted DES said 4/5). Drain-depth covariate 8/8 at kv(t=115)
~ 0.7.

ppc-n16-edge034 - RECOVERED (end h 0.95, wait 1; grazing episode at
t=150 absorbed; realized 1.88 per-8x-eq). With relapse 4/4 at
0.040, the single-router 16x edge sits in (0.034, 0.040) - at
least ~15% below per-capacity scaling of the 8x band (x2 =
(0.040, 0.044)). The point survived kv 0.74 at t=115: the
fast-relapse drain threshold is RATE-DEPENDENT (at lower
per-capacity load the catch-up race is winnable from a shallower
drain), not a universal constant.

cpuofl4x-falsifier-300m - STABLE at the full 300-min horizon (wait
0.1-1.5 throughout, h 0.93-0.96, full drain by t=200; late organic
deepening absorbed through the tier, ext back to 0.71 at t=290 with
wait 1.3). DES predicted wait 52-160: the heal-branch pessimism is
FALSIFIED at 300 min. The 4x point is genuinely stable; open
question 5 closes on the measured side.

## S5 (launched ~21:45 PDT): edge sharpening + 375 repeat

    ppc-n16-edge037   ns16@16x, 0.037 + 0.50 surge, 300 min
                      (narrows the (0.034, 0.040) bracket)
    cpuofl-a4-375-r2  tier-a@8x size 375, 0.022 + 0.25, 300 min
                      (n=2 on the surprise heal; tests the bimodal-
                      band reading vs a real size effect)

shard-a/b and tier-b scaled to 0 after their last collections;
concurrent replicas 24 (within the 32-host grant).

### S5 verdicts (collected ~03:00 PDT 08-16)

ppc-n16-edge037 - RECOVERED (end h 0.93, wait 2; grazing at t=150
kv 0.80 absorbed; realized 1.99 per-8x-eq). 16x hard-relapse edge
narrows to (0.037, 0.040). At matched per-capacity 0.020-eq points
the probability contrast stands at 16x 4/4 collapse vs 8x 5/8.

cpuofl-a4-375-r2 - HEALED AGAIN (2/2 at 375), on a HOT draw
(realized 2.02, hotter than bimod5's congested 500 draw at 2.16's
class boundary). Long restore simmer (ext 0.84-0.85, kv 0.87-0.90
at t=150-200), full drain-back by t=270. The realized-rate
covariate cannot explain 375-vs-500; a real size effect is live.
Candidate mechanism for the modeling pass: a smaller tier churns
stale surge content out faster (shorter tier window), so
post-cancel restores serve live state and drain-back completes; a
larger tier drags stale prefixes and sustains congestion. Tier
ledger at 8x-0.022: 250 cold 1/1; 375 healed 2/2; 500 healed 1/5.

## S6 (launched ~03:45 PDT, final full slot)

    ppc-n16-edge037-r2   edge point n=2 (the bracket claim
                         currently rests on n=1 per point)
    cpuofl-500-bimod6    tier-500 0.022 draw n=6 (sharpens the
                         375-vs-500 contrast)

### S6 verdicts (collected 08:50-09:35 PDT)

ppc-n16-edge037-r2 - RELAPSE (realized 1.84 per-8x-eq; kv 0.65 at
t=115 - BELOW the 8x fast-relapse threshold, decay from t=150, cold
by t=200, wait 189). 0.037 is 1/2: the point is BIMODAL. The 16x
structure mirrors the 8x band shifted down: 0.034 recover (1/1),
0.037 bimodal (1/2), 0.040 relapse (4/4) = per-8x-eq 0.017 / 0.0185
/ 0.020, vs the 8x ladder 0.017 recover 4/4, 0.020 bimodal 5/8
collapse, 0.022 relapse 3/3. Claim form: the collapse-probability
curve shifts left ~5-10% in per-capacity rate and steepens with
router span. The drain-depth covariate's threshold is
rate-and-N-dependent (a correlate, not a law).

cpuofl-500-bimod6 - HEALED (end h 0.96, wait 0, drain-back;
realized 1.72). Tier-500 ledger: {4 congested, 2 healed} of 6;
375: {2 healed} of 2. The 375-vs-500 contrast weakens (2/2 vs 2/6);
both the bimodal-band-everywhere and mild-size-effect readings
remain open. Report outcomes with realized-rate covariates.

## Window summary (19 protocol runs + 19 surge doses, zero data
## losses, zero export hangs)

    S1  ppc-n16-lh040-r2      16x-0.040        RELAPSE (n=3)
        ppc-shard-a2-020      8x-0.020         clean
        ppc-shard-b2-020      8x-0.020         fast relapse
    S2  apx-n16-lh040         16x-0.040 approx RELAPSE (config-indep)
        lo-shard-a-020        8x-0.020 loadonly warm-degraded, collapse
        ppc-shard-b3-020      8x-0.020         fast relapse
    S3  cpuofl-a4-375-lh      tier 375         HEALED
        cpuofl-500-bimod5     tier 500         congested
        ppc-edge020-r2        8x-0.020         organic collapse
        ppc-bimod4-017        8x-0.017         clean (4/4)
    S4  ppc-n16-edge034       16x-0.034        recovered
        cpuofl4x-falsifier-300m 4x-0.011 300m  STABLE (DES falsified)
        ppc-shard-a3-020      8x-0.020         fast relapse
        ppc-shard-b4-020      8x-0.020         clean
    S5  ppc-n16-edge037       16x-0.037        recovered
        cpuofl-a4-375-r2      tier 375         HEALED (2/2)
    S6  ppc-n16-edge037-r2    16x-0.037        RELAPSE (0.037 bimodal)
        cpuofl-500-bimod6     tier 500         HEALED (2/6)
    (+ smoke-ns16-0815)

Headlines: (1) 16x fragility is config-independent and the
collapse-probability curve shifts left with router span (bimodal
band 0.037-eq vs 8x 0.020); sharding contains failures to one
bulkhead in every mixed draw. (2) Every directly measured
coordinator resource is unsaturated during relapses - the C_W
freeze term needs replacement by span-coupling/drain-race
mechanics. (3) Affinity necessity measured (load-only: warm h 0.53,
unconditional collapse). (4) 4x genuinely stable at 300 min - DES
heal branch falsified. (5) Tier outcomes at 0.022 form a bimodal
band across sizes 375-500 with 250 cold; kv-offloading-size is
RAM-backed GB-scale with a boot envelope ending in (500, 650).
(6) Drain-depth at t=115 mediates fast-relapse-vs-survival within a
rate/N class. EPP metrics scraped on every run (first dataset of
its kind here). All fleets scaled to 0 by 09:40 PDT 08-16, ahead of
the 16:45 deadline; CronJob + local backstop remain armed
(idempotent).
    cpuofl-500-bimod5        still running from S3 (collects
                             ~15:40; tier-500 0.022 draw n=5)

### ppc-shard-a3-020 verdict (collected 18:50): FAST RELAPSE

Hottest 0.020 draw yet (warm realized 2.32, band top). Shallow drain
(kv 0.75 at t=115), collapse by t=150, absorbing tail (wait 243).
The 0.020 ledger over 7 draws: clean x2, organic-late x2, fast x3.
The drain-depth covariate separates all 7 at a threshold kv(t=115)
~ 0.7 (fast: 0.73/0.75/0.87; non-fast: 0.59/0.62/0.66 + shard-a).
Realized rate does NOT order outcomes (b2 relapsed at 1.62 while a2
stayed clean at 1.78). The shard-a-vs-b namespace split is broken
(shard-a produced this relapse): draw variance confirmed.

### cpuofl-500-bimod5 verdict (collected 15:45): restore-bound
### CONGESTION

h 0.70-0.75, ext 0.62-0.73, KV pinned 0.93-0.94, wait diverging to
~175 - the classic third regime. Tier-500 at 0.022: {4 congested,
1 healed} across draws. ANALYSIS NOTE (for the paper pass): today's
congested draw ran hot (warm realized 2.16 req/s) while both heals
ran cool (a4full-lh and the 375 draw at ~1.6); check realized rate
vs outcome across ALL 0.022 tier draws - part of the "bimodal band"
may be realized-rate variance rather than intrinsic bistability,
which would sharpen the sizing story and partially rehabilitate the
capacity model. tier-b scaled to 0 after collection (back toward
the 32-host budget; 36 concurrent until shard-a3 ends ~18:30, then
28).
