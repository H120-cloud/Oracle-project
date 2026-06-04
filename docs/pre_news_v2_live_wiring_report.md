# Pre-News V2 — Live Wiring Report

**Date:** 2026-05-04
**Status:** WIRED — all V2 outputs connected to live system

---

## 1. Scheduled Confidence Decay

### Where
- `src/main.py` → `_pre_news_scan_loop()` line ~186

### What
```python
decayed = detector.apply_confidence_decay_all(max_age_hours=6)
if decayed > 0:
    logger.info("PreNews V2 decay: %d anomalies updated", decayed)
```

### Behavior
- Runs every **15 minutes** (scan interval)
- Applies decay to all `PRE_NEWS_WATCH` anomalies older than 15 minutes
- No decay if `NEWS_LAG_CONFIRMED` (follow-through confirmed)
- Standard: -1%/min after grace period; fast: -3%/min if price fading + volume decelerating
- Floor: 30% of original score (never zero)

### Logs
```
PreNewsDetector: applied confidence decay to 4 anomalies
PreNews V2 decay: 4 anomalies updated
```

---

## 2. Agentic Handoff

### Where
- `src/main.py` → `_pre_news_scan_loop()` line ~172-181
- `src/core/agentic/orchestrator.py` → `handoff_from_pre_news()` line ~196-290

### What (in main.py)
```python
handoff_anomalies = detector.get_agentic_handoff_candidates(min_suspicion=70.0)
handoff_result = orch.handoff_from_pre_news(handoff_anomalies)
logger.info(
    "PreNews V2 handoff: created=%d updated=%d skipped=%d",
    handoff_result["created"], handoff_result["updated"], handoff_result["skipped"],
)
```

### Dedup Rules (centralized in orchestrator)
| Condition | Action |
|-----------|--------|
| Ticker NOT in Agentic candidates | **CREATE** new candidate (source=PRE_NEWS_V2) |
| Ticker EXISTS, source=PRE_NEWS_V2 | **UPDATE** fields, preserve ID |
| Ticker EXISTS, source!=PRE_NEWS_V2 | **SKIP** — do NOT overwrite richer candidate |

### Qualifying Filters (in detector)
- `pre_news_suspicion_score >= 70`
- `smart_money_score >= 55`
- Not `SUSPICIOUS_PUMP_RISK`
- Not rejection / failed_spike / already_extended
- Not `late_detection_flag`
- `offering_risk_score < 60`
- `state == PRE_NEWS_WATCH`

### Candidate Fields Populated
- `catalyst.source` = `"PRE_NEWS_V2"`
- `catalyst.headline` = `"[PRE-NEWS V2] quiet_volume_build · suspicion 85 · smart-money 78 · RVOL 2.5x · stage early"`
- `catalyst.strength_score` = `pre_news_suspicion_score`
- `catalyst.sentiment` = `"bullish"` (if VWAP >= 0)
- `final_probability` = `pre_news_suspicion_score`
- `entry_zone_low/high` = `price * 0.98 / 1.02`
- `invalidation_level` = `price * 0.95`
- `last_price` = `anomaly.price`
- `float_shares` / `market_cap` (if known)

### Alertable Gate
Candidate is `alertable = True` ONLY if:
- suspicion >= 75
- not late
- offering risk < 60
- data quality != degraded

---

## 3. Telegram Alert Formatter

### Where
- `src/core/agentic/pre_news_detector.py` → `format_alert()` line ~689-762

### V2 Fields Now Shown
- **Smart Money** score (0-100)
- **Buy Pressure** score (0-100)
- **Float Pressure** score (0-100)
- **Anomaly Type** (with 💎 QUIET_VOLUME_BUILD highlight)
- **Timing Stage** (early/developing/late/exhausted)
- **Move Type** prediction (news_breakout, low_float_squeeze, etc.)
- **Session** quality
- **Late Detection** flag (⚠ warning)
- **Offering / Dilution Risk** (⚠ if ≥50)
- **Pattern Memory** similarity (✨ winner / ⚠ loser)
- **Next Condition Needed**

