"""Open exchange-label table from public label repositories (BQ_SPEC section 5).

Sources (both MIT-licensed, cloned shallow into data_cache/labels_src):
  - dawsbot/eth-labels        data/csv/accounts.csv, data/json/accounts.json
  - brianleect/etherscan-labels  data/etherscan/** (Ethereum mainnet explorer labels)

Each raw label record (address, name, category) is reduced to an exchange root with
normalize_exchange(). An address mapped to two different roots is a conflict and is
dropped. The seed table (config.ENTITIES) always takes priority over open labels.

Run `python -m vein.labels --discover <repo_dir>` to see how each file is parsed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

import pandas as pd

from . import config

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")
MAX_BYTES = 200 * 2 ** 20
SKIP_DIRS = {".git", "node_modules"}
# Explorer directories for other chains. Their files carry no chain field, so
# they are skipped by path, not by content.
NON_ETH_DIRS = {"arbiscan", "avalanche", "bscscan", "ftmscan", "optimism", "polygonscan"}
# Token-contract labels (tokens/ folders, tokens.csv/json) are not wallets, and the
# combined/ folders repeat the per-category wallet files. Both are skipped.
NON_WALLET_DIRS = {"tokens", "combined"}
ETH_CHAIN_IDS = {"1", "ethereum", "eth"}
# Labels that carry an exchange name but are not trading wallets (charity donation
# wallets, MEV/AVS infrastructure). Matched on name and category together.
NON_CEX_EXCLUDE = (r"\b(charity|nonprofit|donate|industry[ -]recovery|avs[ -]operator|"
                   r"mev|proposer[ -]fee[ -]recipient)\b")
_NAME_COLS = ["nametag", "name", "label", "entityname", "entity", "tag"]
_CAT_COLS = ["label", "labels", "category", "type", "labeltype", "tags"]
_CHAIN_COLS = ["chainid", "chain"]


# ---------------------------------------------------------------------------
# cloning and provenance
# ---------------------------------------------------------------------------
def clone_label_repos(dest=CACHE_DIR / "labels_src") -> dict:
    """Shallow-clone (or fast-forward) the label repos. Returns {repo: commit_sha}."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    revs = {}
    for name, url in config.LABEL_REPOS.items():
        path = dest / name
        if (path / ".git").exists():
            subprocess.run(["git", "-C", str(path), "pull", "--ff-only", "--quiet"], check=True)
        else:
            subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(path)], check=True)
        revs[name] = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
    (dest / "REVISIONS.json").write_text(json.dumps(revs, indent=2))
    return revs


def _licence(repo_dir) -> str:
    p = Path(repo_dir) / "LICENSE"
    if not p.exists():
        return "no LICENSE file"
    first = p.read_text(errors="replace").strip().splitlines()
    return first[0] if first else "empty LICENSE file"


# ---------------------------------------------------------------------------
# parsing raw files
# ---------------------------------------------------------------------------
def _norm_col(c) -> str:
    return re.sub(r"[\s_]+", "", str(c)).lower()


def _pick(cols, prefs, exclude=()) -> str | None:
    by_norm = {_norm_col(c): c for c in cols if c not in exclude}
    for p in prefs:
        if p in by_norm:
            return by_norm[p]
    return None


def _addr_col(df: pd.DataFrame) -> str | None:
    best, best_share = None, 0.0
    for c in df.columns:
        vals = df[c].dropna().astype(str).str.strip().str.lower()
        if vals.empty:
            continue
        share = vals.str.match(ADDR_RE).mean()
        if share >= 0.9 and share > best_share:
            best, best_share = c, share
    return best


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v).strip()


def _records_from_frame(df: pd.DataFrame, default_cat: str, source_file: str) -> tuple[list[dict], dict]:
    """Column detection (BQ_SPEC section 5) followed by row extraction."""
    info = {"rows": int(len(df)), "address_col": None, "name_col": None,
            "category_col": None, "chain_col": None}
    if df.empty:
        return [], info
    addr = _addr_col(df)
    if addr is None:
        return [], info
    name = _pick(df.columns, _NAME_COLS, exclude=(addr,))
    cat = _pick(df.columns, _CAT_COLS, exclude=(addr, name))
    chain = _pick(df.columns, _CHAIN_COLS, exclude=(addr,))
    info.update(address_col=str(addr), name_col=name and str(name),
                category_col=cat and str(cat), chain_col=chain and str(chain))
    out = []
    for _, r in df.iterrows():
        if chain is not None:
            cid = _cell(r[chain]).lower()
            if cid and cid not in ETH_CHAIN_IDS:
                continue
        a = _cell(r[addr]).lower()
        if not ADDR_RE.match(a):
            continue
        out.append({"address": a,
                    "name": _cell(r[name]) if name is not None else "",
                    "category": _cell(r[cat]) if cat is not None else default_cat,
                    "source_file": source_file})
    return out, info


def _records_from_json_list(rows: list, default_cat: str, source_file: str) -> tuple[list[dict], dict]:
    flat = []
    for row in rows:
        if isinstance(row, dict):
            flat.append({k: (",".join(map(str, v)) if isinstance(v, list) else v)
                         for k, v in row.items()})
    if not flat:
        return [], {"rows": 0}
    return _records_from_frame(pd.DataFrame(flat, dtype=object), default_cat, source_file)


