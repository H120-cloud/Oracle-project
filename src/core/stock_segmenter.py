"""
Stock-Type Segmentation — V3

Categorizes stocks into:
  - low_float_momentum  (float < 50M shares, high RVOL)
  - mid_cap_liquid      (market cap 2B-50B, normal float)
  - biotech_news        (biotech/pharma sector proxied by ticker patterns + high vol)
  - earnings_mover      (placeholder — needs external catalyst feed)
  - unknown

Adjusts analysis thresholds per category.
"""

import logging
from typing import Optional

from src.models.schemas import ScannedStock, StockType, StockSegment

logger = logging.getLogger(__name__)

# Common biotech-sector tickers (heuristic for V3 — replace with sector API in V5)
BIOTECH_TICKERS = {
    "MRNA", "BNTX", "REGN", "VRTX", "GILD", "BIIB", "AMGN", "SGEN",
    "ALNY", "BMRN", "RARE", "IONS", "NBIX", "EXEL", "SRPT",
}

LOW_FLOAT_THRESHOLD = 50_000_000    # 50M shares
MIDCAP_LOW = 2_000_000_000          # 2B
MIDCAP_HIGH = 50_000_000_000        # 50B
HIGH_RVOL_THRESHOLD = 2.0


class StockSegmenter:
    """Classify a stock into a segment/type based on available fundamentals."""

    def classify(self, stock: ScannedStock) -> StockSegment:
        # 1. Biotech / news-driven (heuristic)
        if stock.ticker.upper() in BIOTECH_TICKERS:
            return StockSegment(
                stock_type=StockType.BIOTECH_NEWS,
                reason="Known biotech ticker",
            )

        # 2. Low-float momentum
        if (
            stock.float_shares is not None
            and stock.float_shares < LOW_FLOAT_THRESHOLD
            and (stock.rvol is not None and stock.rvol >= HIGH_RVOL_THRESHOLD)
        ):
            return StockSegment(
                stock_type=StockType.LOW_FLOAT_MOMENTUM,
                reason=f"Float {stock.float_shares/1e6:.0f}M, RVOL {stock.rvol:.1f}",
            )

        # 3. Mid-cap liquid
        if (
            stock.market_cap is not None
            and MIDCAP_LOW <= stock.market_cap <= MIDCAP_HIGH
        ):
            return StockSegment(
                stock_type=StockType.MID_CAP_LIQUID,
                reason=f"Market cap ${stock.market_cap/1e9:.1f}B",
            )

        # 4. Earnings mover — placeholder (needs catalyst feed)
        # In V5 we can check an earnings calendar API

        return StockSegment(
            stock_type=StockType.UNKNOWN,
            reason="Does not match known segments",
        )

    @staticmethod
    def get_threshold_adjustments(stock_type: StockType) -> dict:
        """
        Return multipliers for detection thresholds per stock type.
        These are applied to dip/bounce thresholds.
        """
        adjustments = {
            StockType.LOW_FLOAT_MOMENTUM: {
                "dip_sensitivity": 1.3,     # bigger moves = need bigger thresholds
                "bounce_sensitivity": 1.3,
                "stop_multiplier": 1.5,     # wider stops
            },
            StockType.MID_CAP_LIQUID: {
                "dip_sensitivity": 1.0,
                "bounce_sensitivity": 1.0,
                "stop_multiplier": 1.0,
            },
            StockType.BIOTECH_NEWS: {
                "dip_sensitivity": 1.4,     # volatile, need wider thresholds
                "bounce_sensitivity": 1.2,
                "stop_multiplier": 1.8,
            },
            StockType.EARNINGS_MOVER: {
                "dip_sensitivity": 1.2,
                "bounce_sensitivity": 1.1,
                "stop_multiplier": 1.3,
            },
            StockType.UNKNOWN: {
                "dip_sensitivity": 1.0,
                "bounce_sensitivity": 1.0,
                "stop_multiplier": 1.0,
            },
        }
        return adjustments.get(stock_type, adjustments[StockType.UNKNOWN])
