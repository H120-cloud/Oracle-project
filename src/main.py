"""
Oracle — AI Dip-and-Bounce Trading Signal System

FastAPI application entry point (V5).
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.models.database import Base
from src.db.session import engine, SessionLocal
from src.api.routes import health, scanner, signals, watchlist, models, analysis, backtest, intelligence, news, htf_scan, paper_trading
from src.core.outcome_simulator import OutcomeSimulator

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("oracle")


# ── Lifespan ─────────────────────────────────────────────────────────────────

SIMULATOR_INTERVAL_SECONDS = 1800  # Run every 30 minutes


async def _outcome_simulator_loop():
    """Background task: auto-evaluate signal outcomes every hour."""
    await asyncio.sleep(30)  # Wait 30s after startup before first run
    while True:
        try:
            logger.info("OutcomeSimulator: starting background check...")
            db = SessionLocal()
            try:
                simulator = OutcomeSimulator(db)
                stats = simulator.run()
                logger.info("OutcomeSimulator stats: %s", stats)
            finally:
                db.close()
        except Exception as exc:
            logger.error("OutcomeSimulator error: %s", exc)

        await asyncio.sleep(SIMULATOR_INTERVAL_SECONDS)


PAPER_TRADING_PRICE_INTERVAL = 30  # seconds between paper position price updates


async def _paper_trading_price_loop():
    """Background task: update paper trading positions with live prices for trailing stop management."""
    await asyncio.sleep(15)  # Wait 15s after startup
    while True:
        try:
            from src.api.routes.paper_trading import _get_broker
            broker = _get_broker()
            if broker.positions:
                import yfinance as yf
                price_map = {}
                tickers = list(broker.positions.keys())
                # Batch fetch with yfinance
                try:
                    data = await asyncio.to_thread(
                        lambda: {t: yf.Ticker(t).fast_info for t in tickers}
                    )
                    for t, fi in data.items():
                        price = float(getattr(fi, "last_price", 0) or 0)
                        if price > 0:
                            price_map[t] = price
                except Exception as exc:
                    logger.warning("Paper price fetch error: %s", exc)

                if price_map:
                    broker.update_prices(price_map)
                    logger.debug("Paper trading: updated %d/%d positions", len(price_map), len(tickers))
        except Exception as exc:
            logger.error("Paper trading price loop error: %s", exc)

        await asyncio.sleep(PAPER_TRADING_PRICE_INTERVAL)


WATCHLIST_BROADCAST_INTERVAL = 1  # seconds (live price updates every second)


ALERT_CHECK_COUNTER = 0
ALERT_CHECK_EVERY = 60  # Check alerts every 60 cycles (60s at 1s interval)


async def _watchlist_broadcast_loop():
    """Background task: push watchlist price updates every 1 second, alert checks every 60s."""
    global ALERT_CHECK_COUNTER
    await asyncio.sleep(10)  # Wait 10s after startup
    while True:
        try:
            # Only broadcast if there are connected clients
            if ws_watchlist_clients:
                db = SessionLocal()
                try:
                    from src.db.repositories import WatchlistRepository
                    import yfinance as yf

                    repo = WatchlistRepository(db)

                    # Get active watchlist items
                    items = repo.get_all_active()
                    if items:
                        updates = []

                        def _fetch_prices(tickers):
                            """Synchronous batch price fetch — runs in thread pool."""
                            results = []
                            for t in tickers:
                                try:
                                    fi = yf.Ticker(t).fast_info
                                    price = float(getattr(fi, "last_price", 0) or 0)
                                    prev_close = float(getattr(fi, "previous_close", 0) or 0)
                                    if price > 0:
                                        results.append((t, price, prev_close))
                                except Exception:
                                    continue
                            return results

                        # Run synchronous yfinance calls in a thread to avoid blocking event loop
                        ticker_list = [item.ticker for item in items]
                        price_results = await asyncio.to_thread(_fetch_prices, ticker_list)

                        for ticker, price, prev_close in price_results:
                            change_pct = round(((price - prev_close) / prev_close * 100), 2) if prev_close > 0 else 0
                            updates.append({
                                "ticker": ticker,
                                "price": round(price, 4),
                                "price_change": round(price - prev_close, 4) if prev_close > 0 else 0,
                                "change_pct": change_pct,
                            })

                        if updates:
                            await broadcast_watchlist({
                                "type": "price_update",
                                "timestamp": datetime.utcnow().isoformat(),
                                "updates": updates,
                            })

                    # Periodic alert detection (every ~60s)
                    ALERT_CHECK_COUNTER += 1
                    if ALERT_CHECK_COUNTER >= ALERT_CHECK_EVERY and items:
                        ALERT_CHECK_COUNTER = 0
                        try:
                            from src.services.watchlist_service import WatchlistService
                            svc = WatchlistService(db)
                            alert_events = []

                            for item in items:
                                try:
                                    metrics = svc._fetch_metrics(item.ticker)
                                    if not metrics:
                                        continue

                                    dip_prob = metrics.get("dip_prob", 0)
                                    bounce_prob = metrics.get("bounce_prob", 0)
                                    bearish_prob = metrics.get("bearish_prob", 0)
                                    rvol = metrics.get("rvol", 0)
                                    change_pct = metrics.get("change_pct", 0)
                                    price = metrics.get("price", 0)

                                    # Dip alert: probability >= 60% and was < 60%
                                    old_dip = item.latest_dip_prob or 0
                                    if dip_prob and dip_prob >= 60 and old_dip < 60:
                                        alert_events.append({
                                            "alert_type": "dip_detected",
                                            "severity": "warning",
                                            "sound": "dip",
                                            "ticker": item.ticker,
                                            "message": f"{item.ticker} dip forming — {dip_prob}% probability",
                                            "value": dip_prob,
                                            "price": price,
                                        })

                                    # Bounce/bullish alert: probability >= 65% and was < 65%
                                    old_bounce = item.latest_bounce_prob or 0
                                    if bounce_prob and bounce_prob >= 65 and old_bounce < 65:
                                        alert_events.append({
                                            "alert_type": "bounce_confirmed",
                                            "severity": "critical",
                                            "sound": "bullish",
                                            "ticker": item.ticker,
                                            "message": f"{item.ticker} bounce confirmed — {bounce_prob}% probability",
                                            "value": bounce_prob,
                                            "price": price,
                                        })

                                    # Bearish warning
                                    old_bearish = item.latest_bearish_prob or 0
                                    if bearish_prob and bearish_prob >= 50 and old_bearish < 50:
                                        alert_events.append({
                                            "alert_type": "bearish_warning",
                                            "severity": "critical",
                                            "sound": "bearish",
                                            "ticker": item.ticker,
                                            "message": f"{item.ticker} bearish shift — {bearish_prob}% probability",
                                            "value": bearish_prob,
                                            "price": price,
                                        })

                                    # Volume surge
                                    old_rvol = item.latest_rvol or 0
                                    if rvol and rvol >= 3.0 and old_rvol < 3.0:
                                        alert_events.append({
                                            "alert_type": "volume_surge",
                                            "severity": "warning",
                                            "sound": "volume",
                                            "ticker": item.ticker,
                                            "message": f"{item.ticker} volume surge — RVOL {rvol}x",
                                            "value": rvol,
                                            "price": price,
                                        })

                                    # Big move (5%+)
                                    if abs(change_pct) >= 5:
                                        direction = "bullish" if change_pct > 0 else "dip"
                                        alert_events.append({
                                            "alert_type": "big_move",
                                            "severity": "warning",
                                            "sound": direction,
                                            "ticker": item.ticker,
                                            "message": f"{item.ticker} moved {change_pct:+.1f}%",
                                            "value": change_pct,
                                            "price": price,
                                        })

                                    # Update metrics in DB
                                    svc.repo.update_metrics(item.ticker, metrics)

                                    # V9: Check for HTF changes during refresh
                                    try:
                                        htf_alert = svc.check_htf_for_ticker(item.ticker)
                                        if htf_alert:
                                            alert_events.append({
                                                "ticker": htf_alert.ticker,
                                                "event": f"htf_{htf_alert.alert_type.value}",
                                                "severity": htf_alert.severity,
                                                "explanation": htf_alert.explanation,
                                                "previous_bias": htf_alert.previous_bias,
                                                "new_bias": htf_alert.new_bias,
                                            })
                                    except Exception:
                                        pass  # HTF check is best-effort

                                except Exception:
                                    continue

                            if alert_events:
                                await broadcast_watchlist({
                                    "type": "alert_event",
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "alerts": alert_events,
                                })
                                logger.info("Broadcast %d alert events", len(alert_events))

                        except Exception as exc:
                            logger.warning("Alert check error: %s", exc)

                finally:
                    db.close()
        except Exception as exc:
            logger.error("Watchlist broadcast error: %s", exc)

        await asyncio.sleep(WATCHLIST_BROADCAST_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Oracle V5 starting (env=%s)", settings.app_env)

    # Create tables if they don't exist (preserves data across restarts)
    Base.metadata.create_all(bind=engine, checkfirst=True)
    logger.info("Database tables ensured")

    # Start background outcome simulator
    sim_task = asyncio.create_task(_outcome_simulator_loop())
    logger.info("Background outcome simulator started (interval=%ds)", SIMULATOR_INTERVAL_SECONDS)

    # Start watchlist real-time broadcaster
    watchlist_task = asyncio.create_task(_watchlist_broadcast_loop())
    logger.info("Watchlist real-time broadcaster started")

    # Start paper trading price updater (trailing stops, auto-exits)
    paper_task = asyncio.create_task(_paper_trading_price_loop())
    logger.info("Paper trading price updater started (interval=%ds)", PAPER_TRADING_PRICE_INTERVAL)

    yield

    sim_task.cancel()
    watchlist_task.cancel()
    paper_task.cancel()
    logger.info("Oracle shutting down")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Oracle — Dip & Bounce Signal System",
    description="AI-powered trading signal engine (V10: Paper Trading + Validation + Calibration)",
    version="10.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(scanner.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(models.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(htf_scan.router, prefix="/api/v1")  # V9: HTF-Aware Scanner
app.include_router(paper_trading.router, prefix="/api/v1")  # V10: Paper Trading + Validation + Calibration


# ── WebSocket — real-time signal streaming ──────────────────────────────────

ws_clients: list[WebSocket] = []
ws_watchlist_clients: list[WebSocket] = []


@app.websocket("/ws/signals")
async def websocket_signals(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    logger.info("WS client connected (%d total)", len(ws_clients))
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        ws_clients.remove(ws)
        logger.info("WS client disconnected (%d total)", len(ws_clients))


@app.websocket("/ws/watchlist")
async def websocket_watchlist(ws: WebSocket):
    """Real-time watchlist price updates."""
    await ws.accept()
    ws_watchlist_clients.append(ws)
    logger.info("Watchlist WS client connected (%d total)", len(ws_watchlist_clients))
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        ws_watchlist_clients.remove(ws)
        logger.info("Watchlist WS client disconnected (%d total)", len(ws_watchlist_clients))


async def broadcast_signals(data: dict):
    """Push signal updates to all connected WebSocket clients."""
    payload = json.dumps(data, default=str)
    for ws in ws_clients[:]:
        try:
            await ws.send_text(payload)
        except Exception:
            ws_clients.remove(ws)


async def broadcast_watchlist(data: dict):
    """Push watchlist updates to all connected clients."""
    payload = json.dumps(data, default=str)
    for ws in ws_watchlist_clients[:]:
        try:
            await ws.send_text(payload)
        except Exception:
            ws_watchlist_clients.remove(ws)


# ── Static frontend (serve built React app) ─────────────────────────────────

import os

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {
            "name": "Oracle — Dip & Bounce Signal System",
            "version": "5.0.0",
            "phase": "V5",
            "docs": "/docs",
            "ui": "Build frontend with: cd frontend && npm run build",
        }
