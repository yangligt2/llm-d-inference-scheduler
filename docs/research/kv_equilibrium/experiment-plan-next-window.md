# Hardware queue: next capacity window

Written 2026-08-14 after the GPU-free pass (per-pod spread analysis,
coordination-layer and tier-capacity refits). Assumes the standard
protocol unless stated: 300 min, salted, cap 10.5, surge =
eviction-scale dose at base t ~ +62 min cancelled at +107, EPP
precise-prefix-cache family, all comparability factors recorded per
experiment-env.md.

## Window-start checklist (before any run)

1. Schedule the unconditional T-minus-15-min scale-down of every
   vllm deployment (HARD RULE, experiment-env.md). Collection beats
   the deadline or the run is lost; the namespaces survive.
2. NOTHING is deployed. Rebuild from blueprints:
   namespace-request-shards.md (no-offload stacks),
   namespace-request-4x-tier.md (tier stacks). The igw-llm-d
   namespace was shared and was destroyed in the 08-13 reclaim -
   flag the loss to its owners BEFORE rebuilding under that name.
3. USER/ADMIN actions per namespace: GCS bucket principalSet IAM
   grant (pod bounce may be needed after propagation), zone-pinned
   bench-assets seed. Propose exact commands and wait.
4. Launch gates on readyReplicas polls only; surge chains keyed on
   the base JOB's existence; leave export margin (a hung export means
   zero data - check "records processed" in aiperf logs before
   trusting a run exists).
5. NEW - EPP metrics scrape: add the EPP pod's metrics endpoint to
   SERVER_METRICS_URLS in every bench config this window. The
   deployed config already sets kvBlockIndexConfig.enableMetrics:
   true; the index/queue metrics were never collected, and they are
   the direct measurement of coordinator saturation (C_W). Verify
   the metric names on the rebuilt stack before the first long run.

## Prioritized queue

P1. Coordinator-saturation discrimination (open question 1).
    EPP config provenance: the only configs ever deployed are in
    guides/agentic-serving-tp/epp-configs - baseline.yaml (approx
    prefix routing: queue-scorer + kv-cache-utilization-scorer +
    prefix-cache-scorer on the routing-history producer +
    no-hit-lru-scorer; no KV events; = the pristine
    no-offloading-tp4-epp and the July run era) and
    precise-prefix-cache.yaml (live since 08-08). The flow-control
    variants are EXCLUDED from this experiment series (known feature
    bug; see flow-control-investigation-2026-08-05.md).
    a. EPP metrics scrape on every run (zero marginal cost; decisive
       if the index queue/lag saturates exactly during the 16x
       catch-up churn).
    b. 16x-0.040 + 0.50 surge under the baseline (approx-prefix)
       config - proven config, no KV-event pipeline. Model reading:
       if the relapse disappears, the saturating resource is in the
       KV-event/index path; if it persists, tokenization/scoring or
       affinity quality itself.
    c. 8x-0.020 + 0.25 surge under a LOAD-ONLY config. This variant
       does NOT exist yet and has never produced data: it is
       baseline.yaml with the prefix scorer (and its producer) and
       no-hit-lru-scorer removed, leaving queue-scorer +
       kv-cache-utilization-scorer - no affinity signal at all.
       Both plugin types already run in the deployed baseline, so
       the variant is one new yaml deployed via swap-epp-config.sh,
       but it MUST be smoke-validated at bring-up (a rejected
       config leaves zero ready EPP replicas under strategy:
       Recreate). Purpose: tests whether affinity is necessary for
       recovery at the boundary (customer-escalation routing
       story). If the new variant is not wanted, the fallback S2
       arm is a baseline (approx) draw at 8x-0.020, which uses only
       proven configs and still contrasts affinity mechanisms at
       the boundary.
    Needs 16 + 8 hosts, full horizon each.

P2. Second shard draw (n=2 for result 10): two fresh 8x namespaces,
    0.020 + 0.25 each, same day as a 16x repeat if capacity allows.
    Refitted-model prediction: each shard behaves as an independent
    8x-0.020 system (no coordinator saturation; per-shard write rate
    77-135k tok/s < C_W).

P3. Tier-size bracket at 8x-0.022 (result 11 threshold): sizes 375
    and 650, 300 min. Refitted-model differential prediction
    (TIER_EFF = 0.5): 375 (0.47M tok/pod effective) sits near the
    cold-persistence boundary - cold-or-congested bimodal outcome;
    650 (0.82M effective) congested, never cold. A 375 draw that
    cleanly heals, or a 650 cold collapse, falsifies the refit. 650
    also probes the kv-offloading-size units question.

P4. 300-min 4x-0.011 tier repeat (the heal-side falsifier): DES
    predicts wait 52-160 at 270-295 min; ~0 means the 4x point is
    genuinely stable at that horizon and the DES heal-branch
    pessimism extends to 4x.

P5. Cheap bimodality draws whenever a fleet idles: tier-500 at 0.022
    (3 congested / 1 healed so far), no-offload 0.020 (organic
    collapse 1/2), no-offload 0.017 (3/0 vs the DES tail).

