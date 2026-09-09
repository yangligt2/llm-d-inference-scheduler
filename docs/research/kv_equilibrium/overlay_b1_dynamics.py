"""Session-reservoir fluid dynamics overlaid on the measured B1/B2 arcs.

The fixed-point model (overlay_fixedpoint.py) matches the warm branch but
cannot produce the measured absorbing collapse at achieved request rates:
on this fleet the collapse is sustained by two effects outside the static
model - decode/prefill interference (tpot grows with the running set) and
elastic session demand (stalled sessions defer and then drain as a
catch-up reservoir). This module adds both and simulates the exact B1/B2
protocols: Poisson session-arrival base, a 45-min surge generator whose
whole population is cancelled at surge end, and an optional CPU tier.

States (fleet-level fluid, counts unless noted):
    G      sessions thinking (next request due after the capped gap)
    Q      requests queued for admission
    Npre   requests in prefill;  Bpre = outstanding prefill tokens
    Ndec   requests in decode
    A_h    HBM age coverage, s (prefix hits iff last touch < A_h ago)
    A_c    CPU-tier additional coverage, s
Surge sessions are tracked as a parallel (G2, Q2) population plus a
fractional share of Npre/Ndec/Bpre; cancellation zeroes them.

Interference calibration (tpot_fit.py, per-window tpot p50 vs fleet
running gauge pooled over the 8x arcs and the 4x cpuofl-b2a arc; the
per-pod form fits both fleets with one constant pair where the fleet-R
form misses the 4x saturated windows by 2.4x):
    tpot(R, N) = 10.8e-3 + 2.56e-4 * (R/N)^2  (s/token), capped 0.3.

CPU-tier restore channel (extract_arcs.py offload counters): restores
run at an effective per-replica capacity B_R_REPLICA tokens/s - the
per-pod restore rate plateaus at 21-24k tok/s across all tier runs at
both fleet scales while demand exceeds it (early-surge ext queries ~2x
hits), far below the ~1.19e6 tok/s raw DMA rate (151.5 GB/s active
bandwidth at ~2% duty; per-transfer overhead gates throughput, not the
link). Restores are pipelined ahead of prefill: the channel drains its
backlog at capacity, and a request finishes its prefill stage only
when both its uncached tokens (prefill channel) and its CPU-cached
tokens (restore channel) are through - the binding channel sets the
finish rate. The restore wait enters wq as a third max() term: the
channels serve different requests concurrently, so a new arrival's
wait is governed by the bottleneck backlog, not the sum. Achieved
restore traffic advances the HBM write clock (restored prefixes
displace resident content) via w_hbm.

Run: .venv/bin/python kv_equilibrium/overlay_b1_dynamics.py
Writes out/overlay_b1_dynamics.png and out/overlay_b1_summary.csv.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fluid_model import (MAIN, SUB, SUB_RATE_RATIO, _class_terms,
                         gap_cdf_main, gap_cdf_sub, THINK_ZERO_FRAC, THINK_MIX,
                         ln_cdf, SYS_PROMPT, D_IN_MAIN)
from phase_diagram import PAGE, INK, INK2, MUTED, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"
ARCS = OUT / "arcs"

GAP_CAP = 10.5
WS = SUB_RATE_RATIO            # subagent requests per main request
WM = 1.0
E_REQ_SESSION = 118.0          # measured realized requests/session in the
                               # 3 h B1 windows (28366 rec / 240 sessions,
                               # b1a); the corpus mean 174 is truncated by
                               # the finite run window
P_TPT_REPLICA = 17_000.0
C_HBM_REPLICA = 6486 * 256.0
B_R_REPLICA = 23_000.0         # effective CPU->HBM restore capacity, tok/s
TPOT0, TPOT_KP, TPOT_CAP = 10.8e-3, 2.56e-4, 0.30   # per-pod (R/N)^2 form
D_OUT_MIX = (WM * MAIN.d_out + WS * SUB.d_out) / (WM + WS)
DT = 2.0


def f_cap(cdf):
    return lambda t: 1.0 if t >= GAP_CAP else (cdf(t) if t > 0 else 0.0)


F_MAIN, F_SUB = f_cap(gap_cdf_main), f_cap(gap_cdf_sub)


def gap_mean_capped() -> float:
    """E[min(gap, cap)] of the request mix (main think mix + subagent pace)."""
    ts = np.linspace(0.0, GAP_CAP, 400)
    def e_min(F):
        # E[min(g,c)] = int_0^c (1-F(t)) dt
        return float(np.trapezoid([1.0 - F(t) for t in ts], ts))
    em = (1 - THINK_ZERO_FRAC) * e_min(lambda t: sum(
        w * ln_cdf(t, m, s) for w, m, s in THINK_MIX) / (1 - 0) )  # positive part
    # zero-gap turns contribute 0
    es = e_min(lambda t: ln_cdf(t, 2, 1))
    return (WM * em + WS * es) / (WM + WS)


E_GAP = gap_mean_capped()


def mixed_terms(u: float, u_hbm: float):
    cm, pm, prm, wm_, rm = _class_terms(MAIN, u, u_hbm)
    cs, ps, prs, ws_, rs = _class_terms(SUB, u, u_hbm)
    w = WM + WS
    return ((WM * cm + WS * cs) / w, (WM * pm + WS * ps) / w,
            (WM * prm + WS * prs) / w, (WM * wm_ + WS * ws_) / w,
            (WM * rm + WS * rs) / w)


# Salted session-first requests are a forced full miss regardless of
# coverage; the corpus class terms only carry them at the steady-state
# fraction (1/64 of main turns), which understates a surge stream whose
# early composition is first-turn-heavy. They are therefore tracked as a
# separate queue class with fixed cost.
U_FIRST = SYS_PROMPT + D_IN_MAIN                  # uncached prefill, tokens
KV_FIRST = U_FIRST + MAIN.d_out


def cont_terms(u: float, u_hbm: float):
    """Continuation mix: MAIN conditioned on not-first + SUB unchanged."""
    cm, pm, prm, wm_, rm = _class_terms(MAIN, u, u_hbm)
    ff = MAIN.f_first
    cm_c = cm / (1 - ff)
    pm_c = (pm - ff * MAIN.first_prefill) / (1 - ff)
    rm_c = rm / (1 - ff)
    prm_c = cm_c + pm_c
    wm_c = pm_c + MAIN.d_out
    cs, ps, prs, ws_, rs = _class_terms(SUB, u, u_hbm)
    w = WM * (1 - ff) + WS
    return ((WM * (1 - ff) * cm_c + WS * cs) / w,
            (WM * (1 - ff) * pm_c + WS * ps) / w,
            (WM * (1 - ff) * prm_c + WS * prs) / w,
            (WM * (1 - ff) * wm_c + WS * ws_) / w,
            (WM * (1 - ff) * rm_c + WS * rs) / w)


def hit_prob(a_tot: float, a_h: float, wq: float):
    eff_t = max(a_tot - wq, 0.0)
    eff_h = max(a_h - wq, 0.0)
    u = (WM * F_MAIN(eff_t) + WS * F_SUB(eff_t)) / (WM + WS)
    uh = (WM * F_MAIN(eff_h) + WS * F_SUB(eff_h)) / (WM + WS)
    return u, min(uh, u)


def simulate(n_replicas, lam_base, surge, t_end_min, c_cpu_replica=0.0):
    """surge = (t_on_s, t_off_s, lam_surge) or None; cancellation at t_off.

    Queues are split by population (base/surge) x class (first request /
    continuation): arriving sessions enqueue a forced-miss first request;
    thinking sessions release continuation requests priced by coverage.
    """
    pool = n_replicas * C_HBM_REPLICA
    cap_p = n_replicas * P_TPT_REPLICA
    cap_r = n_replicas * B_R_REPLICA
    c_cpu = n_replicas * c_cpu_replica

    G = Qf = Qc = 0.0              # base: thinking, queued first, queued cont
    G2 = Qf2 = Qc2 = 0.0           # surge
    Npre = Bpre = Ndec = 0.0
    Brst = 0.0                     # outstanding restore tokens (admitted)
    rst_run = 0.0                  # EMA restore tokens per admitted request
    fs = 0.0                       # surge share of the running set
    U_run, kv_run = U_FIRST, KV_FIRST   # EMA of admitted per-request cost
    sf_run = 1.0                   # EMA first-request share of admissions
    comp_rate = 1.0
    A_h, A_c = 30.0, (300.0 if c_cpu > 0 else 0.0)
    rows = []
    t = 0.0
    while t < t_end_min * 60:
        lam2 = surge[2] if (surge and surge[0] <= t < surge[1]) else 0.0
        if surge and abs(t - surge[1]) < DT:      # cancel surge population
            keep = 1.0 - fs
            Npre, Ndec, Bpre = Npre * keep, Ndec * keep, Bpre * keep
            Brst *= keep
            G2 = Qf2 = Qc2 = 0.0
            fs = 0.0

        N_run = Npre + Ndec
        Qf_t, Qc_t = Qf + Qf2, Qc + Qc2
        Qtot = Qf_t + Qc_t
        # wait of a new arrival: prefill-token time vs slot turnover
        wq = Bpre / cap_p
        for _ in range(2):
            u, uh = hit_prob(A_h + A_c, A_h, wq)
            cc, Uc, prc, wrc, restc = cont_terms(u, uh)
            Uc = max(Uc, 1.0)
            wq_pre = (Bpre + Qc_t * Uc + Qf_t * U_FIRST) / cap_p
            wq_slot = Qtot / max(comp_rate, 0.05)
            wq_rst = (Brst + Qc_t * restc) / cap_r if c_cpu > 0 else 0.0
            wq = max(wq_pre, wq_slot, wq_rst)
        kv_c = prc + D_OUT_MIX

        # arrivals enqueue first requests; thinkers release continuations
        Qf += lam_base * DT
        Qf2 += lam2 * DT
        rel, rel2 = min(G / E_GAP * DT, G), min(G2 / E_GAP * DT, G2)
        G -= rel; Qc += rel
        G2 -= rel2; Qc2 += rel2
        Qf_t, Qc_t = Qf + Qf2, Qc + Qc2
        Qtot = Qf_t + Qc_t

        # admission, KV-slot gated on the running-mix footprint
        slots = max(0.92 * pool / max(kv_run, 1.0), 1.0)
        adm = min(Qtot, max(slots - N_run, 0.0))
        if Qtot > 0 and adm > 0:
            shf = Qf_t / Qtot                     # first-request share
            sh2 = (Qf2 + Qc2) / Qtot              # surge share
            adm_f, adm_c = adm * shf, adm * (1 - shf)
            take_f = adm_f / max(Qf_t, 1e-9)
            take_c = adm_c / max(Qc_t, 1e-9)
            Qf -= Qf * take_f; Qf2 -= Qf2 * take_f
            Qc -= Qc * take_c; Qc2 -= Qc2 * take_c
            adm_tok = adm_f * U_FIRST + adm_c * Uc
            adm_rst = adm_c * restc if c_cpu > 0 else 0.0
            adm_kv = (adm_f * KV_FIRST + adm_c * kv_c) / adm
            adm_U = adm_tok / adm
            w = min(adm / max(N_run + adm, 1e-9), 0.5)
            U_run = (1 - w) * U_run + w * adm_U
            rst_run = (1 - w) * rst_run + w * adm_rst / adm
            kv_run = (1 - w) * kv_run + w * adm_kv
            sf_run = (1 - w) * sf_run + w * shf
            fs = (fs * N_run + adm * sh2) / max(N_run + adm, 1e-9)
            Npre += adm
            Bpre += adm_tok
            Brst += adm_rst
        else:
            adm_f = adm_c = 0.0

        # restore channel: drains its backlog at capacity, ahead of prefill.
        # The frontier gates prefill only while the channel is saturated
        # (backlog deeper than one step); a cleared backlog means every
        # admitted request has its restores done.
        if Brst > cap_r * DT and rst_run > 1.0:
            fin_r = cap_r * DT / rst_run
        else:
            fin_r = float("inf")
        drain_r = min(cap_r * DT, Brst)
        Brst -= drain_r

        # prefill service, gated by the restore-completed frontier; the
        # per-request need is the exact batch average Bpre/Npre so the two
        # backlogs stay consistent when either channel is the binding stage
        u_avg = max(Bpre / Npre, 1.0) if Npre > 1e-9 else 1.0
        fin_cap_p = min(cap_p * DT, Bpre) / u_avg
        fin_pre = min(fin_cap_p, fin_r, Npre)
        drain = min(fin_pre * u_avg, Bpre)
        Bpre -= drain
        Npre -= fin_pre
        Ndec += fin_pre

        # decode completion with interference (per-pod running set)
        tpot = min(TPOT0 + TPOT_KP * (N_run / n_replicas) ** 2, TPOT_CAP)
        comp = min(Ndec / (D_OUT_MIX * tpot) * DT, Ndec)
        comp_rate = comp / DT
        Ndec -= comp
        dep = comp / E_REQ_SESSION
        back = comp - dep
        G += back * (1 - fs); G2 += back * fs

        # coverage relaxation; achieved restore traffic churns HBM
        w_new = (drain / DT) + comp * D_OUT_MIX / DT
        w_hbm = w_new + drain_r / DT
        running_tok = N_run * kv_run
        c_eff = max(pool - running_tok, 0.05 * pool)
        tgt_h = c_eff / max(w_hbm, 1.0)
        # the CPU tier ingests only newly written tokens (measured offload
        # rate tracks uncached prefill + generation, not restores) and a
        # restore hit refreshes the tier entry, so its window churns at
        # w_new; restore traffic churns HBM alone
        tgt_c = (c_cpu / max(w_new, 1.0)) if c_cpu > 0 else 0.0
        if A_h < tgt_h:
            A_h += DT * min(1.0, (tgt_h - A_h) / max(tgt_h, 1.0))
        else:
            A_h += DT * (tgt_h - A_h) / max(tgt_h, 2.0)
        if A_c < tgt_c:
            A_c += DT * min(1.0, (tgt_c - A_c) / max(tgt_c, 1.0))
        else:
            A_c += DT * (tgt_c - A_c) / max(tgt_c, 2.0)

        # served-mix hit rate this step (matches the measured h definition)
        served_f = fin_pre * sf_run
        served_c = fin_pre - served_f
        prompt_served = served_f * U_FIRST + served_c * prc
        cached_served = served_c * cc
        h_tok = cached_served / max(prompt_served, 1.0)
        ext_share = min(drain_r / max(cached_served, 1.0), 1.0)
        rows.append((t / 60.0, h_tok, min(running_tok / pool, 1.0), Qtot,
                     N_run, comp / DT, wq, ext_share, drain_r / DT))
        t += DT
    return pd.DataFrame(rows, columns=["t_min", "h", "kv", "wait", "run",
                                       "comp_s", "wq", "ext_share",
                                       "restore_s"])


SCENARIOS = [
    # label, arc csv, replicas, lam_base, (on_s, off_s, lam_surge), c_cpu/replica
    ("0.022 sps (b1a2: relapse)", "ppc-b1a2-base", 8, 0.022,
     (62 * 60, 107 * 60, 0.25), 0.0),
    ("0.017 sps (b1c: recovery)", "ppc-b1c-base", 8, 0.017,
     (62 * 60, 107 * 60, 0.25), 0.0),
    ("0.012 sps (b1b: recovery)", "ppc-b1b-base", 8, 0.012,
     (62 * 60, 107 * 60, 0.25), 0.0),
    # c_cpu is the TIER_EFF-scaled effective capacity for
    # kv-offloading-size 500; provenance in des_b1.py.
    ("0.011 sps + CPU tier (B2a)", "cpuofl-b2a-base", 4, 0.011,
     (62 * 60, 107 * 60, 0.125), 0.844e6),
]


def main():
    print(f"E_GAP (capped, mixed) = {E_GAP:.2f} s")
    fig, axes = plt.subplots(2, 4, figsize=(16, 6.4), dpi=150, sharex=True)
    fig.patch.set_facecolor(PAGE)
    summary = []
    for col, (label, csv, n, lb, surge, ccpu) in enumerate(SCENARIOS):
        sim = simulate(n, lb, surge, 180, ccpu)
        meas = pd.read_csv(ARCS / f"{csv}.csv")
        axh, axw = axes[0][col], axes[1][col]
        axh.plot(meas.t_min, meas.h, color=SERIES[0], lw=1.8, label="measured")
        axh.plot(sim.t_min, sim.h, color=SERIES[1], lw=1.6, ls=(0, (4, 2)),
                 label="model")
        axh.set_ylim(0, 1.03)
        axh.set_title(label, fontsize=9.5)
        axw.plot(meas.t_min, meas.wait, color=SERIES[0], lw=1.8)
        axw.plot(sim.t_min, sim.wait, color=SERIES[1], lw=1.6, ls=(0, (4, 2)))
        axw.set_yscale("symlog", linthresh=10)
        axw.set_xlabel("minutes", fontsize=9)
        for ax in (axh, axw):
            style_axes(ax)
            ax.grid(True, color=GRID, lw=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.axvspan(surge[0] / 60, surge[1] / 60,
                       color=wash("#d03b3b", 0.10), zorder=0)
        end = sim[(sim.t_min > 150) & (sim.t_min <= 175)]
        end_m = meas[(meas.t_min > 150) & (meas.t_min <= 175)]
        summary.append((label, end.h.mean(), end_m.h.mean(),
                        end.wait.mean(), end_m.wait.mean()))
        print(f"  {label:<28} end-state h model {end.h.mean():5.1%} "
              f"vs meas {end_m.h.mean():5.1%}; wait {end.wait.mean():6.0f} "
              f"vs {end_m.wait.mean():6.0f}")
    axes[0][0].set_ylabel("token hit rate", fontsize=9)
    axes[1][0].set_ylabel("waiting (symlog)", fontsize=9)
    axes[0][0].legend(fontsize=8, frameon=False, loc="lower left",
                      labelcolor=INK2)
    fig.suptitle("Session-reservoir fluid model vs measured arcs "
                 "(45-min surge, cancellation at surge end)",
                 fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "overlay_b1_dynamics.png", facecolor=PAGE)
    pd.DataFrame(summary, columns=["scenario", "h_model", "h_meas",
                                   "wait_model", "wait_meas"]).to_csv(
        OUT / "overlay_b1_summary.csv", index=False, float_format="%.4f")
    print("wrote out/overlay_b1_dynamics.png, out/overlay_b1_summary.csv")


if __name__ == "__main__":
    main()
