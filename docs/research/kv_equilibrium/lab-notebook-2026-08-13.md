# Lab notebook 2026-08-13: N-mechanism + tier-size window (64 hosts, 09:50-18:00 PDT)

Context: research-status.md (written this morning) is the consolidated
state. Today attacks open questions 1-3: the N-dependence mechanism,
the tier size-vs-bandwidth question, and the two n=1 replications
(organic collapse, 16x relapse). All runs 300 min, salted, cap 10.5,
surge = eviction-scale dose at base t ~ +64 min, EPP
precise-prefix-cache family everywhere.

## Experiments (56 of 64 hosts; 8 spare for failures)

Block N (32 hosts) - coordination-layer test, three fleets in
parallel with per-capacity-matched load:

    W1  igw-llm-d @ 16 replicas   0.040 sps + 0.50 x 2700 s surge
        16x long-horizon: confirms/denies yesterday's truncated 16x
        relapse at full horizon (relapse n=2 if it repeats).
    W2a NEW ns yangligt-shard-a @ 8 replicas   0.020 + 0.25 surge
    W2b NEW ns yangligt-shard-b @ 8 replicas   0.020 + 0.25 surge
        Together: same pods (16), same total load and surge dose as
        W1, but coordination SHARDED across two independent routers.
        Each shard is also an independent 8x-0.020 300-min draw
        (organic-collapse replication for result 3).

Block T (16 hosts) - tier size pair, same-day draws:

    W3  yangligt @ 8 replicas, kv-offloading-size=250   0.022 + 0.25
    W4  yangligt-4x @ 8 replicas, kv-offloading-size=500  0.022 + 0.25
        Full-length A4: half vs full tier at the congestion point.
        W4 doubles as 8x-0.022 tier congestion draw n=4.

Surge chains today key on the base JOB's existence (not gate
release) to avoid the 08-12 A4 timing truncation.

## Analysis method (per run, standard; plus joint analyses)

Per run: windowed arc (analyze_run_windows.py / offload variant with
ext_hit), realized req/s and requests/session (draw-variance guard),
outcome class at 270-295 min (cold collapse / congested / recovered /
healed), wait-growth slope in the final hour.

Joint N-block analysis:
- Primary contrast: W1 vs (W2a + W2b aggregated) at matched relative
  times. Identical per-capacity everything; only router span differs.
- Per-pod spread: per-pod h and query share per fleet (extract from
  parquet per endpoint) - the routing-quality proxy. Compare spread
  vs N across 4x/8x/16x arcs (yesterday's + today's), GPU-free during
  the runs.

Joint T-block analysis: h floor, ext_hit share, wait-growth slope,
time-to-congestion at 250 vs 500. Both fleets same geometry, same
lambda, same day.

## Decision rules (what the next experiments are, per outcome)

N-block:
- W1 relapses AND both shards recover -> coordination-layer mechanism
  CONFIRMED. Next: (a) routing ablation at 8x (approx-prefix or
  random EPP config) to identify WHICH coordination property; (b)
  per-pod imbalance metrics into the model as an N-term; (c) paper
  claim upgraded.
- W1 recovers -> yesterday's 16x was draw variance; N-claim demoted
  to suggestive; next window = 16x repeats (2-3 draws) before
  anything else.
- Shards also relapse -> not coordination; check realized rates
  (hot draws?) and revisit; N-claim needs load-matched repeats.
- Either shard organically collapses ~min 240 -> result 3 replicated
  (n>=2); if BOTH stay clean past min 260, the organic collapse at
  0.020 was itself a draw - schedule 0.020 draws.

T-block:
- 250 ~= 500 (same congestion class, similar wait slope, h floor
  within ~5 pts) -> capacity-indifference CONFIRMED; sizing rule is
  bandwidth-based; 650 probe only for the units question; model
  unchanged.
- 250 clearly worse (cold collapse or h floor < 50%) -> capacity
  binds below ~1x working set; model needs a tier-capacity term;
  schedule 650 and an intermediate size next window.
- Either heals -> third-regime robustness weakened; more 0.022 tier
  draws before the mitigation chapter is written.

Cross-cutting: any run whose realized req/s falls outside the
per-capacity band of its comparators is flagged and excluded from
paired claims (draw-variance guard); the pair is then re-run next
window rather than argued around.

## Infra log

- 09:55 scaled igw->16, yangligt->8 (size 250), yangligt-4x->8
  (size 500).
- Shard namespaces renamed yangligt-shard-a/b (owner prefix); user
  creates them from namespace-request-shards.md (blueprint igw-llm-d,
  8 vllm replicas each, IAM + zone-pinned bench-assets per the doc).
  I take over at readyReplicas 8/8. Fallback if not ready by 12:15:
  run shard-a only; if neither, defer the shard arm and keep W1.

## Run log

### W3 cpuofl-a4half-lh (8x, tier 250, 0.022, 300 min) - CAPACITY
### BINDS: congestion decays into COLD COLLAPSE at half tier

- Warm base h ~91%; surge saturates (wait 769). Post-cancel: enters
  restore-bound congestion (min 120-170: h 62-79%, ext_hit 58-68% -
  indistinguishable from full-tier draws), then DEGRADES THROUGH it:
  h 53 -> 38 -> 25 -> 10 -> 3-7% (min 180-300), ext_hit collapses to
  ~1% (working set no longer fits the half tier), KV pinned 92%,
  wait 276 at run end - the cold absorbing state.
- Model falsified at half size (ccpu sweep said congested with h
  0.85-0.95). Refined mechanism: restore BANDWIDTH sets congested
  throughput; tier CAPACITY determines whether the congested regime
  is sustained (500) or transient en route to cold collapse (250).
