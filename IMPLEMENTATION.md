# VEIN — Reference Implementation

A runnable implementation of the VEIN framework described in [`algorithm.md`](algorithm.md),
evaluated on **real Ethereum mainnet data**. It treats the observed on-chain
transaction graph as the structural backbone of a Structural Causal Model (SCM),
then computes interventional (OC-CoVaR) and counterfactual (Pearl Level-3)
systemic-risk measures.

## What is real here

| Layer | Source | Keyless? | Used for |
|---|---|---|---|
| Inter-entity flows | **Dune Analytics** SQL over decoded `erc20_ethereum.evt_Transfer` | no (`DUNE_API_KEY`) | the causal graph G and flow terms F_{pa(i)→i,t} |
| Prices / returns | **DefiLlama** keyless price-chart API (CoinGecko-sourced, multi-year) | yes | stress states, Δ-CoVaR benchmark, backtests |
| Protocol TVL | **DefiLlama** | yes | lending/LST stress states |
| Contract labels/ABIs | **Etherscan V2** (`ETHERSCAN_API_KEY`) | no | entity-resolution seeding |

No synthetic data is used. The Oct 10–11 2025 liquidation cascade is visible
directly in the raw pulls (e.g. USDe on-chain transfer volume spikes from
~$0.7B to ~$8.8B over Oct 9→11).

## Layout

```
vein/
  config.py         # entity universe, real mainnet addresses, time windows
  dune.py           # cached Dune SQL client (results cached by SQL hash)
  market_data.py    # DefiLlama prices + TVL loaders (cached)
  onchain_graph.py  # build observed flow graph G  (Sections 2.2–2.3)
  stress.py         # stress-state operationalization S_{i,t}  (Section 3.3)
  scm.py            # structural equations f_i, forward simulation, abduction
  risk.py           # OC-CoVaR (do-operator) + counterfactual attribution (2.5)
  falsification.py  # edge-reversal test for A3  (Section 2.6)
  benchmarks.py     # Δ-CoVaR (Adrian–Brunnermeier) + correlation graph (4.1)
  backtest.py       # Kupiec / Christoffersen VaR tests  (Section 4.2)
run_evaluation.py   # end-to-end pipeline → results/results.json + EVALUATION.md
```

## How the algorithm maps to code

- **pa(i) read off the ledger** — `onchain_graph.build_graph` derives directed
  edges from observed flows; `scm.StructuralCausalModel.parents` is exactly that
  adjacency, never a statistically-inferred graph.
- **Structural equation** S_{i,t} = f_i(S_{pa(i),t−1}, F_{pa(i)→i,t}, U_{i,t}) —
  `scm.fit` estimates each f_i as a ridge-regularized linear map; the temporal lag
  (assumption A1) makes the cyclic multi-entity system a well-defined recursive
  dynamical system simulated day-by-day in `scm.simulate`.
- **OC-CoVaR (Level 2)** — `risk.oc_covar` forces `do(S_i = s*)` (severing i's
  parents) and Monte-Carlos the exogenous shocks forward to get VaR_q(L_j).
- **Counterfactual attribution (Level 3)** — `risk.counterfactual_attribution`
  runs abduction (recover Û from residuals) → action (force i to pre-crisis) →
  prediction (recompute L_j).
- **Falsification (A3)** — `falsification.run_falsification` refits the SCM on
  true / reversed / symmetric graphs and scores event-window prediction.

## Running

```bash
pip install -r requirements.txt
source secrets.env            # DUNE_API_KEY, ETHERSCAN_API_KEY (git-ignored)
python run_evaluation.py
```

Results land in `results/EVALUATION.md` (human-readable) and
`results/results.json` (machine-readable). All network results are cached under
`data_cache/` (git-ignored), so re-runs are instant and do not re-spend Dune
credits.

## Scope honesty (see also algorithm.md §5.2)

This is the **label-seeded backbone** of the resolution pipeline (Tier 3): a
small, high-precision set of publicly-attributed addresses, with everything else
collapsed into a `retail` node. The Tier-1/2 ML/GNN resolution layer is not yet
implemented, so the graph is high-precision / low-recall. The historical flow
graph uses the Ethena/Binance systemic-core tokens (USDe, sUSDe, wBETH) to
respect Dune free-tier credits. These are recall limitations, not correctness
ones — the causal machinery is independent of how the graph is populated.
