# Pre-News V2 — Live Paper Validation Framework

**Date:** 2026-05-04
**Status:** ACTIVE — observational tracking wired, weekly reports automated
**Tracking Period:** 2–4 weeks (rolling)

---

## 1. Purpose

This document defines the live paper-validation phase for Pre-News V2 + Agentic.

**Constraint:** No new strategy features are added during validation. The system only *observes* and *records* what happens to every PRE_NEWS_V2 handoff candidate. This is pure measurement, not optimization.

---

## 2. What Gets Tracked

For every PRE_NEWS_V2 handoff candidate, the `PreNewsValidationTracker` records:

| Field | Source | Description |
|-------|--------|-------------|
| `record_id` | auto | UUID-like identifier |
| `ticker` | anomaly | Handed-off ticker |
| `anomaly_detected_at` | PreNewsAnomaly | When the volume anomaly was first detected |
| `handoff_at` | orchestrator | When `handoff_from_pre_news()` created/updated the AgenticCandidate |
| `smart_money_score` | PreNewsAnomaly | Smart-money composite at detection |
| `suspicion_score` | PreNewsAnomaly | Pre-news suspicion score at detection |
| `anomaly_type` | PreNewsAnomaly | e.g. `volume_spike`, `quiet_volume_build` |
| `timing_stage` | PreNewsAnomaly | `early` / `developing` / `late` / `exhausted` |
| `buy_pressure_score` | PreNewsAnomaly | 0-100 buy-pressure snapshot |
| `float_pressure_score` | PreNewsAnomaly | 0-100 float-rotation snapshot |
| `offering_risk_score` | PreNewsAnomaly | Dilution risk 0-100 |
| `move_type_prediction` | PreNewsAnomaly | `news_breakout`, `low_float_squeeze`, etc. |
| `discovery_source` | PreNewsAnomaly | `finviz_gainers`, `premarket_gap`, etc. |
| `confidence_decay_factor` | PreNewsAnomaly | Decay multiplier applied at handoff |
| `late_detection_flag` | PreNewsAnomaly | True if caught late in move |
| `entry_timing_state` | AgenticCandidate | `ideal_entry`, `waiting_for_confirmation`, `late_chase`, etc. |
| `entry_zone_low/high` | AgenticCandidate | Entry zone computed by EntryTimingEngine |
| `stop_level` | AgenticCandidate | Stop price |
| `target_1` | AgenticCandidate | First profit target |
| `invalidation_level` | AgenticCandidate | Hard invalidation price |
| `final_probability` | AgenticCandidate | Orchestrator final score |
| `agentic_alertable` | AgenticCandidate | Whether orchestrator marked candidate alertable |
| `telegram_alert_sent` | Telegram loop | Whether a Telegram alert was actually dispatched |
| `alert_sent_at` | Telegram loop | Timestamp of alert dispatch |

---

## 3. Outcome Tracking (Updated Every 15 Min)

The background `_pre_news_scan_loop` in `main.py` calls `validation_tracker.update_prices()` and `resolve_all()` after the existing outcome-recording block.

### Price Evolution
| Metric | How Computed |
|--------|--------------|
| `entry_price` | `AgenticCandidate.last_price` at handoff |
| `peak_price` | Max high since handoff |
| `trough_price` | Min low since handoff |
| `exit_price` | Last checked price at resolution |
| `mfe_pct` | `(peak - entry) / entry * 100` (clamped ≥0) |
| `mae_pct` | `(entry - trough) / entry * 100` (clamped ≥0) |

### Hit Detection
| Hit | Condition |
|-----|-----------|
| `target_hit` | Price ≥ `target_1` + 1% threshold (avoids wick noise) |
| `stop_hit` | Price ≤ `stop_level` |
| `invalidation_hit` | Price ≤ `invalidation_level` |

### News Detection
The tracker records:
- `news_appeared` — True if post-news matching in detector later confirms news
- `time_to_news_minutes` — Minutes from `anomaly_detected_at` to news confirmation
- `news_headline` — First headline matched

---

## 4. Resolution Rules

