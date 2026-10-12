#!/usr/bin/env python3
"""Acceptance checks on the rerun outputs (results/, data_cache/bq_ledger.json).

Every check prints PASS, WARN or FAIL. The exit status is 1 if any check fails; WARN lines
are informational. Run after the full rerun (see the rerun order in the fix spec).
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
ARCHIVE = RESULTS / "v2_bq_initial"
LEDGER = ROOT / "data_cache" / "bq_ledger.json"
GIB = 2 ** 30
LEDGER_CAP_GIB = 338.05
LEDGER_MONTH_CAP_GIB = 950
FIT_STD_MIN = 1e-9
DEFI_ENTITIES = {"Aave", "Lido", "MakerSky", "Ethena", "retail"}
REPORT_DUNE_FILES = ["FINAL_REPORT.md", "VALIDATION.md", "EVALUATION.md", "INTRADAY_A3.md",
                     "ANALYTICS.md"]
REQUIRED = ["final_results.json", "multievent.json", "uncertainty.json", "topk_sensitivity.json",
            "revision.json", "revision2.json", "revision3.json", "coverage.json",
            "hourly_scm_export.json", "FINAL_REPORT.md"]

results: list[tuple[str, str, str]] = []   # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def load(name: str):
    p = RESULTS / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def walk(obj, key: str):
    """Yield every value stored under `key` anywhere in obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _bad_constant(token):
    raise ValueError(token)


# ---------------------------------------------------------------- checks
def check_fit_std():
    """A1: no entity with a degenerate fit-window stress in any hourly run."""
    name = "A1 non-degenerate stress (fit-window std)"
    sources = {"final_results.json": load("final_results.json"),
               "multievent.json": load("multievent.json"),
               "topk_sensitivity.json": load("topk_sensitivity.json"),
               "revision.json": load("revision.json"),
               "revision2.json": load("revision2.json"),
               "revision3.json": load("revision3.json")}
    bad, seen = [], 0
    for fname, obj in sources.items():
        if obj is None:
            continue
        for comp in walk(obj, "stress_components"):
            for e, meta in comp.items():
                seen += 1
                sd = meta.get("fit_std")
                if not finite(sd) or sd <= FIT_STD_MIN:
                    bad.append(f"{fname}:{e}={sd}")
    if not seen:
        record("FAIL", name, "no stress_components found in the hourly outputs")
    elif bad:
        record("FAIL", name, "; ".join(bad[:10]))
    else:
        record("PASS", name, f"{seen} entity records checked")


def check_h1_nodes():
    """A2: all six H1 nodes non-degenerate; H1 n = 6 x event hours."""
    name = "A2 H1 nodes and sample size"
    fr = load("final_results.json")
    if fr is None or "H1" not in fr:
        record("FAIL", name, "final_results.json has no H1 block")
        return
    nodes = fr["H1"].get("comparison_nodes", [])
    comp = fr.get("stress_components")
    if not comp:
        record("FAIL", name, "final_results.json has no stress_components")
        return
    degenerate = [e for e in nodes if not finite(comp.get(e, {}).get("fit_std"))
                  or comp[e]["fit_std"] <= FIT_STD_MIN]
    n_expected = len(nodes) * fr.get("n_event_hours", -1)
    ns = {s["model"]: s.get("n") for s in fr["H1"].get("scores", [])}
    bad_n = {m: n for m, n in ns.items() if n != n_expected}
    if len(nodes) != 6:
        record("FAIL", name, f"expected 6 H1 nodes, found {len(nodes)}")
    elif degenerate:
        record("FAIL", name, f"degenerate H1 nodes: {degenerate}")
    elif bad_n:
        record("FAIL", name, f"H1 n {bad_n} != {n_expected}")
    else:
        record("PASS", name, f"6 nodes, n = {n_expected}")


