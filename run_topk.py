#!/usr/bin/env python3
"""Sensitivity of the hourly results to the number of resolved entities -> results/topk_sensitivity.json.

The main specification keeps the top k = 12 entities by throughput (the seeds are always kept).
k in {10, 15} is re-estimated from the same cached hourly context (no new BigQuery scan). For
each k: the SCM fit on the pre-event hours, the OC-CoVaR ranking (2000 shock paths, seed 7),
the H1 RMSE of the observed graph against the price-estimated graphs, and the top five
counterfactual attribution channels. Agreement with the main k is the Spearman correlation of
the exported risk over the entities both specifications share, and the overlap of the top-3 and
top-5 rankings (number of shared entities).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
from scipy import stats

from vein import config, estimated_graph as eg, fastscm as fs, hourly_stress as hs
from vein import market_data as md, pipeline as pl, risk, validation as val
from vein.scm import StructuralCausalModel

RESULTS = Path(__file__).resolve().parent / "results"
MAIN_K = 12
K_VALUES = [10, 12, 15]
N_SIMS = 2000
SEED = 7
S_STAR_Q = 0.95
TOP_CHANNELS = 5
BLOCK_LEN = 24


def h1_rmse(ctx, stress, flows, ev) -> dict:
    """RMSE of the observed graph and of the Granger / partial-correlation graphs on the event
    window (run_best.py step 4, restricted to the entities with a price)."""
    comp = [e for e in stress.columns if e in eg.ENTITY_ASSET]
    returns = md.log_returns(ctx.prices_ffill)
    rp = eg.entity_return_panel(returns, comp)
    rp_est = rp[rp.index < pl.EVENT_START]
    gr = eg.granger_graph(rp_est, alpha=0.10)
    pc = eg.partial_correlation_graph(rp_est, thresh=0.2)
    obs_sub = {"nodes": comp,
               "edges": [e for e in ctx.graph["edges"] if e["from"] in comp and e["to"] in comp],
               "parents": {n: [p for p in ctx.graph["parents"].get(n, []) if p in comp] for n in comp}}
    ss = stress[comp]
    fl_c = flows[flows.from_entity.isin(comp) & flows.to_entity.isin(comp)]
    res = val.h1_observed_vs_estimated(
        obs_sub, {"granger": gr, "partial_corr": pc},
        ss[ss.index < pl.EVENT_START], fl_c[fl_c.day < pl.EVENT_START], ss, fl_c, ev)
    return {s["model"]: float(s["rmse"]) for s in res["scores"]}


def summarize_k(k: int) -> dict:
    ctx = pl.build_hourly_context(k=k)
    flows, stress, graph = ctx.flows, ctx.stress, ctx.graph
    est = stress[stress.index < pl.EVENT_START]
    est_flows = flows[flows.day < pl.EVENT_START]
    hs.assert_nonzero_stress(stress, est.index)
    scm = StructuralCausalModel(graph, alpha=1.0).fit(est, est_flows).set_flows(flows)
    nodes = list(scm.stress_cols)
    ev = list(stress.index[(stress.index >= pl.EVENT_START) & (stress.index <= pl.EVENT_END)])
    init = est.iloc[-1].to_dict()
    s_star = risk.fit_window_s_star(stress, est.index, S_STAR_Q)
    oc = fs.systemic_ranking_fast(scm, ev, init, s_star, n_sims=N_SIMS, seed=SEED,
                                  block_len=BLOCK_LEN)

    sys = fs.from_scm(scm)
    C = fs.drift(sys, fs.log_flows(scm, ev))
    p0 = stress.index.get_loc(ev[0])
    S_prev0 = stress.iloc[p0 - 1][nodes].values.astype(float)
    S_obs = stress.loc[ev, nodes].values.astype(float)
    precrisis = {e: float(est[e].median()) for e in nodes}
    mat = fs.attribution_matrix(sys, C, S_obs, S_prev0, precrisis)
    pos = {e: i for i, e in enumerate(nodes)}
    pairs = [(i, j) for i in nodes for j in nodes
             if i != j and mat["L_obs"][pos[i], pos[j]] > 0]
    pairs.sort(key=lambda p: -mat["share"][pos[p[0]], pos[p[1]]])
    channels = [{"i": i, "j": j, "share": float(mat["share"][pos[i], pos[j]]),
                 "attribution": float(mat["attr"][pos[i], pos[j]])}
                for i, j in pairs[:TOP_CHANNELS]]

    return {"k": k, "entities": nodes, "n_entities": len(nodes), "n_edges": len(graph["edges"]),
            "n_fit_hours": int(len(est)), "n_event_hours": len(ev),
            "stress_components": ctx.stress_meta,
            "oc_ranking": [{"entity": r.entity, "exported_risk": float(r.exported_risk)}
                           for r in oc.itertuples(index=False)],
            "H1_rmse": h1_rmse(ctx, stress, flows, ev),
            "top_channels": channels}


def compare_to_main(main: dict, other: dict) -> dict:
    """Agreement of two rankings over their common entities."""
    rm = {r["entity"]: r["exported_risk"] for r in main["oc_ranking"]}
    ro = {r["entity"]: r["exported_risk"] for r in other["oc_ranking"]}
    common = sorted(set(rm) & set(ro))
    rho = float("nan")
    if len(common) >= 3:
        rho = float(stats.spearmanr([rm[e] for e in common], [ro[e] for e in common]).statistic)
    top = lambda d, n: {e for e, _ in sorted(d.items(), key=lambda t: -t[1])[:n]}  # noqa: E731
    return {"spearman_common": rho if np.isfinite(rho) else None, "n_common": len(common),
            "top3_overlap": len(top(rm, 3) & top(ro, 3)),
            "top5_overlap": len(top(rm, 5) & top(ro, 5))}


def main():
    by_k = {}
    for k in K_VALUES:
        print(f"[k={k}] hourly context, ranking, H1, channels ...", flush=True)
        by_k[k] = summarize_k(k)
    main_res = by_k[MAIN_K]
    out = {"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND,
           "main_k": MAIN_K, "k_values": K_VALUES,
           "by_k": {str(k): v for k, v in by_k.items()},
           "vs_main": {str(k): compare_to_main(main_res, by_k[k]) for k in K_VALUES if k != MAIN_K}}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "topk_sensitivity.json"
    path.write_text(json.dumps(out, indent=2, default=float))
    print(f"WROTE {path}")


if __name__ == "__main__":
    main()
