"""Drain-depth separatrix: p(fast relapse | kv at t=115, rate, N).

Quantifies research-status open question 3. Inputs: out/arcs/*.csv
(one row per 5-min window; t_min labels the window START, so a value
at t aggregates [t, t+5) min; kv = fleet-mean vllm
kv_cache_usage_perc). Draw set: every standard-dose, affinity-routed
no-offload post-cancel draw across 8x-0.017/0.020/0.022 and the 16x
ladder (22 draws; ppc-n16-inv040 is excluded from the fit because its
post-cancel drain had not started by t=115, see the leakage table;
the two 0.012 draws sit below the fitted rate range, b1a ran a
non-standard dose, and the load-only ablation lo-shard-a-020 lacks
the affinity signal the drain race runs under).

Outcome definitions:
  collapse       canonical end-state class cold over 270 <= t_min <= 295
                 (mean h < 0.15); recovered = mean wait < 15 and mean
                 h > 0.9; else congested. Truncated horizons (< 295 min)
                 take the lab-notebook class and are flagged.
  fast relapse   first window with h < 0.5 after t=110 starts at
                 t <= FAST_ONSET_MAX (160 min). Measured onsets split
                 cleanly: fast draws 115-155, organic-late 220-250.
                 The separatrix response is FAST relapse: kv115 gauges
                 the post-cancel drain-vs-catch-up race, which the
                 organic-late draws win before collapsing by a distinct
                 later mechanism.

Methods (numpy only; scipy/statsmodels absent from the venv):
  - Firth-penalized logistic regression (Jeffreys prior), hand-rolled
    Newton with step halving. Plain MLE diverges here because kv115
    separates the 8x draws perfectly; Firth keeps estimates finite and
    is the standard remedy at this n.
  - Penalized likelihood-ratio tests between nested models (chi2 tail
    via math.erfc for 1 df).
  - Exact stratified permutation test: within the two (N, rate) strata
    with mixed outcomes (8x-0.020: 3 fast / 8; 16x-0.037: 1 / 2),
    enumerate all C(8,3) x C(2,1) = 112 within-stratum relabelings of
    the fast set and compare the summed within-stratum kv115 ranks of
    the fast draws. This conditions on rate and N exactly, so it IS
    the "does kv115 add information beyond rate and N" test.

DES comparison (--des): KvGaugeSim subclasses des_b1.RouterSessionSim
(des_b1.py untouched) with a fleet KV-occupancy gauge, sampled on the
same 5 s cadence as the other gauges: sum(node.kv_used) / (N * C_HBM),
the model analogue of the measured fleet-mean kv_cache_usage_perc.
des_b1.windows() labels t_min at the window END; the sweep shifts the
labels one window down to the arcs' START convention, so DES kv115
covers the same [115, 120)-min interval as the measured kv115.
Sweep: 10 seeds at 8x-0.020 and 8 seeds at 16x-0.040, 300 min, writes
out/separatrix_des.csv (slow: tens of minutes). The analysis pass
reads that CSV if present. The DES reserves each request's full KV
need at admission (documented conservative bias), so its absolute
kv115 placement is expected high; the comparison of interest is the
mediation structure (kv115 vs outcome/onset association).

Run from kv_equilibrium/:
    ../.venv/bin/python separatrix_fit.py          # table + fits + figure
    ../.venv/bin/python separatrix_fit.py --des    # DES kv-gauge sweep

Outputs: out/separatrix_draws.csv, out/separatrix_fit.png,
out/separatrix_des.csv (--des), stdout report.
"""

import math
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from phase_diagram import PAGE, SURFACE, INK, INK2, MUTED, GRID, style_axes, wash

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

FAST_ONSET_MAX = 160.0   # min; onset = t_min (window start) of first h < 0.5 window after t=110
WARM_LO, WARM_HI = 30.0, 60.0
END_LO, END_HI = 270.0, 295.0

