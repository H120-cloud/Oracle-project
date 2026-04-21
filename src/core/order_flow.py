"""
Order Flow Analyzer — V4

Estimates order flow metrics from OHLCV data (proxy).
True order flow requires Level 2 / tick data; this V4 implementation
approximates using volume + price action patterns.

Metrics:
  - bid/ask imbalance (estimated from close vs open + volume)
  - aggressive buy/sell ratios
  - large-order detection (volume spikes)
  - tape speed proxy
  - net flow signal: bullish / bearish / neutral
"""

import logging
from typing import Optional

import numpy as np

from src.models.schemas import OHLCVBar, OrderFlowData

logger = logging.getLogger(__name__)

LARGE_ORDER_THRESHOLD = 2.0  # volume > 2x average = large order


class OrderFlowAnalyzer:
    """Estimate order flow from OHLCV bars."""

    def __init__(self, lookback: int = 20, large_order_mult: float = LARGE_ORDER_THRESHOLD):
        self.lookback = lookback
        self.large_order_mult = large_order_mult

    def analyze(self, bars: list[OHLCVBar]) -> Optional[OrderFlowData]:
        if len(bars) < self.lookback:
            logger.warning("Not enough bars (%d) for order flow analysis", len(bars))
            return None

        recent = bars[-self.lookback:]
        volumes = np.array([b.volume for b in recent])
        opens = np.array([b.open for b in recent])
        closes = np.array([b.close for b in recent])
        highs = np.array([b.high for b in recent])
        lows = np.array([b.low for b in recent])

        total_volume = volumes.sum()
        if total_volume == 0:
            return None

        # ── Buy / sell volume estimation ─────────────────────────────────
        # Use close position within high-low range to estimate buy/sell split
        ranges = highs - lows
        ranges = np.where(ranges == 0, 1e-8, ranges)  # avoid div by zero
        close_position = (closes - lows) / ranges  # 0 = sold at low, 1 = bought at high

        buy_volumes = volumes * close_position
        sell_volumes = volumes * (1 - close_position)

        total_buy = float(buy_volumes.sum())
        total_sell = float(sell_volumes.sum())

        # Bid/ask imbalance
        bid_ask_imbalance = total_buy / total_sell if total_sell > 0 else 2.0

        # Aggressive buy/sell ratios
        aggressive_buy_ratio = total_buy / total_volume if total_volume > 0 else 0.5
        aggressive_sell_ratio = total_sell / total_volume if total_volume > 0 else 0.5

        # ── Large order detection ────────────────────────────────────────
        avg_vol = float(volumes.mean())
        large_mask = volumes > (avg_vol * self.large_order_mult)

        # Classify large orders as buy or sell based on candle direction
        bullish_candle = closes > opens
        large_buy_vol = float(volumes[large_mask & bullish_candle].sum())
        large_sell_vol = float(volumes[large_mask & ~bullish_candle].sum())

        # ── Tape speed proxy ─────────────────────────────────────────────
        # Approximate: avg volume per bar (higher = faster tape)
        tape_speed = float(volumes.mean())

        # ── Net flow ─────────────────────────────────────────────────────
        net_flow = total_buy - total_sell

        # ── Signal classification ────────────────────────────────────────
        if bid_ask_imbalance > 1.3 and large_buy_vol > large_sell_vol * 1.5:
            signal = "bullish"
        elif bid_ask_imbalance < 0.7 and large_sell_vol > large_buy_vol * 1.5:
            signal = "bearish"
        elif bid_ask_imbalance > 1.15:
            signal = "bullish"
        elif bid_ask_imbalance < 0.85:
            signal = "bearish"
        else:
            signal = "neutral"

        result = OrderFlowData(
            bid_ask_imbalance=round(bid_ask_imbalance, 3),
            aggressive_buy_ratio=round(aggressive_buy_ratio, 3),
            aggressive_sell_ratio=round(aggressive_sell_ratio, 3),
            large_order_buy_volume=round(large_buy_vol, 0),
            large_order_sell_volume=round(large_sell_vol, 0),
            tape_speed=round(tape_speed, 0),
            net_flow=round(net_flow, 0),
            signal=signal,
        )

        logger.info(
            "OrderFlow: imb=%.2f buy=%.1f%% sell=%.1f%% large_buy=%.0f large_sell=%.0f signal=%s",
            bid_ask_imbalance,
            aggressive_buy_ratio * 100,
            aggressive_sell_ratio * 100,
            large_buy_vol, large_sell_vol, signal,
        )
        return result