| Outcome | Trigger |
|---------|---------|
| **WIN** | `target_hit` before `stop_hit` / `invalidation_hit` |
| **LOSS** | `stop_hit` or `invalidation_hit` before `target_hit` |
| **BREAKEVEN** | After 4h, price within ±2% of entry, no hits |
| **EXPIRED** | 24h tracking window closes without any hit |
| **CANCELLED** | Candidate explicitly deactivated by orchestrator |
| **OPEN** | Still within 24h window, no resolution yet |

Tie-breaker: if both target AND stop/invalidation hit, whichever timestamp is earlier wins.

---

## 5. Weekly Report Contents

Auto-generated every Monday ~05:00 UTC (and on-demand via API).

### High-Level Metrics
- **Total handoffs** — How many PRE_NEWS_V2 candidates entered the Agentic pipeline
- **Alerted count** — How many triggered a Telegram alert
- **Non-alerted count** — Handed off but not alerted (filter gate)
- **Win / Loss / Breakeven / Expired / Cancelled / Still Open** breakdown
- **Win rate** — `wins / (wins + losses) * 100`
- **False alert rate** — `losses / alerted * 100`
- **Alert rate** — `alerted / total handoffs * 100`

### Performance Metrics
- **Avg MFE** — Mean max favorable excursion across all resolved records
- **Avg MAE** — Mean max adverse excursion across all resolved records
- **Avg MFE (alerted only)** — MFE of records that got Telegram alerts
- **Avg MFE (non-alerted)** — MFE of records that did NOT get alerts

### Drill-Down Tables
- **By anomaly type** — Count, wins, losses, avg MFE per type (`volume_spike`, `quiet_volume_build`, etc.)
- **By timing stage** — Count, wins, losses, avg MFE per stage (`early`, `developing`, `late`, `exhausted`)
- **By move type** — Count, wins, losses per predicted move type

### Missed Opportunities
- **Missed runners** — Candidates where `telegram_alert_sent=False` but `MFE > 10%`
- **Blocked-but-ran** — Candidates where `agentic_alertable=False` but `MFE > 5%`

### News Conversion
- **News appeared count / rate** — How many candidates later had news confirmed
- **Avg time-to-news** — Average minutes from anomaly detection to news confirmation

### Smart Money Distribution
- **Avg smart_money_score** — Overall average
- **Avg smart_money_score (winners)** — For WIN outcomes
- **Avg smart_money_score (losers)** — For LOSS outcomes

### Summary Text
Auto-generated human-readable summary, e.g.:
```
Pre-News V2 Validation Week 2026-W18
  Handoffs: 47  |  Alerted: 31  |  Open: 3
  Win Rate: 58.3% (14W / 10L)
  False Alert Rate: 32.3%
  Avg MFE: 12.4%  |  Avg MAE: 4.1%
  Missed Runners: 5
  Blocked-but-Ran: 2
```

---

## 6. API Endpoints

All under `/api/v1/agentic/pre-news/validation/`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/validation/records` | List records (filter: `?ticker=ABC&outcome=WIN&limit=50`) |
| `GET` | `/validation/reports` | All generated weekly reports |
| `GET` | `/validation/reports/{week_key}` | Specific report (e.g. `2026-W18`) |
| `POST` | `/validation/generate-report` | On-demand report generation (`?week_key=2026-W18`) |

---

## 7. Data Storage

| File | Path | Content |
|------|------|---------|
| Validation records | `data/agentic/pre_news_validation.json` | All `PreNewsValidationRecord` objects |
| Weekly reports | `data/agentic/validation_reports/weekly_report_YYYY-WNN.json` | One `WeeklyReport` per week |

Both are plain JSON, human-readable, and survive restarts.

---

## 8. Wiring Points

### Orchestrator Handoff
`src/core/agentic/orchestrator.py` → `handoff_from_pre_news()`
- After creating or updating an AgenticCandidate, calls `tracker.record_handoff(anomaly, candidate, telegram_alert_sent=False)`
- Wrapped in `try/except` so tracker failures never break the handoff

### Telegram Alert Loop
`src/main.py` → `_pre_news_scan_loop()`
- When `send_telegram_alert()` succeeds, calls `validation_tracker.record_alert(ticker)`

### Price Tracking + Resolution
`src/main.py` → `_pre_news_scan_loop()` (after existing outcome recording)
```python
open_records = validation_tracker.get_open_records()
if open_records:
    # batch-fetch prices via yfinance fast_info
    price_map = {ticker: last_price ...}
    validation_tracker.update_prices(price_map)
    resolved = validation_tracker.resolve_all()
    if resolved > 0:
        logger.info("PreNews V2 validation: resolved %d records", resolved)
