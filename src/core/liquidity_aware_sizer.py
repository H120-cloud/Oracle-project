"""
Liquidity-Aware Position Sizer — V6

Microstructure-aware position sizing for penny stocks and microcaps.
Extends PositionSizer with liquidity caps, spread filtering, slippage modeling.
"""

import logging
from typing import Optional, Tuple

from src.models.schemas import (
    ICTFeatures,
    PositionSizingConfig,
    PositionSizingResult,
    LiquidityProfile,
    LiquidityExecutionConfig,
)
from src.core.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class LiquidityAwarePositionSizer(PositionSizer):
    """
    Position sizer with full microstructure awareness.

    Adds to base PositionSizer:
    - Liquidity caps (order size vs ADV, intraday volume)
    - Spread-based filtering and confidence penalties
    - Slippage modeling by tier/volatility/spread
    - Tick-size awareness for stop precision
    - Liquidity quality scoring
    """

    def __init__(self, config: Optional[PositionSizingConfig] = None):
        super().__init__(config)
        self.liq_config = self.config.liquidity_config or LiquidityExecutionConfig()

    def calculate_position_with_liquidity(
        self,
        entry: float,
        stop: float,
        targets: list[float],
        account_equity: float,
        liquidity: LiquidityProfile,
        ict: Optional[ICTFeatures] = None,
        stock_type: Optional[str] = None,
    ) -> Tuple[PositionSizingResult, float, bool]:
        """
        Calculate position with full liquidity awareness.

        Returns:
            - PositionSizingResult (with liquidity caps applied)
            - Liquidity quality score (0-100)
            - Execution quality acceptable (bool)
        """
        # Step 1: Calculate liquidity quality score
        liq_score = self._calculate_liquidity_score(liquidity)

        # Step 2: Check spread acceptability
        spread_acceptable, spread_penalty = self._check_spread_acceptability(
            liquidity.spread_pct, entry
        )

        # Step 3: Calculate slippage estimate
        slippage_pct = self._estimate_slippage(liquidity, ict)

        # Step 4: Calculate base position (from parent class logic)
        result = self._calculate_base_position(
            entry, stop, targets, account_equity, ict, stock_type
        )

        # Step 5: Apply liquidity caps
        if result.accepted:
            result = self._apply_liquidity_caps(result, liquidity)

        # Step 6: Check minimum liquidity quality
        execution_acceptable = liq_score >= self.liq_config.min_liquidity_score

        if not spread_acceptable:
            execution_acceptable = False
            result.rejection_reason = (
                f"Spread too wide: {liquidity.spread_pct:.2f}% "
                f"(max for tier: {self._get_max_spread_for_tier(entry):.2f}%)"
            )
            result.accepted = False

        # Step 7: Adjust for tick-size on stops (sub-$1 stocks)
        tick_adjusted_stop = self._adjust_stop_for_tick_size(stop, liquidity.tick_size, entry)
        slippage_adjusted_stop = tick_adjusted_stop - (entry * slippage_pct / 100)

        # Step 8: Calculate slippage-adjusted targets
        slippage_adjusted_targets = [
            t - (entry * slippage_pct / 100) for t in targets
        ]

        # Add liquidity metadata to result
        result = self._enrich_result_with_liquidity_data(
            result, liquidity, liq_score, slippage_pct,
            slippage_adjusted_stop, slippage_adjusted_targets
        )

        return result, liq_score, execution_acceptable

    def _calculate_liquidity_score(self, liq: LiquidityProfile) -> float:
        """
        Calculate 0-100 liquidity quality score.

        Factors:
        - Volume score (40 pts): Based on ADV
        - Spread score (30 pts): Lower spread = higher score
        - Intraday volume score (20 pts): Today's activity
        - Consistency score (10 pts): 15min vs daily pacing
        """
        # Volume score (40 pts) - log scale for wide ranges
        if liq.average_daily_volume >= 1_000_000:
            vol_score = 40
        elif liq.average_daily_volume >= 500_000:
            vol_score = 35
        elif liq.average_daily_volume >= 100_000:
            vol_score = 30
        elif liq.average_daily_volume >= 50_000:
            vol_score = 20
        elif liq.average_daily_volume >= 10_000:
            vol_score = 10
        else:
            vol_score = 5

        # Spread score (30 pts) - inverse relationship
        if liq.spread_pct <= 0.1:
            spread_score = 30
        elif liq.spread_pct <= 0.3:
            spread_score = 25
        elif liq.spread_pct <= 0.5:
            spread_score = 20
        elif liq.spread_pct <= 1.0:
            spread_score = 15
        elif liq.spread_pct <= 2.0:
            spread_score = 10
        elif liq.spread_pct <= 3.0:
            spread_score = 5
        else:
            spread_score = 0

        # Intraday volume score (20 pts)
        if liq.today_volume >= liq.average_daily_volume * 0.5:
            intraday_score = 20
        elif liq.today_volume >= liq.average_daily_volume * 0.3:
            intraday_score = 15
        elif liq.today_volume >= liq.average_daily_volume * 0.1:
            intraday_score = 10
        else:
            intraday_score = 5

        # Consistency score (10 pts) - is volume paced normally?
        expected_15min_vol = liq.average_daily_volume / 26  # 6.5 hours / 15 min bars
        if liq.intraday_volume_15min >= expected_15min_vol * 0.5:
            consistency_score = 10
        elif liq.intraday_volume_15min >= expected_15min_vol * 0.3:
            consistency_score = 5
        else:
            consistency_score = 2

        total_score = vol_score + spread_score + intraday_score + consistency_score
        return min(100, total_score)

    def _check_spread_acceptability(
        self, spread_pct: float, price: float
    ) -> Tuple[bool, float]:
        """
        Check if spread is acceptable for the price tier.

        Returns: (acceptable, confidence_penalty)
        """
        max_spread = self._get_max_spread_for_tier(price)

        if spread_pct > max_spread:
            return False, 1.0  # Full penalty (reject)
        elif spread_pct > max_spread * 0.7:
            return True, 0.3   # 30% confidence penalty
        elif spread_pct > max_spread * 0.5:
            return True, 0.15  # 15% confidence penalty
        else:
            return True, 0.0    # No penalty

    def _get_max_spread_for_tier(self, price: float) -> float:
        """Get max acceptable spread for price tier."""
        if price < 1.0:
            return self.liq_config.penny_spread_max_pct
        elif price < 5.0:
            return self.liq_config.micro_spread_max_pct
        elif price < 20.0:
            return self.liq_config.small_spread_max_pct
        else:
            return self.liq_config.standard_spread_max_pct

    def _estimate_slippage(
        self, liq: LiquidityProfile, ict: Optional[ICTFeatures] = None
    ) -> float:
        """
        Estimate slippage % based on price tier, spread, and liquidity.

        Formula: base_slippage × spread_multiplier × volume_multiplier
        """
        # Base slippage by tier
        if liq.price < 1.0:
            base = self.liq_config.penny_slippage_base_pct
        elif liq.price < 5.0:
            base = self.liq_config.micro_slippage_base_pct
        elif liq.price < 20.0:
            base = self.liq_config.small_slippage_base_pct
        else:
            base = self.liq_config.standard_slippage_base_pct

        # Spread multiplier (wider spread = more slippage)
        if liq.spread_pct > 2.0:
            spread_mult = 2.0
        elif liq.spread_pct > 1.0:
            spread_mult = 1.5
        elif liq.spread_pct > 0.5:
            spread_mult = 1.2
        else:
            spread_mult = 1.0

        # Volume multiplier (lower volume = more slippage)
        if liq.average_daily_volume < 50_000:
            vol_mult = 2.0
        elif liq.average_daily_volume < 100_000:
            vol_mult = 1.5
        elif liq.average_daily_volume < 500_000:
            vol_mult = 1.2
        else:
            vol_mult = 1.0

        # Volatility adjustment
        vol_mult_additional = 1.0
        if ict and ict.volatility_class == "high":
            vol_mult_additional = 1.3
        elif ict and ict.volatility_class == "low":
            vol_mult_additional = 0.9

        total_slippage = base * spread_mult * vol_mult * vol_mult_additional
        return round(total_slippage, 2)

    def _adjust_stop_for_tick_size(
        self, stop: float, tick_size: float, price: float
    ) -> float:
        """
        Adjust stop to respect tick size, especially critical for penny stocks.

        For sub-$1 stocks with $0.01 tick:
        - Ensure stop is at valid tick increment
        - Prevent unrealistically tight stops
        """
        # Round stop to nearest tick
        adjusted_stop = round(stop / tick_size) * tick_size

        # For penny stocks, enforce minimum stop distance due to tick granularity
        if price < 1.0:
            min_stop_distance = tick_size * 2  # At least 2 ticks
            if (price - adjusted_stop) < min_stop_distance:
                adjusted_stop = price - min_stop_distance

        return round(adjusted_stop, 4)

    def _apply_liquidity_caps(
        self, result: PositionSizingResult, liq: LiquidityProfile
    ) -> PositionSizingResult:
        """Apply order size caps based on ADV and intraday volume."""
        if not result.accepted:
            return result

        # Cap 1: Order size vs ADV
        max_shares_by_adv = int(
            liq.average_daily_volume * (self.liq_config.max_order_size_pct_of_adv / 100)
        )

        # Cap 2: Order size vs today's volume
        max_shares_by_intraday = int(
            liq.today_volume * (self.liq_config.max_order_size_pct_of_intraday / 100)
        )

        # Apply most restrictive cap
        original_shares = result.shares
        capped_shares = min(result.shares, max_shares_by_adv, max_shares_by_intraday)

        if capped_shares < original_shares:
            result.shares = capped_shares
            result.total_capital_used = round(capped_shares * result.total_capital_used / original_shares, 2)
            result.total_dollar_risk = round(capped_shares * result.dollar_risk_per_share, 2)
            result.liquidity_cap_applied = True
            logger.info(
                f"Liquidity cap applied: {original_shares} → {capped_shares} shares "
                f"(ADV cap: {max_shares_by_adv}, Intraday cap: {max_shares_by_intraday})"
            )

        return result

    def _calculate_base_position(
        self,
        entry: float,
        stop: float,
        targets: list[float],
        account_equity: float,
        ict: Optional[ICTFeatures],
        stock_type: Optional[str],
    ) -> PositionSizingResult:
        """Calculate base position using parent class logic."""
        return self.calculate_position(
            entry=entry,
            stop=stop,
            targets=targets,
            account_equity=account_equity,
            ict=ict,
            stock_type=stock_type,
        )

    def _enrich_result_with_liquidity_data(
        self,
        result: PositionSizingResult,
        liq: LiquidityProfile,
        liq_score: float,
        slippage_pct: float,
        adj_stop: float,
        adj_targets: list[float],
    ) -> PositionSizingResult:
        """Add liquidity metadata to result for signal output."""
        result.liquidity_score = liq_score
        result.slippage_pct = slippage_pct
        result.spread_pct = liq.spread_pct
        result.order_pct_of_adv = (
            (result.shares / liq.average_daily_volume * 100)
            if liq.average_daily_volume > 0 else 0
        )
        result.order_pct_of_intraday = (
            (result.shares / liq.today_volume * 100)
            if liq.today_volume > 0 else 0
        )
        result.slippage_adjusted_stop = adj_stop
        result.slippage_adjusted_targets = adj_targets

        return result

    @staticmethod
    def create_liquidity_profile_from_bars(
        bars: list, bid: float = 0.0, ask: float = 0.0
    ) -> LiquidityProfile:
        """
        Create LiquidityProfile from OHLCV bars and optional bid/ask.
        """
        if not bars:
            return LiquidityProfile()

        # Calculate volumes
        total_volume = sum(b.volume for b in bars)

        # Use last 20 bars (or all if less) for intraday pacing
        recent_bars = bars[-20:] if len(bars) >= 20 else bars
        recent_volume = sum(b.volume for b in recent_bars)

        # Estimate 15min volume (proportional to bar count)
        bars_per_15min = 15  # Assuming 1-min bars
        volume_15min = recent_volume * (bars_per_15min / len(recent_bars))

        # Current price
        current_price = bars[-1].close

        # Spread calculation
        if bid > 0 and ask > 0:
            spread = ask - bid
            spread_pct = (spread / ((ask + bid) / 2)) * 100
        else:
            # Estimate from high/low of last bar
            last_bar = bars[-1]
            spread = last_bar.high - last_bar.low
            spread_pct = (spread / current_price) * 100

        # Tick size based on price tier
        if current_price < 1.0:
            tick_size = 0.01
        elif current_price < 10.0:
            tick_size = 0.01
        else:
            tick_size = 0.01  # Standard for most US equities

        return LiquidityProfile(
            average_daily_volume=total_volume,  # Assuming bars are daily
            today_volume=recent_volume,
            intraday_volume_15min=int(volume_15min),
            bid_price=bid if bid > 0 else current_price - spread / 2,
            ask_price=ask if ask > 0 else current_price + spread / 2,
            spread_amount=spread,
            spread_pct=round(spread_pct, 4),
            tick_size=tick_size,
            price=current_price,
        )
