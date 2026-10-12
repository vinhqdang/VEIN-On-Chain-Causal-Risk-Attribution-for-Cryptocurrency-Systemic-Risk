"""VEIN risk measures (algorithm.md Section 2.5).

Interventional  : On-Chain Causal CoVaR  (Pearl Level 2, do-operator)
Counterfactual  : per-entity loss attribution (Pearl Level 3, abduction-action-
                  prediction)

Loss functional. We summarize an entity's distress over the event window by the
cumulative positive stress  L_j = sum_t max(S_{j,t}, 0).  This is non-negative,
additive across the window, and increases monotonically with distress, so it
behaves like a loss for VaR/attribution purposes.

Defaults. Full abduction (event-window shocks recovered from the observed path),
a joint bootstrap of fit-window residuals (one row draw shared by all entities,
optionally in contiguous blocks), and a pre-event s* (see fit_window_s_star).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scm import StructuralCausalModel


def loss_functional(series: np.ndarray) -> float:
    return float(np.sum(np.clip(series, 0, None)))


def moving_block_indices(n: int, n_draw: int, block_len: int, rng) -> np.ndarray:
    """Row indices for a moving-block bootstrap over n rows.

    Draws ceil(n_draw / L) block starts uniformly from the n - L + 1 admissible
    positions, with L = min(block_len, n), and concatenates the contiguous runs
    start, ..., start + L - 1, truncated to n_draw. Order is preserved inside
    every block. block_len=1 is ordinary i.i.d. resampling of rows.
    """
    if n <= 0:
        raise ValueError("need at least one row to resample")
    if block_len < 1:
        raise ValueError("block_len must be a positive integer")
    L = min(int(block_len), n)
    n_blocks = -(-n_draw // L)
    starts = rng.integers(0, n - L + 1, size=n_blocks)
    idx = (starts[:, None] + np.arange(L)[None, :]).ravel()
    return idx[:n_draw]


def paired_time_block_means(d: np.ndarray, tpos: np.ndarray, n_boot: int,
                            block_len: int, rng) -> np.ndarray:
    """Moving-block bootstrap means of paired errors d, blocked over TIME.

    d holds one value per (entity, time) cell and tpos the time position of each
    cell. Time steps are resampled in contiguous blocks of block_len steps, and
    every entity's cell at a drawn step comes along, so cross-entity dependence
    within a step and serial dependence across steps are both kept. Each
    replicate is the mean of d over all cells of the drawn steps."""
    d = np.asarray(d, dtype=float)
    tpos = np.asarray(tpos)
    order = np.argsort(tpos, kind="stable")
    d, tpos = d[order], tpos[order]
    starts = np.r_[0, np.flatnonzero(np.diff(tpos)) + 1]
    sums = np.add.reduceat(d, starts)
    counts = np.diff(np.r_[starts, len(d)]).astype(float)
    T = len(starts)
    out = np.empty(n_boot)
    for b in range(n_boot):
        idx = moving_block_indices(T, T, block_len, rng)
        out[b] = sums[idx].sum() / counts[idx].sum()
    return out


def _bootstrap_U(scm: StructuralCausalModel, n_days: int, rng,
                 joint: bool = True, block_len: int = 1) -> dict:
    """Sample an exogenous-shock path by resampling the fit-window residuals.

    joint=True (default): one vector of row indices is drawn and shared by all
    entities, so the cross-entity dependence of the residuals on the same days is
    kept. With block_len > 1 the drawn rows come in contiguous runs of block_len
    days (moving-block bootstrap, see moving_block_indices).
    joint=False: each entity's shocks are resampled independently (i.i.d. only;
    block_len must be 1)."""
    U = {}
    if joint:
        lengths = {len(scm.resid_[e]) for e in scm.stress_cols}
        if len(lengths) > 1:
            raise ValueError("joint bootstrap needs residuals of equal length")
        n_resid = lengths.pop() if lengths else 0
        if n_resid == 0:
            return {e: np.zeros(n_days) for e in scm.stress_cols}
        rows = moving_block_indices(n_resid, n_days, block_len, rng)
        for e in scm.stress_cols:
            U[e] = scm.resid_[e].values[rows]
        return U
    if block_len != 1:
        raise ValueError("block bootstrap resamples joint rows; pass joint=True")
    for e in scm.stress_cols:
        r = scm.resid_[e].values
        if len(r) == 0:
            U[e] = np.zeros(n_days)
        else:
            U[e] = rng.choice(r, size=n_days, replace=True)
    return U


def fit_window_s_star(stress: pd.DataFrame, fit_index, q: float = 0.95) -> dict:
    """Severe-distress level s*_i: the q-quantile of each entity's stress over the
    FIT window only.

    fit_index is the index of the pre-event rows the SCM was estimated on. Rows
    outside it, in particular the event window, never enter the quantile."""
    fit = pd.DatetimeIndex(fit_index)
    rows = stress.loc[stress.index.isin(fit)]
    if rows.empty:
        raise ValueError("s* needs at least one fit-window row")
    return {e: float(np.quantile(rows[e].values, q)) for e in stress.columns}


def oc_covar(scm: StructuralCausalModel, i: str, j: str, days,
             init_stress: dict, s_star: float, q: float = 0.95,
             n_sims: int = 400, seed: int = 0, joint: bool = True,
             block_len: int = 1) -> float:
    """VaR_q of L_j under do(S_i = s_star), via Monte Carlo over exogenous shocks.

    joint and block_len select the bootstrap scheme (see _bootstrap_U)."""
    rng = np.random.default_rng(seed)
    losses = np.empty(n_sims)
    do = {i: np.full(len(days), s_star)}
    for k in range(n_sims):
        U = _bootstrap_U(scm, len(days), rng, joint=joint, block_len=block_len)
        sim = scm.simulate(days, init_stress, U, do=do)
        losses[k] = loss_functional(sim[j].values)
    return float(np.quantile(losses, q))


def delta_oc_covar(scm: StructuralCausalModel, i: str, j: str, days,
                   init_stress: dict, stress_hi: dict, q: float = 0.95,
                   n_sims: int = 400, seed: int = 0, joint: bool = True,
                   block_len: int = 1) -> float:
    """OC-CoVaR change: do(S_i = distress) minus do(S_i = baseline).

    stress_hi[i] is the severe-distress value s* for entity i; baseline is 0
    (median stress after z-scoring). This is the on-chain causal analogue of
    Delta-CoVaR: i's marginal contribution to j's tail loss. joint and block_len
    are passed to the bootstrap (see _bootstrap_U)."""
    hi = oc_covar(scm, i, j, days, init_stress, stress_hi[i], q, n_sims, seed,
                  joint, block_len)
    lo = oc_covar(scm, i, j, days, init_stress, 0.0, q, n_sims, seed, joint, block_len)
    return hi - lo


def systemic_ranking(scm: StructuralCausalModel, days, init_stress: dict,
                     stress_hi: dict, q: float = 0.95, n_sims: int = 300,
                     seed: int = 0, joint: bool = True,
                     block_len: int = 1) -> pd.DataFrame:
    """Rank entities by total exported tail risk: sum_j Delta-OC-CoVaR(j | i)."""
    rows = []
    for i in scm.stress_cols:
        total = 0.0
        per_j = {}
        for j in scm.stress_cols:
            if j == i:
                continue
            d = delta_oc_covar(scm, i, j, days, init_stress, stress_hi, q, n_sims, seed,
                               joint, block_len)
            per_j[j] = d
            total += max(d, 0.0)
        rows.append({"entity": i, "exported_risk": total, **{f"->{k}": v for k, v in per_j.items()}})
    df = pd.DataFrame(rows).sort_values("exported_risk", ascending=False).reset_index(drop=True)
    return df


def _pre_window_state(observed_stress: pd.DataFrame, days, init_stress: dict) -> dict:
    """Stress on the day before the window: the observed row when the stress panel
    has one (the same state event_residuals() inverts from), else init_stress."""
    pos = observed_stress.index.get_loc(pd.Timestamp(days[0]))
    if pos > 0:
        return observed_stress.iloc[pos - 1].to_dict()
    return dict(init_stress)


def counterfactual_attribution(scm: StructuralCausalModel, i: str, j: str, days,
                               observed_stress: pd.DataFrame, init_stress: dict,
                               precrisis_value: float,
                               abduction: str = "full") -> dict:
    """Pearl Level-3 attribution: Delta_i^CF = L_j^observed - L_j^do(S_i=precrisis).

    Abduction recovers U_hat on the actual event window; we then hold every other
    entity's shocks fixed and force i to its pre-crisis stress, recomputing j.

    abduction="full" (default) uses SCM.event_residuals(), which inverts the
    structural equations on the observed event path. It needs the observed stress
    on every day of `days` and a flow span covering the window (set_flows). The
    simulation starts from the observed day before the window when the panel has
    one, so the replay reproduces the observed path exactly.

    abduction="legacy_zero" uses SCM.abduct(), whose event-window shocks are zero
    because the residuals are only defined on the pre-event fit days. It is kept
    for comparison with earlier runs only."""
    if abduction == "full":
        U_hat = scm.event_residuals(observed_stress, days, init_stress)
        init = _pre_window_state(observed_stress, days, init_stress)
    elif abduction == "legacy_zero":
        U_hat = scm.abduct(observed_stress, days)
        init = init_stress
    else:
        raise ValueError(f"unknown abduction mode: {abduction!r}")

    # Observed counterfactual baseline: replay with U_hat and i held at its
    # realized path (reconstructs observed dynamics under the fitted SCM).
    do_obs = {i: observed_stress[i].reindex(pd.DatetimeIndex(days)).fillna(0.0).values}
    sim_obs = scm.simulate(days, init, U_hat, do=do_obs)
    L_obs = loss_functional(sim_obs[j].values)

    # Counterfactual: i never became distressed (held at pre-crisis level).
    do_cf = {i: np.full(len(days), precrisis_value)}
    sim_cf = scm.simulate(days, init, U_hat, do=do_cf)
    L_cf = loss_functional(sim_cf[j].values)

    return {"i": i, "j": j, "L_observed": L_obs, "L_counterfactual": L_cf,
            "attribution": L_obs - L_cf,
            "attribution_share": (L_obs - L_cf) / L_obs if L_obs > 1e-9 else 0.0}
