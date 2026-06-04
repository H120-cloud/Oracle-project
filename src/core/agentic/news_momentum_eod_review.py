"""
News Momentum EOD Reviewer

At end of day, scans Finviz top % gainers and checks each big mover against
the system's news event registry to detect:

  1. MISSED_DISCOVERY  — system never saw the news at all
  2. MISSED_ALERT      — system saw the news but didn't alert (uses existing learning)
  3. CAUGHT            — system alerted (great, count as a win)

Outputs a daily report to data/agentic/news_momentum_eod_reports.json and
sends a summary Telegram message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING

from src.utils.atomic_json import save_json_file, load_json_file

if TYPE_CHECKING:
    from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
EOD_REPORT_FILE = DATA_DIR / "news_momentum_eod_reports.json"

# Only review tickers that moved at least this much intraday
MIN_GAINER_PCT = 15.0

# Headline similarity threshold for matching candidate -> finviz mover
HEADLINE_SIMILARITY = 0.55


class NewsMomentumEODReviewer:
    """End-of-day analyzer that finds missed discoveries and missed alerts."""

    def __init__(self, orchestrator: "NewsMomentumOrchestrator"):
        self.orchestrator = orchestrator
        self._last_report_date: Optional[str] = None

    async def run_review(self, force: bool = False) -> Dict:
        """
        Fetch today's top gainers and analyze each against the system's record.
        Returns a summary dict.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not force and self._last_report_date == today:
            logger.info("EOD review already ran today (%s)", today)
            return {"status": "already_ran", "date": today}

        logger.info("EOD review starting for %s", today)

        try:
            from src.core.agentic.finviz_universe import fetch_finviz_top_gainers_snapshot
            gainers = fetch_finviz_top_gainers_snapshot(max_results=30)
        except Exception as exc:
            logger.error("EOD review: failed to fetch finviz gainers: %s", exc)
            return {"status": "scan_failed", "error": str(exc)}

        # Filter for meaningful movers only
        big_movers = [
            g for g in gainers
            if (g.change_percent or 0) >= MIN_GAINER_PCT
        ]

        if not big_movers:
            logger.info("EOD review: no movers >= %s%% today", MIN_GAINER_PCT)
            self._last_report_date = today
            return {"status": "no_movers", "date": today, "gainers_count": len(gainers)}

        # Snapshot current orchestrator state
        active_candidates = self.orchestrator.get_active_candidates()
        candidate_tickers = {c.ticker.upper() for c in active_candidates}
        # Also include resolved candidates (already alerted earlier in day)
        all_candidates = list(self.orchestrator._candidates)
        all_candidate_tickers = {c.ticker.upper() for c in all_candidates}

        results = {
            "date": today,
            "movers_reviewed": len(big_movers),
            "missed_discovery": [],
            "missed_alert": [],
            "caught": [],
            "summary": {},
        }
        timing_review_items: list[dict] = []

        for mover in big_movers:
            tk = mover.ticker.upper()
            change = mover.change_percent or 0

            # Find matching candidate (if any)
            matching = next((c for c in all_candidates if c.ticker.upper() == tk), None)

            if matching is None:
                # System never saw any news for this ticker
                results["missed_discovery"].append({
                    "ticker": tk,
                    "change_pct": round(change, 2),
                    "price": mover.price,
                    "volume": mover.volume,
                    "reason": "no news event registered for ticker today",
                })
                timing_review_items.append({
                    "event_type": "missed_discovery",
                    "mover": mover,
                })
                logger.info("EOD: MISSED_DISCOVERY %s (+%.1f%%)", tk, change)
                continue

            # We saw it — did we alert?
            if matching.telegram_sent:
                results["caught"].append({
                    "ticker": tk,
                    "change_pct": round(change, 2),
                    "headline": matching.headline[:80],
                    "alert_score": matching.news_impact_score,
                })
                timing_review_items.append({
                    "event_type": "alerted",
                    "candidate": matching,
                    "mover": mover,
                })
                logger.info("EOD: CAUGHT %s (+%.1f%%) - alerted", tk, change)
            else:
                # Saw it but didn't alert — use existing missed_learning to analyze why
                analysis = self._analyze_missed_alert(matching, mover)
                results["missed_alert"].append(analysis)
                timing_review_items.append({
                    "event_type": "blocked",
                    "candidate": matching,
                    "mover": mover,
                })
                logger.info(
                    "EOD: MISSED_ALERT %s (+%.1f%%) - reason: %s",
                    tk, change, analysis.get("primary_reason", "unknown")
                )

        # Build summary
        results["summary"] = {
            "total_big_movers": len(big_movers),
            "missed_discovery_count": len(results["missed_discovery"]),
            "missed_alert_count": len(results["missed_alert"]),
            "caught_count": len(results["caught"]),
            "discovery_rate_pct": round(
                100 * (len(big_movers) - len(results["missed_discovery"])) / max(1, len(big_movers)),
                1,
            ),
            "alert_rate_pct": round(
                100 * len(results["caught"]) / max(1, len(big_movers)),
                1,
            ),
        }

        # Persist
        self._save_report(results)
        self._save_timing_reviews(today, timing_review_items)
        self._last_report_date = today

        logger.info(
            "EOD review complete: %d movers, %d missed discoveries, %d missed alerts, %d caught",
            results["summary"]["total_big_movers"],
            results["summary"]["missed_discovery_count"],
            results["summary"]["missed_alert_count"],
            results["summary"]["caught_count"],
        )

        # Send summary Telegram alert
        await self._send_summary_telegram(results)

        return results

    def _save_timing_reviews(self, review_date: str, items: list[dict]) -> None:
        if not items:
            return
        try:
            from src.db.session import SessionLocal
            from src.core.agentic.timing_intelligence import TimingReviewService

            db = SessionLocal()
            try:
                rows = TimingReviewService(db).record_eod_reviews(
                    review_date=review_date,
                    items=items,
                )
                logger.info("EOD timing review: persisted %d rows", len(rows))
            finally:
                db.close()
        except Exception as exc:
            logger.warning("EOD timing review persistence failed: %s", exc)

    def _analyze_missed_alert(self, candidate, mover) -> Dict:
        """Analyze why a discovered candidate did not trigger an alert."""
        cfg = self.orchestrator.config
        reasons = []

        if candidate.news_impact_score < cfg.telegram_min_score:
            reasons.append(f"impact {candidate.news_impact_score:.0f} < {cfg.telegram_min_score}")
        if candidate.expected_return_score < cfg.expected_return_threshold:
            reasons.append(f"er {candidate.expected_return_score:.0f} < {cfg.expected_return_threshold}")
        if candidate.continuation_probability < cfg.continuation_threshold:
            reasons.append(f"cont {candidate.continuation_probability:.0f} < {cfg.continuation_threshold}")
        if candidate.trap_risk > 80:
            reasons.append(f"trap {candidate.trap_risk:.0f} > 80")
        if candidate.dilution_risk > 70:
            reasons.append(f"dilution {candidate.dilution_risk:.0f} > 70")
        if candidate.is_negative:
            reasons.append("classified negative")
        if candidate.is_vague and candidate.news_impact_score < 80:
            reasons.append("vague PR blocked")
        if candidate.current_price and (
            candidate.current_price < cfg.min_price or candidate.current_price > cfg.max_price
        ):
            reasons.append(f"price {candidate.current_price:.2f} outside range")

        return {
            "ticker": candidate.ticker,
            "change_pct": round(mover.change_percent or 0, 2),
            "headline": candidate.headline[:100],
            "catalyst": candidate.catalyst_sub_type.value,
            "session": candidate.session.value,
            "scores": {
                "impact": round(candidate.news_impact_score, 1),
                "expected_return": round(candidate.expected_return_score, 1),
                "continuation": round(candidate.continuation_probability, 1),
                "trap_risk": round(candidate.trap_risk, 1),
            },
            "primary_reason": reasons[0] if reasons else "unknown",
            "all_reasons": reasons,
        }

    def _save_report(self, report: Dict) -> None:
        """Append report to JSON file (keep last 30 days)."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        existing = load_json_file(EOD_REPORT_FILE, default=[])
        # Replace today's report if it exists
        existing = [r for r in existing if r.get("date") != report["date"]]
        existing.append(report)
        # Keep last 30
        existing = sorted(existing, key=lambda r: r.get("date", ""))[-30:]
        save_json_file(EOD_REPORT_FILE, existing)

    async def _send_summary_telegram(self, report: Dict) -> None:
        """Send EOD summary to Telegram."""
        try:
            from src.services.telegram_service import send_telegram_alert
        except Exception:
            logger.warning("Telegram service not available for EOD summary")
            return

        s = report["summary"]
        lines = [
            "<b>📊 NEWS MOMENTUM EOD REPORT</b>",
            f"<i>Date: {report['date']}</i>\n",
            f"<b>Big Movers (≥{MIN_GAINER_PCT}%):</b> {s['total_big_movers']}",
            f"<b>Caught:</b> {s['caught_count']} ({s['alert_rate_pct']}% alert rate)",
            f"<b>Missed Alert:</b> {s['missed_alert_count']} (saw news, didn't alert)",
            f"<b>Missed Discovery:</b> {s['missed_discovery_count']} (never saw news)",
            f"<b>Discovery Rate:</b> {s['discovery_rate_pct']}%\n",
        ]

        # Top 3 missed discoveries
        if report["missed_discovery"]:
            lines.append("<b>🔍 Top Missed Discoveries:</b>")
            for m in report["missed_discovery"][:3]:
                lines.append(f"  • {m['ticker']} +{m['change_pct']}%")

        # Top 3 missed alerts with reasons
        if report["missed_alert"]:
            lines.append("\n<b>🚫 Top Missed Alerts:</b>")
            for m in report["missed_alert"][:3]:
                lines.append(
                    f"  • {m['ticker']} +{m['change_pct']}% — {m['primary_reason']}"
                )

        try:
            await send_telegram_alert("\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            logger.warning("EOD summary telegram failed: %s", exc)

    def get_latest_report(self) -> Optional[Dict]:
        reports = load_json_file(EOD_REPORT_FILE, default=[])
        return reports[-1] if reports else None

    def get_all_reports(self, limit: int = 30) -> List[Dict]:
        reports = load_json_file(EOD_REPORT_FILE, default=[])
        return reports[-limit:]
