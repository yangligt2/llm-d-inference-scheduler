"""Mitigation screen and router-family emulation on the deployed-router DES.

Part 1 (mitigation): four admission controllers over RouterSessionSim,
run under the standard perturbation protocol at (N=8, lambda_s=0.022,
untiered, 300 min) in two protocol variants:

  cancel    the paper protocol: the surge generator cancels its whole
            session population at surge end (t=107 min)
  nocancel  surge arrivals stop at t=107 min but already-arrived surge
            sessions persist and must be served; offered work then
            exceeds the horizon's total capacity by construction, so
            the comparison metrics are served volume and end-state
            health, not completion of all work

Controllers (all fleet-level, acting on new-session admission; turns
of admitted sessions are never deferred):

  none        baseline RouterSessionSim
  defer       deferral gate (the async-serving / concurrency-control
              abstraction): hold new sessions in a FIFO reservoir
              while fleet waiting > W_HI or KV occupancy > KV_HI;
              release K_REL per GATE_DT while waiting <= W_LO.
              Thresholds tuned above warm-state waiting (~10 at this
              rate): W_LO = 24, W_HI = 48 (the dry-run values 8/16
              left a persistent residual reservoir).
  aimd-pub    CONCUR-style AIMD session window, published constants
              transplanted verbatim (alpha=2, beta=0.5, U_low=0.2,
              U_high=0.5, H_thresh=0.2): window += alpha when fleet
              KV occupancy < U_low; window *= beta when occupancy >
              U_high and trailing-minute hit rate < H_thresh; hold
              otherwise. Session-admission adaptation; CONCUR's
              mid-session pausing at tool boundaries is not modeled.
  aimd-tuned  same rule, constants re-tuned to fleet occupancy scale
              (U_low=0.65, U_high=0.85, H_thresh=0.5, W0=64).
  reject      Mooncake-style early rejection: at session arrival,
              reject permanently if predicted queueing delay (queued
              prefill tokens / fleet prefill rate) exceeds 30 s.

A guard row runs every controller at 0.017 (a recovering rate) to
check no-harm.

Part 2 (router families): the standard perturbation under two
emulated third-party routing policies, untiered, rates 0.017 / 0.020
/ 0.022, to test whether the collapse band is specific to the
deployed EPP policy:

  sglang  cache-aware threshold switch (sgl-router): if per-node load
          imbalance exceeds balance thresholds (abs 32, rel 1.0001),
          route shortest-queue; else route to the highest
          prefix-match node if the match ratio exceeds 0.5, else
          least loaded. The real router matches on an approximate
          router-side radix tree; the emulation uses engine-truth
          match state, i.e. the policy's best case.
  aibrix  prefix-aware with imbalance gate: if max-min running
          requests > 8, least loaded; else least loaded among nodes
          holding any prefix match, falling back to least loaded.

Run from kv_equilibrium/:  ../.venv/bin/python mitigation.py
Writes out/mitigation_screen.csv, out/router_family.csv,
out/paper/fig_mitigation.png, out/paper/fig_router_family.png.
"""

from collections import deque
from pathlib import Path
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import des
from des_b1 import RouterSessionSim, SessionSim
from phase_diagram import PAGE, INK, INK2, GRID, SERIES, style_axes, wash

OUT = Path(__file__).parent / "out"
OUTP = OUT / "paper"

N = 8
T_END_MIN = 300
SEEDS = (1, 2, 3, 4, 5)
GUARD_SEEDS = (1, 2, 3)
GATE_DT = 5.0

COLD = "#eb6834"
CONG = "#1baf7a"
RECO = "#2a78d6"
DEGR = "#8a6fc8"


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------


