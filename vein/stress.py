"""Stress-state operationalization S_{i,t} (algorithm.md Section 3.3).

Each entity type gets a type-appropriate daily stress proxy, higher = more
distressed. Proxies are built from real data:

  CEX (Binance)        : net on-chain outflow ratio (withdrawals - deposits,
                         normalized by a rolling reserve/flow estimate)
  Stablecoin (Ethena,  : peg deviation |price - $1| + net redemption outflow
   MakerSky)
  Lending (Aave)       : TVL drawdown (collateral/utilization stress proxy)
  LST (Lido)           : TVL drawdown + price drawdown

Returns a daily DataFrame indexed by date, columns = entity names.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def entity_flow_series(flows: pd.DataFrame, entities=None) -> dict[str, pd.DataFrame]:
    """Per-entity daily inflow / outflow / net-outflow USD series from the panel."""
    out = {}
    days = pd.DatetimeIndex(sorted(flows["day"].unique()))
    entities = entities if entities is not None else list(config.ENTITIES)
    for ent in entities:
        inflow = (flows[flows.to_entity == ent].groupby("day").usd_volume.sum()
                  .reindex(days, fill_value=0.0))
        outflow = (flows[flows.from_entity == ent].groupby("day").usd_volume.sum()
                   .reindex(days, fill_value=0.0))
        df = pd.DataFrame({"inflow": inflow, "outflow": outflow})
        df["net_outflow"] = df.outflow - df.inflow
        out[ent] = df
    return out


def _zscore(s: pd.Series, win: int = 30) -> pd.Series:
    mu = s.rolling(win, min_periods=5).mean()
    sd = s.rolling(win, min_periods=5).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def build_stress_panel(flows: pd.DataFrame,
                       prices: pd.DataFrame,
                       tvl: dict[str, pd.Series],
                       entity_types: dict[str, str] | None = None) -> pd.DataFrame:
    """Construct the daily stress panel S_{i,t} for every entity.

    All proxies are oriented so that larger = more stressed, then expressed as a
    rolling z-score so heterogeneous units are comparable in the SCM.

    entity_types maps every resolved entity to a type. Seed protocols use their
    price/TVL proxies; all other resolved entities are exchanges (CEX) and get
    the net-outflow-ratio proxy computed from on-chain flows.
    """
    if entity_types is None:
        entity_types = {n: m["type"] for n, m in config.ENTITIES.items()}
    idx = pd.DatetimeIndex(sorted(flows["day"].unique()))
    flow_ser = entity_flow_series(flows, entities=list(entity_types))
    cols = {}

    for ent, etype in entity_types.items():
        if ent == "retail":
            continue   # handled by the dedicated market-drawdown proxy below
        meta = config.ENTITIES.get(ent, {"type": etype, "coingecko_id": None})
        if etype in ("CEX", "RETAIL"):
            fs = flow_ser[ent]
            total = (fs.inflow + fs.outflow).rolling(30, min_periods=5).mean().replace(0, np.nan)
            ratio = (fs.net_outflow / total).fillna(0.0)   # >0 => net withdrawals
            cols[ent] = _zscore(ratio)

        elif etype == "STABLECOIN_ISSUER":
            ref = config.STABLE_PEG_REF.get(ent)
            peg_dev = pd.Series(0.0, index=idx)
            if ref and ref in _price_lookup(prices):
                p = _price_lookup(prices)[ref].reindex(idx).ffill()
                peg_dev = (1.0 - p).abs()                   # distance from $1
            fs = flow_ser[ent]
            total = (fs.inflow + fs.outflow).rolling(30, min_periods=5).mean().replace(0, np.nan)
            redemption = (fs.net_outflow / total).clip(lower=0).fillna(0.0)
            cols[ent] = 0.6 * _zscore(peg_dev) + 0.4 * _zscore(redemption)

        elif etype in ("LENDING", "LST"):
            slug = config.DEFILLAMA_PROTOCOLS.get(ent)
            stress = pd.Series(0.0, index=idx)
            if slug and slug in tvl and not tvl[slug].empty:
                t = tvl[slug].reindex(idx).ffill()
                # TVL drawdown: positive when TVL falls below its recent peak
                roll_max = t.rolling(30, min_periods=5).max()
                drawdown = (1.0 - t / roll_max).clip(lower=0).fillna(0.0)
                stress = stress.add(_zscore(drawdown), fill_value=0.0)
            cg = meta.get("coingecko_id")
            pl = _price_lookup(prices)
            if cg and cg in pl:
                p = pl[cg].reindex(idx).ffill()
                roll_max = p.rolling(30, min_periods=5).max()
                px_dd = (1.0 - p / roll_max).clip(lower=0).fillna(0.0)
                stress = stress.add(0.5 * _zscore(px_dd), fill_value=0.0)
            cols[ent] = stress
        else:
            cols[ent] = pd.Series(0.0, index=idx)

    # Aggregate retail/unknown node (Section 2.2): proxy realized loss + forced
    # liquidation by the ETH market drawdown — retail bears broad market stress.
    pl = _price_lookup(prices)
    if "ethereum" in pl:
        p = pl["ethereum"].reindex(idx).ffill()
        roll_max = p.rolling(30, min_periods=5).max()
        dd = (1.0 - p / roll_max).clip(lower=0).fillna(0.0)
        cols["retail"] = _zscore(dd)

    panel = pd.DataFrame(cols).reindex(idx).fillna(0.0)
    return panel


def _price_lookup(prices: pd.DataFrame) -> dict[str, pd.Series]:
    """Map both ticker and coingecko-id to columns so callers can use either."""
    lut = {}
    for col in prices.columns:
        lut[col] = prices[col]
    # also map coingecko ids
    for ticker, cg in config.MARKET_ASSETS.items():
        if ticker in prices.columns:
            lut[cg] = prices[ticker]
    return lut
