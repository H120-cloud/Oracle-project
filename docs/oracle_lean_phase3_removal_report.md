# Oracle Lean Refactor Phase 3 Removal Report

Generated: 2026-06-03

## Scope And Guardrails

This is the Phase 1 archive/removal plan for reducing Oracle to the News Momentum / Rocket Runner platform. No production alert logic, Telegram logic, News Momentum scoring, Pre-News scoring, SEC scoring, or Rocket CatBoost shadow scoring should be changed during removal.

Nothing in this report should be interpreted as approval to delete files immediately. The correct sequence is:

1. Prove the dependency map.
2. Disable or archive legacy systems behind lean mode.
3. Run backend tests and frontend build.
4. Delete only after News Momentum, Telegram, Pre-News, Rocket Runner, SEC, and outcome/learning loops are verified.

## Keep Surface

These systems are strategic and must stay active:

- News Momentum runtime, API, classifiers, scoring engines, outcome resolver, EOD review, historical learning, and ML retrain loops.
- Pre-News Detector, validation, evaluator, baseline, learning, and Telegram alert path.
- Rocket dataset builder, label reconstruction, forward enrichment, CatBoost baseline, and Rocket shadow prediction logging.
- SEC / dilution intelligence, SEC EDGAR fetch/firehose, scoring, and API.
- Telegram service and Telegram command handler.
- Market data providers used by news, pre-news, SEC, and rocket systems.
- News ingestion from Finviz news, StockTitan, StockTwits discovery, Alpaca news stream, and SEC EDGAR.
- Frontend pages for `News`, `Agentic`, `NewsMomentum`, `SECIntelligence`, and `HistoricalTraining`.

## Current Lean-Mode State

Lean mode already exists in `src/config.py` and is covered by `tests/unit/test_oracle_lean_mode.py`.

When `ORACLE_LEAN_MODE=true`, route registration in `src/main.py` skips:

- scanner routes
- legacy signal routes
- watchlist routes
- legacy dip/bounce model routes
- old analysis routes
- backtest routes
- old intelligence routes
- HTF routes
- paper trading routes

Strategic routes remain registered:

- `/api/v1/news`
- `/api/v1/agentic`
- `/api/v1/agentic/pre-news`
- `/api/v1/agentic/training/historical`
- `/api/v1/news-momentum`
- `/api/v1/sec-intelligence`

Important gap: `src/main.py` still imports the legacy route modules at startup:

```python
from src.api.routes import health, scanner, signals, watchlist, models, analysis, backtest, intelligence, news, htf_scan, paper_trading, agentic, pre_news, historical_training, news_momentum, sec_intelligence
```

So lean mode hides legacy routes but does not fully remove startup import coupling yet. Phase 2 should split imports so disabled legacy modules are not imported at all in lean mode.

## Runtime Loops

### Keep

| Loop | File | Reason |
|---|---|---|
| `_pre_news_scan_loop` | `src/main.py` | Core Pre-News detector and Telegram alerts. |
| `_news_momentum_scan_loop` | `src/main.py` | Core News Momentum scan loop. |
| `_sec_edgar_firehose_loop` | `src/main.py` | SEC 8-K catalyst discovery. |
| Alpaca news stream | `src/main.py`, `src/services/alpaca_news_stream.py` | Real-time news ingestion. |
| Telegram command polling | `src/main.py`, `src/services/telegram_command_handler.py` | Telegram interaction layer. |
| News Momentum EOD review | `src/main.py` | Missed-winner learning. |
| News Momentum outcome resolver | `src/main.py` | Alert outcome learning. |
| News Momentum ML retrain | `src/main.py` | Existing learning loop. |

### Disable Or Archive

| Loop | File | Action | Reason |
|---|---|---|---|
| `_watchlist_broadcast_loop` | `src/main.py` | Disable in lean mode, archive later | Legacy watchlist websocket/price update loop. |
| `_paper_trading_price_loop` | `src/main.py` | Disable in lean mode, archive later | Paper trading is outside lean News/Rocket objective. |
| `_outcome_simulator_loop` | `src/main.py` | Disable in lean mode, archive later | Resolves old signal outcomes, not News Momentum outcomes. |
| `_agentic_outcome_loop` | `src/main.py` | Keep disabled, archive after verification | Old agentic candidate loop overlaps newer outcome systems. |

