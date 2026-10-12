"""BigQuery-backed flow loaders (BQ_SPEC section 7).

Pipeline: token_transfers -> per-chunk extract tables (stage 1, materialized and
cached) -> label epoch tables (seed + open labels + Tier-0 sweeps) -> stage-2 queries
whose results are post-processed here into the same frame the Dune layer produced.

google-cloud access happens only through vein.bq, and only when a function here is
called. Importing this module needs no cloud libraries.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import bq, bq_sql, config, labels as lb, market_data as md, sweeps as sw
from .entity_resolution import normalize_entity

CACHE_DIR = bq.CACHE_DIR
OPEN_LABELS = CACHE_DIR / "labels_open.csv.gz"
FLOW_COLS = ["day", "from_entity", "to_entity", "usd_volume", "n_tx", "from_src", "to_src"]
ETH_TOKENS = config.ETH_DENOMINATED
# Tokens whose panel coverage is reported (the flows the hourly stress is built from).
PANEL_TOKENS = {"oct25_hourly": ["USDe", "sUSDe", "wBETH", "USDC", "USDT"],
                "ftx_hourly": ["USDC", "USDT", "WETH"], "svb_hourly": ["USDC", "USDT", "WETH"],
                "ftx_ext": ["USDC", "USDT", "WETH"], "svb_ext": ["USDC", "USDT", "WETH"],
                "core_daily": ["USDe", "sUSDe", "wBETH"]}


def _d(x) -> dt.date:
    return bq_sql._d(x)


def _open_labels(kind: str | None = "wallet") -> pd.DataFrame:
    """Open exchange labels. Default: wallet-kind only (hot/cold/funder wallets), the only
    kind used as entity labels and Tier-3 hot set H. kind='deposit' returns the per-user
    deposit-address labels (validation set only), kind=None returns everything."""
    if not OPEN_LABELS.exists():
        raise RuntimeError(f"{OPEN_LABELS} missing: run run_build_data.py --labels first")
    df = lb.with_kind(pd.read_csv(OPEN_LABELS, dtype=str, keep_default_na=False))
    return df if kind is None else df[df["kind"] == kind].reset_index(drop=True)


def _eth_usd(start, end) -> float:
    px = md.coingecko_prices("ethereum", _d(start), _d(end))
    if px.empty:
        raise RuntimeError("no ETH price series for the window")
    return float(px.mean())


def usd_per_unit(tokens, start, end) -> dict:
    """USD per token unit: $1 for stablecoins (and sUSDe, a documented approximation),
    window-mean ETH price for ETH-denominated tokens."""
    eth = _eth_usd(start, end) if any(t in ETH_TOKENS for t in tokens) else None
    return {t: (eth if t in ETH_TOKENS else 1.0) for t in tokens}


def _eth_lookup(eth_px: pd.Series, days) -> np.ndarray:
    s = eth_px.copy()
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index().astype(float)
    days = pd.DatetimeIndex(days)
    filled = s.reindex(s.index.union(days.unique())).ffill().bfill()
    return filled.reindex(days).to_numpy()


# ---------------------------------------------------------------------------
# stage 1 and labels
# ---------------------------------------------------------------------------
def ensure_extract(key: str, refresh: bool = False) -> tuple[list[str], list[str]]:
    """Materialize every chunk of an extract. Returns (table ids, sql hashes)."""
    spec = config.BQ_EXTRACTS[key]
    client = bq.get_client()
    ids = bq_sql.extract_table_ids(key)
    hashes = []
    for (cs, ce), tid in zip(bq_sql.chunks(spec["start"], spec["end"], spec["chunk_days"]), ids):
        sql = bq_sql.extract_sql(key, cs, ce)
        hashes.append(bq.sql_hash(sql))
        bq.materialize(sql, tid, name=f"extract_{key}", refresh=refresh, client=client)
    return ids, hashes


def _upload_base(client):
    """Upload labels_base (seed + open). Returns (fq table, fingerprint, frame)."""
    seed = lb.seed_label_table()
    base = lb.merge_labels(seed, _open_labels())
    fq = bq.upload_dataframe(lb.to_bq_frame(base), "labels_base", lb.BQ_LABEL_SCHEMA, client)
    return fq, lb.label_fingerprint(base), base


def detect_deposit_sweeps_bq(key: str, labels_table: str = "labels_base") -> pd.DataFrame:
    """Tier-0 sweep detection over one extract, against labels_base."""
    spec = config.BQ_EXTRACTS[key]
    client = bq.get_client()
    ids, hashes = ensure_extract(key)
    fq, fp, _ = _upload_base(client)
    if labels_table != "labels_base":   # any existing label table with the same schema
        fq = bq.table_id(client, labels_table)
    usd = usd_per_unit(spec["tokens"], spec["start"], spec["end"])
    sql = bq_sql.sweep_sql(ids, fq, fp, hashes, usd, config.SWEEP_PARAMS)
    rows = bq.run_sql(sql, name=f"sweeps_{key}", client=client)
    return pd.DataFrame(rows, columns=sw.OUT_COLS)


def ensure_labels(epoch: str, refresh: bool = False) -> tuple[str, str]:
    """Label table for an epoch: seed > open > sweeps from every extract in the epoch.
    Returns (fq table, fingerprint). Sweep addresses claimed by two different roots
    across extracts are dropped."""
    client = bq.get_client()
    cache = CACHE_DIR / f"labels_{epoch}.csv.gz"
    seed = lb.seed_label_table()
    if cache.exists() and not refresh:
        cached = pd.read_csv(cache, dtype=str, keep_default_na=False)
        merged = lb.refresh_seeds(cached)
        promoted = set(merged.loc[merged["src"] == "seed", "address"]) - \
            set(cached.loc[cached["src"] == "seed", "address"])
        changed = {a for a in promoted if a in set(cached["address"])}
        for a in sorted(changed):
            print(f"  label {a}: promoted to seed (was {cached.loc[cached.address == a, 'src'].iloc[0]})")
        if len(merged) != len(cached) or changed:
            merged.to_csv(cache, index=False, compression="gzip")
    else:
        _, _, base = _upload_base(client)   # labels_base is the input to the sweep queries
        keys = bq_sql.sweep_keys(epoch)
        if not keys:
            raise ValueError(f"no sweep extract in epoch {epoch!r}")
        found = [detect_deposit_sweeps_bq(k) for k in keys]
        found = [f for f in found if len(f)]
        if found:
            s = pd.concat(found, ignore_index=True)
            s = pd.DataFrame({"address": s["address"].str.lower(), "entity": s["entity"],
                              "src": "sweep", "etype": "CEX", "raw_name": s["entity"],
                              "source": "sweeps"})
            per = s.groupby("address")["entity"].nunique()
            s = s[s["address"].isin(per[per == 1].index)].drop_duplicates("address")
        else:
            s = None
        merged = lb.merge_labels(seed, _open_labels(), s)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        merged.to_csv(cache, index=False, compression="gzip")
    fp = lb.label_fingerprint(merged)
    fq = bq.upload_dataframe(lb.to_bq_frame(merged), f"labels_{epoch}", lb.BQ_LABEL_SCHEMA, client)
    return fq, fp


# ---------------------------------------------------------------------------
# post-processing and public loaders
# ---------------------------------------------------------------------------
def postprocess_flow_rows(rows, bucket: str, eth_px, min_usd: float) -> pd.DataFrame:
    """Rows from flow_sql -> the frame the analysis expects (BQ_SPEC section 7 order)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=FLOW_COLS)
    day = pd.to_datetime(df["day"])
    if getattr(day.dt, "tz", None) is not None:
        day = day.dt.tz_localize(None)
    if bucket == "day":
        day = day.dt.normalize()          # hourly buckets must not be floored
    df["day"] = day
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["n_tx"] = pd.to_numeric(df["n_tx"], errors="coerce").fillna(0).astype(int)
    is_eth = df["token"].isin(ETH_TOKENS).to_numpy()
    if is_eth.any():
        if eth_px is None or len(eth_px) == 0:
            raise ValueError("ETH price series required for ETH-denominated tokens")
        px = _eth_lookup(eth_px, df.loc[is_eth, "day"].dt.floor("D"))
        unit = np.ones(len(df))
        unit[is_eth] = px
    else:
        unit = np.ones(len(df))
    df["usd"] = df["volume"].to_numpy() * unit
    df["from_entity"] = df["from_entity"].map(normalize_entity)
    df["to_entity"] = df["to_entity"].map(normalize_entity)
    agg = (df.groupby(["day", "from_entity", "to_entity"], as_index=False)
             .agg(usd_volume=("usd", "sum"), n_tx=("n_tx", "sum"),
                  from_src=("from_src", "max"), to_src=("to_src", "max")))
    agg = agg[agg["usd_volume"] >= min_usd]
    agg = agg[agg["from_entity"] != agg["to_entity"]]
    return agg[FLOW_COLS].reset_index(drop=True)


