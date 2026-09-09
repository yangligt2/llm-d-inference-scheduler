# Handoff: DES replication of the B1/B2 protocols (GPU-free)

Self-contained work order for a fresh session. Everything needed is in
this file plus the referenced paths. No cluster access required or
expected; this is pure local simulation and analysis.

## Context in one paragraph

We measured, on real hardware (2026-08-08/10), a KV-cache hysteresis
trichotomy under a validated exogenous session-arrival instrument:
identical 45-min overload perturbations leave the fleet permanently
degraded at base rate 0.022 sessions/s (relapse via deferred-demand
catch-up; n=2), but recover cleanly at 0.017 and 0.012 sps (n=2 at
0.012), and a CPU offload tier deletes the relapse (tier-attributed via
external_prefix_cache metrics). A session-reservoir FLUID model
(overlay_b1_dynamics.py) reproduces all four arcs with independently
measured constants; overlay-findings.md documents results, refinements,
limitations, and three falsifiable predictions. The last GPU-free step
is a DISCRETE EVENT replication of the same four protocols: it replaces
the fluid closures with discrete requests, real queues, and exact LRU,
and it delivers (a) variance bars for the overlay figure, (b) smooth h
transitions from heterogeneous per-session waits (the fluid model's h
is square because the capped gap CDF is a step), and (c) a first-
principles check of the fluid boundary location.

## Read these first (in order)

1. kv_equilibrium/overlay-findings.md   - model state, calibration, predictions
2. kv_equilibrium/overlay_b1_dynamics.py - the fluid model being replicated
3. kv_equilibrium/des.py                - the Phase-2 DES to adapt (474 lines)
4. kv_equilibrium/lab-notebook-2026-08-08.md - experiment log (skim B1/B2 sections)

