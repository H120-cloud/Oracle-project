"""
Oracle — AI Dip-and-Bounce Trading Signal System

FastAPI application entry point (V5).
"""

import os
from dotenv import load_dotenv

# Load .env before any module imports that might read env vars
_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.isfile(_env_path):
    load_dotenv(_env_path)

import asyncio
import importlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.models.database import Base
from src.db.session import engine, SessionLocal
from src.utils.data_paths import (
    agentic_data_dir,
    seed_agentic_data_dir,
    verify_persistent_data_dir,
)
from src.api.routes import health, news, agentic, pre_news, historical_training, news_momentum, sec_intelligence, frontend_auth, timing_reviews, admin_diagnostics
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.pre_news_detector import PreNewsDetector
from src.core.agentic.pre_news_evaluator import PreNewsEvaluator
from src.core.agentic.pre_news_validation import PreNewsValidationTracker, _week_key
from src.middleware.frontend_auth import FrontendAuthMiddleware
from src.services.telegram_command_handler import telegram_command_polling_loop
from src.services.telegram_service import send_telegram_alert, telegram_outbox_sender_loop

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("oracle")

# Suppress noisy loggers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def _log_lean_mode_status(settings) -> None:
    status = settings.lean_mode_status()
    enabled = sorted(name for name, value in status.items() if value)
    disabled = sorted(name for name, value in status.items() if not value)
    logger.info("Oracle lean mode: %s", "enabled" if settings.oracle_lean_mode else "disabled")
    logger.info("Oracle systems enabled: %s", ", ".join(enabled) if enabled else "none")
    logger.info("Oracle systems disabled: %s", ", ".join(disabled) if disabled else "none")


# ── Lifespan ─────────────────────────────────────────────────────────────────

SIMULATOR_INTERVAL_SECONDS = 1800  # Run every 30 minutes


async def _outcome_simulator_loop():
    """Background task: auto-evaluate signal outcomes every hour."""
    await asyncio.sleep(30)  # Wait 30s after startup before first run
    while True:
        try:
            from src.core.outcome_simulator import OutcomeSimulator
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


AGENTIC_OUTCOME_INTERVAL = 1800  # 30 minutes


async def _agentic_outcome_loop():
    """Background task: auto-evaluate agentic candidate outcomes."""
    await asyncio.sleep(60)  # Wait 60s after startup
    while True:
        try:
            from src.core.agentic.orchestrator import AgenticOrchestrator
            from src.core.agentic.learning import LearningEngine
            orch = AgenticOrchestrator()
            orch.load_state()
            learning = LearningEngine()
            recorded = 0
            logger.info("AgenticOutcome: checking %d candidates", len(orch.candidates))

            for ticker, candidate in list(orch.candidates.items()):
                ticker_news_events = []
                try:
                    # Skip if outcome already recorded for this candidate
                    existing = [o for o in learning.outcomes if o.candidate_id == candidate.id]
                    if existing:
                        continue

                    # Fetch current price via yfinance with fallbacks for thinly-traded tickers
                    import yfinance as yf

                    def _fetch_prices(tkr):
                        ticker_obj = yf.Ticker(tkr)
                        # Try 5m intraday first
                        hist = ticker_obj.history(period="1d", interval="5m")
                        if not hist.empty:
                            return float(hist["Close"].iloc[-1]), float(hist["High"].max())
                        # Fallback 1: daily history over 5 days
                        hist = ticker_obj.history(period="5d", interval="1d")
                        if not hist.empty:
                            return float(hist["Close"].iloc[-1]), float(hist["High"].max())
                        # Fallback 2: fast_info
                        try:
                            info = ticker_obj.fast_info
                            cp = float(info.last_price)
                            hp = float(getattr(info, "day_high", cp) or cp)
                            return cp, hp
                        except Exception:
                            return None, None

                    current_price, high_price = await asyncio.to_thread(_fetch_prices, ticker)
                    if current_price is None:
                        logger.debug("Agentic outcome: yfinance no data for %s, checking StockTwits", ticker)
                        # Fallback 3: validate on StockTwits and use last known price
                        from src.core.agentic.ticker_validator import is_ticker_active_on_stocktwits
                        active = is_ticker_active_on_stocktwits(ticker)
                        if active is True and candidate.last_price:
                            current_price = candidate.last_price
                            high_price = candidate.momentum.high_of_day or current_price
                            logger.info(
                                "Agentic outcome: using last known price for %s (StockTwits active, yfinance no data)",
                                ticker,
                            )
                        else:
                            logger.debug("Agentic outcome: no price data for %s, skipping", ticker)
                            continue

                    # Record outcome
                    outcome = learning.record_from_candidate(
                        candidate, peak_price=high_price, exit_price=current_price
                    )
                    logger.info(
                        "Agentic outcome %s: %s (peak=%.2f, exit=%.2f)",
                        ticker, outcome.outcome_class.value, high_price, current_price,
                    )
                    recorded += 1
                except Exception as exc:
                    logger.warning("Agentic outcome error for %s: %s", ticker, exc)

            if recorded > 0:
                logger.info(
                    "AgenticOutcome: recorded %d new outcomes (total=%d)",
                    recorded, len(learning.outcomes),
                )
        except Exception as exc:
            logger.error("AgenticOutcome loop error: %s", exc)

        await asyncio.sleep(AGENTIC_OUTCOME_INTERVAL)


PRE_NEWS_SCAN_INTERVAL = 180  # 3 minutes for timely pre-news alerts
PRE_NEWS_STARTUP_DELAY = 20