def load_resolved_flows_bq(start, end, tokens, eth_price=None, bucket="day",
                           min_addr_volume: float = 5e6) -> pd.DataFrame:
    start, end = _d(start), _d(end)
    key = bq_sql.select_extract(start, end, tokens, bucket)
    epoch = config.BQ_EXTRACTS[key]["epoch"]
    ids, hashes = ensure_extract(key)
    fq, fp = ensure_labels(epoch)
    sql = bq_sql.flow_sql(ids, fq, fp, hashes, start, end, tokens, bucket)
    rows = bq.run_sql(sql, name="vein_resolved_flows_bq")
    if eth_price is None and any(t in ETH_TOKENS for t in tokens):
        eth_price = md.coingecko_prices("ethereum", start - dt.timedelta(days=1), end)
    return postprocess_flow_rows(rows, bucket, eth_price, min_addr_volume)


def fetch_labeled_edges_bq(token: str, start, end) -> pd.DataFrame:
    start, end = _d(start), _d(end)
    key = bq_sql.select_extract(start, end, [token], "hour")
    ids, hashes = ensure_extract(key)
    # Ground truth for the resolver validation keeps the deposit-address labels: finding
    # deposit addresses is exactly what the Tier-1/2 classifier is tested on. Reports must
    # therefore say that the labelled set is deposit-dominated (see DATA_BUILD.md).
    gt = lb.merge_labels(lb.seed_label_table(), _open_labels(kind=None))
    fq = bq.upload_dataframe(lb.to_bq_frame(gt), "labels_edges", lb.BQ_LABEL_SCHEMA)
    fp = lb.label_fingerprint(gt)
    sql = bq_sql.edges_sql(ids, fq, fp, hashes, token, start, end)
    rows = bq.run_sql(sql, name="vein_resolver_edges_bq")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def coverage_bq(key: str, start=None, end=None) -> dict:
    """USD share of extract flow by label coverage of each side (BQ_SPEC section 9.7).

    'both_resolved' splits into distinct labelled entities and one entity on both sides
    (same_entity). panel_tokens restricts the same numbers to the tokens the hourly stress
    is built from (PANEL_TOKENS) and adds the share of entity-touching flow that is named
    on both sides."""
    spec = config.BQ_EXTRACTS[key]
    start = _d(start or spec["start"])
    end = _d(end or spec["end"])
    ids, hashes = ensure_extract(key)
    fq, fp = ensure_labels(spec["epoch"])
    sql = bq_sql.coverage_sql(ids, fq, fp, hashes, start, end)
    df = pd.DataFrame(bq.run_sql(sql, name=f"coverage_{key}"))
    if df.empty:
        return {"key": key, "window": [str(start), str(end)], "total_usd": 0.0}
    unit = usd_per_unit(spec["tokens"], start, end)
    df["usd"] = pd.to_numeric(df["amount"]) * df["token"].map(unit).astype(float)
    df["same"] = df["same_entity"].astype(str).str.lower().isin(["true", "1"])
    total = float(df["usd"].sum())
    mb = df.is_mint_burn.astype(str).str.lower().isin(["true", "1"])
    both = df.from_src.ne("none") & df.to_src.ne("none")
    one = df.from_src.ne("none") ^ df.to_src.ne("none")
    neither = ~(both | one)
    distinct = both & ~df.same

    def share(mask, base=total, frame=df):
        return float(frame.loc[mask, "usd"].sum() / base) if base else 0.0

    by_pair = (df[~mb].groupby(["from_src", "to_src"])["usd"].sum() / total
               if total else pd.Series(dtype=float))
    out = {"key": key, "window": [str(start), str(end)], "total_usd": total,
           "shares": {"both_resolved": share(both & ~mb), "both_resolved_distinct": share(distinct & ~mb),
                      "both_resolved_same_entity": share(both & df.same & ~mb),
                      "one_side": share(one & ~mb), "neither": share(neither & ~mb),
                      "mint_burn": share(mb)},
           "by_src_pair": {f"{a}->{b}": float(v) for (a, b), v in by_pair.items()},
           "by_token_usd": {t: float(v) for t, v in df.groupby("token")["usd"].sum().items()},
           "n_pairs": int(df["n_pairs"].sum()), "n_rows": int(len(df))}
    if key in PANEL_TOKENS:
        pdf = df[df.token.isin(PANEL_TOKENS[key])]
        ptot = float(pdf["usd"].sum())
        pdist = distinct & ~mb & df.token.isin(PANEL_TOKENS[key])
        pone = one & ~mb & df.token.isin(PANEL_TOKENS[key])
        d_usd = float(pdf.loc[pdist[pdf.index], "usd"].sum()) if ptot else 0.0
        o_usd = float(pdf.loc[pone[pdf.index], "usd"].sum()) if ptot else 0.0
        out["panel_tokens"] = {
            "tokens": PANEL_TOKENS[key], "total_usd": ptot,
            "both_resolved_distinct": d_usd / ptot if ptot else 0.0,
            "one_side": o_usd / ptot if ptot else 0.0,
            "named_distinct_share_of_touching": d_usd / (d_usd + o_usd) if (d_usd + o_usd) else 0.0,
            "token_share_of_total": {t: float(pdf.loc[pdf.token == t, "usd"].sum() / total)
                                     for t in PANEL_TOKENS[key]} if total else {}}
    return out


