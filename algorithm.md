# VEIN: On-Chain Causal Risk Attribution for Cryptocurrency Systemic Risk
### Research Design Document — Algorithm, Dataset, Evaluation, and Expected Results

**Target venue:** The Journal of Risk Finance (Emerald)
**Status:** Pre-writing research design — author's own analysis (not for direct AI-generated submission text per JRF's GenAI policy)
**Last updated:** June 2026

---

## 1. Research Question and Positioning

### 1.1 The Gap

Existing causal systemic-risk literature for crypto markets (Causal-NECO VaR, Rigana, Wit & Cook 2024; TV-DIG, Etesami, Habibnia & Kiyavash 2023; CoRisk, Giudici & Parisi) infers the causal/contagion graph *statistically* from price returns using PC-algorithm-style structure learning or directed-information estimation. None of these methods use the **observed blockchain transaction network** as the causal graph itself. Separately, no published work has constructed a **counterfactual (Pearl Level-3)** risk measure for systemic crypto contagion; all existing causal risk measures (Causal-NECO VaR, TV-DIG) operate at most at Pearl Level 2 (interventional).

### 1.2 The Core Contribution

We propose **VEIN** (Verifiable Entity-resolved Interventional/counterfactual Network risk), a framework that:

1. Treats the **resolved on-chain transaction graph** as the structural backbone of a Structural Causal Model (SCM) — the causal parent-set of each entity is *read off the ledger*, not statistically inferred from price correlations.
2. Defines an **interventional risk measure** (On-Chain Causal CoVaR) via the do-operator applied to this SCM.
3. Defines a **counterfactual attribution measure** that decomposes a realized loss into the portion attributable to a specific upstream entity's distress, holding everything else as it actually occurred.
4. Validates against the **October 2025 cascading liquidation event**, the **2026 DeFi exploit wave**, and the **Oct 2025–Jun 2026 bear-market regime**, rather than the now heavily-mined 2022 Terra/FTX episodes.

### 1.3 Hypotheses to Verify

| ID | Hypothesis |
|----|------------|
| **H1** | The on-chain flow-based causal graph predicts which entities transmit vs. absorb stress more accurately than a correlation-based or Granger-based graph estimated from price returns alone. |
| **H2** | Reversing the direction of on-chain flow edges (sender↔receiver) significantly degrades predictive accuracy for the timing and magnitude of distress propagation — i.e., flow direction carries genuine causal information, not just accounting symmetry. |
| **H3** | On-Chain Causal CoVaR identifies a different (and more interpretable) set of systemically important entities than standard ΔCoVaR/MES/SRISK applied to price returns, particularly for the Oct 2025 event, where CEX/DeFi architecture — not price correlation — explains differential fragility. |
| **H4** | The counterfactual attribution measure can correctly decompose realized losses in the Oct 2025 event into "oracle-mispricing-attributable" vs. "pre-existing leverage-attributable" components, consistent with the documented mechanical narrative of that event. |
| **H5** | Entities connected by *observed on-chain collateral/composability edges* (e.g., protocols sharing liquidity pools) show measurably higher counterfactual loss attribution to one another than entities with no on-chain edge but similar price correlation — demonstrating that the graph contributes information beyond what price data alone provides. |

---

## 2. Algorithm

### 2.1 Scope Decision

**Primary chain:** Ethereum + major DeFi protocols (Aave, Kamino-equivalent lending markets, Ethena/USDe, Binance-related on-chain wallets where traceable) — because the validation events (Oct 2025 liquidation cascade, 2026 DeFi exploits) are predominantly DeFi/CeFi-hybrid events.
**Robustness chain:** Bitcoin UTXO graph — included as a sanity check because its strict DAG structure (inputs strictly precede outputs in time) minimizes confounding and lets us verify the estimation pipeline behaves correctly in a near-ideal causal setting before trusting it on the noisier Ethereum/DeFi graph.

### 2.2 Entity Resolution Pipeline

