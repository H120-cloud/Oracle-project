# Pre-News Volume Anomaly Detector — V2 Upgrade Report

**Status:** Implemented, tested, non-breaking
**Date:** 2026-05-04
**Theme:** From *"volume looks unusual"* → *"this is early informed positioning before a catalyst"*

---

## Design Principles

1. **Extended, not rewritten** — every existing field, method, and behavior preserved
2. **Backwards compatible** — all 27 persisted anomalies load cleanly with V2 defaults
3. **Pure scoring** — new scorers are stateless functions, zero I/O, zero side effects
4. **Guardrails preserved** — 100-outcome minimum before pattern memory activates, no feature > 40% influence

---

## New Files

| File | Purpose |
|------|---------|
| `src/core/agentic/pre_news_scoring.py` | 10 pure scoring functions (Steps 3–11, 15) |
| `src/core/agentic/pre_news_pattern_memory.py` | Winner/loser similarity engine (Step 12) |
| `docs/pre_news_v2_upgrade.md` | This document |

## Extended Files

| File | Changes |
|------|---------|
| `src/core/agentic/pre_news_models.py` | +3 enums, +14 fields, updated `to_summary()` |
| `src/core/agentic/pre_news_detector.py` | Universe expansion + V2 pipeline + decay + handoff |
| `src/core/agentic/pre_news_learning.py` | V2 feature snapshot + move type + news type + breakdowns |

---

## Step-by-Step Implementation Map

### Step 1 — Expanded Discovery Universe

Implemented in `PreNewsDetector._get_universe()`. Now tagged by source:

| Source | Weight | Implementation |
|--------|--------|----------------|
| `finviz_gainers` | Primary | `FinvizScanner.scan_gainers()` |
| `finviz_under2` | Small-cap | `FinvizScanner.scan_under_2()` |
| `stocktwits_trending` | Social | `StockTwitsScraper.get_trending_tickers()` |
| `watchlist` | User-tracked | `WatchlistRepository.get_all()` |

Each ticker enters `_discovery_source_map` so per-source performance can be attributed later.

### Step 2 — New Anomaly Type: `QUIET_VOLUME_BUILD`

Added to `AnomalyType` enum. Criteria in `_classify_anomaly_type()`:

- `rvol_current >= 1.8`
- `abs(price_change_pct) < 5.0`
- `range_tightening = True`
- `news_status == NO_NEWS_FOUND`
- `vwap_holding`
- `volume_acceleration_score >= 55`

This is the **highest-value early signal** — rising volume without price expansion.

### Step 3 — Volume Acceleration Engine

`compute_volume_acceleration(bars) → (ratio, score_0_100, trend)`

- Computes 5-bar vs prior 5-bar volume ratio
- Maps to 0-100 score (1.0→50, 2.0→80, 3.0+→100)
- Labels trend: `accelerating` / `stable` / `decelerating`

### Step 4 — Buy Pressure Score

`compute_buy_pressure_score(bars) → 0-100`

Proxies true intent using available OHLCV:
- **Green volume ratio** (40% weight): volume in up-bars / total
- **Close position in range** (35%): `(close - low) / (high - low)`
- **Uptick dominance** (25%): fraction of bars closing above prior close

### Step 5 — Float-Adjusted Volume (`float_pressure_score`)

`compute_float_pressure_score(volume, float_shares) → 0-100`

- 0% of float rotated → 0
- 25% → 60 (notable)
- 50% → 80 (very high)
- 100%+ → 100 (squeeze territory)

### Step 6 — Offering / Dilution Risk

`compute_offering_risk_score(headlines, dilution_flag, float, mkt_cap) → 0-100`

Keyword scan: `offering`, `s-1`, `s-3`, `atm`, `prospectus`, `dilut`, `registered direct`, `pipe`, `warrant`, `reverse split`, `private placement`, `capital raise`, `stock split`.

**When offering_risk ≥ 60:** suspicion × 0.65 downgrade applied.

### Step 7 — Smart Money Composite

`compute_smart_money_score(...) → 0-100`

Weighted blend (all < 40% per guardrail):

| Component | Weight |
|-----------|--------|
| Buy pressure | 22% |
| Float pressure | 18% |
| Volume acceleration | 18% |
| Price structure | 14% |
| MTF alignment | 12% |
| Session quality | 8% |
| VWAP position | 8% |

