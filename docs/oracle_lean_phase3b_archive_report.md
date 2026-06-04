# Oracle Lean Refactor Phase 3B Archive Report

Generated: 2026-06-04

## Scope

Phase 3B isolated and archived the remaining runtime/frontend legacy blockers identified after Phase 3A.

Guardrails honored:

- News Momentum logic was not modified.
- Pre-News logic was not modified.
- Rocket Shadow scoring logic was not modified.
- SEC Intelligence logic was not modified.
- Telegram alert sending was not modified.
- Market-data providers were not modified.
- No files were permanently deleted.

## Blockers Addressed

### 1. Frontend Legacy Page Lazy Imports

Previous blocker:

- `frontend/src/App.jsx` had literal lazy imports for legacy pages.
- Those imports kept old pages as build-time dependencies even when lean mode hid them.

Resolution:

- Removed runtime imports for:
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
- Added a small local `LegacyArchived` placeholder for legacy route paths.
- Confirmed lean frontend build succeeded before and after moving the legacy page files.

Archived frontend pages:

| Original path | Archived path |
|---|---|
| `frontend/src/pages/ActiveTrades.jsx` | `archive/legacy/frontend/src/pages/ActiveTrades.jsx` |
| `frontend/src/pages/Analysis.jsx` | `archive/legacy/frontend/src/pages/Analysis.jsx` |
| `frontend/src/pages/Backtest.jsx` | `archive/legacy/frontend/src/pages/Backtest.jsx` |
| `frontend/src/pages/Dashboard.jsx` | `archive/legacy/frontend/src/pages/Dashboard.jsx` |
| `frontend/src/pages/Intelligence.jsx` | `archive/legacy/frontend/src/pages/Intelligence.jsx` |
| `frontend/src/pages/PaperTrading.jsx` | `archive/legacy/frontend/src/pages/PaperTrading.jsx` |
| `frontend/src/pages/Performance.jsx` | `archive/legacy/frontend/src/pages/Performance.jsx` |
| `frontend/src/pages/Portfolio.jsx` | `archive/legacy/frontend/src/pages/Portfolio.jsx` |
| `frontend/src/pages/Settings.jsx` | `archive/legacy/frontend/src/pages/Settings.jsx` |
| `frontend/src/pages/Watchlist.jsx` | `archive/legacy/frontend/src/pages/Watchlist.jsx` |

### 2. `src/api/dependencies.py` Coupling

Previous blocker:

- `src/api/dependencies.py` imported `SignalService` at module import time.
- `SignalService` pulled in the legacy scanner, dip/bounce detectors, old ML model store, and old analysis engines.

Resolution:

- Confirmed `src/api/dependencies.py` was only referenced by the archived legacy signals route.
- Archived it with the legacy backend cluster.

Archived dependency file:

| Original path | Archived path |
|---|---|
| `src/api/dependencies.py` | `archive/legacy/backend/api/dependencies.py` |

### 3. `signal_service` Dip/Bounce/ML Runtime Coupling

Previous blocker:

- `src/services/signal_service.py` imported legacy runtime modules at import time:
  - dip detector
  - bounce detector
  - stock classifier
  - legacy dip/bounce ML models
  - legacy model store

Resolution:

- Confirmed no strategic import depends on `signal_service`.
- Confirmed `ORACLE_LEAN_MODE=true` starts without importing it.
- Archived `signal_service` and its directly coupled runtime files.

Archived backend runtime files:

