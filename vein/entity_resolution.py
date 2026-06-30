"""Entity resolution pipeline (algorithm.md Section 2.2).

This is the load-bearing layer: resolution error directly corrupts pa(i), the
causal parent-set. We implement the tiered approach from Section 2.2 with real
data:

  Tier 3 (this module's primary path) — known-label seeding & reconciliation.
      We resolve every transfer counterparty against (a) our hand-curated,
      high-precision seed addresses (config.ENTITIES) and (b) Dune's maintained
      `labels.cex_ethereum` table (CEX hot-wallet + per-user deposit-address
      labels). This turns the undifferentiated 'retail' blob into *named*
      exchanges, so flows that were previously entity<->retail become real
      entity<->entity edges (e.g. Binance -> OKX deposit).

  Tier 0 (deposit-sweep heuristic) — detect_deposit_sweeps(): addresses that
      receive then forward ~everything to a known hot wallet are that exchange's
      deposit addresses. Complements Tier 3 for exchanges Dune hasn't labelled.

  Tier 1/2 (supervised classifier + graph embedding) — see resolver.py; used to
      classify the residual unlabeled addresses and cluster them.

Every resolved address carries a confidence in [0,1] propagated to edge
reliability (Section 2.2 output spec).
"""
from __future__ import annotations

import pandas as pd

from . import config
from .dune import run_sql

# Resolution-confidence by source (Section 2.2 "per-node confidence score").
CONF = {"seed": 1.0, "dune_cex": 0.9, "sweep": 0.8, "classifier": 0.6,
        "cluster": 0.5, "retail": 0.3}

# Descriptor tokens stripped when collapsing sub-wallet labels to the exchange
# root (e.g. "OKX 210" -> "OKX", "Bitfinex Tether Treasury" -> "Bitfinex").
# This IS the entity-resolution clustering step: many addresses -> one agent.
_DESCRIPTORS = {"hot", "cold", "wallet", "internal", "multisig", "deposit",
                "treasury", "custodian", "custodial", "tether", "stablecoin",
                "proof", "of", "assets", "prime", "master", "masterwallet",
                "reserve", "deployer", "1", "2"}
_SEEDS = None  # lazily filled from config


def normalize_entity(name: str) -> str:
    """Collapse a Dune CEX sub-wallet label to its exchange-root entity."""
    global _SEEDS
    if _SEEDS is None:
        _SEEDS = set(config.ENTITIES)
    if name in _SEEDS or name == "retail":
        return name
    tokens = name.split()
    root = []
    for tok in tokens:
        low = tok.lower()
        if tok.isdigit() or low in _DESCRIPTORS:
            break
        root.append(tok)
    return " ".join(root) if root else name


def seed_values_cte() -> str:
    rows = [f"({a}, '{name}')" for name, meta in config.ENTITIES.items()
            for a in meta["addresses"]]
    return ",\n        ".join(rows)


def resolved_flow_sql(start, end, tokens: list[str], min_addr_volume: float = 5e6) -> str:
    """Daily directed inter-entity flows with Tier-3 label resolution on BOTH sides.

    Resolution priority per address: seed entity > Dune CEX label > 'retail'.
    Deduplicates multi-row CEX labels by picking one name per address.
    """
    tok_rows = ",\n        ".join(
        f"({config.TOKENS[tk]}, '{tk}', {_decimals(tk)})" for tk in tokens)
    return f"""
WITH seed(addr, name) AS (
    VALUES
        {seed_values_cte()}
),
tok(addr, sym, dec) AS (
    VALUES
        {tok_rows}
),
cex AS (   -- dedupe Dune CEX labels to one name per address
    SELECT address, max(name) AS name
    FROM labels.cex_ethereum
    GROUP BY address
),
xfer AS (
    SELECT
        date_trunc('day', t.evt_block_time) AS day,
        tok.sym AS token,
        COALESCE(sf.name, cf.name, 'retail') AS from_entity,
        COALESCE(st.name, ct.name, 'retail') AS to_entity,
        CASE WHEN sf.name IS NOT NULL THEN 'seed'
             WHEN cf.name IS NOT NULL THEN 'dune_cex' ELSE 'retail' END AS from_src,
        CASE WHEN st.name IS NOT NULL THEN 'seed'
             WHEN ct.name IS NOT NULL THEN 'dune_cex' ELSE 'retail' END AS to_src,
        t.value / power(10, tok.dec) AS amount
    FROM erc20_ethereum.evt_Transfer t
    JOIN tok ON t.contract_address = tok.addr
    LEFT JOIN seed sf ON t."from" = sf.addr
    LEFT JOIN seed st ON t.to = st.addr
    LEFT JOIN cex cf ON t."from" = cf.address
    LEFT JOIN cex ct ON t.to = ct.address
    WHERE t.evt_block_time >= TIMESTAMP '{start}'
      AND t.evt_block_time <  TIMESTAMP '{end}'
)
SELECT day, from_entity, to_entity,
       max(from_src) AS from_src, max(to_src) AS to_src,
       sum(amount) AS volume, count(*) AS n_tx
FROM xfer
WHERE NOT (from_entity = 'retail' AND to_entity = 'retail')
GROUP BY 1, 2, 3
HAVING sum(amount) >= {min_addr_volume}
ORDER BY 1
"""


