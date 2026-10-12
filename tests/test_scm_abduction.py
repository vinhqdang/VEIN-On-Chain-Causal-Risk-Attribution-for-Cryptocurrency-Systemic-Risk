"""Tests for full abduction (SCM.event_residuals), the joint and block bootstrap,
and the pre-event s* helper."""
import numpy as np
import pandas as pd
import pytest

from vein import risk
from vein.scm import StructuralCausalModel


def _synthetic_scm():
    """Three-entity linear SCM with hand-set coefficients and daily flows."""
    graph = {"nodes": ["X", "Y", "Z"],
             "parents": {"X": [], "Y": ["X"], "Z": ["X", "Y"]}}
    scm = StructuralCausalModel(graph)
    scm.stress_cols = ["X", "Y", "Z"]
    scm.coef_ = {
        "X": {"parents": [], "w_stress": np.array([]), "w_flow": np.array([]),
              "b": 0.3, "names": []},
        "Y": {"parents": ["X"], "w_stress": np.array([0.6]), "w_flow": np.array([0.05]),
              "b": -0.1, "names": []},
        "Z": {"parents": ["X", "Y"], "w_stress": np.array([0.2, -0.4]),
              "w_flow": np.array([0.0, 0.1]), "b": 0.05, "names": []},
    }
    scm.resid_ = {}
    days = pd.date_range("2025-10-01", periods=7, freq="D")
    rng = np.random.default_rng(7)
    rows = []
    for d in days:
        rows.append({"from_entity": "X", "to_entity": "Y", "day": d,
                     "usd_volume": float(rng.uniform(1e5, 1e6))})
        rows.append({"from_entity": "X", "to_entity": "Z", "day": d,
                     "usd_volume": float(rng.uniform(1e5, 1e6))})
        rows.append({"from_entity": "Y", "to_entity": "Z", "day": d,
                     "usd_volume": float(rng.uniform(1e5, 1e6))})
    flows = pd.DataFrame(rows)
    scm.set_flows(flows)
    init = {"X": 0.2, "Y": -0.3, "Z": 0.1}
    return scm, days, init, rng


def _resid_ramp(scm, n=10, start="2025-09-01"):
    """Residuals 0..n-1 on every entity, offset by 100 per entity (joint tests)."""
    for e in scm.stress_cols:
        scm.resid_[e] = pd.Series(np.arange(n, dtype=float) + 100 * scm.stress_cols.index(e),
                                  index=pd.date_range(start, periods=n, freq="D"))


def test_event_residuals_recover_known_shocks():
    scm, days, init, rng = _synthetic_scm()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    stress = scm.simulate(days, init, U_true)
    U_hat = scm.event_residuals(stress, days, init)
    for e in scm.stress_cols:
        assert np.max(np.abs(U_hat[e] - U_true[e])) < 1e-9


def test_full_abduction_replay_reproduces_observed_path():
    scm, days, init, rng = _synthetic_scm()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    U_hat = scm.event_residuals(observed, days, init)
    # Intervene on X with its observed path; every other entity must replay exactly
    replay = scm.simulate(days, init, U_hat, do={"X": observed["X"].values})
    for e in ["Y", "Z"]:
        assert np.max(np.abs(replay[e].values - observed[e].values)) < 1e-9


def test_counterfactual_full_uses_event_residuals():
    scm, days, init, rng = _synthetic_scm()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    out = risk.counterfactual_attribution(scm, "X", "Z", days, observed, init,
                                          precrisis_value=0.0, abduction="full")
    replay = scm.simulate(days, init, scm.event_residuals(observed, days, init),
                          do={"X": observed["X"].values})
    assert abs(out["L_observed"] - risk.loss_functional(replay["Z"].values)) < 1e-9


def test_full_abduction_is_default_and_reproduces_observed_loss():
    scm, days, init, rng = _synthetic_scm()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    default = risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0)
    full = risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0,
                                           abduction="full")
    assert default == full
    # the replay under full abduction returns the observed loss of the child
    assert abs(default["L_observed"] - risk.loss_functional(observed["Z"].values)) < 1e-9


