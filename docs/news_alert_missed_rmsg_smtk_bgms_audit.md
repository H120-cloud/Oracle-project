# News Alert Miss Audit: RMSG / SMTK / BGMS

Date: 2026-06-05

## Scope

Investigated user-reported missed runners:

- `RMSG`
- `SMTK`
- `BGMS`

The goal was to identify where each ticker fell out of the pipeline before applying fixes.

## Evidence From Persisted State

Inspected local persisted files:

- `data/agentic/news_momentum_candidates.json`
- `data/agentic/news_momentum_shadow_alerts.json`
- `data/agentic/news_momentum_telegram_alerts.json`
- `data/agentic/news_momentum_unknown_catalyst_log.json`
- `data/agentic/pre_news_anomalies.json`
- `data/agentic/pre_news_validation.json`
- `data/agentic/pre_news_shadow_v2.json`
- `data/agentic/news_momentum_missed_winners.json`
- `data/agentic/rocket_model_shadow_predictions.jsonl`

Findings:

| Ticker | Persisted evidence | Meaning |
|---|---:|---|
| `SMTK` | 14 shadow rows | It entered News Momentum historically but was blocked. |
| `RMSG` | 0 local rows | It did not enter the local persisted News/Pre-News alert path. |
| `BGMS` | 0 local rows | It did not enter the local persisted News/Pre-News alert path locally; user evidence shows StockTitan carried the catalyst on Railway/current market feed. |

`SMTK` shadow rows repeatedly showed:

- `catalyst_type=other`
- `catalyst_category=unknown`
- `news_impact_score=37.4`
- `expected_return_score=29.x`
- `block_reason=impact_floor(...)`

The older shadow schema did not retain the original headline, but this is still enough to show the failure mode: the ticker was observed, scored as unknown/other, and blocked before Telegram.

## Root Causes Found

### 1. Pre-News Universe Was Too Narrow

The old `DiscoveryEngine` knew about:

- Finviz top gainers
- Finviz most active
- Finviz unusual volume
- Finviz most volatile
- Finviz under-$5 active
- Finviz penny movers

The strategic Pre-News universe after lean refactor only used:

- Finviz top gainers
- Finviz under-$2 high-volume
- StockTwits trending
- PRNewswire / Sharecast / wire tickers
- manual universe

This creates a blind spot for no-news runners that first show up as:

- most active
- unusual volume
- volatile
- under-$5 active
- penny movers

That is the most likely path for `RMSG`-style thin-float/no-news runners and fast movers when the news event is not parsed in time.

### 2. StockTwits Can Disappear For An Hour

`StockTwitsScraper` disables itself for 1 hour on `403`. When that happens, the social-discovery leg of Pre-News can return only cache or nothing.

The broader Finviz universe is now the fallback safety net when StockTwits is blocked.

### 3. SMTK-Style Informal Deal Language Was Under-Covered

The classifier had strong coverage for formal phrases like:

- partnership with
- strategic alliance with
- supply agreement
- clinical supply agreement

But informal market headlines can say:

- landing deal with global electronics giant
- inks deal with major customer
- paid proof-of-concept agreement

Those patterns could fall to `other`, producing low impact and an `impact_floor` block.

### 4. BGMS Exposed A StockTitan Payload Weakness

User-provided StockTitan evidence showed explicit M&A headlines:

- `Bio Green Med plans merger with Malaysia medical-waste innovator Future NRG`
- `Bio Green Med (BGMS) to acquire Future NRG in share exchange; control shifts`

Local replay showed the classifier correctly labels the full text as `corporate/acquisition`. The weak link was not catalyst scoring. It was the news payload:

- `StockTitanScraper` did not accept plain finance-title tickers like `(BGMS)` unless the URL/description also exposed a ticker.
- RSS descriptions were used during extraction, then discarded.
- `main.py` classified only `item.headline`, not the source description/summary.
- Cross-source deduplication could keep an earlier thin item while discarding a later richer source description.
- Duplicate suppression ran before existing-candidate promotion, so a later better-classified headline could be skipped as a duplicate before it upgraded the candidate.

That meant a StockTitan URL shape change, missing `/news/BGMS/` path, or description-only deal language could prevent the candidate from becoming a correctly classified high-conviction M&A event.

### 5. Late No-News Movers Still Need Separate Timing Review