async def _pre_news_scan_loop():
    """Background task: scan for pre-news volume anomalies, send Telegram alerts, auto-add to Agentic."""
    # Quick startup refresh: update news status on any persisted anomalies so
    # stale NO_NEWS_FOUND records get re-checked immediately rather than
    # waiting for the first 15-minute tick. Also refresh high-price buckets.
    try:
        startup_detector = PreNewsDetector()
        startup_detector.load_state()
        confirmed = await startup_detector.update_news_status()
        if confirmed:
            logger.info(
                "PreNewsScan startup: refreshed news for %d persisted anomalies",
                len(confirmed),
            )
        # refresh_tracked_prices() is sync and makes blocking provider calls;
        # run it off the event loop so a throttled provider can't stall startup.
        await asyncio.to_thread(startup_detector.refresh_tracked_prices)
    except Exception as exc:
        logger.debug("PreNewsScan startup refresh failed: %s", exc)

    await asyncio.sleep(PRE_NEWS_STARTUP_DELAY)
    while True:
        try:
            detector = PreNewsDetector()
            detector.load_state()

            # Run scan
            anomalies = await detector.scan(min_rvol=2.0)
            logger.info(
                "PreNewsScan: %d anomalies detected",
                len(anomalies),
            )

            # ── Shadow V2 (OBSERVE-ONLY) ──────────────────────────────────
            # Log BASELINE (suspicion>=75) vs V2 (anomaly-type+safety) gate
            # decisions for every detection, then resolve forward outcomes for
            # matured records. Never sends an alert, never mutates production
            # state -- pure data collection to validate replacing the suspicion
            # gate. Fully isolated so any failure cannot affect the live scan.
            try:
                from src.core.agentic.pre_news_shadow_v2 import PreNewsShadowV2
                _shadow = PreNewsShadowV2()
                _shadow.capture_from_anomalies(anomalies)
                try:
                    from src.services.market_data import get_market_data_provider
                    await _shadow.resolve_open(get_market_data_provider())
                except Exception as _shadow_res_exc:
                    logger.debug("ShadowV2 resolve skipped: %s", _shadow_res_exc)
            except Exception as _shadow_exc:
                logger.debug("ShadowV2 capture skipped: %s", _shadow_exc)

            # ── Telegram alerts for EXTREME score anomalies ────────────────
            from src.services.telegram_service import send_telegram_alert
            from src.core.agentic.pre_news_alert_audit import record_pre_news_alert_decision
            validation_tracker = PreNewsValidationTracker()
            for anomaly in anomalies:
                alert_decision = detector.explain_alert_decision(anomaly)
                if alert_decision["should_alert"]:
                    sent = False
                    telegram_error = None
                    msg = detector.format_alert(anomaly)
                    alert_id = f"pre_news:{anomaly.ticker}:{anomaly.detected_at.isoformat()}"
                    try:
                        sent = await send_telegram_alert(
                            msg,
                            parse_mode="HTML",
                            alert_id=alert_id,
                            ticker=anomaly.ticker,
                            alert_type="pre_news",
                            priority=3,
                        )
                        if sent:
                            detector.mark_alert_sent(anomaly.ticker)
                            logger.info("PreNews Telegram alert sent for %s (score=%s)", anomaly.ticker, anomaly.pre_news_suspicion_score)
                            validation_tracker.record_alert(anomaly.ticker)
                        else:
                            logger.warning(
                                "PreNews Telegram alert queued/pending for %s (score=%s)",
                                anomaly.ticker,
                                anomaly.pre_news_suspicion_score,
                            )
                    except Exception as exc:
                        telegram_error = str(exc)
                        logger.exception("PreNews Telegram alert failed for %s", anomaly.ticker)
                    finally:
                        try:
                            record_pre_news_alert_decision(
                                anomaly,
                                alert_decision,
                                telegram_attempted=True,
                                telegram_sent=sent,
                                telegram_error=telegram_error,
                            )
                        except Exception as audit_exc:
                            logger.debug("PreNews alert audit write failed for %s: %s", anomaly.ticker, audit_exc)
                else:
                    logger.info(
                        "PreNews Telegram gate blocked %s score=%.0f reasons=%s",
                        anomaly.ticker,
                        anomaly.pre_news_suspicion_score,
                        ",".join(alert_decision["reasons"]) or "none",
                    )
                    try:
                        record_pre_news_alert_decision(
                            anomaly,
                            alert_decision,
                            telegram_attempted=False,
                            telegram_sent=False,
                        )
                    except Exception as audit_exc:
                        logger.debug("PreNews alert audit write failed for %s: %s", anomaly.ticker, audit_exc)

            # ── V2: Agentic handoff via centralized orchestrator method ────
            from src.core.agentic.orchestrator import AgenticOrchestrator
            orch = AgenticOrchestrator()
            orch.load_state()
            handoff_anomalies = detector.get_agentic_handoff_candidates(min_suspicion=70.0)
            handoff_result = orch.handoff_from_pre_news(handoff_anomalies)
            if handoff_result["created"] or handoff_result["updated"]:
                logger.info(
                    "PreNews V2 handoff: created=%d updated=%d skipped=%d",
                    handoff_result["created"], handoff_result["updated"], handoff_result["skipped"],
                )

            # Update news status for existing anomalies (post-news matching).
            # If news has just been confirmed for a tracked anomaly, fire a
            # Telegram notification so the user knows the catalyst landed.
            newly_confirmed = await detector.update_news_status()
            if newly_confirmed:
                confirmed_handoff = [
                    a for a in newly_confirmed
                    if getattr(a, "pre_news_suspicion_score", 0.0) >= 70.0
                ]
                if confirmed_handoff:
                    confirmed_result = orch.handoff_from_pre_news(confirmed_handoff)
                    if confirmed_result["created"] or confirmed_result["updated"]:
                        logger.info(
                            "PreNews confirmed handoff: created=%d updated=%d skipped=%d",
                            confirmed_result["created"],
                            confirmed_result["updated"],
                            confirmed_result["skipped"],
                        )
            for anomaly in newly_confirmed:
                try:
                    headline = anomaly.first_news_headline or "Catalyst confirmed"
                    gap = anomaly.time_gap_minutes
                    gap_str = f" (volume preceded by {gap:.0f}m)" if gap else ""
                    msg = (
                        f"📰 <b>NEWS CONFIRMED</b> — <b>{anomaly.ticker}</b>{gap_str}\n"
                        f"Price: ${anomaly.price:.2f}  RVOL: {anomaly.volume_metrics.rvol_current:.1f}x\n"
                        f"Suspicion score: {anomaly.pre_news_suspicion_score:.0f}\n"
                        f"<i>{headline[:200]}</i>"
                    )
                    alert_id = f"pre_news_confirmed:{anomaly.ticker}:{(anomaly.news_confirmed_at or anomaly.detected_at).isoformat()}"
                    sent = await send_telegram_alert(
                        msg,
                        alert_id=alert_id,
                        ticker=anomaly.ticker,
                        alert_type="pre_news_confirmed",
                        priority=4,
                    )
                    if sent:
                        detector.mark_news_confirmed_alert_sent(anomaly.ticker)
                        logger.info(
                            "PreNews news-confirmation alert sent for %s", anomaly.ticker
                        )
                    else:
                        logger.warning(
                            "PreNews news-confirmation alert queued/pending for %s",
                            anomaly.ticker,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to send news-confirmation alert for %s: %s",
                        anomaly.ticker, exc,
                    )

            # Refresh high-price buckets for every active anomaly
            try:
                detector.refresh_tracked_prices()
            except Exception as exc:
                logger.debug("refresh_tracked_prices failed: %s", exc)

            # V2: Apply confidence decay to stale anomalies without follow-through
            decayed = detector.apply_confidence_decay_all(max_age_hours=6)
            if decayed > 0:
                logger.info("PreNews V2 decay: %d anomalies updated", decayed)

            # Expire stale anomalies
            detector.expire_stale(max_age_hours=6)

            # ── Record outcomes for completed anomalies ────────────────────
            from src.core.agentic.pre_news_learning import PreNewsLearningEngine
            learning = PreNewsLearningEngine()
            recorded = 0
            for anomaly in list(detector.anomalies.values()):
                if anomaly.outcome_recorded:
                    continue
                if anomaly.state not in ("expired", "catalyst_confirmed"):
                    continue
                try:
                    def _fetch_anomaly_prices(tkr_str):
                        tkr_obj = yf.Ticker(tkr_str)
                        hist = tkr_obj.history(period="1d", interval="5m")
                        if not hist.empty:
                            return float(hist["High"].max()), float(hist["Close"].iloc[-1])
                        return None, None

                    peak, exit_price = await asyncio.to_thread(_fetch_anomaly_prices, anomaly.ticker)
                    learning.record_outcome(anomaly, peak_price=peak, exit_price=exit_price)
                    anomaly.outcome_recorded = True
                    recorded += 1
                except Exception as e:
                    logger.debug("PreNews outcome record %s failed: %s", anomaly.ticker, e)
            if recorded > 0:
                detector._persist_state()
                logger.info("PreNews: recorded %d outcomes", recorded)

            # ── V2 Validation: price tracking + resolution ─────────────────
            try:
                open_records = validation_tracker.get_open_records()
                if open_records:
                    tickers = [r.ticker for r in open_records]

                    def _fetch_validation_prices(tkrs):
                        """Per-ticker price fetch, isolated so one failure (a
                        connect-timeout, a delisted ticker) can't wipe out the
                        whole batch. Prefer the resilient provider quote (cached +
                        rate-limit backoff), fall back to yfinance fast_info."""
                        import yfinance as yf
                        from src.services.market_data import get_market_data_provider
                        try:
                            provider = get_market_data_provider()
                        except Exception:
                            provider = None
                        out = {}
                        for t in tkrs:
                            price = 0.0
                            try:
                                if provider is not None:
                                    q = provider.get_live_quote(t)
                                    price = float((q or {}).get("price", 0) or 0)
                                if price <= 0:
                                    fi = yf.Ticker(t).fast_info
                                    price = float(getattr(fi, "last_price", 0) or 0)
                            except Exception:
                                continue  # isolate: skip this ticker, keep the rest
                            if price > 0:
                                out[t] = price
                        return out

                    try:
                        price_map = await asyncio.to_thread(_fetch_validation_prices, tickers)
                    except Exception as exc:
                        logger.debug("Validation price fetch error: %s", exc)
                        price_map = {}
                    if price_map:
                        logger.debug(
                            "Validation: fetched %d/%d prices", len(price_map), len(tickers)
                        )
                    if price_map:
                        validation_tracker.update_prices(price_map)
                    # Always resolve, even when price fetching failed: EXPIRED is
                    # purely time-based (24h window), so gating resolution behind a
                    # populated price_map left stale records OPEN forever whenever
                    # yfinance was rate-limited. update_prices stays gated (we can't
                    # update prices we don't have); resolve_all must not be.
                    resolved = validation_tracker.resolve_all()
                    if resolved > 0:
                        logger.info("PreNews V2 validation: resolved %d records", resolved)
            except Exception as exc:
                logger.debug("Validation tracking error: %s", exc)

            # ── V2 Validation: weekly report (generate every Monday ~05:00 UTC) ──
            try:
                now_utc = datetime.now(timezone.utc)
                if now_utc.weekday() == 0 and now_utc.hour == 5 and now_utc.minute < 15:
                    last_week = _week_key(now_utc - timedelta(days=7))
                    report = validation_tracker.generate_weekly_report(week_key=last_week)
                    logger.info(
                        "PreNews V2 weekly report %s: handoffs=%d wins=%d losses=%d",
                        report.week_key, report.total_handoffs, report.win_count, report.loss_count,
                    )
            except Exception as exc:
                logger.debug("Weekly report generation error: %s", exc)

            # ── V3: EOD outcome finalization ──────────────────────────────
            try:
                evaluator = PreNewsEvaluator()
                evaluator.finalize_all_eod(force=False)
            except Exception as exc:
                logger.debug("PreNews V3 evaluator EOD finalize error: %s", exc)

            # ── V3: Auto-export daily report + success-rate analysis ────────
            try:
                session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                evaluator.export_daily_report(session_date=session_date)
                from scripts.pre_news_success_rate_analysis import run_analysis
                run_analysis(write_outputs=True)
                logger.info("PreNews V3 success-rate analysis completed for %s", session_date)
            except Exception as exc:
                logger.debug("PreNews V3 success-rate analysis error: %s", exc)

            # ── V3: Baseline EOD finalization + export ──────────────────────
            try:
                from src.core.agentic.pre_news_baseline import PreNewsBaselineTracker
                bt = PreNewsBaselineTracker()
                bt.finalize_all_eod(force=False)
                session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                bt.export_daily_baselines(session_date=session_date)
                logger.info("PreNews V3 baseline EOD finalized for %s", session_date)
            except Exception as exc:
                logger.debug("PreNews V3 baseline EOD error: %s", exc)

        except Exception as exc:
            logger.error("PreNewsScan loop error: %s", exc)

        await asyncio.sleep(PRE_NEWS_SCAN_INTERVAL)


