"""Phase 2 validation: DES vs fluid model.

Experiments:
  A (band)       semi-open sweep over offered rps, HBM-only and +CPU.
                 Each run: bootstrapped warm population, full cache flush at
                 t=2500 s (rolling-deploy trigger). Warm-branch hit rate is
                 measured before the flush, the settled outcome after. The
                 fluid hysteresis curves are overlaid. -> out/des_band.png
  B (customer)   closed loop, l=400, both tiers: table vs fluid.
  C (trajectory) semi-open at 9 rps, flush at t=2500, deliberate shed to
                 1 rps at [4300, 4600]. Windowed DES h(t)/TTFT(t) for both
                 tiers with the fluid trajectory overlaid.
                 -> out/des_trajectory.png
"""

import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from des import Sim, summarize, generate_trace
from fluid_model import System, solve
import dynamics
from phase_diagram import (PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes,
                           wash)

C_CPU = 5.7e6
FLUSH_T = 2500.0
T_END = 6500.0
WARM_WIN = (1500.0, 2500.0)
POST_WIN = (4500.0, 6500.0)

_TRACES = {}


def run_point(rps, c_cpu, seed=0, gate=None, flush=FLUSH_T, t_end=T_END):
    key = (rps, seed, t_end)
    if key not in _TRACES:
        _TRACES[key] = generate_trace(rps, t_end, seed)
    events, warm = _TRACES[key]
    sim = Sim(c_cpu=c_cpu, mode="replay", trace=events, warm=warm,
              gate_schedule=gate, seed=seed, t_end=t_end, flush_at=flush)
    return sim.run()


def fluid_hysteresis_curves():
    rps_grid = np.linspace(2, 16, 57)
    out = {}
    for direction, grid in (("up", rps_grid), ("down", rps_grid[::-1])):
        init, ys = None, []
        for r in grid:
            m = solve(System(c_hbm=0.95e6, c_cpu=0.0, open_loop_rps=r),
                      seed_hit=1.0 if init is None else 0.0, init=init)
            init = (m.t_hbm, m.t_tot, m.ttft)
            ys.append(m.h_tok)
        out[direction] = (grid, np.array(ys))
    return out


