# Rerun summary: Dune (v1) versus BigQuery (v2) results

Scope. Old values are in `results/v1_dune/`, new values in `results/*.json`. Every new number below was read directly from the JSON files. Items marked "(rebuilt)" were also reproduced offline from the cached BigQuery rows in `data_cache/` (no query issued). The rebuild matched the archived results exactly: 100 edges, 17 entities, H1 RMSE 1.1647 / 1.1822 / 1.1653, and the same top-10 attribution list. `results/RERUN_COMPARISON.md` is not used for any list-indexed number, because its path matching is unreliable (see Bug suspicions, item 1).

Verdict labels: survives, weakened, reversed, strengthened (relative to the manuscript statement).

## 1. Sanity audit: bug or data/method?

No evidence of a pipeline bug was found in the rerun. The large changes trace to two causes: (a) the method change to full abduction, and (b) new labels and sweep-detected deposit addresses that change the entity set and graph density. Several weaknesses that predate the rerun were also found. They matter for how the results are read.

1. Entity set and edges (39 to 100).
   - The 39 edges came from Dune labels. The new run has 96 observed-flow edges plus 4 documented edges (confidence 1.0 for 70, 0.5 for 26 retail-touching, 0.7 for 4).
   - Retail has 13 in-edges and 13 out-edges. The denser graph is expected: Kraken is added, Tier-0 sweeps attach many deposit addresses to named hot wallets, and the `min_usd` threshold is US$0.1M cumulative.
   - Bitget dropped out only because of the top-k cut. It is rank 13 by flow ($5.3bn) against Bullish rank 12 ($6.1bn), and `top_k_entities(k=12)` at `run_best.py:78` cuts there. Gate.io is rank 29 by flow, because the new labels do not reproduce its former Dune footprint. The manuscript node list (Gate.io, Bitget) is stale.
2. H1 edge counts 8/14/10 identical to before: expected, not suspicious (rebuilt).
   - The 6 comparison nodes are Aave, Binance, Ethena, Lido, MakerSky and retail.
   - The 8 observed edges are 4 flow edges (Binance<->retail $49.9bn/$59.4bn, Ethena<->retail $0.066bn/$0.065bn) plus the 4 hard-coded `DOCUMENTED_EDGES` (`vein/config.py:122`).
   - Granger (14) and partial-correlation (10) graphs come from prices, which are the same cached hourly panel. The counts are structural.
   - Consequence: Aave, Lido and MakerSky have no flow edges. Their stress is identically 0 in the hourly panel (mean, std, min and max all 0; rebuilt). Half of the 288 H1 predictions (3 of 6 nodes) are trivially 0 with 0 error. H1 is effectively a three-node test (Binance, Ethena, retail). This was also true in v1.
3. Volumes plausible (rebuilt from cached rows).
   - Hourly window pair-level flow touching a named entity is $472.9bn. This is consistent with the old $438bn, and revision.json gives $449.7bn after the top-k and same-entity drops.
   - Token totals: USDC $275bn, USDT $367bn, USDe $35bn, wBETH $1.7bn.
   - Coinbase<->retail is about $85bn each way over the 41-day window. Named-to-named flow is only $7.3bn (1.63% of $449.7bn).
   - The largest single named-to-named item is three round HTX to Bitfinex USDT transfers ($1.0bn, $1.0bn, $1.2bn, one in the fit window, one on 9 Oct). They dominate that edge but are real transfers.
   - Daily core extract: Coinbase<->retail is $43.1bn/$42.8bn (EVALUATION.md), against $43.5bn/$43.4bn in the manuscript. This is a good cross-source consistency check.
   - USDe daily volume matches the manuscript exactly: $0.745bn on 9 Oct, $3.09bn on 10 Oct, $8.83bn on 11 Oct (cached `usde_daily_bq`).
