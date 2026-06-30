"""Tier-1 supervised classifier + Tier-2 graph embedding (algorithm.md Section 2.2).

Tier 1 — a gradient-boosted classifier predicts whether an address belongs to a
         CEX (an economic-agent class) from transaction-level features (degree,
         value patterns, counterparty diversity, sweep ratio), in the spirit of
         the supervised same-entity classification of Tubino/Robardet/Cazabet
         (2022) and Moser/Narayanan (2022).

Tier 2 — node embeddings over the address transaction graph via the
         DeepWalk-as-matrix-factorization view (truncated SVD of the normalized
         co-occurrence/adjacency matrix), then clustering. This captures
         multi-hop structure simple heuristics miss.

Both are validated against held-out Dune `labels.cex_ethereum` ground truth,
which is exactly the Tier-3 reconciliation the algorithm requires (precision /
recall of the resolution layer reported as a robustness statistic, not assumed).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.metrics import average_precision_score, homogeneity_score
from sklearn.model_selection import train_test_split

from . import config
from .dune import run_sql


def fetch_labeled_edges(token: str, start, end) -> pd.DataFrame:
    """Aggregated address->address edges for one token over a window, each side
    tagged with its Dune CEX label (ground truth) if known."""
    addr = config.TOKENS[token]
    dec = {"USDe": 18, "sUSDe": 18, "USDC": 6, "USDT": 6}[token]
    sql = f"""
WITH cex AS (
    SELECT address, max(name) AS name FROM labels.cex_ethereum GROUP BY address
),
e AS (
    SELECT t."from" AS a, t.to AS b, t.value/power(10,{dec}) AS v
    FROM erc20_ethereum.evt_Transfer t
    WHERE t.contract_address = {addr}
      AND t.evt_block_time >= TIMESTAMP '{start}'
      AND t.evt_block_time <  TIMESTAMP '{end}'
)
SELECT e.a AS from_addr, e.b AS to_addr,
       sum(e.v) AS volume, count(*) AS n_tx,
       max(cf.name) AS from_cex, max(ct.name) AS to_cex
