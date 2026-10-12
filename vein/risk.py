"""VEIN risk measures (algorithm.md Section 2.5).

Interventional  : On-Chain Causal CoVaR  (Pearl Level 2, do-operator)
Counterfactual  : per-entity loss attribution (Pearl Level 3, abduction-action-
                  prediction)

Loss functional. We summarize an entity's distress over the event window by the
cumulative positive stress  L_j = sum_t max(S_{j,t}, 0).  This is non-negative,
additive across the window, and increases monotonically with distress, so it
behaves like a loss for VaR/attribution purposes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scm import StructuralCausalModel


def loss_functional(series: np.ndarray) -> float:
    return float(np.sum(np.clip(series, 0, None)))


def _bootstrap_U(scm: StructuralCausalModel, n_days: int, rng,
                 joint: bool = False) -> dict:
    """Sample an exogenous-shock path by resampling the residuals.

    joint=False (legacy, used for the published numbers): each entity's shocks
    are resampled independently.
    joint=True: one vector of row indices is drawn and shared by all entities,
    so the cross-entity dependence of the residuals on the same days is kept.
    """
    U = {}
    if joint:
        lengths = {len(scm.resid_[e]) for e in scm.stress_cols}
        if len(lengths) > 1:
            raise ValueError("joint bootstrap needs residuals of equal length")
        n_resid = lengths.pop() if lengths else 0
        if n_resid == 0:
            return {e: np.zeros(n_days) for e in scm.stress_cols}
        rows = rng.choice(n_resid, size=n_days, replace=True)
        for e in scm.stress_cols:
            U[e] = scm.resid_[e].values[rows]
        return U
    for e in scm.stress_cols:
        r = scm.resid_[e].values
        if len(r) == 0:
            U[e] = np.zeros(n_days)
        else:
            U[e] = rng.choice(r, size=n_days, replace=True)
    return U


def oc_covar(scm: StructuralCausalModel, i: str, j: str, days,
             init_stress: dict, s_star: float, q: float = 0.95,
             n_sims: int = 400, seed: int = 0, joint: bool = False) -> float:
    """VaR_q of L_j under do(S_i = s_star), via Monte Carlo over exogenous shocks.

    joint selects the bootstrap scheme (see _bootstrap_U); the default is the
    legacy independent-per-entity resampling."""
    rng = np.random.default_rng(seed)
    losses = np.empty(n_sims)
    do = {i: np.full(len(days), s_star)}
    for k in range(n_sims):
        U = _bootstrap_U(scm, len(days), rng, joint=joint)
        sim = scm.simulate(days, init_stress, U, do=do)
        losses[k] = loss_functional(sim[j].values)
    return float(np.quantile(losses, q))


def delta_oc_covar(scm: StructuralCausalModel, i: str, j: str, days,
                   init_stress: dict, stress_hi: dict, q: float = 0.95,
                   n_sims: int = 400, seed: int = 0, joint: bool = False) -> float:
    """OC-CoVaR change: do(S_i = distress) minus do(S_i = baseline).

    stress_hi[i] is the severe-distress value s* for entity i; baseline is 0
    (median stress after z-scoring). This is the on-chain causal analogue of
    Delta-CoVaR: i's marginal contribution to j's tail loss. joint is passed
    to the bootstrap (see _bootstrap_U)."""
    hi = oc_covar(scm, i, j, days, init_stress, stress_hi[i], q, n_sims, seed, joint)
    lo = oc_covar(scm, i, j, days, init_stress, 0.0, q, n_sims, seed, joint)
    return hi - lo


def systemic_ranking(scm: StructuralCausalModel, days, init_stress: dict,
                     stress_hi: dict, q: float = 0.95, n_sims: int = 300,
                     seed: int = 0, joint: bool = False) -> pd.DataFrame:
    """Rank entities by total exported tail risk: sum_j Delta-OC-CoVaR(j | i)."""
    rows = []
    for i in scm.stress_cols:
        total = 0.0
        per_j = {}
        for j in scm.stress_cols:
            if j == i:
                continue
            d = delta_oc_covar(scm, i, j, days, init_stress, stress_hi, q, n_sims, seed, joint)
            per_j[j] = d
            total += max(d, 0.0)
        rows.append({"entity": i, "exported_risk": total, **{f"->{k}": v for k, v in per_j.items()}})
    df = pd.DataFrame(rows).sort_values("exported_risk", ascending=False).reset_index(drop=True)
    return df


def counterfactual_attribution(scm: StructuralCausalModel, i: str, j: str, days,
                               observed_stress: pd.DataFrame, init_stress: dict,
                               precrisis_value: float,
                               abduction: str = "legacy_zero") -> dict:
    """Pearl Level-3 attribution: Delta_i^CF = L_j^observed - L_j^do(S_i=precrisis).

    Abduction recovers U_hat on the actual event window; we then hold every other
    entity's shocks fixed and force i to its pre-crisis stress, recomputing j.

    abduction="legacy_zero" (default, produced the published numbers) uses
    SCM.abduct(), whose event-window shocks are zero because the residuals are
    only defined on the pre-event fit days. abduction="full" uses
    SCM.event_residuals(), which inverts the structural equations on the
    observed event path."""
    if abduction == "legacy_zero":
        U_hat = scm.abduct(observed_stress, days)
    elif abduction == "full":
        U_hat = scm.event_residuals(observed_stress, days, init_stress)
    else:
        raise ValueError(f"unknown abduction mode: {abduction!r}")

    # Observed counterfactual baseline: replay with U_hat and i held at its
    # realized path (reconstructs observed dynamics under the fitted SCM).
    do_obs = {i: observed_stress[i].reindex(pd.DatetimeIndex(days)).fillna(0.0).values}
    sim_obs = scm.simulate(days, init_stress, U_hat, do=do_obs)
    L_obs = loss_functional(sim_obs[j].values)

    # Counterfactual: i never became distressed (held at pre-crisis level).
    do_cf = {i: np.full(len(days), precrisis_value)}
    sim_cf = scm.simulate(days, init_stress, U_hat, do=do_cf)
    L_cf = loss_functional(sim_cf[j].values)

    return {"i": i, "j": j, "L_observed": L_obs, "L_counterfactual": L_cf,
            "attribution": L_obs - L_cf,
            "attribution_share": (L_obs - L_cf) / L_obs if L_obs > 1e-9 else 0.0}