Measured arcs: kv_equilibrium/out/arcs/*.csv (18 runs; columns documented
in extract_arcs.py header). Python: docs/research/.venv (numpy, pandas,
matplotlib installed). Run everything from docs/research/ as
`.venv/bin/python kv_equilibrium/<script>`.

## Objective

New script kv_equilibrium/des_b1.py (import des.py machinery; do NOT
rewrite the LRU/trace core) that simulates the four measured protocols
N_SEED times each and produces:

- out/des_b1_overlay.png: 2x4 panels (h and waiting vs time) with
  measured arc (solid), fluid model (dashed), DES mean and min-max band
  across seeds (shaded). Reuse the styling of overlay_b1_dynamics.py
  (phase_diagram helpers).
- out/des_b1_summary.csv: per arm x seed, end-state h and wait
  (window 150-175 min), in-surge peak wait, time-to-collapse, and
  post-surge recovery time (first window with h > 0.8 after surge end,
  if any).
- A DES-vs-fluid-vs-measured verdict appended to overlay-findings.md
  (section "DES replication") and a one-block memory update (see end).

## The four protocols (exact)

All: 180 min simulated, base sessions arrive Poisson from t=0.
Surge: second population, Poisson, t_on=62 min, t_off=107 min,
CANCELLED at t_off (see semantics below).

    arm        replicas  base sps  surge sps  c_cpu/replica (tokens)
    b1a2       8         0.022     0.25       0
    b1c        8         0.017     0.25       0
    b1b        8         0.012     0.25       0
    b2a        4         0.011     0.125      1.26e6

Measured references per arm: out/arcs/ppc-b1a2-base.csv, ppc-b1c-base,
ppc-b1b-base, cpuofl-b2a-base. Expected outcomes: b1a2 RELAPSE (h
pinned low, queue regrowing at end), b1c and b1b recovery (b1c grazes
the threshold), b2a recovery with the tier.

## Calibration constants (all measured; provenance in overlay-findings.md)

    N_NODES     8 (b1a2/b1c/b1b) or 4 (b2a)
    C_HBM       6486 * 256 = 1,660,416 tokens per replica
    P_TPT       17,000 tokens/s per replica
    tpot        INTERFERENCE COUPLING, not a constant:
                tpot(R) = 9.6e-3 + 3.8e-6 * R^2 seconds/token, cap 0.30,
                R = FLEET-wide running request count. des.py uses fixed
                TPOT - this must be replaced (see task list).
    gap cap     think times capped at 10.5 s (min(gap, 10.5)); applies
                to Sampler.think() and sub_gap()
    RESTORE_TPS keep 1.0e6 tokens/s per node (not binding)
    TIMEOUT     DISABLE shedding (set to 1e9). The measured instrument
                (aiperf, 1200 s client timeout) effectively never sheds
                at these scales, and vLLM queues without dropping. The
                des.py default 30 s models the CUSTOMER gateway - wrong
                here and will suppress the relapse if left in.
    KV_HEADROOM 0.92 (matches fluid; measured KV plateaus 91-95%)

## What des.py already gives you (map)

- Sampler (line ~55): corpus-calibrated lognormal draws for system
  prompt, turn IO, think times, turns per conversation, subagent
  structure. Add the 10.5 s cap in think()/sub_gap().
- Node (~105): virtual write clock + cache_window_hbm. Reuse as is.
- Seq / Conversation (~118-150): per-sequence cache state and turn
  chaining. Reuse.
- Sim (~236): event loop, routing (route()), admission (try_start()),
  prefill/decode completion, per-request records. Mode "closed" spawns
  a fixed lane pool with immediate replacement; mode "replay" fires a
  pregenerated schedule.
- summarize() (~457): windowed metrics from records.

## Tasks

1. New arrival mode "session_poisson" in Sim (or subclass in des_b1.py;
   prefer subclass to keep des.py untouched - it is the published
   Phase-2 artifact):
   - Base population: session start events at exponential inter-arrival
     1/lambda_s from t=0. Each start = spawn_conversation() WITHOUT the
     closed mode's replacement-on-finish; a finished conversation just
     departs. Turn chaining stays completion-coupled (this is exactly
     issue_next_turn(): next turn fires at completion + think gap).
   - Surge population: same generator, lambda_2, active only in
     [t_on, t_off). Tag its Seqs.
   - CANCELLATION at t_off: remove all surge requests from node queues,
     abort surge requests in prefill/decode (free their KV/running
     slots), and mark surge conversations dead (no further turns).
     This mirrors the aiperf generator exiting after its grace period.
2. tpot interference: replace the fixed-TPOT decode-time computation
   with tpot(R) evaluated at decode START of each request (R = current
   fleet running count). Simpler than re-timing in-flight decodes and
   accurate enough at these time scales; note the approximation in the
   script docstring.
3. First-request salting: verify a new conversation's first request has
   no cache entry (true by construction in des.py - new Seq). No change
   expected; assert it.
4. Windowed output: adapt summarize() to 5-min windows emitting h
   (cached/prompt tokens), waiting count (sampled or time-averaged),
   running count, completions/s - matching the arcs CSV columns closely
   enough to overlay.
5. Seeds: N_SEED = 5 per arm (20 runs total). If a 180-min run exceeds
   ~2 min wall, profile before reducing seeds - event counts here are
   modest (~30k requests/run).
6. Sanity gates before trusting results:
   - Realized base request rate in the warm hour: b1a2 ~1.6-2.4 req/s,
     b1b ~1.1-1.4, b1c ~2.0-2.3 (draw variance is real and expected;
     the DES should show it ACROSS SEEDS).
   - Realized requests/session across a 3 h window ~100-130 (window
     truncation; the corpus mean 174 only applies to unbounded windows.
     If you see ~174, sessions are being replaced or the window logic
     is wrong).
   - Warm h 92-96%; collapsed h < 15%; in-surge peak wait 500-800
     (8-replica arms) / 300-450 (b2a).
7. Compare against the fluid model: import overlay_b1_dynamics.simulate
   and plot its trajectory as the dashed line (same call signatures as
   its SCENARIOS list).

## Validation targets (measured, from the arcs; DES should bracket these)

    arm    warm h      in-surge peak wait   end-state (150-175 min)
    b1a2   93-96%      776                  h 3-12%, wait 40-130 growing
    b1c    92-96%      ~790                 h 89-95%, wait 0-2
    b1b    88-96%      675-742              h 93-96%, wait 0
    b2a    89-97%      399                  h 93-97%, wait 0

Key qualitative targets beyond the table:
- b1a2 relapse: post-cancellation dip in wait, then regrowth (measured
  regrowth from ~min 125; the first measured draw had a 15-min warm
  interlude, the replicate did not - the DES seed spread should show
  whether the interlude is draw variance, which would resolve a
  documented fluid-model gap).
- h transitions should be SMOOTH (10-15 min erosion), not square -
  heterogeneous per-session waits are the whole point of the DES here.
- b1c should sit near the boundary: expect seed-to-seed outcome
  variance (some seeds may relapse - that is a finding, not a bug;
  measured b1c recovered but grazed KV 75%).

## Pitfalls

- des.py module-level constants (N_NODES, P_TPT, C_HBM, TPOT, TIMEOUT)
  are read by Sim at run time; parameterize per scenario (set module
  attributes before constructing Sim, or refactor into Sim kwargs in
  the subclass). Two arms use 4 replicas.
- Do not leave TIMEOUT=30 (see constants table).
- The closed mode replaces finished conversations - make sure the new
  mode does not inherit that.
- Think-time cap: cap the SAMPLE, not the CDF.
- Runtime: if slow, the usual culprit is per-event Python heap churn;
  acceptable fixes are batching window stats and avoiding per-token
  events. Do not vectorize away the discrete queue - that is the point
  of the DES.
- Repo style: plain dashes, terse comments, no temporal framing, code
  style per CLAUDE.md. These are research docs (untracked), but keep
  the same discipline.

## Wrap-up requirements

1. Append a "DES replication" section to overlay-findings.md: seed
   table, verdict vs fluid and vs measured per arm, whether the b1c
   boundary variance and the b1a2 interlude appear, limitations.
2. Update the auto-memory file kv-cache-equilibrium-research.md
   (project memory) with one compact block: DES replication done,
   headline numbers, artifact paths.
3. Leave out/des_b1_overlay.png, out/des_b1_summary.csv, and
   des_b1.py in kv_equilibrium/.

Suggested kickoff prompt for the new session:
"Read docs/research/kv_equilibrium/handoff-des-replication.md and
execute it end to end."
