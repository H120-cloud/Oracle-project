# Oracle Lean Refactor Phase 2E Archive Readiness

Generated: 2026-06-03

## Scope

Phase 2E removed the last strategic dependency blockers that were preventing safe targeted archive planning. No files were deleted or archived, and production behavior was preserved.

Guardrails honored:

- News Momentum behavior unchanged.
- Pre-News behavior preserved.
- Rocket Shadow behavior unchanged.
- SEC Intelligence behavior unchanged.
- Telegram alert sending unchanged.
- Legacy files remain in place.

## Blockers Resolved

### 1. Pre-News Watchlist Dependency

Why Pre-News touched watchlist repositories:

- Pre-News uses manually tracked tickers as an additional universe source.
- It did not need watchlist alerts, timeline, notes, HTF state, custom alerts, or refresh logic.
- The old implementation imported `WatchlistRepository` from `src/db/repositories.py`, pulling a large legacy repository module into a strategic scan path.

Resolution:

- Added `src/models/strategic.py`.
  - Re-exports `Base`.
  - Exposes `ManualUniverseTicker` as a strategic alias for the existing `Watchlist` table.
- Added `src/core/agentic/manual_universe.py`.
  - Provides `get_manual_universe_tickers()`.
  - Reads only active/non-archived ticker symbols.
  - Does not import `src.db.repositories` or `WatchlistRepository`.
- Updated `src/core/agentic/pre_news_detector.py`.
  - Replaced legacy watchlist repository access with `get_manual_universe_tickers()`.
  - Preserves manual ticker inclusion behavior.

Result:

- Pre-News no longer imports the legacy watchlist repository.
- Strategic behavior remains: manually tracked tickers can still enter the Pre-News universe.

### 2. `News.jsx` Endpoint Dependency

Previous blocker:

- Strategic `frontend/src/pages/News.jsx` used `getLiveQuote()` from `api_strategic.js`.
- That helper still called the old analysis endpoint: `/api/v1/analysis/live-quote/{ticker}`.

Resolution:

- Added strategic quote endpoint:
  - `GET /api/v1/news/quote/{ticker}`
  - implemented in `src/api/routes/news.py`
  - backed by the existing market data provider
- Updated `frontend/src/api_strategic.js`.
  - `getLiveQuote()` now calls `/api/v1/news/quote/{ticker}`.
- `News.jsx` continues importing from `api_strategic.js`.

Result:

- Strategic News UI no longer depends on old analysis routes for quote display.
- Frontend behavior is preserved: ticker chips still receive quote/change data.

### 3. Mixed DB/Repository Models

Safe separation completed:

- `OHLCVBar` was already moved to `src/models/market_data.py` and re-exported from `src/models/schemas.py`.
- Phase 2E added `src/models/strategic.py` as the strategic DB model alias layer.
- Pre-News now uses the strategic alias through `manual_universe.py`, not the legacy repository.

Why this is the safe stopping point:

- The existing database schema and table names are preserved.
- No data migration is needed.
- Legacy DB models remain for legacy routes/services until archive.
- Strategic code has clean imports for the pieces it still needs.

## Files Changed In Phase 2E

- `src/models/strategic.py`
- `src/core/agentic/manual_universe.py`
- `src/core/agentic/pre_news_detector.py`
- `src/api/routes/news.py`
- `frontend/src/api_strategic.js`
- `tests/unit/test_strategic_dependency_extraction.py`
- `docs/oracle_lean_phase2e_archive_readiness.md`

## Remaining Blockers

| Blocker | Status | Deletion risk |
|---|---|---|
| `src/models/database.py` | Still contains both strategic table infrastructure and legacy tables. Do not delete wholesale. | High |
| `src/db/session.py` | Shared DB infrastructure. Must stay. | High |
| `src/models/schemas.py` | Still contains legacy schemas, but strategic `OHLCVBar` has been extracted/re-exported. | Medium |
| `src/db/repositories.py` | Legacy repository module; no longer needed by Pre-News, but still needed by legacy routes/services. | Medium |
| Legacy watchlist table | Still used as storage for manual universe tickers through strategic alias. | Medium |

## Archive Readiness Score

| Area | Previous | Current | Notes |
|---|---:|---:|---|
| Finviz strategic extraction | 85/100 | 90/100 | Strategic callers remain isolated from legacy scanner. |
| Pre-News manual universe | 55/100 | 88/100 | Legacy repository dependency removed; existing table preserved. |
| News frontend quote dependency | 80/100 | 92/100 | Strategic News page now uses `/news/quote/{ticker}`. |
| DB/schema separation | 55/100 | 72/100 | Strategic primitives/aliases exist; shared DB file cannot be deleted wholesale. |
| Telegram command isolation | 85/100 | 85/100 | No Phase 2E change required; alert sending remains untouched. |
| Overall targeted archive readiness | 76/100 | 88/100 | Safe for targeted archive planning, not blanket deletion. |

## Deletion Risk Assessment

Low deletion risk after targeted import checks:

- Legacy scanner route/page clusters.
- Legacy signal route/service clusters.
- Legacy analysis frontend pages, once route imports are proven absent in lean mode.
- Legacy backtest, HTF, paper trading, and old intelligence pages/routes, provided their lean-mode guards stay active.

Medium deletion risk:

- `src/db/repositories.py`, because legacy routes still use it. Delete only after those routes/services are archived.
- `src/models/schemas.py`, because legacy modules still import many schemas. Delete only after schema consumers are migrated or archived.
- Watchlist UI/service files, because the underlying table remains as manual universe storage. Archive UI/service code only; keep table alias.

High deletion risk:

- `src/models/database.py`
- `src/db/session.py`
- `src/models/strategic.py`
- `src/core/agentic/manual_universe.py`
- `src/models/market_data.py`

These should remain in Phase 3.

## Verification

Fresh verification completed after Phase 2E changes:

- Compile:
  - `python -m py_compile src\api\routes\news.py src\core\agentic\manual_universe.py src\core\agentic\pre_news_detector.py src\models\strategic.py src\models\market_data.py src\models\schemas.py`
  - Passed.
- Focused Phase 2E extraction tests:
  - `8 passed`.
- Focused lean mode / News Momentum / Pre-News / Rocket Shadow verification:
  - `26 passed`.
- Frontend build:
  - `npm.cmd run build`
  - Passed, `2387 modules transformed`.
- Full backend suite:
  - `309 passed, 1 xfailed`.

## Final Verdict

PARTIAL.

Phase 3 is now safe for targeted archive/move of lean-disabled legacy systems, provided deletion is limited to proven legacy routes, services, and frontend pages.

Phase 3 is not safe for blanket deletion of shared DB/schema infrastructure. The strategic systems still need:

- shared DB session/base infrastructure,
- the existing watchlist table as manual-universe storage,
- strategic aliases in `src/models/strategic.py`,
- market-data primitives in `src/models/market_data.py`.

Recommended Phase 3 rule:

Archive legacy feature clusters only after import scans show no strategic dependency. Keep shared infrastructure and strategic alias modules.
