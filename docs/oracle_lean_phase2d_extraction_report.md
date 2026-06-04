# Oracle Lean Refactor Phase 2D Extraction Report

Generated: 2026-06-03

## Scope

Implemented strategic dependency extraction without deleting or archiving files.

Guardrails honored:

- News Momentum production scoring and alert behavior were not changed.
- Pre-News production scoring and alert behavior were not changed.
- Rocket Model Shadow behavior was not changed.
- SEC Intelligence behavior was not changed.
- Telegram alert sending was not changed.
- Legacy files remain in place.

## Files Changed In This Phase

### New strategic/shared modules

- `src/core/agentic/finviz_universe.py`
- `src/models/market_data.py`
- `frontend/src/api_shared.js`
- `frontend/src/api_strategic.js`
- `frontend/src/api_legacy.js`
- `tests/unit/test_strategic_dependency_extraction.py`
- `docs/oracle_lean_phase2d_extraction_report.md`

### Updated strategic callers

- `src/main.py`
- `src/core/agentic/pre_news_detector.py`
- `src/core/agentic/pre_news_learning.py`
- `src/core/agentic/news_momentum_eod_review.py`

### Updated schema/import boundaries

- `src/models/schemas.py`
- `src/services/market_data.py`
- `src/services/alpaca_provider.py`
- `src/services/alphavantage_provider.py`
- `src/services/polygon_provider.py`
- `src/core/agentic/abcd_detector.py`
- `src/core/agentic/entry_timing.py`
- `src/core/agentic/failure_velocity.py`
- `src/core/agentic/momentum_classifier.py`
- `src/core/agentic/orchestrator.py`
- `src/core/agentic/trap_detector.py`

### Updated frontend imports

- `frontend/src/api.js`
- `frontend/src/pages/Agentic.jsx`
- `frontend/src/pages/HistoricalTraining.jsx`
- `frontend/src/pages/News.jsx`
- `frontend/src/pages/NewsMomentum.jsx`
- `frontend/src/pages/SECIntelligence.jsx`

### Updated Telegram command isolation

- `src/services/telegram_command_handler.py`
- `tests/unit/test_oracle_lean_mode.py`

## Strategic Imports Now Isolated

### Finviz

Strategic systems no longer import `src.core.finviz_scanner`:

- `src/core/agentic/pre_news_detector.py` now uses:
  - `fetch_finviz_top_gainer_tickers(...)`
  - `fetch_finviz_under2_high_volume_tickers(...)`
- `src/main.py` News Momentum ticker-specific quote-page discovery now uses the same strategic helpers.
- `src/core/agentic/news_momentum_eod_review.py` now uses:
  - `fetch_finviz_top_gainers_snapshot(...)`
- `src/core/agentic/pre_news_learning.py` now uses:
  - `fetch_finviz_top_gainers_snapshot(...)`

`src/core/finviz_scanner.py` remains available for legacy scanner routes and legacy signal generation.

### Frontend API

The API helper surface is split:

- `frontend/src/api_shared.js`: shared fetch client and health helper.
- `frontend/src/api_strategic.js`: News, Agentic, Pre-News, Historical/Rocket, News Momentum, and SEC helpers.
- `frontend/src/api_legacy.js`: signals, old analysis, scanner discovery, watchlist UI, backtest, old model controls, old intelligence/trade tracking.
- `frontend/src/api.js`: backward-compatible barrel re-export.

Strategic pages now import from `../api_strategic`:

- `Agentic.jsx`
- `HistoricalTraining.jsx`
- `News.jsx`
- `NewsMomentum.jsx`
- `SECIntelligence.jsx`

Legacy pages can continue importing from `../api` until Phase 3.

### Telegram Commands

Telegram alert sending is still separate and untouched.

`src/services/telegram_command_handler.py` now avoids top-level legacy imports for:

- volume profile
- regime detector
- stage detector
- order flow
- watchlist repository

Those dependencies are loaded only inside enabled command handlers. In lean mode:

- `/analysis` is disabled.
- `/orderflow` is disabled.
- `/watch` is disabled unless watchlist is explicitly enabled.
- `/help` has a lean-aware branch.

### Shared Strategic Schema Primitive

`OHLCVBar` now lives in:

- `src/models/market_data.py`

`src/models/schemas.py` re-exports it so existing legacy imports keep working. Strategic market-data providers and agentic engines that only need OHLCV bars now import from `src.models.market_data`.

## Remaining Legacy Dependencies

| Dependency | Why it remains | Risk |
|---|---|---|
| Pre-News watchlist integration | `pre_news_detector.py` still reads `WatchlistRepository` for manually tracked tickers. | Medium |
| `frontend/src/pages/News.jsx` live quote helper | Strategic News page still calls the old `/analysis/live-quote/{ticker}` endpoint through `api_strategic.js`. | Medium |
| Legacy DB tables in `src/models/database.py` | `Base.metadata.create_all(...)` still creates mixed strategic/legacy tables. | High |
| Legacy schemas in `src/models/schemas.py` | Many old dip/bounce/signal/backtest schemas remain for legacy modules. | Medium |
| Legacy route/service modules | Still present by design; this phase did not archive/delete. | Low |

## Archive Readiness Score

| Area | Before Phase 2D | After Phase 2D | Notes |
|---|---:|---:|---|
| Finviz strategic extraction | 45/100 | 85/100 | Strategic callers no longer import legacy scanner. |
| DB/schema separation | 30/100 | 55/100 | `OHLCVBar` extracted; watchlist/manual-universe and legacy DB tables remain mixed. |
| Frontend API split | 60/100 | 80/100 | Strategic helper file exists and strategic pages use it; live quote endpoint remains mixed. |
| Telegram command isolation | 55/100 | 85/100 | Legacy command imports are lazy and lean-gated; alert sending untouched. |
| Overall archive readiness | 48/100 | 76/100 | Phase 3 is safer, but not fully safe for a wholesale archive. |

## Verification

Fresh verification run after implementation:

- `python -m py_compile src\main.py src\core\agentic\finviz_universe.py src\services\telegram_command_handler.py src\models\schemas.py src\models\market_data.py` passed.
- Focused tests passed: `6 passed`.
- Focused lean/News Momentum suite passed: `18 passed`.
- Full backend suite passed: `306 passed, 1 xfailed`.
- Frontend production build passed: `vite build`, `2387 modules transformed`.

## Is Phase 3 Archive Now Safe?

PARTIAL.

Safe to proceed with targeted Phase 3 archive planning for:

- legacy scanner routes/services after confirming no route imports remain in lean mode
- old frontend API consumers/pages that are already lean-disabled
- old Telegram interactive analysis command dependencies

Not safe for wholesale archive yet because:

- Pre-News still depends on the watchlist repository for manual ticker universe expansion.
- The strategic News frontend still uses the old analysis live-quote endpoint.
- Database models and repositories are still mixed around shared `Base`, watchlist, and legacy signal tables.

Recommended next step before archive:

1. Decide whether manual watchlist tickers remain strategic. If yes, extract a minimal strategic tracked-ticker repository.
2. Replace `/analysis/live-quote/{ticker}` with a strategic market-data quote endpoint for `News.jsx`.
3. Split legacy DB tables/repositories away from shared `Base` and strategic DB access.
4. Re-run lean-mode import tests, full backend tests, and frontend build.
