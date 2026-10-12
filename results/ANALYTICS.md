# VEIN analytic checks (daily specification)

_Source: results/results.json (daily SCM, T = 7 event days, 17 entities). Hourly coefficients are not archived, so every number here refers to the daily specification. The Shapley checks use a synthetic deviation path (seed 7)._

- Spectral radius of the daily coefficient matrix: 0.276
- Entities with zero flow-free bound: 9
- Violations of the bound (stored exported risk > 0 with zero bound): 0

## Flow-free bounds (Prop A) and stored exported risk

B+ is the exported bound per unit of s*. The implied minimum s* is the scale at which the bound would just reproduce the stored exported risk.

| entity | stored E (MC) | B+ per unit s* | implied min s* | infinite-horizon multiplier | status |
|---|--:|--:|--:|--:|---|
| Lido | 4.06 | 1.37 | 2.97 | 0.228 | bounded |
| Bitget | 0.181 | 2.34 | 0.077 | 0.404 | bounded |
| retail | 0.111 | 0.428 | 0.259 | 0.0718 | bounded |
| Ethena | 0.0863 | 0.442 | 0.195 | 0.0733 | bounded |
| Bybit | 0.0696 | 0.705 | 0.0986 | 0.122 | bounded |
| Copper | 0.043 | 1.46 | 0.0295 | 0.25 | bounded |
| Binance | 0.0325 | 0.0397 | 0.819 | 0.00754 | bounded |
| FalconX | 0.00767 | 0.0944 | 0.0813 | 0.0195 | bounded |
| Aave | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| OKX | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| MakerSky | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| HTX | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Bitfinex | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Ceffu | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Crypto.com | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Coinbase | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Bullish | 0 | 0 | - | 0 | zero_predicted_zero_observed |

## Shapley verification (synthetic deviation path)

- Closed-form walks vs exact subset enumeration, max absolute difference: 5.55e-17
- Subset enumeration vs permutation enumeration (p <= 7), max absolute difference: 0.00e+00
- Efficiency residual (sum of values minus grand-coalition value), max: 0.00e+00

| target | players | p | closed vs subsets | efficiency | subsets vs permutations | hinge vs linear (synthetic S_fact) |
|---|---|--:|--:|--:|--:|--:|
| Bitfinex | Binance, HTX, retail | 3 | 0.00e+00 | 0.00e+00 | 0 | 0 |
| Aave | Ethena, Lido | 2 | 5.55e-17 | 0.00e+00 | 0 | 0.205 |
| Bybit | Binance, retail | 2 | 2.78e-17 | 0.00e+00 | 0 | 0.00583 |
| Crypto.com | Binance, retail | 2 | 0.00e+00 | 0.00e+00 | 0 | 0 |
| OKX | Copper, retail | 2 | 0.00e+00 | 0.00e+00 | 0 | 0 |

## Evaluation counts

| players p | subset enumeration 2^p | permutation enumeration p! x p |
|--:|--:|--:|
| 3 | 8 | 18 |
| 4 | 16 | 96 |
| 5 | 32 | 600 |
| 6 | 64 | 4,320 |
| 7 | 128 | 35,280 |
| 8 | 256 | 322,560 |
| 9 | 512 | 3,265,920 |
| 10 | 1,024 | 36,288,000 |
| 11 | 2,048 | 439,084,800 |
| 12 | 4,096 | 5,748,019,200 |
| 13 | 8,192 | 80,951,270,400 |

Exact subset Shapley for retail (p = 13, 8,192 evaluations): 0.189 s on this machine (machine-dependent). Closed-form vs subsets max difference: 1.04e-14.

## Certified ranking radius

Top of the ranking by Lambda_i (daily exported mass): Bitget, Copper, Lido, Bybit, Ethena.

| pair | gap in Lambda | certified eps* | certified at eps = 1 |
|---|--:|--:|---|
| Bitget > Copper | 0.889 | 0.161 | no |
| Copper > Lido | 0.0898 | 0.0265 | no |
| Lido > Bybit | 0.66 | 0.271 | no |
| Bybit > Ethena | 0.264 | 0.0468 | no |
