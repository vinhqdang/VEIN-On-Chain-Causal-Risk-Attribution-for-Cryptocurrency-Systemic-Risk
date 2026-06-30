"""Structural Causal Model (algorithm.md Sections 2.3-2.5).

The structural equation for each entity i is

    S_{i,t} = f_i( S_{pa(i), t-1},  F_{pa(i)->i, t},  U_{i,t} )

with pa(i) read off the observed on-chain graph (NOT statistically inferred).
f_i is the only estimated component: a ridge-regularized linear map of the
lagged parent stresses and the contemporaneous parent->i flows. The temporal
lag on parent stress (identifying assumption A1, blockchain timestamping) makes
the multi-entity system a well-defined recursive dynamical system even when the
flow graph contains cycles — we simulate it forward one day at a time.

This module fits {f_i}, exposes forward simulation with do-interventions, and
recovers exogenous shocks U (abduction) for counterfactual queries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


class StructuralCausalModel:
    def __init__(self, graph: dict, alpha: float = 1.0):
        self.graph = graph
        self.nodes = graph["nodes"]
        self.parents = graph["parents"]
        self.alpha = alpha
        self.coef_: dict[str, dict] = {}     # entity -> {parents, w_stress, w_flow, b}
        self.resid_: dict[str, pd.Series] = {}
        self.stress_cols: list[str] = []

    # ------------------------------------------------------------------ fit
    def _flow_feature(self, flows_pivot, parent, child, index):
        key = (parent, child)
        if key in flows_pivot:
            return np.log1p(flows_pivot[key].reindex(index).fillna(0.0).values)
        return np.zeros(len(index))

    def fit(self, stress: pd.DataFrame, flows: pd.DataFrame):
        self.stress_cols = list(stress.columns)
        # pivot flows -> dict[(from,to)] = daily usd series
        fp = {}
        for (i, j), g in flows.groupby(["from_entity", "to_entity"]):
            fp[(i, j)] = g.set_index("day").usd_volume
        self._flows_pivot = fp
        idx = stress.index

        for ent in self.stress_cols:
            par = [p for p in self.parents.get(ent, []) if p in self.stress_cols]
            y = stress[ent].values[1:]                      # S_{i,t}, t>=1
            feats = []
            names = []
            for p in par:
                feats.append(stress[p].values[:-1])         # S_{p,t-1}
                names.append(f"stress[{p}]")
            for p in par:
                ff = self._flow_feature(fp, p, ent, idx)[1:]  # F_{p->i,t}
                feats.append(ff)
                names.append(f"flow[{p}->{ent}]")
            if feats:
                X = np.column_stack(feats)
            else:
                X = np.zeros((len(y), 0))
            if X.shape[1] == 0:
                # no parents: pure exogenous entity, f_i = mean
                b = float(np.mean(y)) if len(y) else 0.0
                self.coef_[ent] = {"parents": [], "w_stress": np.array([]),
                                   "w_flow": np.array([]), "b": b, "names": []}
                pred = np.full(len(y), b)
            else:
                model = Ridge(alpha=self.alpha, fit_intercept=True)
                model.shape_in = X.shape[1]
                model.fit(X, y)
                npar = len(par)
                self.coef_[ent] = {
                    "parents": par,
                    "w_stress": model.coef_[:npar],
                    "w_flow": model.coef_[npar:2 * npar],
                    "b": float(model.intercept_),
                    "names": names,
                }
                pred = model.predict(X)
            self.resid_[ent] = pd.Series(y - pred, index=idx[1:])
        return self

    # ----------------------------------------------------------- evaluate f_i
    def _f(self, ent, prev_stress: dict, flow_t: dict) -> float:
        c = self.coef_[ent]
        val = c["b"]
        for k, p in enumerate(c["parents"]):
            val += c["w_stress"][k] * prev_stress.get(p, 0.0)
            val += c["w_flow"][k] * np.log1p(flow_t.get((p, ent), 0.0))
        return val

    def set_flows(self, flows: pd.DataFrame):
        """Repoint the flow lookup (e.g. to full-window flows for event sim)."""
        self._flows_pivot = {(i, j): g.set_index("day").usd_volume
                             for (i, j), g in flows.groupby(["from_entity", "to_entity"])}
        return self

    def flow_on(self, parent, child, day) -> float:
        s = self._flows_pivot.get((parent, child))
        if s is None:
            return 0.0
        try:
            return float(s.loc[s.index == day].sum())
        except Exception:
            return 0.0

    # ------------------------------------------------------ forward simulation
    def simulate(self, days, init_stress: dict, U: dict,
                 do: dict | None = None) -> pd.DataFrame:
        """Simulate the stress system forward over `days`.

        init_stress: stress at day before the window (dict entity->value)
        U: dict entity-> array of exogenous shocks aligned to `days`
        do: dict entity-> array (or scalar) forcing that entity's stress
            (severs its structural equation / parents per the do-operator).
        """
        do = do or {}
        prev = dict(init_stress)
        out = {e: np.zeros(len(days)) for e in self.stress_cols}
        for ti, day in enumerate(days):
            cur = {}
            flow_t = {}
            for e in self.stress_cols:
                for p in self.coef_[e]["parents"]:
                    flow_t[(p, e)] = self.flow_on(p, e, day)
            for e in self.stress_cols:
                if e in do:
                    dv = do[e]
                    cur[e] = float(dv[ti] if np.ndim(dv) else dv)
                else:
                    u = U.get(e, np.zeros(len(days)))
                    cur[e] = self._f(e, prev, flow_t) + (u[ti] if ti < len(u) else 0.0)
            for e in self.stress_cols:
                out[e][ti] = cur[e]
            prev = cur
        return pd.DataFrame(out, index=pd.DatetimeIndex(days))

    # --------------------------------------------------------------- abduction
    def abduct(self, stress: pd.DataFrame, days) -> dict:
        """Recover realized exogenous shocks U_hat over `days` (Pearl step 1)."""
        U = {}
        for e in self.stress_cols:
            ser = self.resid_[e].reindex(pd.DatetimeIndex(days)).fillna(0.0)
            U[e] = ser.values
        return U

    def residual_std(self) -> dict:
        return {e: float(self.resid_[e].std() or 0.0) for e in self.stress_cols}
