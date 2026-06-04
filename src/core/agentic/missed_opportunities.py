"""
Agentic Missed Opportunity Engine — Part 14

At end of day, scans for stocks that moved 30%+ / 50%+ / 100%+.
Classifies whether the system discovered, alerted, rejected, or missed them.
"""

import logging
from datetime import datetime, timezone

import yfinance as yf

from src.core.agentic.models import MissedOpportunity, MissedClass, AgenticCandidate

logger = logging.getLogger(__name__)

# Screen universe — top movers are discovered from Yahoo Finance most active / gainers
GAINER_SCREEN_COUNT = 50


def _fetch_top_gainers() -> list[dict]:
    """
    Fetch today's top gainers via yfinance screener.
    Returns list of {ticker, change_pct, price, volume, high, low}.
    """
    results = []
    try:
        import yfinance as yf
        # yfinance doesn't have a built-in screener for gainers,
        # so we use a broad approach: check known momentum tickers + Finviz
        # For now, use the trending tickers endpoint
        trending = yf.Tickers(
            " ".join(getattr(yf, "get_trending", lambda: [])() or [])
        )
        # Fallback: manual approach
    except Exception:
        pass

    return results


class MissedOpportunityEngine:
    """Analyze end-of-day movers against what the system discovered."""

    def analyze(
        self,
        candidates: dict[str, AgenticCandidate],
        movers: list[dict] | None = None,
    ) -> list[MissedOpportunity]:
        """
        Compare today's big movers against discovered candidates.

        Args:
            candidates: current agentic candidates dict
            movers: list of {ticker, change_pct, high, low, volume} — if None, attempts to fetch

        Returns:
            list of MissedOpportunity records
        """
        if movers is None:
            movers = self._scan_for_big_movers()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []

        for mover in movers:
            ticker = mover["ticker"]
            move_pct = mover.get("change_pct", 0)

            if move_pct < 30:
                continue

            was_discovered = ticker in candidates
            cand = candidates.get(ticker)
            was_alerted = False
            was_rejected = False
            rejection_reason = None
            prob_at_time = None

            if cand:
                was_alerted = cand.alertable
                was_rejected = cand.rejected
                rejection_reason = ", ".join(cand.rejection_reasons) if cand.rejection_reasons else None
                prob_at_time = cand.final_probability

            # Classify
            if not was_discovered:
                classification = MissedClass.NOT_DISCOVERED
                lessons = ["Stock was not in catalyst scanner results — expand discovery sources"]
            elif was_rejected:
                # Was it correctly rejected (moved <50% and had trap signals) or wrongly?
                if move_pct > 50:
                    classification = MissedClass.REJECTED_WRONG
                    lessons = [
                        f"Rejected with prob={prob_at_time} but moved {move_pct:.0f}%",
                        f"Rejection: {rejection_reason}",
                        "Consider loosening rejection criteria for this catalyst type",
                    ]
                else:
                    classification = MissedClass.CORRECTLY_AVOIDED
                    lessons = [f"Rejected and only moved {move_pct:.0f}% — correct avoid"]
            elif was_alerted:
                classification = MissedClass.CORRECTLY_AVOIDED  # We caught it
                lessons = [f"Successfully alerted — prob was {prob_at_time:.0f}%"]
            elif prob_at_time and prob_at_time < 50:
                classification = MissedClass.LOW_SCORE
                lessons = [
                    f"Discovered but scored only {prob_at_time:.0f}%",
                    "Review which sub-scores were low",
                ]
            else:
                classification = MissedClass.TOO_LATE
                lessons = ["Discovered but timing/conditions never aligned for alert"]

            results.append(MissedOpportunity(
                ticker=ticker,
                date=today,
                move_pct=move_pct,
                high_price=mover.get("high", 0),
                low_price=mover.get("low", 0),
                volume=mover.get("volume", 0),
                classification=classification,
                was_discovered=was_discovered,
                was_alerted=was_alerted,
                was_rejected=was_rejected,
                rejection_reason=rejection_reason,
                candidate_probability_at_time=prob_at_time,
                lessons=lessons,
            ))

        logger.info(
            "MissedOpportunityEngine: %d big movers analyzed, %d missed",
            len(results),
            sum(1 for r in results if r.classification != MissedClass.CORRECTLY_AVOIDED),
        )
        return results

    def _scan_for_big_movers(self) -> list[dict]:
        """Scan market for stocks that moved 30%+ today using yfinance."""
        movers = []
        try:
            # Try screening a broad universe
            from src.services.market_data import DEFAULT_SCAN_UNIVERSE
            tickers = DEFAULT_SCAN_UNIVERSE[:80]

            for t in tickers:
                try:
                    fi = yf.Ticker(t).fast_info
                    price = float(getattr(fi, "last_price", 0) or 0)
                    prev = float(getattr(fi, "previous_close", 0) or 0)
                    if prev > 0:
                        change = ((price - prev) / prev) * 100
                        if change >= 30:
                            movers.append({
                                "ticker": t,
                                "change_pct": round(change, 2),
                                "high": float(getattr(fi, "day_high", price) or price),
                                "low": float(getattr(fi, "day_low", price) or price),
                                "volume": float(getattr(fi, "last_volume", 0) or 0),
                            })
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Big mover scan failed: %s", e)

        return movers