## Archive Candidates And Import Dependents

The dependency map below was built from Python AST imports, frontend import scans, and targeted text references. A dependent listed here means the file cannot be moved until that importer is either removed, lean-gated, or refactored.

### Dip / Bounce Detector

| File | Current dependents |
|---|---|
| `src/core/dip_detector.py` | `src/core/backtest_validator.py`, `src/core/backtester.py`, `src/services/signal_service.py`, `src/services/watchlist_service.py` |
| `src/core/bounce_detector.py` | `src/core/backtest_validator.py`, `src/core/backtester.py`, `src/services/signal_service.py`, `src/services/watchlist_service.py` |
| `src/ml/dip_model.py` | `src/api/routes/models.py`, `src/ml/trainer.py`, `src/services/signal_service.py` |
| `src/ml/bounce_model.py` | `src/api/routes/models.py`, `src/ml/trainer.py`, `src/services/signal_service.py` |

Archive after `signals`, `models`, `watchlist`, and legacy backtest modules are removed or lean-gated from imports.

### Legacy Signals

| File | Current dependents |
|---|---|
| `src/api/routes/signals.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Dashboard.jsx`, `frontend/src/pages/Performance.jsx`, `tests/unit/test_oracle_lean_mode.py` |
| `src/services/signal_service.py` | `src/api/dependencies.py`, `src/api/routes/signals.py` |
| `src/core/decision_engine.py` | `src/services/signal_service.py`, `src/core/backtest_validator.py`, `src/core/full_featured_backtester.py`, `src/core/live_trading_simulator.py`, `src/core/regime_aware_backtester.py` |
| `src/core/entry_engine.py` | `src/core/intelligence_engine.py`, old agentic orchestrator |
| `src/core/target_engine.py` | `src/core/intelligence_engine.py` |
| `src/core/risk_scorer.py` | `src/core/decision_engine.py` |
| `src/core/position_sizer.py` | `src/core/decision_engine.py`, `src/core/liquidity_aware_sizer.py` |
| `src/core/trailing_stop.py` | `src/api/routes/paper_trading.py`, `src/services/broker_service.py`, legacy backtest modules |
| `src/core/signal_expiry.py` | `src/api/routes/signals.py`, `src/services/signal_service.py`, schema/repository legacy signal fields |
| `src/core/signal_ranker.py` | `src/services/signal_service.py` |
| `src/core/classifier.py` | legacy dip/bounce classifier; not used by News Momentum after current audit |

Archive as one dependency cluster after frontend legacy pages and old routes are removed from startup imports.

### Legacy Scanner

| File | Current dependents |
|---|---|
| `src/api/routes/scanner.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Dashboard.jsx`, `frontend/src/pages/Watchlist.jsx`, `tests/unit/test_oracle_lean_mode.py` |
| `src/core/discovery_engine.py` | `src/api/routes/scanner.py`, `src/services/signal_service.py` |
| `src/core/professional_scanner.py` | `src/api/routes/scanner.py`, `src/api/routes/htf_scan.py`, `src/services/signal_service.py` |
| `src/core/scanner.py` | legacy scanner route/service references |

Do not archive `src/core/finviz_scanner.py` yet. Despite its legacy-sounding name, it is still used by:

- `src/core/agentic/pre_news_detector.py`
- `src/core/agentic/pre_news_learning.py`
- `src/core/agentic/news_momentum_eod_review.py`
- `src/main.py`
- `tests/unit/test_finviz_scanner_parser.py`

Recommended extraction: move only the Finviz universe discovery code needed by Pre-News into a strategic module such as `src/core/agentic/pre_news_universe.py`, then archive the legacy scanner route/UI cluster.

### Watchlist

| File | Current dependents |
|---|---|
| `src/api/routes/watchlist.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Watchlist.jsx`, `src/api/routes/sec_intelligence.py`, `src/services/telegram_command_handler.py` |
| `src/services/watchlist_service.py` | `src/api/routes/watchlist.py`, `src/main.py` |
| `frontend/src/pages/Watchlist.jsx` | `frontend/src/App.jsx` |

