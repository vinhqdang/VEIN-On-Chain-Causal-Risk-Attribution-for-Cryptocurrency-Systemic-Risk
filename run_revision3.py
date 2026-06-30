#!/usr/bin/env python3
"""Revision-3: ranking/attribution-level robustness to unobserved confounding.

The Cinelli-Hazlett robustness values (RV) reported in the manuscript are
coefficient-level diagnostics: they bound how much hidden-confounder variance
each single structural edge could absorb before its point estimate is
nullified. They do not by themselves show that the *systemic-importance
ranking* or the *attribution shares* downstream of those edges are robust.
This script closes that gap with two checks:

  (1) Drop-low-RV: remove the quartile of structural edges with the smallest
      robustness value from the graph (the edges most vulnerable to a hidden
      confounder) and recompute the OC-CoVaR exported-risk ranking; report
      Spearman rank correlation against the full-graph ranking.
  (2) Latent-shock: inject a shared AR(1) latent factor into every entity's
      stress series (a synthetic unobserved confounder correlated with all
      nodes, the kind of shock an off-chain CEX engine could in principle
      produce), refit the SCM on the confounded series, and recompute the
      ranking; report Spearman rank correlation against the uncontaminated
      ranking, at two latent-shock strengths.

Writes results/revision3.json.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from vein import config, market_data as md, onchain_graph as og
from vein import entity_resolution as er, validation as val
from vein.scm import StructuralCausalModel
from vein import risk
import run_best as rb
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
rng = np.random.default_rng(11)


def det_exported(scm, ev_days, init_stress, hi, zero):
    """Deterministic exported-risk proxy: sum_j max(L_j(do hi) - L_j(do 0), 0)."""
    scores = {}
    for i in scm.stress_cols:
        tot = 0.0
        for j in scm.stress_cols:
            if j == i:
                continue
            hi_loss = risk.loss_functional(scm.simulate(ev_days, init_stress, zero,
                                                         do={i: np.full(len(ev_days), hi[i])})[j].values)
            lo_loss = risk.loss_functional(scm.simulate(ev_days, init_stress, zero,
                                                         do={i: np.zeros(len(ev_days))})[j].values)
            tot += max(hi_loss - lo_loss, 0.0)
        scores[i] = tot
    return pd.Series(scores).sort_values(ascending=False)


def main():
    out = {"generated": "2026-06-30"}
    print("[1] Rebuild the consolidated hourly pipeline (graph, stress, SCM) ...")
    flows = er.load_resolved_flows(rb.WIN_START, rb.WIN_END, rb.TOKENS, bucket="hour", min_addr_volume=1e3)
    flows = er.top_k_entities(flows, k=12)
    flows["day"] = pd.to_datetime(flows["day"])
    entities = sorted(set(flows.from_entity) | set(flows.to_entity) | set(config.ENTITIES))
    prices = md.build_hourly_price_panel(config.MARKET_ASSETS, rb.WIN_START, rb.WIN_END)
    stress = rb.build_hourly_stress(flows, entities, prices).sort_index()
    graph = og.build_graph(flows, min_usd=1e5)
    est_stress = stress[stress.index < rb.EVENT_START]
    est_flows = flows[flows.day < rb.EVENT_START]
    ev = list(stress.index[(stress.index >= rb.EVENT_START) & (stress.index <= rb.EVENT_END)])
    init_stress = est_stress.iloc[-1].to_dict()
    hi = {e: float(np.quantile(stress[e].values, 0.95)) for e in stress.columns}
    zero = {n: np.zeros(len(ev)) for n in graph["nodes"]}

    scm = StructuralCausalModel(graph, alpha=1.0).fit(est_stress, est_flows).set_flows(flows)
    base = det_exported(scm, ev, init_stress, hi, zero)
    out["base_top5"] = list(base.index[:5])

    print("[2] Confounding sensitivity (Cinelli-Hazlett RV per edge) ...")
    sens = val.confounding_sensitivity(scm, stress)
    rv_by_edge = {r["edge"]: r["robustness_value"] for r in sens["edges"]}
    out["n_edges_with_rv"] = len(rv_by_edge)

    print("[3] Drop-low-RV robustness ...")
    all_rows = []
    for child in scm.stress_cols:
        par = scm.coef_[child]["parents"]
        y = stress[child].values[1:]
        feats = [stress[p].values[:-1] for p in par] if par else []
        if feats:
            X = np.column_stack([np.ones_like(y)] + feats)
            _, t, dof = val._ols_t(y, X)
            for k, p in enumerate(par):
                all_rows.append({"parent": p, "child": child,
                                  "rv": val.robustness_value(t[k + 1], dof)})
    rv_df = pd.DataFrame(all_rows).sort_values("rv")
    n_drop = max(1, len(rv_df) // 4)
    drop_set = set(zip(rv_df.parent.iloc[:n_drop], rv_df.child.iloc[:n_drop]))
    out["drop_low_rv"] = {"n_total_edges": len(rv_df), "n_dropped": n_drop,
                          "dropped": [f"{p}->{c}" for p, c in drop_set]}

    graph_dropped = {"nodes": graph["nodes"], "parents": {}, "edges": []}
    for n in graph["nodes"]:
        graph_dropped["parents"][n] = [p for p in graph["parents"].get(n, [])
                                        if (p, n) not in drop_set]
    for e in graph["edges"]:
        if (e["from"], e["to"]) not in drop_set:
            graph_dropped["edges"].append(e)
    scm_dropped = StructuralCausalModel(graph_dropped, alpha=1.0).fit(est_stress, est_flows).set_flows(flows)
    r_dropped = det_exported(scm_dropped, ev, init_stress, hi, zero)
    common = [e for e in base.index if e in r_dropped.index]
    rho_dropped, _ = spearmanr(base.loc[common].values, r_dropped.loc[common].values)
    out["drop_low_rv"]["ranking_spearman_vs_base"] = float(rho_dropped)
    out["drop_low_rv"]["top5_after_drop"] = list(r_dropped.index[:5])
    out["drop_low_rv"]["top3_overlap"] = len(set(base.index[:3]) & set(r_dropped.index[:3])) / 3.0

    print("[4] Latent common-shock robustness ...")
    latent_results = {}
    n = len(stress)
    for strength, tag in [(0.3, "moderate"), (0.6, "strong")]:
        eps = rng.normal(0, 1, n)
        latent = pd.Series(eps, index=stress.index)
        for t in range(1, n):
            latent.iloc[t] = 0.7 * latent.iloc[t - 1] + eps[t]
        latent = (latent - latent.mean()) / latent.std()
        stress_confounded = stress.add(strength * latent, axis=0)
        est_confounded = stress_confounded[stress_confounded.index < rb.EVENT_START]
        scm_c = StructuralCausalModel(graph, alpha=1.0).fit(est_confounded, est_flows).set_flows(flows)
        init_c = est_confounded.iloc[-1].to_dict()
        hi_c = {e: float(np.quantile(stress_confounded[e].values, 0.95)) for e in stress_confounded.columns}
        r_c = det_exported(scm_c, ev, init_c, hi_c, zero)
        common_c = [e for e in base.index if e in r_c.index]
        rho_c, _ = spearmanr(base.loc[common_c].values, r_c.loc[common_c].values)
        latent_results[tag] = {"strength": strength, "ranking_spearman_vs_base": float(rho_c),
                               "top5": list(r_c.index[:5]),
                               "top3_overlap": len(set(base.index[:3]) & set(r_c.index[:3])) / 3.0}
    out["latent_shock"] = latent_results

    (RESULTS / "revision3.json").write_text(json.dumps(out, indent=2, default=float))
    print("WROTE results/revision3.json")
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
