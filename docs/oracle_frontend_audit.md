# Oracle Frontend Audit

## Scope

This audit covers the frontend paths that affect the tool's core purpose:

- keep unauthorized users out of the frontend
- show live News Momentum / Pre-News / SEC / training views
- surface scraper/source-health problems that can cause missed alerts
- remain compatible with Railway deployment

## Current Strategic Pages

The lean frontend entry point is `frontend/src/App.jsx`.

Kept pages:

- News Momentum
- Timing Review
- Agentic / Pre-News
- SEC Intelligence
- Historical Training
- News Feed

Legacy pages were removed from the active route list during the lean refactor.

## Authentication

The app is wrapped by `FrontendAuthGate`.

Backend routes:

- `POST /api/auth/request-code`
- `POST /api/auth/verify-code`
- `GET /api/auth/session`

Important Railway requirement:

- If `ORACLE_FRONTEND_AUTH_ENABLED=true`, `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` must be set.
- If Telegram credentials are missing, the frontend can show the OTP gate but the backend cannot deliver a code.
- Frontend auth also has a build-time flag, `VITE_ORACLE_FRONTEND_AUTH_ENABLED`, so Railway builds should keep that aligned with backend runtime settings.

## Scraper Health Frontend

`frontend/src/pages/News.jsx` renders a `Scraper Health` panel backed by:

- `frontend/src/api_strategic.js::newsMomentumSourceHealth`
- `GET /api/news-momentum/source-health`

The panel shows:

- source status
- tickered headline count
- untickered headline count
- dropped headline count
- missing timestamp count
- parse error count
- average/max source latency

This is the frontend audit view for parser/source failures that can cause missed or late alerts.

## Railway Compatibility Notes

Required behavior:

- Use Railway's injected `PORT`.
- Serve the built frontend from backend static files, or deploy frontend separately with the correct API base URL.
- Keep `ORACLE_LEAN_MODE=true` for strategic-only runtime.
- Keep durable data paths on a Railway volume if Telegram outbox, alert history, or model shadow logs must survive redeploys.

## Remaining Frontend Risks

1. Frontend auth can desync because the UI reads `VITE_ORACLE_FRONTEND_AUTH_ENABLED` at build time while the backend reads `ORACLE_FRONTEND_AUTH_ENABLED` at runtime.
2. The health panel only shows health after backend source-health has collected data during runtime.
3. Browser console messages like `Unchecked runtime.lastError: Could not establish connection` are commonly injected by browser extensions and are not, by themselves, proof the Oracle frontend failed.

## Recommendation

Add a small public runtime config endpoint in a future pass so the frontend can read auth/lean settings from the backend at runtime instead of relying on build-time `VITE_` flags.