4. WETH/ETH price conversion.
   - WETH is not in the hourly `TOKENS` list. Only wBETH is ETH-priced, and it is 0.4% of flow.
   - The ETH series for Sep 14 to Oct 25 has 32 daily points for 42 days (gaps are forward-filled, `bq_flows._eth_lookup`). This is harmless at that weight.
   - In the FTX and SVB extracts entity-touching WETH is only 3.5k and 4.5k WETH (under $10M). WETH is irrelevant to the flow panel.
   - It matters only for COVERAGE.md: WETH is $2.48tn of the $5.44tn Oct total, which dilutes every coverage percentage there.
   - Coverage definitions differ. COVERAGE.md "both resolved" 3.95% includes same-entity deposit-to-hot-wallet transfers and WETH. The manuscript metric is "directly between two named (distinct) entities", which is now 1.63%. The two should not be compared.
5. Stress states (rebuilt).
   - Per-entity stress mean is about 0 and std about 0.7. No NaNs in any results JSON.
   - Event-window stress is moderate (mean 0.1 to 0.3 for the leaders). Maxima reach 6 for several exchanges.
   - Event-window flows are elevated: Binance to Bybit is $2.98M per hour in the event against $0.10M per hour in the fit window (30x). Coinbase<->retail rises about 20%.
6. Full abduction reproduces observed paths (rebuilt).
   - Replay of the observed event path through `event_residuals` gives a max absolute error of 4.4e-16. Per-entity replayed hinge loss equals observed hinge loss exactly (for example Bybit 21.661, Binance 18.860, Kraken 18.002). This is the intended identity.
   - Event-window shock std (0.55 to 1.03) is comparable to fit-window residual std (0.64 to 0.95). The event is not dominated by a few outsized shocks.
7. Why Binance to Bybit fell from 98.1% to 6.7%: method, not a bug (rebuilt).
   - Same new data, legacy zero-shock abduction: Binance to Bybit is 70.6% of Bybit's distress (L_obs 4.14), Bitfinex 43.5%, OKX 41.6%, Kraken 45.8%.
   - Full abduction, same data: Bybit's L_obs is 21.66 (the realised hinge loss), and the share is 6.7%. Bitfinex is -0.6%, OKX 7.8%, Kraken 3.2%.
   - Legacy mode computed the shares on the model-only path, where the shocks were zero, so almost all distress was spillover by construction. Full abduction puts the real idiosyncratic shocks in L_obs.
   - The structural equations explain little of hourly stress. In-sample R-squared is 0.3% to 22% (retail 22%, Coinbase 18%, Kraken 14%, Bybit 5%, Ethena 0.3%). Any channel share is therefore bounded to single digits. The max share over all 272 ordered pairs is 15.8%, the min is -4.2%, and 28 pairs are negative.
   - The data change alone moves the legacy share from 98% to 71%.
8. Does retail dominate? Yes, as before.
   - OC-CoVaR exported risk: retail 101.1, Coinbase 44.0, Kraken 37.0, Binance 35.8, Bitfinex 34.1 (old: retail 57.4, Binance 24.5, Coinbase 17.3, Bitfinex 11.4).
   - Retail is the hub for 26 of the 100 edges. It is "everything not yet resolved".
   - Exported risk is a sum over targets, so it scales with entity count. Magnitudes (101 versus 57) are not comparable across runs. Ranks are.
   - The ordering of ranks 2 to 5 (44.0, 37.0, 35.8, 34.1) rests on 150 Monte-Carlo draws of a 95% quantile and is not statistically resolved. No Monte-Carlo standard error is reported.
9. Placebo and temporal placebo.
   - The negative-control placebo still passes (max unconnected attribution 0). It is a theorem for the linear SCM. The pair counts 197 connected and 75 unconnected are identical in v1 and v2 and in the daily run. They are fixed by three isolated nodes: Aave, Lido and MakerSky. The count 16+16+15+14+14 = 75 is reproduced exactly. Not a bug, but the placebo carries no information about the data.
   - Hourly temporal placebo: calm-window mean 0.055, max 0.89 (old 0.023 and 0.63). The ratio to the event-window connected mean is 0.22 (old 0.09). Cleaner than not, but weaker.
   - Daily temporal placebo is worse: calm-window mean 0.032, max 5.11, against an event-window connected mean of only 0.0146. Calm attribution is larger than event attribution (old 0.0127 and max 1.65 against 0.0104). That placebo does not pass in spirit.
