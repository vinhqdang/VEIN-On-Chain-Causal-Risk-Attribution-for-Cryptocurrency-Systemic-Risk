#!/usr/bin/env python3
"""VEIN analytic checks on the daily SCM archived in results/results.json.

Needs no Dune data or API key. It computes, from the archived coefficients:
  - flow-free bounds on the OC-CoVaR change (Prop A) and the minimum stress
    scale s* that would be needed to reproduce each stored exported risk;
  - the spectral radius and steady-state multipliers of the coefficient matrix;
  - exact Shapley attributions for the linear game, checked against brute force
    (closed-form walks vs subset enumeration vs permutation enumeration), and
    the timing of exact subset enumeration for a 13-player target;
  - the certified radius of the top of the exported-risk ranking.

The Shapley checks use a synthetic deviation path (seed 7) and are labelled as
such. Writes results/analytics.json and results/ANALYTICS.md.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from vein import analytics as an

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SEED = 7
SHAPLEY_TARGETS = ["Bitfinex", "Aave", "Bybit", "Crypto.com", "OKX"]
TIMING_TARGET = "retail"
PERM_MAX_P = 7


def bounds_table(S):
    """Prop A bounds per entity at unit s*, next to the stored exported risk."""
    A, T = S["A"], S["T"]
    rows = []
    for e in S["entities"]:
        i = S["ix"][e]
        b = an.oc_bounds(A, i, T, 1.0)
        b_plus = b["exported_upper"]
        stored = S["stored_E"][e]
        if b_plus == 0.0 and stored == 0.0:
            status = "zero_predicted_zero_observed"
        elif b_plus == 0.0:
            status = "VIOLATION"
        else:
            status = "bounded"
        rows.append({
            "entity": e,
            "stored_E": stored,
            "B_plus_per_unit": b_plus,
            "implied_min_s_star": stored / b_plus if b_plus > 0 else None,
            "infinite_horizon_multiplier": an.infinite_horizon_multiplier(A, i),
            "status": status,
        })
    return rows


def shapley_checks(S, d):
    """Closed-form vs subsets vs permutations on the synthetic deviation path d."""
    A, T, ix = S["A"], S["T"], S["ix"]
    rng = np.random.default_rng(SEED + 1)
    out = {"targets": [], "skipped": [], "walk_vs_subsets_max": 0.0,
           "subsets_vs_permutations_max": 0.0, "efficiency_max": 0.0}
    for name in SHAPLEY_TARGETS:
        if name not in ix:
            out["skipped"].append({"target": name, "reason": "not an entity"})
            continue
        players = [ix[p] for p in S["parents"][name]]
        if len(players) < 2:
            out["skipped"].append({"target": name, "reason": "fewer than 2 players"})
            continue
        j = ix[name]
        value = lambda K: an.linear_value(A, j, K, d, T)
        walk = an.walk_shapley_linear(A, j, players, d, T)
        subs = an.exact_shapley_subsets(value, players)
        eff = abs(sum(subs.values()) - value(frozenset(players)))
        walk_diff = max(abs(walk[k] - subs[k]) for k in players)
        row = {
            "target": name,
            "players": [S["entities"][k] for k in players],
            "p": len(players),
            "phi_closed_form": {S["entities"][k]: walk[k] for k in players},
            "phi_subsets": {S["entities"][k]: subs[k] for k in players},
            "max_abs_diff_closed_vs_subsets": walk_diff,
            "efficiency_residual": eff,
        }
        if len(players) <= PERM_MAX_P:
            perms = an.exact_shapley_permutations(value, players)
            perm_diff = max(abs(perms[k] - subs[k]) for k in players)
            row["max_abs_diff_subsets_vs_permutations"] = perm_diff
            out["subsets_vs_permutations_max"] = max(out["subsets_vs_permutations_max"], perm_diff)
        # Hinge illustration: positive-part loss on a synthetic factual path
        s_fact = rng.normal(size=T)
        hinge = an.exact_shapley_subsets(
            lambda K: an.hinge_value(A, j, K, d, T, s_fact), players)
        row["hinge_max_abs_diff_vs_linear"] = max(abs(hinge[k] - subs[k]) for k in players)
        out["walk_vs_subsets_max"] = max(out["walk_vs_subsets_max"], walk_diff)
        out["efficiency_max"] = max(out["efficiency_max"], eff)
        out["targets"].append(row)
    return out


def timing_check(S, d):
    """Exact subset Shapley for the largest target, timed on this machine."""
    A, T, ix = S["A"], S["T"], S["ix"]
    j = ix[TIMING_TARGET]
    players = [ix[p] for p in S["parents"][TIMING_TARGET]]
    value = lambda K: an.linear_value(A, j, K, d, T)
    t0 = time.perf_counter()
    subs = an.exact_shapley_subsets(value, players)
    seconds = time.perf_counter() - t0
    walk = an.walk_shapley_linear(A, j, players, d, T)
    return {
        "target": TIMING_TARGET,
        "p": len(players),
        "n_evaluations": 2 ** len(players),
        "seconds": seconds,
        "machine_dependent": True,
        "closed_vs_subsets_max": max(abs(walk[k] - subs[k]) for k in players),
    }


def evaluation_counts():
    return [{"p": p, "subsets": 2 ** p, "permutations": math.factorial(p) * p}
            for p in range(3, 14)]


def main():
    S = an.load_daily_scm(RESULTS / "results.json")
    A, T, names = S["A"], S["T"], S["entities"]
    rho = an.spectral_radius(A)
    rng = np.random.default_rng(SEED)
    d = rng.normal(size=(T, len(names)))

    bounds = bounds_table(S)
    n_zero = sum(1 for r in bounds if r["B_plus_per_unit"] == 0.0)
    n_viol = sum(1 for r in bounds if r["status"] == "VIOLATION")
    shap = shapley_checks(S, d)
    timing = timing_check(S, d)

    cr = an.certified_radius(A, T, top_k=5)
    cr_named = {
        "Lambda": {names[i]: v for i, v in cr["Lambda"].items()},
        "ranking": [names[i] for i in cr["ranking"]],
        "pairs": [],
    }
    for p in cr["pairs"]:
        a, b = p["pair"]
        cr_named["pairs"].append({"pair": [names[a], names[b]], "gap": p["gap"],
                                  "eps_star": p["eps_star"],
                                  "at_least_one": p["at_least_one"]})

    out = {
        "spec": "daily (results/results.json)",
        "source": "results/results.json",
        "T": T,
        "n_entities": len(names),
        "spectral_radius": rho,
        "bounds": bounds,
        "n_zero_predicted": n_zero,
        "n_violations": n_viol,
        "shapley_verification": {"seed": SEED, "synthetic": True, **shap},
        "evaluation_counts": evaluation_counts(),
        "retail_subset_timing_seconds": timing,
        "certified_radius": cr_named,
    }
    (RESULTS / "analytics.json").write_text(json.dumps(out, indent=2, default=float))
    (RESULTS / "ANALYTICS.md").write_text(write_report(out))
    print(f"rho(A)={rho:.4f}  zero-predicted={n_zero}  violations={n_viol}  "
          f"walk-vs-subsets={shap['walk_vs_subsets_max']:.2e}  "
          f"retail subsets={timing['seconds']:.3f}s")
    print("Wrote results/analytics.json and results/ANALYTICS.md")


def _g(x, nd=3):
    """Three significant figures for the Markdown tables; '-' for missing."""
    return "-" if x is None else f"{x:.{nd}g}"


def write_report(out):
    L = []
    A = L.append
    A("# VEIN analytic checks (daily specification)\n")
    A(f"_Source: results/results.json (daily SCM, T = {out['T']} event days, "
      f"{out['n_entities']} entities). Hourly coefficients are not archived, so "
      "every number here refers to the daily specification. The Shapley checks "
      "use a synthetic deviation path (seed 7)._\n")
    A(f"- Spectral radius of the daily coefficient matrix: {out['spectral_radius']:.3f}")
    A(f"- Entities with zero flow-free bound: {out['n_zero_predicted']}")
    A(f"- Violations of the bound (stored exported risk > 0 with zero bound): {out['n_violations']}\n")

    A("## Flow-free bounds (Prop A) and stored exported risk\n")
    A("B+ is the exported bound per unit of s*. The implied minimum s* is the "
      "scale at which the bound would just reproduce the stored exported risk.\n")
    A("| entity | stored E (MC) | B+ per unit s* | implied min s* | infinite-horizon multiplier | status |")
    A("|---|--:|--:|--:|--:|---|")
    for r in sorted(out["bounds"], key=lambda r: (-r["stored_E"], -r["B_plus_per_unit"])):
        A(f"| {r['entity']} | {_g(r['stored_E'])} | {_g(r['B_plus_per_unit'])} | "
          f"{_g(r['implied_min_s_star'])} | {_g(r['infinite_horizon_multiplier'])} | {r['status']} |")
    A("")

    sv = out["shapley_verification"]
    A("## Shapley verification (synthetic deviation path)\n")
    A(f"- Closed-form walks vs exact subset enumeration, max absolute difference: {sv['walk_vs_subsets_max']:.2e}")
    A(f"- Subset enumeration vs permutation enumeration (p <= {PERM_MAX_P}), max absolute difference: {sv['subsets_vs_permutations_max']:.2e}")
    A(f"- Efficiency residual (sum of values minus grand-coalition value), max: {sv['efficiency_max']:.2e}\n")
    A("| target | players | p | closed vs subsets | efficiency | subsets vs permutations | hinge vs linear (synthetic S_fact) |")
    A("|---|---|--:|--:|--:|--:|--:|")
    for r in sv["targets"]:
        A(f"| {r['target']} | {', '.join(r['players'])} | {r['p']} | "
          f"{r['max_abs_diff_closed_vs_subsets']:.2e} | {r['efficiency_residual']:.2e} | "
          f"{_g(r.get('max_abs_diff_subsets_vs_permutations'), 2) if 'max_abs_diff_subsets_vs_permutations' in r else 'n/a'} | "
          f"{r['hinge_max_abs_diff_vs_linear']:.3g} |")
    for s in sv["skipped"]:
        A(f"\nSkipped {s['target']}: {s['reason']}.")
    A("")

    A("## Evaluation counts\n")
    A("| players p | subset enumeration 2^p | permutation enumeration p! x p |")
    A("|--:|--:|--:|")
    for r in out["evaluation_counts"]:
        A(f"| {r['p']} | {r['subsets']:,} | {r['permutations']:,} |")
    tm = out["retail_subset_timing_seconds"]
    A(f"\nExact subset Shapley for {tm['target']} (p = {tm['p']}, {tm['n_evaluations']:,} "
      f"evaluations): {tm['seconds']:.3f} s on this machine (machine-dependent). "
      f"Closed-form vs subsets max difference: {tm['closed_vs_subsets_max']:.2e}.\n")

    cr = out["certified_radius"]
    A("## Certified ranking radius\n")
    A(f"Top of the ranking by Lambda_i (daily exported mass): {', '.join(cr['ranking'])}.\n")
    A("| pair | gap in Lambda | certified eps* | certified at eps = 1 |")
    A("|---|--:|--:|---|")
    for p in cr["pairs"]:
        A(f"| {p['pair'][0]} > {p['pair'][1]} | {_g(p['gap'])} | {_g(p['eps_star'])} | "
          f"{'yes' if p['at_least_one'] else 'no'} |")
    A("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
