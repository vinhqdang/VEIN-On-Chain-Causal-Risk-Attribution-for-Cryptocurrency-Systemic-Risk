"""With VEIN_BACKEND=dune the legacy Dune path is used unchanged; with bigquery the
entry points dispatch to vein.bq_flows. Nothing here touches a network or a cloud."""
import pytest

from vein import config, entity_resolution as er, onchain_graph as og, resolver


@pytest.fixture
def dune_rows(monkeypatch):
    calls = []

    def fake_run_sql(sql, name="x", **kw):
        calls.append((name, sql))
        return [{"day": "2025-10-08T00:00:00+00:00", "from_entity": "Binance Hot 1",
                 "to_entity": "Ethena", "from_src": "seed", "to_src": "seed",
                 "volume": 7.0, "n_tx": 2}]
    monkeypatch.setattr(er, "run_sql", fake_run_sql)
    monkeypatch.setattr(config, "DATA_BACKEND", "dune")
    return calls


def test_dune_path_still_runs_legacy_sql(dune_rows, monkeypatch):
    from vein import bq_flows
    monkeypatch.setattr(bq_flows, "load_resolved_flows_bq",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("bq used under dune")))
    df = er.load_resolved_flows("2025-10-08", "2025-10-14", ["USDe"], bucket="day", min_addr_volume=0)
    assert dune_rows and dune_rows[0][0] == "vein_resolved_flows"
    assert "evt_Transfer" in dune_rows[0][1]
    assert list(df.columns) == ["day", "from_entity", "to_entity", "usd_volume", "n_tx",
                                "from_src", "to_src"]
    assert df.from_entity.iloc[0] == "Binance"    # legacy token strip still applied under dune


def test_dune_normalize_keeps_legacy_mapping(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "dune")
    assert er.normalize_entity("Binance US 3") == "Binance US"


def test_bigquery_dispatch_for_flows_resolver_and_sweeps(monkeypatch):
    from vein import bq_flows
    seen = {}
    monkeypatch.setattr(config, "DATA_BACKEND", "bigquery")
    monkeypatch.setattr(bq_flows, "load_resolved_flows_bq",
                        lambda *a, **k: seen.setdefault("flows", (a, k)) and "FLOWS")
    monkeypatch.setattr(bq_flows, "fetch_labeled_edges_bq",
                        lambda *a, **k: seen.setdefault("edges", a) and "EDGES")
    monkeypatch.setattr(bq_flows, "detect_deposit_sweeps_bq",
                        lambda key, *a, **k: seen.setdefault("sweeps", key) and "SWEEPS")
    assert er.load_resolved_flows("2025-10-08", "2025-10-14", ["USDe"], bucket="hour",
                                  min_addr_volume=1e3) == "FLOWS"
    assert resolver.fetch_labeled_edges("USDe", "2025-10-08", "2025-10-14") == "EDGES"
    assert er.detect_deposit_sweeps(key="oct25_hourly") == "SWEEPS"
    assert seen["sweeps"] == "oct25_hourly"


def test_onchain_load_flows_is_dune_only(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "bigquery")
    with pytest.raises(NotImplementedError):
        og.load_flows("2025-10-08", "2025-10-14")


def test_invalid_backend_rejected_at_import(monkeypatch):
    import importlib
    monkeypatch.setenv("VEIN_BACKEND", "snowflake")
    with pytest.raises(ValueError):
        importlib.reload(config)
    monkeypatch.delenv("VEIN_BACKEND")
    importlib.reload(config)
    assert config.DATA_BACKEND == "bigquery"
