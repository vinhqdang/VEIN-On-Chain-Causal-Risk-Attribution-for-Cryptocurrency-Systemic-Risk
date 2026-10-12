# RESULTS V3: evidence base for the methods paper

Status: final rerun (BigQuery data, full abduction, joint circular-block bootstrap, pre-event s*, DeFi protocol stress). **Sections 3, 4, 5.1, 6.2 to 6.5, 8, 9.1, 9.4, 12, 13 and 14 were updated after the bootstrap fix** (circular block bootstrap replaces the plain moving-block bootstrap; replicate shock pools are residuals of the drawn rows; R-squared reporting; all-source attribution list; out-of-sample R-squared). The daily `results.json`, `analytics.json`, `revision*.json` and `topk_sensitivity.json` were also regenerated on 2026-10-12 (11:29 to 11:38), after the circular-bootstrap fix, so they use the current shock-draw scheme; the robustness checks in them remain point comparisons without intervals. `python check_acceptance.py` reports 15 PASS, 2 WARN, 0 FAIL (the two WARN lines are the daily FTX and SVB robustness runs, which are explicitly underpowered).

Conventions.
- Paths are `file.json: key/key[i]` relative to `results/`. "v1" is `results/v1_dune/` (Dune, legacy zero-shock method). "v2" is `results/v2_bq_initial/`.
- Every number below was read from the JSON files named next to it. Numbers marked (calc) were computed here from archived values and are not stored in any results file.
- Verdict labels: ROBUST, WEAK, NOT SUPPORTED, REVERSED (versus v1), INFORMATIONAL.
- Hourly Oct-2025 run: 15 entities, 600 fit hours (2025-09-15 00:00 to 2025-10-09 23:00), 48 event hours (2025-10-10 00:00 to 2025-10-11 23:00), 90 directed edges. `final_results.json: n_entities, n_fit_hours, n_event_hours, graph_edges`.

---

## 0. One-paragraph reading of the results

The pipeline is now sound (non-degenerate stress for every node, joint block bootstrap, MC error reported, no NaNs, acceptance checks pass), and the results are modest. The network structural equations explain little of hourly stress (in-sample R-squared 0.001 to 0.273). As a result no single channel carries more than 15.2% of any entity's realised event distress (v1 reported 98.1% for Binance to Bybit, an artefact of zero-shock abduction). The observed on-chain graph does not predict better than a price-estimated graph (H1 not supported; the sign flips with the error weighting and block length, and the gaps are at most 0.35% of RMSE). Edge direction is not statistically distinguishable from reversal in any of the three hourly events (Oct 2025: 0.17% RMSE gap, paired 95% CI [-0.0006, +0.0093] after the bootstrap fix; FTX and SVB inconclusive). The OC-CoVaR ranking has a stable top group (retail, MakerSky in the top 3 with probability at least 0.88), but both of those ranks run through the aggregate "retail" node, and ranks 3 to 8 are statistically unresolved. Placebo evidence is mixed. Out of sample, the observed-graph equations have a pooled one-step R-squared of +0.005 against an expanding-mean benchmark, an own-lag AR(1) has +0.161, and adding the network to the own lag changes it by -0.3% [-2.0%, +1.4%] (Section 6.5). This is a methods contribution (identification, abduction, uncertainty, decomposition) with a descriptive, low-power empirical application.

---

## 1. Data

### 1.1 Sources

| item | value | path |
|---|---|---|
| Flow source | BigQuery `crypto_ethereum.token_transfers` (view), data_backend `bigquery`, generated 2026-10-12 | `data_build.json: generated, data_backend` |
| Freshness | max block_timestamp 2026-10-12 07:36:35 UTC | `data_build.json: checks/freshness_max_block_timestamp` |
| Partition pruning (dry run) | 1 day 0.81 GiB, 10 days 3.95 GiB | `data_build.json: checks/partitioning` |
| USDe 2025-10-10 dedupe | n = 10501, distinct = 10501, upper-case duplicates 0 | `data_build.json: checks/dedupe` |
| Prices / TVL | CoinGecko, DefiLlama (Jan 2024 to Jun 2026) | `EVALUATION.md` header |
| Label sources | eth-labels (commit d9b21ae..., MIT), etherscan-labels (commit 923aba7..., MIT), Dune Spellbook CEX list (commit 6030202..., Business Source License 1.1, not redistributed) | `data_build.json: labels/revisions, labels/licences` |
| Open label table | 27,514 addresses with one exchange root; 1 conflict dropped (involves Spellbook); public MIT-only table 24,959 addresses | `data_build.json: labels/open_addresses, labels/conflicts, labels/public_addresses` |
| Label kinds | wallet-kind 3,465, deposit-kind 24,049 (Bitget 19,027; Binance 5,014; Coinbase 3). Only wallet-kind labels (plus seeds) enter the label tables (3,471 base rows, fingerprint 5d2705754343). Deposit labels are used only as the Tier-0 validation set. | `data_build.json: labels/open_per_root_deposit, labels/base_rows, labels/base_fingerprint`; `DATA_BUILD.md` |
| Binance 14 maps to Binance | True | `DATA_BUILD.md` |

### 1.2 Windows and entity sets

| run | window | fit rows / event rows | entities | edges |
|---|---|---|---|---|
| Oct-2025 hourly (main) | 2025-09-15 to 2025-10-25 | 600 / 48 | 15: Aave, Binance, Bitfinex, Bybit, Ceffu, Coinbase, Copper, Crypto.com, Ethena, HTX, Kraken, Lido, MakerSky, OKX, retail | 90 (86 custodial, 4 composability: `revision.json: edge_type_falsification/n_*_edges`) |
| FTX hourly (extended) | 2022-10-01 to 2022-11-16, event 2022-11-08 to 2022-11-11 | 912 / 96 | 14: Aave, Binance, Bitfinex, Coinbase, Crypto.com, FTX, FalconX, HTX, Kraken, KuCoin, Lido, MakerSky, OKX, retail | 81 |
| SVB/USDC hourly (extended) | 2023-02-01 to 2023-03-16, event 2023-03-10 to 2023-03-13 | 888 / 96 | 14: Aave, Binance, Bitfinex, Bybit, Coinbase, Crypto.com, FalconX, HTX, Kraken, KuCoin, Lido, MakerSky, OKX, retail | 85 |
| Daily core (secondary) | 2025-01-01 to 2026-06-30, 7 event days | n/a | 15: Aave, Binance, Bitfinex, Bybit, Ceffu, Coinbase, Copper, Ethena, FalconX, HTX, Kraken, Lido, MakerSky, OKX, retail | 54 (`EVALUATION.md`; `results.json: n_event_days`) |
| Intraday A3 | 2025-10-01 to 2025-10-14, 216 fit hours, 48 event hours | 216 / 48 | 15 | n/a |

Sources: `final_results.json`, `multievent.json: events[*]`, `intraday_a3.json`, `results.json`. The daily FTX and SVB runs are flagged `ok: false, reason: underpowered` (38 and 37 fit rows against 125 required): `multievent.json: events[*]/daily_robustness`. Do not report them.

Entity-set differences that matter: the hourly set contains Crypto.com and not FalconX; the daily set contains FalconX and not Crypto.com. Bitget, Bullish, Gate.io (in v1) are out. Kraken is in. Top-k cut at k = 12 (`topk_sensitivity.json: main_k`).

### 1.3 Coverage (label resolution of the flow data)

Definition that matters for the paper: "named distinct" is flow with both endpoints labelled to different named entities. COVERAGE.md "both resolved" also counts same-entity transfers (deposit address to its own hot wallet), so do not quote it as named-to-named flow.

| extract | total USD (bn) | both labelled, distinct entities | both labelled, same entity | one side | neither | path |
|---|--:|--:|--:|--:|--:|---|
| oct25_hourly | 5,435.47 | 0.334% | 4.087% | 11.74% | 82.69% | `coverage.json: oct25_hourly/shares` |
| ftx_hourly | 555.11 | 0.432% | 9.622% | 19.43% | 66.31% | `coverage.json: ftx_hourly/shares` |
| svb_hourly | 560.13 | 0.285% | 9.023% | 27.28% | 60.53% | `coverage.json: svb_hourly/shares` |
| core_daily | 646.40 | 0.135% | 8.410% | 24.37% | 58.89% | `coverage.json: core_daily/shares` |
| ftx_ext | 1,182.23 | 0.350% | 7.565% | 16.41% | 71.82% | `coverage.json: ftx_ext/shares` |
| svb_ext | 1,186.71 | 0.362% | 8.965% | 22.23% | 64.54% | `coverage.json: svb_ext/shares` |

Panel-token view (the tokens the stress is built from). `named_distinct_share_of_touching` is named-to-named flow divided by flow touching a named entity on at least one side (mint/burn excluded). `coverage.json: <extract>/panel_tokens/named_distinct_share_of_touching`:

| extract | panel tokens | named-distinct share of entity-touching flow |
|---|---|--:|
| oct25_hourly | USDe, sUSDe, wBETH, USDC, USDT | 3.009% (total 2,956.03 bn) |
| ftx_hourly | USDC, USDT, WETH | 2.175% |
| svb_hourly | USDC, USDT, WETH | 1.035% |
| core_daily | USDe, sUSDe, wBETH | 0.550% |
| ftx_ext | USDC, USDT, WETH | 2.087% |
| svb_ext | USDC, USDT, WETH | 1.601% |

Cross-check on the model's own flow panel (after the top-k and same-entity drops): named on both sides 2.843% of $569.7bn, `revision.json: resolution_coverage/frac_volume_named_both_sides, total_usd`. (`frac_volume_touching_named = 1.0` in the same block is trivial, because the panel contains only entity-touching flow.)

