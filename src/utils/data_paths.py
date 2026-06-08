"""Central source of truth for the agentic state directory.

Every module that persists agentic state (dedup registries, cooldowns, alert
history, Telegram outbox, ML/CatBoost model artifacts, trace logs, SEC cache,
rocket datasets) MUST resolve its directory through this module instead of
hardcoding ``Path("data/agentic")`` or re-reading ``AGENTIC_DATA_DIR`` inline.

Why this exists
---------------
The Railway deployment audit found ~30 path-definition sites: roughly half
honored ``AGENTIC_DATA_DIR`` and half hardcoded ``Path("data/agentic")``. With
a volume mounted somewhere other than ``/app/data``, the hardcoded modules would
silently keep writing to the ephemeral overlay — "split-brain" state. Routing
everything through one helper makes that impossible.

Resolution rules
----------------
* ``AGENTIC_DATA_DIR`` env var wins when set.
* Otherwise the default is ``data/agentic`` (relative to the process CWD, which
  is ``/app`` in the Docker image — i.e. ``/app/data/agentic``).

The module-level ``AGENTIC_DATA_DIR`` constant is resolved once at import for
convenient ``from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR``
usage. Production sets the env var before the process starts, so the constant is
correct. Tests that need to re-point it use ``agentic_data_dir()`` (live) or
reload this module.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_AGENTIC_DIR = "data/agentic"

# Railway injects these into every deployed container.
_RAILWAY_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
# Set when (and only when) a persistent volume is attached to the service.
_RAILWAY_VOLUME_ENV = "RAILWAY_VOLUME_MOUNT_PATH"


def agentic_data_dir() -> Path:
    """Return the agentic state directory, honoring ``AGENTIC_DATA_DIR``.

    Read live (at call time) so callers and tests always see the current env.
    """
    return Path(os.environ.get("AGENTIC_DATA_DIR", _DEFAULT_AGENTIC_DIR))


def agentic_path(*parts: str | os.PathLike[str]) -> Path:
    """Join *parts* under the agentic data directory."""
    return agentic_data_dir().joinpath(*parts)


# Resolved-once convenience constant (see module docstring).
AGENTIC_DATA_DIR: Path = agentic_data_dir()


def _on_railway() -> bool:
    return any(os.environ.get(marker) for marker in _RAILWAY_MARKERS)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_mounted_volume(path: str | Path) -> bool:
    """Heuristic: check if *path* appears as a mount point in /proc/mounts."""
    try:
        target = str(path)
        with open("/proc/mounts", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) > 1 and parts[1] == target:
                    return True
    except Exception:
        pass
    return False


def verify_persistent_data_dir() -> None:
    """Fail loudly if running on Railway without a persistent data directory.

    On Railway the container filesystem is ephemeral; without a mounted volume
    every redeploy/restart wipes all agentic state. This guard turns that silent
    data-loss footgun into a hard, visible startup failure.

    No-ops when:
      * not running on Railway (local/dev), or
      * ``ORACLE_ALLOW_EPHEMERAL`` is truthy (explicit opt-out).

    Raises ``RuntimeError`` when on Railway and the agentic data dir is not
    located under the attached volume.
    """
    if _is_truthy(os.environ.get("ORACLE_ALLOW_EPHEMERAL")):
        logger.warning(
            "ORACLE_ALLOW_EPHEMERAL set — skipping persistent-data-dir check. "
            "Agentic state will NOT survive restarts."
        )
        return

    if not _on_railway():
        return

    data_dir = agentic_data_dir().resolve()
    mount = os.environ.get(_RAILWAY_VOLUME_ENV)

    # Primary check: Railway injects RAILWAY_VOLUME_MOUNT_PATH when a volume is attached.
    if mount:
        mount_dir = Path(mount).resolve()
        if data_dir == mount_dir or mount_dir in data_dir.parents:
            logger.info("Persistent agentic data dir verified: %s (volume %s)", data_dir, mount_dir)
            return
        raise RuntimeError(
            f"Agentic data dir {data_dir} is not under the Railway volume "
            f"{mount_dir}; state would be lost on restart. Set "
            "AGENTIC_DATA_DIR to a path under the mounted volume "
            "(e.g. /app/data/agentic). To bypass, set ORACLE_ALLOW_EPHEMERAL=true."
        )

    # Fallback: Railway sometimes mounts the volume without injecting the env var.
    # If the expected mount point exists and is listed in /proc/mounts, allow it.
    expected_mount = Path("/app/data")
    if expected_mount.exists() and _is_mounted_volume(expected_mount):
        logger.warning(
            "%s is unset but /app/data appears to be a mounted volume. "
            "Allowing startup — agentic state should persist.",
            _RAILWAY_VOLUME_ENV,
        )
        return

    raise RuntimeError(
        "Railway deployment detected but no persistent volume is attached "
        f"({_RAILWAY_VOLUME_ENV} is unset and /app/data is not a mount point). "
        "Agentic state would be lost on every redeploy/restart. "
        "Attach a Railway volume mounted at /app/data and set "
        "AGENTIC_DATA_DIR=/app/data/agentic. To intentionally run without "
        "persistence, set ORACLE_ALLOW_EPHEMERAL=true."
    )


def default_seed_dir() -> Path:
    """Image-baked baseline artifacts directory (project-root ``seed/agentic``)."""
    # src/utils/data_paths.py -> project root is three parents up.
    return Path(__file__).resolve().parents[2] / "seed" / "agentic"


def seed_agentic_data_dir(
    seed_dir: Path | None = None,
    *,
    target_dir: Path | None = None,
) -> list[str]:
    """Copy baseline artifacts into the agentic data dir, **only when absent**.

    Used to give a freshly-restored or first-boot volume a baseline ML model and
    company-name map so the system is not cold-started. Existing files (live
    state) are NEVER overwritten. Returns the list of relative paths seeded.
    """
    seed_dir = seed_dir if seed_dir is not None else default_seed_dir()
    target_dir = target_dir if target_dir is not None else agentic_data_dir()

    if not seed_dir.exists():
        return []

    seeded: list[str] = []
    for src in sorted(seed_dir.rglob("*")):
        if not src.is_file():
            continue
        # Skip documentation and bookkeeping files — only real artifacts seed.
        if src.suffix.lower() == ".md" or src.name.startswith("."):
            continue
        rel = src.relative_to(seed_dir)
        dest = target_dir / rel
        if dest.exists():
            continue  # never clobber live state
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        seeded.append(str(rel).replace(os.sep, "/"))

    if seeded:
        logger.info("Seeded %d baseline artifact(s) into %s: %s", len(seeded), target_dir, seeded)
    return seeded


__all__ = [
    "AGENTIC_DATA_DIR",
    "agentic_data_dir",
    "agentic_path",
    "verify_persistent_data_dir",
    "seed_agentic_data_dir",
    "default_seed_dir",
]
