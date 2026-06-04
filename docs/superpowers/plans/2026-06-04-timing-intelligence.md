# Timing Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an observe-only Timing Intelligence system that stores EOD reviews of mentioned/alerted/blocked tickers in the backend database and exposes them in the frontend.

**Architecture:** Add a SQLAlchemy `AlertTimingReview` table, a focused `timing_intelligence` service that classifies alert timing from before/after price moves, API routes under `/api/v1/news-momentum/timing-reviews`, and a frontend Timing Review page. The system logs and analyzes only; it does not change live alert gates, Telegram text, Rocket shadow scoring, or production trading behavior.

**Tech Stack:** FastAPI, SQLAlchemy, existing `SessionLocal` DB setup, React/Vite frontend, pytest.

---

### Task 1: Backend Model And Pure Classifier

**Files:**
- Modify: `src/models/database.py`
- Create: `src/core/agentic/timing_intelligence.py`
- Test: `tests/unit/test_timing_intelligence.py`

- [ ] **Step 1: Write failing tests for timing labels**

Create tests that assert:

```python
from src.core.agentic.timing_intelligence import classify_timing

def test_early_win_when_after_move_exceeds_before_move():
    assert classify_timing(move_before_pct=3.0, move_after_pct=45.0, alerted=True, discovered=True) == "EARLY_WIN"

def test_late_chase_when_before_move_already_large():
    assert classify_timing(move_before_pct=90.0, move_after_pct=4.0, alerted=True, discovered=True) == "LATE_CHASE"

def test_missed_alert_when_blocked_then_runs():
    assert classify_timing(move_before_pct=2.0, move_after_pct=55.0, alerted=False, discovered=True) == "MISSED_ALERT"

def test_missed_discovery_when_never_seen_but_runner():
    assert classify_timing(move_before_pct=None, move_after_pct=80.0, alerted=False, discovered=False) == "MISSED_DISCOVERY"

def test_false_positive_when_alerted_without_follow_through():
    assert classify_timing(move_before_pct=2.0, move_after_pct=1.0, alerted=True, discovered=True) == "FALSE_POSITIVE"
```

- [ ] **Step 2: Implement `AlertTimingReview` and classifier**

Add an `AlertTimingReview` model with ticker, source system, event type, timestamps, prices, moves, scores, label, review date, and notes. Implement `classify_timing()` and `build_review_payload()`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/unit/test_timing_intelligence.py -q`

Expected: pass.

### Task 2: Repository And API

**Files:**
- Create: `src/api/routes/timing_reviews.py`
- Modify: `src/main.py`
- Test: `tests/unit/test_timing_reviews_api.py`

- [ ] **Step 1: Write failing API tests**

Use a temporary SQLite DB session to insert `AlertTimingReview` rows and assert list/summary endpoints return correct counts and filters.

- [ ] **Step 2: Add API routes**

Add:

- `GET /api/v1/news-momentum/timing-reviews`
- `GET /api/v1/news-momentum/timing-reviews/summary`

Filters: ticker, label, source_system, event_type, date_from, date_to, limit.

- [ ] **Step 3: Register routes**

Include the router in `src/main.py`.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/unit/test_timing_reviews_api.py -q`

Expected: pass.

### Task 3: EOD Timing Reviewer

**Files:**
- Modify: `src/core/agentic/timing_intelligence.py`
- Modify: `src/core/agentic/news_momentum_eod_review.py`
- Test: `tests/unit/test_timing_intelligence.py`

- [ ] **Step 1: Write failing tests for idempotent persistence**

Create fake candidates and mover snapshots, run the service twice for the same review date, and assert the same ticker/date row is updated rather than duplicated.

- [ ] **Step 2: Implement persistence service**

Add `TimingReviewService.upsert_reviews()` that writes one row per ticker/source/date and stores a JSON feature snapshot.

- [ ] **Step 3: Wire EOD reviewer**

After normal EOD review is saved, create timing reviews for caught, missed_alert, and missed_discovery rows.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_timing_intelligence.py -q`

Expected: pass.

### Task 4: Frontend Timing Review Page

**Files:**
- Modify: `frontend/src/api_strategic.js`
- Modify: `frontend/src/App.jsx`
- Create: `frontend/src/pages/TimingReview.jsx`

- [ ] **Step 1: Add API helpers**

Add `newsMomentumTimingReviews()` and `newsMomentumTimingSummary()`.

- [ ] **Step 2: Add page and navigation**

Create a scanner-style dashboard with summary cards, label filters, and a table of reviews.

- [ ] **Step 3: Build frontend**

Run: `npm --prefix frontend run build`

Expected: Vite build passes in an environment where local Node permissions allow it.

### Task 5: Verification

**Files:**
- Create: `docs/timing_intelligence_report.md`

- [ ] **Step 1: Run focused backend tests**

Run: `pytest tests/unit/test_timing_intelligence.py tests/unit/test_timing_reviews_api.py -q`

- [ ] **Step 2: Run full backend tests**

Run: `pytest -q`

- [ ] **Step 3: Write final report**

Document files changed, routes added, labels, safety guarantees, tests passed, and remaining risks.
