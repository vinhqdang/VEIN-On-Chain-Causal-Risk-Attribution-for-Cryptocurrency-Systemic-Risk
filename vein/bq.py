"""BigQuery client, cost guard, cache and ledger (BQ_SPEC section 3).

Every query is dry-run first and checked against three caps (per query, cumulative
hard cap, calendar-month cap) before it is billed. Every billed query is appended to
a ledger under data_cache/, and results are cached by SQL hash so re-runs bill
nothing. google-cloud libraries are imported inside functions only, so importing
this module (and running the offline tests) never requires them.
"""
from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from . import config

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
LEDGER = CACHE_DIR / "bq_ledger.json"
GIB = 2 ** 30


class BudgetError(RuntimeError):
    """Raised before a query is billed when it would exceed a cap."""


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------
def get_client():
    """Build a BigQuery client from GCP_SA_KEY_B64 (base64 service-account JSON)."""
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("GCP_SA_KEY_B64")
    if not raw:
        raise RuntimeError("GCP_SA_KEY_B64 not set: no BigQuery credentials in this environment")
    info = json.loads(base64.b64decode(raw))
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    project = os.environ.get("GCP_PROJECT_ID") or info["project_id"]
    # Table ids built by bq_sql.extract_table_ids read GCP_PROJECT_ID, so pin it.
    os.environ.setdefault("GCP_PROJECT_ID", project)
    return bigquery.Client(project=project, credentials=creds, location=config.BQ_LOCATION)


def _project(client) -> str:
    return client.project


def _job_config(**kw):
    """QueryJobConfig when the library is installed, otherwise a stand-in with the
    same attribute names (used only by tests that pass a fake client)."""
    try:
        from google.cloud import bigquery
        cfg = bigquery.QueryJobConfig()
    except ImportError:  # pragma: no cover - exercised in offline environments
        cfg = SimpleNamespace()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def sql_hash(sql: str) -> str:
    import hashlib
    return hashlib.sha1(sql.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ledger and budget
# ---------------------------------------------------------------------------
def _empty_ledger() -> dict:
    return {"version": 1, "cumulative_billed_bytes": 0, "by_month": {}, "entries": []}


def load_ledger(path=None) -> dict:
    path = Path(path or LEDGER)
    if not path.exists():
        return _empty_ledger()
    return json.loads(path.read_text())


def save_ledger(ledger: dict, path=None) -> None:
    path = Path(path or LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=1))
    os.replace(tmp, path)


def check_budget(est_bytes, ledger, max_gib_per_query, hard_cap_gib, monthly_cap_gib,
                 month) -> None:
    """Pure guard: raises BudgetError if billing est_bytes would breach a cap."""
    est_gib = est_bytes / GIB
    if est_gib > max_gib_per_query:
        raise BudgetError(f"query estimate {est_gib:.2f} GiB exceeds per-query cap "
                          f"{max_gib_per_query:.2f} GiB")
    cum_gib = ledger.get("cumulative_billed_bytes", 0) / GIB
    if cum_gib + est_gib > hard_cap_gib:
        raise BudgetError(f"cumulative {cum_gib:.2f} GiB + estimate {est_gib:.2f} GiB "
                          f"exceeds hard cap {hard_cap_gib:.2f} GiB")
    month_gib = ledger.get("by_month", {}).get(month, 0) / GIB
    if month_gib + est_gib > monthly_cap_gib:
        raise BudgetError(f"{month} billed {month_gib:.2f} GiB + estimate {est_gib:.2f} GiB "
                          f"exceeds monthly cap {monthly_cap_gib:.2f} GiB")


def _month() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _record(entry: dict, billed: int, path=None) -> None:
    ledger = load_ledger(path)
    ledger["entries"].append(entry)
    if billed:
        ledger["cumulative_billed_bytes"] = ledger.get("cumulative_billed_bytes", 0) + billed
        m = _month()
        ledger.setdefault("by_month", {})[m] = ledger["by_month"].get(m, 0) + billed
    save_ledger(ledger, path)


def dry_run_bytes(sql: str, client=None) -> int:
    """Bytes BigQuery would bill for sql (no billing). Recorded as a dry_run entry."""
    client = client or get_client()
    cfg = _job_config(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=cfg)
    est = int(job.total_bytes_processed or 0)
    _record({"ts": _now(), "name": "dry_run", "sql_hash": sql_hash(sql), "kind": "dry_run",
             "est_bytes": est, "billed_bytes": 0, "cache_hit": False, "job_id": None}, 0)
    return est


def _cache_path(h: str) -> Path:
    return CACHE_DIR / f"bq_{h}.json"


def _jsonable_value(v):
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v.astimezone(dt.timezone.utc).isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex()
    return v


def _row_dict(row) -> dict:
    items = row.items() if hasattr(row, "items") else dict(row).items()
    return {k: _jsonable_value(v) for k, v in items}


def _cap_bytes(max_gib, ledger) -> int:
    cap_gib = min(max_gib or config.BQ_MAX_GIB_PER_QUERY,
                  config.BQ_HARD_CAP_GIB - ledger.get("cumulative_billed_bytes", 0) / GIB)
    return max(10 * 2 ** 20, int(cap_gib * GIB))


