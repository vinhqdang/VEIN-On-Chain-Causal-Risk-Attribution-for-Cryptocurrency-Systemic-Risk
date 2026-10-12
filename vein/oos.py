"""Out-of-sample R^2 of the hourly stress equations, with an own-lag (no-graph) baseline.

Design. For every event hour t (48 hours, Oct 10-11) and every entity i, each model is refit on
all design rows whose target hour is before t (an expanding window that starts at the first
fit-window row, ridge alpha = 1 with intercept, the same estimator as the SCM) and predicts
S_{i,t} from information dated t - 1 (stress) and t (flows, contemporaneous as in the SCM).
Nothing from hour t or later enters a prediction. Models:

  mean         intercept only: expanding historical mean (the benchmark)
  ar           own lag S_{i,t-1} only (AR(1); no graph, no flows)
  network      the SCM equation of the observed graph: lagged parent stress + log1p parent flows
               (an entity without parents falls back to the mean)
  ar_network   own lag plus the network regressors (does the graph add to the own lag?)

Out-of-sample R^2 (Campbell-Thompson):  R2_OS(m) = 1 - SSE(m) / SSE(mean), over the event cells.
Stress series are z-scored, so SSE pools across entities on a common scale. Network increment
over the own-lag model: 1 - SSE(m) / SSE(ar) for m = network, ar_network, with a circular block
bootstrap over event hours (all entities of a drawn hour travel together). The event window has
48 hours, so with 24-hour blocks there are only two blocks: the intervals are indicative; an
8-hour-block version is reported alongside.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from . import risk
from . import uncertainty as un
from .scm import StructuralCausalModel

MODELS = ("mean", "ar", "network", "ar_network")


def _predict(X, y, r, alpha):
    """Fit on rows [0, r) and predict row r (intercept only when X has no columns)."""
    if X.shape[1] == 0 or r < 3:
        return float(np.mean(y[:r]))
    m = Ridge(alpha=alpha, fit_intercept=True).fit(X[:r], y[:r])
    return float(m.predict(X[r:r + 1])[0])


def rolling_one_step(scm: StructuralCausalModel, stress: pd.DataFrame, flows: pd.DataFrame,
                     ev_index, alpha: float = 1.0) -> dict:
    """Per-cell predictions of every model on the event hours (see module docstring).

    Returns arrays over cells ordered by (entity, event step): ent, step, y, pred[model]."""
    ev_index = pd.DatetimeIndex(ev_index)
    designs = un.design(scm, stress, flows)
    rows_ev = np.array([stress.index.get_loc(t) - 1 for t in ev_index])   # design row = time pos - 1
    nodes = list(scm.stress_cols)
    out = {"nodes": nodes, "ent": [], "step": [], "y": [], "pred": {m: [] for m in MODELS}}
    for k, e in enumerate(nodes):
        Xn, y, par = designs[e]
        own = stress[e].values[:-1][:, None]
        Xs = {"mean": np.zeros((len(y), 0)), "ar": own, "network": Xn,
              "ar_network": np.hstack([own, Xn])}
        for s, r in enumerate(rows_ev):
            out["ent"].append(k); out["step"].append(s); out["y"].append(float(y[r]))
            for m in MODELS:
                out["pred"][m].append(_predict(Xs[m], y, int(r), alpha))
    for key in ("ent", "step", "y"):
        out[key] = np.array(out[key])
    out["pred"] = {m: np.array(v) for m, v in out["pred"].items()}
    return out


def _ratio_stat(S, num_idx, den_idx, idx):
    """1 - sum(S[idx, num]) / sum(S[idx, den]) for a (T, K) per-step SSE matrix."""
    den = S[idx, den_idx].sum()
    return float("nan") if den <= 1e-12 else float(1 - S[idx, num_idx].sum() / den)


def summarize(res: dict, B: int = 2000, block_len: int = 24, seed: int = 7) -> dict:
    """R2_OS per model (pooled and per entity) and bootstrap intervals of the pooled values."""
    nodes = res["nodes"]
    T = int(res["step"].max()) + 1
    err = {m: (res["pred"][m] - res["y"]) ** 2 for m in MODELS}
    S = np.zeros((T, len(MODELS)))
    for k, m in enumerate(MODELS):
        S[:, k] = np.bincount(res["step"], weights=err[m], minlength=T)
    mi = {m: k for k, m in enumerate(MODELS)}

    def pooled(num, den, idx=slice(None)):
        return _ratio_stat(S, mi[num], mi[den], idx)

    def boot(num, den, bl):
        rng = np.random.default_rng(seed)
        v = np.array([pooled(num, den, risk.moving_block_indices(T, T, bl, rng)) for _ in range(B)])
        v = v[np.isfinite(v)]
        return v

    def ci(v):
        return [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]

    out = {"design": "expanding-window ridge refit (alpha=1) before each event hour; one-step ahead",
           "n_event_hours": T, "n_cells": int(len(res["y"])), "bootstrap": {
               "kind": "circular block over event hours", "B": B, "block_len": block_len,
               "block_len_sensitivity": 8, "note": "48 hours = 2 blocks of 24: indicative only"},
           "pooled": {}, "increment_over_ar": {}, "by_entity": {}}
    out["pooled"]["sse"] = {m: float(S[:, mi[m]].sum()) for m in MODELS}
    for m in MODELS[1:]:
        v, v8 = boot(m, "mean", block_len), boot(m, "mean", 8)
        out["pooled"][m] = {"r2_os": pooled(m, "mean"), "ci95": ci(v), "ci95_block8": ci(v8)}
    for m in ("network", "ar_network"):
        v, v8 = boot(m, "ar", block_len), boot(m, "ar", 8)
        out["increment_over_ar"][m] = {"gain": pooled(m, "ar"), "ci95": ci(v), "ci95_block8": ci(v8),
                                       "boot_mean": float(np.mean(v))}
    for k, e in enumerate(nodes):
        sel = res["ent"] == k
        base = err["mean"][sel].sum()
        row = {"sse_mean": float(base)}
        for m in MODELS[1:]:
            row[m] = float(1 - err[m][sel].sum() / base) if base > 1e-12 else None
        a = err["ar"][sel].sum()
        for m in ("network", "ar_network"):
            row[f"{m}_vs_ar"] = float(1 - err[m][sel].sum() / a) if a > 1e-12 else None
        out["by_entity"][e] = row
    for m in MODELS[1:]:
        v = [r[m] for r in out["by_entity"].values() if r[m] is not None]
        out["pooled"][m]["macro_mean_r2_os"] = float(np.mean(v)) if v else None
    out["pooled"]["note"] = "pooled R2_OS weights entities by benchmark SSE (Aave dominates); macro_mean_r2_os is the equal-weight mean over entities"
    return out