### Example Output
```
💎 [PRE-NEWS V2 — QUIET VOLUME BUILD]

Ticker: STK001
Price: $2.45
RVOL: 2.5x  (accel accelerating)
Price Change: +1.2%
VWAP Distance: +0.3%
Float: 15.0M
Mkt Cap: $42M

Smart Money: 85/100
Suspicion:   78/100 [HIGH]
Buy Pressure: 90/100
Float Pressure: 66/100

Anomaly Type: quiet_volume_build
Timing Stage: early
Move Type:    news_breakout
Session:      open

News: no_news_found
Price Behaviour: quiet_accumulation

Why flagged:
  • Volume acceleration +87%
  • No visible news yet
  • Price range tightening — potential accumulation
  • Price holding above VWAP
  • 💎 Quiet volume build — early accumulation signature
  • Smart-money footprint strong (85/100)

Next: Await 2x RVOL confirmation

Risk:
  • May be random volume
  • May be pump — wait for confirmation
```

---

## 4. Frontend Pre-News Panel

### Where
- `frontend/src/pages/Agentic.jsx` → Pre-News panel (line ~1363-1453)

### V2 UI Components Added

| Element | Rendered |
|---------|----------|
| **Smart Money score** | Big bold number + color (≥75 green, ≥55 cyan) |
| **Buy Pressure bar** | Horizontal bar (green/cyan/gray fill) |
| **Float Pressure bar** | Horizontal bar (purple/cyan/gray fill) |
| **Timing Stage badge** | Colored pill (early=green, developing=cyan, late=orange, exhausted=red) |
| **Late Detection badge** | Red pill "LATE" |
| **Move Type badge** | Purple/cyan/pink pill with move type name |
| **Acceleration trend** | Small badge (accelerating green, decelerating orange) |
| **MTF aligned** | Blue badge (only if ≥75) |
| **Offering risk** | Red badge with score |
| **Winner pattern** | Green sparkle badge (only if active + w>l+10) |
| **Loser pattern** | Red warning badge (only if active + l>w+10) |
| **Decay factor** | Gray badge (only if <0.95) |
| **Discovery source** | Small gray "via finviz_gainers" etc. |
| **Session** | Added to footer line ("· open") |

### Layout
- Existing 4-column grid (RVOL, Vol Accel, Price Action, News) **preserved**
- V2 block inserted **between** 4-col grid and footer line
- Compact, non-intrusive — no vertical bloat on old anomalies

---

## 5. API Response Fields

### Where
- `src/core/agentic/pre_news_models.py` → `PreNewsAnomaly.to_summary()`
- `src/api/routes/pre_news.py` → returns `to_summary()` output

### All V2 Keys Now Returned
```json
{
  "smart_money_score": 85,
  "buy_pressure_score": 90,
  "float_pressure_score": 66.7,
  "offering_risk_score": 10,
  "session_quality_score": 95,
  "winner_similarity_score": 50,
  "loser_similarity_score": 50,
  "volume_acceleration_score": 58.8,
  "mtf_alignment_score": 75,
  "accel_trend": "accelerating",
  "timing_stage": "early",
  "late_detection_flag": false,
  "move_type_prediction": "news_breakout",
  "session": "open",
  "confidence_decay_factor": 1.0,
  "discovery_source": "finviz_gainers"
}
```

---

## 6. Test Coverage

### File: `tests/test_pre_news_v2.py`

| Test Class | Tests | Status |
|------------|-------|--------|
| `TestVolumeAcceleration` | 4 | ✅ PASS |
| `TestBuyPressureScore` | 4 | ✅ PASS |
| `TestFloatPressureScore` | 4 | ✅ PASS |
| `TestOfferingRiskScore` | 5 | ✅ PASS |
| `TestSmartMoneyScore` | 4 | ✅ PASS |
| `TestMTFAlignment` | 3 | ✅ PASS |
| `TestTimingStage` | 4 | ✅ PASS |
| `TestConfidenceDecay` | 3 | ✅ PASS |
| `TestSessionQuality` | 3 | ✅ PASS |
| `TestMoveTypeClassification` | 5 | ✅ PASS |
| `TestPatternMemory` | 2 | ✅ PASS |
| `TestTelegramV2Formatting` | 3 | ✅ PASS |
| `TestAPISummaryV2Fields` | 1 | ✅ PASS |
| `TestAgenticHandoff` | 4 | ✅ PASS |
| `TestDecayBackgroundCall` | 2 | ✅ PASS |
| `TestBackwardsCompatibility` | 2 | ✅ PASS |

