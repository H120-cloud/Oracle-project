"""
Agentic Time of Day Engine — Part 7

Classifies the current trading session and adjusts probability accordingly.
"""

import logging
from datetime import datetime, timezone

from src.core.agentic.models import TimeOfDayResult, TradingSession, AgenticCandidate
from src.core.agentic.calibration_provider import get_calibration_weights

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except ImportError:
    from datetime import timedelta
    _ET = timezone(timedelta(hours=-5))  # fallback EST

logger = logging.getLogger(__name__)

MAX_MULTIPLIER = 1.15
MIN_MULTIPLIER = 0.85


def _clamp_multiplier(m: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, m))


def _get_et_now() -> datetime:
    return datetime.now(_ET)


class TimeOfDayEngine:
    """Classify session and return probability adjustment."""

    def __init__(self):
        self.cw = get_calibration_weights()
        if self.cw:
            logger.info("TimeOfDayEngine loaded calibration v%s", self.cw.version)

    def classify(self, candidate: AgenticCandidate) -> AgenticCandidate:
        now = _get_et_now()
        hour, minute = now.hour, now.minute
        t = hour * 60 + minute  # minutes since midnight ET

        if t < 570:                         # Before 9:30
            session = TradingSession.PREMARKET
            adj = -5.0
            reason = "Pre-market: reduced liquidity, gaps possible"
        elif t < 630:                       # 9:30–10:30
            session = TradingSession.OPEN
            adj = 10.0
            reason = "Opening range: highest probability for continuation"
        elif t < 840:                       # 10:30–14:00
            session = TradingSession.MIDDAY
            adj = -10.0
            reason = "Midday chop: low probability of clean second legs"
        elif t < 900:                       # 14:00–15:00
            session = TradingSession.MIDDAY
            adj = -5.0
            reason = "Late afternoon: building toward power hour"
        elif t < 960:                       # 15:00–16:00
            session = TradingSession.POWER_HOUR
            adj = 5.0
            reason = "Power hour: renewed volume and directional moves"
        else:
            session = TradingSession.AFTERHOURS
            adj = -15.0
            reason = "After-hours: thin liquidity, avoid new entries"

        calibrated = False
        if self.cw and self.cw.time_of_day_w != 1.0:
            mult = _clamp_multiplier(self.cw.time_of_day_w)
            adj = round(adj * mult, 1)
            calibrated = True
            logger.info("TimeOfDayEngine applied time_of_day_w=%s -> adj=%s", mult, adj)

        candidate.time_of_day = TimeOfDayResult(
            session=session,
            probability_adjustment=adj,
            reason=reason,
            calibrated=calibrated,
        )

        return candidate
