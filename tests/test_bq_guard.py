"""Tests for the BigQuery budget guard, ledger, cache and run_sql (vein/bq.py).

No cloud access: a fake client stands in for google.cloud.bigquery.Client.
"""
import json
from types import SimpleNamespace

import pytest

from vein import bq, config

GIB = 2 ** 30


class FakeRow:
    def __init__(self, d):
        self._d = d

    def items(self):
        return self._d.items()


class FakeJob:
    def __init__(self, dry_bytes=0, billed=0, rows=(), cache_hit=False):
        self.total_bytes_processed = dry_bytes
        self.total_bytes_billed = billed
        self.cache_hit = cache_hit
        self.job_id = "job-1"
        self._rows = list(rows)

    def result(self, page_size=None):
        return [FakeRow(r) for r in self._rows]


class FakeClient:
    project = "proj-x"

    def __init__(self, dry_bytes, rows=()):
        self.dry_bytes = dry_bytes
        self.rows = rows
        self.calls = []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        if getattr(job_config, "dry_run", False):
            return FakeJob(dry_bytes=self.dry_bytes)
        return FakeJob(dry_bytes=self.dry_bytes, billed=self.dry_bytes, rows=self.rows)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(bq, "CACHE_DIR", cache)
    monkeypatch.setattr(bq, "LEDGER", cache / "bq_ledger.json")
    return cache


def test_check_budget_per_query_cap():
    with pytest.raises(bq.BudgetError, match="per-query"):
        bq.check_budget(200 * GIB, bq._empty_ledger(), 150, 800, 950, "2026-06")


def test_check_budget_hard_cap_uses_cumulative():
    ledger = {"cumulative_billed_bytes": 700 * GIB, "by_month": {}}
    with pytest.raises(bq.BudgetError, match="hard cap"):
        bq.check_budget(120 * GIB, ledger, 150, 800, 950, "2026-06")


def test_check_budget_monthly_cap():
    ledger = {"cumulative_billed_bytes": 0, "by_month": {"2026-06": 900 * GIB}}
    with pytest.raises(bq.BudgetError, match="monthly"):
        bq.check_budget(100 * GIB, ledger, 150, 800, 950, "2026-06")


def test_check_budget_passes_under_caps():
    ledger = {"cumulative_billed_bytes": 100 * GIB, "by_month": {"2026-06": 100 * GIB}}
    assert bq.check_budget(50 * GIB, ledger, 150, 800, 950, "2026-06") is None


def test_ledger_round_trip(tmp_path):
    path = tmp_path / "ledger.json"
    assert bq.load_ledger(path)["cumulative_billed_bytes"] == 0
    led = bq._empty_ledger()
    led["cumulative_billed_bytes"] = 5 * GIB
    led["entries"].append({"kind": "query", "billed_bytes": 5 * GIB})
    bq.save_ledger(led, path)
    assert not (tmp_path / "ledger.json.tmp").exists()
    assert bq.load_ledger(path) == led


def test_run_sql_returns_cached_rows_without_client(paths, monkeypatch):
    sql = "SELECT 1 AS x"
    paths.mkdir(parents=True, exist_ok=True)
    (paths / f"bq_{bq.sql_hash(sql)}.json").write_text(json.dumps({"rows": [{"x": 1}]}))

    def boom(*a, **k):
        raise AssertionError("client must not be created for a cache hit")
    monkeypatch.setattr(bq, "get_client", boom)
    assert bq.run_sql(sql) == [{"x": 1}]


def test_fake_client_dry_run_over_cap_never_executes(paths):
    client = FakeClient(dry_bytes=200 * GIB)
    with pytest.raises(bq.BudgetError):
        bq.run_sql("SELECT 2", client=client)
    assert client.calls, "a dry run must happen first"
    assert all(getattr(cfg, "dry_run", False) for _, cfg in client.calls)


def test_executed_job_sets_maximum_bytes_billed_and_records_ledger(paths):
    rows = [{"day": "2025-10-08T00:00:00+00:00", "vol": 1.5}]
    client = FakeClient(dry_bytes=2 * GIB, rows=rows)
    out = bq.run_sql("SELECT 3", name="unit", client=client)
    assert out == rows
    executed = [cfg for _, cfg in client.calls if not getattr(cfg, "dry_run", False)]
    assert len(executed) == 1
    expected_cap = int(min(config.BQ_MAX_GIB_PER_QUERY, config.BQ_HARD_CAP_GIB) * GIB)
    assert executed[0].maximum_bytes_billed == expected_cap
    led = bq.load_ledger()
    kinds = [e["kind"] for e in led["entries"]]
    assert kinds == ["dry_run", "query"]
    assert led["cumulative_billed_bytes"] == 2 * GIB
    cached = json.loads((paths / f"bq_{bq.sql_hash('SELECT 3')}.json").read_text())
    assert cached["rows"] == rows
    # the second call hits the cache and bills nothing
    assert bq.run_sql("SELECT 3", client=FakeClient(dry_bytes=2 * GIB)) == rows


def test_timestamps_and_bytes_are_json_safe():
    import datetime as dt
    import decimal
    from zoneinfo import ZoneInfo
    v = bq._jsonable_value(dt.datetime(2025, 10, 8, 1, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
    assert v == "2025-10-07T18:00:00+00:00"
    assert bq._jsonable_value(b"\x01\xff") == "0x01ff"
    assert bq._jsonable_value(decimal.Decimal("1.25")) == 1.25


def test_job_config_fallback_has_same_attribute_names(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_google(name, *a, **k):
        if name.startswith("google"):
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_google)
    cfg = bq._job_config(dry_run=True, maximum_bytes_billed=5)
    assert isinstance(cfg, SimpleNamespace)
    assert cfg.dry_run is True and cfg.maximum_bytes_billed == 5