def test_full_abduction_starts_from_observed_pre_window_row():
    scm, days, init, rng = _synthetic_scm()
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    full_path = scm.simulate(days, init, U_true)
    # the window is days[1:]; the observed row on days[0] is the pre-window state
    window = days[1:]
    wrong_init = {"X": 5.0, "Y": 5.0, "Z": 5.0}
    out = risk.counterfactual_attribution(scm, "X", "Z", window, full_path,
                                          wrong_init, 0.0)
    assert abs(out["L_observed"] - risk.loss_functional(full_path["Z"].values[1:])) < 1e-9


def test_legacy_zero_abduction_still_available():
    scm, days, init, rng = _synthetic_scm()
    scm.resid_ = {e: pd.Series(0.0, index=days) for e in scm.stress_cols}
    U_true = {e: rng.normal(size=len(days)) for e in scm.stress_cols}
    observed = scm.simulate(days, init, U_true)
    legacy = risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0,
                                             abduction="legacy_zero")
    assert set(legacy) >= {"L_observed", "L_counterfactual", "attribution"}


def test_unknown_abduction_mode_rejected():
    scm, days, init, rng = _synthetic_scm()
    observed = scm.simulate(days, init, {e: np.zeros(len(days)) for e in scm.stress_cols})
    with pytest.raises(ValueError):
        risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0,
                                        abduction="nope")


def test_full_abduction_needs_stress_on_every_event_day():
    scm, days, init, rng = _synthetic_scm()
    observed = scm.simulate(days, init, {e: np.zeros(len(days)) for e in scm.stress_cols})
    with pytest.raises(ValueError, match="missing"):
        risk.counterfactual_attribution(scm, "X", "Z", days, observed.iloc[:-1], init, 0.0)


def test_full_abduction_needs_flows_covering_window():
    scm, days, init, rng = _synthetic_scm()
    observed = scm.simulate(days, init, {e: np.zeros(len(days)) for e in scm.stress_cols})
    early = pd.DataFrame([{"from_entity": "X", "to_entity": "Y", "day": days[0],
                           "usd_volume": 1.0}])
    scm.set_flows(early)
    with pytest.raises(ValueError, match="flows"):
        risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0)


def test_joint_bootstrap_shares_row_indices():
    scm, days, init, rng = _synthetic_scm()
    n = 5
    _resid_ramp(scm, n=10)
    U = risk._bootstrap_U(scm, n, np.random.default_rng(3), joint=True)
    # Same row drawn for every entity: the offset between columns is constant
    assert np.allclose(U["Y"] - U["X"], 100.0)
    assert np.allclose(U["Z"] - U["X"], 200.0)


def test_default_bootstrap_is_joint():
    scm, days, init, rng = _synthetic_scm()
    _resid_ramp(scm, n=10)
    default = risk._bootstrap_U(scm, 6, np.random.default_rng(3))
    joint = risk._bootstrap_U(scm, 6, np.random.default_rng(3), joint=True)
    for e in scm.stress_cols:
        assert np.array_equal(default[e], joint[e])
    assert np.allclose(default["Y"] - default["X"], 100.0)


def test_independent_bootstrap_is_explicit_and_iid_only():
    scm, days, init, rng = _synthetic_scm()
    _resid_ramp(scm, n=10)
    U = risk._bootstrap_U(scm, 6, np.random.default_rng(3), joint=False)
    assert all(len(U[e]) == 6 for e in scm.stress_cols)
    with pytest.raises(ValueError):
        risk._bootstrap_U(scm, 6, np.random.default_rng(3), joint=False, block_len=4)


