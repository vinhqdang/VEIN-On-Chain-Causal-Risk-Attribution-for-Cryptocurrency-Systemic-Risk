# VEIN: On-Chain Causal Risk Attribution for Cryptocurrency Systemic Risk

Treating the **observed on-chain transaction graph** as the structural backbone
of a Pearl Structural Causal Model for systemic-risk measurement in crypto
markets — interventional (On-Chain Causal CoVaR) and counterfactual (Level-3)
loss attribution.

## Contents

| File | What it is |
|---|---|
| [`algorithm.md`](algorithm.md) | The research design: algorithm, dataset, evaluation plan, hypotheses (H1–H5). |
| [`gap_analysis.md`](gap_analysis.md) | Literature gap analysis + verification log confirming the novelty claim. |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | How the reference implementation maps to the algorithm + how to run it. |
| [`vein/`](vein/) | The implementation (graph, SCM, OC-CoVaR, counterfactual attribution, falsification, benchmarks, backtests). |
| [`run_evaluation.py`](run_evaluation.py) | End-to-end evaluation on **real** Ethereum data. |
| [`results/EVALUATION.md`](results/EVALUATION.md) | Latest evaluation report (real-data results). |

## Quick start

```bash
pip install -r requirements.txt
source secrets.env          # DUNE_API_KEY, ETHERSCAN_API_KEY (git-ignored)
python run_evaluation.py     # writes results/EVALUATION.md + results/results.json
```

Real data sources: Dune Analytics (decoded on-chain transfers), DefiLlama
(prices + TVL, keyless), Etherscan V2 (labels). All network results are cached
under `data_cache/` (git-ignored) so re-runs are instant and credit-free.

See [`IMPLEMENTATION.md`](IMPLEMENTATION.md) for scope and honest limitations.