FROM e
LEFT JOIN cex cf ON e.a = cf.address
LEFT JOIN cex ct ON e.b = ct.address
GROUP BY 1, 2
"""
    rows = run_sql(sql, name="vein_resolver_edges")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def build_node_table(edges: pd.DataFrame) -> pd.DataFrame:
    """Per-address features + ground-truth CEX label from the edge list."""
    edges = edges.copy()
    edges["volume"] = pd.to_numeric(edges["volume"], errors="coerce").fillna(0.0)
    edges["n_tx"] = pd.to_numeric(edges["n_tx"], errors="coerce").fillna(0).astype(int)

    out = edges.groupby("from_addr").agg(
        out_vol=("volume", "sum"), out_tx=("n_tx", "sum"),
        out_deg=("to_addr", "nunique")).rename_axis("addr")
    inc = edges.groupby("to_addr").agg(
        in_vol=("volume", "sum"), in_tx=("n_tx", "sum"),
        in_deg=("from_addr", "nunique")).rename_axis("addr")
    nodes = out.join(inc, how="outer").fillna(0.0)

    # sweep ratio: share of an address's outflow going to its single top sink
    top_sink = (edges.groupby(["from_addr", "to_addr"]).volume.sum()
                .groupby(level=0).max())
    nodes["sweep_ratio"] = (top_sink / nodes["out_vol"].replace(0, np.nan)).reindex(nodes.index).fillna(0.0)
    nodes["tot_vol"] = nodes.out_vol + nodes.in_vol
    nodes["tot_tx"] = nodes.out_tx + nodes.in_tx
    nodes["deg"] = nodes.out_deg + nodes.in_deg
    nodes["in_out_ratio"] = nodes.in_vol / (nodes.out_vol + 1.0)

    # ground-truth label: CEX name if either side label seen for this address
    lab = {}
    for _, r in edges.iterrows():
        if r.get("from_cex"):
            lab[r["from_addr"]] = r["from_cex"]
        if r.get("to_cex"):
            lab[r["to_addr"]] = r["to_cex"]
    nodes["cex_name"] = pd.Series(lab).reindex(nodes.index)
    nodes["is_cex"] = nodes["cex_name"].notna().astype(int)
    return nodes


FEATURES = ["out_vol", "out_tx", "out_deg", "in_vol", "in_tx", "in_deg",
            "sweep_ratio", "tot_vol", "tot_tx", "deg", "in_out_ratio"]

NULL_ADDR = "0x0000000000000000000000000000000000000000"


def train_classifier(nodes: pd.DataFrame, seed: int = 0) -> dict:
    """Tier-1: GBM predicting is_cex; held-out precision/recall/AUC."""
    df = nodes.copy()
    X = np.log1p(df[FEATURES].clip(lower=0).values)
    y = df["is_cex"].values
    if y.sum() < 10 or (len(y) - y.sum()) < 10:
        return {"trained": False, "reason": "insufficient label balance",
                "n_pos": int(y.sum()), "n": int(len(y))}
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=seed,
                                          stratify=y)
    # balance the ~0.5% positive rate via sample weights
    w = np.where(ytr == 1, (len(ytr) - ytr.sum()) / max(ytr.sum(), 1), 1.0)
    clf = GradientBoostingClassifier(random_state=seed)
    clf.fit(Xtr, ytr, sample_weight=w)
    proba = clf.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, proba) if len(set(yte)) > 1 else float("nan")
    ap = average_precision_score(yte, proba) if yte.sum() else float("nan")
    # report at the F1-maximizing threshold (0.5 is meaningless at 0.5% base rate)
    _, Xte_idx = train_test_split(np.arange(len(y)), test_size=0.3, random_state=seed,
                                  stratify=y)
    vol_te = df["tot_vol"].values[Xte_idx]
    best = {"f1": -1, "precision": 0.0, "recall": 0.0, "threshold": 0.5,
            "vol_weighted_precision": 0.0, "vol_weighted_recall": 0.0}
    for thr in np.unique(proba):
        pred = (proba >= thr).astype(int)
        p, r, f, _ = precision_recall_fscore_support(yte, pred, average="binary",
                                                     zero_division=0)
        if f > best["f1"]:
            tp_vol = float(vol_te[(pred == 1) & (yte == 1)].sum())
            fp_vol = float(vol_te[(pred == 1) & (yte == 0)].sum())
            fn_vol = float(vol_te[(pred == 0) & (yte == 1)].sum())
            vwp = tp_vol / (tp_vol + fp_vol) if (tp_vol + fp_vol) > 0 else 0.0
            vwr = tp_vol / (tp_vol + fn_vol) if (tp_vol + fn_vol) > 0 else 0.0
            best = {"f1": float(f), "precision": float(p), "recall": float(r),
                    "threshold": float(thr),
                    "vol_weighted_precision": vwp, "vol_weighted_recall": vwr}
    imp = dict(sorted(zip(FEATURES, clf.feature_importances_), key=lambda kv: -kv[1]))
    return {"trained": True, "n": int(len(y)), "n_cex": int(y.sum()),
            "test_auc": float(auc), "test_avg_precision": float(ap),
            "base_rate": float(y.mean()),
            "best_f1": best["f1"], "precision_at_bestF1": best["precision"],
            "recall_at_bestF1": best["recall"],
            "vol_weighted_precision_at_bestF1": best["vol_weighted_precision"],
            "vol_weighted_recall_at_bestF1": best["vol_weighted_recall"],
            "top_features": {k: round(float(v), 3) for k, v in list(imp.items())[:5]}}


def embed_and_cluster(edges: pd.DataFrame, nodes: pd.DataFrame,
                      dim: int = 16, k_clusters: int = 20, seed: int = 0) -> dict:
    """Tier-2: SVD embedding of the symmetric normalized adjacency, KMeans
    clustering, cluster purity vs known CEX labels (homogeneity).

    Uses sklearn's randomized TruncatedSVD (robust on large sparse graphs;
    ARPACK svds can fail to converge here). Degrades gracefully on error."""
    from scipy.sparse import coo_matrix, diags
    from sklearn.decomposition import TruncatedSVD

    idx = {a: i for i, a in enumerate(nodes.index)}
    n = len(idx)
    if n < dim + 2:
        return {"embedded": False, "reason": "too few nodes", "n": n}
    try:
        a_idx = edges["from_addr"].map(idx).to_numpy()
        b_idx = edges["to_addr"].map(idx).to_numpy()
        w = np.log1p(pd.to_numeric(edges["volume"], errors="coerce").fillna(0.0).to_numpy())
        rows = np.concatenate([a_idx, b_idx])
        cols = np.concatenate([b_idx, a_idx])
        vals = np.concatenate([w, w])
        A = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
        deg = np.asarray(A.sum(axis=1)).ravel() + 1e-9
        Dinv = diags(1.0 / np.sqrt(deg))
        A = (Dinv @ A @ Dinv).tocsr()                       # symmetric-normalized
        kdim = min(dim, n - 1)
        svd = TruncatedSVD(n_components=kdim, random_state=seed, algorithm="randomized")
        emb = svd.fit_transform(A)
        km = KMeans(n_clusters=min(k_clusters, n), random_state=seed, n_init=10)
        labels = km.fit_predict(emb)
        mask = nodes["is_cex"].values.astype(bool)
        homo = (homogeneity_score(nodes["cex_name"].fillna("unknown").values[mask],
                                  labels[mask]) if mask.sum() > 2 else float("nan"))
        return {"embedded": True, "n": n, "dim": int(kdim),
                "k_clusters": int(km.n_clusters),
                "cex_cluster_homogeneity": float(homo)}
    except Exception as e:  # noqa: BLE001 - embedding is a robustness extra
        return {"embedded": False, "reason": f"{type(e).__name__}: {e}", "n": n}


def run_resolution_validation(token: str, start, end) -> dict:
    """Full Tier-1/2 demonstration + Tier-3 reconciliation on one token/window."""
    edges = fetch_labeled_edges(token, start, end)
    if edges.empty:
        return {"ok": False, "reason": "no edges"}
    n_addr_before = len(set(edges.from_addr) | set(edges.to_addr))
    edges = edges[(edges.from_addr != NULL_ADDR) & (edges.to_addr != NULL_ADDR)]
    nodes = build_node_table(edges)
    out = {"ok": True, "token": token, "window": [str(start), str(end)],
           "n_addresses_incl_sentinel": int(n_addr_before),
           "n_addresses": int(len(nodes)),
           "n_cex_labeled": int(nodes["is_cex"].sum()),
           "n_distinct_cex": int(nodes["cex_name"].nunique()),
           "tier1_classifier": train_classifier(nodes),
           "tier2_embedding": embed_and_cluster(edges, nodes)}
    return out
