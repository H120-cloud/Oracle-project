"""
Setup Classification & Playbook Engine — Parts 16 + 17

Part 16: Classify each trade setup:
- DIP_BUY / BREAKOUT / REVERSAL / CONTINUATION / SHORT

Part 17: Playbook strategies with specific rules:
- News Breakout
- Dip + Reclaim
- Liquidity Sweep Reversal
- Trend Continuation

Each playbook defines: entry rules, stop rules, target rules.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class SetupType(str, Enum):
    DIP_BUY = "DIP_BUY"
    BREAKOUT = "BREAKOUT"
    REVERSAL = "REVERSAL"
    CONTINUATION = "CONTINUATION"
    SHORT = "SHORT"
    NO_SETUP = "NO_SETUP"


class PlaybookName(str, Enum):
    NEWS_BREAKOUT = "NEWS_BREAKOUT"
    DIP_RECLAIM = "DIP_RECLAIM"
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    EARNINGS_GAP = "EARNINGS_GAP"
    NO_PLAYBOOK = "NO_PLAYBOOK"


@dataclass
class PlaybookRules:
    """Rules for a specific playbook."""
    name: PlaybookName
    entry_rules: List[str] = field(default_factory=list)
    stop_rules: List[str] = field(default_factory=list)
    target_rules: List[str] = field(default_factory=list)
    conditions_met: int = 0
    conditions_total: int = 0
    match_score: float = 0.0  # 0–100


@dataclass
class SetupAnalysis:
    """Complete setup classification and playbook match."""
    ticker: str
    setup_type: SetupType = SetupType.NO_SETUP
    playbook: PlaybookName = PlaybookName.NO_PLAYBOOK
    playbook_rules: Optional[PlaybookRules] = None
    playbook_match_score: float = 0.0
    setup_reasons: List[str] = field(default_factory=list)

    # All evaluated playbooks
    evaluated_playbooks: List[PlaybookRules] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "setup_type": self.setup_type.value,
            "playbook": self.playbook.value,
            "playbook_match_score": self.playbook_match_score,
            "setup_reasons": self.setup_reasons,
            "playbook_rules": {
                "entry": self.playbook_rules.entry_rules if self.playbook_rules else [],
                "stop": self.playbook_rules.stop_rules if self.playbook_rules else [],
                "target": self.playbook_rules.target_rules if self.playbook_rules else [],
            } if self.playbook_rules else None,
        }


class PlaybookEngine:
    """Classifies setups and matches to trading playbooks."""

    def analyze(
        self,
        ticker: str,
        probability=None,     # ProbabilityResult
        news_summary=None,    # TickerNewsSummary
        liquidity=None,       # LiquidityAnalysis
        entry_analysis=None,  # EntryAnalysis
        target=None,          # PriceTarget
        dip_result=None,
        bounce_result=None,
        ict_features=None,
        mtf_result=None,
    ) -> SetupAnalysis:
        """Classify setup and match playbook."""
        result = SetupAnalysis(ticker=ticker)

        # Step 1: Classify setup type
        result.setup_type, result.setup_reasons = self._classify_setup(
            probability, news_summary, liquidity, dip_result, bounce_result,
            ict_features, entry_analysis, mtf_result,
        )

        # Step 2: Evaluate all playbooks
        playbooks = [
            self._eval_news_breakout(news_summary, probability, entry_analysis, target),
            self._eval_dip_reclaim(dip_result, bounce_result, liquidity, entry_analysis, target),
            self._eval_sweep_reversal(liquidity, ict_features, entry_analysis, target),
            self._eval_trend_continuation(mtf_result, probability, entry_analysis, target),
        ]
        result.evaluated_playbooks = playbooks

        # Step 3: Pick best matching playbook
        best = max(playbooks, key=lambda p: p.match_score) if playbooks else None
        if best and best.match_score >= 40:
            result.playbook = best.name
            result.playbook_rules = best
            result.playbook_match_score = best.match_score

        logger.info(
            "Playbook [%s]: setup=%s playbook=%s score=%.0f%%",
            ticker, result.setup_type.value, result.playbook.value, result.playbook_match_score,
        )

        return result

    # ── Setup Classification ──────────────────────────────────────────────

    def _classify_setup(self, prob, news, liq, dip, bounce, ict, entry, mtf) -> tuple:
        """Classify the type of setup."""
        reasons = []

        # Short setup
        if prob and prob.bearish_probability >= 65:
            if entry and entry.reversal.detected:
                reasons.append(f"Bearish probability {prob.bearish_probability:.0f}% with reversal")
                return SetupType.SHORT, reasons

        # Dip buy
        if dip and getattr(dip, 'is_valid_dip', False):
            if bounce and getattr(bounce, 'entry_ready', False):
                reasons.append("Valid dip with bounce ready")
                return SetupType.DIP_BUY, reasons
            if bounce and getattr(bounce, 'probability', 0) >= 50:
                reasons.append("Valid dip with bounce forming")
                return SetupType.DIP_BUY, reasons

        # Breakout
        if liq and liq.breakout_type.value == "TRUE_BREAKOUT":
            reasons.append("True breakout with volume")
            return SetupType.BREAKOUT, reasons
        if news and news.has_breaking_news and news.has_tier1_catalyst:
            reasons.append("News catalyst breakout")
            return SetupType.BREAKOUT, reasons

        # Reversal
        if liq and liq.sweep_detected and liq.sweep_reclaimed:
            reasons.append("Liquidity sweep reversal")
            return SetupType.REVERSAL, reasons

        # Continuation
        if mtf and mtf.alignment_score >= 60:
            bias = mtf.overall_bias.value if hasattr(mtf.overall_bias, 'value') else str(mtf.overall_bias)
            if "BULLISH" in bias:
                reasons.append(f"Trend continuation (MTF aligned {mtf.alignment_score:.0f}%)")
                return SetupType.CONTINUATION, reasons

        reasons.append("No clear setup identified")
        return SetupType.NO_SETUP, reasons

    # ── Playbook: News Breakout ───────────────────────────────────────────

    def _eval_news_breakout(self, news, prob, entry, target) -> PlaybookRules:
        """Evaluate News Breakout playbook."""
        pb = PlaybookRules(
            name=PlaybookName.NEWS_BREAKOUT,
            entry_rules=[
                "Tier 1 or Tier 2 catalyst",
                "News is BREAKING or FRESH",
                "Reaction is ACTIVE or INITIAL",
                "Volume > 2x average",
                "Wait for first pullback, enter on reclaim of VWAP or intraday high",
            ],
            stop_rules=[
                "Stop below pre-news low",
                "Or below VWAP if entering on reclaim",
                "Max stop: 1.5 ATR below entry",
            ],
            target_rules=[
                "T1: Next resistance level",
                "T2: 2x the news-driven range extension",
                "Trail stop after T1 hit",
            ],
        )
        pb.conditions_total = 5

        if news:
            if news.has_tier1_catalyst or (news.catalyst_score >= 50):
                pb.conditions_met += 1
            label = news.freshness_label.value if hasattr(news.freshness_label, 'value') else str(news.freshness_label)
            if label in ("BREAKING", "FRESH"):
                pb.conditions_met += 1
            react = news.reaction_state.value if hasattr(news.reaction_state, 'value') else str(news.reaction_state)
            if react in ("ACTIVE", "INITIAL"):
                pb.conditions_met += 1
        if entry and entry.entry.volume_confirmed:
            pb.conditions_met += 1
        if target and target.reward_risk_ratio >= 2:
            pb.conditions_met += 1

        pb.match_score = pb.conditions_met / pb.conditions_total * 100 if pb.conditions_total > 0 else 0
        return pb

    # ── Playbook: Dip + Reclaim ───────────────────────────────────────────

    def _eval_dip_reclaim(self, dip, bounce, liq, entry, target) -> PlaybookRules:
        """Evaluate Dip + Reclaim playbook."""
        pb = PlaybookRules(
            name=PlaybookName.DIP_RECLAIM,
            entry_rules=[
                "Valid dip detected (dip probability > 50%)",
                "Bounce forming with higher low",
                "Reclaim of key level (EMA/VWAP/support)",
                "Volume confirmation on reclaim",
                "Not overextended (< 8% from open)",
            ],
            stop_rules=[
                "Stop below the dip low",
                "Or below the reclaimed level",
                "Max stop: 1 ATR below entry",
            ],
            target_rules=[
                "T1: Previous high before dip",
                "T2: 1.5x the dip range extension",
                "Close partial at T1, trail rest",
            ],
        )
        pb.conditions_total = 5

        if dip and getattr(dip, 'is_valid_dip', False):
            pb.conditions_met += 1
        if bounce and getattr(bounce, 'probability', 0) >= 50:
            pb.conditions_met += 1
        if bounce and getattr(bounce, 'features', None):
            if getattr(bounce.features, 'key_level_reclaimed', False):
                pb.conditions_met += 1
        if entry and entry.entry.volume_confirmed:
            pb.conditions_met += 1
        if entry and entry.timing.timing_label.value in ("EARLY", "IDEAL"):
            pb.conditions_met += 1

        pb.match_score = pb.conditions_met / pb.conditions_total * 100 if pb.conditions_total > 0 else 0
        return pb

    # ── Playbook: Liquidity Sweep Reversal ────────────────────────────────

    def _eval_sweep_reversal(self, liq, ict, entry, target) -> PlaybookRules:
        """Evaluate Liquidity Sweep Reversal playbook."""
        pb = PlaybookRules(
            name=PlaybookName.LIQUIDITY_SWEEP_REVERSAL,
            entry_rules=[
                "Liquidity sweep detected (stop hunt below key level)",
                "Quick reclaim of swept level",
                "Bullish structure break after sweep",
                "Volume expansion on reclaim",
                "Near order block or demand zone",
            ],
            stop_rules=[
                "Stop below the sweep low (invalidation)",
                "Tight stop: bottom of sweep wick",
                "Max stop: 1.5 ATR below entry",
            ],
            target_rules=[
                "T1: Equal highs / liquidity above",
                "T2: Next major resistance",
                "High R:R (often 3:1+)",
            ],
        )
        pb.conditions_total = 5

        if liq:
            if liq.sweep_detected:
                pb.conditions_met += 1
            if liq.sweep_reclaimed:
                pb.conditions_met += 1
        if ict:
            if getattr(ict, 'structure_break_confirmed', False):
                pb.conditions_met += 1
            if getattr(ict, 'near_order_block', False):
                pb.conditions_met += 1
        if entry and entry.entry.volume_confirmed:
            pb.conditions_met += 1

        pb.match_score = pb.conditions_met / pb.conditions_total * 100 if pb.conditions_total > 0 else 0
        return pb

    # ── Playbook: Trend Continuation ──────────────────────────────────────

    def _eval_trend_continuation(self, mtf, prob, entry, target) -> PlaybookRules:
        """Evaluate Trend Continuation playbook."""
        pb = PlaybookRules(
            name=PlaybookName.TREND_CONTINUATION,
            entry_rules=[
                "Multi-timeframe alignment (3+ TFs bullish)",
                "Pullback to EMA20 or EMA50",
                "Bullish probability > 60%",
                "Volume increasing on pullback recovery",
                "Higher timeframe trend is bullish",
            ],
            stop_rules=[
                "Stop below EMA50 or swing low",
                "Tight stop below pullback low",
                "Max stop: 1 ATR below entry",
            ],
            target_rules=[
                "T1: Previous swing high",
                "T2: Measured move (equal legs)",
                "Trail with EMA9 on entry timeframe",
            ],
        )
        pb.conditions_total = 5

        if mtf:
            if mtf.alignment_score >= 60:
                pb.conditions_met += 1
            bias = mtf.overall_bias.value if hasattr(mtf.overall_bias, 'value') else str(mtf.overall_bias)
            if "BULLISH" in bias:
                pb.conditions_met += 1
            if mtf.trend_tf and mtf.trend_tf.bias.value in ("BULLISH", "STRONG_BULLISH"):
                pb.conditions_met += 1
        if prob and prob.bullish_probability >= 60:
            pb.conditions_met += 1
        if entry and entry.entry.volume_confirmed:
            pb.conditions_met += 1

        pb.match_score = pb.conditions_met / pb.conditions_total * 100 if pb.conditions_total > 0 else 0
        return pb