## Window plan: 32 hosts x 42 hours

Geometry: 1 host = 1 TP4 replica. One router (EPP) per namespace, so
one experiment per namespace at a time; parallelism comes from
running several namespaces concurrently within the 32-host budget.
Slot length 6 h = 300-min run + launch/collection/reconfig margin.
Six slots fit after bring-up, with a terminal buffer.

Namespaces (5, all rebuilt from blueprints):

    ns16       no-offload, scalable 8 <-> 16 replicas; carries the
               precise and baseline (approx) ConfigMap variants for
               config swaps
    shard-a/b  no-offload, 8 replicas each; shard-a also carries the
               NEW load-only ConfigMap variant (P1c; smoke-validate
               at bring-up before any long run)
    tier-a     tier stack, scalable 4 <-> 8; kv-offloading-size
               patchable (375 / 500)
    tier-b     tier stack, 8 replicas; kv-offloading-size 650 / 500

Timeline (T = window start):

    T+0:00          Schedule the unconditional scale-down for
                    T+41:45 FIRST. Then bring-up: namespaces, IAM
                    grants (user), bench-assets seeds, ConfigMap
                    variants, smoke runs, EPP-metrics scrape
                    verification on every stack.
    T+3:00  S1      Replication block (32 = 16+8+8)
    T+9:00  S2      Ablation block (32 = 16+8+8)
    T+15:00 S3      Tier bracket block (32 = 8+8+8+8)
    T+21:00 S4      Falsifier + decision block (28 = 4+8+16; 4 spare)
    T+27:00 S5      Edge bracket + statistics (32 = 16+8+8)
    T+33:00 S6      Contingency / repair slot (composition decided
                    at T+30 review)
    T+39:00         Straggler collection only; nothing launches
                    after T+36:45 (every run must collect before
                    T+41:45).

Slot contents (all runs 300 min, standard surge, EPP metrics scraped
everywhere):

    S1  ns16@16x    0.040 precise        16x relapse n=3, same-day
                                         control for S2
        shard-a     0.020 precise        second shard draw (P2)
        shard-b     0.020 precise        shard n=3; each shard also
                                         an organic-collapse draw
    S2  ns16@16x    0.040 baseline (approx)  P1b: no KV-event pipeline
        shard-a     0.020 LOAD-ONLY      P1c: affinity necessity (new
                                         variant; fallback = baseline
                                         approx at 0.020)
        shard-b     0.020 precise        organic-collapse draw
    S3  tier-a@8x   0.022, size 375      P3 bracket, cold-boundary
        tier-b@8x   0.022, size 650      P3 bracket, units probe
        ns16@8x     0.020 precise        organic-collapse draw
        shard-a     0.017 precise        bimodality draw (DES tail)
    S4  tier-a@4x   0.011, size 500      P4: 300-min falsifier (DES
                                         wait 52-160 vs ~0)
        tier-b@8x   0.022, size 500      tier-500 bimodality n=5
        ns16@16x    DECISION ARM:
                    S2 approx RECOVERED -> repeat 0.040 approx (the
                    ablation verdict must not rest on one draw);
                    S2 approx RELAPSED  -> 0.034 precise (start the
                    16x edge bracket instead)
    S5  ns16@16x    0.034 or 0.037 precise  16x collapse-edge
                    bracket: quantifies the single-router
                    coordination penalty as a per-capacity rate
                    shift (8x edge x2 = (0.040, 0.044); relapse AT
                    0.040 means the 16x edge sits below it)
        tier-a@8x   0.020, size 500      second draw of the 0.020
                                         tier arm (result 5 pair)
        shard-b     0.020 precise        organic-collapse draw
    S6  reserved: re-runs flagged by the draw-variance guard or
        lost to export hangs take absolute priority; otherwise the
        second 16x edge point, a 0.017 draw, and a tier-500 0.022
        draw.

Any run whose realized req/s falls outside the per-capacity band of
its comparators is flagged and excluded from paired claims; the pair
re-runs in S6 rather than being argued around.

## Evidence closure for the paper

What this window adds per claim (research-status result numbers):

    R10 coordination layer   shard n=1 -> n=3 with a same-day 16x
                             control; ablation (approx, load-only)
                             plus EPP-side saturation metrics turn
                             the mechanism claim from inferential to
                             direct
    R3  organic collapse     0.020 draws 2 -> ~5-6; the
                             horizon-dependence claim gets a rate,
                             not an anecdote
    R11 tier capacity        2 sizes -> 4; the 375/650 bracket tests
                             the TIER_EFF differential prediction
                             and yields a sizing rule
    R5  tier heal at 0.020   n=1 per side -> n=2 (S5 tier arm)
    R6  16x fragility        relapse n=2 -> n=3 plus an edge
                             bracket: the coordination penalty
                             becomes quantitative
    Models                   all three standing falsifiers execute
                             (4x 300-min, 375/650, 16x edge)

Acceptable to leave open (stated as future work): which coordinator
resource saturates if the EPP metrics are ambiguous; the heal-branch
model failure; the kv-offloading-size units question beyond what the
650 point settles.
