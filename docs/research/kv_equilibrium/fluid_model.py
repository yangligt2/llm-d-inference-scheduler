"""Fluid fixed-point model for KV cache hit-rate equilibrium.

Implements Phase 1 of docs/research/kv-cache-equilibrium-model.md:

    W(state) = aggregate KV write rate
    T_hbm    = N * c_eff / W_hbm          (Che characteristic time, HBM)
    T_tot    = T_hbm + N * c_cpu / W_new  (adds CPU offload tier)
    hit(T)   = per-class gap CDF evaluated at the retention window
    lambda   = l / E[cycle]               (closed-loop arrivals)

Two workload classes (main conversation turns, subagent turns) are derived
from the trace-calibrated spec (cc-traces-weka-062126-256k) via a
deterministic mean-path walk over the compaction sawtooth.

Solve from seed h=1 and h=0; differing limits = bistable.

All token quantities are tokens; times are seconds; rates are per second.
"""

from dataclasses import dataclass, replace
import math

# ---------------------------------------------------------------------------
# Lognormal helpers. All spec distributions give ARITHMETIC mean/std; convert
# to log-space (mu, sigma) by moment matching.
# ---------------------------------------------------------------------------


def ln_musigma(mean: float, std: float):
    sigma2 = math.log(1.0 + (std / mean) ** 2)
    mu = math.log(mean) - 0.5 * sigma2
    return mu, math.sqrt(sigma2)


def ln_cdf(t: float, mean: float, std: float) -> float:
    if t <= 0:
        return 0.0
    mu, sigma = ln_musigma(mean, std)
    return 0.5 * (1.0 + math.erf((math.log(t) - mu) / (sigma * math.sqrt(2.0))))


def trunc_count_grid(mean: float, std: float, lo: int, hi: int, n: int = 240):
    """Discretize a truncated lognormal count distribution.

    Returns [(k, weight)] with weights summing to 1. Grid is exact integers up
    to 64, geometric bins above.
    """
    edges = []
    k = lo
    while k <= min(hi, 64):
        edges.append(k)
        k += 1
    if hi > 64:
        g = 64.0
        ratio = (hi / 64.0) ** (1.0 / max(n - len(edges), 8))
        while g < hi:
            g *= ratio
            gi = int(round(g))
            if gi > edges[-1] and gi <= hi:
                edges.append(gi)
        if edges[-1] != hi:
            edges.append(hi)
    lo_cdf = ln_cdf(lo - 0.5 if lo > 1 else 0.5, mean, std)
    hi_cdf = ln_cdf(hi + 0.5, mean, std)
    span = hi_cdf - lo_cdf
    out = []
    prev = lo_cdf
    for i, k in enumerate(edges):
        upper = ln_cdf((k + edges[i + 1]) / 2.0 if i + 1 < len(edges) else hi + 0.5, mean, std)
        w = max(upper - prev, 0.0) / span
        prev = upper
        if w > 0:
            out.append((k, w))
    return out


# ---------------------------------------------------------------------------
# Calibrated workload spec (see research note section 5).
# ---------------------------------------------------------------------------

# Main conversation class
SYS_PROMPT = 0.87 * 52858 + 0.13 * 23285          # ~49014, dynamic system prompt mean
D_IN_MAIN = 0.85 * 2882 + 0.15 * 1199             # ~2630 new input tokens/turn
D_OUT_MAIN = 1258
TURNS_MAIN = (64, 66, 1, 1495)                     # mean, std, min, max
COMPACT_TRIGGER = 249_000
COMPACT_POST = 73_800                              # sys prompt + summary
THINK_ZERO_FRAC = 0.356
THINK_MIX = ((0.66, 2, 1), (0.34, 263, 7462))      # (weight, mean, std)
E_THINK = (1 - THINK_ZERO_FRAC) * sum(w * m for w, m, _ in THINK_MIX)

# Subagent class
SUB_CONV_FRAC = 0.445
SUB_GROUPS_MEAN = 8
SUB_TURNS = (19, 24, 1, 642)
SUB_SEED = 36_223                                  # first-request prefill
SUB_D_IN = 3043
SUB_D_OUT = 537
SUB_SUMMARY = 28_800                               # reuse main summary length
SUB_GAP = (2, 1)                                   # agentic pace lognormal
SUB_RATE_RATIO = SUB_CONV_FRAC * SUB_GROUPS_MEAN * SUB_TURNS[0] / TURNS_MAIN[0]


