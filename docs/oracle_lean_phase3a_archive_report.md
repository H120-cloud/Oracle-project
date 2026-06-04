# Oracle Lean Refactor Phase 3A Archive Report

Generated: 2026-06-04

## Scope

Phase 3A performed a targeted archive move only. No files were deleted permanently.

Guardrails honored:

- News Momentum logic was not modified.
- Pre-News logic was not modified.
- Rocket Shadow scoring logic was not modified.
- SEC Intelligence logic was not modified.
- Telegram alert sending was not modified.
- Market-data providers were not modified.
- Shared DB/session/schema infrastructure was not moved.

## Archive Destination

Legacy files moved to:

- `archive/legacy/backend/api/routes/`
- `archive/legacy/backend/ml/`

These files are preserved as source artifacts, but they are no longer in the runtime `src/` tree.

## Pre-Move Checks

Lean startup was verified before moving files:

```text
lean_import_ok True
legacy_imports []
routes 111
```

Import graph checks showed the moved backend route modules were referenced only by:

- `src/main.py` feature-gated legacy route registration blocks
- lean-mode tests that assert those modules are not imported
- historical documentation

No strategic News Momentum, Pre-News, Rocket Shadow, SEC Intelligence, Telegram alert sending, or market-data provider module imported these route files in lean mode.

## Files Archived

| Original path | Archived path | Reason |
|---|---|---|
| `src/api/routes/scanner.py` | `archive/legacy/backend/api/routes/scanner.py` | Legacy scanner route. Lean-disabled and only imported by feature-gated main route registration. |
| `src/api/routes/signals.py` | `archive/legacy/backend/api/routes/signals.py` | Legacy signal route. Lean-disabled and only imported by feature-gated main route registration. |
| `src/api/routes/watchlist.py` | `archive/legacy/backend/api/routes/watchlist.py` | Legacy watchlist route. Pre-News now uses `src/core/agentic/manual_universe.py`; route is lean-disabled. |
| `src/api/routes/models.py` | `archive/legacy/backend/api/routes/models.py` | Legacy dip/bounce model route. Lean-disabled and only imported by feature-gated main route registration. |
| `src/api/routes/analysis.py` | `archive/legacy/backend/api/routes/analysis.py` | Legacy analysis route. Strategic News quote flow uses `/api/v1/news/quote/{ticker}`. |
| `src/api/routes/backtest.py` | `archive/legacy/backend/api/routes/backtest.py` | Legacy backtest route. Lean-disabled and only imported by feature-gated main route registration. |
| `src/api/routes/intelligence.py` | `archive/legacy/backend/api/routes/intelligence.py` | Legacy intelligence route. SEC Intelligence uses its separate strategic route. |
| `src/api/routes/htf_scan.py` | `archive/legacy/backend/api/routes/htf_scan.py` | Legacy HTF scan route. Lean-disabled and only imported by feature-gated main route registration. |
| `src/api/routes/paper_trading.py` | `archive/legacy/backend/api/routes/paper_trading.py` | Legacy paper trading route. Route and paper-trading price loop are lean-disabled. |
| `src/ml/trainer.py` | `archive/legacy/backend/ml/trainer.py` | Legacy dip/bounce ML trainer. Only imported by the archived legacy model route. |

## Post-Move Lean Startup Check

Lean startup was verified after the move:

```text
lean_import_ok True
legacy_imports []
routes 111
```

This confirms `ORACLE_LEAN_MODE=true` starts without importing archived legacy route modules.

## Not Archived In Phase 3A

These candidates remain in place because they still have coupling that should be resolved before a safe archive move.

| Candidate | Reason held back | Risk |
|---|---|---|
| `src/core/dip_detector.py`, `src/core/bounce_detector.py`, `src/core/classifier.py` | Still imported by `src/services/signal_service.py`, `src/services/watchlist_service.py`, and legacy backtest modules. | Medium |
| `src/services/signal_service.py` | `src/api/dependencies.py` imports `SignalService` at module import time. Moving it would require dependency-module extraction first. | Medium |
| `src/services/watchlist_service.py` | Legacy route archived, but service still contains coupled dip/bounce checks and old watchlist behavior. | Medium |
| `src/ml/dip_model.py`, `src/ml/bounce_model.py`, `src/ml/feature_engineer.py`, `src/ml/model_store.py` | Still imported by `src/services/signal_service.py`. | Medium |
| Legacy frontend pages | `frontend/src/App.jsx` still contains literal lazy import paths for legacy pages. Moving pages now would require frontend routing/archive-loader changes and could break Vite build. | Medium |
| Shared DB/session/schema files | Explicitly out of scope and still required by strategic systems. | High |

