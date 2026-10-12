#!/usr/bin/env python3
"""Decisive intraday A3 falsification test (algorithm.md Sections 2.6, 5.2.3).

The daily test had only ~6 points over the Oct-2025 cascade — far too few to
detect propagation timing/direction. On-chain transfers carry block-level
timestamps, so we rebuild the SAME real data at HOURLY resolution and re-run the
edge-reversal test with real statistical power. Stress here is purely
flow-derived (net-outflow ratio + transfer-volume spike), which is exactly the
intraday signal that resolves at the hour scale.

Verdict logic (classify_a3, numbers only):
  - true direction wins by more than 2% RMSE and the paired CI is above 0 -> A3 supported
  - reversed graph wins by more than 2% RMSE and the paired CI is below 0 -> A3 contradicted
  - otherwise -> no direction effect detected (no claim about why the daily run differed).

Outputs results/INTRADAY_A3.md and results/intraday_a3.json.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from vein import config, pipeline as pl
from vein import falsification as fz, validation as val

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

WIN_START = dt.date(2025, 10, 1)        # pre-event baseline for fitting f_i
WIN_END = dt.date(2025, 10, 14)
EVENT_START = pd.Timestamp("2025-10-10 00:00")
EVENT_END = pd.Timestamp("2025-10-11 23:59")
TOKENS = ["USDe", "sUSDe", "wBETH", "USDC", "USDT"]
ROLL = 48                               # 48-hour rolling window for z-scores


def classify_a3(rel_gap: float, ci_reversed_minus_true, tie: float = 0.02) -> str:
    """Verdict from the numbers only. rel_gap = (RMSE reversed - RMSE true) / RMSE true;
    ci_reversed_minus_true = 95% CI of the paired squared-error difference (reversed minus true).
    A3 is supported only if the true direction wins by more than `tie` AND the CI is above 0;
    contradicted only if the reversed graph wins by more than `tie` AND the CI is below 0."""
    lo, hi = float(ci_reversed_minus_true[0]), float(ci_reversed_minus_true[1])
    if rel_gap > tie and lo > 0:
        return "A3_SUPPORTED"
    if rel_gap < -tie and hi < 0:
        return "A3_REFUTED_REVERSAL"
    return "NO_DIFFERENCE_DETECTED"


def main():
    print(f"[1/4] Hourly resolved flows, prices, Lido series ({config.DATA_BACKEND}) ...")
    ctx = pl.build_hourly_context(k=12, win=(WIN_START, WIN_END), tokens=TOKENS)
    flows, stress, graph, entities = ctx.flows, ctx.stress.sort_index(), ctx.graph, ctx.entities
    print(f"      {len(flows)} hourly rows; {flows.day.nunique()} hours; {len(entities)} entities")

    print("[2/4] Hourly stress (shared builder) + observed graph ...")

    ev = stress.index[(stress.index >= EVENT_START) & (stress.index <= EVENT_END)]
    est_stress = stress[stress.index < EVENT_START]
    est_flows = flows[flows.day < EVENT_START]
    print(f"      stress {stress.shape}; fit hours {len(est_stress)}; event hours {len(ev)}")

    print("[3/4] Edge-reversal falsification at hourly resolution ...")
    fal = fz.run_falsification(graph, est_stress, est_flows, stress, flows,
                               list(ev), alpha=1.0)
    print(fal.to_string(index=False))

    print("[4/4] Writing report ...")
    rows = {r["model"]: r for r in fal.to_dict(orient="records")}
    true_rmse = rows["true_direction"]["rmse"]
    rev_rmse = rows["reversed_edges"]["rmse"]
    true_corr = rows["true_direction"]["corr"]
    rev_corr = rows["reversed_edges"]["corr"]
    # classify: clear win for either side vs a near-tie (direction uninformative)
    rel_gap = (rev_rmse - true_rmse) / true_rmse      # >0 => true better
    TIE = 0.02                                         # within 2% RMSE = tie
    # paired circular-block bootstrap of the per-cell squared error (alt minus true; > 0 = true better)
    fit_m, ev_m = val.event_masks(stress, EVENT_START, EVENT_END)
    err_true = val.onestep_errors(stress, flows, graph["parents"], fit_m, ev_m)
    err_rev = val.onestep_errors(stress, flows, fz.reverse_graph(graph)["parents"], fit_m, ev_m)
    err_sym = val.onestep_errors(stress, flows, fz.symmetric_graph(graph)["parents"], fit_m, ev_m)
    paired = {"reversed_minus_true": val.paired_difference_ci(err_true, err_rev, B=2000, block_len=24, seed=7),
              "symmetric_minus_true": val.paired_difference_ci(err_true, err_sym, B=2000, block_len=24, seed=7)}
    ci_rev = paired["reversed_minus_true"]["ci95"]
    verdict_class = classify_a3(rel_gap, ci_rev, TIE)
    out = {"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND, "resolution": "hourly",
           "window": [str(WIN_START), str(WIN_END)],
           "event_hours": int(len(ev)), "fit_hours": int(len(est_stress)),
           "n_entities": len(entities), "n_predictions": int(rows["true_direction"]["n"]),
           "rmse_relative_gap_true_vs_reversed": float(rel_gap),
           "tie_threshold": TIE,
           "paired_bootstrap": paired,
           "falsification": fal.to_dict(orient="records"),
           "verdict": verdict_class}
    (RESULTS / "intraday_a3.json").write_text(json.dumps(out, indent=2, default=float))

    pr, ps = paired["reversed_minus_true"], paired["symmetric_minus_true"]
    numbers = (f"RMSE true {true_rmse:.4f}, reversed {rev_rmse:.4f}, symmetric "
               f"{rows['symmetric']['rmse']:.4f} over {rows['true_direction']['n']} predictions; "
               f"relative RMSE gap reversed vs true {rel_gap*100:+.2f}% (tie threshold "
               f"{TIE*100:.0f}%). Paired squared-error difference, reversed minus true "
               f"{pr['mean_diff']:+.4f}, 95% CI [{pr['ci95'][0]:+.4f}, {pr['ci95'][1]:+.4f}]; "
               f"symmetric minus true {ps['mean_diff']:+.4f}, 95% CI "
               f"[{ps['ci95'][0]:+.4f}, {ps['ci95'][1]:+.4f}] (circular blocks of 24 h over "
               f"{len(ev)} event hours).")
    verdicts = {
        "A3_SUPPORTED": ("**A3 supported at hourly resolution**: the true direction has the lower error "
                         "by more than the tie threshold and the paired CI excludes 0. " + numbers),
        "A3_REFUTED_REVERSAL": ("**A3 contradicted**: the reversed graph has the lower error by more than "
                                "the tie threshold and the paired CI excludes 0. " + numbers),
        "NO_DIFFERENCE_DETECTED": ("**No direction effect detected**: the RMSE gap is within the tie "
                                   "threshold or the paired CI includes 0. This is a statement about "
                                   "these data and this test only; it does not identify why the daily "
                                   "result differed, and it does not show that connectivity rather "
                                   "than direction carries the signal. " + numbers),
    }
    verdict = verdicts[verdict_class]
    md = [
        "# VEIN — Decisive Intraday A3 Falsification Test\n",
        f"_Hourly resolution, Oct 2025 cascade. Fit on {len(est_stress)} pre-event "
        f"hours, tested on {len(ev)} event hours (Oct 10–11). {len(entities)} "
        "entity-resolved nodes. Real on-chain token-transfer data._\n",
        "## Result\n",
        "| model | weighted RMSE | timing corr | n |",
        "|---|--:|--:|--:|",
    ]
    for r in fal.to_dict(orient="records"):
        md.append(f"| {r['model']} | {r['rmse']:.4f} | {r['corr']:.4f} | {r['n']} |")
    md += [
        "",
        f"true RMSE {true_rmse:.3f} (corr {true_corr:+.3f}) vs reversed RMSE "
        f"{rev_rmse:.3f} (corr {rev_corr:+.3f}).\n",
        f"## Verdict\n\n{verdict}\n",
        "## Why this is the decisive test\n",
        "## Design\n",
        "- Daily test: ~6 event points. Hourly test: "
        f"{len(ev)} event hours x {len(entities)} entities = {rows['true_direction']['n']} cells, "
        f"fitted on {len(est_stress)} pre-event hours.",
        "- Same on-chain data at a finer time bucket. The 48 event hours form two 24-hour blocks, so "
        "bootstrap intervals are indicative.",
    ]
    (RESULTS / "INTRADAY_A3.md").write_text("\n".join(md))
    print("Done. Wrote results/INTRADAY_A3.md")
    print("VERDICT:", verdict_class)


if __name__ == "__main__":
    main()