def check_multievent():
    """A3: every event fitted; fit rows above the power floor; hourly block length 24; daily
    robustness fitted or explicitly underpowered."""
    name = "A3 multi-event fits and power"
    me = load("multievent.json")
    if me is None:
        record("FAIL", name, "multievent.json missing")
        return
    problems = []
    for ev in me.get("events", []):
        label = ev.get("event", "?")
        if not ev.get("ok"):
            problems.append(f"{label}: not ok ({ev.get('reason')})")
            continue
        n_fit, need = ev.get("n_fit_rows"), ev.get("min_rows_required")
        if n_fit is None or need is None:
            problems.append(f"{label}: n_fit_rows / min_rows_required not recorded")
        elif n_fit < need:
            problems.append(f"{label}: {n_fit} fit rows < {need}")
        if ev.get("resolution") == "hour" and ev.get("block_len") != 24:
            problems.append(f"{label}: hourly block_len {ev.get('block_len')} != 24")
        d = ev.get("daily_robustness")
        if d is None:
            problems.append(f"{label}: no daily robustness block")
        elif not d.get("ok") and d.get("reason") != "underpowered":
            problems.append(f"{label}: daily robustness failed ({d.get('reason')})")
        elif not d.get("ok"):
            record("WARN", f"{name} ({label})", "daily robustness explicitly underpowered")
    if problems:
        record("FAIL", name, "; ".join(problems))
    else:
        record("PASS", name, f"{len(me.get('events', []))} events")


def check_uncertainty():
    """A4: 300 coefficient replicates; finite intervals; ranks inside [1, N]."""
    name = "A4 uncertainty bootstrap"
    un = load("uncertainty.json")
    if un is None:
        record("FAIL", name, "uncertainty.json missing")
        return
    problems = []
    if un["settings"].get("n_boot") != 300:
        problems.append(f"n_boot {un['settings'].get('n_boot')} != 300")
    by = un["ranking"]["by_entity"]
    N = len(by)
    for e, rec in by.items():
        for key in ("exported_risk_ci95", "rank_ci95"):
            ci = rec.get(key)
            if not (isinstance(ci, list) and len(ci) == 2 and all(finite(x) for x in ci)):
                problems.append(f"{e}.{key} not finite: {ci}")
        ci = rec.get("rank_ci95")
        if isinstance(ci, list) and len(ci) == 2 and not (1 <= ci[0] <= ci[1] <= N):
            problems.append(f"{e}.rank_ci95 {ci} outside [1, {N}]")
    for ch in un["attribution"].get("channels", []):
        if not all(finite(x) for x in ch.get("share_ci95", [])):
            problems.append(f"channel {ch.get('i')}->{ch.get('j')} share CI not finite")
    if problems:
        record("FAIL", name, "; ".join(problems[:8]))
    else:
        record("PASS", name, f"{N} entities, 300 replicates")


def check_h1_claim():
    """A5: the report claims H1 support only when every CI excludes zero."""
    name = "A5 H1 support claim"
    fr = load("final_results.json")
    path = RESULTS / "FINAL_REPORT.md"
    if fr is None or not path.exists():
        record("FAIL", name, "final_results.json or FINAL_REPORT.md missing")
        return
    supported = bool(fr.get("H1", {}).get("H1_supported"))
    claims = bool(re.search(r"H1 supported", path.read_text(), re.I))
    if claims and not supported:
        record("FAIL", name, "FINAL_REPORT.md claims H1 support but H1_supported is false")
    elif supported and not claims:
        record("WARN", name, "H1_supported is true but FINAL_REPORT.md makes no support statement")
    else:
        record("PASS", name, f"H1_supported={supported}")


