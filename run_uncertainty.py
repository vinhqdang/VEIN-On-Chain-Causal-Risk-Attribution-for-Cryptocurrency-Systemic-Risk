#!/usr/bin/env python3
"""Sampling uncertainty for the hourly evaluation -> results/uncertainty.json.

Reads the same cached hourly context as run_best.py (vein/pipeline.py), fits the SCM on the
pre-event hours and reports, with intervals:
  * the OC-CoVaR ranking: point estimate (2000 paths), Monte Carlo error (20 seeds of 500
    paths) and coefficient-bootstrap intervals of the exported risk and rank;
  * the counterfactual attribution of the top channels and the named channels, and the
    Shapley split of the Bybit loss;
  * in-sample R^2 of each equation.
Coefficient draws: 300 joint circular-block pairs bootstrap replicates of the fit-window rows
(24 h blocks) with a ridge refit (alpha=1). s* is the fit-window 95th percentile, fixed.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np

from vein import config, fastscm as fs, hourly_stress as hs, pipeline as pl, risk, uncertainty as un
from vein.scm import StructuralCausalModel

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)
N_BOOT = 300
N_SIMS = 500
N_SIMS_POINT = 2000
N_REP_MC = 20
BLOCK_LEN = 24
Q = 0.95
SEED_BOOT = 20251010
SEED_ATTR = 20251011
SEED_POINT = 7
S_STAR_Q = 0.95
TOP_CHANNELS = 10
NAMED_CHANNELS = [("Binance", "Bybit"), ("Ethena", "Aave"), ("Ethena", "Binance"), ("Lido", "Aave")]
SHAPLEY_TARGET = "Bybit"
SHAPLEY_CANDS = ["Binance", "Coinbase", "Bitfinex"]


def ci(x, lo=0.025, hi=0.975):
    x = np.asarray(x, dtype=float)
    return [float(np.quantile(x, lo)), float(np.quantile(x, hi))]


def main():
    ctx = pl.build_hourly_context(k=12)
    stress, flows, graph = ctx.stress, ctx.flows, ctx.graph
    EV0, EV1 = pl.EVENT_START, pl.EVENT_END
    fit_mask = stress.index < EV0
    est = stress.index[fit_mask]
    hs.assert_nonzero_stress(stress, est)
    stress_fit = stress.loc[est]
    flows_fit = flows[flows.day < EV0]
    scm = StructuralCausalModel(graph, alpha=1.0).fit(stress_fit, flows_fit).set_flows(flows)
    nodes = list(scm.stress_cols)
    sys = fs.from_scm(scm)
    ev = list(stress.index[(stress.index >= EV0) & (stress.index <= EV1)])
    pos0 = stress.index.get_loc(ev[0])
    S_prev0 = stress.iloc[pos0 - 1][nodes].values.astype(float)
    init = {e: float(S_prev0[i]) for i, e in enumerate(nodes)}
    s_star = risk.fit_window_s_star(stress, est, S_STAR_Q)
    s_vec = np.array([s_star[e] for e in nodes])
    precrisis = stress_fit.median()[nodes].values.astype(float)
    S_obs = stress.loc[ev, nodes].values.astype(float)
    C = fs.drift(sys, fs.log_flows(scm, ev))
    print(f"[1] {len(nodes)} entities, {len(est)} fit hours, {len(ev)} event hours")

    # ------------------------------------------------------------ ranking
    print("[2] point ranking and Monte Carlo error")
    point = fs.systemic_ranking_fast(scm, ev, init, s_star, n_sims=N_SIMS_POINT,
                                     seed=SEED_POINT, block_len=BLOCK_LEN, q=Q)
    point_E = point.set_index("entity").loc[nodes, "exported_risk"].values
    mc = un.mc_error(sys, C, S_prev0, s_vec, n_rep=N_REP_MC, n_sims=N_SIMS,
                     block_len=BLOCK_LEN, seed0=1000)
    print("[3] coefficient bootstrap of the ranking")
    E_all = un.ranking_draws(scm, stress_fit, flows_fit, ev, s_vec, init, n_boot=N_BOOT,
                             n_sims=N_SIMS, block_len=BLOCK_LEN, q=Q, seed=SEED_BOOT)
    summ = un.summarize_ranking(E_all, nodes, point_E)
    rank_point = {e: int(summ["by_entity"][e]["rank_point"]) for e in nodes}
    ranking = {
        "point": [{"entity": e, "exported_risk": float(point_E[i]), "rank": rank_point[e],
                   "mc_se": float(mc["se_point"][i])} for i, e in
                  sorted(enumerate(nodes), key=lambda t: rank_point[t[1]])],
        "mc_error": {"n_rep": N_REP_MC, "n_sims": N_SIMS,
                     "sd_by_entity": {e: float(mc["sd"][i]) for i, e in enumerate(nodes)},
                     "se_point_by_entity": {e: float(mc["se_point"][i]) for i, e in enumerate(nodes)}},
        "by_entity": summ["by_entity"],
        "pairwise_top6": summ["pairwise_top6"],
        "spearman_vs_point": summ["spearman_vs_point"],
        "external_validity": {"p_all_transmitters_above_absorbers":
                              summ["external_validity"]["p_all_transmitters_above_absorbers"],
                              "mean_concordance": summ["external_validity"]["mean_concordance"],
                              "transmitters": summ["external_validity"]["transmitters"],
                              "absorbers": summ["external_validity"]["absorbers"]},
    }

    # ------------------------------------------------------------ attribution
    print("[4] attribution, bootstrap of attribution and Shapley split")
    mat = fs.attribution_matrix(sys, C, S_obs, S_prev0, precrisis)
    draws = un.attribution_draws(scm, stress_fit, flows_fit, ev, S_obs, S_prev0, precrisis,
                                 n_boot=N_BOOT, block_len=BLOCK_LEN, seed=SEED_ATTR)
    pairs = [(i, j) for i in range(len(nodes)) for j in range(len(nodes))
             if i != j and mat["L_obs"][i, j] > 0]
    ranked = sorted(pairs, key=lambda p: -mat["share"][p[0], p[1]])[:TOP_CHANNELS]
    chosen = [(p, "top10") for p in ranked]
    for a, b in NAMED_CHANNELS:
        if a in nodes and b in nodes:
            p = (nodes.index(a), nodes.index(b))
            if p not in ranked:
                chosen.append((p, "named"))
    channels = []
    for (i, j), how in chosen:
        ad, sd = draws["attr"][:, i, j], draws["share"][:, i, j]
        channels.append({"i": nodes[i], "j": nodes[j], "attribution": float(mat["attr"][i, j]),
                         "share": float(mat["share"][i, j]),
                         "attribution_ci95": ci(ad), "share_ci95": ci(sd),
                         "p_positive": float(np.mean(ad > 0)), "selected_by": how,
                         "share_boot_median": float(np.median(sd)),
                         "share_ci_contains_point": bool(ci(sd)[0] <= mat["share"][i, j] <= ci(sd)[1])})
    max_point = float(max([mat["share"][p] for p in pairs] or [0.0]))
    max_rep = np.array([max([draws["share"][r][p] for p in pairs] or [0.0])
                        for r in range(N_BOOT)])
    r2_point = un.r2_in_sample(sys, stress_fit)
    r2_orig = {e: [draws["r2"][r][e] for r in range(N_BOOT)] for e in nodes}
    r2_own = {e: [draws["r2_own"][r][e] for r in range(N_BOOT)] for e in nodes}
    r2_report = {}
    for e in nodes:
        own, orig = np.array(r2_own[e]), np.array(r2_orig[e])
        optimism = float(np.nanmean(own - orig))
        r2_report[e] = {
            "point": r2_point[e],
            # percentile interval of the in-sample R^2 statistic recomputed on each resample
            "ci95": ci(own[np.isfinite(own)]),
            "boot_mean_own": float(np.nanmean(own)),
            "optimism": optimism,
            "point_optimism_corrected": float(r2_point[e] - optimism),
            # percentile interval of point - (own - orig) over replicates (Efron-Tibshirani optimism)
            "optimism_corrected_ci95": ci(r2_point[e] - (own - orig)[np.isfinite(own - orig)]),
            "point_in_ci95": bool(ci(own[np.isfinite(own)])[0] - 1e-9 <= r2_point[e]
                                  <= ci(own[np.isfinite(own)])[1] + 1e-9),
            # diagnostic only: refit coefficients scored on the original rows
            "refit_on_original_rows_ci95": ci(orig[np.isfinite(orig)]),
        }

    shap = None
    if SHAPLEY_TARGET in nodes:
        cands = [c for c in SHAPLEY_CANDS if c in nodes]
        point_sh = un.shapley_split(sys, C, S_obs, S_prev0, precrisis, SHAPLEY_TARGET, cands)
        reps = []
        for r, rows, sys_r, C_r in un.bootstrap_systems(scm, stress_fit, flows_fit, ev,
                                                        N_BOOT, SEED_ATTR, BLOCK_LEN):
            reps.append(un.shapley_split(sys_r, C_r, S_obs, S_prev0, precrisis, SHAPLEY_TARGET, cands))
        shap = {"target": SHAPLEY_TARGET, "candidates": cands,
                "point": {c: float(point_sh["values"][c]) for c in cands},
                "ci95": {c: ci([x["values"][c] for x in reps]) for c in cands},
                "additive_residual_max": float(max([abs(point_sh["additive_residual"])] +
                                                   [abs(x["additive_residual"]) for x in reps]))}

    out = {
        "generated": dt.date.today().isoformat(),
        "data_backend": config.DATA_BACKEND,
        "settings": {"n_boot": N_BOOT, "n_sims": N_SIMS, "n_sims_point": N_SIMS_POINT,
                     "block_len": BLOCK_LEN, "block_unit": "hours", "q": Q,
                     "seed_boot": SEED_BOOT, "seed_attr": SEED_ATTR, "seed_point": SEED_POINT,
                     "coefficients": "joint circular-block pairs bootstrap of fit-window rows, ridge refit alpha=1; replicate shock pool = residuals of the drawn rows",
                     "s_star": f"fixed: fit-window {S_STAR_Q} quantile",
                     "event_window": [str(ev[0]), str(ev[-1])],
                     "fit_window": [str(est[0]), str(est[-1])], "n_fit_rows": int(len(est))},
        "ranking": ranking,
        "attribution": {
            "channels": channels,
            "note": "top10 selected on point estimate; CIs not selection-adjusted",
            "max_share": {"point": max_point, "ci95": ci(max_rep)},
            "r2_in_sample": r2_report,
            "r2_note": ("ci95 = percentile interval of the in-sample R^2 recomputed on each bootstrap "
                        "resample (refit on the resample, scored on the resample). It covers the "
                        "point but sits above it: a refit scored on its own resample is optimistic by "
                        "`optimism` (mean of own minus original-rows R^2), so the honest level is "
                        "point_optimism_corrected with optimism_corrected_ci95; see oos_r2.json for "
                        "out-of-sample R^2. The earlier interval (refit scored on the original rows) "
                        "sat below the point by the same optimism and is kept as "
                        "refit_on_original_rows_ci95 (diagnostic only)."),
            "shapley_bybit": shap,
        },
    }
    (RESULTS / "uncertainty.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"WROTE {RESULTS / 'uncertainty.json'}")


if __name__ == "__main__":
    main()
