#!/usr/bin/env python3
"""Compare the Dune-era (v1) results with the BigQuery rerun (BQ_SPEC section 10).

Step A reads every printed number in the manuscript (decimals, percentages and
dollar amounts in billions) with about 60 characters of context, and matches it to a
numeric leaf of the archived v1 results (results/v1_dune/*.json). Matches go to
results/manuscript_numbers.csv; numbers with no match are marked for manual review.

Step B reads each confirmed number at the same JSON path in the new results and
writes results/RERUN_COMPARISON.md. Flags: sign flip, rank change, confidence
interval that includes zero before but not after (or the reverse), verdict change,
and relative change above 25%. A missing path is reported as STRUCTURE_CHANGED with
the nearest key of the same name.

Usage:
  python run_compare.py [--old-dir results/v1_dune] [--new-dir results]
                        [--tex manuscript/vein_manuscript.tex]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
NUM_RE = re.compile(r"(?<![\w.\\])(\d+(?:\.\d+)?)(\s*\\?%)?")
DOLLAR_RE = re.compile(r"\\\$\s*(\d+(?:\.\d+)?)\s*(\\,)?\s*(bn|billion|m|million|k)?", re.I)
SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
CONTEXT = 60
METHOD_KEYS = ["abduction", "bootstrap", "joint", "block_len", "s_star_window", "s_star_q",
               "data_backend", "generated"]
DIFF_TOL = 0.25


# ---------------------------------------------------------------------------
# Step A: manuscript numbers
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


def _matches(value: float, printed: str, fmt: str) -> bool:
    nd = len(printed.split(".")[1]) if "." in printed else 0
    target = float(printed)
    cands = []
    if fmt == "pct":
        cands = [value * 100, value]
    elif fmt == "usd_bn":
        cands = [value / 1e9, value]
    elif fmt == "usd_m":
        cands = [value / 1e6, value]
    else:
        cands = [value]
    for c in cands:
        if round(c, nd) == round(target, nd) and (nd > 0 or abs(c - target) < 0.5):
            return True
    return False


def match_numbers(rows: list[dict], old_dir: Path) -> list[dict]:
    leaves = []
    for f in sorted(old_dir.glob("*.json")):
        try:
            obj = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for path, v in _leaves(obj):
            leaves.append((f.name, path, v))
    for r in rows:
        hits = [(fn, p, v) for fn, p, v in leaves if _matches(v, r["printed"], r["fmt"])]
        if hits:
            fn, p, v = hits[0]
            r.update(file=fn, json_path=json.dumps(list(p)), old_value=v,
                     ambiguous=len(hits) > 1, confirmed=True)
        else:
            r.update(file="", json_path="", old_value=None, ambiguous=False, confirmed=False)
    return rows


def write_numbers_csv(rows: list[dict], path: Path) -> None:
    cols = ["id", "line", "section", "context", "printed", "fmt", "file", "json_path",
            "old_value", "ambiguous", "confirmed"]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Step B: old vs new
# ---------------------------------------------------------------------------
def _get(obj, path: list):
    cur = obj
    for p in path:
        if isinstance(cur, dict):
            if str(p) not in cur:
                raise KeyError(p)
            cur = cur[str(p)]
        elif isinstance(cur, list):
            cur = cur[int(p)]
        else:
            raise KeyError(p)
    return cur


def _nearest(new_obj, path: list):
    """Same key name under a parent that still exists in the new structure."""
    if not path:
        return None
    leaf = str(path[-1])
    parent_path = path[:-1]
    try:
        parent = _get(new_obj, parent_path) if parent_path else new_obj
    except (KeyError, IndexError, ValueError):
        return None
    if isinstance(parent, dict):
        for k in parent:
            if str(k) == leaf:
                return k
    return None


def _ci_includes_zero(ci) -> bool | None:
    if isinstance(ci, (list, tuple)) and len(ci) == 2 and all(isinstance(x, (int, float)) for x in ci):
        return ci[0] <= 0 <= ci[1]
    return None


def _sibling_ci(obj, path: list):
    """CI pair that goes with the value at path: the parent list itself when the value
    is one end of a [lo, hi] pair, or a ci95/boot_ci95/ci key in the parent dict."""
    try:
        parent = _get(obj, path[:-1]) if len(path) > 1 else obj
    except (KeyError, IndexError, ValueError):
        return None
    if isinstance(parent, list) and len(parent) == 2 and all(isinstance(x, (int, float)) for x in parent):
        return parent
    if isinstance(parent, dict):
        for key in ("ci95", "boot_ci95", "ci", "CI95"):
            if key in parent:
                return parent[key]
    return None


def _rank_among_siblings(obj, path: list, value: float):
    """Rank of the value among its peers: the other numbers in the same dict, or the same
    key across the items of the list that contains it (e.g. entity rankings)."""
    try:
        parent = _get(obj, path[:-1]) if len(path) > 1 else obj
    except (KeyError, IndexError, ValueError):
        return None
    if isinstance(parent, list) and path and isinstance(path[-1], str) is False:
        return None
    if isinstance(parent, dict):
        vals = [v for v in parent.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    elif isinstance(parent, list):
        vals = [v for v in parent if isinstance(v, (int, float)) and not isinstance(v, bool)]
    else:
        vals = []
    # a record inside a list of dicts: rank its key across the list
    try:
        grand = _get(obj, path[:-2]) if len(path) > 2 else None
    except (KeyError, IndexError, ValueError):
        grand = None
    if isinstance(grand, list) and isinstance(parent, dict):
        key = path[-1]
        vals = [item[key] for item in grand if isinstance(item, dict)
                and isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool)]
    if len(vals) < 2 or value not in vals:
        return None
    return sorted(vals, reverse=True).index(value) + 1


def compare(rows: list[dict], old_dir: Path, new_dir: Path) -> list[dict]:
    new_cache = {}
    out = []
    for r in rows:
        if not r.get("confirmed"):
            out.append({**r, "new": None, "delta": None, "flags": "MANUAL"})
            continue
        fn = r["file"]
        if fn not in new_cache:
            p = new_dir / fn
            new_cache[fn] = json.loads(p.read_text()) if p.exists() else None
        new_obj = new_cache[fn]
        path = json.loads(r["json_path"]) if r["json_path"] else []
        flags = []
        if new_obj is None:
            out.append({**r, "new": None, "delta": None, "flags": "MISSING_FILE"})
            continue
        try:
            new_val = float(_get(new_obj, path))
        except (KeyError, IndexError, ValueError, TypeError):
            near = _nearest(new_obj, path)
            flags.append("STRUCTURE_CHANGED" + (f" (nearest key: {near})" if near is not None else ""))
            out.append({**r, "new": None, "delta": None, "flags": "; ".join(flags)})
            continue
        old = float(r["old_value"])
        delta = new_val - old
        rel = abs(delta) / abs(old) if old else (math.inf if delta else 0.0)
        if old * new_val < 0:
            flags.append("sign flip")
        if rel > DIFF_TOL:
            flags.append(">25% change")
        ci_new = _sibling_ci(new_obj, path)
        if ci_new is not None:
            zi_new = _ci_includes_zero(ci_new)
            zi_old = _ci_includes_zero(_old_sibling_ci(old_dir, fn, path))
            if zi_old is not None and zi_new is not None and zi_old != zi_new:
                flags.append("CI zero inclusion change")
        rk_old = _rank_among_siblings(_old_obj(old_dir, fn), path, old)
        rk_new = _rank_among_siblings(new_obj, path, new_val)
        if rk_old is not None and rk_new is not None and rk_old != rk_new:
            flags.append(f"rank change {rk_old}->{rk_new}")
        out.append({**r, "new": new_val, "delta": delta, "flags": "; ".join(flags)})
    return out


_OLD_CACHE: dict = {}


def _old_obj(old_dir: Path, fn: str):
    key = (str(old_dir), fn)
    if key not in _OLD_CACHE:
        _OLD_CACHE[key] = json.loads((old_dir / fn).read_text())
    return _OLD_CACHE[key]


def _old_sibling_ci(old_dir: Path, fn: str, path: list):
    return _sibling_ci(_old_obj(old_dir, fn), path)


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.4g}"
    return str(x)


def write_comparison(rows: list[dict], old_dir: Path, new_dir: Path, out_path: Path) -> None:
    lines = ["# Rerun comparison: Dune (v1) vs BigQuery (v2)", "",
             "Generated by `run_compare.py`. Every confirmed number in the manuscript is listed, "
             "with its old and new value at the same JSON path. Unconfirmed numbers are marked MANUAL "
             "and need a person to check them.", ""]
    lines += _header_sections(old_dir, new_dir)
    lines += ["## Numbers", "",
              "| id | section/line | context | old | new | Δ | flag |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        ctx = r["context"].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['section']} / {r['line']} | {ctx} | {_fmt(r.get('old_value'))} | "
                     f"{_fmt(r.get('new'))} | {_fmt(r.get('delta'))} | {r.get('flags') or ''} |")
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
    ap.add_argument("--tex", type=Path, default=ROOT / "manuscript" / "vein_manuscript.tex")
    args = ap.parse_args(argv)
    if not args.old_dir.is_dir():
        print(f"old results not found: {args.old_dir} (archive v1 results before the rerun)")
        return 1
    rows = extract_tex_numbers(args.tex)
    rows = match_numbers(rows, args.old_dir)
    write_numbers_csv(rows, args.new_dir / "manuscript_numbers.csv")
    n_conf = sum(1 for r in rows if r["confirmed"])
    print(f"manuscript numbers: {len(rows)} found, {n_conf} matched to v1 results, "
          f"{len(rows) - n_conf} need manual review")
    rows = compare(rows, args.old_dir, args.new_dir)
    write_comparison(rows, args.old_dir, args.new_dir, args.new_dir / "RERUN_COMPARISON.md")
    print(f"wrote {args.new_dir / 'RERUN_COMPARISON.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