def _parse_json(obj, stem: str, source_file: str) -> tuple[list[dict], dict]:
    if isinstance(obj, list):
        return _records_from_json_list(obj, stem, source_file)
    if not isinstance(obj, dict):
        return [], {"rows": 0}
    if obj and all(isinstance(v, list) for v in obj.values()):
        # dict whose values are lists of label dicts, keyed by category
        out, info = [], {"rows": 0, "shape": "category->list"}
        for cat, rows in obj.items():
            recs, sub = _records_from_json_list(rows, str(cat), source_file)
            out.extend(recs)
            info["rows"] += sub.get("rows", 0)
        return out, info
    # dict keyed by address
    out, n = [], 0
    for key, val in obj.items():
        n += 1
        a = str(key).strip().lower()
        if not ADDR_RE.match(a):
            continue
        if isinstance(val, dict):
            name = _cell(val.get("name") or val.get("nameTag") or val.get("nametag"))
            cat = _cell(val.get("labels") or val.get("label") or val.get("category")) or stem
            chain = _cell(val.get("chainId") or val.get("chain")).lower()
            if chain and chain not in ETH_CHAIN_IDS:
                continue
        else:
            name, cat = _cell(val), stem
        out.append({"address": a, "name": name, "category": cat, "source_file": source_file})
    return out, {"rows": n, "shape": "address->value", "address_col": "<key>",
                 "name_col": "name|nameTag|value", "category_col": "labels|label|<file stem>"}


def _files(repo_dir) -> Iterator[Path]:
    repo = Path(repo_dir)
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".csv", ".json", ".jsonl"}:
            continue
        rel = p.relative_to(repo).parts
        if any(part in SKIP_DIRS for part in rel):
            continue
        if any(part in NON_ETH_DIRS for part in rel):
            continue
        if any(part in NON_WALLET_DIRS for part in rel) or "tokens" in p.stem.lower():
            continue
        if p.stat().st_size > MAX_BYTES:
            continue
        yield p


def parse_file(path) -> tuple[list[dict], dict]:
    """Records and detection info for one label file."""
    path = Path(path)
    stem = path.stem
    src = str(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df = df.replace({"": None})
        recs, info = _records_from_frame(df, stem, src)
        info["format"] = "csv"
        return recs, info
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(errors="replace").splitlines() if line.strip()]
        recs, info = _records_from_json_list(rows, stem, src)
        info["format"] = "jsonl"
        return recs, info
    obj = json.loads(path.read_text(errors="replace"))
    recs, info = _parse_json(obj, stem, src)
    info["format"] = "json"
    return recs, info


def iter_label_records(repo_dir) -> Iterator[dict]:
    """Yield {address, name, category, source_file} for every valid Ethereum label."""
    for p in _files(repo_dir):
        try:
            recs, _ = parse_file(p)
        except (ValueError, OSError, json.JSONDecodeError, pd.errors.ParserError):
            continue
        yield from recs


# ---------------------------------------------------------------------------
# exchange normalisation
# ---------------------------------------------------------------------------
def label_kind(raw_name) -> str:
    """'deposit' for per-user deposit-address labels ('Binance Dep: 0x...'), else 'wallet'
    (hot, cold, funder and other operational wallets)."""
    return "deposit" if re.search(config.DEPOSIT_LABEL_RE, str(raw_name or "").lower()) else "wallet"


