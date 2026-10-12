#!/usr/bin/env python3
"""Out-of-sample R^2 and own-lag baseline on the Oct-2025 event window -> results/oos_r2.json, OOS_R2.md.

Reads the cached hourly context (no new queries). See vein/oos.py for the specification."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np

from vein import config, hourly_stress as hs, pipeline as pl, oos
from vein.scm import StructuralCausalModel

RESULTS = Path(__file__).resolve().parent / "results"


def main():
    ctx = pl.build_hourly_context(k=12)
    stress, flows, graph = ctx.stress, ctx.flows, ctx.graph
    EV0, EV1 = pl.EVENT_START, pl.EVENT_END
    est = stress.index[stress.index < EV0]
    hs.assert_nonzero_stress(stress, est)
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress.loc[est], flows[flows.day < EV0]).set_flows(flows)
    ev = stress.index[(stress.index >= EV0) & (stress.index <= EV1)]
    res = oos.rolling_one_step(scm, stress, flows, ev)
    s = oos.summarize(res)
    s.update({"generated": dt.date.today().isoformat(), "data_backend": config.DATA_BACKEND,
              "event_window": [str(ev[0]), str(ev[-1])], "n_fit_hours": int(len(est))})
    (RESULTS / "oos_r2.json").write_text(json.dumps(s, indent=2, default=float))

    L = ["# Out-of-sample R-squared and own-lag baseline (Oct 2025 event window)\n",
         f"_{s['design']}. {s['n_event_hours']} event hours, {s['n_cells']} entity-hour cells, "
         f"{len(res['nodes'])} entities. R2_OS = 1 - SSE(model)/SSE(expanding mean)._\n",
         "| model | pooled R2_OS | 95% CI (24 h blocks) | 95% CI (8 h blocks) | equal-weight mean over entities |", "|---|--:|--:|--:|--:|"]
    for m in oos.MODELS[1:]:
        p = s["pooled"][m]
        L.append(f"| {m} | {p['r2_os']:+.4f} | [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}] | "
                 f"[{p['ci95_block8'][0]:+.4f}, {p['ci95_block8'][1]:+.4f}] | {p['macro_mean_r2_os']:+.4f} |")
    L += ["", "Gain over the own-lag model, 1 - SSE(model)/SSE(ar):\n",
          "| model | gain | 95% CI (24 h) | 95% CI (8 h) |", "|---|--:|--:|--:|"]
    for m, g in s["increment_over_ar"].items():
        L.append(f"| {m} | {g['gain']:+.4f} | [{g['ci95'][0]:+.4f}, {g['ci95'][1]:+.4f}] | "
                 f"[{g['ci95_block8'][0]:+.4f}, {g['ci95_block8'][1]:+.4f}] |")
    L += ["", "| entity | ar | network | ar_network | network vs ar | ar_network vs ar |",
          "|---|--:|--:|--:|--:|--:|"]
    f = lambda v: "n/a" if v is None else f"{v:+.3f}"
    for e, r in s["by_entity"].items():
        L.append(f"| {e} | {f(r['ar'])} | {f(r['network'])} | {f(r['ar_network'])} | "
                 f"{f(r['network_vs_ar'])} | {f(r['ar_network_vs_ar'])} |")
    L += ["", "The event window has 48 hours, so 24-hour blocks give two blocks and the intervals are "
          "indicative. Entities whose benchmark SSE is zero show n/a."]
    (RESULTS / "OOS_R2.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
