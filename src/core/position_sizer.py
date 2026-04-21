"""
Position Sizer — V5

Risk-based position sizing with volatility-aware caps and safeguards.
"""

import logging
from typing import Optional

from src.models.schemas import ICTFeatures, PositionSizingConfig, PositionSizingResult

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Calculates position size based on risk parameters, volatility, and safeguards.

    Core formula: shares = (account_equity × max_risk_pct) / (entry - stop)

    With safeguards:
    - Minimum position size (practical trading limit)
    - Maximum position size (risk concentration limit)
    - Volatility-based caps (high vol = smaller positions)
    - Stock type caps (low float = more restrictive)
    - Stop distance limits (reject if stop too wide)
    """

    def __init__(self, config: Optional[PositionSizingConfig] = None):
        self.config = config or PositionSizingConfig()

    def calculate_position(
        self,
        entry: float,
        stop: float,
        targets: list[float],
        account_equity: float,
        ict: Optional[ICTFeatures] = None,
        stock_type: Optional[str] = None,
    ) -> PositionSizingResult:
        """
        Calculate optimal position size with all safeguards applied.

        Returns PositionSizingResult with accepted=True if trade passes all checks.
        """
        # Initialize result
        result = PositionSizingResult()
        result.max_risk_pct_applied = self.config.max_risk_per_trade_pct

        # Validate inputs
        if entry <= 0 or stop <= 0 or account_equity <= 0:
            result.rejection_reason = "Invalid price or equity values"
            logger.warning(f"Position sizing rejected: {result.rejection_reason}")
            return result

        # Calculate stop distance
        stop_distance = entry - stop
        stop_distance_pct = (stop_distance / entry) * 100 if entry > 0 else 0

        if stop_distance <= 0:
            result.rejection_reason = "Stop must be below entry for long positions"
            logger.warning(f"Position sizing rejected: {result.rejection_reason}")
            return result

        # Check 1: Stop distance not too wide
        if stop_distance_pct > self.config.max_stop_distance_pct:
            result.rejection_reason = (
                f"Stop distance {stop_distance_pct:.1f}% exceeds max "
                f"{self.config.max_stop_distance_pct:.1f}%"
            )
            logger.warning(f"Position sizing rejected: {result.rejection_reason}")
            return result

        # Calculate R-multiples for each target
        r_multiples = []
        expected_rewards = []
        for target in targets:
            if target > entry:
                reward = target - entry
                r_multiple = reward / stop_distance if stop_distance > 0 else 0
                r_multiples.append(round(r_multiple, 2))
                expected_rewards.append(round(reward, 2))

        result.r_multiples = r_multiples
        result.expected_rewards = expected_rewards
        result.dollar_risk_per_share = round(stop_distance, 2)

        # Calculate base position size from risk
        max_dollar_risk = account_equity * (self.config.max_risk_per_trade_pct / 100)
        base_shares = int(max_dollar_risk / stop_distance)

        # Calculate max position based on capital allocation
        max_position_value = account_equity * (self.config.max_position_size_pct / 100)
        max_shares_by_capital = int(max_position_value / entry)

        # Start with most restrictive limit
        shares = min(base_shares, max_shares_by_capital)

        # Apply volatility cap if ICT data available
        if ict and ict.volatility_class:
            vol_multiplier = self._get_volatility_multiplier(ict.volatility_class)
            vol_capped_shares = int(base_shares * vol_multiplier)
            shares = min(shares, vol_capped_shares)
            if shares < base_shares:
                result.vol_cap_applied = True
                logger.debug(
                    f"Volatility cap applied: {ict.volatility_class} -> "
                    f"{vol_multiplier:.1f}x multiplier"
                )

        # Apply stock type cap
        if stock_type:
            type_capped_shares = self._get_stock_type_cap(
                stock_type, account_equity, entry
            )
            if type_capped_shares < shares:
                shares = type_capped_shares
                result.stock_type_cap_applied = True
                logger.debug(f"Stock type cap applied: {stock_type}")

        # Apply absolute min/max limits
        shares = max(shares, self.config.min_position_size_shares)
        shares = min(shares, self.config.max_position_size_shares)

        # Check 2: Minimum position size (practical limit)
        if shares < self.config.min_position_size_shares:
            result.rejection_reason = (
                f"Calculated shares ({shares}) below minimum "
                f"{self.config.min_position_size_shares}"
            )
            logger.warning(f"Position sizing rejected: {result.rejection_reason}")
            return result

        # Calculate final values
        result.shares = shares
        result.total_capital_used = round(shares * entry, 2)
        result.total_dollar_risk = round(shares * stop_distance, 2)

        # Check 3: Capital allocation limit
        if result.total_capital_used > max_position_value:
            result.rejection_reason = (
                f"Required capital ${result.total_capital_used:.2f} exceeds "
                f"max allocation ${max_position_value:.2f}"
            )
            logger.warning(f"Position sizing rejected: {result.rejection_reason}")
            return result

        # All checks passed
        result.accepted = True
        logger.info(
            f"Position sized: {shares} shares @ ${entry:.2f}, "
            f"Risk: ${result.total_dollar_risk:.2f} "
            f"({self.config.max_risk_per_trade_pct:.1f}% of ${account_equity:.2f}), "
            f"R: {r_multiples[0] if r_multiples else 'N/A'}"
        )

        return result

    def _get_volatility_multiplier(self, volatility_class: str) -> float:
        """Get position size multiplier based on volatility class."""
        multipliers = {
            "low": self.config.low_vol_max_position_multiplier,      # 1.5 default
            "medium": 1.0,                                           # Normal
            "high": self.config.high_vol_max_position_multiplier,    # 0.6 default
        }
        return multipliers.get(volatility_class, 1.0)

    def _get_stock_type_cap(
        self, stock_type: str, account_equity: float, entry: float
    ) -> int:
        """
        Calculate max shares based on stock type risk profile.

        Low float = lower cap (more risk)
        Large cap = higher cap (less risk)
        """
        caps = {
            "low_float_momentum": self.config.low_float_max_position_pct,
            "mid_cap_liquid": 10.0,
            "large_cap": self.config.large_cap_max_position_pct,
            "biotech_news": 5.0,
            "earnings_mover": 7.0,
        }

        max_pct = caps.get(stock_type, 10.0)
        max_value = account_equity * (max_pct / 100)
        return int(max_value / entry) if entry > 0 else 0

    def calculate_r_multiple(
        self, entry: float, exit_price: float, stop: float
    ) -> float:
        """
        Calculate R-multiple for a completed trade.

        R = (exit - entry) / (entry - stop) for long positions
        """
        if entry <= stop:
            return 0.0

        risk_per_share = entry - stop
        pnl_per_share = exit_price - entry

        return round(pnl_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    # ── Penny Stock Support ─────────────────────────────────────────────────

    @staticmethod
    def create_penny_stock_config() -> PositionSizingConfig:
        """
        Create configuration optimized for penny stocks (<$1).

        Adjustments:
        - Wider stop allowance (15% vs 8%)
        - Smaller max position (5% vs 10%)
        - Lower max shares (5,000 vs 10,000)
        - Reduced risk per trade (0.5% vs 1%)
        """
        return PositionSizingConfig(
            max_risk_per_trade_pct=0.5,      # 0.5% risk (half of standard)
            max_position_size_pct=5.0,       # 5% max position (half of standard)
            min_position_size_shares=100,    # 100 shares minimum (higher for penny stocks)
            max_position_size_shares=5000,   # 5,000 max (lower due to liquidity)
            max_stop_distance_pct=15.0,      # 15% max stop (penny stocks need wider stops)
            low_vol_max_position_multiplier=1.2,
            high_vol_max_position_multiplier=0.4,
            low_float_max_position_pct=3.0,  # Very restrictive for penny/low float
            large_cap_max_position_pct=5.0,
        )

    @staticmethod
    def get_config_for_price_tier(price: float) -> PositionSizingConfig:
        """
        Auto-select appropriate config based on stock price tier.

        Tiers:
        - Penny: <$1.00
        - Micro: $1.00 - $5.00
        - Small: $5.00 - $20.00
        - Standard: >$20.00
        """
        if price < 1.0:
            # Penny stock config
            return PositionSizer.create_penny_stock_config()
        elif price < 5.0:
            # Micro cap config (moderate adjustments)
            return PositionSizingConfig(
                max_risk_per_trade_pct=0.75,
                max_position_size_pct=7.5,
                min_position_size_shares=50,
                max_position_size_shares=7500,
                max_stop_distance_pct=12.0,
            )
        elif price < 20.0:
            # Small cap config (minor adjustments)
            return PositionSizingConfig(
                max_risk_per_trade_pct=0.9,
                max_position_size_pct=9.0,
                min_position_size_shares=25,
                max_stop_distance_pct=10.0,
            )
        else:
            # Standard config for large caps
            return PositionSizingConfig()