10. Multi-event sample sizes unchanged: pre-event days 7 (FTX) and 9 (SVB), 4 event days each, 44 and 48 one-step predictions (11 and 12 entities). The 6 to 8 residual rows are fitted with ridge alpha 1, and the block bootstrap uses `BLOCK_LEN = 5` (`run_multievent.py:28`) on those rows, so very few distinct block starts exist.
11. External validity. Hourly separation 12.87 to 19.68, concordance 1.00. But s* is 0 for Aave, Lido and MakerSky (stress identically 0), so their exported risk is 0 by construction. The "absorbers below transmitters" check cannot fail on the hourly panel. Treat it as vacuous.
12. H4 channel shares for Binance to Bybit: see item 7. Entity-set dilution is not the cause.

## 2. Claim-by-claim comparison

### Data and resolution

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Entity universe | 17 (incl. Gate.io, Bitget) | 17 (Kraken added, Gate.io and Bitget removed) | changed | top-k cut and label change; update node list |
| Graph edges (hourly) | 39 | 100 (96 flow + 4 documented) | changed | denser labels and sweeps |
| Daily graph edges | 35 | 60 | changed | same cause |
| Coinbase<->retail (daily core) | $43.5bn / $43.4bn | $43.1bn / $42.8bn | survives | cross-source match |
| USDe daily volume (9, 10, 11 Oct) | 0.74 / 3.09 / 8.83 $bn | identical | survives | exact match |
| Named-to-named share of window flow | about 1% of $438bn | 1.63% of $449.7bn | survives (slightly higher) | revision.json; COVERAGE.md 3.95% uses a broader definition |
| Tier-1 ROC-AUC | 0.98 | 0.89 | weakened | n 7019, 41 CEX-labelled addresses (10 roots) |
| Tier-1 average precision | 0.24 | 0.17 | weakened | |
| Tier-1 best-F1 precision / recall | 0.27 / 0.33 | 0.13 / 0.58 | changed | |
| Tier-1 volume-weighted recall / precision | 0.001 / 0.21 | 0.152 / 0.92 | reversed (recall no longer negligible) | ground-truth set now deposit-dominated and counted per root; not strictly comparable |

### H1 (observed versus estimated graph)

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Hourly RMSE: observed / Granger / partial-corr | 1.2529 / 1.2568 / 1.2547 | 1.1647 / 1.1822 / 1.1653 | strengthened vs Granger; tie vs partial-corr | margin vs Granger 1.5% (old 0.3%); vs partial-corr 0.05% |
| Bootstrap CI (observed minus Granger, mean weighted error) | 0.003, [-0.012, 0.016] (i.i.d.) | 0.0147, [-0.0053, 0.0518] (paired moving-block, 8h) | survives (still includes zero) | bootstrap method changed |
| Share of resamples observed better | 71% | 91.5% | strengthened | not significant |
| Strictly lagged flows | observed 1.258 vs Granger 1.247 | 1.1641 vs 1.1780 | reversed in sign (observed now slightly better) | |
| Non-flow target (H1) | Granger 1.36 vs observed 1.68 | 1.359 vs 1.684 | survives | target unchanged by construction |
| Daily H1 | observed 1.92, Granger 1.35, pc 1.65 | 2.66, 2.37, 2.43 | survives (estimated graph still wins) | gap narrower; n 42 |
| Status "not established" | | | survives | the auto text in FINAL_REPORT.md says "H1 SUPPORTED" on a 0.0006 gap (`run_best.py:253`); keep the manuscript wording |

