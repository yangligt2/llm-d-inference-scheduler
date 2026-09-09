# Session handoff (written 2026-08-14, end of a three-week session)

Entry point for a fresh session taking over the KV-cache equilibrium
research. Facts live in their canonical documents; this file is
navigation, the delta since those documents were written, and the
prioritized pending work. Read in this order:

1. research-status.md - the science: 12 established results with
   evidence grades, ranked open questions, artifact map. CURRENT as
   of 2026-08-14.
2. experiment-env.md - operations runbook: bench.sh usage, launch
   gate patterns, analysis conventions, comparability rules, the
   hard T-15 scale-down rule.
3. lab-notebook-2026-08-13.md - the latest window (N-mechanism
   confirmation, tier-capacity verdict, the namespace-loss incident);
   earlier notebooks (08-08 through 08-12) hold the full run-by-run
   record.
4. overlay-findings.md - modeling: calibration provenance, fluid and
   DES results, refinements, falsifications, boundary predictions.

The project auto-memory mirrors the highlights and survives context
loss independently of this file.

## One-paragraph arc of the project

Started from a customer escalation (hit-rate collapse under load),
built a fluid fixed-point model (bistability via miss-write
feedback), validated and then repeatedly CORRECTED it against ~45
hardware runs on GB200 fleets with a purpose-validated open-loop
session-arrival instrument. The story that emerged is richer than
the original band hypothesis: absorbing cold collapse under an
eviction-scale perturbation (hysteresis in exogenous session units,
n=3), a horizon-dependent stability edge (organic collapse),
demand-elasticity scoping (completion-coupled sessions defer rather
than storm), a THIRD REGIME on CPU-offload tiers (restore-bound
congestion: bandwidth sets throughput, capacity sets persistence),
and - the sharpest late finding - fleet-size fragility that is a
COORDINATION-layer property (per-pod physics measured
scale-invariant; a sharded router restores stability that a single
wider router loses). Models (fluid + DES) reproduce most regimes
from independently measured constants; their two documented
failures (4x stability, tier-capacity persistence) are themselves
results and define the next modeling work.

## What is in hand (data and code)

- ~45 collected report sets under
  /Users/yangligt/workplaces/llm-d/guides/subslicing/aiperf/reports/
  (per-request JSONL, per-pod 5 s server metrics parquet, logs).
  Windowed arcs for the key runs: kv_equilibrium/out/arcs/*.csv
  (extract_arcs.py; note the newest five runs from 08-13 - shard-a,
  n16-lh040, a4half-lh, a4full-lh - are NOT yet in the RUNS dict;
  add them, all 8x/16x pool constants, before the next analysis
  pass).
- Models: fluid_model.py (Phase-1 fixed point), overlay_b1_dynamics.py
  (session-reservoir fluid + per-pod tpot interference + restore
  channel), des.py + des_b1.py (DES with watermark admission,
  two-clock LRU, contended restore channel), tpot_fit.py,
  overlay_fixedpoint.py, overlay_restore.py, extract_arcs.py,
  analyze_run_windows.py. All run from docs/research/ with .venv.
- Blueprints for rebuilding all infrastructure:
  namespace-request-4x-tier.md (tier), namespace-request-shards.md
  (no-offload). NOTHING is currently deployed.

## Pending work, prioritized

GPU-free - DONE 2026-08-14 (this session):

1. DONE. Per-pod spread analysis: per_pod_spread.py +
   per-pod-spread-findings.md. Load imbalance refuted; scatter/
   duplication signatures measured (h deficit, excess KV at matched
   state, staggered pinning cascade at 16x).
2. DONE. Model refits, documented in overlay-findings.md (last two
   sections): (a) RouterSessionSim in des_b1.py - deployed EPP
   algorithm (all constants from config/plugin code) plus a
   coordinator-saturation threshold C_W bracketed (140e3, 190e3)
   fleet write tok/s; reproduces the N-series including the 16x
   absorbing tail and resolves the 4x falsification. (b) TIER_EFF =
   0.5 effective tier capacity; reproduces the tier-250 cold
   collapse. New figures: out/overlay_nseries.png,
   out/overlay_tiercap.png; b1 overlays rerun. Remaining failures
   (documented, not tuned): heal-branch pessimism, binary freeze.
3. DONE. All nine 08-12/08-13 base runs are in extract_arcs.py
   (POOL_16X added; service-endpoint exclusion is now structural on
   the :8000 port); out/arcs/ refreshed, 33 runs.
4. Paper assembly can begin: the figure set is largely complete
   (trichotomy overlay, DES bands, long-horizon pair, 0.020 pair,
   T-block pair, N-series + tier-capacity overlays).
   research-status.md sections 1-11 map to claims.

GPU-free heal-branch status (2026-08-25): the "heal-branch
pessimism" failure in item 2 has four completed candidate rounds,
all screened NEGATIVE - reservation timing, stale-content tier
churn, restore-channel serialization, and occupancy-gated HBM
eviction (heal_variant_progressive.py / heal_variant_stale.py /
heal_variant_serial.py / heal_variant_headroom.py;
overlay-findings.md, 2026-08-25 subsection). The serial channel's
fixed-capacity reading is falsified by the measured heal arcs
(research-status.md results 4 and 9); des_b1.py is unchanged.
Candidates 3 and 4 bound the re-entry trap's carrier from both
sides (widened channel vs corrected residency; the trap survives
each), isolating the deficit to the ~100k-token unconditional
full-context restore per tier hit interacting with full-KV
reservation at admission - the restored-volume term
(research-status.md question 2). Any successor variant keeps the
vLLM gauge-semantics split (pending-onboard entries excluded from
the tpot R) and must hold the congested pin inside the measured
0.81-1.04 N*B_R band (candidate 4 does; candidate 3 overshoots).

Paper: paper/draft.md is the full audited manuscript draft (claims
register paper/claims-map.md, C01-C35); remaining paper work is the
five TO PRODUCE figures and the five owed related-work full-text
reads listed in its Section 9.

Hardware (next capacity window): experiment-plan-next-window.md is
the queue - P1 coordinator-saturation discrimination (EPP metrics
scrape on every run + 16x approx-prefix + 8x load-only ablation),
P2 second shard draw, P3 tier bracket 375/650 with sharp
differential predictions, P4 300-min 4x falsifier, P5 bimodality
draws. ALL infra must be rebuilt first - IAM grants are user/admin
actions.

## Cautions for the next operator (hard-won)

- Schedule the unconditional fleet scale-down at window START
  (T-15 min). The 08-13 incident destroyed five namespaces
  including the shared igw-llm-d - flag that loss to its owners
  before rebuilding anything under that name.
- aiperf artifacts land only at end-of-run export; a hung export
  (seen once in ~40 runs) means zero data. Leave export margin and
  check "records processed" in logs before trusting a run exists.
- readyReplicas polls for gates; surge chains keyed on base-job
  existence; salted cacheBust everywhere; report realized req/s and
  requests/session with every lambda_s claim; per-namespace GCS IAM
  + zone-pinned bench-assets seeds for any new namespace.
- Permission boundaries that held this session and should keep
  holding: IAM changes and cluster-scoped PV surgery are USER
  actions; propose the exact command and wait.


