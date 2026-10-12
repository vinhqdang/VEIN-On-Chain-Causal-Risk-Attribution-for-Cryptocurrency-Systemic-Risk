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


def load_optional(name):
    """Parsed results file, or None if it has not been produced yet."""
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


# --- Fig 1: USDe on-chain transfer volume around the cascade (real on-chain data) --
def fig_usde():
    # Prefer the BigQuery rebuild (results/data_build.json, written by run_build_data.py).
    # Without it, fall back to the Dune daily volumes the paper was first built from.
    build = RES / "data_build.json"
    if build.exists() and "usde_daily" in json.loads(build.read_text()):
        rows = json.loads(build.read_text())["usde_daily"]
        days = [f"Oct {int(r['day'][-2:])}" for r in rows]
        vol = [r["usde_bn"] for r in rows]
        source = "BigQuery crypto_ethereum"
    else:
        days = ["Oct 8", "Oct 9", "Oct 10", "Oct 11", "Oct 12", "Oct 13"]
        vol = [1.405, 0.745, 3.090, 8.828, 1.328, 0.688]   # $B, erc20 USDe transfers (Dune, v1)
        source = "Dune, decoded ERC-20"
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    bars = ax.bar(days, vol, color=[GREY, GREY, RED, RED, GREY, GREY][:len(vol)])
    ax.set_ylabel("USDe on-chain transfer volume (USD bn)")
    ax.set_title(f"Ethena USDe transfer volume, Oct 2025 ({source})")
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
    """Top 10 entities; 95% coefficient-bootstrap intervals when uncertainty.json exists."""
    d = load("final_results.json")
    r = d["oc_covar_ranking"][:10][::-1]
    names = [x["entity"] for x in r]
    vals = [x["exported_risk"] for x in r]
    unc = load_optional("uncertainty.json")
    fig, ax = plt.subplots(figsize=(5.4, 3.4))
    ax.barh(names, vals, color=BLUE)
    if unc:
        by = unc["ranking"]["by_entity"]
        pos = [i for i, n in enumerate(names) if n in by]
        if pos:
            lo = np.array([vals[i] - by[names[i]]["exported_risk_ci95"][0] for i in pos])
            hi = np.array([by[names[i]]["exported_risk_ci95"][1] - vals[i] for i in pos])
            ax.errorbar(np.array(vals)[pos], pos, xerr=[np.clip(lo, 0, None), np.clip(hi, 0, None)],
                        fmt="none", ecolor="black", capsize=2, lw=0.8)
    ax.set_xlabel("Exported tail risk  $\\sum_j \\Delta$OC-CoVaR$(j\\,|\\,\\mathrm{do}(S_i))$")
    ax.set_title("OC-CoVaR systemic-importance ranking (hourly"
                 + (", 95% CI)" if unc else ")"))
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
    """Top 8 channels by share, with 95% intervals when uncertainty.json exists. Without it the
    point estimates from final_results.json are drawn without intervals."""
    unc = load_optional("uncertainty.json")
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    if unc and unc["attribution"].get("channels"):
        ch = sorted(unc["attribution"]["channels"], key=lambda c: -c["share"])[:8][::-1]
        names = [f"{c['i']}→{c['j']}" for c in ch]
        vals = [c["share"] * 100 for c in ch]
        lo = np.array([c["share"] * 100 - c["share_ci95"][0] * 100 for c in ch])
        hi = np.array([c["share_ci95"][1] * 100 - c["share"] * 100 for c in ch])
        ax.barh(names, vals, color=RED)
        ax.errorbar(vals, range(len(names)), xerr=[np.clip(lo, 0, None), np.clip(hi, 0, None)],
                    fmt="none", ecolor="black", capsize=2, lw=0.8)
        title = "Counterfactual loss attribution (Pearl Level-3), hourly, 95% CI"
    else:
        d = load("final_results.json").get("counterfactual_attribution", [])[:8][::-1]
        if not d:
            plt.close(fig)
            return
        names = [f"{x['i']}→{x['j']}" for x in d]
        vals = [x["attribution_share"] * 100 for x in d]
        ax.barh(names, vals, color=RED)
        title = "Counterfactual loss attribution (Pearl Level-3), hourly"
    ax.set_xlabel("counterfactual attribution share (\\% of $j$'s realised distress)")
    ax.set_title(title)
    fig.tight_layout(); fig.savefig(FIG / "fig_attribution.pdf"); plt.close(fig)


