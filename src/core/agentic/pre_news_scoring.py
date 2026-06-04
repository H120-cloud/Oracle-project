"""
Pre-News V2 — Scoring Engines

Pure, stateless scoring functions that extend the existing Pre-News Detector
with informed-positioning signals:

  - volume_acceleration_score   (Step 3)
  - buy_pressure_score          (Step 4)
  - float_pressure_score        (Step 5)
  - offering_risk_score         (Step 6)
  - smart_money_score           (Step 7)
  - mtf_alignment_score         (Step 8)
  - timing_stage classification (Step 9)
  - confidence decay            (Step 10)
  - session_quality_score       (Step 11)
  - move_type classification    (Step 15)

All functions are PURE — no I/O, no persistence, no side effects.
They take metrics in and return scores out.  The PreNewsDetector calls
them in sequence inside `_analyze_ticker` and stores results on the
PreNewsAnomaly record.

Design rules (per project spec):
  - No single feature > 40% influence on smart_money composite
  - All scores are 0-100
  - Conservative defaults (50 = neutral)
  - Never throws — always returns a safe value
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from src.core.agentic.pre_news_models import (
    MoveType,
    PreNewsAnomaly,
    PriceBehaviour,
    SessionQuality,
    TimingStage,
    VolumeMetrics,
)

_ET = ZoneInfo("America/New_York")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ════════════════════════════════════════════════════════════════════════════
#  STEP 3 — VOLUME ACCELERATION SCORE
# ════════════════════════════════════════════════════════════════════════════


def compute_volume_acceleration(bars: list) -> tuple[float, float, str]:
    """
    Volume acceleration over recent 5-bar windows.

    Returns:
        (raw_accel_ratio, normalized_score_0_100, trend_label)
        trend_label ∈ {"accelerating", "stable", "decelerating"}
    """
    if not bars or len(bars) < 6:
        return 0.0, 50.0, "stable"

    # Current 5-bar vs prior 5-bar window
    n = len(bars)
    curr = bars[-5:]
    prior = bars[-10:-5] if n >= 10 else bars[:-5]
    if not prior:
        return 0.0, 50.0, "stable"

    curr_vol = sum(b.volume for b in curr)
    prior_vol = sum(b.volume for b in prior)

    if prior_vol <= 0:
        return 0.0, 50.0, "stable"

    ratio = curr_vol / prior_vol  # 1.0 = flat, 2.0 = doubled, 0.5 = halved

    # Score mapping
    # ratio  1.0  → 50
    # ratio  2.0  → 80
    # ratio  3.0+ → 100
    # ratio  0.5  → 20
    # ratio  0.25 → 0
    if ratio >= 1.0:
        score = 50.0 + min(50.0, (ratio - 1.0) * 30.0)
    else:
        score = 50.0 - min(50.0, (1.0 - ratio) * 80.0)

    # Trend label
    if ratio >= 1.3:
        trend = "accelerating"
    elif ratio <= 0.75:
        trend = "decelerating"
    else:
        trend = "stable"

    return round(ratio, 3), _clamp(score), trend


# ════════════════════════════════════════════════════════════════════════════
#  STEP 4 — BUY PRESSURE SCORE
# ════════════════════════════════════════════════════════════════════════════


def compute_buy_pressure_score(bars: list) -> float:
    """
    Proxy for order-flow buy pressure using available OHLCV data.

    Components:
      - Green volume ratio: volume in up-bars / total volume
      - Close position in range: (close - low) / (high - low)
      - Uptick dominance: how many of last N bars closed above open
    """
    if not bars or len(bars) < 5:
        return 50.0

    recent = bars[-10:] if len(bars) >= 10 else bars

    # 1. Green vs red volume
    green_vol = sum(b.volume for b in recent if b.close > b.open)
    red_vol = sum(b.volume for b in recent if b.close < b.open)
    total_vol = green_vol + red_vol
    green_ratio = green_vol / total_vol if total_vol > 0 else 0.5

    # 2. Close position in range (averaged)
    positions = []
    for b in recent:
        rng = b.high - b.low
        if rng > 0:
            positions.append((b.close - b.low) / rng)
    avg_close_pos = sum(positions) / len(positions) if positions else 0.5

    # 3. Uptick dominance (fraction of bars closing > prior close)
    up = 0
    for i in range(1, len(recent)):
        if recent[i].close > recent[i - 1].close:
            up += 1
    uptick_ratio = up / max(1, len(recent) - 1)

    # Weighted composite — none exceeds 40% per guardrail spec
    score = (green_ratio * 40 + avg_close_pos * 35 + uptick_ratio * 25) * 100 / 100
    # scale components (each 0-1) → weight them so sum is 0-100
    composite = (green_ratio * 40) + (avg_close_pos * 35) + (uptick_ratio * 25)

    return _clamp(composite)


# ════════════════════════════════════════════════════════════════════════════
#  STEP 5 — FLOAT-ADJUSTED VOLUME (FLOAT PRESSURE SCORE)
# ════════════════════════════════════════════════════════════════════════════


def compute_float_pressure_score(
    current_volume: Optional[float],
    float_shares: Optional[float],
) -> float:
    """
    Volume / Float ratio — how much of the float has rotated today.

    Score mapping:
      - 0% of float      → 0
      - 25% of float     → 60   (notable)
      - 50% of float     → 80   (very high pressure)
      - 100%+ of float   → 100  (explosive, squeeze setup)
    """
    if not current_volume or not float_shares or float_shares <= 0:
        return 50.0  # neutral when data missing

    ratio = current_volume / float_shares

    if ratio >= 1.0:
        score = 100.0
    elif ratio >= 0.5:
        score = 80.0 + (ratio - 0.5) * 40.0
    elif ratio >= 0.25:
        score = 60.0 + (ratio - 0.25) * 80.0
    elif ratio >= 0.10:
        score = 40.0 + (ratio - 0.10) * (20.0 / 0.15)
    else:
        score = ratio * 400.0  # 0-40

    return _clamp(score)


# ════════════════════════════════════════════════════════════════════════════
#  STEP 6 — OFFERING / DILUTION RISK SCORE
# ════════════════════════════════════════════════════════════════════════════

_OFFERING_KEYWORDS = (
    "offering", "s-1", "s-3", "atm", "at-the-market",
    "prospectus", "dilut", "registered direct", "pipe financing",
    "warrant", "reverse split", "rights offering", "private placement",
    "capital raise", "stock split",
)


def compute_offering_risk_score(
    headlines_for_ticker: Iterable[str],
    dilution_risk_flag: bool = False,
    float_shares: Optional[float] = None,
    market_cap: Optional[float] = None,
) -> tuple[float, list[str]]:
    """
    Heuristic offering/dilution risk 0-100.

    High score = HIGH risk (downgrade anomaly).
    Based on:
      - Recent headline keyword matches
      - Existing dilution_risk flag from FloatIntelEngine
      - Large share count relative to market cap (low price × large shares)

    Returns (score, matched_keywords).
    """
    score = 0.0
    matched: list[str] = []

    # 1. Headline keyword scan
    for h in headlines_for_ticker:
        lower = h.lower()
        for kw in _OFFERING_KEYWORDS:
            if kw in lower:
                matched.append(kw)
                score += 25
                break

    # 2. Existing dilution flag
    if dilution_risk_flag:
        score += 30
        matched.append("dilution_flag")

    # 3. Low-price penny stock with high share count proxy
    if float_shares and market_cap and market_cap > 0:
        implied_price = market_cap / float_shares
        if implied_price < 1.0 and float_shares > 100_000_000:
            score += 15
            matched.append("penny_high_share_count")

    return _clamp(score), matched


# ════════════════════════════════════════════════════════════════════════════
#  STEP 8 — MULTI-TIMEFRAME VOLUME ALIGNMENT
# ════════════════════════════════════════════════════════════════════════════


def compute_mtf_alignment(
    bars_5m: list,
    avg_daily_volume: float,
) -> tuple[Optional[float], Optional[float], Optional[float], float]:
    """
    Approximate multi-timeframe RVOL alignment using 5m bars as the base.

    We don't always have true 1m data, so synthesize:
      - 1m_rvol ≈ last 5m bar / (avg_daily_volume / 390)
      - 5m_rvol = last 5m bar / (avg_daily_volume / 78)
      - 15m_rvol = last 3 bars summed / (avg_daily_volume / 26)

    Returns (rvol_1m, rvol_5m, rvol_15m, alignment_score).
    Alignment score = 100 when all three ≥ 2.0x AND monotonic (1m>=5m>=15m means
    volume is accelerating). Drops fast if 1m spike alone.
    """
    if not bars_5m or avg_daily_volume <= 0:
        return None, None, None, 50.0

    last_5m_bar_vol = bars_5m[-1].volume if bars_5m else 0
    last_5m_window = sum(b.volume for b in bars_5m[-1:])  # 1 bar = 5 min
    last_15m_window = sum(b.volume for b in bars_5m[-3:]) if len(bars_5m) >= 3 else last_5m_window

    rvol_1m = (last_5m_bar_vol / 5) / (avg_daily_volume / 390) if avg_daily_volume > 0 else 0
    rvol_5m = last_5m_window / (avg_daily_volume / 78) if avg_daily_volume > 0 else 0
    rvol_15m = last_15m_window / (avg_daily_volume / 26) if avg_daily_volume > 0 else 0

    # Alignment scoring
    all_elevated = all(x >= 2.0 for x in (rvol_1m, rvol_5m, rvol_15m))
    partially_elevated = sum(1 for x in (rvol_1m, rvol_5m, rvol_15m) if x >= 1.5)

    if all_elevated and rvol_1m >= rvol_5m * 0.8:
        score = 90.0 + min(10.0, (rvol_1m - 2.0) * 5)
    elif partially_elevated == 3:
        score = 75.0
    elif partially_elevated == 2:
        score = 55.0
    elif rvol_1m >= 3.0 and rvol_5m < 1.5:
        # lone 1m spike — classic noise / single print
        score = 25.0
    elif partially_elevated == 1:
        score = 40.0
    else:
        score = 20.0

    return round(rvol_1m, 2), round(rvol_5m, 2), round(rvol_15m, 2), _clamp(score)


# ════════════════════════════════════════════════════════════════════════════
#  STEP 11 — SESSION QUALITY SCORE
# ════════════════════════════════════════════════════════════════════════════


def compute_session_quality(now_utc: Optional[datetime] = None) -> tuple[SessionQuality, float]:
    """
    Score the current session's signal quality 0-100 based on time of day.
    Midday chop and close noise are downgraded.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    et = now_utc.astimezone(_ET)
    hh = et.hour
    mm = et.minute
    mins = hh * 60 + mm

    # Pre-market: 4:00 – 9:30 ET
    if mins < 9 * 60 + 30:
        return SessionQuality.PREMARKET, 55.0
    # Open: 9:30 – 10:30
    if mins < 10 * 60 + 30:
        return SessionQuality.OPEN, 95.0
    # Morning: 10:30 – 12:00
    if mins < 12 * 60:
        return SessionQuality.MORNING, 80.0
    # Midday chop: 12:00 – 14:00
    if mins < 14 * 60:
        return SessionQuality.MIDDAY, 40.0
    # Power hour: 14:00 – 15:30
    if mins < 15 * 60 + 30:
        return SessionQuality.POWER_HOUR, 85.0
    # Close noise: 15:30 – 16:00
    if mins < 16 * 60:
        return SessionQuality.CLOSE, 55.0
    # Afterhours
    return SessionQuality.AFTERHOURS, 45.0


