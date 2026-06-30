"""Build the observed on-chain flow graph G (algorithm.md Sections 2.2-2.3).

This is the heart of VEIN: the causal parent set pa(i) is *read off the ledger*,
not statistically inferred. We aggregate real ERC-20 transfers (via Dune SQL over
the decoded `erc20_ethereum.evt_Transfer` table) into daily directed,
dollar-weighted flows between resolved entities. Any address not in our
high-precision label set collapses into the aggregate 'retail' node (Section 2.2).

Edges carry a resolution-confidence score: 1.0 for labeled<->labeled flows
(both endpoints publicly attributed), lower for flows touching 'retail'.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from . import config
from .dune import run_sql

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"

# Stablecoins/LSTs are ~1:1 in USD for flow-volume purposes; ETH-denominated
# tokens are scaled by a representative price below. We treat stablecoin units
# as USD and wBETH/WETH via an approximate ETH price applied in Python.
FLOW_TOKENS = ["USDe", "sUSDe", "USDC", "USDT", "wBETH", "WETH"]
# Ethena/Binance systemic core — used for the long historical scan (cheaper than
# pulling 2.5 years of USDC/USDT, which have orders-of-magnitude more transfers).
CORE_TOKENS = ["USDe", "sUSDe", "wBETH"]
USD_PER_UNIT_DECIMALS = 18  # all listed tokens use 18 decimals except USDC/USDT (6)
DECIMALS = {"USDe": 18, "sUSDe": 18, "USDC": 6, "USDT": 6, "wBETH": 18, "WETH": 18}


def _addr_values_cte() -> str:
    """Build a DuneSQL VALUES mapping address -> entity name."""
    rows = []
    for entity, meta in config.ENTITIES.items():
        for a in meta["addresses"]:
            rows.append(f"({a}, '{entity}')")
    return ",\n        ".join(rows)


def _token_values_cte(tokens: list[str]) -> str:
    rows = []
    for tk in tokens:
        rows.append(f"({config.TOKENS[tk]}, '{tk}', {DECIMALS[tk]})")
    return ",\n        ".join(rows)


def build_flow_sql(start: dt.date, end: dt.date, tokens: list[str]) -> str:
    """SQL: daily directed flow volume (token units) between resolved entities.

    Unlabeled endpoints map to 'retail'. Only transfers touching at least one
    labeled address are scanned (keeps the scan/credits small)."""
    return f"""
WITH ent(addr, name) AS (
    VALUES
        {_addr_values_cte()}
),
tok(addr, sym, dec) AS (
    VALUES
        {_token_values_cte(tokens)}
),
xfer AS (
    SELECT
        date_trunc('day', t.evt_block_time)        AS day,
        tok.sym                                     AS token,
        COALESCE(ef.name, 'retail')                 AS from_entity,
        COALESCE(et.name, 'retail')                 AS to_entity,
        t.value / power(10, tok.dec)                AS amount
    FROM erc20_ethereum.evt_Transfer t
    JOIN tok ON t.contract_address = tok.addr
    LEFT JOIN ent ef ON t."from" = ef.addr
    LEFT JOIN ent et ON t.to = et.addr
    WHERE t.evt_block_time >= TIMESTAMP '{start}'
      AND t.evt_block_time <  TIMESTAMP '{end}'
      AND (ef.name IS NOT NULL OR et.name IS NOT NULL)   -- at least one labeled side
)
SELECT day, token, from_entity, to_entity,
       sum(amount) AS volume, count(*) AS n_tx
FROM xfer
WHERE NOT (from_entity = 'retail' AND to_entity = 'retail')
GROUP BY 1, 2, 3, 4
ORDER BY 1
"""


def load_flows(start: dt.date, end: dt.date, eth_price: pd.Series | None = None,
               tokens: list[str] | None = None) -> pd.DataFrame:
    """Return daily directed inter-entity flows in approximate USD.

    Columns: day, from_entity, to_entity, usd_volume, n_tx.
    """
    tokens = tokens or FLOW_TOKENS
    rows = run_sql(build_flow_sql(start, end, tokens), name="vein_flows")
    if not rows:
        return pd.DataFrame(columns=["day", "from_entity", "to_entity", "usd_volume", "n_tx"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"]).dt.tz_localize(None).dt.normalize()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["n_tx"] = pd.to_numeric(df["n_tx"], errors="coerce").fillna(0).astype(int)

    # Convert ETH-denominated tokens to USD using a daily ETH price if provided.
    eth_tokens = {"wBETH", "WETH"}
    if eth_price is not None and not eth_price.empty:
        ep = eth_price.copy()
        ep.index = pd.to_datetime(ep.index).normalize()
        df["eth_px"] = df["day"].map(ep).ffill().bfill().fillna(ep.mean())
    else:
        df["eth_px"] = 3000.0
    df["usd_volume"] = df.apply(
        lambda r: r["volume"] * (r["eth_px"] if r["token"] in eth_tokens else 1.0), axis=1)

    agg = (df.groupby(["day", "from_entity", "to_entity"], as_index=False)
             .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum")))
    return agg


def build_graph(flows: pd.DataFrame, min_usd: float = 1e6) -> dict:
    """Aggregate the flow panel into a directed graph with edge weights/confidence.

    Returns dict with 'nodes', 'edges' (list of dicts), and 'parents' map.
    An edge i->j exists if cumulative observed flow from i to j exceeds min_usd.
    Confidence = 1.0 if both endpoints labeled, 0.5 if one side is 'retail'.
    """
    totals = (flows.groupby(["from_entity", "to_entity"], as_index=False)
                    .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum")))
    nodes = sorted(set(totals.from_entity) | set(totals.to_entity))
    edges = []
    parents: dict[str, list[str]] = {n: [] for n in nodes}
    for _, r in totals.iterrows():
        i, j = r.from_entity, r.to_entity
        if i == j or r.usd_volume < min_usd:
            continue
        conf = 0.5 if ("retail" in (i, j)) else 1.0
        edges.append({"from": i, "to": j, "usd_volume": float(r.usd_volume),
                      "n_tx": int(r.n_tx), "confidence": conf})
        parents[j].append(i)
    return {"nodes": nodes, "edges": edges, "parents": parents}
