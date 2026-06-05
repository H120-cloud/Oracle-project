"""
Pre-News Volume Anomaly Detector — Core Engine

Detects unusual volume activity BEFORE obvious public news appears.
Reuses existing market data providers, news scrapers, and the Finviz
scanner for universe discovery. Does NOT duplicate existing logic.

Usage:
    detector = PreNewsDetector()
    anomalies = detector.scan()            # full universe scan
    anomaly  = detector.analyze(ticker)    # single-ticker deep analysis
"""

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import yfinance as yf

from src.utils.atomic_json import save_json_file, load_json_file
from src.utils.yfinance_cache import configure_yfinance_cache
from src.core.agentic.pre_news_models import (
    AlertQuality,
    AnomalyType,
    CandidateType,
    CatalystAgeBucket,
    DataQuality,
    MoveType,
    NewsStatus,
    PreNewsAnomaly,
    PreNewsOutcome,
    PreNewsState,
    PriceBehaviour,
    PriceBehaviourDetail,
    SessionQuality,
    SuspicionLevel,
    TimingStage,
    VolumeMetrics,
)
from src.core.agentic.pre_news_baseline import PreNewsBaselineTracker, BaselineType
from src.core.agentic.pre_news_scoring import (
    analyze_latest_5_candles,
    apply_confidence_decay,
    classify_move_type,
    classify_timing_stage,
    compute_buy_pressure_score,
    compute_catalyst_relevance,
    compute_float_pressure_score,
    compute_mtf_alignment,
    compute_offering_risk_score,
    compute_session_progress_adjusted_volume_score,
    compute_session_quality,
    compute_smart_money_score,
    compute_time_of_day_rvol,
    compute_5m_volume_zscore_by_time_slot,
    compute_volume_acceleration,
    map_anomaly_to_wyckoff_stage,
    should_suppress_alert,
    compute_vwap_alert_zone,
    compute_offering_risk_v3,
    compute_absorption_quality_score,
)
from src.core.agentic.pre_news_evaluator import PreNewsEvaluator
from src.core.agentic.pre_news_pattern_memory import PreNewsPatternMemory
from src.core.finviz_news import FinvizNewsScraper
from src.core.prnewswire_news import PRNewswireScraper
from src.core.sharecast_news import SharecastScraper
from src.core.wire_news import WireNewsScraper
from src.core.agentic.finviz_universe import (
    fetch_finviz_top_gainer_tickers,
    fetch_finviz_under2_high_volume_tickers,
    fetch_finviz_most_active_tickers,
    fetch_finviz_most_volatile_tickers,
    fetch_finviz_penny_mover_tickers,
    fetch_finviz_under5_active_tickers,
    fetch_finviz_unusual_volume_tickers,
)
from src.core.stocktitan_news import StockTitanScraper
from src.core.stocktwits_scraper import StockTwitsScraper
from src.config import get_settings
from src.services.market_data import get_market_data_provider
from src.core.agentic.calibration_provider import get_calibration_weights

logger = logging.getLogger(__name__)

