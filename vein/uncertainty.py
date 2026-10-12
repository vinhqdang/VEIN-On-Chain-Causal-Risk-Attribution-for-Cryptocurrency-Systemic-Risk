"""Sampling uncertainty of the ranking, the attribution and the Shapley split.

Two sources are separated:
  * Monte Carlo error: the exported-risk estimate with n_sims shock paths varies with the
    seed (mc_error). The point estimate uses 2000 paths, so its error is the 500-path
    spread scaled by sqrt(500/2000).
  * Estimation error of the coefficients: a joint moving-block pairs bootstrap over the
    fit-window rows, with a ridge refit of every equation in each replicate
    (bootstrap_systems). Residuals of the refit form the shock pool of that replicate.

The fit-window s* (severe-distress level) is held fixed across replicates.
"""
from __future__ import annotations

import itertools
from typing import Iterator

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
from sklearn.linear_model import Ridge

from . import fastscm as fs
from . import risk
from .scm import StructuralCausalModel

BLOCK_LEN = 24          # hours
TRANSMITTERS = ("Ethena", "Binance")
ABSORBERS = ("Aave", "Lido")


# ---------------------------------------------------------------- design & refit
def design(scm: StructuralCausalModel, stress: pd.DataFrame, flows: pd.DataFrame) -> dict:
    """Per-entity regression rows {entity: (X, y, parents)}, built as in StructuralCausalModel.fit
    (same features, same column order, same row order)."""
    fp = {}
    for (i, j), g in flows.groupby(["from_entity", "to_entity"]):
        fp[(i, j)] = g.set_index("day").usd_volume
    idx = stress.index
    out = {}
    for ent in scm.stress_cols:
        par = list(scm.coef_[ent]["parents"])
        y = stress[ent].values[1:]
        feats = [stress[p].values[:-1] for p in par]
        feats += [scm._flow_feature(fp, p, ent, idx)[1:] for p in par]
        X = np.column_stack(feats) if feats else np.zeros((len(y), 0))
        out[ent] = (X, y, par)
    return out


def refit(base: fs.LinearSystem, designs: dict, rows, alpha: float = 1.0) -> fs.LinearSystem:
    """Ridge refit of every equation on the design rows `rows` (with repetition allowed).

    Residuals are y - yhat on all design rows in their original order."""
    rows = np.asarray(rows)
    pos = {e: i for i, e in enumerate(base.nodes)}
    N = base.n
    A, Wf, b = np.zeros((N, N)), np.zeros((N, N)), np.zeros(N)
    n_rows = len(next(iter(designs.values()))[1])
    resid = np.zeros((n_rows, N))
    for e in base.nodes:
        X, y, par = designs[e]
        i = pos[e]
        if not par:
            b[i] = float(np.mean(y[rows]))
            resid[:, i] = y - b[i]
            continue
        m = Ridge(alpha=alpha, fit_intercept=True).fit(X[rows], y[rows])
        k = len(par)
        for q, p in enumerate(par):
            A[i, pos[p]] = m.coef_[q]
            Wf[i, pos[p]] = m.coef_[k + q]
        b[i] = float(m.intercept_)
        resid[:, i] = y - m.predict(X)
    return fs.LinearSystem(list(base.nodes), A, Wf, b, resid)


def bootstrap_systems(scm: StructuralCausalModel, stress_fit: pd.DataFrame,
                      flows_fit: pd.DataFrame, ev_days, n_boot: int, seed: int,
                      block_len: int = BLOCK_LEN, alpha: float = 1.0) -> Iterator:
    """Yield (r, rows, sys_r, C_r) for n_boot replicates.

    rows are the joint moving-block draw of the n-1 design rows; C_r is the drift on the
    event days under the refitted coefficients."""
    designs = design(scm, stress_fit, flows_fit)
    base = fs.from_scm(scm)
    LF = fs.log_flows(scm, ev_days)
    n_rows = len(stress_fit) - 1
    rng = np.random.default_rng(seed)
    for r in range(n_boot):
        rows = risk.moving_block_indices(n_rows, n_rows, block_len, rng)
        sys_r = refit(base, designs, rows, alpha)
        yield r, rows, sys_r, fs.drift(sys_r, LF)


