"""Offline tests for vein/bq_sql.py: the SQL text the BigQuery stages will run."""
import datetime as dt
import re

import pytest

from vein import bq, bq_sql, config

D = dt.date
EXTRACT_HASH = ["abc123", "def456"]
LABELS = "PROJECT.vein.labels_e2025"
FP = "0123456789ab"


@pytest.fixture(autouse=True)
def _project(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-x")


def _tables():
    return ["proj-x.vein.x_a_c00", "proj-x.vein.x_a_c01"]


# ---------------------------------------------------------------- extract
def test_extract_sql_bounds_are_literal_and_end_exclusive():
    sql = bq_sql.extract_sql("oct25_hourly", D(2025, 9, 15), D(2025, 9, 30))
    assert "block_timestamp >= TIMESTAMP('2025-09-15 00:00:00+00')" in sql
    assert "block_timestamp <  TIMESTAMP('2025-09-30 00:00:00+00')" in sql
    assert "t.value != '0'" in sql
    assert "TIMESTAMP_TRUNC(t.block_timestamp, HOUR)" in sql


def test_core_extract_buckets_by_day():
    sql = bq_sql.extract_sql("core_daily", D(2025, 1, 1), D(2025, 4, 1))
    assert "TIMESTAMP_TRUNC(t.block_timestamp, DAY)" in sql
    assert "HOUR)" not in sql


def test_extract_token_addresses_are_lowercase_and_complete():
    sql = bq_sql.extract_sql("oct25_hourly", D(2025, 9, 15), D(2025, 9, 30))
    found = re.findall(r"0x[0-9a-fA-F]{40}", sql)
    assert found and all(a == a.lower() for a in found)
    for sym in config.BQ_EXTRACTS["oct25_hourly"]["tokens"]:
        assert config.TOKENS[sym].lower() in sql
    assert f"{config.BQ_SOURCE}.token_transfers" in sql


@pytest.mark.parametrize("forbidden", [
    "DATE(t.block_timestamp", "evt_Transfer", "date_trunc(", "power(", '"from"', "labels.cex",
])
def test_sql_avoids_dune_idioms(forbidden):
    for sql in (bq_sql.extract_sql("core_daily", D(2025, 1, 1), D(2025, 2, 1)),
                bq_sql.flow_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 2),
                                ["USDe"], "day"),
                bq_sql.sweep_sql(_tables(), LABELS, FP, EXTRACT_HASH, {"USDe": 1.0}, config.SWEEP_PARAMS)):
        assert forbidden not in sql


def test_chunks_are_contiguous_non_overlapping_and_cover_span():
    ch = bq_sql.chunks(D(2025, 1, 1), D(2026, 6, 30), 110)
    assert ch[0][0] == D(2025, 1, 1) and ch[-1][1] == D(2026, 6, 30)
    for (a0, a1), (b0, b1) in zip(ch, ch[1:]):
        assert a1 == b0 and a0 < a1
    assert all((e - s).days <= 110 for s, e in ch)


def test_core_daily_has_five_chunks_and_table_ids():
    spec = config.BQ_EXTRACTS["core_daily"]
    assert len(bq_sql.chunks(spec["start"], spec["end"], spec["chunk_days"])) == 5
    ids = bq_sql.extract_table_ids("core_daily")
    assert len(ids) == 5
    assert ids[0] == "proj-x.vein.x_core_daily_c00"
    assert ids[4] == "proj-x.vein.x_core_daily_c04"


def test_chunks_reject_bad_size():
    with pytest.raises(ValueError):
        bq_sql.chunks(D(2025, 1, 1), D(2025, 2, 1), 0)


# ---------------------------------------------------------------- stage 2
def test_flow_sql_structure_and_header():
    sql = bq_sql.flow_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 22),
                          ["USDC", "USDT", "WETH"], "day")
    assert sql.startswith(f"-- vein:flows extract=abc123,def456 labels={FP}")
    assert sql.count("UNION ALL") == 1
    assert "`proj-x.vein.x_a_c00`" in sql and "`proj-x.vein.x_a_c01`" in sql
    assert "x.token IN ('USDC', 'USDT', 'WETH')" in sql
    assert "lf.entity IS NOT NULL OR lt.entity IS NOT NULL" in sql
    assert "TIMESTAMP_TRUNC(x.bucket, DAY)" in sql
    assert "x.bucket >= TIMESTAMP('2025-10-01 00:00:00+00')" in sql
    assert "x.bucket < TIMESTAMP('2025-10-22 00:00:00+00')" in sql


