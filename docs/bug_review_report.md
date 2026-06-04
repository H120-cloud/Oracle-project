# Oracle Codebase Bug Review Report

**Date:** 2026-05-19
**Scope:** Full-stack review — backend API routes, core agentic modules, services, main.py scheduler/websocket, frontend React
**Baseline:** 503/504 tests passing

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| 🔴 **CRITICAL** | Can crash the app, corrupt data, cause hangs, or leak resources unboundedly |
| 🟡 **MEDIUM** | Causes degraded UX, incorrect behaviour, or memory leaks that matter over time |
| 🟢 **LOW** | Minor issues — code smell, inconsistent API design, missing cleanup |

---

## 🔴 CRITICAL

### C1. JSON file corruption from concurrent writes (no file locking)

**Affected files:** 8 modules, 10+ JSON files

| Module | File(s) written |
|--------|-----------------|
| `orchestrator.py` | `candidates.json`, `alerts.json` |
| `pre_news_detector.py` | `pre_news_anomalies.json` |
| `pre_news_evaluator.py` | `pre_news_evaluation_snapshots.json` |
| `pre_news_learning.py` | `pre_news_outcomes.json` |
| `learning.py` | `learning.json` |
| `historical_calibration.py` | `historical_weights.json`, `historical_rollback.json` |
| `broker_service.py` | `orders.json`, `positions.json`, `closed_trades.json`, `trailing_states.json` |
| `news_impact_learning.py` | `news_impact_outcomes.json` |

**Problem:** Every persistence method uses `open(path, "w")` or `Path.write_text()` with no file locking. Multiple background tasks (outcome simulator, agentic outcome loop, pre-news scan loop, paper trading price loop) plus API-triggered writes can fire simultaneously. On Windows this causes `PermissionError`; on all platforms it causes race conditions where one task reads while another is mid-write, producing truncated/corrupt JSON.

**Evidence:** `orchestrator._persist_state()` at line 845 opens two files sequentially. `broker_service._save_state()` at line 632 opens four files. Both can be called from background loops while API requests also trigger saves.

**Fix:** Add `filelock` dependency and wrap every JSON write in a `FileLock`.

---

### C2. Sync route handlers block the async event loop on market data calls

**Affected routes:**

| File | Route | Blocking call |
|------|-------|---------------|
| `analysis.py:100` | `GET /segment/{ticker}` | `_provider.get_live_quote()` (yfinance) |
| `analysis.py:123` | `GET /live-quote/{ticker}` | `_provider.get_live_quote()` (yfinance) |
| `scanner.py:22` | `GET /volume` | `provider.get_scan_universe()` (yfinance) |
| `scanner.py:44` | `GET /rvol` | `provider.get_scan_universe()` |
| `scanner.py:66` | `GET /gainers` | `provider.get_scan_universe()` |
| `scanner.py:88` | `GET /finviz` | `FinvizScanner.scan_gainers()` (HTTP) |
| `scanner.py:108` | `GET /professional` | `DiscoveryEngine.discover()` + `ProfessionalScanner.scan_universe()` |
| `scanner.py:169` | `GET /discover` | `DiscoveryEngine.discover()` |
| `signals.py:24` | `POST /generate` | `service.generate_signals()` (market data) |
| `signals.py:44` | `GET /analyze/{ticker}` | `service.analyze_single()` (market data) |
| `watchlist.py:63` | `POST /` | `yf.Ticker().info` (yfinance) |
| `news.py:25` | `GET /finviz` | `_scraper.fetch_all()` (httpx) |

**Problem:** FastAPI runs `def` routes in a thread pool, but the default pool is small. If multiple requests hit these simultaneously, they queue up. More importantly, `get_live_quote` and `get_segment` have no error handling — a yfinance exception bubbles up as a raw 500 with Python traceback.

**Fix:** Convert routes that do external I/O to `async def` and wrap blocking calls in `asyncio.to_thread(...)` with `asyncio.wait_for(..., timeout=30.0)`.

---

