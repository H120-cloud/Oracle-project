# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Principles

### 1. Think Before Coding
* Surface tradeoffs and ask when uncertain rather than guessing.
* Present multiple interpretations of ambiguous requirements.
* Push back on overly complex solutions and seek simpler approaches.

### 2. Simplicity First
* Prioritize minimal, concise code over speculative, abstract features.
* Avoid unnecessary configuration, abstractions, or error handling.

### 3. Surgical Changes
* Focus on necessary changes, minimizing impact on surrounding code.
* Match existing style, refactoring only if essential.

### 4. Goal-Driven Execution
* Define success criteria and verify against them.
* Write tests for bugs before implementing fixes.

---

## Commands

**Run backend (development):**
```
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
Or double-click `start_oracle.bat`.

**Build Rocket training dataset:**
```
python run_rocket_build.py
```
Outputs `data/agentic/rocket_training_dataset.{csv,parquet}`, `data/agentic/rocket_rejected_rows.csv`, and `docs/rocket_dataset_report.md`.

**Run all tests:**
```
python -m pytest
# or via the wrapper:
./scripts/test.sh
```

**Run a single test file:**
```
pytest tests/unit/test_news_momentum_alert_flow.py -v
```

**Run regression tests only:**
```
pytest tests/regression/ -v
# or:
./scripts/test.sh -m regression
```

**Run by marker:**
```
pytest -m unit          # fast, no I/O, no network
pytest -m regression    # locks-in historical behavior; never skip
pytest -m "not slow"    # exclude tests > 1s
```

**Full CI check (syntax + tests):**
```
./scripts/ci_check.sh    # Linux/Mac
scripts/ci_check.ps1     # Windows PowerShell
```

**Frontend dev server:**
```
cd frontend && npm run dev    # Vite on localhost:5173
```

**Build frontend:**
```
cd frontend && npm install && npm run build
```

**Docker (full stack with Postgres + Redis):**
```
docker-compose up --build
```

**Database migrations (Alembic):**
```
alembic upgrade head
alembic revision --autogenerate -m "description"
```
Note: `alembic/versions/` is currently empty — no migrations have been created yet. The ORM uses `Base.metadata.create_all()` on startup for dev/SQLite.

---

## Architecture

Oracle is a FastAPI backend + React frontend trading signal system. The backend runs on port 8000 and serves the built React app from `frontend/dist/` as static files.

### Data storage
- **SQLAlchemy ORM** for structured data (signals, watchlists). Defaults to SQLite (`oracle.db`) in dev; PostgreSQL in Docker/production. Models in `src/models/database.py`, access via repositories in `src/db/repositories.py`.
- **JSON files in `data/agentic/`** for all agentic/momentum state (candidates, cooldowns, outcomes, ML models). Every write goes through `src/utils/atomic_json.py` to prevent corruption. Never write these files directly with `open()`.

### Configuration
All settings live in `src/config.py` (pydantic-settings). Values come from `.env`. Copy `.env.example` → `.env` to get started. Key optional integrations: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (alerts), `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (real-time news stream + paper trading), `ALPHAVANTAGE_API_KEY`, `POLYGON_API_KEY`.

**Lean mode** — set `ORACLE_LEAN_MODE=true` to disable entire subsystems at startup. Nine per-subsystem feature flags in `src/config.py` provide finer control (e.g. `ORACLE_ENABLE_SEC`, `ORACLE_ENABLE_ML_RETRAIN`). Check these before enabling resource-intensive paths.