## Remaining Legacy Dependencies

Known non-archived legacy dependency chain:

```text
src/api/dependencies.py
  -> src/services/signal_service.py
      -> src/core/scanner.py
      -> src/core/professional_scanner.py
      -> src/core/discovery_engine.py
      -> src/core/dip_detector.py
      -> src/core/bounce_detector.py
      -> src/core/classifier.py
      -> src/core/decision_engine.py
      -> src/ml/dip_model.py
      -> src/ml/bounce_model.py
      -> src/ml/model_store.py
```

This chain is not imported by lean-mode startup, but it should be extracted or archived as one coordinated legacy cluster in the next phase.

## Verification Plan

Required verification for this phase:

- Lean mode startup verification.
- News Momentum focused verification.
- Pre-News focused verification.
- Rocket Shadow focused verification.
- Full backend tests.
- Frontend build.

## Verification Results

### Lean Mode Startup

Command:

```powershell
$env:ORACLE_LEAN_MODE='true'
python -c "import sys; import src.main as m; ..."
```

Result:

```text
lean_import_ok True
legacy_imports []
routes 111
```

### Focused Strategic Backend Tests

Command:

```powershell
python -m pytest tests\unit\test_oracle_lean_mode.py tests\unit\test_strategic_dependency_extraction.py tests\unit\test_news_momentum_alert_flow.py tests\unit\test_pre_news_validation.py tests\unit\test_rocket_model_shadow.py -q
```

Result:

```text
28 passed, 910 warnings
```

Coverage:

- Lean mode import boundaries.
- Strategic dependency extraction.
- News Momentum alert flow.
- Pre-News validation.
- Rocket Shadow scoring.

### Full Backend Tests

Command:

```powershell
python -m pytest -q
```

Result:

```text
311 passed, 1 xfailed, 911 warnings
```

The single xfail is the pre-existing classifier historical miss target:

```text
tests/regression/test_classifier_historical_misses.py::test_classifier_matches_expected_label[lnks_004_neg]
```

### Frontend Build

First sandboxed build attempt failed with a local sandbox permission error:

```text
Error: EPERM: operation not permitted, lstat 'C:\Users\Husna'
```

Rerunning the same build outside the sandbox completed successfully.

Command:

```powershell
npm.cmd run build
```

Result:

```text
vite v5.4.21 building for production...
2387 modules transformed.
built in 13.76s
```

## Archive Readiness Score

| Area | Score | Notes |
|---|---:|---|
| Legacy backend route archive | 95/100 | Route files moved and lean startup confirmed clean. |
| Legacy dip/bounce runtime archive | 55/100 | Still blocked by `src/api/dependencies.py` and legacy service imports. |
| Legacy frontend page archive | 60/100 | Lazy imports are lean-hidden but still literal build-time dependencies. |
| Shared DB/session/schema archive | 0/100 | Explicitly out of scope and must remain. |
| Strategic system safety | 92/100 | Strategic route set starts in lean mode without archived modules. |

Overall Phase 3A archive readiness after this move: 82/100.

## Phase 3B Safe Next Step

Recommended next step:

1. Split `src/api/dependencies.py` into strategic and legacy dependency providers.
2. Move `signal_service`, dip/bounce runtime modules, and remaining dip/bounce ML runtime as one legacy cluster.
3. Replace legacy frontend lazy imports with an archive-safe disabled legacy route boundary before moving frontend pages.

## Final Verdict

PARTIAL SAFE ARCHIVE.

The backend legacy route layer and legacy model trainer were safely moved into `archive/legacy/`. Remaining runtime/service/frontend legacy clusters should not be moved until their last import couplings are removed.
