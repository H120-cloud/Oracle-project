# Oracle Admin Diagnostics Dashboard — Implementation Report

**Date:** 2026-06-05
**Type:** Observability / diagnostics only — **read-only**.
**Invariant honored:** No changes to News Momentum scoring, Pre-News scoring, Rocket
CatBoost scoring, Telegram alert gating, or any production alert decision. This feature
only *reads* existing diagnostics artifacts and renders them.

---

## Summary

A read-only admin dashboard that explains **why alerts are delayed, blocked, missed,
retried, or ranked**. It parses three append-only JSONL artifacts already produced by the
pipeline and exposes them through filtered, paginated, derived API views plus a React
dashboard with tables, charts, summary cards, and CSV export.

- **6 GET endpoints** under `/api/v1/admin/*` (3 required + 3 optional), all verified GET-only.
- **1 frontend page** (`Diagnostics`) with **6 tabs**, sortable/filterable/paginated tables, CSV export, recharts visualizations, summary cards, and top-10 lists.
- **18 new backend tests**; full suite **474 passed, 1 xfailed** (pre-existing). Frontend production build succeeds.

---

## Files changed

### Backend (new)
| File | Purpose |
|------|---------|
| `src/services/admin_diagnostics.py` | Read-only service layer: load/filter/paginate/derive over the 3 JSONL artifacts. Pure functions, `path`-injectable for tests. **Never writes.** |
| `src/api/routes/admin_diagnostics.py` | `APIRouter(prefix="/admin")` — 6 GET endpoints, shared query params (ticker / source / status / date-range / pagination). |
| `tests/unit/test_admin_diagnostics.py` | 13 service tests + 5 route tests (incl. read-only 405 assertions). |

### Backend (modified)
| File | Change |
|------|--------|
| `src/main.py` | Import `admin_diagnostics` and `app.include_router(admin_diagnostics.router, prefix="/api/v1")`. (2 lines.) |

### Frontend (new)
| File | Purpose |
|------|---------|
| `frontend/src/api_admin.js` | Read-only API client (6 functions, query-string builder, reuses `fetchJSON` + bearer auth). |
| `frontend/src/pages/Diagnostics.jsx` | The dashboard: tabs, generic sortable table, filter bar, pagination, CSV export, charts, cards, top-10 lists. |

### Frontend (modified)
| File | Change |
|------|--------|
| `frontend/src/App.jsx` | Add `Diagnostics` import, `/diagnostics` route, and a `Gauge` nav entry. |
| `frontend/src/index.css` | Add two additive component classes (`.input`, `.btn-ghost`). |

---

## Endpoints added

All under `/api/v1/admin/`, all **GET**, all supporting `ticker`, `source`,
`status`, `start`, `end`, `page`, `page_size` (where applicable).

| Endpoint | Source artifact | Returns |
|----------|-----------------|---------|
| `GET /admin/news-latency` | `news_alert_latency_trace.jsonl` | items (+`derived` latencies, `status`, `blocked_category`, flags), `summary`, `charts` |
| `GET /admin/rocket-shadow` | `rocket_model_shadow_predictions.jsonl` | items (+`rule_score`, `catboost_rank`, `rule_rank`), `views`, `comparison`, `summary` |
| `GET /admin/telegram-outbox` | `telegram_outbox.jsonl` | items (+`send_latency_seconds`), `summary` (counts, success rate, retries, avg latency) |
| `GET /admin/source-health` *(optional)* | latency trace | per-source totals/alerted/delayed/blocked/fast-watch/avg-latency |
| `GET /admin/blocked-alerts` *(optional)* | latency trace | latency items filtered to blocked, with sub-category filter |
| `GET /admin/fast-watch-alerts` *(optional)* | latency trace | latency items filtered to `fast_path` |

