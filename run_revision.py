#!/usr/bin/env python3
"""Revision experiments responding to reviewer concerns (real data, cached).

Adds, on top of the main evaluation:
  - H1 paired block-bootstrap confidence interval + extra metrics      (#3,#19)
  - leakage-free lagged-flow variant and pre-event-only graph          (#4,#5,#6)
  - edge-type-specific falsification (composability vs custodial)      (#1,#2,#17)
  - Shapley attribution, additivity, and confounder sensitivity        (#8,#9,#10)
  - no-retail robustness and volume-weighted resolution coverage       (#12,#13)
Writes results/revision.json and revision figures.
"""
from __future__ import annotations
import datetime as dt, json, itertools
from pathlib import Path
import numpy as np, pandas as pd

from vein import config, market_data as md
from vein import estimated_graph as eg, validation as val, pipeline as pl
from vein.validation import onestep_errors
from vein.scm import StructuralCausalModel
from vein import risk
import run_best as rb

RESULTS = Path(__file__).resolve().parent / "results"
EVENT_START, EVENT_END = rb.EVENT_START, rb.EVENT_END
BOOT_BLOCK = 8                      # H1 paired block length (hours; whole time steps)
rng = np.random.default_rng(7)


# ---------------------------------------------------------------- shared build
def build():
    ctx = pl.build_hourly_context(k=12)
    return ctx.flows, ctx.prices_ffill, ctx.stress, ctx.graph


masks = val.event_masks


