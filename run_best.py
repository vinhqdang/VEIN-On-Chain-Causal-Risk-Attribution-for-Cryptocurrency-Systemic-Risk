#!/usr/bin/env python3
"""VEIN — consolidated best-resolution evaluation (hourly).

The Oct-2025 cascade unfolded in HOURS, and on-chain flows are observed at
block level while entity price feeds are effectively daily/coarse. So the fair
*and* decisive test is to run the whole hypothesis suite at hourly resolution,
where VEIN's structural advantage (real-time observed flows) is real and the
price-estimated baselines get the best intraday data actually available.

Runs at hourly granularity on the BigQuery cache (vein/pipeline.py): observed graph + SCM,
OC-CoVaR ranking (H3 vs Delta-CoVaR/MES), counterfactual attribution (H4), edge-reversal
falsification (A3/H2) with paired bootstrap intervals, the H1 head-to-head (observed vs
Granger/partial-corr estimated graph, paired block bootstrap), the causal-validity placebos,
and VaR backtests. Writes results/final_results.json and results/FINAL_REPORT.md.
"""
from __future__ import annotations

import datetime as dt
import json
import numpy as np
from pathlib import Path

import pandas as pd
from scipy import stats

from vein import config, market_data as md, onchain_graph as og
from vein import benchmarks as bm
from vein import validation as val, estimated_graph as eg, falsification as fz, backtest as bt
from vein import pipeline as pl, hourly_stress as hs, fastscm as fs, uncertainty as un
from vein.scm import StructuralCausalModel
from vein import risk

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

WIN_START = pl.WIN_START                # ~3.5 weeks of pre-event hours to fit f_i
WIN_END = pl.WIN_END
EVENT_START = pl.EVENT_START
EVENT_END = pl.EVENT_END
TOKENS = pl.TOKENS
ROLL = hs.ROLL
ABDUCTION = "full"                  # event-window shocks from the observed path
BOOTSTRAP = "joint_moving_block"    # one row draw shared by entities, contiguous blocks
BLOCK_LEN = 24                      # hourly: one day of contiguous residual rows
S_STAR_Q = 0.95                     # s* = 95th percentile of fit-window stress
N_SIMS = 2000                       # shock paths for the point ranking
SEED = 7
N_REP_MC = 20                       # Monte Carlo error: 20 seeds of 500 paths
N_SIMS_MC = 500
B_H1 = 2000                         # paired block-bootstrap replicates (H1, falsification)
B_TIME_SHIFT = 100


def zscore(s, win=ROLL):
    return hs.zscore(s, win)


def build_hourly_stress(flows, entities, prices=None):
    """Panel-only wrapper around vein.hourly_stress.build_hourly_stress (legacy signature)."""
    return hs.build_hourly_stress(flows, entities, prices)[0]


