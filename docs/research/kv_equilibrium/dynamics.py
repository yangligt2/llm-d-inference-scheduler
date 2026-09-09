"""Time-domain demonstration of the bistable band.

Two figures (kv_equilibrium/out/):

  hysteresis.png  - equilibrium hit rate vs offered rps, swept up then down by
                    warm-started continuation. The gap between the collapse
                    point (up-sweep) and the recovery point (down-sweep) is the
                    hysteresis loop; its width is the bistable band.

  disruption.png  - fluid trajectory at fixed 10 rps, bounded queue (requests
                    are shed once queue wait reaches 30 s, as real gateways
                    time out). A 2-minute 2x burst knocks the HBM-only system
                    into the bad state, where it STAYS after the burst ends;
                    the CPU tier version absorbs the same burst and recovers
                    unaided. A deliberate load shed to 1 rps later walks the
                    HBM-only system back to the good state.

Dynamic state per configuration:
  A_h  HBM age coverage (s): a prefix hits HBM iff last touched < A_h ago
  A_c  additional CPU-tier coverage (s)
  B    prefill backlog (tokens); queue wait Wq = B / fleet prefill rate
A prefix must survive think gap + queue wait, so hit prob = F(A - Wq).
Coverage grows at most 1 s/s (content can only age in real time) and shrinks
on the pool-overwrite timescale. This asymmetry is why collapse is fast and
recovery is slow.
"""

import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fluid_model import (System, solve, gap_cdf_main, gap_cdf_sub, _class_terms,
                         MAIN, SUB, SUB_RATE_RATIO)
from phase_diagram import (SURFACE, PAGE, INK, INK2, MUTED, GRID, BASELINE,
                           SERIES, style_axes, wash)

N = 16
P_TPT = 10_000.0
CAP = N * P_TPT
C_HBM = 0.95e6
WQ_MAX = 30.0          # gateway timeout: shed arrivals once wait reaches this
DT = 0.5


def step(state, lam, c_cpu):
    """Advance one DT; returns (state, record).

    Two serving bottlenecks, both expressed in req/s: fleet prefill token
    throughput, and KV residency slots (running requests must fit in HBM).
    A single request backlog b_req queues against the tighter one.
    """
    a_h, a_c, b_req, wq = state
    lam_m = lam / (1.0 + SUB_RATE_RATIO)
    lam_s = lam - lam_m

    a_tot = a_h + a_c
    u_m = gap_cdf_main(max(a_tot - wq, 0.0))
    u_s = gap_cdf_sub(max(a_tot - wq, 0.0))
    uh_m = min(gap_cdf_main(max(a_h - wq, 0.0)), u_m)
    uh_s = min(gap_cdf_sub(max(a_h - wq, 0.0)), u_s)

    cm, pm, prm, wm, rm = _class_terms(MAIN, u_m, uh_m)
    cs, ps, prs, ws, rs = _class_terms(SUB, u_s, uh_s)

    s_m, s_s = pm / P_TPT, ps / P_TPT
    prefill_mix = (lam_m * pm + lam_s * ps) / lam
    svc_m = s_m + MAIN.d_out * 0.012
    svc_s = s_s + SUB.d_out * 0.012
    svc_mix = (lam_m * svc_m + lam_s * svc_s) / lam
    kv_mix = (lam_m * (prm + MAIN.d_out) + lam_s * (prs + SUB.d_out)) / lam

    cap_pre = CAP / prefill_mix                       # req/s, prefill-bound
    m_slots = max(N * C_HBM / kv_mix, 1.0)
    cap_slot = m_slots / svc_mix                      # req/s, residency-bound
    cap_req = min(cap_pre, cap_slot)

    wq_fluid = b_req / cap_req
    admitted = lam if wq_fluid < WQ_MAX else min(lam, cap_req)
    scale = admitted / lam
    b_req = max(0.0, b_req + (admitted - cap_req) * DT)

    # Stochastic waits below saturation: M/G/1 per node for prefill,
    # M/M/m (Sakasegawa) for the slot pool.
    es2 = (lam_m * s_m ** 2 + lam_s * s_s ** 2) / lam * 2.0
    rho_pre = min(admitted / cap_pre, 0.999)
    wq_pre = min((admitted / N) * es2 / (2 * (1 - rho_pre)), WQ_MAX)
    rho_slot = min(admitted / cap_slot, 0.999)
    w_slot = min(svc_mix * rho_slot ** (math.sqrt(2 * (m_slots + 1)) - 1)
                 / (m_slots * (1 - rho_slot)), WQ_MAX)
    wq_new = min(wq_fluid, WQ_MAX) + wq_pre + w_slot

    w_new = scale * (lam_m * wm + lam_s * ws)
    w_hbm = w_new + scale * (lam_m * rm + lam_s * rs)
    running = min(admitted * svc_mix * kv_mix / N, 0.95 * C_HBM)
    c_eff = max(C_HBM - running, 0.05 * C_HBM)

    a_h_t = N * c_eff / w_hbm if w_hbm > 0 else 1e9
    a_c_t = N * c_cpu / w_new if (c_cpu > 0 and w_new > 0) else 0.0

    def relax(a, tgt):
        if a < tgt:
            return a + DT * min(1.0, (tgt - a) / max(tgt, 1.0))
        return a + DT * (tgt - a) / max(tgt, 2.0)

    a_h = relax(a_h, a_h_t)
    a_c = relax(a_c, a_c_t)

    h_tok = (lam_m * cm + lam_s * cs) / (lam_m * prm + lam_s * prs)
    ttft = wq_new + prefill_mix / P_TPT
    return (a_h, a_c, b_req, wq_new), (h_tok, ttft, admitted)