def exp_band():
    print("== Exp A: band validation (replay, warm start, flush at t=2500) ==")
    print(f"  {'rps':>4} {'tier':>8} {'off w':>6} {'off p':>6} {'h warm':>8} "
          f"{'h post':>8} {'shed post':>9} {'ttft post p50':>13}")
    points = {}
    for c_cpu, tier in ((0.0, "HBM"), (C_CPU, "HBM+CPU")):
        for rps in (6, 7, 8, 9, 10, 11, 12):
            rec = run_point(rps, c_cpu)
            warm = summarize(rec, *WARM_WIN)
            post = summarize(rec, *POST_WIN)
            points[(tier, rps)] = (warm, post)
            print(f"  {rps:>4} {tier:>8} {warm['offered_rps']:>6.1f} "
                  f"{post['offered_rps']:>6.1f} {warm['h_tok']:>8.1%} "
                  f"{post['h_tok']:>8.1%} {post['shed_frac']:>9.1%} "
                  f"{post['ttft_p50']:>12.1f}s")

    fl = fluid_hysteresis_curves()
    fig, ax = plt.subplots(figsize=(7.6, 5.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    style_axes(ax)
    for direction, ls, lbl in (("up", "-", "fluid, warm branch"),
                               ("down", (0, (4, 2)), "fluid, cold branch")):
        xs, ys = fl[direction]
        ax.plot(xs, ys, color=MUTED, linewidth=1.6, linestyle=ls, label=lbl)
    for tier, color in (("HBM", SERIES[0]), ("HBM+CPU", SERIES[1])):
        rps_list = sorted(r for (t, r) in points if t == tier)
        warm_h = [points[(tier, r)][0]["h_tok"] for r in rps_list]
        post_h = [points[(tier, r)][1]["h_tok"] for r in rps_list]
        ax.plot(rps_list, warm_h, "o", color=color, markersize=7,
                markeredgecolor="#fcfcfb", markeredgewidth=1.2,
                label=f"DES {tier}, before flush")
        ax.plot(rps_list, post_h, "X", color=color, markersize=8,
                markeredgecolor="#fcfcfb", markeredgewidth=1.2,
                label=f"DES {tier}, after flush")
    ax.set_xlabel("offered load (req/s)")
    ax.set_ylabel("token hit rate")
    ax.set_ylim(0, 1.02)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.set_title("DES vs fluid: warm branch and post-flush outcome",
                 fontsize=11, pad=10)
    ax.legend(loc="lower left", fontsize=8, frameon=False, labelcolor=INK2)
    fig.tight_layout()
    fig.savefig("kv_equilibrium/out/des_band.png", facecolor=PAGE)
    plt.close(fig)


def exp_customer():
    print("\n== Exp B: closed loop, l=400 (DES [900,1800] vs fluid) ==")
    for c_cpu, tier in ((0.0, "HBM only"), (C_CPU, "HBM+CPU")):
        rec = Sim(c_cpu=c_cpu, mode="closed", sessions=400, seed=1,
                  t_end=1800.0).run()
        d = summarize(rec, 900.0, 1800.0)
        f = solve(System(c_hbm=0.95e6, c_cpu=c_cpu, sessions=400), seed_hit=1.0)
        print(f"  {tier:>9}: DES h={d['h_tok']:.1%} rps={d['served_rps']:.2f} "
              f"ttft mean={d['ttft_mean']:.1f}s p95={d['ttft_p95']:.1f}s | "
              f"fluid h={f.h_tok:.1%} rps={f.lam_total:.2f} "
              f"ttft={f.ttft:.1f}s")


def fluid_trajectory(c_cpu, schedule, flush_t, t_end):
    state = (30.0, 1500.0 if c_cpu > 0 else 0.0, 0.0, 0.0)
    for _ in range(int(600 / dynamics.DT)):
        state, _ = dynamics.step(state, schedule[0][1], c_cpu)
    ts, hs, ttfts = [], [], []
    t = 0.0
    flushed = False
    while t < t_end:
        if not flushed and t >= flush_t:
            state = (0.0, 0.0, state[2], state[3])
            flushed = True
        rps = [r for (t0, r) in schedule if t >= t0][-1]
        state, (h, ttft, _) = dynamics.step(state, rps, c_cpu)
        ts.append(t)
        hs.append(h)
        ttfts.append(ttft)
        t += dynamics.DT
    return np.array(ts), np.array(hs), np.array(ttfts)


def windowed(rec, t_end, win=100.0):
    ts, hs, ttfts = [], [], []
    t = win
    while t <= t_end:
        s = summarize(rec, t - win, t)
        if s:
            ts.append(t - win / 2)
            hs.append(s["h_tok"])
            ttfts.append(s["ttft_p50"])
        t += win
    return np.array(ts), np.array(hs), np.array(ttfts)


def exp_trajectory():
    print("\n== Exp C: trajectory at 9 rps (flush 2500, shed 4300-4600) ==")
    schedule = [(0.0, 9.0), (4300.0, 1.0), (4600.0, 9.0)]
    gate = [(0.0, 1.0), (4300.0, 1.0 / 9.0), (4600.0, 1.0)]
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 6.6), dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)

    for c_cpu, tier, color in ((0.0, "HBM only", SERIES[0]),
                               (C_CPU, "HBM + CPU tier", SERIES[1])):
        rec = run_point(9.0, c_cpu, gate=gate)
        ts, hs, ttfts = windowed(rec, T_END)
        fts, fhs, fttfts = fluid_trajectory(c_cpu, schedule, FLUSH_T, T_END)
        axes[0].plot(ts / 60, hs, color=color, linewidth=1.8, label=f"DES {tier}")
        axes[0].plot(fts / 60, fhs, color=color, linewidth=1.2,
                     linestyle=(0, (4, 2)), alpha=0.8, label=f"fluid {tier}")
        axes[1].plot(ts / 60, ttfts, color=color, linewidth=1.8)
        axes[1].plot(fts / 60, fttfts, color=color, linewidth=1.2,
                     linestyle=(0, (4, 2)), alpha=0.8)

    axes[0].set_ylabel("token hit rate", fontsize=9)
    axes[0].set_ylim(0, 1.02)
    axes[0].set_title("Flush -> stuck vs self-recovery, then shed -> recovery "
                      "(9 rps, DES solid vs fluid dashed)", fontsize=11, pad=10)
    axes[0].legend(loc="lower left", fontsize=8, frameon=False,
                   labelcolor=INK2, ncols=2)
    axes[1].set_yscale("log")
    axes[1].set_ylabel("TTFT p50 (s)", fontsize=9)
    axes[1].set_xlabel("time (minutes)", fontsize=9)
    for ax in axes:
        style_axes(ax)
        ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.axvline(FLUSH_T / 60, color=MUTED, linewidth=0.9,
                   linestyle=(0, (2, 2)))
        ax.axvspan(4300 / 60, 4600 / 60, color=wash("#2a78d6", 0.12), zorder=0)
    axes[0].text(FLUSH_T / 60 + 0.4, 0.06, "cache flush", fontsize=8,
                 color=INK2)
    axes[0].text(4300 / 60 + 0.4, 0.06, "shed to 1 rps", fontsize=8,
                 color=INK2)
    fig.align_ylabels(axes)
    fig.tight_layout()
    fig.savefig("kv_equilibrium/out/des_trajectory.png", facecolor=PAGE)
    plt.close(fig)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "band"):
        exp_band()
    if which in ("all", "customer"):
        exp_customer()
    if which in ("all", "traj"):
        exp_trajectory()
    print("\nwrote kv_equilibrium/out/des_band.png, des_trajectory.png")
