"""Causal-validity checks for VEIN (the "how do we know it's correct" battery).

Observational causal claims can't be *proven*; they can be (1) corroborated
against external ground truth, (2) stress-tested with placebos/negative controls,
(3) bounded against unobserved confounding, and (4) checked for robustness to
upstream choices. This module implements all four, plus the H1 head-to-head of
the observed on-chain graph vs a price-estimated graph.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import networkx as nx

from .scm import StructuralCausalModel
from . import risk, falsification as fz
from . import fastscm as fs
from . import uncertainty as un
from . import pipeline as pl

NONDEGENERATE_ENTITIES = ("Ethena", "Binance", "Aave", "Lido")
FIT_STD_MIN = 1e-9


# ---------------------------------------------------------------------------
# 1. External validity vs the documented Oct-2025 post-mortem narrative
# ---------------------------------------------------------------------------
# Documented mechanics (public post-mortems): the USDe depeg was a pricing/
# liquidity artifact (Ethena stayed solvent) and Binance's internal pricing
# engine drove automated liquidations -> Ethena and the CEX are stress
# *transmitters*; Aave (zero bad debt) and Lido were *absorbers*.
DOCUMENTED_TRANSMITTERS = {"Ethena", "Binance"}
DOCUMENTED_ABSORBERS = {"Aave", "Lido"}


def external_validity(oc_ranking: pd.DataFrame, fit_std: dict | None = None,
                      s_star: dict | None = None) -> dict:
    """Do OC-CoVaR exported-risk scores rank documented transmitters above
    documented absorbers? Reports per-entity match and a separation score.

    nondegenerate is True when each of Ethena, Binance, Aave and Lido has a fit-window
    stress std above 1e-9 and a finite s*; vacuous is its negation (a ranking built on
    zero stress says nothing about transmission)."""
    score = dict(zip(oc_ranking["entity"], oc_ranking["exported_risk"]))
    t = [score.get(e, 0.0) for e in DOCUMENTED_TRANSMITTERS if e in score]
    a = [score.get(e, 0.0) for e in DOCUMENTED_ABSORBERS if e in score]
    detail = {e: float(score.get(e, 0.0))
              for e in (DOCUMENTED_TRANSMITTERS | DOCUMENTED_ABSORBERS) if e in score}
    sep = (float(np.mean(t)) - float(np.mean(a))) if t and a else float("nan")
    # pairwise concordance: fraction of (transmitter, absorber) pairs ordered right
    pairs = [(x, y) for x in t for y in a]
    conc = float(np.mean([x > y for x, y in pairs])) if pairs else float("nan")
    out = {"transmitter_scores": {e: float(score.get(e, 0.0)) for e in DOCUMENTED_TRANSMITTERS if e in score},
           "absorber_scores": {e: float(score.get(e, 0.0)) for e in DOCUMENTED_ABSORBERS if e in score},
           "separation": sep, "pairwise_concordance": conc, "detail": detail}
    if fit_std is not None and s_star is not None:
        ok = {}
        for e in NONDEGENERATE_ENTITIES:
            ok[e] = bool(e in fit_std and fit_std[e] > FIT_STD_MIN
                         and e in s_star and np.isfinite(s_star[e]))
        nondeg = all(ok.values())
        out.update({"nondegenerate": bool(nondeg), "vacuous": bool(not nondeg),
                    "nondegenerate_by_entity": ok})
    return out


# ---------------------------------------------------------------------------
# 2. Placebo / negative controls
# ---------------------------------------------------------------------------
def structural_zero_check(scm: StructuralCausalModel, graph: dict, days,
                          observed_stress: pd.DataFrame, init_stress: dict,
                          precrisis: dict) -> dict:
    """Attribution across pairs with NO directed on-chain path, compared with connected pairs.

    Holds by construction (Proposition in algorithm.md): without a path, a shock cannot
    reach j through the equations. It checks the implementation, not the data, so it is
    labelled as such in the output."""
    G = nx.DiGraph()
    G.add_nodes_from(scm.stress_cols)
    for e in graph["edges"]:
        if e["from"] in scm.stress_cols and e["to"] in scm.stress_cols:
            G.add_edge(e["from"], e["to"])

    connected, unconnected = [], []
    for i in scm.stress_cols:
        for j in scm.stress_cols:
            if i == j:
                continue
            a = risk.counterfactual_attribution(scm, i, j, days, observed_stress,
                                                 init_stress, precrisis.get(i, 0.0))
            has_path = nx.has_path(G, i, j) if (i in G and j in G) else False
            (connected if has_path else unconnected).append(abs(a["attribution"]))
    return {
        "note": "holds by construction (Prop.), not evidence",
        "n_connected_pairs": len(connected), "n_unconnected_pairs": len(unconnected),
        "mean_abs_attr_connected": float(np.mean(connected)) if connected else 0.0,
        "mean_abs_attr_unconnected": float(np.mean(unconnected)) if unconnected else 0.0,
        "max_abs_attr_unconnected": float(np.max(unconnected)) if unconnected else 0.0,
        # pass if unconnected attribution is ~0 and well below connected
        "passes": bool((np.max(unconnected) if unconnected else 0.0) < 1e-6),
    }


placebo_negative_controls = structural_zero_check   # legacy name


def temporal_placebo(scm: StructuralCausalModel, calm_days, observed_stress,
                     init_stress, precrisis) -> dict:
    """Run the SAME counterfactual machinery over a calm (pre-crisis) window.
    Attributions should be near zero when nothing is propagating."""
    tot = []
    for i in scm.stress_cols:
        for j in scm.stress_cols:
            if i == j:
                continue
            a = risk.counterfactual_attribution(scm, i, j, calm_days, observed_stress,
                                                 init_stress, precrisis.get(i, 0.0))
            tot.append(abs(a["attribution"]))
    return {"mean_abs_attr_calm": float(np.mean(tot)) if tot else 0.0,
            "max_abs_attr_calm": float(np.max(tot)) if tot else 0.0}


# ---------------------------------------------------------------------------
# 3. Sensitivity to unobserved confounding (Cinelli-Hazlett robustness value)
# ---------------------------------------------------------------------------
def _ols_t(y, X):
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    sigma2 = (resid @ resid) / dof
    se = np.sqrt(np.maximum(np.diag(XtX_inv) * sigma2, 1e-18))
    return beta, beta / se, dof


def robustness_value(t_stat: float, dof: int, q: float = 1.0) -> float:
    """Cinelli & Hazlett (2020) robustness value: the minimum share of residual
    variance an unobserved confounder must explain in BOTH the treatment (parent
    stress) and the outcome (child stress) to reduce the estimate by 100*q%.
    RV in [0,1]; higher = more robust to hidden confounding (e.g. the CEX engine)."""
    f = q * abs(t_stat) / np.sqrt(dof)
    return float(0.5 * (np.sqrt(f**4 + 4 * f**2) - f**2))


def confounding_sensitivity(scm: StructuralCausalModel, stress: pd.DataFrame) -> dict:
    """Robustness value for each parent->child structural coefficient (refit by
    OLS to obtain t-stats; Ridge is used for prediction but OLS for inference)."""
    rows = []
    for child in scm.stress_cols:
        par = scm.coef_[child]["parents"]
        if not par:
            continue
        y = stress[child].values[1:]
        feats = [stress[p].values[:-1] for p in par]
        X = np.column_stack([np.ones_like(y)] + feats)
        beta, t, dof = _ols_t(y, X)
        for k, p in enumerate(par):
            rv = robustness_value(t[k + 1], dof)
            rows.append({"edge": f"{p}->{child}", "coef": float(beta[k + 1]),
                         "t_stat": float(t[k + 1]), "robustness_value": rv})
    rows.sort(key=lambda r: -abs(r["t_stat"]))
    return {"edges": rows[:15],
            "note": "RV is the partial-R^2 a hidden confounder needs in both "
                    "parent and child to nullify the edge; larger = harder to overturn."}


# ---------------------------------------------------------------------------
# 4. Resolution robustness (Tier-0 seed-only vs Tier-3 resolved)
# ---------------------------------------------------------------------------
def resolution_robustness(oc_full: pd.DataFrame, oc_tier0: pd.DataFrame) -> dict:
    """Spearman rank correlation of OC-CoVaR exported-risk between the resolved
    (Tier-3) graph and a seed-only (Tier-0) graph, over their common entities.
    Stable ranking => result is not an artifact of the resolution choice."""
    from scipy.stats import spearmanr
    a = oc_full.set_index("entity")["exported_risk"]
    b = oc_tier0.set_index("entity")["exported_risk"]
    common = [e for e in a.index if e in b.index]
    if len(common) < 3:
        return {"common_entities": common, "spearman": float("nan"),
                "note": "too few common entities"}
    rho, p = spearmanr(a.loc[common].values, b.loc[common].values)
    return {"common_entities": common, "n_common": len(common),
            "spearman": float(rho), "p_value": float(p)}


# ---------------------------------------------------------------------------
# H1 head-to-head: observed on-chain graph vs price-estimated graph
# ---------------------------------------------------------------------------
def h1_observed_vs_estimated(observed_graph, estimated_graphs: dict,
                             est_stress, est_flows, stress_full, flows_full,
                             event_days, alpha=1.0) -> dict:
    """Fit VEIN's SCM on each graph and compare one-step event-window prediction.
    H1 holds if the OBSERVED on-chain graph predicts the cascade better than the
    price-ESTIMATED graphs (lower RMSE / higher timing correlation)."""
    out = {}

    def score(graph, label):
        scm = StructuralCausalModel(graph, alpha=alpha).fit(est_stress, est_flows)
        scm.set_flows(flows_full)
        acc = fz.one_step_accuracy(scm, stress_full, flows_full, event_days)
        return {"model": label, **acc}

    results = [score(observed_graph, "observed_onchain")]
    for name, g in estimated_graphs.items():
        results.append(score(g, f"estimated_{name}"))
    obs = results[0]
    best_est = min((r for r in results[1:]), key=lambda r: r["rmse"], default=None)
    out["scores"] = results
    if best_est:
        out["H1_point_better"] = bool(obs["rmse"] < best_est["rmse"])
        out["rmse_gap_vs_best_estimated"] = float(best_est["rmse"] - obs["rmse"])
    return out


# ---------------------------------------------------------------------------
# 5. H1 status, paired bootstrap of one-step errors, falsification intervals
# ---------------------------------------------------------------------------
def h1_status(ci) -> str:
    """observed_better if the 95% CI of (estimated error - observed error) is above 0,
    estimated_better if it is below 0, inconclusive otherwise."""
    lo, hi = float(ci[0]), float(ci[1])
    if lo > 0:
        return "observed_better"
    if hi < 0:
        return "estimated_better"
    return "inconclusive"


def paired_error_bootstrap(d, tpos, block_len: int = 24, B: int = 2000, seed: int = 7) -> dict:
    """Moving-block bootstrap (blocked over time) of the mean paired error difference d.
    Returns mean_diff, ci95, prob_observed_better (share of replicates above 0) and status."""
    d = np.asarray(d, dtype=float)
    draws = risk.paired_time_block_means(d, np.asarray(tpos), B, block_len,
                                         np.random.default_rng(seed))
    ci = [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]
    return {"mean_diff": float(np.mean(d)), "ci95": ci,
            "prob_observed_better": float(np.mean(draws > 0)), "status": h1_status(ci),
            "block_len": int(block_len), "replicates": int(B)}


def _aligned(a: dict, b: dict):
    if len(a["err2"]) != len(b["err2"]) or not (np.array_equal(a["tpos"], b["tpos"])
                                                and np.array_equal(a["ent"], b["ent"])):
        raise ValueError("paired errors must be evaluated on the same (entity, time) cells")


def h1_bootstrap(obs: dict, est: dict, B: int = 2000, block_len: int = 24, seed: int = 7) -> dict:
    """H1 paired bootstrap of one graph against the observed graph.

    d = est - obs per cell, so a positive mean means the observed graph has the smaller
    error. Main test: unweighted squared error, 24-step blocks. Sensitivity: weighted error
    (werr) and 8-step blocks."""
    _aligned(obs, est)
    d = est["err2"] - obs["err2"]
    main = paired_error_bootstrap(d, obs["tpos"], block_len, B, seed)
    weighted = paired_error_bootstrap(est["werr"] - obs["werr"], obs["tpos"], block_len, B, seed)
    block8 = paired_error_bootstrap(d, obs["tpos"], 8, B, seed)
    return {**main, "ci95_weighted": weighted["ci95"], "ci95_block8": block8["ci95"],
            "status_weighted": weighted["status"], "status_block8": block8["status"]}


def paired_difference_ci(base: dict, alt: dict, B: int = 2000, block_len: int = 24,
                         seed: int = 7) -> dict:
    """Bootstrap CI of alt minus base, squared error per cell (e.g. reversed minus true)."""
    _aligned(base, alt)
    return paired_error_bootstrap(alt["err2"] - base["err2"], base["tpos"], block_len, B, seed)


def onestep_errors(stress, flows, parents, fit_mask, eval_mask, flow_lag=0, alpha=1.0):
    """Ridge one-step-ahead fit on fit rows, evaluated on eval rows.

    Returns weighted/unweighted RMSE, MAE, directional accuracy, the per-cell squared error
    err2 and the weighted error werr, with the (time position, entity position) of every
    cell, so that two graphs evaluated on the same mask can be compared cell by cell."""
    idx = stress.index
    fmap = {(i, j): g.set_index("day").usd_volume.groupby(level=0).sum()
            for (i, j), g in flows.groupby(["from_entity", "to_entity"])}

    def flow_at(p, c, t_pos):
        s = fmap.get((p, c))
        if s is None:
            return 0.0
        day = idx[t_pos - flow_lag] if t_pos - flow_lag >= 0 else idx[0]
        try:
            return float(s.get(day, 0.0))
        except Exception:
            return 0.0

    coefs = {}
    for ent in stress.columns:
        par = [p for p in parents.get(ent, []) if p in stress.columns]
        rows_y, rows_X = [], []
        for tpos in range(1, len(idx)):
            if not fit_mask[tpos]:
                continue
            feats = [stress.iloc[tpos - 1][p] for p in par] + \
                    [np.log1p(flow_at(p, ent, tpos)) for p in par]
            rows_X.append([1.0] + feats); rows_y.append(stress.iloc[tpos][ent])
        if len(rows_y) < 5 or len(par) == 0:
            coefs[ent] = (np.array([np.mean(rows_y) if rows_y else 0.0]), par)
            continue
        X = np.array(rows_X); y = np.array(rows_y)
        A = X.T @ X + alpha * np.eye(X.shape[1]); A[0, 0] -= alpha
        coefs[ent] = (np.linalg.solve(A, X.T @ y), par)

    preds, acts, wts, tpos_all, ent_all = [], [], [], [], []
    for ent_pos, ent in enumerate(stress.columns):
        beta, par = coefs[ent]
        for tpos in range(1, len(idx)):
            if not eval_mask[tpos]:
                continue
            if len(par) == 0 or len(beta) == 1:
                yhat = beta[0]
            else:
                feats = [stress.iloc[tpos - 1][p] for p in par] + \
                        [np.log1p(flow_at(p, ent, tpos)) for p in par]
                yhat = beta @ np.array([1.0] + feats)
            y = stress.iloc[tpos][ent]
            preds.append(yhat); acts.append(y); wts.append(abs(y) + 0.1)
            tpos_all.append(tpos); ent_all.append(ent_pos)
    preds, acts, wts = np.array(preds), np.array(acts), np.array(wts)
    err2 = (preds - acts) ** 2
    wrmse = float(np.sqrt(np.average(err2, weights=wts)))
    rmse = float(np.sqrt(np.mean(err2)))
    mae = float(np.mean(np.abs(preds - acts)))
    diracc = float(np.mean(np.sign(preds) == np.sign(acts)))
    return {"wrmse": wrmse, "rmse": rmse, "mae": mae, "dir_acc": diracc,
            "err2": err2, "werr": err2 * wts, "wts": wts, "n": len(preds),
            "tpos": np.array(tpos_all), "ent": np.array(ent_all)}


def event_masks(stress, ev_start=None, ev_end=None):
    """(fit, event) boolean masks: fit = before the event start, event = inside [start, end]."""
    ev_start = pl.EVENT_START if ev_start is None else pd.Timestamp(ev_start)
    ev_end = pl.EVENT_END if ev_end is None else pd.Timestamp(ev_end)
    idx = stress.index
    ev = np.array([(t >= ev_start) and (t <= ev_end) for t in idx])
    fit = np.array([t < ev_start for t in idx])
    return fit, ev


# ---------------------------------------------------------------------------
# 6. Placebos: rolling calm windows and time-shifted coefficients
# ---------------------------------------------------------------------------
def connected_pairs(graph: dict, nodes, nonzero) -> list:
    """Ordered (i, j) with a directed path i -> j in the graph and i non-degenerate."""
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    for e in graph["edges"]:
        if e["from"] in nodes and e["to"] in nodes:
            G.add_edge(e["from"], e["to"])
    return [(i, j) for i in nodes for j in nodes
            if i != j and i in nonzero and nx.has_path(G, i, j)]


def rolling_temporal_placebo(scm: StructuralCausalModel, stress: pd.DataFrame, fit_index,
                             ev_days, precrisis: dict, connected, step: int = 24,
                             roll: int = 48, gap: int = 24) -> dict:
    """Event statistic against the same statistic on calm windows of the fit period.

    Windows have the event length and start every `step` steps from fit_index[roll + gap]
    on; a window must end at least `gap` steps (rows of the stress panel) before the event starts. p = (1 + #calm >=
    event) / (n + 1); passes if p <= 0.10."""
    nodes = list(scm.stress_cols)
    ev_days = pd.DatetimeIndex(ev_days)
    fit_index = pd.DatetimeIndex(fit_index)
    n = len(ev_days)
    pre = fs._vec(nodes, precrisis)
    stress_idx = stress.index

    sys = fs.from_scm(scm)

    def window_stat(days):
        p0 = stress_idx.get_loc(days[0])
        S_prev0 = stress.iloc[p0 - 1][nodes].values.astype(float)
        S_obs = stress.loc[days, nodes].values.astype(float)
        C = fs.drift(sys, fs.log_flows(scm, days))
        return _stat_from(sys, C, S_obs, S_prev0, pre, connected, nodes)

    event = window_stat(ev_days)
    ev_pos = stress_idx.get_loc(ev_days[0])      # the gap is counted in steps (hours or days)
    calm = []
    start = stress_idx.get_loc(fit_index[min(roll + gap, len(fit_index) - 1)])
    for p in range(start, len(stress_idx), step):
        days = stress_idx[p:p + n]
        if len(days) < n or p + n - 1 > ev_pos - gap or p < 1:
            break
        calm.append(window_stat(days))
    n_w = len(calm)
    p_val = (1 + sum(c >= event for c in calm)) / (n_w + 1)
    return {"event_stat": float(event), "calm_stats": [float(c) for c in calm],
            "n_windows": n_w, "n_connected_pairs": len(connected),
            "p_value": float(p_val), "passes": bool(p_val <= 0.10)}


def time_shift_placebo(scm: StructuralCausalModel, stress: pd.DataFrame, flows_fit: pd.DataFrame,
                       fit_index, ev_days, precrisis: dict, connected, B: int = 100,
                       seed: int = 11, min_shift: int = 72) -> dict:
    """Circularly shift each entity's fit-window stress by an independent offset in
    [min_shift, n_fit - min_shift], refit the equations on the shifted stress with the real
    flows, and recompute the event attribution. The real statistic is compared with the B
    placebo statistics; passes if p <= 0.05."""
    nodes = list(scm.stress_cols)
    ev_days = pd.DatetimeIndex(ev_days)
    fit_index = pd.DatetimeIndex(fit_index)
    fit = stress.loc[fit_index, nodes]
    n_fit = len(fit)
    rng = np.random.default_rng(seed)
    pre = fs._vec(nodes, precrisis)
    p0 = stress.index.get_loc(ev_days[0])
    S_prev0 = stress.iloc[p0 - 1][nodes].values.astype(float)
    S_obs = stress.loc[ev_days, nodes].values.astype(float)
    base = fs.from_scm(scm)
    C_ev = fs.drift(base, fs.log_flows(scm, ev_days))
    real = _stat_from(base, C_ev, S_obs, S_prev0, pre, connected, nodes)
    designs_fn = un.design
    hi = n_fit - min_shift
    placebo = []
    for _ in range(B):
        shifted = fit.copy()
        for e in nodes:
            off = int(rng.integers(min_shift, hi + 1))
            shifted[e] = np.roll(fit[e].values, off)
        designs = designs_fn(scm, shifted, flows_fit)
        sys_b = un.refit(base, designs, np.arange(n_fit - 1), scm.alpha)
        C_b = fs.drift(sys_b, fs.log_flows(scm, ev_days))
        placebo.append(_stat_from(sys_b, C_b, S_obs, S_prev0, pre, connected, nodes))
    p_val = (1 + sum(v >= real for v in placebo)) / (B + 1)
    return {"real_stat": float(real), "placebo_stats": [float(v) for v in placebo],
            "p_value": float(p_val), "passes": bool(p_val <= 0.05), "B": int(B), "seed": int(seed)}


def _stat_from(sys, C, S_obs, S_prev0, pre, connected, nodes):
    if not connected:
        return 0.0
    mat = fs.attribution_matrix(sys, C, S_obs, S_prev0, pre)
    pos = {e: k for k, e in enumerate(nodes)}
    return float(np.mean([abs(mat["attr"][pos[i], pos[j]]) for i, j in connected]))
