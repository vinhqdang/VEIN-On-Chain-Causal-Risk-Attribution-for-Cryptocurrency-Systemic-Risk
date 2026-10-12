"""Pure SQL builders for the BigQuery (crypto_ethereum) data layer.

Nothing here touches the network or imports google-cloud libraries, so every
query text can be unit-tested offline. Stage 1 (extract_sql) reduces the raw
token_transfers table to per-bucket, per-token, per-address-pair sums. Stage 2
(flow_sql, sweep_sql, coverage_sql, edges_sql, usde_daily_sql) joins those
extracts to the label table. Every stage-2 query starts with a header comment
that records the extract hashes and the label fingerprint, so a cached result
can never be attributed to a different label epoch.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from . import config

NULL_ADDR_SQL = "FROM_HEX(REPEAT('0',40))"


def _d(x) -> dt.date:
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x)[:10])


def _ts(d: dt.date) -> str:
    return f"TIMESTAMP('{d.isoformat()} 00:00:00+00')"


def _bucket_kw(bucket: str) -> str:
    if bucket == "hour":
        return "HOUR"
    if bucket == "day":
        return "DAY"
    raise ValueError(f"unknown bucket {bucket!r}")


def hexlist(addrs) -> str:
    """Quoted, lower-cased address literals for an IN (...) list."""
    return ", ".join(f"'{a.lower()}'" for a in addrs)


def chunks(start, end, chunk_days: int) -> list[tuple[dt.date, dt.date]]:
    """Contiguous half-open [cstart, cend) chunks covering [start, end)."""
    s, e = _d(start), _d(end)
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    out = []
    cur = s
    while cur < e:
        nxt = min(e, cur + dt.timedelta(days=chunk_days))
        out.append((cur, nxt))
        cur = nxt
    return out


def _project() -> str:
    return os.environ.get("GCP_PROJECT_ID") or "PROJECT"


def extract_table_ids(key: str) -> list[str]:
    spec = config.BQ_EXTRACTS[key]
    n = len(chunks(spec["start"], spec["end"], spec["chunk_days"]))
    proj = _project()
    return [f"{proj}.{config.BQ_DATASET}.x_{key}_c{i:02d}" for i in range(n)]


def extract_sql(key: str, cstart, cend) -> str:
    spec = config.BQ_EXTRACTS[key]
    B = _bucket_kw(spec["bucket"])
    cstart, cend = _d(cstart), _d(cend)
    rows = []
    for sym in spec["tokens"]:
        rows.append(f"STRUCT('{config.TOKENS[sym].lower()}' AS addr, '{sym}' AS sym, "
                    f"{config.TOKEN_DECIMALS[sym]} AS dec)")
    tok_rows = ", ".join(rows)
    hexes = hexlist(config.TOKENS[s] for s in spec["tokens"])
    return f"""-- vein:extract key={key} chunk={cstart.isoformat()}..{cend.isoformat()}
WITH tok AS (SELECT * FROM UNNEST([{tok_rows}]))
SELECT TIMESTAMP_TRUNC(t.block_timestamp, {B}) AS bucket, tok.sym AS token,
  FROM_HEX(SUBSTR(t.from_address, 3)) AS from_a, FROM_HEX(SUBSTR(t.to_address, 3)) AS to_a,
  SUM(SAFE_CAST(t.value AS FLOAT64) / POW(10, tok.dec)) AS amount, COUNT(*) AS n_tx
FROM `{config.BQ_SOURCE}.token_transfers` AS t
JOIN tok ON t.token_address = tok.addr
WHERE t.block_timestamp >= {_ts(cstart)}
  AND t.block_timestamp <  {_ts(cend)}
  AND t.token_address IN ({hexes})
  AND t.value != '0'