def test_flow_sql_hourly_keeps_hour_bucket():
    sql = bq_sql.flow_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 14),
                          ["USDe"], "hour")
    assert "TIMESTAMP_TRUNC(x.bucket, HOUR)" in sql


def test_flow_sql_deterministic_and_fingerprint_changes_hash():
    a = bq_sql.flow_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 2), ["USDe"], "day")
    b = bq_sql.flow_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 2), ["USDe"], "day")
    c = bq_sql.flow_sql(_tables(), LABELS, "ffffffffffff", EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 2),
                        ["USDe"], "day")
    assert a == b
    assert bq.sql_hash(a) == bq.sql_hash(b)
    assert bq.sql_hash(a) != bq.sql_hash(c)
    assert a.split("\n")[0] != c.split("\n")[0]


def test_sweep_sql_contains_all_params_and_rank_one():
    params = config.SWEEP_PARAMS
    sql = bq_sql.sweep_sql(_tables(), LABELS, FP, EXTRACT_HASH, {"USDe": 1.0, "WETH": 3100.5}, params)
    assert "rk = 1" in sql
    for k in ("tau", "max_other_hot_share", "max_out_cp", "k_in", "min_fwd", "max_fwd",
              "max_in_from_hot_share", "min_timed_share", "min_sweep_usd"):
        assert f"{params[k]}" in sql, k
    assert f"INTERVAL {params['h_hours']} HOUR" in sql
    assert "STRUCT('WETH' AS token, 3100.5 AS u)" in sql
    assert "params=" in sql.split("\n")[0]


def test_sweep_sql_restricts_hot_and_known_sets():
    sql = bq_sql.sweep_sql(_tables(), LABELS, FP, EXTRACT_HASH, {"USDe": 1.0}, config.SWEEP_PARAMS)
    assert "etype='CEX' AND src IN ('seed','label')" in sql
    assert "src IN ('seed','label')" in sql
    assert "xu.from_a != FROM_HEX(REPEAT('0',40))" in sql


def test_edges_and_coverage_and_usde_sql():
    e = bq_sql.edges_sql(_tables(), LABELS, FP, EXTRACT_HASH, "USDe", D(2025, 10, 8), D(2025, 10, 14))
    assert "x.token='USDe'" in e and "CONCAT('0x', TO_HEX(x.from_a))" in e
    assert "etype='CEX'" in e
    c = bq_sql.coverage_sql(_tables(), LABELS, FP, EXTRACT_HASH, D(2025, 10, 1), D(2025, 10, 2))
    assert "is_mint_burn" in c and "COALESCE(lf.src,'none')" in c
    u = bq_sql.usde_daily_sql(_tables(), EXTRACT_HASH, D(2025, 10, 8), D(2025, 10, 14))
    assert "token='USDe'" in u and "TIMESTAMP_TRUNC(bucket, DAY)" in u
    s = bq_sql.sender_usd_sql(_tables(), EXTRACT_HASH, {"USDe": 1.0}, D(2025, 10, 8), D(2025, 10, 14))
    assert "SUM(x.amount * px.u)" in s


def test_select_extract_cases():
    assert bq_sql.select_extract(D(2025, 1, 1), D(2026, 6, 30), ["USDe", "sUSDe", "wBETH"], "day") == "core_daily"
    assert bq_sql.select_extract(D(2025, 10, 1), D(2025, 10, 22), ["USDC", "USDT", "WETH"], "day") == "oct25_hourly"
    assert bq_sql.select_extract(D(2025, 10, 1), D(2025, 10, 14),
                                 ["USDe", "sUSDe", "wBETH", "USDC", "USDT"], "hour") == "oct25_hourly"
    assert bq_sql.select_extract(D(2022, 11, 1), D(2022, 11, 16), ["USDC", "USDT", "WETH"], "day") == "ftx_hourly"
    assert bq_sql.select_extract(D(2023, 3, 1), D(2023, 3, 16), ["USDC", "USDT", "WETH"], "day") == "svb_hourly"


def test_select_extract_rejects_uncovered_window():
    with pytest.raises(ValueError):
        bq_sql.select_extract(D(2024, 1, 1), D(2024, 2, 1), ["USDC"], "day")


def test_select_extract_rejects_day_request_for_core_token_outside_core():
    # WETH is not in core_daily, and no other extract covers 2025-01 with USDe alone.
    with pytest.raises(ValueError):
        bq_sql.select_extract(D(2025, 1, 2), D(2025, 1, 10), ["WETH"], "day")
