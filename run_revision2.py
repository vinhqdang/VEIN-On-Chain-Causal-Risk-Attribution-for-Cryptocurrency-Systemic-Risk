#!/usr/bin/env python3
"""Revision-2 experiments: leakage-free non-flow stress + final-output robustness.

Addresses the reviewer's circularity / lagged-flow concerns head-on by rebuilding
stress states from PRICE / PEG / DRAWDOWN signals only (no flow component), so
on-chain flows enter solely as predictors. We then re-run H1 (observed vs Granger
graph) under both contemporaneous and strict-lagged flows, and the edge-reversal
falsification, on this leakage-free target. We also propagate robustness to the
final OC-CoVaR ranking (stability under coefficient perturbation).
Writes results/revision2.json.
"""
from __future__ import annotations
import json
import numpy as np, pandas as pd
from scipy.stats import spearmanr

from vein import config, market_data as md, onchain_graph as og
from vein import entity_resolution as er, estimated_graph as eg
from vein.scm import StructuralCausalModel
from vein import risk
import run_best as rb
from run_revision import onestep_errors, masks
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
EVENT_START, EVENT_END = rb.EVENT_START, rb.EVENT_END
rng = np.random.default_rng(7)
ROLL = 48

# entity -> non-flow stress source: ('peg', token) or ('drawdown', ticker)
NONFLOW = {
    "Binance": ("drawdown", "BNB"), "Aave": ("drawdown", "AAVE"),
    "Lido": ("drawdown", "stETH"), "retail": ("drawdown", "ETH"),
    "Ethena": ("peg", "USDe"), "MakerSky": ("peg", "DAI"),
}
DEFAULT = ("drawdown", "ETH")   # exchanges/custodians without a token: market drawdown


def z(s, win=ROLL):
    mu = s.rolling(win, min_periods=6).mean(); sd = s.rolling(win, min_periods=6).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def nonflow_stress(entities, prices, idx):
    cols = {}
    for e in entities:
        kind, tk = NONFLOW.get(e, DEFAULT)
        if tk not in prices.columns:
            cols[e] = pd.Series(0.0, index=idx); continue
        p = prices[tk].reindex(idx).ffill()
        if kind == "peg":
            sig = (1.0 - p).abs()
        else:
            sig = (1.0 - p / p.rolling(ROLL, min_periods=6).max()).clip(lower=0).fillna(0.0)
        cols[e] = z(sig)
    return pd.DataFrame(cols, index=idx).fillna(0.0)


