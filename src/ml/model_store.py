"""
Model Store — V2

Handles saving, loading, and versioning of trained sklearn models.
Models are stored as joblib files on disk (upgradeable to S3/GCS in V5).
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import joblib

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("models")


class ModelStore:
    """Persist and retrieve trained ML models."""

    def __init__(self, base_dir: Path | str = DEFAULT_MODEL_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, model: Any, name: str, metadata: dict | None = None) -> str:
        """Save model to disk. Returns the filepath."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{ts}.joblib"
        filepath = self.base_dir / filename

        payload = {"model": model, "metadata": metadata or {}, "saved_at": ts}
        joblib.dump(payload, filepath)

        # Also save as 'latest' symlink-style copy
        latest_path = self.base_dir / f"{name}_latest.joblib"
        joblib.dump(payload, latest_path)

        logger.info("Model saved: %s", filepath)
        return str(filepath)

    def load(self, name: str, version: str = "latest") -> Optional[dict]:
        """Load a model by name. Returns dict with 'model' and 'metadata'."""
        if version == "latest":
            filepath = self.base_dir / f"{name}_latest.joblib"
        else:
            filepath = self.base_dir / f"{name}_{version}.joblib"

        if not filepath.exists():
            logger.warning("Model not found: %s", filepath)
            return None

        payload = joblib.load(filepath)
        logger.info("Model loaded: %s (saved_at=%s)", filepath, payload.get("saved_at"))
        return payload

    def exists(self, name: str) -> bool:
        return (self.base_dir / f"{name}_latest.joblib").exists()

    def list_models(self) -> list[str]:
        return [f.stem for f in self.base_dir.glob("*.joblib")]
