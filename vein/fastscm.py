"""Vectorized engine for the fitted SCM: the same numbers as vein/scm.py and vein/risk.py,
computed for a whole batch of Monte Carlo draws at once.

The fitted equations are linear, S_t = b + A S_{t-1} + Wf L_t + U_t, with L_t the log1p
parent->child flows of day t. LinearSystem holds (A, Wf, b) and the fit-window residuals;
drift() turns the flows into the per-day intercept C_t. simulate_batch() then runs M
shock paths together, and exported_risk() / attribution_matrix() reproduce
risk.systemic_ranking() and risk.counterfactual_attribution() (full abduction).

Random draws follow risk.py: shock_rows() consumes the generator in the same order as
risk.oc_covar(), so the Monte Carlo estimates agree draw by draw.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import risk
from .scm import StructuralCausalModel

FIT_STD_MIN = 1e-9


@dataclass
class LinearSystem:
    nodes: list          # entity order (scm.stress_cols)
    A: np.ndarray        # (N, N): A[e, p] = lagged-stress coefficient of p in the equation of e
    Wf: np.ndarray       # (N, N): Wf[e, p] = coefficient of log1p(flow p -> e)
    b: np.ndarray        # (N,)  intercepts
    resid: np.ndarray    # (n_resid, N) fit-window residuals (rows aligned by position)
    resid_all: np.ndarray | None = None   # bootstrap refits only: residuals of every original row

    @property
    def n(self) -> int:
        return len(self.nodes)


def from_scm(scm: StructuralCausalModel) -> LinearSystem:
    nodes = list(scm.stress_cols)
    pos = {e: i for i, e in enumerate(nodes)}
    N = len(nodes)
    A, Wf, b = np.zeros((N, N)), np.zeros((N, N)), np.zeros(N)
    for e in nodes:
        c = scm.coef_[e]
        i = pos[e]
        b[i] = float(c["b"])
        for k, p in enumerate(c["parents"]):
            A[i, pos[p]] = float(c["w_stress"][k])
            Wf[i, pos[p]] = float(c["w_flow"][k])
    resid = np.column_stack([scm.resid_[e].to_numpy(dtype=float) for e in nodes])
    return LinearSystem(nodes, A, Wf, b, resid)


def _vec(nodes, x) -> np.ndarray:
    """Dict (entity -> value) or sequence in node order -> float vector in node order."""
    if isinstance(x, dict):
        return np.array([float(x.get(e, 0.0)) for e in nodes])
    return np.asarray(x, dtype=float)


def log_flows(scm: StructuralCausalModel, days) -> np.ndarray:
    """LF[t, e, p] = log1p(flow p -> e on day t) for parents p of e, else 0 (scm._f feature)."""
    nodes = list(scm.stress_cols)
    pos = {e: i for i, e in enumerate(nodes)}
    days = pd.DatetimeIndex(days)
    LF = np.zeros((len(days), len(nodes), len(nodes)))
    for e in nodes:
        for p in scm.coef_[e]["parents"]:
            for t, day in enumerate(days):
                LF[t, pos[e], pos[p]] = np.log1p(scm.flow_on(p, e, day))
    return LF


def drift(sys: LinearSystem, LF: np.ndarray) -> np.ndarray:
    """C[t, e] = b_e + sum_p Wf[e, p] LF[t, e, p]."""
    return sys.b[None, :] + (sys.Wf[None, :, :] * LF).sum(axis=2)


def simulate_batch(sys: LinearSystem, C, init, U, do_idx=None, do_vals=None) -> np.ndarray:
    """Forward simulation of M shock paths. U has shape (M, T, N); returns (M, T, N).

    S_t = S_{t-1} A' + C_t + U_t. Entities in do_idx are forced to do_vals: a scalar, a
    length-T vector (one entity) or a (T, len(do_idx)) array. Their own equation and shock
    are then ignored, as in scm.simulate(do=...)."""
    U = np.asarray(U, dtype=float)
    M, T, N = U.shape
    C = np.asarray(C, dtype=float)
    prev = np.broadcast_to(_vec(sys.nodes, init), (M, N)).copy()
    out = np.empty((M, T, N))
    if do_idx is not None:
        do_idx = np.atleast_1d(np.asarray(do_idx, dtype=int))
        K = len(do_idx)
        v = np.asarray(do_vals, dtype=float)
        if v.ndim == 0:
            v = np.full((T, K), float(v))
        elif v.ndim == 1:
            if K != 1 or len(v) != T:
                raise ValueError("a 1-d do_vals needs one entity and T values")
            v = v.reshape(T, 1)
        elif v.shape != (T, K):
            raise ValueError(f"do_vals must have shape ({T}, {K}), got {v.shape}")
    for t in range(T):
        S = prev @ sys.A.T + C[t][None, :] + U[:, t, :]
        if do_idx is not None:
            S[:, do_idx] = v[t][None, :]
        out[:, t, :] = S
        prev = S
    return out


def shock_rows(n_resid: int, T: int, n_sims: int, block_len: int, seed) -> np.ndarray:
    """(n_sims, T) residual row indices, one moving-block draw per simulation.

    Equal to the row draws of risk.oc_covar(..., n_sims, seed, joint=True, block_len).
    seed may be an int or a numpy Generator."""
    rng = np.random.default_rng(seed)
    return np.stack([risk.moving_block_indices(n_resid, T, block_len, rng)
                     for _ in range(n_sims)])


def exported_risk(sys: LinearSystem, C, init, s_star, rows, q: float = 0.95):
    """Exported risk E_i = sum_{j != i} max(D_ij, 0), with D_ij the Delta-OC-CoVaR of j under
    do(S_i = s*_i) against do(S_i = 0), on the shock paths rows (M, T).

    Returns (E (N,), D (N, N)); D[i, i] = 0."""
    rows = np.asarray(rows)
    U = sys.resid[rows]                      # (M, T, N)
    s = _vec(sys.nodes, s_star)
    T = U.shape[1]
    N = sys.n
    D = np.zeros((N, N))
    for i in range(N):
        hi = simulate_batch(sys, C, init, U, [i], np.full(T, s[i]))
        lo = simulate_batch(sys, C, init, U, [i], np.zeros(T))
        Lhi = np.clip(hi, 0, None).sum(axis=1)     # (M, N)
        Llo = np.clip(lo, 0, None).sum(axis=1)
        D[i] = np.quantile(Lhi, q, axis=0) - np.quantile(Llo, q, axis=0)
    np.fill_diagonal(D, 0.0)
    E = np.clip(D, 0, None).sum(axis=1)
    return E, D


def systemic_ranking_fast(scm: StructuralCausalModel, days, init, s_star, n_sims: int = 2000,
                          seed: int = 0, block_len: int = 24, q: float = 0.95) -> pd.DataFrame:
    """Same columns and order as risk.systemic_ranking (entity, exported_risk, ->j ...)."""
    sys = from_scm(scm)
    days = pd.DatetimeIndex(days)
    C = drift(sys, log_flows(scm, days))
    rows = shock_rows(sys.resid.shape[0], len(days), n_sims, block_len, seed)
    E, D = exported_risk(sys, C, init, s_star, rows, q)
    recs = []
    for i, e in enumerate(sys.nodes):
        rec = {"entity": e, "exported_risk": float(E[i])}
        rec.update({f"->{j}": float(D[i, k]) for k, j in enumerate(sys.nodes) if j != e})
        recs.append(rec)
    return pd.DataFrame(recs).sort_values("exported_risk", ascending=False).reset_index(drop=True)


def abduct(sys: LinearSystem, C, S_obs, S_prev0) -> np.ndarray:
    """Full abduction: U_t = S_obs_t - (A S_{t-1} + C_t) with S_{-1} = S_prev0."""
    S_obs = np.asarray(S_obs, dtype=float)
    S_prev = np.vstack([_vec(sys.nodes, S_prev0)[None, :], S_obs[:-1]])
    return S_obs - (S_prev @ sys.A.T + np.asarray(C, dtype=float))


def attribution_matrix(sys: LinearSystem, C, S_obs, S_prev0, precrisis,
                       abduction: str = "full"):
    """Counterfactual attribution for every ordered pair (i, j).

    abduction="full" (default) recovers the event-window shocks from the observed path
    (abduct); abduction="legacy_zero" uses zero shocks on the event window, as
    risk.counterfactual_attribution(abduction="legacy_zero") does because the fit-window
    residuals are undefined there. S_prev0 is the start state in both modes.

    Returns dict with L_obs, attr, share (each (N, N)). Row i is the intervention on i:
    L_obs[i, j] = loss of j along the replay with i held at its observed path, attr =
    L_obs - L_cf with i held at its pre-crisis level, share = attr / L_obs (0 where
    L_obs <= 1e-9). Diagonals of attr and share are 0."""
    S_obs = np.asarray(S_obs, dtype=float)
    T, N = S_obs.shape
    pre = _vec(sys.nodes, precrisis)
    if abduction == "full":
        U_hat = abduct(sys, C, S_obs, S_prev0)[None]
    elif abduction == "legacy_zero":
        U_hat = np.zeros((1, T, N))
    else:
        raise ValueError(f"unknown abduction mode: {abduction!r}")
    L_obs, L_cf = np.zeros((N, N)), np.zeros((N, N))
    for i in range(N):
        obs = simulate_batch(sys, C, S_prev0, U_hat, [i], S_obs[:, i])
        cf = simulate_batch(sys, C, S_prev0, U_hat, [i], np.full(T, pre[i]))
        L_obs[i] = np.clip(obs[0], 0, None).sum(axis=0)
        L_cf[i] = np.clip(cf[0], 0, None).sum(axis=0)
    attr = L_obs - L_cf
    np.fill_diagonal(attr, 0.0)
    share = np.where(L_obs > 1e-9, attr / np.where(L_obs > 1e-9, L_obs, 1.0), 0.0)
    np.fill_diagonal(share, 0.0)
    return {"L_obs": L_obs, "attr": attr, "share": share}
