"""Edge-reversal falsification test for assumption A3 (algorithm.md Section 2.6).

If on-chain flow *direction* carries genuine causal information, the
true-direction SCM should predict the timing and magnitude of the Oct-2025
distress propagation better than (a) a reversed-edge SCM and (b) a symmetric
(undirected) SCM. We fit each variant on the estimation window and score
one-step-ahead prediction of stress over the event window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scm import StructuralCausalModel


def reverse_graph(graph: dict) -> dict:
    nodes = graph["nodes"]
    parents = {n: [] for n in nodes}
    edges = []
    for e in graph["edges"]:
        edges.append({"from": e["to"], "to": e["from"],
                      "usd_volume": e["usd_volume"], "n_tx": e["n_tx"],
                      "confidence": e["confidence"]})
        parents[e["from"]].append(e["to"])      # reversed: to becomes parent of from
    return {"nodes": nodes, "edges": edges, "parents": parents}


def symmetric_graph(graph: dict) -> dict:
    nodes = graph["nodes"]
    parents = {n: set() for n in nodes}
    for e in graph["edges"]:
        parents[e["from"]].add(e["to"])
        parents[e["to"]].add(e["from"])
    return {"nodes": nodes, "edges": graph["edges"],
            "parents": {n: sorted(p) for n, p in parents.items()}}


def one_step_accuracy(scm: StructuralCausalModel, stress: pd.DataFrame,
                      flows: pd.DataFrame, event_days) -> dict:
    """One-step-ahead prediction error over event_days using actual t-1 stress
    and actual contemporaneous flows. Returns RMSE and timing correlation,
    aggregated across entities (weighted by realized stress)."""
    ev = pd.DatetimeIndex(event_days)
    preds, actuals, weights = [], [], []
    for ent in scm.stress_cols:
        c = scm.coef_[ent]
        for day in ev:
            if day not in stress.index:
                continue
            ploc = stress.index.get_loc(day)
            if ploc == 0:
                continue
            prev_day = stress.index[ploc - 1]
            prev = {p: stress.at[prev_day, p] for p in c["parents"] if p in stress.columns}
            flow_t = {(p, ent): scm.flow_on(p, ent, day) for p in c["parents"]}
            yhat = scm._f(ent, prev, flow_t)
            y = stress.at[day, ent]
            preds.append(yhat); actuals.append(y); weights.append(abs(y) + 0.1)
    preds = np.array(preds); actuals = np.array(actuals); weights = np.array(weights)
    if len(preds) == 0:
        return {"rmse": np.nan, "corr": np.nan, "n": 0}
    err = preds - actuals
    rmse = float(np.sqrt(np.average(err ** 2, weights=weights)))
    corr = float(np.corrcoef(preds, actuals)[0, 1]) if np.std(preds) > 0 and np.std(actuals) > 0 else 0.0
    return {"rmse": rmse, "corr": corr, "n": len(preds)}


def run_falsification(graph: dict, stress_est: pd.DataFrame, flows_est: pd.DataFrame,
                      stress_full: pd.DataFrame, flows_full: pd.DataFrame,
                      event_days, alpha: float = 1.0) -> pd.DataFrame:
    """Fit true/reversed/symmetric SCMs on estimation data; score on event window."""
    variants = {
        "true_direction": graph,
        "reversed_edges": reverse_graph(graph),
        "symmetric": symmetric_graph(graph),
    }
    rows = []
    for name, g in variants.items():
        scm = StructuralCausalModel(g, alpha=alpha).fit(stress_est, flows_est)
        # use full-window flows for event-window scoring (need event-day flows)
        scm._flows_pivot = {(i, j): grp.set_index("day").usd_volume
                            for (i, j), grp in flows_full.groupby(["from_entity", "to_entity"])}
        acc = one_step_accuracy(scm, stress_full, flows_full, event_days)
        rows.append({"model": name, **acc})
    return pd.DataFrame(rows)
