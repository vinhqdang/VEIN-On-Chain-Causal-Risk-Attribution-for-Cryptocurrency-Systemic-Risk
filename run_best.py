#!/usr/bin/env python3
"""VEIN — consolidated best-resolution evaluation (hourly).

The Oct-2025 cascade unfolded in HOURS, and on-chain flows are observed at
block level while entity price feeds are effectively daily/coarse. So the fair
*and* decisive test is to run the whole hypothesis suite at hourly resolution,
where VEIN's structural advantage (real-time observed flows) is real and the
price-estimated baselines get the best intraday data actually available.

Runs at hourly granularity: observed graph + SCM, OC-CoVaR ranking (H3 vs
Delta-CoVaR/MES), counterfactual attribution (H4), edge-reversal falsification
(A3/H2), the H1 head-to-head (observed vs Granger/partial-corr estimated graph),
the 4 causal-validity checks, and VaR backtests. Writes results/FINAL_REPORT.md.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from vein import config, market_data as md, onchain_graph as og
from vein import entity_resolution as er, benchmarks as bm
from vein import validation as val, estimated_graph as eg, falsification as fz, backtest as bt
from vein.scm import StructuralCausalModel
from vein import risk

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

WIN_START = dt.date(2025, 9, 15)        # ~3.5 weeks of pre-event hours to fit f_i
WIN_END = dt.date(2025, 10, 25)
EVENT_START = pd.Timestamp("2025-10-10 00:00")
EVENT_END = pd.Timestamp("2025-10-11 23:00")
CALM_START = pd.Timestamp("2025-09-20 00:00")
CALM_END = pd.Timestamp("2025-09-21 23:00")
TOKENS = ["USDe", "sUSDe", "wBETH", "USDC", "USDT"]
ROLL = 48


def zscore(s, win=ROLL):
    mu = s.rolling(win, min_periods=6).mean()
    sd = s.rolling(win, min_periods=6).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def build_hourly_stress(flows, entities, prices=None):
    """Hourly flow-derived stress + (for Ethena) the USDe peg-deviation signal."""
    idx = pd.DatetimeIndex(sorted(flows["day"].unique()))
    cols = {}
    for e in entities:
        inf = flows[flows.to_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        outf = flows[flows.from_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        tot = inf + outf
        net = ((outf - inf) / tot.rolling(ROLL, min_periods=6).mean().replace(0, np.nan)).fillna(0.0)
        cols[e] = 0.6 * zscore(net) + 0.4 * zscore(tot)
    panel = pd.DataFrame(cols, index=idx).fillna(0.0)
    # augment Ethena with USDe hourly peg deviation if available
    if prices is not None and "USDe" in prices.columns and "Ethena" in panel.columns:
        peg = (1.0 - prices["USDe"].reindex(idx).ffill()).abs()
        panel["Ethena"] = 0.5 * panel["Ethena"] + 0.5 * zscore(peg)
    return panel.fillna(0.0)


def main():
    out = {"generated": "2026-06-30", "resolution": "hourly",
           "window": [str(WIN_START), str(WIN_END)]}

    print("[1] Hourly resolved on-chain flows (Dune) ...")
    flows = er.load_resolved_flows(WIN_START, WIN_END, TOKENS, bucket="hour", min_addr_volume=1e3)
    flows = er.top_k_entities(flows, k=12)
    flows["day"] = pd.to_datetime(flows["day"])
    etypes = er.entity_types(flows)
    entities = sorted(set(flows.from_entity) | set(flows.to_entity) | set(config.ENTITIES))

    print("[2] Hourly prices (DefiLlama) + returns ...")
    prices = md.build_hourly_price_panel(config.MARKET_ASSETS, WIN_START, WIN_END)
    returns = md.log_returns(prices)

    print("[3] Stress + observed graph + SCM ...")
    stress = build_hourly_stress(flows, entities, prices).sort_index()
    graph = og.build_graph(flows, min_usd=1e5)
    est_stress = stress[stress.index < EVENT_START]
    est_flows = flows[flows.day < EVENT_START]
    scm = StructuralCausalModel(graph, alpha=1.0).fit(est_stress, est_flows)
    scm.set_flows(flows)
    ev = list(stress.index[(stress.index >= EVENT_START) & (stress.index <= EVENT_END)])
    init_stress = est_stress.iloc[-1].to_dict()
    precrisis = {e: float(est_stress[e].median()) for e in stress.columns}
    out["n_entities"] = len(stress.columns)
    out["n_fit_hours"] = int(len(est_stress))
    out["n_event_hours"] = len(ev)
    out["graph_edges"] = len(graph["edges"])
    print(f"    {len(stress.columns)} entities, {len(est_stress)} fit hours, {len(ev)} event hours, {len(graph['edges'])} edges")

    print("[4] OC-CoVaR systemic ranking (H3) ...")
    hi = {e: float(np.quantile(stress[e].values, 0.95)) for e in stress.columns}
    oc = risk.systemic_ranking(scm, ev, init_stress, hi, n_sims=150, seed=7)
    out["oc_covar_ranking"] = oc[["entity", "exported_risk"]].to_dict("records")

    print("[5] H1 head-to-head (observed vs estimated graph, hourly) ...")
    comp = [e for e in stress.columns if e in eg.ENTITY_ASSET]
    rp = eg.entity_return_panel(returns, comp)
    rp_est = rp[rp.index < EVENT_START]
    gr = eg.granger_graph(rp_est, alpha=0.10)
    pc = eg.partial_correlation_graph(rp_est, thresh=0.2)
    obs_sub = {"nodes": comp,
               "edges": [e for e in graph["edges"] if e["from"] in comp and e["to"] in comp],
               "parents": {n: [p for p in graph["parents"].get(n, []) if p in comp] for n in comp}}
    ss, fs = stress[comp], flows[flows.from_entity.isin(comp) & flows.to_entity.isin(comp)]
    out["H1"] = val.h1_observed_vs_estimated(
        obs_sub, {"granger": gr, "partial_corr": pc},
        ss[ss.index < EVENT_START], fs[fs.day < EVENT_START], ss, fs, ev)
    out["H1"]["comparison_nodes"] = comp
    out["H1"]["edge_counts"] = {"observed": len(obs_sub["edges"]),
                                "granger": len(gr["edges"]), "partial_corr": len(pc["edges"])}

    print("[6] Counterfactual attribution (H4) ...")
    attrs = []
    for i in ["Ethena", "Binance"]:
        if i not in scm.stress_cols:
            continue
        for j in scm.stress_cols:
            if j != i:
                attrs.append(risk.counterfactual_attribution(
                    scm, i, j, ev, stress, init_stress, precrisis.get(i, 0.0)))
    out["counterfactual_attribution"] = sorted(attrs, key=lambda r: -r["attribution"])[:10]

    print("[7] Falsification (A3/H2) ...")
    out["falsification"] = fz.run_falsification(graph, est_stress, est_flows, stress, flows, ev).to_dict("records")

    print("[8] Validation battery ...")
    out["external_validity"] = val.external_validity(oc)
    out["placebo"] = val.placebo_negative_controls(scm, graph, ev, stress, init_stress, precrisis)
    calm = list(stress.index[(stress.index >= CALM_START) & (stress.index <= CALM_END)])
    out["temporal_placebo"] = val.temporal_placebo(scm, calm, stress, init_stress, precrisis) if calm else {}
    out["confounding_sensitivity"] = val.confounding_sensitivity(scm, stress)
    # resolution robustness: seed-only (Tier-0)
    seeds = set(config.ENTITIES)
    f0 = flows.copy()
    f0["from_entity"] = f0["from_entity"].where(f0["from_entity"].isin(seeds), "retail")
    f0["to_entity"] = f0["to_entity"].where(f0["to_entity"].isin(seeds), "retail")
    f0 = f0[f0.from_entity != f0.to_entity]
    f0 = (f0.groupby(["day", "from_entity", "to_entity"], as_index=False)
            .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum"),
                 from_src=("from_src", "max"), to_src=("to_src", "max")))
    et0 = er.entity_types(f0)
    g0 = og.build_graph(f0, min_usd=1e5)
    s0 = build_hourly_stress(f0, sorted(set(f0.from_entity) | set(f0.to_entity) | seeds), prices).sort_index()
    scm0 = StructuralCausalModel(g0, alpha=1.0).fit(s0[s0.index < EVENT_START], f0[f0.day < EVENT_START]).set_flows(f0)
    hi0 = {e: float(np.quantile(s0[e].values, 0.95)) for e in s0.columns}
    init0 = s0[s0.index < EVENT_START].iloc[-1].to_dict()
    oc0 = risk.systemic_ranking(scm0, ev, init0, hi0, n_sims=150, seed=7)
    out["resolution_robustness"] = val.resolution_robustness(oc, oc0)

    print("[9] Baselines (Delta-CoVaR, MES) + backtests ...")
    dcv = bm.delta_covar(returns, q=0.05)
    mes = bm.mes(returns, q=0.05)
    out["baselines"] = {"delta_covar": dcv[["asset", "delta_covar"]].to_dict("records"),
                        "mes": mes[["asset", "MES"]].to_dict("records")}
    e2a = eg.ENTITY_ASSET
    common = [(e, e2a[e]) for e in oc.entity if e in e2a and e2a[e] in set(dcv.asset)]
    if len(common) >= 3:
        ocs = [oc.set_index("entity").loc[e, "exported_risk"] for e, _ in common]
        dvs = [-dcv.set_index("asset").loc[a, "delta_covar"] for _, a in common]
        out["ranking_agreement"] = {"entities": [e for e, _ in common],
                                    "spearman_oc_vs_deltacovar": float(stats.spearmanr(ocs, dvs)[0])}
    out["backtests"] = {a: bt.backtest_var(returns[a].dropna(), window=72, q=0.05)
                        for a in ["BTC", "ETH"] if a in returns.columns}

    (RESULTS / "final_results.json").write_text(json.dumps(out, indent=2, default=float))
    write_report(out)
    print("Done. Wrote results/FINAL_REPORT.md")


def write_report(out):
    L = []; A = L.append
    h1 = out["H1"]; fal = {r["model"]: r for r in out["falsification"]}
    A("# VEIN — Final Evaluation (Hourly Resolution)\n")
    A(f"_Real Ethereum data, hourly. {out['n_fit_hours']} fit hours + "
      f"{out['n_event_hours']} event hours (Oct 10–11 2025); {out['n_entities']} "
      f"resolved entities; {out['graph_edges']} edges. The cascade timescale is "
      "hours, where on-chain flows are observed but price feeds are coarse._\n")

    # H1 headline
    A("## H1 — observed on-chain graph vs price-estimated graph (decisive)\n")
    A(f"Nodes: {', '.join(h1['comparison_nodes'])}. Edges: {h1['edge_counts']}.\n")
    A("| graph source | RMSE | timing corr | n |\n|---|--:|--:|--:|")
    for s in h1["scores"]:
        A(f"| {s['model']} | {s['rmse']:.4f} | {s['corr']:.4f} | {s['n']} |")
    if "H1_supported" in h1:
        A(f"\n**{'H1 SUPPORTED — observed on-chain graph wins' if h1['H1_supported'] else 'H1 not supported on this slice'}** "
          f"(RMSE gap vs best estimated: {h1.get('rmse_gap_vs_best_estimated', float('nan')):+.4f}).\n")

    A("## Hypotheses & checks\n")
    ra = out.get("ranking_agreement", {})
    oc = out["oc_covar_ranking"]
    A(f"- **H3** (different ranking): OC-CoVaR top transmitters "
      f"{', '.join(r['entity'] for r in oc[:3])}; Spearman vs Δ-CoVaR = "
      f"{ra.get('spearman_oc_vs_deltacovar', float('nan')):.2f} "
      "(lower = more divergent).")
    top = out["counterfactual_attribution"][0] if out["counterfactual_attribution"] else None
    if top:
        A(f"- **H4** (counterfactual): top channel {top['i']}→{top['j']} = "
          f"{top['attribution_share']*100:.1f}% of realized distress.")
    tr, rv = fal["true_direction"]["rmse"], fal["reversed_edges"]["rmse"]
    A(f"- **A3/H2** (direction causal): true {tr:.3f} vs reversed {rv:.3f} RMSE "
      f"→ {'direction informative' if tr < rv*0.98 else 'near-tie / direction weak'}.")
    pb = out["placebo"]
    A(f"- **Placebo**: unconnected-pair attribution max {pb['max_abs_attr_unconnected']:.2e} "
      f"→ {'PASS' if pb['passes'] else 'FAIL'}.")
    rr = out["resolution_robustness"]
    A(f"- **Resolution robustness**: Spearman {rr.get('spearman', float('nan')):.2f} "
      f"(Tier-0 vs Tier-3, {rr.get('n_common', 0)} entities).")
    ev_ = out["external_validity"]
    A(f"- **External validity** (Oct-2025 narrative): transmitter–absorber "
      f"separation {ev_['separation']:.2f}, concordance {ev_['pairwise_concordance']:.2f}.")
    bt_ = out.get("backtests", {})
    if bt_:
        bits = [f"{a}: Kupiec p={b['kupiec']['p_value']:.2f}" for a, b in bt_.items()]
        A(f"- **VaR backtests**: {'; '.join(bits)}.")
    A("")

    A("## Confounding robustness (top edges)\n")
    A("| edge | t | robustness value |\n|---|--:|--:|")
    for e in out["confounding_sensitivity"]["edges"][:6]:
        A(f"| {e['edge']} | {e['t_stat']:.2f} | {e['robustness_value']:.3f} |")
    A("")
    A("## OC-CoVaR systemic ranking\n")
    A("| rank | entity | exported risk |\n|--:|---|--:|")
    for k, r in enumerate(oc[:8], 1):
        A(f"| {k} | {r['entity']} | {r['exported_risk']:.3f} |")
    A("")
    (RESULTS / "FINAL_REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
