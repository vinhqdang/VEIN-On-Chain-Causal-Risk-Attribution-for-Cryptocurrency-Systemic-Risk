"""Real market data: CoinGecko prices/returns and DefiLlama TVL, with caching.

These are free, keyless endpoints. Results are cached to data_cache/ so the
pipeline is reproducible and polite to the public APIs.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _get(url: str, cache_name: str, ttl_days: float = 7.0, retries: int = 4) -> dict:
    cache = CACHE_DIR / cache_name
    if cache.exists():
        return json.loads(cache.read_text())
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vein-research/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
            d = json.loads(raw.decode())
            cache.write_text(json.dumps(d))
            return d
        except http.client.IncompleteRead as e:
            # Large chunked payloads (e.g. DefiLlama /protocol) sometimes drop the
            # trailing chunk; the partial body is usually valid JSON already.
            try:
                d = json.loads(e.partial.decode())
                cache.write_text(json.dumps(d))
                return d
            except Exception:  # noqa: BLE001
                last = e
                time.sleep(2 ** i)
        except Exception as e:  # noqa: BLE001 - network resilience
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed for {url}: {last}")


def coingecko_prices(coin_id: str, start: dt.date, end: dt.date) -> pd.Series:
    """Daily USD prices for a CoinGecko id over [start, end].

    Sourced from DefiLlama's keyless price-chart API (the public CoinGecko
    endpoint caps history to 365 days and 401s on /range). DefiLlama serves the
    same CoinGecko-sourced prices with multi-year daily history.
    """
    # DefiLlama caps at 500 points/request, so chunk the window into ≤480-day spans.
    points: dict = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + dt.timedelta(days=479))
        frm = int(dt.datetime.combine(chunk_start, dt.time()).timestamp())
        span = max(1, (chunk_end - chunk_start).days + 1)
        url = (f"https://coins.llama.fi/chart/coingecko:{coin_id}"
               f"?start={frm}&span={span}&period=1d")
        d = _get(url, f"llama_px_{coin_id}_{chunk_start}_{chunk_end}.json")
        entry = d.get("coins", {}).get(f"coingecko:{coin_id}", {})
        for p in entry.get("prices", []):
            points[pd.Timestamp(p["timestamp"], unit="s").normalize()] = p["price"]
        chunk_start = chunk_end + dt.timedelta(days=1)
    if not points:
        return pd.Series(dtype=float, name=coin_id)
    s = pd.Series(points).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = coin_id
    return s


def defillama_tvl(slug: str) -> pd.Series:
    """Daily total USD TVL series for a DefiLlama protocol slug.

    Some protocol payloads are very large (Aave ~18MB) and occasionally truncate;
    on failure we cache an empty series so subsequent runs don't re-download it
    (the stress layer falls back to a price-drawdown proxy)."""
    url = f"https://api.llama.fi/protocol/{slug}"
    empty_cache = CACHE_DIR / f"llama_{slug}_EMPTY.json"
    if empty_cache.exists():
        return pd.Series(dtype=float, name=slug)
    try:
        d = _get(url, f"llama_{slug}.json")
    except Exception:  # noqa: BLE001
        empty_cache.write_text("{}")
        return pd.Series(dtype=float, name=slug)
    tvl = d.get("tvl", [])
    if not tvl:
        return pd.Series(dtype=float, name=slug)
    s = pd.Series({pd.Timestamp(p["date"], unit="s").normalize(): p["totalLiquidityUSD"]
                   for p in tvl})
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = slug
    return s


def build_price_panel(assets: dict[str, str], start: dt.date, end: dt.date) -> pd.DataFrame:
    """Wide daily price panel; columns = asset tickers."""
    cols = {}
    for ticker, cg_id in assets.items():
        s = coingecko_prices(cg_id, start, end)
        if not s.empty:
            cols[ticker] = s
    df = pd.DataFrame(cols).sort_index()
    return df.ffill()


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    import numpy as np
    return np.log(prices / prices.shift(1)).dropna(how="all")
