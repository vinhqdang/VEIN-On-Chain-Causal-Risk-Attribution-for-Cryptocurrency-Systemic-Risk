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
| [`run_analytics.py`](run_analytics.py) | Analytic checks on the archived daily SCM (no Dune data needed). |
| [`tests/`](tests/) | pytest suite for the analytic results and the abduction and bootstrap code. |
| [`results/EVALUATION.md`](results/EVALUATION.md) | Latest evaluation report (real-data results). |
| [`results/ANALYTICS.md`](results/ANALYTICS.md) | Output of `run_analytics.py` (bounds, Shapley checks, certified radius). |

## Analytic checks and tests

`run_analytics.py` reads only `results/results.json` and writes
`results/analytics.json` and `results/ANALYTICS.md`. It checks the flow-free
bounds on the OC-CoVaR change, the exact linear Shapley attribution (closed
form against subset and permutation enumeration), and the certified ranking
radius. It runs on the daily specification; the hourly coefficients are not
archived.

```bash
python run_analytics.py
python -m pytest -q tests
```

The archived results were produced with two default settings that the code
keeps for reproducibility. Both can be switched on to test the alternatives:

- `risk.counterfactual_attribution(..., abduction="legacy_zero")` (default)
  takes the event-window shocks from `SCM.abduct()`, which are zero because the
  residuals exist only on the pre-event fit days. `abduction="full"` uses
  `SCM.event_residuals()`, which inverts the structural equations on the
  observed event path.
- `risk._bootstrap_U(..., joint=False)` (default, also the `joint` argument of
  `oc_covar`, `delta_oc_covar` and `systemic_ranking`) resamples each entity's
  residuals independently. `joint=True` draws one set of row indices shared by
  all entities.

`run_best.py` (hourly, requires the Dune data) also writes
`results/hourly_scm_export.json`, so the analytic checks can be repeated on the
hourly coefficients.

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