### News latency — derived metrics & highlighting
Per row the service derives: `source_fetch_latency_seconds` (published→fetched),
`classification_latency_seconds` (fetched→classified), `gate_latency_seconds`
(classified→gate), `telegram_latency_seconds` (gate→sent/enqueue), and
`total_latency_seconds`. It classifies each row into a `status`
(`alerted`/`delayed`/`blocked`) and a `blocked_category`
(`duplicate` / `freshness` / `unresolved_ticker` / `cooldown` / `ml_veto` / `other`),
and exposes `is_delayed` (>60s), `is_blocked`, `is_fast_watch`. Status filters include
`delayed`, `blocked`, `duplicate_blocked`, `freshness_blocked`, `unresolved_ticker`.

### Rocket shadow — comparison
`rule_score` = mean(`expected_return_score`, `news_impact_score`). The service ranks rows
by CatBoost (`rocket_rank_score` → `catboost_rank`) and by the rule signal (`rule_rank`),
and surfaces divergences: `catboost_high_rules_low` and `rules_high_catboost_low`, plus
`views`: `top_rank`, `highest_monster`, `highest_major`, `highest_confidence`.

### Telegram outbox — metrics
`summary` includes `pending`, `sent`, `retrying`, `failed`, `dead_letter`, `success_rate`,
`total_retries`, `average_send_latency_seconds` (created_at → telegram_response date).

---

## Frontend pages added

**Admin → Diagnostics** (`/diagnostics`) with tabs:

1. **News Latency** — columns Time / Ticker / Headline / Source / Latency / Status / Blocked Reason; color-coded status (green = alerted, yellow = delayed, red = blocked); summary cards; charts: *alerts by source*, *avg latency by source*, *blocked reason distribution*.
2. **Rocket Shadow** — columns Ticker / Runner % / Major % / Monster % / Rank Score / Rule Score / Confidence; Top-10 Monster / Major / Rank lists.
3. **Telegram Outbox** — columns Alert / Ticker / Status / Attempts / Last Error / Created / Next Retry; summary cards Pending / Sent / Retrying / Failed / Dead Letter / Success Rate.
4. **Source Health** *(optional)* — per-source aggregate table.
5. **Blocked Alerts** *(optional)* — blocked-only latency view with sub-category filter.
6. **FAST WATCH** *(optional)* — `fast_path`-only latency view.

Every table supports **filtering** (server-side: ticker / status / source / date range), **sorting** (click column headers), **pagination** (server-side page/page_size), and **CSV export** (current sorted view).

### Usage notes
- Reachable from the left sidebar (**Diagnostics**, gauge icon). Inherits the existing
  `FrontendAuthGate` / bearer-token auth used by all `/api/v1` calls.
- Date filters use `datetime-local` inputs converted to ISO8601 before querying.
- Charts render with the project's existing **recharts** dependency (no new deps added).
- `telegram_outbox.jsonl` only exists once a send has failed (it is a retry queue), so the
  Outbox tab is empty until a transient Telegram/network failure occurs — expected.

---

## Security

- All 6 endpoints are **GET-only** — verified programmatically against the live app
  (`assert all(methods == ['GET'])`). No POST/PUT/PATCH/DELETE exist; route tests assert
  `POST`/`DELETE` return **405**.
- The service module has no write path: it opens artifacts read-only and never imports or
  calls scoring/gating/model code. It reuses only timestamp helpers
  (`aware_utc`, `seconds_between`) and the data-dir helper.
- No model or alert state can be modified through this feature.

---

## Tests passed

| Suite | Result |
|-------|--------|
| `tests/unit/test_admin_diagnostics.py` (new) | **18 passed** |
| Full backend suite (`python -m pytest`) | **474 passed, 1 xfailed** |
| Lean startup (`test_oracle_lean_mode.py`) | 13 passed |
| News Momentum (alert flow + obsolescence + dedup) | 41 passed |
| Pre-News (validation + bridge + alert audit) | 6 passed |
| Rocket Shadow (`test_rocket_model_shadow.py` + ticker integrity) | 7 passed |
| `python -m compileall src` | exit 0 |
| App import + admin route registration | OK (6 GET-only endpoints) |
| Frontend `npm run build` | ✓ built (2377 modules, ~15s) |

The single `xfailed` is the pre-existing P1 semantic-classifier target, unrelated to this work.

---