# ---------------------------------------------------------------- Monte Carlo error
def mc_error(sys: fs.LinearSystem, C, init, s_star, n_rep: int = 20, n_sims: int = 500,
             block_len: int = BLOCK_LEN, seed0: int = 1000) -> dict:
    """Spread of the exported risk across n_rep seeds with n_sims paths each.

    se_point = sd * sqrt(n_sims / 2000): the Monte Carlo error of a 2000-path point estimate."""
    T = np.asarray(C).shape[0]
    E = np.array([fs.exported_risk(sys, C, init, s_star,
                                   fs.shock_rows(sys.resid.shape[0], T, n_sims, block_len, seed0 + r))[0]
                  for r in range(n_rep)])
    sd = E.std(axis=0, ddof=1)
    se = sd * np.sqrt(n_sims / 2000)
    return {"n_rep": n_rep, "n_sims": n_sims, "sd": sd, "se_point": se, "nodes": list(sys.nodes)}


# ---------------------------------------------------------------- ranking uncertainty
def ranking_draws(scm, stress_fit, flows_fit, ev_days, s_star, init, n_boot=300, n_sims=500,
                  block_len=BLOCK_LEN, q=0.95, seed=20251010, alpha=1.0) -> np.ndarray:
    """Exported risk (n_boot, N) over joint coefficient bootstrap replicates. Each replicate
    uses n_sims shock paths drawn from default_rng([seed, r])."""
    ev_days = pd.DatetimeIndex(ev_days)
    T = len(ev_days)
    E_all = []
    for r, rows, sys_r, C_r in bootstrap_systems(scm, stress_fit, flows_fit, ev_days,
                                                 n_boot, seed, block_len, alpha):
        shocks = fs.shock_rows(sys_r.resid.shape[0], T, n_sims, block_len,
                               np.random.default_rng([seed, r]))
        E_all.append(fs.exported_risk(sys_r, C_r, init, s_star, shocks, q)[0])
    return np.array(E_all)


def summarize_ranking(E: np.ndarray, nodes, point_E, transmitters=TRANSMITTERS,
                      absorbers=ABSORBERS, n_top: int = 6) -> dict:
    """Ranking summary: per-entity intervals, top-k probabilities, pairwise order
    probabilities among the n_top point-ranked entities, Spearman agreement with the point
    ranking and external-validity concordance."""
    E = np.asarray(E, dtype=float)
    nodes = list(nodes)
    point_E = np.asarray(point_E, dtype=float)
    n_boot, N = E.shape
    RK = np.array([rankdata(-e, method="min") for e in E])
    rk_point = rankdata(-point_E, method="min")
    by = {}
    for i, e in enumerate(nodes):
        rk = RK[:, i]
        by[e] = {"exported_risk_median": float(np.median(E[:, i])),
                 "exported_risk_ci95": [float(np.quantile(E[:, i], 0.025)), float(np.quantile(E[:, i], 0.975))],
                 "rank_point": int(rk_point[i]),
                 "rank_median": float(np.median(rk)),
                 "rank_ci95": [float(np.quantile(rk, 0.025, method="lower")),
                               float(np.quantile(rk, 0.975, method="higher"))],
                 "p_top1": float(np.mean(rk <= 1)), "p_top3": float(np.mean(rk <= 3)),
                 "p_top5": float(np.mean(rk <= 5))}
    top = [nodes[i] for i in np.argsort(rk_point, kind="stable")[:n_top]]
    P = [[None if a == b else float(np.mean(E[:, nodes.index(a)] > E[:, nodes.index(b)]))
          for b in top] for a in top]
    rho = []
    for r in range(n_boot):
        v = spearmanr(RK[r], rk_point).statistic
        rho.append(float(v) if np.isfinite(v) else np.nan)
    rho = np.array(rho)
    T_ = [nodes.index(e) for e in transmitters if e in nodes]
    A_ = [nodes.index(e) for e in absorbers if e in nodes]
    if T_ and A_:
        p_sep = float(np.mean(E[:, T_].min(axis=1) > E[:, A_].max(axis=1)))
        pairs = E[:, T_][:, :, None] > E[:, A_][:, None, :]          # (n_boot, |T|, |A|)
        conc = float(np.mean(pairs.mean(axis=(1, 2))))
    else:
        p_sep, conc = None, None
    return {"by_entity": by,
            "pairwise_top6": {"entities": top, "p_row_above_col": P},
            "spearman_vs_point": {"mean": float(np.nanmean(rho)),
                                  "q025": float(np.nanquantile(rho, 0.025)),
                                  "q975": float(np.nanquantile(rho, 0.975))},
            "external_validity": {"p_all_transmitters_above_absorbers": p_sep,
                                  "mean_concordance": conc,
                                  "transmitters": [nodes[i] for i in T_], "absorbers": [nodes[i] for i in A_]}}


