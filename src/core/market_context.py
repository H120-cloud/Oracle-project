"""
Market Context Engine — Part 3

Tracks overall market direction using SPY (S&P 500) and QQQ (NASDAQ):
- BULL_MARKET / BEAR_MARKET / SIDEWAYS
- Sector strength detection
- Market momentum scoring
- Confidence/sizing adjustments based on regime
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class MarketCondition(str, Enum):
    BULL_MARKET = "BULL_MARKET"
    BEAR_MARKET = "BEAR_MARKET"
    SIDEWAYS = "SIDEWAYS"


class SectorStrength(str, Enum):
    STRONG = "STRONG"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"


@dataclass
class SectorData:
    name: str
    etf: str               # Sector ETF ticker
    change_1d: float = 0.0
    change_5d: float = 0.0
    strength: SectorStrength = SectorStrength.NEUTRAL
    relative_strength: float = 0.0  # vs SPY


@dataclass
class MarketContext:
    """Full market context output."""
    # Overall market
    condition: MarketCondition = MarketCondition.SIDEWAYS
    condition_confidence: float = 50.0   # 0–100

    # Index data
    spy_price: float = 0.0
    spy_change_1d: float = 0.0
    spy_change_5d: float = 0.0
    spy_above_ema20: bool = False
    spy_above_ema50: bool = False
    spy_above_ema200: bool = False

    qqq_price: float = 0.0
    qqq_change_1d: float = 0.0
    qqq_change_5d: float = 0.0
    qqq_above_ema20: bool = False
    qqq_above_ema50: bool = False

    # Momentum
    market_momentum: float = 0.0        # -100 to +100
    breadth_ratio: float = 0.5          # Advance/decline approx

    # Sectors
    sectors: List[SectorData] = field(default_factory=list)
    strongest_sector: Optional[str] = None
    weakest_sector: Optional[str] = None

    # Trading rules output
    allow_aggressive: bool = False
    confidence_modifier: float = 1.0     # 0.5–1.3
    position_size_modifier: float = 1.0  # 0.5–1.3
    max_concurrent_trades: int = 5

    # Timestamp
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "condition": self.condition.value,
            "condition_confidence": self.condition_confidence,
            "spy_price": self.spy_price,
            "spy_change_1d": self.spy_change_1d,
            "spy_change_5d": self.spy_change_5d,
            "qqq_price": self.qqq_price,
            "qqq_change_1d": self.qqq_change_1d,
            "qqq_change_5d": self.qqq_change_5d,
            "market_momentum": self.market_momentum,
            "allow_aggressive": self.allow_aggressive,
            "confidence_modifier": self.confidence_modifier,
            "position_size_modifier": self.position_size_modifier,
            "strongest_sector": self.strongest_sector,
            "weakest_sector": self.weakest_sector,
        }


# Sector ETFs to track
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Industrials": "XLI",
    "Communication": "XLC",
    "AI / Semiconductors": "SMH",
    "Biotech": "XBI",
    "Clean Energy": "ICLN",
}


class MarketContextEngine:
    """
    Analyzes broad market conditions and provides trading rule adjustments.
    """

    def __init__(self, provider=None):
        """
        Args:
            provider: IMarketDataProvider instance for fetching bars.
        """
        self.provider = provider  # Will be injected

    def analyze(self) -> MarketContext:
        """Run full market context analysis."""
        if not self.provider:
            logger.warning("No market data provider — returning default context")
            return MarketContext(updated_at=datetime.now(timezone.utc))

        ctx = MarketContext(updated_at=datetime.now(timezone.utc))

        # Analyze SPY
        spy_bars = self.provider.get_ohlcv("SPY", period="1mo", interval="1d")
        if spy_bars and len(spy_bars) >= 10:
            self._analyze_index(spy_bars, ctx, "spy")

        # Analyze QQQ
        qqq_bars = self.provider.get_ohlcv("QQQ", period="1mo", interval="1d")
        if qqq_bars and len(qqq_bars) >= 10:
            self._analyze_index(qqq_bars, ctx, "qqq")

        # Classify market condition
        ctx.condition, ctx.condition_confidence = self._classify_condition(ctx)

        # Analyze sectors
        ctx.sectors = self._analyze_sectors(spy_bars)
        if ctx.sectors:
            strongest = max(ctx.sectors, key=lambda s: s.relative_strength)
            weakest = min(ctx.sectors, key=lambda s: s.relative_strength)
            ctx.strongest_sector = strongest.name
            ctx.weakest_sector = weakest.name

        # Compute momentum
        ctx.market_momentum = self._compute_momentum(spy_bars, qqq_bars)

        # Apply trading rules
        self._apply_trading_rules(ctx)

        logger.info(
            "MarketContext: %s (conf=%.0f%%) momentum=%.1f agg=%s conf_mod=%.2f",
            ctx.condition.value, ctx.condition_confidence,
            ctx.market_momentum, ctx.allow_aggressive, ctx.confidence_modifier,
        )

        return ctx

    def _analyze_index(self, bars: list, ctx: MarketContext, prefix: str):
        """Analyze a single index (SPY or QQQ)."""
        closes = np.array([float(b.close) for b in bars])
        price = closes[-1]

        # EMAs
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, min(50, len(closes) - 1))

        # Changes
        change_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0
        change_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0

        if prefix == "spy":
            ctx.spy_price = round(price, 2)
            ctx.spy_change_1d = round(change_1d, 2)
            ctx.spy_change_5d = round(change_5d, 2)
            ctx.spy_above_ema20 = price > ema20
            ctx.spy_above_ema50 = price > ema50
            if len(closes) >= 200:
                ema200 = self._ema(closes, 200)
                ctx.spy_above_ema200 = price > ema200
        elif prefix == "qqq":
            ctx.qqq_price = round(price, 2)
            ctx.qqq_change_1d = round(change_1d, 2)
            ctx.qqq_change_5d = round(change_5d, 2)
            ctx.qqq_above_ema20 = price > ema20
            ctx.qqq_above_ema50 = price > ema50

    def _classify_condition(self, ctx: MarketContext) -> tuple:
        """Classify as BULL, BEAR, or SIDEWAYS."""
        bull_points = 0
        bear_points = 0

        # SPY signals
        if ctx.spy_above_ema20: bull_points += 2
        else: bear_points += 2
        if ctx.spy_above_ema50: bull_points += 2
        else: bear_points += 2
        if ctx.spy_above_ema200: bull_points += 3
        else: bear_points += 3

        if ctx.spy_change_5d > 1: bull_points += 2
        elif ctx.spy_change_5d < -1: bear_points += 2
        if ctx.spy_change_1d > 0.5: bull_points += 1
        elif ctx.spy_change_1d < -0.5: bear_points += 1

        # QQQ signals
        if ctx.qqq_above_ema20: bull_points += 1
        else: bear_points += 1
        if ctx.qqq_above_ema50: bull_points += 1
        else: bear_points += 1

        if ctx.qqq_change_5d > 1: bull_points += 1
        elif ctx.qqq_change_5d < -1: bear_points += 1

        total = bull_points + bear_points
        if total == 0:
            return MarketCondition.SIDEWAYS, 50.0

        bull_pct = bull_points / total * 100
        bear_pct = bear_points / total * 100

        if bull_pct >= 65:
            return MarketCondition.BULL_MARKET, bull_pct
        elif bear_pct >= 65:
            return MarketCondition.BEAR_MARKET, bear_pct
        return MarketCondition.SIDEWAYS, max(bull_pct, bear_pct)

    def _analyze_sectors(self, spy_bars: Optional[list]) -> List[SectorData]:
        """Analyze sector ETFs for relative strength."""
        if not self.provider or not spy_bars:
            return []

        spy_closes = [float(b.close) for b in spy_bars]
        spy_change_5d = ((spy_closes[-1] - spy_closes[-6]) / spy_closes[-6] * 100
                         if len(spy_closes) >= 6 else 0)

        sectors = []
        for name, etf in SECTOR_ETFS.items():
            try:
                bars = self.provider.get_ohlcv(etf, period="1mo", interval="1d")
                if not bars or len(bars) < 6:
                    continue

                closes = [float(b.close) for b in bars]
                change_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0
                change_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
                rel_strength = change_5d - spy_change_5d

                strength = SectorStrength.NEUTRAL
                if rel_strength > 2:
                    strength = SectorStrength.STRONG
                elif rel_strength < -2:
                    strength = SectorStrength.WEAK

                sectors.append(SectorData(
                    name=name, etf=etf,
                    change_1d=round(change_1d, 2),
                    change_5d=round(change_5d, 2),
                    strength=strength,
                    relative_strength=round(rel_strength, 2),
                ))
            except Exception as exc:
                logger.warning("Sector analysis failed for %s (%s): %s", name, etf, exc)

        return sectors

    def _compute_momentum(self, spy_bars: Optional[list], qqq_bars: Optional[list]) -> float:
        """Compute market momentum score (-100 to +100)."""
        momentum = 0.0
        count = 0

        for bars in [spy_bars, qqq_bars]:
            if not bars or len(bars) < 10:
                continue
            closes = np.array([float(b.close) for b in bars])
            # Rate of change
            roc_5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            roc_10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0

            # EMA slope
            ema9 = self._ema(closes, 9)
            ema9_prev = self._ema(closes[:-1], 9)
            slope = (ema9 - ema9_prev) / ema9_prev * 100 if ema9_prev > 0 else 0

            score = roc_5 * 3 + roc_10 * 2 + slope * 5
            momentum += score
            count += 1

        if count > 0:
            momentum /= count

        return round(max(-100, min(100, momentum)), 1)

    def _apply_trading_rules(self, ctx: MarketContext):
        """Set trading rules based on market condition."""
        if ctx.condition == MarketCondition.BULL_MARKET:
            ctx.allow_aggressive = True
            ctx.confidence_modifier = 1.15
            ctx.position_size_modifier = 1.2
            ctx.max_concurrent_trades = 8
        elif ctx.condition == MarketCondition.BEAR_MARKET:
            ctx.allow_aggressive = False
            ctx.confidence_modifier = 0.7
            ctx.position_size_modifier = 0.5
            ctx.max_concurrent_trades = 2
        else:  # SIDEWAYS
            ctx.allow_aggressive = False
            ctx.confidence_modifier = 0.85
            ctx.position_size_modifier = 0.8
            ctx.max_concurrent_trades = 4

        # Momentum adjustment
        if ctx.market_momentum > 30:
            ctx.confidence_modifier *= 1.1
        elif ctx.market_momentum < -30:
            ctx.confidence_modifier *= 0.85

        ctx.confidence_modifier = round(min(1.3, max(0.5, ctx.confidence_modifier)), 2)
        ctx.position_size_modifier = round(min(1.3, max(0.5, ctx.position_size_modifier)), 2)

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> float:
        if len(data) < period:
            return float(data[-1]) if len(data) > 0 else 0.0
        multiplier = 2 / (period + 1)
        ema = float(data[0])
        for val in data[1:]:
            ema = (float(val) - ema) * multiplier + ema
        return ema
