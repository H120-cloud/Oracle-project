# Timestamp Migration Plan — Finviz Scraper Timezone Fixes

## Problem

`FinvizNewsScraper._parse_time()` and `_parse_quote_timestamp()` historically treated raw US/Eastern times from Finviz HTML as UTC without conversion. This caused scraped news timestamps to be off by 4–5 hours depending on DST.

StockTitan RSS timestamps were unaffected (RSS provides explicit UTC `pubDate`).

## Affected Record Count

| File | Total Records | Potentially Affected |
|------|--------------|----------------------|
| `data/agentic/pre_news_anomalies.json` | 50 | 33 (finviz-derived `first_news_timestamp` / `matched_headline_time`) |
| `data/agentic/news_momentum_event_registry.json` | 237 | 3 (finviz events where `published_at != detected_at`) |
| `data/agentic/news_momentum_backfill_records.json` | 3,352 | 0 (`sent_at` is server-generated alert time) |
| `data/agentic/pre_news_evaluation_snapshots.json` | 175 | 0 (server-generated `detected_at`) |

**Total truly affected: ~36 records** (small volume, JSON files, no DB).

## Chosen Strategy: B — Lazy Conversion + Schema Versioning

### Rationale

- **Cannot re-scrape**: Old Finviz news pages are ephemeral; we cannot retrieve the original HTML to re-parse correct timestamps.
- **Small blast radius**: Only ~36 records are affected. An in-place rewrite (Strategy A) is technically feasible but offers limited value because we lack ground-truth data to rewrite with.
- **Operational simplicity**: JSON files are append-only in practice. Rewriting them in-place risks corrupting concurrent writes from the running scanner loops.
- **Forward correctness**: The scraper fix ensures all *new* records will have correct UTC timestamps.

### Implementation

1. **Schema version flag**: All persistence models that store scraper-derived timestamps now include a `timestamp_schema_version` field (default `"2.0"` for new writes, missing/implicit `"1.0"` for legacy records).
2. **Read-path normalization**: When loading legacy records (`schema_version != "2.0"`), consumers that perform time-critical calculations (e.g., `time_gap_minutes`, `catalyst_age_minutes`) should re-derive the timestamp from the stored headline via `_check_news_status` on the next scan cycle. The pre-news detector’s `update_news_status()` already re-fetches news and updates `first_news_timestamp` — this serves as a natural lazy migration path.
3. **No forced rewrite**: Existing records remain in place. Any analytics that depend on exact historical `first_news_timestamp` should filter to `schema_version == "2.0"` or treat pre-fix timestamps with a ±5h confidence band.

### Files to Update for Schema Versioning

- `src/core/agentic/pre_news_models.py` — add `timestamp_schema_version: str = "2.0"` to `PreNewsAnomaly`
- `src/core/agentic/news_momentum_models.py` — add `timestamp_schema_version: str = "2.0"` to `NewsMomentumEvent` / `NewsMomentumCandidate`

## What Was Fixed in Code

- `src/core/finviz_news.py::_parse_time` — now parses ET then converts to UTC via `astimezone()`
- `src/core/finviz_news.py::_parse_quote_timestamp` — full-date branch already used `_ET`; **Today/Yesterday branch was also fixed** to use `datetime.now(_ET)` and convert via `astimezone()`
- `src/core/stocktitan_news.py` — already correct (RSS `pubDate` is reliable)

## Verification

- `tests/unit/test_finviz_news.py` — verifies `_parse_time` ET→UTC conversion and month-boundary safety
- `tests/unit/test_finviz_news.py::TestQuoteTimestamp` — verifies `_parse_quote_timestamp` Today/Yesterday and full-date branches
