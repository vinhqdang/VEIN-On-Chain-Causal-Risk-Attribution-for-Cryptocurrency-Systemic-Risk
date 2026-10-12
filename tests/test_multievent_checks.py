"""Power and block-length rules for the multi-event windows (run_multievent.py), and an
offline smoke run of one window on synthetic flows."""
import numpy as np
import pandas as pd

import run_multievent as rm


def test_min_rows_hourly_floor_and_parameter_rule():
    ok = rm.check_min_rows(240, 11, "hour")                 # max(240, 5*11) = 240
    assert ok["ok"] and ok["min_rows_required"] == 240
    short = rm.check_min_rows(239, 11, "hour")
    assert not short["ok"] and short["reason"] == "underpowered"
    wide = rm.check_min_rows(300, 61, "hour")               # 5*61 = 305 > 300
    assert not wide["ok"] and wide["min_rows_required"] == 305


def test_min_rows_daily_floor():
    assert rm.check_min_rows(30, 5, "day")["ok"]
    assert not rm.check_min_rows(29, 5, "day")["ok"]
    assert rm.check_min_rows(37, 8, "day")["min_rows_required"] == 40   # 5*8 > 30


def test_block_length_rule():
    assert rm.block_len_for("hour", 912) == 24
    assert rm.block_len_for("hour", 240) == 24
    assert rm.block_len_for("day", 37) == 3                 # round(37^(1/3)) = 3
    assert rm.block_len_for("day", 8) == 2                  # floor of 2
    assert rm.block_len_for("day", 1000) == 10


def test_k_max_counts_parents_inside_the_node_set():
    parents = {"A": [], "B": ["A", "X"], "C": ["A", "B", "D"]}
    # X and D are not stress nodes, so B has one parent and C has two
    assert rm.k_max_of(parents, ["A", "B", "C"]) == 5
    assert rm.k_max_of({}, []) == 1


def _synthetic(days=40, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-10-01", periods=24 * days, freq="h")
    ents = ["Binance", "Coinbase", "Bitfinex", "retail"]
    rows = []
    for a in ents:
        for b in ents:
            if a != b and rng.random() < 0.6:
                rows.append(pd.DataFrame({"day": idx, "from_entity": a, "to_entity": b,
                                          "usd_volume": rng.uniform(1e5, 1e6, len(idx)),
                                          "n_tx": 2, "from_src": "label", "to_src": "label"}))
    flows = pd.concat(rows, ignore_index=True)
    prices = pd.DataFrame({"USDC": 1 + rng.normal(0, 1e-3, len(idx)),
                           "DAI": 1 + rng.normal(0, 1e-3, len(idx)),
                           "ETH": 1300 + np.cumsum(rng.normal(0, 5, len(idx))),
                           "stETH": 1300 + np.cumsum(rng.normal(0, 5, len(idx))),
                           "AAVE": 60 + np.cumsum(rng.normal(0, 0.1, len(idx)))}, index=idx)
    return flows, prices, idx


def test_underpowered_daily_window_is_not_fitted():
    flows, prices, idx = _synthetic(days=20)
    flows_d = flows.assign(day=flows["day"].dt.normalize()).groupby(
        ["day", "from_entity", "to_entity"], as_index=False).agg(
        usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum"),
        from_src=("from_src", "max"), to_src=("to_src", "max"))
    out = rm.analyze_window("syn", flows_d, prices.resample("D").last(),
                            ("2022-10-01", "2022-10-20"), ("2022-10-18", "2022-10-19"), "day")
    assert out["ok"] is False and out["reason"] == "underpowered"
    assert "oc_ranking" not in out


def test_hourly_smoke_run_on_synthetic_flows():
    flows, prices, idx = _synthetic(days=40)
    ev = (pd.Timestamp("2022-11-08"), pd.Timestamp("2022-11-09 23:00"))
    out = rm.analyze_window("syn", flows, prices, ("2022-10-01", "2022-11-09"), ev, "hour",
                            calm=(pd.Timestamp("2022-10-12"), pd.Timestamp("2022-10-13 23:00")),
                            n_sims=30, n_boot=3, n_sims_boot=10, n_boot_falsification=10)
    assert out["ok"], out.get("reason")
    assert out["block_len"] == 24
    assert out["n_fit_rows"] >= out["min_rows_required"]
    assert len(out["oc_ranking"]) <= 6
    assert set(out["falsification_ci"]) == {"reversed_minus_true", "symmetric_minus_true"}
    assert 0 <= out["placebo_rolling"]["p_value"] <= 1
    assert out["calm_window"]["n_rows"] == 48
    for e in out["entities"]:
        assert out["stress_components"][e]["fit_std"] > 1e-9
