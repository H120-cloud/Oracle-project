# News Timestamp Safety Fix

## Goal

Prevent any news or secondary catalyst flow from treating an unknown or low-confidence publication time as fresh.

## Rule

If a news item has no reliable timestamp, it must not qualify for:

- first-mover rescue
- fast WATCH
- freshness boost
- Telegram alert based on freshness

Missing timestamps may be logged or skipped, but they must not be replaced with the current clock time.

## Changes

### CatalystScanner

`src/core/agentic/catalyst_scanner.py`

- Removed all `item.timestamp or datetime.now(timezone.utc)` fallbacks.
- Drops news items with `timestamp is None`.
- Keeps date-only/low-confidence items trackable, but assigns `freshness = 0.0`.
- Preserves the original `item.timestamp` as `discovered_at`.

### WireNews

`src/core/wire_news.py`

- Added timestamp confidence parsing.
- Timestamps with an explicit time are marked `HIGH`.
- Date-only timestamps are marked `LOW`.
- Missing/unparseable timestamps remain missing/unknown.

### SEC Firehose

`src/core/agentic/sec_edgar_firehose.py`

- Invalid or missing Atom `<updated>` timestamps now return `None`.
- Filings without a reliable timestamp are skipped and marked seen to avoid repeated malformed processing.
- Internal SEC headline enrichment no longer uses current time as a fallback filing date.

### Historical/Missed Learning

`src/core/agentic/historical_dataset_builder.py`

- Historical events with no timestamp keep `catalyst_timestamp = None`.
- Their `event_date` remains empty.
- Their `data_quality` is downgraded to `PARTIAL`.

`src/core/agentic/news_momentum_missed_learning.py`

- Missed-winner records no longer invent `news_time = now` when `published_at` is missing.
- They use the candidate detection time only as a non-publication fallback.

## Tests Added

`tests/unit/test_timestamp_safety.py`

Covers:

- missing timestamp does not become fresh in `CatalystScanner`
- old timestamp is not refreshed by detection time
- date-only wire timestamp has `LOW` confidence
- missing timestamp cannot trigger first-mover
- missing timestamp cannot trigger fast WATCH
- old timestamp cannot trigger first-mover via fresh detection
- SEC firehose skips missing `<updated>` timestamps
- historical dataset does not fabricate catalyst timestamps

## Verification

Focused timestamp suite:

```text
8 passed
```

## Remaining Notes

The primary News Momentum scan in `src/main.py` was already safe before this change:

- missing timestamps are dropped
- stale timestamps are dropped by the configured max-age cutoff
- `published_at` is passed from the scraper item directly

This fix closes the remaining secondary paths so they follow the same safety rule.
