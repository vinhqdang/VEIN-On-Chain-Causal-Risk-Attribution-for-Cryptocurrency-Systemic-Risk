#!/usr/bin/env python3
"""Multi-event validation (reviewer #16): run VEIN on additional stress windows.

We add two earlier episodes that pre-date Ethena/USDe, so the flow tokens are the
dollar-settlement assets present then (USDC/USDT/WETH) and entities are resolved
via Dune's (timeless) CEX labels:
  - FTX collapse,            7--16 November 2022
  - USDC depeg / SVB,        9--16 March 2023
For each window we build the entity-resolved graph, a flow-based stress panel
(+ USDC peg deviation for the depeg episode), fit the SCM, and report the
OC-CoVaR transmitter ranking and the edge-reversal falsification. This tests
whether VEIN generalises beyond October 2025. Daily resolution (cheaper scan).
Writes results/multievent.json.
"""
from __future__ import annotations
import datetime as dt, json
from pathlib import Path
import numpy as np, pandas as pd

from vein import config, market_data as md, onchain_graph as og
from vein import entity_resolution as er, falsification as fz
from vein.scm import StructuralCausalModel
from vein import risk

RESULTS = Path(__file__).resolve().parent / "results"
TOKENS = ["USDC", "USDT", "WETH"]
ROLL = 14

EVENTS = {
    "FTX_Nov2022":  (dt.date(2022, 11, 1), dt.date(2022, 11, 16),
                     pd.Timestamp("2022-11-08"), pd.Timestamp("2022-11-11"), None),
    "USDC_SVB_Mar2023": (dt.date(2023, 3, 1), dt.date(2023, 3, 16),
                         pd.Timestamp("2023-03-10"), pd.Timestamp("2023-03-13"), "usd-coin"),
}


def zscore(s, win=ROLL):
    mu = s.rolling(win, min_periods=3).mean(); sd = s.rolling(win, min_periods=3).std().replace(0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def stress_panel(flows, entities, peg_series=None, idx=None):
    idx = pd.DatetimeIndex(sorted(flows["day"].unique())) if idx is None else idx
    cols = {}
    for e in entities:
        inf = flows[flows.to_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        outf = flows[flows.from_entity == e].groupby("day").usd_volume.sum().reindex(idx, fill_value=0.0)
        tot = inf + outf
        net = ((outf - inf) / tot.rolling(ROLL, min_periods=3).mean().replace(0, np.nan)).fillna(0.0)
        cols[e] = 0.6 * zscore(net) + 0.4 * zscore(tot)
    panel = pd.DataFrame(cols, index=idx).fillna(0.0)
    if peg_series is not None:
        peg = (1.0 - peg_series.reindex(idx).ffill()).abs()
        # attach peg stress to retail proxy and any stablecoin-ish node by boosting all (systemic)
        panel["market_peg"] = zscore(peg)
    return panel


def run_event(name, start, end, ev0, ev1, peg_id):
    flows = er.load_resolved_flows(start, end, TOKENS, bucket="day", min_addr_volume=1e6)
    if flows.empty:
        return {"event": name, "ok": False, "reason": "no flows"}
    flows = er.top_k_entities(flows, k=10)
    flows["day"] = pd.to_datetime(flows["day"])
    ents = sorted(set(flows.from_entity) | set(flows.to_entity))
    peg = None
    if peg_id:
        peg = md.coingecko_prices(peg_id, start, end)
    stress = stress_panel(flows, ents, peg).sort_index()
    graph = og.build_graph(flows, min_usd=1e6, include_documented=False)
    ev = list(stress.index[(stress.index >= ev0) & (stress.index <= ev1)])
    pre = stress[stress.index < ev0]
    if len(pre) < 4 or len(ev) < 1:
        return {"event": name, "ok": False, "reason": "insufficient window", "n_pre": len(pre), "n_ev": len(ev)}
    scm = StructuralCausalModel(graph, alpha=1.0).fit(pre, flows[flows.day < ev0]).set_flows(flows)
    hi = {e: float(np.quantile(stress[e].values, 0.95)) for e in stress.columns}
    init = pre.iloc[-1].to_dict()
    oc = risk.systemic_ranking(scm, ev, init, hi, n_sims=150, seed=7)
    fal = fz.run_falsification(graph, pre, flows[flows.day < ev0], stress, flows, ev)
    return {"event": name, "ok": True,
            "n_entities": len(stress.columns), "n_pre_days": len(pre), "n_event_days": len(ev),
            "n_edges": len(graph["edges"]),
            "oc_ranking": oc[["entity", "exported_risk"]].head(6).to_dict("records"),
            "falsification": fal.to_dict("records")}


def main():
    out = {"generated": "2026-06-30", "events": []}
    for name, (s, e, e0, e1, peg) in EVENTS.items():
        print(f"[event] {name} ...", flush=True)
        try:
            out["events"].append(run_event(name, s, e, e0, e1, peg))
        except Exception as ex:  # noqa: BLE001
            out["events"].append({"event": name, "ok": False, "reason": str(ex)})
        print("   done", flush=True)
    (RESULTS / "multievent.json").write_text(json.dumps(out, indent=2, default=float))
    print("WROTE results/multievent.json")


if __name__ == "__main__":
    main()