GROUP BY bucket, token, from_a, to_a"""


def union_sql(tables) -> str:
    if not tables:
        raise ValueError("no extract tables")
    return " UNION ALL ".join(
        f"SELECT bucket, token, from_a, to_a, amount, n_tx FROM `{t}`" for t in tables)


def _window(start, end, col: str = "x.bucket") -> str:
    return f"{col} >= {_ts(_d(start))} AND {col} < {_ts(_d(end))}"


def _header(kind: str, extract_hashes, labels_fp: str, extra: str = "") -> str:
    h = ",".join(extract_hashes)
    tail = f" {extra}" if extra else ""
    return f"-- vein:{kind} extract={h} labels={labels_fp}{tail}"


def _x_cte(tables) -> str:
    return f"x AS ({union_sql(tables)})"


def flow_sql(tables, labels_table, labels_fp, extract_hashes, start, end,
             tokens, bucket) -> str:
    B = _bucket_kw(bucket)
    syms = ", ".join(f"'{t}'" for t in tokens)
    return f"""{_header("flows", extract_hashes, labels_fp)}
WITH {_x_cte(tables)}, lab AS (SELECT address, entity, src FROM `{labels_table}`)
SELECT TIMESTAMP_TRUNC(x.bucket, {B}) AS day, x.token AS token,
  COALESCE(lf.entity,'retail') AS from_entity, COALESCE(lt.entity,'retail') AS to_entity,
  COALESCE(lf.src,'retail') AS from_src, COALESCE(lt.src,'retail') AS to_src,
  SUM(x.amount) AS volume, SUM(x.n_tx) AS n_tx
FROM x LEFT JOIN lab AS lf ON x.from_a = lf.address LEFT JOIN lab AS lt ON x.to_a = lt.address
WHERE {_window(start, end)}
  AND x.token IN ({syms}) AND (lf.entity IS NOT NULL OR lt.entity IS NOT NULL)
GROUP BY day, token, from_entity, to_entity, from_src, to_src ORDER BY day"""


def coverage_sql(tables, labels_table, labels_fp, extract_hashes, start, end) -> str:
    return f"""{_header("coverage", extract_hashes, labels_fp)}
WITH {_x_cte(tables)}, lab AS (SELECT address, entity, src FROM `{labels_table}`)
SELECT x.token, COALESCE(lf.src,'none') AS from_src, COALESCE(lt.src,'none') AS to_src,
  (x.from_a = {NULL_ADDR_SQL} OR x.to_a = {NULL_ADDR_SQL}) AS is_mint_burn,
  (lf.entity IS NOT NULL AND lf.entity = lt.entity) AS same_entity,
  SUM(x.amount) AS amount, SUM(x.n_tx) AS n_tx, COUNT(*) AS n_pairs
FROM x LEFT JOIN lab lf ON x.from_a=lf.address LEFT JOIN lab lt ON x.to_a=lt.address
WHERE {_window(start, end)} GROUP BY 1,2,3,4,5"""


def lido_series_sql(tables, extract_hashes, start, end) -> str:
    """Hourly stETH mints (from the zero address), transfers into the Lido Withdrawal Queue
    and gross stETH volume. Mints and queue deposits are the redemption-pressure signal."""
    from . import config as _cfg
    queue = _cfg.PROTOCOL_ADDRESSES["lido_withdrawal_queue"].lower()
    return f"""{_header("lido_series", extract_hashes, "none")}
WITH {_x_cte(tables)}
SELECT x.bucket AS hour,
  SUM(IF(x.from_a = {NULL_ADDR_SQL}, x.amount, 0)) AS steth_mint,
  SUM(IF(x.to_a = FROM_HEX('{queue[2:]}'), x.amount, 0)) AS steth_wq_in,
  SUM(x.amount) AS steth_gross, SUM(x.n_tx) AS n_tx
