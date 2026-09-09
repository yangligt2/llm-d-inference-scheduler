# Lab notebook 2026-08-10 PM: 7-hour window, two 8-replica fleets

Window: ~11:45-18:45 PDT (18:45-01:45 UTC), 16 hosts. Plan source:
experiment-plan-completion.md (cut line: A1, B1, A3, B2, ...).
Operator: Claude (autonomous). Env: experiment-env.md.

Fleets:

- igw-llm-d: no-offloading-tp4 x 8, EPP precise-prefix-cache
  (verify mount at bring-up). Track B.
- yangligt: cpu-offloading-tp4 x 8 (scaled 0 -> 8 at 11:47 PDT;
  --kv-offloading-backend=native --kv-offloading-size=500 UNCHANGED).
  Track A. EPP cpu-offloading-tp4-epp.

kv-offloading-size caution (for A4, NOT exercised today): before any
increase, verify per-host free RAM covers the increment times
replicas-per-host; the configured 500 already exceeds the stated
160 GB physical headroom in units-unclear fashion - treat UP-tuning
as crash-risk until units are confirmed from vllm logs/metrics
(kv_offload metrics exist in the parquet).

## Plan (runs ~in parallel across fleets; all salted, cap 10.5,
## surge = 0.25 sps x 2700 s from 061526 corpus at base t ~ +62 min,
## launched -r false, population cancelled at surge end)

Track B (igw-llm-d, 8x no-offload):

    R1  B1 bimodality draw 2: base 0.017 sps, 9000 s (150 min).
        Outcome classifies by ~min 130 (relapse: KV re-pins, queue
        regrows; recovery: wait 0, h > 0.9). DES: ~1/4 chance of
        relapse per draw.
    R1b CONDITIONAL (only if R1 relapses): B2 recovery-edge probe -
        immediately restart base at 0.012 sps, 3600 s, -r false
        (bench-config-weka-rec-sps012-60m.yaml). Predict recovery;
        measures the recovery edge below the collapse edge.
    R2  B1 bimodality draw 3: same as R1. If R1b consumed the slot
        time, shorten base to 8400 s via sed at launch.

Track A (yangligt, 8x cpu-offload):

    R3  A1 tier arm at centerpiece geometry: base 0.022 sps, 10800 s
        (180 min, mirrors b1a2 exactly). PREDICTION (fluid, DES, B2a):
        in-surge saturation with tier thrash, recovery within ~1
        window of cancellation, NO relapse. Pairs against measured
        n=2 no-offload relapse with zero scaling assumptions.
    R4  DECISION at R3 end:
        - R3 recovers (expected): A3 ladder point 1 - base 0.033 sps
          (1.5x no-offload edge), 9000 s, same surge
          (bench-config-weka-a3-base-sps033-150m.yaml). Question: does
          the tier fleet relapse, or does overload surface as warm
          queueing (model: the latter)?
        - R3 relapses (unexpected, breaks prediction): repeat A1 at
          9000 s to confirm before believing it.

## Timeline (PDT, projected)

    11:47  yangligt scaled 0 -> 8 (model load ~20-30 min)
    ~12:05 igw fleet ready -> launch R1
    ~12:25 yangligt ready -> launch R3
    ~14:45 R1 collected -> decision -> R1b or R2
    ~15:40 R3 collected -> decision -> R4
    ~18:20 R4 collected
    ~18:35 last igw run collected; scale yangligt back if asked
    18:45  capacity ends. Nothing new launches after T-3.5h per run
           length; monitor-only after ~15:45 for track A, ~15:30/16:05
           for track B.

## Run log

### R1 ppc-bimod2 (0.017, draw 2 of the bimodality set) - RECOVERY, grazing

- Profiling 18:50-21:20 UTC. Surge 714-equivalent dose 19:52-20:37
  (own accounting: BIMOD2 SURGE DONE 20:42). In-surge saturation:
  h 1.3-4.1%, KV 94%, wait 779, TTFT p50 313 s.
- Post-cancellation: h 84.6% at +5 min, 89-93% for the final 40 min,
  wait 0-2 throughout, catch-up 3.4-4.5 req/s at KV 72-78% - hot
  grazing like the original b1c draw, no relapse.
- Bimodality tally at 0.017: 2 recoveries / 0 relapses (DES predicts
  ~1/4 relapse per draw; P(no relapse in 2) ~ 0.55 - keep drawing).
- Decision: R2 = draw 3 launched immediately (ppc-bimod3, same
  config); surge chain scheduled t+64 min. R1b recovery probe not
  triggered (no relapse to probe).

### R3 cpuofl-a1-tier022 - PREDICTION FALSIFIED: a THIRD REGIME appears

8x cpu-offload, base 0.022 (realized 1.9-2.5 req/s warm, matching the
b1a2 draws), surge 0.25 x 2700 s (714 sessions). EPP confound checked
and cleared: yangligt mounts the same precise-prefix-cache plugin
family as igw (precise-prefix-cache-producer + prefix-cache-affinity-
filter + token-load-scorer; peakPrefillThroughput 28888).