def gap_cdf_main(t: float) -> float:
    if t <= 0:
        return 0.0
    pos = sum(w * ln_cdf(t, m, s) for w, m, s in THINK_MIX)
    return THINK_ZERO_FRAC + (1 - THINK_ZERO_FRAC) * pos


def gap_cdf_sub(t: float) -> float:
    return ln_cdf(t, *SUB_GAP) if t > 0 else 0.0


@dataclass(frozen=True)
class ClassFunctionals:
    """Turn-weighted per-request functionals of one workload class."""

    f_first: float        # fraction of turns that are conversation-first (forced full miss)
    f_comp: float         # fraction that immediately follow a compaction (partial miss)
    p_norm: float         # mean prefix length of a normal turn
    first_prefill: float  # prefill tokens of a first turn
    comp_prefill: float   # prefill tokens of a post-compaction turn (summary + input)
    comp_cached: float    # cached tokens of a post-compaction turn (system prompt / seed)
    d_in: float
    d_out: float


def walk_class(first_prefix, first_prefill, d_in, d_out, post_ctx, cached_at_comp,
               turns_dist) -> ClassFunctionals:
    """Deterministic mean-path walk over the compaction sawtooth.

    Prefix before turn k is the running context; compaction fires when the
    next turn would push context past the trigger, resetting context to
    post_ctx with cached_at_comp tokens still prefix-cached.
    """
    g = d_in + d_out
    tw = tf = tc = tn = sump = 0.0
    for K, w in turns_dist:
        n_comp = n_norm = 0
        sum_p = 0.0
        ctx = first_prefill + d_out  # context after turn 1
        for _ in range(2, K + 1):
            if ctx + d_in > COMPACT_TRIGGER:
                n_comp += 1
                ctx = post_ctx + d_in + d_out
            else:
                n_norm += 1
                sum_p += ctx
                ctx += g
        tw += w * K
        tf += w * 1.0
        tc += w * n_comp
        tn += w * n_norm
        sump += w * sum_p
    return ClassFunctionals(
        f_first=tf / tw,
        f_comp=tc / tw,
        p_norm=(sump / tn) if tn > 0 else 0.0,
        first_prefill=first_prefill,
        comp_prefill=(post_ctx - cached_at_comp) + d_in,
        comp_cached=cached_at_comp,
        d_in=d_in,
        d_out=d_out,
    )


def build_workload():
    main = walk_class(
        first_prefix=SYS_PROMPT,
        first_prefill=SYS_PROMPT + D_IN_MAIN,
        d_in=D_IN_MAIN, d_out=D_OUT_MAIN,
        post_ctx=COMPACT_POST, cached_at_comp=SYS_PROMPT,
        turns_dist=trunc_count_grid(*TURNS_MAIN),
    )
    sub = walk_class(
        first_prefix=SUB_SEED,
        first_prefill=SUB_SEED,
        d_in=SUB_D_IN, d_out=SUB_D_OUT,
        post_ctx=SUB_SEED + SUB_SUMMARY, cached_at_comp=SUB_SEED,
        turns_dist=trunc_count_grid(*SUB_TURNS),
    )
    return main, sub


MAIN, SUB = build_workload()


# ---------------------------------------------------------------------------
# System parameters and solver.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class System:
    n_nodes: int = 16
    c_hbm: float = 0.95e6          # per-node HBM KV pool, tokens
    c_cpu: float = 0.0             # per-node CPU offload tier, tokens
    p_tpt: float = 10_000.0        # per-node prefill throughput, tokens/s
    d_tpt: float = 2_000.0         # per-node decode throughput cap, tokens/s
    tpot: float = 0.012            # decode seconds/token
    sessions: float = 400.0        # l: concurrent conversations
    open_loop_rps: float = 0.0     # if > 0, fixed offered aggregate req/s
                                   # (ignores sessions and the cycle feedback)
    routing_accuracy: float = 1.0  # multiplies every hit probability
    cv2_prefill: float = 1.0       # squared coeff. of variation of prefill service


@dataclass
class Metrics:
    converged: bool
    h_tok: float          # token-weighted hit rate (cached / prompt tokens)
    h_req: float          # request-weighted full-prefix hit rate
    lam_total: float      # achieved aggregate req/s
    ttft: float           # mean TTFT, s
    t_hbm: float          # HBM retention window, s
    t_tot: float          # HBM+CPU retention window, s
    rho_prefill: float
    rho_decode: float
    rho_kv: float         # running-request KV residency / HBM pool
    thrash: bool          # running set saturates the pool (rho_kv >= 1)