**Total: 53 tests — all passing in 1.99s**

### What Each Class Verifies
- **VolumeAcceleration**: rising volume → accelerating, falling → decelerating, empty → neutral
- **BuyPressure**: green-bar dominance gives high score, red-bar dominance gives low score
- **FloatPressure**: 100%+ float rotation → 100, 50% → ~80, 25% → ~60
- **OfferingRisk**: keyword hits, dilution flag, clamp to 100
- **SmartMoney**: composite weighted properly, no feature > 40%
- **MTFAlignment**: all-elevated-monotonic → 75+, lone spike → low
- **TimingStage**: EARLY when low price change, LATE when +10%, EXHAUSTED when fading
- **ConfidenceDecay**: grace 15 min, decays after, floor 30%, no decay if news confirmed
- **SessionQuality**: OPEN=95, MIDDAY=40, afterhours=45
- **MoveType**: pump (offering/rejection), squeeze (low float), breakout (quiet+no news), accumulation (buy pressure), continuation (breakout)
- **PatternMemory**: inactive below 100 outcomes (50/50), active above with correct similarity ranking
- **TelegramV2Formatting**: all 8 requested fields present in alert string
- **APISummaryV2Fields**: all V2 keys returned by `to_summary()`
- **AgenticHandoff**: creates, skips different source, updates same source, dedup on repeat
- **DecayBackgroundCall**: stale anomalies decay, news-confirmed anomalies do not
- **BackwardsCompatibility**: V1 fields still exist, V2 fields default safely on old persisted data

---

## 7. Verification Commands

### Backend imports
```bash
python -c "from src.core.agentic.pre_news_detector import PreNewsDetector; d=PreNewsDetector(); print('Loaded', len(d.anomalies))"
# → Loaded 27 anomalies
```

### Synthetic scoring
```bash
python -c "from src.core.agentic.pre_news_scoring import compute_smart_money_score; print(compute_smart_money_score(90,80,70,75,60,85,0.5))"
# → 76.5
```

### Tests
```bash
python -m pytest tests/test_pre_news_v2.py -v
# → 53 passed in 1.99s
```

---

## 8. Not Yet Done (Intentional Deferrals)

These are low-risk follow-ups that need separate review:

1. **Frontend build** — `Agentic.jsx` has new JSX; must run `npm run build` in frontend to verify
2. **Telegram emoji rendering** — some terminals may not render 💎 / ⚠ / ✨; tested with standard Unicode
3. **Scheduled decay more granular** — currently every 15 min via scan loop; could add a 5-min dedicated loop if needed
4. **Pattern memory warm-up** — currently needs 100 outcomes before activating; will auto-enable as data accumulates
5. **Per-source performance tracking** — discovery_source map is populated but not yet surfaced in learning stats

---

## 9. Files Touched in This Wiring Session

| File | Action |
|------|--------|
| `src/core/agentic/orchestrator.py` | Added `handoff_from_pre_news()` + `_build_pre_news_headline()` + `_confidence_for_score()` |
| `src/main.py` | Replaced inline handoff with `orch.handoff_from_pre_news()` + added `apply_confidence_decay_all()` call |
| `src/core/agentic/pre_news_detector.py` | Upgraded `format_alert()` to V2 format |
| `frontend/src/pages/Agentic.jsx` | Added V2 scoring block (smart money, pressure bars, badges, decay, source) |
| `tests/test_pre_news_v2.py` | 16 test classes, 53 assertions covering all V2 components |
| `docs/pre_news_v2_live_wiring_report.md` | This document |

---

## 10. Summary

| Feature | Wired | Tested | Logs |
|---------|-------|--------|------|
| Confidence decay | ✅ | ✅ | `PreNews V2 decay: N anomalies updated` |
| Agentic handoff | ✅ | ✅ | `PreNews V2 handoff: created=N updated=N skipped=N` |
| Telegram V2 alerts | ✅ | ✅ | `PreNews Telegram alert sent for TICKER` |
| Frontend V2 display | ✅ | ⏳ (needs npm build) | N/A |
| API V2 fields | ✅ | ✅ | All keys present in `/api/v1/agentic/pre-news/anomalies` |
| Pattern memory | ✅ | ✅ | Inactive until 100 outcomes (safe pass-through) |

---

*End of live wiring report.*