class GateBase(RouterSessionSim):
    """Shared reservoir bookkeeping for admission controllers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deferq = deque()          # (seq, t_deferred)
        self.n_defer = 0
        self.n_drop = 0                # cancelled while in the reservoir
        self.n_reject = 0
        self.rel_delay = []
        self.at(GATE_DT, self.gate_tick)

    def _fleet_wait(self):
        return sum(len(n.queue) for n in self.nodes)

    def _fleet_kv(self):
        return (sum(n.kv_used for n in self.nodes)
                / (len(self.nodes) * des.C_HBM))

    # hooks -------------------------------------------------------------
    def defer_new(self, seq):          # True: hold in reservoir
        return False

    def reject_new(self, seq):         # True: drop permanently
        return False

    def release_quota(self):           # sessions releasable this tick
        return 0

    def on_tick(self):                 # controller state update
        pass

    def on_admit_new(self, seq):       # main first turn actually admitted
        pass

    # plumbing ----------------------------------------------------------
    def _admit_first(self, seq):
        self.on_admit_new(seq)
        RouterSessionSim.issue_next_turn(self, seq, True)

    def issue_next_turn(self, seq, first=False):
        if first and seq.kind == "main" and not seq.dead:
            if self.reject_new(seq):
                seq.dead = True
                self.n_reject += 1
                return
            if self.defer_new(seq):
                self.n_defer += 1
                self.deferq.append((seq, self.now))
                return
            self._admit_first(seq)
            return
        super().issue_next_turn(seq, first)

    def gate_tick(self):
        self.on_tick()
        quota = self.release_quota()
        released = 0
        while self.deferq and released < quota:
            seq, t0 = self.deferq.popleft()
            if seq.dead:
                self.n_drop += 1
                continue
            self.rel_delay.append(self.now - t0)
            self._admit_first(seq)
            released += 1
        self.at(self.now + GATE_DT, self.gate_tick)


class DeferGate(GateBase):
    W_HI, W_LO, KV_HI, K_REL = 48.0, 24.0, 0.85, 1

    def defer_new(self, seq):
        return (self._fleet_wait() > self.W_HI
                or self._fleet_kv() > self.KV_HI)

    def release_quota(self):
        if (self._fleet_wait() <= self.W_LO
                and self._fleet_kv() <= self.KV_HI):
            return self.K_REL
        return 0


class AimdGate(GateBase):
    """CONCUR-style AIMD window over concurrently active sessions."""

    ALPHA, BETA = 2.0, 0.5
    U_LOW, U_HIGH, H_THRESH = 0.2, 0.5, 0.2   # published constants
    W0, W_MIN, BURST = 32.0, 4.0, 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wc = self.W0
        self.active_set = set()
        self.h_est = 1.0
        self.bucket_t0 = 0.0
        self.bucket_prompt = 0.0
        self.bucket_cached = 0.0

    @property
    def active(self):
        return len(self.active_set)

    def on_admit_new(self, seq):
        self.active_set.add(seq)

    def cancel_surge(self):
        super().cancel_surge()
        self.active_set -= {s for s in self.active_set if s.dead}

    def finish_prefill(self, rid, node_idx, seq, arrival, prefix, in_tok,
                       out_tok, cached, prefill, tier):
        super().finish_prefill(rid, node_idx, seq, arrival, prefix,
                               in_tok, out_tok, cached, prefill, tier)
        self.bucket_prompt += prefix + in_tok
        self.bucket_cached += cached

    def finish_decode(self, rid, node_idx, seq, prefix, in_tok, out_tok):
        super().finish_decode(rid, node_idx, seq, prefix, in_tok, out_tok)
        if seq.kind == "main" and (seq.turns_left <= 0 or seq.dead):
            self.active_set.discard(seq)

    def on_tick(self):
        if self.now - self.bucket_t0 >= 60.0:
            if self.bucket_prompt > 0:
                self.h_est = self.bucket_cached / self.bucket_prompt
            self.bucket_t0 = self.now
            self.bucket_prompt = self.bucket_cached = 0.0
        u = self._fleet_kv()
        if u < self.U_LOW:
            self.wc += self.ALPHA
        elif u > self.U_HIGH and self.h_est < self.H_THRESH:
            self.wc = max(self.wc * self.BETA, self.W_MIN)

    def defer_new(self, seq):
        return self.active >= self.wc

    def release_quota(self):
        return max(min(int(self.wc) - self.active, self.BURST), 0)


class AimdGateTuned(AimdGate):
    U_LOW, U_HIGH, H_THRESH = 0.65, 0.85, 0.5   # fleet-scale re-tune
    W0 = 64.0


class RejectGate(GateBase):
    TTFT_SLO = 30.0                    # s of predicted queueing delay

    def reject_new(self, seq):
        queued = sum(p + i for n in self.nodes
                     for (_, _, p, i, _) in n.queue)
        return queued / (len(self.nodes) * des.P_TPT) > self.TTFT_SLO


CONTROLLERS = [
    ("none", RouterSessionSim),
    ("defer", DeferGate),
    ("aimd-pub", AimdGate),
    ("aimd-tuned", AimdGateTuned),
    ("reject", RejectGate),
]


def build(cls, no_cancel):
    if not no_cancel:
        return cls
    return type(cls.__name__ + "NoCancel", (cls,),
                {"cancel_surge": lambda self: None})


# ---------------------------------------------------------------------------
# Router-family emulations (Part 2)
# ---------------------------------------------------------------------------


class _EmuBase(SessionSim):
    def _loads(self):
        n = len(self.nodes)
        c = [len(node.queue) for node in self.nodes]
        for (ni, _, _, _) in self.running.values():
            c[ni] += 1
        return c


class SglRouterSim(_EmuBase):
    """sgl-router cache_aware policy (defaults: cache threshold 0.5,
    balance abs 32, balance rel 1.0001); engine-truth match state."""

    CACHE_T, BAL_ABS, BAL_REL = 0.5, 32, 1.0001

    def route(self, seq, prefix, in_tok, out_tok):
        loads = self._loads()
        lo, hi = min(loads), max(loads)
        if hi - lo > self.BAL_ABS and hi > self.BAL_REL * max(lo, 1):
            best = min(range(len(loads)),
                       key=lambda i: (loads[i], self.s.rng.random()))
        else:
            match = [(self.cached_on(seq, i, prefix)[0], i)
                     for i in range(len(self.nodes))]
            m, mi = max(match, key=lambda t: (t[0], -loads[t[1]]))
            if prefix > 0 and m / prefix > self.CACHE_T:
                best = mi
            else:
                best = min(range(len(loads)),
                           key=lambda i: (loads[i], self.s.rng.random()))
        self.nodes[best].queue.append((seq, self.now, prefix, in_tok,
                                       out_tok))
        self.try_start(best)


class AibrixRouterSim(_EmuBase):
    """AIBrix prefix-aware policy: imbalance gate at 8 running
    requests, else least-loaded among prefix-matching nodes."""

    IMB = 8

    def route(self, seq, prefix, in_tok, out_tok):
        loads = self._loads()
        if max(loads) - min(loads) > self.IMB:
            cands = range(len(loads))
        else:
            matched = [i for i in range(len(self.nodes))
                       if self.cached_on(seq, i, prefix)[0] > 0]
            cands = matched if matched else range(len(loads))
        best = min(cands, key=lambda i: (loads[i], self.s.rng.random()))
        self.nodes[best].queue.append((seq, self.now, prefix, in_tok,
                                       out_tok))
        self.try_start(best)


FAMILIES = [("epp", RouterSessionSim), ("sglang", SglRouterSim),
            ("aibrix", AibrixRouterSim)]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def end_metrics(win):
    end = win[(win.t_min > 270) & (win.t_min <= 295)]
    mid = win[(win.t_min > 200) & (win.t_min <= 240)]
    warm = win[(win.t_min >= 30) & (win.t_min <= 60)]
    return dict(end_h=end.h.mean(), end_wait=end.wait.mean(),
                mid_wait=mid.wait.mean(), warm_h=warm.h.mean())


def classify(m):
    if m["end_h"] < 0.15:
        return "cold"
    if m["end_h"] > 0.8 and m["end_wait"] < 30:
        return "recovered"
    if m["end_wait"] > 30 and m["end_wait"] > m["mid_wait"]:
        return "congested"
    return "degraded"


def run_one(cls, rate, seed, label):
    t0 = time.perf_counter()
    sim = cls(N, rate, 0.25, 0.0, seed, t_end=T_END_MIN * 60.0)
    sim.run()
    m = end_metrics(sim.windows())
    m["outcome"] = classify(m)
    served = len(sim.records)
    surge_served = sum(1 for f in sim.rec_surge if f)
    m.update(served=served, served_base=served - surge_served,
             served_surge=surge_served)
    if isinstance(sim, GateBase):
        if sim.rel_delay:
            d = np.array(sim.rel_delay)
            p50, dmax = float(np.percentile(d, 50)), float(d.max())
        else:
            p50 = dmax = np.nan
        m.update(deferred=sim.n_defer, dropped=sim.n_drop,
                 rejected=sim.n_reject, backlog=len(sim.deferq),
                 delay_p50_min=p50 / 60.0, delay_max_min=dmax / 60.0)
    else:
        m.update(deferred=0, dropped=0, rejected=0, backlog=0,
                 delay_p50_min=np.nan, delay_max_min=np.nan)
    print(f"  {label} seed {seed}: {time.perf_counter()-t0:5.1f}s; "
          f"warm h {m['warm_h']:.2f} end h {m['end_h']:.2f} "
          f"wait {m['end_wait']:.0f} -> {m['outcome']}; served "
          f"{m['served_base']}b+{m['served_surge']}s; defer "
          f"{m['deferred']} rej {m['rejected']} backlog {m['backlog']}")
    return m


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def part1():
    rows = []
    for proto, no_cancel in (("cancel", False), ("nocancel", True)):
        for cname, cls in CONTROLLERS:
            k = build(cls, no_cancel)
            print(f"[{proto}] {cname} @ 0.022")
            for seed in SEEDS:
                m = run_one(k, 0.022, seed, f"{proto}/{cname}")
                m.update(protocol=proto, controller=cname, rate=0.022,
                         seed=seed)
                rows.append(m)
    for cname, cls in CONTROLLERS:
        print(f"[guard] {cname} @ 0.017")
        for seed in GUARD_SEEDS:
            m = run_one(cls, 0.017, seed, f"guard/{cname}")
            m.update(protocol="cancel", controller=cname, rate=0.017,
                     seed=seed)
            rows.append(m)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "mitigation_screen.csv", index=False,
              float_format="%.4f")
    return df


def part2():
    rows = []
    for fname, cls in FAMILIES:
        for rate in (0.017, 0.020, 0.022):
            print(f"[router {fname}] @ {rate}")
            for seed in GUARD_SEEDS:
                m = run_one(cls, rate, seed, f"{fname}/{rate}")
                m.update(family=fname, rate=rate, seed=seed)
                rows.append(m)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "router_family.csv", index=False, float_format="%.4f")
    return df


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

OUTCOL = {"recovered": RECO, "degraded": DEGR, "congested": CONG,
          "cold": COLD}
ORDER = ("recovered", "degraded", "congested", "cold")


def fig_mitigation(df):
    fig, (ax_o, ax_s) = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150)
    fig.patch.set_facecolor(PAGE)
    names = [c for c, _ in CONTROLLERS]
    protos = ("cancel", "nocancel")
    xs, labels = [], []
    x = 0.0
    for pi, proto in enumerate(protos):
        for cname in names:
            cell = df[(df.protocol == proto) & (df.controller == cname)
                      & (df.rate == 0.022)]
            n = len(cell)
            bot = 0.0
            for out in ORDER:
                k = (cell.outcome == out).sum()
                if k:
                    ax_o.bar(x, k / n, width=0.8, bottom=bot,
                             color=wash(OUTCOL[out], 0.8),
                             edgecolor=PAGE, lw=0.8)
                    bot += k / n
            b = cell.served_base.mean()
            s = cell.served_surge.mean()
            ax_s.bar(x, b, width=0.8, color=wash(SERIES[0], 0.8),
                     edgecolor=PAGE, lw=0.8)
            ax_s.bar(x, s, width=0.8, bottom=b,
                     color=wash(SERIES[2], 0.8), edgecolor=PAGE, lw=0.8)
            ax_s.errorbar([x], [cell.served.mean()],
                          yerr=[[cell.served.mean() - cell.served.min()],
                                [cell.served.max() - cell.served.mean()]],
                          color=INK, lw=1.0, capsize=3)
            xs.append(x)
            labels.append(cname)
            x += 1.0
        x += 0.8
    for ax, title, ylab in ((ax_o, "outcomes (fraction of 5 seeds)",
                             "outcome fraction"),
                            (ax_s, "requests served in 300 min",
                             "served requests")):
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=8, rotation=30, ha="right")
        ax.set_title(title, fontsize=9.5)
        ax.set_ylabel(ylab, fontsize=9)
        style_axes(ax)
        ax.grid(True, axis="y", color=GRID, lw=0.6, alpha=0.6)
        ax.set_axisbelow(True)
        mid = (xs[len(names) - 1] + xs[len(names)]) / 2.0
        ax.axvline(mid, color=INK2, lw=0.8, ls=(0, (3, 2)))
        ax.text(mid - 0.4, ax.get_ylim()[1] * 0.97, "surge cancelled",
                ha="right", va="top", fontsize=8, color=INK2)
        ax.text(mid + 0.4, ax.get_ylim()[1] * 0.97, "surge persists",
                ha="left", va="top", fontsize=8, color=INK2)
    ax_o.legend(handles=[Patch(facecolor=wash(OUTCOL[o], 0.8), label=o)
                         for o in ORDER], fontsize=7.5, frameon=False,
                loc="center left", labelcolor=INK2)
    ax_s.legend(handles=[Patch(facecolor=wash(SERIES[0], 0.8),
                               label="base sessions"),
                         Patch(facecolor=wash(SERIES[2], 0.8),
                               label="surge sessions")],
                fontsize=7.5, frameon=False, loc="upper right",
                labelcolor=INK2)
    fig.suptitle("Admission controllers at (N=8, 0.022 sessions/s, "
                 "untiered), standard perturbation, 5 seeds, 300 min "
                 "(model output)", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(OUTP / "fig_mitigation.png", facecolor=PAGE)
    plt.close(fig)


def fig_router_family(df):
    fig, ax = plt.subplots(figsize=(7.6, 4.0), dpi=150)
    fig.patch.set_facecolor(PAGE)
    rates = (0.017, 0.020, 0.022)
    xs, labels = [], []
    x = 0.0
    for fname, _ in FAMILIES:
        for rate in rates:
            cell = df[(df.family == fname) & (df.rate == rate)]
            n = len(cell)
            bot = 0.0
            for out in ORDER:
                k = (cell.outcome == out).sum()
                if k:
                    ax.bar(x, k / n, width=0.8, bottom=bot,
                           color=wash(OUTCOL[out], 0.8), edgecolor=PAGE,
                           lw=0.8)
                    bot += k / n
            xs.append(x)
            labels.append(f"{rate:.3f}")
            x += 1.0
        x += 0.7
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=8)
    for i, (fname, _) in enumerate(FAMILIES):
        ax.text(xs[i * 3 + 1], 1.06, {"epp": "deployed EPP",
                                      "sglang": "SGLang policy",
                                      "aibrix": "AIBrix policy"}[fname],
                ha="center", fontsize=9, color=INK)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("session arrival rate $\\lambda_s$ (sessions/s)",
                  fontsize=9)
    ax.set_ylabel("outcome fraction (3 seeds)", fontsize=9)
    ax.legend(handles=[Patch(facecolor=wash(OUTCOL[o], 0.8), label=o)
                       for o in ORDER], fontsize=7.5, frameon=False,
              ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.15),
              labelcolor=INK2)
    ax.set_title("Standard perturbation under three routing policies "
                 "(N=8, untiered, 300 min; model output)", fontsize=9.5,
                 pad=22)
    style_axes(ax)
    ax.grid(True, axis="y", color=GRID, lw=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUTP / "fig_router_family.png", facecolor=PAGE)
    plt.close(fig)


def main():
    OUTP.mkdir(parents=True, exist_ok=True)
    df1 = part1()
    df2 = part2()
    fig_mitigation(df1)
    fig_router_family(df2)

    print("\n=== tallies (0.022, 5 seeds) ===")
    for proto in ("cancel", "nocancel"):
        for cname, _ in CONTROLLERS:
            cell = df1[(df1.protocol == proto)
                       & (df1.controller == cname) & (df1.rate == 0.022)]
            tally = {o: int((cell.outcome == o).sum()) for o in ORDER
                     if (cell.outcome == o).sum()}
            print(f"  {proto:9s} {cname:10s} {tally}  served "
                  f"{cell.served.min()}-{cell.served.max()}")
    print("=== guard (0.017, 3 seeds) ===")
    for cname, _ in CONTROLLERS:
        cell = df1[(df1.rate == 0.017) & (df1.controller == cname)]
        tally = {o: int((cell.outcome == o).sum()) for o in ORDER
                 if (cell.outcome == o).sum()}
        print(f"  {cname:10s} {tally}  warm h "
              f"{cell.warm_h.min():.2f}-{cell.warm_h.max():.2f}")
    print("=== router families ===")
    for fname, _ in FAMILIES:
        for rate in (0.017, 0.020, 0.022):
            cell = df2[(df2.family == fname) & (df2.rate == rate)]
            tally = {o: int((cell.outcome == o).sum()) for o in ORDER
                     if (cell.outcome == o).sum()}
            print(f"  {fname:7s} {rate:.3f} {tally}")
    print("wrote out/mitigation_screen.csv, out/router_family.csv, "
          "out/paper/fig_mitigation.png, out/paper/fig_router_family.png")


if __name__ == "__main__":
    main()
