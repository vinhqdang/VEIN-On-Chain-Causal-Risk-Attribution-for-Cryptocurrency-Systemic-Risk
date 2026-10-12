"""Tests for vein/analytics.py: impulse responses, Prop A bounds, Shapley solvers."""
import numpy as np
import pytest

from vein import analytics as an


def _random_A(rng, n, rho):
    """Random coefficient matrix rescaled to spectral radius rho."""
    A = rng.normal(size=(n, n))
    A *= rho / an.spectral_radius(A)
    return A


def _simulate(A, c, U, init, i=None, s=None):
    """Forward simulation S_t = A S_{t-1} + c_t + U_t, with S_i = s if intervened."""
    T, n = c.shape
    S = np.zeros((T, n))
    prev = init.copy()
    for t in range(T):
        cur = A @ prev + c[t] + U[t]
        if i is not None:
            cur[i] = s
        S[t] = cur
        prev = cur
    return S


# 1. Clamped impulse response on a chain 0 -> 1 -> 2
def test_clamped_impulse_chain():
    A = np.zeros((3, 3))
    A[1, 0] = 0.5
    A[2, 1] = 0.4
    tau = an.clamped_impulse(A, 0, 4)
    assert np.allclose(tau[:, 2], [0.0, 0.0, 0.2, 0.2])
    assert np.allclose(tau[:, 1], [0.0, 0.5, 0.5, 0.5])
    assert np.allclose(tau[:, 0], [1.0, 1.0, 1.0, 1.0])


# 2. Prop A: flow-free bounds hold for the hinge-loss OC-CoVaR, and the
#    per-period quantile shift equals s* tau exactly
def test_prop_a_bounds_and_exact_shift():
    rng = np.random.default_rng(7)
    n, T, i, j = 5, 4, 0, 3
    A = _random_A(rng, n, 0.6)
    c = rng.normal(size=(T, n))
    init = rng.normal(size=n)
    U = rng.normal(size=(200, T, n))
    s_star = 1.7
    tau = an.clamped_impulse(A, i, T)
    lower = np.minimum(s_star * tau[:, j], 0).sum()
    upper = np.maximum(s_star * tau[:, j], 0).sum()

    L_hi = np.empty(200)
    L_lo = np.empty(200)
    S_hi = np.empty((200, T, n))
    S_lo = np.empty((200, T, n))
    for k in range(200):
        S_hi[k] = _simulate(A, c, U[k], init, i, s_star)
        S_lo[k] = _simulate(A, c, U[k], init, i, 0.0)
        L_hi[k] = np.maximum(S_hi[k, :, j], 0).sum()
        L_lo[k] = np.maximum(S_lo[k, :, j], 0).sum()

    shift = np.quantile(L_hi, 0.95) - np.quantile(L_lo, 0.95)
    assert lower - 1e-12 <= shift <= upper + 1e-12

    for t in range(T):
        for jj in range(n):
            if jj == i:
                continue
            q_hi = np.quantile(S_hi[:, t, jj], 0.95)
            q_lo = np.quantile(S_lo[:, t, jj], 0.95)
            assert abs((q_hi - q_lo) - s_star * tau[t, jj]) < 1e-10

    bounds = an.oc_bounds(A, i, T, s_star)
    assert abs(bounds["lower"][j] - lower) < 1e-12
    assert abs(bounds["upper"][j] - upper) < 1e-12


# 3. Walk-based closed form equals brute-force subset Shapley (cyclic A)
def test_walk_shapley_matches_subsets():
    rng = np.random.default_rng(7)
    n, T, j = 6, 5, 0
    A = _random_A(rng, n, 0.7)
    players = [2, 3, 4]
    d = rng.normal(size=(T, n))
    walk = an.walk_shapley_linear(A, j, players, d, T)
    subs = an.exact_shapley_subsets(lambda K: an.linear_value(A, j, K, d, T), players)
    for k in players:
        assert abs(walk[k] - subs[k]) < 1e-10


# 4. Subset enumeration equals permutation enumeration
def test_subsets_match_permutations():
    rng = np.random.default_rng(7)
    n, T, j = 6, 5, 0
    A = _random_A(rng, n, 0.7)
    players = [1, 3, 4, 5]
    d = rng.normal(size=(T, n))
    subs = an.exact_shapley_subsets(lambda K: an.linear_value(A, j, K, d, T), players)
    perms = an.exact_shapley_permutations(lambda K: an.linear_value(A, j, K, d, T), players)
    for k in players:
        assert abs(subs[k] - perms[k]) < 1e-10


# 5. Efficiency: attributions sum to the grand-coalition value
def test_efficiency():
    rng = np.random.default_rng(7)
    n, T, j = 6, 5, 0
    A = _random_A(rng, n, 0.7)
    players = [1, 2, 4]
    d = rng.normal(size=(T, n))
    walk = an.walk_shapley_linear(A, j, players, d, T)
    total = an.linear_value(A, j, frozenset(players), d, T)
    assert abs(sum(walk.values()) - total) < 1e-10


# 6. With the hinge inactive (factual path strictly positive), the hinge game
#    coincides with the linear game, so the Shapley values coincide
def test_hinge_reduces_to_linear_when_inactive():
    rng = np.random.default_rng(7)
    n, T, j = 6, 5, 0
    A = _random_A(rng, n, 0.7)
    players = [1, 2, 3]
    d = rng.normal(size=(T, n))
    s_fact = 10.0 + rng.normal(size=T)
    lin = an.exact_shapley_subsets(lambda K: an.linear_value(A, j, K, d, T), players)
    hin = an.exact_shapley_subsets(lambda K: an.hinge_value(A, j, K, d, T, s_fact), players)
    for k in players:
        assert abs(lin[k] - hin[k]) < 1e-10


# 7. Certified radius: eps* in [0, 1], and R_i(eps) is non-decreasing in eps
def test_certified_radius_bounds_and_monotone():
    rng = np.random.default_rng(7)
    n, T = 6, 4
    A = _random_A(rng, n, 0.5)
    out = an.certified_radius(A, T, top_k=5)
    for pair in out["pairs"]:
        assert 0.0 <= pair["eps_star"] <= 1.0
    for i in range(n):
        vals = [an.ranking_radius(A, i, T, e) for e in np.linspace(0.0, 1.0, 6)]
        assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))
        assert vals[0] == pytest.approx(0.0, abs=1e-12)


def test_load_daily_scm_shapes():
    S = an.load_daily_scm()
    n = len(S["entities"])
    assert S["A"].shape == (n, n)
    assert S["T"] == 7
    assert set(S["stored_E"]) == set(S["entities"])