def lido_series_bq(start, end, key: str = "oct25_lido") -> pd.DataFrame:
    """Hourly stETH mints, Withdrawal Queue deposits and gross volume on [start, end).

    Returns a tz-naive hourly frame with columns steth_mint, steth_wq_in, steth_gross;
    hours with no transfer are zero."""
    start, end = _d(start), _d(end)
    spec = config.BQ_EXTRACTS[key]
    if not (spec["start"] <= start and end <= spec["end"] and "stETH" in spec["tokens"]):
        raise ValueError(f"extract {key} does not cover stETH {start}..{end}")
    ids, hashes = ensure_extract(key)
    sql = bq_sql.lido_series_sql(ids, hashes, start, end)
    rows = bq.run_sql(sql, name="lido_series")
    cols = ["steth_mint", "steth_wq_in", "steth_gross"]
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="h", inclusive="left")
    if not rows:
        return pd.DataFrame(0.0, index=idx, columns=cols)
    df = pd.DataFrame(rows)
    hour = pd.to_datetime(df["hour"])
    if getattr(hour.dt, "tz", None) is not None:
        hour = hour.dt.tz_localize(None)
    df.index = pd.DatetimeIndex(hour)
    out = df[cols].apply(pd.to_numeric).astype(float)
    return out.groupby(level=0).sum().reindex(idx, fill_value=0.0)


def usde_daily_bq(start=dt.date(2025, 10, 8), end=dt.date(2025, 10, 14),
                  key: str = "oct25_hourly") -> pd.DataFrame:
    """Daily USDe volume. Reads the small hourly Oct-2025 extract by default, so the Dune
    sanity check can run before the large core_daily extract is paid for."""
    start, end = _d(start), _d(end)
    spec = config.BQ_EXTRACTS[key]
    if not (spec["start"] <= start and end <= spec["end"] and "USDe" in spec["tokens"]):
        raise ValueError(f"extract {key} does not cover USDe {start}..{end}")
    ids, hashes = ensure_extract(key)
    sql = bq_sql.usde_daily_sql(ids, hashes, start, end)
    rows = bq.run_sql(sql, name="usde_daily_bq")
    df = pd.DataFrame(rows, columns=["day", "usde", "n_tx"])
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"]).dt.tz_localize(None).dt.normalize()
        df["usde"] = pd.to_numeric(df["usde"]).astype(float)
        df["n_tx"] = pd.to_numeric(df["n_tx"]).astype(int)
    return df