def check_placebos():
    """A6: rolling and time-shift placebo p-values present and finite."""
    name = "A6 placebo p-values"
    fr = load("final_results.json")
    pl = (fr or {}).get("placebo", {})
    ps = {k: (pl.get(k) or {}).get("p_value") for k in ("rolling_temporal", "time_shift")}
    bad = [k for k, v in ps.items() if not (finite(v) and 0 <= v <= 1)]
    if bad:
        record("FAIL", name, f"missing or invalid p-value: {bad}")
    else:
        record("PASS", name, ", ".join(f"{k} p={v:.3f}" for k, v in ps.items()))


def check_external_validity():
    """A7: the external-validity test is not vacuous."""
    name = "A7 external validity not vacuous"
    fr = load("final_results.json")
    ev = (fr or {}).get("external_validity", {})
    if "vacuous" not in ev:
        record("FAIL", name, "external_validity.vacuous missing")
    elif ev["vacuous"]:
        record("FAIL", name, "external validity is vacuous (a transmitter or absorber is degenerate)")
    else:
        record("PASS", name, "not vacuous")


def check_h3_distinct():
    """A8: the OC-CoVaR values of the comparison entities are distinct."""
    name = "A8 distinct OC-CoVaR values for comparison entities"
    fr = load("final_results.json")
    if fr is None:
        record("FAIL", name, "final_results.json missing")
        return
    nodes = fr.get("H1", {}).get("comparison_nodes", [])
    oc = {r["entity"]: r["exported_risk"] for r in fr.get("oc_covar_ranking", [])}
    vals = [oc[e] for e in nodes if e in oc]
    dup = [(a, b) for i, a in enumerate(vals) for b in vals[i + 1:] if abs(a - b) <= 1e-12]
    if len(vals) < len(nodes):
        record("FAIL", name, "comparison entities missing from the OC-CoVaR ranking")
    elif dup:
        record("FAIL", name, f"{len(dup)} equal pairs")
    else:
        record("PASS", name, f"{len(vals)} distinct values")


def check_finite_json():
    """A9: no NaN or Infinity in any top-level results JSON."""
    name = "A9 finite numbers in results/*.json"
    bad = []
    for p in sorted(RESULTS.glob("*.json")):
        try:
            json.loads(p.read_text(), parse_constant=_bad_constant)
        except ValueError as ex:
            bad.append(f"{p.name} ({ex})")
    if bad:
        record("FAIL", name, "; ".join(bad))
    else:
        record("PASS", name, "no NaN/Infinity tokens")


def check_ledger():
    """A10: cumulative and monthly billing within the caps."""
    name = "A10 BigQuery ledger caps"
    if not LEDGER.exists():
        record("FAIL", name, "data_cache/bq_ledger.json missing")
        return
    led = json.loads(LEDGER.read_text())
    cum = led.get("cumulative_billed_bytes", 0) / GIB
    months = {m: b / GIB for m, b in led.get("by_month", {}).items()}
    over = {m: round(v, 2) for m, v in months.items() if v > LEDGER_MONTH_CAP_GIB}
    if cum > LEDGER_CAP_GIB or over:
        record("FAIL", name, f"cumulative {cum:.2f} GiB (cap {LEDGER_CAP_GIB}), months over cap {over}")
    else:
        record("PASS", name, f"cumulative {cum:.2f} GiB of {LEDGER_CAP_GIB}")


def check_coverage():
    """A11: distinct-entity volume is a subset of both-labelled volume; named-to-named share of
    the Oct 2025 touching volume is in a plausible band."""
    name = "A11 coverage consistency"
    cov = load("coverage.json")
    if cov is None:
        record("FAIL", name, "coverage.json missing")
        return
    problems = []
    for key, rec in cov.items():
        sh = rec.get("shares", {})
        if "both_resolved_distinct" in sh and "both_resolved" in sh:
            if sh["both_resolved_distinct"] > sh["both_resolved"] + 1e-12:
                problems.append(f"{key}: distinct > both_resolved")
    share = (cov.get("oct25_hourly", {}).get("panel_tokens") or {}).get("named_distinct_share_of_touching")
    if problems:
        record("FAIL", name, "; ".join(problems))
    else:
        record("PASS", name, "distinct <= both_resolved for every extract")
    if share is None:
        record("WARN", name, "oct25 panel_tokens.named_distinct_share_of_touching not recorded")
    elif not 0.005 <= share <= 0.05:
        record("WARN", name, f"named-to-named share of touching volume {share:.2%} outside 0.5-5%")


