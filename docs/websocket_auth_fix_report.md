# WebSocket Authentication Audit & Fix Report

**Date:** 2026-06-08
**Scope:** Audit the two WebSocket endpoints (`/ws/signals`, `/ws/watchlist`) for
unauthenticated exposure and remediate if active.
**Outcome:** No remediation code required in the deployed configuration. The
endpoints are **disabled in lean mode and unused by the frontend**. A lightweight
regression test was added to lock the posture in. No protected subsystem
(News Momentum, Telegram, Pre-News, Rocket Shadow, scoring) was touched.

---

## 1. Endpoints in scope

Two WebSocket routes exist, both declared inline in `src/main.py`:

| Endpoint | Location | Gating flag |
|----------|----------|-------------|
| `/ws/signals`   | `src/main.py:1817` | `settings.legacy_signals_enabled` |
| `/ws/watchlist` | `src/main.py:1832` | `settings.watchlist_enabled` |

A repo-wide search confirms these are the only WebSocket route declarations
(`@app.websocket` / `@router.websocket`). The Alpaca news stream
(`src/services/alpaca_news_stream.py`) is an outbound client connection, not a
server endpoint, and is out of scope.

## 2. Gating logic

Both endpoints are registered only when their legacy flag is truthy
(`src/main.py:1816` and `:1831`). Those flags resolve through
`Settings._legacy_enabled` (`src/config.py:65`):

```python
def _legacy_enabled(self, value):
    if value is not None:
        return value
    return not self.oracle_lean_mode
```

With no per-flag override, `legacy_signals_enabled` and `watchlist_enabled`
both reduce to `not oracle_lean_mode`. Therefore:

- `ORACLE_LEAN_MODE=true`  → both flags `False` → endpoints **not registered**.
- `ORACLE_LEAN_MODE=false` → both flags `True`  → endpoints **registered**.

## 3. Deployed configuration

- **`.env:51` → `ORACLE_LEAN_MODE=true`.** The deployment runs in lean mode.
- **No per-flag overrides** for `enable_legacy_signals` / `enable_watchlist` exist
  in `.env`, so the lean defaults apply.

## 4. Frontend usage

The strategic News/Rocket frontend does **not** use either WebSocket. A search of
`frontend/src` for `ws/signals`, `ws/watchlist`, `new WebSocket`, `websocket`, and
`wss://` returns **no matches**. The frontend talks to the backend exclusively
over authenticated HTTP (bearer token via `Authorization` header — see
`frontend/src/api_shared.js`).

## 5. Empirical verification

Route registration was confirmed by importing the app under both settings:

```text
# LEAN MODE (as deployed: .env ORACLE_LEAN_MODE=true)
ws routes: NONE

# NON-LEAN (ORACLE_LEAN_MODE=false override)
ws routes: ['/ws/signals', '/ws/watchlist']
```

In the deployed posture there is **no live WebSocket surface** for an attacker to
reach — the routes do not exist on the running app.

## 6. Decision

Per the audit directive: the endpoints are **disabled in `ORACLE_LEAN_MODE=true`
and not used by the strategic frontend**, so this is documented and **not
overbuilt**. No authentication code, connection-handshake changes, or new
middleware were added. Runtime behavior is unchanged.

## 7. Residual / conditional risk

The endpoints are **not deleted** — they re-activate if the app is ever run with
`ORACLE_LEAN_MODE=false`, or if `enable_legacy_signals` / `enable_watchlist` are
explicitly set to `true`. In that configuration they are **unauthenticated**:

- `FrontendAuthMiddleware` is a Starlette `BaseHTTPMiddleware`, which does **not**
  run on WebSocket scopes, and it only gates `/api/v1` paths anyway (the WS routes
  are under `/ws`). So HTTP auth provides no coverage here.
- The connection managers broadcast signal/watchlist price data. This is
  low-sensitivity (market prices), which is part of why no urgent fix is warranted.

### Recommendation if these endpoints are ever revived

Do **not** rely on the bearer `Authorization` header — browsers cannot set custom
headers on a WebSocket handshake. Authenticate at the handshake instead:

```python
@app.websocket("/ws/signals")
async def websocket_signals(ws: WebSocket):
    token = ws.query_params.get("token", "")
    if not frontend_auth_service.verify_token(token):
        await ws.close(code=1008)  # policy violation
        return
    await _signal_mgr.connect(ws)
    ...
```

The frontend would append `?token=<session-token>` to the WebSocket URL. This
reuses the exact same `frontend_auth_service.verify_token` mechanism as the HTTP
routes. Pair with tests for unauthenticated rejection (close 1008) and
authenticated success.

## 8. Changes made

- **Added** `tests/unit/test_websocket_auth.py` — two unit tests asserting the
  gating flags resolve `False` under lean mode (endpoints stay unregistered) and
  `True` otherwise. This guards the documented posture against silent
  re-exposure.
- **Added** this report.
- **No** production code changed; **no** protected subsystem touched.

## 9. Verification

```text
$ python -m pytest tests/unit/test_websocket_auth.py -q
2 passed
```