| Original path | Archived path |
|---|---|
| `src/services/signal_service.py` | `archive/legacy/backend/services/signal_service.py` |
| `src/services/watchlist_service.py` | `archive/legacy/backend/services/watchlist_service.py` |
| `src/services/logging_service.py` | `archive/legacy/backend/services/logging_service.py` |
| `src/ml/dip_model.py` | `archive/legacy/backend/ml/dip_model.py` |
| `src/ml/bounce_model.py` | `archive/legacy/backend/ml/bounce_model.py` |
| `src/ml/feature_engineer.py` | `archive/legacy/backend/ml/feature_engineer.py` |
| `src/ml/model_store.py` | `archive/legacy/backend/ml/model_store.py` |
| `src/core/dip_detector.py` | `archive/legacy/backend/core/dip_detector.py` |
| `src/core/bounce_detector.py` | `archive/legacy/backend/core/bounce_detector.py` |
| `src/core/classifier.py` | `archive/legacy/backend/core/classifier.py` |
| `src/core/backtester.py` | `archive/legacy/backend/core/backtester.py` |
| `src/core/backtest_validator.py` | `archive/legacy/backend/core/backtest_validator.py` |

## Import Safety Checks

Post-move source scan found no strategic imports of archived runtime modules.

The only remaining source reference to an archived service is:

```text
src/main.py -> from src.services.watchlist_service import WatchlistService
```

That reference is inside the legacy watchlist refresh loop guarded by `settings.watchlist_enabled`, which is false in lean mode.

## Lean Startup Verification

Command:

```powershell
$env:ORACLE_LEAN_MODE='true'
python -c "import sys; import src.main as m; ..."
```

Result:

```text
lean_import_ok True
legacy_runtime_imports []
routes 111
```

## Lean Frontend Build Verification

Command:

```powershell
$env:VITE_ORACLE_LEAN_MODE='true'
npm.cmd run build
```

Result after removing old imports and before moving files:

```text
1575 modules transformed.
built in 9.35s
```

Result after moving legacy pages:

```text
1575 modules transformed.
built in 8.66s
```

## Tests Added

Updated `tests/unit/test_oracle_lean_mode.py` to assert:

- `App.jsx` has no runtime imports for archived frontend legacy pages.
- Phase 3B runtime files are absent from the runtime tree and present under `archive/legacy/`.
- Phase 3B frontend legacy pages are absent from `frontend/src/pages` and present under `archive/legacy/`.

## Remaining Legacy Modules

Some non-strategic legacy modules remain in `src/core/` because they are outside the Phase 3B blocker set or have broader internal dependencies:

- legacy decision/backtest engines not directly required by strategic systems
- legacy HTF/scanner helper modules
- legacy analysis primitives used only by disabled Telegram legacy commands

They are not imported during lean startup. They should be evaluated as Phase 3C candidates after another import graph pass.

## Verification Checklist

Required after this report:

- Focused lean/strategic backend tests.
- Full backend test suite.
- Frontend build.
- Lean startup verification.

## Verification Results

### Lean Startup Verification

Command:

```powershell
$env:ORACLE_LEAN_MODE='true'
python -c "import sys; import src.main as m; ..."
```

Result:

```text
lean_import_ok True
legacy_runtime_imports []
routes 111
```

### Focused Strategic Tests

Command:

```powershell
python -m pytest tests\unit\test_oracle_lean_mode.py tests\unit\test_strategic_dependency_extraction.py tests\unit\test_news_momentum_alert_flow.py tests\unit\test_pre_news_validation.py tests\unit\test_rocket_model_shadow.py -q
```

Result:

```text
31 passed, 910 warnings
```

### Full Backend Tests

Command:

```powershell
python -m pytest -q
```

Result:

```text
314 passed, 1 xfailed, 911 warnings
```

The xfail is the pre-existing classifier historical miss target:

```text
tests/regression/test_classifier_historical_misses.py::test_classifier_matches_expected_label[lnks_004_neg]
```

### Frontend Build

Lean build after archive:

```text
1575 modules transformed.
built in 8.66s
```

Final production build:

```text
1575 modules transformed.
built in 39.97s
```

## Final Verdict

SAFE FOR PHASE 3B TARGETED ARCHIVE.

The frontend legacy pages, `src/api/dependencies.py`, `signal_service`, and directly coupled dip/bounce/legacy-ML runtime files have been moved to `archive/legacy/` with lean startup and lean frontend build verified.
