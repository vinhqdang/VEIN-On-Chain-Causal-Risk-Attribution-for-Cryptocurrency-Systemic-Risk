"""Price-estimated contagion graph — the SOTA baseline for H1.

The nearest causal precedents estimate the contagion/causal graph *statistically*
from price returns rather than observing it on-chain:
  - Causal-NECO VaR (Rigana, Wit & Cook 2024): PC-stable structure learning on
    returns.
  - TV-DIG (Etesami, Habibnia & Kiyavash 2023): directed-information (generalized
    Granger) graph on returns.

We reproduce that *approach* on our data with two estimators over the same entity
node set, so VEIN's machinery can be run on an estimated graph and compared
head-to-head with the observed on-chain graph (hypothesis H1). The point is not
to perfectly re-implement those papers but to give the "estimated graph" school a
fair, like-for-like shot on the same entities and stress targets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

# Map each entity to a representative market-return ticker (price-side proxy).
ENTITY_ASSET = {
    "Binance": "BNB", "Ethena": "ENA", "Aave": "AAVE",
    "Lido": "stETH", "retail": "ETH", "MakerSky": "DAI",
}


def entity_return_panel(returns: pd.DataFrame, entities: list[str]) -> pd.DataFrame:
    """Build an entity-indexed return panel using each entity's proxy asset."""
    cols = {}
    for e in entities:
        a = ENTITY_ASSET.get(e)
        if a and a in returns.columns:
            cols[e] = returns[a]
    return pd.DataFrame(cols).dropna()


def _ols_tstat(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS t-stats for each coefficient (X includes intercept column)."""
    XtX = X.T @ X
    XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    sigma2 = (resid @ resid) / dof
    se = np.sqrt(np.maximum(np.diag(XtX_inv) * sigma2, 1e-18))
    return beta / se, dof


def granger_graph(ret_panel: pd.DataFrame, alpha: float = 0.10, lag: int = 1) -> dict:
    """Directed graph: edge i->j if i's lagged return Granger-predicts j's return.

    For each ordered pair we regress r_j(t) on [const, r_j(t-1), r_i(t-1)] and
    keep i->j when the coefficient on r_i(t-1) is significant at `alpha`.
    """
    nodes = list(ret_panel.columns)
    parents = {n: [] for n in nodes}
    edges = []
    R = ret_panel.values
    n = len(ret_panel)
    if n < 20:
        return {"nodes": nodes, "edges": edges, "parents": parents, "method": "granger"}
    for jx, j in enumerate(nodes):
        yj = R[lag:, jx]
        yj_lag = R[:-lag, jx]
        for ix, i in enumerate(nodes):
            if i == j:
                continue
            ri_lag = R[:-lag, ix]
            X = np.column_stack([np.ones_like(yj), yj_lag, ri_lag])
            t, dof = _ols_tstat(yj, X)
            p = 2 * (1 - stats.t.cdf(abs(t[2]), dof))   # coeff on r_i(t-1)
            if p < alpha:
                parents[j].append(i)
                edges.append({"from": i, "to": j, "p_value": float(p),
                              "source": "granger"})
    return {"nodes": nodes, "edges": edges, "parents": parents, "method": "granger"}


def partial_correlation_graph(ret_panel: pd.DataFrame, thresh: float = 0.2) -> dict:
    """Undirected (symmetrized) partial-correlation graph (CoRisk-style)."""
    nodes = list(ret_panel.columns)
    parents = {n: [] for n in nodes}
    edges = []
    if len(ret_panel) < len(nodes) + 2:
        return {"nodes": nodes, "edges": edges, "parents": parents, "method": "pcorr"}
    cov = np.cov(ret_panel.values, rowvar=False)
    prec = np.linalg.pinv(cov)                      # precision matrix
    d = np.sqrt(np.diag(prec))
    pcorr = -prec / np.outer(d, d)
    for a in range(len(nodes)):
        for b in range(len(nodes)):
            if a != b and abs(pcorr[a, b]) >= thresh:
                parents[nodes[a]].append(nodes[b])  # symmetric -> both directions
                edges.append({"from": nodes[b], "to": nodes[a],
                              "pcorr": float(pcorr[a, b]), "source": "pcorr"})
    return {"nodes": nodes, "edges": edges, "parents": parents, "method": "pcorr"}
