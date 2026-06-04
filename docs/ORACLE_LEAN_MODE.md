# Oracle Lean Mode

Oracle Lean Mode safely disables legacy runtime systems without deleting files or permanently removing imports.

## Purpose

Lean Mode keeps the strategic Oracle platform enabled:

- News Momentum
- Pre-News anomaly detection
- Rocket Runner / Agentic mode
- SEC / dilution intelligence
- Telegram alerts and command polling
- Market data providers
- News Momentum outcome resolver
- News Momentum learning and ML retraining loops

Lean Mode disables legacy systems by default when `ORACLE_LEAN_MODE=true`.

## Backend Environment Variables

Set this in `.env` to enable lean mode:

```env
ORACLE_LEAN_MODE=true
```

When lean mode is enabled, these legacy systems default to disabled:

```env
ENABLE_LEGACY_SIGNALS=false
ENABLE_DIP_BOUNCE=false
ENABLE_SCANNER_ROUTES=false
ENABLE_WATCHLIST=false
ENABLE_PAPER_TRADING=false
ENABLE_BACKTEST=false
ENABLE_ANALYSIS_ROUTES=false
ENABLE_INTELLIGENCE_ROUTES=false
ENABLE_HTF_ROUTES=false
ENABLE_LEGACY_OUTCOME_SIMULATOR=false
```

When `ORACLE_LEAN_MODE=false` or unset, the legacy systems default to the current behavior: enabled.

## Per-System Overrides

Any legacy system can be re-enabled explicitly while lean mode is on:

```env
ORACLE_LEAN_MODE=true
ENABLE_WATCHLIST=true
ENABLE_PAPER_TRADING=true
```

Explicit `ENABLE_*` values always override the lean-mode default.

## Systems Disabled In Lean Mode

- Legacy signal routes
- Dip/bounce model routes
- Scanner routes
- Watchlist API route
- Watchlist WebSocket
- Watchlist real-time broadcaster loop
- Paper trading API route
- Paper trading price updater loop
- Backtest route
- Analysis routes
- Intelligence routes
- HTF scanner route
- Legacy outcome simulator loop
- Legacy signals WebSocket

## Systems Still Enabled In Lean Mode

- `/api/v1/news-momentum/*`
- `/api/v1/agentic/*`
- `/api/v1/agentic/pre-news/*`
- `/api/v1/sec-intelligence/*`
- `/api/v1/agentic/training/historical/*`
- `/api/v1/news/*`
- `/health`
- Telegram command polling
- Alpaca real-time news stream when credentials/SDK are available
- News Momentum scan loop
- SEC EDGAR 8-K firehose loop
- Pre-News scan loop
- News Momentum EOD review loop
- News Momentum outcome resolver loop
- News Momentum ML retrain loop

## Frontend Lean Mode

The frontend uses Vite environment variables. Prefix variables with `VITE_`.

Enable lean navigation:

```env
VITE_ORACLE_LEAN_MODE=true
```

Optional frontend overrides:

```env
VITE_ENABLE_ANALYSIS_ROUTES=true
VITE_ENABLE_BACKTEST=true
VITE_ENABLE_INTELLIGENCE_ROUTES=true
VITE_ENABLE_PAPER_TRADING=true
VITE_ENABLE_WATCHLIST=true
```

In lean mode, the frontend hides legacy navigation items and redirects `/` to `/news-momentum`.

## Startup Logging

At backend startup, Oracle logs:

- whether lean mode is enabled
- systems enabled
- systems disabled

Example:

```text
Oracle lean mode: enabled
Oracle systems enabled: learning_loops, market_data, news_momentum, outcome_resolver, pre_news, rocket_runner, sec_intelligence, telegram
Oracle systems disabled: analysis_routes, backtest, dip_bounce, htf_routes, intelligence_routes, legacy_outcome_simulator, legacy_signals, paper_trading, scanner_routes, watchlist
```

## Rollback

To return to legacy/current behavior:

```env
ORACLE_LEAN_MODE=false
VITE_ORACLE_LEAN_MODE=false
```

Then restart the backend and rebuild/restart the frontend.

## Verification Checklist

After enabling lean mode:

- `/health` works.
- `/api/v1/news-momentum/candidates` works.
- `/api/v1/sec-intelligence/stats` works.
- `/api/v1/agentic/pre-news/anomalies` works.
- Telegram command polling starts.
- News Momentum scan loop starts.
- Pre-News scan loop starts.
- SEC EDGAR firehose starts.
- Watchlist broadcaster does not start.
- Paper trading price updater does not start.
- Legacy outcome simulator does not start.
