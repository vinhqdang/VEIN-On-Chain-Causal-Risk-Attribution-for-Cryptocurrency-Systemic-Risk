# Label coverage of on-chain token flows

Shares are of total USD flow in each extract window. 'Both resolved' means both endpoints carry a label (seed, open label or sweep). Mint and burn transfers are reported separately.

Old-vs-new: the Dune pipeline resolved roughly 1% of the $438bn window flow between two named entities (paper baseline). Compare the 'both resolved' row below.

| extract | window | total USD (bn) | both resolved | one side | neither | mint/burn |
|---|---|---|---|---|---|---|
| oct25_hourly | 2025-09-15..2025-10-25 | 5435.47 | 3.95% | 8.51% | 86.39% | 1.15% |
| ftx_hourly | 2022-11-01..2022-11-16 | 555.11 | 10.03% | 16.13% | 69.64% | 4.20% |
| svb_hourly | 2023-03-01..2023-03-16 | 560.13 | 9.31% | 17.67% | 70.15% | 2.88% |
| core_daily | 2025-01-01..2026-06-30 | 646.40 | 8.48% | 7.59% | 75.74% | 8.20% |
