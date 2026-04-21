"""
Feature Engineering — V2

Converts DipFeatures / BounceFeatures / market context into flat
numeric vectors suitable for sklearn models.  Also handles
normalization and missing-value imputation.
"""

import logging
from typing import Optional

import numpy as np

from src.models.schemas import DipFeatures, BounceFeatures, ScannedStock

logger = logging.getLogger(__name__)

# ── Canonical feature order (must stay stable across train & predict) ────────

DIP_FEATURE_NAMES = [
    "vwap_distance_pct",
    "ema9_distance_pct",
    "ema20_distance_pct",
    "drop_from_high_pct",
    "consecutive_red_candles",
    "red_candle_volume_ratio",
    "lower_highs_count",
    "momentum_decay",
]

BOUNCE_FEATURE_NAMES = [
    "support_distance_pct",
    "selling_pressure_change",
    "buying_pressure_ratio",
    "higher_low_formed",
    "key_level_reclaimed",
    "rsi",
    "macd_histogram_slope",
]

CONTEXT_FEATURE_NAMES = [
    "price",
    "volume_log",
    "rvol",
    "change_percent",
]


class FeatureEngineer:
    """Transform domain objects into ML-ready numeric arrays."""

    # ── Dip features ─────────────────────────────────────────────────────

    @staticmethod
    def dip_to_array(features: DipFeatures) -> np.ndarray:
        return np.array(
            [
                features.vwap_distance_pct,
                features.ema9_distance_pct,
                features.ema20_distance_pct,
                features.drop_from_high_pct,
                features.consecutive_red_candles,
                features.red_candle_volume_ratio,
                features.lower_highs_count,
                features.momentum_decay,
            ],
            dtype=np.float64,
        )

    # ── Bounce features ──────────────────────────────────────────────────

    @staticmethod
    def bounce_to_array(features: BounceFeatures) -> np.ndarray:
        return np.array(
            [
                features.support_distance_pct,
                features.selling_pressure_change,
                features.buying_pressure_ratio,
                float(features.higher_low_formed),
                float(features.key_level_reclaimed),
                features.rsi if features.rsi is not None else 50.0,
                features.macd_histogram_slope
                if features.macd_histogram_slope is not None
                else 0.0,
            ],
            dtype=np.float64,
        )

    # ── Market context features ──────────────────────────────────────────

    @staticmethod
    def context_to_array(stock: ScannedStock) -> np.ndarray:
        return np.array(
            [
                stock.price,
                np.log1p(stock.volume) if stock.volume > 0 else 0.0,
                stock.rvol if stock.rvol is not None else 1.0,
                stock.change_percent if stock.change_percent is not None else 0.0,
            ],
            dtype=np.float64,
        )

    # ── Combined vector for risk / ranking models ────────────────────────

    @staticmethod
    def combined_vector(
        dip: Optional[DipFeatures],
        bounce: Optional[BounceFeatures],
        stock: Optional[ScannedStock],
        dip_prob: float = 0.0,
        bounce_prob: float = 0.0,
    ) -> np.ndarray:
        """Concatenate all features + rule-based probabilities into one vector."""
        parts = []

        if dip is not None:
            parts.append(FeatureEngineer.dip_to_array(dip))
        else:
            parts.append(np.zeros(len(DIP_FEATURE_NAMES)))

        if bounce is not None:
            parts.append(FeatureEngineer.bounce_to_array(bounce))
        else:
            parts.append(np.zeros(len(BOUNCE_FEATURE_NAMES)))

        if stock is not None:
            parts.append(FeatureEngineer.context_to_array(stock))
        else:
            parts.append(np.zeros(len(CONTEXT_FEATURE_NAMES)))

        # Append rule-based scores as extra features
        parts.append(np.array([dip_prob, bounce_prob], dtype=np.float64))

        return np.concatenate(parts)

    @staticmethod
    def combined_feature_names() -> list[str]:
        return (
            DIP_FEATURE_NAMES
            + BOUNCE_FEATURE_NAMES
            + CONTEXT_FEATURE_NAMES
            + ["rule_dip_prob", "rule_bounce_prob"]
        )
