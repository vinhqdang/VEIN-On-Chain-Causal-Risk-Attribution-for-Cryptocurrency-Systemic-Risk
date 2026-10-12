# VEIN data build report

_Status: all stages have results (data_build.json generated 2026-10-12, backend bigquery). Billed so far 327.4 GiB (65 billed queries)._

Rendered from `results/data_build.json` and the label report by `run_build_data.py` (`--render` rebuilds this file offline: no BigQuery query, no network).

## Stage results (from `data_build.json`)

- `--check`: schema ok = True; latest block timestamp 2026-10-12 07:36:35+00:00; USDe 2025-10-10 dedupe 10501 rows, 10501 distinct.
- `--budget`: planned 286.17 GiB, of which new 32.68 GiB (extracts not yet materialised when the plan was made).
- `--selftest`: passed = True.
- `--extract`: 11 extract chunks, 58,276,883 rows, 4313 MB cached.
- USDe daily volume vs the earlier source: tolerance 0.02, passed = True.
- `--sweeps` (Tier-0 detections): oct25_hourly 260,325 ($74.5bn); ftx_hourly 95,993 ($25.5bn); svb_hourly 115,862 ($27.5bn); core_daily 10,851 ($22.7bn).
- `--coverage` (share of transfer USD with both sides resolved): oct25_hourly 4.4%; ftx_hourly 10.1%; svb_hourly 9.3%; core_daily 8.5%; ftx_ext 7.9%; svb_ext 9.3%.
- Label epochs (fingerprints): e2025 `77e9bcb096fe`; eftx `79dfa9194ae2`; esvb `55921ed54d53`.
- Billing ledger: 327.40 GiB cumulative, 152 entries (87 dry runs, 65 billed queries, 0 cache hits recorded).

## Label sources

| source | commit | licence | records read | mapped to a root | addresses mapped | wallet addresses | deposit addresses | excluded: other chain | excluded: not a wallet | no root |
|---|---|---|---|---|---|---|---|---|---|---|
| eth-labels | `d9b21aefeded56f7fce7208d6fa173d128526c1b` | MIT License | 226388 | 49938 | 24851 | 812 | 24040 | - | - | - |
| etherscan-labels | `923aba72c7e2d0682f7ae6194b6140bd90668dc9` | MIT License | 50924 | 1024 | 431 | 431 | 0 | - | - | - |
| spellbook | `6030202f2d6ee595dc568100c62723f26e5edda5` | Business Source License 1.1 | 4957 | 3407 | 3407 | 3398 | 9 | 61 | 39 | 1450 |

Record counts are per file. eth-labels ships each account list twice (CSV and JSON) and etherscan-labels has per-category and combined copies, so the address column is the one to read for coverage. `-` marks columns that do not apply to a source.

Licences. eth-labels and etherscan-labels are MIT-licensed (copyright notices kept in their licence files: Dawson Botsford, 2022; Brian Lee Cheow Teng, 2022). The Dune Spellbook list (`cex_evms_addresses.sql`, sparse clone at the pinned commit above) is under the Business Source License 1.1, which does not allow us to redistribute it. It is used only to build the internal label tables. `results/labels_open.csv.gz` is built from the two MIT sources alone (`vein.labels.public_table`): it has no Spellbook rows and no Spellbook source tags. The full table, including Spellbook rows, stays in `data_cache/labels_open.csv.gz`, which is git-ignored.

Spellbook rules. Each row maps to a root by its `cex_name`, falling back to its `distinct_name`. Rows tagged `kaia` in the name are Kaia-chain addresses and are excluded, because the file has no chain column and the table is Ethereum. Rows whose exchange name matches but whose name is not a trading wallet (charity, pool, deployer, router, token) are excluded as non-wallets. Names with `Deposit` are deposit-kind.

## Discovery output (`python -m vein.labels --discover <repo>`)

### eth-labels

2 of 8 files gave Ethereum label records; files with none are left out. Full per-file output: `data_cache/labels_discover_eth-labels.txt`.