# --- Fig 10: ranking uncertainty, point rank and 95% bootstrap rank interval ---
def fig_rank_ci():
    unc = load_optional("uncertainty.json")
    if not unc:
        print("fig_rank_ci skipped: uncertainty.json not produced yet")
        return
    by = unc["ranking"]["by_entity"]
    ents = sorted(by, key=lambda e: by[e]["rank_point"])
    y = np.arange(len(ents))[::-1]
    fig, ax = plt.subplots(figsize=(5.4, 0.28 * len(ents) + 1.4))
    for yi, e in zip(y, ents):
        lo, hi = by[e]["rank_ci95"]
        ax.plot([lo, hi], [yi, yi], color=GREY, lw=2.5, solid_capstyle="butt", zorder=2)
    ax.scatter([by[e]["rank_point"] for e in ents], y, marker="D", color=BLUE, zorder=3,
               label="point rank")
    ax.scatter([by[e]["rank_median"] for e in ents], y, marker="o", s=14, color=RED, zorder=4,
               label="bootstrap median")
    ax.set_yticks(y); ax.set_yticklabels(ents, fontsize=8)
    ax.set_xlim(0.5, len(ents) + 0.5)
    ax.set_xlabel("rank of exported risk (1 = largest)")
    ax.set_title("Ranking uncertainty: 95% bootstrap rank intervals")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(FIG / "fig_rank_ci.pdf"); plt.close(fig)


# --- Fig 11: pairwise order probabilities among the top-6 point-ranked entities ---
def fig_pairwise_top6():
    unc = load_optional("uncertainty.json")
    if not unc:
        print("fig_pairwise_top6 skipped: uncertainty.json not produced yet")
        return
    pw = unc["ranking"]["pairwise_top6"]
    ents = pw["entities"]
    M = np.ma.masked_invalid(np.array([[np.nan if v is None else v for v in row]
                                       for row in pw["p_row_above_col"]], dtype=float))
    fig, ax = plt.subplots(figsize=(4.8, 4.1))
    im = ax.imshow(M, vmin=0, vmax=1, cmap="Blues")
    for i in range(len(ents)):
        for j in range(len(ents)):
            if i != j:
                ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if M[i, j] > 0.6 else "black")
    ax.set_xticks(range(len(ents))); ax.set_xticklabels(ents, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(ents))); ax.set_yticklabels(ents, fontsize=8)
    ax.set_xlabel("entity j"); ax.set_ylabel("entity i")
    ax.set_title("P(exported risk of row $i$ > column $j$)")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(FIG / "fig_pairwise_top6.pdf"); plt.close(fig)


# --- Fig 12: time-shift placebo distribution against the observed statistic ---
def fig_placebo():
    fr = load_optional("final_results.json") or {}
    ts = (fr.get("placebo") or {}).get("time_shift") or {}
    if "placebo_stats" not in ts:
        print("fig_placebo skipped: no time-shift placebo in final_results.json")
        return
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ax.hist(ts["placebo_stats"], bins=20, color=GREY, edgecolor="white")
    ax.axvline(ts["real_stat"], color=RED, lw=1.5,
               label=f"observed (p = {ts['p_value']:.3f})")
    ax.set_xlabel("mean |counterfactual attribution| over connected pairs")
    ax.set_ylabel("placebo draws")
    ax.set_title("Time-shift placebo: coefficients re-estimated on shifted stress")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "fig_placebo.pdf"); plt.close(fig)


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
    fig_attribution(); fig_h3(); fig_stress(); fig_rank_ci(); fig_pairwise_top6(); fig_placebo()
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
