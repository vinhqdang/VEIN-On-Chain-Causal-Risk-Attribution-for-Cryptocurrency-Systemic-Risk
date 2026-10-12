# VEIN — Final Evaluation (Hourly Resolution)

_Real Ethereum data, hourly. 600 fit hours + 48 event hours (Oct 10–11 2025); 15 resolved entities; 90 edges. The cascade timescale is hours, where on-chain flows are observed but price feeds are coarse._

## H1 — observed on-chain graph vs price-estimated graph (decisive)

Nodes: Aave, Binance, Ethena, Lido, MakerSky, retail. Edges: {'observed': 13, 'granger': 14, 'partial_corr': 10}.

| graph source | weighted RMSE | timing corr | n |
|---|--:|--:|--:|
| observed_onchain | 1.5545 | 0.1431 | 288 |
| estimated_granger | 1.5595 | 0.1737 | 288 |
| estimated_partial_corr | 1.5599 | 0.1573 | 288 |

Paired block bootstrap of the unweighted squared one-step error (estimated minus observed; positive = observed better). The RMSE above is weighted by |stress|+0.1, so the weighted CI column is the one on the scale of the table:

| estimated graph | mean diff | 95% CI | status | 95% CI (weighted) | 95% CI (8-h blocks) |
|---|--:|--:|---|--:|--:|
| granger | -0.0053 | [-0.0150, -0.0039] | estimated_better | [+0.0123, +0.0357] | [-0.0220, +0.0089] |
| partial_corr | -0.0031 | [-0.0177, -0.0054] | estimated_better | [-0.0030, +0.0159] | [-0.0233, +0.0076] |

**H1 contradicted vs granger** [-0.0150, -0.0039]
**H1 contradicted vs partial_corr** [-0.0177, -0.0054]

## Hypotheses & checks

- **H3** (different ranking): OC-CoVaR top transmitters retail, MakerSky, Coinbase; Spearman vs Δ-CoVaR = 0.26 (lower = more divergent).
- **H4** (counterfactual): top channel Binance→Bybit = 6.3% of realized distress.
- **A3/H2** (direction causal): true 1.784 vs reversed 1.787 RMSE → near-tie / direction weak; reversed minus true squared error +0.0042, 95% CI [+0.0016, +0.0104].
- **Structural zero** (holds by construction, not evidence): unconnected-pair attribution max 0.00e+00 → PASS.
- **Rolling calm-window placebo**: event 0.2146 vs 20 calm windows, p = 0.286 → FAIL.
- **Time-shift placebo**: real 0.2146 vs 100 shifted refits, p = 0.010 → PASS.
- **Resolution robustness**: Spearman 0.60 (Tier-0 vs Tier-3, 6 entities).
- **External validity** (Oct-2025 narrative): transmitter–absorber separation 8.46, concordance 0.50; non-degenerate stress: True.
- **VaR backtests**: BTC: Kupiec p=0.03; ETH: Kupiec p=0.11.

## Confounding robustness (top edges)

| edge | t | robustness value |
|---|--:|--:|
| MakerSky->retail | 8.11 | 0.231 |
| retail->Coinbase | 6.80 | 0.198 |
| Bitfinex->retail | 5.83 | 0.173 |
| Bitfinex->Coinbase | 4.87 | 0.146 |
| Kraken->retail | 4.19 | 0.127 |
| Binance->Bybit | 4.16 | 0.126 |

## OC-CoVaR systemic ranking

| rank | entity | exported risk | MC s.e. |
|--:|---|--:|--:|
| 1 | retail | 44.966 | 0.436 |
| 2 | MakerSky | 37.864 | 0.337 |
| 3 | Coinbase | 26.374 | 0.300 |
| 4 | Bitfinex | 25.726 | 0.221 |
| 5 | Kraken | 23.973 | 0.278 |
| 6 | Crypto.com | 23.796 | 0.360 |
| 7 | Binance | 22.540 | 0.286 |
| 8 | OKX | 19.053 | 0.282 |
