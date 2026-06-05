# Railway Persistence Fix — P0 Implementation Report

**Date:** 2026-06-05
**Goal:** Oracle must survive Railway redeploys/restarts without losing state.
**Constraint honored:** No changes to alert scoring or Telegram gating logic — this
change only relocates *where* state is read/written and adds startup safety.
**Follow-up to:** `docs/railway_deployment_safety_audit.md` (the P0 items).

---

## Outcome

- **One source of truth** for the agentic state directory: `src/utils/data_paths.py`.
- **44 modules** now resolve their data directory through that helper. **Zero**
  modules hardcode `Path("data/agentic")` or read `AGENTIC_DATA_DIR` inline — proven
  by structural tests, so the split-brain class of bug cannot regress.
- **Startup guard** fails the boot loudly on Railway if no persistent volume is
  attached, instead of silently wiping state on the next redeploy.
- **Seeding mechanism** warms a fresh/restored volume from `seed/agentic/` without
  ever overwriting live state.
- **Tests:** `438 passed, 1 xfailed` (the xfail is the pre-existing P1 classifier
  target, unrelated). 18 new tests in `tests/unit/test_data_paths.py`.

---

## What changed (exact files)

### New
- **`src/utils/data_paths.py`** — central helper. API:
  - `agentic_data_dir() -> Path` — reads `AGENTIC_DATA_DIR` live; default `data/agentic`.
  - `agentic_path(*parts) -> Path` — join under the data dir.
  - `AGENTIC_DATA_DIR: Path` — resolved-once convenience constant.
  - `verify_persistent_data_dir()` — Railway startup guard (task 5).
  - `seed_agentic_data_dir(...)` / `default_seed_dir()` — baseline seeding (task 7).
- **`tests/unit/test_data_paths.py`** — 18 tests (resolution, no-split-brain
  structural + functional, startup guard, seeding).
- **`seed/agentic/README.md`** — what to drop for baseline seeding.

### Modified — wiring & config
- **`src/main.py`** — import the helper; in `lifespan`, before `create_all`:
  `verify_persistent_data_dir()` → `mkdir` → `seed_agentic_data_dir()`.
- **`railway.toml`** — documented the required `/app/data` volume + CLI command.
- **`.env.railway`** — `AGENTIC_DATA_DIR=/app/data/agentic`, volume/Postgres/escape-hatch notes.
- **`.gitignore`** — `!seed/` + `!seed/**` so baseline artifacts can ship despite the
  global `*.joblib`/`*.parquet`/`data/` ignores.

### Modified — path routing (40+ sites across these 41 modules)
All now import from `src.utils.data_paths`. Grouped by original pattern:

- **Hardcoded `Path("data/agentic")` → `AGENTIC_DATA_DIR`:**
  `company_name_resolver`, `feature_flags`, `news_momentum_backfill`,
  `news_momentum_big_winner_model`, `news_momentum_catalyst_learning`,
  `news_momentum_eod_review`, `news_momentum_historical_backfill`,
  `news_momentum_missed_learning`, `news_momentum_ml_engine`,
  `news_momentum_nlp_classifier`, `news_momentum_shadow_logger`,
  `news_momentum_unknown_learner`, `news_momentum_winners`, `pre_news_detector`,
  `pre_news_evaluator`, `pre_news_learning`, `pre_news_shadow_v2`,
  `pre_news_validation`, `pre_news_baseline` (BASE_DIR), `ml_advisory` (was `__file__`-relative).
- **Inline `os.environ.get("AGENTIC_DATA_DIR", …)` → helper:**
  `news_momentum_orchestrator`, `news_momentum_telegram_learning`,
  `news_alert_latency_trace`, `news_impact_learning`, `pre_news_alert_audit`,
  `quality_separator`, `telegram_outbox`, `telegram_command_handler`,
  and string-typed `calibration_provider`, `historical_calibration`,
  `historical_dataset_builder`, `historical_training` (`str(agentic_data_dir())`).
- **Sub-paths / file literals → `agentic_path(...)` / `agentic_data_dir()`:**
  `sec_edgar_fetcher` & `sec_intelligence_orchestrator` (`/sec`),
  `pre_news_bridge` (anomalies file), `rocket_catboost_baseline`,
  `rocket_dataset_builder`, `rocket_forward_enrichment`, `rocket_label_reconstructor`,
  `rocket_model_shadow`, `api/routes/pre_news` (evaluation reports).

> The refactor was applied via a one-shot exact-string migration script (since
> removed). It changed only the directory each module points at; no business logic
> was touched.

---

## How each task is satisfied

### 1. Railway volume mounted at `/app/data`
Railway does **not** create volumes via config-as-code, so this is a one-time
dashboard/CLI action, now documented at the top of `railway.toml`:

```
railway volume add --mount-path /app/data
```

Railway then injects `RAILWAY_VOLUME_MOUNT_PATH=/app/data`. Because `WORKDIR=/app`
and the default data path is `data/agentic`, **all 44 modules** resolve to
`/app/data/agentic` — on the volume — automatically.

### 2. `AGENTIC_DATA_DIR` set consistently
`.env.railway` sets `AGENTIC_DATA_DIR=/app/data/agentic` (explicit and
self-documenting). Because every module now routes through the single helper,
setting this env var is honored **everywhere** — there is no longer a set of
modules that ignore it (that was the original split-brain risk).

