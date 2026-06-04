# Oracle Lean Refactor Audit Plan

## Scope

Phase 1 is audit and dependency mapping only. No production code was changed, no files were deleted, alert behaviour was not altered, and Telegram logic was not modified.

Oracle's strategic direction is now a lean News Momentum and Rocket Runner platform focused on:

1. News Catalyst Detection
2. News Momentum Ranking
3. Pre-News Anomaly Detection
4. Rocket Runner Discovery
5. SEC / Dilution Intelligence
6. Telegram Alert Delivery
7. Historical Learning & ML Ranking

## Executive Summary

The current codebase contains two overlapping generations of Oracle:

- **Strategic platform:** News Momentum, Pre-News, Rocket Runner, SEC intelligence, Telegram alerting, outcome resolution, ML ranking, and historical learning.
- **Legacy platform:** Dip/bounce signal generation, scanner dashboards, watchlists, paper trading, old backtests, older intelligence pages, and related ML models.

The strategic system is concentrated in:

- `src/core/agentic/`
- `src/api/routes/news_momentum.py`
- `src/api/routes/pre_news.py`
- `src/api/routes/sec_intelligence.py`
- `src/api/routes/agentic.py`
- `src/api/routes/historical_training.py`
- `src/services/telegram_service.py`
- `src/services/market_data.py` and required providers
- `frontend/src/pages/Agentic.jsx`
- `frontend/src/pages/NewsMomentum.jsx`
- `frontend/src/pages/SECIntelligence.jsx`
- `frontend/src/pages/HistoricalTraining.jsx`

The heaviest legacy runtime costs are currently:

- `Watchlist` real-time broadcaster loop: wakes every 1 second and can call market data / alert checks.
- `PaperTrading` price updater loop: wakes every 30 seconds and fetches prices for simulated positions.
- `OutcomeSimulator` loop: legacy signal outcome resolver every 30 minutes.
- Legacy routes loaded at startup: `scanner`, `signals`, `watchlist`, `models`, `analysis`, `backtest`, `intelligence`, `htf_scan`, `paper_trading`.
- Frontend legacy pages: `Dashboard`, `Analysis`, `Backtest`, `Performance`, `Portfolio`, `Watchlist`, `Intelligence`, `ActiveTrades`, `PaperTrading`, `Settings`.

Recommended approach: **do not delete immediately**. First put legacy systems behind explicit feature flags, confirm the strategic dashboard still works, then archive routes/pages/modules in stages.

## Current Architecture Summary

### Startup Entry Point

`src/main.py` is the central runtime entry point.

Active startup behaviour observed:

- Loads `.env` before imports.
- Creates database tables via `Base.metadata.create_all(...)`.
- Starts legacy signal outcome simulator.
- Starts watchlist real-time broadcaster.
- Starts paper trading price updater.
- Starts pre-news volume anomaly scanner.
- Starts Telegram command polling.
- Initializes `NewsMomentumOrchestrator`.
- Wires SEC intelligence orchestrator into API.
- Starts Alpaca real-time news stream if credentials/SDK are available.
- Starts News Momentum RSS scan loop.
- Starts SEC EDGAR 8-K firehose.
- Starts News Momentum EOD review.
- Starts News Momentum outcome resolver.
- Starts weekly News Momentum ML retrain.
- SEC Intelligence hourly loop exists but is currently disabled.
- Agentic outcome loop exists but is currently disabled.

### Strategic Runtime Loops

| Loop | File | Interval / Timing | Classification | Reason |
|---|---|---:|---|---|
| `_pre_news_scan_loop` | `src/main.py` | 180s | KEEP | Core pre-news anomaly detection and Telegram alerts. |
| `_news_momentum_scan_loop` | `src/main.py` | config-driven, ~20s active | KEEP | Core RSS/news momentum discovery. |
| Alpaca stream handler | `src/services/alpaca_news_stream.py` + `src/main.py` | event-driven | KEEP | Real-time news alert path. |
| `_sec_edgar_firehose_loop` | `src/main.py` | 15s default | KEEP | SEC 8-K catalyst firehose. |
| `_news_momentum_eod_review_loop` | `src/main.py` | daily | KEEP | Missed winner learning and review. |
| `_news_momentum_outcome_resolver_loop` | `src/main.py` | 30 min | KEEP | ML feedback loop for resolved alerts. |
| `_news_momentum_ml_retrain_loop` | `src/main.py` | weekly | KEEP | Historical learning / ML ranking. |
| `telegram_command_polling_loop` | `src/services/telegram_command_handler.py` | command polling | KEEP | Telegram delivery/interaction layer. |

### Legacy / Candidate Runtime Loops

| Loop | File | Interval / Timing | Classification | Reason |
|---|---|---:|---|---|
| `_watchlist_broadcast_loop` | `src/main.py` | 1s | DISABLE_BEHIND_FLAG | High-frequency legacy watchlist loop; not central to news momentum. |
| `_paper_trading_price_loop` | `src/main.py` | 30s | DISABLE_BEHIND_FLAG | Paper trading is not strategic for lean news/rocket platform. |
| `_outcome_simulator_loop` | `src/main.py` | 30 min | DISABLE_BEHIND_FLAG | Resolves old signal outcomes, not News Momentum outcomes. |
| `_agentic_outcome_loop` | `src/main.py` | disabled | ARCHIVE | Already disabled; old Agentic candidate outcome loop overlaps with newer outcome systems. |
| `_sec_intelligence_scan_loop` | `src/main.py` | disabled | KEEP_DISABLED | SEC is strategic, but current hourly scan is disabled; keep for optional future controlled flag. |

