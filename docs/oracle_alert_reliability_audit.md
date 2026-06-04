# Oracle Alert Reliability Audit

Date: 2026-06-04

## Scope

Reviewed the live alert path for failure modes that could cause:

- late reminders after a catalyst move already happened
- repeat alerts after restart/redeploy
- old headlines being treated as fresh
- Telegram delivery failures causing lost or duplicated alerts
- Pre-News alerts repeating while Telegram is unavailable

Strategic systems checked:

- News Momentum alert gate
- Bullish catalyst flash path
- Telegram persistent outbox
- Pre-News alert send loop
- SEC firehose startup dedupe
- News source ticker extraction and timestamp handling

## Findings And Fixes

### 1. High-conviction late-chase bypass was too broad

`high_conviction` catalysts were allowed to bypass late-chase and daily ticker caps even when the stock had already made a large move. This could create the exact bad behavior where an old catalyst later reappears as a reminder after the run.

Fix:

- High-conviction catalysts only bypass late-chase when both published and detected ages are recent.
- Added `high_conviction_late_chase_max_age_seconds = 900`.
- Stale high-conviction candidates above the chase cap are now blocked as `late_chase`.

Regression coverage:

- stale +140% high-conviction move is blocked
- fresh high-conviction catalyst before extension still alerts

### 2. Bullish flash used detected freshness only

The fast bullish-flash path checked `detected_at`, but not `published_at`. An old headline discovered late could therefore look fresh and bypass slower gates.

Fix:

- Bullish flash now requires both `published_at` and `detected_at` to be fresh.
- Missing publish time cannot qualify for bullish flash.
- Future-dated timestamps are blocked.

Regression coverage:

- old published headline detected now does not flash
- missing `published_at` does not flash
- fresh bullish flash still works

### 3. Telegram outbox delivery-pending state did not set cooldowns

If a News Momentum alert was approved but direct Telegram send failed, the message was queued to the durable outbox. However, the candidate cooldown was not set until direct send success. That left room for repeated attempts while the outbox was also retrying.

Fix:

- Direct send failure now sets ticker and headline cooldowns as delivery-pending.
- Cooldowns and candidates are persisted immediately.
- The outbox still owns retry/delivery; scoring and Telegram content are unchanged.

Regression coverage:

- failed Telegram send sets cooldown and headline cooldown
- successful send still records learning even if learning persistence fails

### 4. Pre-News alert send loop had the same pending-delivery gap

Pre-News only marked an anomaly alerted after direct Telegram success. During Telegram/API outage, the same anomaly could be queued repeatedly.

Fix:

- Pre-News anomaly alerts now use deterministic `alert_id`.
- Pre-News marks alert state once the message is handed to Telegram/outbox.
- News-confirmation alerts now use deterministic `alert_id` and mark confirmation state once handed to Telegram/outbox.

Production behavior unchanged:

- Telegram message content unchanged.
- Pre-News scoring unchanged.
- Alert gating unchanged except duplicate/pending-delivery suppression.

## Areas Checked With No New Blocking Issue Found

### SEC firehose startup

The current logic emits fresh first-poll filings within the configured lookback and only seeds older filings. This protects against the prior VERU-style startup miss.

### Source ticker extraction

Shared ticker extraction is in place for StockTitan, PRNewswire, Sharecast, and wire sources. Existing tests cover the StockTitan `Veru (NASDAQ: VERU)` style.

### Telegram outbox

The outbox has duplicate `alert_id` protection, retry/backoff, 429 `retry_after` handling, dead-letter behavior, and atomic writes.

### Self-learning / shadow systems

Strategic learning systems are still present:

- Adaptive Telegram learning
- News Momentum outcome resolver
- News Momentum shadow logger
- Missed-runner/shadow adjustment learning
- Pre-News learning
- Pre-News shadow V2
- NewsImpactLearning
- Rocket CatBoost shadow scoring

No production alert scoring was replaced by the Rocket model.

## Verification

Commands run:

- `pytest tests/unit/test_bullish_catalyst_flash.py tests/unit/test_news_momentum_alert_flow.py tests/regression/test_alert_gate_end_to_end.py tests/unit/test_telegram_outbox.py tests/unit/test_pre_news_validation.py -q`
- `pytest tests/unit/test_news_ticker_extractor.py tests/unit/test_stocktitan_news.py tests/unit/test_sec_firehose_enrichment.py tests/regression/test_classifier_historical_misses.py tests/unit/test_news_momentum_scan_order.py tests/unit/test_news_momentum_timezones.py tests/unit/test_source_health.py tests/unit/test_bullish_catalyst_flash.py tests/unit/test_news_momentum_alert_flow.py -q`
- `py_compile src/main.py src/core/agentic/bullish_catalyst_flash.py src/core/agentic/news_momentum_orchestrator.py`
- `pytest -q`

Results:

- Focused alert/delivery tests: 35 passed
- Missed-alert/source regression suite: 96 passed, 1 known xfail
- Full backend suite: 366 passed, 1 known xfail

## Remaining Risks

- External source latency can still beat the system if a source publishes late or omits timestamps.
- Vague headlines like "Corporate Update" still need volume/anomaly systems to catch hidden catalysts.
- Telegram can still dead-letter after repeated failures; the outbox prevents silent loss, but credentials and chat ID must be valid.
- If all market-data providers are unavailable, price-aware scoring may degrade to no-price/fallback behavior.

## Verdict

The specific late-reminder class is fixed in both first-mover/high-conviction and bullish-flash paths.

The largest duplicate-delivery risk during Telegram outages is now bounded by persisted cooldowns and deterministic outbox alert IDs.