Watchlist should be disabled fully behind lean mode before archive. SEC has a `clean-watchlist` endpoint, and Telegram command handling may still reference watchlist-style flows; those references need explicit replacement or removal before file moves.

### Paper Trading

| File | Current dependents |
|---|---|
| `src/api/routes/paper_trading.py` | `src/main.py`, frontend paper trading page, tests |
| `src/services/broker_service.py` | `src/api/routes/paper_trading.py`, paper trading loop |
| `src/core/live_trading_simulator.py` | old backtest / decision engine cluster |
| `frontend/src/pages/PaperTrading.jsx` | `frontend/src/App.jsx` |

Phase 2 action: keep route disabled in lean mode and move the background price loop behind `paper_trading_system_enabled`. Archive after backend tests pass without paper trading imports.

### Backtest

| File | Current dependents |
|---|---|
| `src/api/routes/backtest.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Backtest.jsx`, paper trading route |
| `src/core/backtester.py` | `src/api/routes/backtest.py`, advanced backtest modules |
| `src/core/backtest_validator.py` | `src/api/routes/paper_trading.py` |
| `src/core/full_featured_backtester.py` | `src/core/htf_impact_backtester.py` |
| `src/core/htf_impact_backtester.py` | backtest-only |
| `src/core/regime_aware_backtester.py` | backtest-only |
| `src/interfaces/backtester.py` | backtest modules |
| `frontend/src/pages/Backtest.jsx` | `frontend/src/App.jsx` |

News Momentum has its own backfill/backtest files under `src/core/agentic/news_momentum_*`; those are strategic learning tools and should stay.

### Old Analysis And Intelligence

| File | Current dependents |
|---|---|
| `src/api/routes/analysis.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Analysis.jsx`, legacy pages |
| `src/api/routes/intelligence.py` | `src/main.py`, `frontend/src/api.js`, `frontend/src/pages/Intelligence.jsx`, `frontend/src/pages/ActiveTrades.jsx` |
| `src/core/intelligence_engine.py` | old intelligence route/pages |
| `src/core/adaptation_engine.py` | `src/core/intelligence_engine.py` |
| `src/core/market_context.py` | old intelligence engine/probability engine |
| `src/core/liquidity_engine.py` | old intelligence engine |
| `src/core/multi_timeframe.py` | old intelligence engine |
| `src/core/news_intelligence.py` | old intelligence engine |
| `src/core/playbook_engine.py` | old intelligence engine |
| `src/core/probability_engine.py` | old intelligence engine |
| `src/core/bearish_detector.py` | analysis/watchlist/signal service |
| `src/core/ict_detector.py` | decision/backtest/signal cluster |
| `src/core/order_flow.py` | backtest/signal/telegram legacy analysis references |
| `src/core/regime_detector.py` | analysis/backtest/signal cluster |
| `src/core/stage_detector.py` | analysis/signal/telegram command references |
| `src/core/stock_segmenter.py` | analysis/signal cluster |
| `src/core/volume_profile.py` | analysis/signal/watchlist/telegram command references |
| `src/core/no_trade_filter.py` | decision/backtest cluster |
| `src/core/market_trend_regime_detector.py` | decision/backtest/live simulator cluster |
| `src/core/confidence_calibrator.py` | decision/paper trading cluster |
| `src/core/trading212_scraper.py` | legacy scanner discovery |
| `src/interfaces/order_flow.py` | old analysis/telegram references |
| `src/interfaces/regime_detector.py` | old analysis/backtest references |
| `src/interfaces/volume_profile.py` | old analysis/telegram references |

Several strategic files mention "analysis" in comments or generic text; those are not hard imports. The hard archive blockers are the old routes, old frontend pages, and legacy signal/backtest services.

### HTF Routes And Services