### H2 / falsification (edge reversal)

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Hourly consolidated (true / reversed / symmetric) | 1.663 / 1.675 / 1.667 (true best) | 1.7246 / 1.7037 / 1.7164 (reversed best by 1.2%) | reversed | true direction is now worst |
| Hourly, 216 fit hours | 1.801 / 1.790 / 1.797 | 1.8405 / 1.8229 / 1.8479 | survives | reversed best, symmetric worst |
| Daily | 2.19 / 1.92 / 1.94 | 2.43 / 2.24 / 2.25 | survives | reversed best |
| Non-flow target | 1.025 / 1.129 / 0.942 | 1.030 / 1.132 / 0.946 | survives | nearly identical, see note below |
| Edge-type split | reverse custodial 1.675 vs true 1.663; 35 custodial, 4 composability | reverse custodial 1.7037 vs true 1.7246; 96 custodial, 4 composability | reversed | reversing custodial edges now improves fit; "directional signal sits on custodial edges" no longer holds |

Note on the non-flow target (`run_revision2.py:37`): every exchange and custodian uses the same ETH drawdown series as its target, so the nodes are identical series and the result barely depends on the graph. This test is nearly uninformative.

### Multi-event

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| FTX top transmitters | Binance, Coinbase, Crypto.com | retail, FTX, Binance (Coinbase 4th) | weakened | FTX is now a labelled node (24 addresses) |
| FTX true / reversed / symmetric | 1.455 / 1.543 / 1.476 (true best) | 1.707 / 1.402 / 1.803 (reversed best by 18%, symmetric worst) | reversed | "direction informative in FTX" no longer holds |
| SVB top transmitters | retail, Bybit, Binance, OKX | retail, OKX, Kraken, Coinbase | weakened | |
| SVB true / reversed / symmetric | 1.567 / 1.610 / 1.564 | 1.294 / 1.296 / 1.284 | survives (symmetric marginally best) | spread under 1% |
| Sample sizes | 44 and 48; 7 and 9 pre days | same | survives | |
| Reliability | | | unreliable | 6 to 8 fit rows; the 18% FTX swing is within what such a fit can produce |

### H3 (ranking versus Delta-CoVaR / MES)

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Hourly Spearman vs Delta-CoVaR (6 entities) | 0.516 | 0.516 | survives (identical) | the OC side has only 3 distinct values (retail > Binance > Ethena > three tied zeros); identical by tie structure, not by chance |
| Hourly top transmitters | retail, Binance, Coinbase, Bitfinex | retail, Coinbase, Kraken, Binance, Bitfinex | weakened | Binance drops from 2nd to 4th; update text |
| Daily Spearman vs Delta-CoVaR / MES | 0.72 / 0.52 | 0.72 / 0.52 | survives | |
| Daily top exported risk | Lido 4.06 | Lido 11.46 | survives (still the absorber problem) | |
| Daily external validity | separation -1.97, concordance 0.50 | -5.71, 0.50 | survives (check still fails daily) | |
| Hourly external validity | separation 12.87, concordance 1.00 | 19.68, 1.00 | survives, but vacuous | see audit item 11 |
| Delta-CoVaR / MES baseline values | | identical | survives | price-only |

### H4 / attribution channels

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Binance to Bybit share of Bybit distress | 98.1% | 6.7% | reversed (headline) | method change, see audit item 7; still the top channel by absolute attribution (1.45) |
| Binance to Gate.io / Bitfinex | 58.4% / 45.3% | Gate.io not in the entity set; Bitfinex about -0.6% | reversed / not testable | |
| Largest shares in new run | | Binance to OKX 7.8%, Bullish 7.8%, Bybit 6.7%, Coinbase 6.2%, retail 6.0% | | no channel above 15.8% |
| Sensitivity (15% coefficient noise, 40 draws) | 0.98 +/- 0.01, all positive | 0.066 +/- 0.005, all positive | survives (sign robust) | |
| Order-robust Shapley for Bybit (Binance, Coinbase, Bitfinex) | 3.41, 0.00, -0.14; sum 3.28 | 1.355, 0.066, -0.399; sum 1.022; residual 0 | survives (additivity holds) | Bitfinex negative credit is larger |
| Daily leading channel | Ethena to Aave 11.3% | Ethena to Aave 0.2% (abs 0.033) | weakened to about zero | |
| Status "supported, descriptive" | | | weakened | decomposition is exact but explains only 3% to 8% of realised distress per channel |

