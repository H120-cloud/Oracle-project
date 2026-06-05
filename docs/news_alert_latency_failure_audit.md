# News Alert Latency Failure Audit

Generated: 2026-06-05

## Executive Summary

The biggest confirmed latency root cause was inside the News Momentum orchestrator:
`_process_event()` created a candidate, then waited for market-data enrichment before
the candidate could be scored, gated, and sent to Telegram.

That means a high-impact headline could be fetched and classified quickly, but still
sit behind quote providers, Polygon fallback, and yfinance fallback before the user
saw anything.

Fix added: a verified high-impact fast WATCH path now runs immediately after candidate
creation and before market-data enrichment. The normal scoring/gating/full alert path
still runs afterward.

## New Latency Trace

Trace file:

`data/agentic/news_alert_latency_trace.jsonl`

Each trace row records:

- `ticker`
- `headline`
- `source`
- `published_at`
- `fetched_at`
- `parsed_at`
- `candidate_created_at`
- `classified_at`
- `scored_at`
- `gate_decision_at`
- `telegram_enqueue_at`
- `telegram_sent_at`
- `blocked_reason`
- `latency_seconds_from_published_to_fetch`
- `latency_seconds_from_fetch_to_gate`
- `latency_seconds_from_gate_to_telegram`
- `total_latency_seconds`
- `alert_sent`

Code locations:

- Trace writer: `src/core/agentic/news_alert_latency_trace.py`
- Event timing fields: `src/core/agentic/news_momentum_models.py`
- Source fetch/parse/classification timestamps: `src/main.py`
- Candidate creation/scoring/gate/Telegram timestamps: `src/core/agentic/news_momentum_orchestrator.py`

## Alert Path Now Traced

Pipeline:

1. Source publishes headline: `published_at`
2. Source scanner returns items: `fetched_at`
3. Parser output is available: `parsed_at`
4. Classifier finishes: `classified_at`
5. Candidate is created: `candidate_created_at`
6. Scores are computed: `scored_at`
7. Telegram gate decides: `gate_decision_at`
8. Telegram send/outbox attempt starts: `telegram_enqueue_at`
9. Telegram confirms send: `telegram_sent_at`

Blocked candidates are also traced with `blocked_reason`, so misses can be separated
into stale timestamp, duplicate/cooldown, score/gate block, or Telegram delivery.

## Emergency Fast WATCH Path

Implemented in `src/core/agentic/news_momentum_orchestrator.py`.

Fast WATCH eligibility requires:

- Verified source: StockTitan, Alpaca/Benzinga, SEC, GlobeNewswire, BusinessWire,
  PRNewswire, Accesswire, Newsfile, Company Press, or Finviz.
- Fresh `published_at`.
- Fresh `detected_at`.
- High timestamp confidence.
- Not negative.
- Not vague.
- High-impact catalyst type.

High-impact catalyst examples covered:

- FDA approval / clearance / NDA approval / PDUFA
- Phase 2 / Phase 3 / topline data
- Merger / acquisition / buyout
- Government contract / hyperscaler contract / supply agreement / OEM partnership
- AI / Nvidia / OpenAI partnership
- Earnings beat / guidance raise / profitability inflection
- Nasdaq/listing compliance regained
- Warrant overhang removal
- Positive financing / debt restructuring rescue

Behavior:

1. Candidate is created immediately.
2. Fast WATCH Telegram alert is attempted immediately.
3. Market-data enrichment runs afterward.
4. Existing scoring and production Telegram gate still run afterward.

This does not promote the CatBoost shadow model and does not change normal production
scoring logic.

## Source Scanner Audit

Current scan settings:

- News loop interval: `NEWS_MOMENTUM_SCAN_INTERVAL = 45` seconds in `src/main.py`.
- Global source fetch timeout: `NEWS_SOURCE_FETCH_TIMEOUT_SECONDS`, default `12`.
- Finviz ticker enrichment budget: `FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS`, default `6`.
- Per-candidate market-data budget: `NEWS_MARKET_DATA_CANDIDATE_BUDGET_SECONDS`, default `8`.
- First-mover max age: `300` seconds.
- News freshness window: `12` hours.
- Telegram ticker cooldown: `1080` minutes.

Global sources are fetched concurrently. Finviz ticker-page enrichment happens after
the global scan, so global headlines are not blocked by up to 30 ticker page fetches.

The remaining confirmed pre-fix delay was candidate market-data enrichment before
the first Telegram decision. Fast WATCH addresses that for verified high-impact news.

## Gate Blocking Reasons

Local shadow log inspected:

`data/agentic/news_momentum_shadow_alerts.json`

Top observed block reasons in the local shadow file:

| Count | Reason |
|---:|---|
| 2095 | `impact_floor(39.9<50.0)` |
| 772 | `impact_floor(39.9<45.0)` |
| 201 | `impact_floor(42.4<45.0)` |
| 103 | `no_price` |
| 96 | `impact_floor(43.5<45.0)` |
| 89 | `impact_floor(42.4<50.0)` |
| 70 | `score_gate(imp=53.4/50,ret=46.3/55)` |
| 37 | `ticker_cooldown` |
| 28 | `ml_hard_floor(win=0.12)` |
| 21 | `ml_veto(win=0.34)` |

