"""
Hot-reloadable feature flags for the Oracle news momentum system.

Reads from data/agentic/feature_flags.json. Changes are picked up within
5 seconds of file modification (mtime-based polling with a 1-second cache).

No global singleton — instantiate FeatureFlags wherever needed, or inject
it into the orchestrator. Thread-safe for reads via atomic reference swap.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
FLAGS_FILE = DATA_DIR / "feature_flags.json"


class FeatureFlagError(Exception):
    """Base exception for feature-flag infrastructure failures."""


class FeatureFlagSchemaError(FeatureFlagError):
    """The JSON file does not conform to the expected schema."""


@dataclass(frozen=True)
class _Snapshot:
    """Immutable snapshot of the flag state at a point in time."""
    flags: Dict[str, bool]
    mtime: float
    load_time: float


class FeatureFlags:
    """
    Load and query feature flags from a JSON file.

    Usage:
        ff = FeatureFlags()
        if ff.get("USE_NEW_THRESHOLDS"):
            ...
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        default_flags: Optional[Dict[str, bool]] = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._path = path or FLAGS_FILE
        self._default_flags = dict(default_flags or {
            "USE_NEW_THRESHOLDS": False,
            "SHADOW_NEW_CLASSIFIER": False,
        })
        self._poll_interval = poll_interval_seconds
        self._lock = threading.Lock()
        self._snapshot: Optional[_Snapshot] = None
        self._last_check: float = 0.0
        self._load()  # initial eager load

    # ── Internal loading ───────────────────────────────────────────────────

    def _load(self) -> None:
        """Attempt to read the file and update the snapshot.

        If the file is missing, malformed, or schema-invalid, the current
        snapshot is left untouched and a warning is logged. If there has
        never been a successful load, the default flags are used.
        """
        try:
            raw_mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            logger.warning("FeatureFlags: file not found at %s — using defaults", self._path)
            if self._snapshot is None:
                self._snapshot = _Snapshot(
                    flags=dict(self._default_flags),
                    mtime=0.0,
                    load_time=self._now(),
                )
            return
        except OSError as exc:
            logger.warning("FeatureFlags: cannot stat %s: %s — using defaults", self._path, exc)
            if self._snapshot is None:
                self._snapshot = _Snapshot(
                    flags=dict(self._default_flags),
                    mtime=0.0,
                    load_time=self._now(),
                )
            return

        # If we already have a snapshot for this mtime, skip re-parsing.
        if self._snapshot is not None and raw_mtime <= self._snapshot.mtime:
            return

        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            logger.warning(
                "FeatureFlags: JSON decode error in %s: %s — keeping last known good state",
                self._path, exc,
            )
            if self._snapshot is None:
                self._snapshot = _Snapshot(
                    flags=dict(self._default_flags),
                    mtime=raw_mtime,
                    load_time=self._now(),
                )
            return
        except OSError as exc:
            logger.warning(
                "FeatureFlags: cannot read %s: %s — keeping last known good state",
                self._path, exc,
            )
            if self._snapshot is None:
                self._snapshot = _Snapshot(
                    flags=dict(self._default_flags),
                    mtime=raw_mtime,
                    load_time=self._now(),
                )
            return

        # Schema validation
        try:
            flags = self._validate_schema(data)
        except FeatureFlagSchemaError as exc:
            logger.warning("FeatureFlags: schema error: %s — keeping last known good state", exc)
            if self._snapshot is None:
                self._snapshot = _Snapshot(
                    flags=dict(self._default_flags),
                    mtime=raw_mtime,
                    load_time=self._now(),
                )
            return

        with self._lock:
            self._snapshot = _Snapshot(
                flags=flags,
                mtime=raw_mtime,
                load_time=self._now(),
            )
        logger.debug("FeatureFlags: loaded %d flags from %s", len(flags), self._path)

    @staticmethod
    def _validate_schema(data: Any) -> Dict[str, bool]:
        """Ensure the JSON object looks like {flags: {...}}.

        Raises FeatureFlagSchemaError on any structural problem.
        """
        if not isinstance(data, dict):
            raise FeatureFlagSchemaError(f"top-level must be an object, got {type(data).__name__}")
        flags = data.get("flags")
        if flags is None:
            raise FeatureFlagSchemaError("missing 'flags' key")
        if not isinstance(flags, dict):
            raise FeatureFlagSchemaError(f"'flags' must be a dict, got {type(flags).__name__}")
        for key, value in flags.items():
            if not isinstance(key, str):
                raise FeatureFlagSchemaError(f"flag key must be a string: {key!r}")
            if not isinstance(value, bool):
                raise FeatureFlagSchemaError(
                    f"flag '{key}' must be a boolean, got {type(value).__name__} ({value!r})"
                )
        return dict(flags)

    @staticmethod
    def _now() -> float:
        return os.times().system  # any monotonic-ish source is fine; not perf-critical

    # ── Public API ─────────────────────────────────────────────────────────

    def get(self, name: str, default: bool = False) -> bool:
        """Return the current value of a feature flag.

        Polls the file for modification every ~poll_interval_seconds.
        Missing flags return *default* (False by convention).
        """
        now = self._now()
        if now - self._last_check >= self._poll_interval:
            self._last_check = now
            self._load()

        snapshot = self._snapshot
        if snapshot is None:
            return self._default_flags.get(name, default)
        return snapshot.flags.get(name, default)

    def all_flags(self) -> Dict[str, bool]:
        """Return a shallow-copy dict of the current flag snapshot.

        Mostly useful for debugging and audit logging.
        """
        self._load()
        snapshot = self._snapshot
        if snapshot is None:
            return dict(self._default_flags)
        return dict(snapshot.flags)

    def set(self, name: str, value: bool) -> None:
        """Write a flag value back to the JSON file.

        Updates the in-memory snapshot atomically so callers see the change
        immediately without waiting for the next poll cycle.
        """
        with self._lock:
            current = dict(self._snapshot.flags) if self._snapshot else dict(self._default_flags)
            current[name] = value
            payload = {
                "description": "Hot-reloadable feature flags for the Oracle news momentum system.",
                "flags": current,
                "last_modified": _iso_now(),
            }
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.write("\n")
                raw_mtime = self._path.stat().st_mtime
                self._snapshot = _Snapshot(
                    flags=current,
                    mtime=raw_mtime,
                    load_time=self._now(),
                )
            except OSError as exc:
                raise FeatureFlagError(f"Failed to write {self._path}: {exc}") from exc


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
