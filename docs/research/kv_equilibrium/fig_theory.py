"""Theory-section figures for the paper, GB200 calibration throughout.

Three figures, written to out/paper/:

  fig_fixed_point.png   (a) the conditional cache map Phi(u | backlog)
                        at 0.022 sessions/s: queue-free vs backlogged
                        branches of the one-step hit-rate map;
                        (b) the (hit rate, backlog) phase plane with
                        basins of attraction, equilibria, and the
                        drain-race separatrix.
  fig_hysteresis.png    DES branch diagram: end-state hit rate vs
                        session rate for the unperturbed protocol
                        (warm branch) and the standard-surge protocol
                        (post-perturbation state), deployed-router
                        model, no offload, N=8, 300-min horizon.
  fig_phase_diagram.png DES outcome map over (session rate, effective
                        tier capacity) under the standard perturbation
                        protocol, 300-min horizon.

The map/phase-plane constructions use the trace-calibrated workload
functionals of fluid_model.py with the experiment gap cap (10.5 s) and
the measured GB200 constants of overlay_fixedpoint.py / des_b1.py. The
phase plane models the post-cancellation drain window, where demand is
a deferred reservoir draining at full flux (inelastic); its time
normalization is qualitative (fixed hit-rate relaxation constant), so
the figure shows equilibrium and basin structure, not calibrated
transit times.

Run from kv_equilibrium/:  ../.venv/bin/python fig_theory.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import fluid_model as fm
from fluid_model import MAIN, SUB, SUB_RATE_RATIO, _class_terms
import overlay_fixedpoint as ofp
from des_b1 import RouterSessionSim, TIER_EFF
from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out" / "paper"

# GB200 constants (provenance: paper constants table / overlay_fixedpoint.py)
N = 8
C_HBM = 6486 * 256.0          # tokens per replica
POOL = N * C_HBM
P_TPT = 17_000.0              # tokens/s per replica
TPOT = 0.015                  # s/token, mid measured warm range
E_REQ = 118.0                 # realized requests per session
WATERMARK = 0.92
GAP_CAP = 10.5
Q_SOFT = 10.0                 # backlog scale over which admission pins KV

ofp.set_gap_cap(GAP_CAP)

LM, LS = 1.0, SUB_RATE_RATIO
TOT = LM + LS
NN_M = 1.0 - MAIN.f_first - MAIN.f_comp
NN_S = 1.0 - SUB.f_first - SUB.f_comp


def mix_terms(u):
    """Per-request expectations at normal-turn hit probability u."""
    cm, pm, prm, wm, _ = _class_terms(MAIN, u, u)
    cs, ps, prs, ws, _ = _class_terms(SUB, u, u)
    prefill = (LM * pm + LS * ps) / TOT
    write = (LM * wm + LS * ws) / TOT
    kv = (LM * (prm + MAIN.d_out) + LS * (prs + SUB.d_out)) / TOT
    return prefill, write, kv


def phi(u, q, lam_r):
    """One-step hit-rate map at backlog q (requests fleet-wide).

    Retention window from the pool net of running-request residency
    (pinned to the admission watermark while a backlog exists), survival
    window net of the queueing delay q / mu(u).
    """
    prefill, write, kv = mix_terms(u)
    mu = N * P_TPT / prefill                     # prefill-bound service rate
    svc = prefill / P_TPT + MAIN.d_out * TPOT
    occ_run = min(lam_r * svc * kv / POOL, WATERMARK)
    occ = occ_run + (WATERMARK - occ_run) * q / (q + Q_SOFT)
    t_ret = POOL * (1.0 - occ) / (lam_r * write)
    surv = t_ret - q / mu
    um = fm.gap_cdf_main(surv)
    us = fm.gap_cdf_sub(surv)
    return (LM * NN_M * um + LS * NN_S * us) / (LM * NN_M + LS * NN_S), mu


def drain_flow(u, q, lam_r, tau_h=60.0):
    """(du/dt, dq/dt) during the post-cancellation drain window."""
    p, mu = phi(u, q, lam_r)
    return (p - u) / tau_h, lam_r - mu if (q > 0 or lam_r > mu) else 0.0


def fig_fixed_point():
    lam_r = 0.022 * E_REQ
    us = np.linspace(0.0, 1.0, 201)

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11, 4.6), dpi=150)
    fig.patch.set_facecolor(PAGE)

    # (a) conditional maps: backlog level tilts the map from monostable
    # warm (Q=0) through bistable (Q=60) to monostable cold (Q=150)
    for q, color, label in ((0.0, SERIES[0], "Q = 0"),
                            (60.0, SERIES[2], "Q = 60"),
                            (150.0, SERIES[1], "Q = 150")):
        ph = [phi(u, q, lam_r)[0] for u in us]
        ax_a.plot(us, ph, color=color, lw=1.8, label=label)
    ax_a.plot([0, 1], [0, 1], color=INK2, lw=0.9, ls=(0, (3, 2)))
    ax_a.set_ylim(-0.03, 1.05)
    ax_a.set_xlabel("hit probability u", fontsize=9)
    ax_a.set_ylabel("$\\Phi(u \\mid Q)$", fontsize=9)
    ax_a.set_title("(a) cache map, conditional on backlog\n"
                   "$\\lambda_s$ = 0.022 sessions/s, N = 8, no offload",
                   fontsize=9.5)
    ax_a.legend(fontsize=8, frameon=False, loc="center right",
                labelcolor=INK2)
    uw = 0.9
    for _ in range(200):
        uw = phi(uw, 0.0, lam_r)[0]
    ax_a.plot([uw], [uw], "o", color=SERIES[0], ms=6, zorder=5)
    ax_a.annotate("warm", (uw, uw), xytext=(uw - 0.22, uw - 0.09),
                  fontsize=8.5, color=INK2)
    ax_a.plot([0], [phi(0.0, 150.0, lam_r)[0]], "o", color=SERIES[1],
              ms=6, zorder=5)
    ax_a.annotate("cold", (0.0, 0.0), xytext=(0.05, 0.05), fontsize=8.5,
                  color=INK2)

    # (b) basins in the (u, Q) plane
    ugrid = np.linspace(0.0, 1.0, 61)
    qgrid = np.linspace(0.0, 400.0, 61)
    basin = np.zeros((len(qgrid), len(ugrid)))
    for i, q0 in enumerate(qgrid):
        for j, u0 in enumerate(ugrid):
            u, q = u0, q0
            for _ in range(400):
                du, dq = drain_flow(u, q, lam_r)
                u = min(max(u + 10.0 * du, 0.0), 1.0)
                q = max(q + 10.0 * dq, 0.0)
                if q > 2000.0:
                    break
            basin[i, j] = 1.0 if (q <= 1.0 and u > 0.5) else 0.0
    ax_b.contourf(ugrid, qgrid, basin, levels=[-0.5, 0.5, 1.5],
                  colors=[wash(SERIES[1], 0.30), wash(SERIES[0], 0.30)])
    ax_b.contour(ugrid, qgrid, basin, levels=[0.5], colors=[INK],
                 linewidths=1.4)
    # sparse flow arrows
    for u0 in np.linspace(0.05, 0.95, 8):
        for q0 in np.linspace(15, 380, 7):
            du, dq = drain_flow(u0, q0, lam_r)
            nrm = np.hypot(du / 0.02, dq / 8.0)
            if nrm > 0:
                ax_b.annotate("", xytext=(u0, q0),
                              xy=(u0 + 0.028 * du / 0.02 / nrm,
                                  q0 + 11.0 * dq / 8.0 / nrm),
                              arrowprops=dict(arrowstyle="->", lw=0.7,
                                              color=INK2, alpha=0.7))
    ax_b.plot([uw], [0], "o", color=SERIES[0], ms=7, zorder=5,
              clip_on=False)
    ax_b.annotate("warm equilibrium", (uw, 2), xytext=(0.50, 45),
                  fontsize=8.5, color=INK2,
                  arrowprops=dict(arrowstyle="->", lw=0.8, color=INK2))
    ax_b.annotate("cold absorbing region\n(backlog diverges)",
                  (0.12, 330), fontsize=8.5, color=INK2)
    ax_b.annotate("separatrix", (0.66, 150), fontsize=8.5, color=INK)
    ax_b.set_xlabel("hit probability u", fontsize=9)
    ax_b.set_ylabel("backlog Q (waiting requests)", fontsize=9)
    ax_b.set_title("(b) drain-window phase plane, basins of attraction\n"
                   "time normalization qualitative", fontsize=9.5)

    for ax in (ax_a, ax_b):
        style_axes(ax)
        ax.grid(True, color=GRID, lw=0.6, alpha=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "fig_fixed_point.png", facecolor=PAGE)
    plt.close(fig)
    print(f"fixed-point figure done (warm equilibrium u = {uw:.3f})")


# ---------------------------------------------------------------------------
# DES figures
# ---------------------------------------------------------------------------

T_END_MIN = 300
SEEDS = (1, 2, 3)


def end_metrics(win):
    end = win[(win.t_min > 270) & (win.t_min <= 295)]
    mid = win[(win.t_min > 200) & (win.t_min <= 240)]
    return dict(end_h=end.h.mean(), end_wait=end.wait.mean(),
                mid_wait=mid.wait.mean())


def classify(m):
    if m["end_h"] < 0.15:
        return "cold"
    if m["end_h"] > 0.8 and m["end_wait"] < 30:
        return "recovered"
    if m["end_wait"] > 30 and m["end_wait"] > m["mid_wait"]:
        return "congested"
    return "degraded"


def des_run(lam_base, c_cpu, seed, surge=True):
    sim = RouterSessionSim(N, lam_base, 0.25 if surge else 1e-9, c_cpu,
                           seed, t_end=T_END_MIN * 60.0)
    sim.run()
    return end_metrics(sim.windows())


def fig_hysteresis():
    rates = (0.010, 0.012, 0.014, 0.017, 0.020, 0.022, 0.024)
    rows = []
    for r in rates:
        for seed in SEEDS:
            for surge in (False, True):
                m = des_run(r, 0.0, seed, surge=surge)
                m.update(rate=r, seed=seed, surge=surge,
                         outcome=classify(m))
                rows.append(m)
                print(f"  hyst rate {r:.3f} seed {seed} "
                      f"{'surge' if surge else 'plain'}: h {m['end_h']:.2f} "
                      f"wait {m['end_wait']:.0f} -> {m['outcome']}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "fig_hysteresis.csv", index=False, float_format="%.4f")

    fig, ax = plt.subplots(figsize=(7.4, 4.4), dpi=150)
    fig.patch.set_facecolor(PAGE)
    jit = {1: -0.00025, 2: 0.0, 3: 0.00025}
    for surge, color, mk, off, label in (
            (False, SERIES[0], "o", -0.0004, "unperturbed (warm branch)"),
            (True, SERIES[1], "s", 0.0004, "after the standard surge")):
        sub = df[df.surge == surge]
        ax.scatter(sub.rate + off + sub.seed.map(jit), sub.end_h, s=30,
                   marker=mk, color=color, label=label, zorder=4,
                   edgecolors=PAGE, linewidths=0.5)
    ax.axvspan(0.017, 0.022, color=wash(SERIES[2], 0.18), zorder=0)
    ax.annotate("coexistence band", (0.0185, 0.5), fontsize=8.5,
                color=INK2, ha="center")
    ax.set_xlabel("session arrival rate $\\lambda_s$ (sessions/s)",
                  fontsize=9)
    ax.set_ylabel("end-state hit rate (270-295 min)", fontsize=9)
    ax.set_ylim(-0.03, 1.03)
    ax.legend(fontsize=8, frameon=False, loc="center left",
              labelcolor=INK2)
    ax.set_title("Warm and post-perturbation states vs load "
                 "(deployed-router model, N = 8, no offload, "
                 f"{len(SEEDS)} seeds)", fontsize=9.5)
    style_axes(ax)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "fig_hysteresis.png", facecolor=PAGE)
    plt.close(fig)
    print("hysteresis figure done")


def fig_phase_diagram():
    rates = (0.014, 0.017, 0.020, 0.022, 0.025)
    caps = ((0.0, "none"),
            (TIER_EFF * 0.63e6, "0.42M\n(size 250)"),
            (TIER_EFF * 0.945e6, "0.63M\n(size 375)"),
            (TIER_EFF * 1.26e6, "0.84M\n(size 500)"))
    order = ("recovered", "degraded", "congested", "cold")
    colors = {"recovered": SERIES[0], "degraded": "#8a6fc8",
              "congested": SERIES[2], "cold": SERIES[1]}
    rows = []
    for ci, (c_cpu, clabel) in enumerate(caps):
        for ri, r in enumerate(rates):
            outs = []
            for seed in SEEDS:
                m = des_run(r, c_cpu, seed, surge=True)
                m.update(rate=r, c_cpu=c_cpu, seed=seed,
                         outcome=classify(m))
                rows.append(m)
                outs.append(m["outcome"])
            print(f"  phase cap {clabel.splitlines()[0]} rate {r:.3f}: "
                  f"{outs}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "fig_phase_diagram.csv", index=False,
              float_format="%.4f")

    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    for ci, (c_cpu, clabel) in enumerate(caps):
        for ri, r in enumerate(rates):
            cell = df[(df.c_cpu == c_cpu) & (df.rate == r)]
            n = len(cell)
            x0 = ri
            for oi, out in enumerate(order):
                k = (cell.outcome == out).sum()
                if k == 0:
                    continue
                ax.bar(x0 + 0.5, 0.9 * k / n, width=0.92,
                       bottom=ci + 0.05 + 0.9 * (cell.outcome
                                                 .isin(order[:oi])).sum() / n,
                       color=wash(colors[out], 0.75), edgecolor=PAGE,
                       linewidth=0.8, zorder=3)
    ax.set_xticks(np.arange(len(rates)) + 0.5)
    ax.set_xticklabels([f"{r:.3f}" for r in rates], fontsize=8.5)
    ax.set_yticks(np.arange(len(caps)) + 0.5)
    ax.set_yticklabels([c[1] for c in caps], fontsize=8.5)
    ax.set_xlabel("session arrival rate $\\lambda_s$ (sessions/s)",
                  fontsize=9)
    ax.set_ylabel("effective host-tier capacity per replica (tokens)",
                  fontsize=9)
    ax.set_xlim(0, len(rates))
    ax.set_ylim(0, len(caps))
    ax.legend(handles=[Patch(facecolor=wash(colors[o], 0.75), label=o)
                       for o in order],
              fontsize=8, frameon=False, ncols=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.13), labelcolor=INK2)
    ax.set_title("Outcome of the standard perturbation over "
                 "(load, tier capacity)\n(deployed-router model, N = 8, "
                 f"{len(SEEDS)} seeds per cell, 300-min horizon)",
                 fontsize=9.5)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(OUT / "fig_phase_diagram.png", facecolor=PAGE)
    plt.close(fig)
    print("phase-diagram figure done")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_fixed_point()
    fig_hysteresis()
    fig_phase_diagram()