Old paper statement: about 1% of $438bn. New: about 3.0% (Oct panel tokens), 2.8% (model panel). Verdict: INFORMATIONAL. Named-to-named flow is a few percent of entity-touching flow; the graph is dominated by edges between a named entity and the aggregate "retail" node (the "unresolved" remainder). WETH is 45.6% of the oct25 total USD (2,479.45 bn of 5,435.47 bn), which dilutes the all-token percentages (`COVERAGE.md`).

### 1.4 Tier-0 deposit-sweep detection: validation

Holdout: 25,080 deposit-kind labelled addresses never used to build the table. Acceptance rule: precision at least 0.9 on at least 20 overlapping holdout detections. `data_build.json: sweeps/validation/<extract>`.

| extract | rule chosen | overlap (correct root / wrong root) | precision | Wilson 95% lower bound (calc) | recall (count) | recall (volume) | detections |
|---|---|---|--:|--:|--:|--:|--:|
| oct25_hourly | default (tau 0.8, max_out_cp 3) | 423 / 0 | 1.000 | 0.991 | 0.683 | 0.0036 | 234,062 |
| ftx_hourly | tightened (tau 0.9, max_out_cp 2) | 13 / 0 | 1.000 | 0.772 | 0.171 | 0.0435 | 86,557 |
| svb_hourly | default | 31 / 0 | 1.000 | 0.890 | 0.341 | 0.0318 | 100,430 |
| core_daily | default | 64 / 0 | 1.000 | 0.943 | 0.552 | 0.0006 | 10,842 |

Swept volume in the production runs (`sweeps/per_extract`): oct25 $74.5bn (260,325 detections), ftx $25.5bn (95,993), svb $27.5bn (115,862), daily $22.7bn (10,851).

Flags.
- FTX holdout overlap is 13, below the 20 required by the acceptance rule. Precision 13/13 is real but the lower bound is 0.77. State it as limited evidence.
- Precision is measured on deposit labels, which are almost all Binance and Bitget (data_build: Bitget 19,027, Binance 5,014, Coinbase 3). Sweep detections for Coinbase (47,778), Bybit (41,597) and Kraken (12,993) in the Oct extract have essentially no independent holdout. Do not extrapolate "precision 1.0" to every exchange.
- Recall by volume is tiny (0.0006 to 0.0435). The sweep layer finds many small deposit addresses, not the bulk of volume.

Verdict: precision ROBUST for Binance/Bitget-type deposit addresses; coverage of volume WEAK.

Tier-1 / Tier-2 resolver (USDe, 2025-10-08 to 10-14, 7,019 addresses, 41 CEX-labelled over 10 roots): ROC-AUC 0.891, average precision 0.170 (base rate 0.0058), best-F1 0.215 (precision 0.132, recall 0.583); volume-weighted precision 0.916, recall 0.152; Tier-2 embedding cluster homogeneity 0.103. `results.json: entity_resolution_validation/tier1_classifier, tier2_embedding`. Verdict: WEAK (an exploratory layer; the ground truth set is deposit-dominated and tiny).

### 1.5 USDe check (BigQuery against the Dune figures in the original paper)

Six days, 2025-10-08 to 10-13, relative differences between 4.5e-5 and 5.6e-4 (tolerance 0.02): `data_build.json: usde_daily_check`. USDe daily volume ($bn): 1.405, 0.745, 3.090, 8.828, 1.328, 0.688. Peak: 10 Oct 3.09, 11 Oct 8.83. Verdict: ROBUST (passed).

Protocol token checks: all expected Aave/Ethena/MakerSky/Lido tokens resolved (`protocol_check/tokens_lookup/symbols_missing_expected: []`); Lido withdrawal queue active in 97.9% of 960 hours (`protocol_check/lido/share_hours_wq_in_gt0 = 0.979`).

### 1.6 BigQuery cost

`data_build.json: ledger`: cumulative billed 327.40 GiB (cap 338.05 GiB; monthly cap 950 GiB), 152 ledger entries, 87 dry runs, 65 billed queries, 0 cache hits, all in 2026-10. Plan: 286.17 GiB planned, 32.68 GiB new in the last stage, 421.95 GiB headroom (`budget/planned_gib, planned_new_gib, headroom_gib`). Extract sizes (`extract_rows`): oct25_hourly 25,443,752 rows (1.88 GB), ftx_ext 10,836,722 rows, svb_ext 11,825,053 rows, ftx_hourly 4,226,301, svb_hourly 4,332,357, oct25_lido 79,922, core_daily 5 chunks (about 1.53 million rows in total). Selftest passed (SQL and pandas sweeps agree: `selftest/passed: true`).

Stale-file warning: `DATA_BUILD.md` still carries its early status line ("labels stage only; BigQuery stages not run") and an entity seed table (Aave 2, MakerSky 1 seed addresses) that predates the protocol seeds in `vein/config.py` (Aave 10, MakerSky 6, Ethena 2, Lido 1). `data_build.json` is current. Cite the JSON, not the .md.

---

## 2. Stress construction (including DeFi components)

Stress for entity i at hour t is the equal-weight mean of its components (`vein/hourly_stress.py`; `vein/config.py: HOURLY_STRESS_COMPONENTS`). Each component is z-scored on a 48-hour rolling window (min 6 periods). A component is kept only if its fit-window standard deviation exceeds 1e-9 and its inputs exist; drop reasons are recorded.

| entity | components used (Oct hourly) | dropped | fit-window std | path |
|---|---|---|--:|---|
| CEXs, Copper, Ceffu, retail (10 CEX + retail) | `flow` only (0.6 z(net flow ratio) + 0.4 z(total flow)) | none | 0.65 to 0.98 | `final_results.json: stress_components` |
| Aave | `flow`, `drawdown:AAVE` (price drawdown) | none | 0.768 | same |
| Ethena | `flow`, `peg:USDe` (peg deviation) | none | 0.706 | same |
| MakerSky | `flow`, `peg:DAI` | none | 0.649 | same |
| Lido | `discount:stETH/ETH`, `lido_redeem` (withdrawal-queue net redemption) | none | 0.762 | same |

- In the Oct run all four DeFi entities have non-degenerate stress (A1 check: 117 entity records, all fit std above 1e-9). This fixes the v1 and v2 problem where Aave, Lido, MakerSky had identically zero stress, zero s*, zero exported risk by construction, a half-trivial H1, and a vacuous external-validity check.
- In FTX and SVB: Aave (`flow`, `drawdown:AAVE`) and MakerSky (`flow`, `peg:DAI`) are used; Lido uses `discount:stETH/ETH` only, with `lido_redeem` dropped ("no Lido series", `multievent.json: events[*]/stress_components/Lido/dropped`). Ethena does not exist in those windows.
- Fit-window gross flow: Lido $0.0bn (no flow edges; its stress is price and queue only), Ethena $0.103bn, Aave $69.6bn, MakerSky $22.7bn, retail $350.7bn (`final_results.json: fit_gross_usd`).
- s* is fixed at the 0.95 quantile of fit-window stress, excluding the event window (`final_results.json: settings/s_star_quantile, s_star_excludes_event_window`). Hourly s* ranges from 0.31 (Ceffu) to 2.14 (Bitfinex) (`hourly_scm_export.json: s_star`).

Caveat for the paper: 4 of 15 nodes (Aave, Ethena, MakerSky, Lido) carry price-based stress components (drawdown, peg, discount) alongside or instead of flow. The DeFi parts of the model are therefore not a purely on-chain measurement, and Lido enters the graph only through the documented Lido to Aave edge (Lido has no parents in the fitted SCM and exports only via Aave: `hourly_scm_export.json: scm_coefficients/Lido, Aave`).

Verdict: construction ROBUST (non-degenerate, screened, logged). Interpretation of the DeFi nodes WEAK (single documented edge, price-based proxies).

---

## 3. H1: observed on-chain graph versus estimated graph

Setup. Same SCM machinery; the graph is taken from observed flows (plus 4 documented edges) or estimated from price returns (Granger, partial correlation). Six comparison nodes: Aave, Binance, Ethena, Lido, MakerSky, retail. n = 288 predictions (6 nodes x 48 hours). Edge counts observed 13, Granger 14, partial correlation 10. `final_results.json: H1`.

Point scores (weighted RMSE, weights |stress| + 0.1):

| graph | weighted RMSE | timing corr | path |
|---|--:|--:|---|
| observed on-chain | 1.5545 | 0.1431 | `H1/scores[0]` |
| Granger | 1.5595 | 0.1737 | `H1/scores[1]` |
| partial correlation | 1.5599 | 0.1573 | `H1/scores[2]` |

Gap: observed better by 0.0050 weighted RMSE (0.32%) against Granger and 0.0054 (0.35%) against partial correlation (`H1/rmse_gap_vs_best_estimated = 0.00498`). All timing correlations are at most 0.17, so every graph has very low skill.

Paired circular block bootstrap of the difference (estimated minus observed; positive = observed better), B = 2000, seed 7 (updated after bootstrap fix; before the fix the plain moving-block bootstrap gave unweighted 24-h CIs [-0.01501, -0.00386] and [-0.01768, -0.00539], both "estimated_better", and weighted CIs [+0.01235, +0.03567] and [-0.00297, +0.01588]). `final_results.json: H1/bootstrap`:

| estimand | block | Granger: mean diff, 95% CI, status | partial correlation: mean diff, 95% CI, status |
|---|---|---|---|
| unweighted squared one-step error | 24 h | -0.00532, [-0.01288, +0.00212], inconclusive (P(observed better) = 0.062) | -0.00308, [-0.01514, +0.00942], inconclusive (P = 0.289) |
| unweighted squared one-step error | 8 h | [-0.02169, +0.00711], inconclusive (`ci95_block8`) | [-0.02091, +0.01010], inconclusive |
| weighted error (the table's scale) | 24 h | mean +0.01044, [-0.01399, +0.03501], inconclusive (`ci95_weighted`) | mean +0.01137, [+0.00026, +0.02287], observed_better (borderline: lower bound 0.0003) |

Other archived H1 numbers.
- `revision.json: H1`: weighted error, 8-h blocks, 2000 replicates, Granger minus observed mean +0.01044, CI [-0.00199, +0.04338], P(observed better) = 0.9585. Unweighted RMSE: observed 0.8455, Granger 0.8423; MAE 0.5645 vs 0.5621; directional accuracy 0.500 vs 0.535.
- Strictly lagged flows: observed weighted RMSE 1.5496, Granger 1.5571 (`revision.json: lagged_flow`).
- Non-flow target (all exchange nodes share one ETH drawdown target, so nearly uninformative): contemporaneous observed 1.628 vs Granger 1.359; lagged 1.631 vs 1.359 (`revision2.json: nonflow_H1`). Estimated graph wins.
- Daily (n = 42): observed 2.603, Granger 2.336, partial correlation 2.408; estimated graph wins (`validation.json: H1_observed_vs_estimated`).
- Top-k sensitivity: observed weighted RMSE 1.5548 / 1.5545 / 1.5514 at k = 10 / 12 / 15, always about 0.3% below the estimated graphs (`topk_sensitivity.json: by_k/*/H1_rmse`).

Status: `H1_supported: false` (`final_results.json: H1/H1_supported`). The point estimate favours the observed graph in weighted RMSE; the unweighted bootstrap is inconclusive at both block lengths against both estimated graphs; the weighted 24-h bootstrap favours the observed graph only against partial correlation and only just (lower bound +0.0003), and is inconclusive against Granger. Before the fix the unweighted 24-h intervals said "estimated_better"; that was the edge artefact below, not evidence.

Flags.
- Diagnosed and fixed: the old intervals excluded their own means because the plain moving-block bootstrap draws block starts from the n - L + 1 admissible positions only, so with 48 steps and L = 24 the middle steps carry up to 24 times the weight of the first and last steps, and the replicate mean is pulled towards where the errors are concentrated (replicate mean of the symmetric-minus-true difference 0.0063 against the sample mean 0.0029, reproduced from the archived per-cell errors; the partial-correlation H1 interval was displaced the same way, entirely below its mean). The circular block bootstrap gives every step the same weight; replicate means now equal the sample means to 4 decimals (`boot_mean`, `ci_contains_mean` are stored). Only two 24-h blocks exist, so the intervals remain indicative.
- A graph-free own-lag baseline is now archived (Section 6.5, `oos_r2.json`); on the six-node H1 subset it is not evaluated.

Versus v1: v1 reported observed 1.2529 vs Granger 1.2568 vs partial correlation 1.2547 (`v1_dune/final_results.json: H1/scores`) and `H1_supported: true` on a 0.0039 gap with no interval. Verdict: REVERSED in status (supported to not supported), WEAK as a finding. The paper should state "no evidence that observing the graph beats estimating it at this horizon; differences of at most 0.35% whose sign depends on the estimand".

---

## 4. Falsification / H2 (true versus reversed versus symmetric direction)

Weighted RMSE, one-step-ahead event-window prediction, entity-hours as units.

| event | n | true | reversed | symmetric | reversed minus true (unweighted squared error), 95% CI, status | symmetric minus true, 95% CI, status |
|---|--:|--:|--:|--:|---|---|
| Oct-2025 hourly (main) | 720 | 1.7841 | 1.7871 | 1.7862 | +0.00416, [-0.00059, +0.00933], inconclusive (24-h circular blocks, 2000 reps; before the fix [+0.00163, +0.01036], observed_better) | +0.00289, [-0.00159, +0.00752], inconclusive (before the fix [+0.00425, +0.00793], which excluded its own mean) |
| Oct-2025 intraday A3 (216 fit hours) | 720 | 1.8022 | 1.8036 | 1.8097 | +0.00663, [-0.00346, +0.01661], inconclusive; relative gap true vs reversed 0.078%; verdict NO_DIFFERENCE_DETECTED | +0.01267, [+0.00031, +0.02497], observed_better (borderline; lower bound 0.0003) |
| FTX Nov 2022 hourly | 1344 | 1.3019 | 1.2987 | 1.2995 | -0.00048, [-0.00252, +0.00140], inconclusive (500 reps) | -0.00067, [-0.00370, +0.00210], inconclusive |
| USDC/SVB Mar 2023 hourly | 1344 | 1.6514 | 1.6551 | 1.6528 | +0.00325, [-0.00255, +0.01129], inconclusive | +0.00240, [-0.00113, +0.00641], inconclusive |
| Daily core (7 days) | 105 | 2.5207 | 2.2941 | 2.3073 | n/a (reversed better by 9.0%) | n/a |

Paths: `final_results.json: falsification, falsification_ci`; `intraday_a3.json: falsification, rmse_relative_gap_true_vs_reversed, paired_bootstrap, verdict`; `multievent.json: events[0|1]/falsification, falsification_ci`; `results.json: falsification`. Timing correlations (Oct main): 0.1116 / 0.0988 / 0.1069.

Effect sizes: Oct main true beats reversed by 0.17% RMSE and symmetric by 0.12%; FTX reversed beats true by 0.25%; SVB true beats reversed by 0.22%. The direction effect is at most a quarter of one percent in every event.

Edge-type split, Oct hourly (`revision.json: edge_type_falsification`): true 1.7841; reversing the 86 custodial edges worsens to 1.7905; reversing the 4 composability edges improves slightly to 1.7806. Direction information, to the extent it exists, sits on the custodial edges, and the documented composability edges are not supported by the data (only 4 edges, so this is anecdotal).

Non-flow target falsification (`revision2.json: nonflow_falsification`): true 1.091, reversed 1.004, symmetric 1.002. Uninformative by construction (shared target series).

Flags.
- Fixed: the `symmetric_minus_true` CI [0.00425, 0.00793] excluded its mean 0.00289 because of the edge weighting of the plain moving-block bootstrap (replicate mean 0.0063; see Section 3 flags). With the circular bootstrap the interval is [-0.00159, +0.00752] and contains the mean (replicate mean 0.00292); the Oct-main direction "significance" disappears for both reversed and symmetric. Only the intraday A3 symmetric comparison (different window and fit length) has a CI above zero, by 0.0003.
- Intervals use 720 pooled entity-hours with a 24-hour block bootstrap on 48 event hours (2 blocks). Treat them as indicative.
- Multiple events, no correction: 0 of 3 hourly events (and 1 borderline symmetric comparison in the intraday A3 window) show a direction effect.

Versus v1: v1 true 1.663 < symmetric 1.667 < reversed 1.675 (n = 816). The ordering of true versus reversed is the same in the Oct main run, with a smaller margin (0.17% vs 0.71%), and the intraday test is a tie. FTX: v1 true best (1.455 vs 1.543 reversed, as quoted in `RERUN_SUMMARY.md`) becomes reversed best (by 0.25%) and inconclusive. Verdict: H2 / A3 NOT SUPPORTED as a general claim (no difference detected at intraday, inconclusive in all three hourly events, effect below 0.3% everywhere); Oct main inconclusive (was WEAK-supported before the bootstrap fix).

---

## 5. Ranking: OC-CoVaR exported risk

Definition: exported risk of i = sum over targets j of the change in j's CoVaR under do(S_i = distress). Magnitudes scale with the number of entities (top-k table below), so compare ranks, not levels across runs.

### 5.1 Ranking, MC error and bootstrap rank uncertainty

Point estimate: n_sims = 2000, seed 7 (`final_results.json: oc_covar_ranking`). Bootstrap: 300 joint circular-block pairs bootstrap refits, 500 sims per replicate, block length 24 h (`uncertainty.json: settings`). Updated after the bootstrap fix: the shock draws are circular, and the shock pool of each replicate is the set of residuals of the rows that replicate was fitted on (before: residuals of all original rows, 37% of which the refit had not seen, which inflated the replicate variance). `mc_se` is the Monte Carlo standard error at 2000 sims (`uncertainty.json: ranking/point[*]/mc_se`, 20 repeated runs at 500 sims, `ranking/mc_error`).

| rank | entity | exported risk | MC s.e. | bootstrap 95% CI of risk | rank 95% CI | P(top 1) | P(top 3) |
|--:|---|--:|--:|---|---|--:|--:|
| 1 | retail | 44.98 | 0.435 | [27.18, 75.19] | [1, 3] | 0.767 | 0.983 |
| 2 | MakerSky | 37.89 | 0.288 | [23.70, 58.08] | [1, 5] | 0.173 | 0.880 |
| 3 | Bitfinex | 26.20 | 0.320 | [8.89, 43.70] | [2, 10] | 0.020 | 0.243 |
| 4 | Coinbase | 26.08 | 0.278 | [10.55, 45.96] | [1, 9] | 0.027 | 0.340 |
| 5 | Kraken | 24.80 | 0.287 | [12.81, 41.64] | [2, 10] | 0.003 | 0.197 |
| 6 | Crypto.com | 23.92 | 0.307 | [8.07, 45.43] | [2, 11] | 0.000 | 0.147 |
| 7 | Binance | 22.35 | 0.302 | [12.06, 47.23] | [2, 9] | 0.003 | 0.167 |
| 8 | OKX | 19.51 | 0.238 | [8.22, 34.16] | [3, 10] | 0.007 | 0.043 |
| 9 | HTX | 13.68 | 0.251 | [3.97, 26.28] | [5, 12] | 0.000 | 0.000 |
| 10 | Bybit | 13.43 | 0.205 | [3.25, 23.69] | [5, 13] | 0.000 | 0.000 |
| 11 | Copper | 4.50 | 0.134 | [1.37, 13.83] | [9, 14] | 0.000 | 0.000 |
| 12 | Aave | 3.38 | 0.118 | [0.08, 13.26] | [9, 15] | 0.000 | 0.000 |
| 13 | Lido | 3.37 | 0.125 | [0.00233, 9.26] | [10, 15] | 0.000 | 0.000 |
| 14 | Ethena | 0.70 | 0.037 | [0.04, 7.57] | [11, 15] | 0.000 | 0.000 |
| 15 | Ceffu | 0.55 | 0.018 | [0.000764, 1.58] | [13, 15] | 0.000 | 0.000 |

(`uncertainty.json: ranking/by_entity/<entity>`.) Bootstrap resolution is 1/300 = 0.0033.

Pairwise P(row above column) among the top six (`uncertainty.json: ranking/pairwise_top6`):

| | MakerSky | Bitfinex | Coinbase | Kraken | Crypto.com |
|---|--:|--:|--:|--:|--:|
| retail above | 0.800 | 0.970 | 0.937 | 0.990 | 0.990 |
| MakerSky above | n/a | 0.883 | 0.897 | 0.917 | 0.913 |
| Bitfinex above | | n/a | 0.433 | 0.547 | 0.560 |
| Coinbase above | | | n/a | 0.593 | 0.657 |
| Kraken above | | | | n/a | 0.547 |

Rank stability: Spearman between the bootstrap rankings and the point ranking has mean 0.903, 95% interval [0.793, 0.968] (`ranking/spearman_vs_point`).

MC error is negligible against estimation uncertainty: the retail-minus-MakerSky gap is 7.09 against a combined MC s.e. of 0.52 (13.6 s.e., calc), yet the bootstrap gives P(retail above MakerSky) = 0.800. The uncertainty in the ranking comes from coefficient estimation, not from simulation.

Reading. Robust: the top group {retail, MakerSky} (P(top 3) = 0.98 and 0.88), retail above Bitfinex, Coinbase, Kraken and Crypto.com with probability 0.94 to 0.99 and MakerSky above them with 0.88 to 0.92, and the bottom group {Ethena, Ceffu, Aave, Lido, Copper} (P(top 5) = 0). Not resolved: the order of retail and MakerSky (0.80), the third place (Bitfinex P(top 3) = 0.24, Coinbase 0.34; the point order of these two swapped with the circular shock draws, 26.20 vs 26.08, a 0.12 gap against combined MC s.e. 0.42), and everything in ranks 3 to 8 (pairwise 0.34 to 0.66). Binance, the headline of v1, is 7th (rank CI [2, 9], P(top 3) = 0.167).

Flags.
- Both top ranks run through the aggregate "retail" node ("everything not resolved"). With retail removed (`revision.json: no_retail_ranking`): Binance 17.94, Crypto.com 15.57, Kraken 14.93, Coinbase 11.35, OKX 10.12, Bitfinex 9.95. MakerSky drops out of the top six. The leading channel is MakerSky to retail (Section 7), so MakerSky's rank 2 depends on the retail aggregate.
- Centring check (updated after the bootstrap fix): before, bootstrap medians exceeded point estimates for most entities (MakerSky 42.70 vs 37.86, Coinbase 31.65 vs 26.37, Aave 4.74 vs 2.94, Ethena 1.56 vs 0.69), caused by the residual-pool mismatch described above. After the fix medians are within 2.0 of the points for the top eight (MakerSky 37.92 vs 37.89, Coinbase 26.66 vs 26.08, retail 46.98 vs 44.98) and the intervals narrow (retail [27.18, 75.19], was [27.65, 83.50]). Small exporters still have right-skewed CIs because exported risk is non-negative (Ethena median 1.26 vs point 0.70, CI [0.04, 7.57]). All 15 point estimates lie inside their intervals.
- The 2000-path point estimates also moved slightly with the circular shock draws (Aave 2.94 to 3.38, Lido 3.37 to 3.37 but their order swapped, Bitfinex 25.73 to 26.20, Coinbase 26.37 to 26.08, Kraken 23.97 to 24.80). Differences above 3 MC s.e. for Aave show that ranks 12 to 13 depend on the shock-pool scheme; they are inside each other's CIs.
- Ranks of small exporters (Ethena rank 14, Aave 13, Lido 12) have CIs spanning 5 to 6 places.

Verdict: top group ROBUST; full ordering WEAK; Binance as top transmitter REVERSED versus v1 (v1: retail 57.4, Binance 24.5, Coinbase 17.4, `v1_dune/final_results.json: oc_covar_ranking`).

### 5.2 Top-k sensitivity

`topk_sensitivity.json` (main k = 12):

| k | entities | edges | top 5 | Spearman vs main (common entities) | top-3 overlap | top-5 overlap | retail risk |
|--:|--:|--:|---|--:|--:|--:|--:|
| 10 | 13 | 73 | retail, MakerSky, Coinbase, Bitfinex, Binance | 0.989 (n = 13) | 3 | 4 | 33.9 |
| 12 (main) | 15 | 90 | retail, MakerSky, Coinbase, Bitfinex, Kraken | n/a | n/a | n/a | 45.0 |
| 15 | 18 (adds Bitget, Bullish, FalconX) | 123 | retail, MakerSky, Bitfinex, Coinbase, Kraken | 0.979 (n = 15) | 2 | 5 | 61.6 |

(`by_k/<k>/oc_ranking`, `vs_main`.) The whole ordering is stable (Spearman at least 0.979); the exact top three is not (at k = 15 Bitfinex displaces Coinbase). Exported-risk levels scale with entity count (33.9, 45.0, 61.6). Top channel in all three runs: MakerSky to retail (15.6%, 15.2%, 16.4%); at k = 15 the second is retail to Bullish (14.3%). H1 holds at every k. Verdict: ordering ROBUST to the entity cut, top-3 identity WEAK.

### 5.3 Agreement with price-based measures (H3)

| comparison | Spearman | n entities | p | path |
|---|--:|--:|--:|---|
| Hourly OC-CoVaR vs Delta-CoVaR | 0.371 (was 0.257 before the shock-draw change: Aave and Lido swapped order, 3.38 vs 3.37) | 6 (retail, MakerSky, Binance, Aave, Lido, Ethena) | not stored (n = 6: indistinguishable from 0) | `final_results.json: ranking_agreement/spearman_oc_vs_deltacovar` |
| Daily OC-CoVaR vs Delta-CoVaR, `results.json` (H3) | 0.700 | 5 (retail, Lido, Aave, Ethena, Binance); entity-to-asset map Binance-BNB, Aave-AAVE, Lido-stETH, Ethena-USDe, retail-ETH; MakerSky not mapped | 0.188 | `results.json: H3_spearman_oc_vs_deltacovar` (now carries `entity_asset_map`, `comparison`) |
| Daily OC-CoVaR vs Delta-CoVaR, `validation.json` | 0.600 | 6 (retail, Lido, Aave, MakerSky, Ethena, Binance); map as `estimated_graph.ENTITY_ASSET`: Ethena-ENA, MakerSky-DAI | not stored | `validation.json: ranking_agreement` (`entity_asset_map`, `comparison`) |
| OC-CoVaR vs MES | hourly not computed; daily 0.143 (6 entities) | 6 | not stored | `validation.json: ranking_agreement/spearman_oc_vs_mes` |

Versus v1: hourly 0.516 (n = 6). With 6 entities, a Spearman of 0.26 is statistically indistinguishable from 0 and from 0.52; no uncertainty is archived for either. Verdict: WEAK. "The ranking differs from the price-based one" is a point statement; it is not established with a test. The measures also rank different objects (price-based on 9 assets, OC-CoVaR on 15 entities, 6 mapped), so the comparison is an illustration.

The two daily Spearman values are two labelled comparisons, not a contradiction: 0.70 uses 5 entities with Ethena proxied by USDe and no MakerSky; 0.60 uses 6 entities with Ethena proxied by ENA and MakerSky proxied by DAI. Both use the same daily OC-CoVaR ranking from `results.json`. Cite one with its n and proxy map. (`validation.json` was regenerated, so `ranking_agreement` is unchanged at 0.600; its resolution-robustness Spearman changed 0.714 to 0.771 under the circular shock draws, Section 9.1.)

---

## 6. Attribution (H4): channels, shares, explained variance, Shapley

### 6.1 Definition and why it changed

Attribution of channel i to j = L_j(observed) - L_j(do(S_i = pre-crisis)). Share = attribution / L_j(observed). With full abduction, L_j(observed) is the entity's realised hinge loss over the event (shocks abducted from the observed path; replay error 4.4e-16), so it includes the entity's own idiosyncratic shocks (`RERUN_SUMMARY.md` item 6). In v1 the shares were computed on a model-only path with zero shocks, so almost all of the (small) L_obs was spillover by construction.

| quantity | v1 | v3 | path |
|---|--:|--:|---|
| L_obs Bybit | 3.486 | 21.661 | `v1_dune/final_results.json` and `final_results.json: counterfactual_attribution[0]` |
| Binance to Bybit attribution | 3.421 | 1.370 | same |
| Binance to Bybit share of Bybit distress | 0.981 | 0.0633 | same |

The earlier audit (`RERUN_SUMMARY.md` item 7) shows that, on the new data, the legacy zero-shock method gives 70.6% and full abduction 6.7% (v2 initial), so about 27 points of the drop come from the data and about 64 points from the abduction. These two intermediate numbers are not in the final JSON files.

### 6.2 Top channels with uncertainty

`uncertainty.json: attribution/channels` (300 circular-block bootstrap refits, updated after the bootstrap fix; the point shares are unchanged; top 10 selected on the point estimate, so CIs are not selection-adjusted: `attribution/note`):

| channel | attribution | share | 95% CI of share | P(attribution > 0) |
|---|--:|--:|---|--:|
| MakerSky to retail | 2.186 | 15.17% | [12.16%, 18.81%] | 1.000 |
| Kraken to retail | 1.922 | 13.34% | [6.27%, 19.04%] | 0.997 |
| MakerSky to Coinbase | 1.344 | 10.92% | [7.70%, 15.16%] | 1.000 |
| Coinbase to retail | 1.483 | 10.29% | [5.73%, 11.83%] | 1.000 |
| retail to Coinbase | 1.201 | 9.76% | [5.24%, 15.11%] | 1.000 |
| Bitfinex to retail | 1.308 | 9.08% | [2.74%, 15.67%] | 0.993 |
| retail to OKX | 0.862 | 8.10% | [4.00%, 11.23%] | 1.000 |
| Crypto.com to Binance | 1.357 | 7.20% | [1.29%, 12.51%] | 0.993 |
| Kraken to Bitfinex | 0.611 | 6.81% | [-9.15%, 12.43%] | 0.870 |
| Binance to OKX | 0.718 | 6.75% | [0.37%, 11.23%] | 0.990 |
| Binance to Bybit (named) | 1.370 | 6.33% | [2.70%, 8.60%] | 1.000 |
| Ethena to Aave (named) | -0.406 | -1.14% | [-4.07%, 2.28%] | 0.280 |
| Ethena to Binance (named) | 0.078 | 0.41% | [-2.71%, 3.16%] | 0.590 |
| Lido to Aave (named) | -0.012 | -0.034% | [-0.100%, 0.022%] | 0.123 |

Maximum share over all channels: 15.17%, 95% CI [13.16%, 19.53%] (was [12.82%, 20.21%]) (`attribution/max_share`). The same top-5 channels appear at k = 10, 12 and 15 (shares 15.6%, 15.2%, 16.4% for MakerSky to retail).

Sign robustness under small coefficient noise (`revision.json: attribution_sensitivity`): Binance to Bybit share 0.0633, mean 0.0635, sd 0.0065, positive in 100% of draws; Ethena to Aave share -0.0114, sd 0.0017, positive in 0% of draws. The bootstrap is much wider than this noise (Ethena to Aave P(positive) = 0.31).

Flags.
- Fixed: `final_results.json: counterfactual_attribution` used to list only channels whose source is Binance or Ethena, so `FINAL_REPORT.md` said "top channel Binance to Bybit = 6.3%" while the largest channel is MakerSky to retail (15.2%). `run_best.py` now builds the list from the attribution matrix over all 15 sources (all 210 ordered pairs have positive realised target loss), ranked by share, top 10, with `counterfactual_attribution_scope` stating this. Its top 10 equals the `uncertainty.json` top-10 channels (MakerSky to retail 15.17% first), and `FINAL_REPORT.md` now reads "top channel over all sources MakerSky→retail = 15.2%". Binance to Bybit (6.33%) remains in `uncertainty.json` as a named channel.
- Centring: all 14 channel intervals contain their point shares (`share_ci_contains_point`) and bootstrap medians are within 0.7 percentage points of the points for the top 10; the old intervals were also roughly centred, so attribution was not materially affected by the bootstrap-centring problem (the attribution uses the refit coefficients only, not the shock pool).
- The leading channels are CEX or protocol to retail, where retail is the aggregate remainder. The attribution is therefore mostly "named entity to unresolved crowd". Only Binance to Bybit, Crypto.com to Binance, Binance to OKX, and Kraken to Bitfinex are named-to-named among the top 10; the last two include zero in their CI.
- The documented mechanism of the original paper (Ethena to Binance to Aave) is not detected: Ethena to Aave -1.1% [-4.1%, 2.3%], Ethena to Binance +0.4% [-2.7%, 3.2%].

Verdict: top channels (positive, CI above zero) ROBUST in sign and rank 1 to 5, WEAK in magnitude for lower channels; Binance to Bybit 6.3% [2.7%, 8.6%] is a real but small, well-identified channel (CI above zero); 98.1% REVERSED.

### 6.3 How much of event distress does the network explain? (in-sample R-squared)

`uncertainty.json: attribution/r2_in_sample/<entity>/point`:

| entity | R-squared | entity | R-squared | entity | R-squared |
|---|--:|---|--:|---|--:|
| retail | 0.273 | Binance | 0.061 | Aave | 0.014 |
| Kraken | 0.140 | Bitfinex | 0.052 | MakerSky | 0.011 |
| Coinbase | 0.128 | Bybit | 0.048 | Copper | 0.011 |
| Crypto.com | 0.023 | OKX | 0.042 | Ethena | 0.0008 |
| Ceffu | 0.021 | HTX | 0.015 | Lido | 0 (3e-16) |

The structural equations explain at most 27% (retail), 14% (Kraken), 13% (Coinbase) of an entity's hourly stress, and below 6.5% for the other 12 entities. This is why no channel exceeds 15.2%: a share is bounded by the explained fraction of the target's distress. Hourly coefficients are small (maximum stress coefficient 0.282, maximum flow coefficient 0.107; `hourly_scm_export.json: scm_coefficients`, calc).

Diagnosis and fix (updated after the bootstrap fix). The old intervals did not contain any of the 15 point values (retail point 0.273, CI [0.178, 0.251]; Aave 0.014, [-0.106, 0.009]). That was expected optimism, not a bug: each replicate refits the equations on a resample and scored them on the ORIGINAL rows, a partly out-of-sample R-squared that is below the in-sample point by roughly the in-sample optimism (two regressors per parent, 599 design rows). `uncertainty.json: attribution/r2_in_sample` now reports, per entity: `point`; `ci95` = percentile interval of the same in-sample statistic recomputed on each resample (refit on the resample, scored on the resample), which contains all 15 points (`point_in_ci95`); `optimism` = mean over replicates of (R-squared on own resample minus R-squared on original rows), the Efron-Tibshirani optimism; `point_optimism_corrected` = point minus optimism, with its percentile interval `optimism_corrected_ci95`; and the old quantity as `refit_on_original_rows_ci95` (diagnostic only).

| entity | in-sample R-squared (point) | bootstrap 95% interval (refit on own resample) | optimism | optimism-corrected R-squared | 95% interval of corrected |
|---|--:|---|--:|--:|---|
| retail | 0.2733 | [0.241, 0.395] | 0.088 | 0.186 | [0.077, 0.265] |
| Kraken | 0.1397 | [0.087, 0.319] | 0.090 | 0.050 | [-0.157, 0.158] |
| Coinbase | 0.1284 | [0.098, 0.235] | 0.061 | 0.068 | [-0.032, 0.131] |
| Binance | 0.0612 | [0.059, 0.139] | 0.069 | -0.008 | [-0.089, 0.043] |
| Bitfinex | 0.0524 | [0.043, 0.144] | 0.058 | -0.006 | [-0.116, 0.046] |
| Bybit | 0.0477 | [0.032, 0.140] | 0.062 | -0.014 | [-0.109, 0.037] |
| OKX | 0.0417 | [0.030, 0.098] | 0.039 | 0.003 | [-0.049, 0.038] |
| Crypto.com | 0.0235 | [0.018, 0.075] | 0.045 | -0.022 | [-0.078, 0.017] |
| Ceffu | 0.0209 | [0.005, 0.174] | 0.064 | -0.043 | [-0.237, 0.024] |
| HTX | 0.0154 | [0.009, 0.084] | 0.047 | -0.031 | [-0.098, 0.008] |
| Aave | 0.0142 | [0.009, 0.069] | 0.055 | -0.041 | [-0.150, 0.007] |
| Copper | 0.0112 | [0.001, 0.046] | 0.011 | 0.000 | [-0.044, 0.016] |
| MakerSky | 0.0110 | [0.002, 0.040] | 0.010 | 0.001 | [-0.034, 0.015] |
| Ethena | 0.0008 | [0.000, 0.018] | 0.016 | -0.015 | [-0.047, -0.001] |
| Lido | 0.0000 | [0.000, 0.000] | 0.002 | -0.002 | [-0.011, -0.000] |

Reading. The resample-scored interval covers the point but sits above it (the bootstrap world is itself in-sample), so it is not a confidence interval of an out-of-sample skill. After the optimism correction only retail (0.186 [0.077, 0.265]) has an interval clearly above zero; Coinbase (0.068 [-0.032, 0.131]) and Kraken (0.050 [-0.157, 0.158]) do not, and for the other 12 entities the corrected value is within 0.05 of zero or negative. Quote the point values as in-sample, and the optimism-corrected values or the out-of-sample R-squared of Section 6.5 as the honest explained share.

Verdict: low explained share ROBUST (the in-sample point is an upper bound; the corrected and out-of-sample values are lower still).

### 6.4 Shapley decomposition for Bybit

Players: Binance, Coinbase, Bitfinex. Efficiency holds exactly (additive residual 2.2e-16 in `uncertainty.json`, 0.0 in `revision.json`). Total effect 1.2366 = 5.7% of Bybit's L_obs 21.661 (calc).

| player | Shapley value | 95% CI (bootstrap) | share of Bybit L_obs (calc) |
|---|--:|---|--:|
| Binance | 1.488 | [0.528, 2.003] | 6.9% |
| Coinbase | 0.117 | [-0.086, 0.244] | 0.5% |
| Bitfinex | -0.369 | [-0.972, 0.184] | -1.7% |

(`uncertainty.json: attribution/shapley_bybit`; `revision.json: shapley`.) Only Binance's credit has a CI above zero. v1 Shapley, from the earlier audit: 3.41, 0.00, -0.14 (sum 3.28).

Verdict: additivity ROBUST (algorithmic); Binance's positive share ROBUST in sign; Coinbase and Bitfinex WEAK (CIs include zero).

### 6.5 Out-of-sample R-squared and own-lag baseline (new)

Specification (`vein/oos.py`, `run_oos.py`, outputs `oos_r2.json`, `OOS_R2.md`; computed from the cached hourly context, no new queries). For each of the 48 event hours t and each of the 15 entities, every model is refit by ridge (alpha = 1, intercept) on all design rows whose target hour is before t (expanding window from the first fit-window row) and predicts S_(i,t) from stress dated t-1 and flows dated t, as in the SCM; no information from hour t or later is used (tested). Models: `mean` (expanding historical mean, the benchmark); `ar` (own lag only, AR(1), no graph); `network` (the observed-graph SCM equation: parent lagged stress plus parent log1p flows, no own lag; entities without parents fall back to the mean); `ar_network` (own lag plus the network regressors). Out-of-sample R-squared R2_OS(m) = 1 - SSE(m) / SSE(mean) over the event cells; stress is z-scored so SSE pools across entities. Network gain over the own lag = 1 - SSE(m) / SSE(ar). Intervals: circular block bootstrap over event hours (all entities of a drawn hour together), B = 2000, 24-h blocks (2 blocks) and 8-h blocks; they are indicative.

| model | pooled R2_OS | 95% CI (24 h) | 95% CI (8 h) | equal-weight mean over 15 entities |
|---|--:|---|---|--:|
| ar (own lag) | +0.1607 | [+0.056, +0.222] | [+0.045, +0.249] | +0.0815 |
| network (observed graph) | +0.0046 | [-0.017, +0.019] | [-0.025, +0.031] | -0.0034 |
| ar_network | +0.1584 | [+0.045, +0.226] | [+0.031, +0.256] | +0.0767 |

Gain over the own-lag model: network alone -0.186 [-0.271, -0.062] (8 h: [-0.319, -0.051]); own lag plus network -0.0028 [-0.020, +0.014] (8 h: [-0.032, +0.033]).

Reading. Hourly stress is mostly persistence: the own lag alone explains 16% of event-hour squared error pooled (8% equal-weighted), Aave alone carrying 83% of the squared-error reduction (own-lag R2_OS 0.759; calc from `by_entity/sse_mean`). The observed-graph equations, which by construction exclude the own lag, have R2_OS of 0.005 pooled and -0.003 equal-weighted, i.e. no out-of-sample skill over a mean, and are worse than the own-lag model by 19% of its squared error (CI excludes zero). Adding the network to the own lag changes squared error by -0.3% (CI [-2.0%, +1.4%]): the network adds nothing detectable. Per entity (`by_entity`), the only clear gains are retail (R2_OS 0.321 network, +0.296 over the own lag) and Coinbase (+0.116 for ar_network over ar); Bitfinex, HTX, OKX and Kraken are worse with the network. Compare Section 6.3: retail is also the only entity with an in-sample R-squared of 0.27 and a corrected value clearly above zero. A statement the paper can make: "the observed-graph structural equations add at most a small, retail- and Coinbase-specific amount of one-step predictive information over each entity's own lag at hourly resolution; pooled, the gain is -0.3% [-2.0%, +1.4%]". Caveats: one event window (48 hours), two 24-h blocks, one specification of the network equation (no own lag, ridge alpha 1), pooled R2_OS weights entities by benchmark SSE.

Verdict: network explanatory power out of sample WEAK to absent; own-lag baseline now archived.

---

## 7. Placebos

All in `final_results.json: placebo`. The statistic is mean |attribution| over connected ordered pairs, event window 0.2146.

| placebo | result | verdict |
|---|---|---|
| Structural zero (negative control) | 196 connected pairs mean 0.2146; 14 unconnected pairs mean 0.0, max 0.0; passes | Holds by construction (a theorem for the linear SCM; the file note says "holds by construction, not evidence"). The count 196 + 14 = 210 is fixed by graph reachability. Do not present as evidence. |
| Rolling calm-window temporal | event 0.2146 against 20 calm windows (values 0.052 to 0.403); 5 of 20 are at least 0.2146; p = 0.2857; passes: false (`placebo/rolling_temporal`) | Fails: network-attributed distress during the event is not larger than in about a quarter of calm windows. |
| Time-shift | real 0.2146 against 100 shifted refits (0.0996 to 0.1750), all below the real value; p = 1/101 = 0.0099; passes: true (`placebo/time_shift`, B = 100, seed 11) | Passes, but p cannot go below 0.0099 with B = 100. |
| Multi-event rolling placebo | FTX p = 0.1875 (31 windows, fails); SVB p = 0.0323 (30 windows, passes) (`multievent.json: events[*]/placebo_rolling`) | Mixed. |

Interpretation. The two Oct placebos ask different questions. The time-shift test breaks the alignment between each entity's network inputs and its outcome while keeping the marginal series; passing means the realised attribution in the event depends on the actual timing of the network (p = 0.0099, uncorrected). The rolling test asks whether the event is unusual relative to quiet periods; failing means that magnitude of network-attributed distress is not specific to the crisis. Combined: the fitted network carries timing information, but the data do not show that it transmitted more than in comparable calm windows. This cannot support "the network explains the crisis cascade". Three placebo p-values across events with no multiplicity correction (1 of 3 rolling passes). The daily placebo is worse: calm-window mean 0.0921 (max 4.71) against event connected mean 0.0355 (`validation.json: placebo_negative_controls, temporal_placebo`).

Versus v1: v1 had the same structural zero (197 connected, 75 unconnected pairs) and calm-window mean 0.0229, max 0.627, against connected event mean 0.2557 (ratio 0.09). Verdict: structural zero NOT EVIDENCE; rolling WEAK (p = 0.286); time-shift ROBUST at the 1% level; multi-event MIXED.

---

## 8. External validity (Oct-2025 post-mortem)

Documented transmitters {Ethena, Binance} should out-rank absorbers {Aave, Lido}. `final_results.json: external_validity`:

- Exported risk (updated after the bootstrap fix): Binance 22.35, Ethena 0.70; Aave 3.38, Lido 3.37 (before: 22.54, 0.69, 2.94, 3.37). Separation (mean transmitter minus mean absorber) +8.15 (was +8.46); pairwise concordance 0.50 (Binance above both absorbers, Ethena below both).
- `nondegenerate: true`, `vacuous: false` (all four have fit-window std above 1e-9: `nondegenerate_by_entity`). A7 passes.
- Bootstrap (`uncertainty.json: ranking/external_validity`): P(all transmitters above all absorbers) = 0.143 (was 0.123), mean concordance 0.65 (was 0.63).

Reading. The check can now fail and it half-fails: Binance passes, Ethena does not (rank 14 of 15, P(top 5) = 0). It is a non-vacuous but inconclusive test of a small, hand-picked contrast of 4 entities and 4 pairs. Ethena exports almost nothing in the model because its fit-window gross flow is $0.10bn and its fitted parents are weak (coefficients 0.019 and 0.020).

Versus v1: v1 separation 12.87 and concordance 1.00 with absorbers at exactly 0.0 (vacuous: zero stress by construction). Daily: separation -6.01, concordance 0.00 (Aave 5.92, Lido 6.19, Ethena 0.076, Binance 0.0007; `validation.json: external_validity`). Verdict: v1 result was VACUOUS; v3 WEAK / inconclusive (and the daily version fails).

---

## 9. Resolution robustness, confounding, coefficient perturbation, intraday A3

### 9.1 Resolution robustness (Tier-0 seeds-only versus resolved graph)

Hourly: Spearman 0.714, p = 0.111, n = 6 (retail, MakerSky, Binance, Aave, Lido, Ethena) (`final_results.json: resolution_robustness`; was 0.600, p = 0.208 before the shock-draw change, which swapped Aave and Lido). Daily: 0.771, p = 0.072, n = 6 (`validation.json: resolution_robustness`; was 0.714, p = 0.111). The movement of 0.11 and 0.06 from a change in the shock-draw scheme alone shows how little six entities pin the statistic down. v1: 0.806, p = 0.053. Verdict: WEAK (not significant; six entities; the claim "the ranking is not an artefact of the resolution tier" is not established).

### 9.2 Robustness to unobserved confounding (partial R-squared robustness values)

`final_results.json: confounding_sensitivity/edges` (15 edges with the largest t): robustness values range 0.089 to 0.231.

| edge | coef | t | RV |
|---|--:|--:|--:|
| MakerSky to retail | 0.277 | 8.11 | 0.231 |
| retail to Coinbase | 0.216 | 6.80 | 0.198 |
| Bitfinex to retail | 0.137 | 5.83 | 0.173 |
| Bitfinex to Coinbase | 0.118 | 4.87 | 0.146 |
| Kraken to retail | 0.129 | 4.19 | 0.127 |
| Binance to Bybit | 0.144 | 4.16 | 0.126 |
| retail to Aave (15th) | 0.102 | 2.88 | 0.089 |

A hidden confounder would need partial R-squared of 0.09 to 0.23 with both endpoints to nullify these edges. These are moderate values, not large (an hourly common market shock could plausibly explain this much).

Revision 3 (`revision3.json`): dropping the 22 of 90 edges with lowest RV gives Spearman 0.989 against the base ranking, top-5 retail, MakerSky, Binance, Coinbase, Bitfinex, top-3 overlap 0.667. A latent common shock of strength 0.3 gives Spearman 0.986, strength 0.6 gives 0.904; top-3 overlap 0.667 in both. The top-5 identities reshuffle (Coinbase, Binance, Kraken swap), the overall order does not. Verdict: ordering ROBUST; top-3 identity WEAK.

### 9.3 Coefficient perturbation (revision2)

`revision2.json: ranking_stability`: 25 perturbations of a deterministic proxy ranking: mean Spearman 0.964, min 0.911, mean top-3 overlap 0.787. Caveat: the proxy's base top 5 is retail, HTX, Aave, Bybit, OKX, which is not the reported ranking. Use the bootstrap in Section 5 instead (Spearman vs point 0.903 [0.793, 0.968]).

### 9.4 Intraday A3

Section 4: true 1.8022, reversed 1.8036, symmetric 1.8097 on 216 fit hours and 48 event hours, 720 predictions; relative gap true vs reversed 0.078%. `intraday_a3.json` now also stores the paired circular-block bootstrap: reversed minus true +0.0066 [-0.0035, +0.0166] (inconclusive), symmetric minus true +0.0127 [+0.0003, +0.0250] (borderline above zero), and the verdict is computed from these numbers by `classify_a3` (supported only if the RMSE gap exceeds 2% and the paired CI is above zero; contradicted symmetrically; otherwise `NO_DIFFERENCE_DETECTED`). It is `NO_DIFFERENCE_DETECTED` (was `TIE_DIRECTION_UNINFORMATIVE`). `INTRADAY_A3.md` no longer contains the template sentences "dataset/power artifact, now resolved" and "connectivity, not direction, carries the signal"; it lists the numbers and says the test does not explain why the daily result differed. The connectivity statement is addressed with data in Section 6.5: the network adds nothing detectable over the own lag.

---

## 10. Analytic checks (daily specification only)

Source: `analytics.json` and `ANALYTICS.md` (computed on `results.json`, daily, 7 event days, 15 entities). Hourly coefficients are archived (`hourly_scm_export.json`) but the analytics have not been run on them.

- Spectral radius of the daily coefficient matrix: 0.569 (`analytics.json: spectral_radius`). (v1 0.276.) Hourly lag-1 stress coefficient matrix from `hourly_scm_export.json`: spectral radius 0.433 (calc, not archived), 90 non-zero entries.
- Flow-free bounds (Prop A): 0 violations, 5 entities with zero bound and zero stored risk (HTX, Bitfinex, Kraken, Coinbase, OKX; these have all-zero coefficients in the daily SCM, so the check is vacuous for them) (`n_violations: 0`, `n_zero_predicted: 5`). Examples: retail stored E 7.92 vs bound per unit s* 4.41 (implied minimum s* 1.80); Lido 6.19 vs 3.15 (1.96); Aave 5.92 vs 3.91 (1.51); MakerSky 1.28 vs 1.78 (0.72); Ethena 0.0762 vs 0.243 (0.31); Copper 0.0021 vs 0.365 (0.0058). All "bounded". The check says the bound is consistent whenever s* exceeds the implied minimum; it is a consistency check, not an empirical test.
- Shapley: closed-form walks versus exact subset enumeration max absolute difference 4.44e-16; subsets versus permutations (p at most 7) 4.72e-16; efficiency residual at most 1.67e-16 (synthetic deviation path, seed 7). Exact subset Shapley for retail with p = 13 (8,192 evaluations) takes 0.235 s (machine-dependent). Evaluation counts: 2^p subsets versus p! x p permutations, for example p = 10: 1,024 versus 36,288,000; p = 13: 8,192 versus 80,951,270,400. Verdict: ROBUST (algorithmic).
- Certified ranking radius (daily Lambda ranking: retail, Aave, Lido, MakerSky, Copper): certified eps* retail over Aave 0.0475, Aave over Lido 0.0643, Lido over MakerSky 0.134, MakerSky over Copper 0.305; none certified at eps = 1. Verdict: ROBUST as a method result; shows the daily ranking is certified only for small coefficient perturbation.

---

## 11. Backtests (price-only, not part of the OC-CoVaR evidence)

`final_results.json: backtests` (hourly, n = 886): BTC 59 failures (6.66% against 5%), Kupiec LR 4.67, p = 0.031, Christoffersen independence p = 0.049, conditional coverage p = 0.014; ETH 55 failures (6.21%), Kupiec p = 0.111, independence p = 0.065, conditional coverage p = 0.051. Daily (`results.json: backtests`, n = 810): BTC 48 failures (5.93%), Kupiec p = 0.239, conditional coverage p = 0.106; ETH 44 failures (5.43%), Kupiec p = 0.578, independence p = 0.0003, conditional coverage p = 0.0013. Identical to v1. Verdict: hourly BTC VaR rejected at 5%; ETH borderline; these concern the price baselines, so they do not support or weaken VEIN.

---

## 12. v1 versus v3 summary

| item | v1 (Dune, legacy) | v3 (final) | verdict |
|---|---|---|---|
| entities / edges | 17 / 39 | 15 / 90 | changed |
| named-to-named coverage | about 1% of $438bn | about 3.0% panel tokens; 2.8% of $569.7bn | changed |
| H1 | observed 1.2529 vs Granger 1.2568, supported | 1.5545 vs 1.5595, not supported (sign depends on estimand) | REVERSED |
| H2 / A3 (hourly) | true 1.663, reversed 1.675 (0.71%) | true 1.784, reversed 1.787 (0.17%), paired CI includes 0; intraday no difference; FTX, SVB inconclusive | WEAKER |
| Binance to Bybit share | 98.1% | 6.33% [3.59%, 8.93%] | REVERSED |
| max channel share | n/a | 15.17% [13.16%, 19.53%] (MakerSky to retail) | new |
| top transmitters | retail, Binance, Coinbase | retail, MakerSky, then Bitfinex/Coinbase (unresolved); Binance 7th | REVERSED |
| Spearman vs Delta-CoVaR (hourly) | 0.516 | 0.371 (was 0.257; n = 6, not distinguishable from 0) | WEAK |
| external validity | separation 12.87, concordance 1.0 (vacuous) | separation 8.15 (was 8.46), concordance 0.5, non-vacuous | v1 vacuous; v3 inconclusive |
| resolution robustness | 0.806 (p 0.053) | 0.714 (p 0.111; was 0.600, p 0.208) | WEAKER |
| placebo (rolling) | not formal | p = 0.286 (fails); time-shift p = 0.0099 | mixed |
| hourly spectral radius | n/a | 0.433 (calc); daily 0.569 (v1 daily 0.276) | informational |

---

## 13. Oddities, contradictions and stale files (check before citing)

1. (Resolved, updated after bootstrap fix.) Bootstrap intervals not centred on their point estimates: H1 partial correlation (mean -0.00308, old CI [-0.01768, -0.00539]); falsification symmetric minus true (mean 0.00289, old CI [0.00425, 0.00793]); all 15 in-sample R-squared intervals. Cause of the first two: the plain moving-block bootstrap draws block starts from the n - L + 1 admissible positions, so with 48 event steps and 24-h blocks the middle steps carry up to 24 times the weight of the end steps; the replicate mean of the symmetric-minus-true difference was 0.0063 against a sample mean of 0.0029 (circular blocks: 0.0029). Fix: `risk.moving_block_indices(..., circular=True)` is now the default everywhere (paired error bootstraps, coefficient bootstrap rows, Monte Carlo shock rows); the plain version stays available as `circular=False`. New intervals: H1 partial correlation [-0.01514, +0.00942] (inconclusive), symmetric minus true [-0.00159, +0.00752] (inconclusive); `boot_mean` and `ci_contains_mean` are stored. Cause of the third: expected in-sample optimism, not a bug (Section 6.3); the intervals are now percentile intervals of the in-sample statistic on each resample plus an optimism-corrected value, and out-of-sample R-squared is in Section 6.5. A related defect was found in the coefficient bootstrap: each replicate's shock pool was the refit's residuals over ALL original rows, which includes rows the refit had not seen; exported-risk bootstrap medians were above the points (MakerSky 42.7 vs 37.9). Replicate pools are now residuals of the drawn rows; medians match the points. Attribution intervals were already roughly centred and are unchanged in substance. `s*` is still held fixed across replicates (its sampling error is not in any interval).
2. (Resolved.) `final_results.json: counterfactual_attribution` was restricted to Binance and Ethena sources, so "top channel Binance to Bybit" in `FINAL_REPORT.md` was not the largest channel. It now covers all 15 sources (top 10 by share; first entry MakerSky to retail 15.17%), the same list as `uncertainty.json`, and the report says so.
3. (Resolved.) `validation.json` carried a hard-coded `generated: 2026-06-30` (`run_validation.py`). It now uses the run date (2026-10-12). `VALIDATION.md` is the rendered version of the daily battery.
4. (Resolved.) `DATA_BUILD.md` had a stale status line ("labels stage only") and stale protocol seed counts (Aave 2 and MakerSky 1 against 10 and 6 in the current seed definitions; base table 3471 rows fingerprint 5d2705754343, now 3484 rows 9a306b377e0e). `python run_build_data.py --render` rebuilds it offline (no BigQuery query) from `data_build.json` and the cached label report: the status line and the Pending list now follow the stages present in `data_build.json`, a stage-results section was added, and the seed counts in `data_build.json: labels` and `data_cache/labels_report.json` were refreshed. `data_cache/labels_base.csv.gz` was deliberately not rewritten (it feeds cached query keys). The label epochs used by the extracts (e2025, eftx, esvb fingerprints in `data_build.json`) were built by `ensure_labels` with current seeds and are unaffected.
5. `RERUN_COMPARISON.md` flags 6 numbers as MANUSCRIPT_STALE (entities 17 to 15, edges 39 to 90, Spearman 0.52 to 0.371, and the three falsification RMSEs). Its entity section now labels two sets: the daily set (`results.json: entity_types`; FalconX in, Crypto.com out) and the hourly set (`final_results.json: oc_covar_ranking`; Crypto.com in, FalconX out, Gate.io and Bullish out), instead of one unlabelled list. Its path matching is unreliable for list-indexed numbers (`RERUN_SUMMARY.md` section 4). `RERUN_SUMMARY.md` describes the v2 initial run (100 edges, 17 entities) and is superseded for any number.
6. (Labelled.) Two daily Spearman values vs Delta-CoVaR: 0.70 (5 entities, `results.json: H3_spearman_oc_vs_deltacovar`, Ethena proxied by USDe, no MakerSky) and 0.60 (6 entities, `validation.json: ranking_agreement`, Ethena proxied by ENA, MakerSky by DAI). Same daily OC-CoVaR ranking, different entity sets and proxy assets; each record now stores `entity_asset_map`, `n_entities` and `comparison`, and `VALIDATION.md` explains the difference. (`results.json` was patched additively; `run_evaluation.py` writes the same fields on its next run.)
7. The OC-CoVaR vs MES comparison exists only for the daily run (0.143); no hourly MES Spearman was produced.
8. (Resolved.) `INTRADAY_A3.md` contained template verdict text ("dataset/power artifact now resolved"; "connectivity, not direction, carries the signal") beyond the numbers. The verdict is now chosen by `classify_a3` from the RMSE gap and a paired bootstrap CI, and the text lists those numbers only (Section 9.4).
9. FTX Tier-0 validation: 13 overlapping detections (acceptance rule requires 20).
10. Time-shift placebo uses B = 100, so p has a floor of 0.0099. Bootstrap rank probabilities have resolution 1/300.
11. The daily SCM has all-zero coefficients for five entities (HTX, Bitfinex, Kraken, Coinbase, OKX), so the daily OC-CoVaR ranking (retail 7.92, Lido 6.19, Aave 5.92) is a different, degenerate object; do not mix daily and hourly rankings.
12. Exported-risk levels scale with entity count (retail 33.9 / 45.0 / 61.6 for k = 10 / 12 / 15); only ranks are comparable.
13. (Resolved.) An own-lag (no-graph) baseline and out-of-sample R-squared are now archived (`oos_r2.json`, `OOS_R2.md`, Section 6.5). The daily `results.json`, `revision*.json`, `topk_sensitivity.json` and `analytics.json` were regenerated on 2026-10-12 after the circular-bootstrap fix and use the current shock-draw scheme; the robustness checks in them are point comparisons without intervals.
14. Hourly Lido has no incoming edges and one outgoing edge (to Aave), and no flow stress; its exported risk (3.37) flows entirely through that documented edge.
15. Checked for NaN and Infinity: none (A9 passes). `fit_gross_usd` Lido 0.0 is expected.

---

## 14. What the paper can claim

Methods claims (all supported by archived algorithm checks).
- A causal SCM over entity-resolved on-chain flows, with the distress measure OC-CoVaR (exported risk) defined by do-interventions, is computable at hourly resolution on 15 nodes and 90 edges: 2000-simulation point estimates with MC s.e. 0.017 to 0.436, bootstrap uncertainty over 300 joint circular-block refits.
- Exact Shapley decomposition of a target's counterfactual loss is additive to machine precision (residual at most 2.2e-16) and closed-form walks equal subset enumeration to 4.4e-16; exact subset evaluation with p = 13 costs 8,192 evaluations and 0.235 s, against 8.1e10 for permutations.
- Flow-free bounds are never violated on the daily specification (0 violations; 5 zero-bound entities are vacuous); the certified ranking radius is small (0.0475 to 0.305; none certified at eps = 1).
- Full abduction reproduces the observed path exactly (replay error 4.4e-16) and changes the attribution reading: v1's 98.1% Binance to Bybit share was an artefact of zero-shock abduction; with realised shocks the share is 6.33% [3.59%, 8.93%].
- The structural-zero property (no attribution without an on-chain path) holds by construction; it is a property of the method, not evidence.
- Tier-0 deposit-sweep detection has precision 1.000 on 423 (Oct), 31 (SVB) and 64 (daily) holdout detections (Wilson lower bounds 0.991, 0.890, 0.943; 13 for FTX, lower bound 0.77), but recall by volume is below 4.4%.

Empirical claims (application to Oct 2025 and two earlier events; descriptive).
- Named-to-named flow is about 3.0% of entity-touching flow in the Oct panel-token extract (0.55% to 3.0% across extracts); the observed graph consists mostly of named-entity to "retail" (unresolved) edges.
- The network structural equations explain little of hourly stress: in-sample R-squared at most 0.273 (retail), 0.140 (Kraken), 0.128 (Coinbase), below 0.065 for the other 12 entities; optimism-corrected 0.186 (retail), 0.068 (Coinbase), 0.050 (Kraken) and about zero or below for the rest; out-of-sample one-step R-squared of the network equations +0.005 pooled against an own-lag AR(1) at +0.161, and the network adds -0.3% [-2.0%, +1.4%] to the own lag. Consequently the largest channel share is 15.17% [13.16%, 19.53%] (MakerSky to retail), and no channel explains more than about 20% (upper CI) of any entity's realised event distress.
- Binance to Bybit is a positive, well-identified but small channel: 6.33% of Bybit's distress, share CI [2.70%, 8.60%], P(positive) = 1.000; Shapley credit for Bybit: Binance 1.488 [0.528, 2.003].
- Among entities, retail and MakerSky are the top two exporters of tail risk (P(top 3) = 0.983 and 0.880; rank CIs [1, 3] and [1, 5]); the third place is unresolved (Bitfinex P(top 3) = 0.243, Coinbase 0.340). The bottom group (Ethena, Ceffu, Aave, Lido, Copper) is never in the top five. The ordering is stable to the entity cut (Spearman 0.979 to 0.989 across k = 10, 12, 15) and to dropping 22 low-robustness edges (0.989).
- The observed on-chain graph does not predict hourly stress better than a price-estimated graph: weighted RMSE 1.5545 vs 1.5595 (Granger) and 1.5599 (partial correlation), differences at most 0.35%; the unweighted paired bootstrap is inconclusive against both estimated graphs (partial correlation [-0.0151, +0.0094], Granger [-0.0129, +0.0021]), the weighted one is inconclusive against Granger and borderline favourable to the observed graph against partial correlation (lower bound +0.0003); H1 is not supported.
- Edge direction is not shown to matter at the entity-aggregate level: no difference detected at intraday resolution (true 1.8022 vs reversed 1.8036, paired CI [-0.0035, +0.0166]), inconclusive in FTX and SVB, and 0.17% better for the true direction in Oct main with a paired CI that includes zero ([-0.0006, +0.0093], 2 effective blocks).
- Rolling-window placebo does not distinguish the event from calm periods (p = 0.286 Oct, 0.1875 FTX; SVB 0.032); the time-shift placebo does (p = 0.0099).
- The hourly external-validity check is non-vacuous and gives mixed results: concordance 0.50, separation +8.15, P(all transmitters above all absorbers) = 0.143.
- The retail aggregate is both the top exporter and the destination of the leading channels: without it the ranking is Binance 17.9, Crypto.com 15.6, Kraken 14.9, Coinbase 11.4, OKX 10.1, Bitfinex 9.9 (unresolved by the bootstrap).

---

## 15. What the paper must not claim

- Do not claim that the observed on-chain graph beats estimated graphs (H1), or that "VEIN outperforms price-based causal baselines". Status is not supported; an own-lag baseline now exists (Section 6.5) and the network adds nothing detectable to it.
- Do not claim that flow direction is causally informative (A3/H2) as a general finding. No difference is detected intraday, it is inconclusive in FTX and SVB, and Oct main is a 0.17% effect whose paired CI includes zero.
- Do not report "98.1% of Bybit's distress from Binance" or any share above about 15%; do not say a single channel "explains" the cascade.
- Do not name Binance as the top systemic transmitter (7th, rank CI [2, 9]); do not claim an ordering among ranks 4 to 8, or that retail outranks MakerSky (P = 0.800), or an order between Bitfinex and Coinbase for third place.
- Do not present MakerSky's rank 2 as institution-specific: it runs through the retail aggregate and it drops out of the top six without retail. It rests on 6 seed addresses.
- Do not claim the model recovers the documented Oct-2025 mechanism (Ethena to Binance to Aave): Ethena ranks 14th, Ethena to Aave -1.1% [-4.1%, 2.3%], Ethena to Binance +0.4% [-2.7%, 3.2%].
- Do not cite the structural-zero placebo as evidence of validity; do not claim the placebos "pass" overall (rolling fails in Oct and FTX).
- Do not claim the OC-CoVaR ranking "diverges significantly" from Delta-CoVaR or MES (Spearman 0.371, n = 6; no hourly MES comparison; the two daily values, 0.70 on 5 and 0.60 on 6 entities, use different entity sets and proxy assets).
- Do not claim the ranking is robust to label resolution (Spearman 0.714, p = 0.111, n = 6).
- Do not claim external validity (concordance 0.50) or reuse the v1 value (separation 12.87, concordance 1.00; vacuous).
- Do not claim Tier-0 detections are validated for Coinbase, Bybit or Kraken (holdout is Binance and Bitget deposit labels), nor that the graph covers most flow (named-to-named is about 3% of entity-touching flow; volume recall below 4.4%).
- Do not report the daily FTX or SVB results (underpowered), the daily falsification as a causal finding (n = 105, five all-zero entities), or the non-flow-target tests (shared target series).
- Do not describe the R-squared bootstrap intervals as confidence intervals of out-of-sample skill (they are intervals of the in-sample statistic and sit above the point); quote the optimism-corrected or out-of-sample values. Do not quote the pre-fix intervals (symmetric-vs-true "observed_better", H1 "estimated_better"): they came from the edge-weighted moving-block bootstrap.
- Do not compare exported-risk levels across runs or entity sets (scale with entity count), and do not mix the daily and hourly rankings.
- Do not describe the DeFi nodes (Aave, Ethena, MakerSky, Lido) as measured purely from on-chain flows: their stress includes price-based components (drawdown, peg, stETH discount), and Lido has no flow.
- Do not quote the rolling-statistic and time-shift p-values as a family-wise result without correction (three events, two placebos).
- Do not cite the removed template wording of `INTRADAY_A3.md` ("dataset/power artifact now resolved") as a finding; the file now lists numbers only. The H4 line in `FINAL_REPORT.md` now reports the top channel over all sources (MakerSky to retail).