## Dependency Map

### Strategic Core Dependency Map

#### News Momentum Orchestrator

**File:** `src/core/agentic/news_momentum_orchestrator.py`

**Imports / dependencies:**

- `news_momentum_models`
- `news_momentum_catalyst_classifier`
- `bullish_catalyst_flash`
- `news_momentum_impact_scorer`
- `news_momentum_reaction_engine`
- `news_momentum_expected_return_engine`
- `news_momentum_continuation_engine`
- `news_momentum_telegram_learning`
- `news_momentum_catalyst_learning`
- `news_momentum_missed_learning`
- `news_momentum_ml_engine`
- `news_momentum_winners`
- `news_momentum_big_winner_model`
- `news_momentum_unknown_learner`
- `sec_intelligence_orchestrator`
- `telegram_service.send_telegram_alert`
- `atomic_json`
- optional `PolygonProvider`

**What depends on it:**

- `src/main.py`
- `src/api/routes/news_momentum.py`
- SEC API wiring via shared orchestrator
- Alpaca stream handler path
- SEC EDGAR firehose path
- outcome resolver / EOD / ML retrain loops

**What breaks if removed:**

- Core alert engine
- News Momentum dashboard
- Telegram news alerts
- ML outcome loop
- missed winner loop
- SEC cross-analysis inside candidates

**Classification:** KEEP

#### News Catalyst Classifier

**Files:**

- `src/core/agentic/news_momentum_catalyst_classifier.py`
- `src/core/agentic/news_momentum_nlp_classifier.py`
- `src/core/agentic/news_momentum_models.py`

**What depends on it:**

- News Momentum scan loop in `src/main.py`
- `NewsMomentumOrchestrator`
- `/api/v1/news-momentum/classify-headline`
- regression tests

**What breaks if removed:**

- Catalyst type/subtype detection
- impact scoring input quality
- high-conviction routing
- Telegram gate logic

**Classification:** KEEP

#### News Impact / Reaction / Continuation / Expected Return Engines

**Files:**

- `src/core/agentic/news_momentum_impact_scorer.py`
- `src/core/agentic/news_momentum_reaction_engine.py`
- `src/core/agentic/news_momentum_continuation_engine.py`
- `src/core/agentic/news_momentum_expected_return_engine.py`
- `src/core/agentic/news_momentum_winners.py`
- `src/core/agentic/news_momentum_big_winner_model.py`
- `src/core/agentic/news_momentum_ml_engine.py`

**What depends on them:**

- `NewsMomentumOrchestrator`
- `/api/v1/news-momentum/*`
- ML retrain / outcome resolver workflows
- frontend `NewsMomentum.jsx`

**What breaks if removed:**

- ranking
- alert quality gates
- continuation estimates
- rocket/big-winner probability
- Telegram score summaries

**Classification:** KEEP

#### News Scrapers and Streams

**Files:**

- `src/core/finviz_news.py`
- `src/core/stocktitan_news.py`
- `src/services/alpaca_news_stream.py`
- `src/core/agentic/sec_edgar_firehose.py`
- `src/core/agentic/news_momentum_utils.py`

**What depends on them:**

- `_news_momentum_scan_loop`
- `_handle_streamed_news`
- `_sec_edgar_firehose_loop`
- `PreNewsDetector.update_news_status()`
- `CatalystScanner`
- `/api/v1/news/*`

**What breaks if removed:**

- news ingestion
- deduplication
- early catalyst detection
- pre-news catalyst confirmation

**Classification:** KEEP

#### Pre-News Detector

**Files:**

- `src/core/agentic/pre_news_detector.py`
- `src/core/agentic/pre_news_models.py`
- `src/core/agentic/pre_news_learning.py`
- `src/core/agentic/pre_news_validation.py`
- `src/core/agentic/pre_news_shadow_v2.py`
- `src/core/agentic/pre_news_baseline.py`
- `src/core/agentic/pre_news_evaluator.py`
- `src/core/agentic/pre_news_scoring.py`

**What depends on it:**

- `_pre_news_scan_loop` in `src/main.py`
- `src/api/routes/pre_news.py`
- `AgenticOrchestrator.handoff_from_pre_news(...)`
- frontend `Agentic.jsx`
- frontend API methods `preNews*`

**What breaks if removed:**

- pre-news volume anomaly alerts
- hidden catalyst detection
- pre-news validation/outcome tracking
- Agentic pre-news handoff

**Classification:** KEEP

#### Rocket Runner / Historical Learning

**Files:**

- `src/core/agentic/rocket_dataset_builder.py`
- `src/core/agentic/rocket_label_reconstruction.py`
- `src/core/agentic/rocket_forward_enrichment.py`
- `src/core/agentic/news_momentum_historical_backfill.py`
- `src/core/agentic/historical_training.py`
- `src/core/agentic/historical_dataset_builder.py`
- `src/core/agentic/historical_features.py`
- `src/core/agentic/historical_models.py`
- `src/core/agentic/historical_outcomes.py`
- `src/core/agentic/historical_calibration.py`
- `src/api/routes/historical_training.py`
- `frontend/src/pages/HistoricalTraining.jsx`

