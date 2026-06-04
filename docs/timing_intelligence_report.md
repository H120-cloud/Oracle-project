# Oracle Timing Intelligence Report

## Purpose

Timing Intelligence is an observe-only review layer for News Momentum / Rocket Runner alerts. It records whether Oracle mentioned a ticker before or after the meaningful move, so late chases, missed alerts, and good early calls can be inspected from the backend and frontend without changing production alert behavior.

## What Changed

- Added a persistent `alert_timing_reviews` database table.
- Added `TimingReviewService` to classify end-of-day alert timing outcomes.
- Wired News Momentum EOD review to persist timing reviews for:
  - alerted movers
  - blocked/missed movers
  - movers never discovered by the pipeline
- Added read-only API endpoints:
  - `GET /api/v1/news-momentum/timing-reviews`
  - `GET /api/v1/news-momentum/timing-reviews/summary`
- Added frontend API helpers and a `Timing Review` page for filtering and inspecting results.

## Timing Labels

- `EARLY_WIN`: Oracle alerted and the ticker moved strongly after the alert.
- `ON_TIME_WIN`: Oracle alerted and the ticker moved at least 10% after the alert.
- `LATE_CHASE`: the ticker had already moved at least 50% before Oracle alerted or mentioned it.
- `MISSED_ALERT`: Oracle discovered the ticker but did not alert, then it moved strongly.
- `MISSED_DISCOVERY`: the ticker moved strongly but was not found by the pipeline.
- `FALSE_POSITIVE`: Oracle alerted but the ticker produced little follow-through.
- `NEUTRAL`: no strong timing outcome.
- `NO_ACTION_NEEDED`: undiscovered ticker did not become a meaningful mover.

## Data Stored

Each review stores ticker, source system, event type, headline, catalyst fields, published/detected/alerted times, move-before and move-after percentages, high prices, scores, primary issue or block reason, and a feature snapshot for later analysis.

## Safety

This feature does not change:

- Telegram message content
- alert scoring
- alert gating
- News Momentum production decisions
- Pre-News scoring
- Rocket CatBoost shadow scoring
- SEC scoring
- trading behavior

It is a measurement and diagnosis layer only.

## Frontend

The new `Timing Review` page shows summary counts, label filters, source filters, ticker search, move-before and move-after columns, block issue, detected time, and headline context.

## Verification

Focused tests added:

- `tests/unit/test_timing_intelligence.py`
- `tests/unit/test_timing_reviews_api.py`
- `tests/unit/test_timing_review_frontend.py`

Focused result:

- `8 passed`

## Remaining Risks

- The first version uses EOD mover/candidate data. If a source never records a mover, there is still nothing to review.
- Thresholds are intentionally conservative and should be tuned from real review history, not live alert behavior.
- Frontend page is read-only; threshold tuning controls can be added later once enough review rows exist.