### Robustness checks

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Deterministic-proxy ranking stability (15% noise, 25 draws) | 0.88 mean, 0.66 min, top-3 overlap 0.79 | 0.989 mean, 0.970 min, overlap 0.92 | strengthened | the proxy's base top 5 changed (retail, OKX, Coinbase, Bybit, HTX); still a proxy, not the reported ranking |
| Drop low-RV edges | Spearman 0.94, top 3 identical | 0.993, top-3 overlap 0.67 (25 of 100 edges dropped) | strengthened by Spearman, weakened by top-3 identity | Coinbase, Kraken and Binance are within noise of each other |
| Latent common shock (moderate / strong) | 0.84 / 0.81, top 3 unchanged | 0.94 / 0.96, top-3 overlap 0.67 | strengthened by Spearman | |
| RV, retail to Coinbase | 0.226 | 0.232 | survives | Coinbase to retail 0.175 to 0.182 |
| No-retail ranking | Binance 16.0, FalconX 2.4, Ethena 2.1 | Binance 21.3, Kraken 21.0, Crypto.com 19.1 (Coinbase 16.7) | weakened | Binance is top only by a margin of 0.3 |

### Analytic bounds and propositions (daily specification)

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Spectral radius | 0.276 | 0.244 | survives | |
| Bound violations | 0 | 0 | survives | 9 zero-bound entities in both |
| Largest implied minimum s* (Lido) | 2.97 | 3.03 | survives | stored E 4.06 to 11.46 |
| Certified top-5 | Bitget, Copper, Lido, Bybit, Ethena | Lido, Copper, Bybit, retail, Ethena | changed | radii 0.256, 0.333, 0.076, 0.058; none certified at epsilon 1 (survives) |
| Walk versus subset agreement | 5.6e-17 | 8e-17 (ANALYTICS.md) | survives | |
| Subset enumeration timing (retail, p=13) | 0.19 s | 0.20 s | survives | |
| "Hourly coefficients not archived" | | `hourly_scm_export.json` now exists (215 KB) | statement stale | the analytic checks could now be run on the hourly SCM; from the rebuilt hourly SCM the spectral radius is 0.536 |

### Resolution robustness, backtests, coverage

| Claim | Old | New | Verdict | Note |
|---|---|---|---|---|
| Hourly Tier-0 versus Tier-3 Spearman | 0.806 (p 0.053) | 0.806 (p 0.053) | survives (identical) | 6 entities with ties; the same tie structure as H3 |
| Daily Tier-0 versus Tier-3 | 0.82 (p 0.044) | 0.94 (p 0.005) | strengthened | |
| VaR backtests (hourly, daily) | Kupiec BTC 0.03, ETH 0.11; daily 0.24 / 0.58 | identical | survives | price-only, unaffected |
| Christoffersen (daily ETH) | 0.001 | 0.001 | survives | |
| Resolution recall | about 1% | 1.63% | survives | |

## 3. Results flagged unreliable

1. **Hourly external validity (separation 19.68, concordance 1.00).** Vacuous: absorber entities have identically zero stress and s* = 0, so exported risk is 0 by construction.
2. **H1 and the H3/resolution Spearman values.** Half of the H1 predictions are trivial zeros. The 0.516 and 0.806 Spearman values are fixed by ties among three zero-valued entities and do not respond to data changes.
3. **Placebo pair counts and the negative-control pass.** A theorem plus graph structure, not evidence about the data.
4. **FTX and SVB results** (7 and 9 fit days, ridge on 6 to 8 rows). The reversed-versus-true swing in FTX (18%) should not be read as evidence about direction.
5. **Non-flow-target falsification.** All exchange nodes share one target series.
6. **Rank order among Coinbase, Kraken, Binance and Bitfinex** (150 draws, no Monte-Carlo error bars).
7. **Daily temporal placebo** (calm attribution exceeds event attribution).
8. **RERUN_COMPARISON.md and manuscript_numbers.csv** for any list-indexed number (see below).
9. **Tier-1/2 validation** versus old: the label set and the "distinct exchanges" count (`vein/resolver.py:203`, now roots) changed, and the set is deposit-dominated, whose behaviour resembles the sweep rule.

