#!/usr/bin/env python3
"""Compare the Dune-era (v1) results with the BigQuery rerun and check the manuscript numbers.

The comparison uses a curated map, results/manuscript_numbers_map.json. Each entry names one
printed number of the manuscript (the text anchor, the printed string and its format) and the
JSON path of the value in the old and in the new results. Paths never fall back to searching
for a matching value: a path that does not resolve is reported, not guessed.

Path elements:
  "key"            dict key
  {"field": value} selects the unique element of a list whose fields equal the given values
                   (error if none or several match), e.g. {"entity": "Coinbase"}
  "lo" / "hi"      endpoints of a [lo, hi] interval, only directly after a key ending in ci95
  integers         rejected (positional indices are not allowed)

Each entry's flags: sign flip, >25% change, CI zero-inclusion change (when the entry names the
interval with "ci_path"), MANUSCRIPT_STALE (the printed number is not the new value rounded to
the printed decimals). Entries marked "pending" name results that a later step produces; they
are listed but not compared.

Usage:
  python run_compare.py [--old-dir results/v1_dune] [--new-dir results]
                        [--map results/manuscript_numbers_map.json]
  python run_compare.py --extract-candidates [--tex manuscript/vein_manuscript.tex]

--extract-candidates writes results/manuscript_numbers_candidates.csv: every number of the
manuscript with its context and the leaf of the old results it happens to equal. It is a
curator aid for building the map; the comparison does not read it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MAP_PATH = RESULTS / "manuscript_numbers_map.json"
NUM_RE = re.compile(r"(?<![\w.\\])(\d+(?:\.\d+)?)(\s*\\?%)?")
DOLLAR_RE = re.compile(r"\\\$\s*(\d+(?:\.\d+)?)\s*(\\,)?\s*(bn|billion|m|million|k)?", re.I)
SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
CONTEXT = 60
METHOD_KEYS = ["abduction", "bootstrap", "joint", "block_len", "s_star_window", "s_star_q",
               "data_backend", "generated"]
DIFF_TOL = 0.25
FORMATS = ("num", "pct", "usd", "usd_bn", "usd_m")


# ---------------------------------------------------------------------------
# candidates (curator aid, not used by the comparison)
# ---------------------------------------------------------------------------
def extract_tex_numbers(tex_path: Path) -> list[dict]:
    text = tex_path.read_text(errors="replace")
    lines = text.splitlines()
    sections, cur = {}, "(preamble)"
    for i, line in enumerate(lines, 1):
        m = SECTION_RE.search(line)
        if m:
            cur = m.group(1).strip()
        sections[i] = cur
    flat = "\n".join(lines)
    out = []
    for m in list(DOLLAR_RE.finditer(flat)) + list(NUM_RE.finditer(flat)):
        raw = m.group(0)
        if m.re is NUM_RE and "." not in m.group(1) and not m.group(2):
            continue     # bare integers are too ambiguous (years, counts, labels)
        if m.re is DOLLAR_RE:
            val, unit = m.group(1), (m.group(3) or "").lower()
            fmt = "usd_bn" if unit in ("bn", "billion") else ("usd_m" if unit in ("m", "million") else "usd")
        else:
            val, fmt = m.group(1), ("pct" if m.group(2) else "num")
        start, end = max(0, m.start() - CONTEXT), min(len(flat), m.end() + CONTEXT)
        ctx = re.sub(r"\s+", " ", flat[start:end]).strip()
        line_no = flat.count("\n", 0, m.start()) + 1
        out.append({"line": line_no, "section": sections.get(line_no, ""), "context": ctx,
                    "printed": val, "fmt": fmt, "raw": raw.strip()})
    for k, row in enumerate(out, 1):
        row["id"] = f"N{k:04d}"
    return out


def _leaves(obj, path=()):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and math.isnan(obj):
            return
        yield path, float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, path + (i,))


def _candidate_match(value: float, printed: str, fmt: str) -> bool:
    nd = len(printed.split(".")[1]) if "." in printed else 0
    target = float(printed)
    cands = {"pct": [value * 100, value], "usd_bn": [value / 1e9, value],
             "usd_m": [value / 1e6, value]}.get(fmt, [value])
    for c in cands:
        if round(c, nd) == round(target, nd) and (nd > 0 or abs(c - target) < 0.5):
            return True
    return False


def candidate_rows(rows: list[dict], old_dir: Path) -> list[dict]:
    leaves = []
    for f in sorted(old_dir.glob("*.json")):
        try:
            obj = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for path, v in _leaves(obj):
            leaves.append((f.name, path, v))
    for r in rows:
        hits = [(fn, p, v) for fn, p, v in leaves if _candidate_match(v, r["printed"], r["fmt"])]
        if hits:
            fn, p, v = hits[0]
            r.update(file=fn, json_path=json.dumps(list(p)), old_value=v,
                     ambiguous=len(hits) > 1, confirmed=True)
        else:
            r.update(file="", json_path="", old_value=None, ambiguous=False, confirmed=False)
    return rows


def write_candidates_csv(rows: list[dict], path: Path) -> None:
    cols = ["id", "line", "section", "context", "printed", "fmt", "file", "json_path",
            "old_value", "ambiguous", "confirmed"]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------
_MISSING = object()


def _select(items: list, selector: dict):
    hits = [x for x in items
            if isinstance(x, dict) and all(x.get(k, _MISSING) == v for k, v in selector.items())]
    if not hits:
        raise KeyError(f"no element matches {selector}")
    if len(hits) > 1:
        raise ValueError(f"selector {selector} is ambiguous ({len(hits)} matches)")
    return hits[0]


def resolve(obj, path: list):
    """Value at a curated path. Raises KeyError, ValueError or TypeError if it does not resolve."""
    cur = obj
    for k, p in enumerate(path):
        if isinstance(p, bool) or isinstance(p, int):
            raise ValueError("positional index not allowed")
        if isinstance(p, dict):
            if not isinstance(cur, list):
                raise TypeError(f"selector {p} applied to a non-list")
            cur = _select(cur, p)
        elif isinstance(p, str):
            after_ci = k > 0 and isinstance(path[k - 1], str) and path[k - 1].endswith("ci95")
            if p in ("lo", "hi") and after_ci:
                if not (isinstance(cur, (list, tuple)) and len(cur) == 2):
                    raise ValueError(f"{p} needs a [lo, hi] pair")
                cur = cur[0] if p == "lo" else cur[1]
            elif isinstance(cur, dict):
                if p not in cur:
                    raise KeyError(p)
                cur = cur[p]
            else:
                raise TypeError(f"key {p!r} applied to a non-dict")
        else:
            raise TypeError(f"unsupported path element {p!r}")
    return cur


def _zero_included(ci) -> bool | None:
    if isinstance(ci, (list, tuple)) and len(ci) == 2 and all(_is_num(x) for x in ci):
        return bool(ci[0] <= 0 <= ci[1])
    return None


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (
        isinstance(x, float) and math.isnan(x))


# ---------------------------------------------------------------------------
# map and comparison
# ---------------------------------------------------------------------------
def load_map(path: Path) -> list[dict]:
    doc = json.loads(path.read_text())
    if doc.get("version") != 1:
        raise ValueError(f"{path}: unsupported map version {doc.get('version')!r}")
    entries = doc.get("entries", [])
    ids = [e["id"] for e in entries]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        raise ValueError(f"{path}: duplicate ids {dup}")
    for e in entries:
        if e.get("fmt", "num") not in FORMATS:
            raise ValueError(f"{e['id']}: unknown fmt {e.get('fmt')!r}")
    return entries


def _display(x: float, fmt: str) -> float:
    return {"pct": x * 100, "usd_bn": x / 1e9, "usd_m": x / 1e6}.get(fmt, x)


def printed_matches(value: float, printed: str, fmt: str) -> bool:
    nd = len(printed.split(".")[1]) if "." in printed else 0
    return round(_display(value, fmt), nd) == round(float(printed), nd)


_CACHE: dict = {}


def _load(directory: Path, name: str):
    key = (str(directory), name)
    if key not in _CACHE:
        p = directory / name
        _CACHE[key] = json.loads(p.read_text()) if p.exists() else None
    return _CACHE[key]


def compare_entry(e: dict, old_dir: Path, new_dir: Path) -> dict:
    fmt = e.get("fmt", "num")
    row = {"id": e["id"], "printed": e.get("printed"), "fmt": fmt, "file": e["file"],
           "path": json.dumps(e["path"]), "old": None, "new": None, "delta": None,
           "matches": None, "flags": [], "status": "ok"}
    if e.get("pending"):
        row["status"] = "PENDING"
        row["note"] = e.get("note", "produced by a later step")
        return row
    new_obj = _load(new_dir, e["file"])
    if new_obj is None:
        row["status"] = "MISSING_FILE"
        return row
    try:
        new_val = resolve(new_obj, e["path"])
    except (KeyError, IndexError, ValueError, TypeError) as ex:
        row["status"] = "STRUCTURE_CHANGED"
        row["flags"].append(f"STRUCTURE_CHANGED ({ex})")
        return row
    if not _is_num(new_val):
        row["status"] = "NOT_NUMERIC"
        return row
    row["new"] = float(new_val)

    old_obj = _load(old_dir, e.get("old_file", e["file"]))
    old_val = None
    if old_obj is not None:
        try:
            old_val = resolve(old_obj, e.get("old_path", e["path"]))
        except (KeyError, IndexError, ValueError, TypeError):
            old_val = None
    if _is_num(old_val):
        old = float(old_val)
        row["old"] = old
        row["delta"] = row["new"] - old
        if old * row["new"] < 0:
            row["flags"].append("sign flip")
        rel = abs(row["delta"]) / abs(old) if old else (math.inf if row["delta"] else 0.0)
        if rel > DIFF_TOL:
            row["flags"].append(">25% change")

    if e.get("ci_path"):
        zi_new = None
        try:
            zi_new = _zero_included(resolve(new_obj, e["ci_path"]))
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        zi_old = None
        if old_obj is not None:
            try:
                zi_old = _zero_included(resolve(old_obj, e.get("old_ci_path", e["ci_path"])))
            except (KeyError, IndexError, ValueError, TypeError):
                pass
        if zi_new is not None and zi_old is not None and zi_new != zi_old:
            row["flags"].append("CI zero inclusion change")

    if e.get("printed") is not None:
        row["matches"] = printed_matches(row["new"], e["printed"], fmt)
        if not row["matches"]:
            row["flags"].append("MANUSCRIPT_STALE")
    return row


def compare_map(entries: list[dict], old_dir: Path, new_dir: Path) -> list[dict]:
    _CACHE.clear()
    return [compare_entry(e, old_dir, new_dir) for e in entries]


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.4g}"
    return str(x)


def _matches_cell(m) -> str:
    return {True: "yes", False: "no", None: "-"}[m]


def write_comparison(rows: list[dict], old_dir: Path, new_dir: Path, out_path: Path) -> None:
    status = Counter(r["status"] for r in rows)
    flagged = Counter(f.split(" (")[0] for r in rows if r["status"] != "PENDING" for f in r["flags"])
    lines = ["# Rerun comparison: Dune (v1) vs BigQuery (v2)", "",
             "Generated by `run_compare.py` from `results/manuscript_numbers_map.json`. Each row is one "
             "printed number of the manuscript, with its value at the curated path in the old and new "
             "results. PENDING rows name results that a later step produces.", "",
             "Status: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())), ""]
    if flagged:
        lines.append("Flags: " + ", ".join(f"{k} {v}" for k, v in sorted(flagged.items())))
        lines.append("")
    lines += _header_sections(old_dir, new_dir)
    lines += ["## Numbers", "",
              "| id | printed | old | new | manuscript matches new (rounded) | flags | source |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        src = f"{r['file']} {r['path']}"
        flags = "; ".join(r["flags"]) if r["flags"] else ""
        if r["status"] == "PENDING":
            flags = f"PENDING: {r['note']}"
        elif r["status"] != "ok":
            flags = r["status"] + ("; " + flags if flags else "")
        lines.append(f"| {r['id']} | {r.get('printed') or '-'} | {_fmt(r['old'])} | {_fmt(r['new'])} | "
                     f"{_matches_cell(r['matches'])} | {flags} | {src.replace('|', chr(92) + '|')} |")
    out_path.write_text("\n".join(lines) + "\n")


def _header_sections(old_dir: Path, new_dir: Path) -> list[str]:
    lines = ["## Data changes", ""]
    new_build = new_dir / "data_build.json"
    if new_build.exists():
        nb = json.loads(new_build.read_text())
        lines.append(f"- New data: backend `{nb.get('data_backend')}`, generated {nb.get('generated')}.")
        if "labels" in nb:
            lines.append(f"- Open labels: {nb['labels'].get('open_addresses')} addresses, "
                         f"{nb['labels'].get('conflicts')} conflicts.")
    else:
        lines.append("- No `data_build.json` in the new results: the BigQuery rebuild has not run.")
    lines += ["", "## Method changes", "", "| key | old | new |", "|---|---|---|"]
    for f in ("results.json", "final_results.json"):
        o = (old_dir / f)
        n = (new_dir / f)
        if not (o.exists() and n.exists()):
            continue
        oj, nj = json.loads(o.read_text()), json.loads(n.read_text())
        for k in METHOD_KEYS:
            if k in oj or k in nj:
                lines.append(f"| {f}:{k} | {_fmt(oj.get(k))} | {_fmt(nj.get(k))} |")
    lines += ["", "## Entity set", ""]
    oj = _try_json(old_dir / "results.json")
    nj = _try_json(new_dir / "results.json")
    oe = set((oj or {}).get("entity_types", {}))
    ne = set((nj or {}).get("entity_types", {}))
    lines.append(f"- Old: {sorted(oe) or 'n/a'}")
    lines.append(f"- New: {sorted(ne) or 'n/a'}")
    lines.append(f"- Added: {sorted(ne - oe) or '-'}; removed: {sorted(oe - ne) or '-'}")
    lines += ["", "## Coverage", ""]
    cov = _try_json(new_dir / "coverage.json")
    if cov:
        for k, v in cov.items():
            sh = v.get("shares") or {}
            lines.append(f"- {k}: both resolved {sh.get('both_resolved', 0):.2%} of USD flow "
                         f"(one side {sh.get('one_side', 0):.2%}, neither {sh.get('neither', 0):.2%})")
    else:
        lines.append("- New: no coverage.json yet.")
    lines.append("- Old (paper): about 1% of the $438bn window flow between two named entities.")
    lines.append("")
    return lines


def _try_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old-dir", type=Path, default=RESULTS / "v1_dune")
    ap.add_argument("--new-dir", type=Path, default=RESULTS)
    ap.add_argument("--map", type=Path, default=MAP_PATH)
    ap.add_argument("--tex", type=Path, default=ROOT / "manuscript" / "vein_manuscript.tex")
    ap.add_argument("--extract-candidates", action="store_true",
                    help="write manuscript_numbers_candidates.csv (curator aid) and stop")
    args = ap.parse_args(argv)
    if not args.old_dir.is_dir():
        print(f"old results not found: {args.old_dir} (archive v1 results before the rerun)")
        return 1
    if args.extract_candidates:
        rows = candidate_rows(extract_tex_numbers(args.tex), args.old_dir)
        path = args.new_dir / "manuscript_numbers_candidates.csv"
        write_candidates_csv(rows, path)
        n_conf = sum(1 for r in rows if r["confirmed"])
        print(f"manuscript numbers: {len(rows)} found, {n_conf} with a candidate in the old results; "
              f"wrote {path}")
        return 0
    if not args.map.exists():
        print(f"map not found: {args.map}")
        return 1
    entries = load_map(args.map)
    rows = compare_map(entries, args.old_dir, args.new_dir)
    out = args.new_dir / "RERUN_COMPARISON.md"
    write_comparison(rows, args.old_dir, args.new_dir, out)
    status = Counter(r["status"] for r in rows)
    print(f"compared {len(rows)} mapped numbers: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