def _class_terms(cf: ClassFunctionals, u: float, u_hbm: float):
    """Per-request expectations of one class at hit probs (u total, u_hbm HBM)."""
    nn = 1.0 - cf.f_first - cf.f_comp
    cached = nn * u * cf.p_norm + cf.f_comp * cf.comp_cached
    prefill = (nn * (cf.d_in + (1.0 - u) * cf.p_norm)
               + cf.f_first * cf.first_prefill
               + cf.f_comp * cf.comp_prefill)
    prompt = cached + prefill
    write = prefill + cf.d_out
    restore = nn * max(u - u_hbm, 0.0) * cf.p_norm
    return cached, prefill, prompt, write, restore


TTFT_CAP = 1800.0


def solve(sys: System, seed_hit: float, max_iter: int = 20000, tol: float = 1e-8,
          init=None) -> Metrics:
    n = sys.n_nodes
    a = sys.routing_accuracy
    # State: retention windows and TTFT. `init` warm-starts continuation runs.
    if init is not None:
        t_hbm, t_tot, ttft = init
    elif seed_hit >= 0.5:
        t_hbm, t_tot, ttft = 1e9, 1e9, 1.0
    else:
        t_hbm, t_tot, ttft = 1e-3, 1e-3, 15.0
    damp = 0.3
    prev_resid = math.inf
    for it in range(max_iter):
        u_m, uh_m = a * gap_cdf_main(t_tot), a * gap_cdf_main(t_hbm)
        u_s, uh_s = a * gap_cdf_sub(t_tot), a * gap_cdf_sub(t_hbm)

        cm, pm, prm, wm, rm = _class_terms(MAIN, u_m, uh_m)
        cs, ps, prs, ws, rs = _class_terms(SUB, u_s, uh_s)

        if sys.open_loop_rps > 0:
            lam = sys.open_loop_rps
            lam_m = lam / (1.0 + SUB_RATE_RATIO)
            lam_s = lam - lam_m
        else:
            cycle = E_THINK + ttft + MAIN.d_out * sys.tpot
            lam_m = sys.sessions / cycle
            lam_s = SUB_RATE_RATIO * lam_m
            lam = lam_m + lam_s

        # Prefill queueing (M/G/1 per node, class-mixed service).
        s_m, s_s = pm / sys.p_tpt, ps / sys.p_tpt
        es = (lam_m * s_m + lam_s * s_s) / lam
        es2 = (lam_m * s_m ** 2 + lam_s * s_s ** 2) / lam * (1.0 + sys.cv2_prefill)
        lam_node = lam / n
        rho_p = lam_node * es
        rho_c = min(rho_p, 0.999)
        wq = min(lam_node * es2 / (2.0 * (1.0 - rho_c)), TTFT_CAP)

        # Running requests hold KV for their whole service time; the pool must
        # host them alongside the cache. Near saturation, requests additionally
        # queue for a KV slot (vLLM caps running concurrency at what fits).
        svc_m = s_m + MAIN.d_out * sys.tpot
        svc_s = s_s + SUB.d_out * sys.tpot
        svc_mix = (lam_m * svc_m + lam_s * svc_s) / lam
        kv_mix = (lam_m * (prm + MAIN.d_out) + lam_s * (prs + SUB.d_out)) / lam
        running = (lam_m * svc_m * (prm + MAIN.d_out)
                   + lam_s * svc_s * (prs + SUB.d_out)) / n
        rho_kv = running / sys.c_hbm
        # Waiting for a KV slot: M/M/m via Sakasegawa, m = fleet-wide slots.
        m_slots = max(n * sys.c_hbm / kv_mix, 1.0)
        rk = min(rho_kv, 0.999)
        w_slot = min(svc_mix * rk ** (math.sqrt(2.0 * (m_slots + 1.0)) - 1.0)
                     / (m_slots * (1.0 - rk)), TTFT_CAP)
        ttft_new = min(wq + w_slot + es, TTFT_CAP)

        c_eff = max(sys.c_hbm - running, 0.05 * sys.c_hbm)

        w_new = lam_m * wm + lam_s * ws
        w_hbm = w_new + lam_m * rm + lam_s * rs
        t_hbm_new = n * c_eff / w_hbm
        t_tot_new = t_hbm_new + (n * sys.c_cpu / w_new if sys.c_cpu > 0 else 0.0)

        # Damped update in log space (the 1/(1-rho) terms are stiff).
        d1 = abs(math.log(t_hbm_new / t_hbm))
        d2 = abs(math.log(t_tot_new / t_tot))
        d3 = abs(math.log(ttft_new / ttft))
        resid = max(d1, d2, d3)
        t_hbm = math.exp((1 - damp) * math.log(t_hbm) + damp * math.log(t_hbm_new))
        t_tot = math.exp((1 - damp) * math.log(t_tot) + damp * math.log(t_tot_new))
        ttft = math.exp((1 - damp) * math.log(ttft) + damp * math.log(ttft_new))
        if resid < tol and it > 10:
            break
        # Oscillation guard: if the residual stalls, damp harder.
        if it % 500 == 499:
            if resid > 0.9 * prev_resid:
                damp = max(damp * 0.5, 0.02)
            prev_resid = resid
    converged = resid < 1e-4

    h_tok = (lam_m * cm + lam_s * cs) / (lam_m * prm + lam_s * prs)
    nn_m = 1.0 - MAIN.f_first - MAIN.f_comp
    nn_s = 1.0 - SUB.f_first - SUB.f_comp
    h_req = (lam_m * nn_m * u_m + lam_s * nn_s * u_s) / lam
    rho_d = (lam_m * MAIN.d_out + lam_s * SUB.d_out) / (n * sys.d_tpt)
    return Metrics(converged, h_tok, h_req, lam, ttft, t_hbm, t_tot,
                   rho_p, rho_d, rho_kv, rho_kv >= 1.0)


