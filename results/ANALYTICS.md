# VEIN analytic checks (daily specification)

_Source: results/results.json (daily SCM, T = 7 event days, 15 entities). Hourly coefficients are not archived, so every number here refers to the daily specification. The Shapley checks use a synthetic deviation path (seed 7)._

- Spectral radius of the daily coefficient matrix: 0.569
- Entities with zero flow-free bound: 5
- Violations of the bound (stored exported risk > 0 with zero bound): 0

## Flow-free bounds (Prop A) and stored exported risk

B+ is the exported bound per unit of s*. The implied minimum s* is the scale at which the bound would just reproduce the stored exported risk.

| entity | stored E (MC) | B+ per unit s* | implied min s* | infinite-horizon multiplier | status |
|---|--:|--:|--:|--:|---|
| retail | 8.28 | 4.41 | 1.88 | 0.737 | bounded |
| Lido | 6.68 | 3.15 | 2.12 | 0.675 | bounded |
| Aave | 6.46 | 3.91 | 1.65 | 0.682 | bounded |
| MakerSky | 1.16 | 1.78 | 0.652 | 0.373 | bounded |
| Ethena | 0.0407 | 0.243 | 0.168 | 0.0413 | bounded |
| Bybit | 0.024 | 0.0343 | 0.701 | 0.00681 | bounded |
| Ceffu | 0.0192 | 0.0369 | 0.521 | 0.00905 | bounded |
| Copper | 0.00155 | 0.365 | 0.00425 | 0.0609 | bounded |
| Binance | 0.00127 | 0.00461 | 0.276 | 0.000932 | bounded |
| FalconX | 0 | 0.0576 | 0 | 0.0141 | bounded |
| HTX | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Bitfinex | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Coinbase | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| Kraken | 0 | 0 | - | 0 | zero_predicted_zero_observed |
| OKX | 0 | 0 | - | 0 | zero_predicted_zero_observed |

## Shapley verification (synthetic deviation path)

- Closed-form walks vs exact subset enumeration, max absolute difference: 4.44e-16
- Subset enumeration vs permutation enumeration (p <= 7), max absolute difference: 9.71e-16
- Efficiency residual (sum of values minus grand-coalition value), max: 0.00e+00

| target | players | p | closed vs subsets | efficiency | subsets vs permutations | hinge vs linear (synthetic S_fact) |
|---|---|--:|--:|--:|--:|--:|
| Bitfinex | Binance, HTX, retail | 3 | 0.00e+00 | 0.00e+00 | 0 | 0 |
| Aave | HTX, retail, Ethena, Lido | 4 | 4.44e-16 | 0.00e+00 | 2.2e-16 | 0.0098 |
| Bybit | Binance, Coinbase, Copper, HTX, OKX, retail | 6 | 5.55e-17 | 0.00e+00 | 9.7e-16 | 0.0286 |
| OKX | Binance, Bybit, Coinbase, Copper, Kraken, retail | 6 | 0.00e+00 | 0.00e+00 | 0 | 0 |

Skipped Crypto.com: not an entity.

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

Exact subset Shapley for retail (p = 13, 8,192 evaluations): 0.223 s on this machine (machine-dependent). Closed-form vs subsets max difference: 3.39e-15.

## Certified ranking radius

Top of the ranking by Lambda_i (daily exported mass): retail, Aave, Lido, MakerSky, Copper.

| pair | gap in Lambda | certified eps* | certified at eps = 1 |
|---|--:|--:|---|
| retail > Aave | 0.508 | 0.0475 | no |
| Aave > Lido | 0.755 | 0.0643 | no |
| Lido > MakerSky | 1.37 | 0.134 | no |
| MakerSky > Copper | 1.42 | 0.305 | no |