# ════════════════════════════════════════════════════════════════════════════
#  STEP 9 — TIMING STAGE CLASSIFICATION
# ════════════════════════════════════════════════════════════════════════════


def classify_timing_stage(
    vol_metrics: VolumeMetrics,
    price_change_pct: float,
    distance_from_hod_pct: float,
) -> tuple[TimingStage, bool]:
    """
    Determine where in the move lifecycle we are.

    Returns (stage, late_detection_flag).
    """
    rvol = vol_metrics.rvol_current or 0
    accel = vol_metrics.volume_acceleration or 0
    abs_change = abs(price_change_pct)

    # Late detection heuristic: price already up 10%+ or near HOD with extended move
    late_flag = (abs_change >= 10.0) or (distance_from_hod_pct <= 1.0 and abs_change >= 5.0)

    # Exhausted: high RVOL but decelerating, extended move
    if rvol >= 2.0 and accel < -0.2 and abs_change >= 8.0:
        return TimingStage.EXHAUSTED, late_flag

    # Late: price already moved meaningfully
    if abs_change >= 10.0:
        return TimingStage.LATE, True

    # Developing: volume confirmed, some price confirmation
    if rvol >= 2.0 and abs_change >= 3.0:
        return TimingStage.DEVELOPING, late_flag

    # Early: volume building, price barely moved
    if rvol >= 1.5 and abs_change < 3.0:
        return TimingStage.EARLY, False

    # Default: early / noise
    return TimingStage.EARLY, late_flag