def h_tok_ceiling() -> float:
    """Token hit rate with an infinite retention window (structural ceiling)."""
    cm, pm, prm, _, _ = _class_terms(MAIN, 1.0, 1.0)
    cs, ps, prs, _, _ = _class_terms(SUB, 1.0, 1.0)
    lm, ls = 1.0, SUB_RATE_RATIO
    return (lm * cm + ls * cs) / (lm * prm + ls * prs)


REGIONS = ("good", "bistable", "degraded", "overload")


def classify(sys: System):
    hi = solve(sys, seed_hit=1.0)
    lo = solve(sys, seed_hit=0.0)
    ceiling = h_tok_ceiling()
    if hi.h_tok - lo.h_tok > 0.05:
        return "bistable", hi, lo
    m = hi
    if m.rho_prefill >= 0.9 or m.thrash:
        return "overload", hi, lo
    if m.h_tok >= 0.8 * ceiling and m.ttft <= 5.0:
        return "good", hi, lo
    return "degraded", hi, lo


# ---------------------------------------------------------------------------
# CLI: customer case study.
# ---------------------------------------------------------------------------


def _fmt(m: Metrics) -> str:
    return (f"h_tok={m.h_tok:5.1%}  h_req={m.h_req:5.1%}  rps={m.lam_total:6.2f}  "
            f"TTFT={m.ttft:7.2f}s  T_hbm={m.t_hbm:8.1f}s  T_tot={m.t_tot:8.1f}s  "
            f"rho_p={m.rho_prefill:5.2f}  rho_d={m.rho_decode:5.2f}  rho_kv={m.rho_kv:5.2f}"
            f"{'  THRASH' if m.thrash else ''}{'' if m.converged else '  NOCONV'}")


def main():
    print(f"workload functionals:")
    print(f"  main: f_first={MAIN.f_first:.4f} f_comp={MAIN.f_comp:.4f} "
          f"P_norm={MAIN.p_norm:,.0f} d_in={MAIN.d_in:,.0f} d_out={MAIN.d_out:,.0f}")
    print(f"  sub:  f_first={SUB.f_first:.4f} f_comp={SUB.f_comp:.4f} "
          f"P_norm={SUB.p_norm:,.0f} rate_ratio={SUB_RATE_RATIO:.3f}")
    print(f"  E[think]={E_THINK:.1f}s  h_tok ceiling={h_tok_ceiling():.1%}\n")

    for c_cpu, label in ((0.0, "HBM only (0.95M tok/node)"),
                         (5.7e6, "HBM + CPU tier (6.65M tok/node)")):
        print(f"== {label}, N=16, l=400 sessions ==")
        sys_ = System(c_cpu=c_cpu)
        region, hi, lo = classify(sys_)
        print(f"  region: {region}")
        print(f"  from h=1: {_fmt(hi)}")
        print(f"  from h=0: {_fmt(lo)}\n")

    print("== routing accuracy sweep (HBM + CPU, l=400, seeded warm) ==")
    for acc in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        m = solve(System(c_cpu=5.7e6, routing_accuracy=acc), seed_hit=1.0)
        print(f"  a={acc:.1f}: {_fmt(m)}")


if __name__ == "__main__":
    main()
