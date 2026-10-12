"""Shared hourly data context for the evaluation scripts.

build_hourly_context() loads the resolved flows, the hourly prices, the stETH series and the
stress panel once, so run_best, run_revision*, run_intraday_a3 and run_uncertainty use the
same inputs. Everything is read from the BigQuery cache (no new billing) once the extracts
exist.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from . import bq_flows, config, entity_resolution as er, hourly_stress as hs
from . import market_data as md, onchain_graph as og

WIN_START = dt.date(2025, 9, 15)        # ~3.5 weeks of pre-event hours to fit f_i
WIN_END = dt.date(2025, 10, 25)
TOKENS = ["USDe", "sUSDe", "wBETH", "USDC", "USDT"]
EVENT_START = pd.Timestamp("2025-10-10 00:00")
EVENT_END = pd.Timestamp("2025-10-11 23:00")


def build_hourly_context(k: int = 12, win=None, tokens=None) -> SimpleNamespace:
    """Flows (top-k entities), hourly prices, Lido series, stress panel and observed graph."""
    start, end = win if win is not None else (WIN_START, WIN_END)
    tokens = list(tokens) if tokens is not None else list(TOKENS)
    flows = er.load_resolved_flows(start, end, tokens, bucket="hour", min_addr_volume=1e3)
    flows = er.top_k_entities(flows, k=k)
    flows["day"] = pd.to_datetime(flows["day"])
    etypes = er.entity_types(flows)
    entities = sorted(set(flows.from_entity) | set(flows.to_entity) | set(config.ENTITIES))
    prices = md.build_hourly_price_panel(config.MARKET_ASSETS, start, end, ffill=False)
    lido = bq_flows.lido_series_bq(start, end)
    stress, meta = hs.build_hourly_stress(flows, entities, prices, lido=lido,
                                          freq="h", window=(start, end))
    stress = stress.sort_index()
    graph = og.build_graph(flows, min_usd=1e5)
    return SimpleNamespace(flows=flows, etypes=etypes, entities=entities, prices=prices,
                           prices_ffill=prices.ffill(),
                           lido=lido, stress=stress, stress_meta=meta, graph=graph,
                           win=(start, end), tokens=tokens, k=k)


def _daily_prices_raw(assets: dict, start, end) -> pd.DataFrame:
    """Daily price panel with observed quotes only (no forward fill)."""
    cols = {}
    for ticker, cg in assets.items():
        s = md.coingecko_prices(cg, start, end)
        if s is not None and not s.empty:
            cols[ticker] = s
    return pd.DataFrame(cols).sort_index()


def load_window_inputs(start, end, tokens, bucket: str = "hour", min_addr_volume: float = 1e3,
                       k: int = 12):
    """Top-k resolved flows and raw (not forward-filled) prices for one event window.

    bucket "hour" gives the primary resolution; "day" the daily robustness variant (the
    caller passes the daily min_addr_volume, 1e6)."""
    flows = er.load_resolved_flows(start, end, list(tokens), bucket=bucket,
                                   min_addr_volume=min_addr_volume)
    if flows.empty:
        return flows, pd.DataFrame()
    flows = er.top_k_entities(flows, k=k)
    flows["day"] = pd.to_datetime(flows["day"])
    if bucket == "hour":
        prices = md.build_hourly_price_panel(config.MARKET_ASSETS, start, end, ffill=False)
    else:
        prices = _daily_prices_raw(config.MARKET_ASSETS, start, end)
    return flows, prices
