# Oracle Lean Refactor Phase 2B Blocker Audit

Generated: 2026-06-03

## Scope And Guardrails

This audit identifies remaining blockers before legacy systems can be archived or moved. It is documentation-only: no files were deleted, moved, or runtime-modified.

Strategic systems remain:

- News Momentum
- Pre-News Detector
- Rocket Dataset / CatBoost shadow model
- SEC / Dilution Intelligence
- Telegram alert sending
- Market data providers required by news, pre-news, SEC, and rocket systems
- Outcome resolver and learning loops

## Executive Summary

| Blocker | Strategic dependency? | Risk level | Recommendation |
|---|---:|---|---|
| `src/core/finviz_scanner.py` | Yes | High | Do not archive yet. Split Finviz ticker discovery and Finviz mover snapshots into strategic modules first. |
| Shared DB/schema modules | Partial/Yes | High | Do not archive wholesale. Separate strategic primitives from legacy signal/watchlist/backtest models. |
| `frontend/src/api.js` | Partial/Yes | Medium | Split strategic API helpers from legacy helpers after route/page isolation. |
| Telegram command references | Partial/Yes | High | Keep Telegram polling and alert sending. Hide or lean-disable legacy analysis/watchlist commands later. |

## Blocker 1: `finviz_scanner.py`

### Strategic Dependents

| Dependent file | Strategic dependency | Usage | Recommended action | Risk |
|---|---:|---|---|---|
| `src/core/agentic/pre_news_detector.py` | Yes | Builds Pre-News universe from Finviz top gainers and under-$2 high-volume screener using `_scrape_finviz_tickers(..., validate=False)`. | Extract lightweight ticker-only screener functions into a strategic universe module. | High |
| `src/core/agentic/pre_news_learning.py` | Yes | EOD missed-opportunity review uses `scan_gainers()` to compare large movers against detected anomalies. | Move EOD mover discovery to a strategic Finviz mover provider. | High |
| `src/core/agentic/news_momentum_eod_review.py` | Yes | EOD review uses `scan_gainers()` to identify missed News Momentum movers. | Keep until a replacement mover snapshot provider exists. | High |
| `src/main.py` | Yes | News Momentum loop fetches hot tickers for ticker-specific Finviz quote-page news. | Replace private `_scrape_finviz_tickers` calls with extracted strategic helper. | Medium |

### Legacy Dependents

| Dependent file | Strategic dependency | Usage | Recommended action | Risk |
|---|---:|---|---|---|
| `src/api/routes/scanner.py` | No | Legacy scanner/discovery route. | Archive after route remains lean-disabled and frontend references are removed. | Medium |
| `src/services/signal_service.py` | No | Legacy signal generation scans Finviz gainers/under-$2 lists. | Archive with legacy signal stack. | Medium |
| `tests/unit/test_finviz_scanner_parser.py` | Yes, test coverage | Parser coverage for Finviz table extraction. | Keep or move tests to new strategic Finviz universe module. | Low |

### Audit Notes

- `finviz_scanner.py` is not safe to archive just because scanner routes are legacy.
- Strategic code currently reaches into private scanner internals (`_scrape_finviz_tickers`) for ticker-only discovery.
- `src/main.py` references `scanner.FINVIZ_UNDER2_URL`, while the constant is module-level in `src/core/finviz_scanner.py`. This is a brittle dependency and should be cleaned during extraction, not as part of this read-only audit.

### Decision

Split/extract, then archive the legacy remainder.

Safe next step:

1. Create a strategic Finviz universe/mover module with public functions:
   - `fetch_finviz_top_gainer_tickers(validate=False)`
   - `fetch_finviz_under2_high_volume_tickers(validate=False)`
   - `fetch_finviz_top_gainers_snapshot()`
2. Update only strategic callers to the public module.
3. Leave `src/core/finviz_scanner.py` in place until legacy route/service imports are removed.

## Blocker 2: Shared DB And Schema Modules

### Shared Modules

| Module | Strategic dependency | Current strategic usage | Archive safety | Recommended action | Risk |
|---|---:|---|---|---|---|
| `src/models/database.py` | Partial | `src/main.py` imports `Base` and runs `Base.metadata.create_all(...)`; `Watchlist` is indirectly used by Pre-News universe via repository. | Unsafe wholesale | Split strategic DB base/session from legacy table definitions, or keep until DB refactor. | High |
| `src/db/session.py` | Yes | Main startup and Telegram/Pre-News DB sessions. | Unsafe | Keep. | High |
| `src/db/repositories.py` | Partial | `WatchlistRepository` is used by `src/core/agentic/pre_news_detector.py` and `src/services/telegram_command_handler.py`. | Unsafe wholesale | Split `WatchlistRepository` into minimal strategic universe repository vs legacy watchlist UI repository. | High |
| `src/models/schemas.py` | Partial | `OHLCVBar` is used by strategic market providers and agentic engines; `ScannedStock` is used by Finviz strategic EOD paths. | Unsafe wholesale | Extract strategic shared schemas (`OHLCVBar`, `ScannedStock` or replacement mover snapshot) before archiving legacy schemas. | High |