def main():
    out = {"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND,
           "resolution": "hourly", "window": [str(WIN_START), str(WIN_END)]}

    print(f"[1] Hourly resolved on-chain flows ({config.DATA_BACKEND}) + prices + Lido series ...")
    ctx = pl.build_hourly_context(k=12)
    flows, stress, graph, prices = ctx.flows, ctx.stress, ctx.graph, ctx.prices_ffill
    out["stress_components"] = ctx.stress_meta

    print("[2] Stress + observed graph + SCM ...")
    est_stress = stress[stress.index < EVENT_START]
    est_flows = flows[flows.day < EVENT_START]
    hs.assert_nonzero_stress(stress, est_stress.index)
    scm = StructuralCausalModel(graph, alpha=1.0).fit(est_stress, est_flows)
    scm.set_flows(flows)
    nodes = list(scm.stress_cols)
    ev = list(stress.index[(stress.index >= EVENT_START) & (stress.index <= EVENT_END)])
    init_stress = est_stress.iloc[-1].to_dict()
    precrisis = {e: float(est_stress[e].median()) for e in stress.columns}
    out["n_entities"] = len(stress.columns)
    out["n_fit_hours"] = int(len(est_stress))
    out["n_event_hours"] = len(ev)
    out["graph_edges"] = len(graph["edges"])
    out["fit_gross_usd"] = {e: float(est_flows.loc[(est_flows.from_entity == e) | (est_flows.to_entity == e),
                                                   "usd_volume"].sum()) for e in stress.columns}
    settings = run_settings(est_stress.index)
    out["settings"] = settings
    print(f"    {len(stress.columns)} entities, {len(est_stress)} fit hours, {len(ev)} event hours, {len(graph['edges'])} edges")

    print("[3] OC-CoVaR systemic ranking (H3) ...")
    hi = risk.fit_window_s_star(stress, est_stress.index, S_STAR_Q)
    sys = fs.from_scm(scm)
    C_ev = fs.drift(sys, fs.log_flows(scm, ev))
    init_vec = [init_stress[e] for e in nodes]
    s_vec = [hi[e] for e in nodes]
    oc = fs.systemic_ranking_fast(scm, ev, init_stress, hi, n_sims=N_SIMS, seed=SEED,
                                  block_len=BLOCK_LEN)
    mc = un.mc_error(sys, C_ev, init_vec, s_vec, n_rep=N_REP_MC, n_sims=N_SIMS_MC,
                     block_len=BLOCK_LEN, seed0=1000)
    mc_se = dict(zip(nodes, mc["se_point"]))
    oc["mc_se"] = oc["entity"].map(mc_se)
    out["oc_covar_ranking"] = oc[["entity", "exported_risk", "mc_se"]].to_dict("records")
    export_hourly_scm(scm, stress, flows, ev, hi, init_stress, precrisis, settings)

    print("[4] H1 head-to-head (observed vs estimated graph, hourly, paired bootstrap) ...")
    comp = [e for e in stress.columns if e in eg.ENTITY_ASSET]
    returns = md.log_returns(prices)
    rp = eg.entity_return_panel(returns, comp)
    rp_est = rp[rp.index < EVENT_START]
    gr = eg.granger_graph(rp_est, alpha=0.10)
    pc = eg.partial_correlation_graph(rp_est, thresh=0.2)
    obs_sub = {"nodes": comp,
               "edges": [e for e in graph["edges"] if e["from"] in comp and e["to"] in comp],
               "parents": {n: [p for p in graph["parents"].get(n, []) if p in comp] for n in comp}}
    ss = stress[comp]
    fl_c = flows[flows.from_entity.isin(comp) & flows.to_entity.isin(comp)]
    out["H1"] = val.h1_observed_vs_estimated(
        obs_sub, {"granger": gr, "partial_corr": pc},
        ss[ss.index < EVENT_START], fl_c[fl_c.day < EVENT_START], ss, fl_c, ev)
    out["H1"]["comparison_nodes"] = comp
    out["H1"]["edge_counts"] = {"observed": len(obs_sub["edges"]),
                                "granger": len(gr["edges"]), "partial_corr": len(pc["edges"])}
    fit_m, ev_m = val.event_masks(ss)
    obs_err = val.onestep_errors(ss, fl_c, obs_sub["parents"], fit_m, ev_m)
    boot = {}
    for g, est_g in {"granger": gr, "partial_corr": pc}.items():
        boot[g] = val.h1_bootstrap(obs_err, val.onestep_errors(ss, fl_c, est_g["parents"], fit_m, ev_m),
                                   B=B_H1, block_len=BLOCK_LEN, seed=SEED)
    out["H1"]["bootstrap"] = boot
    out["H1"]["H1_supported"] = bool(all(b["status"] == "observed_better" for b in boot.values()))

    print("[5] Counterfactual attribution (H4) ...")
    # every ordered source -> target pair (not only Binance/Ethena sources), ranked by the share of
    # the target's realised distress; the same object as uncertainty.json "attribution.channels"
    S_obs_ev = stress.loc[ev, nodes].values.astype(float)
    pre_vec = np.array([precrisis.get(e, 0.0) for e in nodes])
    mat = fs.attribution_matrix(sys, C_ev, S_obs_ev, np.array(init_vec, dtype=float), pre_vec)
    top, n_pairs = un.top_attribution_channels(nodes, mat, 10)
    out["counterfactual_attribution"] = top
    out["counterfactual_attribution_scope"] = (
        f"all {len(nodes)} entities as sources, {n_pairs} ordered pairs with positive realised "
        "target loss, ranked by attribution share, top 10")

    print("[6] Falsification (A3/H2) with paired intervals ...")
    out["falsification"] = fz.run_falsification(graph, est_stress, est_flows, stress, flows, ev).to_dict("records")
    fit_f, ev_f = val.event_masks(stress)
    err_true = val.onestep_errors(stress, flows, graph["parents"], fit_f, ev_f)
    err_rev = val.onestep_errors(stress, flows, fz.reverse_graph(graph)["parents"], fit_f, ev_f)
    err_sym = val.onestep_errors(stress, flows, fz.symmetric_graph(graph)["parents"], fit_f, ev_f)
    out["falsification_ci"] = {
        "reversed_minus_true": val.paired_difference_ci(err_true, err_rev, B=B_H1, block_len=BLOCK_LEN, seed=SEED),
        "symmetric_minus_true": val.paired_difference_ci(err_true, err_sym, B=B_H1, block_len=BLOCK_LEN, seed=SEED)}

    print("[7] Validation battery and placebos ...")
    fit_std = {e: float(est_stress[e].std()) for e in stress.columns}
    out["external_validity"] = val.external_validity(oc, fit_std=fit_std, s_star=hi)
    nonzero = {e for e, sd in fit_std.items() if sd > 1e-9}
    connected = val.connected_pairs(graph, nodes, nonzero)
    out["placebo"] = {
        "structural_zero_check": val.structural_zero_check(scm, graph, ev, stress, init_stress, precrisis),
        "rolling_temporal": val.rolling_temporal_placebo(scm, stress, est_stress.index, ev, precrisis,
                                                         connected, step=BLOCK_LEN, roll=ROLL, gap=BLOCK_LEN),
        "time_shift": val.time_shift_placebo(scm, stress, est_flows, est_stress.index, ev, precrisis,
                                             connected, B=B_TIME_SHIFT, seed=11)}
    out["confounding_sensitivity"] = val.confounding_sensitivity(scm, stress)

    print("[8] Resolution robustness (Tier-0 seed-only graph) ...")
    seeds = set(config.ENTITIES)
    f0 = flows.copy()
    f0["from_entity"] = f0["from_entity"].where(f0["from_entity"].isin(seeds), "retail")
    f0["to_entity"] = f0["to_entity"].where(f0["to_entity"].isin(seeds), "retail")
    f0 = f0[f0.from_entity != f0.to_entity]
    f0 = (f0.groupby(["day", "from_entity", "to_entity"], as_index=False)
            .agg(usd_volume=("usd_volume", "sum"), n_tx=("n_tx", "sum"),
                 from_src=("from_src", "max"), to_src=("to_src", "max")))
    g0 = og.build_graph(f0, min_usd=1e5)
    ents0 = sorted(set(f0.from_entity) | set(f0.to_entity) | seeds)
    s0, _ = hs.build_hourly_stress(f0, ents0, ctx.prices, lido=ctx.lido, fit_end=EVENT_START,
                                   window=ctx.win)
    s0 = s0.sort_index()
    s0_fit = s0[s0.index < EVENT_START]
    scm0 = StructuralCausalModel(g0, alpha=1.0).fit(s0_fit, f0[f0.day < EVENT_START]).set_flows(f0)
    hi0 = risk.fit_window_s_star(s0, s0_fit.index, S_STAR_Q)
    init0 = s0_fit.iloc[-1].to_dict()
    oc0 = fs.systemic_ranking_fast(scm0, ev, init0, hi0, n_sims=N_SIMS, seed=SEED, block_len=BLOCK_LEN)
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


