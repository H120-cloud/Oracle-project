"""
Telegram Command Handler

Polls the Telegram Bot API getUpdates endpoint and handles commands:
  /analysis TICKER  - Full stock analysis with price, volume, regime, stage, order flow
  /orderflow TICKER - Quick buy/sell order flow snapshot
  /status TICKER    - Show latest alert/cooldown/block status for a ticker
  /help             - Show available commands

Runs as a background task in the FastAPI lifespan.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from src.config import get_settings
from src.services.telegram_service import _get_config, TELEGRAM_API, TIMEOUT

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3.0  # seconds between polls
ANALYSIS_TIMEOUT = 30.0  # seconds for analysis to complete
from src.utils.data_paths import AGENTIC_DATA_DIR

_settings = get_settings()
LEGACY_TELEGRAM_COMMANDS_ENABLED = not _settings.oracle_lean_mode
TELEGRAM_WATCH_COMMAND_ENABLED = _settings.watchlist_enabled


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

async def send_telegram_message(chat_id: str, text: str) -> bool:
    """Send a message to a specific chat ID.

    HTML body is sanitized so stray `<`, `>`, `&` in scraped headlines or
    user-supplied tickers (e.g. `/analysis A&B`) don't blow up Telegram's
    HTML parser with a 400 'can't parse entities'. Mirrors what
    `send_telegram_alert` already does.
    """
    token, _ = _get_config()
    if not token:
        return False

    # Defer the import to keep telegram_service the canonical sanitizer.
    from src.services.telegram_service import _sanitize_html
    text = _sanitize_html(text)

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                # Don't swallow silently — the Telegram body usually tells us
                # exactly why parsing failed (entity, offset, etc.).
                logger.warning(
                    "Telegram sendMessage %s: %s",
                    resp.status_code, resp.text[:200],
                )
            return resp.status_code == 200
    except Exception as e:
        logger.warning("Failed to send Telegram message: %s", e)
        return False


# ---------------------------------------------------------------------------
# Analysis runners (synchronous — executed in thread pool)
# ---------------------------------------------------------------------------

def _run_analysis(ticker: str) -> dict:
    """Run complete analysis synchronously."""
    from src.services.market_data import get_market_data_provider
    from src.core.volume_profile import VolumeProfileEngine
    from src.core.regime_detector import RegimeDetector
    from src.core.stage_detector import StageDetector

    try:
        from src.core.order_flow import OrderFlowAnalyzer
        has_orderflow = True
    except ImportError:
        OrderFlowAnalyzer = None
        has_orderflow = False

    provider = get_market_data_provider()
    ticker = ticker.upper()
    result: dict = {"ticker": ticker}

    try:
        quote = provider.get_live_quote(ticker)
        result["price"] = quote.get("price", 0)
        result["quote"] = quote
    except Exception as e:
        result["error"] = f"Quote failed: {e}"
        return result

    try:
        bars_5m = provider.get_ohlcv(ticker, period="5d", interval="5m")
    except Exception as e:
        result["error"] = f"OHLCV failed: {e}"
        return result

    if not bars_5m:
        result["error"] = "No price data available for this ticker."
        return result

    # Volume Profile
    try:
        if len(bars_5m) >= 10:
            vp = VolumeProfileEngine().compute(bars_5m)
            if vp:
                result["volume_profile"] = vp.model_dump()
    except Exception as exc:
        logger.debug("Volume profile failed for %s: %s", ticker, exc)

    # Regime
    try:
        if len(bars_5m) >= 30:
            regime = RegimeDetector().detect(bars_5m)
            if regime:
                result["regime"] = regime.model_dump()
    except Exception as exc:
        logger.debug("Regime detection failed for %s: %s", ticker, exc)

    # Stage
    try:
        if len(bars_5m) >= 15:
            stage = StageDetector().detect(ticker, bars_5m)
            if stage:
                result["stage"] = stage.model_dump()
    except Exception as exc:
        logger.debug("Stage detection failed for %s: %s", ticker, exc)

    # Order Flow
    if has_orderflow:
        try:
            of = OrderFlowAnalyzer()
            flow = of.analyze(bars_5m)
            if flow:
                try:
                    result["order_flow"] = flow.model_dump()
                except AttributeError:
                    result["order_flow"] = dict(flow.__dict__)
        except Exception as e:
            logger.debug("Order flow failed for %s: %s", ticker, e)

    return result


def _run_orderflow(ticker: str) -> dict:
    """Run order-flow snapshot synchronously."""
    try:
        from src.core.order_flow import OrderFlowAnalyzer
    except ImportError:
        return {"ticker": ticker.upper(), "error": "OrderFlow module not available"}

    from src.services.market_data import get_market_data_provider

    provider = get_market_data_provider()
    ticker = ticker.upper()

    try:
        bars_5m = provider.get_ohlcv(ticker, period="5d", interval="5m")
        if not bars_5m:
            return {"ticker": ticker, "error": "No price data available."}

        of = OrderFlowAnalyzer()
        flow = of.analyze(bars_5m)
        if not flow:
            return {"ticker": ticker, "error": "Could not compute order flow."}

        try:
            return {"ticker": ticker, "order_flow": flow.model_dump()}
        except AttributeError:
            return {"ticker": ticker, "order_flow": dict(flow.__dict__)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_analysis(data: dict) -> str:
    """Format analysis dict into a Telegram-friendly HTML message."""
    ticker = data.get("ticker", "UNKNOWN")

    if "error" in data:
        return f"<b>{ticker}</b>\n\nError: {data['error']}"

    lines = [f"<b>{ticker} Analysis</b>"]

    # Price
    price = data.get("price", 0)
    if price:
        lines.append(f"Price: ${price:.2f}")

    quote = data.get("quote", {})
    pre = quote.get("premarket_price")
    post = quote.get("after_hours_price")
    if pre:
        lines.append(f"Pre-market: ${pre:.2f}")
    if post:
        lines.append(f"After-hours: ${post:.2f}")

    # Volume Profile
    vp = data.get("volume_profile")
    if vp:
        lines.append("")
        lines.append("<b>Volume Profile</b>")
        lines.append(f"POC: ${vp.get('poc', 0):.2f}")
        lines.append(f"VAH: ${vp.get('vah', 0):.2f}")
        lines.append(f"VAL: ${vp.get('val', 0):.2f}")
        lines.append(f"Support zones: {vp.get('support_count', 0)}")
        lines.append(f"Resistance zones: {vp.get('resistance_count', 0)}")

    # Regime
    regime = data.get("regime")
    if regime:
        lines.append("")
        lines.append("<b>Regime</b>")
        lines.append(f"State: {regime.get('regime', 'unknown')}")
        lines.append(f"ADX: {regime.get('adx', 0):.1f}")
        lines.append(f"ATR%: {regime.get('atr_pct', 0):.2f}")
        lines.append(f"Strength: {regime.get('strength_multiplier', 0):.2f}x")

    # Stage
    stage = data.get("stage")
    if stage:
        lines.append("")
        lines.append("<b>Stage</b>")
        lines.append(f"Stage: {stage.get('stage', 'unknown')}")
        lines.append(f"Confidence: {stage.get('confidence', 0):.1f}%")
        chars = stage.get("characteristics", [])
        if chars:
            lines.append(f"Characteristics: {', '.join(str(c) for c in chars)}")

    # Order Flow
    flow = data.get("order_flow")
    if flow:
        lines.append("")
        lines.append("<b>Order Flow</b>")
        buy_ratio = flow.get("aggressive_buy_ratio", 0)
        sell_ratio = flow.get("aggressive_sell_ratio", 0)
        signal = flow.get("signal", "neutral")
        imb = flow.get("bid_ask_imbalance", 0)
        lines.append(f"Buy pressure: {buy_ratio * 100:.1f}%")
        lines.append(f"Sell pressure: {sell_ratio * 100:.1f}%")
        lines.append(f"Signal: {signal.upper()} (imbalance {imb:.2f})")
        lb = flow.get("large_order_buy_volume", 0)
        ls = flow.get("large_order_sell_volume", 0)
        if lb or ls:
            lines.append(f"Large orders — Buy: {lb:,.0f}  Sell: {ls:,.0f}")
    else:
        lines.append("")
        lines.append("<i>Order flow data unavailable for this ticker.</i>")

    return "\n".join(lines)


def _format_orderflow(data: dict) -> str:
    """Format order-flow dict into a short Telegram message."""
    ticker = data.get("ticker", "UNKNOWN")

    if "error" in data:
        return f"<b>{ticker}</b>\n\nError: {data['error']}"

    flow = data.get("order_flow")
    if not flow:
        return f"<b>{ticker}</b>\n\nNo order flow data available."

    buy_ratio = flow.get("aggressive_buy_ratio", 0)
    sell_ratio = flow.get("aggressive_sell_ratio", 0)
    signal = flow.get("signal", "neutral")
    imb = flow.get("bid_ask_imbalance", 0)
    lb = flow.get("large_order_buy_volume", 0)
    ls = flow.get("large_order_sell_volume", 0)

    lines = [
        f"<b>{ticker} Order Flow</b>",
        "",
        f"Buy: {buy_ratio * 100:.1f}%  |  Sell: {sell_ratio * 100:.1f}%",
        f"Signal: {signal.upper()} (imbalance {imb:.2f})",
    ]
    if lb or ls:
        lines.append(f"Large orders — Buy: {lb:,.0f}  Sell: {ls:,.0f}")

    return "\n".join(lines)


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_text(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    seconds = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _fmt_float(value, default: str = "unknown") -> str:
    try:
        if value is None:
            return default
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return default


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _run_status(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    candidates = _load_json(AGENTIC_DATA_DIR / "news_momentum_candidates.json", [])
    cooldowns = _load_json(AGENTIC_DATA_DIR / "news_momentum_cooldowns.json", {})
    alert_memory = _load_json(AGENTIC_DATA_DIR / "news_momentum_alert_memory.json", {})
    shadow = _load_json(AGENTIC_DATA_DIR / "news_momentum_shadow_alerts.json", [])

    ticker_candidates = [c for c in candidates if str(c.get("ticker", "")).upper() == ticker]
    ticker_candidates.sort(key=lambda c: c.get("detected_at") or "", reverse=True)
    latest = ticker_candidates[0] if ticker_candidates else None

    ticker_memory = [
        item for item in alert_memory.values()
        if str(item.get("ticker", "")).upper() == ticker
    ]
    ticker_memory.sort(key=lambda item: item.get("sent_at") or "", reverse=True)
    last_alert = ticker_memory[0] if ticker_memory else None

    blocked = [
        item for item in shadow
        if str(item.get("ticker", "")).upper() == ticker
    ]
    blocked.sort(key=lambda item: item.get("logged_at") or item.get("detected_at") or "", reverse=True)
    last_block = blocked[0] if blocked else None

    cooldown_dt = _parse_dt(cooldowns.get(ticker))

    return {
        "ticker": ticker,
        "latest": latest,
        "last_alert": last_alert,
        "last_block": last_block,
        "cooldown_at": cooldown_dt,
        "data_dir": str(AGENTIC_DATA_DIR),
    }


def _format_status(data: dict) -> str:
    ticker = data["ticker"]
    latest = data.get("latest")
    last_alert = data.get("last_alert")
    last_block = data.get("last_block")
    cooldown_at = data.get("cooldown_at")

    lines = [f"<b>{ticker} Oracle Status</b>", ""]
    if latest:
        published = _parse_dt(latest.get("published_at"))
        detected = _parse_dt(latest.get("detected_at"))
        lines.extend([
            f"Last headline: {latest.get('headline', 'unknown')}",
            f"Source: {latest.get('source', 'unknown')}",
            f"Published age: {_age_text(published)}",
            f"Detected age: {_age_text(detected)}",
            f"Move: {latest.get('move_pct', 'unknown')}%",
            f"Impact / Return: {_fmt_float(latest.get('news_impact_score'))} / {_fmt_float(latest.get('expected_return_score'))}",
            f"Telegram sent: {latest.get('telegram_sent', False)}",
        ])
    else:
        lines.append("No active News Momentum candidate found.")

    lines.append("")
    if cooldown_at:
        lines.append(f"Ticker cooldown last set: {_age_text(cooldown_at)} ago")
    else:
        lines.append("Ticker cooldown: none found")

    if last_alert:
        sent_at = _parse_dt(last_alert.get("sent_at"))
        lines.append(f"Last alert memory: {_age_text(sent_at)} ago")
    else:
        lines.append("Alert memory: none found")

    if last_block:
        reason = last_block.get("block_reason") or last_block.get("_block_reason") or "unknown"
        lines.append(f"Last block reason: {reason}")
    else:
        lines.append("Last block reason: none found")

    lines.append("")
    lines.append(f"Data dir: {data.get('data_dir')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _handle_analysis_command(chat_id: str, ticker: str):
    """Handle /analysis TICKER."""
    if not LEGACY_TELEGRAM_COMMANDS_ENABLED:
        await send_telegram_message(chat_id, "The /analysis command is disabled in Oracle lean mode.")
        return

    await send_telegram_message(chat_id, f"Analyzing {ticker.upper()}...")

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_run_analysis, ticker),
            timeout=ANALYSIS_TIMEOUT,
        )
        msg = _format_analysis(data)
    except asyncio.TimeoutError:
        msg = (
            f"<b>{ticker.upper()}</b>\n\n"
            f"Analysis timed out after {ANALYSIS_TIMEOUT:.0f}s.\n"
            f"The data provider may be slow for this ticker."
        )
    except Exception as e:
        msg = f"<b>{ticker.upper()}</b>\n\nUnexpected error: {e}"

    await send_telegram_message(chat_id, msg)


async def _handle_orderflow_command(chat_id: str, ticker: str):
    """Handle /orderflow TICKER."""
    if not LEGACY_TELEGRAM_COMMANDS_ENABLED:
        await send_telegram_message(chat_id, "The /orderflow command is disabled in Oracle lean mode.")
        return

    await send_telegram_message(chat_id, f"Fetching order flow for {ticker.upper()}...")

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_run_orderflow, ticker),
            timeout=ANALYSIS_TIMEOUT,
        )
        msg = _format_orderflow(data)
    except asyncio.TimeoutError:
        msg = (
            f"<b>{ticker.upper()}</b>\n\n"
            f"Order flow timed out after {ANALYSIS_TIMEOUT:.0f}s."
        )
    except Exception as e:
        msg = f"<b>{ticker.upper()}</b>\n\nUnexpected error: {e}"

    await send_telegram_message(chat_id, msg)


async def _handle_help(chat_id: str):
    """Handle /help command."""
    if not LEGACY_TELEGRAM_COMMANDS_ENABLED or not TELEGRAM_WATCH_COMMAND_ENABLED:
        lines = ["<b>Oracle Bot Commands</b>", ""]
        if LEGACY_TELEGRAM_COMMANDS_ENABLED:
            lines.extend([
                "/analysis TICKER - Full stock analysis",
                "/orderflow TICKER - Quick buy/sell snapshot",
                "",
            ])
        if TELEGRAM_WATCH_COMMAND_ENABLED:
            lines.extend([
                "/watch TICKER [bullish|bearish] - Add to watchlist, optional bias alert",
                "  Example: /watch AAPL bullish",
                "",
            ])
        lines.extend([
            "/status TICKER - Show latest alert/cooldown/block status",
            "/help - Show this message",
            "",
            "<i>News Momentum and Pre-News alerts continue automatically.</i>",
        ])
        await send_telegram_message(chat_id, "\n".join(lines))
        return

    msg = (
        "<b>Oracle Bot Commands</b>\n\n"
        "/analysis TICKER — Full stock analysis\n"
        "  (price, volume profile, regime, stage, order flow)\n\n"
        "/orderflow TICKER — Quick buy/sell snapshot\n\n"
        "/watch TICKER [bullish|bearish] — Add to watchlist, optional bias alert\n"
        "  Example: /watch AAPL bullish\n\n"
        "/status TICKER - Show latest alert/cooldown/block status\n\n"
        "/help — Show this message\n\n"
        "<i>Example: /analysis AAPL</i>"
    )
    await send_telegram_message(chat_id, msg)


async def _handle_watch_command(chat_id: str, ticker: str, preference: Optional[str] = None):
    """Handle /watch TICKER [bullish|bearish]."""
    if not TELEGRAM_WATCH_COMMAND_ENABLED:
        await send_telegram_message(chat_id, "The /watch command is disabled in Oracle lean mode.")
        return

    from src.db.session import SessionLocal
    from src.db.repositories import WatchlistRepository

    ticker = ticker.upper()
    db = SessionLocal()
    try:
        repo = WatchlistRepository(db)
        existing = repo.get_by_ticker(ticker)

        watch_reason = None
        if preference and preference.lower() in ("bullish", "bearish"):
            watch_reason = preference.lower()

        if existing:
            if watch_reason:
                repo.update(ticker, watch_reason=watch_reason, active=True, status="active")
                msg = f"<b>{ticker}</b> updated — watching for <b>{watch_reason}</b> conditions."
            else:
                msg = f"<b>{ticker}</b> is already on your watchlist."
        else:
            repo.add(ticker, source="telegram", watch_reason=watch_reason)
            if watch_reason:
                msg = f"<b>{ticker}</b> added to watchlist — you'll be notified on <b>{watch_reason}</b> signals."
            else:
                msg = f"<b>{ticker}</b> added to watchlist."
    except Exception as e:
        logger.warning("Watch command failed for %s: %s", ticker, e)
        msg = f"Failed to add <b>{ticker}</b> to watchlist."
    finally:
        db.close()

    await send_telegram_message(chat_id, msg)


async def _handle_status_command(chat_id: str, ticker: str):
    """Handle /status TICKER."""
    ticker = ticker.upper().strip()
    try:
        data = await asyncio.to_thread(_run_status, ticker)
        msg = _format_status(data)
    except Exception as e:
        logger.warning("Status command failed for %s: %s", ticker, e)
        msg = f"<b>{ticker}</b>\n\nStatus lookup failed: {e}"

    await send_telegram_message(chat_id, msg)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

async def telegram_command_polling_loop():
    """
    Poll Telegram getUpdates and dispatch commands.
    Designed to run as a FastAPI lifespan background task.
    """
    token, configured_chat_id = _get_config()
    if not token or not configured_chat_id:
        logger.info("Telegram not configured — command polling disabled")
        return

    last_update_id = 0

    logger.info("Telegram command polling started")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    poll_count = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                url = f"{TELEGRAM_API}/bot{token}/getUpdates"
                params = {"offset": last_update_id + 1, "limit": 10}

                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "Telegram getUpdates returned %s: %s",
                        resp.status_code, resp.text[:200],
                    )
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                data = resp.json()
                if not data.get("ok"):
                    logger.warning("Telegram getUpdates returned ok=false: %s", str(data)[:200])
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    last_update_id = update.get("update_id", last_update_id)

                    message = update.get("message", {})
                    chat = message.get("chat", {})
                    msg_chat_id = str(chat.get("id", ""))

                    # Security: only respond to the configured chat
                    if msg_chat_id != configured_chat_id:
                        logger.warning(
                            "Telegram message ignored from unauthorized chat_id=%s (configured=%s)",
                            msg_chat_id, configured_chat_id,
                        )
                        continue

                    text = message.get("text", "").strip()
                    if not text:
                        continue

                    parts = text.split()
                    cmd = parts[0].lower()

                    if cmd == "/analysis":
                        if len(parts) >= 2:
                            ticker = parts[1]
                            asyncio.create_task(_handle_analysis_command(msg_chat_id, ticker))
                        else:
                            asyncio.create_task(
                                send_telegram_message(
                                    msg_chat_id,
                                    "Usage: /analysis TICKER\nExample: /analysis AAPL",
                                )
                            )
                    elif cmd == "/orderflow":
                        if len(parts) >= 2:
                            ticker = parts[1]
                            asyncio.create_task(_handle_orderflow_command(msg_chat_id, ticker))
                        else:
                            asyncio.create_task(
                                send_telegram_message(
                                    msg_chat_id,
                                    "Usage: /orderflow TICKER\nExample: /orderflow AAPL",
                                )
                            )
                    elif cmd == "/watch":
                        if len(parts) >= 2:
                            ticker = parts[1]
                            preference = parts[2] if len(parts) >= 3 else None
                            asyncio.create_task(_handle_watch_command(msg_chat_id, ticker, preference))
                        else:
                            asyncio.create_task(
                                send_telegram_message(
                                    msg_chat_id,
                                    "Usage: /watch TICKER [bullish|bearish]\nExample: /watch AAPL bullish",
                                )
                            )
                    elif cmd == "/status":
                        if len(parts) >= 2:
                            ticker = parts[1]
                            asyncio.create_task(_handle_status_command(msg_chat_id, ticker))
                        else:
                            asyncio.create_task(
                                send_telegram_message(
                                    msg_chat_id,
                                    "Usage: /status TICKER\nExample: /status STI",
                                )
                            )
                    elif cmd == "/help":
                        asyncio.create_task(_handle_help(msg_chat_id))
                    elif cmd.startswith("/"):
                        asyncio.create_task(
                            send_telegram_message(
                                msg_chat_id,
                                "Unknown command. Try /help",
                            )
                        )

            except Exception as e:
                import traceback
                logger.warning(
                    "Telegram polling error: %s | %s",
                    e, traceback.format_exc().splitlines()[-1]
                )

            poll_count += 1
            if poll_count % 60 == 0:
                logger.info("Telegram polling alive (%d polls)", poll_count)

            await asyncio.sleep(POLL_INTERVAL)
