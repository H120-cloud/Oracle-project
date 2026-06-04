# Rocket Dataset Report

## Run Metadata
| Field | Value |
|---|---|
| dataset_version | `rocket_v1` |
| builder_version | `1.0.0` |
| created_at | 2026-06-01T18:16:42.730267+00:00 |
| elapsed_seconds | 1280.6 |

## Row Counts
| Source | Ingested | Exported | Rejected |
|---|---|---|---|
| backfill | 3352 | 0 | 3352 |
| missed | 121 | 119 | 2 |
| prenews | 85 | 85 | 0 |
| shadow | 30000 | 24941 | 5059 |
| telegram | 11869 | 3940 | 7929 |
| **TOTAL** | **45427** | **29085** | **16342** |

## Rejection Summary
| Reason | Count | % of Ingested |
|---|---|---|
| duplicate | 15604 | 34.3% |
| invalid_price | 738 | 1.6% |

## Duplicate Summary
| Kept Source | Dropped Source | Dedup Reason | Count |
|---|---|---|---|
| missed | missed | priority_order | 2 |
| shadow | shadow | priority_order | 3933 |
| telegram | backfill | priority_order | 3352 |
| telegram | shadow | priority_order | 402 |
| telegram | telegram | priority_order | 7915 |

## Pricing & Enrichment
| Metric | Value |
|---|---|
| fetched | 0 |
| unavailable | 29085 |
| outcome_source=missing | 25520 |
| outcome_source=stored_resolved | 3565 |

## Runner Tier Distribution
| Tier | Count | % |
|---|---|---|
| LEGENDARY_RUNNER | 10 | 0.0% |
| MAJOR_RUNNER | 0 | 0.0% |
| MONSTER_RUNNER | 11 | 0.0% |
| STANDARD_WIN | 0 | 0.0% |
| _(unlabeled)_ | 29064 | 99.9% |

## Drawdown Quality Distribution

> ⚠️ `daily_proxy` rows (0) carry lower-confidence CLEAN/DIRTY labels derived from daily-bar lows. Do not treat them as equivalent to `intraday_exact` rows.

| Quality | Count | % |
|---|---|---|
| CLEAN_RUNNER | 0 | 0.0% |
| DIRTY_RUNNER | 0 | 0.0% |
| TRAP | 0 | 0.0% |
| _(unlabeled)_ | 29085 | 100.0% |
| _(daily_proxy rows)_ | 0 | 0.0% |

## Feature Null Rates
| Feature Column | Null % |
|---|---|
| sec_dilution_probability | 100.0% |
| sec_toxic_financing_score | 100.0% |
| sec_warrant_overhang_score | 100.0% |
| sec_cash_runway_score | 100.0% |
| sec_survival_risk_score | 100.0% |
| sec_balance_sheet_quality_score | 100.0% |
| sec_offering_risk_score | 100.0% |
| sec_reverse_split_risk_score | 100.0% |
| sec_structural_trap_risk_score | 100.0% |
| sec_historical_dilution_behavior_score | 100.0% |
| sec_dilution_behavior | 100.0% |
| sec_oracle_action | 100.0% |
| sec_atm_active | 100.0% |
| sec_going_concern_active | 100.0% |
| catalyst_subtype | 99.6% |
| ml_predicted_win_prob | 87.6% |
| spread_pct_at_alert | 87.3% |
| prenews_anomaly_score | 87.0% |
| rvol_at_alert | 9.4% |
| volume_at_alert | 1.5% |
| float_category | 1.3% |
| market_cap_category | 1.3% |
| move_pct_at_alert | 1.3% |
| velocity_score_at_alert | 1.3% |
| sources_seen_count | 1.3% |
| is_negative | 1.3% |
| is_vague | 1.3% |
| is_delayed_reaction | 1.3% |
| catalyst_category | 0.9% |
| trap_risk_at_alert | 0.9% |
| dilution_risk_at_alert | 0.9% |
| session_type | 0.7% |
| catalyst_type | 0.3% |
| news_impact_score | 0.3% |
| expected_return_score | 0.3% |
| continuation_probability | 0.3% |
| multi_day_score | 0.3% |
| row_id | 0.0% |
| source_type | 0.0% |
| ticker | 0.0% |
| alert_time | 0.0% |
| price_at_alert | 0.0% |
| dataset_version | 0.0% |
| builder_version | 0.0% |

## Segmentation Breakdowns

### By Catalyst Category
| Catalyst Category | Count | % |
|---|---|---|
| unknown | 25339 | 87.1% |
| corporate | 1492 | 5.1% |
| negative | 912 | 3.1% |
| biotech | 705 | 2.4% |
| None | 248 | 0.9% |
| financial | 213 | 0.7% |
| crypto | 114 | 0.4% |
| ai_tech | 62 | 0.2% |

### By Float Bucket
| Float Bucket | Count | % |
|---|---|---|
| high | 10092 | 34.7% |
| medium | 10039 | 34.5% |
| low | 7052 | 24.2% |
| ultra_low | 1535 | 5.3% |
| None | 367 | 1.3% |

### By Market Cap Bucket
| Market Cap Bucket | Count | % |
|---|---|---|
| all | 10021 | 34.5% |
| small | 7572 | 26.0% |
| micro | 6576 | 22.6% |
| nano | 4549 | 15.6% |
| None | 367 | 1.3% |

### By Price Bucket
| Price Bucket | Count | % |
|---|---|---|
| $0–$1 | 4748 | 16.3% |
| $1–$5 | 4656 | 16.0% |
| $5–$10 | 2617 | 9.0% |
| >$10 | 17064 | 58.7% |

## Dropped Non-Manifest Columns
The following `RocketRecord` fields exist on the model but are not exported (they are neither in `FEATURE_COLUMNS` nor `LABEL_COLUMNS`).

| Column | Reason |
|---|---|
| _(none)_ | — |