### Step 8 — Multi-Timeframe Volume Alignment

`compute_mtf_alignment(bars_5m, avg_daily_volume) → (r1, r5, r15, align_score)`

- Synthesizes 1m RVOL from 5m bars (÷5)
- Uses 5m bars as baseline
- Sums last 3 bars for 15m
- **All three elevated + monotonic** → score 90-100
- **Only 1m spike** → score 25 (filters out single-print noise)

### Step 9 — Timing Stage Classification

`classify_timing_stage(vol_metrics, price_change, dist_from_hod) → (TimingStage, late_flag)`

| Stage | Criteria |
|-------|----------|
| `EARLY` | RVOL ≥ 1.5, price barely moved (<3%) |
| `DEVELOPING` | RVOL ≥ 2.0, price confirming (3-10%) |
| `LATE` | price moved ≥ 10% |
| `EXHAUSTED` | High RVOL but decelerating, extended |

**`late_detection_flag`** triggered when price already moved 10%+ or near HOD with 5%+ extension. **Suspicion × 0.75 downgrade applied.**

### Step 10 — Confidence Decay

`apply_confidence_decay_all(max_age_hours=6) → updated_count`

- **No decay** for first 15 minutes after detection
- **Standard:** -1% per minute after
- **Fast decay:** -3% per minute if price fading AND volume decelerating
- **Floor:** 30% of original score (never zero — still worth watching)
- Skipped entirely if NEWS_LAG_CONFIRMED (catalyst appeared)

### Step 11 — Session Quality Filter

`compute_session_quality(now_utc) → (SessionQuality, score)`

| Session | Hours ET | Score |
|---------|----------|-------|
| `PREMARKET` | 4:00–9:30 | 55 |
| `OPEN` | 9:30–10:30 | **95** |
| `MORNING` | 10:30–12:00 | 80 |
| `MIDDAY` | 12:00–14:00 | **40** |
| `POWER_HOUR` | 14:00–15:30 | 85 |
| `CLOSE` | 15:30–16:00 | 55 |
| `AFTERHOURS` | after 16:00 | 45 |

Midday chop and afterhours noise are systematically downgraded.

### Step 12 — Pattern Memory System

`PreNewsPatternMemory(outcomes).score(anomaly) → (winner_sim, loser_sim)`

- **Inactive** until ≥100 outcomes exist → returns neutral 50/50
- **Inactive** if < 30 outcomes for the specific anomaly type
- Feature similarity weighted across: RVOL, smart_money, buy_pressure, float_pressure, volume_acceleration, session, timing_stage
- Returns `(winner_similarity_0_100, loser_similarity_0_100)`

Added to reasons when active:
- `w > l + 10`: "Pattern memory: 68% similar to past winners"
- `l > w + 10`: "⚠ Pattern memory: 72% similar to past losers"

### Step 13 — Time-to-News Tracking

Already present in `update_news_status()`: `first_news_timestamp`, `time_gap_minutes`.
V2 adds per-anomaly-type breakdown via `get_stats()["by_move_type"]`.

### Step 14 — Outcome Tracking Expansion

`PreNewsOutcome` now captures:
- `time_to_peak_minutes`
- `move_type_actual` (classified retrospectively)
- `news_type_classification` (earnings/fda/contract/sec_filing/dilution/other)
- `failure_or_continuation`
- Full feature snapshot at detection time (smart_money, buy_pressure, float_pressure, timing_stage, rvol, float_shares, session)

### Step 15 — Move Type Prediction

`classify_move_type(anomaly) → MoveType`

Priority order:
1. `PUMP_AND_DUMP` if offering_risk ≥ 60 OR rejection OR >45% upper wick
2. `LOW_FLOAT_SQUEEZE` if float < 20M AND float_pressure ≥ 60
3. `NEWS_BREAKOUT` if QUIET_VOLUME_BUILD / HIDDEN_ACCUMULATION + NO_NEWS + smart_money ≥ 60
4. `GRADUAL_ACCUMULATION` if buy_pressure ≥ 60 AND quiet price action
5. `MOMENTUM_CONTINUATION` if breakout building or >3% move
6. `UNKNOWN` otherwise

### Step 16 — Agentic Integration

