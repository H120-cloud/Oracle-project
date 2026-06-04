# Oracle V22 — Full Market News Momentum Intelligence System

## Overview

Oracle V22 adds a comprehensive **News Momentum Intelligence System** that detects news catalysts across all market sessions (premarket, regular, after-hours), scores their impact, tracks price/volume reactions, and uses AI/ML to predict continuation probability and expected return.

## Architecture

```
News Sources (Finviz, StockTitan)
         |
         v
CatalystClassifier — classifies headlines into categories
         |
         v
NewsImpactScorer — scores catalyst materiality (0-100)
         |
         v
NewsReactionEngine — tracks price/volume reaction
         |
         v
ExpectedReturnMLEngine — AI ranking of candidates
         |
         v
ContinuationProbabilityEngine — predicts continuation
         |
         v
MultiDayContinuationEngine — predicts multi-day moves
         |
         v
NewsMomentumOrchestrator — wires everything, sends Telegram alerts
         |
         v
AdaptiveTelegramLearning — tracks alert outcomes, adapts thresholds
CatalystLearningEngine — learns best/worst catalysts from history
```

## Core Components

### 1. Data Models (`news_momentum_models.py`)

- **NewsMomentumCandidate** — Full candidate with all AI scores
- **NewsImpactScore** — Catalyst materiality, float sensitivity, sector hype, etc.
- **NewsReactionScore** — Price/volume reaction strength
- **ExpectedReturnMLScore** — ML-predicted expected return
- **ContinuationProbability** — Same-day, next-day, second-leg probabilities
- **MultiDayContinuation** — Multi-day runner prediction
- **TelegramAlertRecord** — Alert outcome tracking
- **CatalystLearningStats** — Historical catalyst statistics
- **NewsMomentumConfig** — System configuration

### 2. Catalyst Classifier (`news_momentum_catalyst_classifier.py`)

Classifies headlines into:
- **BIOTECH**: FDA approval, Phase 1/2/3, Fast Track, PDUFA, topline data
- **AI/TECH**: AI partnership, Nvidia/OpenAI partnership, hyperscaler contracts
- **FINANCIAL**: Earnings beat, guidance raise, profitability, insider buying
- **CRYPTO**: Bitcoin treasury, mining, blockchain partnerships
- **CORPORATE**: Merger, acquisition, buyout, licensing, patent
- **NEGATIVE**: Offering, ATM filing, reverse split, delisting, vague PR

### 3. News Impact Scorer (`news_momentum_impact_scorer.py`)

Computes composite score (0-100) from:
- Catalyst materiality (base score per catalyst type)
- Surprise factor
- Float sensitivity
- Market cap sensitivity
- Sector hype multiplier
- Short squeeze potential
- Volume expansion
- Spread quality
- VWAP behavior
- Pre-news accumulation
- Dilution risk (-weighted)
- Trap risk (-weighted)
- Price extension risk (-weighted)

### 4. News Reaction Engine (`news_momentum_reaction_engine.py`)

Tracks:
- Price before/after news
- Volume reaction
- RVOL score
- Spread behavior
- VWAP distance
- Continuation quality
- Halt impact

### 5. Expected Return ML Engine (`news_momentum_expected_return_engine.py`)

Weighted feature scoring:
- News impact score (18%)
- News reaction score (14%)
- Float sensitivity (12%)
- Volume expansion (12%)
- VWAP behavior (10%)
- Continuation quality (10%)
- Trap risk (-10%)
- Dilution risk (-8%)
- Price extension risk (-6%)

Applies catalyst-specific multipliers and historical stats blending.

### 6. Continuation Probability Engine (`news_momentum_continuation_engine.py`)

Predicts:
- Same-day continuation probability
- Second-leg probability
- Next-day continuation
- Gap-up next session
- Fade probability

### 7. Multi-Day Continuation Engine (`news_momentum_continuation_engine.py`)

Classifies setups as:
- ONE_DAY_SPIKE_ONLY
- POSSIBLE_CONTINUATION
- STRONG_MULTI_DAY_CANDIDATE
- SWING_RUNNER
- LIKELY_FADE
- EXHAUSTED

Predicts:
- Next-day continuation probability
- 2-day continuation probability
- 5-day continuation probability
- Swing trade quality score
- Exhaustion probability

### 8. Adaptive Telegram Learning (`news_momentum_telegram_learning.py`)

Tracks every alert:
- Price at alert
- Price 15m/1h/4h later
- Next-day open/high/close
- 2-day and 5-day highs
- MFE / MAE
- Outcome classification (GREAT, GOOD, LATE, TRAP, NO_FOLLOW_THROUGH)

Adapts thresholds after 100+ outcomes:
- Lowers thresholds if alert quality is high
- Raises thresholds if too many traps/no-follow-throughs

### 9. Catalyst Learning Engine (`news_momentum_catalyst_learning.py`)

Learns from historical outcomes:
- Best/worst catalyst types by continuation rate
- Best time of day
- Best float categories
- Best sessions
- Generates adaptive recommendations

### 10. Orchestrator (`news_momentum_orchestrator.py`)

