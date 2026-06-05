# Railway Deployment Safety Audit

**Date:** 2026-06-05
**Scope:** Oracle backend deployment on Railway (Docker builder, `railway.toml`).
**Status:** Findings only — **no production logic was modified.** All recommendations are proposals.

---

## TL;DR

Oracle keeps almost all of its runtime intelligence — duplicate registries, alert
cooldowns, the Telegram retry outbox, ML model artifacts, and ticker caches — as
**JSON/joblib files under `data/agentic/`** (and SQLite at `oracle.db`). On Railway:

1. The container filesystem is **ephemeral** — it is reset on every redeploy *and*
   every crash-restart.
2. `.dockerignore` **excludes `data/` and `*.db`** from the image, so the container
   starts with an **empty** `data/agentic/` even on the very first boot.
3. **No persistent volume is declared anywhere in the repo** (`railway.toml` has no
   `[[deploy.volumes]]`; the only mount reference is a comment in `.env.railway`).

The net effect: **unless a Railway volume is manually attached at `/app/data` in the
dashboard, every restart wipes all learned/dedup/outbox state.** The most user-visible
consequence is a **duplicate-alert storm** after each redeploy (every still-fresh
headline re-fires) and **silent loss of queued Telegram alerts**.

The code contains a thoughtful mitigation (`_hydrate_cooldowns_from_alert_history`),
but it reads from the *same* ephemeral files, so it is a no-op when state is wiped.

| # | Area | Severity (no volume) | Severity (volume at `/app/data`) |
|---|------|----------------------|-----------------------------------|
| 1 | Persistent state vs ephemeral FS | **Critical** | Low |
| 2 | Processed-headline / dup registry | **Critical** | Low |
| 3 | Telegram outbox durability | **High** | Low |
| 4 | Model artifact persistence | **High** | Low |
| 5 | Ticker-resolution false-match | **Medium** (independent of volume) | Medium |
| 6 | Freshness filters after restart | **High** | Low–Medium |

---

## 1. Persistent state vs ephemeral filesystem

### What happens
Railway containers have an ephemeral overlay filesystem. Anything written outside a
mounted volume is lost on redeploy and on restart.

### Evidence (exact files)
- **`.dockerignore:21-24`** — excludes `data/`, `*.db`, `backend.log` from the build
  context. The image ships with **no** `data/` directory and **no** `oracle.db`.
- **`railway.toml`** — declares `[build]` and `[deploy]` only. **No `[[deploy.volumes]]`
  block.** Restart policy is `ON_FAILURE`, `restartPolicyMaxRetries = 10` (`railway.toml:8-9`).
- **`.env.railway:37-38`** — the *only* hint of a volume is a comment:
  `# Railway volume mount path for persistent broker state` /
  `PAPER_TRADING_DATA_DIR=/app/data/paper_trading`. Nothing actually mounts it.
- **`Dockerfile:13`** — `WORKDIR /app`. All relative `data/agentic` paths resolve to
  `/app/data/agentic`. A volume mounted at `/app/data` would cover them.
- **`src/config.py:8`** — `database_url: str = "sqlite:///./oracle.db"`. If `DATABASE_URL`
  is not set on Railway, SQLite lands on the ephemeral FS.
- **`src/db/session.py:9-22`** — engine built directly from `settings.database_url`.
- **`src/main.py:1541`** — `Base.metadata.create_all(bind=engine, checkfirst=True)`.
  The comment says *"preserves data across restarts"* — true **only if the DB file
  itself persists**, which it does not without a volume or external Postgres.

### Path-resolution inconsistency (latent footgun)
About half the state modules honor an `AGENTIC_DATA_DIR` override; the other half
hardcode `Path("data/agentic")`:

- **Honor `AGENTIC_DATA_DIR`:** `news_momentum_orchestrator.py:87`,
  `telegram_outbox.py:21`, `news_momentum_telegram_learning.py:28`,
  `calibration_provider.py:26`, `news_impact_learning.py:31`,
  `telegram_command_handler.py:30`, `quality_separator.py:13`,
  `news_alert_latency_trace.py:17`, `historical_*`.
- **Hardcoded `Path("data/agentic")` (ignore the env var):** `company_name_resolver.py:30`,
  `feature_flags.py:23`, `news_momentum_ml_engine.py:42`,
  `news_momentum_big_winner_model.py:30`, `news_momentum_nlp_classifier.py:24`,
  `news_momentum_shadow_logger.py:31`, `pre_news_detector.py:93`,
  `news_momentum_winners.py:36`, `sec_intelligence_orchestrator.py:58`, others.
