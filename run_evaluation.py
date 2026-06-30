#!/usr/bin/env python3
"""VEIN end-to-end evaluation on real data (algorithm.md Sections 2-5).

Pipeline:
  1. Real market data (CoinGecko prices) + DefiLlama TVL.
  2. Real on-chain inter-entity flows (Dune SQL over decoded ERC-20 transfers).
  3. Build observed flow graph G; operationalize stress states S_{i,t}.
  4. Fit the SCM {f_i} on the estimation window.
  5. OC-CoVaR systemic ranking (H3) + Delta-CoVaR benchmark + Spearman divergence.
  6. Counterfactual attribution for the Oct-2025 USDe event (H4/H5).
  7. Edge-reversal falsification test (H2).
  8. VaR backtests (Kupiec / Christoffersen).
Outputs: results/results.json and results/EVALUATION.md.

Requires DUNE_API_KEY (source secrets.env). Market/TVL data are keyless.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from vein import config, market_data as md, onchain_graph as og, stress as st
from vein.scm import StructuralCausalModel
from vein import risk, falsification as fz, benchmarks as bm, backtest as bt

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

# Flow window kept to 2025 onward for the systemic-core tokens to stay within
# Dune free-tier credits while covering pre-crisis baseline + event + regime.
FLOW_START = dt.date(2025, 1, 1)
FLOW_END = config.REGIME_END
EST_CUTOFF = pd.Timestamp(config.ESTIMATION_END)


def jsonable(o):
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, dict): return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [jsonable(x) for x in o]
    if isinstance(o, pd.DataFrame): return jsonable(o.to_dict(orient="records"))
    return o


def main():
    out = {"generated": "2026-06-30", "data_window": [str(FLOW_START), str(FLOW_END)]}

    # ---- 1. market data + TVL (real, keyless) --------------------------------
    print("[1/8] Fetching market prices (CoinGecko) ...")
    prices = md.build_price_panel(config.MARKET_ASSETS, config.FULL_START, config.FULL_END)
    returns = md.log_returns(prices)
    eth_px = prices["ETH"] if "ETH" in prices else None
    print(f"      prices {prices.shape}, returns {returns.shape}")

    print("[2/8] Fetching protocol TVL (DefiLlama) ...")
    tvl = {}
    for ent, slug in config.DEFILLAMA_PROTOCOLS.items():
        try:
            tvl[slug] = md.defillama_tvl(slug)
        except Exception as e:  # noqa: BLE001 - TVL is optional; stress falls back to price drawdown
            print(f"      WARN: TVL fetch failed for {slug} ({e}); using price-drawdown proxy")
            tvl[slug] = pd.Series(dtype=float)
    print("      TVL slugs:", {k: len(v) for k, v in tvl.items()})

    # ---- 2. on-chain flows (real, Dune) --------------------------------------
    print("[3/8] Fetching on-chain inter-entity flows (Dune SQL) ...")
    flows = og.load_flows(FLOW_START, FLOW_END, eth_price=eth_px,
                          tokens=og.CORE_TOKENS)
    print(f"      flow rows {len(flows)}; days {flows.day.nunique()}")

    # ---- 3. graph + stress ---------------------------------------------------
    graph = og.build_graph(flows, min_usd=1e6)
    out["graph"] = {"nodes": graph["nodes"],
                    "edges": [(e["from"], e["to"], round(e["usd_volume"], 0), e["confidence"])
                              for e in graph["edges"]],
                    "parents": graph["parents"]}
    print(f"      graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")

    stress = st.build_stress_panel(flows, prices, tvl)
    stress = stress.sort_index()
    print(f"      stress panel {stress.shape}: {list(stress.columns)}")

    # event window days present in the panel
    ev_mask = (stress.index >= pd.Timestamp(config.EVENT_START)) & \
              (stress.index <= pd.Timestamp(config.EVENT_END))
    event_days = list(stress.index[ev_mask])
    est_stress = stress[stress.index <= EST_CUTOFF]
    est_flows = flows[flows.day <= EST_CUTOFF]
    out["n_event_days"] = len(event_days)

    # ---- 4. fit SCM ----------------------------------------------------------
    print("[4/8] Fitting structural equations f_i (Ridge) ...")
    scm = StructuralCausalModel(graph, alpha=1.0).fit(est_stress, est_flows)
    scm.set_flows(flows)   # use full-window flows for event-window simulation
    out["scm_residual_std"] = scm.residual_std()
    out["scm_coefficients"] = {
        e: {"parents": c["parents"],
            "w_stress": [round(x, 4) for x in np.atleast_1d(c["w_stress"]).tolist()],
            "w_flow": [round(x, 6) for x in np.atleast_1d(c["w_flow"]).tolist()],
            "intercept": round(c["b"], 4)}
        for e, c in scm.coef_.items()}

    # severe-distress level s* per entity = 95th pct of its stress over full window
    stress_hi = {e: float(np.quantile(stress[e].values, 0.95)) for e in stress.columns}
    # init stress = last day before event window
    pre = stress[stress.index < pd.Timestamp(config.EVENT_START)]
    init_stress = pre.iloc[-1].to_dict() if len(pre) else {e: 0.0 for e in stress.columns}

    # ---- 5. OC-CoVaR ranking (H3) + Delta-CoVaR benchmark --------------------
    print("[5/8] Computing OC-CoVaR systemic ranking + Delta-CoVaR benchmark ...")
    oc_rank = risk.systemic_ranking(scm, event_days, init_stress, stress_hi,
                                    q=0.95, n_sims=300, seed=7)
    out["oc_covar_ranking"] = oc_rank[["entity", "exported_risk"]].to_dict(orient="records")

    dcv = bm.delta_covar(returns[[c for c in returns.columns]], q=0.05)
    out["delta_covar_ranking"] = dcv[["asset", "delta_covar", "rank"]].to_dict(orient="records")

    # H3 divergence: Spearman between OC-CoVaR and Delta-CoVaR on the entities
    # we can map to a market asset.
    ent_to_asset = {"Binance": "BNB", "Aave": "AAVE", "Lido": "stETH",
                    "Ethena": "USDe", "retail": "ETH"}
    common = [(e, ent_to_asset[e]) for e in oc_rank.entity if e in ent_to_asset
              and ent_to_asset[e] in set(dcv.asset)]
    if len(common) >= 3:
        oc_scores = {e: oc_rank.set_index("entity").loc[e, "exported_risk"] for e, _ in common}
        dcv_scores = {e: -dcv.set_index("asset").loc[a, "delta_covar"] for e, a in common}  # flip sign: larger=riskier
        ents = [e for e, _ in common]
        rho, p = stats.spearmanr([oc_scores[e] for e in ents], [dcv_scores[e] for e in ents])
        out["H3_spearman_oc_vs_deltacovar"] = {"rho": float(rho), "p_value": float(p),
                                               "entities": ents}

    # ---- 6. counterfactual attribution for Oct-2025 USDe event (H4/H5) -------
    print("[6/8] Counterfactual attribution (Pearl L3) for the USDe event ...")
    precrisis = {e: float(est_stress[e].median()) for e in stress.columns}
    attributions = []
    for i in ["Ethena", "Binance"]:
        if i not in scm.stress_cols:
            continue
        for j in scm.stress_cols:
            if j == i:
                continue
            a = risk.counterfactual_attribution(
                scm, i, j, event_days, stress, init_stress, precrisis.get(i, 0.0))
            attributions.append(a)
    out["counterfactual_attribution"] = sorted(
        attributions, key=lambda r: -r["attribution"])

    # ---- 7. falsification test (H2) ------------------------------------------
    print("[7/8] Edge-reversal falsification test (A3) ...")
    fal = fz.run_falsification(graph, est_stress, est_flows, stress, flows,
                               event_days, alpha=1.0)
    out["falsification"] = fal.to_dict(orient="records")

    # ---- 8. VaR backtests (Section 4.2) --------------------------------------
    print("[8/8] VaR backtests (Kupiec / Christoffersen) ...")
    out["backtests"] = {}
    for asset in ["BTC", "ETH"]:
        if asset in returns.columns:
            out["backtests"][asset] = bt.backtest_var(returns[asset].dropna(), window=100, q=0.05)

    # ---- write outputs -------------------------------------------------------
    (RESULTS / "results.json").write_text(json.dumps(jsonable(out), indent=2))
    write_report(out)
    print("Done. Wrote results/results.json and results/EVALUATION.md")
    return out


def write_report(out: dict):
    from textwrap import dedent
    lines = []
    A = lines.append
    A("# VEIN — Empirical Evaluation on Real Data\n")
    A(f"_Generated {out['generated']}. On-chain flow window "
      f"{out['data_window'][0]} → {out['data_window'][1]} (Dune); "
      f"prices/TVL Jan 2024 → Jun 2026 (CoinGecko/DefiLlama)._\n")
    A("All numbers below come from real Ethereum mainnet data (decoded ERC-20 "
      "transfers via Dune), real market prices (CoinGecko), and real protocol "
      "TVL (DefiLlama). No synthetic data is used.\n")

    A("## 1. Observed on-chain graph G\n")
    A(f"- Nodes ({len(out['graph']['nodes'])}): {', '.join(out['graph']['nodes'])}")
    A(f"- Directed flow edges (≥ $1M cumulative): {len(out['graph']['edges'])}\n")
    A("| from | to | cum. USD volume | confidence |")
    A("|---|---|--:|--:|")
    for f_, t_, v, c in sorted(out["graph"]["edges"], key=lambda x: -x[2])[:15]:
        A(f"| {f_} | {t_} | {v:,.0f} | {c} |")
    A("")

    A("## 2. OC-CoVaR systemic ranking (H3)\n")
    A("Exported tail risk = Σ_j ΔOC-CoVaR(j | do(S_i = distress)). Higher = more "
      "systemically important as a *transmitter*.\n")
    A("| rank | entity | exported risk |")
    A("|--:|---|--:|")
    for k, r in enumerate(out["oc_covar_ranking"], 1):
        A(f"| {k} | {r['entity']} | {r['exported_risk']:.3f} |")
    A("")
    if "H3_spearman_oc_vs_deltacovar" in out:
        h3 = out["H3_spearman_oc_vs_deltacovar"]
        A(f"**H3 divergence vs Δ-CoVaR:** Spearman ρ = {h3['rho']:.3f} "
          f"(p = {h3['p_value']:.3f}) across {', '.join(h3['entities'])}. "
          "Low/negative ρ supports H3 (on-chain causal ranking diverges from "
          "price-correlation ranking).\n")

    A("## 3. Δ-CoVaR benchmark (Adrian & Brunnermeier)\n")
    A("| asset | Δ-CoVaR | rank |")
    A("|---|--:|--:|")
    for r in out["delta_covar_ranking"]:
        A(f"| {r['asset']} | {r['delta_covar']:.4f} | {r['rank']} |")
    A("")

    A("## 4. Counterfactual attribution — Oct 2025 USDe event (H4/H5)\n")
    A("Δᵢ^CF = L_j^observed − L_j^do(Sᵢ = pre-crisis): how much of entity j's "
      "realized distress is attributable to entity i becoming distressed.\n")
    A("| i (source) | j (affected) | L_obs | L_cf | attribution | share |")
    A("|---|---|--:|--:|--:|--:|")
    for r in out["counterfactual_attribution"][:12]:
        A(f"| {r['i']} | {r['j']} | {r['L_observed']:.2f} | {r['L_counterfactual']:.2f} "
          f"| {r['attribution']:.2f} | {r['attribution_share']*100:.1f}% |")
    A("")

    A("## 5. Edge-reversal falsification test (H2 / assumption A3)\n")
    A("One-step-ahead prediction of event-window stress. If flow direction is "
      "causally informative, **true_direction** should have the lowest RMSE / "
      "highest correlation.\n")
    A("| model | weighted RMSE | timing corr | n |")
    A("|---|--:|--:|--:|")
    for r in out["falsification"]:
        A(f"| {r['model']} | {r['rmse']:.4f} | {r['corr']:.4f} | {r['n']} |")
    A("")

    A("## 6. VaR backtests (Section 4.2)\n")
    A("| asset | obs | failures | rate | expected | Kupiec p | Christoffersen CC p |")
    A("|---|--:|--:|--:|--:|--:|--:|")
    for asset, b in out["backtests"].items():
        k = b["kupiec"]; c = b["christoffersen"]
        A(f"| {asset} | {k['n']} | {k['failures']} | {k['rate']:.3f} | {k['expected_rate']:.3f} "
          f"| {k['p_value']:.3f} | {c['p_value_cc']:.3f} |")
    A("")

    A("## 7. Honest limitations\n")
    A(dedent("""
    - **CEX opacity (algorithm.md §5.2.1).** Binance's internal pricing/liquidation
      engine is off-chain; we observe only its on-chain settlement flows. CEX-internal
      mechanics enter as exogenous shocks U, not structurally.
    - **Entity resolution = label-seeded backbone only.** This run uses the Tier-3
      known-label set (publicly attributed Binance/Ethena/Aave/Lido addresses).
      The Tier-1/2 ML/GNN resolution (algorithm.md §2.2) is not yet run, so the
      graph is high-precision but low-recall; edges to unlabeled counterparties
      collapse into 'retail'.
    - **Flow tokens.** The historical graph uses the Ethena/Binance systemic-core
      tokens (USDe, sUSDe, wBETH) to stay within Dune free-tier credits; USDC/USDT
      and native ETH flows would densify the graph.
    - **Short event window.** Daily resolution over Oct 8–14 2025; minute-level
      resolution (§3.4) needs a non-Binance intraday feed (Binance API is geo-blocked
      here).
    """).strip())
    A("")
    (RESULTS / "EVALUATION.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