def run_scenario(c_cpu, schedule, t_end):
    """schedule: list of (t_start, rps); piecewise-constant offered load."""
    state = (30.0, 1500.0 if c_cpu > 0 else 0.0, 0.0, 0.0)
    for _ in range(int(600 / DT)):                       # warm pre-roll
        state, _ = step(state, schedule[0][1], c_cpu)
    ts, hs, ttfts, served, offered = [], [], [], [], []
    t = 0.0
    while t < t_end:
        rps = [r for (t0, r) in schedule if t >= t0][-1]
        state, (h, ttft, sv) = step(state, rps, c_cpu)
        ts.append(t / 60.0)
        hs.append(h)
        ttfts.append(ttft)
        served.append(sv)
        offered.append(rps)
        t += DT
    return tuple(np.array(x) for x in (ts, hs, ttfts, served, offered))


def plot_disruption():
    # Baseline 9 rps sits inside the bistable band (8.0 - 10.8 rps) on the
    # good branch; the burst knocks it to the bad branch, which persists at
    # 9 rps; recovery requires shedding below the band's lower edge.
    schedule = [(0, 9.0), (300, 18.0), (420, 9.0), (1080, 1.0), (1260, 9.0)]
    t_end = 1800
    runs = {
        "HBM only": (0.0, SERIES[0]),
        "HBM + CPU tier": (5.7e6, SERIES[1]),
    }
    fig, axes = plt.subplots(3, 1, figsize=(9.5, 8.2), dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)

    results = {}
    for label, (c_cpu, color) in runs.items():
        results[label] = run_scenario(c_cpu, schedule, t_end)

    ax = axes[0]
    ts, _, _, _, offered = results["HBM only"]
    ax.step(ts, offered, where="post", color=MUTED, linewidth=1.2)
    ax.text(ts[10], 18.6, "offered", fontsize=8, color=MUTED)
    for label, (c_cpu, color) in runs.items():
        ts, _, _, served, _ = results[label]
        ax.plot(ts, served, color=color, linewidth=1.8, label=label)
    ax.set_ylabel("req/s", fontsize=9)
    ax.set_ylim(0, 23)
    ax.set_title("Burst -> collapse -> deliberate shed -> recovery  "
                 "(open loop, 16 nodes, c=0.95M tokens)", fontsize=11, pad=10)
    ax.legend(loc="center right", fontsize=8.5, frameon=False, labelcolor=INK2)

    ax = axes[1]
    for label, (c_cpu, color) in runs.items():
        ts, hs, _, _, _ = results[label]
        ax.plot(ts, hs, color=color, linewidth=1.8)
    ax.set_ylabel("token hit rate", fontsize=9)
    ax.set_ylim(0, 1.02)

    ax = axes[2]
    for label, (c_cpu, color) in runs.items():
        ts, _, ttfts, _, _ = results[label]
        ax.plot(ts, ttfts, color=color, linewidth=1.8)
    ax.set_yscale("log")
    ax.set_ylabel("TTFT (s)", fontsize=9)
    ax.set_xlabel("time (minutes)", fontsize=9)

    for ax in axes:
        style_axes(ax)
        ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axvspan(5, 7, color=wash("#d03b3b", 0.15), zorder=0)
        ax.axvspan(18, 21, color=wash("#2a78d6", 0.12), zorder=0)
    axes[0].text(5.1, 1.5, "2x burst", fontsize=8, color=INK2)
    axes[0].text(18.1, 1.5, "shed to 1 rps", fontsize=8, color=INK2)

    fig.align_ylabels(axes)
    fig.tight_layout()
    fig.savefig("kv_equilibrium/out/disruption.png", facecolor=PAGE)
    plt.close(fig)