def run_settings(fit_index):
    """Estimator settings recorded with every hourly run and export."""
    fit = pd.DatetimeIndex(fit_index)
    return {"abduction": ABDUCTION,
            "bootstrap": BOOTSTRAP,
            "joint_residual_rows": True,
            "block_len": BLOCK_LEN,
            "block_unit": "hours",
            "s_star_quantile": S_STAR_Q,
            "s_star_window": [str(fit[0]), str(fit[-1])],
            "s_star_window_rows": int(len(fit)),
            "s_star_excludes_event_window": bool(fit.max() < EVENT_START),
            "n_sims": N_SIMS,
            "seed": SEED,
            "ranking_engine": "fastscm",
            "mc_error": {"n_rep": N_REP_MC, "n_sims": N_SIMS_MC, "seed0": 1000},
            "h1_bootstrap": {"B": B_H1, "block_len": BLOCK_LEN, "seed": SEED}}


def export_hourly_scm(scm, stress, flows, ev, s_star, init_stress, precrisis, settings):
    """Archive the hourly SCM so the analytic checks can be re-run offline.

    Writes the coefficients in the schema of results/results.json
    ("scm_coefficients", with "intercept" in place of the in-memory "b"), the
    residual std, s*, the pre-event and pre-crisis levels, the event-window
    stress, the event-window flow per edge, and the settings used (abduction
    mode, bootstrap mode, block length, s* window). Needs the resolved flow data
    (BigQuery cache in data_cache/), so it is produced by a local rerun of this
    script, not by the archived results.
    """
    coef = {e: {"parents": list(c["parents"]),
                "w_stress": [float(x) for x in c["w_stress"]],
                "w_flow": [float(x) for x in c["w_flow"]],
                "intercept": float(c["b"])}
            for e, c in scm.coef_.items()}
    fl = flows[(flows.day >= ev[0]) & (flows.day <= ev[-1])]
    edges = fl.groupby(["from_entity", "to_entity", "day"]).usd_volume.sum().reset_index()
    payload = {
        "resolution": "hourly",
        "settings": settings,
        "event_window": [str(ev[0]), str(ev[-1])],
        "scm_coefficients": coef,
        "scm_residual_std": scm.residual_std(),
        "s_star": s_star,
        "init_stress": init_stress,
        "precrisis": precrisis,
        "event_stress": {str(t): {e: float(v) for e, v in row.items()}
                         for t, row in stress.loc[ev].iterrows()},
        "event_flows": [{"from": r.from_entity, "to": r.to_entity, "hour": str(r.day),
                         "usd_volume": float(r.usd_volume)} for r in edges.itertuples()],
    }
    (RESULTS / "hourly_scm_export.json").write_text(json.dumps(payload, indent=2, default=float))


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
    A("| graph source | weighted RMSE | timing corr | n |\n|---|--:|--:|--:|")
    for s in h1["scores"]:
        A(f"| {s['model']} | {s['rmse']:.4f} | {s['corr']:.4f} | {s['n']} |")
    A("\nPaired block bootstrap of the unweighted squared one-step error (estimated minus observed; "
      "positive = observed better). The RMSE above is weighted by |stress|+0.1, so the weighted CI "
      "column is the one on the scale of the table:\n")
    A("| estimated graph | mean diff | 95% CI | status | 95% CI (weighted) | 95% CI (8-h blocks) |\n|---|--:|--:|---|--:|--:|")
    for g, b in h1["bootstrap"].items():
        A(f"| {g} | {b['mean_diff']:+.4f} | [{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}] | {b['status']} | "
          f"[{b['ci95_weighted'][0]:+.4f}, {b['ci95_weighted'][1]:+.4f}] | "
          f"[{b['ci95_block8'][0]:+.4f}, {b['ci95_block8'][1]:+.4f}] |")
    A("")
    if h1["H1_supported"]:
        A("**H1 supported: observed graph better than every estimated graph (95% block-bootstrap CIs exclude 0)**")
    else:
        for g, b in h1["bootstrap"].items():
            if b["status"] == "observed_better":
                continue
            ci = f"[{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}]"
            if b["status"] == "inconclusive":
                A(f"**H1 not established: CI includes 0 vs {g}** {ci}")
            else:
                A(f"**H1 contradicted vs {g}** {ci}")
    A("")

    A("## Hypotheses & checks\n")
    ra = out.get("ranking_agreement", {})
    oc = out["oc_covar_ranking"]
    A(f"- **H3** (different ranking): OC-CoVaR top transmitters "
      f"{', '.join(r['entity'] for r in oc[:3])}; Spearman vs Δ-CoVaR = "
      f"{ra.get('spearman_oc_vs_deltacovar', float('nan')):.2f} "
      "(lower = more divergent).")
    top = out["counterfactual_attribution"][0] if out["counterfactual_attribution"] else None
    if top:
        A(f"- **H4** (counterfactual): top channel over all sources {top['i']}→{top['j']} = "
          f"{top['attribution_share']*100:.1f}% of realized distress "
          f"({out.get('counterfactual_attribution_scope', 'all sources')}).")
    tr, rv = fal["true_direction"]["rmse"], fal["reversed_edges"]["rmse"]
    fc = out["falsification_ci"]["reversed_minus_true"]
    A(f"- **A3/H2** (direction causal): true {tr:.3f} vs reversed {rv:.3f} RMSE "
      f"→ {'direction informative' if tr < rv*0.98 else 'near-tie / direction weak'}; "
      f"reversed minus true squared error {fc['mean_diff']:+.4f}, 95% CI "
      f"[{fc['ci95'][0]:+.4f}, {fc['ci95'][1]:+.4f}].")
    sz = out["placebo"]["structural_zero_check"]
    A(f"- **Structural zero** (holds by construction, not evidence): unconnected-pair attribution max "
      f"{sz['max_abs_attr_unconnected']:.2e} → {'PASS' if sz['passes'] else 'FAIL'}.")
    rt, ts = out["placebo"]["rolling_temporal"], out["placebo"]["time_shift"]
    A(f"- **Rolling calm-window placebo**: event {rt['event_stat']:.4g} vs {rt['n_windows']} calm windows, "
      f"p = {rt['p_value']:.3f} → {'PASS' if rt['passes'] else 'FAIL'}.")
    A(f"- **Time-shift placebo**: real {ts['real_stat']:.4g} vs {ts['B']} shifted refits, "
      f"p = {ts['p_value']:.3f} → {'PASS' if ts['passes'] else 'FAIL'}.")
    rr = out["resolution_robustness"]
    A(f"- **Resolution robustness**: Spearman {rr.get('spearman', float('nan')):.2f} "
      f"(Tier-0 vs Tier-3, {rr.get('n_common', 0)} entities).")
    ev_ = out["external_validity"]
    A(f"- **External validity** (Oct-2025 narrative): transmitter–absorber "
      f"separation {ev_['separation']:.2f}, concordance {ev_['pairwise_concordance']:.2f}"
      f"; non-degenerate stress: {ev_.get('nondegenerate')}.")
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
    A("| rank | entity | exported risk | MC s.e. |\n|--:|---|--:|--:|")
    for k, r in enumerate(oc[:8], 1):
        A(f"| {k} | {r['entity']} | {r['exported_risk']:.3f} | {r['mc_se']:.3f} |")
    A("")
    (RESULTS / "FINAL_REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
