"""Offline tests for vein/uncertainty.py: refit, bootstrap summaries and determinism."""
import numpy as np
import pandas as pd

from vein import fastscm as fs
from vein import risk, uncertainty as un
from vein.scm import StructuralCausalModel


def _data(n=160, seed=3):
    """Synthetic stress panel with a known graph X -> Y -> Z, Z <- X, and daily-style flows."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-09-01", periods=n, freq="h")
    graph = {"nodes": ["X", "Y", "Z", "W"],
             "parents": {"X": [], "Y": ["X"], "Z": ["X", "Y"], "W": []}}
    X = np.zeros(n); Y = np.zeros(n); Z = np.zeros(n); W = rng.normal(size=n)
    fl = {("X", "Y"): rng.uniform(1e4, 1e6, n), ("X", "Z"): rng.uniform(1e4, 1e6, n),
          ("Y", "Z"): rng.uniform(1e4, 1e6, n)}
    for t in range(1, n):
        X[t] = 0.5 * X[t - 1] + rng.normal(scale=0.3)
        Y[t] = 0.6 * X[t - 1] + 0.05 * np.log1p(fl[("X", "Y")][t]) * 0.1 + rng.normal(scale=0.2)
        Z[t] = 0.2 * X[t - 1] - 0.4 * Y[t - 1] + 0.1 * np.log1p(fl[("Y", "Z")][t]) * 0.1 + rng.normal(scale=0.25)
    stress = pd.DataFrame({"X": X, "Y": Y, "Z": Z, "W": W}, index=idx)
    rows = []
    for k, (a, b) in enumerate(fl):
        for t, day in enumerate(idx):
            rows.append({"from_entity": a, "to_entity": b, "day": day, "usd_volume": float(fl[(a, b)][t])})
    flows = pd.DataFrame(rows)
    return graph, stress, flows


def _fit():
    graph, stress, flows = _data()
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress, flows).set_flows(flows)
    return graph, stress, flows, scm


def test_refit_all_rows_reproduces_scm_fit_coefficients():
    _, stress, flows, scm = _fit()
    designs = un.design(scm, stress, flows)
    base = fs.from_scm(scm)
    sys_all = un.refit(base, designs, np.arange(len(stress) - 1))
    for i, e in enumerate(base.nodes):
        c = scm.coef_[e]
        for k, p in enumerate(c["parents"]):
            j = base.nodes.index(p)
            assert abs(sys_all.A[i, j] - c["w_stress"][k]) < 1e-8
            assert abs(sys_all.Wf[i, j] - c["w_flow"][k]) < 1e-8
        assert abs(sys_all.b[i] - c["b"]) < 1e-8
    assert np.max(np.abs(sys_all.resid - np.column_stack(
        [scm.resid_[e].values for e in base.nodes]))) < 1e-8


def test_small_run_ranking_intervals_are_valid():
    _, stress, flows, scm = _fit()
    est = stress.index
    ev = list(stress.index[-24:])
    sys = fs.from_scm(scm)
    init = stress.iloc[-25].to_dict()
    s_star = risk.fit_window_s_star(stress, est, 0.95)
    s_vec = [s_star[e] for e in sys.nodes]
    E = un.ranking_draws(scm, stress, flows, ev, s_vec, init, n_boot=20, n_sims=50, block_len=8,
                         seed=7)
    assert E.shape == (20, len(sys.nodes)) and np.all(np.isfinite(E))
    point = fs.systemic_ranking_fast(scm, ev, init, s_star, n_sims=200, seed=7, block_len=8)
    point_E = point.set_index("entity").loc[sys.nodes, "exported_risk"].values
    summ = un.summarize_ranking(E, sys.nodes, point_E, transmitters=("X",), absorbers=("Z",))
    N = len(sys.nodes)
    for e, rec in summ["by_entity"].items():
        lo, hi = rec["rank_ci95"]
        assert 1 <= lo <= hi <= N
        assert 0 <= rec["p_top1"] <= rec["p_top3"] <= rec["p_top5"] <= 1
    P = summ["pairwise_top6"]["p_row_above_col"]
    for a in range(len(P)):
        for b in range(len(P)):
            if a != b:
                assert P[a][b] + P[b][a] <= 1 + 1e-12
            else:
                assert P[a][b] is None


def test_draws_are_deterministic_for_same_seed():
    _, stress, flows, scm = _fit()
    ev = list(stress.index[-24:])
    sys = fs.from_scm(scm)
    init = stress.iloc[-25].to_dict()
    s_vec = [1.0] * len(sys.nodes)
    a = un.ranking_draws(scm, stress, flows, ev, s_vec, init, n_boot=5, n_sims=20, block_len=8, seed=11)
    b = un.ranking_draws(scm, stress, flows, ev, s_vec, init, n_boot=5, n_sims=20, block_len=8, seed=11)
    assert np.array_equal(a, b)


def test_mc_error_is_finite_and_scaled():
    _, stress, flows, scm = _fit()
    ev = list(stress.index[-24:])
    sys = fs.from_scm(scm)
    init = stress.iloc[-25].to_dict()
    C = fs.drift(sys, fs.log_flows(scm, ev))
    out = un.mc_error(sys, C, [init[e] for e in sys.nodes], [1.0] * len(sys.nodes),
                      n_rep=4, n_sims=30, block_len=8, seed0=5)
    assert np.all(np.isfinite(out["se_point"])) and np.all(out["sd"] >= 0)
    assert np.allclose(out["se_point"], out["sd"] * np.sqrt(30 / 2000))


def test_shapley_split_is_additive_on_fast_engine():
    _, stress, flows, scm = _fit()
    ev = list(stress.index[-24:])
    sys = fs.from_scm(scm)
    S_obs = stress.loc[ev, sys.nodes].values
    S_prev0 = stress.iloc[-25][sys.nodes].values
    C = fs.drift(sys, fs.log_flows(scm, ev))
    pre = stress.iloc[:-24].median()[sys.nodes].values
    res = un.shapley_split(sys, C, S_obs, S_prev0, pre, target="Z", cands=["X", "Y"])
    assert abs(res["additive_residual"]) < 1e-9
