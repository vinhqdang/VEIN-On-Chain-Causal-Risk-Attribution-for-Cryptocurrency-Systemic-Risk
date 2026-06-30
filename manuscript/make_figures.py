#!/usr/bin/env python3
"""Generate publication figures for the VEIN manuscript from the real results."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
FIG = Path(__file__).resolve().parent / "figures"
FIG.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "serif", "font.size": 10, "axes.titlesize": 11,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 200,
})
BLUE, RED, GREY, GREEN = "#2b5d8a", "#b3402f", "#888888", "#3a7d44"


def load(name):
    return json.loads((RES / name).read_text())


# --- Fig 1: USDe on-chain transfer volume around the cascade (real Dune data) --
def fig_usde():
    days = ["Oct 8", "Oct 9", "Oct 10", "Oct 11", "Oct 12", "Oct 13"]
    vol = [1.405, 0.745, 3.090, 8.828, 1.328, 0.688]   # $B, erc20 USDe transfers
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    bars = ax.bar(days, vol, color=[GREY, GREY, RED, RED, GREY, GREY])
    ax.set_ylabel("USDe on-chain transfer volume (USD bn)")
    ax.set_title("Ethena USDe transfer volume, Oct 2025 (Dune, decoded ERC-20)")
    for b, v in zip(bars, vol):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_ylim(0, 9.8)
    fig.tight_layout(); fig.savefig(FIG / "fig_usde_spike.pdf"); plt.close(fig)


# --- Fig 2: entity-resolved flow graph -----------------------------------------
def fig_graph():
    d = load("results.json")
    edges = d["graph"]["edges"]   # [from,to,vol,conf,source]
    G = nx.DiGraph()
    for f, t, v, c, src in edges:
        if v and v > 0:
            G.add_edge(f, t, w=v)
    if G.number_of_nodes() == 0:
        return
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    pos = nx.spring_layout(G, seed=3, k=1.1)
    sizes = [600 if n != "retail" else 1100 for n in G.nodes()]
    colors = [RED if n == "retail" else BLUE for n in G.nodes()]
    ws = np.array([G[u][v]["w"] for u, v in G.edges()])
    widths = 0.4 + 3.0 * (ws / ws.max())
    nx.draw_networkx_nodes(G, pos, node_size=sizes, node_color=colors, alpha=0.85, ax=ax)
    nx.draw_networkx_edges(G, pos, width=widths, edge_color=GREY, alpha=0.6,
                           arrowsize=8, connectionstyle="arc3,rad=0.08", ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=7.5, font_color="white", ax=ax)
    ax.set_title("Entity-resolved on-chain flow graph $G$ (edge width $\\propto$ USD volume)")
    ax.axis("off")
    fig.tight_layout(); fig.savefig(FIG / "fig_graph.pdf"); plt.close(fig)


# --- Fig 3: OC-CoVaR systemic ranking (hourly) ---------------------------------
def fig_ocranking():
    d = load("final_results.json")
    r = d["oc_covar_ranking"][:8]
    names = [x["entity"] for x in r][::-1]
    vals = [x["exported_risk"] for x in r][::-1]
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.barh(names, vals, color=BLUE)
    ax.set_xlabel("Exported tail risk  $\\sum_j \\Delta$OC-CoVaR$(j\\,|\\,\\mathrm{do}(S_i))$")
    ax.set_title("OC-CoVaR systemic-importance ranking (hourly)")
    fig.tight_layout(); fig.savefig(FIG / "fig_oc_ranking.pdf"); plt.close(fig)


# --- Fig 4: H1 head-to-head, daily vs hourly -----------------------------------
def fig_h1():
    daily = {s["model"]: s["rmse"] for s in load("validation.json")["H1_observed_vs_estimated"]["scores"]}
    hourly = {s["model"]: s["rmse"] for s in load("final_results.json")["H1"]["scores"]}
    labels = ["observed\non-chain", "estimated\nGranger", "estimated\npartial-corr"]
    keys = ["observed_onchain", "estimated_granger", "estimated_partial_corr"]
    dv = [daily.get(k, np.nan) for k in keys]
    hv = [hourly.get(k, np.nan) for k in keys]
    x = np.arange(len(labels)); w = 0.38
    fig, ax = plt.subplots(figsize=(5.6, 3.2))
    ax.bar(x - w/2, dv, w, label="daily", color=GREY)
    ax.bar(x + w/2, hv, w, label="hourly", color=BLUE)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("event-window prediction RMSE (lower better)")
    ax.set_title("H1: observed on-chain vs price-estimated graph")
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(FIG / "fig_h1.pdf"); plt.close(fig)


# --- Fig 5: falsification (A3) daily vs hourly ---------------------------------
def fig_falsification():
    daily = {r["model"]: r["rmse"] for r in load("results.json")["falsification"]}
    hourly = {r["model"]: r["rmse"] for r in load("intraday_a3.json")["falsification"]}
    keys = ["true_direction", "reversed_edges", "symmetric"]
    labels = ["true", "reversed", "symmetric"]
    x = np.arange(len(keys)); w = 0.38
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.bar(x - w/2, [daily.get(k, np.nan) for k in keys], w, label="daily (6 pts)", color=GREY)
    ax.bar(x + w/2, [hourly.get(k, np.nan) for k in keys], w, label="hourly (816 pts)", color=BLUE)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("one-step prediction RMSE")
    ax.set_title("A3 edge-reversal falsification test")
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(FIG / "fig_falsification.pdf"); plt.close(fig)


# --- Fig 6: robustness values (confounding sensitivity) ------------------------
def fig_robustness():
    d = load("final_results.json")["confounding_sensitivity"]["edges"][:7]
    names = [e["edge"] for e in d][::-1]
    rv = [e["robustness_value"] for e in d][::-1]
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.barh(names, rv, color=GREEN)
    ax.set_xlabel("robustness value  $RV_{q=1}$")
    ax.set_title("Sensitivity to unobserved confounding (higher = more robust)")
    fig.tight_layout(); fig.savefig(FIG / "fig_robustness.pdf"); plt.close(fig)


# --- Fig 7: counterfactual attribution shares (hourly) -------------------------
def fig_attribution():
    d = load("final_results.json")["counterfactual_attribution"]
    pairs = [(f"{x['i']}→{x['j']}", x["attribution_share"] * 100) for x in d
             if x["attribution_share"] > 0.5][:7][::-1]
    if not pairs:
        return
    names = [p[0] for p in pairs]; vals = [p[1] for p in pairs]
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ax.barh(names, vals, color=RED)
    ax.set_xlabel("counterfactual attribution share (\\% of $j$'s realised distress)")
    ax.set_title("Counterfactual loss attribution (Pearl Level-3), hourly")
    fig.tight_layout(); fig.savefig(FIG / "fig_attribution.pdf"); plt.close(fig)


# --- Fig 8: H3 rank divergence scatter -----------------------------------------
def fig_h3():
    fr = load("final_results.json")
    e2a = {"Binance": "BNB", "Ethena": "ENA", "Aave": "AAVE", "Lido": "stETH",
           "retail": "ETH", "MakerSky": "DAI"}
    oc = {x["entity"]: x["exported_risk"] for x in fr["oc_covar_ranking"]}
    dcv = {x["asset"]: x["delta_covar"] for x in fr["baselines"]["delta_covar"]}
    ents = [e for e in e2a if e in oc and e2a[e] in dcv]
    if len(ents) < 3:
        return
    import scipy.stats as ss
    ocr = ss.rankdata([oc[e] for e in ents])
    dvr = ss.rankdata([-dcv[e2a[e]] for e in ents])   # larger risk = higher rank
    fig, ax = plt.subplots(figsize=(4.8, 4.0))
    ax.scatter(dvr, ocr, color=BLUE, s=60, zorder=3)
    for e, x, y in zip(ents, dvr, ocr):
        ax.annotate(e, (x, y), fontsize=8, xytext=(4, 3), textcoords="offset points")
    lim = [0.5, len(ents) + 0.5]
    ax.plot(lim, lim, "--", color=GREY, lw=1)
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("$\\Delta$CoVaR systemic rank")
    ax.set_ylabel("OC-CoVaR systemic rank")
    ax.set_title("H3: rank divergence ($\\rho=0.52$)")
    fig.tight_layout(); fig.savefig(FIG / "fig_h3_scatter.pdf"); plt.close(fig)


# --- Fig 9: event stress trajectories (recomputed from cached hourly flows) ----
def fig_stress():
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        import datetime as dt
        from vein import entity_resolution as er
        import run_best as rb
        flows = er.load_resolved_flows(rb.WIN_START, rb.WIN_END, rb.TOKENS,
                                       bucket="hour", min_addr_volume=1e3)
        flows = er.top_k_entities(flows, k=12)
        import pandas as pd
        flows["day"] = pd.to_datetime(flows["day"])
        ents = sorted(set(flows.from_entity) | set(flows.to_entity))
        S = rb.build_hourly_stress(flows, ents).sort_index()
        win = S[(S.index >= pd.Timestamp("2025-10-08")) & (S.index <= pd.Timestamp("2025-10-13"))]
        show = [e for e in ["Binance", "Bybit", "Ethena", "retail"] if e in win.columns]
        fig, ax = plt.subplots(figsize=(6.0, 3.2))
        for e, c in zip(show, [BLUE, RED, GREEN, GREY]):
            ax.plot(win.index, win[e], label=e, color=c, lw=1.3)
        ax.axvspan(pd.Timestamp("2025-10-10"), pd.Timestamp("2025-10-11 23:00"),
                   color="orange", alpha=0.12, label="event window")
        ax.set_ylabel("stress $S_{i,t}$ (z-score)")
        ax.set_title("Hourly entity stress around the October 2025 cascade")
        ax.legend(frameon=False, ncol=3, fontsize=8)
        fig.autofmt_xdate()
        fig.tight_layout(); fig.savefig(FIG / "fig_stress.pdf"); plt.close(fig)
    except Exception as e:  # pragma: no cover
        print("fig_stress skipped:", e)


if __name__ == "__main__":
    fig_usde(); fig_graph(); fig_ocranking(); fig_h1(); fig_falsification(); fig_robustness()
    fig_attribution(); fig_h3(); fig_stress()
    print("figures written to", FIG)
    for p in sorted(FIG.glob("*.pdf")):
        print(" ", p.name)


# --- Revision figures -----------------------------------------------------------
def fig_h1_ci():
    import json
    d = json.loads((RES / "revision.json").read_text())["H1"]
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    diff = d["mean_werr_diff_granger_minus_observed"]; ci = d["boot_ci95_diff"]
    ax.errorbar([diff], [0], xerr=[[diff - ci[0]], [ci[1] - diff]], fmt="o",
                color=BLUE, capsize=4, lw=1.5)
    ax.axvline(0, color=GREY, ls="--", lw=1)
    ax.set_yticks([]); ax.set_xlabel("weighted-error advantage of observed over Granger graph")
    ax.set_title(f"H1 paired block-bootstrap ($P=${d['prob_observed_better']:.2f} observed better)")
    fig.tight_layout(); fig.savefig(FIG / "fig_h1_ci.pdf"); plt.close(fig)


def fig_shapley():
    import json
    d = json.loads((RES / "revision.json").read_text())["shapley"]
    sv = d["shapley_values"]; names = list(sv)[::-1]; vals = [sv[n] for n in names]
    fig, ax = plt.subplots(figsize=(5.0, 2.6))
    ax.barh(names, vals, color=[GREEN if v >= 0 else RED for v in vals])
    ax.axvline(0, color=GREY, lw=0.8)
    ax.set_xlabel("Shapley contribution to " + d["target"] + " distress")
    ax.set_title("Order-robust attribution (additive: residual $\\approx 0$)")
    fig.tight_layout(); fig.savefig(FIG / "fig_shapley.pdf"); plt.close(fig)


if __name__ == "__main__" and "--revision" in __import__("sys").argv:
    fig_h1_ci(); fig_shapley(); print("revision figures done")