- Fetches news from Finviz + StockTitan scrapers
- Classifies each headline
- Enriches with market data
- Computes all scores
- Determines Oracle action (WATCH, TRADEABLE, SWING_WATCH, AVOID_TRAP, etc.)
- Sends Telegram alerts when thresholds met
- Trap warnings sent separately

## API Endpoints

All under `/api/v1/news-momentum/`:

- `GET /candidates` — List active candidates
- `GET /candidates/{ticker}` — Get single candidate
- `POST /candidates/{ticker}/deactivate` — Deactivate candidate
- `GET /top-ranked` — Top ranked by expected return
- `GET /top-expected-return` — Top expected return
- `GET /top-continuation` — Top continuation probability
- `GET /top-multiday` — Top multi-day runners
- `GET /telegram-quality` — Alert quality stats
- `GET /history` — Historical candidates
- `GET /config` — Get configuration
- `POST /config` — Update configuration
- `POST /scan-now` — Trigger manual scan
- `GET /stats` — System statistics
- `GET /catalyst-stats` — Catalyst learning stats
- `GET /classify-headline?headline=...` — Test headline classification

## Telegram Alert Format

### High Impact Alert
```
🚨 HIGH IMPACT NEWS MOMENTUM

Ticker: ABC
Headline: ABC receives FDA approval for...
Session: premarket

Price: $2.50 | Move: +45%
Volume: 5.2M | RVOL: 8.5x
Float: low | MCap: micro

Catalyst: FDA Approval
News Impact: 95/100
Expected Return: 88/100
Continuation: 82%
Multi-Day: 75/100

Trap Risk: 15/100 | Dilution: 5/100

Oracle Action: TRADEABLE

Est. Moves:
  Conservative: +15%
  Bullish: +35%
  Extreme: +75%

Bull Case: Low float means explosive moves possible...
Bear Case: Limited if catalyst is genuine...
```

### Multi-Day Runner Alert
```
📈 MULTI-DAY RUNNER WATCH

Ticker: XYZ
Catalyst: AI Partnership
Multi-Day Score: 85/100
Next-Day: 72% | 2-Day: 60% | 5-Day: 45%
Swing Quality: 82/100
Exhaustion: 20/100

Oracle Action: SWING_WATCH
```

### Trap Warning
```
⚠️ MOMENTUM TRAP WARNING

Ticker: BAD
Trap Risk: 85/100
Dilution: 80/100
Exhaustion: 70/100

Oracle: DO NOT CHASE
Reason: Offering detected, already extended
```

## Background Scanning

The `_news_momentum_scan_loop()` in `main.py` runs continuously:
- Fetches news from Finviz and StockTitan every 45-120 seconds
- Classifies and scores each headline
- Enriches with live market data
- Sends Telegram alerts for high-scoring candidates
- Adaptive interval based on session type

## Configuration

Default config (`data/agentic/news_momentum_config.json`):
```json
{
  "enabled": true,
  "min_price": 0.20,
  "max_price": 5.00,
  "market_cap_filter": "micro",
  "float_filter": "low",
  "news_impact_threshold": 70.0,
  "expected_return_threshold": 75.0,
  "continuation_threshold": 70.0,
  "multi_day_threshold": 70.0,
  "scan_interval_seconds": 45,
  "low_activity_interval_seconds": 120,
  "telegram_enabled": true,
  "telegram_min_score": 70.0,
  "telegram_cooldown_minutes": 10,
  "ml_enabled": true,
  "min_outcomes_for_ml": 100,
  "learning_enabled": true,
  "min_samples_per_catalyst": 30,
  "min_total_samples": 100
}
```

## Frontend Dashboard

The `/news-momentum` page provides:
- Live candidate feed with all AI scores
- Tabbed views: All / Top Expected Return / Top Continuation / Multi-Day / Traps
- Telegram Quality panel with outcome statistics
- Learning panel with catalyst statistics and recommendations
- Adaptive threshold display
- Session filtering
- Manual scan trigger
- Auto-refresh every 30 seconds

## Guardrails

- Never auto-trades
- Telegram alerts only
- Aggressively flags dilution (offering, ATM, warrants)
- Downgrades vague PR
- Downgrades parabolic exhaustion (>200% move)
- Flags wide spreads (>8%)
- Prevents obvious chase entries
- Minimum 100 outcomes before adaptive threshold changes
- Minimum 30 outcomes per catalyst type for recommendations

## Persistence

- `data/agentic/news_momentum_candidates.json` — Active candidates
- `data/agentic/news_momentum_config.json` — System config
- `data/agentic/news_momentum_telegram_alerts.json` — Alert outcome records
- `data/agentic/news_momentum_outcomes.json` — Catalyst outcome records

All use atomic JSON file locking to prevent corruption.

## Future Roadmap

- Integrate Polygon.io real-time WebSocket for faster price updates
- Add SEC filing parser for 8-K / 6-K catalyst detection
- Train actual XGBoost models once 500+ outcomes collected
- Add sentiment analysis from social media (StockTwits, Twitter/X)
- Multi-timeframe volume profile integration
- Options flow integration for gamma squeeze detection
