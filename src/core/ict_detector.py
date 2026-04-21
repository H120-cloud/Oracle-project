"""
ICT/Smart Money Concepts Detector — V1

Simple rule-based detection for:
  - Break of Structure (BOS)
  - Liquidity sweeps (wick below/above key levels with reversal)
  - Impulsive move origin (where large move started)
  - Order blocks (last opposing candle before impulse)
  - Extension filter (avoid entries after X% move without pullback)
"""

import logging
from dataclasses import dataclass
from typing import Optional, List

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ICTFeatures:
    """Container for ICT/smart money features."""
    # Core ICT features
    bos_detected: bool = False
    bos_direction: str = "none"  # "bullish" or "bearish"
    liquidity_sweep: bool = False
    sweep_direction: str = "none"  # "up" (wick above) or "down" (wick below)
    sweep_level: float = 0.0
    impulse_origin_price: float = 0.0
    impulse_strength_pct: float = 0.0
    order_block_price: float = 0.0
    order_block_type: str = "none"  # "bullish" or "bearish"
    extension_pct: float = 0.0
    is_overextended: bool = False
    recent_swing_low: float = 0.0
    recent_swing_high: float = 0.0

    # V2: Enhanced precision features
    ict_score: int = 0  # 0-100 weighted score

    # Micro Structure Break (MSB) - entry confirmation
    micro_high_level: float = 0.0  # Most recent local high during pullback
    micro_low_level: float = 0.0  # Most recent local low
    structure_break_confirmed: bool = False  # Price > micro_high_level

    # Order block proximity
    distance_to_order_block_pct: float = 0.0  # % distance from current price to OB
    near_order_block: bool = False  # Within 2-3% of OB

    # Trap detection
    trap_detected: bool = False  # Near highs, failing to break, exhaustion
    trap_reason: str = ""  # Why it's a trap

    # Structure reclaim
    structure_reclaimed: bool = False  # After sweep, reclaimed key level
    reclaim_level: float = 0.0  # Level that was reclaimed

    # V4: Execution quality fields
    atr_value: float = 0.0
    atr_pct: float = 0.0
    volatility_class: str = "medium"  # "low", "medium", "high"
    atr_stop_multiplier: float = 1.5
    order_block_freshness: float = 1.0  # 0.0-1.0, 1.0 = fresh

    # V7: Follow-through confirmation fields
    breakout_quality: str = "none"  # "confirmed", "weak", "fake", "none"
    follow_through_confirmed: bool = False
    follow_through_candles: int = 0
    upper_wick_pressure: bool = False
    volume_stable_or_increasing: bool = False


