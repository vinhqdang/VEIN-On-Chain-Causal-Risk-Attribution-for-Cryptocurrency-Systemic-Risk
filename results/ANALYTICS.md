# VEIN analytic checks (daily specification)

_Source: results/results.json (daily SCM, T = 7 event days, 17 entities). Hourly coefficients are not archived, so every number here refers to the daily specification. The Shapley checks use a synthetic deviation path (seed 7)._

- Spectral radius of the daily coefficient matrix: 0.244
- Entities with zero flow-free bound: 9
- Violations of the bound (stored exported risk > 0 with zero bound): 0

## Flow-free bounds (Prop A) and stored exported risk

B+ is the exported bound per unit of s*. The implied minimum s* is the scale at which the bound would just reproduce the stored exported risk.

| entity | stored E (MC) | B+ per unit s* | implied min s* | infinite-horizon multiplier | status |
|---|--:|--:|--:|--:|---|
| Lido | 11.5 | 3.78 | 3.03 | 0.631 | bounded |
| Bybit | 0.682 | 0.71 | 0.96 | 0.121 | bounded |
| retail | 0.366 | 0.52 | 0.705 | 0.0882 | bounded |
| Copper | 0.0982 | 2.07 | 0.0475 | 0.351 | bounded |
| Ceffu | 0.0548 | 0.0989 | 0.554 | 0.0204 | bounded |
| Ethena | 0.0352 | 0.213 | 0.166 | 0.0378 | bounded |
| Binance | 0.00544 | 0.0148 | 0.367 | 0.00229 | bounded |
| FalconX | 0 | 0.112 | 0 | 0.023 | bounded |
| Aave | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| MakerSky | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Coinbase | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Kraken | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| HTX | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| OKX | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Bullish | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Bitfinex | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Crypto.com | 0 | 0 | - | 0 | zero_predicted_zero_observed |

## Shapley verification (synthetic deviation path)

- Closed-form walks vs exact subset enumeration, max absolute difference: 8.33e-17
- Subset enumeration vs permutation enumeration (p <= 7), max absolute difference: 3.05e-16
- Efficiency residual (sum of values minus grand-coalition value), max: 5.55e-17

| target | players | p | closed vs subsets | efficiency | subsets vs permutations | hinge vs linear (synthetic S_fact) |
|---|---|--:|--:|--:|--:|--:|
| Bitfinex | Binance, HTX, retail | 3 | 0.00e+00 | 0.00e+00 | 0 | 0 |
| Aave | Ethena, Lido | 2 | 5.55e-17 | 0.00e+00 | 0 | 0.0265 |
| Bybit | Binance, Coinbase, Copper, HTX, OKX, retail | 6 | 8.33e-17 | 5.55e-17 | 3.1e-16 | 0.0611 |
| Crypto.com | Binance, retail | 2 | 0.00e+00 | 0.00e+00 | 0 | 0 |
| OKX | Binance, Bybit, Coinbase, Copper, Kraken, retail | 6 | 0.00e+00 | 0.00e+00 | 0 | 0 |

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

Exact subset Shapley for retail (p = 13, 8,192 evaluations): 0.202 s on this machine (machine-dependent). Closed-form vs subsets max difference: 4.22e-15.

## Certified ranking radius

Top of the ranking by Lambda_i (daily exported mass): Lido, Copper, Bybit, retail, Ethena.

| pair | gap in Lambda | certified eps* | certified at eps = 1 |
|---|--:|--:|---|
| Lido > Copper | 1.72 | 0.256 | no |
| Copper > Bybit | 1.36 | 0.333 | no |
| Bybit > retail | 0.191 | 0.0756 | no |
| retail > Ethena | 0.307 | 0.0584 | no |