- Base solo (0-60 min): warm, h 90-96%, ext_hit 0-5%, KV 21-34%.
- Surge (65-105): saturation DEEPER than the no-offload relapse arms
  (waiting 876 vs 745-780). Tier serves hard early (ext_hit 57-60%),
  then exhausts (1-2% by min 90) - same thrash shape as B2a.
- Post-cancel (110-120): the B2a signature appears - restore-driven
  catch-up (ext_hit 42-57%), h back to 90%, waiting to 2.
- THEN (125-175): instead of draining, the fleet settles into a
  TIER-SUSTAINED CONGESTED STATE: h 71-85%, ext_hit pinned 66-77%
  (most hits are CPU restores), KV 92-94%, throughput 2.6-4.2 req/s
  (~2x the no-offload collapsed state), TTFT p50 creeping 3 -> 24 s,
  waiting 7 -> 58 over 50 min. Slow divergence, not stationary.
- Reading: the tier does NOT delete the failure at this operating
  point - it TRANSFORMS it. Cold-prefill collapse (h ~5%, TTFT
  60-190 s) becomes restore-bound congestion (h ~75%, TTFT ~20 s):
  the reservoir's prefixes live in the CPU tier, so catch-up work is
  restores instead of re-prefills, but restore traffic itself churns
  HBM and the drain cannot outpace 0.022 sps arrivals. All three
  models (fluid, DES, B2a extrapolation) predicted clean recovery -
  none model restore bandwidth or the restore-churn feedback.
- Open question vs B2a (4x, same per-capacity point, clean recovery):
  draw variance cannot obviously explain it (realized rates match
  after scaling). Candidate physics: interference and restore-churn
  do not scale linearly with fleet size. The A1 repeat (in flight)
  tests reproducibility first.
- Decision: R4 slot = A1 repeat at 150 min (cpuofl-a1rep, launched
  ~15:20 PDT with surge chain). The 0.033 ladder point is moot if
  0.022 already fails on the tier fleet.

### R2 ppc-bimod3 (0.017, draw 3) - clean RECOVERY

- Profiling 21:31-00:01 UTC. In-surge saturation as always (h 1.2%,
  wait 730). Post-cancel: h 86.3% at +5 min, 91-95% thereafter,
  wait 0, KV 40-52% - noticeably COOLER than draw 2's grazing
  (KV 72-78%): the post-surge reservoir size varies across draws.
- Bimodality tally at 0.017: 3 recoveries / 0 relapses. DES predicts
  ~1/4 relapse per draw; P(0 relapses in 3) ~ 0.42 - not yet in
  tension, but the relapse tail remains unobserved on hardware.
  Future window: 2-3 more draws, or accept the DES tail with the
  hardware spread (48-78% post-surge KV) as supporting evidence.

### R4 cpuofl-a1rep (A1 repeat, 150 min) - third regime REPRODUCES

- Profiling 22:13-00:43 UTC. Same arc: warm base (h 92-95%), deep
  in-surge saturation (wait 794), post-cancel recovery to h 91-92%
  (min 115-120), then the tier-sustained restore-bound state
  (min 125-145: h 83-92%, ext_hit 57-73%, KV 84-94%, wait 2-12).
- Milder than draw 1 at the same relative time (wait 3-12 vs 7-19),
  and the 150-min window ends before draw 1's slow-divergence phase
  (min 150-175). Regime entry: n=2. Divergence tail: still n=1.
- Open for next window: long-horizon tier run (180-300 min) to
  classify the third regime as absorbing, metastable, or slowly
  recovering; and the B2a-vs-A1 scale question.

## Window summary (2026-08-10 PM, 7 h, all collected before cutoff)

    run             fleet          outcome
    ppc-bimod2      8x no-offload  0.017 draw 2: RECOVERY (grazing, KV 72-78)
    ppc-bimod3      8x no-offload  0.017 draw 3: RECOVERY (cool, KV 40-52)
    cpuofl-a1       8x offload     0.022 tier arm: THIRD REGIME - restore-
                                   bound congestion, slow divergence
    cpuofl-a1rep    8x offload     regime reproduces (150-min window)

Take-aways: (1) tier transforms rather than deletes the failure at
the centerpiece point - restore-bound congestion (h ~75-90%, ext_hit
~60-77%, ~2x collapsed throughput, slowly worsening) replaces cold
collapse; all three model layers missed it (no restore bandwidth /
restore-churn feedback) - top modeling item; (2) 0.017 bimodality
tally 3/0 recoveries with large draw-to-draw reservoir spread;
relapse tail still unobserved on hardware. Completion-plan deltas:
A3 ladder is superseded by characterizing the third regime (long-
horizon + tier-size A4 becomes MORE important, since restore-bound
congestion is exactly what tier sizing modulates); A2 unchanged.

Fleets scaled to 0 at window end per user instruction (EPPs left
running).
