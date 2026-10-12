#!/usr/bin/env python3
"""Build the BigQuery data layer for VEIN (BQ_SPEC section 9).

Stages, run in this order by --all (each stops the run on failure):

  --check      auth, dataset, schema, freshness and dedupe checks on crypto_ethereum
  --budget     dry-run every stage-1 chunk and gate the planned spend
  --selftest   synthetic extract/labels round trip: SQL result == pandas mirror
  --labels     clone the open label repos, discover formats, build the open label table
               and results/DATA_BUILD.md (runs without BigQuery)
  --extract K  materialize stage-1 extracts (K = key or 'all'); checks USDe vs Dune
  --sweeps     Tier-0 sweep detection per extract, holdout validation, epoch label tables
  --coverage   label coverage per extract -> results/coverage.json, results/COVERAGE.md
  --labels-epochs E1,E2   rebuild the label epoch tables of the given epochs (no full sweeps)
  --verify-protocol       check the Aave aToken / stETH symbols and the Lido queue series

Outputs: results/data_build.json (merged across stages), results/DATA_BUILD.md.
Every query is dry-run and billed through vein.bq, which enforces the byte caps and
writes data_cache/bq_ledger.json.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from vein import bq, bq_flows, bq_sql, config, labels as lb, sweeps as sw

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)
DATA_BUILD_JSON = RESULTS / "data_build.json"
DATA_BUILD_MD = RESULTS / "DATA_BUILD.md"
COVERAGE_JSON = RESULTS / "coverage.json"
COVERAGE_MD = RESULTS / "COVERAGE.md"
PLANNED_CEILING_GIB = 700.0
CORE_KEY = "core_daily"
EXTRACT_ORDER = ["oct25_hourly", "ftx_hourly", "svb_hourly", "core_daily"]
# Extracts reported by --coverage in addition to EXTRACT_ORDER (the 2022/2023 windows).
COVERAGE_EXTRA = ["ftx_ext", "svb_ext"]
NEW_GIB_CEILING = 40.0          # planned spend of not-yet-materialized extracts (--budget)
AAVE_POOLS = {"0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2", "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9"}
PROTOCOL_SYMBOLS = ["aEthUSDC", "aEthUSDT", "aEthUSDe", "aEthsUSDe", "aEthWETH",
                    "aUSDC", "aUSDT", "aWETH", "stETH"]
# Dune USDe daily transfer volume (USD bn) for Oct 8-13 2025, from the old pipeline.
DUNE_USDE_BN = {"2025-10-08": 1.405, "2025-10-09": 0.745, "2025-10-10": 3.090,
                "2025-10-11": 8.828, "2025-10-12": 1.328, "2025-10-13": 0.688}
USDE_TOL = 0.02
USDE_ADDR = config.TOKENS["USDe"]
STOP = 3   # exit code for a failed check that needs a human decision


class StageFailed(RuntimeError):
    """A check failed; the run stops here."""


def _log(msg: str) -> None:
    print(msg, flush=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def update_data_build(**kv) -> None:
    """Merge keys into results/data_build.json (other stages' keys are kept)."""
    d = _load_json(DATA_BUILD_JSON)
    d.update(kv)
    d["generated"] = dt.date.today().isoformat()
    d["data_backend"] = config.DATA_BACKEND
    DATA_BUILD_JSON.write_text(json.dumps(d, indent=2, default=str))


def _ledger_summary() -> dict:
    led = bq.load_ledger()
    entries = led.get("entries", [])
    return {"cumulative_billed_gib": led.get("cumulative_billed_bytes", 0) / bq.GIB,
            "by_month_gib": {m: v / bq.GIB for m, v in led.get("by_month", {}).items()},
            "n_entries": len(entries),
            "n_dry_runs": sum(1 for e in entries if e.get("kind") == "dry_run"),
            "n_queries_billed": sum(1 for e in entries if e.get("kind") in ("query", "materialize")),
            "n_cache_hits": sum(1 for e in entries if e.get("cache_hit"))}


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def stage_check() -> dict:
    client = bq.get_client()
    bq.ensure_dataset(client)
    src = config.BQ_SOURCE
    proj, ds = src.split(".")[0], src.split(".")[1]
    cols_sql = (f"SELECT table_name, column_name, data_type, is_partitioning_column, "
                f"clustering_ordinal_position FROM `{proj}.{ds}.INFORMATION_SCHEMA.COLUMNS` "
                f"WHERE table_name IN ('token_transfers','tokens','transactions')")
    cols = pd.DataFrame(bq.run_sql(cols_sql, name="check_columns", refresh=True, client=client))
    need = {"token_address": "STRING", "from_address": "STRING", "to_address": "STRING",
            "value": "STRING", "block_timestamp": "TIMESTAMP"}
    tt = cols[cols.table_name == "token_transfers"].set_index("column_name")
    schema_ok = {c: (c in tt.index and tt.loc[c, "data_type"] == t) for c, t in need.items()}
    if not all(schema_ok.values()):
        raise StageFailed(f"token_transfers schema mismatch: {schema_ok}")
    part = tt[tt.is_partitioning_column.astype(str).eq("YES")].index.tolist()
    clus = tt[tt.clustering_ordinal_position.notna()].sort_values("clustering_ordinal_position").index.tolist()
    if "block_timestamp" not in part:
        # token_transfers is published as a view over a partitioned table, so the
        # view's columns carry no partitioning flag. Verify pruning by dry run
        # instead: ten days must scan clearly more than one day.
        one = bq.dry_run_bytes(f"SELECT token_address, from_address, to_address, value FROM "
                               f"`{src}.token_transfers` WHERE block_timestamp >= "
                               f"TIMESTAMP('2025-10-10 00:00:00+00') AND block_timestamp < "
                               f"TIMESTAMP('2025-10-11 00:00:00+00')", client)
        ten = bq.dry_run_bytes(f"SELECT token_address, from_address, to_address, value FROM "
                               f"`{src}.token_transfers` WHERE block_timestamp >= "
                               f"TIMESTAMP('2025-10-10 00:00:00+00') AND block_timestamp < "
                               f"TIMESTAMP('2025-10-20 00:00:00+00')", client)
        if not (one > 0 and ten > 2.5 * one):
            raise StageFailed(f"block_timestamp filter does not prune token_transfers "
                              f"(1 day {one} B, 10 days {ten} B)")
        part = ["block_timestamp (via view; pruning verified by dry run: "
                f"1 day {one / 2**30:.2f} GiB, 10 days {ten / 2**30:.2f} GiB)"]
    _log(f"  schema ok; partitioning={part} clustering={clus}")

    fresh = bq.run_sql(f"SELECT MAX(block_timestamp) AS mx FROM `{src}.token_transfers` "
                       f"WHERE block_timestamp >= TIMESTAMP('2026-06-25 00:00:00+00')",
                       name="check_freshness", refresh=True, client=client)
    mx = pd.Timestamp(fresh[0]["mx"]) if fresh and fresh[0]["mx"] else None
    if mx is None or mx < pd.Timestamp("2026-06-30", tz="UTC"):
        raise StageFailed(f"token_transfers stops at {mx}; need >= 2026-06-30 "
                          f"(fallback goog_blockchain_ethereum_mainnet_us.logs is not implemented)")
    _log(f"  freshness ok: MAX(block_timestamp) = {mx}")

    dd = bq.run_sql(
        f"SELECT COUNT(*) AS n, COUNT(DISTINCT CONCAT(transaction_hash, '-', CAST(log_index AS STRING))) AS nd, "
        f"COUNTIF(token_address != LOWER(token_address)) AS upper_n "
        f"FROM `{src}.token_transfers` WHERE token_address = '{USDE_ADDR}' "
        f"AND block_timestamp >= TIMESTAMP('2025-10-10 00:00:00+00') "
        f"AND block_timestamp < TIMESTAMP('2025-10-11 00:00:00+00')",
        name="check_dedupe", refresh=True, client=client)[0]
    if int(dd["n"]) != int(dd["nd"]) or int(dd["upper_n"]) != 0:
        raise StageFailed(f"USDe 2025-10-10 dedupe/case check failed: {dd}")
    _log(f"  dedupe ok: {dd['n']} USDe transfers on 2025-10-10, all unique, all lower-case")
    check = {"schema_ok": True, "partitioning": part, "clustering": clus,
             "freshness_max_block_timestamp": str(mx), "dedupe": {k: int(v) for k, v in dd.items()}}
    update_data_build(checks=check)
    return check


# ---------------------------------------------------------------------------
# --budget
# ---------------------------------------------------------------------------
def _materialized(key: str) -> bool:
    """True when every chunk of the extract already carries a marker whose sql hash matches
    the SQL the current config would run (nothing to bill)."""
    spec = config.BQ_EXTRACTS[key]
    chunks = bq_sql.chunks(spec["start"], spec["end"], spec["chunk_days"])
    ids = bq_sql.extract_table_ids(key)
    for (cs, ce), tid in zip(chunks, ids):
        marker = bq._marker(tid)
        if not marker.exists():
            return False
        if json.loads(marker.read_text()).get("sql_hash") != bq.sql_hash(bq_sql.extract_sql(key, cs, ce)):
            return False
    return True


def stage_budget() -> dict:
    client = bq.get_client()
    plan, total, new_total = {}, 0.0, 0.0
    for key in config.BQ_EXTRACTS:
        spec = config.BQ_EXTRACTS[key]
        mat = _materialized(key)
        rows = []
        for cs, ce in bq_sql.chunks(spec["start"], spec["end"], spec["chunk_days"]):
            gib = bq.dry_run_bytes(bq_sql.extract_sql(key, cs, ce), client) / bq.GIB
            rows.append({"chunk": f"{cs}..{ce}", "gib": round(gib, 2)})
            total += gib
            if not mat:
                new_total += gib
        plan[key] = {"chunks": rows, "gib": round(sum(r["gib"] for r in rows), 2),
                     "materialized": mat, "new_gib": 0.0 if mat else round(sum(r["gib"] for r in rows), 2)}
        _log(f"  {key:14s} {plan[key]['gib']:8.2f} GiB over {len(rows)} chunks"
             f"{'  (materialized, skipped)' if mat else ''}")
    cum = bq.load_ledger().get("cumulative_billed_bytes", 0) / bq.GIB
    headroom = PLANNED_CEILING_GIB - cum
    _log(f"  planned total {total:.2f} GiB, new (not materialized) {new_total:.2f} GiB; ceiling "
         f"{PLANNED_CEILING_GIB:.0f} - billed {cum:.2f} = {headroom:.2f} GiB")
    update_data_build(budget={"plan": plan, "planned_gib": round(total, 2),
                              "planned_new_gib": round(new_total, 2),
                              "headroom_gib": round(headroom, 2)})
    if new_total > NEW_GIB_CEILING:
        raise StageFailed(f"planned new spend {new_total:.1f} GiB > {NEW_GIB_CEILING:.0f} GiB")
    if new_total >= headroom:
        raise StageFailed(f"planned {new_total:.1f} GiB >= headroom {headroom:.1f} GiB")
    if not plan[CORE_KEY]["materialized"] and plan[CORE_KEY]["gib"] > 400:
        # Contingency from BQ_SPEC section 8: needs a decision, not an automatic change.
        raise StageFailed(f"{CORE_KEY} estimate {plan[CORE_KEY]['gib']:.0f} GiB > 400: follow the "
                          f"clustered-column check and FLOW_START contingency in BQ_SPEC section 8")
    return plan


# ---------------------------------------------------------------------------
# --selftest
# ---------------------------------------------------------------------------
def _selftest_frames():
    """Synthetic extract + labels. D1 is a deposit address (2 senders, all swept to Binance
    within hours), D2 splits 50/50 between Binance and OKX, F forwards 30%, W is funded
    by Binance hot itself, and K is a labelled address."""
    h = lambda n: "0x" + f"{n:040x}"            # noqa: E731
    B_HOT, O_HOT = h(0xB1), h(0x0C)
    D1, D2, F, W, K, S1, S2, S3 = (h(x) for x in (0xD1, 0xD2, 0xF0, 0xE0, 0xC0, 0x51, 0x52, 0x53))
    t0 = pd.Timestamp("2025-10-08 00:00:00", tz="UTC")
    rows = []

    def tr(hour, frm, to, usd):
        rows.append({"bucket": t0 + pd.Timedelta(hours=hour), "token": "USDe",
                     "from_a": frm, "to_a": to, "amount": float(usd), "n_tx": 1})
    for hr, s_ in ((0, S1), (1, S2), (3, S3)):      # D1: 3 non-hot senders, 15k in
        tr(hr, s_, D1, 5000)
    tr(2, D1, B_HOT, 6000); tr(9, D1, B_HOT, 6000)  # 12k out, all to Binance (accepted)
    tr(4, S1, D2, 4000); tr(5, D2, B_HOT, 2000); tr(6, D2, O_HOT, 2000)   # 50/50 (rejected)
    tr(3, S2, F, 4000); tr(4, F, B_HOT, 1200); tr(5, F, S3, 2800)        # 30% (rejected)
    tr(7, S3, W, 2000); tr(8, B_HOT, W, 1000)                             # hot-funded (rejected)
    tr(10, S1, K, 2000); tr(10, K, B_HOT, 5000)     # K is labelled: never a candidate
    x = pd.DataFrame(rows)
    labels = pd.DataFrame([
        {"address": B_HOT, "entity": "Binance", "src": "label", "etype": "CEX", "raw_name": "Binance Hot", "source": "selftest"},
        {"address": O_HOT, "entity": "OKX", "src": "label", "etype": "CEX", "raw_name": "OKX Hot", "source": "selftest"},
        {"address": K, "entity": "Binance", "src": "label", "etype": "CEX", "raw_name": "Binance Dep", "source": "selftest"},
    ])
    return x, labels


def _x_schema():
    return [("bucket", "TIMESTAMP"), ("token", "STRING"), ("from_a", "BYTES"),
            ("to_a", "BYTES"), ("amount", "FLOAT64"), ("n_tx", "INT64")]


def stage_selftest() -> dict:
    client = bq.get_client()
    x, labels = _selftest_frames()
    fq_x = fq_l = None
    try:
        xb = x.copy()
        fq_x = bq.upload_dataframe(
            xb.assign(from_a=[bytes.fromhex(a[2:]) for a in xb.from_a],
                      to_a=[bytes.fromhex(a[2:]) for a in xb.to_a]),
            "selftest_x", _x_schema(), client)
        fq_l = bq.upload_dataframe(lb.to_bq_frame(labels), "selftest_labels", lb.BQ_LABEL_SCHEMA, client)
        fp = lb.label_fingerprint(labels)
        usd = {"USDe": 1.0}
        sql = bq_sql.sweep_sql([fq_x], fq_l, fp, ["selftest"], usd, config.SWEEP_PARAMS)
        got = pd.DataFrame(bq.run_sql(sql, name="selftest_sweeps", refresh=True, client=client))
        want = sw.detect_sweeps_frame(x, labels, usd, config.SWEEP_PARAMS)
        _log(f"  sweeps: SQL {len(got)} rows, pandas mirror {len(want)} rows")
        sql_addrs = set(got["address"]) if len(got) else set()
        if sql_addrs != set(want.address):
            raise StageFailed(f"sweep address sets differ: SQL={sorted(sql_addrs)} "
                              f"pandas={sorted(want.address)}")
        if len(want):
            g = got.sort_values("address").reset_index(drop=True)
            w = want.sort_values("address").reset_index(drop=True)
            for c in sw.OUT_COLS[2:]:
                if not np.allclose(g[c].astype(float), w[c].astype(float), rtol=1e-9, atol=1e-9):
                    raise StageFailed(f"sweep column {c} differs between SQL and pandas")
            if not (g.entity.values == w.entity.values).all():
                raise StageFailed("sweep entities differ between SQL and pandas")

        flow = bq_sql.flow_sql([fq_x], fq_l, fp, ["selftest"], "2025-10-08", "2025-10-09",
                               ["USDe"], "hour")
        fr = pd.DataFrame(bq.run_sql(flow, name="selftest_flows", refresh=True, client=client))
        ref = _flow_reference(x, labels)
        tot_sql = float(pd.to_numeric(fr["volume"]).sum()) if len(fr) else 0.0
        tot_ref = float(ref["volume"].sum())
        if not np.isclose(tot_sql, tot_ref, rtol=1e-9):
            raise StageFailed(f"flow volume SQL {tot_sql} != reference {tot_ref}")
        _log(f"  flows: SQL {len(fr)} rows, labelled volume {tot_sql:.1f} == reference")
        if len(want) == 0:
            raise StageFailed("selftest fixture produced no sweep detections; check the fixture")
        result = {"sweeps_sql_rows": int(len(got)), "sweeps_pandas_rows": int(len(want)),
                  "flow_rows": int(len(fr)), "flow_volume_sql": tot_sql, "passed": True}
        update_data_build(selftest=result)
        return result
    finally:
        for fq in (fq_x, fq_l):
            if fq:
                with contextlib.suppress(Exception):
                    client.delete_table(fq, not_found_ok=True)


def _flow_reference(x: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Pandas version of flow_sql's labelled-volume sum (one-side-labelled rows)."""
    ent = dict(zip(labels.address, labels.entity))
    d = x.assign(fe=x.from_a.map(ent), te=x.to_a.map(ent))
    d = d[d.fe.notna() | d.te.notna()]
    return d.groupby(["bucket", "token"], as_index=False)["amount"].sum().rename(columns={"amount": "volume"})


# ---------------------------------------------------------------------------
# --labels (runs without BigQuery)
# ---------------------------------------------------------------------------
SPELLBOOK_NAME = lb.SPELLBOOK
PAPER_ENTITIES = ["Binance", "Coinbase", "OKX", "Bybit", "Bitfinex", "HTX", "Gate.io",
                  "Crypto.com", "Bitget", "Bullish", "Copper", "Ceffu", "FalconX", "Aave",
                  "Ethena", "Lido", "MakerSky"]


def stage_labels() -> dict:
    revs = lb.clone_label_repos()
    repo_dirs = [lb.CACHE_DIR / "labels_src" / name for name in config.LABEL_REPOS]
    discover_out = {}
    for rd in repo_dirs:
        if rd.name in config.LABEL_PINNED:   # pinned sources are parsed by their own reader
            continue
        cap = io.StringIO()
        with contextlib.redirect_stdout(cap):
            lb.discover(rd)
        full = cap.getvalue().rstrip()
        (lb.CACHE_DIR / f"labels_discover_{rd.name}.txt").parent.mkdir(parents=True, exist_ok=True)
        (lb.CACHE_DIR / f"labels_discover_{rd.name}.txt").write_text(full + "\n")
        lines = full.splitlines()
        used = [ln for ln in lines if not ln.endswith("parsed=0")]
        discover_out[rd.name] = {"used": "\n".join(used),
                                 "n_files": len(lines) - 1, "n_used": len(used) - 1 if used else 0}
        _log(f"[discover] {rd.name}: {len(used) - 1} files with records of {len(lines) - 1} "
             f"({lines[-1]})")

    open_df, rep = lb.build_open_label_table(repo_dirs)
    b14 = open_df[open_df.address == "0x28c6c06298d514db089934071355e5743bf21d60"]
    b14_ok = bool(len(b14) == 1 and b14.entity.iloc[0] == "Binance")
    _log(f"  known-good check: Binance 14 -> {b14.entity.tolist() or 'MISSING'}")
    if not b14_ok:
        raise StageFailed("Binance 14 is not mapped to Binance by the open label parser")
    # Redistributable file: MIT sources only (no spellbook rows, no spellbook source tags).
    pub_df, pub_rep = lb.public_table(repo_dirs)
    cache = lb.CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    open_df.to_csv(cache / "labels_open.csv.gz", index=False, compression="gzip")
    pub_df.to_csv(RESULTS / "labels_open.csv.gz", index=False, compression="gzip")

    seed = lb.seed_label_table()
    base = lb.merge_labels(seed, lb.wallet_labels(open_df))   # deposit labels excluded
    base.to_csv(cache / "labels_base.csv.gz", index=False, compression="gzip")
    fp = lb.label_fingerprint(base)

    wal, dep = rep["addresses_per_root_wallet"], rep["addresses_per_root_deposit"]
    seed_n = seed.entity.value_counts().to_dict()
    base_w = base.entity.value_counts().to_dict()
    paper = [{"entity": e, "seed": int(seed_n.get(e, 0)), "open_wallet": int(wal.get(e, 0)),
              "open_deposit": int(dep.get(e, 0)), "base_rows": int(base_w.get(e, 0))}
             for e in PAPER_ENTITIES]

    licences = {name: rep["licence"].get(name) for name in config.LABEL_REPOS}
    summary = {"revisions": revs, "licences": licences, "discover": discover_out,
               "open_addresses": int(len(open_df)), "open_per_root": rep["addresses_per_root"],
               "open_per_root_wallet": wal, "open_per_root_deposit": dep,
               "public_addresses": int(len(pub_df)), "public_per_root": pub_rep["addresses_per_root"],
               "conflicts": rep["conflicts"], "conflicts_involving_spellbook":
                   rep["conflicts_involving_spellbook"], "conflict_examples": rep["conflict_examples"],
               "kind_mixed_addresses": rep["kind_mixed_addresses"],
               "sources": {k: {kk: vv for kk, vv in v.items() if kk != "files"}
                           | {"files_parsed": v["files"]} for k, v in rep["sources"].items()},
               "unmapped_exchange_names": rep["unmapped_exchange_names"],
               "unmapped_spellbook_names": rep["unmapped_spellbook_names"],
               "paper_entities": paper,
               "base_rows": int(len(base)), "base_fingerprint": fp,
               "binance14_ok": b14_ok}
    (cache / "labels_report.json").write_text(json.dumps(summary, indent=2, default=str))
    write_labels_md(summary)
    update_data_build(labels={"revisions": revs, "licences": licences,
                              "open_addresses": summary["open_addresses"],
                              "open_per_root": summary["open_per_root"],
                              "open_per_root_wallet": summary["open_per_root_wallet"],
                              "open_per_root_deposit": summary["open_per_root_deposit"],
                              "public_addresses": summary["public_addresses"],
                              "conflicts": summary["conflicts"],
                              "conflicts_involving_spellbook": summary["conflicts_involving_spellbook"],
                              "sources": {k: {kk: vv for kk, vv in v.items() if kk != "files_parsed"}
                                         for k, v in summary["sources"].items()},
                              "paper_entities": paper,
                              "base_rows": summary["base_rows"], "base_fingerprint": fp})
    _log(f"  open labels: {summary['open_addresses']} addresses, {summary['conflicts']} conflicts; "
         f"public {summary['public_addresses']}; base {summary['base_rows']} rows, fingerprint {fp}")
    return summary


def write_labels_md(s: dict) -> None:
    pinned = set(config.LABEL_PINNED)

    def sc(src: dict, key: str, name: str) -> str:
        return str(src.get(key, 0)) if name in pinned else "-"

    lines = ["# VEIN data build report", "",
             "_Status: labels stage only; the BigQuery stages have not been run yet._", "",
             "Generated by `run_build_data.py --labels`. The BigQuery stages (`--check`, `--budget`, "
             "`--selftest`, `--extract`, `--sweeps`, `--coverage`) have not been run for this build, "
             "so no extract, sweep or coverage number has been produced yet.", "",
             "## Label sources", "",
             "| source | commit | licence | records read | mapped to a root | addresses mapped | "
             "wallet addresses | deposit addresses | excluded: other chain | excluded: not a wallet | "
             "no root |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in config.LABEL_REPOS:
        src = s["sources"].get(name, {})
        lines.append(f"| {name} | `{s['revisions'].get(name)}` | {s['licences'].get(name)} | "
                     f"{src.get('records', 0)} | {src.get('mapped_records', 0)} | "
                     f"{src.get('mapped_addresses', 0)} | {src.get('wallet_addresses', 0)} | "
                     f"{src.get('deposit_addresses', 0)} | {sc(src, 'excluded_other_chain', name)} | "
                     f"{sc(src, 'excluded_non_wallet', name)} | {sc(src, 'unmapped_names', name)} |")
    lines += ["", "Record counts are per file. eth-labels ships each account list twice (CSV and JSON) "
              "and etherscan-labels has per-category and combined copies, so the address column is the "
              "one to read for coverage. `-` marks columns that do not apply to a source.", "",
              "Licences. eth-labels and etherscan-labels are MIT-licensed (copyright notices kept in "
              "their licence files: Dawson Botsford, 2022; Brian Lee Cheow Teng, 2022). The Dune "
              "Spellbook list (`cex_evms_addresses.sql`, sparse clone at the pinned commit above) is "
              "under the Business Source License 1.1, which does not allow us to redistribute it. It is "
              "used only to build the internal label tables. `results/labels_open.csv.gz` is built from "
              "the two MIT sources alone (`vein.labels.public_table`): it has no Spellbook rows and no "
              "Spellbook source tags. The full table, including Spellbook rows, stays in "
              "`data_cache/labels_open.csv.gz`, which is git-ignored.", "",
              "Spellbook rules. Each row maps to a root by its `cex_name`, falling back to its "
              "`distinct_name`. Rows tagged `kaia` in the name are Kaia-chain addresses and are excluded, "
              "because the file has no chain column and the table is Ethereum. Rows whose exchange name "
              "matches but whose name is not a trading wallet (charity, pool, deployer, router, token) "
              "are excluded as non-wallets. Names with `Deposit` are deposit-kind.", "",
              "## Discovery output (`python -m vein.labels --discover <repo>`)", ""]
    for name, info in s["discover"].items():
        groups: dict[str, list[str]] = {}
        for ln in info["used"].splitlines():
            if ": " not in ln or ln.startswith("TOTAL"):
                continue
            fname, rest = ln.split(": ", 1)
            sig = re.sub(r"\s*(rows|parsed)=\S+", "", rest).strip()
            groups.setdefault(sig, []).append(fname)
        lines += [f"### {name}", "",
                  f"{info['n_used']} of {info['n_files']} files gave Ethereum label records; "
                  f"files with none are left out. Full per-file output: "
                  f"`data_cache/labels_discover_{name}.txt`.", "",
                  "| detected format and columns | files | example |", "|---|---|---|"]
        for sig, files in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| `{sig.replace('|', '/')}` | {len(files)} | `{files[0]}` |")
        lines.append("")
    lines += ["## Open label table", "",
              f"- Addresses with one exchange root, all sources (cache `labels_open`): **{s['open_addresses']}**",
              f"- Public table `results/labels_open.csv.gz` (MIT sources only): **{s['public_addresses']}**",
              f"- Addresses dropped as conflicts (two different roots across sources): **{s['conflicts']}**, "
              f"of which {s['conflicts_involving_spellbook']} involve the Spellbook list",
              f"- Addresses labelled both wallet and deposit (kept as deposit): {s['kind_mixed_addresses']}",
              f"- of which wallet-kind (hot, cold, funder): **{sum(s['open_per_root_wallet'].values())}**; "
              f"deposit-kind (`Dep:` or `Deposit` per-user addresses): **{sum(s['open_per_root_deposit'].values())}**",
              f"- Seed + wallet-kind base table (`labels_base`): {s['base_rows']} rows, fingerprint `{s['base_fingerprint']}`",
              f"- Binance 14 (`0x28c6c06298d514db089934071355e5743bf21d60`) mapped to Binance: **{s['binance14_ok']}**", "",
              "### The 17 paper entities", "",
              "Wallet-kind counts used for the entity table. `config seeds` are the hand-curated addresses, "
              "`open wallet` and `open deposit` come from all open sources, and `labels_base rows` is the "
              "entity's row count in the base table (seeds plus open wallets).", "",
              "| entity | config seeds | open wallet | open deposit | labels_base rows |", "|---|---|---|---|---|"]
    for p in s["paper_entities"]:
        lines.append(f"| {p['entity']} | {p['seed']} | {p['open_wallet']} | {p['open_deposit']} | {p['base_rows']} |")
    lines += ["", "### Addresses per exchange root", "",
              "| root | addresses |", "|---|---|"]
    for root, n in sorted(s["open_per_root"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {root} | {n} |")
    dep, wal = s["open_per_root_deposit"], s["open_per_root_wallet"]
    sb_dep = s["sources"].get(SPELLBOOK_NAME, {}).get("deposit_addresses", 0)
    lines += ["", "### Label kind: wallets versus deposit addresses (treatment decision)", "",
              "The open repositories mix operational wallets with per-user deposit addresses "
              "(`Binance Dep: 0x...`, `Bitget Dep: 0x...`), and the Spellbook list adds "
              f"{sb_dep} deposit-kind addresses (`... Deposit N` names). Deposit labels are almost all from "
              "two exchanges: " + ", ".join(f"{k} {v}" for k, v in sorted(dep.items(), key=lambda kv: -kv[1])[:3])
              + ". Used as entity labels they would make Bitget the best-resolved exchange by far "
              "(it would capture most retail-to-exchange volume) for reasons unrelated to size, and "
              "would bias graph centrality and every ranking. Treatment:", "",
              "1. Only wallet-kind labels (plus the config seeds) enter the label tables: they are "
              "the entity labels and the Tier-3 hot set H. Deposit-kind labels are not uploaded.",
              "2. Deposit addresses are found uniformly for every exchange by Tier-0 sweep detection "
              "(one rule, applied to every hot wallet).",
              "3. The deposit-kind labels are kept in `data_cache/labels_open.csv.gz` (column `kind`) as an "
              "independent validation set for Tier-0 (`overlap_deposit_labels` in the sweeps "
              "report), and as ground truth for the Tier-1/2 resolver validation "
              "(`labels_edges`), which must be reported as deposit-dominated.", "",
              "Limitation: Tier-0 can only find deposit addresses of exchanges that have hot-wallet "
              "labels in H, so coverage still differs by exchange (wallet labels per root below).", "",
              "| root | wallet labels | deposit labels |", "|---|---|---|"]
    for root in sorted(set(wal) | set(dep), key=lambda r: -(wal.get(r, 0) + dep.get(r, 0)))[:15]:
        lines.append(f"| {root} | {wal.get(root, 0)} | {dep.get(root, 0)} |")
    lines += ["", "### Unmapped names", ""]
    if s["unmapped_exchange_names"]:
        lines += ["Ethereum explorer labels with an 'exchange' category and no root. Most are DEX or "
                  "protocol contracts (routers, exchange proxies, old Synthetix rate oracles), so no alias "
                  "was added for them.", "",
                  "| name | records |", "|---|---|"]
        for name, n in s["unmapped_exchange_names"][:25]:
            lines.append(f"| {name} | {n} |")
    else:
        lines.append("None: every eth-labels name with an 'exchange' category maps to an exchange root or is excluded.")
    sb = s["sources"].get(SPELLBOOK_NAME, {})
    lines += ["", f"Spellbook rows with no exchange root and no known exchange name: {sb.get('unmapped_names', 0)} "
              "(counts only, since the list is not redistributed; the distinct names are in "
              "`data_cache/labels_report.json`).", "",
              "### Exclusions", "",
              "- `vein.config.LABEL_EXCLUDE` (token, deployer, bridge, router, commerce, airdrop, "
              "nft, governance, pool, vault, swap, exploit, phish, fake) on name and category.",
              "- `vein.labels.NON_CEX_EXCLUDE` (charity, nonprofit, donate, industry recovery, AVS "
              "operator, MEV, proposer fee recipient): Binance Charity and similar wallets are not "
              "trading wallets.",
              "- Token-contract files (`tokens/`, `tokens.csv`, `tokens.json`) and the duplicated "
              "`combined/` folders. Non-Ethereum explorer folders (bscscan, polygonscan, arbiscan, "
              "avalanche, ftmscan, optimism) are skipped by path because they have no chain field.",
              f"- Spellbook rows tagged with another chain (`kaia`): {sb.get('excluded_other_chain', 0)}. "
              f"Spellbook rows that name a known exchange but are not trading wallets: "
              f"{sb.get('excluded_non_wallet', 0)}.", "",
              "## Pending", "",
              "- `--check`: schema, partitioning and clustering of `token_transfers`, freshness "
              "(`MAX(block_timestamp) >= 2026-06-30`), USDe 2025-10-10 dedupe.",
              "- `--budget`, `--selftest`, `--extract all`, `--sweeps`, `--coverage`.", ""]
    DATA_BUILD_MD.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# --extract
# ---------------------------------------------------------------------------
def stage_extract(which: str) -> dict:
    keys = EXTRACT_ORDER if which == "all" else [which]
    out = {}
    client = bq.get_client()
    bq.ensure_dataset(client)
    for key in keys:
        if key not in config.BQ_EXTRACTS:
            raise ValueError(f"unknown extract {key!r}")
        _log(f"  extracting {key} ...")
        ids, hashes = bq_flows.ensure_extract(key)
        out[key] = {"tables": ids, "sql_hashes": hashes}
        if key == "oct25_hourly":
            check_usde_against_dune()
    return out


def stage_labels_epochs(epochs: list[str]) -> dict:
    """Rebuild only the named label epochs from their cached extracts (no full sweep stage)."""
    out = {}
    for epoch in epochs:
        fq, fp = bq_flows.ensure_labels(epoch, refresh=True)
        out[epoch] = {"table": fq, "fingerprint": fp}
        _log(f"  label epoch {epoch}: {fq} ({fp})")
    update_data_build(labels_epochs=out)
    return out


def stage_verify_protocol() -> dict:
    """Check the protocol-level inputs of the hourly Lido and Aave stress.

    (a) the aToken and stETH symbols, from the public tokens table, only when that dry run
    is at most 2 GiB; (b) the hourly stETH series over the Oct-2025 window. Fails when the
    Withdrawal Queue or the mint series is empty, because the redemption signal would then
    be degenerate."""
    client = bq.get_client()
    spec = config.BQ_EXTRACTS["oct25_lido"]
    atokens = [a for a in config.ENTITIES["Aave"]["addresses"] if a not in AAVE_POOLS]
    addrs = atokens + [config.TOKENS["stETH"]]
    lookup_sql = (f"SELECT address, symbol, decimals FROM `bigquery-public-data.crypto_ethereum.tokens` "
                  f"WHERE address IN ({bq_sql.hexlist(addrs)})")
    est = bq.dry_run_bytes(lookup_sql, client) / bq.GIB
    if est <= 2.0:
        rows = bq.run_sql(lookup_sql, name="verify_tokens", client=client)
        symbols = sorted({r["symbol"] for r in rows if r.get("symbol")})
        tokens_lookup = {"rows": [{"address": r["address"], "symbol": r["symbol"]} for r in rows],
                         "symbols_missing_expected": [s for s in PROTOCOL_SYMBOLS if s not in symbols]}
    else:
        tokens_lookup = "skipped"
        _log(f"  token lookup skipped: dry run {est:.2f} GiB > 2 GiB")
    series = bq_flows.lido_series_bq(spec["start"], spec["end"])
    lido = {"hours": int(len(series)),
            "share_hours_wq_in_gt0": float((series["steth_wq_in"] > 0).mean()),
            "sum_wq_in": float(series["steth_wq_in"].sum()),
            "sum_mint": float(series["steth_mint"].sum())}
    _log(f"  lido: {lido}")
    res = {"tokens_lookup": tokens_lookup, "lido": lido}
    update_data_build(protocol_check=res)
    if lido["sum_wq_in"] == 0 or lido["sum_mint"] == 0:
        raise StageFailed(f"Lido series degenerate: {lido}")
    return res


def check_usde_against_dune() -> pd.DataFrame:
    df = bq_flows.usde_daily_bq(dt.date(2025, 10, 8), dt.date(2025, 10, 14))
    got = {d.strftime("%Y-%m-%d"): float(v) / 1e9 for d, v in zip(df["day"], df["usde"])}
    rows, bad = [], []
    for day, dune in DUNE_USDE_BN.items():
        new = got.get(day)
        rel = None if new is None else (new - dune) / dune
        rows.append({"day": day, "dune_bn": dune, "bigquery_bn": new, "rel_diff": rel})
        if new is None or abs(rel) > USDE_TOL:
            bad.append(day)
    _log("  USDe daily check (USD bn):")
    for r in rows:
        _log(f"    {r['day']} dune={r['dune_bn']:.3f} bigquery={r['bigquery_bn'] if r['bigquery_bn'] is None else round(r['bigquery_bn'], 3)} "
             f"rel={None if r['rel_diff'] is None else round(r['rel_diff'] * 100, 2)}%")
    update_data_build(usde_daily=[{"day": r["day"], "usde_bn": r["bigquery_bn"], "dune_bn": r["dune_bn"],
                                   "rel_diff": r["rel_diff"]} for r in rows],
                      usde_daily_check={"tolerance": USDE_TOL, "passed": not bad, "failed_days": bad})
    if bad:
        raise StageFailed(f"USDe differs from Dune by more than {USDE_TOL:.0%} on {bad}")
    return df


# ---------------------------------------------------------------------------
# --sweeps
# ---------------------------------------------------------------------------
def _holdout_mask(addresses: pd.Series) -> pd.Series:
    return addresses.map(lambda a: int(hashlib.sha1(a.encode()).hexdigest(), 16) % 10 < 3)


def validate_tier0(key: str) -> dict:
    """Hold out ~30% of open CEX labels, detect sweeps with the rest, and score the
    detections against the held-out labels (BQ_SPEC section 6)."""
    spec = config.BQ_EXTRACTS[key]
    client = bq.get_client()
    ids, hashes = bq_flows.ensure_extract(key)
    open_df = bq_flows._open_labels()                      # wallet-kind labels only
    hold = _holdout_mask(open_df.address)
    train = open_df[~hold]
    # Holdout = 30% of wallet labels plus every deposit-address label. The deposit labels
    # are never in any label table, so they are an independent check that Tier-0 finds real
    # deposit addresses (Binance and Bitget only: the other exchanges have none).
    holdout = pd.concat([open_df[hold], bq_flows._open_labels(kind="deposit")], ignore_index=True)
    seed = lb.seed_label_table()
    t0 = lb.merge_labels(seed, train)
    fq = bq.upload_dataframe(lb.to_bq_frame(t0), f"labels_t0val_{key}", lb.BQ_LABEL_SCHEMA, client)
    fp = lb.label_fingerprint(t0)
    usd = bq_flows.usd_per_unit(spec["tokens"], spec["start"], spec["end"])
    senders = pd.DataFrame(bq.run_sql(bq_sql.sender_usd_sql(ids, hashes, usd, spec["start"], spec["end"]),
                                      name=f"senders_{key}", client=client))
    results = {}
    for label, params in (("default", config.SWEEP_PARAMS),
                          ("tightened", dict(config.SWEEP_PARAMS, tau=0.9, max_out_cp=2))):
        sql = bq_sql.sweep_sql(ids, fq, fp, hashes, usd, params)
        det = pd.DataFrame(bq.run_sql(sql, name=f"sweeps_t0val_{key}_{label}", client=client),
                           columns=sw.OUT_COLS)
        results[label] = _score(det, holdout, senders, params)
    chosen = "default" if results["default"]["overlap"] >= 20 and results["default"]["precision"] >= 0.9 else "tightened"
    out = {"key": key, "holdout_addresses": int(len(holdout)), "chosen": chosen,
           "acceptance": "precision >= 0.9 on >= 20 overlapping holdout detections", **results}
    return out


def _score(det: pd.DataFrame, holdout: pd.DataFrame, senders: pd.DataFrame, params: dict) -> dict:
    deposit_addrs = set(holdout.loc[holdout.get("kind", "wallet") == "deposit", "address"]) \
        if "kind" in holdout.columns else set()
    hmap = dict(zip(holdout.address, holdout.entity))
    det = det.copy()
    det["holdout_entity"] = det.address.map(hmap)
    overlap = det[det.holdout_entity.notna()]
    n_dep = int(overlap.address.isin(deposit_addrs).sum()) if deposit_addrs else 0
    correct = overlap[overlap.holdout_entity == overlap.entity]
    wrong = overlap[overlap.holdout_entity != overlap.entity]
    prec = len(correct) / len(overlap) if len(overlap) else float("nan")
    s = senders[senders.address.isin(set(holdout.address))].copy() if len(senders) else pd.DataFrame(columns=["address", "out_usd"])
    s = s[s.out_usd >= 1000.0]
    hit = s.address.isin(set(correct.address))
    rec_count = float(hit.mean()) if len(s) else float("nan")
    rec_vol = float(s.loc[hit, "out_usd"].sum() / s.out_usd.sum()) if len(s) and s.out_usd.sum() else float("nan")
    per_ex = (det.groupby("entity").agg(detections=("address", "count"), swept_usd=("to_x_usd", "sum"))
              .reset_index().to_dict(orient="records")) if len(det) else []
    return {"params": params, "detections": int(len(det)), "overlap": int(len(overlap)),
            "correct_root": int(len(correct)), "wrong_root": int(len(wrong)),
            "overlap_deposit_labels": n_dep,
            "precision": None if np.isnan(prec) else round(prec, 4),
            "holdout_senders_ge_1k": int(len(s)),
            "recall_count": None if np.isnan(rec_count) else round(rec_count, 4),
            "recall_volume": None if np.isnan(rec_vol) else round(rec_vol, 4),
            "per_exchange": per_ex}


def stage_sweeps() -> dict:
    out = {"per_extract": {}, "validation": {}, "epochs": {}}
    for key in EXTRACT_ORDER:
        _log(f"  sweeps for {key} ...")
        det = bq_flows.detect_deposit_sweeps_bq(key)
        out["per_extract"][key] = {"detections": int(len(det)),
                                   "swept_usd": float(det.to_x_usd.sum()) if len(det) else 0.0,
                                   "per_exchange": det.groupby("entity").size().to_dict() if len(det) else {}}
        out["validation"][key] = validate_tier0(key)
        v = out["validation"][key]
        _log(f"    holdout precision {v['default']['precision']} on {v['default']['overlap']} overlaps; "
             f"chosen params: {v['chosen']}")
    for epoch in sorted({v["epoch"] for v in config.BQ_EXTRACTS.values()}):
        fq, fp = bq_flows.ensure_labels(epoch, refresh=True)
        out["epochs"][epoch] = {"table": fq, "fingerprint": fp}
        _log(f"  label epoch {epoch}: {fq} ({fp})")
    update_data_build(sweeps=out)
    return out


# ---------------------------------------------------------------------------
# --coverage
# ---------------------------------------------------------------------------
def stage_coverage() -> dict:
    res = {}
    for key in EXTRACT_ORDER + COVERAGE_EXTRA:
        res[key] = bq_flows.coverage_bq(key)
    COVERAGE_JSON.write_text(json.dumps(res, indent=2, default=str))
    write_coverage_md(res)
    update_data_build(coverage_summary={k: {"total_usd": v.get("total_usd"), "shares": v.get("shares")}
                                        for k, v in res.items()},
                      ledger=_ledger_summary(), extract_rows=_extract_markers())
    return res


def _extract_markers() -> dict:
    out = {}
    for p in sorted(bq.CACHE_DIR.glob("bq_mat_x_*.json")):
        m = json.loads(p.read_text())
        out[m["table"].split(".")[-1]] = {"rows": m.get("num_rows"), "bytes": m.get("num_bytes")}
    return out


def write_coverage_md(res: dict) -> None:
    def f(x):
        return f"{x:.2%}"
    lines = ["# Label coverage of on-chain token flows", "",
             "Shares are of total USD flow in each extract window. 'Both labelled, distinct "
             "entities' means both endpoints carry a label and the labels name different "
             "entities (named-to-named flow). 'Both labelled, same entity' is flow between two "
             "addresses of one entity. Mint and burn transfers are reported separately.", "",
             "| extract | window | total USD (bn) | both labelled, distinct entities | both labelled, same entity | one side | neither | mint/burn |",
             "|---|---|---|---|---|---|---|---|"]
    for key, r in res.items():
        sh = r.get("shares") or {}
        win = r.get("window", [None, None])
        lines.append(f"| {key} | {win[0]}..{win[1]} | {r.get('total_usd', 0) / 1e9:.2f} | "
                     f"{f(sh.get('both_resolved_distinct', 0))} | {f(sh.get('both_resolved_same_entity', 0))} | "
                     f"{f(sh.get('one_side', 0))} | {f(sh.get('neither', 0))} | {f(sh.get('mint_burn', 0))} |")
    lines += ["", "## Panel tokens only", "",
              "Restricted to the tokens the hourly stress is built from. 'Distinct named-to-named / "
              "entity-touching' is the share of flow that touches a named entity and is named on both "
              "sides, among flow touching a named entity on at least one side (mint/burn excluded).", "",
              "| extract | panel tokens | total USD (bn) | distinct named-to-named | one side | distinct named-to-named / entity-touching |",
              "|---|---|---|---|---|---|"]
    for key, r in res.items():
        p = r.get("panel_tokens")
        if not p:
            continue
        lines.append(f"| {key} | {', '.join(p['tokens'])} | {p['total_usd'] / 1e9:.2f} | "
                     f"{f(p['both_resolved_distinct'])} | {f(p['one_side'])} | "
                     f"{f(p['named_distinct_share_of_touching'])} |")
    lines.append("")
    for key in ("oct25_hourly",):
        r = res.get(key) or {}
        bt = r.get("by_token_usd") or {}
        tot = r.get("total_usd") or 0
        if tot and "WETH" in bt:
            lines.append(f"WETH is {bt['WETH'] / tot:.1%} of the {key} total USD flow "
                         f"({bt['WETH'] / 1e9:.2f} bn of {tot / 1e9:.2f} bn), so the ETH-denominated "
                         "flow is a large part of the October window; the panel-token table above "
                         "shows the stablecoin and staked-ETH panel separately.")
    COVERAGE_MD.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
STAGES = ["check", "budget", "selftest", "labels", "extract", "sweeps", "coverage",
          "labels_epochs", "verify_protocol"]


def run(stage: str, extract_key: str | None = None) -> None:
    _log(f"== {stage}")
    if stage == "check":
        stage_check()
    elif stage == "budget":
        stage_budget()
    elif stage == "selftest":
        stage_selftest()
    elif stage == "labels":
        stage_labels()
    elif stage == "extract":
        stage_extract(extract_key or "all")
    elif stage == "sweeps":
        stage_sweeps()
    elif stage == "coverage":
        stage_coverage()
    elif stage == "labels_epochs":
        stage_labels_epochs(extract_key.split(","))
    elif stage == "verify_protocol":
        stage_verify_protocol()
    else:
        raise ValueError(stage)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--budget", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--labels", action="store_true")
    ap.add_argument("--extract", metavar="KEY|all", nargs="?", const="all")
    ap.add_argument("--sweeps", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--labels-epochs", metavar="E1,E2", dest="labels_epochs")
    ap.add_argument("--verify-protocol", action="store_true", dest="verify_protocol")
    ap.add_argument("--all", action="store_true", help="run every stage in order, stopping at a failure")
    args = ap.parse_args(argv)

    plan = []
    if args.all:
        plan = [("check", None), ("budget", None), ("selftest", None), ("labels", None),
                ("extract", "all"), ("sweeps", None), ("coverage", None)]
    else:
        if args.check: plan.append(("check", None))
        if args.budget: plan.append(("budget", None))
        if args.selftest: plan.append(("selftest", None))
        if args.labels: plan.append(("labels", None))
        if args.extract is not None: plan.append(("extract", args.extract))
        if args.sweeps: plan.append(("sweeps", None))
        if args.coverage: plan.append(("coverage", None))
        if args.labels_epochs: plan.append(("labels_epochs", args.labels_epochs))
        if args.verify_protocol: plan.append(("verify_protocol", None))
    if not plan:
        ap.print_help()
        return 1
    for stage, key in plan:
        try:
            run(stage, key)
        except StageFailed as e:
            _log(f"STOP at --{stage}: {e}")
            return STOP
        except RuntimeError as e:
            _log(f"STOP at --{stage}: {e}")
            return 2
    _log("all requested stages passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
