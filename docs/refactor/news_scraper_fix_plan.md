# News Scraper Fix Plan

**Author:** Cascade AI
**Date:** 2026-05-28
**Scope:** `src/core/finviz_news.py`, `src/core/stocktitan_news.py`, downstream consumers
**Status:** Approved for implementation

---

## 1. Problem Statement

The news scraper system (Finviz HTML + Stock Titan RSS) has five high-priority defects identified during audit:

1. **Timezone mislabeling** — Finviz timestamps are US/Eastern but tagged as UTC, causing 4–5 hour freshness errors.
2. **Month-boundary crash** — `_parse_time()` uses `now.day-1` which raises `ValueError` on the 1st of each month.
3. **No HTTP retry** — Single-request-per-fetch with no backoff; transient 503/429 errors cause complete scan failures.
4. **No cross-source deduplication** — Same press release on Finviz + Stock Titan generates duplicate `NewsEvent` objects.
5. **Scraper instances recreated per scan loop** — 5-minute in-memory cache is effectively disabled because fresh instances are created every iteration.

---

## 2. Fix Specification

### 2.1 Fix: Timezone Handling (ET → UTC)

**File:** `src/core/finviz_news.py`
**Change:**
- Import `zoneinfo` (stdlib, Python 3.9+).
- Define `_ET = zoneinfo.ZoneInfo("America/New_York")`.
- In `_parse_time()`: parse as ET naive, attach `_ET`, then `.astimezone(timezone.utc)`.
- In `_parse_quote_timestamp()`: same pattern.
- In `StockTitanScraper._parse_rss()`: if `parsedate_to_datetime` returns naive, assume ET and convert.

**Rollback:** Revert the two methods to their current form.

**Test:** Unit test with a known Finviz timestamp string; assert UTC output equals expected ET→UTC conversion.

### 2.2 Fix: Month-Boundary Bug

**File:** `src/core/finviz_news.py`
**Change:**
- Replace `now.replace(day=now.day-1, ...)` with `(now - timedelta(days=1)).replace(...)`.

**Rollback:** Single-line revert.

**Test:** Unit test with `now = datetime(2026, 05, 01, ...)`; assert output is April 30.

### 2.3 Fix: HTTP Retry with Exponential Backoff

**File:** `src/core/finviz_news.py`, `src/core/stocktitan_news.py`
**Change:**
- Add `_fetch_with_retry()` helper in `finviz_news.py`:
  - 3 retries max
  - Backoff: 1s → 2s → 4s
  - Retry on: `httpx.HTTPStatusError` (5xx, 429), `httpx.TimeoutException`, `httpx.ConnectError`
  - Do NOT retry on 4xx (client errors)
- Use `_fetch_with_retry()` in `_get()` and `_parse_rss()`.
- Log each retry attempt at `WARNING` level.

**Rollback:** Replace `_fetch_with_retry()` calls with direct `client.get()`.

**Test:** Mock `httpx.Client.get()` to fail twice then succeed; assert retry count and final result.

### 2.4 Fix: Cross-Source Deduplication

**File:** `src/core/agentic/news_momentum_utils.py` (new utility)
**Change:**
- Add `deduplicate_news_items(items: List[FinvizNewsItem]) -> List[FinvizNewsItem]`:
  - Normalize headline: lowercase, strip whitespace, remove `" | TICKER Stock News"` suffix.
  - Keep the item with the **earliest** timestamp (most original source).
  - If timestamps equal, prefer Finviz over Stock Titan.
- Update `src/main.py:_news_momentum_scan_loop()` to call dedup after collecting from both sources.
- Update `src/core/agentic/catalyst_scanner.py:scan()` to call dedup.
- Update `src/core/agentic/pre_news_detector.py:_fetch_news_batch()` to call dedup.

**Rollback:** Remove dedup calls from consumers; delete `news_momentum_utils.py` if it contains only this function.

**Test:** Create two `FinvizNewsItem` with same headline but different sources/timestamps; assert only earliest survives.

### 2.5 Fix: Reuse Scraper Instances in Scan Loops

**File:** `src/main.py`
**Change:**
- Move `FinvizNewsScraper()` and `StockTitanScraper()` instantiation **outside** the `while True` loop.
- Reuse the same instances across iterations so the 5-minute cache actually works.

**File:** `src/core/agentic/pre_news_detector.py`
**Change:**
- Store scraper instances as class attributes in `PreNewsDetector.__init__()`.
- Reuse in `_fetch_news_batch()`.

**Rollback:** Move instantiation back inside the loop / method.

**Test:** Not directly testable, but verify via logging that cache hits increase.

---

## 3. Dependency Impact

| Dependency | Change | Risk |
|------------|--------|------|
| `zoneinfo` | New import (stdlib) | Zero — Python 3.9+ only |
| `httpx` | No change | Zero |
| `beautifulsoup4` | No change | Zero |
| `tenacity` | **Not used** — hand-rolled retry to avoid new dep | Zero |

**No new external dependencies.**

---

## 4. Testing Plan

1. **Unit tests** in `tests/unit/test_finviz_news.py`:
   - `test_parse_time_yesterday_crosses_month_boundary`
   - `test_parse_time_et_to_utc_conversion`
   - `test_fetch_with_retry_succeeds_after_two_failures`
   - `test_fetch_with_retry_does_not_retry_404`
2. **Unit tests** in `tests/unit/test_news_dedup.py`:
   - `test_deduplicate_keeps_earliest_timestamp`
   - `test_deduplicate_prefers_finviz_on_tie`
   - `test_deduplicate_normalizes_headlines`
3. **Regression test:** `python -m pytest tests/unit/ -x`
4. **Smoke test:** Run a single news momentum scan loop iteration manually and verify log output.

---

## 5. Rollback Strategy

All changes are additive or localized:
- Revert individual files via git.
- If a single fix causes issues, revert that file only; others remain.
- No database schema changes or data migrations required.

---

## 6. Sign-Off

| Item | Status |
|------|--------|
| Plan reviewed | ✅ Owner (Cascade AI) |
| No new deps | ✅ Confirmed |
| Tests specified | ✅ 6 tests defined |
| Rollback safe | ✅ File-level revert |
| Implementation approved | ✅ Proceed |