PAPER_TRADING_PRICE_INTERVAL = 30  # seconds between paper position price updates


async def _paper_trading_price_loop():
    """Background task: update paper trading positions with live prices for trailing stop management."""
    await asyncio.sleep(15)  # Wait 15s after startup
    try:
        paper_trading_module = importlib.import_module("src.api.routes.paper_trading")
        _get_broker = getattr(paper_trading_module, "_get_broker")
    except ImportError as exc:
        logger.warning("Paper trading price loop disabled: %s", exc)
        return
    except AttributeError as exc:
        logger.warning("Paper trading price loop disabled: %s", exc)
        return

    while True:
        try:
            broker = _get_broker()
            if broker.positions:
                import yfinance as yf
                tickers = list(broker.positions.keys())

                def _fetch_position_prices(tkrs):
                    """Per-ticker fetch, isolated so one bad/timing-out position
                    can't wipe out price updates for all the others."""
                    out = {}
                    for t in tkrs:
                        try:
                            fi = yf.Ticker(t).fast_info
                            price = float(getattr(fi, "last_price", 0) or 0)
                        except Exception:
                            continue
                        if price > 0:
                            out[t] = price
                    return out

                try:
                    price_map = await asyncio.to_thread(_fetch_position_prices, tickers)
                except Exception as exc:
                    logger.warning("Paper price fetch error: %s", exc)
                    price_map = {}

                if price_map:
                    broker.update_prices(price_map)
                    logger.debug("Paper trading: updated %d/%d positions", len(price_map), len(tickers))
        except Exception as exc:
            logger.error("Paper trading price loop error: %s", exc)

        await asyncio.sleep(PAPER_TRADING_PRICE_INTERVAL)


WATCHLIST_BROADCAST_INTERVAL = 1  # seconds (live price updates every second)


ALERT_CHECK_COUNTER = 0
ALERT_CHECK_EVERY = 60  # Check alerts every 60 cycles (60s at 1s interval)

# Cooldown: track last alerted bracket per ticker to avoid repeat big_move alerts
_big_move_alerted: dict[str, int] = {}

# Cooldown for Telegram /watch bias alerts (5 min)
_telegram_watch_alerted: dict[str, datetime] = {}


def _prune_cooldowns():
    """Remove stale entries from unbounded cooldown dictionaries (called every ~60s)."""
    global _telegram_watch_alerted
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Prune Telegram watch alerts older than 24h
    stale_keys = [
        k for k, v in _telegram_watch_alerted.items()
        if (now - v).total_seconds() > 86400
    ]
    for k in stale_keys:
        _telegram_watch_alerted.pop(k, None)
    # _big_move_alerted stores integer brackets, not timestamps,
    # but we can still cap total size to prevent unbounded growth
    if len(_big_move_alerted) > 1000:
        # Keep the 500 most recently touched tickers
        _big_move_alerted.clear()


async def _watchlist_broadcast_loop():
    """Background task: push watchlist price updates every 1 second, alert checks every 60s."""
    global ALERT_CHECK_COUNTER
    await asyncio.sleep(10)  # Wait 10s after startup
    try:
        from src.db.repositories import WatchlistRepository
    except ImportError as exc:
        logger.warning("Watchlist broadcaster disabled: %s", exc)
        return

    try:
        from src.services.watchlist_service import WatchlistService
    except ImportError as exc:
        WatchlistService = None  # type: ignore[assignment]
        logger.warning("Watchlist alert checks disabled: %s", exc)

    while True:
        try:
            # Broadcast to watchlist WS clients (ConnectionManager handles empties)
            if _watchlist_mgr.has_clients:
                db = SessionLocal()
                try:
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
                                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                                "updates": updates,
                            })

                    # Periodic alert detection (every ~60s)
                    ALERT_CHECK_COUNTER += 1
                    if ALERT_CHECK_COUNTER >= ALERT_CHECK_EVERY and items:
                        ALERT_CHECK_COUNTER = 0
                        _prune_cooldowns()
                        if WatchlistService is None:
                            continue
                        try:
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

                                    # Big move (5%+) — only alert once per 5% bracket to prevent spam
                                    if abs(change_pct) >= 5:
                                        bracket = int(abs(change_pct) // 5) * 5  # 5, 10, 15, 20...
                                        last_bracket = _big_move_alerted.get(item.ticker, 0)
                                        if bracket > last_bracket:
                                            _big_move_alerted[item.ticker] = bracket
                                            direction = "money_up" if change_pct > 0 else "money_down"
                                            alert_events.append({
                                                "alert_type": "big_move",
                                                "severity": "warning",
                                                "sound": direction,
                                                "ticker": item.ticker,
                                                "message": f"{item.ticker} moved {change_pct:+.1f}%",
                                                "value": change_pct,
                                                "price": price,
                                            })

                                    # Check custom price alerts (e.g. price_above, price_below)
                                    try:
                                        custom_triggered = svc._check_custom_alerts(item.ticker, metrics)
                                        for ct in custom_triggered:
                                            sound = "money_up" if ct.get("type") == "price_above" else "money_down" if ct.get("type") == "price_below" else "default"
                                            alert_events.append({
                                                "alert_type": "custom_alert_triggered",
                                                "severity": "critical",
                                                "sound": sound,
                                                "ticker": item.ticker,
                                                "message": ct.get("message") or f"Custom alert triggered for {item.ticker}",
                                                "value": ct.get("triggered_price", 0),
                                                "price": ct.get("triggered_price", 0),
                                            })
                                    except Exception:
                                        pass  # Custom alerts are best-effort

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
                                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                                    "alerts": alert_events,
                                })
                                logger.info("Broadcast %d alert events", len(alert_events))

                                # ── Telegram notifications for /watch bias preferences ──
                                for alert in alert_events:
                                    try:
                                        item_watch_reason = getattr(item, "watch_reason", None)
                                        if not item_watch_reason:
                                            continue

                                        alert_type = alert.get("alert_type")
                                        change_pct = alert.get("value", 0) if alert_type == "big_move" else 0

                                        match = False
                                        if item_watch_reason == "bullish":
                                            match = alert_type in ("bounce_confirmed", "dip_detected") or (
                                                alert_type == "big_move" and change_pct > 0
                                            )
                                        elif item_watch_reason == "bearish":
                                            match = alert_type == "bearish_warning" or (
                                                alert_type == "big_move" and change_pct < 0
                                            )

                                        if match:
                                            cooldown_key = f"{item.ticker}:{alert_type}"
                                            now = datetime.now(timezone.utc).replace(tzinfo=None)
                                            last_alert = _telegram_watch_alerted.get(cooldown_key)
                                            if last_alert and (now - last_alert).total_seconds() < 300:
                                                continue  # 5-minute cooldown

                                            _telegram_watch_alerted[cooldown_key] = now
                                            msg = (
                                                f"🔔 <b>{item.ticker}</b> — {alert.get('message', 'Signal triggered')}\n"
                                                f"Price: ${alert.get('price', 0):.2f}"
                                            )
                                            asyncio.create_task(send_telegram_alert(msg))
                                    except Exception:
                                        pass

                        except Exception as exc:
                            logger.warning("Alert check error: %s", exc)

                finally:
                    db.close()
        except Exception as exc:
            logger.error("Watchlist broadcast error: %s", exc)

        await asyncio.sleep(WATCHLIST_BROADCAST_INTERVAL)


