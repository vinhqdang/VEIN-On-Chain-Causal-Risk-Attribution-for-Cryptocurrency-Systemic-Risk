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


# ---------------------------------------------------------------------------
# 1. External validity vs the documented Oct-2025 post-mortem narrative
# ---------------------------------------------------------------------------
# Documented mechanics (public post-mortems): the USDe depeg was a pricing/
# liquidity artifact (Ethena stayed solvent) and Binance's internal pricing
# engine drove automated liquidations -> Ethena and the CEX are stress
# *transmitters*; Aave (zero bad debt) and Lido were *absorbers*.
DOCUMENTED_TRANSMITTERS = {"Ethena", "Binance"}
DOCUMENTED_ABSORBERS = {"Aave", "Lido"}


def external_validity(oc_ranking: pd.DataFrame) -> dict:
    """Do OC-CoVaR exported-risk scores rank documented transmitters above
    documented absorbers? Reports per-entity match and a separation score."""
    score = dict(zip(oc_ranking["entity"], oc_ranking["exported_risk"]))
    t = [score.get(e, 0.0) for e in DOCUMENTED_TRANSMITTERS if e in score]
    a = [score.get(e, 0.0) for e in DOCUMENTED_ABSORBERS if e in score]
    detail = {e: float(score.get(e, 0.0))
              for e in (DOCUMENTED_TRANSMITTERS | DOCUMENTED_ABSORBERS) if e in score}
    sep = (float(np.mean(t)) - float(np.mean(a))) if t and a else float("nan")
    # pairwise concordance: fraction of (transmitter, absorber) pairs ordered right
    pairs = [(x, y) for x in t for y in a]
    conc = float(np.mean([x > y for x, y in pairs])) if pairs else float("nan")
    return {"transmitter_scores": {e: float(score.get(e, 0.0)) for e in DOCUMENTED_TRANSMITTERS if e in score},
            "absorber_scores": {e: float(score.get(e, 0.0)) for e in DOCUMENTED_ABSORBERS if e in score},
            "separation": sep, "pairwise_concordance": conc, "detail": detail}


# ---------------------------------------------------------------------------
# 2. Placebo / negative controls
# ---------------------------------------------------------------------------
def placebo_negative_controls(scm: StructuralCausalModel, graph: dict, days,
                              observed_stress: pd.DataFrame, init_stress: dict,
                              precrisis: dict) -> dict:
    """A valid causal method must attribute ~0 loss across edges with NO directed
    on-chain path. We compare |attribution| for connected vs unconnected (i,j)."""
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
        "n_connected_pairs": len(connected), "n_unconnected_pairs": len(unconnected),
        "mean_abs_attr_connected": float(np.mean(connected)) if connected else 0.0,
        "mean_abs_attr_unconnected": float(np.mean(unconnected)) if unconnected else 0.0,
        "max_abs_attr_unconnected": float(np.max(unconnected)) if unconnected else 0.0,
        # pass if unconnected attribution is ~0 and well below connected
        "passes": bool((np.max(unconnected) if unconnected else 0.0) < 1e-6),
    }


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
        out["H1_supported"] = bool(obs["rmse"] < best_est["rmse"])
        out["rmse_gap_vs_best_estimated"] = float(best_est["rmse"] - obs["rmse"])
    return out
