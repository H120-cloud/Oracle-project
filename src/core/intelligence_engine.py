"""
Market Intelligence Engine — Master Orchestrator (Parts 7, 9, 18, 19)

Combines ALL engines into a unified intelligence pipeline:
1. News Intelligence → catalyst + freshness + reaction
2. Market Context → bull/bear/sideways + sectors
3. Multi-Timeframe → alignment + bias
4. Liquidity → sweeps + traps + fake breakouts
5. Probability → composite bull/bear %
6. Targets → T1/T2 + stop + R:R
7. Entry → quality + timing + reversal + decision
8. Playbook → setup type + matched strategy
9. Adaptation → real-time tracking + EOD learning

Output: Unified MarketIntelligence per ticker
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict

from src.models.schemas import OHLCVBar

logger = logging.getLogger(__name__)


# ── Part 7: Auto Watchlist Rules ──────────────────────────────────────────────

class AutoWatchlistPriority:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    REJECT = "REJECT"


@dataclass
class WatchlistRecommendation:
    """Auto-watchlist recommendation."""
    ticker: str
    priority: str = AutoWatchlistPriority.REJECT
    reason_for_addition: str = ""
    catalyst_summary: str = ""
    reject_reason: str = ""


# ── Part 19: Unified Output ──────────────────────────────────────────────────

@dataclass
class MarketIntelligence:
    """The complete intelligence output for a single stock.
    This is the final output format for the system (Part 19).
    """
    ticker: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Probability
    bullish_probability: float = 50.0
    bearish_probability: float = 50.0

    # Catalyst
    catalyst_tier: str = "TIER_3"
    catalyst_score: float = 0.0
    freshness_label: str = "DEAD"
    reaction_state: str = "NO_REACTION"
    catalyst_summary: str = ""

    # Market context
    market_condition: str = "SIDEWAYS"
    market_momentum: float = 0.0
    sector_strength: str = ""

    # Multi-TF
    mtf_alignment: str = "CONFLICTING"
    mtf_alignment_score: float = 0.0
    trend_bias: str = "NEUTRAL"

    # Execution
    entry_quality: str = "CHASE"
    setup_type: str = "NO_SETUP"
    playbook: str = "NO_PLAYBOOK"
    playbook_match_score: float = 0.0
    breakout_type: str = "NO_BREAKOUT"
    reversal_stage: str = "NONE"

    # Prediction
    target_price_1: float = 0.0
    target_price_2: float = 0.0
    stop_loss: float = 0.0
    predicted_move_pct: float = 0.0
    prediction_confidence: float = 0.0

    # Risk
    reward_risk_ratio: float = 0.0
    entry_timing: str = "TOO_LATE"
    trade_decision: str = "AVOID"

    # Tracking (Part 9)
    progress_to_target: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    trade_status: str = ""

    # Watchlist (Part 7)
    watchlist_priority: str = "REJECT"
    watchlist_reason: str = ""

    # Premarket Data
    premarket_gap_pct: float = 0.0
    premarket_volume: float = 0.0
    premarket_status: str = "NONE"
    premarket_high: float = 0.0
    premarket_low: float = 0.0
    previous_close: float = 0.0
    current_price: float = 0.0
    change_from_close: float = 0.0

    # Reasons
    decision_reasons: List[str] = field(default_factory=list)
    playbook_entry_rules: List[str] = field(default_factory=list)
    playbook_stop_rules: List[str] = field(default_factory=list)
    playbook_target_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "generated_at": self.generated_at.isoformat(),

            "bullish_probability": self.bullish_probability,
            "bearish_probability": self.bearish_probability,

            "catalyst_tier": self.catalyst_tier,
            "catalyst_score": self.catalyst_score,
            "freshness_label": self.freshness_label,
            "reaction_state": self.reaction_state,
            "catalyst_summary": self.catalyst_summary,

            "market_condition": self.market_condition,
            "market_momentum": self.market_momentum,

            "setup_type": self.setup_type,
            "playbook": self.playbook,
            "playbook_match_score": self.playbook_match_score,
            "entry_quality": self.entry_quality,
            "entry_timing": self.entry_timing,
            "trade_decision": self.trade_decision,

            "target_price_1": self.target_price_1,
            "target_price_2": self.target_price_2,
            "stop_loss": self.stop_loss,
            "predicted_move_pct": self.predicted_move_pct,
            "prediction_confidence": self.prediction_confidence,
            "reward_risk_ratio": self.reward_risk_ratio,

            "mtf_alignment": self.mtf_alignment,
            "trend_bias": self.trend_bias,
            "breakout_type": self.breakout_type,
            "reversal_stage": self.reversal_stage,

            "watchlist_priority": self.watchlist_priority,
            "watchlist_reason": self.watchlist_reason,

            "decision_reasons": self.decision_reasons,
            "playbook_entry_rules": self.playbook_entry_rules,
            "playbook_stop_rules": self.playbook_stop_rules,
            "playbook_target_rules": self.playbook_target_rules,

            "progress_to_target": self.progress_to_target,
            "mfe": self.mfe,
            "mae": self.mae,

            "premarket_gap_pct": self.premarket_gap_pct,
            "premarket_volume": self.premarket_volume,
            "premarket_status": self.premarket_status,
            "premarket_high": self.premarket_high,
            "premarket_low": self.premarket_low,
            "previous_close": self.previous_close,
            "current_price": self.current_price,
            "change_from_close": self.change_from_close,
        }


class IntelligenceEngine:
    """
    Master orchestrator — runs all analysis engines and produces
    unified MarketIntelligence output per ticker.
    """

    def __init__(self, provider=None):
        from src.core.news_intelligence import NewsIntelligenceEngine
        from src.core.market_context import MarketContextEngine
        from src.core.multi_timeframe import MultiTimeframeEngine
        from src.core.liquidity_engine import LiquidityEngine
        from src.core.probability_engine import ProbabilityEngine
        from src.core.target_engine import TargetEngine
        from src.core.entry_engine import EntryEngine
        from src.core.playbook_engine import PlaybookEngine
        from src.core.adaptation_engine import AdaptationEngine

        self.provider = provider
        self.news_engine = NewsIntelligenceEngine()
        self.market_ctx_engine = MarketContextEngine(provider)
        self.mtf_engine = MultiTimeframeEngine(provider)
        self.liquidity_engine = LiquidityEngine()
        self.probability_engine = ProbabilityEngine()
        self.target_engine = TargetEngine()
        self.entry_engine = EntryEngine()
        self.playbook_engine = PlaybookEngine()
        self.adaptation = AdaptationEngine()

        # Cache market context (refreshed periodically, not per-ticker)
        self._market_context = None
        self._market_context_time = None

    def get_market_context(self, force_refresh=False):
        """Get cached or fresh market context."""
        now = datetime.now(timezone.utc)
        if (self._market_context is None or force_refresh or
            self._market_context_time is None or
            (now - self._market_context_time).seconds > 300):
            self._market_context = self.market_ctx_engine.analyze()
            self._market_context_time = now
        return self._market_context

    def analyze_ticker(
        self,
        ticker: str,
        # Existing analysis components (from signal pipeline)
        stock=None,
        dip_result=None,
        bounce_result=None,
        ict_features=None,
        vol_profile=None,
        bearish_data=None,
        bars=None,
    ) -> MarketIntelligence:
        """Run full intelligence analysis for a single ticker."""
        intel = MarketIntelligence(ticker=ticker)

        # Fetch bars if not provided
        if bars is None and self.provider:
            bars = self.provider.get_ohlcv(ticker, period="1d", interval="1m")

        # 1. News Intelligence
        news_summary = None
        try:
            avg_vol = 0
            if bars:
                avg_vol = sum(b.volume for b in bars) / len(bars) if bars else 0
            news_summary = self.news_engine.analyze_ticker(ticker, bars, avg_vol)
            if news_summary:
                intel.catalyst_score = news_summary.catalyst_score
                intel.catalyst_tier = news_summary.catalyst_tier.value if hasattr(news_summary.catalyst_tier, 'value') else str(news_summary.catalyst_tier)
                intel.freshness_label = news_summary.freshness_label.value if hasattr(news_summary.freshness_label, 'value') else str(news_summary.freshness_label)
                intel.reaction_state = news_summary.reaction_state.value if hasattr(news_summary.reaction_state, 'value') else str(news_summary.reaction_state)
                if news_summary.strongest_catalyst:
                    intel.catalyst_summary = news_summary.strongest_catalyst.headline[:100]
        except Exception as exc:
            logger.warning("News analysis failed for %s: %s", ticker, exc)

        # 2. Market Context (cached)
        market_ctx = None
        try:
            market_ctx = self.get_market_context()
            if market_ctx:
                intel.market_condition = market_ctx.condition.value
                intel.market_momentum = market_ctx.market_momentum
                if market_ctx.strongest_sector:
                    intel.sector_strength = market_ctx.strongest_sector
        except Exception as exc:
            logger.warning("Market context failed: %s", exc)

        # 2b. Premarket Analysis
        try:
            if bars:
                self._analyze_premarket(ticker, intel, bars)
        except Exception as exc:
            logger.warning("Premarket analysis failed for %s: %s", ticker, exc)

        # 3. Multi-Timeframe
        mtf_result = None
        try:
            mtf_result = self.mtf_engine.analyze(ticker)
            if mtf_result:
                intel.mtf_alignment = mtf_result.alignment.value
                intel.mtf_alignment_score = mtf_result.alignment_score
                intel.trend_bias = mtf_result.trend_bias.value if hasattr(mtf_result.trend_bias, 'value') else str(mtf_result.trend_bias)
        except Exception as exc:
            logger.warning("MTF analysis failed for %s: %s", ticker, exc)

        # 4. Liquidity
        liquidity = None
        try:
            if bars and len(bars) >= 30:
                liquidity = self.liquidity_engine.analyze(ticker, bars)
                if liquidity:
                    intel.breakout_type = liquidity.breakout_type.value
        except Exception as exc:
            logger.warning("Liquidity analysis failed for %s: %s", ticker, exc)

        # 5. Probability
        probability = None
        try:
            probability = self.probability_engine.compute(
                ticker=ticker,
                news_summary=news_summary,
                market_context=market_ctx,
                mtf_result=mtf_result,
                liquidity=liquidity,
                ict_features=ict_features,
                dip_result=dip_result,
                bounce_result=bounce_result,
                bearish_data=bearish_data,
                stock=stock,
                vol_profile=vol_profile,
            )
            if probability:
                intel.bullish_probability = probability.bullish_probability
                intel.bearish_probability = probability.bearish_probability
        except Exception as exc:
            logger.warning("Probability computation failed for %s: %s", ticker, exc)

        # 6. Price Targets
        target = None
        try:
            if bars:
                target = self.target_engine.predict(
                    ticker, bars, vol_profile, ict_features, liquidity, probability,
                )
                if target:
                    intel.target_price_1 = target.target_price_1
                    intel.target_price_2 = target.target_price_2
                    intel.stop_loss = target.stop_loss
                    intel.predicted_move_pct = target.predicted_move_pct
                    intel.prediction_confidence = target.confidence
                    intel.reward_risk_ratio = target.reward_risk_ratio
        except Exception as exc:
            logger.warning("Target prediction failed for %s: %s", ticker, exc)

        # 7. Entry Analysis
        entry_analysis = None
        try:
            if bars:
                entry_analysis = self.entry_engine.analyze(
                    ticker, bars, target, ict_features, liquidity, probability, vol_profile,
                )
                if entry_analysis:
                    intel.entry_quality = entry_analysis.entry.entry_quality.value
                    intel.entry_timing = entry_analysis.timing.timing_label.value
                    intel.reversal_stage = entry_analysis.reversal.reversal_stage.value
                    intel.trade_decision = entry_analysis.trade_decision.value
                    intel.decision_reasons = entry_analysis.decision_reasons
        except Exception as exc:
            logger.warning("Entry analysis failed for %s: %s", ticker, exc)

        # 8. Playbook
        try:
            setup = self.playbook_engine.analyze(
                ticker, probability, news_summary, liquidity,
                entry_analysis, target, dip_result, bounce_result,
                ict_features, mtf_result,
            )
            if setup:
                intel.setup_type = setup.setup_type.value
                intel.playbook = setup.playbook.value
                intel.playbook_match_score = setup.playbook_match_score
                if setup.playbook_rules:
                    intel.playbook_entry_rules = setup.playbook_rules.entry_rules
                    intel.playbook_stop_rules = setup.playbook_rules.stop_rules
                    intel.playbook_target_rules = setup.playbook_rules.target_rules
        except Exception as exc:
            logger.warning("Playbook analysis failed for %s: %s", ticker, exc)

        # 9. Auto-Watchlist Recommendation (Part 7)
        watchlist_rec = self._compute_watchlist_recommendation(intel, news_summary, probability, entry_analysis)
        intel.watchlist_priority = watchlist_rec.priority
        intel.watchlist_reason = watchlist_rec.reason_for_addition or watchlist_rec.reject_reason

        logger.info(
            "Intelligence [%s]: bull=%.0f%% bear=%.0f%% setup=%s playbook=%s decision=%s watchlist=%s",
            ticker, intel.bullish_probability, intel.bearish_probability,
            intel.setup_type, intel.playbook, intel.trade_decision, intel.watchlist_priority,
        )

        return intel

    def analyze_batch(
        self, tickers: List[str], **kwargs
    ) -> Dict[str, MarketIntelligence]:
        """Analyze multiple tickers."""
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.analyze_ticker(ticker, **kwargs)
            except Exception as exc:
                logger.error("Intelligence failed for %s: %s", ticker, exc)
                results[ticker] = MarketIntelligence(ticker=ticker)
        return results

    # ── Part 7: Auto-Watchlist Logic ──────────────────────────────────────

    def _compute_watchlist_recommendation(
        self, intel: MarketIntelligence, news, probability, entry,
    ) -> WatchlistRecommendation:
        """Determine if ticker should be added to watchlist."""
        rec = WatchlistRecommendation(ticker=intel.ticker)
        reasons = []

        # Reject conditions
        if intel.freshness_label in ("STALE", "DEAD"):
            rec.priority = AutoWatchlistPriority.REJECT
            rec.reject_reason = "Stale or dead news"
            return rec

        if intel.reaction_state in ("FADING", "EXHAUSTED"):
            rec.priority = AutoWatchlistPriority.REJECT
            rec.reject_reason = f"Reaction is {intel.reaction_state}"
            return rec

        if intel.entry_timing == "TOO_LATE":
            rec.priority = AutoWatchlistPriority.REJECT
            rec.reject_reason = "Entry too late — overextended"
            return rec

        if intel.reversal_stage in ("CONFIRMED", "STRONG"):
            rec.priority = AutoWatchlistPriority.REJECT
            rec.reject_reason = f"Reversal detected: {intel.reversal_stage}"
            return rec

        # HIGH priority
        if (intel.bullish_probability >= 70 and
            intel.freshness_label in ("BREAKING", "FRESH", "SAME_DAY") and
            intel.reaction_state in ("ACTIVE", "INITIAL") and
            intel.market_condition != "BEAR_MARKET"):
            reasons.append(f"Bull prob {intel.bullish_probability:.0f}%")
            reasons.append(f"Fresh catalyst: {intel.catalyst_summary[:50]}")
            reasons.append(f"Setup: {intel.setup_type}")
            rec.priority = AutoWatchlistPriority.HIGH
            rec.reason_for_addition = " | ".join(reasons)
            rec.catalyst_summary = intel.catalyst_summary
            return rec

        # MEDIUM priority
        if (55 <= intel.bullish_probability < 70 and
            intel.freshness_label not in ("STALE", "DEAD")):
            reasons.append(f"Bull prob {intel.bullish_probability:.0f}%")
            if intel.setup_type != "NO_SETUP":
                reasons.append(f"Setup: {intel.setup_type}")
            rec.priority = AutoWatchlistPriority.MEDIUM
            rec.reason_for_addition = " | ".join(reasons)
            return rec

        rec.priority = AutoWatchlistPriority.REJECT
        rec.reject_reason = f"Bull prob too low ({intel.bullish_probability:.0f}%)"
        return rec

    def _analyze_premarket(self, ticker: str, intel: MarketIntelligence, bars: List[OHLCVBar]):
        """Analyze premarket data using fast_info (avoids slow .info call)."""
        try:
            if not self.provider:
                return

            quote = self.provider.get_live_quote(ticker)

            intel.current_price = quote.get("price", 0.0)
            intel.previous_close = quote.get("previous_close", 0.0)
            intel.change_from_close = quote.get("change_pct", 0.0)

            pre = quote.get("premarket", {})
            intel.premarket_gap_pct = pre.get("gap_pct", 0.0)
            intel.premarket_volume = pre.get("volume", 0)
            intel.premarket_high = pre.get("high", 0.0)
            intel.premarket_low = pre.get("low", 0.0)

            gap = abs(intel.premarket_gap_pct)
            vol = intel.premarket_volume
            if gap > 5 and vol > 100000:
                intel.premarket_status = "STRONG"
            elif gap > 3:
                intel.premarket_status = "ACTIVE"
            elif gap > 1:
                intel.premarket_status = "WEAK"
            else:
                intel.premarket_status = "NONE"

            logger.info(
                "Premarket [%s]: gap=%.2f%%, vol=%d, status=%s, price=%.2f",
                ticker, intel.premarket_gap_pct, intel.premarket_volume,
                intel.premarket_status, intel.current_price,
            )

        except Exception as exc:
            logger.warning("Failed to fetch premarket data for %s: %s", ticker, exc)

    def close(self):
        """Cleanup."""
        try:
            self.news_engine.close()
        except Exception:
            pass