def main():
    out = {"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND}
    flows, prices, stress, graph = build()
    fit_mask, ev_mask = masks(stress)
    comp = [e for e in stress.columns if e in eg.ENTITY_ASSET]

    # restrict to comparison nodes for H1
    sub_parents_obs = {n: [p for p in graph["parents"].get(n, []) if p in comp] for n in comp}
    ret = prices  # returns for granger
    returns = md.log_returns(prices)
    rp = eg.entity_return_panel(returns, comp)
    rp = rp[rp.index < EVENT_START]
    gr = eg.granger_graph(rp, alpha=0.10)
    stress_c = stress[comp]
    flows_c = flows[flows.from_entity.isin(comp) & flows.to_entity.isin(comp)]
    fitm, evm = masks(stress_c)

    # ---- #3,#19: H1 metrics + paired bootstrap CI ----
    print("[1] H1 metrics + bootstrap CI")
    obs = onestep_errors(stress_c, flows_c, sub_parents_obs, fitm, evm)
    grg = onestep_errors(stress_c, flows_c, gr["parents"], fitm, evm)
    # Paired moving-block bootstrap of the weighted prediction-level errors
    # (granger minus observed). Both models predict the same (entity, hour) cells,
    # so the arrays are paired by position. Blocking is over TIME: whole hours
    # (all entities at that hour) are resampled in contiguous blocks of BOOT_BLOCK
    # hours, so cross-entity and serial dependence are both kept.
    assert len(grg["werr"]) == len(obs["werr"]), "paired H1 errors must align"
    assert np.array_equal(grg["tpos"], obs["tpos"]) and np.array_equal(grg["ent"], obs["ent"])
    d = grg["werr"] - obs["werr"]
    B = 2000
    diffs = risk.paired_time_block_means(d, obs["tpos"], B, BOOT_BLOCK, rng)
    out["H1"] = {
        "observed": {k: obs[k] for k in ["wrmse", "rmse", "mae", "dir_acc", "n"]},
        "granger": {k: grg[k] for k in ["wrmse", "rmse", "mae", "dir_acc", "n"]},
        "mean_werr_diff_granger_minus_observed": float(np.mean(d)),
        "boot_ci95_diff": [float(np.quantile(diffs, .025)), float(np.quantile(diffs, .975))],
        "prob_observed_better": float(np.mean(diffs > 0)),
        "bootstrap": {"scheme": "paired_moving_block", "block_len": BOOT_BLOCK,
                      "block_unit": "hours (whole time steps, all entities)", "replicates": B}}

    # ---- #4,#5,#6: leakage-free lagged-flow + pre-event graph ----
    print("[2] lagged-flow / leakage-free")
    obs_lag = onestep_errors(stress_c, flows_c, sub_parents_obs, fitm, evm, flow_lag=1)
    grg_lag = onestep_errors(stress_c, flows_c, gr["parents"], fitm, evm, flow_lag=1)
    out["lagged_flow"] = {"observed_wrmse": obs_lag["wrmse"], "granger_wrmse": grg_lag["wrmse"],
                          "observed_dir_acc": obs_lag["dir_acc"]}

    # ---- #1,#2,#17: edge-type falsification ----
    print("[3] edge-type falsification")
    documented = set((e["from"], e["to"]) for e in graph["edges"] if e.get("source") == "documented")
    def reverse_subset(parents_edges, which):
        # build parents map reversing only edges in `which` set
        P = {n: [] for n in graph["nodes"]}
        for e in graph["edges"]:
            a, b = e["from"], e["to"]
            key = (a, b); is_doc = e.get("source") == "documented"
            if (which == "composability" and is_doc) or (which == "custodial" and not is_doc):
                P[a].append(b)   # reversed
            else:
                P[b].append(a)   # true
        return P
    full_parents = {n: list(graph["parents"].get(n, [])) for n in graph["nodes"]}
    fitm2, evm2 = masks(stress)
    et = {}
    et["true"] = onestep_errors(stress, flows, full_parents, fitm2, evm2)["wrmse"]
    et["reverse_composability"] = onestep_errors(stress, flows, reverse_subset(graph, "composability"), fitm2, evm2)["wrmse"]
    et["reverse_custodial"] = onestep_errors(stress, flows, reverse_subset(graph, "custodial"), fitm2, evm2)["wrmse"]
    out["edge_type_falsification"] = {**et,
        "n_composability_edges": len(documented),
        "n_custodial_edges": len([e for e in graph["edges"] if e.get("source") != "documented"])}

    # ---- main SCM for attribution analyses ----
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress[stress.index < EVENT_START],
                                                      flows[flows.day < EVENT_START]).set_flows(flows)
    ev_days = list(stress.index[ev_mask])
    init = stress[stress.index < EVENT_START].iloc[-1].to_dict()
    precrisis = {e: float(stress[stress.index < EVENT_START][e].median()) for e in stress.columns}
    U = scm.event_residuals(stress, ev_days, init)

    def Lj(target, distressed_sources):
        """loss of target with `distressed_sources` held at observed, others at precrisis."""
        do = {}
        for s in scm.stress_cols:
            if s == target:
                continue
            if s in distressed_sources:
                do[s] = stress[s].reindex(pd.DatetimeIndex(ev_days)).fillna(0.0).values
            else:
                do[s] = np.full(len(ev_days), precrisis.get(s, 0.0))
        sim = scm.simulate(ev_days, init, U, do=do)
        return risk.loss_functional(sim[target].values)

    # ---- #10: Shapley attribution + additivity (target = Bybit) ----
    print("[4] Shapley attribution")
    target = "Bybit" if "Bybit" in scm.stress_cols else scm.stress_cols[0]
    cand = [e for e in ["Binance", "Coinbase", "Bitfinex", "retail"] if e in scm.stress_cols and e != target]
    cand = cand[:3]
    full = Lj(target, set(cand)); none = Lj(target, set())
    shap = {s: 0.0 for s in cand}
    perms = list(itertools.permutations(cand))
    for perm in perms:
        cur = set(); prev = Lj(target, cur)
        for s in perm:
            cur = cur | {s}; nv = Lj(target, cur)
            shap[s] += (nv - prev); prev = nv
    shap = {s: shap[s] / len(perms) for s in cand}
    tot = full - none
    out["shapley"] = {"target": target, "candidates": cand,
                      "shapley_values": {s: float(v) for s, v in shap.items()},
                      "sum_shapley": float(sum(shap.values())), "total_effect": float(tot),
                      "additive_residual": float(tot - sum(shap.values()))}

    # ---- #8: confounder/coefficient sensitivity for key channels ----
    print("[5] attribution sensitivity")
    def attr_share(i, j):
        a = risk.counterfactual_attribution(scm, i, j, ev_days, stress, init, precrisis.get(i, 0.0))
        return a["attribution_share"]
    channels = [("Binance", "Bybit"), ("Ethena", "Aave")]
    sens = {}
    for (i, j) in channels:
        if i not in scm.stress_cols or j not in scm.stress_cols:
            continue
        base = attr_share(i, j)
        shares = []
        for _ in range(40):
            scm2 = StructuralCausalModel(graph, alpha=1.0).fit(stress[stress.index < EVENT_START],
                                                               flows[flows.day < EVENT_START]).set_flows(flows)
            for e in scm2.coef_:
                c = scm2.coef_[e]
                if len(c["w_stress"]):
                    c["w_stress"] = c["w_stress"] * (1 + rng.normal(0, 0.15, size=len(c["w_stress"])))
            shares.append(attr_share_scm(scm2, i, j, ev_days, stress, init, precrisis))
        shares = np.array(shares)
        sens[f"{i}->{j}"] = {"base_share": float(base), "mean": float(np.mean(shares)),
                             "sd": float(np.std(shares)), "frac_positive": float(np.mean(shares > 0))}
    out["attribution_sensitivity"] = sens

    # ---- #13: no-retail ranking ----
    print("[6] no-retail robustness")
    no_ret_nodes = [n for n in graph["nodes"] if n != "retail"]
    g_nr = {"nodes": no_ret_nodes,
            "edges": [e for e in graph["edges"] if e["from"] != "retail" and e["to"] != "retail"],
            "parents": {n: [p for p in graph["parents"].get(n, []) if p != "retail"] for n in no_ret_nodes}}
    s_nr = stress[[c for c in stress.columns if c != "retail"]]
    scm_nr = StructuralCausalModel(g_nr, alpha=1.0).fit(s_nr[s_nr.index < EVENT_START],
                                                        flows[(flows.from_entity != "retail") & (flows.to_entity != "retail") & (flows.day < EVENT_START)]).set_flows(flows)
    hi_nr = risk.fit_window_s_star(s_nr, s_nr.index[s_nr.index < EVENT_START], rb.S_STAR_Q)
    init_nr = s_nr[s_nr.index < EVENT_START].iloc[-1].to_dict()
    oc_nr = risk.systemic_ranking(scm_nr, ev_days, init_nr, hi_nr, n_sims=120, seed=7,
                                  joint=True, block_len=rb.BLOCK_LEN)
    out["no_retail_ranking"] = oc_nr[["entity", "exported_risk"]].head(6).to_dict("records")

    # ---- #12: resolution volume coverage ----
    print("[7] resolution coverage")
    tot_vol = flows.usd_volume.sum()
    named = flows[(flows.from_entity != "retail") & (flows.to_entity != "retail")].usd_volume.sum()
    touch_named = flows[(flows.from_entity != "retail") | (flows.to_entity != "retail")].usd_volume.sum()
    out["resolution_coverage"] = {
        "total_usd": float(tot_vol),
        "frac_volume_named_both_sides": float(named / tot_vol),
        "frac_volume_touching_named": float(touch_named / tot_vol),
        "n_named_entities": len([n for n in graph["nodes"] if n != "retail"])}

    (RESULTS / "revision.json").write_text(json.dumps(out, indent=2, default=float))
    print("WROTE results/revision.json")
    for k in out:
        if k != "generated":
            print(" ", k)


def attr_share_scm(scm, i, j, days, stress, init, precrisis):
    a = risk.counterfactual_attribution(scm, i, j, days, stress, init, precrisis.get(i, 0.0))
    return a["attribution_share"]


if __name__ == "__main__":
    main()
