# News Momentum Self-Training ML Pipeline

A closed feedback loop that turns every Telegram alert into a training example
and auto-retrains weekly to recognize which news catalysts actually predict
profitable moves. **Zero user input required** beyond running the system.

---

## How it Works

```
┌─────────────────┐    ┌──────────────────┐    ┌────────────────────┐    ┌──────────────────┐
│  Alert sent     │───▶│ Outcome Resolver │───▶│  Auto-label as     │───▶│  Weekly ML       │
│  (40 features   │    │ fetches 15m/1h/  │    │  WIN / LOSS /      │    │  retrain →       │
│  recorded)      │    │ 4h/1d/2d/5d      │    │  TRAP /            │    │  smarter gates   │
│                 │    │ price bars       │    │  NO_FOLLOW_THROUGH │    │                  │
└─────────────────┘    └──────────────────┘    └────────────────────┘    └──────────────────┘
```

You set this up once. It gets smarter every week.

---

## Components

### 1. `news_momentum_ml_engine.py`
- **XGBoost classifier** (LogisticRegression fallback if XGB fails)
- 32 features: scores, price action, market structure, catalyst archetype, session, time-of-day
- Auto-loads saved model on startup, auto-saves on retrain
- Auto-promotes new model only if AUC is at least as good as previous (within 0.02 tolerance)
- Returns `MLPrediction(win_probability, confidence, top_features, ...)` for every candidate
- Rule-based neutral fallback (`win_probability=0.5`, `used_model=False`) when no model is trained yet

### 2. `news_momentum_outcome_resolver.py`
- Background task: every **30 minutes**
- For every `TelegramAlertRecord` without an outcome:
  - Fetches 5d of 5m intraday bars + 10d of daily bars from market data provider
  - Computes price levels at 15m / 1h / 4h post-alert + next-day OHLC + 2d/5d highs
  - Calls `AdaptiveTelegramLearning.resolve_outcome()` to compute MFE/MAE and classify
- Force-finalizes outcomes after 5 days even with partial data, so the loop doesn't churn forever

### 3. Auto-Retrain Loop (`_news_momentum_ml_retrain_loop` in `main.py`)
- Runs every **Sunday at 02:00 UTC**
- Trains on all resolved alert records (needs ≥30 samples to train, ≥50 to promote)
- Telegram-pings you with model version, AUC, and top predictors when a new model is promoted

### 4. ML-Aware Gating (`_should_send_telegram`)
- After all rule-based gates pass, the trained model gets a final veto:
  - If `confidence ≥ 0.6` AND `win_probability < 0.30` → blocked
- The model can only **veto**, never override hard risk filters or float a junk alert through

---

## What Features the Model Sees (per alert)

| Category | Features |
|----------|----------|
| News scores | `news_impact_score`, `expected_return_score`, `continuation_probability`, `multi_day_score` |
| Price | `price_at_alert`, `log_price`, `move_pct_at_alert`, `abs_move_pct` |
| Volume | `rvol_at_alert`, `log_volume`, `spread_pct_at_alert` |
| Risk | `trap_risk_at_alert`, `dilution_risk_at_alert` |
| Velocity | `velocity_score_at_alert`, `sources_seen_count` |
| Flags | `is_negative`, `is_vague`, `is_delayed_reaction`, `prenews_anomaly_score` |
| Structure | `float_category_ord`, `market_cap_category_ord` |
| Time | `session_ord`, `is_premarket`, `is_after_hours`, `is_weekend_send`, `hour_of_day` |
| Catalyst archetype | `is_fda_catalyst`, `is_ai_catalyst`, `is_earnings_catalyst`, `is_corporate_action`, `is_vague_catalyst`, `is_negative_catalyst` |

---

## Auto-Labeling Logic

Labels are derived purely from price action — no manual tagging.
The existing `_classify_outcome` in `AdaptiveTelegramLearning` returns:

| Label | Condition |
|-------|-----------|
| `GREAT_ALERT` | MFE > 50% |
| `GOOD_ALERT` | MFE > 20% |
| `LATE_ALERT` | MFE ≤ 20%, MAE ≤ 20% |
| `TRAP_ALERT` | MFE < 5%, MAE > 10% (or MAE > 20%) |
| `NO_FOLLOW_THROUGH` | MFE < 5% |

For ML training, we map:
- **WIN class (1)** = `GREAT_ALERT`, `GOOD_ALERT`
- **LOSS class (0)** = `TRAP_ALERT`, `NO_FOLLOW_THROUGH`, `LATE_ALERT`

---

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/v1/agentic/news-momentum/ml/status` | Model version, AUC, top features |
| `POST /api/v1/agentic/news-momentum/ml/retrain` | Force immediate retrain |
| `POST /api/v1/agentic/news-momentum/outcomes/resolve-now` | Force outcome resolution pass |
| `GET  /api/v1/agentic/news-momentum/outcomes/unresolved` | List alerts still waiting on outcomes |
| `GET  /api/v1/agentic/news-momentum/stats` | Now includes `ml_engine` block |

---

## Persistence

| File | Contents |
|------|----------|
| `data/agentic/news_momentum_telegram_alerts.json` | Every alert with all features + outcome (training data) |
| `data/agentic/news_momentum_ml_model.joblib` | Trained model (joblib pickle) |
| `data/agentic/news_momentum_ml_meta.json` | Model version, AUC, sample count, feature importance |

---

## Cold Start Behavior

| Resolved alerts | Behavior |
|-----------------|----------|
| 0 to 29 | ML engine returns neutral (0.5) — pure rule-based gating |
| 30 to 49 | ML trains but does NOT promote (collecting evidence) |
| 50+ | ML promoted, starts vetoing low-confidence alerts |

So you get **no degradation** during the cold start phase, and **automatic improvement** as data accumulates.

---

## Tests

`tests/test_ml_engine_and_resolver.py` (11 tests, all passing):
- Untrained engine returns neutral fallback
- Training succeeds with balanced synthetic dataset
- Training fails gracefully on insufficient or single-class data
- Predictions distinguish strong winners from strong losers (AUC > 0.7)
- Save/load round-trip preserves predictions
- Feature extraction works on both `TelegramAlertRecord` and live `NewsMomentumCandidate`
- Outcome resolver helpers compute correct prices from synthetic OHLCV bars
- Resolver handles empty bars / missing data without crashing
- End-to-end flow with mocked market data provider

Plus the **full existing pytest suite (552 tests) still passes** — no regressions.
