# Rocket Synthetic Ticker Audit

## Scope

This audit checks Rocket dataset inputs and derived exports for reserved
synthetic ticker patterns:

- `GREAT###`
- `GOOD###`
- `TEST###`
- `FAKE###`
- `MOCK###`
- `SAMPLE###`
- `DEMO###`
- `LATE###`
- `TRAP###`

The matching rule is case-insensitive and requires one or more digits after
the reserved prefix. Real symbols such as `GOOD`, `GREATNESS`, and `DEMO-A`
are not rejected.

## Findings

| Metric | Value |
|---|---:|
| Unique synthetic tickers found | 350 |
| Synthetic source rows found | 350 |
| Matching `GOOD###` tickers | 100 |
| Matching `GREAT###` tickers | 100 |
| Matching `LATE###` tickers | 50 |
| Matching `TRAP###` tickers | 100 |
| Synthetic ticker/date groups encountered by forward enrichment | 250 |
| Terminal synthetic group failures recorded | 250 |
| Wasted provider-level fetch attempts recorded | 3,000 |

The failure ledger records `3,000` provider-level attempts for synthetic
symbols. This is a conservative lower bound for wasted upstream requests:
provider clients may perform internal retries, and authenticated URL logging
is intentionally suppressed, so the exact HTTP request total is not
recoverable from the stored logs.

## Affected Source Files

| Source file | Rows scanned | Synthetic rows | Unique synthetic tickers |
|---|---:|---:|---:|
| `data/agentic/news_momentum_telegram_alerts.json` | 11,869 | 350 | 350 |
| `data/agentic/news_momentum_shadow_alerts.json` | 30,000 | 0 | 0 |
| `data/agentic/news_momentum_backfill_records.json` | 3,352 | 0 | 0 |
| `data/agentic/news_momentum_missed_winners.json` | 121 | 0 | 0 |
| `data/agentic/pre_news_shadow_v2.json` | 185 | 0 | 0 |

The contamination originates from the historical Telegram alert source. No
real ticker records were modified or deleted.

## Derived Export Contamination

| Derived export | Rows scanned | Synthetic rows present |
|---|---:|---:|
| `data/agentic/rocket_training_dataset.csv` | 29,085 | 350 |
| `data/agentic/rocket_training_dataset.parquet` | 29,085 | 350 |
| `data/agentic/rocket_training_dataset_reconstructed.csv` | 29,085 | 350 |
| `data/agentic/rocket_training_dataset_reconstructed.parquet` | 29,085 | 350 |
| `data/agentic/rocket_training_dataset_reconstructed_v2_final_smoke.csv` | 29,085 | 350 |
| `data/agentic/rocket_training_dataset_reconstructed_v2_final_smoke.parquet` | 29,085 | 350 |

Synthetic tickers did enter the prior Rocket exports. The full V2 export had
not yet been written when the audit was performed.

## Integrity Filter

A centralized ticker-integrity utility now:

1. Identifies reserved synthetic ticker patterns.
2. Marks rejected rows with
   `rejection_reason = "synthetic_test_ticker"`.
3. Rejects synthetic rows during Rocket dataset assembly.
4. Excludes synthetic rows before historical market-data provider calls.
5. Excludes synthetic rows from reconstructed V2 exports and ML training
   readiness counts.
6. Writes excluded legacy rows to separate
   `*_synthetic_rejections.csv` and `*_synthetic_rejections.parquet`
   sidecars for traceability.

Original source files and previous Rocket exports remain unchanged.

## Resume Impact

The paused `full_v1` run preserved its cache and checkpoint:

| Metric | Value |
|---|---:|
| Cached completed real ticker/date groups | 1,966 |
| Original ticker/date groups including synthetic rows | 4,366 |
| Original unknown rows including synthetic rows | 25,740 |
| Synthetic groups excluded from future fetches | 350 |
| Synthetic unknown rows excluded from training | 350 |
| Eligible real unknown rows after filtering | 25,390 |
| Eligible real ticker/date groups after filtering | 4,016 |
| Real groups remaining after resume | 2,050 |

The full enrichment run can safely resume from the existing checkpoint
without clearing cache or refetching completed real ticker/date groups.