## 4. Bug suspicions (evidence)

1. **`run_compare.py:73-120` (`_leaves`, `match_numbers`): wrong or misaligned comparisons.**
   - Numbers are matched to JSON leaves by value, and the path is stored with positional list indices. 120 of 203 matches are ambiguous (`manuscript_numbers.csv`).
   - Evidence: N0004 and N0005 map to `results.json graph.edges[24][2]` and `[9][2]`, which are different edges in the new graph, hence the false "$43.5bn to $0.09bn" drop. N0011 (0.88, the stability figure) is mapped to `multievent.json events[1].oc_ranking[4]`. N0008, N0012, N0030 and N0035 map to unrelated `analytics.json bounds[...]` leaves. N0009 maps to the first attribution entry, which is a different channel after the rerun. All "rank change" flags on list-indexed items are spurious. The correct comparisons are in section 2.
   - Not a pipeline bug, but the comparison file should not be cited.
2. **`run_best.py:54-70` (`build_hourly_stress`) with `vein/config.py` seeds: zero-stress nodes.** Aave, Lido and MakerSky have 0 to 2 seed addresses and no labelled flow, so stress is identically 0, s* = 0 and exported risk = 0. This also makes H1 half-trivial. It predates the rerun (v1 shows the same zeros).
3. **`run_best.py:253` (`write_report`): wording.** "H1 SUPPORTED, observed on-chain graph wins" is printed for an RMSE gap of 0.0006 against partial-correlation (the boolean is `rmse < best_est`). It conflicts with the manuscript's "not established".
4. **`run_best.py:78` top-k cut at k=12.** Entity membership is threshold-sensitive (Bitget is 13th, $0.8bn below Bullish). Not wrong, but it changes the comparison universe between runs.
5. **`run_multievent.py:28` `BLOCK_LEN = 5` on 6 to 8 residual rows.** The "moving-block" bootstrap has only 2 to 4 distinct block starts.
6. **Comments and log labels still say Dune** (`run_best.py:76` "(Dune)", `run_best.py:210` "Needs the Dune data"). Cosmetic. The manuscript data section also still describes Dune.
7. **Coverage definition mismatch** (`vein/bq_sql.py` `coverage_sql`, `is_mint_burn` at about line 137; no same-entity exclusion): COVERAGE.md "both resolved" includes same-entity sweep transfers and WETH volume, so it cannot be compared with the manuscript's "directly between two named entities".

Items checked and found clean: NaN/Infinity scan of every results JSON, factual replay (4.4e-16), per-entity L_obs equals observed hinge loss, price-based outputs (Delta-CoVaR, MES, backtests, Granger and partial-correlation graphs) identical to v1 as expected from the unchanged price cache, H1 and the attribution list reproduced exactly from cached rows.

## 5. What to change in the manuscript text (list, no edits made)

- Replace 98% Binance to Bybit and Gate.io/Bitfinex shares with the full-abduction values, and state that the structural equations explain 0.3% to 22% of hourly stress variance, so no single channel exceeds 16% of an entity's distress.
- Update the hourly ranking text (retail, Coinbase, Kraken, Binance, Bitfinex), Table 3 and the node list (Kraken in, Gate.io and Bitget out).
- Hourly falsification: true direction is now not best, and the custodial-edge directional signal disappears. FTX: reversed is best. The abstract sentence "reversing edges degrades prediction in FTX and USDC/SVB" no longer holds in FTX and is a tie in SVB.
- H1 text: new numbers, block-bootstrap interval [-0.005, +0.052], 91.5% of resamples.
- Coverage: 1.6% of $450bn. Tier-1 validation numbers. Methods paragraphs that say legacy abduction, independent resampling and full-sample s* (Appendix A) are now outdated. Data sources (Dune) need updating to BigQuery plus open labels.
