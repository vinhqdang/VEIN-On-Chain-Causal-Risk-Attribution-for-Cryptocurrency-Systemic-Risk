"""Hourly stress panel (vein/hourly_stress.py).

The CEX/retail and Ethena columns must reproduce the legacy formula of run_best.py exactly
(copied below from the pre-fix version). The new components are checked on synthetic
inputs for their drop reasons and for the zero-stress guard.
"""
import numpy as np
import pandas as pd
import pytest

from vein import config, hourly_stress as hs

# ---- legacy implementation, copied from run_best.py before the fix -------------------
LEGACY_ROLL = 48


def legacy_zscore(s, win=LEGACY_ROLL):
    mu = s.rolling(win, min_periods=6).mean()
    sd = s.rolling(win, min_periods=6).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def legacy_build_hourly_stress(flows, entities, prices=None):
    idx = pd.DatetimeIndex(sorted(flows["day"].unique()))
    cols = {}
    for e in entities:
        inf = flows[flows.to_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        outf = flows[flows.from_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        tot = inf + outf
        net = ((outf - inf) / tot.rolling(LEGACY_ROLL, min_periods=6).mean().replace(0, np.nan)).fillna(0.0)
        cols[e] = 0.6 * legacy_zscore(net) + 0.4 * legacy_zscore(tot)
    panel = pd.DataFrame(cols, index=idx).fillna(0.0)
    if prices is not None and "USDe" in prices.columns and "Ethena" in panel.columns:
        peg = (1.0 - prices["USDe"].reindex(idx).ffill()).abs()
        panel["Ethena"] = 0.5 * panel["Ethena"] + 0.5 * legacy_zscore(peg)
    return panel.fillna(0.0)


# ---- synthetic inputs ----------------------------------------------------------------
def _flows(n=240, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-09-15", periods=n, freq="h")
    rows = []
    pairs = [("Binance", "retail"), ("retail", "Binance"), ("Ethena", "Binance"),
             ("Binance", "Ethena"), ("retail", "Ethena"), ("Ethena", "retail")]
    for a, b in pairs:
        for t in idx:
            if rng.uniform() < 0.8:
                rows.append({"from_entity": a, "to_entity": b, "day": t,
                             "usd_volume": float(rng.uniform(1e4, 1e6))})
    return pd.DataFrame(rows), idx


def _prices(idx, seed=2):
    rng = np.random.default_rng(seed)
    usde = 1.0 + np.cumsum(rng.normal(scale=2e-4, size=len(idx)))
    return pd.DataFrame({"USDe": usde, "ETH": 3000 * np.exp(np.cumsum(rng.normal(scale=1e-3, size=len(idx)))),
                         "stETH": 2900 * np.exp(np.cumsum(rng.normal(scale=1.2e-3, size=len(idx))))},
                        index=idx)


# ---- legacy equivalence --------------------------------------------------------------
def test_flow_only_entities_match_legacy_formula_exactly():
    flows, idx = _flows()
    ents = ["Binance", "retail"]
    new, meta = hs.build_hourly_stress(flows, ents)
    old = legacy_build_hourly_stress(flows, ents)
    np.testing.assert_allclose(new[ents].values, old[ents].values, atol=1e-12, rtol=0)
    assert meta["Binance"]["used"] == ["flow"] and meta["retail"]["used"] in ([], ["flow"])


def test_ethena_matches_legacy_flow_plus_usde_peg_exactly():
    flows, idx = _flows()
    prices = _prices(idx)
    new, meta = hs.build_hourly_stress(flows, ["Ethena", "Binance"], prices)
    old = legacy_build_hourly_stress(flows, ["Ethena", "Binance"], prices)
    np.testing.assert_allclose(new["Ethena"].values, old["Ethena"].values, atol=1e-12, rtol=0)
    np.testing.assert_allclose(new["Binance"].values, old["Binance"].values, atol=1e-12, rtol=0)
    assert meta["Ethena"]["used"] == ["flow", "peg:USDe"]


def test_ethena_matches_legacy_when_some_price_timestamps_are_off_the_hour():
    # 60% of quotes sit on the hour, the rest 37 minutes later. The observed share (0.6) keeps
    # the peg component; the off-hour quotes are carried forward on their own timestamps, as
    # the legacy price panel was, before the reindex to flow hours.
    flows, idx = _flows()
    prices = _prices(idx)
    cut = int(0.6 * len(idx))
    shifted = prices.copy()
    shifted.index = list(idx[:cut]) + list(idx[cut:] + pd.Timedelta(minutes=37))
    legacy_panel = shifted.sort_index().reindex(shifted.index.union(idx)).ffill()
    new, meta = hs.build_hourly_stress(flows, ["Ethena"], shifted)
    old = legacy_build_hourly_stress(flows, ["Ethena"], legacy_panel.reindex(idx))
    assert meta["Ethena"]["used"] == ["flow", "peg:USDe"]
    np.testing.assert_allclose(new["Ethena"].values, old["Ethena"].values, atol=1e-12, rtol=0)


def test_legacy_ethena_without_usde_price_is_flow_only():
    flows, idx = _flows()
    prices = _prices(idx).drop(columns=["USDe"])
    new, meta = hs.build_hourly_stress(flows, ["Ethena"], prices)
    old = legacy_build_hourly_stress(flows, ["Ethena"], prices)
    np.testing.assert_allclose(new["Ethena"].values, old["Ethena"].values, atol=1e-12, rtol=0)
    assert meta["Ethena"]["dropped"]["peg:USDe"] == "no price column USDe"


# ---- new components and guards -------------------------------------------------------
def test_lido_without_series_drops_redeem_with_reason_and_keeps_discount():
    flows, idx = _flows()
    prices = _prices(idx)
    panel, meta = hs.build_hourly_stress(flows, ["Lido"], prices, lido=None)
    assert meta["Lido"]["used"] == ["discount:stETH/ETH"]
    assert meta["Lido"]["dropped"]["lido_redeem"] == "no Lido series"
    assert panel["Lido"].std() > hs.FIT_STD_MIN


def test_lido_redeem_component_used_when_series_given():
    flows, idx = _flows()
    prices = _prices(idx)
    rng = np.random.default_rng(4)
    lido = pd.DataFrame({"steth_mint": rng.uniform(0, 1e6, len(idx)),
                         "steth_wq_in": rng.uniform(0, 1e6, len(idx)),
                         "steth_gross": rng.uniform(0, 1e7, len(idx))}, index=idx)
    _, meta = hs.build_hourly_stress(flows, ["Lido"], prices, lido=lido)
    assert meta["Lido"]["used"] == ["discount:stETH/ETH", "lido_redeem"]


def test_entity_with_low_observed_price_share_drops_component():
    flows, idx = _flows()
    prices = _prices(idx)
    prices.loc[prices.index[: int(0.7 * len(idx))], "USDe"] = np.nan   # 30% observed
    _, meta = hs.build_hourly_stress(flows, ["Ethena"], prices)
    assert "observed price share" in meta["Ethena"]["dropped"]["peg:USDe"]


def test_entity_without_inputs_is_zero_stress_and_guard_raises():
    flows, idx = _flows()
    panel, meta = hs.build_hourly_stress(flows, ["Binance", "Aave"], prices=None)
    assert meta["Aave"]["used"] == []
    assert "fit-window std" in meta["Aave"]["dropped"]["flow"]
    assert hs.zero_stress_entities(panel, panel.index) == ["Aave"]
    with pytest.raises(RuntimeError, match="Aave"):
        hs.assert_nonzero_stress(panel, panel.index)
    hs.assert_nonzero_stress(panel[["Binance"]], panel.index)   # no raise


def test_fit_window_screen_uses_fit_end_only():
    flows, idx = _flows(n=240)
    cut = idx[120]
    panel, meta = hs.build_hourly_stress(flows, ["Binance"], fit_end=cut)
    assert meta["Binance"]["fit_std"] > 0
    assert hs.zero_stress_entities(panel, idx[:120]) == []


def test_window_mismatch_warns():
    flows, idx = _flows(n=240)
    with pytest.warns(UserWarning, match="steps"):
        hs.build_hourly_stress(flows, ["Binance"], window=(idx[0], idx[0] + pd.Timedelta(hours=300)))


def test_daily_variant_runs_with_daily_roll():
    flows, idx = _flows(n=240)
    daily = flows.assign(day=flows["day"].dt.normalize()).groupby(
        ["day", "from_entity", "to_entity"], as_index=False).usd_volume.sum()
    panel, meta = hs.build_hourly_stress(daily, ["Binance"], roll=14, min_periods=3, freq="D")
    assert panel.shape[0] == daily.day.nunique() and meta["Binance"]["used"] == ["flow"]


def test_component_names_are_configured():
    for e, comps in config.HOURLY_STRESS_COMPONENTS.items():
        for c in comps:
            assert c == "flow" or c.startswith(("peg:", "drawdown:")) or c in (
                "discount:stETH/ETH", "lido_redeem"), (e, c)
