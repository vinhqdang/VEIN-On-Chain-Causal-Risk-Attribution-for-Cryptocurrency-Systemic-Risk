"""Stress panel built from named components (algorithm.md Section 3.3).

Every entity's stress is the equal-weight mean of its components listed in
config.HOURLY_STRESS_COMPONENTS. A component is kept only if it has a non-degenerate
fit-window std and its inputs exist; the reasons for every drop are returned in meta.

Component definitions (higher = more stressed):
  flow                 F = 0.6 z(net) + 0.4 z(total), net = (out - in) / rolling total.
                       Already a z-score combination, so it is not z-scored again.
  peg:X                z(|1 - P_X|), hourly price of stablecoin X, forward-filled.
  drawdown:X           z(1 - P_X / rolling max of P_X), clipped at zero.
  discount:stETH/ETH   z(1 - median_3h(P_stETH / P_ETH)), clipped at zero.
  lido_redeem          z(net redemption ratio), net = queue deposits - mints of stETH,
                       scaled by their rolling total.

z(s) = (s - rolling mean) / rolling std over `roll` steps (min_periods), NaN-safe.
roll=48 and min_periods=6 for hourly data (the legacy setting); daily data uses roll=14,
min_periods=3.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from . import config

ROLL = 48
FIT_STD_MIN = 1e-9
OBSERVED_MIN = 0.5          # minimum share of steps with an observed (not filled) price


def zscore(s: pd.Series, win: int = ROLL, min_periods: int = 6) -> pd.Series:
    mu = s.rolling(win, min_periods=min_periods).mean()
    sd = s.rolling(win, min_periods=min_periods).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def _flow_component(flows: pd.DataFrame, e: str, idx, roll: int, min_periods: int) -> pd.Series:
    inf = flows[flows.to_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
    outf = flows[flows.from_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
    tot = inf + outf
    net = ((outf - inf) / tot.rolling(roll, min_periods=min_periods).mean().replace(0, np.nan)).fillna(0.0)
    return 0.6 * zscore(net, roll, min_periods) + 0.4 * zscore(tot, roll, min_periods)


def _observed_share(raw: pd.Series) -> float:
    return float(raw.notna().mean()) if len(raw) else 0.0


def build_hourly_stress(flows: pd.DataFrame, entities, prices: pd.DataFrame | None = None,
                        lido: pd.DataFrame | None = None, fit_end=None, roll: int = ROLL,
                        min_periods: int = 6, freq: str = "h", window=None):
    """Stress panel on the flow timestamps. Returns (panel, meta).

    prices: DataFrame of raw (not forward-filled) prices indexed by timestamp, one column per
            asset name (config.MARKET_ASSETS keys). Missing columns drop the matching component.
    lido:   hourly frame with steth_mint and steth_wq_in (see bq_flows.lido_series_bq); None
            drops lido_redeem and the stETH discount is still used if prices are given.
    fit_end: rows before this timestamp form the fit window for the std screen. None uses
            all rows.
    window: optional (start, end); the index is checked against the number of steps in it.
    """
    idx = pd.DatetimeIndex(sorted(flows["day"].unique()))
    if window is not None:
        expected = len(pd.date_range(pd.Timestamp(window[0]), pd.Timestamp(window[1]),
                                     freq=freq, inclusive="left"))
        if len(idx) != expected:
            warnings.warn(f"stress index has {len(idx)} steps, window {window[0]}..{window[1]} "
                          f"has {expected}; steps without any flow are absent")
    fit = np.ones(len(idx), dtype=bool) if fit_end is None else np.asarray(idx < pd.Timestamp(fit_end))
    obs = filled = None
    if prices is not None:
        prices = prices.sort_index()
        obs = prices.reindex(idx)                       # observed quotes only
        # forward fill on the price timestamps first (as the legacy panel was), then onto idx
        filled = prices.reindex(prices.index.union(idx)).ffill().reindex(idx)
    lido_r = None
    if lido is not None:
        lido_r = lido.reindex(idx).fillna(0.0)

    def price(name):
        if obs is None or name not in obs.columns:
            return None
        return obs[name], filled[name]

    cols, meta = {}, {}
    for e in entities:
        names = config.HOURLY_STRESS_COMPONENTS.get(e, config.HOURLY_STRESS_COMPONENTS["_default"])
        kept, dropped = {}, {}
        for name in names:
            series, reason = _component(name, flows, e, idx, price, lido_r, roll, min_periods)
            if series is None:
                dropped[name] = reason
                continue
            sd = float(series[fit].std()) if fit.any() else 0.0
            if not np.isfinite(sd) or sd <= FIT_STD_MIN:
                dropped[name] = f"fit-window std {sd:.3g} <= {FIT_STD_MIN:g}"
                continue
            kept[name] = series
        if kept:
            cols[e] = pd.concat(kept, axis=1).mean(axis=1)
        else:
            cols[e] = pd.Series(0.0, index=idx)
        meta[e] = {"used": list(kept), "dropped": dropped,
                   "fit_std": float(cols[e][fit].std()) if fit.any() else 0.0}
    panel = pd.DataFrame(cols, index=idx)[list(entities)].fillna(0.0)
    return panel, meta


def _component(name, flows, e, idx, price, lido_r, roll, min_periods):
    """(series, None) for a usable component, or (None, reason).

    price(name) returns (observed, forward-filled) quotes on idx, or None if absent."""
    if name == "flow":
        return _flow_component(flows, e, idx, roll, min_periods), None
    if name.startswith("peg:"):
        got = price(name[4:])
        if got is None:
            return None, f"no price column {name[4:]}"
        share = _observed_share(got[0])
        if share < OBSERVED_MIN:
            return None, f"observed price share {share:.2f} < {OBSERVED_MIN}"
        peg = (1.0 - got[1]).abs()
        return zscore(peg, roll, min_periods), None
    if name.startswith("drawdown:"):
        got = price(name[len("drawdown:"):])
        if got is None:
            return None, f"no price column {name[len('drawdown:'):]}"
        share = _observed_share(got[0])
        if share < OBSERVED_MIN:
            return None, f"observed price share {share:.2f} < {OBSERVED_MIN}"
        p = got[1]
        dd = (1 - p / p.rolling(roll, min_periods=min_periods).max()).clip(lower=0).fillna(0.0)
        return zscore(dd, roll, min_periods), None
    if name == "discount:stETH/ETH":
        a, b = price("stETH"), price("ETH")
        if a is None or b is None:
            return None, "no stETH or ETH price column"
        share = min(_observed_share(a[0]), _observed_share(b[0]))
        if share < OBSERVED_MIN:
            return None, f"observed price share {share:.2f} < {OBSERVED_MIN}"
        r = (a[1] / b[1]).rolling(3, min_periods=1).median()
        return zscore((1 - r).clip(lower=0).fillna(0.0), roll, min_periods), None
    if name == "lido_redeem":
        if lido_r is None:
            return None, "no Lido series"
        wq, mint = lido_r["steth_wq_in"], lido_r["steth_mint"]
        net = wq - mint
        den = (wq + mint).rolling(roll, min_periods=min_periods).mean().replace(0, np.nan)
        return zscore((net / den).fillna(0.0), roll, min_periods), None
    raise ValueError(f"unknown stress component {name!r}")


def zero_stress_entities(panel: pd.DataFrame, fit_index) -> list:
    """Entities whose stress has (near) zero std over the fit window."""
    fit = panel.index.isin(pd.DatetimeIndex(fit_index))
    sd = panel.loc[fit].std()
    return [e for e in panel.columns if not np.isfinite(sd[e]) or sd[e] <= FIT_STD_MIN]


def assert_nonzero_stress(panel: pd.DataFrame, fit_index) -> None:
    bad = zero_stress_entities(panel, fit_index)
    if bad:
        raise RuntimeError(f"entities with zero fit-window stress: {', '.join(bad)}")