**What depends on it:**

- historical training routes
- frontend historical training dashboard
- ML/research datasets under `data/agentic`

**What breaks if removed:**

- rocket dataset build/reconstruction/enrichment
- historical training UI
- model calibration tooling

**Classification:** KEEP, with data pruning recommended separately.

#### SEC / Dilution Intelligence

**Files:**

- `src/core/agentic/sec_intelligence_orchestrator.py`
- `src/core/agentic/sec_filing_models.py`
- `src/core/agentic/sec_filing_fetcher.py`
- `src/core/agentic/sec_filing_analyzer.py`
- `src/core/agentic/sec_edgar_firehose.py`
- `src/api/routes/sec_intelligence.py`
- `frontend/src/pages/SECIntelligence.jsx`

**What depends on it:**

- `NewsMomentumOrchestrator` SEC adjustment path
- `/api/v1/sec-intelligence/*`
- SEC EDGAR 8-K firehose loop
- frontend `SECIntelligence.jsx`

**What breaks if removed:**

- dilution risk adjustment
- SEC structural trap analysis
- EDGAR catalyst firehose

**Classification:** KEEP

#### Telegram Alert System

**Files:**

- `src/services/telegram_service.py`
- `src/services/telegram_command_handler.py`

**What depends on it:**

- News Momentum alerts
- Pre-News alerts
- EOD review summaries
- ML retrain summaries
- watchlist legacy alerts currently also call it

**What breaks if removed:**

- primary alert delivery channel

**Classification:** KEEP

### Legacy Candidate Dependency Map

#### Dip Detector / Bounce Detector / Old Signal Pipeline

**Files:**

- `src/core/dip_detector.py`
- `src/core/bounce_detector.py`
- `src/ml/dip_model.py`
- `src/ml/bounce_model.py`
- `src/ml/model_store.py`
- `src/services/signal_service.py`
- `src/api/routes/signals.py`
- `src/api/routes/models.py`

**Imports / dependencies observed:**

- `src/services/signal_service.py` imports `DipDetector`, `BounceDetector`, `DipModel`, `BounceModel`.
- `src/services/watchlist_service.py` lazily imports `DipDetector` and `BounceDetector` during metric refresh.
- `src/core/backtester.py` imports `DipDetector` and `BounceDetector`.
- `src/core/backtest_validator.py` imports `DipDetector` and `BounceDetector`.
- `src/api/dependencies.py` constructs `SignalService`.
- `src/main.py` includes `signals.router` and `models.router`.
- `frontend/src/api.js` exposes `getSignals`, `analyzeSignal`, `recordOutcome`, `getModelStatus`, `trainModels`.

**What depends on it:**

- `/api/v1/signals/*`
- `/api/v1/models/*`
- legacy Dashboard/Settings signal pipeline concepts
- old backtest and validation modules
- watchlist metrics optional dip/bounce probabilities

**What would break if removed now:**

- Signal generation endpoints
- old model status/training endpoints
- old backtest validator
- watchlist dip/bounce columns/alerts
- any frontend page calling legacy signal APIs

**Safe to disable:**

- Yes, but only if `signals.router`, `models.router`, and watchlist dip/bounce metrics are disabled together or behind flags.

**Classification:** DISABLE_BEHIND_FLAG first, ARCHIVE later, DELETE_LATER after no traffic.

#### Legacy Scanner Routes

**Files:**

- `src/api/routes/scanner.py`
- `src/core/scanner.py`
- `src/core/professional_scanner.py`
- `src/core/discovery_engine.py`
- `src/core/finviz_scanner.py`

**Imports / dependencies observed:**

- `scanner.py` imports `FinvizScanner`, `MarketScanner`, `ProfessionalScanner`, `DiscoveryEngine`, `get_market_data_provider`.
- `signal_service.py` also uses scanners.
- `PreNewsDetector` and News Momentum ticker-specific scan reuse `FinvizScanner`.

**What depends on it:**

- `/api/v1/scanner/*`
- frontend `discoverTickers`, `discoverTrading212`
- legacy dashboard/scanner flows
- strategic systems reuse `FinvizScanner`, not necessarily the route.

**What would break if removed now:**

- scanner API/UI
- any manual scanner discovery calls

**Safe to disable:**

- Routes are safe to disable behind a flag.
- Do **not** remove `FinvizScanner`; strategic Pre-News and News Momentum use it.

**Classification:**

- `src/api/routes/scanner.py`: DISABLE_BEHIND_FLAG
- `src/core/scanner.py`: ARCHIVE after route disabled
- `src/core/professional_scanner.py`: ARCHIVE after route disabled
- `src/core/discovery_engine.py`: REVIEW; may still support news discovery / scanner only
- `src/core/finviz_scanner.py`: KEEP

#### Legacy Watchlist

**Files:**

- `src/api/routes/watchlist.py`
- `src/services/watchlist_service.py`
- `frontend/src/pages/Watchlist.jsx`
- database watchlist tables/repositories
- `/ws/watchlist` WebSocket in `src/main.py`

**Imports / dependencies observed:**

