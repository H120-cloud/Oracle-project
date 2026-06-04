# Rocket Label Reconstruction Report

## Scope

Deterministic no-fetch reconstruction from existing historical outcome fields.
The original exports were not overwritten. No market data was fetched and no ML models were built.

## Coverage Summary

| Metric | Rows | % of Examined Rows |
|---|---:|---:|
| Rows examined | 29,085 | 100.00% |
| Existing runner labels | 21 | 0.07% |
| Exact labels available after reconstruction | 3,277 | 11.27% |
| Exact labels added | 3,256 | 11.19% |
| Exact positive runners | 283 | 0.97% |
| Exact non-runners | 2,994 | 10.29% |
| Provisional positive labels | 43 | 0.15% |
| Remaining unlabeled rows | 25,765 | 88.59% |
| Maximum positives with provisional labels | 326 | 1.12% |

Coverage improved from **21** existing runner labels to **3,277** exact training-ready rows.

## Final Runner Distribution

| Label | Rows |
|---|---:|
| `LEGENDARY_RUNNER` | 10 |
| `MAJOR_RUNNER` | 40 |
| `MONSTER_RUNNER` | 11 |
| `NON_RUNNER` | 2,994 |
| `PROVISIONAL_MAJOR_RUNNER` | 3 |
| `PROVISIONAL_STANDARD_WIN` | 40 |
| `STANDARD_WIN` | 222 |
| `UNKNOWN` | 25,765 |

## Confidence Breakdown

| Confidence | Rows |
|---|---:|
| `HIGH` | 3,277 |
| `LOW` | 25,765 |
| `MEDIUM` | 43 |

## Label Source Breakdown

| Source | Rows |
|---|---:|
| `existing_runner_tier` | 21 |
| `insufficient_evidence` | 25,765 |
| `reconstructed_exact` | 3,256 |
| `reconstructed_provisional` | 43 |

## Rule IDs

- `exact_complete_windows_below_thresholds`: 2,994
- `exact_next_day_move_at_least_10`: 222
- `exact_two_day_move_at_least_30`: 40
- `existing_trusted_runner_tier`: 21
- `no_audited_outcome_fields`: 25,520
- `partial_windows_below_observed_thresholds`: 245
- `provisional_next_day_move_at_least_10`: 40
- `provisional_two_day_move_at_least_30`: 3

## Limitations

- Drawdown quality is not reconstructed because aggregate returns do not preserve price paths.
- Provisional labels are lower bounds and must remain separate from exact training labels.
- Rows without complete audited windows cannot receive exact NON_RUNNER labels.
- No external market data was fetched.
- No ML models were trained or introduced.

## Next Recommended Step

Repair forward-pricing enrichment for rows that remain unknown, preserve path data for drawdown labels, and rerun the coverage audit before any ML training.