### Strategic Schema Usage

| Schema/model | Strategic dependents | Keep? | Notes |
|---|---|---:|---|
| `OHLCVBar` | `src/services/market_data.py`, `src/services/polygon_provider.py`, `src/services/alphavantage_provider.py`, `src/core/agentic/entry_timing.py`, `src/core/agentic/momentum_classifier.py`, `src/core/agentic/trap_detector.py`, `src/core/agentic/orchestrator.py` | Yes | Core market-data primitive. |
| `ScannedStock` | `src/core/finviz_scanner.py`, EOD review paths through `scan_gainers()` | Temporary | Replace with strategic mover snapshot DTO before archiving scanner/schema pieces. |
| `Watchlist` / `WatchlistRepository` | `src/core/agentic/pre_news_detector.py`, Telegram `/watch`, watchlist loop/routes | Partial | The UI/service watchlist is legacy, but Pre-News uses active watchlist tickers as a strategic universe input. |

### Legacy-Only Or Archive Candidates After Split

| Cluster | Modules/classes | Archive condition |
|---|---|---|
| Legacy signals | `Signal`, `SignalOutcome`, `ScanResult`, `SignalRepository`, `SignalOutcomeRepository`, signal response schemas | Safe only after signal routes, signal service, outcome simulator, old ML trainer, and legacy frontend pages are gone. |
| Watchlist UI features | `WatchlistAlert`, `WatchlistTimeline`, `CustomAlert`, watchlist response/custom alert schemas | Safe only after Pre-News no longer depends on the same repository/table or a minimal universe table replaces it. |
| Legacy analysis/backtest/dip/bounce schemas | `DipFeatures`, `BounceFeatures`, `TradingSignal`, `BacktestConfig`, performance/backtest models | Safe after legacy analysis, model, backtest, paper trading, and signal stacks are archived. |

### Decision

Do not archive shared DB/schema modules wholesale.

Safe next step:

1. Add a dependency boundary document or module split plan:
   - `src/models/market_data_schemas.py` for `OHLCVBar`.
   - `src/core/agentic/finviz_models.py` for mover/ticker discovery DTOs.
   - minimal strategic watchlist/universe repository if manual ticker inclusion remains desired.
2. Move legacy signal/watchlist/backtest schemas only after strategic callers stop importing from `src/models/schemas.py` and `src/db/repositories.py`.

## Blocker 3: `frontend/src/api.js`

### Strategic API Helper Groups

| Helper group | Helpers | Strategic dependency | Recommended action | Risk |
|---|---|---:|---|---|
| Health/news | `getHealth`, `getFinvizNews`, `getStockTitanNews`, `getAllNews` | Yes | Keep in strategic API surface. | Low |
| Agentic / Pre-News | `agentic*`, `qualitySeparator*`, `newsImpact*`, `preNews*` | Yes | Keep, though older `agentic/ml/*` should be reviewed separately from Rocket CatBoost shadow. | Medium |
| Historical/Rocket training | `historicalTraining*` | Yes | Keep. | Low |
| News Momentum | `newsMomentum*` | Yes | Keep. | Low |
| SEC Intelligence | `sec*` | Yes | Keep. `secCleanWatchlist` is SEC terminology, not the legacy DB watchlist route. | Low |

### Legacy-Only API Helper Groups

| Helper group | Helpers | Current frontend consumers | Recommended action | Risk |
|---|---|---|---|---|
| Legacy signals | `getSignals`, `analyzeSignal`, `recordOutcome` | `Dashboard.jsx` | Move to legacy API module; remove from lean bundle after page retirement. | Medium |
| Old analysis | `getVolumeProfile`, `getRegime`, `getStage`, `getSegment`, `getCompleteAnalysis`, `getBearishAnalysis`, `getOrderFlow` | `Analysis.jsx`, `News.jsx` partially | Move to legacy API module. | Medium |
| Legacy live quote endpoint | `getLiveQuote` | `Analysis.jsx`, `Intelligence.jsx`, `News.jsx` | Blocker: `News.jsx` is strategic but calls old analysis live quote endpoint. Move live quote to a strategic market-data endpoint or remove quote enrichment from the News page. | High |
| Backtest/performance | `runBacktest`, `getPerformance`, `getAdjustments` | `Backtest.jsx`, `Performance.jsx` | Legacy API module. | Low |
| Old dip/bounce model controls | `getModelStatus`, `trainModels` | `Settings.jsx` | Legacy API module. | Low |
| Legacy scanner/discovery | `discoverTickers`, `discoverTrading212` | `Dashboard.jsx` | Legacy API module. | Medium |
| Watchlist UI | `getWatchlist`, `addToWatchlist`, `getWatchlistDetail`, `updateWatchlistItem`, `removeFromWatchlist`, `archiveWatchlistItem`, `restoreWatchlistItem`, alert/timeline/custom alert/earnings helpers, `getTickerNews` | `Watchlist.jsx`, `Dashboard.jsx`, `Analysis.jsx` | Legacy API module, except any future minimal manual-universe helper should be rebuilt under strategic endpoint. | High |
| Old intelligence/trade tracking | `analyzeIntelligence`, `analyzeBatchIntelligence`, `getMarketContext`, `getActiveTrades`, `startTradeTracking`, `updateTradeTracking`, `closeTradeTracking`, `getLearningWeights`, `computeLearningAdjustments` | `Intelligence.jsx`, `ActiveTrades.jsx` | Legacy API module. | Medium |