| detected format and columns | files | example |
|---|---|---|
| `format=csv address=address name=nameTag category=label chain=chainId` | 1 | `data/csv/accounts.csv` |
| `format=json address=address name=nameTag category=label chain=chainId` | 1 | `data/json/accounts.json` |

### etherscan-labels

844 of 1093 files gave Ethereum label records; files with none are left out. Full per-file output: `data_cache/labels_discover_etherscan-labels.txt`.

| detected format and columns | files | example |
|---|---|---|
| `format=csv address=Address name=Name Tag category=None chain=None` | 422 | `data/etherscan/accounts/0x-protocol-ecosystem.csv` |
| `format=json address=<key> name=name/nameTag/value category=labels/label/<file stem> chain=None` | 422 | `data/etherscan/accounts/0x-protocol-ecosystem.json` |

## Open label table

- Addresses with one exchange root, all sources (cache `labels_open`): **27514**
- Public table `results/labels_open.csv.gz` (MIT sources only): **24959**
- Addresses dropped as conflicts (two different roots across sources): **1**, of which 1 involve the Spellbook list
- Addresses labelled both wallet and deposit (kept as deposit): 7
- of which wallet-kind (hot, cold, funder): **3465**; deposit-kind (`Dep:` or `Deposit` per-user addresses): **24049**
- Seed + wallet-kind base table (`labels_base`): 3484 rows, fingerprint `9a306b377e0e`
- Binance 14 (`0x28c6c06298d514db089934071355e5743bf21d60`) mapped to Binance: **True**

### The 17 label-table entities

Wallet-kind counts used for the entity table. `config seeds` are the hand-curated addresses, `open wallet` and `open deposit` come from all open sources, and `labels_base rows` is the entity's row count in the base table (seeds plus open wallets).

| entity | config seeds | open wallet | open deposit | labels_base rows |
|---|---|---|---|---|
| Binance | 7 | 144 | 5014 | 144 |
| Coinbase | 0 | 451 | 3 | 451 |
| OKX | 0 | 272 | 0 | 272 |
| Bybit | 0 | 50 | 0 | 50 |
| Bitfinex | 0 | 38 | 0 | 38 |
| HTX | 0 | 239 | 0 | 239 |
| Gate.io | 0 | 11 | 1 | 11 |
| Crypto.com | 0 | 68 | 0 | 68 |
| Bitget | 0 | 38 | 19027 | 38 |
| Bullish | 0 | 8 | 0 | 8 |
| Copper | 0 | 47 | 0 | 47 |
| Ceffu | 0 | 16 | 0 | 16 |
| FalconX | 0 | 9 | 0 | 9 |
| Aave | 10 | 0 | 0 | 10 |
| Ethena | 2 | 0 | 0 | 2 |
| Lido | 1 | 0 | 0 | 1 |
| MakerSky | 6 | 0 | 0 | 6 |

### Addresses per exchange root

| root | addresses |
|---|---|
| Bitget | 19065 |
| Binance | 5158 |
| Bithumb | 531 |
| Coinbase | 454 |
| OKX | 272 |
| Kraken | 263 |
| HTX | 239 |
| HitBTC | 112 |
| KuCoin | 80 |
| Crypto.com | 68 |
| Bitstamp | 65 |
| CoinW | 57 |
| CoinEx | 55 |
| CoinDCX | 53 |
| BingX | 52 |
| Bybit | 50 |
| Copper | 47 |
| MaskEX | 47 |
| Bitvavo | 39 |
| Bitfinex | 38 |
| Poloniex | 38 |
| BitMart | 37 |
| Bitkub | 36 |
| Upbit | 35 |
| Korbit | 34 |
| Bit-Z | 29 |
| Coinsquare | 28 |
| MEXC | 27 |
| Nobitex | 25 |
| FTX | 24 |
| CoinSpot | 23 |
| Hotbit | 23 |
| XT.com | 23 |
| LBank | 22 |
| BtcTurk | 20 |
| Deribit | 20 |
| ZB.com | 20 |
| Hoo | 19 |
| BitForex | 18 |
| Cobinhood | 18 |
| Gemini | 18 |
| Paribu | 18 |
| Bitpanda | 16 |
| Ceffu | 16 |
| WhiteBIT | 15 |
| EXMO | 14 |
| Robinhood | 14 |
| Binance.US | 13 |
| AscendEX | 12 |
| Coinhako | 12 |
| Gate.io | 12 |
| Indodax | 11 |
| BTSE | 9 |
| FalconX | 9 |
| bitFlyer | 9 |
| Bullish | 8 |
| Bitbank | 7 |
| Bittrex | 7 |
| DigiFinex | 6 |
| BigONE | 5 |
| Coincheck | 5 |
| Coinone | 4 |
| Coinsbit | 4 |
| Delta Exchange | 3 |
| BitMEX | 2 |
| BloFin | 1 |