| File | Current dependents |
|---|---|
| `src/api/routes/htf_scan.py` | `src/main.py` |
| `src/core/higher_timeframe_bias.py` | `src/core/htf_aware_scanner.py`, `src/services/htf_alert_service.py`, decision/backtest/watchlist cluster |
| `src/core/htf_aware_scanner.py` | `src/api/routes/htf_scan.py`, `src/services/signal_service.py` |
| `src/services/htf_alert_service.py` | `src/api/routes/watchlist.py`, `src/services/watchlist_service.py` |

Archive after watchlist and legacy scanner/signals are removed.

### Legacy ML Dip/Bounce Stack

| File | Current dependents |
|---|---|
| `src/ml/dip_model.py` | `src/api/routes/models.py`, `src/ml/trainer.py`, `src/services/signal_service.py` |
| `src/ml/bounce_model.py` | `src/api/routes/models.py`, `src/ml/trainer.py`, `src/services/signal_service.py` |
| `src/ml/feature_engineer.py` | `src/ml/dip_model.py`, `src/ml/bounce_model.py`, `src/ml/trainer.py`, old `ml_advisory` |
| `src/ml/model_store.py` | `src/api/routes/models.py`, old ML model files, `src/services/signal_service.py` |
| `src/ml/trainer.py` | `src/api/routes/models.py` |
| `src/api/routes/models.py` | `src/main.py` behind `dip_bounce_enabled` |

Do not archive `src/core/agentic/news_momentum_ml_engine.py`, `news_momentum_big_winner_model.py`, `rocket_catboost_baseline.py`, or `rocket_model_shadow.py`. Those are strategic.

### Frontend Legacy Pages

| File | Current dependents |
|---|---|
| `frontend/src/pages/Dashboard.jsx` | `frontend/src/App.jsx` |
| `frontend/src/pages/Analysis.jsx` | `frontend/src/App.jsx`, old API helpers |
| `frontend/src/pages/Backtest.jsx` | `frontend/src/App.jsx`, old API helpers |
| `frontend/src/pages/Performance.jsx` | `frontend/src/App.jsx`, old API helpers |
| `frontend/src/pages/Portfolio.jsx` | `frontend/src/App.jsx` |
| `frontend/src/pages/Watchlist.jsx` | `frontend/src/App.jsx`, old API helpers |
| `frontend/src/pages/Intelligence.jsx` | `frontend/src/App.jsx`, old API helpers |
| `frontend/src/pages/ActiveTrades.jsx` | `frontend/src/App.jsx` |
| `frontend/src/pages/PaperTrading.jsx` | `frontend/src/App.jsx` |
| `frontend/src/pages/Settings.jsx` | `frontend/src/App.jsx` |

Current frontend already hides many legacy routes with `VITE_ORACLE_LEAN_MODE=true`, but legacy page imports remain top-level in `frontend/src/App.jsx`. Phase 2 should lazy-split or remove those imports so a lean build does not bundle legacy pages.

Keep frontend pages:

- `frontend/src/pages/News.jsx`
- `frontend/src/pages/Agentic.jsx`
- `frontend/src/pages/NewsMomentum.jsx`
- `frontend/src/pages/SECIntelligence.jsx`
- `frontend/src/pages/HistoricalTraining.jsx`

## Archive Order

### Step 1: Startup Import Isolation

Modify `src/main.py` so legacy route modules are imported only when their lean-mode flags are enabled. This must happen before moving route files.

Target legacy imports:

- `scanner`
- `signals`
- `watchlist`
- `models`
- `analysis`
- `backtest`
- `intelligence`
- `htf_scan`
- `paper_trading`

Strategic imports should remain static:

- `health`
- `news`
- `agentic`
- `pre_news`
- `historical_training`
- `news_momentum`
- `sec_intelligence`

### Step 2: Runtime Loop Guards

Ensure the following startup tasks are guarded by lean-mode settings:

- `OutcomeSimulator` task only if `legacy_outcome_simulator_enabled`.
- watchlist broadcaster only if `watchlist_enabled`.
- paper trading price updater only if `paper_trading_system_enabled`.

Do not alter:

- Telegram command polling.
- News Momentum scan loop.
- Pre-News scan loop.
- SEC EDGAR firehose.
- News Momentum outcome resolver.
- News Momentum EOD review.
- Rocket shadow scoring.