Interpretation:

- The main local block family is impact/score floors.
- `no_price` is still visible historically; fast WATCH now prevents high-impact fresh
  catalysts from waiting on price enrichment before the first WATCH.
- `ticker_cooldown` can still suppress repeat alerts. That is intentional for normal
  alerts but should be watched in the latency trace when a materially new catalyst
  appears for the same ticker.
- Local shadow data contains historical/test/synthetic records, so the new latency
  trace should be considered the source of truth after Railway has run with this build.

## Duplicate / Freshness Audit

Duplicate logic uses `(primary_ticker, normalized_headline)`.

Risk audited:

- Same ticker with materially different headlines should not be collapsed.
- Same headline from multiple sources should keep the earliest verifiable timestamp.
- Untimestamped duplicates should not outrank timestamped source rows.

Regression added:

- Two materially different BGMS headlines are preserved as two news items.

Freshness logic:

- Old published headlines detected now do not receive first-mover treatment.
- Missing `published_at` does not qualify for first-mover rescue.
- Low-confidence timestamps do not qualify for first-mover rescue.

## Telegram Delivery Audit

Telegram service behavior:

- Immediate send is attempted.
- On timeout/API failure, alert is enqueued in durable outbox:
  `data/agentic/telegram_outbox.jsonl`
- 429 `retry_after` is respected.
- Exponential backoff is used.
- Dead-letter status is applied after repeated failures.
- Duplicate `alert_id` is protected.
- Background outbox sender starts in `src/main.py`.

Local outbox state:

- No local `data/agentic/telegram_outbox.jsonl` file was present during this audit.

New latency fields distinguish:

- gate passed but Telegram failed/queued
- Telegram enqueue time
- Telegram sent confirmation time

## Top 20 Delayed Alerts

The new trace file exists but currently contains only local verification rows, not
Railway runtime evidence. After Railway runs this build, sort
`data/agentic/news_alert_latency_trace.jsonl` by `total_latency_seconds` descending
to produce the real top 20 delayed alerts.

Expected useful breakdown:

- High `published_to_fetch`: source/feed delay.
- High `fetch_to_gate`: classification/scoring/enrichment delay.
- High `gate_to_telegram`: Telegram/API/outbox delay.

## Top 20 Blocked High-Impact Headlines

The current local shadow file contains historical/test records and is not reliable
enough to rank live misses. With this build, blocked high-impact candidates will be
traceable using:

- `alert_sent=false`
- high-impact `catalyst_sub_type`
- populated `blocked_reason`
- `published_at`, `fetched_at`, `gate_decision_at`

## Exact Root Causes Identified

1. Market-data enrichment before first alert opportunity.
   - Location: `src/core/agentic/news_momentum_orchestrator.py`
   - Fix: emergency fast WATCH path before `_enrich_with_market_data()`.

2. Telegram send failures could previously look like alert success from the scanner
   perspective.
   - Existing durable outbox is present.
   - New trace distinguishes enqueue vs sent.

3. Historical `no_price` blocks could suppress fresh high-impact news when providers
   lagged or timed out.
   - Fix: fast WATCH bypasses quote enrichment for verified fresh high-impact news.

4. Repeated late recap headlines can look like live alerts if only `detected_at` is
   trusted.
   - Existing fix retained: first-mover requires fresh `published_at` and fresh
   `detected_at`.
   - New trace records both.

5. Duplicate/cooldown blocks were hard to debug after the fact.
   - Fix: blocked decisions now write latency trace rows with `blocked_reason`.

## Recommended Next Fixes

1. Add a small admin endpoint or frontend page for the latency trace.
   - Show latest 100 traces.
   - Sort by total latency.
   - Filter `alert_sent=false`.

2. Add a Railway health alert if no `news_alert_latency_trace.jsonl` row is produced
   for more than one scan cycle while sources are returning headlines.

3. Add a daily latency review:
   - top delayed alerts
   - top blocked high-impact candidates
   - Telegram queued/dead-letter count

4. Watch cooldown blocks carefully.
   - Normal cooldown is needed to prevent spam.
   - Materially different high-impact catalysts for the same ticker should remain
     visible in trace data so the threshold can be tuned later with evidence.

## Verification

Focused tests run:

`pytest tests/unit/test_news_alert_latency_trace.py tests/unit/test_news_momentum_alert_flow.py tests/unit/test_news_dedup.py tests/unit/test_telegram_outbox.py -q`

Result:

`41 passed`

Full backend suite:

`pytest -q`

Result:

`420 passed, 1 xfailed`

Lean startup verification:

`ORACLE_LEAN_MODE=true python -c "from src.main import app; print('lean_startup_import_ok')"`

Result:

`lean_startup_import_ok`

Frontend build:

`npm.cmd run build` from `frontend/`

Result:

Passed.

Compile check run:

`py_compile` on touched production and test modules.

Result:

Passed.
