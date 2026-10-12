"""The vectorized engine (vein/fastscm.py) must reproduce vein/scm.py and vein/risk.py."""
import numpy as np
import pandas as pd
import pytest

from vein import fastscm as fs
from vein import risk
from test_scm_abduction import _synthetic_scm


def _with_resid(scm, n=12, seed=5):
    rng = np.random.default_rng(seed)
    for e in scm.stress_cols:
        scm.resid_[e] = pd.Series(rng.normal(scale=0.5, size=n),
                                  index=pd.date_range("2025-09-01", periods=n, freq="D"))
    return scm


def _setup():
    scm, days, init, rng = _synthetic_scm()
    scm = _with_resid(scm)
    sys = fs.from_scm(scm)
    C = fs.drift(sys, fs.log_flows(scm, days))
    return scm, days, init, rng, sys, C


def test_simulate_batch_matches_scm_simulate_without_and_with_do():
    scm, days, init, rng, sys, C = _setup()
    U = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    Ub = np.stack([np.column_stack([U[e] for e in sys.nodes])])   # (1, T, N)
    init_vec = [init[e] for e in sys.nodes]
    ref = scm.simulate(days, init, U)
    got = fs.simulate_batch(sys, C, init_vec, Ub)[0]
    assert np.max(np.abs(got - ref[sys.nodes].values)) < 1e-12

    x_path = rng.normal(size=len(days))
    ref_do = scm.simulate(days, init, U, do={"X": x_path})
    got_do = fs.simulate_batch(sys, C, init_vec, Ub,
                               do_idx=[sys.nodes.index("X")], do_vals=x_path)[0]
    assert np.max(np.abs(got_do - ref_do[sys.nodes].values)) < 1e-12


def test_exported_risk_matches_systemic_ranking():
    scm, days, init, rng, sys, C = _setup()
    s_star = {"X": 1.0, "Y": 0.5, "Z": -0.2}
    rows = fs.shock_rows(sys.resid.shape[0], len(days), 50, 2, seed=3)
    E, D = fs.exported_risk(sys, C, init, [s_star[e] for e in sys.nodes], rows)
    ref = risk.systemic_ranking(scm, days, init, s_star, q=0.95, n_sims=50, seed=3,
                                joint=True, block_len=2)
    for i, e in enumerate(sys.nodes):
        row = ref.set_index("entity").loc[e]
        assert abs(E[i] - row["exported_risk"]) < 1e-9
        for k, j in enumerate(sys.nodes):
            if j != e:
                assert abs(D[i, k] - row[f"->{j}"]) < 1e-9


def test_systemic_ranking_fast_frame_matches_reference():
    scm, days, init, rng, sys, C = _setup()
    s_star = {"X": 1.0, "Y": 0.5, "Z": -0.2}
    ref = risk.systemic_ranking(scm, days, init, s_star, n_sims=40, seed=3, joint=True, block_len=2)
    got = fs.systemic_ranking_fast(scm, days, init, s_star, n_sims=40, seed=3, block_len=2)
    assert list(got.columns) == list(ref.columns)
    assert list(got.entity) == list(ref.entity)
    # the self-column (entity -> itself) is empty in both frames
    np.testing.assert_allclose(got[ref.columns[1:]].values, ref[ref.columns[1:]].values,
                               atol=1e-9, rtol=0, equal_nan=True)


def test_shock_rows_equal_sequential_moving_block_indices():
    n_resid, T, n_sims, L, seed = 9, 6, 5, 4, 11
    rows = fs.shock_rows(n_resid, T, n_sims, L, seed)
    rng = np.random.default_rng(seed)
    seq = np.stack([risk.moving_block_indices(n_resid, T, L, rng) for _ in range(n_sims)])
    assert rows.shape == (n_sims, T)
    assert np.array_equal(rows, seq)


def test_attribution_matrix_matches_counterfactual_attribution():
    scm, days, init, rng, sys, C = _setup()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    precrisis = {"X": 0.1, "Y": -0.4, "Z": 0.3}
    S_obs = observed[sys.nodes].values
    S_prev0 = np.array([init[e] for e in sys.nodes])
    mat = fs.attribution_matrix(sys, C, S_obs, S_prev0, [precrisis[e] for e in sys.nodes])
    for i, a in enumerate(sys.nodes):
        for j, b in enumerate(sys.nodes):
            if a == b:
                continue
            ref = risk.counterfactual_attribution(scm, a, b, days, observed, init, precrisis[a])
            assert abs(mat["attr"][i, j] - ref["attribution"]) < 1e-9
            assert abs(mat["share"][i, j] - ref["attribution_share"]) < 1e-9
            assert abs(mat["L_obs"][i, j] - ref["L_observed"]) < 1e-9


def test_attribution_matrix_legacy_zero_matches_counterfactual_attribution():
    scm, days, init, rng, sys, C = _setup()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    precrisis = {"X": 0.1, "Y": -0.4, "Z": 0.3}
    S_obs = observed[sys.nodes].values
    init_vec = [init[e] for e in sys.nodes]
    mat = fs.attribution_matrix(sys, C, S_obs, init_vec, [precrisis[e] for e in sys.nodes],
                                abduction="legacy_zero")
    for i, a in enumerate(sys.nodes):
        for j, b in enumerate(sys.nodes):
            if a == b:
                continue
            ref = risk.counterfactual_attribution(scm, a, b, days, observed, init, precrisis[a],
                                                  abduction="legacy_zero")
            assert abs(mat["attr"][i, j] - ref["attribution"]) < 1e-9
            assert abs(mat["share"][i, j] - ref["attribution_share"]) < 1e-9
            assert abs(mat["L_obs"][i, j] - ref["L_observed"]) < 1e-9


def test_attribution_matrix_rejects_unknown_abduction():
    scm, days, init, rng, sys, C = _setup()
    S_obs = np.zeros((len(days), sys.n))
    with pytest.raises(ValueError):
        fs.attribution_matrix(sys, C, S_obs, np.zeros(sys.n), np.zeros(sys.n), abduction="nope")


def test_simulate_batch_rejects_bad_do_shape():
    scm, days, init, rng, sys, C = _setup()
    U = np.zeros((1, len(days), 3))
    with pytest.raises(ValueError):
        fs.simulate_batch(sys, C, [0.0, 0.0, 0.0], U, do_idx=[0, 1], do_vals=np.zeros(len(days)))