- Decision rule fired: capacity term needed in the tier model;
  schedule 650 + an intermediate size next window. W4 (500,
  same-day) completes the pair.

### W4 cpuofl-a4full-lh (8x, tier 500, 0.022, 300 min) - HEALED;
### tier-500 at 0.022 is itself bimodal

- Same surge saturation; post-cancel quick recovery (h 94.8 at min
  120), long restore-assisted simmer (h 91-94%, ext 15-53%, wait
  1-3), one grazing episode absorbed (min 220-230: ext 71-72%, KV
  92.5%, wait 13), then full drain-down: ext 0%, KV 4.6%, h 97.3% at
  run end.
- Against the three prior congested draws at identical settings
  (a1, a1rep, lh-tier), 8x-0.022 tier-500 outcomes are now
  {congested x3, healed x1} - the tier fleet sits near its own
  boundary at 0.022 (the restore model's congested-5/5 there is
  slightly pessimistic; its 0.020-bimodal placement was close).
- T-BLOCK PAIR VERDICT (same-day): 250 -> cold collapse; 500 ->
  healed. Size effect unambiguous in direction and large; every
  observed 500 draw strictly dominates the 250 outcome. Capacity
  term confirmed necessary; next window: 650 + intermediate (375)
  points to bracket the persistence threshold.

### W1 ppc-n16-lh040 (16x, 0.040, 300 min) - 16x RELAPSE CONFIRMED
### at full horizon (n=2)

- In-surge saturation (wait 1393); post-cancel partial recovery
  (h 78% at min 110-120, wait to 8), then relapse: h 57 -> 30 -> 7
  -> 1-4% by min 150, cold-absorbing for the remaining 2.5 h (KV
  91-92%, wait growing to ~400, TTFT p50 150 s, throughput 2.3-2.9
  req/s = per-capacity ~1.2-1.5 in 8x terms, matching the 8x cold
  state).
- Yesterday's truncated 16x relapse replicated with a full absorbing
  tail. N-block verdict now rests on the shards.

### W2a shard-a-020 (8x, 0.020, 300 min) - CLEAN RECOVERY, no
### organic collapse

- Post-cancel: h 81 -> 89-95%, wait 0-1 from min 120 to run end, KV
  36-62% throughout, no organic collapse through min 290 (contrast:
  Tuesday's single 8x-0.020 draw collapsed organically at min 240 -
  that event is now 1-of-2, draw-dependent). One-window counter-reset
  artifact at min 80 (negative diff), immaterial.

### W2b shard-b-020 - LOST (no data ever reached disk)

- PV rescue executed (Retain patch, claimRef clear, rebind, mount):
  the volume is EMPTY (24K, lost+found only). Combined with the
  lifecycle never observing job completion: aiperf writes ALL
  artifacts at end-of-run export; shard-b's process hung in
  records-processing after its ~15:25 finish and the 18:00 namespace
  deletion killed it pre-export. First such hang in ~40 runs.
- Methodology consequence: a run's data does not exist until export
  completes - deadline planning must include export margin (the
  T-15 scale-down rule already forces this).
- N-block consequence: the verdict rests on W1 + W2a (decision rule
  satisfied); a second shard draw next window makes it n=2.

### INCIDENT: capacity reclaim destroyed all five namespaces at
### window end

The scale-down was left gated on shard-b's collection, which never
fired; at the 18:00 reclaim all five namespaces (igw-llm-d, yangligt,
yangligt-4x, yangligt-shard-a/b) were deleted outright. Data impact:
NONE for W1/W2a/W3/W4 (collected locally by ~16:00). W2b's report
disk was saved by patching its PV to Retain while the PVC was still
Bound (pv pvc-4a5f16ac-aca0-4b77-8fed-c7af332a88d2, phase pending
Released). Recovery once authorized: clear the PV claimRef, bind a
rescue PVC in any namespace, retrieve with a retriever pod, then
restore the PV reclaim policy. Infrastructure impact: all EPPs,
configmaps, and bench-assets must be rebuilt next window from the
blueprint docs (namespace-request-*.md; igw stack needs its own
blueprint doc written from the collected manifests... note: the
igw-llm-d namespace was NOT ours to lose - flag to the user).
Operational rule added to experiment-env.md: unconditional
T-minus-15-min scale-down task scheduled at window START.

## Window summary (2026-08-13)

    W1  16x-0.040 noofl    RELAPSE, full absorbing tail (n=2)
    W2a shard-a 8x-0.020   clean recovery, no organic collapse
    W2b shard-b 8x-0.020   LOST (aiperf hung pre-export; ns deleted)
    W3  tier-250 0.022     congestion decays to COLD COLLAPSE
    W4  tier-500 0.022     HEALED (tier-500 at 0.022 bimodal: 3 cong/1 heal)

N-block verdict (pending shard-b): 16x relapses while a sharded 8x
router over the same pods and load recovers cleanly - the
coordination-layer mechanism is CONFIRMED on the evidence in hand
(decision rule satisfied by W1 + W2a; W2b was lost pre-export - re-run
a second shard draw next window). Next per rules: routing ablation at 8x to identify the
property; N-term for the models.

T-block verdict: tier CAPACITY binds - 250 falls through congestion
to cold collapse while 500 heals, same day, same everything else.
Model needs a tier-capacity term; bracket the persistence threshold
at 375/650 next window.

Also: organic collapse at 8x-0.020 is draw-dependent (1/2, W2b may
make it 1/3); 8x-0.022 tier-500 is bimodal (3 congested / 1 healed).