### 3. Audit all hardcoded `Path("data/agentic")` → central helper
Done for all 40+ sites. Enforced permanently by two structural tests that scan the
whole `src/` tree and fail if any module reintroduces a hardcoded path or an inline
env read:
- `test_no_module_hardcodes_agentic_data_path`
- `test_no_module_reads_agentic_env_inline`

### 4. Outbox, registry, cooldowns, alert history, model artifacts, trace logs co-located
All of these resolve under the same `AGENTIC_DATA_DIR`, hence the same volume:
- Telegram outbox — `telegram_outbox.py` → `…/telegram_outbox.jsonl`
- Dedup/event registry, ticker & headline cooldowns, alert memory — `news_momentum_orchestrator.py`
- Alert history — `news_momentum_telegram_learning.py`
- ML / Big-Winner / NLP models — `news_momentum_ml_engine.py`, `…_big_winner_model.py`, `…_nlp_classifier.py`
- CatBoost / Rocket shadow model + predictions — `rocket_model_shadow.py`, `rocket_catboost_baseline.py`
- Trace logs — `news_alert_latency_trace.py`
- SEC cache — `sec_edgar_fetcher.py`, `sec_intelligence_orchestrator.py` (`…/sec`)

Functional proof: `test_representative_modules_resolve_under_configured_dir`
reloads a representative set under a custom `AGENTIC_DATA_DIR` and asserts they all
land under it.

### 5. Startup check that fails loudly without persistent data dir
`verify_persistent_data_dir()` (called first in `main.py` lifespan):
- **No-op** off Railway (local/dev) and when `ORACLE_ALLOW_EPHEMERAL=true` (explicit opt-out).
- **Raises `RuntimeError`** when on Railway (`RAILWAY_ENVIRONMENT`/`_PROJECT_ID`/`_SERVICE_ID`)
  and either no `RAILWAY_VOLUME_MOUNT_PATH` is present or the data dir is not under it.

Verified live: simulating Railway-without-volume raises; with the volume it passes.
Tests: `test_verify_guard_*` (5 cases).

### 6. Tests proving no split-brain
`tests/unit/test_data_paths.py`:
- **Structural** (whole-tree scan): no hardcoded paths, no inline env reads.
- **Functional** (module reload under a custom dir): telegram_outbox, ml_engine,
  company_name_resolver, shadow_logger all resolve under the configured dir.
- Plus resolution, guard, and seeding behavior.

### 7. Seed baseline model/name-map (or document volume restore)
Both paths provided:
- **Seed-on-boot:** drop baseline artifacts into `seed/agentic/` (e.g.
  `news_momentum_ml_model.joblib` + meta, `company_name_ticker_map.json`).
  `seed_agentic_data_dir()` copies them into the data dir **only if absent** — never
  clobbering live state. Docs/dotfiles are skipped, so `README.md` is not seeded.
  `.gitignore`/`.dockerignore` allow these artifacts to ship.
- **Volume restore (documented alternative):** leave `seed/agentic/` empty and
  restore the Railway volume from a backup. Either way, cold-start is avoided.

> Note: no binary baseline artifacts are committed in this change — the directory
> and mechanism are in place; the operator chooses seed-in-image vs volume-restore.

---

## Required operator actions to go live

1. **Create + attach a Railway volume** mounted at `/app/data`
   (`railway volume add --mount-path /app/data`).
2. Set **`AGENTIC_DATA_DIR=/app/data/agentic`** (already in `.env.railway`).
3. **Provision Postgres** and let Railway inject `DATABASE_URL` (recommended), or
   set `DATABASE_URL=sqlite:////app/data/oracle.db` to keep SQLite on the volume.
4. (Optional) Populate `seed/agentic/` with a baseline model + name-map, **or**
   restore the volume from backup, to avoid a cold ML start.

Without step 1/2 the app will **refuse to start** on Railway (by design). To run
intentionally ephemerally, set `ORACLE_ALLOW_EPHEMERAL=true`.

---

## Verification evidence

| Check | Result |
|-------|--------|
| `python -m compileall src` | exit 0 |
| `import src.main` | OK |
| Hardcoded `Path("data/agentic")` in `src` (excl. helper) | 0 |
| Inline `AGENTIC_DATA_DIR` env reads in `src` (excl. helper) | 0 |
| Modules importing the helper | 44 |
| Startup guard: Railway w/o volume | raises `RuntimeError` |
| Startup guard: Railway w/ volume at `/app/data` | passes |
| `tests/unit/test_data_paths.py` | 18 passed |
| Full suite (`python -m pytest`) | **438 passed, 1 xfailed** |

---

## Scope / non-goals

- **No** changes to alert scoring, Telegram gating, cooldown windows, or freshness
  logic. Audit areas §5 (ticker false-match) and §6 (post-restart freshness
  defense-in-depth) from the deployment audit remain as separate P1 items.
- Volume **provisioning** is a Railway dashboard/CLI action; this change makes the
  app *require and use* it correctly, and documents the step.
- The relational store (SQLite/Postgres) durability is covered by the documented
  `DATABASE_URL` guidance; the code change here is limited to the agentic file state.
