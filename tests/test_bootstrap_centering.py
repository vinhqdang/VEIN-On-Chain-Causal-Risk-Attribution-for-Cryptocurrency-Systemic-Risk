"""Centring of the block bootstraps, R^2 reporting, all-source attribution, out-of-sample R^2."""
import json

import numpy as np
import pandas as pd

from vein import fastscm as fs, oos, risk, uncertainty as un, validation as val
from vein.scm import StructuralCausalModel

import run_best as rb
import run_intraday_a3 as a3
import run_build_data as rbd


def _ar_series(T, phi, seed, mean=0.0):
    rng = np.random.default_rng(seed)
    x = np.zeros(T)
    for t in range(1, T):
        x[t] = phi * x[t - 1] + rng.normal()
    return x + mean


def test_circular_weights_are_uniform_and_plain_mbb_is_edge_light():
    n, L = 48, 24
    rng = np.random.default_rng(0)
    c = np.zeros(n); p = np.zeros(n)
    for _ in range(4000):
        c += np.bincount(risk.moving_block_indices(n, n, L, rng), minlength=n)
        p += np.bincount(risk.moving_block_indices(n, n, L, rng, circular=False), minlength=n)
    assert c.max() / c.min() < 1.15
    assert p[0] < 0.1 * p[n // 2]            # first row almost never drawn without wrap-around


def test_paired_bootstrap_ci_contains_sample_mean_on_ar_data():
    """48 steps (as in the event window), 15 cells per step, AR(1) per-step effect."""
    hits_c = hits_p = 0
    n_sim = 120
    for s in range(n_sim):
        step = _ar_series(48, 0.5, s) * np.r_[np.ones(10), 3 * np.ones(28), np.ones(10)]
        d = np.repeat(step, 15) + np.random.default_rng(1000 + s).normal(scale=0.5, size=48 * 15)
        tpos = np.repeat(np.arange(48), 15)
        m = d.mean()
        for circ in (True, False):
            draws = risk.paired_time_block_means(d, tpos, 400, 24, np.random.default_rng(s), circular=circ)
            inside = np.quantile(draws, 0.025) <= m <= np.quantile(draws, 0.975)
            hits_c += inside and circ
            hits_p += inside and not circ
    assert hits_c / n_sim >= 0.9
    assert hits_p < hits_c                   # the plain moving-block version misses more often


def test_bootstrap_mean_is_centred_circular_but_not_plain_when_effect_is_mid_sample():
    T = 48
    d = np.zeros(T); d[18:30] = 1.0           # effect concentrated in the middle, as in the Oct event
    tpos = np.arange(T)
    circ = risk.paired_time_block_means(d, tpos, 4000, 24, np.random.default_rng(1))
    plain = risk.paired_time_block_means(d, tpos, 4000, 24, np.random.default_rng(1), circular=False)
    assert abs(circ.mean() - d.mean()) < 0.01
    assert plain.mean() > d.mean() * 1.5


def test_paired_error_bootstrap_reports_centring():
    d = np.repeat(_ar_series(48, 0.4, 5), 3)
    r = val.paired_error_bootstrap(d, np.repeat(np.arange(48), 3), B=500)
    assert r["bootstrap"] == "circular_block"
    assert abs(r["boot_mean"] - r["mean_diff"]) < 0.1 * (np.std(d) + 1e-9)


# ---------------------------------------------------------------- refit pool and R^2
def _fit():
    from tests.test_uncertainty import _data
    graph, stress, flows = _data()
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress, flows).set_flows(flows)
    return stress, flows, scm


def test_refit_pool_is_residuals_of_drawn_rows_and_r2_optimism_has_expected_sign():
    stress, flows, scm = _fit()
    designs = un.design(scm, stress, flows)
    base = fs.from_scm(scm)
    n = len(stress) - 1
    rng = np.random.default_rng(0)
    own, orig, point = [], [], un.r2_in_sample(base, stress)
    for _ in range(80):
        rows = risk.moving_block_indices(n, n, 12, rng)
        sys_r = un.refit(base, designs, rows)
        assert np.allclose(sys_r.resid, sys_r.resid_all[rows])
        rep = un.r2_replicates(sys_r, stress, rows)
        own.append(rep["own"]["Z"]); orig.append(rep["orig"]["Z"])
    # refit scored on the original rows is below the in-sample point (optimism); scored on its own
    # resample it is at or above it (bootstrap-world in-sample fit), and its percentile CI covers the point
    assert np.mean(orig) < point["Z"] - 0.003
    assert np.mean(own) > np.mean(orig)
    lo, hi = np.quantile(own, [0.025, 0.975])
    assert lo <= point["Z"] <= hi