def check_gross_flow():
    """A12: Aave and MakerSky carry fit-window flow (gross volume above floors)."""
    name = "A12 protocol flow in the fit window"
    fr = load("final_results.json")
    gross = (fr or {}).get("fit_gross_usd")
    if gross is None:
        record("WARN", name, "fit_gross_usd not recorded in final_results.json; not evaluated")
        return
    floors = {"Aave": 1e9, "MakerSky": 1e8}
    zero = [e for e in floors if gross.get(e, 0) <= 0]
    low = [e for e, f in floors.items() if 0 < gross.get(e, 0) < f]
    if zero:
        record("FAIL", name, f"no fit-window flow for {zero}")
    elif low:
        record("WARN", name, f"fit-window gross flow below floor for {low}")
    else:
        record("PASS", name, "Aave and MakerSky carry fit-window flow")


def check_export_stability():
    """A13: CEX event-window stress matches the archived BigQuery run (correlation >= 0.99)."""
    name = "A13 CEX stress stable against the archived run"
    new = load("hourly_scm_export.json")
    old_p = ARCHIVE / "hourly_scm_export.json"
    if new is None or not old_p.exists():
        record("FAIL", name, "hourly_scm_export.json (new or archived) missing")
        return
    old = json.loads(old_p.read_text())
    hours = sorted(set(new["event_stress"]) & set(old["event_stress"]))
    ents = sorted(set(next(iter(new["event_stress"].values()))) & set(next(iter(old["event_stress"].values()))))
    cex = [e for e in ents if e not in DEFI_ENTITIES]
    low = []
    for e in cex:
        a = np.array([new["event_stress"][h][e] for h in hours], dtype=float)
        b = np.array([old["event_stress"][h][e] for h in hours], dtype=float)
        if a.std() == 0 or b.std() == 0:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if r < 0.99:
            low.append(f"{e} r={r:.3f}")
    if low:
        record("WARN", name, "; ".join(low))
    else:
        record("PASS", name, f"{len(cex)} CEX entities, correlation >= 0.99")


def check_dune_text():
    """A14: no Dune wording in the reports of the BigQuery pipeline."""
    name = "A14 no Dune wording in reports"
    hits = []
    for f in REPORT_DUNE_FILES:
        p = RESULTS / f
        if p.exists() and re.search(r"dune", p.read_text(), re.I):
            hits.append(f)
    if hits:
        record("FAIL", name, f"Dune mentioned in {hits}")
    else:
        record("PASS", name, "none in the reports")


def check_files():
    missing = [f for f in REQUIRED if not (RESULTS / f).exists()]
    if missing:
        record("FAIL", "required outputs present", f"missing: {missing}")
    else:
        record("PASS", "required outputs present", f"{len(REQUIRED)} files")


CHECKS = [check_files, check_fit_std, check_h1_nodes, check_multievent, check_uncertainty,
          check_h1_claim, check_placebos, check_external_validity, check_h3_distinct,
          check_finite_json, check_ledger, check_coverage, check_gross_flow,
          check_export_stability, check_dune_text]


def main() -> int:
    for fn in CHECKS:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            record("FAIL", fn.__name__, f"check crashed: {ex!r}")
    for status, name, detail in results:
        print(f"{status:4s} {name}" + (f": {detail}" if detail else ""))
    n_fail = sum(1 for s, _, _ in results if s == "FAIL")
    n_warn = sum(1 for s, _, _ in results if s == "WARN")
    print(f"\n{len(results) - n_fail - n_warn} passed, {n_warn} warnings, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
