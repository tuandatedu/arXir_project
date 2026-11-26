# M3 Global5 — Machine Learning & Evaluation (scope: model-owner only)

This folder documents the **ML and evaluation** deliverable. Data cleaning, labels,
feature extraction and candidate-pair construction are **owned by the data preparation teammate(s)**
and remain in `src/m3_matching/`. We consume their frozen `dataset_pairs.parquet`.

## Current frozen experiment

- **Scope:** five assigned ranges, 18,523 labeled publications / 790,862 BibTeX queries.
- **Split unit:** publication (never per-pair). Current frozen split: 18,519 Train publications,
  2 Validation, 2 Test. Each holdout has one manual and one automatic publication.
- **Important compliance gate:** `src/m3_matching/split.py` supports `k` publications **per label origin in each holdout**,
  with `k` documented as the number of members. The current Global5 frozen experiment used `k=1`.
  **Before final submission, confirm `k` from the official statement and the actual team size**.
  Do not quietly relabel/re-split/re-test this completed experiment: treat any changed split as a new experiment.
- **Models:** LR13 (primary selected before global Test), LightGBM13 (comparator), fixed heuristic B1/B2.
- **Features:** 13 numeric features; `doi_match` excluded from both ML models.
- **Validation MRR@5:** B1=B2=LR13=LGBM13=0.656250 (42 positive, 22 GT-null queries).
- **Test MRR@5:** all four methods: manual 1.0 (25 queries), automatic 0.823529 (34 queries),
  pooled 0.898305 (53 positive / 6 GT-null). No observable MRR improvement over baselines.
- **Predictions:** 790,862 rows, columns `arxiv_id`, `partition`, `citation_key`,
  `groundtruth_arxiv_id`, `cand_1`..`cand_5`; SHA-256 recorded as
  `db02fd5eb79b06b1d67ac4cae619fce49523f066372dd630a2986b732d18f5e1`.
- **Known GT outside pool:** 3 Train queries, retained with non-null GT, listed in results.

## Repository layout

```
scripts/m3_global5/
  M3_GLOBAL5_PREPARE_READONLY.py      # frozen split, full source integrity, no model fit
  M3_GLOBAL5_TRAIN_VALIDATE.py       # disk-backed LR13/LGBM13 training, B1/B2 Valid
  M3_GLOBAL5_TEST_AND_EXPORT.py      # Test evaluation OR prediction export; never refits
configs/m3_global5/
  global5_publication_split.csv      # publication-level assignment, frozen
  global5_split_manifest.json        # frozen SHA and holdout declaration
results/m3_global5/
  global5_prepared_manifest.json     # source SHA, split row counts
  global5_pretest_model_lock.json    # model SHA, validation, Test unopened at model freeze
  global5_test_metrics.json          # test per-manual/auto and 4-method metrics
  global5_predictions_manifest.json  # predictions SHA, schema and counts
  validation_query_metrics.csv
  global5_test_query_metrics.csv
  known_gt_outside_pool.csv
tests/test_m3_global5_contract.py     # synthetic model evaluation & frozen contract tests
requirements-m3-global5.txt
```

Generated raw Train/Valid/Test Parquet, `.joblib`, and final predictions live under
`outputs/` on the user's machine and are **not committed to GitHub**. The full
original Range-specific Parquet files are also local (`data/` ignored).

## Installation (repository root)

Use a virtual environment; for just this ML portion:

```powershell
python -m pip install -r .\requirements-m3-global5.txt
python -m pytest -q tests\test_m3_global5_contract.py
```

## Full reproducibility commands (DO NOT rerun the locked Test to tune models)

Obtain the five immutable original `dataset_pairs.parquet` files from the
assigned group source. Confirm the paths are **full candidate-pair files**,
not the older per-Range Train-only subsets. Put them at
`data/m3/global5_input/range_{1..5}/dataset_pairs.parquet`.

**1. Repartition (read-only inputs):**

```powershell
python -m scripts.m3_global5.M3_GLOBAL5_PREPARE_READONLY `
  --split .\configs\m3_global5\global5_publication_split.csv `
  --manifest .\configs\m3_global5\global5_split_manifest.json `
  --r1 .\data\m3\global5_input\range_1\dataset_pairs.parquet `
  --r2 .\data\m3\global5_input\range_2\dataset_pairs.parquet `
  --r3 .\data\m3\global5_input\range_3\dataset_pairs.parquet `
  --r4 .\data\m3\global5_input\range_4\dataset_pairs.parquet `
  --r5 .\data\m3\global5_input\range_5\dataset_pairs.parquet `
  --out-dir .\outputs\global5_prepared_repro
```

**2. Train and Validation:**

```powershell
python -m scripts.m3_global5.M3_GLOBAL5_TRAIN_VALIDATE `
  --prepared-dir .\outputs\global5_prepared_repro `
  --out-dir .\outputs\global5_models_repro `
  --num-threads 4
```

**3. Evaluate the frozen Test (audit only):**

```powershell
python -m scripts.m3_global5.M3_GLOBAL5_TEST_AND_EXPORT `
  --phase test `
  --prepared-dir .\outputs\global5_prepared_repro `
  --model-dir .\outputs\global5_models_repro `
  --split .\configs\m3_global5\global5_publication_split.csv `
  --manifest .\configs\m3_global5\global5_split_manifest.json `
  --out-dir .\outputs\global5_test_repro
```

**4. Export predictions:**

```powershell
python -m scripts.m3_global5.M3_GLOBAL5_TEST_AND_EXPORT `
  --phase export `
  --prepared-dir .\outputs\global5_prepared_repro `
  --model-dir .\outputs\global5_models_repro `
  --split .\configs\m3_global5\global5_publication_split.csv `
  --manifest .\configs\m3_global5\global5_split_manifest.json `
  --out-dir .\outputs\global5_predictions_repro
```

Commands refuse to overwrite existing outputs. Use new directory names if rerunning.
**Re-training may produce different binary file hashes across library versions and
platforms; do not replace original frozen snapshots or alter Test-based decisions.**

## Interpretation and limits

1. Pairwise binary classification with `P(y=1)` scores, stable Top-5 within each query.
2. GT-null entries receive RR=0 under this fixed protocol. This is not a proven real-world negative.
3. Manual Test has 25 positive queries; automatic Test 28 positive and 6 GT-null.
4. All methods tie on MRR@5; ML did not show a measurable improvement over B1/B2.
5. Automatic labels may be DOI-first/title-author-year heuristic, which overlaps with model features.
6. Models use frozen metadata features, not image/text foundation models.
7. This folder **does not** implement the shared M3 labeling/feature pipeline,
   HF six-table upload, or replace current `src/m3_matching/pipeline.py` stubs.

## Original course and data context

- [Course M3 statement](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/)
- Model frozen results are preserved as small JSON/CSV files in `results/m3_global5`.
- All code and artifacts should be integrated by **selective path merge** into the group main.