## Performance impact

- **Hot path: zero.** Nothing in this feature runs in the scan / scoring / gating /
  Telegram loops. The endpoints are pulled on-demand by the admin UI only.
- **Per-request cost:** each reader does one sequential read of its JSONL artifact, an
  O(n) filter/derive pass, then in-memory pagination. The artifacts are small
  (latency trace and shadow predictions are KB-scale; outbox is empty until a failure).
- **No new backend dependencies.** Frontend reuses the existing `recharts`.
- **Note / future hardening:** readers parse the whole file per request (no cache, no tail
  limit). If `news_alert_latency_trace.jsonl` grows large over time, add a tail/`mtime`
  cache — this is a read-only optimization and does not affect production logic. The
  Vite "chunk > 500 kB" warning is pre-existing (single-bundle app), not introduced here.

---

## What was explicitly NOT changed
- No edits to News Momentum / Pre-News / Rocket scoring modules.
- No edits to Telegram gating (`_should_send_telegram_impl`, outbox send logic).
- No new write/delete endpoints; no mutation of alerts, models, or state files.

---

## Addendum — Report Download Feature

Adds easy, read-only report/data downloads to the dashboard.

### Endpoints added (all GET, read-only)
| Endpoint | Purpose |
|----------|---------|
| `GET /admin/download/news-latency?format=csv\|jsonl\|json` | Export the filtered news-latency dataset |
| `GET /admin/download/rocket-shadow?format=…` | Export the filtered Rocket-shadow dataset |
| `GET /admin/download/telegram-outbox?format=…` | Export the filtered Telegram-outbox dataset |
| `GET /admin/reports` | List allowlisted report files + metadata (name, type, size, last_modified, exists) |
| `GET /admin/download/report/{report_name}` | Download one **allowlisted** report file (native CSV/JSONL/Markdown) |

The data-export endpoints accept the same filters as their list counterparts
(`ticker`, `source`, `status`, `start`, `end`), so a download reflects the
current view. CSV flattens nested fields (`derived.*` → `derived_*`, lists → JSON
text). Total now: **11 GET-only admin endpoints** (verified programmatically).

### Allowlist + path-traversal defense (`src/services/admin_diagnostics.py`)
- `report_files()` is a hardcoded allowlist keyed by **plain basename** (no path
  separators): the 3 JSONL artifacts + 5 `docs/*.md` reports named in the spec.
- The download route uses a non-greedy `{report_name}` param, so any value
  containing `/` (i.e. every traversal attempt) fails to match the route. The
  allowlist membership check is the primary defense — a name not an exact key
  returns **404**, regardless of encoding.
- Allowlisted-but-not-yet-generated reports return **404 "Report not generated yet"**.
- `docs_dir()` is a seam so tests can point the docs root at a temp dir.

### Frontend
- **Download buttons** on News Latency / Rocket Shadow / Telegram Outbox tabs:
  CSV / JSONL / JSON (server-side, full filtered dataset). Implemented as an
  authenticated blob download (`downloadAdminFile`) because the bearer token must
  travel in a header — a plain `<a href>` can't carry it.
- **New "Reports" tab** listing every allowlisted report with name, type,
  last-modified, size, and a Download button (disabled when a report file does
  not exist yet).
- The existing in-table "CSV" button (current page, client-side) is retained
  alongside the new server-side full-dataset downloads.

### Tests (11 new, all passing)
`tests/unit/test_admin_diagnostics.py`: valid report download, invalid report
name → 404, **path traversal → 404/400** (4 encoded variants), allowlisted-but-
missing → 404, CSV export, JSONL download, bad format → 400, reports listing
metadata, and pure `rows_to_csv` / `rows_to_jsonl` / `export_diagnostics`
validation. Backend suite: **485 passed, 1 xfailed**. Frontend build: ✓.

> Frontend note: the project ships no JS test runner (no vitest/jest in
> `package.json`), so "download buttons render correctly" is covered by the
> production build (which compiles/type-checks all JSX) rather than a unit test;
> adding a JS test runner would introduce new devDependencies, out of scope here.
