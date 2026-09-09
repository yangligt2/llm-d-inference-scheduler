# Handoff: restore-bandwidth modeling of the third regime (GPU-free)

Self-contained work order for a fresh session. Pure local analysis
and simulation; no cluster access. Companion to (and same conventions
as) handoff-des-replication.md, which was executed successfully.

## Context in one paragraph

The CPU-offload tier was predicted (fluid model, DES, and a 4-replica
validation run) to delete the relapse that the no-offload fleet
suffers after an eviction-scale surge. On hardware at the centerpiece
operating point (8 replicas, 0.022 sessions/s, 45-min 0.25 sps surge)
it does NOT: the fleet enters a THIRD REGIME - restore-bound
congestion - reproduced in three runs (cpuofl-a1, cpuofl-a1rep,
cpuofl-lh-tier). Signature: h holds 70-85% with external_prefix_cache
hit share pinned at ~66-79% (most hits are CPU-tier restores), KV
92-94%, throughput ~2.2x the collapsed no-offload fleet, TTFT ~4x
better, but the waiting queue SLOWLY DIVERGES (6 -> 164 over 195 min
in the long-horizon run, with a brief plateau at min 150-170).
Meanwhile the same per-capacity point at 4 replicas (cpuofl-b2a,
0.011 sps, 0.125 surge) recovered CLEANLY - the scale discrepancy is
unexplained. Every model layer missed the third regime because none
prices restores: the fluid tier is an ideal coverage window and the
DES charges restores against a generous uncontended constant. The
task: add restore bandwidth and restore-churn feedback to both model
layers, calibrated from measured offload counters, so that one
parameterization reproduces (a) 4x clean recovery, (b) 8x restore-
bound congestion with slow divergence, (c) the unchanged no-offload
arms - and then predict the tier fleet's stability boundary to aim
the next hardware window.

## Read first (in order)

1. kv_equilibrium/lab-notebook-2026-08-10-pm.md (R3/R4 sections) and
   lab-notebook-2026-08-11.md - the third-regime measurements
2. kv_equilibrium/overlay-findings.md - model state through the DES
   replication
