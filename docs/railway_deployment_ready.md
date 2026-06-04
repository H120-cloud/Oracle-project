# Railway Deployment Checklist

This repository is configured to deploy Oracle as a single Railway backend service with the built React frontend served by FastAPI.

## Before Pushing To GitHub

- Do not commit `.env`, `.env.local`, or personal `.env.*` files.
- `.env.railway` is a reference template only. Real secrets must be entered in Railway Dashboard > Variables.
- Rotate any API keys that were previously pasted into local files or chat before pushing.

## Railway Service Settings

The repo includes:

- `Dockerfile` for backend + frontend build
- `railway.toml` with a Uvicorn start command
- healthcheck path: `/health`

Railway must run the app on the provided `PORT`. Current start command:

```bash
uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Required Railway Variables

Set these in Railway Dashboard > Variables:

```env
APP_ENV=production
APP_DEBUG=false
ORACLE_LEAN_MODE=true
DATABASE_URL=<Railway Postgres DATABASE_URL>
TELEGRAM_BOT_TOKEN=<your Telegram bot token>
TELEGRAM_CHAT_ID=<your Telegram chat id>
ALPACA_API_KEY=<your rotated Alpaca key>
ALPACA_SECRET_KEY=<your rotated Alpaca secret>
ALPACA_DATA_FEED=iex
MARKET_DATA_PROVIDER=alpaca
POLYGON_API_KEY=<your rotated Polygon key>
POLYGON_REQUESTS_PER_MINUTE=5
SEC_FIREHOSE_ENABLED=true
PAPER_TRADING_ENABLED=false
PAPER_TRADING_USE_ALPACA=false
```

Optional:

```env
FINNHUB_API_KEY=<optional fallback provider key>
ALPHAVANTAGE_API_KEY=<optional fallback provider key>
```

## Persistent Volume

Attach a Railway volume to the service with mount path:

```text
/app/data
```

Oracle writes runtime state under `./data`, including:

- Telegram outbox
- News Momentum candidates and cooldowns
- Rocket shadow predictions
- SEC cache
- Pre-News validation and anomaly state
- learning/outcome files

Without a volume, this state is lost on redeploy/restart.

## Deployment Notes

- Use a single replica/service unless shared-state locking is added. Multiple replicas can duplicate Telegram alerts and race on JSONL state files.
- Keep `ORACLE_LEAN_MODE=true` for the Railway deployment.
- Do not run historical Rocket enrichment or ML training on the same always-on alert service unless intentionally scheduled as a separate Railway job.
- Watch initial deploy logs for:
  - `Application startup complete`
  - `News Momentum Intelligence System initialized`
  - `Telegram outbox sender started`
  - `SEC EDGAR 8-K firehose started`
  - `Alpaca real-time news stream started` or a clear credentials/SDK fallback message

## Quick Smoke Checks After Deploy

Open:

```text
https://<your-railway-domain>/health
```

Expected:

```json
{"status":"ok","version":"5.0.0","phase":"V5"}
```

Then confirm Telegram receives the next qualifying alert or health warning. Do not test by changing production gating.