# run, N, base lambda_s, notebook class if the horizon truncates the
# canonical 270-295 window (None = classify from the arc), fit flag
# (False = t=115 reading leaked/invalid, keep in table only).
DRAWS = [
    ("ppc-edge020-noofl",  8, 0.020, None,        True),
    ("shard-a-020",        8, 0.020, None,        True),
    ("ppc-shard-a2-020",   8, 0.020, None,        True),
    ("ppc-shard-b2-020",   8, 0.020, None,        True),
    ("ppc-shard-b3-020",   8, 0.020, None,        True),
    ("ppc-edge020-r2",     8, 0.020, None,        True),
    ("ppc-shard-a3-020",   8, 0.020, None,        True),
    ("ppc-shard-b4-020",   8, 0.020, None,        True),
    ("ppc-b1c-base",       8, 0.017, "recovered", True),
    ("ppc-bimod2",         8, 0.017, "recovered", True),
    ("ppc-bimod3",         8, 0.017, "recovered", True),
    ("ppc-bimod4-017",     8, 0.017, "recovered", True),
    ("ppc-b1a2-base",      8, 0.022, "cold",      True),
    ("ppc-b1a2-rep-base",  8, 0.022, "cold",      True),
    ("ppc-lh-noofl",       8, 0.022, None,        True),
    ("ppc-n16-lh040",     16, 0.040, None,        True),
    ("ppc-n16-lh040-r2",  16, 0.040, None,        True),
    ("apx-n16-lh040",     16, 0.040, None,        True),
    ("ppc-n16-edge034",   16, 0.034, None,        True),
    ("ppc-n16-edge037",   16, 0.037, None,        True),
    ("ppc-n16-edge037-r2", 16, 0.037, None,       True),
    # inv040: backlog still pinned at t=115 (h 0.010, wait 1360); the
    # re-warm arrives at t=120-125 and the horizon ends at 135. Its
    # kv115 = 0.94 reads the pinned backlog, not the post-cancel drain.
    ("ppc-n16-inv040",    16, 0.040, "cold",      False),
]


# -- draw table ---------------------------------------------------------------

def kv_at(d, t):
    r = d[d.t_min == t]
    return float(r.kv.iloc[0]) if len(r) else np.nan


def classify_end(d):
    end = d[(d.t_min >= END_LO) & (d.t_min <= END_HI)]
    if not len(end):
        return None, np.nan, np.nan
    eh, ew = end.h.mean(), end.wait.mean()
    if eh < 0.15:
        cls = "cold"
    elif ew < 15 and eh > 0.9:
        cls = "recovered"
    else:
        cls = "congested"
    return cls, eh, ew


def build_table():
    rows = []
    for run, n, lam, nb_cls, fit_ok in DRAWS:
        d = pd.read_csv(ARCS / f"{run}.csv")
        cls, eh, ew = classify_end(d)
        truncated = cls is None
        if truncated:
            cls = nb_cls
        post = d[d.t_min > 110]
        t_h50 = post[post.h < 0.5].t_min.min()
        t_h15 = post[post.h < 0.15].t_min.min()
        rows.append({
            "run": run, "N": n, "lam": lam,
            "rate_eq": lam * 8.0 / n,          # per-8x-equivalent sps
            "kv110": kv_at(d, 110.0), "kv115": kv_at(d, 115.0),
            "kv120": kv_at(d, 120.0),
            "warm_req_s": d[(d.t_min >= WARM_LO)
                            & (d.t_min <= WARM_HI)].req_s.mean(),
            "horizon_min": d.t_min.max(),
            "truncated": truncated,
            "cls": cls,
            "end_h": eh, "end_wait": ew,
            "t_h50": t_h50, "t_h15": t_h15,
            "collapse": int(cls == "cold"),
            "fast": int(np.isfinite(t_h50) and t_h50 <= FAST_ONSET_MAX),
            "fit_ok": fit_ok,
        })
    return pd.DataFrame(rows)


# -- Firth-penalized logistic -------------------------------------------------

