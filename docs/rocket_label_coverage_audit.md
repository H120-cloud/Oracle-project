# Rocket Label Coverage Audit

## Scope

This audit measures label coverage in:

- `data/agentic/rocket_training_dataset.parquet`
- `data/agentic/rocket_training_dataset.csv`

It also inventories historical outcome fields in the raw builder inputs and the
existing resolved-outcome JSONL archives. No new market-data fetches were run and
no ML models were built.

All statistics below were computed from the exported Parquet file and the
historical records on disk on 2026-06-01. Month and year groupings use
`alert_time` parsed as UTC.

Price buckets are mutually exclusive:

| Bucket | Definition |
|---|---|
| `sub_penny` | price < $0.01 |
| `under_1` | $0.01 <= price < $1 |
| `under_5` | $1 <= price < $5 |
| `under_10` | $5 <= price < $10 |
| `over_10` | price >= $10 |

## Executive Summary

The exported dataset contains **29,085** rows, but only **21 rows (0.07%)**
currently have `runner_tier`. No rows have `drawdown_quality`.

The first no-fetch reconstruction opportunity is already inside the exported
dataset:

- **3,565 rows (12.26%)** have at least one stored forward-return window.
- **3,277 rows (11.27%)** have complete 1d, 2d, and 5d return windows.
- **283 rows (0.97%)** can receive a conservative exact positive runner tier
  from complete windows.
- **2,994 rows (10.29%)** can be classified as exact non-runners if the dataset
  adds an explicit non-runner label.
- **43 additional rows** can receive a provisional lower-bound positive tier
  from partial windows, but should not be treated as exact tiers.
- The maximum positive-tier count without fetching bars is therefore **326
  rows (1.12%)**, including the 43 provisional rows.

The most useful immediate implementation is not a new model. It is a no-bars
label reconstruction pass that uses stored 1d, 2d, and 5d returns and records
label quality explicitly.

## 1. Overall Label Coverage

| Metric | Count | % of 29,085 exported rows |
|---|---:|---:|
| Total exported rows | 29,085 | 100.00% |
| `runner_tier` populated | 21 | 0.07% |
| `runner_tier` missing | 29,064 | 99.93% |
| `drawdown_quality` populated | 0 | 0.00% |
| `drawdown_quality` missing | 29,085 | 100.00% |

### Outcome Source

| `outcome_source` | Rows | % |
|---|---:|---:|
| `stored_resolved` | 3,565 | 12.26% |
| `missing` | 25,520 | 87.74% |

### Drawdown Data Quality

| `drawdown_data_quality` | Rows | % |
|---|---:|---:|
| `missing` | 29,085 | 100.00% |

### Exported Forward-Label Field Availability

| Field | Available Rows | % |
|---|---:|---:|
| `peak_move_pct` | 3,277 | 11.27% |
| `peak_timestamp` | 0 | 0.00% |
| `calendar_time_to_peak_minutes` | 0 | 0.00% |
| `trading_time_to_peak_minutes` | 0 | 0.00% |
| `mfe_15m` | 0 | 0.00% |
| `mfe_60m` | 0 | 0.00% |
| `mfe_1d` | 3,565 | 12.26% |
| `mfe_2d` | 3,520 | 12.10% |
| `mfe_5d` | 3,277 | 11.27% |
| `mae_15m` | 0 | 0.00% |
| `mae_60m` | 0 | 0.00% |
| `mae_1d` | 0 | 0.00% |
| `mae_2d` | 0 | 0.00% |
| `mae_5d` | 0 | 0.00% |
| `runner_tier` | 21 | 0.07% |
| `drawdown_quality` | 0 | 0.00% |
| `drawdown_data_quality` | 29,085 | 100.00% |
| `data_quality_score` | 29,085 | 100.00% |

`drawdown_data_quality` is populated, but every value is `missing`.

## 2. Current Runner Distribution

| Runner Tier | Rows | % of Exported Rows | % of Currently Labeled Runner Rows |
|---|---:|---:|---:|
| `STANDARD_WIN` | 0 | 0.00% | 0.00% |
| `MAJOR_RUNNER` | 0 | 0.00% | 0.00% |
| `MONSTER_RUNNER` | 11 | 0.04% | 52.38% |
| `LEGENDARY_RUNNER` | 10 | 0.03% | 47.62% |
| Unlabeled | 29,064 | 99.93% | - |