Raw addresses are not economic agents. The pipeline collapses millions of addresses into a smaller set of meaningful nodes. **This step is the single largest source of risk to the entire framework**, because — unlike in typical blockchain-forensics use cases — entity-resolution error here does not just mislabel a node; it directly corrupts $pa(i)$, the causal parent-set itself (Section 2.3). A noisy graph silently becomes a noisy causal model with no separate error term to absorb the mistake. The classical multi-input/co-spend heuristic and deposit-sweep pattern matching, while standard in the forensics literature, are known to be weak on their own: they systematically **underestimate** a user's true address set when peeling-chain or fork-merge obfuscation patterns are present, and produce false merges in the opposite direction when independent users coincidentally combine inputs. Relying on heuristics alone is therefore a methodological weak point worth strengthening before the causal layer is built on top of it.

**Tiered approach — heuristics as a baseline, ML/GNN-based resolution as the primary method:**

```
Tier 0 — Classical heuristic baseline (for comparison only, not primary pipeline)
  - Multi-input/co-spend clustering (Bitcoin)
  - Deposit-address sweep pattern detection (exchanges mint unique
    per-user deposit addresses that periodically sweep to a hot wallet)
  - Known to underestimate true clusters under peeling-chain/fork-merge
    obfuscation; retained only as a baseline to quantify the improvement
    from Tier 1–2 methods, and as a sanity check when ML methods disagree
    sharply with the simple heuristic

Tier 1 — Supervised change-address / same-entity classification
  - Train a supervised classifier (gradient-boosted trees or a small
    feed-forward net) on transaction-level features (output structure,
    value patterns, script type, address-reuse behavior) to detect
    change outputs and same-entity transaction pairs, following the
    supervised-classification approach demonstrated on Bitcoin
    (Tubino, Robardet & Cazabet 2022; Möser & Narayanan 2022) and on
    Ethereum blacklist/address classification (Kılıç et al. 2022)
  - Requires a small labeled seed set (known exchange/protocol addresses,
    self-disclosed wallets, prior forensics datasets) to bootstrap training

Tier 2 — Graph representation learning / GNN-based entity resolution
  - Learn node embeddings over the transaction graph (e.g., GCN/GAT-style
    architectures, in the spirit of the Elliptic benchmark dataset
    methodology) capturing multi-hop structural and temporal patterns
    that simple heuristics cannot see (e.g., layered fund-splitting
    across many hops designed specifically to defeat co-spend clustering)
  - Cluster embeddings (e.g., density-based clustering on the learned
    representation space) rather than relying on a single hand-crafted
    rule
  - Multi-resolution clustering (cf. BitScope-style approaches, Zhang,
    Zhou & Xie) to scale this across the full Jan 2024–Jun 2026 window
    without losing entity-level precision

Tier 3 — Known-label seeding and reconciliation
  - Etherscan public label cloud + exchange-disclosed hot wallet addresses
    + commercial attribution data where accessible (e.g., Nansen, Elliptic,
    Chainalysis-style labels), used both as Tier 1/2 training signal and
    as a held-out reconciliation set to estimate residual entity-resolution
    error empirically, not just assume it away
  - Smart contract bytecode/ABI matching → protocol identity (deterministic,
    not heuristic — contract addresses are unambiguous given verified source)
  - Residual unlabeled addresses aggregated into a single "retail/unknown"
    node to avoid spurious node-level noise

Output
  Entity graph G = (V, E), with an explicit per-edge/per-node confidence
  score propagated from the Tier 1–2 classifiers — NOT a binary "resolved/
  unresolved" graph. This confidence score is carried forward into the
  structural causal model (Section 2.3) as a weight on edge reliability,
  and into the falsification test (Section 2.6) as a covariate, so that
  entity-resolution uncertainty is visible in downstream results rather
  than silently absorbed.
  V = {centralized exchanges, DeFi protocols, stablecoin issuers,
       large/whale wallet clusters, aggregate retail node}
  E = directed, timestamped, dollar-volume-weighted edges, each with an
      associated resolution-confidence score
```