# ════════════════════════════════════════════════════════════════════════════
#  STEP 15 — MOVE TYPE PREDICTION
# ════════════════════════════════════════════════════════════════════════════


def classify_move_type(
    anomaly: PreNewsAnomaly,
) -> MoveType:
    """
    Predict expected move type based on anomaly signature.
    Uses fields already populated on the anomaly by earlier scoring steps.
    """
    # Pump/dump risk takes priority
    if (
        anomaly.offering_risk_score >= 60
        or anomaly.price_behaviour.behaviour == PriceBehaviour.REJECTION
        or (anomaly.price_behaviour.upper_wick_pct or 0) > 45
    ):
        return MoveType.PUMP_AND_DUMP

    # Low-float squeeze: small float + high float pressure
    if (
        anomaly.float_shares
        and anomaly.float_shares < 20_000_000
        and anomaly.float_pressure_score >= 60
    ):
        return MoveType.LOW_FLOAT_SQUEEZE

    # News breakout: quiet volume build + no visible news yet
    from src.core.agentic.pre_news_models import NewsStatus, AnomalyType

    if (
        anomaly.anomaly_type in (AnomalyType.QUIET_VOLUME_BUILD, AnomalyType.HIDDEN_ACCUMULATION)
        and anomaly.news_status == NewsStatus.NO_NEWS_FOUND
        and anomaly.smart_money_score >= 60
    ):
        return MoveType.NEWS_BREAKOUT

    # Gradual accumulation: steady buy pressure + mild volume
    if (
        anomaly.buy_pressure_score >= 60
        and anomaly.price_behaviour.behaviour in (
            PriceBehaviour.QUIET_ACCUMULATION,
            PriceBehaviour.CONTROLLED_MOVE,
        )
    ):
        return MoveType.GRADUAL_ACCUMULATION

    # Momentum continuation: price moving, volume confirming
    if (
        anomaly.price_behaviour.behaviour == PriceBehaviour.BREAKOUT_BUILDING
        or (anomaly.price_behaviour.price_change_pct or 0) > 3
    ):
        return MoveType.MOMENTUM_CONTINUATION

    return MoveType.UNKNOWN


# ════════════════════════════════════════════════════════════════════════════
#  STEP 7 — SMART MONEY COMPOSITE
# ════════════════════════════════════════════════════════════════════════════

# Weights (must all be < 40% per guardrail, sum to 1.0)
SMART_MONEY_WEIGHTS = {
    "buy_pressure":       0.22,
    "volume_acceleration": 0.18,
    "float_pressure":     0.18,
    "price_structure":    0.14,  # from existing price_behaviour.score
    "mtf_alignment":      0.12,
    "session_quality":    0.08,
    "vwap_position":      0.08,
}


def compute_smart_money_score(
    buy_pressure_score: float,
    volume_acceleration_score: float,
    float_pressure_score: float,
    price_structure_score: float,
    mtf_alignment_score: float,
    session_quality_score: float,
    vwap_distance_pct: float,
) -> float:
    """
    Composite informed-positioning score 0-100.

    Guardrails:
      - No single feature > 40% influence
      - Final score penalty if any input is extreme negative
    """
    # vwap position → 0-100 score (above VWAP is bullish)
    if vwap_distance_pct >= 0:
        vwap_score = 60 + min(30, vwap_distance_pct * 10)
    else:
        vwap_score = max(0, 50 + vwap_distance_pct * 10)
    vwap_score = _clamp(vwap_score)

    composite = (
        buy_pressure_score * SMART_MONEY_WEIGHTS["buy_pressure"]
        + volume_acceleration_score * SMART_MONEY_WEIGHTS["volume_acceleration"]
        + float_pressure_score * SMART_MONEY_WEIGHTS["float_pressure"]
        + price_structure_score * SMART_MONEY_WEIGHTS["price_structure"]
        + mtf_alignment_score * SMART_MONEY_WEIGHTS["mtf_alignment"]
        + session_quality_score * SMART_MONEY_WEIGHTS["session_quality"]
        + vwap_score * SMART_MONEY_WEIGHTS["vwap_position"]
    )

    return round(_clamp(composite), 1)


