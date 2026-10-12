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

The estimator defaults are the ones the code now uses everywhere:

- Full abduction. `risk.counterfactual_attribution(..., abduction="full")` (default)
  recovers the event-window shocks from the observed path with
  `SCM.event_residuals()`, which inverts the structural equations on the observed
  stress and flows. It requires the observed stress on every event day and a flow
  span (from `fit` or `set_flows`) covering the window. `abduction="legacy_zero"`
  takes the shocks from `SCM.abduct()` (zero on the event window) and is kept only
  for comparison with earlier runs.
- Joint block bootstrap. `risk._bootstrap_U`, `oc_covar`, `delta_oc_covar` and
  `systemic_ranking` default to `joint=True`: one set of row indices is shared by
  all entities. `block_len` draws contiguous runs of residual rows. The run scripts
  pass `block_len=24` for hourly runs and `block_len=5` for daily runs. `joint=False`
  is independent per-entity i.i.d. resampling and accepts only `block_len=1`.
- Pre-event s*. `risk.fit_window_s_star(stress, fit_index, q=0.95)` takes the 95th
  percentile of each entity's stress over the fit window only, so event-window rows
  never enter s*.

The H1 paired bootstrap in `run_revision.py` is a moving-block bootstrap (block
length 8) over the paired prediction errors, put in time order (hour, then entity).

`run_best.py` (hourly, requires the Dune data) also writes
`results/hourly_scm_export.json`, so the analytic checks can be repeated on the
hourly coefficients. The export and `results/final_results.json` record the
settings used (abduction mode, bootstrap mode, block length, s* window).

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
