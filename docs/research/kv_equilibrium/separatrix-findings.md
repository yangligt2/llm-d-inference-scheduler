# Drain-depth separatrix: p(fast relapse | kv at t=115, rate, N)

Date: 2026-08-25. Resolves research-status open question 3
(quantitative form of headline D). Inputs: out/arcs/*.csv for the 22
standard-dose, affinity-routed no-offload post-cancel draws at
rate_eq >= 0.017 (the 0.012 pair, the non-standard-dose b1a, and the
load-only ablation are excluded; see Limitations); des_b1.
RouterSessionSim for the DES
comparison. Code: separatrix_fit.py (the fit, test, and DES numbers
below are its stdout; the Limitations bullets add arc-level checks;
scipy/statsmodels are absent from the venv, so the logistic layer
is a hand-rolled Firth-penalized Newton). Outputs:
out/separatrix_draws.csv, out/separatrix_des.csv,
out/separatrix_fit.png.

## Outcome definitions

All times are arc t_min labels: a value at t is the 5-min window
aggregate over [t, t+5) min from the first metrics sample
(extract_arcs.py labels the window start).

    collapse   canonical end-state class cold (mean h < 0.15 over
               270 <= t_min <= 295); horizons shorter than 295 min
               take the lab-notebook verdict and are flagged.
    fast       first window with h < 0.5 after t=110 starts at
               t <= 160 min. The measured onsets are bimodal - fast
               draws at 115-155, organic-late at 220-250 - so any
               cut in (155, 220) yields the same labels.

The separatrix response is FAST relapse. kv at t=115 (fleet-mean
vllm kv_cache_usage_perc over the window [115, 120), which opens
8 min after the nominal surge cancellation at t+107) gauges the
drain-vs-catch-up race; the organic-late
draws (ppc-edge020-noofl, ppc-edge020-r2) win that race from deep
drains (kv115 0.616, 0.663) and collapse ~2 h later by a distinct
mechanism that kv115 does not predict.

## Draw table

run                    N  rate_eq  kv115  warm_req_s  class      onset  note
ppc-b1c-base           8  0.017    0.676  2.16        recovered  -      180-min horizon
ppc-bimod2             8  0.017    0.683  1.99        recovered  -      150-min horizon
ppc-bimod3             8  0.017    0.475  1.81        recovered  -      150-min horizon
ppc-bimod4-017         8  0.017    0.624  1.30        recovered  -      180-min horizon
ppc-edge020-noofl      8  0.020    0.616  2.00        cold       250    organic-late
shard-a-020            8  0.020    0.606  2.21        recovered  -
ppc-shard-a2-020       8  0.020    0.592  1.91        recovered  -
ppc-shard-b2-020       8  0.020    0.735  1.82        cold       150    fast
ppc-shard-b3-020       8  0.020    0.874  2.18        cold       130    fast
ppc-edge020-r2         8  0.020    0.663  1.78        cold       220    organic-late
ppc-shard-a3-020       8  0.020    0.750  2.37        cold       145    fast
ppc-shard-b4-020       8  0.020    0.620  1.98        recovered  -
ppc-b1a2-base          8  0.022    0.793  1.64        cold       145    fast; 180-min horizon
ppc-b1a2-rep-base      8  0.022    0.931  1.85        cold       115    fast; 180-min horizon; onset-marginal
ppc-lh-noofl           8  0.022    0.903  2.03        cold       125    fast
ppc-n16-lh040         16  0.020    0.796  3.46        cold       140    fast
ppc-n16-lh040-r2      16  0.020    0.790  4.25        cold       145    fast
apx-n16-lh040         16  0.020    0.861  4.95        cold       135    fast; approx config
ppc-n16-edge034       16  0.017    0.736  3.97        recovered  -
ppc-n16-edge037       16  0.0185   0.734  4.39        recovered  -
ppc-n16-edge037-r2    16  0.0185   0.650  3.85        cold       155    fast
ppc-n16-inv040        16  0.020    0.941  4.15        cold       115    EXCLUDED from fit

rate_eq = per-8x-equivalent session rate (lambda_s x 8/N); onset =
t_h50, t_min label of the first window with h < 0.5 after t=110
(minutes); warm_req_s = realized req/s over windows 30-60 min.
kv110/kv120, end-state h/wait, and t_h15 are in
out/separatrix_draws.csv.

Cross-tab (21 fitted draws):

    N  rate_eq  draws  fast  collapse  kv115 range
    8  0.017    4      0     0         0.475-0.683
    8  0.020    8      3     5         0.592-0.874
    8  0.022    3      3     3         0.793-0.931
    16 0.017    1      0     0         0.736
    16 0.0185   2      1     1         0.650-0.734
    16 0.020    3      3     3         0.790-0.861

## Leakage

The t=115 reading precedes erosion onset in 20 of 21 fitted draws:
every collapsing draw except one satisfies t_h50 >= 125, i.e. h was
still >= 0.5 through the window starting t=120, so the first
sub-0.5 window opens at least 5 min after the kv115 window closes
at t=120 (>= 100 min after it for the organic-late draws). The
exception is ppc-b1a2-rep-base (re-warm peak h 0.80 in the t=110
window, h 0.43 in the t=115 window): erosion runs inside the kv115
window itself, so its kv115 is contemporaneous with onset. Dropping it
changes nothing material (sensitivity below). ppc-n16-inv040 is
excluded outright: its surge backlog was still pinned at t=115
(h 0.010, wait 1360; the re-warm arrives at t=120-125 and the
horizon ends at 135), so kv115 = 0.941 reads the pinned backlog,
not the post-cancel drain.

## Fit

Firth-penalized logistic regression, response = fast, n = 21,
events = 10. Firth is required: kv115 separates the 8x draws
perfectly, so the unpenalized MLE diverges. rate is in units of
1e-3 sps per-8x-eq.

    model             penLL    coefficients (se)
    intercept        -13.70    b0 -0.09 (0.44)
    rate              -8.55    rate +0.91 (0.44)
    kv115             -8.22    kv115 +23.4 (9.8)
    rate+kv115        -6.52    rate +0.63 (0.54), kv115 +20.1 (9.7)
    rate+N16          -6.77    rate +1.43 (0.72), N16 +2.67 (1.62)
    rate+N16+kv115    -6.85    rate +0.73 (0.65), N16 +1.09 (1.71),
                               kv115 +14.8 (9.3)

    penalized LR  kv115 | rate      4.05   p ~ 0.044
    penalized LR  kv115 | rate+N16 -0.17   (no gain; see below)
    penalized LR  rate  | kv115     3.39   p ~ 0.066
    penalized LR  N16   | rate      3.56   p ~ 0.059

Does kv115 add information beyond rate and N? Two answers with
different conditioning:

1. Exact stratified permutation test (conditions on rate and N
   exactly; the only assumption is within-stratum exchangeability).
   Statistic: summed within-stratum kv115 ranks of the fast draws
   over the two mixed-outcome strata, 8x-0.020 (3 fast of 8) and
   16x-0.037 (1 of 2). One-sided p = 3/112 = 0.027. The signal is
   entirely 8x-borne: within 8x-0.020 the three fast draws hold
   exactly the three highest kv115 values (p = 1/C(8,3) = 1/56 =
   0.018), while the 16x-0.037 pair is anti-aligned (collapser
   0.650 below survivor 0.734).
2. In the logistic ladder, kv115 and the N16 indicator are
   confounded: rate+N16 and rate+kv115 fit almost equally
   (penLL -6.77 vs -6.52) and adding kv115 on top of rate+N16 gains
   nothing. The design cannot separate a direct span effect from
   kv115-mediation because every 16x draw at the 0.020-eq point
   both drained shallow AND relapsed; the mediation reading is
   carried by the within-stratum test above and by the DES section.

Fitted separatrix (p(fast) = 0.5, rate+kv115 model):

    rate_eq 0.017   kv115* = 0.786
    rate_eq 0.020   kv115* = 0.693
    rate_eq 0.022   kv115* = 0.630

slope -0.031 kv per 1e-3 sps per-8x-eq. The 0.020 value sits inside
the empirical 8x separation interval (0.683, 0.735). Uncertainty is
large by construction at n = 21: the kv115 coefficient's Wald 95%
interval is roughly (1, 39), i.e. the direction and the threshold
location are established, the steepness is not.

Onset gradation: among the 12 fitted collapsing draws the rank
correlation between kv115 and onset time is -0.99 (-0.98 without
the onset-marginal ppc-b1a2-rep-base) - shallower drain collapses
earlier. One pair of the 66 is discordant (ppc-n16-edge037-r2,
kv115 0.650, onset 155, vs ppc-edge020-r2, kv115 0.663, onset 220 -
a cross-mechanism pair, 16x fast vs 8x organic-late); every other
non-tied pair is concordant across both fleet sizes and all three
rates. kv115 is not merely a classifier input; it orders the
collapse-onset spectrum, including the organic-late draws at its
deep end.

Sensitivity and robustness:

- Dropping the onset-marginal ppc-b1a2-rep-base: LR kv115 | rate =
  3.94 (p ~ 0.047), kv115* at 0.020 = 0.692 (vs 0.693).
- Sampling-time: kv110 does NOT separate the 8x draws (survivor
  shard-a-020 read 0.674 at t=110 mid-drain, above fast draw
  minima); kv115 separates with gap (0.683, 0.735); kv120 separates
  with a wider gap (0.717, 0.783) but is contaminated for the
  earliest onsets. t=115 is the earliest clean reading.
- Realized warm rate does not separate outcomes within 8x-0.020
  (fast 1.82-2.37 vs non-fast 1.78-2.21 req/s, interleaved),
  confirming the notebook observation; kv115 is not proxying
  realized load.

## Rate and N dependence of the threshold

Within 8x, a single rate-independent threshold ~0.70 is consistent
with all 15 draws (0.017 survivors reach 0.683; 0.022 fast draws
start at 0.793). The rate dependence is established by the 16x edge
points: ppc-n16-edge034 survived kv115 = 0.736 at 0.017-eq (above
the 8x-0.020 band) and ppc-n16-edge037-r2 relapsed from 0.650 at
0.0185-eq (below it). Direction: at lower per-capacity rate the
catch-up race is winnable from a shallower drain; at 16x the
survivable depth contracts faster than rate alone predicts (the
0.650 relapse), consistent with the span-coupling mechanism.
Separately, drain depth itself is N-dependent at matched
per-capacity rate: measured mean kv115 at the 0.020-eq point is
0.816 (16x, 3 draws) vs 0.682 (8x, 8 draws) - the wide router
drains shallower, which is the mediation path by which span raises
collapse probability.

## DES comparison

KvGaugeSim (separatrix_fit.py --des) subclasses RouterSessionSim
with a fleet KV-occupancy gauge on the standard 5 s cadence
(sum(node.kv_used) / (N x C_HBM), the model analogue of the measured
fleet-mean gauge). des_b1.windows() labels t_min at the window END;
the sweep shifts the labels one window down to the arcs' START
convention, so DES kv115 aggregates the same [115, 120)-min
interval as the measured kv115. 300-min horizon; 10 seeds at
8x-0.020, 8 seeds at 16x-0.040; out/separatrix_des.csv.

    point      collapse   kv115: survivors / collapsers   rank corr
                                                          (kv115, onset)
    8x-0.020   9/10       0.641 / 0.694-0.883             -0.77 (n=9)
    16x-0.040  8/8        -     / 0.752-0.887             -0.73 (n=8)

The mediation structure reproduces: the single surviving seed holds
the minimum kv115 of its point, and among collapsing seeds shallower
drains collapse earlier at both fleet sizes (same sign as the
measured -0.99, weaker gradient). The DES also reproduces the
measured N-ordering of drain depth at matched per-capacity rate,
with the gap compressed from the 8x side: DES mean kv115 0.828 at
16x vs 0.800 at 8x, measured 0.816 vs 0.682 - the DES 16x mean
matches measurement while its 8x fleet drains too shallow.

Absolute placement carries the documented conservative bias in
direction but not magnitude: the DES implied separatrix at 8x-0.020
lies in (0.641, 0.694), ~0.04 left of the measured (0.683, 0.735) -
the model relapses from drain depths the measured system survives,
consistent with the full-KV-at-admission reservation inflating the
kv gauge. The larger structural gaps are elsewhere: the DES
over-collapses at 8x-0.020 (9/10 vs measured 5/8; not significant
from this sweep alone, but matching the 11/12 of the independent
12-seed no-freeze ladder in overlay-findings.md), and its onset
distribution at that point is a continuum (135-205 min) where the
measured onsets are bimodal (130-155 fast, 220-250 organic-late,
nothing between) - the DES lacks a distinct organic-collapse
mechanism and instead produces slow versions of the same erosion.

## Limitations

- n = 21 fitted draws, 10 events: a 2-covariate model is at the
  events-per-parameter edge; the 3-covariate row exists only to
  state the kv115/N16 confounding. Coefficient magnitudes are not
  load-bearing; the threshold placement and its rate/N direction
  are.
- The fitted rate range is 0.017-0.022 per-8x-eq. The two
  standard-dose 0.012 draws (ppc-b1b-base, ppc-b1b-rep-base) are
  outside it and not in the table; both drained deep and recovered
  (kv115 0.304/0.420), on the survival side of any fitted
  threshold, so their omission cannot flip the fit's direction.
  b1a is excluded on protocol (non-standard dose, 0.15 x 600 s +
  0.25 x 900 s). The load-only ablation (lo-shard-a-020) is
  excluded because its EPP config removes the affinity signal the
  drain race runs under.
- Draw non-independence: the shard draws ran pairwise in shared
  windows over shard-a/shard-b namespaces; the b1a2 and lh040 pairs
  are same-config replicates across days. All draws are treated as
  independent; the notebook's namespace-split check (shard-a vs
  shard-b, broken by ppc-shard-a3-020) supports draw variance over
  a fixed namespace effect.
- The two organic-late draws are exactly the two dedicated-fleet
  (non-shard) 8x-0.020 draws; all six shard draws are clean or
  fast (1/28 under exchangeable assignment). If dedicated and
  shard draws are not exchangeable units, the conservative form of
  the within-8x permutation test uses the shard draws alone: the
  three fast draws still hold the three highest kv115 of the six,
  p = 1/C(6,3) = 1/20.
- kv rises from the t=110 to the t=115 window in every fast draw
  (+0.06 to +0.16), so kv115 reads the drain floor plus early
  re-inflation, not a floor alone. The 110->115 delta itself does
  not separate outcomes (survivor deltas reach +0.11); the level
  does. In three fast draws the hit rate is already declining
  through the kv115 window while holding above 0.5 (h over the
  t=110/115/120 windows: shard-b3 0.86/0.79/0.75, shard-a3
  0.89/0.85/0.78, apx-n16-lh040 0.85/0.80/0.76), so part of their
  kv115 elevation is contemporaneous miss-write flux rather than
  drain depth. Four fast draws carry the elevation with h flat at
  >= 0.88 through t=120 (shard-b2, b1a2-base, n16-lh040-r2,
  n16-edge037-r2), and two hold their re-warm level through the
  window and erode only after it closes (n16-lh040 h 0.88 -> 0.80,
  lh-noofl 0.71 -> 0.52 across t=115 -> 120): the covariate does
  not reduce to an erosion echo.
- Hypothesis timing: the drain-depth covariate was articulated
  mid-campaign (lab-notebook-2026-08-15, S2, after ppc-shard-b3-020)
  from draws that are themselves in the fit; 14 of the 21 fitted
  draws predate or coincide with that articulation, including 5 of
  the 8 in the 8x-0.020 stratum that carries the permutation
  signal, so the p-values are not from a pre-registered
  confirmatory test. The 7 later draws split: the three 8x-0.020
  draws land on the hypothesized sides of the threshold (a3 0.750
  fast, b4 0.620 clean, edge020-r2 0.663 organic-late); the 16x
  edge draws motivate the rate/N dependence and include the
  anti-aligned 0.037 pair.
- Six draws have truncated horizons and take notebook classes. For
  the b1a2 pair the fast response is unaffected (onsets 115-145,
  inside the 180-min horizon). The 8x-0.017 row (0 collapse in 4)
  is horizon-limited at 150-180 min: an organic-late collapse there
  would be invisible, so that row understates collapse probability
  if 0.017 has an organic tail.
- The 16x-0.037 stratum (n = 2) is anti-aligned with the covariate;
  kv115 is a mediating correlate whose threshold moves with rate
  and N, not a control law. Deployment use would require the local
  (rate, N) calibration.
- kv is the fleet-mean gauge; per-pod dispersion (the staggered
  pinning cascades in per-pod-spread-findings.md) is averaged out.
- ppc-n16-inv040 contributes no fit information (backlog still
  pinned at t=115); the 16x-0.040 fast tally in the fit is 3/3,
  not 4/4.