### Step 3: Frontend Lean Import Isolation

Update `frontend/src/App.jsx` so legacy pages are not top-level imports in lean mode. Either remove the pages after route removal or lazy-load them only when their flags are enabled.

Also split `frontend/src/api.js` into strategic and legacy helpers, or keep the file but stop importing legacy helpers from strategic pages.

### Step 4: Archive Cluster Moves

Move the legacy clusters to an archive folder such as:

```text
archive/oracle_legacy_phase3/
```

Suggested structure:

```text
archive/oracle_legacy_phase3/backend/routes/
archive/oracle_legacy_phase3/backend/core/
archive/oracle_legacy_phase3/backend/services/
archive/oracle_legacy_phase3/backend/ml/
archive/oracle_legacy_phase3/frontend/pages/
```

Use file moves only after Step 1 and Step 2 pass tests.

### Step 5: Delete Only After Soak

After archive moves pass tests/build and the app runs in lean mode, keep archived code for a short soak period. Delete only after verifying no production process references it.

## Files Not Safe To Archive Yet

These are legacy-adjacent but still used by the strategic system:

| File | Why it stays for now |
|---|---|
| `src/core/finviz_scanner.py` | Pre-News universe discovery and News Momentum EOD review still use it. |
| `src/core/finviz_news.py` | News Momentum and Pre-News news ingestion. |
| `src/core/stocktitan_news.py` | News Momentum and Pre-News source. |
| `src/core/stocktwits_scraper.py` | Pre-News/social discovery. |
| `src/services/market_data.py` | Strategic provider abstraction. |
| `src/services/alpaca_provider.py` | Market data/news provider path. |
| `src/services/polygon_provider.py` | Rocket enrichment, Pre-News high-fidelity enrichment, News Momentum quote fallback. |
| `src/services/yahoo_finance_provider.py` | fallback market data provider. |
| `src/services/alphavantage_provider.py` | configured fallback provider. |
| `src/models/database.py` | Shared DB tables still used by API and legacy; requires schema audit before pruning. |
| `src/models/schemas.py` | Shared schema module; route/page pruning should happen before schema pruning. |
| `src/db/repositories.py` | Shared database access; watchlist/signal methods can be pruned later. |

## Verification Plan

### Backend

Run after Phase 2 startup isolation:

```powershell
python -m pytest tests\unit\test_oracle_lean_mode.py -q
python -m pytest tests\unit\test_news_momentum_alert_flow.py tests\unit\test_news_momentum_timezones.py tests\unit\test_pre_news_validation.py tests\unit\test_rocket_model_shadow.py tests\unit\test_rocket_catboost_baseline.py tests\unit\test_rocket_forward_enrichment.py tests\unit\test_rocket_label_reconstructor.py tests\unit\test_rocket_ticker_integrity.py tests\unit\test_polygon_provider_daily_bars.py tests\unit\test_ticker_normalization.py -q
python -m pytest tests\regression -q
```

Then run the full backend suite:

```powershell
python -m pytest -q
```

### Frontend

Run after frontend route/import isolation:

```powershell
cd frontend
npm run build
```

### Runtime Smoke

Start the app with lean mode:

```powershell
$env:ORACLE_LEAN_MODE="true"
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Verify:

- `/api/v1/news-momentum/candidates` responds.
- `/api/v1/sec-intelligence/stats` responds.
- `/api/v1/agentic/pre-news/status` or equivalent Pre-News route responds.
- Telegram command polling starts.
- News Momentum scan loop starts.
- Pre-News scan loop starts.
- SEC EDGAR firehose starts if enabled.
- `data/agentic/rocket_model_shadow_predictions.jsonl` receives passive predictions when live candidates are processed.

## Phase 2 Completion Status

Completed on 2026-06-03.

### Legacy Imports Now Isolated

`src/main.py` no longer imports legacy route modules at top level. These modules are imported only inside the same feature-flag blocks that register their routes:

- `src.api.routes.scanner`
- `src.api.routes.signals`
- `src.api.routes.watchlist`
- `src.api.routes.models`
- `src.api.routes.analysis`
- `src.api.routes.backtest`
- `src.api.routes.intelligence`
- `src.api.routes.htf_scan`
- `src.api.routes.paper_trading`

Legacy background-loop imports were moved inside the loops that use them:

- `src.core.outcome_simulator.OutcomeSimulator` is imported only inside `_outcome_simulator_loop`.
- Old agentic outcome imports are imported only inside `_agentic_outcome_loop`, which remains disabled.
- Paper trading broker access was already imported inside `_paper_trading_price_loop`; that loop remains behind `paper_trading_system_enabled`.
- Watchlist broadcast remains behind `watchlist_enabled`.

Strategic route imports remain top-level and always enabled:

- `health`
- `news`
- `agentic`
- `pre_news`
- `historical_training`
- `news_momentum`
- `sec_intelligence`

### Frontend Import Isolation

`frontend/src/App.jsx` now statically imports only strategic pages:

- `News`
- `Agentic`
- `HistoricalTraining`
- `NewsMomentum`
- `SECIntelligence`

Legacy pages are now `React.lazy` imports and are only created when their lean-mode visibility flag allows the route:

- `Dashboard`
- `Analysis`
- `Backtest`
- `Performance`
- `Portfolio`
- `Settings`
- `Watchlist`
- `Intelligence`
- `ActiveTrades`
- `PaperTrading`

In lean mode, `/` redirects to `/news-momentum`; settings is treated as legacy and hidden from lean navigation.

### Tests Added

Added backend/frontend guard coverage in `tests/unit/test_oracle_lean_mode.py`:

- `test_lean_mode_does_not_import_legacy_route_or_loop_modules`
- `test_frontend_lean_mode_does_not_static_import_legacy_pages`

The first test removes legacy modules from `sys.modules`, imports `src.main` with lean mode enabled, and proves disabled legacy route/loop modules are not imported at startup.

The second test prevents static top-level imports of known legacy frontend page modules from returning to `frontend/src/App.jsx`.

### Verification Results

Backend full suite:

```powershell
python -m pytest -q
```

Result:

```text
300 passed, 1 xfailed, 910 warnings in 63.26s
```

Frontend lean build:

```powershell
$env:VITE_ORACLE_LEAN_MODE='true'
npm.cmd run build
```

Result:

```text
vite v5.4.21 building for production...
2384 modules transformed.
dist/index.html                 0.52 kB
dist/assets/index-BKwR3r2s.css 37.68 kB
dist/assets/index-uyHC8Pv-.js 331.98 kB
built in 42.75s
```

Note: `npm run build` through PowerShell was blocked by local execution policy for `npm.ps1`; `npm.cmd run build` succeeded. A sandboxed attempt hit `EPERM` resolving `C:\Users\Husna`, and the elevated rerun succeeded.

## Go / No-Go

Current state: **GO for Phase 3 archive/move planning in lean mode, NO-GO for deletion**.

Reason:

- Lean mode route gating no longer imports disabled legacy route modules at startup.
- Frontend lean mode no longer statically imports legacy page modules at startup.
- Full backend tests pass.
- Frontend lean production build passes.
- Some legacy-adjacent modules are still strategic dependencies and must not be moved yet.
- Deletion still requires a soak period and a runtime smoke against a live lean-mode server.

Remaining blockers to archiving:

- `src/core/finviz_scanner.py` is still used by Pre-News and News Momentum EOD review; extract strategic universe discovery before moving scanner code.
- `src/models/database.py`, `src/models/schemas.py`, and `src/db/repositories.py` still contain shared legacy and strategic structures; schema pruning must wait.
- `frontend/src/api.js` still contains legacy helper exports, although strategic pages do not need to import them for lean startup.
- `src/services/telegram_command_handler.py` still references some legacy analysis/watchlist-style commands; command-level cleanup should be audited separately so Telegram itself stays intact.
- Archive moves should happen cluster-by-cluster with tests after each cluster.

Next safe action: Phase 3 archive/move of fully isolated legacy route/page clusters into `archive/oracle_legacy_phase3/`, starting with frontend pages and disabled API route modules. Do not delete files yet.