configure_yfinance_cache(yf)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
ANOMALIES_FILE = DATA_DIR / "pre_news_anomalies.json"
ALERT_COOLDOWN_MINUTES = 30
SCORE_RESEND_DELTA = 10  # only re-alert if score improves by 10+


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════════
#  VOLUME ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_volume_metrics(
    bars: list, avg_volume: float
) -> VolumeMetrics:
    """
    Compute RVOL, volume acceleration, z-score from intraday bars.
    `bars` are OHLCVBar objects from the market data provider.
    """
    if not bars:
        return VolumeMetrics()

    total_vol = sum(b.volume for b in bars)
    n = len(bars)
    if avg_volume <= 0:
        avg_volume = total_vol

    # Current RVOL (total today vs avg daily)
    rvol_current = total_vol / avg_volume if avg_volume > 0 else 0

    # Recent-window RVOL: last 5 bars vs expected 5-bar fraction of daily
    bars_per_day = max(n, 78)  # ~78 5-min bars in reg session
    expected_per_bar = avg_volume / bars_per_day

    last5 = bars[-5:] if n >= 5 else bars
    vol_5 = sum(b.volume for b in last5)
    rvol_5min = vol_5 / (expected_per_bar * len(last5)) if expected_per_bar > 0 else 0

    last15 = bars[-15:] if n >= 15 else bars
    vol_15 = sum(b.volume for b in last15)
    rvol_15min = vol_15 / (expected_per_bar * len(last15)) if expected_per_bar > 0 else 0

    # Volume acceleration: current 5 bars vs prior 5 bars
    if n >= 10:
        prior5 = bars[-10:-5]
        prior_vol = sum(b.volume for b in prior5)
        accel = (vol_5 - prior_vol) / prior_vol if prior_vol > 0 else 0
    else:
        accel = 0

    # Z-score: how far current bar volume is from mean of all bars
    volumes = [b.volume for b in bars]
    mean_v = sum(volumes) / n
    std_v = math.sqrt(sum((v - mean_v) ** 2 for v in volumes) / max(n - 1, 1))
    z = (volumes[-1] - mean_v) / std_v if std_v > 0 else 0

    # Abnormal volume score 0-100
    # Combine RVOL tiers + z-score + acceleration
    rvol_score = min(100, max(0, (rvol_current - 1) * 25))  # 1x=0, 5x=100
    z_score_comp = min(100, max(0, z * 20))
    accel_comp = min(100, max(0, accel * 50))
    abnormal = rvol_score * 0.5 + z_score_comp * 0.25 + accel_comp * 0.25

    # V2 — acceleration score + trend label + MTF alignment
    accel_ratio, accel_score, accel_trend = compute_volume_acceleration(bars)
    rvol_1m, rvol_5m_mtf, rvol_15m_mtf, mtf_align = compute_mtf_alignment(bars, avg_volume)

    # V3 — time-of-day adjusted volume metrics
    tod_rvol, curve_deviation, session_progress_score = compute_time_of_day_rvol(bars, avg_volume)
    zscore_5m = compute_5m_volume_zscore_by_time_slot(bars, avg_volume)
    session_vol_score = compute_session_progress_adjusted_volume_score(bars, avg_volume)

    return VolumeMetrics(
        rvol_current=round(rvol_current, 2),
        rvol_5min=round(rvol_5min, 2),
        rvol_15min=round(rvol_15min, 2),
        volume_acceleration=round(accel, 4),
        volume_z_score=round(z, 2),
        abnormal_volume_score=round(min(100, max(0, abnormal)), 1),
        avg_volume=avg_volume,
        current_volume=total_vol,
        # V2
        volume_acceleration_score=accel_score,
        mtf_1m_rvol=rvol_1m,
        mtf_5m_rvol=rvol_5m_mtf,
        mtf_15m_rvol=rvol_15m_mtf,
        mtf_alignment_score=mtf_align,
        accel_trend=accel_trend,
        # V3
        time_of_day_rvol=tod_rvol,
        intraday_volume_curve_deviation=curve_deviation,
        current_5m_volume_zscore=zscore_5m,
        session_progress_adjusted_volume_score=session_vol_score,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  PRICE BEHAVIOUR
# ═══════════════════════════════════════════════════════════════════════════════


def _classify_price_behaviour(bars: list, quote: dict) -> PriceBehaviourDetail:
    """Classify price behaviour from intraday bars and live quote."""
    if not bars or len(bars) < 5:
        return PriceBehaviourDetail(behaviour=PriceBehaviour.QUIET_ACCUMULATION, score=30)

    price = float(quote.get("price", 0) or 0)
    prev_close = float(quote.get("previous_close", 0) or 0)
    open_price = float(quote.get("open", 0) or 0)
    day_high = float(quote.get("day_high", 0) or 0)

    if price <= 0 or prev_close <= 0:
        return PriceBehaviourDetail(behaviour=PriceBehaviour.QUIET_ACCUMULATION, score=20)

    change_pct = ((price - prev_close) / prev_close) * 100
    dist_from_hod = ((day_high - price) / day_high) * 100 if day_high > 0 else 0
    dist_from_open = ((price - open_price) / open_price) * 100 if open_price > 0 else 0

    # VWAP from bars
    tp_vol_sum = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars)
    vol_sum = sum(b.volume for b in bars)
    vwap = tp_vol_sum / vol_sum if vol_sum > 0 else price
    vwap_dist = ((price - vwap) / vwap) * 100 if vwap > 0 else 0

    # Wick analysis (last 5 bars)
    recent = bars[-5:]
    upper_wicks = []
    lower_wicks = []
    ranges = []
    for b in recent:
        body = abs(b.close - b.open)
        full = b.high - b.low
        if full > 0:
            upper_wicks.append((b.high - max(b.close, b.open)) / full * 100)
            lower_wicks.append((min(b.close, b.open) - b.low) / full * 100)
            ranges.append(full)

    avg_upper_wick = sum(upper_wicks) / len(upper_wicks) if upper_wicks else 0
    avg_lower_wick = sum(lower_wicks) / len(lower_wicks) if lower_wicks else 0

    # Range tightening: compare last 5 bar range to prior 5
    range_tightening = False
    if len(bars) >= 10:
        prior_ranges = [b.high - b.low for b in bars[-10:-5]]
        avg_prior = sum(prior_ranges) / len(prior_ranges) if prior_ranges else 1
        avg_recent = sum(ranges) / len(ranges) if ranges else 1
        range_tightening = avg_recent < avg_prior * 0.7

    # ── Classification ──
    score = 50.0
    behaviour = PriceBehaviour.QUIET_ACCUMULATION

    if abs(change_pct) > 15:
        behaviour = PriceBehaviour.ALREADY_EXTENDED
        score = 15
    elif avg_upper_wick > 40 and change_pct > 3:
        behaviour = PriceBehaviour.REJECTION
        score = 20
    elif change_pct < -5 and avg_lower_wick > 30:
        behaviour = PriceBehaviour.FAILED_SPIKE
        score = 15
    elif range_tightening and abs(change_pct) < 3 and vwap_dist > -1:
        behaviour = PriceBehaviour.QUIET_ACCUMULATION
        score = 85
    elif abs(change_pct) < 5 and vwap_dist > -1 and avg_upper_wick < 25:
        behaviour = PriceBehaviour.CONTROLLED_MOVE
        score = 75
    elif dist_from_hod < 2 and change_pct > 2:
        behaviour = PriceBehaviour.BREAKOUT_BUILDING
        score = 70

    # Bonuses / penalties
    if vwap_dist >= 0:
        score += 5  # above VWAP
    if vwap_dist < -3:
        score -= 15  # well below VWAP
    if avg_upper_wick > 35:
        score -= 10  # rejection wicks
    if range_tightening:
        score += 10  # accumulation pattern

    score = max(0, min(100, score))

    # V3 — analyze latest 5 candles for quality metrics
    candle_analysis = analyze_latest_5_candles(bars, vwap)

    # V3.1 — compute absorption quality score
    absorption_score = compute_absorption_quality_score(
        bars, vwap, change_pct, range_tightening
    )

    return PriceBehaviourDetail(
        behaviour=behaviour,
        price_change_pct=round(change_pct, 2),
        vwap_distance_pct=round(vwap_dist, 2),
        distance_from_hod_pct=round(dist_from_hod, 2),
        distance_from_open_pct=round(dist_from_open, 2),
        upper_wick_pct=round(avg_upper_wick, 1),
        lower_wick_pct=round(avg_lower_wick, 1),
        range_tightening=range_tightening,
        score=round(score, 1),
        # V3
        latest_5candle_buying_pressure=candle_analysis["buying_pressure"],
        latest_5candle_selling_pressure=candle_analysis["selling_pressure"],
        latest_5candle_wick_dominance=candle_analysis["wick_dominance"],
        latest_5candle_summary=candle_analysis["summary"],
        # V3.1
        absorption_quality_score=absorption_score,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  NEWS CHECK
# ═══════════════════════════════════════════════════════════════════════════════


def _news_item_analysis_text(item) -> str:
    """Return headline plus source detail for risk/catalyst analysis."""
    parts = [
        getattr(item, "headline", "") or "",
        getattr(item, "description", "") or "",
        getattr(item, "summary", "") or "",
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _check_news_status(
    ticker: str,
    anomaly_time: datetime,
    news_items: Optional[list] = None,
) -> tuple[NewsStatus, Optional[str], Optional[datetime], float, CatalystAgeBucket, str, str]:
    """
    Check existing news providers for fresh news for this ticker.
    If news_items is provided (pre-fetched batch), uses that; otherwise fetches once.

    Returns:
        (status, headline, timestamp, catalyst_relevance_score, catalyst_age_bucket, reason, source)
    """
    now = datetime.now(timezone.utc)
    cutoff_2h = now - timedelta(hours=2)

    all_items = news_items
    if all_items is None:
        # Fallback: fetch once (used by single-ticker analyze)
        all_items = []
        try:
            scraper = FinvizNewsScraper()
            summary = scraper.fetch_all_sync()
            all_items.extend(summary.news_items + summary.blog_items)
        except Exception as e:
            logger.debug("News check Finviz fetch failed: %s", e)
        try:
            titan = StockTitanScraper()
            titan_summary = titan.fetch_all_sync()
            all_items.extend(titan_summary.news_items)
        except Exception as e:
            logger.debug("News check StockTitan fetch failed: %s", e)
        try:
            prn = PRNewswireScraper()
            prn_summary = prn.fetch_all_sync()
            all_items.extend(prn_summary.news_items)
        except Exception as e:
            logger.debug("News check PRNewswire fetch failed: %s", e)
        try:
            sharecast = SharecastScraper()
            sharecast_summary = sharecast.fetch_all_sync()
            all_items.extend(sharecast_summary.news_items)
        except Exception as e:
            logger.debug("News check Sharecast fetch failed: %s", e)
        try:
            wire = WireNewsScraper()
            wire_summary = wire.fetch_all_sync()
            all_items.extend(wire_summary.news_items)
        except Exception as e:
            logger.debug("News check WireNews fetch failed: %s", e)

    best_headline: Optional[str] = None
    best_ts: Optional[datetime] = None
    best_source = "finviz_global"

    # Tier 1: global feed (most recent, highest confidence)
    for item in all_items:
        if not getattr(item, "tickers", None):
            continue
        if ticker.upper() not in [t.upper() for t in item.tickers]:
            continue
        # Skip items with no parseable timestamp — falling back to `now`
        # would back-date stale headlines as a fresh catalyst, contradicting
        # main.py's news-momentum skip and corrupting NewsStatus/relevance.
        ts = item.timestamp
        if ts is None:
            continue
        if ts >= cutoff_2h:
            if best_ts is None or ts > best_ts:
                best_headline = item.headline
                best_ts = ts
                best_source = getattr(item, "source", "finviz_global")

    if best_headline and best_ts:
        status, bucket, relevance, reason = compute_catalyst_relevance(best_ts, anomaly_time, best_source)
        return status, best_headline, best_ts, relevance, bucket, reason, best_source

    # ── Fallback: per-ticker Finviz quote page ─────────────────────────────
    # The global feed only surfaces recent items. Existing catalysts drive
    # ongoing volume but aren't in `all_items`. Hit the ticker-specific page.
    try:
        scraper = FinvizNewsScraper()
        ticker_items = scraper.fetch_ticker_news_sync(ticker, max_items=15)
        cutoff_recent = now - timedelta(days=60)
        for item in ticker_items:
            # Same rationale as Tier-1: skip undated items rather than
            # fabricate `now`. An undated item appearing in the per-ticker
            # quote page is almost always an editorial entry, not a catalyst.
            ts = item.timestamp
            if ts is None:
                continue
            if ts < cutoff_recent:
                continue
            if best_ts is None or ts > best_ts:
                best_headline = item.headline
                best_ts = ts
                best_source = "finviz_ticker"
    except Exception as exc:
        logger.debug("Per-ticker news fallback failed for %s: %s", ticker, exc)

    if best_headline and best_ts:
        status, bucket, relevance, reason = compute_catalyst_relevance(best_ts, anomaly_time, best_source)
        return status, best_headline, best_ts, relevance, bucket, reason, best_source

    return NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES, None, None, 0.0, CatalystAgeBucket.UNKNOWN, "no match", ""


# ═══════════════════════════════════════════════════════════════════════════════
#  ANOMALY TYPE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════════


def _classify_anomaly_type(
    vol: VolumeMetrics,
    price: PriceBehaviourDetail,
    news: NewsStatus,
    higher_lows: bool = False,
    vwap_holding: bool = False,
    quiet_accumulation_candidate: bool = False,
    early_breakout_candidate: bool = False,
) -> AnomalyType:
    """Classify the anomaly into one of the categories (V3.1 splits discovery paths)."""
    # Pump risk: high volume + wide spread / rejection + no catalyst
    if (
        price.behaviour in (PriceBehaviour.REJECTION, PriceBehaviour.FAILED_SPIKE)
        and vol.abnormal_volume_score > 60
        and news in (NewsStatus.NO_NEWS_FOUND, NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES)
    ):
        return AnomalyType.SUSPICIOUS_PUMP_RISK

    # V3.1: Quiet accumulation candidate → HIDDEN_ACCUMULATION or QUIET_VOLUME_BUILD
    if quiet_accumulation_candidate:
        if price.absorption_quality_score >= 70 and price.range_tightening:
            return AnomalyType.QUIET_VOLUME_BUILD
        return AnomalyType.HIDDEN_ACCUMULATION

    # V3.1: Early breakout candidate → EARLY_BREAKOUT_POSITIONING
    if early_breakout_candidate:
        if price.vwap_distance_pct > 15:
            return AnomalyType.UNUSUAL_VOLUME_NO_NEWS  # will get late downgrade downstream
        return AnomalyType.EARLY_BREAKOUT_POSITIONING

    # Volume before news (news appeared after detection)
    if news in (NewsStatus.NEWS_LAG_CONFIRMED, NewsStatus.NEWS_APPEARED_AFTER_DETECTION):
        return AnomalyType.VOLUME_BEFORE_NEWS

    # Hidden accumulation (classic path)
    if (
        price.behaviour == PriceBehaviour.QUIET_ACCUMULATION
        and price.range_tightening
        and vol.abnormal_volume_score > 40
    ):
        return AnomalyType.HIDDEN_ACCUMULATION

    # Early breakout positioning (classic path)
    if price.behaviour == PriceBehaviour.BREAKOUT_BUILDING:
        return AnomalyType.EARLY_BREAKOUT_POSITIONING

    # Default: unusual volume no news
    return AnomalyType.UNUSUAL_VOLUME_NO_NEWS


# ═══════════════════════════════════════════════════════════════════════════════
#  SUSPICION SCORE
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_suspicion_score(
    vol: VolumeMetrics,
    price: PriceBehaviourDetail,
    news: NewsStatus,
    float_shares: Optional[float],
    market_cap: Optional[float],
    data_quality: DataQuality,
    catalyst_relevance_score: float = 0.0,
) -> float:
    """
    Composite pre-news suspicion score (0-100) — V3 weights.

    Weights:
      time-of-day volume anomaly:  25%
      volume acceleration:         20%
      VWAP / range / quality:      25%
      float rotation + liquidity:  15%
      catalyst visibility confidence: 10%
      data quality:                  5%
    """
    # 1. Time-of-day volume anomaly (0-100) — prefer time_of_day_rvol when available
    tod_rvol = vol.time_of_day_rvol or vol.rvol_current or 0.0
    tod_score = min(100, max(0, (tod_rvol - 1.0) * 30))
    # Blend with session-progress score for robustness
    vol_comp = (tod_score * 0.7) + (vol.session_progress_adjusted_volume_score * 0.3)

    # 2. Volume acceleration (0-100)
    accel = min(100, max(0, vol.volume_acceleration * 50))
    accel_comp = max(vol.volume_acceleration_score, accel)

    # 3. VWAP / range / absorption quality (0-100)
    # Base from price behaviour score, then adjust for VWAP distance and candle quality
    vwap_quality = 50.0
    if price.vwap_distance_pct >= 0 and price.vwap_distance_pct <= 8:
        vwap_quality = 85.0
    elif price.vwap_distance_pct > 8 and price.vwap_distance_pct <= 15:
        vwap_quality = 60.0
    elif price.vwap_distance_pct > 15:
        vwap_quality = 25.0
    elif price.vwap_distance_pct < 0 and price.vwap_distance_pct >= -3:
        vwap_quality = 55.0
    else:
        vwap_quality = 30.0

    candle_boost = 0.0
    if price.latest_5candle_summary == "accumulation":
        candle_boost = 15.0
    elif price.latest_5candle_summary == "breakout":
        candle_boost = 10.0
    elif price.latest_5candle_summary == "rejection":
        candle_boost = -20.0
    elif price.latest_5candle_summary == "distribution":
        candle_boost = -25.0
    elif price.latest_5candle_summary == "failed_spike":
        candle_boost = -20.0

    price_comp = _clamp(price.score * 0.6 + vwap_quality * 0.25 + candle_boost, 0, 100)

    # 4. Float rotation + liquidity (0-100)
    float_comp = 50
    if float_shares:
        if float_shares < 5_000_000:
            float_comp = 90
        elif float_shares < 20_000_000:
            float_comp = 70
        elif float_shares < 100_000_000:
            float_comp = 50
        else:
            float_comp = 30
    elif market_cap:
        if market_cap < 100_000_000:
            float_comp = 80
        elif market_cap < 500_000_000:
            float_comp = 60

    # 5. Catalyst visibility confidence (0-100) — NOT overweighted
    # High relevance = modest boost; no news = neutral (data limitation, not signal)
    if catalyst_relevance_score >= 70:
        catalyst_comp = 80.0
    elif catalyst_relevance_score >= 40:
        catalyst_comp = 60.0
    elif catalyst_relevance_score > 0:
        catalyst_comp = 35.0
    else:
        catalyst_comp = 50.0  # no news found = neutral, not bullish

    # 6. Data quality (0-100)
    dq_map = {
        DataQuality.FULL: 100,
        DataQuality.PARTIAL: 70,
        DataQuality.DEGRADED: 40,
        DataQuality.STALE: 20,
    }
    dq_comp = dq_map.get(data_quality, 50)

    score = (
        vol_comp * 0.25
        + accel_comp * 0.20
        + price_comp * 0.25
        + float_comp * 0.15
        + catalyst_comp * 0.10
        + dq_comp * 0.05
    )
    return round(max(0, min(100, score)), 1)


def _classify_suspicion(score: float) -> SuspicionLevel:
    if score >= 75:
        return SuspicionLevel.EXTREME
    if score >= 60:
        return SuspicionLevel.HIGH
    if score >= 45:
        return SuspicionLevel.WATCH
    return SuspicionLevel.LOW


# ═══════════════════════════════════════════════════════════════════════════════
#  SAFETY CHECKS
# ═══════════════════════════════════════════════════════════════════════════════


def _safety_checks(anomaly: PreNewsAnomaly) -> PreNewsAnomaly:
    """Apply hard reject / downgrade rules (V3: VWAP distance, offering risk, alert quality)."""
    reasons = anomaly.risk_notes or []

    # VWAP distance zones
    vwap_dist = anomaly.price_behaviour.vwap_distance_pct
    if vwap_dist > 15:
        anomaly.pre_news_suspicion_score *= 0.45
        reasons.append(f"Price {vwap_dist:.1f}% above VWAP — late/chase zone")
    elif vwap_dist > 8:
        anomaly.pre_news_suspicion_score *= 0.75
        reasons.append(f"Price {vwap_dist:.1f}% above VWAP — caution zone")
    elif vwap_dist < -5:
        anomaly.pre_news_suspicion_score *= 0.6
        reasons.append("Price well below VWAP")

    # Already extended
    if anomaly.price_behaviour.behaviour == PriceBehaviour.ALREADY_EXTENDED:
        anomaly.pre_news_suspicion_score *= 0.4
        reasons.append("Price already extended — reduced suspicion")

    # Rejection
    if anomaly.price_behaviour.behaviour == PriceBehaviour.REJECTION:
        anomaly.pre_news_suspicion_score *= 0.5
        reasons.append("Strong wick rejection detected")

    # Failed spike
    if anomaly.price_behaviour.behaviour == PriceBehaviour.FAILED_SPIKE:
        anomaly.pre_news_suspicion_score *= 0.3
        reasons.append("Volume spike faded / failed")

    # Very low RVOL despite z-score
    if (anomaly.volume_metrics.rvol_current or 0) < 1.5:
        anomaly.pre_news_suspicion_score *= 0.5
        reasons.append("RVOL below 1.5x — insufficient")

    # Volume fading
    if anomaly.volume_metrics.accel_trend == "decelerating" and (anomaly.volume_metrics.volume_acceleration or 0) < -0.2:
        anomaly.pre_news_suspicion_score *= 0.7
        reasons.append("Volume decelerating — interest fading")

    # V3.1 — late breakout candidate downgrade (breakout + excessive VWAP extension)
    if (
        anomaly.anomaly_type == AnomalyType.EARLY_BREAKOUT_POSITIONING
        and anomaly.price_behaviour.vwap_distance_pct > 10
    ):
        if anomaly.price_behaviour.vwap_distance_pct > 15:
            anomaly.pre_news_suspicion_score *= 0.5
            reasons.append("Early breakout but >15% above VWAP — late chase / buying climax risk")
        else:
            anomaly.pre_news_suspicion_score *= 0.75
            reasons.append("Early breakout >10% above VWAP — caution zone")

    # Offering risk — stronger for small/micro caps (V3 spec #9)
    if anomaly.offering_risk_score >= 60:
        anomaly.pre_news_suspicion_score *= 0.65
        reasons.append(f"Offering/dilution risk elevated ({anomaly.offering_risk_score:.0f}/100)")
        if anomaly.float_shares and anomaly.float_shares < 20_000_000:
            reasons.append("Microcap dilution risk — extra penalty applied")
            anomaly.pre_news_suspicion_score *= 0.85

    anomaly.pre_news_suspicion_score = round(
        max(0, min(100, anomaly.pre_news_suspicion_score)), 1
    )
    anomaly.classification = _classify_suspicion(anomaly.pre_news_suspicion_score)
    anomaly.risk_notes = reasons

    # V3 — compute alert quality and suppression reasons
    should_suppress, alert_quality, suppression_reasons = should_suppress_alert(anomaly)
    anomaly.alert_quality = alert_quality
    anomaly.alert_suppression_reasons = suppression_reasons

    # Disclaimer
    if "Pre-news volume anomaly is NOT confirmation" not in " ".join(reasons):
        reasons.append(
            "Pre-news volume anomaly is NOT confirmation. Wait for technical or catalyst confirmation."
        )

    return anomaly


# ═══════════════════════════════════════════════════════════════════════════════
#  NEXT CONDITION LOGIC
# ═══════════════════════════════════════════════════════════════════════════════


def _set_next_condition(anomaly: PreNewsAnomaly) -> PreNewsAnomaly:
    """Decide what needs to happen next for this anomaly."""
    behaviour = anomaly.price_behaviour.behaviour
    news = anomaly.news_status

    if news == NewsStatus.NO_NEWS_FOUND:
        anomaly.next_condition_needed = "Waiting for catalyst confirmation"
    elif behaviour == PriceBehaviour.BREAKOUT_BUILDING:
        anomaly.next_condition_needed = "Waiting for breakout above range"
    elif behaviour == PriceBehaviour.QUIET_ACCUMULATION:
        anomaly.next_condition_needed = "Waiting for VWAP hold + volume continuation"
    elif news == NewsStatus.NEWS_LAG_CONFIRMED:
        anomaly.next_condition_needed = "News appeared — monitor for follow-through"
    elif (anomaly.volume_metrics.volume_acceleration or 0) < 0:
        anomaly.next_condition_needed = "Avoid if volume fades"
    else:
        anomaly.next_condition_needed = "Waiting for news confirmation"

    return anomaly


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN DETECTOR CLASS
# ═══════════════════════════════════════════════════════════════════════════════


class PreNewsDetector:
    """
    Scans a universe of tickers for pre-news volume anomalies.

    Reuses:
      - Finviz strategic universe discovery (top gainers)
      - get_market_data_provider() for quotes and bars
      - FinvizNewsScraper + StockTitanScraper for news checks
    """

    def __init__(self):
        provider_override = os.getenv("PRE_NEWS_MARKET_DATA_PROVIDER", "").strip().lower()
        if provider_override:
            previous_provider = os.environ.get("MARKET_DATA_PROVIDER")
            os.environ["MARKET_DATA_PROVIDER"] = provider_override
            try:
                self._provider = get_market_data_provider()
            finally:
                if previous_provider is None:
                    os.environ.pop("MARKET_DATA_PROVIDER", None)
                else:
                    os.environ["MARKET_DATA_PROVIDER"] = previous_provider
        else:
            # NOTE: Polygon is intentionally NOT auto-selected for bulk scanning.
            # The free tier allows only 5 requests/minute, which cannot sustain a
            # universe scan of hundreds of tickers (every call 429s). Bulk OHLCV
            # goes through the configured provider (yfinance by default); Polygon's
            # small quota is reserved for the low-volume priority-quote fallback in
            # news_momentum_orchestrator. To force Polygon here, set
            # PRE_NEWS_MARKET_DATA_PROVIDER=polygon explicitly.
            self._provider = get_market_data_provider()
        self._anomalies: dict[str, PreNewsAnomaly] = {}
        self._alert_cooldowns: dict[str, datetime] = {}
        # V2: universe discovery source map populated by _get_universe()
        self._discovery_source_map: dict[str, str] = {}
        # V2: lazy-loaded pattern memory
        self._pattern_memory: Optional[PreNewsPatternMemory] = None
        # V3: evaluation harness
        self._evaluator: Optional[PreNewsEvaluator] = None
        # V3 baseline harness
        self._baseline_tracker: Optional[PreNewsBaselineTracker] = None
        # Reuse news scrapers across scans so the 5-minute cache works
        self._finviz_scraper: Optional[Any] = None
        self._stocktitan_scraper: Optional[Any] = None
        self._prnewswire_scraper: Optional[Any] = None
        self._sharecast_scraper: Optional[Any] = None
        self._wire_scraper: Optional[Any] = None
        # Offline Rocket CatBoost shadow scorer. It logs predictions only and
        # never changes pre-news alert eligibility or Telegram content.
        try:
            from src.core.agentic.rocket_model_shadow import RocketModelShadowScorer
            self._rocket_shadow_scorer = RocketModelShadowScorer()
        except Exception as exc:
            logger.warning("PreNewsDetector: Rocket shadow scorer init failed: %s", exc)
            self._rocket_shadow_scorer = None

        # Historical calibration weights (approved only)
        self._calibration_weights = get_calibration_weights()
        if self._calibration_weights:
            logger.info("PreNewsDetector loaded approved calibration weights v%s", self._calibration_weights.version)
        _ensure_dir()
        self._load_state()

    def _get_baseline_tracker(self) -> PreNewsBaselineTracker:
        if self._baseline_tracker is None:
            self._baseline_tracker = PreNewsBaselineTracker()
        return self._baseline_tracker

    def _get_pattern_memory(self) -> PreNewsPatternMemory:
        """Lazy-load pattern memory from PreNewsLearningEngine outcomes."""
        if self._pattern_memory is not None:
            return self._pattern_memory
        try:
            from src.core.agentic.pre_news_learning import PreNewsLearningEngine
            eng = PreNewsLearningEngine()
            self._pattern_memory = PreNewsPatternMemory(eng.outcomes)
        except Exception as e:
            logger.debug("PreNewsDetector: pattern memory init failed: %s", e)
            self._pattern_memory = PreNewsPatternMemory([])
        return self._pattern_memory

    @property
    def anomalies(self) -> dict[str, PreNewsAnomaly]:
        return self._anomalies

    def _get_evaluator(self) -> PreNewsEvaluator:
        if self._evaluator is None:
            self._evaluator = PreNewsEvaluator()
        return self._evaluator

    # ── Public API ────────────────────────────────────────────────────────

    async def scan(self, min_rvol: float = 2.0) -> list[PreNewsAnomaly]:
        """
        Full universe scan:
        1. Get top gainers + high-volume tickers from Finviz
        2. Batch-fetch news once (avoid N repeated fetches)
        3. For each, compute volume metrics
        4. Classify price behaviour + check news status (cached)
        5. Score and classify
        """
        logger.info("PreNewsDetector: starting scan...")
        universe = self._get_universe()
        logger.info("PreNewsDetector: universe = %d tickers", len(universe))

        # Fetch all news ONCE for the entire scan
        news_items = await self._fetch_news_batch()

        max_concurrent = max(1, int(os.environ.get("PRE_NEWS_MAX_CONCURRENT_ANALYSES", "8") or 8))
        per_ticker_timeout = max(0.5, float(os.environ.get("PRE_NEWS_PER_TICKER_TIMEOUT_SECONDS", "12") or 12))
        scan_budget = max(1.0, float(os.environ.get("PRE_NEWS_SCAN_BUDGET_SECONDS", "180") or 180))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _analyze_one(ticker: str) -> Optional[PreNewsAnomaly]:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            self._analyze_ticker,
                            ticker,
                            min_rvol=min_rvol,
                            news_items=news_items,
                        ),
                        timeout=per_ticker_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.debug("PreNewsDetector timeout %s after %.1fs", ticker, per_ticker_timeout)
                    return None
                except Exception as e:
                    logger.debug("PreNewsDetector skip %s: %s", ticker, e)
                    return None

        tasks = [asyncio.create_task(_analyze_one(ticker)) for ticker in universe]
        done, pending = await asyncio.wait(tasks, timeout=scan_budget)
        for task in pending:
            task.cancel()
        if pending:
            logger.warning("PreNewsDetector: scan budget exhausted; cancelled %d tickers", len(pending))

        results = []
        for task in done:
            try:
                anomaly = task.result()
                if anomaly:
                    results.append(anomaly)
            except Exception as e:
                logger.debug("PreNewsDetector task result failed: %s", e)

        # Upgrade the top flagged anomalies with Polygon extended-hours data.
        # The bulk loop above ran on yfinance (free-tier safe); only the few
        # highest-suspicion names get the accurate Polygon pre/after-hours bars.
        results = self._enrich_top_anomalies_with_polygon(results, news_items=news_items)

        # Sort by suspicion score descending
        results.sort(key=lambda a: a.pre_news_suspicion_score, reverse=True)
        self._persist_state()

        # V3: record evaluation snapshots for new detections
        try:
            ev = self._get_evaluator()
            for anomaly in results:
                ev.record_detection(anomaly, detection_source="scan")
        except Exception as exc:
            logger.debug("PreNewsDetector: evaluator record failed: %s", exc)

        # V3: capture baseline snapshots for non-alerting tickers
        try:
            alerted_tickers = {a.ticker.upper() for a in results}
            non_alerting = [t for t in universe if t.upper() not in alerted_tickers]
            self._capture_baselines(non_alerting, news_items=news_items)
        except Exception as exc:
            logger.debug("PreNewsDetector: baseline capture failed: %s", exc)

        logger.info(
            "PreNewsDetector: %d anomalies detected (HIGH+: %d)",
            len(results),
            sum(1 for a in results if a.classification in (SuspicionLevel.HIGH, SuspicionLevel.EXTREME)),
        )
        self._log_rocket_shadow_predictions(results)
        return results

    def _log_rocket_shadow_predictions(self, anomalies: list[PreNewsAnomaly]) -> None:
        scorer = getattr(self, "_rocket_shadow_scorer", None)
        if scorer is None:
            return
        for anomaly in anomalies:
            try:
                scorer.predict_and_log_candidate(anomaly, source_pipeline="pre_news")
            except Exception as exc:
                logger.debug("PreNewsDetector: Rocket shadow log failed for %s: %s", anomaly.ticker, exc)

    def analyze(self, ticker: str) -> Optional[PreNewsAnomaly]:
        """Deep analysis of a single ticker."""
        try:
            return self._analyze_ticker(ticker, min_rvol=1.5)
        except Exception as e:
            logger.error("PreNewsDetector analyze %s failed: %s", ticker, e)
            return None

    def _get_polygon_provider(self):
        """Lazy Polygon provider for high-fidelity extended-hours enrichment.

        Returns None if no Polygon key is configured. Used only for the small
        set of flagged anomalies — never for the bulk universe scan — so it
        stays within the free-tier 5 req/min quota.
        """
        if getattr(self, "_polygon_provider", "unset") != "unset":
            return self._polygon_provider
        self._polygon_provider = None
        try:
            if get_settings().polygon_api_key:
                from src.services.polygon_provider import PolygonProvider
                self._polygon_provider = PolygonProvider()
        except Exception as exc:
            logger.debug("PreNewsDetector: Polygon enrichment unavailable: %s", exc)
            self._polygon_provider = None
        return self._polygon_provider

    def _enrich_top_anomalies_with_polygon(
        self, results: list[PreNewsAnomaly], news_items: Optional[list] = None
    ) -> list[PreNewsAnomaly]:
        """Re-analyze the top flagged anomalies using Polygon's extended-hours bars.

        The bulk universe scan runs on yfinance, whose pre/after-hours coverage
        is unreliable for small-caps. Here we upgrade only the highest-suspicion
        anomalies with Polygon data (accurate for extended hours) by re-running
        the full analysis with the provider temporarily swapped. Capped via
        PRE_NEWS_POLYGON_ENRICH_LIMIT (default 3) to stay within the 5 req/min
        free-tier quota. If Polygon re-analysis fails or filters a ticker out,
        the original yfinance anomaly is kept.
        """
        polygon = self._get_polygon_provider()
        if polygon is None or not results:
            return results

        try:
            limit = int(os.getenv("PRE_NEWS_POLYGON_ENRICH_LIMIT", "3") or 3)
        except ValueError:
            limit = 3
        if limit <= 0:
            return results

        # Highest-suspicion first — these are the ones worth the quota.
        ranked = sorted(results, key=lambda a: a.pre_news_suspicion_score, reverse=True)
        top = ranked[:limit]

        original_provider = self._provider
        self._provider = polygon
        enriched = 0
        try:
            for anomaly in top:
                try:
                    # min_rvol=0.0: enrich metrics, don't re-apply the entry filter.
                    refined = self._analyze_ticker(
                        anomaly.ticker, min_rvol=0.0, news_items=news_items
                    )
                except Exception as exc:
                    logger.debug("Polygon enrichment failed for %s: %s", anomaly.ticker, exc)
                    refined = None
                if refined is None:
                    continue
                for i, a in enumerate(results):
                    if a.ticker == anomaly.ticker:
                        results[i] = refined
                        break
                enriched += 1
        finally:
            self._provider = original_provider

        if enriched:
            logger.info(
                "PreNewsDetector: enriched %d/%d top anomalies with Polygon extended-hours data",
                enriched, len(top),
            )
        return results

    async def update_news_status(self) -> list[PreNewsAnomaly]:
        """
        Re-check news for all tracked anomalies (post-news matching).
        If news appeared after anomaly, mark as VOLUME_BEFORE_NEWS.
        Returns list of anomalies that just had news confirmed (for downstream
        notification — caller should mark `news_confirmed_alert_sent` on send).
        """
        updated = 0
        newly_confirmed: list[PreNewsAnomaly] = []
        news_items = await self._fetch_news_batch()
        for ticker, anomaly in list(self._anomalies.items()):
            if anomaly.state != PreNewsState.PRE_NEWS_WATCH:
                continue
            if anomaly.news_status not in (NewsStatus.NO_NEWS_FOUND, NewsStatus.UNKNOWN_NEWS_STATUS, NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES):
                continue

            news_status, headline, ts, relevance, bucket, reason, source = _check_news_status(
                ticker, anomaly.detected_at, news_items=news_items
            )
            if news_status != anomaly.news_status:
                anomaly.news_status = news_status
                anomaly.first_news_headline = headline
                anomaly.first_news_timestamp = ts
                anomaly.matched_headline = headline
                anomaly.matched_headline_time = ts
                anomaly.catalyst_relevance_score = relevance
                anomaly.catalyst_age_bucket = bucket
                anomaly.catalyst_source = source
                if ts and anomaly.detected_at:
                    anomaly.time_gap_minutes = round(
                        (ts - anomaly.detected_at).total_seconds() / 60, 1
                    )
                if news_status in (NewsStatus.NEWS_LAG_CONFIRMED, NewsStatus.NEWS_APPEARED_AFTER_DETECTION):
                    anomaly.anomaly_type = AnomalyType.VOLUME_BEFORE_NEWS
                    anomaly.state = PreNewsState.CATALYST_CONFIRMED
                    # Stamp confirmation time + seed post-news high bucket
                    if anomaly.news_confirmed_at is None:
                        anomaly.news_confirmed_at = datetime.now(timezone.utc)
                    if anomaly.high_price_post_news is None:
                        anomaly.high_price_post_news = anomaly.price
                    if not anomaly.news_confirmed_alert_sent:
                        newly_confirmed.append(anomaly)
                anomaly.updated_at = datetime.now(timezone.utc)
                updated += 1

        if updated > 0:
            self._persist_state()
            logger.info("PreNewsDetector: updated news status for %d anomalies", updated)

        # V3: propagate news confirmation to evaluator snapshots
        try:
            ev = self._get_evaluator()
            for anomaly in newly_confirmed:
                ev.update_news_confirmation(anomaly)
        except Exception as exc:
            logger.debug("PreNewsDetector: evaluator news update failed: %s", exc)

        if newly_confirmed:
            self._log_rocket_shadow_predictions(newly_confirmed)

        return newly_confirmed

    def mark_news_confirmed_alert_sent(self, ticker: str):
        """Record that a news-confirmation Telegram alert was sent."""
        anomaly = self._anomalies.get(ticker)
        if anomaly:
            anomaly.news_confirmed_alert_sent = True
            anomaly.news_confirmed_alert_at = datetime.now(timezone.utc)
            self._persist_state()

    def refresh_tracked_prices(self) -> int:
        """
        For every active (non-expired) anomaly, fetch the current price/day-high
        and update the appropriate high-price bucket (pre vs post news). Also
        backfills `news_confirmed_at` and seeds `high_price_post_news` for any
        anomaly already in NEWS_LAG_CONFIRMED that is missing this tracking.

        This covers anomalies that dropped out of the current Finviz universe
        — their _analyze_ticker pipeline no longer runs, but we still want
        to watch their price extremes.
        """
        updated = 0
        shadow_updated: list[PreNewsAnomaly] = []
        for ticker, anomaly in list(self._anomalies.items()):
            if anomaly.state == PreNewsState.EXPIRED:
                continue

            # Backfill confirmation timestamp for already-confirmed anomalies
            backfilled = False
            if anomaly.news_status == NewsStatus.NEWS_LAG_CONFIRMED:
                if anomaly.news_confirmed_at is None:
                    anomaly.news_confirmed_at = (
                        anomaly.first_news_timestamp or anomaly.updated_at
                    )
                    backfilled = True
                if anomaly.high_price_post_news is None:
                    anomaly.high_price_post_news = anomaly.price
                    backfilled = True

            # Fetch current price
            try:
                quote = self._provider.get_live_quote(ticker)
                price = float(quote.get("price", 0) or 0)
                if price <= 0:
                    if backfilled:
                        updated += 1
                        shadow_updated.append(anomaly)
                    continue
                try:
                    day_high = float(quote.get("day_high", 0) or 0)
                except Exception:
                    day_high = 0.0
                observed_high = max(day_high, price)
            except Exception as exc:
                logger.debug("refresh_tracked_prices %s quote failed: %s", ticker, exc)
                if backfilled:
                    updated += 1
                    shadow_updated.append(anomaly)
                continue

            # Update live price + the correct high bucket
            anomaly.price = price
            if anomaly.news_status == NewsStatus.NEWS_LAG_CONFIRMED:
                prev = anomaly.high_price_post_news or 0
                if observed_high > prev:
                    anomaly.high_price_post_news = round(observed_high, 4)
            else:
                prev = anomaly.high_price_pre_news or 0
                if observed_high > prev:
                    anomaly.high_price_pre_news = round(observed_high, 4)

            anomaly.updated_at = datetime.now(timezone.utc)
            updated += 1
            shadow_updated.append(anomaly)

        if updated > 0:
            self._persist_state()
            logger.info("PreNewsDetector: refreshed prices on %d anomalies", updated)
            self._log_rocket_shadow_predictions(shadow_updated)

        # V3: update forward prices in evaluator snapshots
        try:
            ev = self._get_evaluator()
            for ticker, anomaly in list(self._anomalies.items()):
                if anomaly.state == PreNewsState.EXPIRED:
                    continue
                try:
                    quote = self._provider.get_live_quote(ticker)
                    price = float(quote.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    vwap = None
                    try:
                        vwap = float(quote.get("vwap", 0) or 0)
                    except Exception:
                        pass
                    ev.update_forward_for_ticker(
                        ticker, price, datetime.now(timezone.utc), vwap=vwap if vwap and vwap > 0 else None
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("PreNewsDetector: evaluator forward update failed: %s", exc)

        # V3: update forward prices in baseline snapshots
        try:
            bt = self._get_baseline_tracker()
            for ticker in list(self._anomalies.keys()):
                try:
                    quote = self._provider.get_live_quote(ticker)
                    price = float(quote.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    vwap = None
                    try:
                        vwap = float(quote.get("vwap", 0) or 0)
                    except Exception:
                        pass
                    bt.update_forward_for_ticker(
                        ticker, price, datetime.now(timezone.utc), vwap=vwap if vwap and vwap > 0 else None
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("PreNewsDetector: baseline forward update failed: %s", exc)

        return updated

    def expire_stale(self, max_age_hours: int = 6):
        """Expire anomalies older than max_age_hours that are still in WATCH."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        for ticker, anomaly in list(self._anomalies.items()):
            if anomaly.state == PreNewsState.PRE_NEWS_WATCH and anomaly.detected_at < cutoff:
                anomaly.state = PreNewsState.EXPIRED
        self._persist_state()

    def explain_alert_decision(
        self,
        anomaly: PreNewsAnomaly,
        *,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Return the exact Pre-News Telegram gate decision and block reasons."""
        reasons: list[str] = []
        if anomaly.pre_news_suspicion_score < 75:
            reasons.append("score_below_75")

        # V3 — suppress if alert quality is poor
        if anomaly.alert_quality in ("suppressed", "trap_risk"):
            reasons.append(f"alert_quality_{anomaly.alert_quality}")
        if anomaly.alert_quality == "late" and anomaly.pre_news_suspicion_score < 85:
            reasons.append("late_quality_score_below_85")

        # Already alerted and score hasn't improved enough
        if anomaly.alert_sent:
            if anomaly.pre_news_suspicion_score < anomaly.last_alert_score + SCORE_RESEND_DELTA:
                reasons.append("already_alerted_score_delta_too_small")

        # In-memory cooldown for same-scan duplicates
        now = now or datetime.now(timezone.utc)
        last = self._alert_cooldowns.get(anomaly.ticker)
        if last and (now - last).total_seconds() < ALERT_COOLDOWN_MINUTES * 60:
            reasons.append("cooldown_active")

        # Suppress if price extended or volume fading
        if anomaly.price_behaviour.behaviour == PriceBehaviour.ALREADY_EXTENDED:
            reasons.append("already_extended")
        if (anomaly.volume_metrics.volume_acceleration or 0) < -0.3:
            reasons.append("volume_fading")

        # V3 — suppress if too many suppression reasons
        if len(anomaly.alert_suppression_reasons) >= 3:
            reasons.append("too_many_suppression_reasons")

        return {
            "should_alert": not reasons,
            "reasons": reasons,
        }

    def should_alert(self, anomaly: PreNewsAnomaly) -> bool:
        """Check if we should send a Telegram alert for this anomaly (V3)."""
        return bool(self.explain_alert_decision(anomaly)["should_alert"])

    def format_alert(self, anomaly: PreNewsAnomaly) -> str:
        """Format Telegram alert message (V2: informed-positioning fields)."""
        vm = anomaly.volume_metrics
        pb = anomaly.price_behaviour

        # Header — emphasize QUIET_VOLUME_BUILD when present
        if anomaly.anomaly_type == AnomalyType.QUIET_VOLUME_BUILD:
            header = "\U0001f48e [PRE-NEWS V2 — QUIET VOLUME BUILD]"
        elif anomaly.late_detection_flag:
            header = "\u26a0\ufe0f [PRE-NEWS V2 — LATE DETECTION]"
        else:
            header = "\u26a0\ufe0f [PRE-NEWS V2 VOLUME ANOMALY]"

        lines = [
            header,
            "",
            f"Ticker: {anomaly.ticker}",
            f"Price: ${anomaly.price:.2f}",
            f"RVOL: {vm.rvol_current or 0:.1f}x  (accel {vm.accel_trend})",
            f"Price Change: {pb.price_change_pct:+.1f}%",
            f"VWAP Distance: {pb.vwap_distance_pct:+.1f}%",
        ]
        if anomaly.float_shares:
            lines.append(f"Float: {anomaly.float_shares/1e6:.1f}M")
        if anomaly.market_cap:
            lines.append(f"Mkt Cap: ${anomaly.market_cap/1e6:.0f}M")

        # V2 scoring block
        lines += [
            "",
            f"Smart Money: {anomaly.smart_money_score:.0f}/100",
            f"Suspicion:   {anomaly.pre_news_suspicion_score:.0f}/100 [{anomaly.classification.value.upper()}]",
            f"Buy Pressure: {anomaly.buy_pressure_score:.0f}/100",
            f"Float Pressure: {anomaly.float_pressure_score:.0f}/100",
            "",
            f"Anomaly Type: {anomaly.anomaly_type.value}",
            f"Timing Stage: {anomaly.timing_stage.value}",
            f"Move Type:    {anomaly.move_type_prediction.value}",
            f"Session:      {anomaly.session.value}",
        ]

        if anomaly.late_detection_flag:
            lines.append("\u26a0\ufe0f LATE DETECTION — move may already be extended")
        if anomaly.offering_risk_score >= 50:
            lines.append(f"\u26a0\ufe0f Offering/dilution risk: {anomaly.offering_risk_score:.0f}/100")

        # Pattern memory (only surface if meaningful signal)
        w_sim = anomaly.winner_similarity_score
        l_sim = anomaly.loser_similarity_score
        if w_sim != 50.0 or l_sim != 50.0:
            if w_sim > l_sim + 10:
                lines.append(f"\u2728 Pattern: {w_sim:.0f}% similar to past winners")
            elif l_sim > w_sim + 10:
                lines.append(f"\u26a0\ufe0f Pattern: {l_sim:.0f}% similar to past losers")

        lines += [
            f"News: {anomaly.news_status.value}",
            f"Price Behaviour: {pb.behaviour.value}",
            "",
            "Why flagged:",
        ]
        for r in anomaly.reasons[:6]:
            lines.append(f"  \u2022 {r}")

        next_cond = anomaly.next_condition_needed or "Await catalyst or price confirmation"
        lines += [
            "",
            f"Next: {next_cond}",
            "",
            "Risk:",
            "  \u2022 May be random volume",
            "  \u2022 May be pump — wait for confirmation",
        ]
        return "\n".join(lines)

    def mark_alert_sent(self, ticker: str):
        """Record that alert was sent for cooldown tracking."""
        now = datetime.now(timezone.utc)
        self._alert_cooldowns[ticker] = now
        if ticker in self._anomalies:
            a = self._anomalies[ticker]
            a.alert_sent = True
            a.alert_sent_at = now
            a.last_alert_score = a.pre_news_suspicion_score
        self._persist_state()

    # ── V2: Confidence Decay (Step 10) ────────────────────────────────────

    def apply_confidence_decay_all(self, max_age_hours: int = 6) -> int:
        """
        Apply confidence decay to all PRE_NEWS_WATCH anomalies without follow-through.
        Returns number of anomalies whose factor was updated.

        Called by a scheduler (e.g. every 5 minutes) or during `update_news_status`.
        """
        now = datetime.now(timezone.utc)
        updated = 0
        for ticker, anomaly in list(self._anomalies.items()):
            if anomaly.state != PreNewsState.PRE_NEWS_WATCH:
                continue
            age_h = (now - anomaly.detected_at).total_seconds() / 3600
            if age_h > max_age_hours:
                continue

            # Treat NEWS_LAG_CONFIRMED as follow-through; otherwise check price/vol trend
            had_ft = (
                anomaly.news_status == NewsStatus.NEWS_LAG_CONFIRMED
                or (anomaly.price_behaviour.price_change_pct or 0) >= 3
                or anomaly.volume_metrics.accel_trend == "accelerating"
            )
            new_factor = apply_confidence_decay(anomaly, now_utc=now, had_followthrough=had_ft)
            if abs(new_factor - anomaly.confidence_decay_factor) > 0.001:
                anomaly.confidence_decay_factor = new_factor
                # Apply to suspicion score (softly — never below 20)
                decayed = anomaly.pre_news_suspicion_score * new_factor
                anomaly.pre_news_suspicion_score = round(max(20.0, decayed), 1)
                anomaly.classification = _classify_suspicion(anomaly.pre_news_suspicion_score)
                anomaly.updated_at = now
                updated += 1

        if updated > 0:
            self._persist_state()
            logger.info("PreNewsDetector: applied confidence decay to %d anomalies", updated)
        return updated

    # ── V2: Agentic Integration (Step 16) ──────────────────────────────────

    def get_agentic_handoff_candidates(self, min_suspicion: float = 70.0) -> list[PreNewsAnomaly]:
        """
        Return high-quality pre-news anomalies ready for handoff to Agentic pipeline.

        Criteria:
          - Suspicion >= min_suspicion
          - Not a pump risk / rejection / failed spike
          - Not late-detection flagged
          - Offering risk < 60
          - Smart money score >= 55 (meaningful informed-positioning signal)
          - State still PRE_NEWS_WATCH

        The AgenticOrchestrator can poll this list and convert to AgenticCandidate
        via its own catalyst pipeline.
        """
        eligible = []
        for ticker, a in self._anomalies.items():
            if a.state != PreNewsState.PRE_NEWS_WATCH:
                continue
            if a.pre_news_suspicion_score < min_suspicion:
                continue
            if a.anomaly_type == AnomalyType.SUSPICIOUS_PUMP_RISK:
                continue
            if a.price_behaviour.behaviour in (PriceBehaviour.REJECTION, PriceBehaviour.FAILED_SPIKE, PriceBehaviour.ALREADY_EXTENDED):
                continue
            if a.late_detection_flag:
                continue
            if a.offering_risk_score >= 60:
                continue
            if a.smart_money_score < 55:
                continue
            eligible.append(a)

        # Best first
        eligible.sort(key=lambda x: x.smart_money_score, reverse=True)
        return eligible

    # ── Baseline Capture ──────────────────────────────────────────────────

    def _capture_baselines(self, tickers: list[str], news_items: Optional[list] = None):
        """
        For non-alerting tickers, do lightweight analysis and record
        baseline snapshots for A/B comparison.
        """
        if not tickers:
            return
        tracker = self._get_baseline_tracker()
        now = datetime.now(timezone.utc)
        session_date = now.strftime("%Y-%m-%d")

        # Random same-universe: pick ~20% of non-alerting tickers
        random_sample = set(random.sample(tickers, min(max(1, len(tickers) // 5), len(tickers))))

        recorded = 0
        for ticker in tickers:
            try:
                quote = self._provider.get_live_quote(ticker)
                price = float(quote.get("price", 0) or 0)
                if price <= 0:
                    continue

                # Lightweight bars fetch
                bars = self._provider.get_ohlcv(ticker, period="1d", interval="5m", prepost=True)
                if not bars or len(bars) < 3:
                    continue

                # Compute minimal metrics
                avg_volume = 0.0
                try:
                    fi = yf.Ticker(ticker).fast_info
                    avg_volume = float(getattr(fi, "ten_day_average_volume", 0) or 0)
                except Exception:
                    pass

                vol_metrics = _compute_volume_metrics(bars, avg_volume)
                price_detail = _classify_price_behaviour(bars, quote)

                # Check news
                news_status, _, _, _, catalyst_bucket, _, _ = _check_news_status(
                    ticker, now, news_items=news_items
                )
                news_status_str = news_status.value if news_status else ""
                catalyst_bucket_str = catalyst_bucket.value if catalyst_bucket else ""

                # Determine baseline types this ticker qualifies for
                rvol = vol_metrics.time_of_day_rvol or vol_metrics.rvol_current or 0.0
                vwap_dist = price_detail.vwap_distance_pct or 0.0
                price_change = price_detail.price_change_pct or 0.0
                vol_accel = vol_metrics.volume_acceleration_score or 0.0
                upper_wick = price_detail.upper_wick_pct or 0.0
                candle_summary = price_detail.latest_5candle_summary or ""
                buy_p = compute_buy_pressure_score(bars)
                sell_p = 100.0 - buy_p
                absorption = price_detail.absorption_quality_score or 0.0
                offering_risk = 0.0
                try:
                    ticker_headlines = []
                    for item in (news_items or []):
                        try:
                            if ticker.upper() in [t.upper() for t in getattr(item, "tickers", [])]:
                                ticker_headlines.append(_news_item_analysis_text(item))
                        except Exception:
                            continue
                    offering_risk, _, _ = compute_offering_risk_v3(
                        ticker_headlines, dilution_risk_flag=False,
                        float_shares=None, market_cap=float(quote.get("market_cap", 0) or 0), price=price,
                    )
                except Exception:
                    pass

                mcap = float(quote.get("market_cap", 0) or 0)
                float_shares = None
                try:
                    shares = float(getattr(yf.Ticker(ticker).fast_info, "shares", 0) or 0)
                    float_shares = shares if shares > 0 else None
                except Exception:
                    pass

                discovery_source = self._discovery_source_map.get(ticker.upper(), "")

                # Determine which baseline types to record
                baseline_types = []

                # 1. TOP_GAINERS_BASELINE — from finviz_gainers source
                if discovery_source == "finviz_gainers":
                    baseline_types.append(BaselineType.TOP_GAINERS)

                # 2. HIGH_RVOL_BASELINE — raw RVOL >= 2.0, no V3 quality filters
                if rvol >= 2.0:
                    baseline_types.append(BaselineType.HIGH_RVOL)

                # 3. BREAKOUT_ONLY_BASELINE — breaking highs, no absorption filtering
                if candle_summary == "breakout" and vwap_dist <= 10 and price_change > 2.0:
                    baseline_types.append(BaselineType.BREAKOUT_ONLY)

                # 4. RANDOM_SAME_UNIVERSE_BASELINE
                if ticker in random_sample:
                    baseline_types.append(BaselineType.RANDOM_SAME_UNIVERSE)

                # 5. QUIET_VOLUME_BASELINE — abnormal volume + modest price change, no full V3 rules
                if vol_accel >= 50 and abs(price_change) < 5.0 and rvol >= 1.5:
                    baseline_types.append(BaselineType.QUIET_VOLUME)

                # Record one snapshot per baseline type
                for bl_type in baseline_types:
                    tracker.record_baseline(
                        baseline_type=bl_type,
                        ticker=ticker,
                        scan_time=now,
                        session_date=session_date,
                        scan_source=discovery_source,
                        price_at_scan=price,
                        open_price=float(quote.get("open", 0) or 0) or None,
                        previous_close=float(quote.get("previous_close", 0) or 0) or None,
                        day_high_at_scan=float(quote.get("day_high", 0) or 0) or None,
                        day_low_at_scan=float(quote.get("day_low", 0) or 0) or None,
                        vwap_at_scan=float(quote.get("vwap", 0) or 0) or None,
                        vwap_distance=vwap_dist,
                        price_change_pct=price_change,
                        price_change_from_open_pct=price_detail.price_change_from_open_pct or 0.0,
                        current_volume=vol_metrics.current_volume,
                        average_volume=avg_volume if avg_volume > 0 else None,
                        relative_volume=vol_metrics.rvol_current,
                        time_of_day_rvol=rvol,
                        intraday_volume_curve_deviation=vol_metrics.intraday_volume_curve_deviation,
                        current_5m_volume_zscore=vol_metrics.current_5m_volume_zscore,
                        volume_acceleration_score=vol_accel,
                        latest_5candle_summary=candle_summary,
                        buying_pressure=buy_p,
                        selling_pressure=sell_p,
                        upper_wick_pct=upper_wick,
                        absorption_quality_score=absorption,
                        news_status=news_status_str,
                        catalyst_age_bucket=catalyst_bucket_str,
                        offering_risk_score=offering_risk,
                        market_cap=mcap if mcap > 0 else None,
                        float_shares=float_shares,
                    )
                    recorded += 1

            except Exception as exc:
                logger.debug("PreNewsDetector baseline skip %s: %s", ticker, exc)

        if recorded > 0:
            logger.info("PreNewsDetector: recorded %d baseline snapshots", recorded)

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_universe(self) -> list[str]:
        """
        V2 expanded universe discovery — tagged by source so we can attribute
        per-source performance in learning.

        Sources:
          1. Finviz top gainers
          2. Finviz under $2 with high volume
          3. StockTwits trending
          4. Watchlist (existing user-tracked tickers)
          5. Unusual volume with low price move (<5%) — the sweet spot for QUIET_VOLUME_BUILD
        """
        tickers_sources: dict[str, str] = {}

        def _tag(t: str, source: str):
            if not t:
                return
            t = t.upper()
            if t not in tickers_sources:
                tickers_sources[t] = source

        # 1. Finviz top gainers
        try:
            for ticker in fetch_finviz_top_gainer_tickers(max_results=40, validate=False):
                _tag(ticker, "finviz_gainers")
        except Exception as e:
            logger.warning("PreNewsDetector: Finviz gainers failed: %s", e)

        # 2. Finviz under $2 (small-cap high volume)
        try:
            for ticker in fetch_finviz_under2_high_volume_tickers(max_results=30, validate=False):
                _tag(ticker, "finviz_under2")
        except Exception as e:
            logger.debug("PreNewsDetector: Finviz under-$2 failed: %s", e)

        # 3. Broader Finviz momentum screens.
        #
        # Top-gainers alone can miss no-news runners that appear first as
        # "most active", "unusual volume", or "most volatile" before they
        # reach the headline/top-gainer path. Keep caps modest; bounded
        # concurrency and the global scan budget still control runtime.
        extra_finviz_sources = [
            ("finviz_active", fetch_finviz_most_active_tickers, int(os.environ.get("PRE_NEWS_FINVIZ_ACTIVE_LIMIT", "30") or 30)),
            ("finviz_unusual_volume", fetch_finviz_unusual_volume_tickers, int(os.environ.get("PRE_NEWS_FINVIZ_UNUSUAL_VOLUME_LIMIT", "30") or 30)),
            ("finviz_most_volatile", fetch_finviz_most_volatile_tickers, int(os.environ.get("PRE_NEWS_FINVIZ_MOST_VOLATILE_LIMIT", "30") or 30)),
            ("finviz_under5_active", fetch_finviz_under5_active_tickers, int(os.environ.get("PRE_NEWS_FINVIZ_UNDER5_ACTIVE_LIMIT", "30") or 30)),
            ("finviz_penny_movers", fetch_finviz_penny_mover_tickers, int(os.environ.get("PRE_NEWS_FINVIZ_PENNY_LIMIT", "30") or 30)),
        ]
        for source_name, fetcher, limit in extra_finviz_sources:
            try:
                for ticker in fetcher(max_results=limit, validate=False):
                    _tag(ticker, source_name)
            except Exception as e:
                logger.debug("PreNewsDetector: %s failed: %s", source_name, e)

        # 4. StockTwits trending (social-driven discovery)
        try:
            st = StockTwitsScraper()
            for t in st.get_trending_tickers(limit=20):
                _tag(t, "stocktwits_trending")
        except Exception as e:
            logger.debug("PreNewsDetector: StockTwits trending failed: %s", e)

        # 5. PRNewswire public-company releases (fresh catalysts even when Finviz is blocked)
        try:
            if self._prnewswire_scraper is None:
                self._prnewswire_scraper = PRNewswireScraper()
            summary = self._prnewswire_scraper.fetch_all_sync()
            max_age_hours = float(os.environ.get("PRNEWSWIRE_UNIVERSE_MAX_AGE_HOURS", "6") or 6)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            for item in summary.news_items:
                if getattr(item, "sentiment", "") == "bearish":
                    continue
                ts = getattr(item, "timestamp", None)
                if ts is not None:
                    ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                    if ts_utc < cutoff:
                        continue
                for ticker in getattr(item, "tickers", []) or []:
                    _tag(ticker, "prnewswire_public_company")
        except Exception as e:
            logger.debug("PreNewsDetector: PRNewswire universe fetch failed: %s", e)

        # 6. Sharecast press notes (supplemental; only high-confidence tickered items)
        try:
            if self._sharecast_scraper is None:
                self._sharecast_scraper = SharecastScraper()
            summary = self._sharecast_scraper.fetch_all_sync()
            max_age_hours = float(os.environ.get("SHARECAST_UNIVERSE_MAX_AGE_HOURS", "24") or 24)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            for item in summary.news_items:
                if getattr(item, "sentiment", "") == "bearish":
                    continue
                ts = getattr(item, "timestamp", None)
                if ts is not None:
                    ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                    if ts_utc < cutoff:
                        continue
                for ticker in getattr(item, "tickers", []) or []:
                    _tag(ticker, "sharecast_press_note")
        except Exception as e:
            logger.debug("PreNewsDetector: Sharecast universe fetch failed: %s", e)

        # 7. Supplemental wires (GlobeNewswire, BusinessWire, Accesswire, Newsfile)
        try:
            if self._wire_scraper is None:
                self._wire_scraper = WireNewsScraper()
            summary = self._wire_scraper.fetch_all_sync()
            max_age_hours = float(os.environ.get("WIRE_UNIVERSE_MAX_AGE_HOURS", "6") or 6)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            for item in summary.news_items:
                if getattr(item, "sentiment", "") == "bearish":
                    continue
                ts = getattr(item, "timestamp", None)
                if ts is not None:
                    ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                    if ts_utc < cutoff:
                        continue
                source = getattr(item, "source", "wire") or "wire"
                for ticker in getattr(item, "tickers", []) or []:
                    _tag(ticker, f"{source.lower()}_wire")
        except Exception as e:
            logger.debug("PreNewsDetector: WireNews universe fetch failed: %s", e)

        # 8. Manual universe integration (tickers the user is already tracking)
        try:
            from src.core.agentic.manual_universe import get_manual_universe_tickers
            for ticker in get_manual_universe_tickers():
                _tag(ticker, "manual_universe")
        except Exception as e:
            logger.debug("PreNewsDetector: manual universe fetch failed: %s", e)

        # Store source map for downstream per-ticker tagging
        self._discovery_source_map = tickers_sources
        return list(tickers_sources.keys())

    async def _fetch_news_batch(self) -> list:
        """Fetch all news once for the scan to avoid N repeated requests."""
        # Lazy-init scrapers once
        if self._finviz_scraper is None:
            from src.core.finviz_news import FinvizNewsScraper
            self._finviz_scraper = FinvizNewsScraper()
        if self._stocktitan_scraper is None:
            from src.core.stocktitan_news import StockTitanScraper
            self._stocktitan_scraper = StockTitanScraper()
        if self._prnewswire_scraper is None:
            self._prnewswire_scraper = PRNewswireScraper()
        if self._sharecast_scraper is None:
            self._sharecast_scraper = SharecastScraper()
        if self._wire_scraper is None:
            self._wire_scraper = WireNewsScraper()

        items: list = []
        try:
            summary = await self._finviz_scraper.fetch_all()
            items.extend(summary.news_items + summary.blog_items)
        except Exception as e:
            logger.debug("News batch fetch Finviz failed: %s", e)
        try:
            titan_summary = await self._stocktitan_scraper.fetch_all()
            items.extend(titan_summary.news_items)
        except Exception as e:
            logger.debug("News batch fetch StockTitan failed: %s", e)
        try:
            prn_summary = await self._prnewswire_scraper.fetch_all()
            items.extend(prn_summary.news_items)
        except Exception as e:
            logger.debug("News batch fetch PRNewswire failed: %s", e)
        try:
            sharecast_summary = await self._sharecast_scraper.fetch_all()
            items.extend(sharecast_summary.news_items)
        except Exception as e:
            logger.debug("News batch fetch Sharecast failed: %s", e)
        try:
            wire_summary = await self._wire_scraper.fetch_all()
            items.extend(wire_summary.news_items)
        except Exception as e:
            logger.debug("News batch fetch WireNews failed: %s", e)

        # Deduplicate across sources
        try:
            from src.core.agentic.news_momentum_utils import deduplicate_news_items
            items = deduplicate_news_items(items)
        except Exception as e:
            logger.debug("News batch deduplication failed: %s", e)
        return items

    def _analyze_ticker(self, ticker: str, min_rvol: float = 2.0, news_items: Optional[list] = None) -> Optional[PreNewsAnomaly]:
        """Analyze a single ticker for pre-news volume anomaly."""
        now = datetime.now(timezone.utc)

        # 1. Get quote
        quote = self._provider.get_live_quote(ticker)
        price = float(quote.get("price", 0) or 0)
        if price <= 0:
            return None

        # 2. Get avg volume + float
        avg_volume = 0.0
        float_shares = None
        market_cap = float(quote.get("market_cap", 0) or 0)
        try:
            fi = yf.Ticker(ticker).fast_info
            avg_volume = float(getattr(fi, "ten_day_average_volume", 0) or 0)
            if market_cap == 0:
                market_cap = float(getattr(fi, "market_cap", 0) or 0)
            shares = float(getattr(fi, "shares", 0) or 0)
            float_shares = shares if shares > 0 else None
        except Exception as exc:
            logger.debug("Failed to fetch fast_info for %s: %s", ticker, exc)
        if avg_volume <= 0:
            avg_volume = float(
                quote.get("average_volume", 0)
                or quote.get("avg_volume", 0)
                or quote.get("volume", 0)
                or 0
            )

        # 3. Get intraday bars
        bars = self._provider.get_ohlcv(ticker, period="1d", interval="5m", prepost=True)

        # Determine data quality
        data_quality = DataQuality.FULL
        if not bars or len(bars) < 5:
            data_quality = DataQuality.DEGRADED
        elif avg_volume <= 0:
            data_quality = DataQuality.PARTIAL

        # 4. Compute volume metrics
        vol_metrics = _compute_volume_metrics(bars, avg_volume)

        # Quick filter: skip if RVOL below threshold
        if (vol_metrics.rvol_current or 0) < min_rvol and vol_metrics.abnormal_volume_score < 40:
            return None

        # 5. Classify price behaviour
        price_detail = _classify_price_behaviour(bars, quote)

        # 6. Check news (pass pre-fetched batch if available)
        news_status, news_headline, news_ts, catalyst_relevance, catalyst_bucket, catalyst_reason, catalyst_source = _check_news_status(
            ticker, now, news_items=news_items
        )

        # V3.1 — split quiet candidate into two discovery paths
        quiet_accumulation_candidate = False
        early_breakout_candidate = False

        base_criteria = (
            (vol_metrics.time_of_day_rvol or vol_metrics.rvol_current or 0) >= 1.5
            and price_detail.vwap_distance_pct >= -1.0
            and price_detail.upper_wick_pct < 30
            and vol_metrics.volume_acceleration_score >= 50
            and news_status in (NewsStatus.NO_NEWS_FOUND, NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES)
        )

        if base_criteria:
            if (
                abs(price_detail.price_change_pct) < 5.0
                and price_detail.range_tightening
                and price_detail.latest_5candle_summary in ("accumulation", "neutral", "")
                and price_detail.absorption_quality_score >= 55
            ):
                quiet_accumulation_candidate = True

            if (
                price_detail.latest_5candle_summary == "breakout"
                and price_detail.behaviour == PriceBehaviour.BREAKOUT_BUILDING
                and price_detail.vwap_distance_pct <= 10
            ):
                early_breakout_candidate = True

        # 7. Compute suspicion score (V3 weights)
        suspicion = _compute_suspicion_score(
            vol_metrics, price_detail, news_status, float_shares, market_cap, data_quality,
            catalyst_relevance_score=catalyst_relevance,
        )

        # ─── V2 SCORING PIPELINE (informed-positioning signals) ────────────
        vwap_holding = price_detail.vwap_distance_pct >= -0.5

        # Step 4 — buy pressure (green vs red vol, close position, uptick dominance)
        buy_pressure = compute_buy_pressure_score(bars)

        # Step 5 — float-adjusted volume
        float_pressure = compute_float_pressure_score(
            vol_metrics.current_volume, float_shares
        )

        # Step 6 — offering / dilution risk (V3 enhanced for small/micro caps)
        ticker_headlines: list[str] = []
        for item in (news_items or []):
            try:
                if ticker.upper() in [t.upper() for t in getattr(item, "tickers", [])]:
                    ticker_headlines.append(_news_item_analysis_text(item))
            except Exception:
                continue
        offering_risk, offering_hits, dilution_severe = compute_offering_risk_v3(
            ticker_headlines, dilution_risk_flag=False,
            float_shares=float_shares, market_cap=market_cap, price=price,
        )

        # Step 11 — session quality (time-of-day liquidity/noise)
        session_enum, session_score = compute_session_quality(now)

        # Step 9 — timing stage classification
        timing_stage, late_flag = classify_timing_stage(
            vol_metrics,
            price_detail.price_change_pct,
            price_detail.distance_from_hod_pct,
        )

        # Step 7 — smart money composite
        smart_money = compute_smart_money_score(
            buy_pressure_score=buy_pressure,
            volume_acceleration_score=vol_metrics.volume_acceleration_score,
            float_pressure_score=float_pressure,
            price_structure_score=price_detail.score,
            mtf_alignment_score=vol_metrics.mtf_alignment_score,
            session_quality_score=session_score,
            vwap_distance_pct=price_detail.vwap_distance_pct,
        )

        # 8. Classify anomaly type (V3.1 — passes both candidate flags)
        anomaly_type = _classify_anomaly_type(
            vol_metrics, price_detail, news_status,
            higher_lows=price_detail.range_tightening,
            vwap_holding=vwap_holding,
            quiet_accumulation_candidate=quiet_accumulation_candidate,
            early_breakout_candidate=early_breakout_candidate,
        )

        # 9. Build reasons
        reasons = []
        if (vol_metrics.rvol_current or 0) >= 2:
            reasons.append(f"RVOL elevated at {vol_metrics.rvol_current:.1f}x")
        if vol_metrics.volume_acceleration > 0.3:
            reasons.append(f"Volume acceleration +{vol_metrics.volume_acceleration:.0%}")
        if news_status in (NewsStatus.NO_NEWS_FOUND, NewsStatus.NO_PUBLIC_NEWS_FOUND_IN_SOURCES):
            reasons.append("No visible public news yet")
        if news_status in (NewsStatus.NEWS_LAG_CONFIRMED, NewsStatus.NEWS_APPEARED_AFTER_DETECTION):
            reasons.append("Volume preceded news")
        if quiet_accumulation_candidate:
            reasons.append("Quiet accumulation candidate — volume rising with minimal price expansion and absorption quality")
        if early_breakout_candidate:
            reasons.append("Early breakout candidate — price pressing highs with VWAP support")
        if catalyst_relevance > 0 and catalyst_relevance < 40:
            reasons.append(f"Old catalyst present ({catalyst_bucket.value.replace('_', ' ')}) — background only")
        if price_detail.range_tightening:
            reasons.append("Price range tightening — potential accumulation")
        if price_detail.behaviour == PriceBehaviour.BREAKOUT_BUILDING:
            reasons.append("Price building near resistance")
        if price_detail.vwap_distance_pct >= 0:
            reasons.append("Price holding above VWAP")

        # 9. Enrich with StockTwits social data
        st_data = {}
        try:
            st = StockTwitsScraper()
            st_info = st.fetch_ticker_data(ticker)
            st_data = {
                "stocktwits_trending": st_info.is_trending,
                "stocktwits_rank": st_info.trending_rank,
                "stocktwits_watchers": st_info.watchlist_count,
                "stocktwits_message_volume": st_info.message_volume_24h,
                "stocktwits_sentiment_bullish_pct": st_info.sentiment_bullish_pct,
            }
            if st_info.is_trending:
                reasons.append(f"Trending on StockTwits (rank #{st_info.trending_rank})")
            if st_info.sentiment_bullish_pct is not None and st_info.sentiment_bullish_pct > 70:
                reasons.append(f"Bullish social sentiment ({st_info.sentiment_bullish_pct:.0f}%)")
        except Exception:
            pass  # StockTwits enrichment is optional

        # 9b. Apply historical calibration (if approved)
        cw = self._calibration_weights
        if cw and cw.pre_news_suspicion_w != 1.0:
            suspicion = round(min(100, suspicion * cw.pre_news_suspicion_w), 1)
            if cw.pre_news_suspicion_w > 1.0:
                reasons.append(f"Suspicion boosted by calibration (+{round((cw.pre_news_suspicion_w - 1) * 100)}%)")
            else:
                reasons.append(f"Suspicion dampened by calibration (-{round((1 - cw.pre_news_suspicion_w) * 100)}%)")

        # ─── V2 reasons — informed-positioning context ──────────────────────
        if smart_money >= 70:
            reasons.append(f"Smart-money footprint strong ({smart_money:.0f}/100)")
        if buy_pressure >= 65:
            reasons.append(f"Buy pressure dominant ({buy_pressure:.0f}/100)")
        if float_pressure >= 70:
            reasons.append(f"Float rotation heavy ({float_pressure:.0f}/100)")
        if vol_metrics.mtf_alignment_score >= 75:
            reasons.append("Multi-timeframe volume aligned (1m, 5m, 15m)")
        if offering_risk >= 50:
            reasons.append(f"⚠ Offering/dilution risk elevated ({offering_risk:.0f}/100)")
        if late_flag:
            reasons.append("⚠ Late-detection: move may already be extended")
        if anomaly_type == AnomalyType.QUIET_VOLUME_BUILD:
            reasons.append("💎 Quiet volume build — early accumulation signature")

        # 10. Build anomaly
        time_gap = None
        if news_ts and now:
            time_gap = round((news_ts - now).total_seconds() / 60, 1)

        discovery_src = (self._discovery_source_map or {}).get(ticker.upper(), "unknown")

        # V3.1 — determine candidate type and tape read
        if quiet_accumulation_candidate:
            candidate_type = CandidateType.QUIET_ACCUMULATION
        elif early_breakout_candidate:
            candidate_type = CandidateType.EARLY_BREAKOUT
        elif price_detail.vwap_distance_pct > 15:
            candidate_type = CandidateType.LATE_CHASE
        elif price_detail.behaviour in (PriceBehaviour.REJECTION, PriceBehaviour.DISTRIBUTION, PriceBehaviour.FAILED_SPIKE):
            candidate_type = CandidateType.TRAP_RISK
        else:
            candidate_type = CandidateType.GENERAL

        # V3.1 — one-sentence tape read
        tape_parts = []
        if vol_metrics.volume_acceleration > 0.2:
            tape_parts.append("volume rising")
        elif vol_metrics.volume_acceleration < -0.1:
            tape_parts.append("volume fading")
        else:
            tape_parts.append("volume stable")

        if price_detail.behaviour == PriceBehaviour.QUIET_ACCUMULATION:
            tape_parts.append("quiet accumulation")
        elif price_detail.behaviour == PriceBehaviour.BREAKOUT_BUILDING:
            tape_parts.append("pressing highs")
        elif price_detail.behaviour == PriceBehaviour.REJECTION:
            tape_parts.append("rejection at highs")
        elif price_detail.behaviour == PriceBehaviour.ALREADY_EXTENDED:
            tape_parts.append("already extended")
        else:
            tape_parts.append("controlled move")

        if price_detail.vwap_distance_pct >= 0:
            tape_parts.append("holding VWAP")
        else:
            tape_parts.append("below VWAP")

        if quiet_accumulation_candidate:
            tape_read = f"Tape shows {tape_parts[0]} with {tape_parts[1]} {tape_parts[2]} — absorption quality {price_detail.absorption_quality_score:.0f}/100 suggests quiet demand."
        elif early_breakout_candidate:
            tape_read = f"Tape shows {tape_parts[0]} with {tape_parts[1]} {tape_parts[2]} — breakout structure with early momentum."
        else:
            tape_read = f"Tape shows {tape_parts[0]} with {tape_parts[1]} {tape_parts[2]}."

        # V3 — compute alert quality from VWAP distance before building anomaly
        initial_alert_quality, _ = compute_vwap_alert_zone(price_detail.vwap_distance_pct)

        anomaly = PreNewsAnomaly(
            ticker=ticker,
            price=price,
            detected_at=now,
            updated_at=now,
            volume_metrics=vol_metrics,
            volume_anomaly_score=vol_metrics.abnormal_volume_score,
            price_behaviour=price_detail,
            news_status=news_status,
            first_news_timestamp=news_ts,
            first_news_headline=news_headline,
            time_gap_minutes=time_gap,
            anomaly_type=anomaly_type,
            pre_news_suspicion_score=suspicion,
            classification=_classify_suspicion(suspicion),
            float_shares=float_shares,
            market_cap=market_cap,
            reasons=reasons,
            data_quality_state=data_quality,
            # V2 fields
            smart_money_score=smart_money,
            buy_pressure_score=buy_pressure,
            float_pressure_score=float_pressure,
            offering_risk_score=offering_risk,
            session_quality_score=session_score,
            timing_stage=timing_stage,
            late_detection_flag=late_flag,
            session=session_enum,
            discovery_source=discovery_src,
            # V3 fields
            catalyst_age_minutes=(now - news_ts).total_seconds() / 60.0 if news_ts else None,
            catalyst_age_bucket=catalyst_bucket,
            catalyst_relevance_score=catalyst_relevance,
            catalyst_source=catalyst_source,
            matched_headline=news_headline,
            matched_headline_time=news_ts,
            alert_quality=initial_alert_quality,
            detection_price=price,
            # V3.1 fields
            candidate_type=candidate_type,
            tape_read=tape_read,
            **st_data,
        )

        # V2 — move type classification (uses anomaly fields we just set)
        anomaly.move_type_prediction = classify_move_type(anomaly)

        # V2 — pattern memory similarity (only active if ≥100 outcomes)
        try:
            pm = self._get_pattern_memory()
            w_sim, l_sim = pm.score(anomaly)
            anomaly.winner_similarity_score = w_sim
            anomaly.loser_similarity_score = l_sim
            if pm.active and w_sim > l_sim + 10:
                reasons.append(f"Pattern memory: {w_sim:.0f}% similar to past winners")
            elif pm.active and l_sim > w_sim + 10:
                reasons.append(f"⚠ Pattern memory: {l_sim:.0f}% similar to past losers")
        except Exception as e:
            logger.debug("Pattern memory scoring failed: %s", e)

        # V3 — Wyckoff stage mapping
        anomaly.wyckoff_stage = map_anomaly_to_wyckoff_stage(anomaly)

        # V2 — apply offering-risk downgrade (spec Step 6)
        if offering_risk >= 60:
            anomaly.pre_news_suspicion_score = round(anomaly.pre_news_suspicion_score * 0.65, 1)
            anomaly.classification = _classify_suspicion(anomaly.pre_news_suspicion_score)

        # V2 — late-detection downgrade (spec Step 9)
        if late_flag:
            anomaly.pre_news_suspicion_score = round(anomaly.pre_news_suspicion_score * 0.75, 1)
            anomaly.classification = _classify_suspicion(anomaly.pre_news_suspicion_score)

        # 11. Safety checks (V3 enhanced)
        anomaly = _safety_checks(anomaly)

        # 12. Next condition
        anomaly = _set_next_condition(anomaly)

        # 13. Preserve alert history from previous scan
        old = self._anomalies.get(ticker.upper())
        if old and old.alert_sent:
            if anomaly.pre_news_suspicion_score < old.last_alert_score + SCORE_RESEND_DELTA:
                anomaly.alert_sent = True
                anomaly.last_alert_score = old.last_alert_score
                anomaly.alert_sent_at = old.alert_sent_at

        # Preserve news-confirmation alert state + confirmation timestamp
        if old:
            anomaly.news_confirmed_alert_sent = old.news_confirmed_alert_sent
            anomaly.news_confirmed_alert_at = old.news_confirmed_alert_at
            anomaly.news_confirmed_at = old.news_confirmed_at

        # 13b. Track high-price buckets (pre vs post news confirmation).
        # Use the day high from the quote if available; fall back to current price.
        try:
            day_high = float(quote.get("day_high", 0) or 0)
        except Exception:
            day_high = 0.0
        observed_high = max(day_high, price)

        pre_high = old.high_price_pre_news if old else None
        post_high = old.high_price_post_news if old else None

        news_confirmed_now = anomaly.news_status in (
            NewsStatus.NEWS_LAG_CONFIRMED, NewsStatus.NEWS_APPEARED_AFTER_DETECTION
        )
        if news_confirmed_now:
            # If this is the first scan seeing the confirmed state, stamp it.
            if anomaly.news_confirmed_at is None:
                anomaly.news_confirmed_at = now
            post_high = max(post_high or 0, observed_high)
            # Freeze pre_high (never overwrite it once news is confirmed)
        else:
            pre_high = max(pre_high or 0, observed_high)

        anomaly.high_price_pre_news = round(pre_high, 4) if pre_high else None
        anomaly.high_price_post_news = round(post_high, 4) if post_high else None

        # 14. Store
        self._anomalies[ticker] = anomaly

        return anomaly

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist_state(self):
        _ensure_dir()
        data = {
            ticker: anomaly.model_dump(mode="json")
            for ticker, anomaly in self._anomalies.items()
        }
        save_json_file(ANOMALIES_FILE, data)

    def _load_state(self):
        raw = load_json_file(ANOMALIES_FILE, default=None)
        if raw is None:
            return
        for ticker, d in raw.items():
            try:
                self._anomalies[ticker] = PreNewsAnomaly(**d)
            except Exception:
                pass
        logger.info("PreNewsDetector: loaded %d persisted anomalies", len(self._anomalies))

    def load_state(self):
        """Public alias for loading persisted state."""
        self._load_state()