- `main.py` imports `watchlist.router` and runs `_watchlist_broadcast_loop`.
- `_watchlist_broadcast_loop` lazily imports `WatchlistService`.
- `watchlist_service.py` imports `WatchlistRepository`, `get_market_data_provider`, HTF services, `HigherTimeframeBiasDetector`, and lazily imports dip/bounce detectors.
- frontend `Watchlist.jsx` opens WebSocket at `/ws/watchlist` and calls many `/watchlist/*` endpoints.
- frontend `Watchlist.jsx` has known XSS risk from `dangerouslySetInnerHTML` with scraped headlines.

**What depends on it:**

- Watchlist frontend page
- custom alerts
- HTF alerts
- dashboard/watchlist UX
- old dip/bounce alerting

**What would break if removed now:**

- `/api/v1/watchlist/*`
- `/ws/watchlist`
- watchlist page
- custom alerts and earnings warnings

**Safe to disable:**

- Yes for lean platform, but behind a flag first because it has DB state and frontend route coupling.

**Classification:** DISABLE_BEHIND_FLAG, then ARCHIVE.

#### Paper Trading

**Files:**

- `src/api/routes/paper_trading.py`
- `src/services/broker_service.py`
- `frontend/src/pages/PaperTrading.jsx`
- `data/paper_trading/*`
- `_paper_trading_price_loop` in `src/main.py`

**Imports / dependencies observed:**

- `main.py` imports `paper_trading.router` and starts `_paper_trading_price_loop`.
- `_paper_trading_price_loop` imports `_get_broker` from `api.routes.paper_trading`.
- `paper_trading.py` imports `BrokerService` and `PaperOrder`.
- `paper_trading.py` uses `BacktestValidator` for validation endpoints.
- `broker_service.py` optionally uses Alpaca trading client but defaults local simulation.

**What depends on it:**

- `/api/v1/paper-trading/*`
- frontend `PaperTrading.jsx`
- paper validation endpoints
- local JSON paper trading state

**What would break if removed now:**

- Paper trading UI/API
- validation endpoints under paper trading
- open paper position updates

**Safe to disable:**

- Yes. Not part of the strategic core. Disable loop and route behind a flag before archiving.

**Classification:** DISABLE_BEHIND_FLAG, ARCHIVE later.

#### Backtest / Legacy Validation

**Files:**

- `src/api/routes/backtest.py`
- `src/core/backtester.py`
- `src/core/backtest_validator.py`
- `src/core/full_featured_backtester.py`
- `src/core/htf_impact_backtester.py`
- `frontend/src/pages/Backtest.jsx`

**Imports / dependencies observed:**

- `backtest.py` imports `Backtester`, `SelfLearner`, `OrderFlowAnalyzer`, `get_market_data_provider`.
- `paper_trading.py` imports `BacktestValidator`.
- `backtester.py` and `backtest_validator.py` depend on dip/bounce detectors.

**What depends on it:**

- `/api/v1/backtest`
- paper trading validation endpoints
- frontend `Backtest.jsx`

**What would break if removed now:**

- legacy backtest page/API
- paper validation endpoints

**Safe to disable:**

- Yes, but coordinate with paper trading disablement.

**Classification:** ARCHIVE after `paper_trading` and `backtest` routes are disabled.

#### Legacy Intelligence / Analysis / Active Trades

**Files:**

- `src/api/routes/intelligence.py`
- `src/core/intelligence_engine.py`
- `src/api/routes/analysis.py`
- `frontend/src/pages/Intelligence.jsx`
- `frontend/src/pages/Analysis.jsx`
- `frontend/src/pages/ActiveTrades.jsx`

**Imports / dependencies observed:**

- `intelligence.py` constructs `IntelligenceEngine` at import time using `get_market_data_provider()`.
- `signal_service.py` constructs `IntelligenceEngine` too.
- `intelligence_engine.py` imports many old modules including `AdaptationEngine` and market context engines.
- frontend `api.js` exposes `analyzeIntelligence`, active trade tracking, learning weights, market context.

**What depends on it:**

- `/api/v1/intelligence/*`
- legacy Intelligence and Active Trades pages
- signal service advanced analysis

**What would break if removed now:**

- old intelligence dashboard
- active trade tracking
- old learning weights

**Safe to disable:**

- Yes if the new News Momentum / SEC / Agentic dashboards replace it.

**Classification:** DISABLE_BEHIND_FLAG, ARCHIVE later.

#### HTF-Aware Scanner / Higher Timeframe Services

**Files:**

- `src/api/routes/htf_scan.py`
- `src/core/htf_aware_scanner.py`
- `src/core/higher_timeframe_bias.py`
- `src/services/htf_alert_service.py`

**Imports / dependencies observed:**

- `main.py` includes `htf_scan.router`.
- `watchlist_service.py` uses HTF detector and alert service.
- `signal_service.py` imports HTF scanner helpers.

**What depends on it:**

- watchlist HTF section
- old scanner/signal pipeline

**What would break if removed now:**

- HTF watchlist alerts
- HTF scanner endpoints

**Safe to disable:**

- Yes with watchlist/signal route disablement.

**Classification:** ARCHIVE with watchlist/scanner legacy group.

#### General News API Page

**Files:**

- `src/api/routes/news.py`
- `frontend/src/pages/News.jsx`
- `src/core/finviz_news.py`
- `src/core/stocktitan_news.py`

**What depends on it:**

- frontend news page
- manual news debugging
- scrapers are used by strategic systems.