Pre-News intentionally suppresses `ALREADY_EXTENDED` / late-chase detections from Telegram. That avoids chasing after a move, but it can make the system look silent when the only detection happens after the spike.

This is not a Telegram failure. It is a discovery-latency failure.

## Changes Made

### Strategic Finviz Universe Restored

Added strategic helpers in `src/core/agentic/finviz_universe.py`:

- `fetch_finviz_most_active_tickers`
- `fetch_finviz_unusual_volume_tickers`
- `fetch_finviz_most_volatile_tickers`
- `fetch_finviz_under5_active_tickers`
- `fetch_finviz_penny_mover_tickers`

Wired them into `PreNewsDetector._get_universe()` with modest per-source caps:

- `PRE_NEWS_FINVIZ_ACTIVE_LIMIT`
- `PRE_NEWS_FINVIZ_UNUSUAL_VOLUME_LIMIT`
- `PRE_NEWS_FINVIZ_MOST_VOLATILE_LIMIT`
- `PRE_NEWS_FINVIZ_UNDER5_ACTIVE_LIMIT`
- `PRE_NEWS_FINVIZ_PENNY_LIMIT`

Defaults are `30` each.

### SMTK Classifier Coverage Added

Added high-conviction major-partnership patterns for:

- `lands/landing/inks/signs/secures deal with global/major/leading/tier-1`
- `global/major electronics/technology/semiconductor/display customer/deal`
- `paid proof-of-concept agreement`
- `proof-of-concept agreement with global/major/leading/tier-1`

### BGMS / StockTitan Feed Hardening Added

Changed `StockTitanScraper` to:

- accept plain parenthesized finance tickers like `(BGMS)` for StockTitan RSS titles
- preserve cleaned RSS `description` on `FinvizNewsItem`
- run sentiment on headline + description

Changed PRNewswire and supplemental wire parsing to:

- use the same high-confidence finance-source `(TICKER)` extraction path
- keep exchange-name parentheticals like `(NASDAQ)` / `(NYSE)` filtered as noise
- preserve full wire item text in `description` for classification

Changed global news event construction to:

- classify using `headline + description + summary`
- preserve the original headline for Telegram/user-facing copy
- store the combined classifier payload in `NewsEvent.raw_text`

Changed News Momentum candidate handling to:

- carry `raw_text` from `NewsEvent` to `NewsMomentumCandidate`
- merge richer duplicate metadata during dedup instead of discarding it
- allow duplicate-looking events through when they upgrade an existing candidate or carry richer source text
- merge richer source text into existing candidates before refresh/rescore

Added M&A coverage for:

- `share-for-share exchange`
- `all-stock share exchange`
- `share exchange`
- `wholly owned unit/subsidiary`

### Regression Tests Added

Added:

- `test_pre_news_universe_includes_broad_strategic_finviz_sources`
- `smtk_global_electronics_deal_001` historical classifier fixture
- `test_stocktitan_extracts_bgms_plain_parentheses_and_preserves_description`
- `test_prnewswire_extracts_plain_parentheses_ticker_from_finance_listing`
- `test_wire_feed_extracts_plain_parentheses_and_preserves_full_description`
- `test_merges_richer_duplicate_metadata_for_classification`
- `test_duplicate_event_can_refresh_when_it_upgrades_existing_candidate`
- `test_duplicate_event_stays_suppressed_when_it_adds_nothing`

## Verification

Focused tests:

```text
100 passed, 1 xfailed
```

Full backend test suite:

```text
383 passed, 1 xfailed
```

The single xfail is the existing `lnks_004_neg` semantic-classifier target, unrelated to this work.

## Remaining Risks

These fixes reduce the blind spot but do not guarantee every no-news runner will be caught before it moves.

Remaining risk areas:

- Finviz can still lag or block scraping.
- StockTwits can still block with `403`.
- Some after-hours movers may not appear in Finviz strategic screens until after extension.
- News articles with company names but no ticker/exchange text are still intentionally ignored to avoid false ticker extraction.
- Runners with no visible catalyst require market-wide mover discovery, not just news ingestion.

## Recommended Next Step

Add a dedicated market-mover sentinel that records the first time any ticker appears in a broad mover source, then compares price at first sight vs. Telegram-alert time.

This should feed the Timing Intelligence database so the frontend can show:

- missed because not in universe
- missed because source/parser failed
- detected but suppressed as late
- detected early but score/gate blocked
- detected and alerted on time