### Background loops (all in `src/main.py` lifespan)
Ten async loops start on app startup, staggered to avoid thundering-herd on market data APIs:
| Loop | Interval | Purpose |
|------|----------|---------|
| `_watchlist_broadcast_loop` | 1s | WebSocket price updates + alert detection every 60s |
| `_paper_trading_price_loop` | 30s | Live price updates for paper positions |
| `_outcome_simulator_loop` | 30 min | Simulates outcome resolution for paper/shadow candidates |
| `_pre_news_scan_loop` | 3 min | Pre-news volume anomaly detection |
| `_news_momentum_scan_loop` | 45s (adaptive) | Multi-source news catalyst scanning |
| `_sec_edgar_firehose_loop` | 15s | SEC 8-K filing ingestion |
| `_news_momentum_eod_review_loop` | Daily 21:30 UTC | End-of-day review and outcome finalization |
| `_news_momentum_outcome_resolver_loop` | 30 min | Auto-label alert outcomes (win/loss) |
| `_news_momentum_ml_retrain_loop` | Weekly (Sun 02:00 UTC) | Retrain ML scoring model |
| `_agentic_outcome_loop` | 30 min | *(currently disabled)* Agentic candidate outcome recording |

`_news_scan_lock` serializes calls to `NewsMomentumOrchestrator.scan()` between the periodic RSS loop and the event-driven Alpaca news WebSocket, preventing race conditions on candidate/cooldown state.

### Core subsystems

**News Momentum (V22)** — `src/core/agentic/news_momentum_orchestrator.py`
The central coordinator. Ingests `NewsEvent` objects from Finviz, StockTitan, Alpaca stream, and SEC EDGAR. Pipeline: `classify_headline` → `score_news_impact` → `compute_reaction_metrics` → `compute_expected_return_score` → `compute_continuation_probability` → ML gate → Telegram alert. State persisted to `data/agentic/news_momentum_*.json`. The orchestrator instance is shared between the background loops and the API route via `set_orchestrator()` in `src/api/routes/news_momentum.py`.

**Pre-News Detector** — `src/core/agentic/pre_news_detector.py`
Scans for abnormal volume BEFORE any news appears. Assigns a `pre_news_suspicion_score` (0–100); anomalies ≥75 trigger a Telegram alert. Confirmed anomalies are handed off to `AgenticOrchestrator` for tracking. Shadow V2 system (`pre_news_shadow_v2.py`) runs alongside in observe-only mode to validate gate changes.

**Agentic Orchestrator** — `src/core/agentic/orchestrator.py`
Tracks catalyst-driven candidates post-alert. Receives handoffs from PreNewsDetector via `handoff_from_pre_news()`. Outcomes recorded by `LearningEngine`.

**SEC Intelligence** — `src/core/agentic/sec_intelligence_orchestrator.py`
Ingests SEC 8-K filings via `sec_edgar_firehose.py` (15s polling). Scoring pipeline in `sec_scoring_engine.py`; dilution history tracked separately in `sec_dilution_history.py`. Wired to the API route via `set_orchestrator()` in `src/api/routes/sec_intelligence.py`.

**Market data abstraction** — `src/services/market_data.py`
`get_market_data_provider()` returns the configured provider (yfinance by default; Alpaca, AlphaVantage, Polygon also available). Always use this instead of calling `yfinance` or provider clients directly, except in background loops where `asyncio.to_thread` is used for yfinance calls to avoid blocking the event loop.

**ML models** — `src/core/agentic/news_momentum_ml_engine.py` (news momentum ranker) and `src/core/agentic/rocket_catboost_baseline.py` (Rocket baseline). `src/ml/` is currently an empty placeholder. The news ML model is a scikit-learn classifier stored as `data/agentic/news_momentum_ml_model.joblib`. It auto-retrains weekly; `BigWinnerMLEngine` separately targets high-conviction setups.