**What would break if route/page removed:**

- manual news dashboard only.
- Strategic scans do **not** require the route, but require the scraper files.

**Safe to disable:**

- Page/route can be disabled later if dashboard simplification is desired.
- Keep scrapers.

**Classification:** KEEP_SHORT_TERM; possible ARCHIVE for route/page only after core dashboard covers manual feed diagnostics.

## Keep List

### Backend

- `src/main.py` strategic loops and app shell
- `src/core/agentic/news_momentum_orchestrator.py`
- `src/core/agentic/news_momentum_models.py`
- `src/core/agentic/news_momentum_catalyst_classifier.py`
- `src/core/agentic/news_momentum_nlp_classifier.py`
- `src/core/agentic/news_momentum_impact_scorer.py`
- `src/core/agentic/news_momentum_reaction_engine.py`
- `src/core/agentic/news_momentum_expected_return_engine.py`
- `src/core/agentic/news_momentum_continuation_engine.py`
- `src/core/agentic/news_momentum_winners.py`
- `src/core/agentic/news_momentum_ml_engine.py`
- `src/core/agentic/news_momentum_big_winner_model.py`
- `src/core/agentic/news_momentum_missed_learning.py`
- `src/core/agentic/news_momentum_unknown_learner.py`
- `src/core/agentic/news_momentum_telegram_learning.py`
- `src/core/agentic/news_momentum_catalyst_learning.py`
- `src/core/agentic/news_momentum_outcome_resolver.py`
- `src/core/agentic/news_momentum_eod_review.py`
- `src/core/agentic/news_momentum_utils.py`
- `src/core/agentic/bullish_catalyst_flash.py`
- `src/core/agentic/pre_news_*`
- `src/core/agentic/sec_*`
- `src/core/agentic/rocket_*`
- `src/core/agentic/historical_*`
- `src/core/agentic/calibration_provider.py`
- `src/core/agentic/feature_flags.py`
- `src/core/agentic/alert_state_machine.py` if used by strategic alerts / gating
- `src/core/finviz_news.py`
- `src/core/stocktitan_news.py`
- `src/core/finviz_scanner.py`
- `src/core/stocktwits_scraper.py` if still used by Pre-News universe discovery
- `src/services/telegram_service.py`
- `src/services/telegram_command_handler.py`
- `src/services/market_data.py`
- `src/services/alpaca_provider.py`
- `src/services/alpaca_news_stream.py`
- `src/services/polygon_provider.py`
- `src/services/yahoo_finance_provider.py`
- `src/api/routes/news_momentum.py`
- `src/api/routes/pre_news.py`
- `src/api/routes/sec_intelligence.py`
- `src/api/routes/agentic.py`
- `src/api/routes/historical_training.py`
- `src/api/routes/news.py` temporarily for feed diagnostics
- `src/api/routes/health.py`

### Frontend

- `frontend/src/pages/Agentic.jsx`
- `frontend/src/pages/NewsMomentum.jsx`
- `frontend/src/pages/SECIntelligence.jsx`
- `frontend/src/pages/HistoricalTraining.jsx`
- `frontend/src/pages/News.jsx` temporarily
- `frontend/src/api.js` strategic functions
- `frontend/src/App.jsx` after nav pruning

### Data / Models

- `data/agentic/news_momentum_candidates.json`
- `data/agentic/news_momentum_event_registry.json`
- `data/agentic/news_momentum_shadow_alerts.json`
- `data/agentic/news_momentum_missed_winners.json`
- `data/agentic/news_momentum_*_meta.json`
- `data/agentic/pre_news_anomalies.json`
- `data/agentic/pre_news_outcomes.json`
- `data/agentic/pre_news_validation*.json`
- `data/agentic/sec/*`
- `data/agentic/ml_models/*` current promoted/recent models
- rocket datasets, but prune/archive old enrichment artifacts after backup

## Disable Behind Flag List

These should first be hidden behind environment or config flags, defaulting off in lean mode.

| Component | Files | Suggested Flag | Why |
|---|---|---|---|
| Legacy signal routes | `src/api/routes/signals.py`, `src/services/signal_service.py` | `ENABLE_LEGACY_SIGNALS=false` | Old dip/bounce pipeline. |
| Legacy model routes | `src/api/routes/models.py`, `src/ml/dip_model.py`, `src/ml/bounce_model.py` | `ENABLE_LEGACY_MODELS=false` | Old dip/bounce ML. |
| Scanner routes | `src/api/routes/scanner.py` | `ENABLE_LEGACY_SCANNER=false` | Keep `FinvizScanner`, disable manual scanner API. |
| Watchlist routes/page/loop | `src/api/routes/watchlist.py`, `src/services/watchlist_service.py`, `_watchlist_broadcast_loop`, `Watchlist.jsx` | `ENABLE_LEGACY_WATCHLIST=false` | High-frequency loop and old alert model. |
| Paper trading routes/page/loop | `src/api/routes/paper_trading.py`, `src/services/broker_service.py`, `_paper_trading_price_loop`, `PaperTrading.jsx` | `ENABLE_PAPER_TRADING=false` | Not strategic for alerting. |
| Legacy analysis routes/page | `src/api/routes/analysis.py`, `Analysis.jsx` | `ENABLE_LEGACY_ANALYSIS=false` | Old manual technical analysis UI. |
| Legacy intelligence routes/page | `src/api/routes/intelligence.py`, `Intelligence.jsx`, `ActiveTrades.jsx` | `ENABLE_LEGACY_INTELLIGENCE=false` | Older intelligence/trade tracking system. |
| Backtest routes/page | `src/api/routes/backtest.py`, `Backtest.jsx` | `ENABLE_LEGACY_BACKTEST=false` | Old dip/bounce backtest path. |
| HTF scanner route | `src/api/routes/htf_scan.py` | `ENABLE_LEGACY_HTF=false` | Coupled to watchlist/signal pipeline. |
| Legacy outcome simulator | `_outcome_simulator_loop`, `src/core/outcome_simulator.py` | `ENABLE_LEGACY_OUTCOME_SIMULATOR=false` | Old signal outcomes, not News Momentum outcomes. |

