# Rocket CatBoost Baseline Report

## Scope

Offline shadow baseline only. No Telegram logic, production alert logic,
or live gating code was modified. The saved model artifact must not be
loaded by production services without a separate promotion step.

## Inputs

- Dataset: `data\agentic\rocket_training_dataset_reconstructed_v2_full.parquet`
- Model artifact: `data\agentic\rocket_catboost_baseline_shadow.joblib`
- Report: `docs\rocket_catboost_baseline_report.md`
- Feature policy: only `FEATURE_COLUMNS` from `rocket_dataset_builder.py`.
- Label policy: exact labels only; `UNKNOWN` and `PROVISIONAL_*` rows excluded.

## Time Split

| Split | Rows | Date range |
|---|---:|---|
| Train | 22,426 | 2024-11-06T21:30:00+00:00 to 2026-05-28T14:26:31.028719+00:00 |
| Test | 5,607 | 2026-05-28T14:26:31.143343+00:00 to 2026-05-29T22:17:28.465287+00:00 |
| Split boundary |  | 2026-05-28T14:26:31.143343+00:00 |

## Target Metrics

| Target | Positives | Baseline | AUC | Precision | Recall | F1 | Top-decile hit rate | Lift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `binary_runner` | 1,224 | 21.83% | 0.870 | 42.78% | 89.13% | 0.578 | 70.94% | 3.250 |
| `binary_major_plus` | 411 | 7.33% | 0.931 | 24.95% | 90.51% | 0.391 | 45.10% | 6.152 |
| `binary_monster_plus` | 107 | 1.91% | 0.941 | 11.07% | 77.57% | 0.194 | 14.80% | 7.753 |

## Feature Importance: `binary_runner`

| Rank | Feature | Importance |
|---:|---|---:|
| 1 | `ticker` | 30.187 |
| 2 | `alert_time` | 16.725 |
| 3 | `move_pct_at_alert` | 12.238 |
| 4 | `price_at_alert` | 6.602 |
| 5 | `market_cap_category` | 4.532 |
| 6 | `volume_at_alert` | 4.450 |
| 7 | `session_type` | 4.038 |
| 8 | `source_type` | 3.331 |
| 9 | `rvol_at_alert` | 3.119 |
| 10 | `float_category` | 2.752 |
| 11 | `is_negative` | 2.244 |
| 12 | `expected_return_score` | 1.775 |
| 13 | `trap_risk_at_alert` | 1.622 |
| 14 | `catalyst_type` | 1.147 |
| 15 | `news_impact_score` | 1.058 |
| 16 | `continuation_probability` | 0.836 |
| 17 | `is_delayed_reaction` | 0.702 |
| 18 | `ml_predicted_win_prob` | 0.534 |
| 19 | `catalyst_category` | 0.496 |
| 20 | `is_vague` | 0.468 |

## Feature Importance: `binary_major_plus`

| Rank | Feature | Importance |
|---:|---|---:|
| 1 | `ticker` | 41.748 |
| 2 | `market_cap_category` | 8.916 |
| 3 | `price_at_alert` | 7.513 |
| 4 | `move_pct_at_alert` | 5.553 |
| 5 | `expected_return_score` | 5.535 |
| 6 | `alert_time` | 4.586 |
| 7 | `volume_at_alert` | 3.228 |
| 8 | `float_category` | 2.966 |
| 9 | `news_impact_score` | 2.910 |
| 10 | `source_type` | 2.564 |
| 11 | `rvol_at_alert` | 2.051 |
| 12 | `session_type` | 2.028 |
| 13 | `catalyst_category` | 1.926 |
| 14 | `spread_pct_at_alert` | 1.372 |
| 15 | `is_negative` | 1.099 |
| 16 | `is_vague` | 1.007 |
| 17 | `catalyst_type` | 0.980 |
| 18 | `is_delayed_reaction` | 0.967 |
| 19 | `ml_predicted_win_prob` | 0.728 |
| 20 | `velocity_score_at_alert` | 0.700 |

## Feature Importance: `binary_monster_plus`

