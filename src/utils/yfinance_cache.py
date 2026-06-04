"""Configure yfinance cache storage for local runtimes."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def configure_yfinance_cache(yf_module) -> None:
    """Point yfinance SQLite caches at a writable project-local directory."""
    cache_dir = Path(os.getenv("YFINANCE_CACHE_DIR", "data/cache/yfinance"))
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(yf_module, "set_tz_cache_location"):
            yf_module.set_tz_cache_location(str(cache_dir))
        elif hasattr(yf_module, "set_cache_location"):
            yf_module.set_cache_location(str(cache_dir))
    except Exception as exc:
        logger.debug("Failed to configure yfinance cache at %s: %s", cache_dir, exc)