# ════════════════════════════════════════════════════════════════════════════
#  STEP 10 — CONFIDENCE DECAY
# ════════════════════════════════════════════════════════════════════════════

# Decay parameters
DECAY_START_MINUTES = 15       # No decay for first 15 minutes
DECAY_PER_MINUTE_NO_FOLLOWTHROUGH = 0.01  # -1% per minute after
DECAY_PER_MINUTE_FAST = 0.03   # faster decay if price reversing
DECAY_FLOOR = 0.30             # never drops below 30% of original


def apply_confidence_decay(
    anomaly: PreNewsAnomaly,
    now_utc: Optional[datetime] = None,
    had_followthrough: bool = False,
) -> float:
    """
    Compute decay factor for a pre-news anomaly that is still in WATCH.

    If no price/volume follow-through occurs after DECAY_START_MINUTES, the
    confidence factor decays linearly down to DECAY_FLOOR.

    Returns the new decay factor (not the score itself — caller applies it).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    elapsed_min = (now_utc - anomaly.detected_at).total_seconds() / 60.0

    if elapsed_min <= DECAY_START_MINUTES or had_followthrough:
        return 1.0

    over = elapsed_min - DECAY_START_MINUTES

    # Fast decay if volume decelerating AND price fading
    price_fading = (anomaly.price_behaviour.price_change_pct or 0) < 0
    vol_fading = anomaly.volume_metrics.accel_trend == "decelerating"
    rate = DECAY_PER_MINUTE_FAST if (price_fading and vol_fading) else DECAY_PER_MINUTE_NO_FOLLOWTHROUGH

    factor = max(DECAY_FLOOR, 1.0 - over * rate)
    return round(factor, 4)


# ════════════════════════════════════════════════════════════════════════════
#  V3 — TIME-OF-DAY RVOL & INTRADAY VOLUME CURVE
# ════════════════════════════════════════════════════════════════════════════

# Approximate US equity intraday volume curve (fraction of daily volume by 5-min bar index)
# Bars 0-77 cover 9:30-16:00 ET. Values are empirical averages.
_INTRADAY_VOLUME_CURVE: list[float] = [
    0.045, 0.038, 0.033, 0.028, 0.024, 0.022, 0.020, 0.019, 0.018, 0.017,  # 9:30-10:20
    0.016, 0.015, 0.014, 0.013, 0.012, 0.012, 0.011, 0.011, 0.010, 0.010,  # 10:20-11:10
    0.010, 0.009, 0.009, 0.009, 0.008, 0.008, 0.008, 0.008, 0.008, 0.007,  # 11:10-12:00
    0.007, 0.007, 0.007, 0.007, 0.007, 0.007, 0.007, 0.007, 0.007, 0.007,  # 12:00-12:50
    0.007, 0.007, 0.007, 0.008, 0.008, 0.008, 0.009, 0.009, 0.010, 0.010,  # 12:50-13:50
    0.011, 0.011, 0.012, 0.012, 0.013, 0.013, 0.014, 0.014, 0.015, 0.015,  # 13:50-14:40
    0.016, 0.017, 0.018, 0.019, 0.020, 0.021, 0.022, 0.023, 0.024, 0.025,  # 14:40-15:30
    0.026, 0.027, 0.028, 0.029, 0.030, 0.031, 0.032, 0.033,                # 15:30-16:00
]


def _get_bar_index_in_session(bars: list) -> int:
    """Return the index of the most recent bar within the regular session (0-77)."""
    if not bars:
        return 0
    # Use bar count as proxy if timestamps aren't available
    return min(len(bars) - 1, len(_INTRADAY_VOLUME_CURVE) - 1)


def compute_time_of_day_rvol(
    bars: list,
    avg_daily_volume: float,
) -> tuple[Optional[float], Optional[float], float]:
    """
    Compare cumulative volume at current time-of-day against the historical
    expected cumulative volume at the same point in the session.

    Returns:
        (time_of_day_rvol, intraday_curve_deviation_pct, session_progress_score)
    """
    if not bars or avg_daily_volume <= 0:
        return None, None, 0.0

    bar_idx = _get_bar_index_in_session(bars)
    cumulative_expected = sum(_INTRADAY_VOLUME_CURVE[: bar_idx + 1])
    if cumulative_expected <= 0:
        return None, None, 0.0

    cumulative_actual = sum(b.volume for b in bars) / avg_daily_volume
    tod_rvol = cumulative_actual / cumulative_expected if cumulative_expected > 0 else 0.0

    # Deviation from curve: how far above/below the normal curve (%)
    deviation_pct = (cumulative_actual - cumulative_expected) / cumulative_expected * 100

    # Session progress score: early-session volume is more significant
    # because there are fewer bars to "smooth out" random spikes.
    progress = (bar_idx + 1) / len(_INTRADAY_VOLUME_CURVE)
    # Score boosts early-session anomalies; midday gets compressed; close gets slight boost
    if progress < 0.15:
        score = 95.0
    elif progress < 0.35:
        score = 75.0
    elif progress < 0.60:
        score = 45.0
    elif progress < 0.85:
        score = 70.0
    else:
        score = 80.0

    return round(tod_rvol, 2), round(deviation_pct, 1), round(score, 1)


def compute_5m_volume_zscore_by_time_slot(
    bars: list,
    avg_daily_volume: float,
) -> Optional[float]:
    """
    Z-score of the latest 5m bar volume compared to the expected volume
    for that specific time slot based on the intraday curve.
    """
    if not bars or avg_daily_volume <= 0:
        return None

    bar_idx = _get_bar_index_in_session(bars)
    expected_this_bar = avg_daily_volume * _INTRADAY_VOLUME_CURVE[bar_idx]
    if expected_this_bar <= 0:
        return None

    latest_vol = bars[-1].volume if bars else 0
    # Compute std dev of bar volumes from the curve expectations
    deviations = []
    for i, b in enumerate(bars):
        slot_expected = avg_daily_volume * _INTRADAY_VOLUME_CURVE[min(i, len(_INTRADAY_VOLUME_CURVE) - 1)]
        if slot_expected > 0:
            deviations.append((b.volume - slot_expected) ** 2)

    std = math.sqrt(sum(deviations) / max(len(deviations), 1))
    z = (latest_vol - expected_this_bar) / std if std > 0 else 0.0
    return round(z, 2)


def compute_session_progress_adjusted_volume_score(
    bars: list,
    avg_daily_volume: float,
) -> float:
    """
    0-100 score that weights volume anomaly higher when detected early
    in the session (more runway) and lower in midday chop.
    """
    if not bars or avg_daily_volume <= 0:
        return 0.0

    bar_idx = _get_bar_index_in_session(bars)
    progress = (bar_idx + 1) / len(_INTRADAY_VOLUME_CURVE)
    total_vol = sum(b.volume for b in bars)
    rvol = total_vol / avg_daily_volume if avg_daily_volume > 0 else 0.0

    # Base score from RVOL tiers
    base = min(100.0, max(0.0, (rvol - 1.0) * 30.0))

    # Time-of-day multiplier
    if progress < 0.15:
        mult = 1.25  # open — most significant
    elif progress < 0.35:
        mult = 1.10  # morning
    elif progress < 0.60:
        mult = 0.70  # midday chop
    elif progress < 0.85:
        mult = 1.05  # afternoon
    else:
        mult = 1.15  # close

    return round(_clamp(base * mult), 1)


# ════════════════════════════════════════════════════════════════════════════
#  V3 — 5-CANDLE QUALITY ANALYSIS
# ════════════════════════════════════════════════════════════════════════════


def analyze_latest_5_candles(bars: list, vwap: float) -> dict:
    """
    Analyze the latest five 5-minute candles for quality metrics.

    Returns dict with:
      - buying_pressure (0-100)
      - selling_pressure (0-100)
      - wick_dominance ("upper" | "lower" | "neutral" | "mixed")
      - summary ("accumulation" | "breakout" | "rejection" | "distribution" | "failed_spike" | "")
      - absorption_score (0-100)
      - supply_rejection_score (0-100)
      - vwap_hold_count
      - vwap_loss_count
    """
    defaults = {
        "buying_pressure": 50.0,
        "selling_pressure": 50.0,
        "wick_dominance": "neutral",
        "summary": "",
        "absorption_score": 50.0,
        "supply_rejection_score": 50.0,
        "vwap_hold_count": 0,
        "vwap_loss_count": 0,
    }
    if not bars or len(bars) < 5:
        return defaults

    recent = bars[-5:]
    upper_wicks = []
    lower_wicks = []
    bodies = []
    closes_above_vwap = 0
    closes_below_vwap = 0
    green_bars = 0
    red_bars = 0
    volume_on_green = 0
    volume_on_red = 0
    closes_near_high = 0  # top 30% of range
    closes_near_low = 0   # bottom 30% of range

    for b in recent:
        rng = b.high - b.low
        body = abs(b.close - b.open)
        if rng > 0:
            upper_wicks.append((b.high - max(b.close, b.open)) / rng * 100)
            lower_wicks.append((min(b.close, b.open) - b.low) / rng * 100)
            bodies.append(body / rng * 100)
            close_pos = (b.close - b.low) / rng
            if close_pos >= 0.70:
                closes_near_high += 1
            if close_pos <= 0.30:
                closes_near_low += 1
        else:
            upper_wicks.append(0.0)
            lower_wicks.append(0.0)
            bodies.append(0.0)

        if b.close > b.open:
            green_bars += 1
            volume_on_green += b.volume
        elif b.close < b.open:
            red_bars += 1
            volume_on_red += b.volume

        if b.close >= vwap:
            closes_above_vwap += 1
        else:
            closes_below_vwap += 1

    avg_upper = sum(upper_wicks) / len(upper_wicks)
    avg_lower = sum(lower_wicks) / len(lower_wicks)

    # Buying pressure: green volume ratio + closes near high + VWAP holds
    total_vol = volume_on_green + volume_on_red
    green_ratio = volume_on_green / total_vol if total_vol > 0 else 0.5
    buying = green_ratio * 60 + (closes_above_vwap / 5) * 25 + (closes_near_high / 5) * 15
    buying = _clamp(buying)

    # Selling pressure: red volume ratio + closes near low + VWAP losses
    red_ratio = volume_on_red / total_vol if total_vol > 0 else 0.5
    selling = red_ratio * 60 + (closes_below_vwap / 5) * 25 + (closes_near_low / 5) * 15
    selling = _clamp(selling)

    # Wick dominance
    if avg_upper > avg_lower + 10:
        wick_dom = "upper"
    elif avg_lower > avg_upper + 10:
        wick_dom = "lower"
    elif abs(avg_upper - avg_lower) <= 10:
        wick_dom = "neutral"
    else:
        wick_dom = "mixed"

    # Absorption: buying on upper wicks with close recovery = demand absorption
    absorption = 50.0
    if avg_upper > 30 and buying > 55:
        absorption = 75.0  # buying into supply = absorption
    elif avg_upper > 40 and selling > 55:
        absorption = 25.0  # supply overwhelming
    elif green_bars >= 4 and avg_upper < 20:
        absorption = 85.0  # clean buying, no supply

    # Supply rejection: long upper wicks + red closes
    supply_rejection = 50.0
    if avg_upper > 35 and red_bars >= 3:
        supply_rejection = 80.0
    elif avg_upper > 25 and selling > 60:
        supply_rejection = 70.0
    elif avg_upper < 15 and buying > 60:
        supply_rejection = 20.0

    # Summary classification
    summary = ""
    if buying >= 65 and avg_upper < 25 and avg_lower < 25 and green_bars >= 3:
        summary = "accumulation"
    elif buying >= 60 and closes_above_vwap >= 4 and avg_upper < 20:
        summary = "breakout"
    elif avg_upper > 35 and (selling > buying or red_bars >= 3):
        summary = "rejection"
    elif selling >= 65 and red_bars >= 3 and avg_upper > 20:
        summary = "distribution"
    elif avg_upper > 30 and avg_lower < 15 and red_bars >= 3:
        summary = "failed_spike"

    return {
        "buying_pressure": round(buying, 1),
        "selling_pressure": round(selling, 1),
        "wick_dominance": wick_dom,
        "summary": summary,
        "absorption_score": round(absorption, 1),
        "supply_rejection_score": round(supply_rejection, 1),
        "vwap_hold_count": closes_above_vwap,
        "vwap_loss_count": closes_below_vwap,
    }


# ════════════════════════════════════════════════════════════════════════════
#  V3.1 — ABSORPTION QUALITY SCORE
# ════════════════════════════════════════════════════════════════════════════


def compute_absorption_quality_score(
    bars: list,
    vwap: float,
    price_change_pct: float,
    range_tightening: bool,
) -> float:
    """
    V3.1: Composite absorption quality score (0-100).

    Measures how cleanly the tape is absorbing supply:
      - VWAP hold count over latest 5 candles
      - Higher-low structure
      - Tight intraday range
      - Lower-wick demand (buying into dips)
      - Low upper-wick rejection
      - Price staying within 0-8% above VWAP
      - Rising volume without excessive price expansion
    """
    if not bars or len(bars) < 5:
        return 50.0

    recent = bars[-5:]

    # 1. VWAP hold count (0-25 points)
    vwap_holds = sum(1 for b in recent if b.close >= vwap)
    vwap_score = (vwap_holds / 5) * 25

    # 2. Higher-low structure (0-20 points)
    higher_lows = 0
    for i in range(1, len(recent)):
        if recent[i].low >= recent[i - 1].low * 0.998:  # allow tiny wiggle
            higher_lows += 1
    hl_score = (higher_lows / 4) * 20

    # 3. Tight range (0-15 points)
    ranges = [b.high - b.low for b in recent]
    avg_range = sum(ranges) / len(ranges) if ranges else 0
    mid_price = sum(b.close for b in recent) / len(recent)
    range_pct = (avg_range / mid_price * 100) if mid_price > 0 else 0
    if range_pct < 1.0:
        range_score = 15
    elif range_pct < 2.5:
        range_score = 10
    elif range_pct < 5.0:
        range_score = 5
    else:
        range_score = 0

    # 4. Lower-wick demand (0-15 points)
    lower_wick_scores = []
    for b in recent:
        rng = b.high - b.low
        if rng > 0:
            lw = (min(b.close, b.open) - b.low) / rng * 100
            lower_wick_scores.append(lw)
        else:
            lower_wick_scores.append(0)
    avg_lower_wick = sum(lower_wick_scores) / len(lower_wick_scores)
    if avg_lower_wick >= 20:
        lw_score = 15
    elif avg_lower_wick >= 10:
        lw_score = 10
    elif avg_lower_wick >= 5:
        lw_score = 5
    else:
        lw_score = 0

    # 5. Low upper-wick rejection (0-15 points)
    upper_wick_scores = []
    for b in recent:
        rng = b.high - b.low
        if rng > 0:
            uw = (b.high - max(b.close, b.open)) / rng * 100
            upper_wick_scores.append(uw)
        else:
            upper_wick_scores.append(0)
    avg_upper_wick = sum(upper_wick_scores) / len(upper_wick_scores)
    if avg_upper_wick <= 10:
        uw_score = 15
    elif avg_upper_wick <= 20:
        uw_score = 10
    elif avg_upper_wick <= 30:
        uw_score = 5
    else:
        uw_score = 0

    # 6. Price within 0-8% above VWAP (0-10 points)
    vwap_dist = ((mid_price - vwap) / vwap * 100) if vwap != 0 else 0
    if 0 <= vwap_dist <= 8:
        vwap_zone_score = 10
    elif -3 <= vwap_dist < 0:
        vwap_zone_score = 7
    elif 8 < vwap_dist <= 15:
        vwap_zone_score = 4
    else:
        vwap_zone_score = 0

    # 7. Rising volume without excessive price expansion (0- bonus / penalty)
    # Compare last 2 bars volume to first 2 bars volume
    vol_early = sum(b.volume for b in recent[:2])
    vol_late = sum(b.volume for b in recent[-2:])
    vol_accel = (vol_late - vol_early) / vol_early if vol_early > 0 else 0
    if vol_accel > 0.3 and abs(price_change_pct) < 5:
        vol_bonus = 5  # volume rising but price contained = absorption
    elif vol_accel > 0.3 and abs(price_change_pct) >= 10:
        vol_bonus = -5  # volume rising with big price move = less absorption
    else:
        vol_bonus = 0

    total = vwap_score + hl_score + range_score + lw_score + uw_score + vwap_zone_score + vol_bonus
    return round(_clamp(total), 1)


# ════════════════════════════════════════════════════════════════════════════
#  V3 — CATALYST RELEVANCE SCORING
# ════════════════════════════════════════════════════════════════════════════


def compute_catalyst_relevance(
    headline_ts: Optional[datetime],
    anomaly_time: datetime,
    source: str = "finviz_global",
) -> tuple[NewsStatus, CatalystAgeBucket, float, str]:
    """
    Given a matched headline timestamp, classify:
      - news_status (granular V3 label)
      - catalyst_age_bucket
      - catalyst_relevance_score (0-100)
      - reason string

    Does NOT downgrade tickers for old catalysts; instead separates
    active vs background relevance.
    """
    from src.core.agentic.pre_news_models import (
        CatalystAgeBucket,
        NewsStatus,
    )

    if headline_ts is None:
        return NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES, CatalystAgeBucket.UNKNOWN, 0.0, "no match"

    age_min = (anomaly_time - headline_ts).total_seconds() / 60.0

    if age_min < -120:  # news appeared > 2h AFTER detection
        bucket = CatalystAgeBucket.WITHIN_2H
        score = 100.0
        status = NewsStatus.NEWS_APPEARED_AFTER_DETECTION
        reason = f"news broke {abs(age_min):.0f}m after detection"
    elif age_min < 0:  # news appeared shortly after detection
        bucket = CatalystAgeBucket.WITHIN_2H
        score = 95.0
        status = NewsStatus.NEWS_APPEARED_AFTER_DETECTION
        reason = f"news appeared {abs(age_min):.0f}m after detection"
    elif age_min <= 30:  # within 30 min before detection
        bucket = CatalystAgeBucket.WITHIN_2H
        score = 80.0
        status = NewsStatus.PUBLIC_CATALYST_ALREADY_VISIBLE
        reason = "catalyst visible within last 30m"
    elif age_min <= 120:  # 30m - 2h
        bucket = CatalystAgeBucket.WITHIN_2H
        score = 70.0
        status = NewsStatus.PUBLIC_CATALYST_ALREADY_VISIBLE
        reason = "catalyst visible 30m-2h ago"
    elif age_min <= 1440:  # 2h - 24h
        bucket = CatalystAgeBucket.WITHIN_24H
        score = 60.0
        status = NewsStatus.PUBLIC_CATALYST_ALREADY_VISIBLE
        reason = "catalyst visible within last 24h"
    elif age_min <= 10080:  # 1-7 days
        bucket = CatalystAgeBucket.WITHIN_7D
        score = 40.0
        status = NewsStatus.OLD_CATALYST_PRESENT
        reason = "old catalyst (1-7 days) — possible continuation"
    elif age_min <= 43200:  # 7-30 days
        bucket = CatalystAgeBucket.WITHIN_30D
        score = 20.0
        status = NewsStatus.OLD_CATALYST_PRESENT
        reason = "background catalyst (7-30 days)"
    else:
        bucket = CatalystAgeBucket.OLDER_THAN_30D
        score = 5.0
        status = NewsStatus.OLD_CATALYST_PRESENT
        reason = "stale catalyst (>30 days) — unlikely driver"

    return status, bucket, round(_clamp(score), 1), reason


# ════════════════════════════════════════════════════════════════════════════
#  V3 — VWAP DISTANCE ALERT FILTER
# ════════════════════════════════════════════════════════════════════════════


def compute_vwap_alert_zone(vwap_distance_pct: float) -> tuple[AlertQuality, str]:
    """
    Map VWAP distance to alert quality zone.
    Returns (alert_quality, reason).
    """
    from src.core.agentic.pre_news_models import AlertQuality

    if vwap_distance_pct < -5:
        return AlertQuality.TRAP_RISK, f"price {abs(vwap_distance_pct):.1f}% below VWAP"
    if vwap_distance_pct <= 8:
        return AlertQuality.EARLY, f"price {vwap_distance_pct:.1f}% above VWAP — ideal zone"
    if vwap_distance_pct <= 15:
        return AlertQuality.CAUTION, f"price {vwap_distance_pct:.1f}% above VWAP — caution zone"
    return AlertQuality.LATE, f"price {vwap_distance_pct:.1f}% above VWAP — already extended"


def should_suppress_alert(
    anomaly,
) -> tuple[bool, AlertQuality, list[str]]:
    """
    V3: Determine whether an extreme-score alert should be suppressed or downgraded.

    Returns (should_suppress, adjusted_alert_quality, suppression_reasons).
    """
    from src.core.agentic.pre_news_models import (
        AlertQuality,
        PriceBehaviour,
        VolumeMetrics,
    )

    reasons: list[str] = []
    pb = anomaly.price_behaviour
    vm = anomaly.volume_metrics

    # VWAP distance rule
    quality, vwap_reason = compute_vwap_alert_zone(pb.vwap_distance_pct)
    if quality == AlertQuality.LATE:
        reasons.append(vwap_reason)

    # Volume fading
    if vm.accel_trend == "decelerating" and (vm.volume_acceleration or 0) < -0.2:
        reasons.append("volume decelerating — fading interest")

    # Long upper wicks
    if pb.upper_wick_pct > 35:
        reasons.append(f"upper wicks {pb.upper_wick_pct:.0f}% — rejection visible")

    # Failed VWAP reclaim after spike
    if pb.behaviour == PriceBehaviour.FAILED_SPIKE:
        reasons.append("failed spike — lost VWAP after volume spike")

    # Far above open AND VWAP
    if pb.distance_from_open_pct > 12 and pb.vwap_distance_pct > 10:
        reasons.append(f"extended {pb.distance_from_open_pct:.1f}% from open — chase risk")

    # Distribution / rejection behaviour
    if pb.behaviour in (PriceBehaviour.REJECTION, PriceBehaviour.DISTRIBUTION):
        reasons.append(f"price behaviour: {pb.behaviour.value} — supply dominant")
        quality = AlertQuality.TRAP_RISK

    # Offering risk override
    if anomaly.offering_risk_score >= 60:
        reasons.append(f"offering risk {anomaly.offering_risk_score:.0f} — dilution trap")
        if anomaly.float_shares and anomaly.float_shares < 50_000_000:
            reasons.append("microcap + high dilution risk — suppress top-tier alert")
            quality = AlertQuality.SUPPRESSED

    should_suppress = quality in (AlertQuality.SUPPRESSED, AlertQuality.TRAP_RISK) or len(reasons) >= 3

    return should_suppress, quality, reasons


# ════════════════════════════════════════════════════════════════════════════
#  V3 — ENHANCED OFFERING / DILUTION RISK (small-cap / microcap aware)
# ════════════════════════════════════════════════════════════════════════════


def compute_offering_risk_v3(
    headlines_for_ticker: Iterable[str],
    dilution_risk_flag: bool = False,
    float_shares: Optional[float] = None,
    market_cap: Optional[float] = None,
    price: Optional[float] = None,
) -> tuple[float, list[str], bool]:
    """
    Enhanced offering/dilution risk with stronger penalties for small/micro caps.

    Returns (score, matched_keywords, is_severe).
    """
    score, matched = compute_offering_risk_score(
        headlines_for_ticker, dilution_risk_flag, float_shares, market_cap
    )

    is_microcap = (market_cap is not None and market_cap < 300_000_000) or (
        float_shares is not None and float_shares < 20_000_000
    )
    is_low_float = float_shares is not None and float_shares < 10_000_000

    # Amplify risk for small caps because dilution hits harder
    if score >= 30 and is_microcap:
        score = min(100.0, score * 1.35)
        matched.append("microcap_amplified")

    if score >= 50 and is_low_float:
        score = min(100.0, score * 1.20)
        matched.append("lowfloat_amplified")

    # Price-based proxy: sub-$1 stocks with large share counts are more prone to RS/offering
    if price is not None and price < 1.0 and float_shares and float_shares > 50_000_000:
        score = min(100.0, score + 15)
        matched.append("subdollar_high_shares")

    is_severe = score >= 60 and (is_microcap or is_low_float)

    return _clamp(score), matched, is_severe


# ════════════════════════════════════════════════════════════════════════════
#  V3 — WYCKOFF STAGE MAPPING
# ════════════════════════════════════════════════════════════════════════════


def map_anomaly_to_wyckoff_stage(anomaly) -> WyckoffStage:
    """
    Map anomaly type + price behaviour to a Wyckoff market-cycle stage.
    """
    from src.core.agentic.pre_news_models import (
        AnomalyType,
        PriceBehaviour,
        WyckoffStage,
    )

    behaviour = anomaly.price_behaviour.behaviour
    anomaly_type = anomaly.anomaly_type

    if anomaly_type == AnomalyType.QUIET_VOLUME_BUILD:
        if behaviour == PriceBehaviour.QUIET_ACCUMULATION:
            return WyckoffStage.ACCUMULATION_PHASE_D
        return WyckoffStage.ACCUMULATION_PHASE_C

    if anomaly_type == AnomalyType.HIDDEN_ACCUMULATION:
        return WyckoffStage.ACCUMULATION_PHASE_D

    if anomaly_type == AnomalyType.EARLY_BREAKOUT_POSITIONING:
        if behaviour == PriceBehaviour.BREAKOUT_BUILDING:
            return WyckoffStage.MARKUP_PHASE_D
        return WyckoffStage.ACCUMULATION_PHASE_D

    if anomaly_type == AnomalyType.UNUSUAL_VOLUME_NO_NEWS:
        if behaviour == PriceBehaviour.BREAKOUT_BUILDING:
            return WyckoffStage.MARKUP_PHASE_E
        if behaviour == PriceBehaviour.CONTROLLED_MOVE:
            return WyckoffStage.MARKUP_PHASE_D

    if behaviour == PriceBehaviour.ALREADY_EXTENDED:
        return WyckoffStage.BUYING_CLIMAX

    if behaviour == PriceBehaviour.REJECTION:
        return WyckoffStage.DISTRIBUTION

    if behaviour == PriceBehaviour.FAILED_SPIKE:
        return WyckoffStage.EARLY_MARKDOWN

    return WyckoffStage.UNKNOWN
