# Oracle Lean Refactor Phase 4 Deletion Report

Generated: 2026-06-04

## Scope

Phase 4 permanently removed the archived legacy bundle:

- `archive/legacy/`

No strategic source, data, or model artifact directories were deleted.

Explicitly preserved:

- News Momentum files.
- Pre-News files.
- Rocket Dataset / CatBoost Shadow files.
- SEC Intelligence files.
- Telegram alert sender.
- Market-data providers.
- Shared DB/session/schema infrastructure.
- `data/agentic` training datasets and model artifacts.

## Pre-Deletion Gate

### Lean Startup

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

### Strategic Archive Import Check

Checked strategic/runtime paths for:

- `archive/legacy`
- `archive.legacy`
- deleted legacy runtime imports

Result:

```text
No strategic import dependency on archive/legacy found.
```

### Focused Strategic Tests Before Deletion

Command:

```powershell
python -m pytest tests\unit\test_oracle_lean_mode.py tests\unit\test_strategic_dependency_extraction.py tests\unit\test_news_momentum_alert_flow.py tests\unit\test_pre_news_validation.py tests\unit\test_rocket_model_shadow.py -q
```

Result:

```text
31 passed, 910 warnings
```

## Files Deleted

Deleted exactly `archive/legacy/`, containing 33 files:

```text
archive\legacy\backend\api\dependencies.py
archive\legacy\backend\api\routes\analysis.py
archive\legacy\backend\api\routes\backtest.py
archive\legacy\backend\api\routes\htf_scan.py
archive\legacy\backend\api\routes\intelligence.py
archive\legacy\backend\api\routes\models.py
archive\legacy\backend\api\routes\paper_trading.py
archive\legacy\backend\api\routes\scanner.py
archive\legacy\backend\api\routes\signals.py
archive\legacy\backend\api\routes\watchlist.py
archive\legacy\backend\core\backtest_validator.py
archive\legacy\backend\core\backtester.py
archive\legacy\backend\core\bounce_detector.py
archive\legacy\backend\core\classifier.py
archive\legacy\backend\core\dip_detector.py
archive\legacy\backend\ml\bounce_model.py
archive\legacy\backend\ml\dip_model.py
archive\legacy\backend\ml\feature_engineer.py
archive\legacy\backend\ml\model_store.py
archive\legacy\backend\ml\trainer.py
archive\legacy\backend\services\logging_service.py
archive\legacy\backend\services\signal_service.py
archive\legacy\backend\services\watchlist_service.py
archive\legacy\frontend\src\pages\ActiveTrades.jsx
archive\legacy\frontend\src\pages\Analysis.jsx
archive\legacy\frontend\src\pages\Backtest.jsx
archive\legacy\frontend\src\pages\Dashboard.jsx
archive\legacy\frontend\src\pages\Intelligence.jsx
archive\legacy\frontend\src\pages\PaperTrading.jsx
archive\legacy\frontend\src\pages\Performance.jsx
archive\legacy\frontend\src\pages\Portfolio.jsx
archive\legacy\frontend\src\pages\Settings.jsx
archive\legacy\frontend\src\pages\Watchlist.jsx
```

Deletion result:

```text
DELETED archive\legacy
EXISTS_AFTER=False
```

## Post-Deletion Verification

### Lean Startup

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
32 passed, 910 warnings
```

Coverage:

- lean-mode startup and import guards
- News Momentum alert flow
- Pre-News validation
- Rocket Shadow scoring
- strategic dependency extraction

### Full Backend Tests

Command:

```powershell
python -m pytest -q
```

Result:

```text
315 passed, 1 xfailed, 911 warnings
```

The single xfail is the pre-existing classifier target:

```text
tests/regression/test_classifier_historical_misses.py::test_classifier_matches_expected_label[lnks_004_neg]
```

### Frontend Build

Command:

```powershell
npm.cmd run build
```

Result:

```text
1575 modules transformed.
built in 15.37s
```

## Remaining Legacy References

Final scan found one source reference to a deleted legacy service:

```text
src\main.py:553: from src.services.watchlist_service import WatchlistService
```

This reference is inside the legacy watchlist refresh loop and is guarded by `settings.watchlist_enabled`. It is not imported when `ORACLE_LEAN_MODE=true`; lean startup verified `legacy_runtime_imports []`.

Impact:

- Lean mode is safe.
- Strategic systems are safe.
- Non-lean legacy watchlist refresh is no longer runnable unless restored from history.

## Tests Updated

Updated `tests/unit/test_oracle_lean_mode.py` so Phase 4 now asserts:

- `archive/legacy` does not exist.
- archived route/runtime files are absent from the runtime tree.
- legacy frontend pages are absent from `frontend/src/pages`.
- strategic/lean imports still do not load deleted legacy modules.

## Rollback Note

Rollback requires restoring `archive/legacy/` from version control history or an external backup. The deleted files were intentionally removed from the working tree after passing the pre-deletion gate.

## Final Status

SAFE DELETE COMPLETED.

`archive/legacy/` is removed, lean startup passes, focused strategic tests pass, full backend tests pass, and the frontend build passes.
