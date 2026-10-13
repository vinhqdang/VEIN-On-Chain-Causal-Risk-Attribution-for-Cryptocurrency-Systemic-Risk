# Submission log

| Date | Journal | Version | Status |
|---|---|---|---|
| 2026 (earlier) | Journal of Risk Finance | Dune data, empirical framing | Manuscript prepared (commit ae74d6e) |
| 2026 (earlier) | Financial Innovation | Dune data, empirical framing | Manuscript and cover letter prepared (commits f6c1b5c–b59bda2) |
| 2026 (earlier) | Computational Economics | Dune data, empirical framing | Desk rejected |
| 2026-10-12 | Digital Finance (Springer) | Methods paper on BigQuery public data, full abduction, bootstrap uncertainty | Submitted (blinded LaTeX package `manuscript/vein_latex_submission.zip`, commit 0a09548) |
| 2026-10-13 | Digital Finance (Springer) | Same content | Technical check: author names must appear in the manuscript; resubmitted with author details (`manuscript/vein_latex_submission_named.zip`, built by `manuscript/make_named_package.py`) |

## Submitted version (Digital Finance)

- Title: see `manuscript/vein_manuscript.tex`; 37 pages (referee mode), blinded.
- Built from `manuscript/source/ms_template.tex` with `python manuscript/source/build_ms.py`;
  every number is read from `results/*.json` and checked by `run_compare.py`.
- Evidence base: `results/RESULTS_V3.md`; data build: `results/DATA_BUILD.md`.
- Data: BigQuery `crypto_ethereum` (project `vein-bq-10120733`, no billing), open labels
  (eth-labels, etherscan-labels, Spellbook CEX list at pinned commits).
- Earlier results kept for reference: `results/v1_dune/`, `results/v2_bq_initial/`.

## For a revision

- Edit the template, not the generated `.tex`; rebuild, compile, run `run_compare.py`,
  then `manuscript/make_blind.py` to refresh the blinded version and the zip.
- Reruns hit the BigQuery cache in `data_cache/`; the spend ledger is
  `data_cache/bq_ledger.json`.