def firth_logit(X, y, max_iter=500, tol=1e-9):
    """Newton on the Firth-modified score. X includes the intercept.
    Returns (beta, se, penalized log-likelihood)."""
    n, k = X.shape
    b = np.zeros(k)

    def parts(b):
        p = 1.0 / (1.0 + np.exp(-(X @ b)))
        W = np.clip(p * (1 - p), 1e-12, None)
        F = X.T @ (X * W[:, None])
        Finv = np.linalg.inv(F)
        h = W * np.einsum("ij,jk,ik->i", X, Finv, X)
        U = X.T @ (y - p + h * (0.5 - p))
        pl = (np.sum(y * np.log(np.clip(p, 1e-300, None))
                     + (1 - y) * np.log(np.clip(1 - p, 1e-300, None)))
              + 0.5 * np.linalg.slogdet(F)[1])
        return p, Finv, U, pl

    _, Finv, U, pl = parts(b)
    for _ in range(max_iter):
        step = Finv @ U
        s = 1.0
        while s > 1e-6:
            b_new = b + s * step
            try:
                _, Finv_n, U_n, pl_n = parts(b_new)
            except np.linalg.LinAlgError:
                s /= 2
                continue
            if pl_n >= pl - 1e-12:
                break
            s /= 2
        if np.max(np.abs(b_new - b)) < tol:
            b, Finv, pl = b_new, Finv_n, pl_n
            break
        b, Finv, U, pl = b_new, Finv_n, U_n, pl_n
    return b, np.sqrt(np.diag(Finv)), pl


def chi2_sf1(x):
    return math.erfc(math.sqrt(max(x, 0.0) / 2.0))


def fit_models(t):
    """Model ladder on the fit-eligible draws; response = fast."""
    y = t.fast.values.astype(float)
    one = np.ones(len(t))
    # rate scaled to per-mille per-8x-eq so coefficients are O(1)-printable
    r = t.rate_eq.values * 1000.0
    kv = t.kv115.values
    n16 = (t.N.values == 16).astype(float)
    specs = {
        "1":            [one],
        "rate":         [one, r],
        "kv115":        [one, kv],
        "rate+kv115":   [one, r, kv],
        "rate+N16":     [one, r, n16],
        "rate+N16+kv115": [one, r, n16, kv],
    }
    fits = {}
    for name, cols in specs.items():
        X = np.column_stack(cols)
        b, se, pl = firth_logit(X, y)
        fits[name] = (b, se, pl)
    return fits


def exact_stratified_test(t):
    """Exact permutation of the fast labels within (N, rate) strata,
    statistic = summed within-stratum kv115 ranks of the fast draws.
    One-sided: fast draws sit at HIGHER kv115."""
    strata = []
    for _, g in t.groupby(["N", "rate_eq"]):
        if 0 < g.fast.sum() < len(g):
            ranks = g.kv115.rank().values
            strata.append((ranks, int(g.fast.sum()),
                           g.fast.values.astype(bool)))
    t_obs = sum(r[m].sum() for r, _, m in strata)
    combos = [list(combinations(range(len(r)), k)) for r, k, _ in strata]
    total, ge = 0, 0
    idx = [0] * len(strata)
    from itertools import product
    for pick in product(*combos):
        s = sum(strata[i][0][list(pick[i])].sum() for i in range(len(strata)))
        total += 1
        if s >= t_obs - 1e-9:
            ge += 1
    return t_obs, ge, total


# -- DES sweep ----------------------------------------------------------------

