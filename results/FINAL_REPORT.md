# VEIN — Final Evaluation (Hourly Resolution)

_Real Ethereum data, hourly. 600 fit hours + 48 event hours (Oct 10–11 2025); 17 resolved entities; 39 edges. The cascade timescale is hours, where on-chain flows are observed but price feeds are coarse._

## H1 — observed on-chain graph vs price-estimated graph (decisive)

Nodes: Aave, Binance, Ethena, Lido, MakerSky, retail. Edges: {'observed': 8, 'granger': 14, 'partial_corr': 10}.

| graph source | RMSE | timing corr | n |
|---|--:|--:|--:|
| observed_onchain | 1.2529 | 0.2917 | 288 |
| estimated_granger | 1.2568 | 0.2546 | 288 |
| estimated_partial_corr | 1.2547 | 0.2846 | 288 |

**H1 SUPPORTED — observed on-chain graph wins** (RMSE gap vs best estimated: +0.0018).

## Hypotheses & checks

- **H3** (different ranking): OC-CoVaR top transmitters retail, Binance, Coinbase; Spearman vs Δ-CoVaR = 0.52 (lower = more divergent).
- **H4** (counterfactual): top channel Binance→Bybit = 98.1% of realized distress.
- **A3/H2** (direction causal): true 1.663 vs reversed 1.675 RMSE → near-tie / direction weak.
- **Placebo**: unconnected-pair attribution max 0.00e+00 → PASS.
- **Resolution robustness**: Spearman 0.81 (Tier-0 vs Tier-3, 6 entities).
- **External validity** (Oct-2025 narrative): transmitter–absorber separation 12.87, concordance 1.00.
- **VaR backtests**: BTC: Kupiec p=0.03; ETH: Kupiec p=0.11.

## Confounding robustness (top edges)

| edge | t | robustness value |
|---|--:|--:|
| retail->Coinbase | 7.94 | 0.226 |
| Coinbase->retail | 5.92 | 0.175 |
| retail->Bullish | 5.41 | 0.160 |
| Binance->Gate.io | 5.19 | 0.154 |
| retail->Bitfinex | 4.55 | 0.137 |
| Binance->Bybit | 4.54 | 0.136 |

## OC-CoVaR systemic ranking

| rank | entity | exported risk |
|--:|---|--:|
| 1 | retail | 57.360 |
| 2 | Binance | 24.516 |
| 3 | Coinbase | 17.347 |
| 4 | Bitfinex | 11.420 |
| 5 | Gate.io | 7.917 |
| 6 | Bybit | 4.884 |
| 7 | OKX | 4.817 |
| 8 | FalconX | 3.852 |
