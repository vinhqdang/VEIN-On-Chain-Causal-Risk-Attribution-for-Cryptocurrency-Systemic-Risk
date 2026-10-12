#!/usr/bin/env python3
"""Multi-event validation: VEIN on two earlier stress windows -> results/multievent.json.

Two episodes that pre-date Ethena/USDe, so the flow tokens are the dollar-settlement assets
present then (USDC/USDT/WETH) and entities are resolved through the open CEX labels and the
deposit-sweep detection (BigQuery extracts ftx_ext and svb_ext):
  - FTX collapse,       event 8--11 November 2022, window 1 October -- 16 November 2022
  - USDC depeg / SVB,   event 10--13 March 2023,   window 1 February -- 16 March 2023
Each window is analysed at hourly resolution (primary) and at daily resolution (robustness).
The stress panel is the named-component panel of vein/hourly_stress.py (flow, the Aave
drawdown and Maker peg, the stETH discount); the fit uses the pre-event rows only.

Every event reports whether the fit has enough rows for the number of parameters
(check_min_rows). A window that fails this is reported as underpowered and not fitted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from vein import config, fastscm as fs, falsification as fz, hourly_stress as hs
from vein import onchain_graph as og, pipeline as pl, risk, uncertainty as un, validation as val
from vein.scm import StructuralCausalModel

RESULTS = Path(__file__).resolve().parent / "results"
TOKENS = ["USDC", "USDT", "WETH"]
K_ENTITIES = 12
EXTRA_ENTITIES = ("Aave", "Lido", "MakerSky")   # protocol entities that may be absent from top-k
MIN_USD = 1e5
MIN_ADDR_VOLUME = {"hour": 1e3, "day": 1e6}
ROLL = {"hour": 48, "day": 14}                  # rolling window of the z-scores (hs.zscore)
MIN_PERIODS = {"hour": 6, "day": 3}
FREQ = {"hour": "h", "day": "D"}
MIN_FIT_ROWS = {"hour": 240, "day": 30}         # floor on the pre-event rows
ROWS_PER_PARAM = 5
S_STAR_Q = 0.95
N_SIMS = 1000                                   # point ranking
N_BOOT = 200                                    # coefficient bootstrap replicates
N_SIMS_BOOT = 300
N_BOOT_FALSIFICATION = 500
SEED = 7
SEED_BOOT = 20251010
HOUR_BLOCK = 24

EVENTS = {
    "FTX_Nov2022": {
        "window": (dt.date(2022, 10, 1), dt.date(2022, 11, 16)),
        "event": (pd.Timestamp("2022-11-08 00:00"), pd.Timestamp("2022-11-11 23:00")),
        "calm": (pd.Timestamp("2022-10-12 00:00"), pd.Timestamp("2022-10-13 23:00")),
    },
    "USDC_SVB_Mar2023": {
        "window": (dt.date(2023, 2, 1), dt.date(2023, 3, 16)),
        "event": (pd.Timestamp("2023-03-10 00:00"), pd.Timestamp("2023-03-13 23:00")),
        "calm": (pd.Timestamp("2023-02-22 00:00"), pd.Timestamp("2023-02-23 23:00")),
    },
}


# ---------------------------------------------------------------------------
# power and block length
# ---------------------------------------------------------------------------
def k_max_of(parents: dict, nodes) -> int:
    """Largest number of regressors of any equation: intercept, lagged stress and flow of
    each parent inside the node set (2 |pa(e)| + 1)."""
    nodes = set(nodes)
    counts = [2 * sum(1 for p in parents.get(e, []) if p in nodes) + 1 for e in nodes]
    return max(counts) if counts else 1


def block_len_for(res: str, n_fit: int) -> int:
    """Moving-block length: 24 hours at hourly resolution; about n^(1/3) days at daily
    resolution (at least 2)."""
    if res == "hour":
        return HOUR_BLOCK
    return max(2, int(round(n_fit ** (1.0 / 3.0))))


def check_min_rows(n_fit: int, k_max: int, res: str) -> dict:
    """ok if the fit has at least max(MIN_FIT_ROWS, ROWS_PER_PARAM * k_max) rows."""
    need = max(MIN_FIT_ROWS[res], ROWS_PER_PARAM * int(k_max))
    out = {"ok": bool(n_fit >= need), "n_fit_rows": int(n_fit), "k_max": int(k_max),
           "min_rows_required": int(need), "block_len": int(block_len_for(res, n_fit))}
    if not out["ok"]:
        out["reason"] = "underpowered"
    return out


# ---------------------------------------------------------------------------
# one window
# ---------------------------------------------------------------------------
def _base(name, res, window, ev) -> dict:
    return {"event": name, "resolution": res, "ok": False,
            "window": [str(window[0]), str(window[1])],
            "event_window": [str(ev[0]), str(ev[1])]}


def analyze_window(name, flows, prices, window, ev, res: str, calm=None, *,
                   n_sims: int = N_SIMS, n_boot: int = N_BOOT, n_sims_boot: int = N_SIMS_BOOT,
                   n_boot_falsification: int = N_BOOT_FALSIFICATION, seed: int = SEED,
                   seed_boot: int = SEED_BOOT) -> dict:
    """Fit VEIN on the pre-event rows of one window and score the event.

    flows:  resolved flows at resolution `res` (columns day, from_entity, to_entity,
            usd_volume, n_tx, from_src, to_src), top-k entities already collapsed.
    prices: raw (not forward-filled) price panel of config.MARKET_ASSETS, or empty.
    window: (start, end) of the data window; ev: (start, end) of the event; calm: optional
            (start, end) of a calm stretch inside the fit window, scored as a reference.
    """
    ev0, ev1 = pd.Timestamp(ev[0]), pd.Timestamp(ev[1])
    out = _base(name, res, window, (ev0, ev1))
    if flows is None or flows.empty:
        return {**out, "reason": "no flows"}
    flows = flows.copy()
    flows["day"] = pd.to_datetime(flows["day"])
    ents = sorted(set(flows.from_entity) | set(flows.to_entity) | set(EXTRA_ENTITIES))
    panel, meta = hs.build_hourly_stress(flows, ents, prices, lido=None, fit_end=ev0,
                                         roll=ROLL[res], min_periods=MIN_PERIODS[res],
                                         freq=FREQ[res], window=window)
    stress = panel.sort_index()
    pre = stress[stress.index < ev0]
    zero = hs.zero_stress_entities(stress, pre.index)
    stress = stress.drop(columns=zero)
    nodes = list(stress.columns)
    ev_idx = stress.index[(stress.index >= ev0) & (stress.index <= ev1)]
    graph = og.build_graph(flows, min_usd=MIN_USD, include_documented=False)
    parents = {e: [p for p in graph["parents"].get(e, []) if p in nodes] for e in nodes}
    k_max = k_max_of(parents, nodes)
    chk = check_min_rows(len(pre) - 1, k_max, res)
    n_edges = sum(1 for ed in graph["edges"] if ed["from"] in nodes and ed["to"] in nodes)
    out.update(entities=nodes, n_entities=len(nodes), zero_stress_dropped=zero,
               stress_components={e: meta[e] for e in nodes},
               n_fit_rows=len(pre), n_event_rows=len(ev_idx), n_edges=n_edges,
               k_max=chk["k_max"], min_rows_required=chk["min_rows_required"],
               block_len=chk["block_len"])
    if len(ev_idx) == 0:
        return {**out, "reason": "no event rows"}
    if not chk["ok"]:
        return {**out, "reason": "underpowered"}
    blk = chk["block_len"]

    # --- fit on the pre-event rows and rank -----------------------------------
    fl_fit = flows[flows.day < ev0]
    scm = StructuralCausalModel(graph, alpha=1.0).fit(pre[nodes], fl_fit).set_flows(flows)
    s_star = risk.fit_window_s_star(stress, pre.index, S_STAR_Q)
    init = pre.iloc[-1].to_dict()
    point = fs.systemic_ranking_fast(scm, ev_idx, init, s_star, n_sims=n_sims, seed=seed,
                                     block_len=blk)
    point_E = point.set_index("entity").loc[nodes, "exported_risk"].to_numpy(dtype=float)
    E_all = un.ranking_draws(scm, pre[nodes], fl_fit, ev_idx, s_star, init, n_boot=n_boot,
                             n_sims=n_sims_boot, block_len=blk, q=0.95, seed=seed_boot)
    summ = un.summarize_ranking(E_all, nodes, point_E, n_top=6)
    by = summ["by_entity"]
    order = sorted(nodes, key=lambda e: by[e]["rank_point"])
    out["oc_ranking"] = [{"entity": e, "exported_risk": float(point_E[nodes.index(e)]),
                          "rank_point": by[e]["rank_point"], "rank_ci95": by[e]["rank_ci95"],
                          "p_top3": by[e]["p_top3"]} for e in order[:6]]

    # --- falsification: edge direction and reversal ---------------------------
    fal = fz.run_falsification(graph, pre[nodes], fl_fit, stress, flows, ev_idx)
    fit_m, ev_m = val.event_masks(stress, ev0, ev1)
    err_true = val.onestep_errors(stress, flows, graph["parents"], fit_m, ev_m)
    err_rev = val.onestep_errors(stress, flows, fz.reverse_graph(graph)["parents"], fit_m, ev_m)
    err_sym = val.onestep_errors(stress, flows, fz.symmetric_graph(graph)["parents"], fit_m, ev_m)
    fal_ci = {"reversed_minus_true": val.paired_difference_ci(err_true, err_rev, B=n_boot_falsification,
                                                             block_len=blk, seed=seed),
              "symmetric_minus_true": val.paired_difference_ci(err_true, err_sym, B=n_boot_falsification,
                                                               block_len=blk, seed=seed)}

    # --- placebo: calm windows of the fit period ------------------------------
    precrisis = {e: float(pre[e].median()) for e in nodes}
    connected = val.connected_pairs(graph, nodes, set(nodes))
    rolling = val.rolling_temporal_placebo(scm, stress, pre.index, ev_idx, precrisis, connected,
                                           step=blk, roll=ROLL[res], gap=blk)
    out.update(oc_ranking_settings={"n_sims": n_sims, "seed": seed, "block_len": blk,
                                    "n_boot": n_boot, "n_sims_boot": n_sims_boot,
                                    "seed_boot": seed_boot, "s_star_q": S_STAR_Q},
               falsification=fal.to_dict("records"), falsification_ci=fal_ci,
               placebo_rolling=rolling, calm_window=_calm_stat(scm, stress, nodes, calm,
                                                               precrisis, connected))
    out["usdc_peg_min"] = _usdc_min(prices, ev0, ev1)
    out["ok"] = True
    return out


def _calm_stat(scm, stress, nodes, calm, precrisis, connected):
    """Attribution statistic of a calm stretch, for reference next to the event value."""
    if calm is None:
        return None
    c0, c1 = pd.Timestamp(calm[0]), pd.Timestamp(calm[1])
    days = stress.index[(stress.index >= c0) & (stress.index <= c1)]
    if len(days) == 0 or stress.index.get_loc(days[0]) < 1:
        return None
    p0 = stress.index.get_loc(days[0])
    sys = fs.from_scm(scm)
    S_prev0 = stress.iloc[p0 - 1][nodes].values.astype(float)
    S_obs = stress.loc[days, nodes].values.astype(float)
    C = fs.drift(sys, fs.log_flows(scm, days))
    stat = val._stat_from(sys, C, S_obs, S_prev0, fs._vec(nodes, precrisis), connected, nodes)
    return {"window": [str(days[0]), str(days[-1])], "n_rows": int(len(days)), "stat": float(stat)}


def _usdc_min(prices, ev0, ev1):
    if prices is None or prices.empty or "USDC" not in prices.columns:
        return None
    w = prices["USDC"].sort_index().loc[ev0:ev1].dropna()
    return float(w.min()) if len(w) else None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def run_event(name: str, spec: dict) -> dict:
    s, e = spec["window"]
    flows_h, prices_h = pl.load_window_inputs(s, e, TOKENS, bucket="hour",
                                              min_addr_volume=MIN_ADDR_VOLUME["hour"], k=K_ENTITIES)
    hourly = analyze_window(name, flows_h, prices_h, (s, e), spec["event"], "hour",
                            calm=spec["calm"])
    flows_d, prices_d = pl.load_window_inputs(s, e, TOKENS, bucket="day",
                                              min_addr_volume=MIN_ADDR_VOLUME["day"], k=K_ENTITIES)
    daily = analyze_window(name, flows_d, prices_d, (s, e), spec["event"], "day",
                           calm=spec["calm"])
    hourly["daily_robustness"] = daily
    return hourly


def main():
    out = {"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND,
           "primary_resolution": "hour", "events": []}
    for name, spec in EVENTS.items():
        print(f"[event] {name} ...", flush=True)
        try:
            out["events"].append(run_event(name, spec))
        except Exception as ex:  # noqa: BLE001
            out["events"].append({"event": name, "ok": False, "reason": str(ex)})
        print("   done", flush=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "multievent.json").write_text(json.dumps(out, indent=2, default=float))
    print("WROTE results/multievent.json")


if __name__ == "__main__":
    main()
