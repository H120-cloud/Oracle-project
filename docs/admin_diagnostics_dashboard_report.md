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
