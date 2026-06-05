"""Historical Calibration Provider

Loads approved calibration weights from the historical training system
and makes them available to live engines.  This is a lightweight
read-only bridge — live engines query it at compute time and apply
multipliers safely (never auto-apply, fall back to defaults).

Usage:
    from src.core.agentic.calibration_provider import get_calibration_weights
    cw = get_calibration_weights()
    if cw and cw.is_approved:
        prob *= cw.second_leg_probability_w
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from src.core.agentic.historical_models import CalibrationWeights

logger = logging.getLogger(__name__)

from src.utils.data_paths import agentic_data_dir as _agentic_data_dir
DATA_DIR = str(_agentic_data_dir())


def _weights_path() -> str:
    return os.path.join(DATA_DIR, "historical_calibration_weights.json")


def get_calibration_weights() -> Optional[CalibrationWeights]:
    """Load the currently approved calibration weights, if any."""
    path = _weights_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cw = CalibrationWeights(**data)
        if not cw.is_approved:
            logger.debug("Calibration weights exist but are not approved")
            return None
        return cw
    except Exception as exc:
        logger.warning("Failed to load calibration weights: %s", exc)
        return None


def is_calibrated() -> bool:
    """Quick check whether approved calibration weights exist."""
    cw = get_calibration_weights()
    return cw is not None and cw.is_approved