def main():
    out = {"generated": "2026-06-30"}
    flows = er.load_resolved_flows(rb.WIN_START, rb.WIN_END, rb.TOKENS, bucket="hour", min_addr_volume=1e3)
    flows = er.top_k_entities(flows, k=12); flows["day"] = pd.to_datetime(flows["day"])
    prices = md.build_hourly_price_panel(config.MARKET_ASSETS, rb.WIN_START, rb.WIN_END)
    ents = sorted(set(flows.from_entity) | set(flows.to_entity) | set(config.ENTITIES))
    idx = pd.DatetimeIndex(sorted(flows["day"].unique()))
    stress = nonflow_stress(ents, prices, idx).sort_index()
    graph = og.build_graph(flows, min_usd=1e5)

    comp = [e for e in stress.columns if e in eg.ENTITY_ASSET]
    sub_parents = {n: [p for p in graph["parents"].get(n, []) if p in comp] for n in comp}
    returns = md.log_returns(prices)
    rp = eg.entity_return_panel(returns, comp); rp = rp[rp.index < EVENT_START]
    gr = eg.granger_graph(rp, alpha=0.10)
    sc = stress[comp]; fc = flows[flows.from_entity.isin(comp) & flows.to_entity.isin(comp)]
    fitm, evm = masks(sc)

    print("[1] non-flow H1 (contemporaneous + lagged)")
    res = {}
    for lag, tag in [(0, "contemporaneous"), (1, "lagged")]:
        o = onestep_errors(sc, fc, sub_parents, fitm, evm, flow_lag=lag)
        g = onestep_errors(sc, fc, gr["parents"], fitm, evm, flow_lag=lag)
        res[tag] = {"observed_wrmse": o["wrmse"], "granger_wrmse": g["wrmse"],
                    "observed_dir_acc": o["dir_acc"], "granger_dir_acc": g["dir_acc"],
                    "observed_better": bool(o["wrmse"] < g["wrmse"])}
    out["nonflow_H1"] = res

    print("[2] non-flow falsification (true/reversed/symmetric)")
    fitm2, evm2 = masks(stress)
    full = {n: list(graph["parents"].get(n, [])) for n in graph["nodes"]}
    rev = {n: [] for n in graph["nodes"]}
    for e in graph["edges"]:
        rev[e["from"]].append(e["to"])
    sym = {n: set() for n in graph["nodes"]}
    for e in graph["edges"]:
        sym[e["from"]].add(e["to"]); sym[e["to"]].add(e["from"])
    sym = {n: sorted(v) for n, v in sym.items()}
    out["nonflow_falsification"] = {
        "true": onestep_errors(stress, flows, full, fitm2, evm2)["wrmse"],
        "reversed": onestep_errors(stress, flows, rev, fitm2, evm2)["wrmse"],
        "symmetric": onestep_errors(stress, flows, sym, fitm2, evm2)["wrmse"]}

    print("[3] OC-CoVaR ranking stability under coefficient perturbation")
    ev_days = list(stress.index[evm2])
    init = stress[stress.index < EVENT_START].iloc[-1].to_dict()
    hi = {e: float(np.quantile(stress[e].values, 0.95)) for e in stress.columns}
    Z = {e: np.zeros(len(ev_days)) for e in graph["nodes"]}   # zero-shock (deterministic)

    def det_exported(scm):
        """Deterministic exported-risk proxy: sum_j max(L_j(do hi) - L_j(do 0), 0)."""
        scores = {}
        for i in scm.stress_cols:
            tot = 0.0
            for j in scm.stress_cols:
                if j == i:
                    continue
                hi_loss = risk.loss_functional(scm.simulate(ev_days, init, Z, do={i: np.full(len(ev_days), hi[i])})[j].values)
                lo_loss = risk.loss_functional(scm.simulate(ev_days, init, Z, do={i: np.zeros(len(ev_days))})[j].values)
                tot += max(hi_loss - lo_loss, 0.0)
            scores[i] = tot
        return pd.Series(scores).sort_values(ascending=False)

    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress[stress.index < EVENT_START],
                                                      flows[flows.day < EVENT_START]).set_flows(flows)
    base = det_exported(scm); base_order = list(base.index)
    rhos, top3 = [], []
    for k in range(25):
        scmp = StructuralCausalModel(graph, alpha=1.0).fit(stress[stress.index < EVENT_START],
                                                           flows[flows.day < EVENT_START]).set_flows(flows)
        for e in scmp.coef_:
            c = scmp.coef_[e]
            if len(c["w_stress"]):
                c["w_stress"] = c["w_stress"] * (1 + rng.normal(0, 0.15, len(c["w_stress"])))
            if len(c["w_flow"]):
                c["w_flow"] = c["w_flow"] * (1 + rng.normal(0, 0.15, len(c["w_flow"])))
        r = det_exported(scmp)
        common = [e for e in base.index if e in r.index]
        rho, _ = spearmanr(base.loc[common].values, r.loc[common].values)
        if not np.isnan(rho):
            rhos.append(float(rho))
        top3.append(len(set(base_order[:3]) & set(list(r.index)[:3])) / 3.0)
    out["ranking_stability"] = {"base_top5": base_order[:5],
                                "mean_spearman_vs_base": float(np.mean(rhos)),
                                "min_spearman": float(np.min(rhos)),
                                "mean_top3_overlap": float(np.mean(top3)), "n_perturbations": len(top3)}

    (RESULTS / "revision2.json").write_text(json.dumps(out, indent=2, default=float))
    print("WROTE results/revision2.json"); print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
