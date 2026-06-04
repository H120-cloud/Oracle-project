# Oracle Reliability + Latency Upgrade

## What Changed

This upgrade improves alert delivery reliability and removes avoidable latency from news processing without changing alert scoring, gating thresholds, Telegram alert formatting, production trading behavior, Pre-News scoring, SEC scoring, or Rocket CatBoost shadow scoring.

## Telegram Persistent Outbox

Failed Telegram sends are now persisted to:

`data/agentic/telegram_outbox.jsonl`

Each record stores `alert_id`, `ticker`, `alert_type`, `message`, `created_at`, `status`, `attempts`, `last_error`, `next_retry_at`, `telegram_response`, and `priority`.

The sender now:

- enqueues failed sends after timeout, network, or Telegram API errors
- respects Telegram `429 retry_after`
- retries with exponential backoff
- dead-letters after repeated failures
- protects against duplicate `alert_id`
- drains in a background loop without blocking news scanning
- writes the outbox atomically so restart/crash does not lose pending alerts

## Global News Immediate Scan

The News Momentum scan now processes global Finviz, StockTitan, and other global headlines immediately before ticker-specific Finviz quote-page enrichment.

Old behavior:

`global news fetch -> ticker enrichment for up to 30 tickers -> orchestrator scan`

New behavior:

`global news fetch -> orchestrator scan immediately -> bounded ticker enrichment -> second orchestrator scan`

Ticker enrichment is still used, but it has `FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS` and per-ticker `asyncio.wait_for` timeouts, so global alerts do not wait behind slow quote pages.

## First-Mover Freshness Logic

First-mover rescue now requires both:

- fresh `published_at`
- fresh `detected_at`

If `published_at` is missing, the candidate does not qualify for first-mover rescue and receives `freshness_confidence = LOW`.

Candidates now carry:

- `published_age_seconds`
- `detected_age_seconds`
- `freshness_confidence`

This prevents an old headline discovered late from being treated as breaking news.

## Non-Blocking Market Data Enrichment

Primary market-data provider calls and Polygon fallback calls now run behind `asyncio.to_thread` with a per-candidate latency budget.

If pricing is slow:

- the scan continues
- the candidate remains evaluable
- `price_status = pending`

If price data arrives within budget:

- `price_status = complete`

If no price is available and no timeout occurred:

- `price_status = missing`

The default per-candidate budget is controlled by `NEWS_MARKET_DATA_CANDIDATE_BUDGET_SECONDS`.

## SEC Firehose Content Enrichment

SEC 8-K firehose events now attempt lightweight content enrichment from the filing page.

When content is available, the system builds more specific SEC headlines for:

- financing / dilution
- M&A / acquisition
- Nasdaq compliance / delisting
- balance-sheet improvement

If filing content is unavailable, it safely falls back to the previous generic headline:

`Company filed SEC Form 8-K`

## Source-Health Alerts

Source health is tracked per parser/source:

- headlines fetched
- missing timestamp count
- parse error count
- dropped headline count
- last successful parse time

Warnings are logged and sent as admin Telegram health alerts when:

- missing timestamp rate spikes
- a source becomes stale

Cooldown logic prevents normal parser activity from spamming alerts.

## Pre-News Bounded Concurrency

Pre-News ticker analysis now runs with bounded concurrency around the existing `_analyze_ticker` scoring path.

Controls:

- `PRE_NEWS_MAX_CONCURRENT_ANALYSES`
- `PRE_NEWS_PER_TICKER_TIMEOUT_SECONDS`
- `PRE_NEWS_SCAN_BUDGET_SECONDS`

Slow or stuck tickers are cancelled safely and do not kill the full scan. The scoring logic itself is unchanged.

## Tests Added

Focused tests cover:

- Telegram timeout retry
- Telegram `429 retry_after`
- failed-then-success retry
- dead-letter behavior
- duplicate alert ID handling
- no alert loss on send exception
- global headline scan before ticker enrichment
- ticker enrichment timeout budget
- old published headline blocked from first-mover rescue
- fresh published + fresh detected first-mover eligibility
- missing `published_at` freshness confidence
- slow market data returning `price_status = pending`
- fast market data returning `price_status = complete`
- SEC financing/M&A/fallback enrichment
- source-health missing timestamp and stale-source warnings
- Pre-News concurrency limit and timeout survival

Focused verification result:

`26 passed`

## Remaining Risks

- A background thread used by `asyncio.to_thread` can still finish after a timeout, but it no longer blocks the active async scan path.
- SEC content enrichment depends on SEC page availability and remains best-effort.
- Source-health alerts use aggregate counters; if a source intermittently breaks and recovers quickly, it may only appear in logs.
- Ticker-specific Finviz enrichment is now bounded, so rare quote-page-only headlines may arrive in the second scan pass or a later cycle if the budget is exhausted.
