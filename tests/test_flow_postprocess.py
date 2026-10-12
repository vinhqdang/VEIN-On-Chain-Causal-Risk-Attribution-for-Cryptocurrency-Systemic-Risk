"""Tests for bq_flows.postprocess_flow_rows: the Python half of the BigQuery flow loader."""
import numpy as np
import pandas as pd
import pytest

from vein import bq_flows, config


@pytest.fixture(autouse=True)
def bigquery_backend(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "bigquery")


def _row(**kw):
    base = {"day": "2025-10-08T00:00:00+00:00", "token": "USDe", "from_entity": "Ethena",
            "to_entity": "Binance", "from_src": "seed", "to_src": "label", "volume": 1000.0, "n_tx": 3}
    base.update(kw)
    return base


ETH_PX = pd.Series([3000.0, 2000.0], index=pd.to_datetime(["2025-10-08", "2025-10-09"]))


def test_weth_rows_are_converted_with_daily_eth_price():
    rows = [_row(token="WETH", volume=2.0, day="2025-10-09T00:00:00+00:00")]
    out = bq_flows.postprocess_flow_rows(rows, "day", ETH_PX, min_usd=0.0)
    assert out.usd_volume.iloc[0] == pytest.approx(4000.0)


def test_stablecoin_rows_are_dollar_per_unit_and_eth_price_not_required():
    rows = [_row(volume=1234.5)]
    out = bq_flows.postprocess_flow_rows(rows, "day", None, min_usd=0.0)
    assert out.usd_volume.iloc[0] == pytest.approx(1234.5)


def test_eth_rows_without_price_fail_loudly():
    with pytest.raises(ValueError, match="ETH price"):
        bq_flows.postprocess_flow_rows([_row(token="wBETH")], "day", None, min_usd=0.0)


def test_threshold_applies_after_root_aggregation():
    # Two sub-wallets of Binance, $600 each: neither passes $1,000 alone, the root does.
    rows = [_row(from_entity="Binance Hot 1", to_entity="Ethena", volume=600.0),
            _row(from_entity="Binance Hot 2", to_entity="Ethena", volume=600.0)]
    out = bq_flows.postprocess_flow_rows(rows, "day", None, min_usd=1000.0)
    assert len(out) == 1
    assert out.from_entity.iloc[0] == "Binance" and out.to_entity.iloc[0] == "Ethena"
    assert out.usd_volume.iloc[0] == pytest.approx(1200.0)
    assert out.n_tx.iloc[0] == 6


def test_self_loops_are_dropped_after_root_mapping():
    rows = [_row(from_entity="Binance Hot 1", to_entity="Binance Hot 2", volume=5000.0),
            _row(volume=10.0)]
    out = bq_flows.postprocess_flow_rows(rows, "day", None, min_usd=0.0)
    assert len(out) == 1
    assert not (out.from_entity == out.to_entity).any()


def test_hourly_buckets_are_not_floored_daily_are():
    hourly = [_row(day="2025-10-10T13:00:00+00:00", volume=5.0)]
    out_h = bq_flows.postprocess_flow_rows(hourly, "hour", None, min_usd=0.0)
    assert out_h.day.iloc[0] == pd.Timestamp("2025-10-10 13:00:00")
    daily = [_row(day="2025-10-10T00:00:00+00:00", volume=5.0)]
    out_d = bq_flows.postprocess_flow_rows(daily, "day", None, min_usd=0.0)
    assert out_d.day.iloc[0] == pd.Timestamp("2025-10-10")


def test_timestamps_are_tz_naive():
    out = bq_flows.postprocess_flow_rows([_row()], "day", None, min_usd=0.0)
    assert out.day.dt.tz is None


def test_output_columns_exact_including_empty():
    cols = ["day", "from_entity", "to_entity", "usd_volume", "n_tx", "from_src", "to_src"]
    out = bq_flows.postprocess_flow_rows([_row()], "day", None, min_usd=0.0)
    assert list(out.columns) == cols
    empty = bq_flows.postprocess_flow_rows([], "day", None, min_usd=0.0)
    assert list(empty.columns) == cols and empty.empty


def test_threshold_drops_small_flows():
    rows = [_row(volume=999.0), _row(from_entity="OKX", volume=1001.0)]
    out = bq_flows.postprocess_flow_rows(rows, "day", None, min_usd=1000.0)
    assert list(out.from_entity) == ["OKX"]


def test_eth_lookup_fills_missing_days():
    days = pd.DatetimeIndex(["2025-10-07", "2025-10-08", "2025-10-10"])
    px = bq_flows._eth_lookup(ETH_PX, days)
    assert np.allclose(px, [3000.0, 3000.0, 2000.0])


def test_usde_daily_check_uses_small_hourly_extract_not_core(monkeypatch):
    """The Dune sanity check must not force the large core_daily extract to be built."""
    import datetime as dt
    built = []
    monkeypatch.setattr(bq_flows, "ensure_extract",
                        lambda key, refresh=False: (built.append(key) or (["t"], ["h"])))
    monkeypatch.setattr(bq_flows.bq, "run_sql", lambda *a, **k: [])
    bq_flows.usde_daily_bq(dt.date(2025, 10, 8), dt.date(2025, 10, 14))
    assert built == ["oct25_hourly"]
    with pytest.raises(ValueError):
        bq_flows.usde_daily_bq(dt.date(2025, 10, 8), dt.date(2025, 10, 14), key="ftx_hourly")


def test_open_labels_default_is_wallet_only(monkeypatch, tmp_path):
    p = tmp_path / "labels_open.csv.gz"
    pd.DataFrame({"address": ["0x" + "a" * 40, "0x" + "b" * 40], "entity": ["Bitget"] * 2,
                  "src": ["label"] * 2, "etype": ["CEX"] * 2,
                  "raw_name": ["Bitget Dep: 0x" + "a" * 40, "Bitget: Hot Wallet 1"],
                  "source": ["t"] * 2}).to_csv(p, index=False, compression="gzip")
    monkeypatch.setattr(bq_flows, "OPEN_LABELS", p)
    assert bq_flows._open_labels().address.tolist() == ["0x" + "b" * 40]
    assert bq_flows._open_labels(kind="deposit").address.tolist() == ["0x" + "a" * 40]
    assert len(bq_flows._open_labels(kind=None)) == 2
