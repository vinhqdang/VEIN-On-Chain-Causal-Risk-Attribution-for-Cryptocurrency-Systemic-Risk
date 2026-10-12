"""Pandas mirror of bq_sql.sweep_sql (Tier-0 deposit-sweep detection, BQ_SPEC section 6).

detect_sweeps_frame applies exactly the same rules as the BigQuery query, so the
selftest in run_build_data.py can compare the two on synthetic data. Addresses are
lower-case '0x' strings here (the BigQuery query works on BYTES and converts).

A non-labelled address A is a deposit address of exchange X when (1) it sends at
least min_sweep_usd to X's hot wallets, (2) at least tau of its outflow goes to X,
(3) at most max_other_hot_share goes to other exchanges, (4) it has at most
max_out_cp distinct outbound counterparties, (5) at least k_in non-hot senders pay
it, (6) its outflow/inflow ratio lies in [min_fwd, max_fwd], (7) at most
max_in_from_hot_share of its inflow comes from hot wallets, and (8) at least
min_timed_share of the swept USD falls in buckets preceded (within h_hours,
inclusive) by an inflow from a non-hot sender.
"""
from __future__ import annotations

import pandas as pd

from . import config

NULL_ADDR = "0x" + "0" * 40
OUT_COLS = ["address", "entity", "to_x_usd", "n_sweeps", "out_usd", "out_cp", "in_usd",
            "n_senders_nonhot", "in_from_hot_usd", "timed_usd", "sweep_ratio"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUT_COLS)


def detect_sweeps_frame(x: pd.DataFrame, labels: pd.DataFrame, usd_per_unit: dict,
                        params: dict | None = None) -> pd.DataFrame:
    """x: bucket, token, from_a, to_a, amount, n_tx. labels: address, entity, src, etype.
    usd_per_unit: token -> USD per token unit (tokens missing from it are dropped,
    as in the SQL inner join). Returns one row per detected deposit address."""
    p = dict(config.SWEEP_PARAMS, **(params or {}))
    if x.empty:
        return _empty()

    px = x["token"].map(usd_per_unit)
    xu = x[px.notna()].copy()
    xu["usd"] = xu["amount"].astype(float) * px[px.notna()].astype(float)
    bkt = pd.to_datetime(xu["bucket"])
    xu["bucket"] = bkt.dt.tz_localize(None) if bkt.dt.tz is not None else bkt
    xu = xu[["bucket", "from_a", "to_a", "usd", "n_tx"]]

    lab = labels.drop_duplicates("address", keep="first")
    hot = dict(zip(lab.loc[(lab.etype == "CEX") & lab.src.isin(["seed", "label"]), "address"],
                   lab.loc[(lab.etype == "CEX") & lab.src.isin(["seed", "label"]), "entity"]))
    known = set(lab.loc[lab.src.isin(["seed", "label"]), "address"])

    # outs: flows from unlabelled, non-null addresses
    outs = xu[~xu["from_a"].isin(known) & (xu["from_a"] != NULL_ADDR)].copy()
    outs["hot_entity"] = outs["to_a"].map(hot)
    out_stats = outs.groupby("from_a").agg(out_usd=("usd", "sum"),
                                           out_cp=("to_a", "nunique"))
    by_x = (outs[outs.hot_entity.notna()]
            .groupby(["from_a", "hot_entity"])
            .agg(to_x_usd=("usd", "sum"), n_sweeps=("n_tx", "sum")).reset_index())
    if by_x.empty:
        return _empty()
    by_x["to_any_hot_usd"] = by_x.groupby("from_a")["to_x_usd"].transform("sum")
    by_x = by_x.sort_values(["from_a", "to_x_usd", "hot_entity"],
                            ascending=[True, False, True])
    by_x["rk"] = by_x.groupby("from_a").cumcount() + 1
    ranked = by_x[by_x.rk == 1].set_index("from_a")

    # ins: flows into the candidate, with the sender's hot-wallet status
    ins = xu.rename(columns={"to_a": "a", "from_a": "s"}).copy()
    ins["from_hot"] = ins["s"].map(hot)
    in_stats = ins.groupby("a").apply(
        lambda g: pd.Series({
            "in_usd": g["usd"].sum(),
            "n_senders_nonhot": g.loc[g.from_hot.isna(), "s"].nunique(),
            "in_from_hot_usd": g.loc[g.from_hot.notna(), "usd"].sum()}),
        include_groups=False)

    # timed share: swept buckets with a non-hot inflow in [bucket - h, bucket]
    sw = (outs[outs.hot_entity.notna()]
          .groupby(["from_a", "hot_entity", "bucket"], as_index=False)["usd"].sum())
    inb = (ins[ins.from_hot.isna()][["a", "bucket"]].drop_duplicates()
           .rename(columns={"a": "from_a"}))
    m = sw.merge(inb, on="from_a", suffixes=("", "_in"))
    lo = m["bucket"] - pd.Timedelta(hours=int(p["h_hours"]))
    m = m[(m["bucket_in"] <= m["bucket"]) & (m["bucket_in"] >= lo)]
    timed_keys = m[["from_a", "hot_entity", "bucket"]].drop_duplicates()
    timed = sw.merge(timed_keys, on=["from_a", "hot_entity", "bucket"])
    timed_stats = timed.groupby(["from_a", "hot_entity"])["usd"].sum().rename("timed_usd")

    # final filter, mirroring the WHERE clause of sweep_sql
    r = ranked.join(out_stats, how="inner").join(in_stats, how="inner")
    r = r.reset_index().rename(columns={"index": "from_a"})
    r = r.merge(timed_stats.reset_index(), on=["from_a", "hot_entity"], how="left")
    r["timed_usd"] = r["timed_usd"].fillna(0.0)
    r["sweep_ratio"] = r["to_x_usd"] / r["out_usd"]
    fwd = r["out_usd"] / r["in_usd"]
    in_hot = r["in_from_hot_usd"] / r["in_usd"]
    keep = ((r.to_x_usd >= p["min_sweep_usd"])
            & (r.sweep_ratio >= p["tau"])
            & ((r.to_any_hot_usd - r.to_x_usd) / r.out_usd <= p["max_other_hot_share"])
            & (r.out_cp <= p["max_out_cp"])
            & (r.n_senders_nonhot >= p["k_in"])
            & fwd.between(p["min_fwd"], p["max_fwd"])
            & (in_hot <= p["max_in_from_hot_share"])
            & (r.timed_usd / r.to_x_usd >= p["min_timed_share"]))
    r = r[keep.fillna(False)]
    out = r.rename(columns={"from_a": "address", "hot_entity": "entity"})[OUT_COLS]
    out = out.sort_values(["to_x_usd", "entity"], ascending=[False, True]).reset_index(drop=True)
    return out
