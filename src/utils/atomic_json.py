"""Atomic JSON read/write with file locking to prevent corruption.

All Oracle modules that persist state to JSON should use these helpers
instead of raw ``open(..., "w")`` / ``Path.write_text()``.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from filelock import FileLock

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT = 10.0  # seconds


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def save_json_file(path: str | Path, data: Any, indent: int = 2) -> bool:
    """Atomically write *data* to *path* using an exclusive file lock.

    Returns ``True`` on success, ``False`` on failure (logged).
    """
    path = Path(path)
    lock_file = _lock_path(path)
    lock = FileLock(str(lock_file), timeout=DEFAULT_LOCK_TIMEOUT)
    try:
        with lock:
            # Write to a temp file first, then rename for atomicity
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, default=str)
            os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.error("Failed to save JSON to %s: %s", path, exc)
        return False
    # NOTE: deliberately do NOT delete lock_file. filelock holds the lock on the
    # open file handle; unlinking the path lets a later process create a new inode
    # for the same path and acquire the lock concurrently, defeating mutual
    # exclusion. The empty .lock marker is meant to persist.


def load_json_file(path: str | Path, default: Any = None) -> Any:
    """Load JSON from *path* using a shared file lock.

    Returns *default* if the file does not exist or is unreadable.
    """
    path = Path(path)
    if not path.exists():
        return default
    lock_file = _lock_path(path)
    lock = FileLock(str(lock_file), timeout=DEFAULT_LOCK_TIMEOUT)
    try:
        with lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load JSON from %s: %s", path, exc)
        return default
    # NOTE: do NOT delete lock_file here — see save_json_file for why.
