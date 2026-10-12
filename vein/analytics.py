"""Analytic results for the linear on-chain SCM (daily specification).

Everything here is linear algebra on the daily coefficient matrix archived in
results/results.json, so the checks can be re-run from the archive without the
Dune data. Only numpy and the standard library are used.

Notation. In the linear SCM the stress vector obeys S_t = A S_{t-1} + c_t + U_t,
where A[j, p] is the lagged stress coefficient of parent p in the equation of j
(zero if p is not a parent of j). Intervening with S_i = s (the do-operator)
moves every entity's path by s * tau_{.i}(t), where tau is the clamped impulse
response computed by clamped_impulse(). Flows, intercepts and shocks cancel
between the two regimes, which is why the resulting bounds are flow-free.

Contents
    load_daily_scm           read the archived daily SCM
    clamped_impulse          tau_{.i}(t) for an intervention on entity i
    oc_bounds                flow-free bounds on the OC-CoVaR change (Prop A)
    infinite_horizon_multiplier
                             steady-state version of the same multiplier
    linear_path, linear_value, hinge_value
                             deviation paths and the coalition games for Shapley
    exact_shapley_subsets    exact Shapley by enumerating all 2^p subsets
    exact_shapley_permutations
                             exact Shapley by enumerating all p! orders (checks)
    walk_shapley_linear      closed-form Shapley for the linear game (Prop C)
    certified_radius         perturbation radius for the top of the ranking
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np

DEFAULT_RESULTS = Path(__file__).resolve().parent.parent / "results" / "results.json"


# ----------------------------------------------------------------- loading
def load_daily_scm(path=DEFAULT_RESULTS) -> dict:
    """Read the daily SCM archived in results/results.json.

    Returns the entity order (file order of scm_coefficients), the parent
    lists, the lagged stress matrix A, the event-window length T, and the
    stored exported risk of each entity from oc_covar_ranking (entities absent
    there are 0.0).
    """
    with open(path) as f:
        res = json.load(f)
    coef = res["scm_coefficients"]
    entities = list(coef.keys())
    ix = {e: k for k, e in enumerate(entities)}
    n = len(entities)
    A = np.zeros((n, n))
    for j, c in coef.items():
        for p, w in zip(c["parents"], c["w_stress"]):
            if p in ix:
                A[ix[j], ix[p]] = float(w)
    stored = {r["entity"]: float(r["exported_risk"]) for r in res["oc_covar_ranking"]}
    return {
        "entities": entities,
        "ix": ix,
        "parents": {j: list(c["parents"]) for j, c in coef.items()},
        "A": A,
        "T": int(res["n_event_days"]),
        "stored_E": {e: stored.get(e, 0.0) for e in entities},
    }


def spectral_radius(A) -> float:
    """Largest modulus of the eigenvalues of A (0.0 for an empty matrix)."""
    A = np.asarray(A, dtype=float)
    if A.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(A))))


# ------------------------------------------------------- impulse response
def clamped_impulse(A, i: int, T: int) -> np.ndarray:
    """Clamped impulse response tau_{.i}(t), t = 0..T-1, as a (T, n) array.

    Starting from a unit deviation at i at t = 0, the deviation propagates
    through A, and entity i is reset to 1 in every period (the do-operator
    holds S_i at its shocked value). Row t, column j is tau_{ji}(t).
    """
    n = A.shape[0]
    D = np.zeros(n)
    D[i] = 1.0
    out = np.zeros((T, n))
    out[0] = D
    for t in range(1, T):
        D = A @ D
        D[i] = 1.0
        out[t] = D
    return out


# ---------------------------------------------------- flow-free bounds (A)
def oc_bounds(A, i: int, T: int, s_star: float = 1.0) -> dict:
    """Flow-free bounds on the OC-CoVaR change of each j caused by i (Prop A).

    For any flows, shock law and quantile level, the change in the loss
    quantile of j under do(S_i = s_star) lies between
        lower_j = sum_t min(s_star tau_{ji}(t), 0)
        upper_j = sum_t max(s_star tau_{ji}(t), 0).
    exported_upper = sum_j upper_j bounds the exported risk of i, since the
    exported risk sums only the positive parts of the per-target changes.
    """
    if s_star < 0:
        raise ValueError("s_star must be non-negative")
    P = s_star * clamped_impulse(A, i, T)
    n = A.shape[0]
    lower, upper = {}, {}
    for j in range(n):
        if j == i:
            continue
        lower[j] = float(np.minimum(P[:, j], 0.0).sum())
        upper[j] = float(np.maximum(P[:, j], 0.0).sum())
    return {"lower": lower, "upper": upper, "exported_upper": float(sum(upper.values()))}


def infinite_horizon_multiplier(A, i: int):
    """Steady-state response of each j to S_i = 1, summed over positive parts.

    With S_i held at 1 forever, the stationary deviations solve
    x = A_{-i,-i} x + A_{-i,i}, so x = (I - A_{-i,-i})^{-1} A_{-i,i}. Returns
    None when rho(A_{-i,-i}) >= 1, since the response then does not converge.
    """
    n = A.shape[0]
    m = [k for k in range(n) if k != i]
    if not m:
        return 0.0
    Amm = A[np.ix_(m, m)]
    if spectral_radius(Amm) >= 1.0:
        return None
    x = np.linalg.solve(np.eye(len(m)) - Amm, A[m, i])
    return float(np.maximum(x, 0.0).sum())


# ------------------------------------------------------- coalition games
def linear_path(A, clamped, d, T: int) -> np.ndarray:
    """Deviation path (T, n) with the entities in `clamped` forced to d.

    Unclamped entities follow the lagged linear equations started from zero
    deviation. A clamped entity k takes the value d[t, k] in every period and
    its own propagated value is discarded.
    """
    n = A.shape[0]
    dev = np.zeros((T, n))
    for t in range(T):
        prev = dev[t - 1] if t > 0 else np.zeros(n)
        cur = A @ prev
        for k in clamped:
            cur[k] = d[t, k]
        dev[t] = cur
    return dev


def linear_value(A, j: int, K, d, T: int) -> float:
    """Linear coalition game v(K) = sum_t delta_{jt}(K)."""
    return float(linear_path(A, tuple(K), d, T)[:, j].sum())


def hinge_value(A, j: int, K, d, T: int, s_fact) -> float:
    """Hinge coalition game L(empty) - L(K) for the positive-part loss.

    L(K) = sum_t max(s_fact[t] - delta_{jt}(K), 0), the loss of j when the
    deviation carried by K is removed from the factual path s_fact. When s_fact
    is positive throughout, the hinge is inactive and the game is linear.
    """
    dev = linear_path(A, tuple(K), d, T)[:, j]
    base = np.maximum(s_fact, 0.0).sum()
    return float(base - np.maximum(s_fact - dev, 0.0).sum())


# ------------------------------------------------------- Shapley solvers
def exact_shapley_subsets(value, players) -> dict:
    """Exact Shapley values by evaluating the game on all 2^p subsets once.

    value: callable taking a frozenset of players. Each marginal contribution
    v(K + k) - v(K) is weighted by |K|! (p - |K| - 1)! / p!. Costs 2^p calls.
    """
    players = list(players)
    p = len(players)
    vals = np.empty(2 ** p)
    for mask in range(2 ** p):
        subset = frozenset(players[b] for b in range(p) if mask >> b & 1)
        vals[mask] = value(subset)
    weight = [math.factorial(s) * math.factorial(p - s - 1) / math.factorial(p)
              for s in range(p)]
    phi = {}
    for b, k in enumerate(players):
        total = 0.0
        for mask in range(2 ** p):
            if mask >> b & 1:
                continue
            s = bin(mask).count("1")
            total += weight[s] * (vals[mask | (1 << b)] - vals[mask])
        phi[k] = float(total)
    return phi


def exact_shapley_permutations(value, players) -> dict:
    """Exact Shapley values by averaging marginals over all p! orders.

    Intended as an independent check of exact_shapley_subsets for small p.
    """
    players = list(players)
    phi = {k: 0.0 for k in players}
    orders = list(itertools.permutations(players))
    for order in orders:
        seen = frozenset()
        prev = value(seen)
        for k in order:
            seen = seen | {k}
            cur = value(seen)
            phi[k] += cur - prev
            prev = cur
    return {k: float(v / len(orders)) for k, v in phi.items()}


def walk_shapley_linear(A, j: int, players, d, T: int) -> dict:
    """Closed-form Shapley values for the linear game via time-unrolled walks.

    Each walk from (k, t0) to (j, t) carries weight omega = d[t0, k] times the
    product of the coefficients along it. Walks that revisit k are excluded,
    since k is overwritten by its clamped value. Let m be the number of
    distinct players among the intermediate nodes. The walk credits omega /
    (1 + m) to its source k and -omega / (m (m + 1)) to each intermediate
    player, so its total credit is zero when m >= 1 and the values sum to the
    walks that reach j without any intermediate player, i.e. to v(players).

    The walks are propagated by dynamic programming over the set of players
    already visited, with one vector of node weights per visited set. That set
    is exactly the set of intermediate players of the walks it carries.
    """
    players = list(players)
    if j in players:
        raise ValueError("the target j cannot be a player")
    n = A.shape[0]
    bit = {p: b for b, p in enumerate(players)}
    phi = {k: 0.0 for k in players}
    for k in players:
        cur = {0: np.zeros(n)}
        for t in range(T):
            cur.setdefault(0, np.zeros(n))[k] += d[t, k]
            if t == T - 1:
                break
            nxt = {}
            for mask, vec in cur.items():
                new = A @ vec
                new[k] = 0.0
                m = bin(mask).count("1")
                if m == 0:
                    phi[k] += new[j]
                else:
                    phi[k] += new[j] / (1 + m)
                    for b, p in enumerate(players):
                        if mask >> b & 1:
                            phi[p] -= new[j] / (m * (m + 1))
                for w in np.flatnonzero(new):
                    m2 = mask | (1 << bit[w]) if w in bit else mask
                    nxt.setdefault(m2, np.zeros(n))[w] += new[w]
            cur = nxt
    return phi


# ------------------------------------------------- certified ranking radius
def ranking_mass(A, i: int, T: int) -> float:
    """Lambda_i = sum_{j != i} sum_t max(tau_{ji}(t), 0), the daily exported mass."""
    tau = clamped_impulse(A, i, T)
    mask = np.arange(A.shape[0]) != i
    return float(np.maximum(tau[:, mask], 0.0).sum())


def ranking_radius(A, i: int, T: int, eps: float) -> float:
    """R_i(eps) bounding |Lambda_i(A~) - Lambda_i(A)| for |A~ - A| <= eps |A|."""
    absA = np.abs(A)
    base = clamped_impulse(absA, i, T)
    wide = clamped_impulse((1.0 + eps) * absA, i, T)
    mask = np.arange(A.shape[0]) != i
    return float((wide - base)[:, mask].sum())


def certified_radius(A, T: int, top_k: int = 5, iters: int = 60) -> dict:
    """Largest relative coefficient error at which adjacent ranks are preserved.

    Entities are ranked by Lambda_i. For each consecutive pair (r, r+1) among
    the top_k, the order is certified at eps when
        Lambda_r - Lambda_{r+1} > R_r(eps) + R_{r+1}(eps).
    R is increasing in eps, so the certified set is an interval [0, eps*), which
    is found by bisection on [0, 1]. at_least_one flags pairs still certified
    at eps = 1, where eps* is reported as 1.0.
    """
    n = A.shape[0]
    Lam = {i: ranking_mass(A, i, T) for i in range(n)}
    order = sorted([i for i in range(n) if Lam[i] > 0], key=lambda i: -Lam[i])
    pairs = []
    for r in range(min(top_k, len(order)) - 1):
        a, b = order[r], order[r + 1]
        gap = Lam[a] - Lam[b]

        def certified(eps):
            return gap > ranking_radius(A, a, T, eps) + ranking_radius(A, b, T, eps)

        if gap <= 0:
            eps_star, at_least_one = 0.0, False
        elif certified(1.0):
            eps_star, at_least_one = 1.0, True
        else:
            lo, hi = 0.0, 1.0
            for _ in range(iters):
                mid = 0.5 * (lo + hi)
                if certified(mid):
                    lo = mid
                else:
                    hi = mid
            eps_star, at_least_one = lo, False
        pairs.append({"pair": [a, b], "gap": float(gap), "eps_star": float(eps_star),
                      "at_least_one": at_least_one})
    return {"Lambda": {i: float(v) for i, v in Lam.items()},
            "ranking": order[:top_k], "pairs": pairs}