- **Module-relative:** `ml_advisory.py:84` (`Path(__file__).../data/agentic`).

**Implication:** With the default (env var unset) and a volume at `/app/data`,
everything lands consistently at `/app/data/agentic` and works. But if an operator
sets `AGENTIC_DATA_DIR=/data/agentic` to relocate state onto a volume mounted elsewhere,
**only half the modules follow** — producing split-brain state (dedup on the volume,
ML models on ephemeral, etc.). This makes the "obvious" relocation fix dangerous.

### Risks
- **Total state loss on every redeploy/crash** (no volume) — see sections 2–6 for blast radius.
- **Split-brain state** if `AGENTIC_DATA_DIR` is used to relocate (the hardcoded modules won't follow).
- **SQLite signals/watchlist** lost per restart if `DATABASE_URL` is unset.

### Recommended fixes
1. **Attach a Railway volume mounted at `/app/data`** (covers both the env-var-honoring
   and hardcoded modules, since both resolve relative to `/app`). Verify it is large
   enough — see the 166 MB `news_momentum_shadow_alerts.json.166MB-bak` artifact already
   present locally; shadow/jsonl logs grow unbounded.
2. **Provision Postgres** and set `DATABASE_URL` (already auto-injected by Railway if a
   Postgres service is added — see `.env.railway:1-3`). Do not rely on SQLite-on-volume
   for the relational store.
3. **Unify path resolution:** make every module derive its data dir from a single helper
   (e.g. `src/config.py` `agentic_data_dir`) that reads `AGENTIC_DATA_DIR` once. This
   removes the split-brain risk and makes relocation safe. *(Code change — deferred.)*
4. **Fail-fast guard:** at startup, if `APP_ENV=production` and the data dir is not on a
   mounted volume (e.g. detect a sentinel file or check the mount), log a loud warning.
   *(Code change — deferred.)*

---

## 2. Processed-headline / duplicate registry durability

### Mechanism
Duplicate suppression is layered across four in-memory dicts, each persisted to JSON:

- **`news_momentum_orchestrator.py:284`** `EVENT_REGISTRY_FILE = news_momentum_event_registry.json`
  — cross-source velocity + duplicate detection. Cleaned to `max(velocity_window, 2h)`
  (`_clean_event_registry`, `:959-978`). Duplicate check uses an 80% headline-similarity
  match within 2h (`_check_duplicate`, `:982-999`).
- **`:283`** `HEADLINE_COOLDOWN_FILE = news_momentum_headline_cooldowns.json` — per
  `(ticker, headline_hash)` cooldown, 4h window (gate at `:1883-1889`).
- **`:282`** `COOLDOWN_FILE = news_momentum_cooldowns.json` — per-ticker cooldown
  (`telegram_cooldown_minutes`, default **1080 min / 18h**, gate at `:1876-1881`).
- **`:285`** `ALERT_MEMORY_FILE = news_momentum_alert_memory.json` — durable
  `(ticker, headline)` → `sent_at` record; suppression window `max(18h, news_max_age)`
  (gate at `:1891-1905`).

### Durability mitigation already present
`_hydrate_cooldowns_from_alert_history` (`:639-690`) explicitly rebuilds ticker/headline
cooldowns from `alert_memory` and the Telegram learning alert log on startup. The
docstring calls out Railway: *"second line of defence for Railway redeploys/crashes where
the explicit cooldown files are missing, empty, or stale."*

### The gap
**Every one of these files lives under `data/agentic/`.** With no volume:
- All four registries start **empty** on each boot.
- `_hydrate_cooldowns_from_alert_history` reads `alert_memory` and the learning log —
  **also wiped** — so it hydrates nothing.

Result: after a redeploy, the same headlines re-ingested from the RSS/SEC loops are seen
as brand-new (no event-registry match, no cooldown, no memory) and re-alert. The 2h
event-registry window and 4h headline cooldown only protect *within a single
container lifetime*.

### Risks
- **Duplicate-alert storm** on every redeploy for all headlines still inside the freshness
  window (see §6 for the exact window math).
- Cross-source velocity scoring resets (first source after restart looks like a fresh
  single-source event), perturbing `velocity_score`-gated paths (`:1917`).

### Recommended fixes
1. Same volume as §1 makes all four registries durable and makes the existing
   hydration logic effective — **this is the single highest-leverage fix.**
2. Consider persisting the dedup keys to the relational DB (Postgres) instead of JSON so
   they survive even without a file volume. *(Code change — deferred.)*
3. Confirm `_hydrate_cooldowns_from_alert_history` is exercised by a test that simulates
   "cooldown files deleted, alert_memory intact" to lock in the mitigation. *(Test — deferred.)*

---

## 3. Telegram outbox durability

### Mechanism
- **`src/services/telegram_outbox.py:21-22`** —
  `OUTBOX_FILE = data/agentic/telegram_outbox.jsonl` (honors `AGENTIC_DATA_DIR`).
- Writes are **atomic and durable within a lifetime**: `save_outbox` (`:115-133`) writes
  a temp file, `flush()` + `os.fsync()`, then `os.replace()`. This is correct, robust code.
- A background drain loop retries pending/failed entries with exponential backoff
  (`telegram_outbox_sender_loop`, `telegram_service.py:266-277`; started at
  `main.py:1576`).

### The gaps
1. **Ephemeral FS defeats the outbox's entire purpose.** The outbox exists so a transient
   Telegram/network failure does not drop an approved alert. But a **pending** entry
   (failed send awaiting retry) sits only in `telegram_outbox.jsonl`. If the container
   restarts before the retry succeeds, the queued alert is **silently lost** — exactly
   the failure the outbox was built to prevent. `fsync` guarantees durability against
   *process* crashes, **not** against Railway tearing down the filesystem.
2. **The outbox is failure-only.** `send_telegram_alert` (`telegram_service.py:159-174`)
   enqueues **only when the live send fails**. Successful sends are *not* recorded in the
   outbox — their dedup lives in `alert_memory` (§2). So the outbox is a *retry queue*,
   not a *sent-ledger*; it cannot help reconstruct "what did we already send" after a wipe.
3. `MAX_ATTEMPTS` default 6 (`telegram_outbox.py:23`); after that an entry becomes
   `dead_letter` and is retained in the file but never retried — fine, but also lost on wipe.

### Risks
- **Dropped alerts** whenever a restart coincides with a pending retry (most likely during
  a Telegram outage or rate-limit — precisely when retries are queued).
- No cross-restart visibility into dead-lettered alerts for ops review.

### Recommended fixes
1. Volume (per §1) makes the outbox genuinely durable — the drain loop will pick up
   pending entries after a restart.
2. Optionally back the outbox with Postgres so it survives even without a file volume.
   *(Code change — deferred.)*
3. Consider emitting a startup log of `pending`/`dead_letter` counts so operators notice
   stuck alerts after a deploy. *(Code change — deferred.)*

---

## 4. Model artifact persistence

### Artifacts (exact paths)
- **`news_momentum_ml_engine.py:42-43`** — `news_momentum_ml_model.joblib` (main alert ranker).
- **`news_momentum_big_winner_model.py:30-31`** — `news_momentum_big_winner_model.joblib`.
- **`news_momentum_nlp_classifier.py:24-25`** — `news_momentum_nlp_model.joblib`.
- **`rocket_model_shadow.py:29` / `rocket_catboost_baseline.py:44`** —
  `rocket_catboost_baseline_shadow.joblib`.
- Companion `*_meta.json` calibration files in the same dir.

All hardcode `Path("data/agentic")` (do **not** honor `AGENTIC_DATA_DIR`).

### The gaps
1. **`.gitignore:21` excludes `*.joblib`** → models are not in the repo.
2. **`.dockerignore` excludes `data/`** → models are not in the image.
3. Therefore the container **always starts with no model files**, regardless of volume.
   Load failures are handled gracefully (e.g. `orchestrator __init__` wraps
   `self._ml_engine.load()` in try/except, `:329-332`), so the app boots — but it boots
   into a **cold, unscored state** until a retrain runs.
4. Retraining is **weekly** (`_news_momentum_ml_retrain_loop`, Sun 02:00 UTC per CLAUDE.md).
   Without a volume, **every redeploy throws away the trained model and ML-percentile
   calibration** (`_calibrate_ml_percentiles`, `:387-399`), and the system runs ungated/
   default-gated until the next weekly cycle — up to ~7 days of degraded scoring.

### Risks
- **Loss of learned model weights and percentile calibration on every deploy.** Because the
  ML gate influences which alerts fire, this silently changes alert quality/volume after
  each deploy.
- First-ever production boot has no model at all (expected, but worth documenting as the
  baseline behavior).

### Recommended fixes
1. Volume at `/app/data` persists the joblib + meta files across deploys — primary fix.
2. **Seed an initial model into the image** (or pull from object storage on boot) so the
   first boot and post-wipe boots are not cold. Since `.dockerignore`/`.gitignore` exclude
   them, this needs an explicit carve-out (e.g. ship a `models/seed/` baseline that is
   copied to the data dir if absent). *(Build/code change — deferred.)*
3. Unify these hardcoded paths through the same data-dir helper as §1.4 so models follow a
   relocated `AGENTIC_DATA_DIR`. *(Code change — deferred.)*

---

## 5. Ticker-resolution false-match risk

Two distinct resolution surfaces; neither depends on the volume, so these risks exist
regardless of the persistence decision.

### A. Company-name → ticker (`src/core/company_name_resolver.py`)
- Builds a `{normalized_name: ticker}` map from SEC `company_tickers.json`, cached to
  `company_name_ticker_map.json` (`:30-34`).
- **Conservative core:** exact normalized-name match only (`:118-121`); "first ticker wins"
  for a normalized name (`:90-92`).
- **False-match surface — the prefix fallback (`:122-131`):** when an exact match fails it
  tries the **leading 3-word then 2-word prefix**. This can mis-attribute a headline:
  e.g. a name normalizing to `apple hospitality` could fall back to the `apple` prefix and
  resolve to **AAPL** if `apple` exists as a key; any "First Word + descriptor" company can
  collide with a larger issuer that registered under the bare prefix. The 2-word fallback in
  particular is broad.
- **Cold-start network dependency (`:79-101`):** if the cache is missing (post-wipe) and the
  SEC fetch fails/ratelimits, the map is empty → `resolve()` returns `None` for everything
  → all name-only headlines are dropped. Fail-safe (no false alert) but a **silent coverage
  gap** until SEC succeeds. The cache also hardcodes `Path("data/agentic")` (§1.4).

### B. Symbol extraction from headlines/URLs (`src/core/news_ticker_extractor.py`)
- Generally conservative: prefers exchange-prefixed (`NASDAQ: ABCD`), cashtags (`$ABCD`),
  and URL path tickers, with a `SKIP_TICKERS` denylist (`:12-16`).
- **Looser patterns that can false-match:**
  - `DASH_SUFFIX_RE` (`:30`) — grabs a trailing `… - WORD`, which can capture a non-ticker
    uppercase word at the end of a title.
  - `PLAIN_PARENS_RE` (`:35`, gated behind `include_plain_parens`) — any `(XYZ)` 2–6 caps,
    only partially protected by `SKIP_TICKERS`.
  - `TITLE_SUFFIX_RE` / `QUOTED_SYMBOL_RE` are tighter and lower-risk.

### Risks
- **Wrong-ticker alerts** (alerting/scoring the wrong company) from the 2-word prefix
  fallback or the dash/parens extractors — a correctness bug, not just noise, because a
  false ticker can drive a Telegram alert and ML training labels.
- **Coverage gaps** after a wipe until the SEC name map rebuilds.

### Recommended fixes
1. **Tighten the prefix fallback:** require the prefix to be an *unambiguous* unique mapping,
   or drop the 2-word fallback and keep only exact + full-name matches. Add a confidence
   flag so prefix-resolved tickers can be gated more strictly. *(Code change — deferred.)*
2. **Ship/seed the `company_name_ticker_map.json`** in the image (or on a volume) so cold
   starts are not coverage-blind and don't hammer SEC. *(Build change — deferred.)*
3. Add regression fixtures asserting known false-match pairs do **not** resolve (e.g.
   `Apple Hospitality REIT` ≠ `AAPL`). *(Test — deferred.)*
4. Re-confirm where `include_plain_parens=True` is passed; restrict it to sources whose
   parenthesized symbols are reliably tickers. *(Code change — deferred.)*

---

## 6. Freshness filters after restart

### The relevant windows (`src/core/agentic/news_momentum_models.py`)
- `news_max_age_hours = 12.0` (`:862`)
- `telegram_cooldown_minutes = 1080` (**18h**, `:834`) — the comment notes 18h > 12h is
  what *guarantees one alert per headline within the freshness window*.
- `first_mover_max_age_seconds = 300` (`:926`); `velocity_time_window_seconds = 300` (`:812`).

### The gates (`news_momentum_orchestrator.py`)
- **`detected_at` stale guard:** drop if candidate age > 24h (`:1912-1920`), with an
  exception for aggressive-refresh / high velocity.
- **`published_at` stale guard:** drop if `published_at` age > `news_max_age_hours` (12h)
  (`:1922-1931`).
- Candidate pruning at 48h / cap 500 (`_prune_old_candidates`, `:749`).

### The restart interaction (core risk)
`detected_at` is the moment **Oracle first ingested** the headline. After a wipe:
- The dedup registry, cooldowns, and alert_memory are empty (§2), so suppression is gone.
- The RSS/SEC loops re-fetch current headlines and assign a **fresh `detected_at = now`**,
  so the 24h `detected_at` guard does **not** filter them.
- The **only** remaining brake is the `published_at` ≤ 12h guard. Therefore **any headline
  published within the last 12 hours re-alerts after a redeploy**, because:
  - it passes the 12h published-age gate,
  - it has no ticker cooldown (18h window — but the record is gone),
  - it has no headline cooldown / alert_memory (gone),
  - it has no event-registry duplicate match (gone).

The carefully chosen `18h cooldown > 12h freshness` invariant only holds **as long as the
cooldown file survives** — which it does not on Railway without a volume.

### Risks
- **Re-alert storm of up to 12h of headlines** on every redeploy. A midday deploy can
  re-blast the morning's entire catalyst set to Telegram.
- High-velocity items can additionally bypass even the 24h `detected_at` guard
  (`velocity_score >= 8`, `:1917`), making them the most likely to double-fire.

### Recommended fixes
1. Volume (§1) — restores cooldown/memory/registry durability, which is what the
   freshness/cooldown invariant actually relies on. Primary fix.
2. **Defense-in-depth (code, deferred):** on startup, seed a short "post-restart quiet
   window" or treat re-ingested headlines whose `published_at` predates process start as
   suppressed-by-default unless cooldown state confirms they were never sent. This makes the
   system safe even if a volume is mis-configured.
3. Verify `_hydrate_cooldowns_from_alert_history` runs **before** the first
   `_news_momentum_scan_loop` iteration so hydration wins the race against re-ingestion
   (it is called in `__init__`, `:320`; confirm orchestrator construction precedes loop
   start in `main.py` lifespan). *(Verification — deferred.)*

---

## Consolidated remediation priority

| Priority | Action | Type | Addresses |
|----------|--------|------|-----------|
| **P0** | Attach a Railway **volume at `/app/data`** | Config (dashboard) | §1, §2, §3, §4, §6 |
| **P0** | Provision **Postgres** + set `DATABASE_URL` | Config (dashboard) | §1 (relational store) |
| **P1** | Seed baseline **ML model + name-map** into image/volume | Build | §4, §5 cold-start |
| **P1** | Tighten **company-name prefix fallback** + add false-match tests | Code/Test | §5 |
| **P2** | Unify all data-dir paths through one `AGENTIC_DATA_DIR` helper | Code | §1 split-brain, §4 |
| **P2** | Startup **fail-fast/warn** if prod data dir is not on a volume | Code | §1 |
| **P2** | Post-restart **freshness quiet-window** defense-in-depth | Code | §6 |
| **P3** | Back outbox/dedup keys with Postgres for volume-independent durability | Code | §2, §3 |
| **P3** | Startup log of outbox `pending`/`dead_letter` counts | Code | §3 |

### Important nuance on the volume
Because `WORKDIR=/app` and the default data path resolves to `/app/data/agentic` for
**both** env-var-honoring and hardcoded modules, a single volume at **`/app/data`** (with
`AGENTIC_DATA_DIR` left **unset**) is sufficient and consistent. Do **not** set
`AGENTIC_DATA_DIR` to a different mount without first unifying path resolution (§1.4 /
P2) — half the modules would ignore it and split state across volume and ephemeral FS.

---

## Appendix: minor / adjacent observations (not in the 6 focus areas)

- **Healthcheck:** `railway.toml:6` uses `healthcheckPath = "/health"`; the route is
  defined unprefixed in `src/api/routes/health.py:10`. Confirm it is mounted without the
  `/api/v1` prefix so the healthcheck resolves.
- **Restart cap:** `restartPolicyMaxRetries = 10` (`railway.toml:9`) — after 10 crash-loops
  Railway stops restarting. Combined with cold-start model loads and network-dependent SEC
  fetches, ensure startup degrades gracefully (it largely does via try/except wrappers).
- **Unbounded log growth:** shadow/jsonl artifacts (`news_momentum_shadow_alerts.json`,
  the existing `*.166MB-bak`, `rocket_model_shadow_predictions.jsonl`,
  `news_alert_latency_trace.jsonl`) grow without rotation; size the volume accordingly and
  consider retention/rotation. *(Code change — deferred.)*
- **`.env` in build context:** `.env` exists in the repo dir; `.dockerignore:18` excludes
  `.env`/`.env.railway`, which is correct. Confirm secrets are set as Railway variables,
  not baked into the image.
