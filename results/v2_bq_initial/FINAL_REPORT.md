# VEIN — Final Evaluation (Hourly Resolution)

_Real Ethereum data, hourly. 600 fit hours + 48 event hours (Oct 10–11 2025); 17 resolved entities; 100 edges. The cascade timescale is hours, where on-chain flows are observed but price feeds are coarse._

## H1 — observed on-chain graph vs price-estimated graph (decisive)

Nodes: Aave, Binance, Ethena, Lido, MakerSky, retail. Edges: {'observed': 8, 'granger': 14, 'partial_corr': 10}.

| graph source | RMSE | timing corr | n |
|---|--:|--:|--:|
| observed_onchain | 1.1647 | 0.2875 | 288 |
| estimated_granger | 1.1822 | 0.2167 | 288 |
| estimated_partial_corr | 1.1653 | 0.2821 | 288 |

**H1 SUPPORTED — observed on-chain graph wins** (RMSE gap vs best estimated: +0.0006).

## Hypotheses & checks

- **H3** (different ranking): OC-CoVaR top transmitters retail, Coinbase, Kraken; Spearman vs Δ-CoVaR = 0.52 (lower = more divergent).
- **H4** (counterfactual): top channel Binance→Bybit = 6.7% of realized distress.
- **A3/H2** (direction causal): true 1.725 vs reversed 1.704 RMSE → near-tie / direction weak.
- **Placebo**: unconnected-pair attribution max 0.00e+00 → PASS.
- **Resolution robustness**: Spearman 0.81 (Tier-0 vs Tier-3, 6 entities).
- **External validity** (Oct-2025 narrative): transmitter–absorber separation 19.68, concordance 1.00.
- **VaR backtests**: BTC: Kupiec p=0.03; ETH: Kupiec p=0.11.

## Confounding robustness (top edges)

| edge | t | robustness value |
|---|--:|--:|
| retail->Coinbase | 8.15 | 0.232 |
| Coinbase->retail | 6.20 | 0.182 |
| Kraken->retail | 5.66 | 0.168 |
| retail->Bullish | 4.98 | 0.149 |
| FalconX->Coinbase | 4.71 | 0.142 |
| Bitfinex->Coinbase | 4.51 | 0.136 |

## OC-CoVaR systemic ranking

| rank | entity | exported risk |
|--:|---|--:|
| 1 | retail | 101.119 |
| 2 | Coinbase | 43.996 |
| 3 | Kraken | 37.014 |
| 4 | Binance | 35.789 |
| 5 | Bitfinex | 34.143 |
| 6 | OKX | 24.273 |
| 7 | Crypto.com | 22.431 |
| 8 | HTX | 20.364 |
