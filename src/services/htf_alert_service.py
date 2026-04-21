"""HTF Change Alert Service — V9

Detects and alerts on meaningful HTF context changes:
- Bias transitions (BULLISH → NEUTRAL → BEARISH)
- Alignment changes (ALIGNED → COUNTER_TREND)
- Strength threshold crossings
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable
from datetime import datetime
from enum import Enum

from src.models.schemas import WatchlistItem, TradingSignal
from src.core.higher_timeframe_bias import HTFBias, AlignmentStatus

logger = logging.getLogger(__name__)


class HTFAlertType(Enum):
    """Types of HTF alerts."""
    BIAS_FLIP = "bias_flip"
    ALIGNMENT_CHANGE = "alignment_change"
    STRENGTH_DROP = "strength_drop"
    STRENGTH_RISE = "strength_rise"
    NEWLY_ALIGNED = "newly_aligned"
    HTF_BLOCKED = "htf_blocked"
    HTF_FAVORABLE = "htf_favorable"


@dataclass
class HTFAlert:
    """HTF context change alert."""
    ticker: str
    alert_type: HTFAlertType
    previous_bias: Optional[str]
    new_bias: Optional[str]
    previous_alignment: Optional[str]
    new_alignment: Optional[str]
    previous_strength: Optional[float]
    new_strength: Optional[float]
    explanation: str
    timestamp: str
    severity: str  # info/warning/critical


class HTFAlertService:
    """
    V9: HTF Alert Service
    
    Monitors HTF context and generates alerts on meaningful changes.
    
    Usage:
        alerts = HTFAlertService()
        alerts.check_watchlist(watchlist_items)
        
        # In signal generation:
        alert = alerts.check_signal(ticker, new_htf_result)
        if alert:
            notify_user(alert)
    """
    
    # Thresholds
    STRENGTH_LOW_THRESHOLD = 30.0
    STRENGTH_HIGH_THRESHOLD = 70.0
    SIGNIFICANT_CHANGE_PCT = 15.0
    
    def __init__(self):
        self._history: Dict[str, dict] = {}  # ticker -> last HTF state
        self._listeners: List[Callable[[HTFAlert], None]] = []
    
    def add_listener(self, callback: Callable[[HTFAlert], None]):
        """Register a callback to receive alerts."""
        self._listeners.append(callback)
    
    def check_watchlist(self, items: List[WatchlistItem]) -> List[HTFAlert]:
        """Check all watchlist items for HTF changes."""
        alerts = []
        for item in items:
            current_state = self._extract_state(item)
            alert = self._detect_change(item.ticker, current_state)
            if alert:
                alerts.append(alert)
                self._notify(alert)
        return alerts
    
    def check_signal(self, ticker: str, htf_result) -> Optional[HTFAlert]:
        """Check a single signal/ticker for HTF changes."""
        current_state = self._extract_state_from_result(htf_result)
        alert = self._detect_change(ticker, current_state)
        if alert:
            self._notify(alert)
        return alert
    
    def _extract_state(self, item: WatchlistItem) -> dict:
        """Extract HTF state from watchlist item."""
        return {
            'bias': item.latest_htf_bias,
            'alignment': item.latest_alignment_status,
            'strength': item.latest_htf_strength_score,
            'blocked': item.latest_htf_blocked,
            'timestamp': datetime.now().isoformat()
        }
    
    def _extract_state_from_result(self, htf_result) -> dict:
        """Extract HTF state from detector result."""
        if not htf_result:
            return {'bias': None, 'alignment': None, 'strength': None, 'blocked': False}
        
        return {
            'bias': htf_result.bias.value if hasattr(htf_result.bias, 'value') else str(htf_result.bias),
            'alignment': getattr(htf_result, 'alignment_status', None),
            'strength': getattr(htf_result, 'strength_score', None),
            'blocked': getattr(htf_result, 'trade_blocked', False)
        }
    
    def _detect_change(self, ticker: str, current: dict) -> Optional[HTFAlert]:
        """Detect if there's a meaningful change from previous state."""
        previous = self._history.get(ticker)
        self._history[ticker] = current
        
        if not previous:
            return None  # First time seeing this ticker
        
        # Check bias flip
        if current['bias'] != previous['bias'] and current['bias'] and previous['bias']:
            return self._create_bias_flip_alert(ticker, previous, current)
        
        # Check alignment change
        if current['alignment'] != previous['alignment']:
            return self._create_alignment_alert(ticker, previous, current)
        
        # Check strength threshold crossing
        if current['strength'] and previous['strength']:
            strength_delta = current['strength'] - previous['strength']
            if abs(strength_delta) >= self.SIGNIFICANT_CHANGE_PCT:
                return self._create_strength_alert(ticker, previous, current, strength_delta)
        
        # Check newly HTF blocked
        if current.get('blocked') and not previous.get('blocked'):
            return HTFAlert(
                ticker=ticker,
                alert_type=HTFAlertType.HTF_BLOCKED,
                previous_bias=previous.get('bias'),
                new_bias=current.get('bias'),
                previous_alignment=previous.get('alignment'),
                new_alignment=current.get('alignment'),
                previous_strength=previous.get('strength'),
                new_strength=current.get('strength'),
                explanation=f"{ticker} is now HTF blocked due to bearish daily context",
                timestamp=datetime.now().isoformat(),
                severity="warning"
            )
        
        # Check newly favorable (was blocked, now aligned)
        if previous.get('blocked') and not current.get('blocked') and current.get('bias') == 'BULLISH':
            return HTFAlert(
                ticker=ticker,
                alert_type=HTFAlertType.HTF_FAVORABLE,
                previous_bias=previous.get('bias'),
                new_bias=current.get('bias'),
                previous_alignment=previous.get('alignment'),
                new_alignment=current.get('alignment'),
                previous_strength=previous.get('strength'),
                new_strength=current.get('strength'),
                explanation=f"{ticker} is now HTF favorable (bullish alignment)",
                timestamp=datetime.now().isoformat(),
                severity="info"
            )
        
        return None
    
    def _create_bias_flip_alert(self, ticker: str, prev: dict, curr: dict) -> HTFAlert:
        """Create alert for bias transition."""
        prev_bias = prev['bias']
        curr_bias = curr['bias']
        
        # Determine severity
        if (prev_bias == "BULLISH" and curr_bias == "BEARISH") or \
           (prev_bias == "BEARISH" and curr_bias == "BULLISH"):
            severity = "critical"
        elif prev_bias in ["BULLISH", "BEARISH"] and curr_bias == "NEUTRAL":
            severity = "warning"
        else:
            severity = "info"
        
        explanation = f"{ticker} HTF bias changed: {prev_bias} → {curr_bias}"
        
        return HTFAlert(
            ticker=ticker,
            alert_type=HTFAlertType.BIAS_FLIP,
            previous_bias=prev_bias,
            new_bias=curr_bias,
            previous_alignment=prev.get('alignment'),
            new_alignment=curr.get('alignment'),
            previous_strength=prev.get('strength'),
            new_strength=curr.get('strength'),
            explanation=explanation,
            timestamp=datetime.now().isoformat(),
            severity=severity
        )
    
    def _create_alignment_alert(self, ticker: str, prev: dict, curr: dict) -> HTFAlert:
        """Create alert for alignment change."""
        prev_align = prev.get('alignment')
        curr_align = curr.get('alignment')
        
        if curr_align == "ALIGNED":
            severity = "info"
            explanation = f"{ticker} is now ALIGNED with HTF bias"
        elif curr_align == "COUNTER_TREND":
            severity = "warning"
            explanation = f"{ticker} is now COUNTER-TREND to HTF bias"
        else:
            severity = "info"
            explanation = f"{ticker} alignment changed: {prev_align} → {curr_align}"
        
        return HTFAlert(
            ticker=ticker,
            alert_type=HTFAlertType.ALIGNMENT_CHANGE,
            previous_bias=prev.get('bias'),
            new_bias=curr.get('bias'),
            previous_alignment=prev_align,
            new_alignment=curr_align,
            previous_strength=prev.get('strength'),
            new_strength=curr.get('strength'),
            explanation=explanation,
            timestamp=datetime.now().isoformat(),
            severity=severity
        )
    
    def _create_strength_alert(self, ticker: str, prev: dict, curr: dict, delta: float) -> HTFAlert:
        """Create alert for strength threshold crossing."""
        prev_strength = prev['strength']
        curr_strength = curr['strength']
        
        # Check threshold crossings
        crossed_high = prev_strength < self.STRENGTH_HIGH_THRESHOLD <= curr_strength
        crossed_low = prev_strength > self.STRENGTH_LOW_THRESHOLD >= curr_strength
        
        if crossed_high:
            alert_type = HTFAlertType.STRENGTH_RISE
            severity = "info"
            explanation = f"{ticker} HTF strength crossed above {self.STRENGTH_HIGH_THRESHOLD} (now {curr_strength:.0f})"
        elif crossed_low:
            alert_type = HTFAlertType.STRENGTH_DROP
            severity = "warning"
            explanation = f"{ticker} HTF strength dropped below {self.STRENGTH_LOW_THRESHOLD} (now {curr_strength:.0f})"
        elif delta > 0:
            alert_type = HTFAlertType.STRENGTH_RISE
            severity = "info"
            explanation = f"{ticker} HTF strength increased by {delta:.0f} points"
        else:
            alert_type = HTFAlertType.STRENGTH_DROP
            severity = "info"
            explanation = f"{ticker} HTF strength decreased by {abs(delta):.0f} points"
        
        return HTFAlert(
            ticker=ticker,
            alert_type=alert_type,
            previous_bias=prev.get('bias'),
            new_bias=curr.get('bias'),
            previous_alignment=prev.get('alignment'),
            new_alignment=curr.get('alignment'),
            previous_strength=prev_strength,
            new_strength=curr_strength,
            explanation=explanation,
            timestamp=datetime.now().isoformat(),
            severity=severity
        )
    
    def _notify(self, alert: HTFAlert):
        """Notify all registered listeners."""
        for callback in self._listeners:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert listener failed: {e}")
    
    def get_alert_summary(self, alerts: List[HTFAlert]) -> dict:
        """Get summary statistics for a list of alerts."""
        if not alerts:
            return {"total": 0, "by_type": {}, "by_severity": {}}
        
        by_type = {}
        by_severity = {}
        
        for alert in alerts:
            by_type[alert.alert_type.value] = by_type.get(alert.alert_type.value, 0) + 1
            by_severity[alert.severity] = by_severity.get(alert.severity, 0) + 1
        
        return {
            "total": len(alerts),
            "by_type": by_type,
            "by_severity": by_severity
        }


# Singleton instance for global access
_htf_alert_service: Optional[HTFAlertService] = None


def get_htf_alert_service() -> HTFAlertService:
    """Get or create global HTF alert service."""
    global _htf_alert_service
    if _htf_alert_service is None:
        _htf_alert_service = HTFAlertService()
    return _htf_alert_service