def with_kind(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a 'kind' column (derived from raw_name for tables written without one)."""
    if "kind" in df.columns and df["kind"].astype(str).str.len().gt(0).all():
        return df
    out = df.copy()
    out["kind"] = [label_kind(n) for n in out.get("raw_name", pd.Series([""] * len(out)))]
    return out


def wallet_labels(df: pd.DataFrame) -> pd.DataFrame:
    d = with_kind(df)
    return d[d["kind"] == "wallet"].reset_index(drop=True)


def deposit_labels(df: pd.DataFrame) -> pd.DataFrame:
    d = with_kind(df)
    return d[d["kind"] == "deposit"].reset_index(drop=True)


def normalize_exchange(name, category="") -> str | None:
    """Exchange root for a raw label, or None if the label is not a CEX wallet."""
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if not n:
        return None
    text = f"{n} {str(category or '').lower()}"
    if re.search(config.LABEL_EXCLUDE, text) or re.search(NON_CEX_EXCLUDE, text):
        return None
    for root, pat in config.EXCHANGE_ALIASES:
        if re.search(pat, n):
            return root
    return None


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def build_open_label_table(repo_dirs) -> tuple[pd.DataFrame, dict]:
    """One row per address with a single exchange root, plus a report dict."""
    per_addr: dict[str, Counter] = defaultdict(Counter)
    raw_name: dict[str, str] = {}
    sources: dict[str, set] = defaultdict(set)
    report: dict = {"sources": {}, "unmapped_exchange_names": Counter(), "repo_sha": {},
                    "licence": {}}
    for rd in repo_dirs:
        repo = Path(rd).name
        report["licence"][repo] = _licence(rd)
        try:
            report["repo_sha"][repo] = subprocess.run(
                ["git", "-C", str(rd), "rev-parse", "HEAD"], capture_output=True,
                text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            report["repo_sha"][repo] = None
        st = {"records": 0, "mapped_records": 0, "mapped_addresses": set(),
              "files": Counter()}
        for rec in iter_label_records(rd):
            st["records"] += 1
            st["files"][Path(rec["source_file"]).name] += 1
            root = normalize_exchange(rec["name"], rec["category"])
            if root is None:
                if "exchange" in rec["category"].lower():
                    report["unmapped_exchange_names"][rec["name"] or rec["category"]] += 1
                continue
            st["mapped_records"] += 1
            st["mapped_addresses"].add(rec["address"])
            per_addr[rec["address"]][root] += 1
            sources[rec["address"]].add(repo)
            raw_name.setdefault(rec["address"], rec["name"])
        st["mapped_addresses"] = len(st["mapped_addresses"])
        st["files"] = dict(st["files"])
        report["sources"][repo] = st

    conflicts = {a: dict(c) for a, c in per_addr.items() if len(c) > 1}
    rows = []
    for a, c in per_addr.items():
        if len(c) != 1:
            continue
        root = next(iter(c))
        rows.append({"address": a, "entity": root, "src": "label", "etype": "CEX",
                     "raw_name": raw_name.get(a, ""), "source": "+".join(sorted(sources[a])),
                     "kind": label_kind(raw_name.get(a, ""))})
    df = pd.DataFrame(rows, columns=["address", "entity", "src", "etype", "raw_name", "source",
                                     "kind"])
    df = df.sort_values(["entity", "address"]).reset_index(drop=True)
    report["conflicts"] = len(conflicts)
    report["conflict_examples"] = dict(list(conflicts.items())[:10])
    report["addresses_per_root"] = df.entity.value_counts().to_dict()
    report["addresses_per_root_wallet"] = df[df.kind == "wallet"].entity.value_counts().to_dict()
    report["addresses_per_root_deposit"] = df[df.kind == "deposit"].entity.value_counts().to_dict()
    report["addresses_total"] = int(len(df))
    report["unmapped_exchange_names"] = report["unmapped_exchange_names"].most_common(25)
    return df, report


def seed_label_table() -> pd.DataFrame:
    rows = []
    for name, meta in config.ENTITIES.items():
        etype = "CEX" if meta["type"] == "CEX" else meta["type"]
        for a in meta["addresses"]:
            rows.append({"address": a.lower(), "entity": name, "src": "seed", "etype": etype,
                         "raw_name": name, "source": "config", "kind": "wallet"})
    return pd.DataFrame(rows, columns=["address", "entity", "src", "etype", "raw_name", "source",
                                       "kind"])


_PRIORITY = {"seed": 0, "label": 1, "sweep": 2}


def merge_labels(seed: pd.DataFrame, open_: pd.DataFrame,
                 sweeps: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per address; priority seed > label > sweep."""
    parts = [seed, open_] + ([sweeps] if sweeps is not None and len(sweeps) else [])
    df = pd.concat(parts, ignore_index=True)
    df["_p"] = df["src"].map(_PRIORITY)
    df = df.sort_values(["address", "_p", "entity"]).drop_duplicates("address", keep="first")
    return df.drop(columns="_p").sort_values("address").reset_index(drop=True)


def label_fingerprint(df: pd.DataFrame) -> str:
    lines = sorted(f"{a}|{e}|{s}" for a, e, s in zip(df.address, df.entity, df.src))
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12]


def to_bq_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "address": [bytes.fromhex(a[2:]) for a in df["address"]],
        "entity": df["entity"].astype(str),
        "src": df["src"].astype(str),
        "etype": df["etype"].astype(str),
        "raw_name": df.get("raw_name", pd.Series([""] * len(df))).fillna("").astype(str),
        "source": df.get("source", pd.Series([""] * len(df))).fillna("").astype(str),
    })
    return out


BQ_LABEL_SCHEMA = [("address", "BYTES"), ("entity", "STRING"), ("src", "STRING"),
                   ("etype", "STRING"), ("raw_name", "STRING"), ("source", "STRING")]


# ---------------------------------------------------------------------------
# discovery CLI
# ---------------------------------------------------------------------------
def discover(repo_dir) -> int:
    total = 0
    for p in _files(repo_dir):
        try:
            recs, info = parse_file(p)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"{p.relative_to(repo_dir)}: ERROR {type(e).__name__}: {e}")
            continue
        total += len(recs)
        print(f"{p.relative_to(repo_dir)}: format={info.get('format')} rows={info.get('rows')} "
              f"address={info.get('address_col')} name={info.get('name_col')} "
              f"category={info.get('category_col')} chain={info.get('chain_col')} "
              f"parsed={len(recs)}")
    print(f"TOTAL parsed records: {total}")
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--discover", metavar="REPO_DIR", help="print per-file column detection")
    args = ap.parse_args(argv)
    if args.discover:
        discover(args.discover)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