class ICTDetector:
    """Detect ICT/smart money patterns from OHLCV data."""

    # Configurable thresholds
    IMPULSE_THRESHOLD_PCT = 2.0  # Min 2% move to count as impulsive
    EXTENSION_THRESHOLD_PCT = 15.0  # Avoid entries after 15% move
    SWEEP_WICK_RATIO = 0.6  # Wick must be 60%+ of candle range
    LOOKBACK_BARS = 20  # How far back to look for structure

    # V2: Precision thresholds
    OB_PROXIMITY_THRESHOLD_PCT = 3.0  # Within 3% of order block = high quality
    TRAP_DISTANCE_FROM_HIGH_PCT = 2.0  # Within 2% of recent high = potential trap
    STRUCTURE_BREAK_BUFFER_PCT = 0.3  # Must exceed micro high by 0.3% for confirmation

    # V4: Volatility and ATR thresholds
    ATR_PERIOD = 14  # Standard ATR period
    LOW_VOLATILITY_ATR_PCT = 1.5  # ATR < 1.5% = low vol
    HIGH_VOLATILITY_ATR_PCT = 3.0  # ATR > 3.0% = high vol
    ATR_STOP_MULTIPLIER_LOW = 1.0  # Tight stops for low vol
    ATR_STOP_MULTIPLIER_MEDIUM = 1.5  # Normal stops
    ATR_STOP_MULTIPLIER_HIGH = 2.0  # Wide stops for high vol

    def detect(self, ticker: str, bars: list) -> Optional[ICTFeatures]:
        """
        Analyze price bars and return ICT features with enhanced precision.

        bars: list of dict/ objects with open, high, low, close, volume
        """
        if len(bars) < 10:
            logger.warning("Not enough bars for ICT detection [%s]", ticker)
            return None

        try:
            highs = np.array([b.high for b in bars])
            lows = np.array([b.low for b in bars])
            opens = np.array([b.open for b in bars])
            closes = np.array([b.close for b in bars])
            volumes = np.array([b.volume for b in bars]) if hasattr(bars[0], 'volume') else np.ones(len(bars))

            # Find swing highs and lows
            swing_highs, swing_lows = self._find_swings(highs, lows)

            # Detect BOS
            bos_detected, bos_dir = self._detect_bos(
                highs, lows, closes, swing_highs, swing_lows
            )

            # Detect liquidity sweep
            sweep_detected, sweep_dir, sweep_level = self._detect_liquidity_sweep(
                highs, lows, closes, swing_highs, swing_lows
            )

            # Detect impulse origin and order block
            impulse_price, impulse_pct, ob_price, ob_type = self._detect_impulse_and_ob(
                opens, highs, lows, closes
            )

            # Calculate extension
            extension_pct, is_overextended = self._calculate_extension(
                closes, impulse_price
            )

            # V2: Micro Structure Break detection
            micro_high, micro_low, structure_break = self._detect_micro_structure_break(
                highs, lows, closes
            )

            # V2: Order block distance
            ob_distance, near_ob = self._calculate_ob_distance(
                closes, ob_price
            )

            # V2: Structure reclaim (after sweep)
            reclaimed, reclaim_level = self._detect_structure_reclaim(
                closes, sweep_detected, sweep_level, swing_highs, swing_lows
            )

            # V4: Trap detection
            trap_detected, trap_reason = self._detect_trap(
                highs, lows, closes, volumes, swing_highs, swing_lows
            )

            # V4: ATR and volatility classification
            atr_value, atr_pct, volatility_class = self._calculate_atr_and_volatility(
                highs, lows, closes
            )

            # V4: Order block freshness tracking
            ob_freshness = self._calculate_ob_freshness(
                closes, ob_price, swing_highs, swing_lows
            )

            # V4: Calculate weighted ICT score (with trap cap)
            ict_score = self._calculate_ict_score_v4(
                sweep_detected, reclaimed, structure_break, near_ob,
                trap_detected, bos_detected, is_overextended, ob_freshness
            )

            # V7: Follow-through confirmation for breakouts
            breakout_quality, follow_through_confirmed, follow_candles, upper_wick_pressure, volume_stable = self._detect_follow_through(
                opens, highs, lows, closes, volumes, structure_break, micro_high
            )

            features = ICTFeatures(
                # Core features
                bos_detected=bos_detected,
                bos_direction=bos_dir,
                liquidity_sweep=sweep_detected,
                sweep_direction=sweep_dir,
                sweep_level=sweep_level,
                impulse_origin_price=impulse_price,
                impulse_strength_pct=impulse_pct,
                order_block_price=ob_price,
                order_block_type=ob_type,
                extension_pct=extension_pct,
                is_overextended=is_overextended,
                recent_swing_low=swing_lows[-1][1] if swing_lows else 0.0,
                recent_swing_high=swing_highs[-1][1] if swing_highs else 0.0,
                # V2 features
                ict_score=ict_score,
                micro_high_level=micro_high,
                micro_low_level=micro_low,
                structure_break_confirmed=structure_break,
                distance_to_order_block_pct=ob_distance,
                near_order_block=near_ob,
                trap_detected=trap_detected,
                trap_reason=trap_reason,
                structure_reclaimed=reclaimed,
                reclaim_level=reclaim_level,
                # V4 features
                atr_value=atr_value,
                atr_pct=atr_pct,
                volatility_class=volatility_class,
                atr_stop_multiplier=self._get_atr_multiplier(volatility_class),
                order_block_freshness=ob_freshness,
                # V7 features
                breakout_quality=breakout_quality,
                follow_through_confirmed=follow_through_confirmed,
                follow_through_candles=follow_candles,
                upper_wick_pressure=upper_wick_pressure,
                volume_stable_or_increasing=volume_stable,
            )

            logger.debug(
                "ICT[%s]: score=%d BOS=%s sweep=%s msb=%s trap=%s OB=%.1f%%",
                ticker, ict_score, bos_detected, sweep_detected,
                structure_break, trap_detected, ob_distance
            )
            return features

        except Exception as exc:
            logger.error("ICT detection failed for %s: %s", ticker, exc)
            return None

    def _find_swings(self, highs: np.ndarray, lows: np.ndarray) -> tuple:
        """Find swing highs and lows (local extrema)."""
        swing_highs = []
        swing_lows = []

        for i in range(2, len(highs) - 2):
            # Swing high: higher than neighbors
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append((i, float(highs[i])))

            # Swing low: lower than neighbors
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append((i, float(lows[i])))

        return swing_highs, swing_lows

    def _detect_bos(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        swing_highs: list, swing_lows: list
    ) -> tuple[bool, str]:
        """
        Detect Break of Structure.

        Bullish BOS: Price takes out previous swing high
        Bearish BOS: Price takes out previous swing low
        """
        if not swing_highs or not swing_lows:
            return False, "none"

        current_price = float(closes[-1])

        # Get recent significant swings (last 3)
        recent_highs = [h for _, h in swing_highs[-3:]]
        recent_lows = [l for _, l in swing_lows[-3:]]

        if not recent_highs or not recent_lows:
            return False, "none"

        # Bullish BOS: Close above previous swing high
        prev_swing_high = max(recent_highs[:-1]) if len(recent_highs) > 1 else recent_highs[0]
        if current_price > prev_swing_high * 1.005:  # 0.5% buffer
            return True, "bullish"

        # Bearish BOS: Close below previous swing low
        prev_swing_low = min(recent_lows[:-1]) if len(recent_lows) > 1 else recent_lows[0]
        if current_price < prev_swing_low * 0.995:  # 0.5% buffer
            return True, "bearish"

        return False, "none"

    def _detect_liquidity_sweep(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        swing_highs: list, swing_lows: list
    ) -> tuple[bool, str, float]:
        """
        Detect liquidity sweep: wick beyond swing level with reversal.

        Bearish sweep (trapping longs): Wick above swing high, close below
        Bullish sweep (trapping shorts): Wick below swing low, close above
        """
        if len(closes) < 5 or not swing_highs or not swing_lows:
            return False, "none", 0.0

        # Check last 3 bars for sweeps
        for i in range(-3, 0):
            if i + len(closes) < 0:
                continue

            candle_high = float(highs[i])
            candle_low = float(lows[i])
            candle_close = float(closes[i])
            candle_open = float(closes[i-1]) if i > -len(closes) else candle_close

            # Get key levels
            recent_highs = [h for _, h in swing_highs[-3:]]
            recent_lows = [l for _, l in swing_lows[-3:]]
            swing_high_level = max(recent_highs) if recent_highs else candle_high
            swing_low_level = min(recent_lows) if recent_lows else candle_low

            # Bearish sweep: Wick above swing high, close lower (rejection)
            upper_wick = candle_high - max(candle_close, candle_open)
            candle_range = candle_high - candle_low
            if candle_range > 0:
                if candle_high > swing_high_level and upper_wick / candle_range > 0.5:
                    if candle_close < swing_high_level:  # Reversed back below
                        return True, "up", swing_high_level

            # Bullish sweep: Wick below swing low, close higher (reversal)
            lower_wick = min(candle_close, candle_open) - candle_low
            if candle_range > 0:
                if candle_low < swing_low_level and lower_wick / candle_range > 0.5:
                    if candle_close > swing_low_level:  # Reversed back above
                        return True, "down", swing_low_level

        return False, "none", 0.0

    def _detect_impulse_and_ob(
        self, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> tuple[float, float, float, str]:
        """
        Detect impulsive move origin and order block.

        Impulse: Large candle (>2%) with strong close
        Order block: Last opposing candle before impulse
        """
        if len(closes) < 5:
            return 0.0, 0.0, 0.0, "none"

        # Look for largest recent candle
        max_impulse_idx = -1
        max_impulse_pct = 0.0

        for i in range(-10, -1):  # Last 10 bars excluding current
            if i + len(closes) < 0:
                continue

            candle_range = abs(float(closes[i]) - float(opens[i]))
            mid_price = (float(highs[i]) + float(lows[i])) / 2
            impulse_pct = (candle_range / mid_price) * 100

            if impulse_pct > max_impulse_pct and impulse_pct > self.IMPULSE_THRESHOLD_PCT:
                max_impulse_pct = impulse_pct
                max_impulse_idx = i

        if max_impulse_idx == -1:
            return 0.0, 0.0, 0.0, "none"

        # Determine impulse direction
        impulse_close = float(closes[max_impulse_idx])
        impulse_open = float(opens[max_impulse_idx])
        is_bullish_impulse = impulse_close > impulse_open

        # Find order block (candle before impulse, opposing direction)
        ob_idx = max_impulse_idx - 1
        if ob_idx >= -len(closes):
            ob_open = float(opens[ob_idx])
            ob_close = float(closes[ob_idx])
            ob_high = float(highs[ob_idx])
            ob_low = float(lows[ob_idx])

            # Order block is opposing candle
            if is_bullish_impulse and ob_close < ob_open:  # Bearish candle before bullish impulse
                ob_price = ob_high  # Use high as reference level
                return impulse_open, max_impulse_pct, ob_price, "bullish"
            elif not is_bullish_impulse and ob_close > ob_open:  # Bullish candle before bearish impulse
                ob_price = ob_low  # Use low as reference level
                return impulse_open, max_impulse_pct, ob_price, "bearish"

        return impulse_open, max_impulse_pct, 0.0, "none"

    def _calculate_extension(
        self, closes: np.ndarray, impulse_origin: float
    ) -> tuple[float, bool]:
        """
        Calculate how extended price is from impulse origin.

        Extension = % move from origin without significant pullback
        """
        if impulse_origin == 0 or len(closes) < 5:
            return 0.0, False

        current_price = float(closes[-1])
        extension_pct = abs((current_price - impulse_origin) / impulse_origin) * 100

        is_overextended = extension_pct > self.EXTENSION_THRESHOLD_PCT

        return extension_pct, is_overextended

    # ── V2: Enhanced Precision Methods ─────────────────────────────────────

    def _detect_micro_structure_break(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> tuple[float, float, bool]:
        """
        Detect Micro Structure Break (MSB) for entry confirmation.

        Finds most recent local high/low during pullback and checks
        if price has broken above the micro high.

        Returns: (micro_high, micro_low, structure_break_confirmed)
        """
        if len(closes) < 10:
            return 0.0, 0.0, False

        current_price = float(closes[-1])

        # Find micro structure in recent bars (last 10-15)
        lookback = min(15, len(closes) - 2)
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]

        # Find the most recent significant high (must have lower bars after it)
        micro_high = 0.0
        micro_low = float(recent_lows.min())

        # Look for pattern: rise, then pullback forming a local high
        for i in range(len(recent_highs) - 3, 2, -1):
            # Check if this bar is higher than bars after it (local peak)
            if recent_highs[i] > recent_highs[i+1] and recent_highs[i] > recent_highs[i+2]:
                micro_high = float(recent_highs[i])
                break

        # If no clear micro high, use max of recent highs
        if micro_high == 0.0:
            micro_high = float(recent_highs.max())

        # Structure break: current price exceeds micro high by buffer
        buffer = micro_high * (1 + self.STRUCTURE_BREAK_BUFFER_PCT / 100)
        structure_break = current_price > buffer

        return micro_high, micro_low, structure_break

    def _calculate_ob_distance(
        self, closes: np.ndarray, ob_price: float
    ) -> tuple[float, bool]:
        """
        Calculate distance to order block as % and proximity flag.

        Returns: (distance_pct, near_order_block)
        """
        if ob_price == 0 or len(closes) == 0:
            return 0.0, False

        current_price = float(closes[-1])
        distance_pct = abs((current_price - ob_price) / ob_price) * 100

        near_ob = distance_pct < self.OB_PROXIMITY_THRESHOLD_PCT

        return distance_pct, near_ob

    def _detect_structure_reclaim(
        self, closes: np.ndarray, sweep_detected: bool, sweep_level: float,
        swing_highs: list, swing_lows: list
    ) -> tuple[bool, float]:
        """
        Detect if price reclaimed key structure after a sweep.

        After a liquidity sweep below lows, check if price reclaimed:
        - The sweep level, or
        - Recent swing high (bullish confirmation)

        Returns: (structure_reclaimed, reclaim_level)
        """
        if len(closes) < 3:
            return False, 0.0

        current_price = float(closes[-1])
        prev_close = float(closes[-2])

        # If we swept lows, check if we reclaimed above a key level
        if sweep_detected and sweep_level > 0:
            # Reclaimed if now above sweep level
            if current_price > sweep_level:
                return True, sweep_level

        # Check if reclaimed recent swing low (for bullish setups)
        if swing_lows:
            recent_low = swing_lows[-1][1]
            if current_price > recent_low and prev_close < recent_low:
                return True, recent_low

        return False, 0.0

    def _detect_trap(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        volumes: np.ndarray, swing_highs: list, swing_lows: list
    ) -> tuple[bool, str]:
        """
        Detect potential distribution traps or fake breakouts.

        Signs of a trap:
        1. Price near recent highs (within 2%)
        2. Multiple tests of resistance with failure
        3. Volume decreasing (exhaustion)
        4. Small candles (momentum slowing)
        """
        if len(closes) < 10 or not swing_highs:
            return False, ""

        current_price = float(closes[-1])
        recent_high = max([h for _, h in swing_highs[-3:]]) if swing_highs else float(highs.max())

        # Check 1: Near recent high
        distance_from_high = abs(recent_high - current_price) / recent_high * 100
        near_high = distance_from_high < self.TRAP_DISTANCE_FROM_HIGH_PCT

        if not near_high:
            return False, ""

        # Check 2: Multiple tests of resistance
        recent_highs_count = sum(1 for h in highs[-10:] if h > recent_high * 0.995)
        multiple_tests = recent_highs_count >= 3

        # Check 3: Volume decreasing (exhaustion)
        recent_vol = float(np.mean(volumes[-5:])) if len(volumes) >= 5 else 0
        prior_vol = float(np.mean(volumes[-15:-5])) if len(volumes) >= 15 else recent_vol
        volume_decreasing = recent_vol < prior_vol * 0.8 if prior_vol > 0 else False

        # Check 4: Small candles (momentum slowing)
        recent_ranges = highs[-5:] - lows[-5:]
        avg_range = float(np.mean(recent_ranges))
        historical_range = float(np.mean(highs[-20:] - lows[-20:]))
        small_candles = avg_range < historical_range * 0.7 if historical_range > 0 else False

        # Determine trap type
        if multiple_tests and volume_decreasing:
            return True, "distribution_trap: multiple tests with declining volume"
        elif small_candles and near_high:
            return True, "exhaustion_trap: near highs with small candles"
        elif near_high and not multiple_tests:
            return True, "resistance_trap: near highs without clean breakout"

        return False, ""

    def _calculate_ict_score(
        self, sweep_detected: bool, structure_reclaimed: bool,
        structure_break: bool, near_ob: bool, trap_detected: bool,
        bos_detected: bool, is_overextended: bool
    ) -> int:
        """
        Calculate weighted ICT score (0-100).

        Priorities (highest to lowest):
        - Liquidity sweep + reclaim: +40
        - Structure break confirmed: +25
        - Near order block: +15
        - BOS detected: +10
        - Penalties:
          - No sweep: -20
          - Trap detected: -30
          - Overextended: -15
        """
        score = 50  # Start neutral

        # High priority: Liquidity sweep with reclaim (the holy grail)
        if sweep_detected and structure_reclaimed:
            score += 40
        elif sweep_detected:
            score += 25  # Sweep alone is still good

        # Entry confirmation
        if structure_break:
            score += 25

        # Quality boosters
        if near_ob:
            score += 15
        if bos_detected:
            score += 10

        # Penalties
        if not sweep_detected:
            score -= 20  # No sweep = reduced confidence
        if trap_detected:
            score -= 30  # Trap = major penalty
        if is_overextended:
            score -= 15  # Chasing = bad

        # Clamp to 0-100
        return max(0, min(100, score))

    # ── V4: Execution Quality Methods ───────────────────────────────────────

    def _calculate_atr_and_volatility(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> tuple[float, float, str]:
        """
        Calculate ATR (Average True Range) and classify volatility.

        Returns: (atr_value, atr_pct_of_price, volatility_class)
        volatility_class: "low", "medium", "high"
        """
        if len(closes) < self.ATR_PERIOD + 1:
            return 0.0, 0.0, "medium"

        # Calculate True Range for each bar
        tr_values = []
        for i in range(1, len(closes)):
            high = float(highs[i])
            low = float(lows[i])
            prev_close = float(closes[i-1])

            # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            tr_values.append(tr)

        # Calculate ATR (simple moving average of TR)
        atr = np.mean(tr_values[-self.ATR_PERIOD:]) if len(tr_values) >= self.ATR_PERIOD else np.mean(tr_values)

        # ATR as % of current price
        current_price = float(closes[-1])
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0.0

        # Classify volatility
        if atr_pct < self.LOW_VOLATILITY_ATR_PCT:
            volatility_class = "low"
        elif atr_pct > self.HIGH_VOLATILITY_ATR_PCT:
            volatility_class = "high"
        else:
            volatility_class = "medium"

        return float(atr), atr_pct, volatility_class

    def _get_atr_multiplier(self, volatility_class: str) -> float:
        """Get ATR multiplier for stop calculation based on volatility class."""
        multipliers = {
            "low": self.ATR_STOP_MULTIPLIER_LOW,
            "medium": self.ATR_STOP_MULTIPLIER_MEDIUM,
            "high": self.ATR_STOP_MULTIPLIER_HIGH,
        }
        return multipliers.get(volatility_class, self.ATR_STOP_MULTIPLIER_MEDIUM)

    def _calculate_ob_freshness(
        self, closes: np.ndarray, ob_price: float,
        swing_highs: list, swing_lows: list
    ) -> float:
        """
        Calculate order block freshness score (0.0 - 1.0).

        1.0 = fresh (never tested)
        0.0 = fully used (tested multiple times, price through it)

        Factors:
        - How many times has price approached OB
        - Has price closed through OB
        - Recency of tests
        """
        if ob_price == 0 or len(closes) < 10:
            return 1.0  # Assume fresh if no data

        current_price = float(closes[-1])
        lookback = min(20, len(closes))
        recent_closes = closes[-lookback:]

        # Count approaches (within 1% of OB)
        approach_threshold = ob_price * 0.01
        approaches = sum(1 for c in recent_closes if abs(float(c) - ob_price) < approach_threshold)

        # Check if price closed through OB (invalidated)
        # For bullish OB (below price), check if price broke below
        # For bearish OB (above price), check if price broke above
        ob_direction = "bullish" if ob_price < current_price else "bearish"

        invalidated = False
        if ob_direction == "bullish":
            # Bullish OB: price should hold above it
            # Invalidated if close below OB
            invalidated = any(float(c) < ob_price * 0.995 for c in recent_closes)
        else:
            # Bearish OB: price should stay below it
            # Invalidated if close above OB
            invalidated = any(float(c) > ob_price * 1.005 for c in recent_closes)

        # Calculate freshness score
        if invalidated:
            return 0.2  # Severely reduced but not zero (could still act as S/R)

        # Reduce freshness based on number of approaches
        freshness = max(0.3, 1.0 - (approaches * 0.15))

        return freshness

    def _calculate_ict_score_v4(
        self, sweep_detected: bool, structure_reclaimed: bool,
        structure_break: bool, near_ob: bool, trap_detected: bool,
        bos_detected: bool, is_overextended: bool, ob_freshness: float
    ) -> int:
        """
        V4: Enhanced ICT score with trap cap and OB freshness.

        Changes from V3:
        - Trap caps score at maximum 40
        - OB freshness reduces quality multiplier
        - No liquidity sweep has additional penalty
        """
        score = 50  # Start neutral

        # High priority: Liquidity sweep with reclaim
        if sweep_detected and structure_reclaimed:
            score += 40
        elif sweep_detected:
            score += 25

        # Entry confirmation
        if structure_break:
            score += 25

        # Quality boosters (with OB freshness adjustment)
        if near_ob:
            # Reduce OB bonus if stale
            ob_bonus = 15 * ob_freshness
            score += int(ob_bonus)

        if bos_detected:
            score += 10

        # Penalties
        if not sweep_detected:
            score -= 25  # V4: Increased penalty (was -20)
        if not structure_reclaimed and sweep_detected:
            score -= 10  # V4: Additional penalty for sweep without reclaim

        if trap_detected:
            score -= 30  # Major penalty

        if is_overextended:
            score -= 15

        # Clamp to 0-100
        score = max(0, min(100, score))

        # V4: Trap cap - if trap detected, max score is 40 regardless
        if trap_detected:
            score = min(score, 40)

        return score

    def _detect_follow_through(
        self, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
        closes: np.ndarray, volumes: np.ndarray, structure_break: bool, micro_high: float
    ) -> tuple[str, bool, int, bool, bool]:
        """
        V7: Detect follow-through confirmation after breakout/MSB.

        Returns:
            - breakout_quality: "confirmed", "weak", "fake", or "none"
            - follow_through_confirmed: True if 2-3 candles confirm
            - follow_through_candles: count of confirming candles
            - upper_wick_pressure: True if strong upper wicks present
            - volume_stable_or_increasing: True if volume sustained
        """
        if len(closes) < 5 or not structure_break or micro_high == 0:
            return "none", False, 0, False, True

        # Look at last 3-5 candles after breakout level
        lookback = min(5, len(closes) - 1)
        recent_closes = closes[-lookback:]
        recent_opens = opens[-lookback:]
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        recent_volumes = volumes[-lookback:]

        # Count candles that closed above breakout level (micro_high)
        breakout_buffer = micro_high * 1.002  # 0.2% buffer
        confirming_candles = sum(1 for c in recent_closes if c > breakout_buffer)

        # Check for strong upper wicks (>50% of candle range)
        candle_ranges = recent_highs - recent_lows
        candle_ranges = np.where(candle_ranges == 0, 1e-8, candle_ranges)  # Avoid div by zero
        upper_wicks = recent_highs - np.maximum(recent_closes, recent_opens)
        upper_wick_ratios = upper_wicks / candle_ranges
        strong_upper_wicks = sum(1 for ratio in upper_wick_ratios if ratio > 0.5)
        upper_wick_pressure = strong_upper_wicks >= 2

        # Volume analysis - stable or increasing?
        if len(volumes) >= lookback + 3:
            pre_breakout_vol = float(np.mean(volumes[-(lookback+3):-lookback]))
            post_breakout_vol = float(np.mean(recent_volumes))
            volume_stable_or_increasing = post_breakout_vol >= pre_breakout_vol * 0.9
        else:
            volume_stable_or_increasing = True  # Not enough data

        # Determine breakout quality
        if confirming_candles >= 3 and not upper_wick_pressure and volume_stable_or_increasing:
            breakout_quality = "confirmed"
            follow_through_confirmed = True
        elif confirming_candles >= 2 and strong_upper_wicks <= 1:
            breakout_quality = "weak"
            follow_through_confirmed = True
        elif confirming_candles <= 1 or (upper_wick_pressure and confirming_candles < 2):
            breakout_quality = "fake"
            follow_through_confirmed = False
        else:
            breakout_quality = "weak"
            follow_through_confirmed = confirming_candles >= 2

        return (
            breakout_quality,
            follow_through_confirmed,
            confirming_candles,
            upper_wick_pressure,
            volume_stable_or_increasing
        )
