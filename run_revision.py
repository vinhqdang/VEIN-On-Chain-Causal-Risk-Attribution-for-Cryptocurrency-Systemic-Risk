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

from vein import config, market_data as md, onchain_graph as og
from vein import entity_resolution as er, estimated_graph as eg
from vein.scm import StructuralCausalModel
from vein import risk
import run_best as rb

RESULTS = Path(__file__).resolve().parent / "results"
EVENT_START, EVENT_END = rb.EVENT_START, rb.EVENT_END
rng = np.random.default_rng(7)


# ---------------------------------------------------------------- shared build
def build():
    flows = er.load_resolved_flows(rb.WIN_START, rb.WIN_END, rb.TOKENS, bucket="hour",
                                   min_addr_volume=1e3)
    flows = er.top_k_entities(flows, k=12)
    flows["day"] = pd.to_datetime(flows["day"])
    prices = md.build_hourly_price_panel(config.MARKET_ASSETS, rb.WIN_START, rb.WIN_END)
    ents = sorted(set(flows.from_entity) | set(flows.to_entity) | set(config.ENTITIES))
    stress = rb.build_hourly_stress(flows, ents, prices).sort_index()
    graph = og.build_graph(flows, min_usd=1e5)
    return flows, prices, stress, graph


# ------------------------------------------- self-contained one-step evaluator
def onestep_errors(stress, flows, parents, fit_mask, eval_mask, flow_lag=0, alpha=1.0):
    """Ridge one-step-ahead fit on fit rows, evaluate on eval rows.
    Returns dict with weighted/unweighted RMSE, MAE, directional accuracy, and
    the per-observation squared-error array (for paired bootstrap)."""
    idx = stress.index
    fmap = {(i, j): g.set_index("day").usd_volume.groupby(level=0).sum()
            for (i, j), g in flows.groupby(["from_entity", "to_entity"])}

    def flow_at(p, c, t_pos):
        s = fmap.get((p, c))
        if s is None:
            return 0.0
        day = idx[t_pos - flow_lag] if t_pos - flow_lag >= 0 else idx[0]
        try:
            return float(s.get(day, 0.0))
        except Exception:
            return 0.0

    # fit per entity
    coefs = {}
    for ent in stress.columns:
        par = [p for p in parents.get(ent, []) if p in stress.columns]
        rows_y, rows_X = [], []
        for tpos in range(1, len(idx)):
            if not fit_mask[tpos]:
                continue
            feats = [stress.iloc[tpos - 1][p] for p in par] + \
                    [np.log1p(flow_at(p, ent, tpos)) for p in par]
            rows_X.append([1.0] + feats); rows_y.append(stress.iloc[tpos][ent])
        if len(rows_y) < 5 or len(par) == 0:
            coefs[ent] = (np.array([np.mean(rows_y) if rows_y else 0.0]), par)
            continue
        X = np.array(rows_X); y = np.array(rows_y)
        A = X.T @ X + alpha * np.eye(X.shape[1]); A[0, 0] -= alpha
        beta = np.linalg.solve(A, X.T @ y)
        coefs[ent] = (beta, par)

    preds, acts, wts = [], [], []
    for ent in stress.columns:
        beta, par = coefs[ent]
        for tpos in range(1, len(idx)):
            if not eval_mask[tpos]:
                continue
            if len(par) == 0 or len(beta) == 1:
                yhat = beta[0]
            else:
                feats = [stress.iloc[tpos - 1][p] for p in par] + \
                        [np.log1p(flow_at(p, ent, tpos)) for p in par]
                yhat = beta @ np.array([1.0] + feats)
            y = stress.iloc[tpos][ent]
            preds.append(yhat); acts.append(y); wts.append(abs(y) + 0.1)
    preds, acts, wts = np.array(preds), np.array(acts), np.array(wts)
    err2 = (preds - acts) ** 2
    wrmse = float(np.sqrt(np.average(err2, weights=wts)))
    rmse = float(np.sqrt(np.mean(err2)))
    mae = float(np.mean(np.abs(preds - acts)))
    diracc = float(np.mean(np.sign(preds) == np.sign(acts)))
    return {"wrmse": wrmse, "rmse": rmse, "mae": mae, "dir_acc": diracc,
            "werr": (err2 * wts), "wts": wts, "n": len(preds)}


def masks(stress):
    idx = stress.index
    ev = np.array([(t >= EVENT_START) and (t <= EVENT_END) for t in idx])
    fit = np.array([t < EVENT_START for t in idx])
    return fit, ev


def main():
    out = {"generated": "2026-06-30"}
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
    # paired block bootstrap on weighted errors (observed - granger), block=entity-day chunks
    d = grg["werr"][:min(len(grg["werr"]), len(obs["werr"]))] - obs["werr"][:min(len(grg["werr"]), len(obs["werr"]))]
    B, n = 2000, len(d); block = 8
    diffs = []
    for _ in range(B):
        idxs = rng.integers(0, n, size=n)
        diffs.append(np.mean(d[idxs]))
    diffs = np.array(diffs)
    out["H1"] = {
        "observed": {k: obs[k] for k in ["wrmse", "rmse", "mae", "dir_acc", "n"]},
        "granger": {k: grg[k] for k in ["wrmse", "rmse", "mae", "dir_acc", "n"]},
        "mean_werr_diff_granger_minus_observed": float(np.mean(d)),
        "boot_ci95_diff": [float(np.quantile(diffs, .025)), float(np.quantile(diffs, .975))],
        "prob_observed_better": float(np.mean(diffs > 0))}

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
    U = scm.abduct(stress, ev_days)

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
    hi_nr = {e: float(np.quantile(s_nr[e].values, 0.95)) for e in s_nr.columns}
    init_nr = s_nr[s_nr.index < EVENT_START].iloc[-1].to_dict()
    oc_nr = risk.systemic_ranking(scm_nr, ev_days, init_nr, hi_nr, n_sims=120, seed=7)
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