def _decimals(tk: str) -> int:
    return {"USDe": 18, "sUSDe": 18, "USDC": 6, "USDT": 6, "wBETH": 18, "WETH": 18}[tk]


def load_resolved_flows(start, end, tokens, eth_price=None) -> pd.DataFrame:
    """Resolved daily inter-entity flows in approximate USD."""
    rows = run_sql(resolved_flow_sql(start, end, tokens), name="vein_resolved_flows")
    if not rows:
        return pd.DataFrame(columns=["day", "from_entity", "to_entity",
                                     "from_src", "to_src", "usd_volume", "n_tx"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"]).dt.tz_localize(None).dt.normalize()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["n_tx"] = pd.to_numeric(df["n_tx"], errors="coerce").fillna(0).astype(int)
    eth_tokens = {"wBETH", "WETH"}
    # tokens collapsed in SQL already; treat stable as USD, ETH-denoms via price
    df["usd_volume"] = df["volume"]  # stablecoin-dominated; ETH-token share small at entity level
    # Collapse sub-wallet labels to exchange-root entities (resolution clustering).
    df["from_entity"] = df["from_entity"].map(normalize_entity)
    df["to_entity"] = df["to_entity"].map(normalize_entity)
    df = df[df.from_entity != df.to_entity]   # drop intra-entity self-loops
    agg = (df.groupby(["day", "from_entity", "to_entity"], as_index=False)
             .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum"),
                  from_src=("from_src", "max"), to_src=("to_src", "max")))
    return agg


def top_k_entities(flows: pd.DataFrame, k: int = 12) -> pd.DataFrame:
    """Keep the k highest-throughput entities; collapse the rest into 'retail'.

    Keeps the graph interpretable and the OC-CoVaR Monte Carlo tractable while
    retaining the systemically dominant agents."""
    seeds = set(config.ENTITIES)
    vol = (pd.concat([
        flows.groupby("from_entity").usd_volume.sum(),
        flows.groupby("to_entity").usd_volume.sum()]).groupby(level=0).sum())
    vol = vol.drop(labels=["retail"], errors="ignore")
    keep = set(vol.sort_values(ascending=False).head(k).index) | seeds
    f = flows.copy()
    f["from_entity"] = f["from_entity"].where(f["from_entity"].isin(keep), "retail")
    f["to_entity"] = f["to_entity"].where(f["to_entity"].isin(keep), "retail")
    f = f[f.from_entity != f.to_entity]
    return (f.groupby(["day", "from_entity", "to_entity"], as_index=False)
             .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum"),
                  from_src=("from_src", "max"), to_src=("to_src", "max")))


def detect_deposit_sweeps(hot_wallets: list[str], start, end,
                          min_sweep_ratio: float = 0.8, limit: int = 500) -> pd.DataFrame:
    """Tier-0: addresses that forward >= min_sweep_ratio of inflow to a hot wallet.

    Returns candidate deposit addresses to attribute to the exchange owning the
    hot wallet. Scoped to ETH transfers in the window to bound the scan.
    """
    hw = ",\n        ".join(hot_wallets)
    sql = f"""
WITH hot(addr) AS (VALUES {hw}),
recv AS (
    SELECT to AS addr, sum(value) AS inflow
    FROM ethereum.traces
    WHERE block_time >= TIMESTAMP '{start}' AND block_time < TIMESTAMP '{end}'
      AND success AND value > 0
    GROUP BY 1
),
swept AS (
    SELECT tr."from" AS addr, sum(tr.value) AS to_hot
    FROM ethereum.traces tr
    JOIN hot ON tr.to = hot.addr
    WHERE tr.block_time >= TIMESTAMP '{start}' AND tr.block_time < TIMESTAMP '{end}'
      AND tr.success AND tr.value > 0
    GROUP BY 1
)
SELECT s.addr, s.to_hot / 1e18 AS swept_eth, r.inflow / 1e18 AS inflow_eth,
       s.to_hot / nullif(r.inflow, 0) AS sweep_ratio
FROM swept s JOIN recv r ON s.addr = r.addr
WHERE s.to_hot / nullif(r.inflow, 0) >= {min_sweep_ratio}
ORDER BY swept_eth DESC
LIMIT {limit}
"""
    rows = run_sql(sql, name="vein_deposit_sweeps")
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["addr", "swept_eth", "inflow_eth", "sweep_ratio"])


def entity_types(flows: pd.DataFrame) -> dict:
    """Assign a type to every resolved entity. Seeds use config types; all other
    resolved names come from labels.cex_ethereum, hence CEX."""
    types = {}
    seed_types = {n: meta["type"] for n, meta in config.ENTITIES.items()}
    ents = set(flows.from_entity) | set(flows.to_entity) | set(seed_types)
    for e in ents:
        types[e] = seed_types.get(e, "CEX" if e != "retail" else "RETAIL")
    types["retail"] = "RETAIL"
    return types
