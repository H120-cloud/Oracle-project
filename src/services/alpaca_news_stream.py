"""Alpaca real-time news WebSocket stream — V12.

Pushes breaking headlines to the news-momentum pipeline within seconds of the
wire, instead of waiting on polled RSS feeds (Finviz/StockTitan) that lag the
wire by 2-5 minutes. This is the primary latency win for catalyst alerting.

The Alpaca SDK's stream owns its own asyncio loop (via ``run()``), so we run it
in a dedicated daemon thread and marshal each pushed item back to the main
application event loop with ``run_coroutine_threadsafe``. The provided callback
is an async function that receives a list of ready-to-process payloads.

Free with any Alpaca account (news is not gated behind the SIP data plan).
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

from src.config import get_settings

logger = logging.getLogger(__name__)

# Lazy import so the app still boots if alpaca-py is missing.
_NEWS_STREAM_AVAILABLE = False
try:
    from alpaca.data.live.news import NewsDataStream
    _NEWS_STREAM_AVAILABLE = True
except Exception as exc:  # pragma: no cover - import guard
    logger.warning("alpaca-py NewsDataStream unavailable: %s", exc)


@dataclass
class StreamedNewsItem:
    """Normalized news payload handed to the pipeline.

    Mirrors the fields the RSS ingestion path produces (headline, tickers,
    url, timestamp) so the downstream NewsEvent construction is identical.
    """
    headline: str
    tickers: List[str]
    url: Optional[str]
    timestamp: datetime
    source: str = "Alpaca"
    summary: str = ""


# Callback receives the normalized items for one pushed news article.
NewsCallback = Callable[[List[StreamedNewsItem]], Awaitable[None]]


class AlpacaNewsStream:
    """Background Alpaca news WebSocket listener.

    Usage:
        stream = AlpacaNewsStream(on_news=handle_news)
        stream.start(main_loop=asyncio.get_running_loop())
        ...
        stream.stop()
    """

    def __init__(self, on_news: NewsCallback, symbols: Optional[List[str]] = None):
        self._on_news = on_news
        # "*" subscribes to all symbols — we filter/score downstream.
        self._symbols = symbols or ["*"]
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._received = 0

    @property
    def received_count(self) -> int:
        return self._received

    def start(self, main_loop: asyncio.AbstractEventLoop) -> bool:
        """Start the listener thread. Returns False if it cannot start."""
        if not _NEWS_STREAM_AVAILABLE:
            logger.warning("AlpacaNewsStream: SDK not available — not starting")
            return False
        settings = get_settings()
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            logger.warning("AlpacaNewsStream: Alpaca credentials not configured — not starting")
            return False
        if self._running:
            return True

        self._main_loop = main_loop
        self._running = True
        self._thread = threading.Thread(
            target=self._run_thread,
            name="alpaca-news-stream",
            daemon=True,
        )
        self._thread.start()
        logger.info("AlpacaNewsStream: started (symbols=%s)", ",".join(self._symbols))
        return True

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                logger.debug("AlpacaNewsStream: stop error: %s", exc)

    # ── internal ──────────────────────────────────────────────────────────

    def _run_thread(self) -> None:
        """Thread body: own the Alpaca stream and its reconnect loop."""
        settings = get_settings()
        while self._running:
            try:
                self._stream = NewsDataStream(
                    settings.alpaca_api_key, settings.alpaca_secret_key
                )
                self._stream.subscribe_news(self._handle_raw, *self._symbols)
                # run() blocks, managing connect + reconnect internally.
                self._stream.run()
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("AlpacaNewsStream: connection error, retrying in 10s: %s", exc)
                # Avoid a tight reconnect loop on persistent failures.
                import time
                time.sleep(10)
        logger.info("AlpacaNewsStream: listener thread exited")

    async def _handle_raw(self, news) -> None:
        """Async handler invoked inside the stream's own loop.

        Normalize the Alpaca News object and marshal it to the main loop's
        callback. Must not touch main-loop state directly.
        """
        try:
            items = self._normalize(news)
        except Exception as exc:
            logger.debug("AlpacaNewsStream: normalize failed: %s", exc)
            return
        if not items:
            return
        self._received += 1

        if self._main_loop is None or self._main_loop.is_closed():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._on_news(items), self._main_loop
            )
            # Don't block the stream loop on downstream processing, but do
            # surface exceptions for debugging via a callback.
            future.add_done_callback(self._log_future_error)
        except Exception as exc:
            logger.debug("AlpacaNewsStream: dispatch failed: %s", exc)

    @staticmethod
    def _log_future_error(future) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.debug("AlpacaNewsStream: downstream handler error: %s", exc)

    @staticmethod
    def _normalize(news) -> List[StreamedNewsItem]:
        symbols = list(getattr(news, "symbols", None) or [])
        headline = (getattr(news, "headline", "") or "").strip()
        if not headline or not symbols:
            return []
        ts = getattr(news, "created_at", None) or getattr(news, "updated_at", None)
        if ts is None:
            ts = datetime.now(timezone.utc)
        elif ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return [
            StreamedNewsItem(
                headline=headline,
                tickers=symbols,
                url=getattr(news, "url", None),
                timestamp=ts,
                summary=(getattr(news, "summary", "") or ""),
            )
        ]