## Archive List

Archive means move out of the runtime import path after one release with flags disabled and no traffic/errors.

- `src/core/dip_detector.py`
- `src/core/bounce_detector.py`
- `src/ml/dip_model.py`
- `src/ml/bounce_model.py`
- `src/ml/model_store.py` if only used by dip/bounce models
- `src/core/backtester.py`
- `src/core/backtest_validator.py`
- `src/core/full_featured_backtester.py`
- `src/core/htf_impact_backtester.py`
- `src/core/scanner.py`
- `src/core/professional_scanner.py`
- `src/core/decision_engine.py`
- `src/core/signal_ranker.py`
- `src/core/classifier.py` if only used by legacy signals
- `src/core/volume_profile.py` if only used by legacy analysis/signals
- `src/core/regime_detector.py` if only used by legacy analysis/signals
- `src/core/stage_detector.py` if only used by legacy analysis/signals/backtests
- `src/core/order_flow.py` if only used by legacy signals/backtest
- `src/core/ict_detector.py` if only used by legacy signals/backtest
- `src/core/intelligence_engine.py` and related old intelligence engines if not referenced by strategic modules
- frontend pages: `Analysis.jsx`, `Backtest.jsx`, `Performance.jsx`, `Portfolio.jsx`, `Watchlist.jsx`, `Intelligence.jsx`, `ActiveTrades.jsx`, `PaperTrading.jsx`

## Delete-Later List

Delete only after:

1. Feature flag disabled in production.
2. One full market week without usage or errors.
3. Strategic dashboards verified.
4. Backup of data files and model artifacts created.
5. Tests updated to remove legacy expectations.

Candidate delete-later groups:

- Legacy signal API + service group.
- Legacy dip/bounce model group.
- Legacy backtest group.
- Legacy watchlist group.
- Paper trading group.
- Old frontend pages removed from navigation and routes.
- Old JSON state under `data/paper_trading`.
- Old model artifacts that are not News Momentum / rocket models.
- `__pycache__` directories from `src`, `tests`, and services. These are safe cleanup targets but should be done separately from functional refactor.

## Data Store Audit

Observed `data/agentic` contains many strategic and research artifacts.

Largest areas observed from read-only inventory:

- `data/agentic/rocket_forward_enrichment`: about 37 MB, 778 files.
- `data/agentic/backfill_runs`: about 27 MB.
- `data/agentic/sec`: about 3.6 MB.
- `data/agentic/ml_models`: about 1.2 MB.
- `data/agentic/evaluation_reports`: about 221 KB.

Recommendations:

- Keep active state files required by runtime alerting.
- Keep current promoted model and last few backups.
- Archive old backfill runs and rocket enrichment artifacts to compressed cold storage.
- Do not delete `news_momentum_shadow_alerts.json`; it is critical for missed-alert forensics.
- Do not delete `news_momentum_event_registry.json` unless a migration is implemented.
- Do not delete pre-news validation files; they feed learning and audit.

## Performance Analysis

### Startup Time Contributors

| Contributor | Evidence | Impact | Recommendation |
|---|---|---:|---|
| Importing all routes in `src/main.py` | `main.py` imports scanner/signals/watchlist/models/analysis/backtest/intelligence/news/htf/paper/agentic/pre_news/historical/news_momentum/sec | Medium | Lazy/conditional include legacy routes. |
| `intelligence.py` constructs `IntelligenceEngine` at import time | route-level `_provider = get_market_data_provider(); _engine = IntelligenceEngine(...)` | Medium to high | Disable route or lazy-init behind flag. |
| DB table creation | `Base.metadata.create_all` at startup | Low to medium | Keep; not primary target. |
| NewsMomentumOrchestrator model/data loads | ML engines and JSON state loaded in `__init__` | Medium but strategic | Keep; optimize only if slow. |
| SEC orchestrator state load | wired through News Momentum | Low/medium and strategic | Keep. |

### Memory Contributors

| Contributor | Approx evidence | Classification |
|---|---:|---|
| `src/core/agentic` codebase | about 3.6 MB source | KEEP |
| `news_momentum_orchestrator.py` | 122 KB | KEEP |
| `pre_news_detector.py` | 84 KB | KEEP |
| `rocket_dataset_builder.py` | 58 KB | KEEP |
| `decision_engine.py` | 41 KB | ARCHIVE candidate |
| `broker_service.py` | 27 KB | DISABLE/ARCHIVE candidate |
| `watchlist_service.py` | 23 KB | DISABLE/ARCHIVE candidate |
| frontend `Agentic.jsx` | 143 KB | KEEP but later split for maintainability |
| frontend `Watchlist.jsx` | 51 KB | DISABLE/ARCHIVE candidate |