def des_sweep():
    import des
    import des_b1
    from des_b1 import RouterSessionSim

    class KvGaugeSim(RouterSessionSim):
        """RouterSessionSim + fleet KV-occupancy gauge on the standard
        5 s sampling cadence: sum(node.kv_used) / (N * C_HBM)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.kv_sum = np.zeros(int(self.t_end / des_b1.WIN))

        def sample_gauges(self):
            wi = int(self.now // des_b1.WIN)
            if wi < len(self.kv_sum):
                pool = len(self.nodes) * des.C_HBM
                self.kv_sum[wi] += sum(nd.kv_used for nd in self.nodes) / pool
            super().sample_gauges()

        def windows(self):
            w = super().windows()
            w["kv"] = self.kv_sum / np.maximum(self.n_samp, 1)
            return w

    t_end = 300 * 60.0
    points = [("8x-0.020", 8, 0.020, 0.25, range(1, 11)),
              ("16x-0.040", 16, 0.040, 0.50, range(1, 9))]
    rows = []
    for label, n, lb, ls, seeds in points:
        for seed in seeds:
            t0 = time.perf_counter()
            sim = KvGaugeSim(n, lb, ls, 0.0, seed, t_end=t_end)
            sim.run()
            w = sim.windows()
            # des_b1.windows() labels t_min at the window END; the arcs
            # label the window START. Shift one window to align.
            w = w.assign(t_min=w.t_min - des_b1.WIN / 60.0)
            end = w[(w.t_min >= END_LO) & (w.t_min <= END_HI)]
            eh, ew = end.h.mean(), end.wait.mean()
            cls = ("cold" if eh < 0.15 else
                   "recovered" if ew < 15 and eh > 0.9 else "congested")
            post = w[w.t_min > 110]
            rows.append({
                "point": label, "N": n, "lam": lb, "seed": seed,
                "kv110": float(w[w.t_min == 110].kv.iloc[0]),
                "kv115": float(w[w.t_min == 115].kv.iloc[0]),
                "kv120": float(w[w.t_min == 120].kv.iloc[0]),
                "warm_req_s": sum(1 for rec in sim.records
                                  if rec[0] < des_b1.T_ON) / des_b1.T_ON,
                "end_h": eh, "end_wait": ew, "cls": cls,
                "t_h50": post[post.h < 0.5].t_min.min(),
                "t_h15": post[post.h < 0.15].t_min.min(),
            })
            r = rows[-1]
            print(f"{label} seed {seed}: {time.perf_counter() - t0:.0f}s, "
                  f"kv115 {r['kv115']:.3f}, cls {cls}, t_h50 {r['t_h50']}",
                  flush=True)
    pd.DataFrame(rows).to_csv(OUT / "separatrix_des.csv", index=False,
                              float_format="%.4f")
    print("wrote out/separatrix_des.csv")


# -- figure -------------------------------------------------------------------

C_FAST, C_SURV = "#d03b3b", "#2a78d6"   # validated pair on SURFACE

def figure(t, fits):
    fig, ax = plt.subplots(figsize=(6.4, 4.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    style_axes(ax)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)

    # measured 8x separation band (max non-fast kv115, min fast kv115)
    t8 = t[(t.N == 8) & t.fit_ok]
    lo = t8[t8.fast == 0].kv115.max()
    hi = t8[t8.fast == 1].kv115.min()
    ax.axhspan(lo, hi, color=wash(INK2, 0.10), zorder=0)
    ax.annotate("8x separation band", (0.0163, (lo + hi) / 2),
                fontsize=7.5, color=MUTED, va="center")

    # Firth p(fast) = 0.5 line from the rate+kv115 model
    b = fits["rate+kv115"][0]
    rr = np.linspace(0.016, 0.023, 50)
    ax.plot(rr, -(b[0] + b[1] * rr * 1000.0) / b[2], color=INK2, lw=1.2,
            ls=(0, (4, 2)), label="Firth p(fast)=0.5 (rate+kv115)")

    jit = {}
    for _, row in t.iterrows():
        x = row.rate_eq
        jit[x] = jit.get(x, -1) + 1
        x = x + (jit[x] % 4 - 1.5) * 0.00012
        fast = bool(row.fast)
        color = C_FAST if fast else C_SURV
        marker = "o" if row.N == 8 else "^"
        organic = (not fast) and row.cls == "cold"
        face = "none" if organic else color
        alpha = 0.45 if not row.fit_ok else 1.0
        ax.scatter(x, row.kv115, s=46, marker=marker, facecolor=face,
                   edgecolor=color, linewidth=1.4, alpha=alpha, zorder=3)
    for run, dx, dy in [("ppc-n16-edge037-r2", 0.0002, -0.012),
                        ("ppc-n16-edge034", 0.0002, 0.004),
                        ("ppc-n16-inv040", -0.0009, 0.012)]:
        row = t[t.run == run].iloc[0]
        ax.annotate(run.replace("ppc-", ""), (row.rate_eq, row.kv115),
                    xytext=(row.rate_eq + dx, row.kv115 + dy),
                    fontsize=7, color=INK2)

    from matplotlib.lines import Line2D
    handles = [
        Line2D([], [], marker="o", ls="", mfc=C_FAST, mec=C_FAST,
               label="fast relapse (onset <= 160 min)"),
        Line2D([], [], marker="o", ls="", mfc=C_SURV, mec=C_SURV,
               label="survived the race, clean end"),
        Line2D([], [], marker="o", ls="", mfc="none", mec=C_SURV,
               label="survived the race, organic collapse"),
        Line2D([], [], marker="o", ls="", mfc="none", mec=INK2,
               label="8x fleet"),
        Line2D([], [], marker="^", ls="", mfc="none", mec=INK2,
               label="16x fleet"),
        Line2D([], [], color=INK2, lw=1.2, ls=(0, (4, 2)),
               label="Firth p(fast)=0.5"),
    ]
    ax.legend(handles=handles, fontsize=7.5, frameon=False,
              loc="lower right", labelcolor=INK2)
    ax.set_xlabel("per-8x-equivalent session rate (sps)", fontsize=9)
    ax.set_ylabel("fleet KV occupancy at t=115 min", fontsize=9)
    ax.set_title("Drain-depth separatrix: post-cancel KV vs fast relapse "
                 "(22 measured draws)", fontsize=10)
    ax.set_xlim(0.016, 0.023)
    fig.tight_layout()
    fig.savefig(OUT / "separatrix_fit.png", facecolor=PAGE)
    print("wrote out/separatrix_fit.png")


# -- report -------------------------------------------------------------------

def main():
    t = build_table()
    t.to_csv(OUT / "separatrix_draws.csv", index=False, float_format="%.4f")
    print("wrote out/separatrix_draws.csv")
    pd.set_option("display.width", 200)
    print(t[["run", "N", "rate_eq", "kv110", "kv115", "kv120", "warm_req_s",
             "horizon_min", "truncated", "cls", "t_h50", "fast",
             "fit_ok"]].to_string(index=False))

    print("\n-- leakage check: onset (t_min, start of first h<0.5 window) "
          "per collapsing draw, vs the t=115 reading --")
    for _, row in t[t.collapse == 1].iterrows():
        ok = "OK (sub-0.5 window opens >= 125)" if row.t_h50 >= 125 else (
            "MARGINAL (erosion inside the kv115 window)"
            if row.t_h50 == 115.0 and row.fit_ok else "LEAKED (excluded)")
        print(f"  {row.run:20s} t_h50={row.t_h50:5.0f}  {ok}")

    tf = t[t.fit_ok].copy()
    print(f"\n-- cross-tab over the {len(tf)} fitted draws --")
    ct = tf.groupby(["N", "rate_eq"]).agg(
        draws=("run", "size"), fast=("fast", "sum"),
        collapse=("collapse", "sum"),
        kv115_min=("kv115", "min"), kv115_max=("kv115", "max"))
    print(ct.to_string())

    cc = tf[(tf.collapse == 1) & np.isfinite(tf.t_h50)]
    rho = np.corrcoef(cc.kv115.rank(), cc.t_h50.rank())[0, 1]
    cc2 = cc[cc.run != "ppc-b1a2-rep-base"]
    rho2 = np.corrcoef(cc2.kv115.rank(), cc2.t_h50.rank())[0, 1]
    print(f"\n  measured rank corr (kv115, onset) among collapsing draws: "
          f"{rho:+.2f} (n={len(cc)}); without the onset-marginal draw "
          f"{rho2:+.2f} (n={len(cc2)})")
    m8 = tf[(tf.N == 8) & (tf.rate_eq == 0.020)].kv115
    m16 = tf[(tf.N == 16) & (tf.rate_eq == 0.020)].kv115
    print(f"  mean kv115 at the 0.020-eq point: 8x {m8.mean():.3f} "
          f"(n={len(m8)}) vs 16x {m16.mean():.3f} (n={len(m16)})")

    fits = fit_models(tf)
    print("\n-- Firth-penalized logistic, response = fast relapse "
          f"(n={len(tf)}, events={int(tf.fast.sum())}) --")
    names = {"1": ["b0"], "rate": ["b0", "rate(x1e-3)"],
             "kv115": ["b0", "kv115"],
             "rate+kv115": ["b0", "rate(x1e-3)", "kv115"],
             "rate+N16": ["b0", "rate(x1e-3)", "N16"],
             "rate+N16+kv115": ["b0", "rate(x1e-3)", "N16", "kv115"]}
    for name, (b, se, pl) in fits.items():
        terms = ", ".join(f"{nm}={v:+.2f} (se {s:.2f})"
                          for nm, v, s in zip(names[name], b, se))
        print(f"  {name:16s} penLL {pl:8.3f}   {terms}")
    for full, red, label in [
            ("rate+kv115", "rate", "kv115 | rate"),
            ("rate+N16+kv115", "rate+N16", "kv115 | rate+N16"),
            ("rate+kv115", "kv115", "rate | kv115"),
            ("rate+N16", "rate", "N16 | rate")]:
        lr = 2 * (fits[full][2] - fits[red][2])
        print(f"  penalized LR {label:18s} = {lr:6.2f}, "
              f"p ~ {chi2_sf1(lr):.4f} (1 df)")

    b, se, _ = fits["rate+kv115"]
    for req in (0.017, 0.020, 0.022):
        print(f"  p(fast)=0.5 threshold at rate_eq {req:.3f}: "
              f"kv115* = {-(b[0] + b[1] * req * 1000.0) / b[2]:.3f}")

    t_obs, ge, total = exact_stratified_test(tf)
    print(f"\n-- exact stratified permutation (kv115 rank of fast draws "
          f"within mixed (N, rate) strata) --\n  T_obs={t_obs:.1f}, "
          f"one-sided p = {ge}/{total} = {ge / total:.4f}")

    print("\n-- sensitivity: drop the onset-marginal draw "
          "(ppc-b1a2-rep-base) --")
    ts = tf[tf.run != "ppc-b1a2-rep-base"]
    fs = fit_models(ts)
    lr = 2 * (fs["rate+kv115"][2] - fs["rate"][2])
    bs = fs["rate+kv115"][0]
    print(f"  n={len(ts)}, events={int(ts.fast.sum())}; penalized LR "
          f"kv115 | rate = {lr:.2f}, p ~ {chi2_sf1(lr):.4f}; kv115* at "
          f"rate_eq 0.020 = {-(bs[0] + bs[1] * 20.0) / bs[2]:.3f}")

    print("\n-- sampling-time robustness (8x fitted draws: max survivor "
          "kv vs min fast kv) --")
    t8 = tf[tf.N == 8]
    for col in ("kv110", "kv115", "kv120"):
        lo = t8[t8.fast == 0][col].max()
        hi = t8[t8.fast == 1][col].min()
        sep = "separates" if hi > lo else "OVERLAPS"
        print(f"  {col}: non-fast max {lo:.3f} vs fast min {hi:.3f} -> {sep}")

    des_csv = OUT / "separatrix_des.csv"
    if des_csv.exists():
        d = pd.read_csv(des_csv)
        print("\n-- DES (KvGaugeSim, RouterSessionSim + fleet kv gauge) --")
        print(d.to_string(index=False))
        for pt, g in d.groupby("point"):
            coll = g[g.cls == "cold"]
            surv = g[g.cls != "cold"]
            print(f"  {pt}: collapse {len(coll)}/{len(g)}; kv115 "
                  f"collapsers {coll.kv115.min():.3f}-{coll.kv115.max():.3f}"
                  + (f", survivors {surv.kv115.min():.3f}-"
                     f"{surv.kv115.max():.3f}" if len(surv) else
                     ", no survivors")
                  + f"; mean kv115 {g.kv115.mean():.3f}")
            cc = coll.dropna(subset=["t_h50"])
            if len(cc) >= 3:
                rho = np.corrcoef(cc.kv115.rank(), cc.t_h50.rank())[0, 1]
                print(f"    rank corr (kv115, onset) among collapsers: "
                      f"{rho:+.2f} (n={len(cc)})")
    else:
        print("\n(out/separatrix_des.csv absent; run --des for the DES "
              "comparison)")

    figure(t, fits)


if __name__ == "__main__":
    if "--des" in sys.argv:
        des_sweep()
    else:
        main()