### C3. WebSocket client leak — unclean disconnects never removed from lists

**File:** `main.py:720-770`

**Problem:** `websocket_signals()` and `websocket_watchlist()` catch `WebSocketDisconnect` but not other exceptions (e.g. `ConnectionClosedError`, `RuntimeError`, OS-level connection reset). When a client disconnects uncleanly, the handler exits without removing the socket from `ws_clients` / `ws_watchlist_clients`. The `broadcast_*` functions then try to send to dead sockets forever.

**Also:** `broadcast_signals()` and `broadcast_watchlist()` remove dead clients from the list while iterating, but if two broadcasts run concurrently they can race on the list.

**Fix:** Use a `ConnectionManager` class with `asyncio.Lock` for add/remove, and catch all exceptions in the handler.

---

### C4. `_pre_news_scan_loop` can exceed its 15-minute interval

**File:** `main.py:155-346`

**Problem:** One loop iteration performs: scan → Telegram alerts → Agentic handoff → news matching → price refresh → confidence decay → stale expiration → outcome recording (yfinance calls per anomaly) → validation price tracking → weekly report check → EOD finalization → success-rate analysis → baseline EOD. All of this happens before `await asyncio.sleep(900)`. If any step is slow (especially yfinance calls for 50+ anomalies), the loop interval stretches and alerts are delayed.

**Also:** The detector and orchestrator are instantiated fresh each loop, reloading JSON state from disk every time.

**Fix:** Split heavy operations into separate background tasks with independent intervals. Keep singleton detector/orchestrator instances.

---

### C5. `BrokerService` singleton race on initialization

**File:** `paper_trading.py:11-22`

**Problem:**
```python
_broker = None

def _get_broker():
    global _broker
    if _broker is None:
        _broker = BrokerService(use_alpaca=False)
    return _broker
```
In a multi-threaded Uvicorn worker, two threads can pass `is None` simultaneously and create two `BrokerService` instances. Only one gets stored in `_broker`, but the other may have already opened files.

**Fix:** Use `threading.Lock()` around singleton initialization.

---

## 🟡 MEDIUM

### M1. `PaperTrading.jsx` validation polling leak

**File:** `frontend/src/pages/PaperTrading.jsx:50-54`

**Problem:** `runValidation()` creates a `setInterval` poll. The cleanup `setTimeout` fires after 5 minutes, but if the component unmounts during validation, the poll keeps running. The `clearInterval(poll)` is only called inside the interval callback or timeout — never on unmount.

**Fix:** Store the poll interval in a `useRef` and clear it in `useEffect` cleanup.

---

### M2. Unbounded dictionary growth in broadcast loop

**File:** `main.py:391-394`

**Problem:** `_big_move_alerted` and `_telegram_watch_alerted` dictionaries are never pruned. Over months of uptime they accumulate thousands of ticker keys, consuming memory.

**Fix:** Prune entries older than 24 hours each cycle.

---

### M3. `news.py` error paths return HTTP 200 with `{"error": ...}`

**File:** `news.py:25-110`

**Problem:** All catch blocks return a dict with an `error` key and HTTP 200. The frontend can't distinguish success from failure without inspecting the body. Standard practice is to raise `HTTPException(status_code=503, ...)` for external service failures.

**Fix:** Raise `HTTPException` for external fetch failures, or at least return a non-2xx status.

---

### M4. `analysis.py:get_live_quote` has no error handling

**File:** `analysis.py:123-126`

```python
@router.get("/live-quote/{ticker}")
def get_live_quote(ticker: str):
    return _provider.get_live_quote(ticker.upper())
```

If yfinance raises, this returns a 500 with a raw traceback. Every other route in `analysis.py` has try/except.

**Fix:** Wrap in try/except and return a clean error dict or raise `HTTPException(503)`.

---

### M5. `_agentic_outcome_loop` makes 100+ sequential yfinance calls

**File:** `main.py:72-149`