### Longest / Most Frequent Background Loops

| Loop | Frequency | Expected Gain if Disabled |
|---|---:|---|
| Watchlist broadcaster | 1s | High reduction in wakeups, DB sessions, WebSocket work, quote checks. |
| Paper trading price loop | 30s | Medium reduction when paper positions exist. |
| Legacy outcome simulator | 30 min | Low to medium; removes old DB/market checks. |
| News Momentum scan | ~20s active | Keep; core. |
| Pre-News scan | 180s | Keep; core. |
| SEC firehose | 15s | Keep; core, but can be tuned if rate issues. |

### Duplicate Scans / Market Data Calls

Potential duplication observed:

- News Momentum scan loop fetches Finviz global feed, StockTitan feed, then ticker-specific Finviz news for hot tickers from `FinvizScanner` gainers/under-$2.
- Pre-News scan also uses `FinvizScanner`, `FinvizNewsScraper`, `StockTitanScraper`, and market data provider.
- Watchlist broadcaster separately fetches watchlist prices and event checks every second.
- Paper trading loop separately fetches yfinance prices every 30 seconds.
- Legacy analysis/intelligence endpoints create their own provider/engine paths.

Recommended optimization after flags:

1. Disable watchlist + paper loops first.
2. Add a shared short-lived quote/news cache for News Momentum + Pre-News.
3. Consider shared hot ticker universe between Pre-News and News Momentum ticker-specific fetches.
4. Keep SEC firehose separate because it is event-source-specific.

### Estimated CPU/RAM Reduction

These are estimates because no profiler run was performed in this audit phase.

| Change | CPU / I/O reduction | RAM reduction | Notes |
|---|---:|---:|---|
| Disable watchlist broadcaster | 20-40% runtime wakeup/DB/quote reduction during active UI use | Low/medium | Biggest non-core loop. |
| Disable paper trading loop | 5-15% when positions exist | Low | Removes yfinance fetch cycle. |
| Disable legacy route imports | 5-15% startup/import reduction | Medium | Avoids loading old engines at boot. |
| Disable legacy intelligence import-time engine | 5-20% startup reduction | Medium | Depends on provider/model initialization cost. |
| Archive frontend legacy pages | Faster frontend build/load/nav clarity | Low runtime | Biggest UX simplification. |
| Archive old backfill/enrichment data | Disk reduction 30-60 MB | None at runtime unless loaded | Keep compressed backup. |

### Estimated Scan-Speed Improvement

Expected impact on strategic scans:

- News Momentum scan speed: **10-25% improvement** if duplicate quote pressure from watchlist/paper/legacy endpoints is removed.
- Pre-News scan stability: **10-20% improvement** due to reduced provider contention / fewer simultaneous yfinance calls.
- Startup time: **15-35% improvement** after conditional route loading and disabling import-time legacy engines.
- Alert latency: indirect improvement; fewer background competitors should reduce event-loop and network contention.

## Risk Assessment

### High Risk If Removed Directly

- `FinvizScanner`: strategic systems use it even though scanner routes are legacy.
- `market_data.py`: required everywhere.
- `telegram_service.py`: alert delivery.
- `news.py` route/scrapers: scrapers are strategic; route can be optional but files cannot be deleted.
- `AgenticOrchestrator`: legacy-ish Agentic V11 overlaps with Rocket Runner but still receives Pre-News handoff and powers `Agentic.jsx`.

### Medium Risk

- Watchlist: has DB tables, WebSocket route, custom alerts, and frontend page. Disable behind flag first.
- Paper trading: has local state and validation endpoints. Disable behind flag first.
- Legacy intelligence: route constructs heavy engine at import time; disable carefully.
- Backtest: coupled to paper validation.

### Low Risk

- Old frontend nav entries after routes are disabled.
- `__pycache__` cleanup.
- Archived old backfill run artifacts after backup.
- Disabled `_agentic_outcome_loop` cleanup after confirming no planned use.

## Recommended Migration Order

### Phase 2A — Add Lean Mode Flags Only

No deletion. Add config/env flags and conditionally include routes/loops.

Recommended flags:

```env
ORACLE_LEAN_MODE=true
ENABLE_LEGACY_SIGNALS=false
ENABLE_LEGACY_MODELS=false
ENABLE_LEGACY_SCANNER=false
ENABLE_LEGACY_WATCHLIST=false
ENABLE_PAPER_TRADING=false
ENABLE_LEGACY_BACKTEST=false
ENABLE_LEGACY_ANALYSIS=false
ENABLE_LEGACY_INTELLIGENCE=false
ENABLE_LEGACY_HTF=false
ENABLE_LEGACY_OUTCOME_SIMULATOR=false
```

Expected immediate gains:

- Fewer startup imports.
- Watchlist 1s loop removed.
- Paper trading 30s loop removed.
- Legacy signal outcome loop removed.

### Phase 2B — Frontend Lean Navigation

Hide or remove nav entries for disabled systems:

- Dashboard, or replace with lean summary dashboard.
- Intelligence.
- Active Trades.
- Analysis.
- Watchlist.
- Portfolio.
- Backtest.
- Paper Trading.
- Performance.
- Settings legacy signal pipeline section.

Keep nav:

- News Momentum
- Agentic / Rocket Runner
- SEC Intelligence
- Historical Training
- News feed diagnostics, optional
- Settings, only if converted to lean settings

### Phase 2C — Runtime Cache Consolidation

After legacy loops are off:

- Share hot ticker universe between News Momentum and Pre-News.
- Add common quote cache for yfinance/Alpaca/Polygon provider calls.
- Add common news item cache for Finviz/StockTitan where safe.
- Measure per-loop duration and provider call counts.

### Phase 2D — Archive Legacy Code

Move legacy systems to an archive area or branch after one full market week of lean-mode operation.

Archive groups:

1. dip/bounce signal pipeline
2. legacy scanner routes and old scanner classes except `FinvizScanner`
3. watchlist service/page/routes
4. paper trading service/page/routes
5. backtest and validation modules
6. old intelligence/analysis pages and routes

### Phase 2E — Delete Later

Delete only after archived backups exist and tests are updated.

## Concrete Candidate Classifications

| Component | Classification | Safe to disable now? | Notes |
|---|---|---:|---|
| News Momentum Orchestrator | KEEP | No | Core platform. |
| News Catalyst Classifier | KEEP | No | Core catalyst detection. |
| News Impact Engine | KEEP | No | Core scoring. |
| News Reaction Engine | KEEP | No | Core ranking. |
| Continuation Engine | KEEP | No | Core runner evaluation. |
| Expected Return Engine | KEEP | No | Core ML/ranking. |
| ML Ranking Layer | KEEP | No | Core learning. |
| Missed Winner Learning | KEEP | No | Essential for not missing PRFX/OLOX-style runners. |
| Pre-News Detector | KEEP | No | Core hidden catalyst detection. |
| Pre-News Shadow V2 | KEEP | No | Observe-only validation. |
| Rocket Dataset Builder | KEEP | No | Strategic ML research. |
| Rocket Label Reconstruction | KEEP | No | Strategic ML research. |
| Rocket Forward Enrichment | KEEP | No | Strategic ML research; prune old data only. |
| SEC Intelligence | KEEP | No | Strategic dilution intelligence. |
| Telegram Alert System | KEEP | No | Alert delivery. |
| Market Data Providers | KEEP | No | Required by all strategic systems. |
| Outcome Resolver | KEEP | No | ML feedback loop. |
| Learning Loop | KEEP | No | Historical improvement. |
| Dip Detector | DISABLE_BEHIND_FLAG | Yes, with signals/watchlist/backtest | Legacy. |
| Bounce Detector | DISABLE_BEHIND_FLAG | Yes, with signals/watchlist/backtest | Legacy. |
| Dip/Bounce ML models | DISABLE_BEHIND_FLAG | Yes, with model routes | Legacy. |
| Legacy scanners | DISABLE_BEHIND_FLAG / ARCHIVE | Partially | Keep `FinvizScanner`; archive old manual scanners later. |
| Legacy watchlists | DISABLE_BEHIND_FLAG | Yes | High-frequency loop; XSS risk in page. |
| Paper Trading | DISABLE_BEHIND_FLAG | Yes | Not core. |
| Old screener routes | DISABLE_BEHIND_FLAG | Yes | Manual legacy scanner APIs. |
| Unused websocket streams | DISABLE_BEHIND_FLAG | Yes | `/ws/watchlist` candidate. |
| Unused frontend pages | ARCHIVE | After backend flags | Remove nav first. |
| Duplicate market-data providers | KEEP/REVIEW | No | Providers are fallback chain; review after lean mode. |
| Unused background loops | DISABLE_BEHIND_FLAG | Yes | Watchlist/paper/legacy outcome first. |
| Unused JSON state stores | ARCHIVE | After backup | Data audit required per file. |
| Legacy training pipelines | ARCHIVE | After ML audit | Do not remove News Momentum/Rocket training. |

## Validation Checklist Before Any Production Refactor

- Start backend with lean flags enabled.
- Confirm `/health` works.
- Confirm `/api/v1/news-momentum/candidates` works.
- Confirm `/api/v1/news-momentum/scan-now` works.
- Confirm `/api/v1/agentic/pre-news/anomalies` works.
- Confirm `/api/v1/sec-intelligence/stats` works.
- Confirm Telegram test alert still sends.
- Confirm News Momentum background heartbeat appears.
- Confirm Pre-News scanner runs.
- Confirm SEC EDGAR firehose runs.
- Confirm no watchlist broadcaster logs appear in lean mode.
- Confirm no paper trading price updater logs appear in lean mode.
- Confirm frontend loads lean nav and no disabled API calls fire on page load.

## Final Recommendation

Approve a staged lean refactor, not a direct deletion.

Recommended first implementation after approval:

1. Add config flags.
2. Conditionally include legacy routers in `main.py`.
3. Conditionally start legacy loops in `lifespan()`.
4. Hide legacy frontend nav items based on a lean-mode constant/env.
5. Run one market week with lean mode enabled.
6. Archive disabled systems.
7. Delete later after backups and test cleanup.

This gives the largest performance win with the lowest risk while preserving the strategic News Momentum / Rocket Runner / SEC / Telegram / ML platform.
