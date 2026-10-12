# Label coverage of on-chain token flows

Shares are of total USD flow in each extract window. 'Both labelled, distinct entities' means both endpoints carry a label and the labels name different entities (named-to-named flow). 'Both labelled, same entity' is flow between two addresses of one entity. Mint and burn transfers are reported separately.

| extract | window | total USD (bn) | both labelled, distinct entities | both labelled, same entity | one side | neither | mint/burn |
|---|---|---|---|---|---|---|---|
| oct25_hourly | 2025-09-15..2025-10-25 | 5435.47 | 0.33% | 4.09% | 11.74% | 82.69% | 1.15% |
| ftx_hourly | 2022-11-01..2022-11-16 | 555.11 | 0.43% | 9.62% | 19.43% | 66.31% | 4.20% |
| svb_hourly | 2023-03-01..2023-03-16 | 560.13 | 0.29% | 9.02% | 27.28% | 60.53% | 2.88% |
| core_daily | 2025-01-01..2026-06-30 | 646.40 | 0.13% | 8.41% | 24.37% | 58.89% | 8.20% |
| ftx_ext | 2022-10-01..2022-11-16 | 1182.23 | 0.35% | 7.57% | 16.41% | 71.82% | 3.85% |
| svb_ext | 2023-02-01..2023-03-16 | 1186.71 | 0.36% | 8.96% | 22.23% | 64.54% | 3.91% |

## Panel tokens only

Restricted to the tokens the hourly stress is built from. 'Distinct named-to-named / entity-touching' is the share of flow that touches a named entity and is named on both sides, among flow touching a named entity on at least one side (mint/burn excluded).

| extract | panel tokens | total USD (bn) | distinct named-to-named | one side | distinct named-to-named / entity-touching |
|---|---|---|---|---|---|
| oct25_hourly | USDe, sUSDe, wBETH, USDC, USDT | 2956.03 | 0.61% | 19.80% | 3.01% |
| ftx_hourly | USDC, USDT, WETH | 555.11 | 0.43% | 19.43% | 2.17% |
| svb_hourly | USDC, USDT, WETH | 560.13 | 0.29% | 27.28% | 1.03% |
| core_daily | USDe, sUSDe, wBETH | 646.40 | 0.13% | 24.37% | 0.55% |
| ftx_ext | USDC, USDT, WETH | 1182.23 | 0.35% | 16.41% | 2.09% |
| svb_ext | USDC, USDT, WETH | 1186.71 | 0.36% | 22.23% | 1.60% |

WETH is 45.6% of the oct25_hourly total USD flow (2479.45 bn of 5435.47 bn), so the ETH-denominated flow is a large part of the October window; the panel-token table above shows the stablecoin and staked-ETH panel separately.