FROM x WHERE x.token='stETH' AND {_window(start, end)} GROUP BY 1 ORDER BY 1"""


def sweep_keys(epoch: str) -> list[str]:
    """Extracts of a label epoch that feed Tier-0 sweep detection (sweeps flag not False)."""
    return [k for k, v in config.BQ_EXTRACTS.items()
            if v["epoch"] == epoch and v.get("sweeps", True)]


def edges_sql(tables, labels_table, labels_fp, extract_hashes, token, start, end) -> str:
    return f"""{_header("edges", extract_hashes, labels_fp)}
WITH {_x_cte(tables)},
lab AS (SELECT address, entity FROM `{labels_table}` WHERE src IN ('seed','label') AND etype='CEX')
SELECT CONCAT('0x', TO_HEX(x.from_a)) AS from_addr, CONCAT('0x', TO_HEX(x.to_a)) AS to_addr,
  SUM(x.amount) AS volume, SUM(x.n_tx) AS n_tx, MAX(lf.entity) AS from_cex, MAX(lt.entity) AS to_cex
FROM x LEFT JOIN lab lf ON x.from_a=lf.address LEFT JOIN lab lt ON x.to_a=lt.address
WHERE x.token='{token}' AND {_window(start, end)} GROUP BY 1,2"""


def usde_daily_sql(tables, extract_hashes, start, end) -> str:
    return f"""{_header("usde_daily", extract_hashes, "none")}
WITH {_x_cte(tables)}
SELECT TIMESTAMP_TRUNC(bucket, DAY) AS day, SUM(amount) AS usde, SUM(n_tx) AS n_tx
FROM x WHERE token='USDe' AND {_window(start, end, "bucket")} GROUP BY 1 ORDER BY 1"""


def sender_usd_sql(tables, extract_hashes, usd_per_unit: dict, start, end) -> str:
    """USD sent per address over a window (denominator for Tier-0 recall)."""
    px_rows = ",\n  ".join(f"STRUCT('{tk}' AS token, {float(u)!r} AS u)"
                           for tk, u in usd_per_unit.items())
    return f"""{_header("senders", extract_hashes, "none")}
WITH {_x_cte(tables)},
px AS (SELECT * FROM UNNEST([{px_rows}]))
SELECT CONCAT('0x', TO_HEX(x.from_a)) AS address, SUM(x.amount * px.u) AS out_usd, SUM(x.n_tx) AS n_tx
FROM x JOIN px USING (token)
WHERE {_window(start, end)} AND x.from_a != {NULL_ADDR_SQL}
GROUP BY 1"""


def sweep_sql(tables, labels_table, labels_fp, extract_hashes, usd_per_unit: dict,
              params: dict) -> str:
    """Tier-0 deposit-sweep detection (algorithm: BQ_SPEC section 6)."""
    px_rows = ",\n  ".join(f"STRUCT('{tk}' AS token, {float(u)!r} AS u)"
                           for tk, u in usd_per_unit.items())
    p = params
    pjson = json.dumps(p, sort_keys=True)
    return f"""{_header("sweeps", extract_hashes, labels_fp, f"params={pjson}")}
WITH {_x_cte(tables)},
px AS (SELECT * FROM UNNEST([{px_rows}])),
xu AS (SELECT x.bucket, x.from_a, x.to_a, x.amount * px.u AS usd, x.n_tx FROM x JOIN px USING (token)),
hot   AS (SELECT address, entity FROM `{labels_table}` WHERE etype='CEX' AND src IN ('seed','label')),
known AS (SELECT address FROM `{labels_table}` WHERE src IN ('seed','label')),
outs AS (SELECT xu.from_a AS a, xu.to_a AS b, h.entity AS hot_entity, xu.bucket, xu.usd, xu.n_tx
  FROM xu LEFT JOIN hot h ON xu.to_a = h.address LEFT JOIN known k ON xu.from_a = k.address
  WHERE k.address IS NULL AND xu.from_a != {NULL_ADDR_SQL}),