### Label kind: wallets versus deposit addresses (treatment decision)

The open repositories mix operational wallets with per-user deposit addresses (`Binance Dep: 0x...`, `Bitget Dep: 0x...`), and the Spellbook list adds 9 deposit-kind addresses (`... Deposit N` names). Deposit labels are almost all from two exchanges: Bitget 19027, Binance 5014, Coinbase 3. Used as entity labels they would make Bitget the best-resolved exchange by far (it would capture most retail-to-exchange volume) for reasons unrelated to size, and would bias graph centrality and every ranking. Treatment:

1. Only wallet-kind labels (plus the config seeds) enter the label tables: they are the entity labels and the Tier-3 hot set H. Deposit-kind labels are not uploaded.
2. Deposit addresses are found uniformly for every exchange by Tier-0 sweep detection (one rule, applied to every hot wallet).
3. The deposit-kind labels are kept in `data_cache/labels_open.csv.gz` (column `kind`) as an independent validation set for Tier-0 (`overlap_deposit_labels` in the sweeps report), and as ground truth for the Tier-1/2 resolver validation (`labels_edges`), which must be reported as deposit-dominated.

Limitation: Tier-0 can only find deposit addresses of exchanges that have hot-wallet labels in H, so coverage still differs by exchange (wallet labels per root below).

| root | wallet labels | deposit labels |
|---|---|---|
| Bitget | 38 | 19027 |
| Binance | 144 | 5014 |
| Bithumb | 531 | 0 |
| Coinbase | 451 | 3 |
| OKX | 272 | 0 |
| Kraken | 263 | 0 |
| HTX | 239 | 0 |
| HitBTC | 112 | 0 |
| KuCoin | 80 | 0 |
| Crypto.com | 68 | 0 |
| Bitstamp | 65 | 0 |
| CoinW | 57 | 0 |
| CoinEx | 55 | 0 |
| CoinDCX | 53 | 0 |
| BingX | 52 | 0 |

### Unmapped names

None: every eth-labels name with an 'exchange' category maps to an exchange root or is excluded.

Spellbook rows with no exchange root and no known exchange name: 1450 (counts only, since the list is not redistributed; the distinct names are in `data_cache/labels_report.json`).

### Exclusions

- `vein.config.LABEL_EXCLUDE` (token, deployer, bridge, router, commerce, airdrop, nft, governance, pool, vault, swap, exploit, phish, fake) on name and category.
- `vein.labels.NON_CEX_EXCLUDE` (charity, nonprofit, donate, industry recovery, AVS operator, MEV, proposer fee recipient): Binance Charity and similar wallets are not trading wallets.
- Token-contract files (`tokens/`, `tokens.csv`, `tokens.json`) and the duplicated `combined/` folders. Non-Ethereum explorer folders (bscscan, polygonscan, arbiscan, avalanche, ftmscan, optimism) are skipped by path because they have no chain field.
- Spellbook rows tagged with another chain (`kaia`): 61. Spellbook rows that name a known exchange but are not trading wallets: 39.


## Pending

None: every stage has a result in `data_build.json`.
