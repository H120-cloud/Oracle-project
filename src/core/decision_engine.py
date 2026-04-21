"""
Decision Engine — V2

Aggregates dip detection, bounce detection, classification, no-trade
filter, and risk scoring into a final TradingSignal with action, entry,
stop, targets, risk_score, setup_grade, and confidence.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.models.schemas import (
    TradingSignal,
    SignalAction,
    StockClassification,
    DipResult,
    BounceResult,
    ScannedStock,
    ICTFeatures,
    VolumeProfileData,
    PositionSizingConfig,
    LiquidityProfile,
    MarketTrendRegime,
    OHLCVBar,
)
from src.core.no_trade_filter import NoTradeFilter, FilterResult
from src.core.risk_scorer import RiskScorer, RiskAssessment
from src.core.ict_detector import ICTDetector
from src.core.position_sizer import PositionSizer
from src.core.liquidity_aware_sizer import LiquidityAwarePositionSizer
from src.core.market_trend_regime_detector import MarketTrendRegimeDetector, RegimeFilterResult
from src.core.higher_timeframe_bias import (
    HigherTimeframeBiasDetector,
    HTFAlignmentEvaluator,
    HTFBiasResult,
    HTFAlignmentResult,
    HTFBias,
)

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Produces final trading signals from analysis components."""

    def __init__(
        self,
        signal_expiry_minutes: int = 30,
        position_sizing_config: Optional[PositionSizingConfig] = None,
        account_equity: float = 100000.0,  # Default $100k account
        use_liquidity_aware_sizing: bool = True,  # V6: Enable liquidity-aware sizing
    ):
        self.signal_expiry_minutes = signal_expiry_minutes
        self.no_trade_filter = NoTradeFilter()
        self.risk_scorer = RiskScorer()
        self.account_equity = account_equity
        self.use_liquidity_aware_sizing = use_liquidity_aware_sizing
        self.bounce_threshold_override: Optional[int] = None  # Set to override volatility-based threshold
        self.disable_regime_filter: bool = False  # Set True for backtesting across regimes

        # V6: Use LiquidityAwarePositionSizer if enabled
        if use_liquidity_aware_sizing:
            self.position_sizer = LiquidityAwarePositionSizer(position_sizing_config)
        else:
            self.position_sizer = PositionSizer(position_sizing_config)
        
        # V6: Market Regime Detector for trend filtering
        self.regime_detector = MarketTrendRegimeDetector()
        
        # V8: Higher Timeframe Bias Detector for multi-timeframe confirmation
        self.htf_detector = HigherTimeframeBiasDetector()
        self.htf_evaluator = HTFAlignmentEvaluator()

    def decide(
        self,
        stock: ScannedStock,
        classification: StockClassification,
        dip: Optional[DipResult],
        bounce: Optional[BounceResult],
        ict: Optional[ICTFeatures] = None,
        vol_profile: Optional[VolumeProfileData] = None,
        liquidity: Optional[LiquidityProfile] = None,
        bars: Optional[list[OHLCVBar]] = None,
        daily_bars: Optional[list[OHLCVBar]] = None,  # V8: Daily bars for HTF analysis
    ) -> TradingSignal:

        # Run no-trade filter first
        filter_result: FilterResult = self.no_trade_filter.evaluate(
            stock=stock,
            classification=classification,
            dip=dip,
            bounce=bounce,
        )

        now = datetime.utcnow()
        reasons: list[str] = []

        # ── V6: MARKET REGIME DETECTION ────────────────────────────────────
        regime_result: Optional[RegimeFilterResult] = None
        regime_blocked = False
        regime_downgrade_applied = False
        
        if bars and len(bars) >= 50:
            regime_result = self.regime_detector.detect(bars)
            
            # Apply regime filtering rules
            if regime_result.regime == MarketTrendRegime.BEARISH and not self.disable_regime_filter:
                # Block BUY signals in bearish regime
                regime_blocked = True
                reasons.append(f"BEARISH regime detected (score: {regime_result.confidence_score:.0f}) - blocking BUY")
                reasons.append(f"Reason: {regime_result.reason}")
            elif regime_result.regime == MarketTrendRegime.CHOPPY:
                # Downgrade confidence in choppy markets
                regime_downgrade_applied = True
                reasons.append(f"CHOPPY regime detected (score: {regime_result.confidence_score:.0f}) - confidence downgraded 20%")

        # Compute risk assessment for all signals
        risk: RiskAssessment = self.risk_scorer.assess(
            stock=stock, classification=classification, dip=dip, bounce=bounce,
        )

        # ── V4: VOLATILITY-ADAPTIVE ENTRY CRITERIA ─────────────────────────
        # Adjust requirements based on volatility class
        adjusted_bounce_threshold = self.bounce_threshold_override or self._get_volatility_adjusted_threshold(ict)

        # BUY requires: valid dip + bounce + ICT alignment + structure break + NOT trap
        can_enter_buy = self._evaluate_entry_criteria_v4(
            classification, dip, bounce, ict, reasons, adjusted_bounce_threshold
        )

        # ── V6: APPLY REGIME CONFIDENCE ADJUSTMENT ───────────────────────
        final_confidence = risk.confidence
        if regime_downgrade_applied:
            final_confidence = int(final_confidence * 0.80)  # Downgrade 20%
        
        # ── NO VALID SETUP ───────────────────────────────────────────────
        # V6: Add regime_blocked to the criteria
        if not filter_result.passed or not can_enter_buy or regime_blocked:
            # Add specific rejection reasons
            if regime_blocked:
                reasons.append("BEARISH regime - blocking BUY signal")
            if not can_enter_buy and ict:
                if ict.trap_detected:
                    reasons.append(f"TRAP: {ict.trap_reason}")
                if not ict.structure_break_confirmed:
                    reasons.append("No structure break confirmation (MSB)")
                if not ict.liquidity_sweep and not ict.structure_reclaimed:
                    reasons.append("No ICT alignment (sweep or reclaim)")
                if ict.is_overextended:
                    reasons.append(f"Overextended {ict.extension_pct:.1f}%")

            # Calculate entry/stop/target even for NO_VALID_SETUP so UI can display them
            entry = stock.price
            stop = entry * 0.95 if dip and dip.is_valid_dip else entry * 0.97
            targets = [entry * 1.05, entry * 1.10, entry * 1.15] if bounce and bounce.is_valid_bounce else [entry * 1.03, entry * 1.06, entry * 1.09]
            
            return TradingSignal(
                ticker=stock.ticker,
                action=SignalAction.NO_VALID_SETUP,
                classification=classification,
                dip_probability=dip.probability if dip else None,
                bounce_probability=bounce.probability if bounce else None,
                entry_price=entry,
                stop_price=stop,
                target_prices=targets,
                risk_score=risk.risk_score,
                setup_grade=risk.setup_grade,
                confidence=final_confidence,
                reason=filter_result.reasons + risk.risk_factors + reasons,
                created_at=now,
                # V6: Include regime info even in rejected signals
                market_regime=regime_result.regime.value if regime_result else None,
                regime_confidence_score=regime_result.confidence_score if regime_result else None,
                regime_reason=regime_result.reason if regime_result else None,
                regime_blocked=regime_blocked,
                regime_downgrade_applied=regime_downgrade_applied,
            )

        # ── V8: HIGHER TIMEFRAME BIAS DETECTION ───────────────────────────
        # Must detect HTF bias before deciding if we can take the trade
        htf_result: Optional[HTFBiasResult] = None
        alignment_result: Optional[HTFAlignmentResult] = None
        
        if daily_bars and len(daily_bars) >= 50:
            htf_result = self.htf_detector.detect_bias(stock.ticker, daily_bars)
            if htf_result:
                reasons.append(f"HTF {htf_result.bias.value} (score: {htf_result.strength_score:.0f})")
                reasons.extend(htf_result.reasoning[:2])  # Add first 2 reasoning items
                
                # Evaluate alignment with LTF signal
                early_warning = getattr(ict, 'early_bearish_warning', False) if ict else False
                alignment_result = self.htf_evaluator.evaluate_alignment(
                    ticker=stock.ticker,
                    htf_result=htf_result,
                    ltf_can_buy=can_enter_buy and bounce is not None,
                    ict=ict,
                    early_bearish_warning=early_warning
                )
                reasons.append(f"HTF Alignment: {alignment_result.alignment_status.value}")
        
        # ── BUY ──────────────────────────────────────────────────────────
        # V6: Strict criteria passed - generate confirmed entry with liquidity-aware sizing
        # V8: Also requires HTF alignment check to pass
        if can_enter_buy and bounce is not None:
            # V8: Check HTF alignment - block if not allowed
            if alignment_result and not alignment_result.allowed:
                reasons.append(f"HTF FILTER BLOCKED: {alignment_result.reason}")
                return TradingSignal(
                    ticker=stock.ticker,
                    action=SignalAction.WATCH,
                    classification=classification,
                    dip_probability=dip.probability if dip else None,
                    bounce_probability=bounce.probability,
                    entry_price=stock.price,
                    stop_price=stock.price * 0.95,
                    target_prices=[stock.price * 1.05, stock.price * 1.10, stock.price * 1.15],
                    risk_score=risk.risk_score,
                    setup_grade=risk.setup_grade,
                    confidence=risk.confidence,
                    signal_expiry=now + timedelta(minutes=self.signal_expiry_minutes),
                    reason=reasons + risk.risk_factors,
                    created_at=now,
                    htf_bias=htf_result.bias.value if htf_result else None,
                    htf_strength_score=htf_result.strength_score if htf_result else None,
                    alignment_status=alignment_result.alignment_status.value if alignment_result else None,
                    trade_type=alignment_result.trade_type.value if alignment_result else None,
                    htf_blocked=True,
                    htf_alignment_reason=alignment_result.reason if alignment_result else None,
                    alignment_confidence_adj=alignment_result.confidence_adjustment if alignment_result else None,
                )
            
            entry = self._calc_entry(stock.price, ict)
            stop = self._calc_stop_v4(entry, dip, ict)
            targets = self._calc_targets_v3(entry, stop, ict, vol_profile)

            # V6: Calculate position sizing with liquidity awareness
            liq_score = 100.0  # Default high score
            execution_quality_ok = True

            if self.use_liquidity_aware_sizing and liquidity:
                # Use LiquidityAwarePositionSizer
                position_result, liq_score, execution_quality_ok = (
                    self.position_sizer.calculate_position_with_liquidity(
                        entry=entry,
                        stop=stop,
                        targets=targets,
                        account_equity=self.account_equity,
                        liquidity=liquidity,
                        ict=ict,
                        stock_type=stock.stock_type if hasattr(stock, 'stock_type') else None,
                        market_regime=regime_result.regime.value if regime_result else None,
                        regime_confidence_score=regime_result.confidence_score if regime_result else None,
                        regime_reason=regime_result.reason if regime_result else None,
                        regime_blocked=regime_blocked,
                        regime_downgrade_applied=regime_downgrade_applied,
                        created_at=now,
                    )
                )
            else:
                # Fallback to standard sizing
                position_result = self.position_sizer.calculate_position(
                    entry=entry,
                    stop=stop,
                    targets=targets,
                    account_equity=self.account_equity,
                    ict=ict,
                    stock_type=stock.stock_type if hasattr(stock, 'stock_type') else None,
                )

            # V6: Check execution quality (spread, liquidity score)
            if not execution_quality_ok:
                reasons.append(f"Execution quality poor: Liquidity score {liq_score:.0f}/100")
                return TradingSignal(
                    ticker=stock.ticker,
                    action=SignalAction.WATCH,
                    classification=classification,
                    dip_probability=dip.probability if dip else None,
                    bounce_probability=bounce.probability,
                    entry_price=entry,
                    stop_price=stop,
                    target_prices=targets,
                    risk_score=risk.risk_score,
                    setup_grade=risk.setup_grade,
                    confidence=risk.confidence,
                    execution_quality_acceptable=False,
                    rejection_reason=f"Poor liquidity: score {liq_score:.0f}",
                    signal_expiry=now + timedelta(minutes=self.signal_expiry_minutes),
                    reason=reasons + risk.risk_factors,
                    created_at=now,
                )

            # V5/V6: Check if position sizing accepted the trade
            if not position_result.accepted:
                # Revert to WATCH if sizing rejected (setup valid but can't size properly)
                reasons.append(f"Position sizing rejected: {position_result.rejection_reason}")
                return TradingSignal(
                    ticker=stock.ticker,
                    action=SignalAction.WATCH,
                    classification=classification,
                    dip_probability=dip.probability if dip else None,
                    bounce_probability=bounce.probability,
                    entry_price=entry,
                    stop_price=stop,
                    target_prices=targets,
                    risk_score=risk.risk_score,
                    setup_grade=risk.setup_grade,
                    confidence=risk.confidence,
                    position_sizing_rejected=True,
                    rejection_reason=position_result.rejection_reason,
                    signal_expiry=now + timedelta(minutes=self.signal_expiry_minutes),
                    reason=reasons + risk.risk_factors,
                    created_at=now,
                )

            # V4: Enhanced reasons with ICT and volatility context
            reasons.append(f"Bounce probability {bounce.probability:.0f}%")
            if dip:
                reasons.append(f"Dip phase: {dip.phase.value}")
            if ict:
                reasons.append(f"ICT score: {ict.ict_score}/100")
                reasons.append(f"Volatility: {ict.volatility_class} (ATR: {ict.atr_pct:.1f}%)")
                if ict.structure_break_confirmed:
                    reasons.append(f"MSB confirmed: broke {ict.micro_high_level:.2f}")
                if ict.liquidity_sweep:
                    reasons.append(f"Sweep+reclaim at {ict.sweep_level:.2f}")
                if ict.near_order_block:
                    reasons.append(f"Near OB ({ict.distance_to_order_block_pct:.1f}%, fresh: {ict.order_block_freshness:.1f})")
                if ict.atr_value > 0:
                    reasons.append(f"ATR stop: {ict.atr_value:.2f} × {ict.atr_stop_multiplier:.1f} = {(ict.atr_value * ict.atr_stop_multiplier):.2f}")

            # V5: Add position sizing info to reasons
            reasons.append(f"Position: {position_result.shares} shares, Risk: ${position_result.total_dollar_risk:.2f}")
            reasons.append(f"R-multiples: T1={position_result.r_multiples[0] if position_result.r_multiples else 'N/A'}R")
            if position_result.vol_cap_applied:
                reasons.append("Volatility cap applied")
            if position_result.stock_type_cap_applied:
                reasons.append("Stock type cap applied")

            # V6: Add liquidity execution info
            if hasattr(position_result, 'liquidity_score') and position_result.liquidity_score > 0:
                reasons.append(f"Liquidity score: {position_result.liquidity_score:.0f}/100")
                reasons.append(f"Spread: {position_result.spread_pct:.2f}%")
                reasons.append(f"Slippage est: {position_result.slippage_pct:.2f}%")
                reasons.append(f"Order/ADV: {position_result.order_pct_of_adv:.1f}%")
                if position_result.liquidity_cap_applied:
                    reasons.append("Liquidity cap applied")

            # V4: Adjust confidence based on ICT score (with volatility consideration)
            # V6: Also apply spread-based confidence penalty
            adjusted_confidence = self._adjust_confidence_v4(risk.confidence, ict)
            if hasattr(position_result, 'spread_pct'):
                adjusted_confidence = self._apply_spread_penalty(
                    adjusted_confidence, position_result.spread_pct, entry
                )
            
            # V8: Apply HTF alignment confidence adjustment (if HTF data available)
            if alignment_result and alignment_result.allowed:
                adjusted_confidence = max(0, min(100, adjusted_confidence + alignment_result.confidence_adjustment))
                if alignment_result.confidence_adjustment != 0:
                    reasons.append(f"HTF alignment adj: {alignment_result.confidence_adjustment:+.0f}%")

            # V10: Apply confidence calibration (maps raw score to actual win rate)
            try:
                from src.core.confidence_calibrator import ConfidenceCalibrator
                calibrator = ConfidenceCalibrator()
                htf_bias_val = htf_result.bias.value if htf_result else None
                raw_conf = adjusted_confidence
                adjusted_confidence = calibrator.adjust(
                    raw_confidence=adjusted_confidence,
                    grade=risk.setup_grade,
                    htf_bias=htf_bias_val,
                )
                if calibrator.profile.is_calibrated and abs(adjusted_confidence - raw_conf) > 1:
                    reasons.append(f"Calibrated confidence: {raw_conf:.0f}% → {adjusted_confidence:.0f}%")
            except Exception:
                pass  # Calibration is best-effort

            # V7: Extract enhanced fields for output
            momentum_state = "neutral"
            structure_status = "unknown"
            breakout_quality = "none"
            target_type = "fixed_r"
            early_warning = False
            early_confidence = None
            is_falling_knife = False
            follow_through = False
            dip_quality = None

            if dip and dip.features:
                momentum_state = dip.features.momentum_state
                structure_status = "intact" if dip.features.structure_intact else "broken"
                is_falling_knife = dip.features.is_falling_knife
                dip_quality = round(dip.features.price_velocity + dip.features.price_acceleration + 50, 1)

            if bounce and bounce.features:
                if momentum_state == "neutral":
                    momentum_state = bounce.features.momentum_state

            if ict:
                breakout_quality = ict.breakout_quality
                follow_through = ict.follow_through_confirmed
                target_type = getattr(ict, 'target_type', 'fixed_r')

            return TradingSignal(
                ticker=stock.ticker,
                action=SignalAction.BUY,
                classification=classification,
                dip_probability=dip.probability if dip else None,
                bounce_probability=bounce.probability,
                entry_price=entry,
                stop_price=stop,
                target_prices=targets,
                # V5: Position sizing fields
                account_equity=self.account_equity,
                max_risk_per_trade_pct=self.position_sizer.config.max_risk_per_trade_pct,
                position_size_shares=position_result.shares,
                dollar_risk_per_share=position_result.dollar_risk_per_share,
                total_dollar_risk=position_result.total_dollar_risk,
                total_capital_used=position_result.total_capital_used,
                r_multiples=position_result.r_multiples,
                expected_reward_t1=position_result.expected_rewards[0] if position_result.expected_rewards else None,
                expected_reward_t2=position_result.expected_rewards[1] if len(position_result.expected_rewards) > 1 else None,
                expected_reward_t3=position_result.expected_rewards[2] if len(position_result.expected_rewards) > 2 else None,
                position_sizing_rejected=False,
                # V6: Liquidity execution fields
                bid_ask_spread_pct=getattr(position_result, 'spread_pct', None),
                estimated_slippage_pct=getattr(position_result, 'slippage_pct', None),
                liquidity_score=getattr(position_result, 'liquidity_score', None),
                order_size_pct_of_adv=getattr(position_result, 'order_pct_of_adv', None),
                order_size_pct_of_intraday=getattr(position_result, 'order_pct_of_intraday', None),
                tick_size=liquidity.tick_size if liquidity else None,
                execution_quality_acceptable=True,
                slippage_adjusted_stop=getattr(position_result, 'slippage_adjusted_stop', None),
                slippage_adjusted_targets=getattr(position_result, 'slippage_adjusted_targets', None),
                # Standard fields
                risk_score=risk.risk_score,
                setup_grade=risk.setup_grade,
                confidence=adjusted_confidence,
                signal_expiry=now + timedelta(minutes=self.signal_expiry_minutes),
                reason=reasons + risk.risk_factors,
                created_at=now,
                # V7: Momentum & Structure Intelligence
                momentum_state=momentum_state,
                structure_status=structure_status,
                breakout_quality=breakout_quality,
                target_type=target_type,
                early_bearish_warning=early_warning,
                early_bearish_confidence=early_confidence,
                dip_quality_score=dip_quality,
                is_falling_knife=is_falling_knife,
                follow_through_confirmed=follow_through,
                # V8: Higher Timeframe Confirmation
                htf_bias=htf_result.bias.value if htf_result else None,
                htf_strength_score=htf_result.strength_score if htf_result else None,
                htf_structure_score=htf_result.structure_score if htf_result else None,
                htf_ema_score=htf_result.ema_alignment_score if htf_result else None,
                htf_momentum_score=htf_result.momentum_score if htf_result else None,
                htf_adx_score=htf_result.adx_score if htf_result else None,
                htf_rsi=htf_result.rsi if htf_result else None,
                htf_adx=htf_result.adx if htf_result else None,
                alignment_status=alignment_result.alignment_status.value if alignment_result else None,
                trade_type=alignment_result.trade_type.value if alignment_result else None,
                htf_blocked=False,
                htf_alignment_reason=alignment_result.reason if alignment_result else None,
                alignment_confidence_adj=alignment_result.confidence_adjustment if alignment_result else None,
            )

        # ── WATCH ────────────────────────────────────────────────────────
        if classification in (
            StockClassification.DIP_FORMING,
            StockClassification.BOUNCE_FORMING,
        ):
            reasons.append("Setup developing, not yet ready")
            if dip:
                reasons.append(f"Dip prob {dip.probability:.0f}% phase={dip.phase.value}")
            if bounce:
                reasons.append(f"Bounce prob {bounce.probability:.0f}%")

            # Calculate entry/stop/target for WATCH signals too
            entry = stock.price
            stop = entry * 0.95 if dip and dip.is_valid_dip else entry * 0.97
            targets = [entry * 1.05, entry * 1.10, entry * 1.15] if bounce and bounce.is_valid_bounce else [entry * 1.03, entry * 1.06, entry * 1.09]
            
            return TradingSignal(
                ticker=stock.ticker,
                action=SignalAction.WATCH,
                classification=classification,
                dip_probability=dip.probability if dip else None,
                bounce_probability=bounce.probability if bounce else None,
                entry_price=entry,
                stop_price=stop,
                target_prices=targets,
                risk_score=risk.risk_score,
                setup_grade=risk.setup_grade,
                confidence=risk.confidence,
                signal_expiry=now + timedelta(minutes=self.signal_expiry_minutes),
                reason=reasons + risk.risk_factors,
                created_at=now,
            )

        # ── AVOID ────────────────────────────────────────────────────────
        reasons.append(f"Classification: {classification.value}")
        
        # Calculate entry/stop/target for AVOID signals too
        entry = stock.price
        stop = entry * 0.95 if dip and dip.support_level else entry * 0.97
        targets = [entry * 1.05, entry * 1.10, entry * 1.15] if bounce and bounce.resistance_level else [entry * 1.03, entry * 1.06, entry * 1.09]
        
        return TradingSignal(
            ticker=stock.ticker,
            action=SignalAction.AVOID,
            classification=classification,
            dip_probability=dip.probability if dip else None,
            bounce_probability=bounce.probability if bounce else None,
            entry_price=entry,
            stop_price=stop,
            target_prices=targets,
            risk_score=risk.risk_score,
            setup_grade=risk.setup_grade,
            confidence=risk.confidence,
            reason=reasons + risk.risk_factors,
            created_at=now,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _evaluate_entry_criteria_v4(
        self,
        classification: StockClassification,
        dip: Optional[DipResult],
        bounce: Optional[BounceResult],
        ict: Optional[ICTFeatures],
        reasons: list[str],
        bounce_threshold: int = 50,
    ) -> bool:
        """
        V4/V7: Volatility-adaptive entry criteria evaluation with momentum and structure intelligence.

        BUY requires ALL:
        1. Valid classification (DIP_BOUNCE_FORMING, BOUNCE_FORMING)
        2. Bounce ready with adaptive probability threshold
        3. ICT alignment: liquidity sweep OR structure reclaim
        4. Structure break confirmed (MSB)
        5. NOT overextended
        6. NOT in a trap zone
        7. Confidence not capped by trap (ict_score > 40 if trap)
        V7 ADDITIONS:
        8. Structure intact or reclaimed (no falling knife)
        9. Follow-through confirmation (not fake breakout)
        10. Momentum state favorable (not accelerating down)
        """
        # 1. Classification check
        valid_classification = classification in (
            StockClassification.DIP_BOUNCE_FORMING,
            StockClassification.BOUNCE_FORMING,
            StockClassification.DIP_FORMING,
        )
        if not valid_classification:
            reasons.append(f"Classification {classification.value} not entry-ready")
            return False

        # 2. Bounce check (with volatility-adjusted threshold)
        # For dip classifications, bounce doesn't need to be fully entry_ready
        if classification in (StockClassification.DIP_FORMING, StockClassification.DIP_BOUNCE_FORMING):
            if bounce is None or bounce.probability < bounce_threshold:
                reasons.append(f"Bounce probability {bounce.probability if bounce else 0:.0f}% < {bounce_threshold}%")
                return False
        else:
            if bounce is None or not bounce.entry_ready or bounce.probability < bounce_threshold:
                reasons.append(f"Bounce not ready or probability < {bounce_threshold}%")
                return False

        # V7: Momentum state check on bounce
        if bounce and bounce.features:
            if bounce.features.momentum_state == "accelerating_up":
                reasons.append("Momentum accelerating up (favorable)")
            elif bounce.features.momentum_state == "slowing_down":
                reasons.append("Selling slowing (favorable)")
            # Neutral or bullish is fine

        # 3-7. ICT validation (if available)
        if ict is not None:
            # 3. ICT alignment: sweep OR reclaim
            ict_aligned = ict.liquidity_sweep or ict.structure_reclaimed
            if not ict_aligned:
                reasons.append("No ICT alignment (no sweep or reclaim)")
                return False

            # 4. Structure break confirmed
            if not ict.structure_break_confirmed:
                reasons.append("No micro structure break (MSB)")
                return False

            # V7: Follow-through confirmation - reject fake breakouts
            if ict.breakout_quality == "fake":
                reasons.append("FAKE BREAKOUT: No follow-through confirmation")
                return False
            elif ict.breakout_quality == "weak":
                reasons.append("Weak breakout - reduced confidence")
                # Don't block, but note the quality reduction
            elif ict.breakout_quality == "confirmed":
                reasons.append("Confirmed breakout with follow-through")

            # 5. Not overextended
            if ict.is_overextended:
                reasons.append(f"Overextended {ict.extension_pct:.1f}%")
                return False

            # 6. Not a trap
            if ict.trap_detected:
                reasons.append(f"Trap: {ict.trap_reason}")
                return False

            # 7. Order block freshness check (reduce quality if stale)
            if ict.near_order_block and ict.order_block_freshness < 0.5:
                reasons.append(f"Stale OB (freshness: {ict.order_block_freshness:.1f})")
                # Don't block, but note the quality reduction

        # V7: Structure validation on dip - HARD FILTER
        if dip and dip.features:
            # V7: Falling knife rejection
            if dip.features.is_falling_knife:
                reasons.append("FALLING KNIFE: Strong negative velocity+acceleration")
                return False

            # V7: Structure must be intact or reclaimed
            if not dip.features.structure_intact:
                reasons.append("Structure broken: No higher low or reclaim")
                return False
            else:
                reasons.append("Structure intact (higher low or reclaim)")

            # V7: Momentum state check on dip
            if dip.features.momentum_state == "accelerating_down":
                reasons.append("Dip momentum accelerating down - danger")
                return False
            elif dip.features.momentum_state == "slowing_down":
                reasons.append("Dip selling slowing (favorable)")

        # Without ICT data, use threshold (was hardcoded at 65%)
        if ict is None:
            fallback = bounce_threshold if bounce_threshold < 65 else 65
            if bounce.probability < fallback:
                reasons.append(f"No ICT data, require bounce > {fallback}%")
                return False

        return True

    @staticmethod
    def _get_volatility_adjusted_threshold(ict: Optional[ICTFeatures]) -> int:
        """
        V4: Adjust bounce probability threshold based on volatility.

        HIGH volatility: Require stronger confirmation (higher threshold)
        LOW volatility: Can use normal threshold
        """
        if ict is None:
            return 50  # Default threshold

        # High volatility stocks need stronger confirmation
        if ict.volatility_class == "high":
            return 60  # Require 60% bounce probability in high vol
        elif ict.volatility_class == "low":
            return 45  # Can accept 45% in low vol (more predictable)
        else:
            return 50  # Medium volatility, standard threshold

    @staticmethod
    def _calc_entry(current_price: float, ict: Optional[ICTFeatures]) -> float:
        """V3: Calculate entry price, preferring order block if near."""
        if ict and ict.order_block_price > 0 and ict.near_order_block:
            # Prefer entry at or near order block for better R:R
            entry = min(current_price, ict.order_block_price * 1.005)
            return round(entry, 2)
        return round(current_price, 2)

    @staticmethod
    def _calc_stop_v4(entry: float, dip: Optional[DipResult], ict: Optional[ICTFeatures]) -> float:
        """
        V4: ATR-based dynamic stop calculation.

        Logic:
        1. Calculate micro low based stop (base_stop)
        2. Calculate ATR-based stop (atr_stop)
        3. Use the WIDER of the two (prevents premature stop-outs)
        """
        base_stop = 0.0
        atr_stop = 0.0

        # 1. Micro low based stop (if ICT data available)
        if ict and ict.micro_low_level > 0:
            base_stop = ict.micro_low_level * 0.995  # 0.5% buffer below micro low
        else:
            # Fallback: percentage-based stop
            if dip and dip.probability > 60:
                base_stop = entry * 0.975  # 2.5% below entry
            else:
                base_stop = entry * 0.985  # 1.5% below entry

        # 2. ATR-based stop (if ICT data with ATR available)
        if ict and ict.atr_value > 0 and ict.atr_stop_multiplier > 0:
            # ATR stop = entry - (ATR × volatility multiplier)
            atr_distance = ict.atr_value * ict.atr_stop_multiplier
            atr_stop = entry - atr_distance

            # Ensure ATR stop doesn't exceed reasonable bounds (max 5% risk)
            max_stop = entry * 0.95
            atr_stop = max(atr_stop, max_stop)
        else:
            # No ATR data: use base stop only
            atr_stop = base_stop * 0.95  # Make it wider than base

        # 3. Use the WIDER stop (lower price) for protection
        # In uptrend: wider stop = lower number
        final_stop = min(base_stop, atr_stop)

        # Sanity checks
        if final_stop <= 0 or final_stop >= entry:
            # Invalid stop, use conservative fallback
            final_stop = entry * 0.97

        return round(final_stop, 2)

    def _calc_targets_v3(
        self,
        entry: float,
        stop: float,
        ict: Optional[ICTFeatures],
        vol_profile: Optional[VolumeProfileData],
    ) -> list[float]:
        """
        V3: Target calculation based on structure, not just R:R.

        Priority:
        1. Recent swing high (resistance)
        2. Volume Profile VAH (supply zone)
        3. Order block level above
        4. R:R fallback
        """
        targets = []

        # Risk amount
        risk = entry - stop
        if risk <= 0:
            risk = entry * 0.02  # Default 2% risk

        # Target 1: Nearest resistance (swing high)
        if ict and ict.recent_swing_high > entry:
            targets.append(round(ict.recent_swing_high, 2))
        elif ict and ict.micro_high_level > entry:
            targets.append(round(ict.micro_high_level, 2))
        else:
            # Fallback to 1.5R
            targets.append(round(entry + risk * 1.5, 2))

        # Target 2: Volume Profile VAH (if available and above T1)
        if vol_profile and vol_profile.value_area_high > targets[0]:
            targets.append(round(vol_profile.value_area_high, 2))
        elif ict and ict.recent_swing_high > 0:
            # Extend to next logical level
            extended = ict.recent_swing_high * 1.02
            targets.append(round(extended, 2))
        else:
            # Fallback to 2.5R
            targets.append(round(entry + risk * 2.5, 2))

        # Target 3: Extended target (3R or next major level)
        if len(targets) >= 2:
            # Gap from T2
            gap = targets[1] - targets[0]
            targets.append(round(targets[1] + gap, 2))
        else:
            targets.append(round(entry + risk * 3, 2))

        # Ensure targets are sorted and above entry
        targets = sorted(set(t for t in targets if t > entry))

        # Always return at least 2 targets
        if len(targets) < 2:
            targets = [
                round(entry + risk * 1.5, 2),
                round(entry + risk * 2.5, 2),
                round(entry + risk * 3.5, 2),
            ]

        return targets[:3]  # Max 3 targets

    @staticmethod
    def _adjust_confidence_v4(base_confidence: int, ict: Optional[ICTFeatures]) -> int:
        """
        V4: Adjust confidence based on ICT score with volatility awareness.

        High volatility: Reduce confidence slightly (more uncertainty)
        Low volatility: Use normal calculation
        """
        if ict is None:
            return base_confidence

        # Base ICT score weight: 40% ICT, 60% base
        adjusted = int(ict.ict_score * 0.4 + base_confidence * 0.6)

        # V4: Volatility adjustment
        if ict.volatility_class == "high":
            # Reduce confidence by 10% in high volatility (more uncertainty)
            adjusted = int(adjusted * 0.90)
        elif ict.volatility_class == "low":
            # Slight boost for low volatility (more predictable)
            adjusted = int(adjusted * 1.05)

        # V4: Order block freshness adjustment
        if ict.near_order_block and ict.order_block_freshness < 0.5:
            # Reduce confidence if trading near stale order block
            adjusted = int(adjusted * 0.95)

        # Clamp to 0-100
        return max(0, min(100, adjusted))

    @staticmethod
    def _apply_spread_penalty(confidence: int, spread_pct: float, price: float) -> int:
        """
        V6: Apply confidence penalty based on bid-ask spread.

        Wider spreads = higher execution risk = lower confidence.
        """
        # Determine tier-based penalty thresholds
        if price < 1.0:
            # Penny stocks: 3% max, penalties at 1.5%, 2.1%
            if spread_pct > 2.5:
                penalty = 0.25  # 25% penalty
            elif spread_pct > 1.8:
                penalty = 0.15  # 15% penalty
            elif spread_pct > 1.0:
                penalty = 0.08  # 8% penalty
            else:
                penalty = 0
        elif price < 5.0:
            # Micro caps: 2% max, penalties at 1.0%, 1.4%
            if spread_pct > 1.6:
                penalty = 0.25
            elif spread_pct > 1.2:
                penalty = 0.15
            elif spread_pct > 0.7:
                penalty = 0.08
            else:
                penalty = 0
        elif price < 20.0:
            # Small caps: 1% max, penalties at 0.5%, 0.7%
            if spread_pct > 0.8:
                penalty = 0.25
            elif spread_pct > 0.6:
                penalty = 0.15
            elif spread_pct > 0.35:
                penalty = 0.08
            else:
                penalty = 0
        else:
            # Standard: 0.5% max, penalties at 0.25%, 0.35%
            if spread_pct > 0.4:
                penalty = 0.25
            elif spread_pct > 0.3:
                penalty = 0.15
            elif spread_pct > 0.18:
                penalty = 0.08
            else:
                penalty = 0

        adjusted = int(confidence * (1 - penalty))
        return max(0, min(100, adjusted))