Open-source tooling (GraphSense, BlockSci) and existing labeled benchmark datasets (the Elliptic dataset for methodology validation, public Etherscan/Dune label exports) are used as building blocks rather than training entity-resolution models entirely from scratch — the ML/GNN entity-resolution layer is treated as **necessary supporting infrastructure that must be validated**, not as a from-scratch contribution of the paper. Its validation (Tier 3 reconciliation) should itself be reported as a robustness statistic (e.g., estimated precision/recall against held-out known labels) rather than asserted.

**Why this matters more here than in typical forensics applications.** In standard blockchain-forensics or AML work, entity-resolution errors mostly affect *attribution* (whose address is this) and are tolerated because the downstream task (flagging suspicious activity) is robust to some noise. In VEIN, an entity-resolution error can silently **fabricate or sever a causal edge** in $pa(i)$, which then propagates through both the interventional (Section 2.5) and counterfactual (Section 2.5) computations. This is why Tier 1–2 methods, confidence-weighted edges, and the Tier 3 reconciliation check are treated as required components of the core method rather than optional refinements.

### 2.3 Structural Causal Model

For each resolved entity $i$ at time $t$, define a stress state $S_{i,t}$ (e.g., net outflow ratio, collateral health ratio, liquidity buffer depletion — operationalized per entity type in Section 3.3). The structural equation is:

$$
S_{i,t} = f_i\Big(S_{pa(i),\,t-1},\; F_{pa(i)\rightarrow i,\,t},\; U_{i,t}\Big)
$$

- $pa(i)$ — causal parents of $i$, defined as entities with an **observed on-chain flow edge into** $i$ in the resolved transaction graph. This is the key structural move: $pa(i)$ is read from the ledger, not statistically estimated via PC-algorithm or directed information.
- $F_{pa(i)\rightarrow i,t}$ — actual observed on-chain flow volume from each parent at time $t$.
- $U_{i,t}$ — exogenous idiosyncratic shock / unmodeled noise for entity $i$.
- $f_i$ — an entity-specific stress-propagation function, estimated from historical data (Section 2.5); this is the *only* component requiring statistical estimation in this framework.

### 2.4 Identifying Assumptions

| Assumption | Statement | Justification |
|---|---|---|
| **A1 — Temporal precedence** | $F_{i\rightarrow j,t}$ strictly precedes any effect on $j$ at $t' > t$. | Given for free by blockchain immutability and timestamping — does not need to be assumed or tested, unlike Granger-style precedence on price series. |
| **A2 — No unobserved common cause for flow edges** | Conditional on the full transaction graph up to $t$, edge $i \rightarrow j$ reflects $i$'s direct economic action on $j$. | Defensible because a public ledger captures *every* fund movement in the flow mechanism itself — unlike price-based causal discovery, where the underlying data-generating process is never fully observed. |
| **A3 — Monotonic propagation along flow direction** | Distress at $i$ can causally affect $j$ only through realized flow paths from $i$ to $j$ (directly or via intermediate nodes). | This is the substantive, falsifiable causal claim of the paper — tested directly via H2 (edge-reversal falsification test, Section 2.6). |

A1–A2 are structural properties of the data source itself, which is the principal identification advantage over price-based causal discovery (where both the graph *and* the structural equations must be estimated, compounding error). A3 is the assumption that does the empirical work and is the one we explicitly test for falsifiability, not merely assume.

### 2.5 Risk Measures

**Interventional — On-Chain Causal CoVaR (Pearl Level 2):**

$$
\text{OC-CoVaR}_q\big(j \mid \text{do}(S_i = s^{*})\big) = \text{VaR}_q\Big(L_j \mid \text{do}(S_i = s^{*})\Big)
$$

