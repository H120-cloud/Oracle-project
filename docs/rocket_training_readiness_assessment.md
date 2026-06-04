# Rocket Training Readiness Assessment

## Final Enriched Dataset

This assessment uses the completed full enrichment export:

`data/agentic/rocket_training_dataset_reconstructed_v2_full.parquet`

Synthetic/test ticker rows are excluded from the training export and preserved
only in the rejection sidecar:

`data/agentic/rocket_training_dataset_reconstructed_v2_full_synthetic_rejections.parquet`

No ML model has been trained.

| Metric | Value |
|---|---:|
| Final training export rows | 28,735 |
| Synthetic rows excluded to sidecar | 350 |
| Synthetic rows in final training export | 0 |
| Reconstructed exact labels | 28,012 |
| Existing exact labels | 21 |
| Total high-confidence exact labels | 28,033 |
| Provisional labels | 43 |
| Remaining unknown rows | 659 |
| High-confidence exact coverage | 97.56% |
| Any-label coverage | 97.71% |

## Label Source Distribution

| Label source | Rows |
|---|---:|
| `existing_runner_tier` | 21 |
| `reconstructed_exact` | 28,012 |
| `reconstructed_provisional` | 43 |
| `insufficient_evidence` | 659 |

## Final Class Distribution

| Class | Rows | Share of all rows |
|---|---:|---:|
| `NON_RUNNER` | 23,329 | 81.18% |
| `STANDARD_WIN` | 3,143 | 10.94% |
| `MAJOR_RUNNER` | 1,092 | 3.80% |
| `MONSTER_RUNNER` | 287 | 1.00% |
| `LEGENDARY_RUNNER` | 182 | 0.63% |
| `PROVISIONAL_STANDARD_WIN` | 40 | 0.14% |
| `PROVISIONAL_MAJOR_RUNNER` | 3 | 0.01% |
| `UNKNOWN` | 659 | 2.29% |

## Drawdown Data Quality

| Quality | Rows |
|---|---:|
| `intraday_exact` | 24,930 |
| `daily_proxy` | 30 |
| `missing` | 3,775 |

## Provider Outcome

| Metric | Value |
|---|---:|
| Distinct real ticker/date groups examined | 4,016 |
| Durable cache hits | 2,470 |
| Failed groups after all providers | 73 |
| Polygon API calls | 3,314 |
| Alpaca API calls | 356 |
| yfinance API calls | 300 |

## Model Readiness

### CatBoost

**GO for a first offline binary baseline.**

The dataset now has 28,033 high-confidence exact labels, with 4,704 exact
runner positives across `STANDARD_WIN`, `MAJOR_RUNNER`, `MONSTER_RUNNER`, and
`LEGENDARY_RUNNER`. That is enough for an offline CatBoost binary model:

```text
positive = STANDARD_WIN | MAJOR_RUNNER | MONSTER_RUNNER | LEGENDARY_RUNNER
negative = NON_RUNNER
```

Do not connect the model to alerting until temporal validation proves it is
better than the existing rules.

### LightGBM

**GO for comparison after CatBoost.**

LightGBM is trainable on this label volume, but CatBoost should be first
because the dataset has mixed categorical features and many missing values.

### Monster Runner Classifier

**NO-GO for standalone production training.**

There are 469 exact `MONSTER_RUNNER` plus `LEGENDARY_RUNNER` examples. That is
useful for reporting recall and for a secondary sensitivity experiment, but it
is still too sparse for a dependable standalone monster-runner classifier.

## Recommended First Model

Train CatBoost binary runner-vs-non-runner first, offline only.

Recommended exclusions for the first fit:

- Exclude `UNKNOWN`.
- Exclude provisional labels from the primary fit.
- Keep `PROVISIONAL_*` rows for sensitivity analysis only.
- Exclude synthetic rejection sidecars entirely.

## Validation Methodology

Use temporal, leakage-resistant validation:

1. Sort by alert timestamp.
2. Train on earlier time blocks and validate on later time blocks.
3. Reserve the newest block as untouched final test data.
4. Group by ticker and trading date so related alert variants cannot cross
   train/validation/test boundaries.
5. Report PR-AUC, precision at alert-budget thresholds, runner recall,
   calibration error, false positives per trading day, and recall for
   `MONSTER_RUNNER` plus `LEGENDARY_RUNNER`.
6. Compare against the current rule-based gate before any model influences
   production alert ranking.

## Final Decision

**GO for offline CatBoost binary baseline training.**

**NO-GO for production deployment or Telegram integration until validation is
reviewed.**
