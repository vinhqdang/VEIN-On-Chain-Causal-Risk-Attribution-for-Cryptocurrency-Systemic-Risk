# Out-of-sample R-squared and own-lag baseline (Oct 2025 event window)

_expanding-window ridge refit (alpha=1) before each event hour; one-step ahead. 48 event hours, 720 entity-hour cells, 15 entities. R2_OS = 1 - SSE(model)/SSE(expanding mean)._

| model | pooled R2_OS | 95% CI (24 h blocks) | 95% CI (8 h blocks) | equal-weight mean over entities |
|---|--:|--:|--:|--:|
| ar | +0.1607 | [+0.0563, +0.2216] | [+0.0454, +0.2487] | +0.0815 |
| network | +0.0046 | [-0.0166, +0.0189] | [-0.0247, +0.0309] | -0.0034 |
| ar_network | +0.1584 | [+0.0446, +0.2256] | [+0.0306, +0.2563] | +0.0767 |

Gain over the own-lag model, 1 - SSE(model)/SSE(ar):

| model | gain | 95% CI (24 h) | 95% CI (8 h) |
|---|--:|--:|--:|
| network | -0.1861 | [-0.2709, -0.0621] | [-0.3193, -0.0506] |
| ar_network | -0.0028 | [-0.0202, +0.0145] | [-0.0323, +0.0333] |

| entity | ar | network | ar_network | network vs ar | ar_network vs ar |
|---|--:|--:|--:|--:|--:|
| Aave | +0.759 | +0.041 | +0.756 | -2.985 | -0.013 |
| Binance | +0.150 | +0.021 | +0.148 | -0.152 | -0.003 |
| Bitfinex | -0.018 | -0.203 | -0.184 | -0.181 | -0.163 |
| Bybit | -0.040 | -0.017 | -0.064 | +0.022 | -0.023 |
| Ceffu | -0.003 | -0.015 | -0.020 | -0.012 | -0.017 |
| Coinbase | +0.022 | +0.053 | +0.135 | +0.032 | +0.116 |
| Copper | +0.033 | +0.023 | +0.041 | -0.010 | +0.009 |
| Crypto.com | +0.007 | +0.016 | +0.023 | +0.010 | +0.016 |
| Ethena | +0.118 | +0.020 | +0.128 | -0.111 | +0.011 |
| HTX | -0.000 | -0.120 | -0.121 | -0.120 | -0.121 |
| Kraken | +0.021 | -0.056 | -0.036 | -0.078 | -0.058 |
| Lido | -0.005 | +0.000 | -0.005 | +0.005 | +0.000 |
| MakerSky | +0.148 | -0.027 | +0.145 | -0.205 | -0.003 |
| OKX | -0.004 | -0.108 | -0.114 | -0.104 | -0.110 |
| retail | +0.035 | +0.321 | +0.319 | +0.296 | +0.294 |

The event window has 48 hours, so 24-hour blocks give two blocks and the intervals are indicative. Entities whose benchmark SSE is zero show n/a.
