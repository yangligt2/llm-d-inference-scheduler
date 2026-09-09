"""(c, l) phase diagram and fixed-point map plots for the fluid model.

Outputs (kv_equilibrium/out/):
  phase_diagram.png  - regions over (concurrent sessions, per-node HBM pool),
                       one panel without and one with the CPU offload tier
  fixed_point.png    - one-step map Phi(u) vs u at illustrative configs

Region semantics:
  good      single equilibrium near the structural hit ceiling, TTFT <= 5 s
  bistable  warm and cold seeds converge to different equilibria
  degraded  single equilibrium with depressed hit rate or inflated TTFT
  overload  prefill utilization >= 0.9 or running KV saturates the pool
"""

import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

from fluid_model import (System, Metrics, classify, solve, h_tok_ceiling,
                         gap_cdf_main, gap_cdf_sub, _class_terms,
                         MAIN, SUB, SUB_RATE_RATIO, E_THINK, REGIONS)

# ---------------------------------------------------------------------------
# Palette (dataviz reference instance, light mode).
# ---------------------------------------------------------------------------
SURFACE = "#ffffff"
PAGE = "#ffffff"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
STATUS = {"good": "#0ca30c", "bistable": "#fab219",
          "degraded": "#ec835a", "overload": "#d03b3b"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3


def wash(hex_color, alpha=0.24, surface=SURFACE):
    c = np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], float)
    s = np.array([int(surface[i:i + 2], 16) for i in (1, 3, 5)], float)
    b = s + alpha * (c - s)
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in b)


def style_axes(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)
    ax.title.set_color(INK)


# ---------------------------------------------------------------------------
# Phase diagram sweep.
# ---------------------------------------------------------------------------

L_GRID = np.geomspace(50, 4000, 41)
C_GRID = np.geomspace(2e5, 8e6, 41)


def sweep(c_cpu_fn):
    region_idx = np.zeros((len(C_GRID), len(L_GRID)), dtype=int)
    h_high = np.zeros_like(region_idx, dtype=float)
    for i, c in enumerate(C_GRID):
        for j, l in enumerate(L_GRID):
            sys_ = System(c_hbm=c, c_cpu=c_cpu_fn(c), sessions=l)
            region, hi, lo = classify(sys_)
            region_idx[i, j] = REGIONS.index(region)
            h_high[i, j] = hi.h_tok
    return region_idx, h_high


def label_pos(region_idx, k):
    """Log-space centroid of region k cells, snapped to a cell of that region."""
    cells = np.argwhere(region_idx == k)
    if len(cells) == 0:
        return None
    ci = np.log(C_GRID[cells[:, 0]]).mean()
    lj = np.log(L_GRID[cells[:, 1]]).mean()
    d = (np.log(C_GRID[cells[:, 0]]) - ci) ** 2 + (np.log(L_GRID[cells[:, 1]]) - lj) ** 2
    r, c = cells[np.argmin(d)]
    return L_GRID[c], C_GRID[r]