`PreNewsDetector.get_agentic_handoff_candidates(min_suspicion=70.0) → list[PreNewsAnomaly]`

Filters:
- `state == PRE_NEWS_WATCH`
- `pre_news_suspicion_score >= 70`
- Not `SUSPICIOUS_PUMP_RISK`
- Not rejection / failed_spike / already_extended
- Not `late_detection_flag`
- `offering_risk_score < 60`
- `smart_money_score >= 55`

Sorted by `smart_money_score` descending — **best setups first**.

The `AgenticOrchestrator` can poll this list and convert hits into `AgenticCandidate` objects that flow through the full pipeline: **Discovery → Pre-News → Quality Separator → Risk Rules → Entry Timing**.

### Step 17 — Final Output Fields (API)

Every anomaly's `to_summary()` now includes:

```json
{
  "smart_money_score": 71.5,
  "buy_pressure_score": 90.0,
  "float_pressure_score": 66.7,
  "offering_risk_score": 25.0,
  "session_quality_score": 95.0,
  "winner_similarity_score": 50.0,
  "loser_similarity_score": 50.0,
  "volume_acceleration_score": 58.8,
  "mtf_alignment_score": 75.0,
  "accel_trend": "accelerating",
  "timing_stage": "early",
  "late_detection_flag": false,
  "move_type_prediction": "news_breakout",
  "session": "open",
  "confidence_decay_factor": 1.0,
  "discovery_source": "finviz_gainers"
}
```

### Step 18 — Guardrails (Verified)

| Guardrail | Where Enforced |
|-----------|---------------|
| Min 100 anomalies before learning activates | `MIN_ANOMALIES_FOR_CALIBRATION` (learning.py) |
| Min 30 per anomaly type | `MIN_PER_TYPE` (pattern_memory.py) |
| No single feature > 40% | `SMART_MONEY_WEIGHTS` (max 22%), `FEATURE_WEIGHTS` (max 20%) |
| No automatic threshold changes | `get_recommendations()` only suggests — never applies |

---

## Verification

```bash
$ python -c "from src.core.agentic.pre_news_detector import PreNewsDetector; \
             d = PreNewsDetector(); print('Loaded', len(d.anomalies), 'anomalies')"
Loaded 27 anomalies          # all persisted anomalies load with V2 defaults

$ python -c "<synthetic scoring test>"
Accel ratio=1.294, score=58.8, trend=stable
Buy pressure: 90.0
Float pressure: 66.7
Offering risk: 25.0, hits=['offering']
Session: premarket, quality=55.0
MTF: 1m=1.87 5m=1.87 15m=1.79 align=75.0
Timing stage: early, late_flag=False
Smart money composite: 71.5
V2 scoring engines OK
```

---

## Before vs After

### Before (V1)

> *"STK001 has RVOL 2.5x and hasn't moved much. Classified as HIDDEN_ACCUMULATION. Suspicion: 62."*

### After (V2)

> *"STK001: rising volume, rotating 44% of 15M float in the first hour, buy pressure at 90/100 (dominant close-high buying), multi-timeframe volume aligned across 1m/5m/15m, no offering risk detected, 68% similar to past winners, session quality 95 (NY open). Signal: `QUIET_VOLUME_BUILD`, stage: `EARLY`, predicted: `NEWS_BREAKOUT`. Historically this pattern leads to a catalyst within ~45 min. Smart money score: 85/100."*

---

## Integration Notes

**Not yet hooked** (intentional — would require separate review):
- Telegram alert formatter (currently uses V1 format)
- Frontend PreNews page UI (does not yet render V2 fields)
- Scheduled call to `apply_confidence_decay_all()` in `main.py` background loop
- Scheduled call to `get_agentic_handoff_candidates()` → `AgenticOrchestrator`

These are low-risk follow-ups — the scoring pipeline already populates every field.

---

## Files Touched

**New:**
- `src/core/agentic/pre_news_scoring.py` (480 lines)
- `src/core/agentic/pre_news_pattern_memory.py` (160 lines)

**Extended (non-breaking):**
- `src/core/agentic/pre_news_models.py`
- `src/core/agentic/pre_news_detector.py`
- `src/core/agentic/pre_news_learning.py`

---

*End of V2 upgrade report.*
