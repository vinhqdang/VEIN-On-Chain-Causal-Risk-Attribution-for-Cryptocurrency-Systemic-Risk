"""Benchmark systemic-risk measures (algorithm.md Section 4.1).

Delta-CoVaR (Adrian & Brunnermeier 2016) via quantile regression on price
returns — the standard non-causal measure VEIN is compared against (H3). We
also expose a simple price-correlation graph used as the symmetric baseline and
for the H5 "edge adds info beyond correlation" comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor


def _var(series: np.ndarray, q: float) -> float:
    return float(np.quantile(series, q))


def delta_covar(returns: pd.DataFrame, system_col: str | None = None,
                q: float = 0.05) -> pd.DataFrame:
    """Delta-CoVaR for each asset i on the system (mean of the rest).

    CoVaR_q(system | i at VaR_q) via quantile regression r_sys = a + b r_i.
    Delta-CoVaR = b * (VaR_q(i) - VaR_50(i)).  Returns one row per asset; a more
    negative Delta-CoVaR = larger systemic-risk contribution.
    """
    rets = returns.dropna()
    rows = []
    for i in rets.columns:
        others = [c for c in rets.columns if c != i]
        if not others:
            continue
        r_sys = rets[others].mean(axis=1).values if system_col is None else rets[system_col].values
        r_i = rets[i].values.reshape(-1, 1)
        try:
            qr = QuantileRegressor(quantile=q, alpha=0.0, solver="highs").fit(r_i, r_sys)
            b = float(qr.coef_[0]); a = float(qr.intercept_)
        except Exception:
            b, a = 0.0, float(np.quantile(r_sys, q))
        var_q = _var(rets[i].values, q)
        var_50 = _var(rets[i].values, 0.5)
        covar_q = a + b * var_q
        covar_50 = a + b * var_50
        rows.append({"asset": i, "VaR_q": var_q, "CoVaR_q": covar_q,
                     "delta_covar": covar_q - covar_50})
    df = pd.DataFrame(rows)
    # rank: most systemically risky = most negative delta_covar
    df["rank"] = df["delta_covar"].rank(method="min").astype(int)
    return df.sort_values("delta_covar").reset_index(drop=True)


def correlation_graph(returns: pd.DataFrame, threshold: float = 0.3) -> dict:
    """Undirected price-correlation graph (parents = correlated assets)."""
    corr = returns.corr().abs()
    nodes = list(returns.columns)
    parents = {n: [] for n in nodes}
    edges = []
    for a in nodes:
        for b in nodes:
            if a != b and corr.at[a, b] >= threshold:
                parents[a].append(b)
                edges.append({"from": b, "to": a, "weight": float(corr.at[a, b])})
    return {"nodes": nodes, "edges": edges, "parents": parents, "corr": corr}