def plot_phase():
    panels = [
        ("HBM only", lambda c: 0.0),
        ("HBM + 5.7M-token CPU tier per node", lambda c: 5.7e6),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.4), dpi=150)
    fig.patch.set_facecolor(PAGE)
    cmap = ListedColormap([wash(STATUS[r]) for r in REGIONS])
    norm = BoundaryNorm(np.arange(-0.5, len(REGIONS) + 0.5), cmap.N)

    found_bistable = None
    for ax, (title, cpu_fn) in zip(axes, panels):
        region_idx, h_high = sweep(cpu_fn)
        ax.pcolormesh(L_GRID, C_GRID, region_idx, cmap=cmap, norm=norm,
                      shading="nearest")
        ax.set_xscale("log")
        ax.set_yscale("log")
        style_axes(ax)
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlabel("concurrent sessions  l")
        ax.set_ylabel("per-node HBM KV pool  c  (tokens)")
        ax.grid(True, which="major", color=GRID, linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)

        # Hardware-feasible band for the motivating case (mem-frac 0.80/0.87).
        ax.axhline(0.95e6, color=MUTED, linewidth=0.8, linestyle=(0, (4, 3)))
        ax.text(L_GRID[0] * 1.08, 0.95e6 * 1.1, "B200 pool @ mem-frac 0.80",
                fontsize=7.5, color=MUTED)

        # Customer operating point.
        ax.plot(400, 0.95e6, marker="o", markersize=7, markerfacecolor=INK,
                markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=5)
        ax.annotate("customer\n(l=400, 10 rps)", (400, 0.95e6),
                    textcoords="offset points", xytext=(8, -26),
                    fontsize=8, color=INK)

        for k, r in enumerate(REGIONS):
            pos = label_pos(region_idx, k)
            if pos is not None and (region_idx == k).sum() >= 12:
                ax.text(pos[0], pos[1], r, fontsize=9.5, color=INK,
                        ha="center", va="center", fontweight="bold")
            if r == "bistable" and (region_idx == k).sum() > 0 and found_bistable is None:
                cells = np.argwhere(region_idx == k)
                r0, c0 = cells[len(cells) // 2]
                found_bistable = (C_GRID[r0], L_GRID[c0], cpu_fn(C_GRID[r0]), title)

    handles = [Patch(facecolor=wash(STATUS[r]), edgecolor=STATUS[r], label=r)
               for r in REGIONS]
    axes[1].legend(handles=handles, loc="lower left", fontsize=8, frameon=False,
                   labelcolor=INK2)
    fig.suptitle("KV cache equilibrium regions  (N=16, perfect prefix routing, "
                 "CC-trace workload)", fontsize=12, color=INK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig("kv_equilibrium/out/phase_diagram.png", facecolor=PAGE)
    plt.close(fig)
    return found_bistable


# ---------------------------------------------------------------------------
# One-step fixed-point map Phi(u): assume hit prob u, compute realized hit prob.
# ---------------------------------------------------------------------------


def phi(sys_: System, u: float, state=None, iters: int = 5000):
    """One-step map: realized hit prob given assumed hit prob u.

    Inner loop settles lambda/TTFT/T_hbm at fixed u; warm-startable via state.
    """
    a = sys_.routing_accuracy
    n = sys_.n_nodes
    ttft, t_hbm = state if state is not None else (1.0, 10.0)
    for _ in range(iters):
        uh = min(a * gap_cdf_main(t_hbm), u)
        us_h = min(a * gap_cdf_sub(t_hbm), u)
        cm, pm, prm, wm, rm = _class_terms(MAIN, u, uh)
        cs, ps, prs, ws, rs = _class_terms(SUB, u, us_h)
        cycle = E_THINK + ttft + MAIN.d_out * sys_.tpot
        lam_m = sys_.sessions / cycle
        lam_s = SUB_RATE_RATIO * lam_m
        lam = lam_m + lam_s
        s_m, s_s = pm / sys_.p_tpt, ps / sys_.p_tpt
        es = (lam_m * s_m + lam_s * s_s) / lam
        es2 = (lam_m * s_m ** 2 + lam_s * s_s ** 2) / lam * (1 + sys_.cv2_prefill)
        rho_p = min(lam / n * es, 0.999)
        wq = min((lam / n) * es2 / (2 * (1 - rho_p)), 1800.0)
        svc_m = s_m + MAIN.d_out * sys_.tpot
        svc_s = s_s + SUB.d_out * sys_.tpot
        running = (lam_m * svc_m * (prm + MAIN.d_out)
                   + lam_s * svc_s * (prs + SUB.d_out)) / n
        kv_mix = (lam_m * (prm + MAIN.d_out) + lam_s * (prs + SUB.d_out)) / lam
        m_slots = max(n * sys_.c_hbm / kv_mix, 1.0)
        rk = min(running / sys_.c_hbm, 0.999)
        svc_mix = (lam_m * svc_m + lam_s * svc_s) / lam
        w_slot = min(svc_mix * rk ** (math.sqrt(2 * (m_slots + 1)) - 1)
                     / (m_slots * (1 - rk)), 1800.0)
        ttft_new = min(wq + w_slot + es, 1800.0)
        c_eff = max(sys_.c_hbm - running, 0.05 * sys_.c_hbm)
        w_new = lam_m * wm + lam_s * ws
        w_hbm = w_new + lam_m * rm + lam_s * rs
        t_hbm_new = n * c_eff / w_hbm
        resid = max(abs(math.log(ttft_new / ttft)), abs(math.log(t_hbm_new / t_hbm)))
        ttft = math.exp(0.9 * math.log(ttft) + 0.1 * math.log(ttft_new))
        t_hbm = math.exp(0.9 * math.log(t_hbm) + 0.1 * math.log(t_hbm_new))
        if resid < 1e-10:
            break
    t_tot = t_hbm + (n * sys_.c_cpu / w_new if sys_.c_cpu > 0 else 0.0)
    out = (lam_m * a * gap_cdf_main(t_tot) + lam_s * a * gap_cdf_sub(t_tot)) / lam
    return out, (ttft, t_hbm)


RPS_GRID = np.geomspace(2, 40, 41)


def plot_phase_open():
    """Open-loop variant: fixed offered rps, no cycle feedback (the benchmark
    and fixed-rate-producer regime). This is where bistability lives."""
    panels = [
        ("HBM only", 0.0),
        ("HBM + 5.7M-token CPU tier per node", 5.7e6),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.4), dpi=150)
    fig.patch.set_facecolor(PAGE)
    cmap = ListedColormap([wash(STATUS[r]) for r in REGIONS])
    norm = BoundaryNorm(np.arange(-0.5, len(REGIONS) + 0.5), cmap.N)

    for ax, (title, cpu) in zip(axes, panels):
        region_idx = np.zeros((len(C_GRID), len(RPS_GRID)), dtype=int)
        for i, c in enumerate(C_GRID):
            for j, r in enumerate(RPS_GRID):
                region, hi, lo = classify(System(c_hbm=c, c_cpu=cpu,
                                                 open_loop_rps=r))
                region_idx[i, j] = REGIONS.index(region)
        ax.pcolormesh(RPS_GRID, C_GRID, region_idx, cmap=cmap, norm=norm,
                      shading="nearest")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xticks([2, 5, 10, 20, 40], labels=["2", "5", "10", "20", "40"])
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        style_axes(ax)
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlabel("offered load  (req/s, fixed)")
        ax.set_ylabel("per-node HBM KV pool  c  (tokens)")
        ax.grid(True, which="major", color=GRID, linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axhline(0.95e6, color=MUTED, linewidth=0.8, linestyle=(0, (4, 3)))
        ax.text(RPS_GRID[0] * 1.06, 0.95e6 * 1.1, "B200 pool @ mem-frac 0.80",
                fontsize=7.5, color=MUTED)
        ax.plot(10, 0.95e6, marker="o", markersize=7, markerfacecolor=INK,
                markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=5)
        ax.annotate("customer (10 rps)", (10, 0.95e6),
                    textcoords="offset points", xytext=(8, -20),
                    fontsize=8, color=INK)
        for k, r in enumerate(REGIONS):
            pos_cells = np.argwhere(region_idx == k)
            if len(pos_cells) >= 12:
                if r == "bistable":
                    # Band-shaped: label the lower-left quarter of the band
                    # to keep clear of the customer marker.
                    order = np.argsort(pos_cells[:, 1])
                    r0, c0 = pos_cells[order[len(order) // 5]]
                else:
                    ci = np.log(C_GRID[pos_cells[:, 0]]).mean()
                    lj = np.log(RPS_GRID[pos_cells[:, 1]]).mean()
                    d = ((np.log(C_GRID[pos_cells[:, 0]]) - ci) ** 2
                         + (np.log(RPS_GRID[pos_cells[:, 1]]) - lj) ** 2)
                    r0, c0 = pos_cells[np.argmin(d)]
                ax.text(RPS_GRID[c0], C_GRID[r0], r, fontsize=9.5, color=INK,
                        ha="center", va="center", fontweight="bold")

    handles = [Patch(facecolor=wash(STATUS[r]), edgecolor=STATUS[r], label=r)
               for r in REGIONS]
    axes[1].legend(handles=handles, loc="lower left", fontsize=8, frameon=False,
                   labelcolor=INK2)
    fig.suptitle("Open-loop (fixed offered rate) equilibrium regions  "
                 "(N=16, perfect prefix routing, CC-trace workload)",
                 fontsize=12, color=INK, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig("kv_equilibrium/out/phase_diagram_open.png", facecolor=PAGE)
    plt.close(fig)


def plot_fixed_point(bistable_cfg):
    configs = [
        ("customer, HBM only", System(c_hbm=0.95e6, c_cpu=0.0, sessions=400), SERIES[0]),
        ("customer, HBM + CPU", System(c_hbm=0.95e6, c_cpu=5.7e6, sessions=400), SERIES[1]),
    ]
    if bistable_cfg is not None:
        c, l, cpu, _ = bistable_cfg
        configs.append((f"bistable cell (c={c / 1e6:.2f}M, l={l:.0f})",
                        System(c_hbm=c, c_cpu=cpu, sessions=l), SERIES[2]))

    us = np.linspace(0.001, 0.999, 60)
    fig, ax = plt.subplots(figsize=(6.8, 5.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    style_axes(ax)
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1.0, linestyle=(0, (4, 3)))
    ax.text(0.545, 0.575, "identity", fontsize=8, color=MUTED, rotation=38)

    for label, sys_, color in configs:
        ys, state = [], None
        for u in us:
            y, state = phi(sys_, u, state)
            ys.append(y)
        ax.plot(us, ys, color=color, linewidth=2.0, label=label)
        # Mark stable crossings (sign changes of Phi(u)-u, downward).
        diff = np.array(ys) - us
        for k in range(1, len(us)):
            if diff[k - 1] > 0 >= diff[k] or diff[k - 1] >= 0 > diff[k]:
                x = us[k - 1] + (us[k] - us[k - 1]) * diff[k - 1] / (diff[k - 1] - diff[k])
                ax.plot(x, x, marker="o", markersize=7, markerfacecolor=color,
                        markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=5)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("assumed hit probability  u")
    ax.set_ylabel("realized hit probability  Phi(u)")
    ax.set_title("Fixed-point map: equilibria are crossings with the identity",
                 fontsize=11, pad=10)
    ax.legend(loc="lower right", fontsize=8.5, frameon=False, labelcolor=INK2)
    fig.tight_layout()
    fig.savefig("kv_equilibrium/out/fixed_point.png", facecolor=PAGE)
    plt.close(fig)


def c_crit_table():
    print("\nminimum per-node HBM pool c for region 'good' (N=16):")
    print(f"  {'l':>6}  {'HBM only':>12}  {'HBM + CPU':>12}")
    for l in (100, 200, 400, 800, 1600, 3200):
        row = []
        for cpu in (0.0, 5.7e6):
            crit = None
            for c in C_GRID:
                region, _, _ = classify(System(c_hbm=c, c_cpu=cpu, sessions=l))
                if region == "good":
                    crit = c
                    break
            row.append(f"{crit / 1e6:.2f}M" if crit else "none")
        print(f"  {l:>6}  {row[0]:>12}  {row[1]:>12}")


if __name__ == "__main__":
    import os
    import sys as _argv
    os.makedirs("kv_equilibrium/out", exist_ok=True)
    if "fixedpoint" in _argv.argv:
        # Skip the sweeps; reuse the bistable cell found by the last full run.
        plot_fixed_point((0.289e6, 621.0, 0.0, "HBM only"))
        print("wrote kv_equilibrium/out/fixed_point.png")
    elif "openloop" in _argv.argv:
        plot_phase_open()
        print("wrote kv_equilibrium/out/phase_diagram_open.png")
    else:
        bistable_cfg = plot_phase()
        print("bistable example cell:", bistable_cfg)
        plot_phase_open()
        plot_fixed_point(bistable_cfg)
        c_crit_table()
        print("wrote kv_equilibrium/out/*.png")
