#!/usr/bin/env python3
"""Counterfactual attribution under two abduction modes -> results/abduction_lesson.json.

Same hourly context, fit window, event window and settings as run_best.py (vein/pipeline.py,
the SCM fitted on the pre-event hours, s* not used here). The attribution is computed twice:

  * abduction="legacy_zero": event-window shocks are zero (fit-window residuals are undefined on
    the event window). Computed with the reference engine vein.risk.counterfactual_attribution
    for every ordered pair, and cross-checked against vein.fastscm.attribution_matrix.
  * abduction="full": event-window shocks are recovered from the observed path (the mode used by
    run_best.py and the reported results). Computed with fastscm and cross-checked against
    risk.counterfactual_attribution for every pair.

Full-mode point estimates are asserted against results/final_results.json and
results/uncertainty.json (1e-9). The Bybit L_observed is derived from those files as
attribution / share, since neither file stores it directly.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np

from vein import config, fastscm as fs, pipeline as pl, risk
from vein.scm import StructuralCausalModel

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)
SOURCE, TARGET = "Binance", "Bybit"
TOL = 1e-9
MODES = ["legacy_zero", "full"]


def pair_table(nodes, mat, pairs=None):
    """Share and loss for every ordered pair with positive observed loss (share criterion)."""
    out = {}
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i == j or mat["L_obs"][i, j] <= 1e-9:
                continue
            out[(a, b)] = {"L_observed": float(mat["L_obs"][i, j]),
                           "attribution": float(mat["attr"][i, j]),
                           "share": float(mat["share"][i, j])}
    return out


def mode_record(mode, nodes, mat_fast, ref):
    """One JSON block for an abduction mode, from the fastscm matrix (checked vs reference)."""
    ni = nodes.index(SOURCE)
    nj = nodes.index(TARGET)
    pairs = pair_table(nodes, mat_fast)
    bybit_by_source = {s: float(mat_fast["L_obs"][nodes.index(s), nj]) for s in nodes if s != TARGET}
    (mi, mj), mx = max(pairs.items(), key=lambda kv: kv[1]["share"])
    bb = pairs[(SOURCE, TARGET)]
    # the share of a pair with near-zero observed loss is dominated by the denominator
    big = max(((k, v) for k, v in pairs.items() if v["L_observed"] >= 1.0),
              key=lambda kv: kv[1]["share"])
    return {
        "abduction": mode,
        "engine": {"ranking": "vein.fastscm.attribution_matrix",
                   "reference": "vein.risk.counterfactual_attribution"},
        "bybit_L_observed": float(mat_fast["L_obs"][ni, nj]),
        "bybit_L_observed_by_source": {"min": min(bybit_by_source.values()),
                                       "max": max(bybit_by_source.values())},
        "binance_to_bybit": {"L_observed": bb["L_observed"],
                             "attribution": bb["attribution"],
                             "share": bb["share"]},
        "max_share": {"share": mx["share"], "i": mi, "j": mj,
                      "attribution": mx["attribution"], "L_observed": mx["L_observed"]},
        "max_share_L_observed_ge_1": {
            "share": big[1]["share"], "i": big[0][0], "j": big[0][1],
            "L_observed": big[1]["L_observed"]},
        "n_pairs": len(pairs),
        "L_observed_by_entity": {s: float(mat_fast["L_obs"][nodes.index(SOURCE), k])
                                 for k, s in enumerate(nodes)},
        "pairs": [{"i": a, "j": b, **v} for (a, b), v in
                  sorted(pairs.items(), key=lambda kv: -kv[1]["share"])],
        "reference_max_abs_diff": ref,
    }


def main():
    ctx = pl.build_hourly_context(k=12)
    stress, flows, graph = ctx.stress, ctx.flows, ctx.graph
    est_stress = stress[stress.index < pl.EVENT_START]
    est_flows = flows[flows.day < pl.EVENT_START]
    scm = StructuralCausalModel(graph, alpha=1.0).fit(est_stress, est_flows)
    scm.set_flows(flows)
    nodes = list(scm.stress_cols)
    ev = list(stress.index[(stress.index >= pl.EVENT_START) & (stress.index <= pl.EVENT_END)])
    init_stress = est_stress.iloc[-1].to_dict()
    precrisis = {e: float(est_stress[e].median()) for e in stress.columns}
    # the legacy shocks are zero only if no event day is a fit day
    assert not any(d in est_stress.index for d in ev)

    sys = fs.from_scm(scm)
    C_ev = fs.drift(sys, fs.log_flows(scm, ev))
    S_obs = stress.loc[ev, nodes].values.astype(float)
    init_vec = np.array([init_stress[e] for e in nodes], dtype=float)
    pre_vec = np.array([precrisis[e] for e in nodes], dtype=float)
    # run_uncertainty.py starts from the observed row before the window; check they agree
    pos0 = stress.index.get_loc(ev[0])
    assert np.max(np.abs(stress.iloc[pos0 - 1][nodes].values.astype(float) - init_vec)) < TOL

    modes = []
    for mode in MODES:
        mat = fs.attribution_matrix(sys, C_ev, S_obs, init_vec, pre_vec, abduction=mode)
        ref_diff = {"attribution": 0.0, "share": 0.0, "L_observed": 0.0}
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes):
                if i == j:
                    continue
                ref = risk.counterfactual_attribution(scm, a, b, ev, stress.loc[ev, nodes],
                                                      init_stress, precrisis[a], abduction=mode)
                ref_diff["attribution"] = max(ref_diff["attribution"],
                                              abs(mat["attr"][i, j] - ref["attribution"]))
                ref_diff["share"] = max(ref_diff["share"],
                                        abs(mat["share"][i, j] - ref["attribution_share"]))
                ref_diff["L_observed"] = max(ref_diff["L_observed"],
                                             abs(mat["L_obs"][i, j] - ref["L_observed"]))
        assert max(ref_diff.values()) < TOL, (mode, ref_diff)
        print(f"[{mode}] fastscm == risk reference over all ordered pairs: {ref_diff}")
        modes.append(mode_record(mode, nodes, mat, ref_diff))

    # full mode must reproduce the reported point estimates
    full = next(m for m in modes if m["abduction"] == "full")
    final = json.loads((RESULTS / "final_results.json").read_text())
    unc = json.loads((RESULTS / "uncertainty.json").read_text())
    checks = {}
    chan = {(c["i"], c["j"]): c for c in unc["attribution"]["channels"]}
    b2b = chan[(SOURCE, TARGET)]
    checks["binance_to_bybit_attribution"] = abs(full["binance_to_bybit"]["attribution"] - b2b["attribution"])
    checks["binance_to_bybit_share"] = abs(full["binance_to_bybit"]["share"] - b2b["share"])
    checks["bybit_L_observed_from_uncertainty"] = abs(
        full["bybit_L_observed"] - b2b["attribution"] / b2b["share"])
    checks["max_share_vs_uncertainty"] = abs(full["max_share"]["share"]
                                             - unc["attribution"]["max_share"]["point"])
    fin_diffs = []
    for c in final["counterfactual_attribution"]:
        key = (c["i"], c["j"])
        m = next((p for p in full["pairs"] if (p["i"], p["j"]) == key), None)
        fin_diffs.append(abs(m["share"] - c["attribution_share"]))
        fin_diffs.append(abs(m["attribution"] - c["attribution"]))
        fin_diffs.append(abs(m["L_observed"] - c["L_observed"]))
    checks["final_results_top10_max_abs_diff"] = max(fin_diffs)
    for k, v in checks.items():
        assert v < TOL, (k, v)
    print("full-mode checks:", {k: float(f"{v:.3g}") for k, v in checks.items()})

    out = {
        "generated": dt.date.today().isoformat(),
        "data_backend": config.DATA_BACKEND,
        "resolution": "hourly",
        "event_window": [str(ev[0]), str(ev[-1])],
        "fit_window": [str(est_stress.index[0]), str(est_stress.index[-1])],
        "n_entities": len(nodes),
        "source": SOURCE,
        "target": TARGET,
        "pair_criterion": "ordered pairs with L_observed > 1e-9",
        "checks": {"full_vs_reported_points_max_abs_diff": max(checks.values()),
                   "tolerance": TOL,
                   "reported_points": ["results/final_results.json counterfactual_attribution (top 10)",
                                       "results/uncertainty.json attribution.channels and max_share.point"]},
        "modes": modes,
    }
    (RESULTS / "abduction_lesson.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"WROTE {RESULTS / 'abduction_lesson.json'}")


if __name__ == "__main__":
    main()
