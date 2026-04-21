"""
Volume Profile Engine — V3

Computes:
  - Point of Control (POC): price level with the highest traded volume
  - Value Area High/Low: range containing ~70% of total volume
  - High-volume nodes: significant volume clusters
  - Support/resistance levels derived from volume concentrations
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.models.schemas import VolumeProfileData, OHLCVBar

logger = logging.getLogger(__name__)

DEFAULT_NUM_BINS = 50
VALUE_AREA_PCT = 0.70
HVN_THRESHOLD_PCT = 0.60  # bins above 60th-percentile volume are HVN


class VolumeProfileEngine:
    """Compute volume-at-price profile from OHLCV bars."""

    def __init__(
        self,
        num_bins: int = DEFAULT_NUM_BINS,
        value_area_pct: float = VALUE_AREA_PCT,
    ):
        self.num_bins = num_bins
        self.value_area_pct = value_area_pct

    def compute(self, bars: list[OHLCVBar]) -> Optional[VolumeProfileData]:
        """Build volume profile from a list of OHLCV bars."""
        if len(bars) < 10:
            logger.warning("Not enough bars (%d) for volume profile", len(bars))
            return None

        prices = np.array([(b.high + b.low + b.close) / 3 for b in bars])
        volumes = np.array([b.volume for b in bars])

        price_min, price_max = float(prices.min()), float(prices.max())
        if price_max == price_min:
            return None

        # Build histogram: volume distributed into price bins
        bin_edges = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_volumes = np.zeros(self.num_bins)

        for tp, vol in zip(prices, volumes):
            idx = int((tp - price_min) / (price_max - price_min) * (self.num_bins - 1))
            idx = min(idx, self.num_bins - 1)
            bin_volumes[idx] += vol

        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        # POC: bin with highest volume
        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float(bin_centers[poc_idx])

        # Value Area: expand outward from POC until 70% of total volume
        total_vol = bin_volumes.sum()
        if total_vol == 0:
            return None

        va_vol = bin_volumes[poc_idx]
        low_idx, high_idx = poc_idx, poc_idx

        while va_vol / total_vol < self.value_area_pct:
            expand_low = bin_volumes[low_idx - 1] if low_idx > 0 else 0
            expand_high = bin_volumes[high_idx + 1] if high_idx < self.num_bins - 1 else 0

            if expand_low == 0 and expand_high == 0:
                break

            if expand_low >= expand_high and low_idx > 0:
                low_idx -= 1
                va_vol += bin_volumes[low_idx]
            elif high_idx < self.num_bins - 1:
                high_idx += 1
                va_vol += bin_volumes[high_idx]
            else:
                low_idx -= 1
                va_vol += bin_volumes[low_idx]

        val = float(bin_centers[low_idx])
        vah = float(bin_centers[high_idx])

        # High-volume nodes: bins above the threshold percentile
        threshold = np.percentile(bin_volumes[bin_volumes > 0], HVN_THRESHOLD_PCT * 100)
        hvn_indices = np.where(bin_volumes >= threshold)[0]
        hvn_prices = [round(float(bin_centers[i]), 2) for i in hvn_indices]

        # Support levels: HVN below current price
        current_price = float(prices[-1])
        support_levels = sorted(
            [p for p in hvn_prices if p < current_price], reverse=True
        )[:3]

        # Resistance levels: HVN above current price
        resistance_levels = sorted(
            [p for p in hvn_prices if p > current_price]
        )[:3]

        result = VolumeProfileData(
            poc_price=round(poc_price, 2),
            value_area_high=round(vah, 2),
            value_area_low=round(val, 2),
            high_volume_nodes=hvn_prices,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
        )

        logger.info(
            "VolumeProfile: POC=%.2f VAH=%.2f VAL=%.2f HVNs=%d S=%d R=%d",
            poc_price, vah, val, len(hvn_prices),
            len(support_levels), len(resistance_levels),
        )
        return result
