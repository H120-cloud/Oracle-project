# News Alert Deep Delay Audit

## Scope

This audit looked for hidden paths that could cause Oracle to alert after a stock has already moved, or quietly miss the primary catalyst source and fall back to later recap headlines.

## Confirmed Hidden Risks

### 1. Stale original publication could still alert after refresh

The Telegram gate had a 24-hour stale guard based on `detected_at`, but a candidate can be detected late while the real `published_at` is already old. That allowed refreshed candidates to remain eligible even when the source article was outside the configured `news_max_age_hours` window.

Fix:

- Added a `published_at` stale guard in the Telegram gate.
- Block reason: `stale_published(X.Xh)`.

### 2. Stale active candidates stayed active in persisted state

Local data audit found hundreds of stale unalerted candidates still marked `is_active=True`. `_prune_old_candidates()` always kept active candidates, regardless of article age, and rebuilt `_candidate_by_ticker` using inactive records too.

Risk:

- wasted refresh time
- stale candidates surviving deploy/restart
- inactive records interfering with clean ticker replacement

Fix:

- Prune now deactivates active candidates whose original `published_at` is older than `news_max_age_hours`.
- Prune now excludes inactive candidates from `_candidate_by_ticker`.

### 3. Individual wire-source failures were hidden

`WireNewsScraper` fetches multiple sources under one combined `WireNews` fetch. If BusinessWire failed but another source succeeded, the main loop saw a successful wire fetch and did not know BusinessWire failed.

Fix:

- `WireNewsScraper` now records `failed_sources`.
- The main loop forwards each failed source into `SourceHealthTracker.record_parse_error()`.
- Repeated BusinessWire failures can now trigger admin source-health Telegram warnings.

### 4. Recap headlines had more wording variants than the first FJET fix covered

The first FJET guard blocked wording such as:

- `drives 16% FJET surge`
- `shares surge`
- `jumps after`

The deeper audit found another common form:

- `RECAP stock rises 18% after ...`

Fix:

- Expanded the late-reaction detector to include `rises`, `climbs`, and `advances`, including ticker-first forms like `FJET stock rises`.

## Local Data Audit

Read-only scan of `data/agentic/news_momentum_candidates.json` found:

- 350 persisted candidates
- 6 recap-like move candidates
- 333 stale, unalerted candidates still marked active
- 0 candidates missing `published_at`

The new stale-published gate prevents those stale items from alerting, and the prune/index fix prevents them from staying active across restart cycles.

## Tests Added

- FJET-style recap headline blocked as `late_reaction_headline`.
- `stock rises ... after ...` recap wording blocked as `late_reaction_headline`.
- stale original `published_at` blocked as `stale_published`.
- repeated BusinessWire parse errors surface in source-health evaluation.
- per-source wire failures are reported even when another wire succeeds.
- prune deactivates stale active candidates and excludes inactive records from the ticker index.

## Verification Status

Verified before the final prune/index patch:

- `38 passed` across focused News Momentum, scan-order, timezone, source-health, wire-news, Finviz, and StockTitan tests.

The environment blocked the final Python test run after the prune/index patch due to the local usage-limit reviewer. Run this when available:

```powershell
& 'C:\Users\Husna\AppData\Local\Programs\Python\Python310\python.exe' -m pytest tests\unit\test_news_momentum_alert_flow.py tests\unit\test_news_momentum_scan_order.py tests\unit\test_news_momentum_timezones.py tests\unit\test_source_health.py tests\unit\test_wire_news.py tests\unit\test_finviz_news.py tests\unit\test_stocktitan_news.py -q
```

Then run:

```powershell
& 'C:\Users\Husna\AppData\Local\Programs\Python\Python310\python.exe' -m pytest -q
```
