# Oracle Frontend Telegram Auth

Oracle now protects the frontend with a Telegram one-time-code gate.

## Flow

1. The frontend shows an Oracle Access screen before rendering the dashboard.
2. Clicking `Send code to Telegram` calls `POST /api/v1/auth/request-code`.
3. The backend generates a random six-digit code and sends it to the configured Oracle Telegram chat.
4. The user submits the code to `POST /api/v1/auth/verify-code`.
5. The backend returns a short-lived bearer token.
6. The frontend stores the token in `sessionStorage` and attaches it to strategic API calls.

Codes expire after 5 minutes and can be used once. Closing the browser tab clears the session naturally.

## Protected Routes

The backend rejects unauthenticated requests to `/api/v1/*` except:

- `/api/v1/auth/*`
- `/health`
- `/docs`
- `/openapi.json`
- `/redoc`

This keeps Railway health checks and the login flow available while protecting Oracle data endpoints.

## Environment

Production/Railway:

```env
ORACLE_FRONTEND_AUTH_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Optional local frontend bypass:

```env
VITE_ORACLE_FRONTEND_AUTH_ENABLED=false
```

Do not set the bypass in Railway unless you intentionally want the dashboard open.

## Operational Notes

- Login codes are not stored in the durable Telegram outbox. If Telegram is unavailable, the request fails and the user should request a fresh code later.
- Session tokens are in-memory on the backend. Restarting Railway logs active browser sessions out, which is safer than keeping stale sessions alive.
- The auth layer does not change News Momentum, Pre-News, Telegram alerts, Rocket Shadow scoring, SEC intelligence, or production alert behavior.