**Rocket Dataset Builder** — `src/core/agentic/rocket_dataset_builder.py`
Builds a leakage-safe, labelled CSV/Parquet training dataset from Oracle alert sources (telegram, shadow, backfill, missed, prenews) for the Rocket model. Four-stage pipeline: ingest → enrich (fetch intraday + daily bars) → label → assemble. Key invariants:
- `FEATURE_COLUMNS` and `LABEL_COLUMNS` are explicit manifests with zero overlap — the anti-leakage contract is enforced in tests.
- Label functions: `compute_peak_metrics`, `compute_runner_tier`, `compute_mfe_mae_profiles`, `compute_drawdown_quality`. Runner tiers: `STANDARD_WIN` (≥10%), `MAJOR_RUNNER` (≥30%, within 2d), `MONSTER_RUNNER` (≥100%, within 5d), `LEGENDARY_RUNNER` (≥300%).
- Drawdown quality: `CLEAN_RUNNER` (no MAE breach en route), `DIRTY_RUNNER` (MAE breach but recovered), `TRAP` (rule 1: low ≤−10% of alert; rule 2: close drops ≥35% from peak).
- Deduplication priority (highest first): telegram > missed > shadow > backfill > prenews.
- `RocketDatasetBuilder(data_dir=..., docs_dir=...)` accepts overrides for test isolation — use `tmp_path` in tests, never the production `data/agentic/` path.
- Entrypoint: `python run_rocket_build.py`. Requires `pyarrow>=14.0.0`.

**Feature flags** — `src/core/agentic/feature_flags.py`, backed by `data/agentic/feature_flags.json`. Check flags before enabling new experimental paths.

### Service layer (`src/services/`)
Key services beyond market data:
- `telegram_service.py` — `send_telegram_alert()` with outbox deduplication via `telegram_outbox.py` (persists sent alerts to prevent re-sends across restarts).
- `alpaca_news_stream.py` — real-time Alpaca WebSocket; feeds `_handle_streamed_news()` in main.py which acquires `_news_scan_lock` before calling the orchestrator.
- `htf_alert_service.py` — higher-timeframe bias detection, called in the watchlist broadcast loop.

### API routes (`src/api/routes/`)
All prefixed `/api/v1/`. Route modules: `scanner`, `signals`, `watchlist`, `news_momentum`, `pre_news`, `agentic`, `sec_intelligence`, `paper_trading`, `news`, `frontend_auth`, `timing_reviews`, `historical_training`. Two WebSocket endpoints: `/ws/signals` and `/ws/watchlist`.

**Route wiring pattern**: orchestrators that span background loops and API routes are instantiated once in `src/main.py` lifespan and injected into route modules via `set_orchestrator()`. This applies to `NewsMomentumOrchestrator` (news_momentum routes) and `SecIntelligenceOrchestrator` (sec_intelligence routes). Never instantiate these inside route handlers.

### Dependency constraints
- `websockets` is pinned to `==13.1` — `alpaca-py 0.28` uses a legacy `extra_headers` argument removed in websockets ≥14, which would break the real-time Alpaca news stream.
- `pyarrow>=14.0.0` is required for Parquet output in the Rocket Dataset Builder.

### Testing conventions
- Tests must not touch `data/agentic/` production files. Use the `tmp_data_dir` fixture from `conftest.py` for any test exercising state persistence.
- `make_candidate` and `make_telegram_record` fixtures provide cheap model construction. `make_shadow_record` is available for shadow-logger tests.
- `_fixed_random_seed` is an autouse fixture (pins RNG to 42) — do not override it.
- Regression tests in `tests/regression/` guard the catalyst classifier contract against `tests/fixtures/historical_misses.json` — update the fixture file when intentionally changing classifications.
- Do not construct `NewsMomentumOrchestrator` in unit tests; it touches disk and is too heavy.
- Rocket Dataset Builder tests (`tests/unit/test_rocket_labeler.py`) instantiate `RocketDatasetBuilder(data_dir=tmp_path, docs_dir=tmp_path)` and monkeypatch `_fetch_bars` to `(None, None)` to avoid live market data calls. Never pass the production `data/agentic/` path.

**Pytest markers** (defined in `pytest.ini`):
| Marker | Meaning |
|--------|---------|
| `unit` | Fast, no I/O, no network |
| `regression` | Locks in historical behavior; never skip |
| `classifier` | Catalyst classifier behavior |
| `gate` | Telegram gate / threshold tests |
| `alert_gate` | End-to-end alert-gate decisions (synthetic candidates) |
| `slow` | Takes >1s; deselect with `-m "not slow"` |
