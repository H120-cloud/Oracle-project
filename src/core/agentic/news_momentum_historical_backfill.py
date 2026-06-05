"""
News Momentum Historical Backfill Engine (V24)

Fetches historical news + prices, simulates the scoring pipeline,
and generates resolved TelegramAlertRecords for ML training.

Data sources:
  - Polygon.io Ticker News API (historical news, requires POLYGON_API_KEY)
  - Yahoo Finance (historical prices, no API key needed)

Key improvements in V24:
  - Polygon API pagination (cursor-based) — fetches ALL pages
  - Exponential backoff with jitter for rate limits
  - Resume capability — tracks processed ticker-date combos
  - Concurrent processing with semaphore for rate-limit respect
  - Better outcome labeling using multi-day highs
  - Progress tracking and reporting

Usage:
    engine = HistoricalBackfillEngine()
    result = await engine.backfill_range(
        tickers=["AAPL", "TSLA", ...],
        start_date="2025-01-01",
        end_date="2025-12-31",
    )
    # Inject into orchestrator and retrain:
    engine.inject_into_orchestrator(orch)
    orch.retrain_ml()

CLI Usage:
    python -m src.core.agentic.news_momentum_historical_backfill --tickers AAPL,TSLA --start 2025-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

import httpx

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

from src.core.agentic.news_momentum_models import (
    AlertOutcome,
    CatalystSubType,
    FloatCategory,
    MarketCapCategory,
    SessionType,
    TelegramAlertRecord,
)
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
BACKFILL_RECORDS_FILE = DATA_DIR / "news_momentum_backfill_records.json"
BACKFILL_PROGRESS_FILE = DATA_DIR / "news_momentum_backfill_progress.json"

POLYGON_BASE = "https://api.polygon.io"


# Lazy-load key so .env can be imported after this module
_POLY_KEY: str | None = None


def _polygon_api_key() -> str:
    global _POLY_KEY
    if _POLY_KEY is None:
        _POLY_KEY = os.environ.get("POLYGON_API_KEY", "")
    return _POLY_KEY


# ── helpers ──────────────────────────────────────────────────────────────────


def _jitter(base: float, jitter: float = 0.3) -> float:
    """Add random jitter to a delay."""
    import random
    return base + random.uniform(-jitter * base, jitter * base)


class HistoricalBackfillEngine:
    """Backfill engine for historical news momentum training data (V24)."""

    def __init__(
        self,
        data_dir: str = str(DATA_DIR),
        rate_limit_delay: float = 12.0,
        max_retries: int = 3,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self._records: List[TelegramAlertRecord] = []
        self._seen: Set[str] = set()  # dedup key: "ticker|headline|date"
        self._progress: Dict[str, Any] = {}
        self._load_existing()
        self._load_progress()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_existing(self) -> None:
        raw = load_json_file(BACKFILL_RECORDS_FILE, default=[])
        self._records = []
        self._seen = set()
        for r in raw:
            try:
                if "outcome" in r and r["outcome"]:
                    r["outcome"] = AlertOutcome(r["outcome"])
                rec = TelegramAlertRecord.model_validate(r)
                self._records.append(rec)
                self._seen.add(self._dedup_key(rec.ticker, rec.sent_at))
            except Exception as exc:
                logger.debug("Backfill: skip bad record: %s", exc)
        logger.info("Backfill: loaded %d existing records", len(self._records))

    def _persist(self) -> None:
        data = []
        for r in self._records:
            d = r.model_dump(mode="json")
            if d.get("outcome"):
                d["outcome"] = str(d["outcome"])
            data.append(d)
        save_json_file(BACKFILL_RECORDS_FILE, data)

    def _load_progress(self) -> None:
        self._progress = load_json_file(BACKFILL_PROGRESS_FILE, default={})

    def _save_progress(self) -> None:
        save_json_file(BACKFILL_PROGRESS_FILE, self._progress)

    def _dedup_key(self, ticker: str, sent_at: datetime) -> str:
        return f"{ticker.upper()}|{sent_at.strftime('%Y-%m-%d')}"

    # ── Polygon News Fetch (paginated) ───────────────────────────────────────

    async def _fetch_polygon_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        per_page: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch ALL historical news pages for a ticker from Polygon."""
        api_key = _polygon_api_key()
        if not api_key:
            raise ValueError(
                "POLYGON_API_KEY is not set. "
                "Add POLYGON_API_KEY=your_key to your .env file and restart the server."
            )

        all_results: List[Dict[str, Any]] = []
        next_url: Optional[str] = None
        page = 0

        self._write_diag({"ticker": ticker, "source": "polygon_start", "api_key_present": bool(api_key)})
        logger.info("Backfill: fetching Polygon news for %s (%s to %s)", ticker, start_date, end_date)

        base_url = (
            f"{POLYGON_BASE}/v2/reference/news"
            f"?ticker={ticker.upper()}"
            f"&published_utc.gte={start_date}"
            f"&published_utc.lte={end_date}"
            f"&limit={per_page}"
            f"&apiKey={api_key}"
        )

        current_url = base_url

        async with httpx.AsyncClient(timeout=30) as client:
            while current_url and page < 20:  # safety cap
                page += 1
                for attempt in range(self.max_retries):
                    try:
                        r = await client.get(current_url)
                        if r.status_code == 429:
                            delay = _jitter(self.rate_limit_delay * (attempt + 1))
                            logger.debug("Backfill: Polygon rate limited page %d for %s — sleep %.1fs", page, ticker, delay)
                            await asyncio.sleep(delay)
                            continue
                        if r.status_code == 403:
                            logger.warning("Backfill: Polygon auth failed — check POLYGON_API_KEY")
                            return all_results
                        if r.status_code != 200:
                            body = r.text[:200] if hasattr(r, 'text') else 'N/A'
                            logger.warning("Backfill: Polygon news %s page %d returned %d — body: %s", ticker, page, r.status_code, body)
                            return all_results

                        data = r.json()
                        results = data.get("results", [])
                        all_results.extend(results)

                        next_url = data.get("next_url")
                        if next_url and "apiKey=" not in next_url:
                            next_url = f"{next_url}&apiKey={api_key}"
                        current_url = next_url

                        # Free-tier rate limit: sleep between pages
                        await asyncio.sleep(_jitter(self.rate_limit_delay / 2))
                        break

                    except Exception as exc:
                        if attempt == self.max_retries - 1:
                            logger.warning("Backfill: Polygon fetch failed for %s page %d after %d retries: %s", ticker, page, self.max_retries, exc)
                            self._write_diag({"ticker": ticker, "source": "polygon", "ok": False, "reason": f"fetch_failed: {exc}", "articles": len(all_results)})
                            return all_results
                        await asyncio.sleep(_jitter(self.rate_limit_delay))

                if not current_url:
                    break

        self._write_diag({"ticker": ticker, "source": "polygon_done", "articles": len(all_results), "pages": page})
        logger.info("Backfill: fetched %d news articles for %s (%d pages)", len(all_results), ticker, page)
        return all_results

    # ── Yahoo Finance Price Fetch ────────────────────────────────────────────

    def _fetch_yf_prices(
        self,
        ticker: str,
        news_date: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch daily OHLCV around a news date. Returns price snapshot."""
        diag = {"ticker": ticker, "news_date": news_date, "ok": False, "reason": ""}
        try:
            import yfinance as yf

            event_dt = datetime.strptime(news_date, "%Y-%m-%d").date()
            start = (event_dt - timedelta(days=10)).strftime("%Y-%m-%d")
            end = (event_dt + timedelta(days=10)).strftime("%Y-%m-%d")

            hist = yf.download(ticker, start=start, end=end, progress=False, threads=False)
            # Flatten multi-level columns from yfinance, e.g. ('Close','AAPL') -> 'Close'
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]

            diag["hist_empty"] = hist.empty
            diag["hist_shape"] = str(hist.shape)
            diag["hist_columns"] = str(list(hist.columns))
            diag["hist_index_type"] = str(type(hist.index))
            if hist.empty:
                diag["reason"] = "hist_empty"
                self._write_diag(diag)
                return None

            date_str = event_dt.strftime("%Y-%m-%d")
            idx = hist.index
            closest = idx[idx.strftime("%Y-%m-%d") >= date_str]
            diag["closest_count"] = len(closest)
            diag["closest_dates"] = [str(d) for d in list(closest)[:3]]
            if len(closest) == 0:
                diag["reason"] = "no_closest_date"
                self._write_diag(diag)
                return None

            row = hist.loc[closest[0]]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            def _col(row, name):
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                if hasattr(row, 'get'):
                    val = row.get(name)
                    if val is None:
                        for c in row.index:
                            if isinstance(c, tuple) and c[0] == name:
                                val = row[c]
                                break
                    # Defensive: extract scalar if pandas object leaked through
                    if isinstance(val, pd.Series):
                        val = val.iloc[0] if len(val) > 0 else None
                    elif isinstance(val, pd.DataFrame):
                        val = val.iloc[0, 0] if val.size > 0 else None
                    return val if val is not None else 0
                return row.get(name, 0)

            price_at_news = float(_col(row, "Close") or _col(row, "Adj Close") or 0)
            diag["raw_price"] = price_at_news
            if price_at_news <= 0:
                diag["reason"] = "price_zero"
                self._write_diag(diag)
                return None

            volume = int(_col(row, "Volume") or 0)
            event_idx_pos = list(idx).index(closest[0])
            future = hist.iloc[event_idx_pos + 1 : event_idx_pos + 6]

            next_day_open = next_day_high = next_day_close = None
            two_day_high = five_day_high = None

            if len(future) >= 1:
                r1 = future.iloc[0]
                if isinstance(r1, pd.DataFrame):
                    r1 = r1.iloc[0]
                next_day_open = float(_col(r1, "Open"))
                next_day_high = float(_col(r1, "High"))
                next_day_close = float(_col(r1, "Close") or _col(r1, "Adj Close"))

            if len(future) >= 2:
                two_day_high = float(future.iloc[:2].apply(lambda x: _col(x, "High") if not isinstance(x, pd.DataFrame) else x.iloc[0].get("High", 0), axis=1).max())

            if len(future) >= 5:
                five_day_high = float(future.iloc[:5].apply(lambda x: _col(x, "High") if not isinstance(x, pd.DataFrame) else x.iloc[0].get("High", 0), axis=1).max())

            diag["ok"] = True
            diag["price"] = price_at_news
            self._write_diag(diag)
            return {
                "price_at_news": price_at_news,
                "volume": volume,
                "next_day_open": next_day_open,
                "next_day_high": next_day_high,
                "next_day_close": next_day_close,
                "two_day_high": two_day_high,
                "five_day_high": five_day_high,
            }
        except Exception as exc:
            import traceback
            diag["reason"] = f"exception: {exc}"
            diag["traceback"] = traceback.format_exc()
            self._write_diag(diag)
            logger.info("Backfill: yfinance failed for %s on %s: %s", ticker, news_date, exc)
            return None

    def _write_diag(self, diag: dict):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "backfill_diag.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(diag, default=str) + "\n")

    # ── Outcome Computation ──────────────────────────────────────────────────

    def _compute_outcome(
        self,
        price_at_news: float,
        prices: Dict[str, Any],
    ) -> Tuple[AlertOutcome, Dict[str, Any]]:
        """Label a historical event based on post-news price action."""
        outcomes: Dict[str, Any] = {
            "next_day_open": prices.get("next_day_open"),
            "next_day_high": prices.get("next_day_high"),
            "next_day_close": prices.get("next_day_close"),
            "two_day_high": prices.get("two_day_high"),
            "five_day_high": prices.get("five_day_high"),
            "mfe_pct": None,
            "mae_pct": None,
        }

        if price_at_news <= 0:
            return AlertOutcome.NO_FOLLOW_THROUGH, outcomes

        highs = [v for k, v in prices.items() if "high" in k.lower() and v]
        if highs:
            max_high = max(highs)
            outcomes["mfe_pct"] = round(((max_high - price_at_news) / price_at_news) * 100, 2)

        # Label based on best multi-day high (MFE)
        mfe = outcomes.get("mfe_pct") or 0
        if mfe >= 100:
            outcome = AlertOutcome.GREAT_ALERT
        elif mfe >= 30:
            outcome = AlertOutcome.GOOD_ALERT
        elif mfe >= 15:
            outcome = AlertOutcome.LATE_ALERT
        elif mfe <= -10:
            outcome = AlertOutcome.TRAP_ALERT
        else:
            outcome = AlertOutcome.NO_FOLLOW_THROUGH

        return outcome, outcomes

    # ── Pipeline Simulation ──────────────────────────────────────────────────

    def _simulate_pipeline(
        self,
        headline: str,
        price: float,
    ) -> Dict[str, Any]:
        """Simulate the scoring pipeline for a historical event."""
        category, subtype, is_negative, is_vague = classify_headline(headline)

        impact = 50.0
        if subtype == CatalystSubType.FDA_APPROVAL:
            impact = 90.0
        elif subtype in (CatalystSubType.MERGER, CatalystSubType.ACQUISITION, CatalystSubType.MAJOR_PARTNERSHIP, CatalystSubType.AI_PARTNERSHIP):
            impact = 80.0
        elif subtype in (CatalystSubType.GOVERNMENT_CONTRACT, CatalystSubType.SUPPLY_AGREEMENT):
            impact = 75.0
        elif subtype == CatalystSubType.AI_PARTNERSHIP:
            impact = 70.0
        elif subtype == CatalystSubType.EARNINGS_BEAT:
            impact = 65.0
        elif subtype in (CatalystSubType.PHASE_1, CatalystSubType.PHASE_2, CatalystSubType.PHASE_3, CatalystSubType.FAST_TRACK):
            impact = 68.0
        elif is_negative:
            impact = 20.0
        elif is_vague:
            impact = 35.0

        if price < 1.0:
            impact += 5
        elif price > 50:
            impact -= 10

        expected_return = min(impact * 0.9, 95.0)

        continuation = 55.0
        if subtype in (CatalystSubType.FDA_APPROVAL, CatalystSubType.MERGER, CatalystSubType.ACQUISITION):
            continuation = 75.0
        elif subtype in (CatalystSubType.PHASE_1, CatalystSubType.PHASE_2, CatalystSubType.PHASE_3, CatalystSubType.FAST_TRACK):
            continuation = 65.0
        elif is_negative:
            continuation = 15.0
        elif is_vague:
            continuation = 30.0

        multi_day = 40.0
        if subtype == CatalystSubType.FDA_APPROVAL:
            multi_day = 70.0
        elif subtype in (CatalystSubType.MERGER, CatalystSubType.ACQUISITION):
            multi_day = 60.0
        elif subtype in (CatalystSubType.MAJOR_PARTNERSHIP, CatalystSubType.AI_PARTNERSHIP):
            multi_day = 55.0

        return {
            "catalyst_type": subtype,
            "catalyst_category": category.value if hasattr(category, "value") else str(category),
            "news_impact_score": round(impact, 1),
            "expected_return_score": round(expected_return, 1),
            "continuation_probability": round(continuation, 1),
            "multi_day_score": round(multi_day, 1),
            "is_negative": is_negative,
            "is_vague": is_vague,
            "price_at_alert": price,
            "move_pct_at_alert": 0.0,
            "rvol_at_alert": 2.0,
            "spread_pct_at_alert": 1.5,
            "trap_risk_at_alert": 25.0,
            "dilution_risk_at_alert": 20.0,
            "velocity_score_at_alert": 30.0,
            "sources_seen_count": 1,
            "float_category": FloatCategory.MEDIUM,
            "market_cap_category": MarketCapCategory.SMALL,
            "session_type": SessionType.REGULAR,
            "is_premarket": False,
            "is_after_hours": False,
            "is_delayed_reaction": False,
            "prenews_anomaly_score": 0.0,
        }

    # ── Main Backfill ────────────────────────────────────────────────────────

    async def backfill_ticker(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        news_limit: int = 50,
        force: bool = False,
    ) -> int:
        """Backfill historical data for a single ticker. Returns count added."""
        logger.info("Backfill: starting %s (%s to %s) force=%s", ticker, start_date, end_date, force)

        # Check if already processed
        progress_key = f"{ticker.upper()}|{start_date}|{end_date}"
        if not force and self._progress.get(progress_key, {}).get("completed"):
            logger.info("Backfill: %s already processed, skipping (use force=True to override)", ticker)
            return 0

        # Fetch news (paginated)
        articles = await self._fetch_polygon_news(ticker, start_date, end_date, per_page=min(news_limit, 50))
        if not articles:
            logger.info("Backfill: no news found for %s", ticker)
            self._progress[progress_key] = {"completed": True, "added": 0, "timestamp": datetime.now(timezone.utc).isoformat()}
            self._save_progress()
            return 0

        added = 0
        skip_no_title = skip_no_date = skip_dedup = skip_no_prices = skip_low_price = skip_error = 0
        for article in articles:
            try:
                headline = article.get("title", "").strip()
                if not headline:
                    skip_no_title += 1
                    continue

                pub_str = article.get("published_utc", "")
                if not pub_str:
                    skip_no_date += 1
                    continue
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                news_date = pub_dt.strftime("%Y-%m-%d")

                # Deduplicate
                dedup = self._dedup_key(ticker, pub_dt)
                if dedup in self._seen:
                    skip_dedup += 1
                    continue

                # Fetch prices
                prices = self._fetch_yf_prices(ticker, news_date)
                if not prices:
                    skip_no_prices += 1
                    continue

                price = prices["price_at_news"]
                volume = prices["volume"]

                # Skip if price too low (noise)
                if price < 0.10:
                    skip_low_price += 1
                    continue

                # Simulate pipeline
                sim = self._simulate_pipeline(headline, price)

                # Compute outcome
                outcome, outcome_prices = self._compute_outcome(price, prices)

                # Build record
                record = TelegramAlertRecord(
                    alert_id=f"backfill_{uuid.uuid4().hex[:8]}",
                    ticker=ticker,
                    sent_at=pub_dt,
                    catalyst_type=sim["catalyst_type"],
                    session_type=sim["session_type"],
                    price_at_alert=price,
                    news_impact_score=sim["news_impact_score"],
                    expected_return_score=sim["expected_return_score"],
                    continuation_probability=sim["continuation_probability"],
                    multi_day_score=sim["multi_day_score"],
                    catalyst_category=sim["catalyst_category"],
                    float_category=sim["float_category"].value,
                    market_cap_category=sim["market_cap_category"].value,
                    move_pct_at_alert=sim["move_pct_at_alert"],
                    rvol_at_alert=sim["rvol_at_alert"],
                    volume_at_alert=volume,
                    spread_pct_at_alert=sim["spread_pct_at_alert"],
                    trap_risk_at_alert=sim["trap_risk_at_alert"],
                    dilution_risk_at_alert=sim["dilution_risk_at_alert"],
                    velocity_score_at_alert=sim["velocity_score_at_alert"],
                    sources_seen_count=sim["sources_seen_count"],
                    is_negative=sim["is_negative"],
                    is_vague=sim["is_vague"],
                    is_delayed_reaction=sim["is_delayed_reaction"],
                    prenews_anomaly_score=sim["prenews_anomaly_score"],
                    ml_predicted_win_prob=0.5,
                    ml_model_version="backfill",
                    next_day_open=outcome_prices.get("next_day_open"),
                    next_day_high=outcome_prices.get("next_day_high"),
                    next_day_close=outcome_prices.get("next_day_close"),
                    two_day_high=outcome_prices.get("two_day_high"),
                    five_day_high=outcome_prices.get("five_day_high"),
                    mfe_pct=outcome_prices.get("mfe_pct"),
                    mae_pct=outcome_prices.get("mae_pct"),
                    outcome=outcome,
                    resolved_at=pub_dt + timedelta(days=5),
                )

                self._records.append(record)
                self._seen.add(dedup)
                added += 1

            except Exception as exc:
                import traceback
                skip_error += 1
                tb = traceback.format_exc()
                self._write_diag({
                    "ticker": ticker,
                    "news_date": news_date,
                    "source": "article_processing_error",
                    "error": str(exc),
                    "traceback": tb,
                    "headline": headline[:100] if headline else "",
                    "price": price if 'price' in dir() else None,
                })
                logger.info("Backfill: error processing article for %s: %s", ticker, exc)
                continue

        if added > 0:
            self._persist()

        total_skipped = skip_no_title + skip_no_date + skip_dedup + skip_no_prices + skip_low_price + skip_error
        logger.info(
            "Backfill: %s summary — added=%d, articles=%d, skipped=%d (no_title=%d no_date=%d dedup=%d no_prices=%d low_price=%d error=%d)",
            ticker, added, len(articles), total_skipped, skip_no_title, skip_no_date, skip_dedup, skip_no_prices, skip_low_price, skip_error,
        )
        self._progress[progress_key] = {"completed": True, "added": added, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._save_progress()
        return added

    async def backfill_range(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        news_limit: int = 50,
        max_concurrent: int = 2,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Backfill a list of tickers over a date range with concurrency control."""
        semaphore = asyncio.Semaphore(max_concurrent)
        results: Dict[str, int] = {}
        total_added = 0

        async def _worker(ticker: str) -> int:
            async with semaphore:
                return await self.backfill_ticker(ticker, start_date, end_date, news_limit, force=force)

        tasks = [asyncio.create_task(_worker(t)) for t in tickers]
        for ticker, task in zip(tickers, tasks):
            try:
                count = await task
                results[ticker] = count
                total_added += count
            except Exception as exc:
                logger.error("Backfill: failed for %s: %s", ticker, exc)
                results[ticker] = 0

        self._persist()
        return {
            "total_added": total_added,
            "tickers_processed": len(tickers),
            "per_ticker": results,
            "total_records": len(self._records),
        }

    def get_records(self) -> List[TelegramAlertRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()
        self._seen.clear()
        self._progress.clear()
        self._persist()
        self._save_progress()

    def inject_into_orchestrator(self, orchestrator: Any) -> int:
        """Inject backfill records into an orchestrator's learning system."""
        try:
            for record in self._records:
                orchestrator._telegram_learning.record_alert(record)
            return len(self._records)
        except Exception as exc:
            logger.error("Backfill: inject failed: %s", exc)
            return 0

    def get_summary(self) -> Dict[str, Any]:
        """Return summary of backfill data."""
        from collections import Counter
        def _outcome_str(o):
            if o is None:
                return "unresolved"
            return o.value if hasattr(o, "value") else str(o)
        outcomes = Counter(_outcome_str(r.outcome) for r in self._records)
        return {
            "total_records": len(self._records),
            "by_outcome": dict(outcomes),
            "tickers": sorted(set(r.ticker for r in self._records)),
            "date_range": {
                "earliest": min(r.sent_at.isoformat() for r in self._records) if self._records else None,
                "latest": max(r.sent_at.isoformat() for r in self._records) if self._records else None,
            },
        }


# ═════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="News Momentum Historical Backfill")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,TSLA,NVDA")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=100, help="Max news articles per ticker (default: 100)")
    parser.add_argument("--concurrent", type=int, default=2, help="Max concurrent requests (default: 2)")
    parser.add_argument("--delay", type=float, default=12.0, help="Rate limit delay in seconds (default: 12)")
    parser.add_argument("--train", action="store_true", help="Inject and trigger ML retrain after backfill")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    engine = HistoricalBackfillEngine(rate_limit_delay=args.delay)

    print(f"Starting backfill for {len(tickers)} tickers: {tickers}")
    print(f"Date range: {args.start} to {args.end}")
    print(f"Concurrent: {args.concurrent}, Delay: {args.delay}s")

    result = asyncio.run(engine.backfill_range(
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        news_limit=args.limit,
        max_concurrent=args.concurrent,
    ))

    print(f"\nBackfill complete!")
    print(f"Total added: {result['total_added']}")
    print(f"Tickers processed: {result['tickers_processed']}")
    print(f"Total records in DB: {result['total_records']}")

    summary = engine.get_summary()
    print(f"\nOutcome breakdown:")
    for outcome, count in summary["by_outcome"].items():
        print(f"  {outcome}: {count}")

    if args.train:
        print("\nInjecting into orchestrator and triggering retrain...")
        try:
            from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
            orch = NewsMomentumOrchestrator()
            injected = engine.inject_into_orchestrator(orch)
            train_result = orch.retrain_ml()
            print(f"Injected: {injected}, Training: AUC={train_result.auc:.3f}, Promoted={train_result.promoted}")
        except Exception as exc:
            print(f"Training failed: {exc}")