The current builder assigns 5-day tiers from stored `peak_move_pct` even when
timing is unavailable. It does not reconstruct `STANDARD_WIN` or
`MAJOR_RUNNER` from the stored 1d and 2d return windows.

## 3. Coverage Breakdowns

The tables below report:

- current `runner_tier`
- current `drawdown_quality`
- rows with `outcome_source=stored_resolved`
- rows with complete 1d, 2d, and 5d return windows
- positive tiers reconstructable from stored returns without fetching bars

### By Source Type

| Source Type | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `missed` | 119 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `prenews` | 85 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `shadow` | 24,941 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `telegram` | 3,940 | 21 (0.53%) | 0 (0.00%) | 3,565 (90.48%) | 3,277 (83.17%) | 326 (8.27%) |

### By Month

| Month | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `2024-11` | 2 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2025-01` | 344 | 3 (0.87%) | 0 (0.00%) | 344 (100.00%) | 292 (84.88%) | 34 (9.88%) |
| `2025-02` | 215 | 0 (0.00%) | 0 (0.00%) | 215 (100.00%) | 194 (90.23%) | 34 (15.81%) |
| `2025-03` | 206 | 0 (0.00%) | 0 (0.00%) | 205 (99.51%) | 205 (99.51%) | 16 (7.77%) |
| `2025-04` | 207 | 0 (0.00%) | 0 (0.00%) | 205 (99.03%) | 186 (89.86%) | 26 (12.56%) |
| `2025-05` | 248 | 0 (0.00%) | 0 (0.00%) | 238 (95.97%) | 212 (85.48%) | 23 (9.27%) |
| `2025-06` | 235 | 2 (0.85%) | 0 (0.00%) | 215 (91.49%) | 189 (80.43%) | 22 (9.36%) |
| `2025-07` | 289 | 0 (0.00%) | 0 (0.00%) | 262 (90.66%) | 256 (88.58%) | 22 (7.61%) |
| `2025-08` | 334 | 0 (0.00%) | 0 (0.00%) | 310 (92.81%) | 284 (85.03%) | 12 (3.59%) |
| `2025-09` | 318 | 0 (0.00%) | 0 (0.00%) | 286 (89.94%) | 286 (89.94%) | 10 (3.14%) |
| `2025-10` | 384 | 2 (0.52%) | 0 (0.00%) | 354 (92.19%) | 354 (92.19%) | 31 (8.07%) |
| `2025-11` | 382 | 1 (0.26%) | 0 (0.00%) | 354 (92.67%) | 338 (88.48%) | 11 (2.88%) |
| `2025-12` | 397 | 0 (0.00%) | 0 (0.00%) | 364 (91.69%) | 313 (78.84%) | 14 (3.53%) |
| `2026-01` | 37 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2026-02` | 40 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2026-03` | 35 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2026-04` | 36 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2026-05` | 25,376 | 13 (0.05%) | 0 (0.00%) | 213 (0.84%) | 168 (0.66%) | 71 (0.28%) |

### By Year

| Year | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `2024` | 2 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `2025` | 3,559 | 8 (0.22%) | 0 (0.00%) | 3,352 (94.18%) | 3,109 (87.36%) | 255 (7.16%) |
| `2026` | 25,524 | 13 (0.05%) | 0 (0.00%) | 213 (0.83%) | 168 (0.66%) | 71 (0.28%) |

### By Catalyst Category

| Catalyst Category | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `(missing)` | 248 | 12 (4.84%) | 0 (0.00%) | 162 (65.32%) | 162 (65.32%) | 48 (19.35%) |
| `ai_tech` | 62 | 0 (0.00%) | 0 (0.00%) | 6 (9.68%) | 5 (8.06%) | 2 (3.23%) |
| `biotech` | 705 | 0 (0.00%) | 0 (0.00%) | 31 (4.40%) | 24 (3.40%) | 6 (0.85%) |
| `corporate` | 1,492 | 0 (0.00%) | 0 (0.00%) | 33 (2.21%) | 24 (1.61%) | 2 (0.13%) |
| `crypto` | 114 | 0 (0.00%) | 0 (0.00%) | 6 (5.26%) | 4 (3.51%) | 1 (0.88%) |
| `financial` | 213 | 0 (0.00%) | 0 (0.00%) | 14 (6.57%) | 6 (2.82%) | 7 (3.29%) |
| `negative` | 912 | 1 (0.11%) | 0 (0.00%) | 22 (2.41%) | 21 (2.30%) | 5 (0.55%) |
| `unknown` | 25,339 | 8 (0.03%) | 0 (0.00%) | 3,291 (12.99%) | 3,031 (11.96%) | 255 (1.01%) |

### By Market Cap Category

| Market Cap Category | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `(missing)` | 367 | 12 (3.27%) | 0 (0.00%) | 162 (44.14%) | 162 (44.14%) | 48 (13.08%) |
| `all` | 10,021 | 0 (0.00%) | 0 (0.00%) | 3 (0.03%) | 0 (0.00%) | 0 (0.00%) |
| `micro` | 6,576 | 0 (0.00%) | 0 (0.00%) | 13 (0.20%) | 1 (0.02%) | 6 (0.09%) |
| `nano` | 4,549 | 1 (0.02%) | 0 (0.00%) | 34 (0.75%) | 5 (0.11%) | 16 (0.35%) |
| `small` | 7,572 | 8 (0.11%) | 0 (0.00%) | 3,353 (44.28%) | 3,109 (41.06%) | 256 (3.38%) |

### By Float Category

| Float Category | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `(missing)` | 367 | 12 (3.27%) | 0 (0.00%) | 162 (44.14%) | 162 (44.14%) | 48 (13.08%) |
| `high` | 10,092 | 0 (0.00%) | 0 (0.00%) | 2 (0.02%) | 0 (0.00%) | 0 (0.00%) |
| `low` | 7,052 | 0 (0.00%) | 0 (0.00%) | 19 (0.27%) | 3 (0.04%) | 8 (0.11%) |
| `medium` | 10,039 | 8 (0.08%) | 0 (0.00%) | 3,364 (33.51%) | 3,110 (30.98%) | 262 (2.61%) |
| `ultra_low` | 1,535 | 1 (0.07%) | 0 (0.00%) | 18 (1.17%) | 2 (0.13%) | 8 (0.52%) |

### By Price Bucket

| Price Bucket | Rows | Current Runner Tier | Drawdown Quality | Stored Outcome Source | Complete 1d/2d/5d | Reconstructable Positive Tier |
|---|---:|---:|---:|---:|---:|---:|
| `sub_penny` | 145 | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| `under_1` | 4,554 | 13 (0.29%) | 0 (0.00%) | 150 (3.29%) | 137 (3.01%) | 53 (1.16%) |
| `under_5` | 4,681 | 1 (0.02%) | 0 (0.00%) | 350 (7.48%) | 313 (6.69%) | 67 (1.43%) |
| `under_10` | 2,629 | 6 (0.23%) | 0 (0.00%) | 326 (12.40%) | 296 (11.26%) | 54 (2.05%) |
| `over_10` | 17,076 | 1 (0.01%) | 0 (0.00%) | 2,739 (16.04%) | 2,531 (14.82%) | 152 (0.89%) |

## 4. Historical Outcome Field Inventory

### Primary Builder Inputs

The builder currently ingests 45,427 raw records before rejection and
deduplication:

| Raw Input File | Records |
|---|---:|
| `news_momentum_telegram_alerts.json` | 11,869 |
| `news_momentum_shadow_alerts.json` | 30,000 |
| `news_momentum_backfill_records.json` | 3,352 |
| `news_momentum_missed_winners.json` | 121 |
| `pre_news_shadow_v2.json` | 85 |
| **Total** | **45,427** |

The following outcome fields exist in those primary inputs. Percentages use
45,427 raw ingested records as the denominator.

| Field | Available Rows | % | Source Files Containing Field |
|---|---:|---:|---|
| `price_15m_later` | 242 | 0.53% | `news_momentum_telegram_alerts.json` (242) |
| `price_1h_later` | 241 | 0.53% | `news_momentum_telegram_alerts.json` (241) |
| `price_4h_later` | 241 | 0.53% | `news_momentum_telegram_alerts.json` (241) |
| `next_day_open` | 14,846 | 32.68% | `news_momentum_telegram_alerts.json` (11,494); `news_momentum_backfill_records.json` (3,352) |
| `next_day_high` | 14,846 | 32.68% | `news_momentum_telegram_alerts.json` (11,494); `news_momentum_backfill_records.json` (3,352) |
| `next_day_close` | 14,846 | 32.68% | `news_momentum_telegram_alerts.json` (11,494); `news_momentum_backfill_records.json` (3,352) |
| `two_day_high` | 14,801 | 32.58% | `news_momentum_telegram_alerts.json` (11,449); `news_momentum_backfill_records.json` (3,352) |
| `five_day_high` | 13,702 | 30.16% | `news_momentum_telegram_alerts.json` (10,593); `news_momentum_backfill_records.json` (3,109) |
| `mfe_pct` | 15,137 | 33.32% | `news_momentum_telegram_alerts.json` (11,785); `news_momentum_backfill_records.json` (3,352) |
| `mae_pct` | 518 | 1.14% | `news_momentum_telegram_alerts.json` (518) |
| `return_15m_pct` | 228 | 0.50% | `news_momentum_telegram_alerts.json` (228) |
| `return_1h_pct` | 227 | 0.50% | `news_momentum_telegram_alerts.json` (227) |
| `return_4h_pct` | 227 | 0.50% | `news_momentum_telegram_alerts.json` (227) |
| `return_next_day_close_pct` | 11,480 | 25.27% | `news_momentum_telegram_alerts.json` (11,480) |
| `return_next_day_high_pct` | 11,480 | 25.27% | `news_momentum_telegram_alerts.json` (11,480) |
| `return_two_day_high_pct` | 11,435 | 25.17% | `news_momentum_telegram_alerts.json` (11,435) |
| `return_five_day_high_pct` | 10,579 | 23.29% | `news_momentum_telegram_alerts.json` (10,579) |

The builder already copies `return_next_day_high_pct`,
`return_two_day_high_pct`, and `return_five_day_high_pct` into exported
`mfe_1d`, `mfe_2d`, and `mfe_5d` fallback fields. The label gap exists because
the tier assignment step still relies on `peak_move_pct` plus
`trading_time_to_peak_minutes`; stored outcomes have no peak timestamp.

### Auxiliary Resolved-Outcome Archives

Two JSONL archives contain substantial historical outcomes:

#### `candidate_resolved.jsonl`

| Metric | Value |
|---|---:|
| Records | 19,418 |
| Unique `record_id` values | 19,418 |

| Field | Available Rows | % |
|---|---:|---:|
| `price_15m_later` | 7,018 | 36.14% |
| `price_1h_later` | 7,329 | 37.74% |
| `price_4h_later` | 8,622 | 44.40% |
| `next_day_open` | 19,001 | 97.85% |
| `next_day_high` | 19,001 | 97.85% |
| `next_day_close` | 19,001 | 97.85% |
| `two_day_high` | 19,001 | 97.85% |
| `five_day_high` | 19,001 | 97.85% |
| `mfe_pct` | 19,238 | 99.07% |
| `mae_pct` | 19,238 | 99.07% |

#### `shadow_resolved.jsonl`

| Metric | Value |
|---|---:|
| Records | 48,006 |
| Unique `record_id` values | 46,558 |

| Field | Available Rows | % |
|---|---:|---:|
| `price_15m_later` | 19,545 | 40.71% |
| `price_1h_later` | 21,035 | 43.82% |
| `price_4h_later` | 26,565 | 55.34% |
| `next_day_open` | 37,128 | 77.34% |
| `next_day_high` | 37,128 | 77.34% |
| `next_day_close` | 37,128 | 77.34% |
| `two_day_high` | 37,128 | 77.34% |
| `five_day_high` | 37,128 | 77.34% |
| `mfe_pct` | 44,741 | 93.20% |
| `mae_pct` | 44,741 | 93.20% |

These archives overlap with historical records and must not be counted as new
independent observations until joined by `record_id`.

### Current Auxiliary Join Results

Joining deduplicated `shadow_resolved.jsonl` records onto the current export by
`row_id` yields:

| Metric | Count | % |
|---|---:|---:|
| Exported shadow rows | 24,941 | - |
| Exported rows joining to a resolved shadow record | 4,953 | 17.03% of all exported rows |
| Joined shadow coverage | 4,953 | 19.86% of exported shadow rows |
| Joined `price_15m_later` | 4,448 | 15.29% of all exported rows |
| Joined `price_1h_later` | 4,570 | 15.71% of all exported rows |
| Joined `price_4h_later` | 4,953 | 17.03% of all exported rows |
| Joined `mfe_pct` | 4,953 | 17.03% of all exported rows |
| Joined `mae_pct` | 4,953 | 17.03% of all exported rows |
| Joined `next_day_high` | 0 | 0.00% |
| Joined `two_day_high` | 0 | 0.00% |
| Joined `five_day_high` | 0 | 0.00% |

The current rolling shadow file overlaps with the short-horizon portion of the
archive, not the older rows with complete 1d/2d/5d highs. The joined fields are
useful for short-horizon analysis and refetch prioritization, but they do not
increase exact tier coverage today.

The current `news_momentum_candidates.json` registry contains 500 rolling rows.
None of those current IDs join to the 19,418 archived `candidate_resolved.jsonl`
IDs. Candidate archive enrichment therefore needs preserved at-alert feature
snapshots or a historical candidate archive before it can add training rows.

## 5. Reconstruction Feasibility Without Fetching Bars

### Candidate Mapping

For stored forward returns, use highest-tier precedence:

| Tier | Stored Field Rule |
|---|---|
| `LEGENDARY_RUNNER` | `return_five_day_high_pct >= 300%` |
| `MONSTER_RUNNER` | `return_five_day_high_pct >= 100%` |
| `MAJOR_RUNNER` | `return_two_day_high_pct >= 30%` |
| `STANDARD_WIN` | `return_next_day_high_pct >= 10%` |
| `NON_RUNNER` | complete 1d/2d/5d windows and none of the above |

This mapping does not require bars because each threshold is evaluated against
its matching stored time window.

### Field Availability and Threshold Hits

| Tier Rule | Rows With Required Field | Field Availability | Threshold Hits | % of Export |
|---|---:|---:|---:|---:|
| `STANDARD_WIN`: `mfe_1d >= 10%` | 3,565 | 12.26% | 313 | 1.08% |
| `MAJOR_RUNNER`: `mfe_2d >= 30%` | 3,520 | 12.10% | 64 | 0.22% |
| `MONSTER_RUNNER`: `mfe_5d >= 100%` | 3,277 | 11.27% | 21 | 0.07% |
| `LEGENDARY_RUNNER`: `mfe_5d >= 300%` | 3,277 | 11.27% | 10 | 0.03% |

Threshold hits overlap. Applying highest-tier precedence produces the
distribution below.

### Maximum Positive-Tier Reconstruction

| Tier | Reconstructable Rows | % of Export | % of Reconstructed Positive Tiers |
|---|---:|---:|---:|
| `STANDARD_WIN` | 262 | 0.90% | 80.37% |
| `MAJOR_RUNNER` | 43 | 0.15% | 13.19% |
| `MONSTER_RUNNER` | 11 | 0.04% | 3.37% |
| `LEGENDARY_RUNNER` | 10 | 0.03% | 3.07% |
| **Total** | **326** | **1.12%** | **100.00%** |

### Exact Versus Provisional Labels

| Reconstruction Class | Rows | % of Export |
|---|---:|---:|
| Rows with any 1d/2d/5d field | 3,565 | 12.26% |
| Rows with complete 1d/2d/5d windows | 3,277 | 11.27% |
| Rows with partial windows only | 288 | 0.99% |
| Exact positive tiers from complete windows | 283 | 0.97% |
| Exact non-runners from complete windows | 2,994 | 10.29% |
| Provisional lower-bound positive tiers from partial windows | 43 | 0.15% |
| Partial rows still undecidable | 245 | 0.84% |

The 43 provisional rows are:

| Provisional Lower-Bound Tier | Rows |
|---|---:|
| `STANDARD_WIN` | 40 |
| `MAJOR_RUNNER` | 3 |

They are valid positive detections but not exact final tiers because later
missing windows could promote them to a higher class.

### Estimated Post-Reconstruction Coverage

| Coverage View | Current | Post-Reconstruction | Notes |
|---|---:|---:|---|
| Positive `runner_tier` rows | 21 (0.07%) | 283 (0.97%) | Conservative exact tiers only |
| Additional exact positive tiers | - | 262 | Excludes the 21 already labeled |
| Positive rows including provisional lower bounds | 21 (0.07%) | 326 (1.12%) | Includes 43 quality-flagged partial rows |
| Exact tier-training examples with explicit `NON_RUNNER` | 21 (0.07%) | 3,277 (11.27%) | 283 runner tiers + 2,994 non-runners |
| Exact `drawdown_quality` rows | 0 (0.00%) | 0 (0.00%) | Bars or path-preserving data still required |

## 6. Drawdown Reconstruction Limits

`drawdown_quality` cannot be reconstructed exactly from one aggregate
`mfe_pct` or `mae_pct` value.

The current rules require price-path information:

- whether price first rose at least 20%
- whether the low later fell to -20% from alert
- whether close later lost at least 40% from the running peak
- whether MAE breached -15% before the tier target was reached

The auxiliary shadow join recovers `mfe_pct` and `mae_pct` for 4,953 exported
rows. Those fields are useful for coarse diagnostics, prioritizing refetches,
and validating future drawdown enrichment. They are not sufficient to assign
authoritative `CLEAN_RUNNER`, `DIRTY_RUNNER`, or `TRAP` labels.

## 7. Recommended Implementation Plan

### P0: Reconstruct Exact Runner Labels From Stored Returns

1. Add a no-bars reconstruction helper to the rocket dataset builder.
2. Apply highest-tier precedence using the matching 1d, 2d, and 5d stored
   return windows.
3. Add an explicit `NON_RUNNER` outcome for complete windows below every
   threshold, or add a separate `is_runner` field so nullable `runner_tier`
   no longer conflates missing labels with non-runners.
4. Add `runner_label_quality` with values such as:
   - `exact_stored_windows`
   - `lower_bound_partial_windows`
   - `bars_exact`
   - `missing`
5. Keep the 43 partial-window positives out of exact multi-class training until
   the missing later windows are resolved.

Expected immediate result: **3,277 exact training examples (11.27%)** without
fetching bars.

### P0: Preserve and Join Historical Resolution Archives

1. Join `shadow_resolved.jsonl` by `record_id` during dataset construction.
2. Persist at-alert shadow snapshots instead of keeping only a rolling
   30,000-row window.
3. Preserve candidate snapshots alongside `candidate_resolved.jsonl`; the
   current rolling candidate registry no longer contains matching IDs.
4. Store absolute forward highs and computed return percentages together so
   future builders do not depend on a second reconstruction pass.

This will recover short-horizon MFE/MAE for 4,953 current exported rows and
prevent future archive joins from being lost as rolling files rotate.

### P1: Repair Forward-Pricing Enrichment

1. Fix the market-data fetch path before rebuilding labels.
2. Re-run enrichment for the 25,520 exported rows with
   `outcome_source=missing`.
3. Persist intraday bars or compact path summaries needed by the drawdown
   rules.
4. Rebuild and re-run this audit after enrichment.

### P1: Gate Any Future ML Work on Coverage

Do not build a new ML architecture yet. Require a refreshed coverage audit
first. At minimum:

- report exact runner-label coverage separately from provisional labels
- report non-runner labels explicitly
- report drawdown quality separately by `intraday_exact` and `daily_proxy`
- retain leakage checks

## 8. Bottom Line

The dataset builder is functioning, but label coverage is the bottleneck.

Without fetching bars, the current export can realistically become:

- **283 exact positive runner tiers**
- **2,994 exact non-runner examples**
- **3,277 exact tier-training examples total (11.27%)**
- **43 additional provisional positive lower-bound tiers**

The correct next engineering step is stored-window label reconstruction and
explicit non-runner encoding, followed by forward-pricing repair for the
remaining rows. New model architecture work should remain paused.