3. kv_equilibrium/overlay_b1_dynamics.py - fluid model to extend
4. kv_equilibrium/des_b1.py, then des.py - DES to extend (note
   des.py's RESTORE_TPS and how/where it is charged)
5. kv_equilibrium/extract_arcs.py - arc extraction to extend

Python: docs/research/.venv; run from docs/research/ as
`.venv/bin/python kv_equilibrium/<script>`. Reports live under
/Users/yangligt/workplaces/llm-d/guides/subslicing/aiperf/reports/.

## Task 1 - data extraction (do this first; everything calibrates from it)

Extend extract_arcs.py:

- Add runs (ALL are 8-replica fleets, pool = POOL_8X, except the old
  cpuofl-b2a-base which stays 4x): ppc-bimod2, ppc-bimod3,
  cpuofl-a1-tier022, cpuofl-a1rep, ppc-lh-noofl, cpuofl-lh-tier.
  Artifact subdirs carry the sps- prefix (qwen3coder-weka1-sps-<run>).
- Add windowed columns from the offload counters (present on the
  yangligt runs): vllm:kv_offload_total_bytes and
  vllm:kv_offload_total_time (cumulative; window-diff them like the
  other counters). Derived: achieved offload bandwidth
  bytes/time per window, and restore token rate. VERIFY UNITS before
  trusting: total_time may be seconds or ms; check plausibility
  against 127 KB/token (fp8 KV constant, validated) and the ext_hit
  token rates. Also confirm whether the counters cover offload
  (GPU->CPU), onboard (CPU->GPU), or both - vLLM native offload may
  expose only one direction; say which in the notes.
- external_prefix_cache_queries/hits are believed to be TOKEN counts
  (B2a early-surge windows show ~38M queries/300 s ~= 127k tok/s,
  matching prefill capacity). Sanity-check once and record.

Key calibration numbers to produce:

    B_r      restore bandwidth per replica, tokens/s (from
             kv_offload counters in the congested windows; the
             des.py placeholder 1e6 tok/s is almost certainly high)
    r_tok    restore token rate in the congested state (~ ext_hits
             tokens/s; expect order 70-90k tok/s fleet at 8x from
             h ~0.75 x prompt rate)

## Task 2 - tpot re-fit: fleet-R vs per-pod-R (the scale-question discriminator)

The interference fit tpot(R) = 9.6e-3 + 3.8e-6 R^2 used FLEET running
count R, calibrated only on 8-replica data. It is not scale-invariant:
at equal per-pod load it predicts 4x more interference at 8 replicas
than at 4. The 4-replica arcs (cpuofl-b2a) provide independent
(running, tpot) points: extract per-window tpot p50 from the jsonl
(request_latency - ttft)/(output_tokens - 1) as in /tmp/tpot.py-style
logic, pair with the windowed running gauge, and fit both forms:

    tpot = a + b * R_fleet^2      vs      tpot = a + b' * (R_fleet/N)^2

If the per-pod form fits both fleets with one (a, b'), the 4x-vs-8x
discrepancy is (at least partly) a calibration artifact and the fluid/
DES B2a runs were simulated with the wrong interference; refit and
rerun the four original arms before adding any new physics, then
re-evaluate what remains unexplained. Report this explicitly - it
changes how the scale question is framed in the paper.

## Task 3 - fluid model extension (overlay_b1_dynamics.py or a sibling)

Add to the tier path:

1. Restore bandwidth: restores are a contended per-replica channel of
   capacity B_r tokens/s (fleet: N * B_r). Demand = restore token
   rate implied by HBM-miss-CPU-hit traffic (the existing `restc`
   term times finish rate). When demand > capacity, the excess queues:
   add the queueing delay to the effective request wait (it lands in
   wq alongside prefill-token and slot waits - a third max() term or
   additive, justify the choice) and cap the achieved restore rate.
2. Restore churn: restored tokens already enter w_hbm; verify, and
   additionally count restore traffic against HBM residency the same
   way prefill writes are counted (restored prefixes occupy pool).
3. Tier capacity honesty: A_c is an age window c_cpu/w_new; during
   congestion the tier serves at 70%+ continuously, meaning the
   working set FITS the tier but cycles through HBM. Check that the
   extended model reproduces this (ext-share ~0.7 emerges when HBM
   window < gap cap < HBM+CPU window and restore bandwidth is the
   binding resource).

Expected qualitative result: at 8x-0.022 the model should now settle
into a congested slowly-diverging state (wait growth ~0.5-1.5/min,
h ~0.7-0.85, sustained restore rate ~ B_r-bound) instead of clean
recovery; at 4x-0.011 (with the Task-2 corrected interference) it
should still recover if the hardware discrepancy is real physics.

## Task 4 - DES extension (des_b1.py)

Make restore a contended per-node resource: a request whose prefix
hits the CPU window but not the HBM window queues for the node's
restore channel (capacity B_r tok/s) before prefill; restored bytes
also advance the node's virtual write clock (they displace HBM
content). Keep everything else from the validated des_b1 setup.
5 seeds x {8x-0.022 tier, 4x-0.011 tier} plus the two no-offload
arms as regression (must not change).

## Task 5 - validation, prediction, deliverables

Validation targets (measured):

    arm             expected model outcome
    8x-0.022 tier   congestion: h 0.70-0.85, ext share 0.66-0.79,
                    wait diverging slowly (6 -> 164 over 195 min,
                    plateau episodes allowed), tput ~2.2x collapsed
    4x-0.011 tier   clean recovery (B2a), wait -> 0 post-surge
    8x-0.022 noofl  absorbing collapse (unchanged regression)
    8x-0.017 noofl  recovery w/ boundary variance (unchanged)

Then produce the PREDICTION for the next hardware window: sweep
lambda_s on the 8x tier fleet in-model and report the two boundaries
(recovery -> congestion, congestion -> cold collapse if it exists),
plus the A4 prediction: how the congestion onset moves with c_cpu at
half and double the current 1.26M tokens/replica.

Deliverables:

- extract_arcs.py extended + refreshed out/arcs/*.csv
- tpot re-fit note (fleet-R vs per-pod-R verdict) in the findings doc
- extended fluid + DES code, new overlay figure adding the three tier
  runs and the long-horizon pair (out/overlay_restore.png)
- "Restore-bound congestion model" section appended to
  overlay-findings.md: calibration provenance (B_r measured), per-arm
  verdicts, the scale-question resolution or its sharpened remainder,
  boundary predictions for the next window
- one compact memory-file update block

## Pitfalls

- extract_arcs.py pool constants: the three new tier runs are 8x
  (yangligt was scaled to 8 on 2026-08-10); only cpuofl-b2a-base is 4x.
- Service endpoints to exclude: 10.0.44.19 (igw) AND 10.0.47.15
  (yangligt) - extract_arcs.py already excludes both.
- kv_offload counter units and direction: verify before calibrating
  B_r (Task 1); do not inherit des.py's RESTORE_TPS=1e6 uncritically.
- Do not tune the third regime into existence: B_r comes from
  measured counters, interference from the Task-2 refit; if the
  regime does not emerge, report which measured constraint fails to
  bind rather than adjusting constants to force it.
- Repo style per CLAUDE.md: plain dashes, terse comments, no
  temporal framing.

Suggested kickoff prompt:
"Read docs/research/kv_equilibrium/handoff-restore-model.md and
execute it end to end."