def run_sql(sql: str, name: str = "vein_query", refresh: bool = False, max_gib=None,
            client=None) -> list[dict]:
    """Dry-run, guard, execute and cache one query. Returns rows as plain dicts."""
    h = sql_hash(sql)
    cache = _cache_path(h)
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())["rows"]   # cache hit: no client, no bytes

    client = client or get_client()
    est = dry_run_bytes(sql, client)
    ledger = load_ledger()
    check_budget(est, ledger, max_gib or config.BQ_MAX_GIB_PER_QUERY,
                 config.BQ_HARD_CAP_GIB, config.BQ_MONTHLY_CAP_GIB, _month())

    cfg = _job_config(use_query_cache=True, maximum_bytes_billed=_cap_bytes(max_gib, ledger))
    job = client.query(sql, job_config=cfg)
    rows = [_row_dict(r) for r in job.result(page_size=50000)]
    billed = int(job.total_bytes_billed or 0)
    _record({"ts": _now(), "name": name, "sql_hash": h, "kind": "query", "est_bytes": est,
             "billed_bytes": billed, "cache_hit": bool(getattr(job, "cache_hit", False)),
             "job_id": job.job_id}, billed)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"sql": sql, "name": name, "job_id": job.job_id,
                                 "billed_bytes": billed, "rows": rows}))
    return rows


def table_id(client, table: str) -> str:
    return table if table.count(".") == 2 else f"{_project(client)}.{config.BQ_DATASET}.{table}"


def dataset_storage_bytes(client=None) -> int:
    client = client or get_client()
    total = 0
    for item in client.list_tables(f"{_project(client)}.{config.BQ_DATASET}"):
        total += int(client.get_table(item.reference).num_bytes or 0)
    return total


def ensure_dataset(client=None) -> None:
    from google.cloud import bigquery
    client = client or get_client()
    ds = bigquery.Dataset(f"{_project(client)}.{config.BQ_DATASET}")
    ds.location = config.BQ_LOCATION
    client.create_dataset(ds, exists_ok=True)


def _marker(table: str) -> Path:
    return CACHE_DIR / f"bq_mat_{table.split('.')[-1]}.json"


def materialize(sql: str, table: str, name: str = "vein_materialize", refresh: bool = False,
                max_gib=None, client=None) -> dict:
    """Run sql into a (non-partitioned) table, reusing it when its description carries
    the same sql hash. Returns the marker dict {table, sql_hash, num_rows, num_bytes, created}."""
    from google.api_core.exceptions import NotFound

    client = client or get_client()
    fq = table_id(client, table)
    h = sql_hash(sql)
    marker_path = _marker(table)
    prev = json.loads(marker_path.read_text()) if marker_path.exists() else None

    if not refresh:
        # Reuse even when the local marker is lost (fresh checkout, cleared data_cache):
        # the table's own description carries the sql hash, so nothing is rebilled.
        try:
            t = client.get_table(fq)
            if f"sql_hash={h}" in (t.description or ""):
                if prev and prev.get("sql_hash") == h:
                    return prev
                marker = {"table": fq, "sql_hash": h, "num_rows": int(t.num_rows or 0),
                          "num_bytes": int(t.num_bytes or 0), "created": _now()}
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                marker_path.write_text(json.dumps(marker, indent=1))
                return marker
        except NotFound:
            pass

    # Storage guard: the new table is assumed to be as large as the previous build.
    storage = dataset_storage_bytes(client)
    expected_new = int(prev.get("num_bytes", 0)) if prev else 0
    if storage + expected_new > config.BQ_STORAGE_CAP_GIB * GIB:
        raise BudgetError(f"dataset storage {storage / GIB:.2f} GiB + expected {expected_new / GIB:.2f} GiB "
                          f"exceeds storage cap {config.BQ_STORAGE_CAP_GIB:.1f} GiB")

    est = dry_run_bytes(sql, client)
    ledger = load_ledger()
    check_budget(est, ledger, max_gib or config.BQ_MAX_GIB_PER_QUERY,
                 config.BQ_HARD_CAP_GIB, config.BQ_MONTHLY_CAP_GIB, _month())
    cfg = _job_config(destination=fq, write_disposition="WRITE_TRUNCATE",
                      use_query_cache=False, maximum_bytes_billed=_cap_bytes(max_gib, ledger))
    job = client.query(sql, job_config=cfg)
    job.result()
    billed = int(job.total_bytes_billed or 0)
    t = client.get_table(fq)
    t.description = f"vein sql_hash={h}"
    client.update_table(t, ["description"])
    _record({"ts": _now(), "name": name, "sql_hash": h, "kind": "materialize", "est_bytes": est,
             "billed_bytes": billed, "cache_hit": False, "job_id": job.job_id, "table": fq},
            billed)

    marker = {"table": fq, "sql_hash": h, "num_rows": int(t.num_rows or 0),
              "num_bytes": int(t.num_bytes or 0), "created": _now()}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker, indent=1))
    after = dataset_storage_bytes(client)
    if after > config.BQ_STORAGE_CAP_GIB * GIB:
        print(f"WARNING: dataset storage {after / GIB:.2f} GiB exceeds cap "
              f"{config.BQ_STORAGE_CAP_GIB:.1f} GiB after building {table}", file=sys.stderr)
    return marker


def upload_dataframe(df, table: str, schema: list[tuple[str, str]], client=None) -> str:
    """Load a pandas frame into table (WRITE_TRUNCATE). schema = [(column, BQ type)]."""
    from google.cloud import bigquery

    client = client or get_client()
    ensure_dataset(client)
    fq = table_id(client, table)
    fields = [bigquery.SchemaField(c, t) for c, t in schema]
    cfg = bigquery.LoadJobConfig(schema=fields, write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df[[c for c, _ in schema]], fq, job_config=cfg).result()
    return fq