| Rank | Feature | Importance |
|---:|---|---:|
| 1 | `price_at_alert` | 25.540 |
| 2 | `ticker` | 21.653 |
| 3 | `market_cap_category` | 11.386 |
| 4 | `float_category` | 4.995 |
| 5 | `source_type` | 4.438 |
| 6 | `news_impact_score` | 3.452 |
| 7 | `catalyst_type` | 3.338 |
| 8 | `multi_day_score` | 3.260 |
| 9 | `rvol_at_alert` | 3.255 |
| 10 | `volume_at_alert` | 2.491 |
| 11 | `expected_return_score` | 2.326 |
| 12 | `ml_predicted_win_prob` | 2.013 |
| 13 | `is_delayed_reaction` | 1.774 |
| 14 | `spread_pct_at_alert` | 1.762 |
| 15 | `dilution_risk_at_alert` | 1.275 |
| 16 | `alert_time` | 1.211 |
| 17 | `is_vague` | 1.012 |
| 18 | `velocity_score_at_alert` | 0.925 |
| 19 | `move_pct_at_alert` | 0.834 |
| 20 | `catalyst_category` | 0.585 |

## Calibration: `binary_runner`

| Probability bucket | Rows | Avg predicted | Actual rate |
|---|---:|---:|---:|
| `0.0-0.1` | 1,664 | 3.65% | 1.92% |
| `0.1-0.2` | 238 | 14.49% | 9.66% |
| `0.2-0.3` | 398 | 25.48% | 3.02% |
| `0.3-0.4` | 396 | 34.82% | 7.58% |
| `0.4-0.5` | 361 | 45.05% | 9.97% |
| `0.5-0.6` | 436 | 54.79% | 12.39% |
| `0.6-0.7` | 379 | 64.84% | 22.96% |
| `0.7-0.8` | 296 | 74.85% | 29.73% |
| `0.8-0.9` | 353 | 84.78% | 52.97% |
| `0.9-1.0` | 1,086 | 96.92% | 62.15% |

## Calibration: `binary_major_plus`

| Probability bucket | Rows | Avg predicted | Actual rate |
|---|---:|---:|---:|
| `0.0-0.1` | 2,248 | 4.37% | 0.00% |
| `0.1-0.2` | 755 | 15.41% | 0.00% |
| `0.2-0.3` | 502 | 25.32% | 3.39% |
| `0.3-0.4` | 468 | 34.54% | 3.21% |
| `0.4-0.5` | 143 | 44.97% | 4.90% |
| `0.5-0.6` | 310 | 55.22% | 8.06% |
| `0.6-0.7` | 256 | 64.85% | 7.03% |
| `0.7-0.8` | 219 | 74.34% | 21.00% |
| `0.8-0.9` | 143 | 85.15% | 20.98% |
| `0.9-1.0` | 563 | 97.47% | 44.94% |

## Calibration: `binary_monster_plus`

| Probability bucket | Rows | Avg predicted | Actual rate |
|---|---:|---:|---:|
| `0.0-0.1` | 3,412 | 1.82% | 0.00% |
| `0.1-0.2` | 860 | 14.43% | 0.00% |
| `0.2-0.3` | 233 | 24.39% | 3.43% |
| `0.3-0.4` | 159 | 34.12% | 9.43% |
| `0.4-0.5` | 193 | 46.19% | 0.52% |
| `0.5-0.6` | 250 | 54.37% | 0.00% |
| `0.6-0.7` | 140 | 63.92% | 9.29% |
| `0.7-0.8` | 69 | 74.04% | 24.64% |
| `0.8-0.9` | 79 | 86.27% | 0.00% |
| `0.9-1.0` | 212 | 96.66% | 25.00% |

## Rule-Score Benchmarks

| Target | Best rule score | Rule AUC | Rule top-decile hit | Rule lift | Model AUC | Model top-decile hit | Model lift |
|---|---|---:|---:|---:|---:|---:|---:|
| `binary_runner` | `rvol_at_alert` | 0.697 | 58.16% | 2.378 | 0.870 | 70.94% | 3.250 |
| `binary_major_plus` | `rvol_at_alert` | 0.701 | 34.18% | 3.877 | 0.931 | 45.10% | 6.152 |
| `binary_monster_plus` | `expected_return_score` | 0.753 | 9.16% | 4.811 | 0.941 | 14.80% | 7.753 |

## Answers

- Is the model useful? **Yes**. The runner target AUC is 0.870 with top-decile lift 3.250.
- Is it better than current rule scores? **Yes on this temporal test slice**. The rule-score benchmark above compares against the best available
  at-alert rule/score column for each target on the same test rows.
- Which target is strongest? **`binary_monster_plus`** by AUC.
- Is `monster_plus` reliable enough yet? **Yes for offline ranking tests only**. It has 107 positives in the test slice, AUC 0.941, precision 11.07%, and recall 77.57%.

## Recommendation

Keep this artifact as an offline shadow model. Next step is walk-forward
validation, threshold tuning, and probability calibration before considering
any promotion.