### Decision

Keep `api.js` for now, but split it before file archival.

Safe next step:

1. Create `frontend/src/api/strategic.js` containing only health/news/agentic/pre-news/historical/news-momentum/SEC helpers.
2. Create `frontend/src/api/legacy.js` for disabled legacy pages.
3. Resolve `News.jsx` dependency on `getLiveQuote` by moving live quote to a strategic route or dropping that enrichment in lean mode.
4. Keep the current `frontend/src/api.js` as a compatibility barrel until imports are migrated.

## Blocker 4: Telegram Command References

### Current Command Surface

| Command/path | Dependent modules | Strategic dependency | Recommended action | Risk |
|---|---|---:|---|---|
| Telegram alert sending | `src/services/telegram_service.py`, News Momentum/Pre-News callers | Yes | Keep untouched. This audit does not alter alert delivery. | High |
| Telegram polling loop | `src/services/telegram_command_handler.py`, `src/main.py` | Yes | Keep if Telegram command channel remains desired. | Medium |
| `/analysis TICKER` | `market_data`, `VolumeProfileEngine`, `RegimeDetector`, `StageDetector`, optional `OrderFlowAnalyzer` | No | Hide or disable in lean mode; this is old analysis tooling. | Medium |
| `/orderflow TICKER` | `OrderFlowAnalyzer`, market data provider | No | Hide or disable in lean mode. | Medium |
| `/watch TICKER [bullish|bearish]` | `SessionLocal`, `WatchlistRepository` | Partial | Decide whether manual ticker tracking is strategic. If yes, replace with minimal `/track` or `/universe-add` command backed by a small strategic table. If no, hide/disable. | High |
| `/help` | Same command handler | Partial | Update later to show only enabled lean-mode commands. | Low |

### Audit Notes

- There are no active Telegram commands for paper trading, backtest, HTF, dip, bounce, or legacy scanner in the current command handler.
- The command handler imports legacy analysis engines at module import time:
  - `src.core.volume_profile.VolumeProfileEngine`
  - `src.core.regime_detector.RegimeDetector`
  - `src.core.stage_detector.StageDetector`
  - optional `src.core.order_flow.OrderFlowAnalyzer`
- Because `src/main.py` imports `telegram_command_polling_loop` unconditionally, these analysis modules are still imported at startup even in lean mode.
- Telegram alert sending is separate from the command handler and must remain untouched.

### Decision

Keep Telegram alert delivery and polling infrastructure, but isolate or lean-disable legacy commands.

Safe next step:

1. Move `/analysis` and `/orderflow` imports inside handlers or behind command feature flags.
2. Add lean-mode command filtering so disabled commands return a short "command disabled" response or are hidden from `/help`.
3. Decide whether `/watch` becomes a strategic manual-universe command. If yes, build a minimal strategic repository before archiving watchlist UI/service code.

## Phase 2B Safe Next-Step Checklist

| Step | Why | Safe to do before archive? |
|---|---|---:|
| Extract Finviz strategic universe/mover helpers | Removes strategic dependency on legacy scanner internals. | Yes |
| Split strategic DB schemas from legacy schemas | Prevents DB/schema wholesale archive risk. | Yes |
| Resolve `News.jsx` -> `getLiveQuote` legacy route dependency | Keeps strategic News page functional after analysis routes are archived. | Yes |
| Split frontend API helpers into strategic and legacy modules | Makes frontend archive boundaries explicit. | Yes |
| Lean-gate Telegram interactive commands while preserving alert sending | Removes startup imports of old analysis modules without touching alert delivery. | Yes |

## Final Recommendation

Phase 3 archive/move is not safe yet for these blockers.

The safest sequence is:

1. Extract strategic Finviz discovery/mover code.
2. Split or quarantine shared DB/schema modules.
3. Split frontend API helpers and fix the strategic News page quote dependency.
4. Lean-gate Telegram command imports and help text.
5. Re-run backend tests and frontend lean build.

Only after those steps should legacy scanner, old analysis, watchlist UI/service, signal, backtest, HTF, paper trading, and legacy ML files be moved or archived.