def test_block_bootstrap_keeps_contiguous_runs():
    scm, days, init, rng = _synthetic_scm()
    _resid_ramp(scm, n=20)
    U = risk._bootstrap_U(scm, 12, np.random.default_rng(5), joint=True, block_len=4)
    for e in scm.stress_cols:
        blocks = U[e].reshape(3, 4)
        assert np.all(np.diff(blocks, axis=1) % 20 == 1.0)     # order kept inside blocks (circular wrap)
    assert np.allclose(U["Y"] - U["X"], 100.0)                 # rows still shared


def test_block_bootstrap_truncates_last_block():
    scm, days, init, rng = _synthetic_scm()
    _resid_ramp(scm, n=20)
    U = risk._bootstrap_U(scm, 10, np.random.default_rng(9), joint=True, block_len=4)
    assert len(U["X"]) == 10
    assert np.all(np.diff(U["X"][:8].reshape(2, 4), axis=1) % 20 == 1.0)


def test_moving_block_indices_bounds_and_capping():
    rng = np.random.default_rng(1)
    idx = risk.moving_block_indices(30, 30, 8, rng)
    assert len(idx) == 30 and idx.min() >= 0 and idx.max() < 30
    assert np.all(np.diff(idx[:24].reshape(3, 8), axis=1) % 30 == 1)
    plain = risk.moving_block_indices(30, 30, 8, rng, circular=False)
    assert plain.max() < 30 and np.all(np.diff(plain[:24].reshape(3, 8), axis=1) == 1)
    # a block longer than the sample is capped at the sample length
    capped = risk.moving_block_indices(5, 12, 99, rng)
    assert len(capped) == 12 and capped.max() < 5
    with pytest.raises(ValueError):
        risk.moving_block_indices(5, 5, 0, rng)


def test_s_star_uses_fit_window_only():
    idx = pd.date_range("2025-10-01", periods=10, freq="D")
    fit = idx[:6]
    stress = pd.DataFrame({"A": np.arange(10, dtype=float), "B": np.linspace(-1, 1, 10)},
                          index=idx)
    s = risk.fit_window_s_star(stress, fit, q=0.95)
    assert abs(s["A"] - np.quantile(np.arange(6.0), 0.95)) < 1e-12
    assert abs(s["B"] - np.quantile(np.linspace(-1, 1, 10)[:6], 0.95)) < 1e-12
    # the full-window quantile would have been pulled up by the event rows
    assert s["A"] < np.quantile(stress["A"].values, 0.95)


def test_s_star_ignores_event_rows_entirely():
    idx = pd.date_range("2025-10-01", periods=10, freq="D")
    fit = idx[:6]
    base = pd.DataFrame({"A": np.arange(10, dtype=float)}, index=idx)
    spiked = base.copy()
    spiked.iloc[6:, 0] = 1e6                                  # event window blown up
    assert risk.fit_window_s_star(base, fit) == risk.fit_window_s_star(spiked, fit)


def test_s_star_rejects_empty_fit_window():
    idx = pd.date_range("2025-10-01", periods=3, freq="D")
    stress = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    with pytest.raises(ValueError):
        risk.fit_window_s_star(stress, pd.date_range("2024-01-01", periods=2, freq="D"))


def test_paired_time_block_means_blocks_whole_time_steps():
    # 3 entities x 40 hours; the value encodes the hour, so a replicate mean is
    # the mean of the drawn hours when whole time steps are resampled.
    T, E = 40, 3
    tpos = np.repeat(np.arange(T), E)
    d = tpos.astype(float)
    m = risk.paired_time_block_means(d, tpos, 50, 8, np.random.default_rng(2))
    assert m.shape == (50,) and m.min() >= 0 and m.max() <= T - 1
    # entity-major input order must not matter
    perm = np.random.default_rng(0).permutation(len(d))
    m2 = risk.paired_time_block_means(d[perm], tpos[perm], 50, 8, np.random.default_rng(2))
    assert np.allclose(m, m2)
    idx = risk.moving_block_indices(T, T, 8, np.random.default_rng(2))
    assert np.isclose(m[0], idx.mean())