# ---------------------------------------------------------------- attribution
def attribution_draws(scm, stress_fit, flows_fit, ev_days, S_obs, S_prev0, precrisis,
                      n_boot=300, block_len=BLOCK_LEN, seed=20251011, alpha=1.0) -> dict:
    """Attribution matrices (n_boot, N, N) over the same kind of coefficient bootstrap.
    Abduction is redone with each replicate's coefficients."""
    ev_days = pd.DatetimeIndex(ev_days)
    out = {"L_obs": [], "attr": [], "share": [], "r2": []}
    for r, rows, sys_r, C_r in bootstrap_systems(scm, stress_fit, flows_fit, ev_days,
                                                 n_boot, seed, block_len, alpha):
        m = fs.attribution_matrix(sys_r, C_r, S_obs, S_prev0, precrisis)
        for k in ("L_obs", "attr", "share"):
            out[k].append(m[k])
        out["r2"].append(r2_in_sample(sys_r, stress_fit))
    return {k: np.array(v) for k, v in out.items()}


def r2_in_sample(sys: fs.LinearSystem, stress_fit: pd.DataFrame) -> dict:
    """In-sample R^2 of each refitted equation over its design rows."""
    y = stress_fit[sys.nodes].values[1:]
    ss_tot = ((y - y.mean(axis=0)) ** 2).sum(axis=0)
    ss_res = (sys.resid ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = 1 - ss_res / ss_tot
    return {e: float(r2[i]) if np.isfinite(r2[i]) else float("nan") for i, e in enumerate(sys.nodes)}


# ---------------------------------------------------------------- Shapley
def shapley_split(sys: fs.LinearSystem, C, S_obs, S_prev0, precrisis, target: str, cands) -> dict:
    """Shapley split of the target's event loss over candidate entities (run_revision.Lj on
    the fast engine). Every entity other than the target is intervened on: candidates in a
    coalition at their observed path, everyone else at the pre-crisis level."""
    nodes = list(sys.nodes)
    tk = nodes.index(target)
    S_obs = np.asarray(S_obs, dtype=float)
    T = S_obs.shape[0]
    pre = fs._vec(nodes, precrisis)
    U_hat = fs.abduct(sys, C, S_obs, S_prev0)[None]
    do_idx = [k for k in range(len(nodes)) if k != tk]

    def Lj(coalition):
        vals = np.column_stack([S_obs[:, k] if nodes[k] in coalition else np.full(T, pre[k])
                                for k in do_idx])
        sim = fs.simulate_batch(sys, C, S_prev0, U_hat, do_idx, vals)
        return risk.loss_functional(sim[0, :, tk])

    cands = list(cands)
    full, none = Lj(set(cands)), Lj(set())
    shap = {s: 0.0 for s in cands}
    perms = list(itertools.permutations(cands))
    for perm in perms:
        cur, prev = set(), Lj(set())
        for s in perm:
            cur = cur | {s}
            nv = Lj(cur)
            shap[s] += nv - prev
            prev = nv
    shap = {s: shap[s] / len(perms) for s in cands}
    total = full - none
    return {"values": shap, "total": float(total),
            "additive_residual": float(total - sum(shap.values()))}
