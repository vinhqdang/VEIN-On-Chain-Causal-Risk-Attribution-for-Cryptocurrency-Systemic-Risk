"""Minimal Dune Analytics SQL client with on-disk result caching.

The free Dune plan meters execution credits, so every query result is cached to
``data_cache/dune_<sha1>.json`` keyed by the SQL text. Re-runs read the cache and
never re-execute. This is what gives VEIN its "SQL over the decoded on-chain
ledger" capability (the BigQuery substitute described to the user).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)
API = "https://api.dune.com/api/v1"


def _key() -> str:
    k = os.environ.get("DUNE_API_KEY")
    if not k:
        raise RuntimeError("DUNE_API_KEY not set (source secrets.env)")
    return k


def _req(method: str, url: str, body: dict | None = None, retries: int = 5) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Dune-API-Key", _key())
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 502, 503, 504):
                time.sleep(2 ** i + 1)   # backoff on rate-limit / transient
                continue
            raise
    raise RuntimeError(f"Dune request failed after {retries} tries: {last}")


def run_sql(sql: str, name: str = "vein_query", poll_s: float = 5.0,
            max_polls: int = 180, refresh: bool = False) -> list[dict]:
    """Execute SQL against Dune and return rows. Cached by SQL hash."""
    h = hashlib.sha1(sql.encode()).hexdigest()[:16]
    cache = CACHE_DIR / f"dune_{h}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())["rows"]

    time.sleep(1.0)   # politeness spacing to respect free-tier rate limits
    created = _req("POST", f"{API}/query",
                   {"name": f"{name}_{h}", "query_sql": sql, "is_private": False})
    qid = created.get("query_id")
    if qid is None:
        raise RuntimeError(f"Dune query creation failed: {created}")

    ex = _req("POST", f"{API}/query/{qid}/execute", {})
    exec_id = ex.get("execution_id")
    if exec_id is None:
        raise RuntimeError(f"Dune execute failed: {ex}")

    for _ in range(max_polls):
        st = _req("GET", f"{API}/execution/{exec_id}/status")
        if st.get("is_execution_finished"):
            if st.get("state") != "QUERY_STATE_COMPLETED":
                raise RuntimeError(f"Dune execution failed: {st}")
            break
        time.sleep(poll_s)
    else:
        raise RuntimeError("Dune execution timed out")

    res = _req("GET", f"{API}/execution/{exec_id}/results")
    rows = res.get("result", {}).get("rows", [])
    cache.write_text(json.dumps({"sql": sql, "query_id": qid, "rows": rows}))
    return rows