def test_all_source_attribution_can_pick_a_non_binance_ethena_source():
    nodes = ["Binance", "Ethena", "Kraken", "retail"]
    L = np.ones((4, 4)); attr = np.zeros((4, 4)); share = np.zeros((4, 4))
    attr[2, 3], share[2, 3] = 0.5, 0.5          # Kraken -> retail is the largest channel
    attr[0, 2], share[0, 2] = 0.1, 0.1
    top, n_pairs = un.top_attribution_channels(nodes, {"L_obs": L, "attr": attr, "share": share}, 2)
    assert (top[0]["i"], top[0]["j"]) == ("Kraken", "retail") and n_pairs == 12


def test_report_names_top_channel_over_all_sources(tmp_path, monkeypatch):
    from tests.test_h1_status import _out, _report
    out = _out({"granger": ("inconclusive", [-0.01, 0.01]), "partial_corr": ("inconclusive", [-0.01, 0.01])})
    out["counterfactual_attribution"] = [{"i": "Kraken", "j": "retail", "attribution_share": 0.15}]
    txt = _report(tmp_path, monkeypatch, out)
    assert "Kraken→retail" in txt and "all sources" in txt


# ---------------------------------------------------------------- out-of-sample R^2
def _oos_panel(seed=2, n=200):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-09-01", periods=n, freq="h")
    p = _ar_series(n, 0.3, seed + 1) * 1.0                     # parent
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.7 * y[t - 1] + 0.8 * p[t - 1] + rng.normal(scale=0.3)
    stress = pd.DataFrame({"P": p, "Y": y}, index=idx)
    graph = {"nodes": ["P", "Y"], "parents": {"P": [], "Y": ["P"]}}
    rows = [{"from_entity": "P", "to_entity": "Y", "day": t, "usd_volume": 1e5} for t in idx]
    return stress, pd.DataFrame(rows), graph


def test_oos_r2_ranks_models_and_uses_no_future_information():
    stress, flows, graph = _oos_panel()
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress.iloc[:150], flows[flows.day < stress.index[150]])
    scm.set_flows(flows)
    ev = stress.index[150:190]
    res = oos.rolling_one_step(scm, stress, flows, ev)
    s = oos.summarize(res, B=200)
    assert s["pooled"]["ar"]["r2_os"] > 0.2                     # own lag is informative
    assert s["pooled"]["ar_network"]["r2_os"] >= s["pooled"]["ar"]["r2_os"]
    assert s["increment_over_ar"]["ar_network"]["gain"] > 0     # the parent adds information
    # corrupt everything from the 11th event hour on: predictions up to that hour are unchanged
    st2 = stress.copy(); st2.iloc[161:] += 100.0
    scm2 = StructuralCausalModel(graph, alpha=1.0).fit(st2.iloc[:150], flows[flows.day < stress.index[150]])
    scm2.set_flows(flows)
    res2 = oos.rolling_one_step(scm2, st2, flows, ev)
    k = (res["ent"] == 1) & (res["step"] <= 10)
    for m in oos.MODELS:
        assert np.allclose(res["pred"][m][k], res2["pred"][m][k])


# ---------------------------------------------------------------- A3 verdict and stale-file fixes
def test_a3_verdict_is_driven_by_numbers():
    assert a3.classify_a3(0.0008, [-0.002, 0.004]) == "NO_DIFFERENCE_DETECTED"
    assert a3.classify_a3(0.05, [0.001, 0.01]) == "A3_SUPPORTED"
    assert a3.classify_a3(0.05, [-0.001, 0.01]) == "NO_DIFFERENCE_DETECTED"   # gap big, CI includes 0
    assert a3.classify_a3(-0.05, [-0.01, -0.001]) == "A3_REFUTED_REVERSAL"


def test_validation_script_has_no_hard_coded_date():
    from pathlib import Path
    src = (Path(rb.__file__).parent / "run_validation.py").read_text()
    assert '"generated": "2026' not in src


def test_data_build_status_follows_data_build_json(tmp_path, monkeypatch):
    p = tmp_path / "data_build.json"
    p.write_text(json.dumps({"generated": "2026-10-12", "data_backend": "bigquery",
                             "labels": {"x": 1}, "checks": {"schema_ok": True}}))
    monkeypatch.setattr(rbd, "DATA_BUILD_JSON", p)
    done = rbd._stages_done()
    assert done == {"labels", "check"}
    line = rbd._status_line(done)
    assert "labels" in line and "pending" in line and "budget" in line
    p.write_text(json.dumps({k: {"x": 1} for k in rbd.STAGE_KEYS.values()}))
    assert "all stages have results" in rbd._status_line(rbd._stages_done())