Computed by forcing $S_i = s^{*}$ (severing $i$'s own causal parents per the do-operator), then propagating forward through the structural equations $f_k$ along observed flow paths to obtain the resulting loss distribution for $j$.

**Counterfactual — Attribution (Pearl Level 3):**

$$
\Delta_i^{CF} = L_j^{\text{observed}} - L_j^{\,\text{do}(S_i = S_i^{\text{pre-crisis}})}
$$

Computed via the standard three-step counterfactual procedure:
1. **Abduction** — infer the realized exogenous shocks $U_{i,t}$ from observed data given the fitted structural equations.
2. **Action** — replace entity $i$'s structural equation with the counterfactual value $S_i^{\text{pre-crisis}}$, holding all $U_{k,t}$ ($k \neq i$) fixed at their abduced values.
3. **Prediction** — recompute downstream entity states using the modified model to obtain $L_j^{\,\text{do}(S_i = S_i^{\text{pre-crisis}})}$.

$\Delta_i^{CF}$ answers: *"How much of $j$'s realized loss would not have occurred had $i$ never become distressed, holding everything else exactly as it actually unfolded?"*

### 2.6 Falsification / Robustness Test for A3

To empirically support (not merely assume) that flow direction carries causal information:

```
Reversed-edge model: construct G_reversed by flipping every edge direction
  (recipients treated as causal parents of senders)

Compare predictive accuracy of:
  - True-direction VEIN model
  - Reversed-edge VEIN model
  - A symmetric (undirected/correlation-based) baseline

Metric: timing and magnitude accuracy of predicted distress propagation
        during the Oct 2025 cascading liquidation event (Section 4)
```

If the true-direction model outperforms the reversed and symmetric variants at predicting the actual sequence and severity of contagion, this constitutes empirical evidence for A3, addressing the most likely reviewer objection ("a flow edge isn't necessarily a causal edge").

### 2.7 Algorithm Summary (Pseudocode)

```
INPUT: raw on-chain transaction logs (Ethereum + Bitcoin), price/return data,
       entity label sources, event window definitions

1. Entity resolution
   G = resolve_entities(raw_transactions, labels)         # Section 2.2

2. Structural equation estimation
   for each entity i in G:
       f_i = fit_stress_propagation(
           parents = pa(i, G),
           historical_flows = F[pa(i) -> i],
           historical_stress = S_history[i]
       )                                                    # Section 2.3

3. Interventional risk computation
   for each (i, j, s*) of interest:
       OC_CoVaR[j | do(S_i = s*)] = propagate_forward(G, {f_k}, do(S_i = s*))

4. Counterfactual attribution
   for each (i, j, crisis_window) of interest:
       U_hat = abduct(G, {f_k}, observed_data, crisis_window)
       L_j_cf = predict_forward(G, {f_k}, U_hat, do(S_i = S_i_precrisis))
       Delta_i_CF[j] = L_j_observed - L_j_cf

5. Falsification test
   G_reversed = reverse_edges(G)
   compare_predictive_accuracy(G, G_reversed, baseline_correlation_graph)

OUTPUT: OC-CoVaR rankings, counterfactual attribution decompositions,
        falsification test results
```

---

## 3. Dataset

### 3.1 Data Sources (all downloadable)

| Layer | Source | Access | Granularity |
|---|---|---|---|
| Raw transactions (ETH + BTC) | Google BigQuery public datasets (`bigquery-public-data.crypto_ethereum`, `crypto_bitcoin`) | SQL, free tier | Block-level, every transaction since genesis |
| ERC-20 token transfers | Same BigQuery dataset, `token_transfers` table | SQL | Every transfer event |
| DeFi protocol events (swaps, liquidations, deposits) | Dune Analytics (community + spellbook queries) | SQL via API/export | Protocol-specific event logs |
| Entity/exchange labels | Etherscan public label cloud; open heuristic tooling (GraphSense, BlockSci) | API/scrape + clustering | Address → entity mapping |
| Stablecoin reserve attestations | Circle (USDC) and Ethena (USDe) transparency disclosures | Manual/scraped | Daily/weekly |
| Oracle feed data (for the Oct 2025 event specifically) | On-chain oracle contract logs (Binance internal feed reconstruction where traceable; Chainlink/other external oracle logs for comparison) | On-chain logs + exchange disclosures | Per-update, sub-minute around the event window |
| Market price/return data | CoinGecko API, Binance API | REST API | 1-minute to daily |

### 3.2 Asset / Entity Universe

- **Centralized layer:** Binance and other major exchange hot wallets (to the extent traceable on-chain), with explicit acknowledgment that internal CEX order-book/liquidation-engine mechanics are *not* on-chain and must be reconstructed from public disclosures and post-mortems where possible.
- **DeFi layer:** Aave, Kamino-equivalent lending markets, Ethena/USDe issuance and redemption contracts, plus composability-linked protocols holding USDe/wBETH/bnSOL as collateral.
- **2026 exploit layer:** Kelp DAO and other protocols affected in the Jan–June 2026 DeFi exploit wave, selected based on documented composability links to the primary entity set.
- **Aggregate retail node:** all unresolved addresses, included to avoid attributing systemic importance to noise.

### 3.3 Stress State Operationalization

| Entity type | Stress state $S_{i,t}$ proxy |
|---|---|
| CEX | Net on-chain outflow ratio (withdrawals net of deposits, normalized by historical reserve estimate) |
| Lending protocol (Aave, Kamino-equivalent) | Collateralization ratio decline / utilization rate spike / bad-debt flag |
| Stablecoin issuer (Ethena) | Peg deviation (observed market price vs. $1) and redemption queue depth |
| Whale wallet cluster | Realized loss on holdings + net liquidation flow |

### 3.4 Time Windows

| Window | Span | Purpose |
|---|---|---|
| Estimation/training window | Jan 2024 – Sep 2025 | Fit structural equations $f_i$ under "normal" regime conditions |
| Primary event window | Oct 8 – Oct 14, 2025 | Oct 10–11 cascading liquidation — minute-level resolution |
| Secondary event window(s) | Jan – Jun 2026 | 2026 DeFi exploit wave — per-incident windows around each major exploit (e.g., Kelp DAO, April 2026) |
| Regime/background window | Oct 2025 – Jun 2026 | Sustained bear-market deleveraging — weekly resolution for sequential validation |
| Historical out-of-sample benchmark (optional) | 2022 (Terra/Luna, FTX) | Comparison only, to show consistency with prior literature (ASRI, TV-DIG already validate here) — not a primary contribution |

---

## 4. Evaluation Plan

### 4.1 Benchmarks

| Benchmark | Source | Role |
|---|---|---|
| ΔCoVaR | Adrian & Brunnermeier (2016) | Standard non-causal systemic risk measure |
| MES / SRISK | Acharya et al. (2017) | Marginal expected shortfall family |
| Diebold–Yilmaz connectedness | Diebold & Yilmaz | Variance-decomposition-based spillover network |
| ASRI | Farzulla & Maksakov (2026) | Crypto-specific composite systemic risk index |
| Causal-NECO VaR (re-implemented on our data, if feasible) | Rigana, Wit & Cook (2024) | Nearest causal-VaR precedent, using PC-algorithm-estimated graph instead of on-chain graph — direct test of H1 |
| TV-DIG-style directed network (re-implemented, if feasible) | Etesami, Habibnia & Kiyavash (2023) | Nearest causal crypto-systemic-risk precedent |

### 4.2 Evaluation Metrics

**For interventional/standard risk-measure validity (statistical backtesting):**
- Kupiec unconditional coverage test
- Christoffersen conditional coverage test
- Dynamic quantile (DQ) test

**For H1 (on-chain graph vs. estimated graph predictive accuracy):**
- Precision/recall of predicted "transmitter" vs. "absorber" entity classification against documented post-mortem accounts of the Oct 2025 event and the 2026 exploit wave
- Lead-time accuracy: does OC-CoVaR flag elevated risk for downstream entities *before* their distress is reflected in price, compared to price-based benchmarks?

**For H2 (falsification test):**
- Comparative predictive accuracy (timing + magnitude of propagation) of true-direction vs. reversed-edge vs. symmetric/undirected graph models (Section 2.6)

**For H3 (systemic importance ranking divergence):**
- Rank correlation (Spearman) between OC-CoVaR-based entity rankings and ΔCoVaR/MES/ASRI rankings
- Qualitative case comparison: Aave/Kamino (transparent on-chain collateral, zero bad debt) vs. CEX risk engines (opaque, oracle-driven cascade) during the same Oct 2025 shock — does OC-CoVaR correctly rank DeFi protocols as lower systemic-transmission risk despite similar price-correlation exposure?

**For H4 (counterfactual attribution validity):**
- Decompose the Oct 2025 USDe depeg loss into oracle-mispricing-attributable vs. pre-existing-leverage-attributable components; compare the decomposition against the documented mechanical account (Binance internal pricing system using its own order book rather than external oracles → mispricing → automated liquidations) as an external validity check
- Sensitivity analysis: does the attribution decomposition remain stable under reasonable perturbations of the abduced exogenous shocks $U_{i,t}$?

**For H5 (graph edges add information beyond price correlation):**
- Controlled comparison: among entity pairs with similar price-return correlation, do pairs with an observed on-chain composability/collateral edge show significantly higher counterfactual loss attribution than pairs without such an edge?
- Regression of counterfactual attribution magnitude on (a) price correlation, (b) presence/absence of on-chain edge, (c) edge weight — testing whether (b)/(c) retain significant explanatory power after controlling for (a)

### 4.3 Robustness Checks

- Bitcoin UTXO robustness check: verify the estimation pipeline recovers sensible, low-noise structural equations in the near-ideal DAG setting before trusting Ethereum/DeFi results
- Sensitivity to entity-resolution clustering choices: explicitly compare Tier 0 (heuristic) vs. Tier 1–2 (ML/GNN) entity graphs and check whether OC-CoVaR rankings and counterfactual attributions are stable across them; report the estimated precision/recall of the Tier 1–2 pipeline against the Tier 3 held-out label set (Section 2.2) as a standalone robustness statistic, not just a qualitative caveat
- Out-of-sample check against 2022 Terra/FTX events for consistency with prior literature (not primary validation, see Section 3.4)
- Alternative stress-state operationalizations (Section 3.3) to confirm results are not artifacts of a single proxy choice

---

## 5. Expected Results (to verify hypotheses)

| Hypothesis | Expected result if VEIN's core claim holds | What would falsify it |
|---|---|---|
| **H1** | On-chain-graph-based OC-CoVaR achieves higher precision/recall in classifying transmitter vs. absorber entities, and earlier lead-time flagging of downstream distress, than Causal-NECO VaR / TV-DIG re-implementations using price-estimated graphs. | If the on-chain graph performs no better (or worse) than price-estimated graphs, the central "observed graph beats estimated graph" claim fails, and the paper's contribution narrows to a methodological variant rather than a genuine improvement. |
| **H2** | True-direction model outperforms reversed-edge and symmetric/undirected models in predicting the actual timing and severity of the Oct 2025 cascade (e.g., correctly predicting that DeFi-collateral-linked protocols absorbed stress later and less severely than CEX-linked entities). | If reversed-edge or undirected models perform comparably, assumption A3 lacks empirical support, and flow-direction-as-causal-direction would need to be substantially qualified or abandoned. |
| **H3** | OC-CoVaR ranks Aave/Kamino-type protocols as lower systemic-transmission risk and CEX risk-engine-linked entities as higher, diverging from price-correlation-based rankings (ΔCoVaR/MES), which we expect to rank purely by price co-movement and miss the architectural distinction documented in the Oct 2025 post-mortems (zero bad debt in DeFi vs. CEX chaos). | If OC-CoVaR rankings closely track ΔCoVaR/MES rankings with no meaningful divergence, the on-chain causal structure adds no discriminating power over price data, weakening the practical case for the method. |
| **H4** | The counterfactual decomposition attributes a dominant share of the USDe-related loss magnitude to the oracle-mispricing intervention rather than pre-existing leverage, consistent with the documented account that USDe remained fully solvent and the depeg was a pricing/liquidity-mechanism artifact rather than a fundamental insolvency. | If the decomposition instead attributes most loss to pre-existing leverage with little oracle-specific contribution, this would contradict the documented mechanical narrative and suggest either misspecification of $f_i$ or that the counterfactual identification assumptions do not hold for this event. |
| **H5** | Entity pairs with an observed on-chain composability/collateral edge show significantly higher counterfactual attribution than equally-correlated pairs without such an edge, and edge presence/weight remains significant after controlling for price correlation in the regression. | If on-chain edge presence adds no significant explanatory power once price correlation is controlled for, this undermines the paper's central claim that the transaction graph carries causal information beyond what is already available in price data. |

### 5.1 Anticipated Contribution Statement (pending empirical confirmation above)

Assuming H1–H3 hold and H2 provides adequate falsification support, the paper's contribution is: the first systemic risk framework to use an *observed* (not statistically inferred) causal graph for crypto contagion, yielding measurably better transmitter/absorber identification and finer-grained, mechanically-grounded counterfactual loss attribution than existing price-based causal risk measures — validated on the largest deleveraging event in crypto history (Oct 2025) rather than the now-saturated 2022 case studies.

If H4–H5 hold as well, the paper additionally establishes the first empirically validated counterfactual (Pearl Level-3) systemic risk measure in finance, with direct regulatory relevance for stress-test attribution and protocol-level composability risk assessment.

### 5.2 Honest Risk Assessment

The most likely points of failure, to monitor during empirical work:

1. **CEX opacity.** A substantial share of the Oct 2025 event's causal mechanism (Binance's internal pricing engine) is *not* on-chain by construction. The on-chain graph can only capture the downstream consequences (liquidation transactions), not the proximate cause (the internal oracle decision). This must be explicitly scoped in the paper — VEIN models *on-chain-observable* contagion channels, and CEX-internal mechanisms are treated as exogenous shocks $U_{i,t}$ rather than structurally modeled. This is a real limitation, not just a caveat.
2. **Entity resolution error propagating into the causal graph.** Since $pa(i)$ is read directly from resolved entities, clustering errors directly corrupt the causal structure (unlike price-based methods, where structure-learning error and data error are at least separable). The Tier 0–3 pipeline (Section 2.2) is designed specifically to mitigate this — using supervised classifiers and graph representation learning rather than heuristics alone, and carrying a confidence score on every edge — but residual risk remains, particularly for newly-deployed 2026-era protocols and addresses with limited label history. The robustness check in Section 4.3 is essential, not optional, and results should be reported alongside the measured precision/recall of the entity-resolution layer itself.
3. **A3 may hold only partially.** It is plausible that flow direction is causally informative for some channels (e.g., collateral/composability) but not others (e.g., simple custodial transfers). The paper should be prepared to report a *qualified* version of A3, restricted to specific edge types, if the falsification test in Section 2.6 produces mixed results.

---

## 6. Next Steps

1. Confirm BigQuery + Dune access and run a small-scale pilot entity resolution on a 2-week window around Oct 10–11, 2025, comparing Tier 0 (heuristic) against Tier 1–2 (supervised classifier / GNN embedding) outputs on a held-out labeled subset before committing to the full estimation window — if Tier 1–2 does not measurably outperform Tier 0 on this pilot, the entity-resolution design needs revisiting before any causal modeling proceeds.
2. Attempt re-implementation of Causal-NECO VaR and TV-DIG on the same entity set as direct benchmarks (Section 4.1) — this is necessary for H1 to be testable at all.
3. Draft the identification section (Section 2.4) in full formal notation before any empirical work, since A1–A3 are the section most likely to draw reviewer scrutiny.
4. Revisit this document once the Jan–Jun 2026 DeFi exploit wave data is more fully indexed by Dune/Etherscan label sets (some very recent incidents may have incomplete public labeling as of mid-2026).