out_stats AS (SELECT a, SUM(usd) AS out_usd, COUNT(DISTINCT b) AS out_cp FROM outs GROUP BY a),
out_by_x AS (SELECT a, hot_entity, SUM(usd) AS to_x_usd, SUM(n_tx) AS n_sweeps FROM outs WHERE hot_entity IS NOT NULL GROUP BY a, hot_entity),
ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY a ORDER BY to_x_usd DESC, hot_entity) AS rk,
  SUM(to_x_usd) OVER (PARTITION BY a) AS to_any_hot_usd FROM out_by_x),
ins AS (SELECT xu.to_a AS a, xu.from_a AS s, h.entity AS from_hot, xu.bucket, xu.usd FROM xu LEFT JOIN hot h ON xu.from_a = h.address),
in_stats AS (SELECT a, SUM(usd) AS in_usd, COUNT(DISTINCT IF(from_hot IS NULL, s, NULL)) AS n_senders_nonhot,
  SUM(IF(from_hot IS NOT NULL, usd, 0)) AS in_from_hot_usd FROM ins GROUP BY a),
sw  AS (SELECT a, hot_entity, bucket, SUM(usd) AS usd FROM outs WHERE hot_entity IS NOT NULL GROUP BY 1,2,3),
inb AS (SELECT DISTINCT a, bucket FROM ins WHERE from_hot IS NULL),
timed AS (SELECT sw.a, sw.hot_entity, sw.bucket, ANY_VALUE(sw.usd) AS usd FROM sw JOIN inb ON inb.a = sw.a
  AND inb.bucket <= sw.bucket AND inb.bucket >= TIMESTAMP_SUB(sw.bucket, INTERVAL {int(p["h_hours"])} HOUR) GROUP BY 1,2,3),
timed_stats AS (SELECT a, hot_entity, SUM(usd) AS timed_usd FROM timed GROUP BY 1,2)
SELECT CONCAT('0x', TO_HEX(r.a)) AS address, r.hot_entity AS entity, r.to_x_usd, r.n_sweeps,
  o.out_usd, o.out_cp, i.in_usd, i.n_senders_nonhot, i.in_from_hot_usd,
  COALESCE(t.timed_usd, 0) AS timed_usd, r.to_x_usd / o.out_usd AS sweep_ratio
FROM ranked r JOIN out_stats o USING (a) JOIN in_stats i USING (a)
LEFT JOIN timed_stats t ON t.a = r.a AND t.hot_entity = r.hot_entity
WHERE r.rk = 1 AND r.to_x_usd >= {p["min_sweep_usd"]} AND r.to_x_usd / o.out_usd >= {p["tau"]}
  AND (r.to_any_hot_usd - r.to_x_usd) / o.out_usd <= {p["max_other_hot_share"]}
  AND o.out_cp <= {p["max_out_cp"]} AND i.n_senders_nonhot >= {p["k_in"]}
  AND SAFE_DIVIDE(o.out_usd, i.in_usd) BETWEEN {p["min_fwd"]} AND {p["max_fwd"]}
  AND SAFE_DIVIDE(i.in_from_hot_usd, i.in_usd) <= {p["max_in_from_hot_share"]}
  AND COALESCE(t.timed_usd, 0) / r.to_x_usd >= {p["min_timed_share"]}
ORDER BY r.to_x_usd DESC"""


def select_extract(start, end, tokens, bucket: str) -> str:
    """Name of the extract that serves a request, or ValueError.

    An extract serves a request if its span contains [start, end), it holds every
    requested token, and its bucket matches (an hourly extract can serve a daily
    request, since flows are re-bucketed in SQL)."""
    s, e = _d(start), _d(end)
    want = set(tokens)
    for key, spec in config.BQ_EXTRACTS.items():
        if not (spec["start"] <= s and e <= spec["end"]):
            continue
        if not want <= set(spec["tokens"]):
            continue
        if not (spec["bucket"] == bucket or spec["bucket"] == "hour"):
            continue
        return key
    raise ValueError(f"no BigQuery extract covers {s}..{e} tokens={sorted(want)} bucket={bucket}")