```

### Weekly Report Auto-Generation
`src/main.py` → `_pre_news_scan_loop()`
```python
if now_utc.weekday() == 0 and now_utc.hour == 5 and now_utc.minute < 15:
    last_week = _week_key(now_utc - timedelta(days=7))
    report = validation_tracker.generate_weekly_report(week_key=last_week)
```

### News Tracking
When `detector.update_news_status()` confirms news for a watched anomaly, the existing loop can call `validation_tracker.record_news_appeared(ticker, headline)`.

*(Wiring for news tracking is deferred to a lightweight hook in the detector's news-update path — no structural changes needed.)*

---

## 9. Validation Phase Protocol

### Week 1–2: Baseline
- Let the system run live with all existing logic unchanged
- Observe handoff volume, alert rate, and early outcomes
- Do NOT change thresholds, scores, or filters

### Week 2–3: Pattern Emergence
- Review weekly reports for:
  - Which `anomaly_type` has highest win rate
  - Which `timing_stage` is most predictive
  - Whether `smart_money_score` correlates with outcomes
  - How many missed runners / blocked-but-ran cases exist

### Week 3–4: Calibration Readiness
- If sample size ≥ 30 resolved outcomes:
  - Compute per-feature correlation with win rate
  - Flag thresholds that may be too conservative (high blocked-but-ran)
  - Flag thresholds that may be too loose (high false-alert rate)
- **Still do not auto-change anything** — only produce recommendations

### Go/No-Go Criteria
| Criterion | Threshold | Action if Missed |
|-----------|-----------|-----------------|
| Win rate (alerted) | ≥ 55% | Investigate alert gating |
| False alert rate | ≤ 40% | Tighten offering-risk / late flags |
| Avg MFE / MAE ratio | ≥ 2:1 | Review stop/target placement |
| Missed runners / total | ≤ 15% | Lower alert threshold if safe |
| Blocked-but-ran / total | ≤ 10% | Relax alertable filters |
| News conversion rate | ≥ 30% | Validate "informed positioning" hypothesis |

---

## 10. Files Added / Modified

| File | Action | Lines Added |
|------|--------|-------------|
| `src/core/agentic/pre_news_validation.py` | **New** — tracker, record model, weekly report generator | ~620 |
| `src/core/agentic/orchestrator.py` | **Modified** — `handoff_from_pre_news()` now records every handoff | +10 |
| `src/main.py` | **Modified** — alert recording, price tracking, resolution, weekly report auto-gen | +40 |
| `src/api/routes/pre_news.py` | **Modified** — 4 new validation endpoints | +50 |
| `tests/test_pre_news_validation.py` | **New** — 34 tests covering all tracker logic | ~500 |
| `docs/pre_news_v2_live_validation_report.md` | **New** — this document | ~200 |

---

## 11. Test Coverage

`pytest tests/test_pre_news_validation.py -v`

| Class | Tests | Status |
|-------|-------|--------|
| `TestRecordHandoff` | 2 | ✅ PASS |
| `TestRecordAlert` | 2 | ✅ PASS |
| `TestUpdatePrices` | 6 | ✅ PASS |
| `TestResolveAll` | 7 | ✅ PASS |
| `TestResolveCancelled` | 2 | ✅ PASS |
| `TestRecordNewsAppeared` | 2 | ✅ PASS |
| `TestWeeklyReport` | 11 | ✅ PASS |
| `TestObservationalOnly` | 2 | ✅ PASS |

**Total: 34 passed in 2.47s**

---

## 12. Observational-Only Guarantee

The validation tracker **never**:
- Modifies `AgenticCandidate` objects
- Changes entry zones, stop levels, or targets
- Generates new trading signals
- Sends alerts (it only records that alerts were sent)
- Adjusts thresholds or weights
- Interferes with the existing pipeline flow

It **only** reads state and writes to its own JSON files.

---

*End of live validation framework document.*
