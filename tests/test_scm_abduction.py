"""Tests for full abduction (SCM.event_residuals) and the joint bootstrap."""
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


def test_unknown_abduction_mode_rejected():
    scm, days, init, rng = _synthetic_scm()
    observed = scm.simulate(days, init, {e: np.zeros(len(days)) for e in scm.stress_cols})
    with pytest.raises(ValueError):
        risk.counterfactual_attribution(scm, "X", "Z", days, observed, init, 0.0,
                                        abduction="nope")


def test_joint_bootstrap_shares_row_indices():
    scm, days, init, rng = _synthetic_scm()
    n = 5
    for e in scm.stress_cols:
        scm.resid_[e] = pd.Series(np.arange(10, dtype=float) + 100 * scm.stress_cols.index(e),
                                  index=pd.date_range("2025-09-01", periods=10, freq="D"))
    U = risk._bootstrap_U(scm, n, np.random.default_rng(3), joint=True)
    # Same row drawn for every entity: the offset between columns is constant
    assert np.allclose(U["Y"] - U["X"], 100.0)
    assert np.allclose(U["Z"] - U["X"], 200.0)


def test_legacy_bootstrap_default_is_independent():
    scm, days, init, rng = _synthetic_scm()
    for e in scm.stress_cols:
        scm.resid_[e] = pd.Series(np.arange(10, dtype=float),
                                  index=pd.date_range("2025-09-01", periods=10, freq="D"))
    a = risk._bootstrap_U(scm, 6, np.random.default_rng(3))
    b = risk._bootstrap_U(scm, 6, np.random.default_rng(3), joint=False)
    for e in scm.stress_cols:
        assert np.array_equal(a[e], b[e])