def plot_hysteresis():
    rps_up = np.linspace(2, 24, 89)
    fig, ax = plt.subplots(figsize=(7.6, 5.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    style_axes(ax)

    stats = {}
    for label, c_cpu, color in (("HBM only", 0.0, SERIES[0]),
                                ("HBM + CPU tier", 5.7e6, SERIES[1])):
        for direction, grid, ls in (("up", rps_up, "-"),
                                    ("down", rps_up[::-1], (0, (4, 2)))):
            init = None
            xs, ys = [], []
            for r in grid:
                m = solve(System(c_hbm=C_HBM, c_cpu=c_cpu, open_loop_rps=r),
                          seed_hit=1.0 if direction == "up" and init is None else 0.0,
                          init=init)
                init = (m.t_hbm, m.t_tot, m.ttft)
                xs.append(r)
                ys.append(m.h_tok)
            stats[(label, direction)] = (np.array(xs), np.array(ys))
            ax.plot(xs, ys, color=color, linewidth=2.0, linestyle=ls,
                    label=f"{label}, sweep {direction}")

    # Annotate the jump points of the HBM-only loop.
    xu, yu = stats[("HBM only", "up")]
    drop = np.argmax(np.diff(yu) < -0.15) if np.any(np.diff(yu) < -0.15) else None
    if drop is not None:
        ax.annotate("collapse", (xu[drop], yu[drop]), textcoords="offset points",
                    xytext=(10, 12), fontsize=8.5, color=INK,
                    arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
    xd, yd = stats[("HBM only", "down")]
    rec = np.argmax(np.diff(yd) > 0.15) if np.any(np.diff(yd) > 0.15) else None
    if rec is not None:
        ax.annotate("recovery", (xd[rec + 1], yd[rec + 1]),
                    textcoords="offset points", xytext=(12, -14), fontsize=8.5,
                    color=INK, arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))

    ax.set_xlabel("offered load (req/s, fixed)")
    ax.set_ylabel("equilibrium token hit rate")
    ax.set_ylim(0, 1.02)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.set_title("Hysteresis loop: where you are depends on where you came from",
                 fontsize=11, pad=10)
    ax.legend(loc="lower left", fontsize=8.5, frameon=False, labelcolor=INK2)
    fig.tight_layout()
    fig.savefig("kv_equilibrium/out/hysteresis.png", facecolor=PAGE)
    plt.close(fig)

    if drop is not None and rec is not None:
        print(f"HBM-only: collapses at ~{xu[drop]:.1f} rps on the way up, "
              f"recovers at ~{xd[rec]:.1f} rps on the way down")


if __name__ == "__main__":
    plot_hysteresis()
    plot_disruption()
    print("wrote kv_equilibrium/out/hysteresis.png, disruption.png")