**Problem:** For every candidate (potentially 100+), the loop does:
1. `yf.Ticker(ticker).history(period="1d", interval="5m")`
2. Fallback to `history(period="5d", interval="1d")`
3. Fallback to `fast_info`
4. Fallback to StockTwits check

These are sequential (`for ticker, candidate in list(...)`). With 100 candidates this can take 5-10 minutes, exceeding the 30-minute interval.

**Fix:** Batch fetch or add a max-per-iteration limit.

---

### M6. Frontend WebSocket hardcodes `window.location.host` (dev port mismatch)

**File:** `Watchlist.jsx:995`

```javascript
const wsUrl = `${wsProto}//${window.location.host}/ws/watchlist`
```

In dev (Vite on :3000), this tries to connect to `ws://localhost:3000/ws/watchlist`, but the backend is on :8000. The console shows this exact error.

**Fix:** Use a configurable WS base URL or proxy through Vite.

---

## 🟢 LOW

### L1. `Agentic.jsx` tab badge shows filtered count, not total

Line: `count: newsImpactRows.length` — but `newsImpactRows` is already filtered by `decisionFilter` and `minScore`. The badge should show the unfiltered total.

### L2. `orchestrator._fetch_intraday_bars` uses yfinance directly

This bypasses the provider abstraction and doesn't benefit from Alpaca/Polygon fallbacks.

### L3. Multiple modules use relative `../../..` path for `data/` directory

Hard to refactor. Should use a shared `DATA_DIR` constant.

### L4. `news_impact_engine.py` `to_dict()` method re-serializes model fields manually

Could use `model_dump()` from Pydantic v2 instead of custom serialization.

---

## Summary Table

| # | Severity | File(s) | Issue | Impact |
|---|----------|---------|-------|--------|
| C1 | 🔴 Critical | 8 modules | JSON writes without file locking | Data corruption, PermissionError |
| C2 | 🔴 Critical | `analysis.py`, `scanner.py`, `signals.py`, `watchlist.py`, `news.py` | Sync routes block event loop | Request queuing, raw 500s |
| C3 | 🔴 Critical | `main.py` | WebSocket unclean disconnect leak | Memory leak, broadcast failures |
| C4 | 🔴 Critical | `main.py` | Pre-news loop too heavy per iteration | Interval stretching, alert delays |
| C5 | 🔴 Critical | `paper_trading.py` | Broker singleton race condition | Duplicate state, file races |
| M1 | 🟡 Medium | `PaperTrading.jsx` | Validation polling leak | Memory leak, ghost polling |
| M2 | 🟡 Medium | `main.py` | Unbounded dict growth | Memory leak over months |
| M3 | 🟡 Medium | `news.py` | Error paths return HTTP 200 | Silent failures in frontend |
| M4 | 🟡 Medium | `analysis.py` | No error handling on live quote | Raw 500 traceback |
| M5 | 🟡 Medium | `main.py` | Sequential yfinance per candidate | Loop interval exceeded |
| M6 | 🟡 Medium | `Watchlist.jsx` | WS URL port mismatch in dev | WS connection fails in dev |
| L1 | 🟢 Low | `Agentic.jsx` | Badge shows filtered count | UI inconsistency |
| L2 | 🟢 Low | `orchestrator.py` | Direct yfinance usage | Missing provider fallbacks |
| L3 | 🟢 Low | Multiple | Hardcoded relative paths | Refactoring friction |
| L4 | 🟢 Low | `news_impact_engine.py` | Manual dict serialization | Minor code smell |

---

## Recommended Fix Order

1. **C1** — File locking (prevents data corruption)
2. **C2** — Async route wrapping (prevents request queuing/hangs)
3. **C3** — WebSocket connection manager (prevents memory leak)
4. **C5** — Broker singleton lock (prevents duplicate state)
5. **C4** — Split pre-news loop (prevents alert delays)
6. **M1** — PaperTrading cleanup (prevents frontend leak)
7. **M2** — Dict pruning (prevents memory growth)
8. **M6** — WS URL fix (fixes dev experience)
