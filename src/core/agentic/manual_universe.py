"""
Strategic manual-universe access for Pre-News.

The existing watchlist table stores user-tracked tickers. Pre-News only needs
the active ticker symbols, not legacy watchlist UI alerts/timeline behavior.
"""

from __future__ import annotations

import logging

from src.db.session import SessionLocal
from src.models.strategic import ManualUniverseTicker

logger = logging.getLogger(__name__)


def get_manual_universe_tickers() -> list[str]:
    """Return active manually tracked tickers for strategic universe expansion."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ManualUniverseTicker.ticker)
            .filter(
                ManualUniverseTicker.active.is_(True),
                ManualUniverseTicker.status != "archived",
            )
            .order_by(ManualUniverseTicker.priority_score.desc())
            .all()
        )
        return [str(row[0]).upper() for row in rows if row and row[0]]
    except Exception as exc:
        logger.debug("Manual universe ticker fetch failed: %s", exc)
        return []
    finally:
        db.close()
