"""H1 decision rule and the report wording that depends on it."""
import run_best as rb
from vein import validation as val


def test_status_observed_better_when_ci_above_zero():
    assert val.h1_status((0.01, 0.05)) == "observed_better"


def test_status_inconclusive_when_ci_covers_zero():
    assert val.h1_status((-0.005, 0.05)) == "inconclusive"


def test_status_estimated_better_when_ci_below_zero():
    assert val.h1_status((-0.05, -0.01)) == "estimated_better"


def _out(statuses):
    boot = {g: {"mean_diff": 0.01, "ci95": ci, "status": st,
                "ci95_weighted": ci, "ci95_block8": ci, "prob_observed_better": 0.9}
            for g, (st, ci) in statuses.items()}
    return {
        "n_fit_hours": 10, "n_event_hours": 48, "n_entities": 5, "graph_edges": 4,
        "H1": {"comparison_nodes": ["Ethena", "Binance"], "edge_counts": {},
               "scores": [{"model": "observed_onchain", "rmse": 0.1, "corr": 0.5, "n": 96},
                          {"model": "estimated_granger", "rmse": 0.2, "corr": 0.4, "n": 96}],
               "bootstrap": boot,
               "H1_supported": all(b["status"] == "observed_better" for b in boot.values())},
        "falsification": [{"model": "true_direction", "rmse": 0.1},
                          {"model": "reversed_edges", "rmse": 0.2},
                          {"model": "symmetric", "rmse": 0.2}],
        "falsification_ci": {"reversed_minus_true": {"mean_diff": 0.1, "ci95": [0.0, 0.2]}},
        "oc_covar_ranking": [{"entity": "Ethena", "exported_risk": 1.0, "mc_se": 0.01}],
        "counterfactual_attribution": [{"i": "Ethena", "j": "Binance", "attribution_share": 0.1}],
        "placebo": {"structural_zero_check": {"max_abs_attr_unconnected": 0.0, "passes": True},
                    "rolling_temporal": {"event_stat": 1.0, "n_windows": 5, "p_value": 0.2, "passes": False},
                    "time_shift": {"real_stat": 1.0, "B": 10, "p_value": 0.5, "passes": False}},
        "resolution_robustness": {"spearman": 0.9, "n_common": 5},
        "external_validity": {"separation": 0.1, "pairwise_concordance": 0.5, "nondegenerate": True},
        "confounding_sensitivity": {"edges": []},
        "backtests": {},
    }


def _report(tmp_path, monkeypatch, out):
    monkeypatch.setattr(rb, "RESULTS", tmp_path)
    rb.write_report(out)
    return (tmp_path / "FINAL_REPORT.md").read_text()


def test_report_claims_support_only_when_all_ci_exclude_zero(tmp_path, monkeypatch):
    txt = _report(tmp_path, monkeypatch, _out({
        "granger": ("observed_better", [0.01, 0.05]),
        "partial_corr": ("observed_better", [0.02, 0.06])}))
    assert "H1 supported: observed graph better than every estimated graph" in txt


def test_report_has_no_support_claim_when_inconclusive(tmp_path, monkeypatch):
    txt = _report(tmp_path, monkeypatch, _out({
        "granger": ("inconclusive", [-0.005, 0.05]),
        "partial_corr": ("observed_better", [0.02, 0.06])}))
    assert "supported" not in txt.lower()
    assert "H1 not established: CI includes 0 vs granger" in txt


def test_report_states_contradiction(tmp_path, monkeypatch):
    txt = _report(tmp_path, monkeypatch, _out({
        "granger": ("estimated_better", [-0.05, -0.01]),
        "partial_corr": ("observed_better", [0.02, 0.06])}))
    assert "H1 contradicted vs granger" in txt
    assert "supported" not in txt.lower()