NEWS_MOMENTUM_SCAN_INTERVAL = 45  # seconds between scans

# News Momentum Orchestrator (initialized in lifespan)
_news_momentum_orch: Optional[NewsMomentumOrchestrator] = None
# Serializes orchestrator.scan() between the periodic RSS loop and the
# event-driven Alpaca news-stream handler (both mutate candidate/cooldown state).
_news_scan_lock: Optional[asyncio.Lock] = None
# Real-time Alpaca news WebSocket listener (initialized in lifespan).
_alpaca_news_stream = None


def _get_news_scan_lock() -> asyncio.Lock:
    global _news_scan_lock
    if _news_scan_lock is None:
        _news_scan_lock = asyncio.Lock()
    return _news_scan_lock


def _news_item_classification_text(item) -> str:
    """Use source summary text for classification without changing alert copy."""
    parts = [
        getattr(item, "headline", "") or "",
        getattr(item, "description", "") or "",
        getattr(item, "summary", "") or "",
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


async def _handle_streamed_news(items) -> None:
    """Event-driven handler for real-time Alpaca news pushes.

    Builds NewsEvents from the pushed items and triggers the orchestrator
    IMMEDIATELY rather than waiting for the next periodic scan tick — this is
    where the minutes-to-seconds latency win comes from. Shares scan state with
    the periodic loop via _news_scan_lock to avoid races.
    """
    if _news_momentum_orch is None or not _news_momentum_orch.config.enabled:
        return
    try:
        from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
        from src.core.agentic.news_momentum_models import NewsEvent, NewsSource

        now_utc = datetime.now(timezone.utc)
        max_age_h = _news_momentum_orch.config.news_max_age_hours
        cutoff = now_utc - timedelta(hours=max_age_h) if max_age_h and max_age_h > 0 else None

        news_events = []
        for item in items:
            if not item.tickers or not item.headline:
                continue
            ts = item.timestamp
            # Drop items with no parseable timestamp instead of fabricating
            # "now" — stamping undated items as fresh is exactly how old news
            # (e.g. a day-old Finviz headline) gets surfaced as a live catalyst.
            if ts is None:
                continue
            ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            if cutoff is not None and ts_utc < cutoff:
                continue
            raw_text = _news_item_classification_text(item)
            classified_at = datetime.now(timezone.utc)
            cat, sub, neg, vague = classify_headline(raw_text or item.headline)
            for ticker in item.tickers:
                news_events.append(NewsEvent(
                    ticker=ticker,
                    headline=item.headline,
                    source=NewsSource.ALPACA,
                    source_url=item.url,
                    published_at=ts_utc,
                    timestamp_confidence="HIGH",
                    fetched_at=now_utc,
                    parsed_at=now_utc,
                    classified_at=classified_at,
                    catalyst_category=cat,
                    catalyst_sub_type=sub,
                    is_negative=neg,
                    is_vague=vague,
                    raw_text=raw_text,
                ))

        if not news_events:
            return

        async with _get_news_scan_lock():
            result = await _news_momentum_orch.scan(news_events)
        if result.telegram_alerts_sent > 0:
            logger.info(
                "NewsMomentum[stream]: %d real-time events → %d Telegram alerts",
                len(news_events), result.telegram_alerts_sent,
            )
    except Exception as exc:
        logger.warning("NewsMomentum[stream]: handler error: %s", exc)


async def _sec_edgar_firehose_loop():
    """Poll EDGAR's global 8-K feed and push fresh filings into the alert path.

    Material 8-Ks (M&A, FDA, big contracts) often hit EDGAR before the PR wire,
    so this is a low-latency catalyst source. New filings are fed through the
    same orchestrator.scan() path (under _news_scan_lock) as the news streams.
    Capped per poll so it doesn't blow the free-tier market-data quotas.
    """
    await asyncio.sleep(30)  # let the app settle after startup
    if _news_momentum_orch is None or not _news_momentum_orch.config.enabled:
        return
    if os.getenv("SEC_FIREHOSE_ENABLED", "true").lower() in ("0", "false", "no"):
        logger.info("SEC EDGAR firehose disabled by env")
        return

    import httpx
    from src.core.agentic.sec_edgar_fetcher import SEC_USER_AGENT
    from src.core.agentic.sec_edgar_firehose import (
        enrich_filing_content,
        fetch_current_filings,
        load_seen_accessions,
        save_seen_accessions,
    )
    from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
    from src.core.agentic.news_momentum_models import NewsEvent, NewsSource

    seen: set[str] = load_seen_accessions()
    poll_interval = int(os.getenv("SEC_FIREHOSE_INTERVAL_SECONDS", "15") or 15)
    max_per_poll = int(os.getenv("SEC_FIREHOSE_MAX_PER_POLL", "15") or 15)
    feed_count = int(os.getenv("SEC_FIREHOSE_FEED_COUNT", "200") or 200)
    initial_lookback = int(os.getenv("SEC_FIREHOSE_INITIAL_LOOKBACK_MINUTES", "30") or 30)
    client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": SEC_USER_AGENT})
    logger.info("SEC EDGAR 8-K firehose started (every %ds, cap %d/poll)", poll_interval, max_per_poll)
    try:
        while True:
            try:
                filings = await fetch_current_filings(
                    seen,
                    form="8-K",
                    count=feed_count,
                    max_to_emit=max_per_poll,
                    client=client,
                    initial_emit_lookback_minutes=initial_lookback,
                )
                save_seen_accessions(seen)
                if filings:
                    events = []
                    for f in filings:
                        fetched_at = datetime.now(timezone.utc)
                        f = await enrich_filing_content(f, client)
                        headline = f.get("headline") or f"{f['company']} filed SEC Form 8-K"
                        classified_at = datetime.now(timezone.utc)
                        cat, sub, neg, vague = classify_headline(headline)
                        events.append(NewsEvent(
                            ticker=f["ticker"],
                            headline=headline,
                            source=NewsSource.SEC,
                            source_url=f["url"],
                            published_at=f["published_at"],
                            fetched_at=fetched_at,
                            parsed_at=fetched_at,
                            classified_at=classified_at,
                            catalyst_category=cat,
                            catalyst_sub_type=sub,
                            is_negative=neg,
                            is_vague=vague,
                        ))
                    if events:
                        async with _get_news_scan_lock():
                            result = await _news_momentum_orch.scan(events)
                        if result.telegram_alerts_sent > 0:
                            logger.info(
                                "SEC firehose: %d new 8-Ks → %d Telegram alerts",
                                len(events), result.telegram_alerts_sent,
                            )
            except Exception as exc:
                logger.debug("SEC firehose loop error: %s", exc)
            await asyncio.sleep(poll_interval)
    finally:
        await client.aclose()


async def _news_momentum_scan_loop():
    """Background task: scan for news-driven momentum candidates."""
    global _news_momentum_orch
    await asyncio.sleep(20)  # Wait 20s after startup

    # Reuse scraper instances across iterations so the 5-minute cache is effective
    _finviz_scraper: Optional[Any] = None
    _stocktitan_scraper: Optional[Any] = None
    _prnewswire_scraper: Optional[Any] = None
    _sharecast_scraper: Optional[Any] = None
    _wire_scraper: Optional[Any] = None
    _finviz_news_scraper: Optional[Any] = None
    # Heartbeat: log every N iterations so we can confirm the loop is alive
    # even when no new events are detected. Without this, an audit of the
    # event registry can't distinguish "loop running but no new news" from
    # "loop dead / server restarted." Log at INFO every ~5 minutes.
    _iter_count = 0
    _missing_ts_count = 0
    _stale_news_count = 0
    _untickered_news_count = 0
    from src.core.agentic.source_health_registry import source_health_tracker as _source_health

    while True:
        _iter_count += 1
        try:
            if _news_momentum_orch and _news_momentum_orch.config.enabled:
                # Fetch fresh news from existing scrapers
                news_events = []
                from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
                from src.core.agentic.news_momentum_models import NewsEvent, NewsSource
                from src.core.agentic.news_momentum_utils import deduplicate_news_items

                # Lazily initialize scrapers once
                if _finviz_scraper is None:
                    from src.core.finviz_news import FinvizNewsScraper
                    _finviz_scraper = FinvizNewsScraper()
                if _stocktitan_scraper is None:
                    from src.core.stocktitan_news import StockTitanScraper
                    _stocktitan_scraper = StockTitanScraper()
                if _prnewswire_scraper is None:
                    from src.core.prnewswire_news import PRNewswireScraper
                    _prnewswire_scraper = PRNewswireScraper()
                if _sharecast_scraper is None:
                    from src.core.sharecast_news import SharecastScraper
                    _sharecast_scraper = SharecastScraper()
                if _wire_scraper is None:
                    from src.core.wire_news import WireNewsScraper
                    _wire_scraper = WireNewsScraper()

                all_items: List[Any] = []
                source_timeout = float(os.getenv("NEWS_SOURCE_FETCH_TIMEOUT_SECONDS", "12") or 12)

                async def _fetch_source(source_name: str, fetch_coro):
                    try:
                        summary = await asyncio.wait_for(fetch_coro(), timeout=source_timeout)
                        fetched_at = datetime.now(timezone.utc)
                        items = (getattr(summary, "news_items", None) or []) + (getattr(summary, "blog_items", None) or [])
                        for item in items:
                            try:
                                setattr(item, "fetched_at", fetched_at)
                                setattr(item, "parsed_at", fetched_at)
                            except Exception:
                                pass
                        return source_name, summary, items, None
                    except Exception as exc:
                        return source_name, None, [], exc

                source_results = await asyncio.gather(
                    _fetch_source("Finviz", lambda: _finviz_scraper.fetch_all(force_refresh=True)),
                    _fetch_source("StockTitan", _stocktitan_scraper.fetch_all),
                    _fetch_source("PRNewswire", _prnewswire_scraper.fetch_all),
                    _fetch_source("Sharecast", _sharecast_scraper.fetch_all),
                    _fetch_source("WireNews", _wire_scraper.fetch_all),
                )

                for source_name, summary, items, exc in source_results:
                    if exc is not None:
                        _source_health.record_parse_error(source_name, now=datetime.now(timezone.utc))
                        logger.warning("NewsMomentum: %s fetch error: %s", source_name, exc)
                        continue

                    if source_name == "WireNews":
                        by_source: dict[str, int] = {}
                        for item in items:
                            item_source = getattr(item, "source", "WireNews") or "WireNews"
                            by_source[item_source] = by_source.get(item_source, 0) + 1
                        if not by_source:
                            _source_health.record_fetch("WireNews", 0, now=datetime.now(timezone.utc))
                        for source, count in by_source.items():
                            _source_health.record_fetch(source, count, now=datetime.now(timezone.utc))
                    else:
                        _source_health.record_fetch(source_name, len(items), now=datetime.now(timezone.utc))
                    for failed_source, count in getattr(summary, "failed_sources", {}).items():
                        for _ in range(int(count or 0)):
                            _source_health.record_parse_error(failed_source, now=datetime.now(timezone.utc))
                    all_items.extend(items)

                # Deduplicate across sources before emitting events
                all_items = deduplicate_news_items(all_items)

                # News-freshness cutoff: feeds carry 24-48h of items, so a stale
                # story lingering in the feed would otherwise be re-detected as
                # "new" each scan (detected_at defaults to now) and re-alerted
                # every cooldown cycle. Drop anything published before the cutoff.
                _now_utc = datetime.now(timezone.utc)
                _max_age_h = _news_momentum_orch.config.news_max_age_hours
                _news_cutoff = _now_utc - timedelta(hours=_max_age_h) if _max_age_h and _max_age_h > 0 else None

                def _is_stale(ts) -> bool:
                    if _news_cutoff is None or ts is None:
                        return False
                    try:
                        ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                        return ts_utc < _news_cutoff
                    except Exception:
                        return False

                for item in all_items:
                    if not item.tickers:
                        _untickered_news_count += 1
                        _source_health.record_untickered_headline(getattr(item, "source", "unknown") or "unknown")
                        continue
                    _source_health.record_tickered_headline(getattr(item, "source", "unknown") or "unknown")
                    # Drop items with no parseable timestamp rather than
                    # fabricating "now" — silently stamping unknown items as
                    # fresh corrupts the calibrator, expected-return model,
                    # and the user-facing "Xm ago" labels. We count drops so
                    # the heartbeat can surface parser regressions.
                    if item.timestamp is None:
                        _missing_ts_count += 1
                        _source_health.record_missing_timestamp(getattr(item, "source", "unknown") or "unknown")
                        continue
                    # Skip stale headlines so old news never re-pings Telegram.
                    if _is_stale(item.timestamp):
                        _stale_news_count += 1
                        _source_health.record_dropped_headline(getattr(item, "source", "unknown") or "unknown")
                        continue
                    _source_health.record_latency(
                        getattr(item, "source", "unknown") or "unknown",
                        item.timestamp,
                        detected_at=_now_utc,
                    )
                    raw_text = _news_item_classification_text(item)
                    classified_at = datetime.now(timezone.utc)
                    cat, sub, neg, vague = classify_headline(raw_text or item.headline)
                    source_name = getattr(item, "source", "")
                    if source_name == "StockTitan":
                        source_enum = NewsSource.STOCKTITAN
                    elif source_name == "PRNewswire":
                        source_enum = NewsSource.PR_NEWSWIRE
                    elif source_name == "Sharecast":
                        source_enum = NewsSource.SHARECAST
                    elif source_name == "GlobeNewswire":
                        source_enum = NewsSource.GLOBE_NEWSWIRE
                    elif source_name == "BusinessWire":
                        source_enum = NewsSource.BUSINESS_WIRE
                    elif source_name == "Accesswire":
                        source_enum = NewsSource.ACCESSWIRE
                    elif source_name == "Newsfile":
                        source_enum = NewsSource.NEWSFILE
                    else:
                        source_enum = NewsSource.FINVIZ
                    for ticker in item.tickers:
                        news_events.append(NewsEvent(
                            ticker=ticker,
                            headline=item.headline,
                            source=source_enum,
                            source_url=item.url,
                            published_at=item.timestamp,
                            timestamp_confidence=getattr(item, "timestamp_confidence", "HIGH") or "HIGH",
                            fetched_at=getattr(item, "fetched_at", None),
                            parsed_at=getattr(item, "parsed_at", None),
                            classified_at=classified_at,
                            catalyst_category=cat,
                            catalyst_sub_type=sub,
                            is_negative=neg,
                            is_vague=vague,
                            raw_text=raw_text,
                        ))

                if news_events:
                    async with _get_news_scan_lock():
                        result = await _news_momentum_orch.scan(news_events)
                    if result.candidates or result.telegram_alerts_sent > 0:
                        logger.info(
                            "NewsMomentum: global scan found %d candidates, sent %d Telegram alerts",
                            len(result.candidates), result.telegram_alerts_sent,
                        )

                ticker_news_events = []

                # ── Ticker-specific quote-page news (catches items not in the global feed) ──
                try:
                    from src.core.agentic.finviz_universe import (
                        fetch_finviz_top_gainer_tickers,
                        fetch_finviz_under2_high_volume_tickers,
                    )
                    from src.core.finviz_news import FinvizNewsScraper

                    if _finviz_news_scraper is None:
                        _finviz_news_scraper = FinvizNewsScraper()

                    # Collect hot tickers from Finviz gainers + under-$2 screener.
                    # Preserve screener order so the highest-priority movers are
                    # enriched first under the strict latency budget.
                    hot_tickers: list[str] = []
                    hot_seen: set[str] = set()

                    def _add_hot_tickers(tickers: list[str]) -> None:
                        for raw in tickers or []:
                            ticker = str(raw or "").strip().upper()
                            if ticker and ticker not in hot_seen:
                                hot_seen.add(ticker)
                                hot_tickers.append(ticker)

                    try:
                        # Discovery should not depend on yfinance validation.
                        # A transient quote/history failure can wrongly shrink
                        # the ticker-specific enrichment universe.
                        gainers = fetch_finviz_top_gainer_tickers(validate=False)
                        _add_hot_tickers(gainers)
                    except Exception as exc:
                        _source_health.record_parse_error("FinvizTickerUniverse", now=datetime.now(timezone.utc))
                        logger.warning("NewsMomentum: Finviz top-gainer ticker discovery failed: %s", exc)
                    try:
                        under2 = fetch_finviz_under2_high_volume_tickers(validate=False)
                        _add_hot_tickers(under2)
                    except Exception as exc:
                        _source_health.record_parse_error("FinvizTickerUniverse", now=datetime.now(timezone.utc))
                        logger.warning("NewsMomentum: Finviz under-$2 ticker discovery failed: %s", exc)

                    # Already seen headlines from global feed so we don't dup
                    seen_headlines = {e.headline.lower().strip() for e in news_events}
                    enrichment_budget = float(os.environ.get("FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS", "6") or 6)
                    enrichment_deadline = asyncio.get_running_loop().time() + max(0.5, enrichment_budget)

                    for ticker in hot_tickers[:30]:
                        try:
                            remaining = enrichment_deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                logger.debug("NewsMomentum: ticker-specific enrichment budget exhausted")
                                break
                            ticker_items = await asyncio.wait_for(
                                _finviz_news_scraper.fetch_ticker_news(ticker, force_refresh=True),
                                timeout=max(0.1, min(1.5, remaining)),
                            )
                            ticker_fetched_at = datetime.now(timezone.utc)
                            for fetched_item in ticker_items:
                                try:
                                    setattr(fetched_item, "fetched_at", ticker_fetched_at)
                                    setattr(fetched_item, "parsed_at", ticker_fetched_at)
                                except Exception:
                                    pass
                            for item in ticker_items:
                                if not item.tickers:
                                    continue
                                h_norm = item.headline.lower().strip()
                                if h_norm in seen_headlines:
                                    continue
                                seen_headlines.add(h_norm)
                                if item.timestamp is None:
                                    _missing_ts_count += 1
                                    _source_health.record_missing_timestamp("FinvizTickerNews")
                                    continue
                                if _is_stale(item.timestamp):
                                    _stale_news_count += 1
                                    _source_health.record_dropped_headline("FinvizTickerNews")
                                    continue
                                raw_text = _news_item_classification_text(item)
                                classified_at = datetime.now(timezone.utc)
                                cat, sub, neg, vague = classify_headline(raw_text or item.headline)
                                for t in item.tickers:
                                    ticker_news_events.append(NewsEvent(
                                        ticker=t,
                                        headline=item.headline,
                                        source=NewsSource.FINVIZ,
                                        source_url=item.url,
                                        published_at=item.timestamp,
                                        timestamp_confidence=getattr(item, "timestamp_confidence", "HIGH") or "HIGH",
                                        fetched_at=getattr(item, "fetched_at", None),
                                        parsed_at=getattr(item, "parsed_at", None),
                                        classified_at=classified_at,
                                        catalyst_category=cat,
                                        catalyst_sub_type=sub,
                                        is_negative=neg,
                                        is_vague=vague,
                                        raw_text=raw_text,
                                    ))
                        except asyncio.TimeoutError:
                            _source_health.record_parse_error("FinvizTickerNews", now=datetime.now(timezone.utc))
                            logger.warning("NewsMomentum: ticker-specific news timeout for %s", ticker)
                        except Exception as exc:
                            _source_health.record_parse_error("FinvizTickerNews", now=datetime.now(timezone.utc))
                            logger.warning("NewsMomentum: ticker-specific news failed for %s: %s", ticker, exc)

                    if hot_tickers:
                        logger.debug(
                            "NewsMomentum: added ticker-specific news for %d hot tickers",
                            len(hot_tickers),
                        )
                except Exception as exc:
                    logger.debug("NewsMomentum: ticker-specific news fetch error: %s", exc)

                if ticker_news_events:
                    async with _get_news_scan_lock():
                        result = await _news_momentum_orch.scan(ticker_news_events)
                    if result.candidates or result.telegram_alerts_sent > 0:
                        logger.info(
                            "NewsMomentum: ticker-enrichment scan found %d candidates, sent %d Telegram alerts",
                            len(result.candidates), result.telegram_alerts_sent,
                        )

                # Adaptive interval based on session
                session = _news_momentum_orch._detect_session()
                if session.value == "regular":
                    interval = _news_momentum_orch.config.scan_interval_seconds
                else:
                    interval = _news_momentum_orch.config.low_activity_interval_seconds
            else:
                interval = NEWS_MOMENTUM_SCAN_INTERVAL
        except Exception as exc:
            logger.error("NewsMomentum scan loop error: %s", exc)
            interval = NEWS_MOMENTUM_SCAN_INTERVAL

        # Heartbeat: log roughly every 5 min so the operator can confirm the
        # scan loop is alive between detection bursts. Also surface how many
        # items the parsers dropped for lacking a timestamp — a sudden jump
        # is a strong signal of a Finviz/StockTitan layout change.
        if _iter_count % max(1, int(300 / max(1, interval))) == 0:
            logger.info(
                "NewsMomentum heartbeat: iter=%d interval=%ds untickered_dropped=%d missing_ts_dropped=%d stale_news_dropped=%d",
                _iter_count, interval, _untickered_news_count, _missing_ts_count, _stale_news_count,
            )
            for warning in _source_health.evaluate(now=datetime.now(timezone.utc)):
                logger.warning("News source health: %s", warning)
                asyncio.create_task(send_telegram_alert(
                    f"Oracle source health warning: {warning}",
                    alert_type="source_health",
                    priority=1,
                ))

        await asyncio.sleep(interval)


async def _news_momentum_eod_review_loop():
    """Run EOD review once daily after market close (21:30 UTC = 17:30 ET).

    Sleeps until next scheduled run, then triggers Finviz top-gainers analysis
    to detect missed discoveries and missed alerts.
    """
    global _news_momentum_orch
    from datetime import datetime, timezone, timedelta

    # Wait for orchestrator to be ready
    await asyncio.sleep(60)

    while True:
        try:
            now = datetime.now(timezone.utc)
            # Target 21:30 UTC daily (17:30 ET, ~30min after close)
            target = now.replace(hour=21, minute=30, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            sleep_seconds = (target - now).total_seconds()
            logger.info("EOD review scheduled in %.1f hours (%s UTC)", sleep_seconds / 3600, target.isoformat())
            await asyncio.sleep(sleep_seconds)

            if _news_momentum_orch is None:
                logger.warning("EOD review skipped — orchestrator not initialized")
                continue

            reviewer = _news_momentum_orch.get_eod_reviewer()
            result = await reviewer.run_review()
            logger.info("EOD review result: %s", result.get("summary", result))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("EOD review loop error: %s", exc)
            await asyncio.sleep(3600)  # back off 1h on error


# ── Outcome Resolver + ML Retrain ──────────────────────────────────────────
NEWS_MOMENTUM_RESOLVER_INTERVAL = 30 * 60  # 30 minutes


async def _news_momentum_outcome_resolver_loop():
    """Background task: every 30 minutes, fetch follow-up prices for sent
    Telegram alerts and resolve their outcomes (auto-label as win/loss).

    This is the feedback loop that feeds the ML engine its training data.
    """
    global _news_momentum_orch
    await asyncio.sleep(120)  # let everything settle on startup
    while True:
        try:
            if _news_momentum_orch is not None:
                resolver = _news_momentum_orch.get_outcome_resolver()
                summary = await resolver.run_once()
                if summary.get("resolved", 0) > 0 or summary.get("updated", 0) > 0:
                    logger.info("OutcomeResolver: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("OutcomeResolver loop error: %s", exc)
        await asyncio.sleep(NEWS_MOMENTUM_RESOLVER_INTERVAL)


async def _news_momentum_ml_retrain_loop():
    """Background task: weekly retrain of the news-momentum ML model.

    Runs every Sunday at 02:00 UTC. Auto-promotes the new model if it's at
    least as good as the current one (within tolerance). Sends a brief
    Telegram summary so the user knows the model improved.
    """
    global _news_momentum_orch
    from datetime import datetime, timezone, timedelta

    # Wait for orchestrator + outcome resolver to settle
    await asyncio.sleep(180)

    while True:
        try:
            now = datetime.now(timezone.utc)
            # Compute next Sunday 02:00 UTC
            days_until_sun = (6 - now.weekday()) % 7
            target = (now + timedelta(days=days_until_sun)).replace(
                hour=2, minute=0, second=0, microsecond=0,
            )
            if target <= now:
                target += timedelta(days=7)
            sleep_seconds = (target - now).total_seconds()
            logger.info(
                "ML retrain scheduled in %.1f hours (%s UTC)",
                sleep_seconds / 3600, target.isoformat(),
            )
            await asyncio.sleep(sleep_seconds)

            if _news_momentum_orch is None:
                logger.warning("ML retrain skipped — orchestrator not initialized")
                continue

            result = _news_momentum_orch.retrain_ml()
            logger.info(
                "ML retrain: success=%s samples=%d auc=%.3f promoted=%s reason=%s",
                result.success, result.samples, result.auc, result.promoted, result.reason,
            )

            # Telegram summary on every retrain attempt
            try:
                from src.services.telegram_service import send_telegram_alert
                if result.success:
                    status_emoji = "✅" if result.promoted else "⚠️"
                    status_text = "PROMOTED" if result.promoted else "TRAINED (not promoted)"
                    top = ", ".join(
                        f"{name}:{w:.2f}" for name, w in result.feature_importance[:5]
                    ) if result.feature_importance else "n/a"
                    drift = ""
                    if "drift_detected" in result.reason:
                        drift = "\n<b>⚠️ Model drift detected!</b>"
                    cv_str = ""
                    # CV info is stored in the result as extra attributes via meta;
                    # check orchestrator's meta dict if accessible, otherwise skip.
                    orch = _news_momentum_orch
                    if orch and orch._ml_engine:
                        meta = orch._ml_engine._meta
                        cv_mean = meta.get("cv_auc_mean", 0)
                        cv_std = meta.get("cv_auc_std", 0)
                        if cv_mean > 0:
                            cv_str = f"\nCV AUC: {cv_mean:.3f} (±{cv_std:.3f})"
                    missed = getattr(result, "reason", "")
                    missed_injected = 0
                    if orch and orch._ml_engine:
                        missed_injected = orch._ml_engine._meta.get("missed_injected", 0)
                    missed_str = f"\nMissed winners injected: {missed_injected}" if missed_injected else ""
                    msg = (
                        f"<b>{status_emoji} News Momentum ML {status_text}</b>\n"
                        f"Version: <code>{result.model_version}</code>\n"
                        f"Samples: {result.samples}{missed_str}\n"
                        f"AUC: {result.auc:.3f}  Test acc: {result.test_accuracy:.1%}{cv_str}\n"
                        f"Win-rate baseline: {result.win_rate_baseline:.1%}\n"
                        f"Top predictors: {top}{drift}"
                    )
                else:
                    msg = (
                        "<b>📊 News Momentum ML Training</b>\n"
                        f"Status: <i>Not enough data yet</i>\n"
                        f"Samples: {result.samples}\n"
                        f"Reason: {result.reason}"
                    )
                await send_telegram_alert(msg, parse_mode="HTML")
            except Exception as exc:
                logger.debug("ML retrain telegram summary failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("ML retrain loop error: %s", exc)
            await asyncio.sleep(3600)


SEC_INTELLIGENCE_INTERVAL = 60 * 60  # 1 hour


async def _sec_intelligence_scan_loop():
    """Background task: hourly SEC filing scan for active candidates.

    Refreshes structural scores (dilution probability, toxic financing,
    warrant overhang, etc.) so the momentum gate has up-to-date data.
    Safe on network failures — the SEC engine degrades gracefully.
    """
    global _news_momentum_orch
    # Wait for momentum orchestrator to settle and pick up candidates
    await asyncio.sleep(120)
    while True:
        try:
            if _news_momentum_orch is None:
                await asyncio.sleep(SEC_INTELLIGENCE_INTERVAL)
                continue
            scanned = await _news_momentum_orch.scan_sec_for_candidates(max_tickers=25)
            logger.info("SEC Intelligence: scanned %d tickers", scanned)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("SEC Intelligence scan loop error: %s", exc)
        await asyncio.sleep(SEC_INTELLIGENCE_INTERVAL)


_background_tasks: set[asyncio.Task] = set()


def _spawn(coro, name: str | None = None) -> asyncio.Task:
    """Create a background task and keep a strong reference to it.

    asyncio only holds weak references to tasks, so an untracked task can be
    garbage-collected mid-flight. Registering here also lets the lifespan
    cancel + drain every loop on shutdown instead of killing them abruptly.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Oracle V5 starting (env=%s)", settings.app_env)
    _log_lean_mode_status(settings)

    # Persistence guard (Railway P0): fail loudly rather than silently losing all
    # agentic state on the next redeploy/restart if no volume is mounted.
    verify_persistent_data_dir()
    data_dir = agentic_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Agentic data dir: %s", data_dir.resolve())

    # Seed baseline artifacts (ML model, company-name map) into an empty/restored
    # volume. Never overwrites live state.
    try:
        seeded = seed_agentic_data_dir()
        if seeded:
            logger.info("Seeded %d baseline artifact(s): %s", len(seeded), seeded)
    except Exception as exc:
        logger.warning("Baseline seeding skipped: %s", exc)

    # Create tables if they don't exist (preserves data across restarts)
    Base.metadata.create_all(bind=engine, checkfirst=True)
    logger.info("Database tables ensured")

    sim_task = None
    if settings.legacy_outcome_simulator_enabled:
        sim_task = _spawn(_outcome_simulator_loop(), "outcome_simulator")
        logger.info("Background outcome simulator started (interval=%ds)", SIMULATOR_INTERVAL_SECONDS)
    else:
        logger.info("Background outcome simulator disabled by lean-mode flags")

    # DISABLED: Agentic outcome simulator (not actively traded)
    # agentic_outcome_task = asyncio.create_task(_agentic_outcome_loop())
    # logger.info("Agentic outcome simulator started (interval=%ds)", AGENTIC_OUTCOME_INTERVAL)

    # Stagger background loops to avoid thundering-herd of quote requests
    async def _delayed_start(coro_factory, delay_sec: float, name: str):
        await asyncio.sleep(delay_sec)
        _spawn(coro_factory(), name)
        logger.info("%s started (staggered +%.1fs)", name, delay_sec)

    if settings.watchlist_enabled:
        _spawn(_watchlist_broadcast_loop(), "watchlist_broadcast")
        logger.info("Watchlist real-time broadcaster started")
    else:
        logger.info("Watchlist real-time broadcaster disabled by lean-mode flags")

    if settings.paper_trading_system_enabled:
        _spawn(_delayed_start(_paper_trading_price_loop, 2.0, "Paper trading price updater"))
    else:
        logger.info("Paper trading price updater disabled by lean-mode flags")

    _spawn(_delayed_start(_pre_news_scan_loop, 4.0, "Pre-news volume anomaly scanner"))

    # Start Telegram command polling (+1s)
    _spawn(_delayed_start(telegram_command_polling_loop, 1.0, "Telegram command polling"))
    _spawn(_delayed_start(telegram_outbox_sender_loop, 2.5, "Telegram outbox sender"))

    # Startup: initialize News Momentum Orchestrator
    global _news_momentum_orch
    try:
        from src.api.routes.news_momentum import set_orchestrator
        _news_momentum_orch = NewsMomentumOrchestrator()
        set_orchestrator(_news_momentum_orch)
        logger.info("News Momentum Intelligence System initialized")
    except Exception as exc:
        logger.warning("NewsMomentum init failed: %s", exc)

    # Startup: share SEC Intelligence orchestrator instance with the API
    # so /api/v1/sec-intelligence and the momentum engine use the same state.
    try:
        from src.api.routes.sec_intelligence import set_orchestrator as _set_sec_orch
        if _news_momentum_orch is not None and _news_momentum_orch.get_sec_intelligence() is not None:
            _set_sec_orch(_news_momentum_orch.get_sec_intelligence())
            logger.info("SEC Filing Intelligence orchestrator wired to API (V23)")
    except Exception as exc:
        logger.warning("SEC Intelligence wiring failed: %s", exc)

    # Start real-time Alpaca news WebSocket — event-driven alerting that fires
    # within seconds of the wire, instead of waiting on the periodic RSS loop.
    global _alpaca_news_stream
    try:
        if _news_momentum_orch is not None:
            from src.services.alpaca_news_stream import AlpacaNewsStream
            _alpaca_news_stream = AlpacaNewsStream(on_news=_handle_streamed_news)
            if _alpaca_news_stream.start(main_loop=asyncio.get_running_loop()):
                logger.info("Alpaca real-time news stream started (event-driven alerts)")
            else:
                _alpaca_news_stream = None
                logger.info("Alpaca news stream not started (no creds/SDK) — RSS polling only")
    except Exception as exc:
        logger.warning("Alpaca news stream init failed: %s", exc)

    # Start news momentum scan loop (+6s — after all other loops)
    _spawn(_delayed_start(_news_momentum_scan_loop, 6.0, "News momentum scan loop"))

    # Start SEC EDGAR 8-K firehose — low-latency filing-driven catalysts
    _spawn(_delayed_start(_sec_edgar_firehose_loop, 8.0, "SEC EDGAR 8-K firehose"))

    # Start EOD review loop (runs daily at 21:30 UTC)
    _spawn(_news_momentum_eod_review_loop(), "news_momentum_eod_review")
    logger.info("News momentum EOD review loop scheduled (daily at 21:30 UTC)")

    # Start outcome resolver loop (every 30 min)
    _spawn(_news_momentum_outcome_resolver_loop(), "news_momentum_outcome_resolver")
    logger.info("News momentum outcome resolver loop scheduled (every 30 min)")

    # Start ML retrain loop (weekly Sunday 02:00 UTC)
    _spawn(_news_momentum_ml_retrain_loop(), "news_momentum_ml_retrain")
    logger.info("News momentum ML retrain loop scheduled (weekly Sunday 02:00 UTC)")

    # DISABLED: SEC Intelligence hourly scan loop (not actively used)
    # asyncio.create_task(_sec_intelligence_scan_loop())
    # logger.info("SEC Filing Intelligence scan loop scheduled (every 1h)")

    yield

    # Shutdown — cancel and drain every background loop we spawned, so in-flight
    # work is given a chance to unwind instead of being killed abruptly.
    logger.info("Oracle V5 shutting down — cancelling %d background task(s)", len(_background_tasks))
    for task in list(_background_tasks):
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    if _alpaca_news_stream is not None:
        try:
            _alpaca_news_stream.stop()
        except Exception:
            pass
    logger.info("Oracle V5 shutting down")


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
    # Auth is a bearer token in the Authorization header and the frontend is
    # served same-origin from frontend/dist/, so credentialed CORS is never
    # needed. allow_origins=["*"] + allow_credentials=True is invalid per the
    # CORS spec (Starlette would reflect any Origin); keep credentials off.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    FrontendAuthMiddleware,
    enabled=get_settings().oracle_frontend_auth_enabled,
)

# ── Routes ───────────────────────────────────────────────────────────────────

_route_settings = get_settings()


def _include_optional_legacy_router(module_name: str, *, prefix: str = "/api/v1") -> bool:
    """Include a legacy router only if its archived module still exists."""
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        logger.warning("Legacy router unavailable (%s): %s", module_name, exc)
        return False

    router = getattr(module, "router", None)
    if router is None:
        logger.warning("Legacy router module has no router (%s)", module_name)
        return False
    app.include_router(router, prefix=prefix)
    return True


app.include_router(health.router)
app.include_router(frontend_auth.router, prefix="/api/v1")
if _route_settings.scanner_routes_enabled:
    _include_optional_legacy_router("src.api.routes.scanner")
if _route_settings.legacy_signals_enabled:
    _include_optional_legacy_router("src.api.routes.signals")
if _route_settings.watchlist_enabled:
    _include_optional_legacy_router("src.api.routes.watchlist")
if _route_settings.dip_bounce_enabled:
    _include_optional_legacy_router("src.api.routes.models")
if _route_settings.analysis_routes_enabled:
    _include_optional_legacy_router("src.api.routes.analysis")
if _route_settings.backtest_enabled:
    _include_optional_legacy_router("src.api.routes.backtest")
if _route_settings.intelligence_routes_enabled:
    _include_optional_legacy_router("src.api.routes.intelligence")
app.include_router(news.router, prefix="/api/v1")
if _route_settings.htf_routes_enabled:
    _include_optional_legacy_router("src.api.routes.htf_scan")  # V9: HTF-Aware Scanner
if _route_settings.paper_trading_system_enabled:
    _include_optional_legacy_router("src.api.routes.paper_trading")  # V10: Paper Trading + Validation + Calibration
app.include_router(agentic.router, prefix="/api/v1")  # V11: Agentic Catalyst Momentum Mode
app.include_router(pre_news.router, prefix="/api/v1")  # Pre-News Volume Anomaly Detector
app.include_router(historical_training.router, prefix="/api/v1")  # Historical Catalyst Training Engine
app.include_router(news_momentum.router, prefix="/api/v1")  # V22: News Momentum Intelligence System
app.include_router(timing_reviews.router, prefix="/api/v1")  # Timing Intelligence reviews
app.include_router(sec_intelligence.router, prefix="/api/v1")  # V23: SEC Filing Intelligence & Dilution Risk Engine
app.include_router(admin_diagnostics.router, prefix="/api/v1")  # Admin Diagnostics (read-only observability)


# ── WebSocket — real-time signal streaming ──────────────────────────────────

class ConnectionManager:
    """Thread-safe WebSocket connection manager with unclean-disconnect handling."""

    def __init__(self):
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        logger.info("WS client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass
        logger.info("WS client disconnected (%d total)", len(self._clients))

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)

    async def broadcast(self, data: dict) -> None:
        payload = json.dumps(data, default=str)
        dead = []
        # Snapshot under lock so we don't race with connect/disconnect
        async with self._lock:
            clients = self._clients[:]
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self._clients.remove(ws)
                    except ValueError:
                        pass


_signal_mgr = ConnectionManager()
_watchlist_mgr = ConnectionManager()


if _route_settings.legacy_signals_enabled:
    @app.websocket("/ws/signals")
    async def websocket_signals(ws: WebSocket):
        await _signal_mgr.connect(ws)
        try:
            while True:
                await ws.receive_text()  # keep-alive
        except Exception:
            # Any exception (WebSocketDisconnect, ConnectionClosedError, RuntimeError, OSError)
            # means the client is gone — clean up regardless.
            pass
        finally:
            await _signal_mgr.disconnect(ws)


if _route_settings.watchlist_enabled:
    @app.websocket("/ws/watchlist")
    async def websocket_watchlist(ws: WebSocket):
        """Real-time watchlist price updates."""
        await _watchlist_mgr.connect(ws)
        try:
            while True:
                await ws.receive_text()  # keep-alive
        except Exception:
            pass
        finally:
            await _watchlist_mgr.disconnect(ws)


async def broadcast_signals(data: dict):
    """Push signal updates to all connected WebSocket clients."""
    await _signal_mgr.broadcast(data)


async def broadcast_watchlist(data: dict):
    """Push watchlist updates to all connected clients."""
    await _watchlist_mgr.broadcast(data)


# ── Static frontend (serve built React app) ─────────────────────────────────

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
frontend_assets = os.path.join(frontend_dist, "assets")
frontend_index = os.path.join(frontend_dist, "index.html")

if os.path.isdir(frontend_dist) and os.path.isfile(frontend_index):
    if os.path.isdir(frontend_assets):
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")

    _FRONTEND_INDEX_HEADERS = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        requested = os.path.abspath(os.path.join(frontend_dist, full_path))
        if requested.startswith(frontend_dist) and os.path.isfile(requested):
            if requested == frontend_index:
                return FileResponse(requested, headers=_FRONTEND_INDEX_HEADERS)
            return FileResponse(requested)
        return FileResponse(frontend_index, headers=_FRONTEND_INDEX_HEADERS)
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
