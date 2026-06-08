"""Tests for the central agentic data-dir helper (Railway persistence P0).

These tests prove:
  * there is a single source of truth for the agentic state directory,
  * no module hardcodes ``Path("data/agentic")`` or re-reads ``AGENTIC_DATA_DIR``
    inline (the split-brain risk identified in the Railway audit),
  * the startup guard fails loudly on Railway without a persistent volume,
  * seeding copies baseline artifacts only when absent (never overwrites state).
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

import src.utils.data_paths as data_paths

pytestmark = pytest.mark.unit


# ── Source-of-truth resolution ─────────────────────────────────────────────

def test_agentic_data_dir_defaults_to_data_agentic(monkeypatch):
    monkeypatch.delenv("AGENTIC_DATA_DIR", raising=False)
    assert data_paths.agentic_data_dir() == Path("data/agentic")


def test_agentic_data_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "state"))
    assert data_paths.agentic_data_dir() == tmp_path / "state"


def test_agentic_path_joins_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path))
    assert data_paths.agentic_path("sec", "x.json") == tmp_path / "sec" / "x.json"


# ── No split-brain: structural guarantee across the whole src tree ─────────

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

# A hardcoded Path("data/agentic"...) ignores AGENTIC_DATA_DIR entirely.
_HARDCODED_PATH_RE = re.compile(r"""Path\(\s*['"]data/agentic""")
# An inline env read duplicates the default and can silently diverge from it.
_INLINE_ENV_RE = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]AGENTIC_DATA_DIR""")


def _src_py_files():
    for p in _SRC_ROOT.rglob("*.py"):
        # The helper is the ONE place allowed to read the env / define the default.
        if p.name == "data_paths.py":
            continue
        yield p


def test_no_module_hardcodes_agentic_data_path():
    offenders = []
    for path in _src_py_files():
        text = path.read_text(encoding="utf-8")
        if _HARDCODED_PATH_RE.search(text):
            offenders.append(str(path.relative_to(_SRC_ROOT)))
    assert not offenders, (
        "These modules hardcode Path(\"data/agentic\") and ignore AGENTIC_DATA_DIR "
        f"(split-brain risk). Route them through src.utils.data_paths: {offenders}"
    )


def test_no_module_reads_agentic_env_inline():
    offenders = []
    for path in _src_py_files():
        text = path.read_text(encoding="utf-8")
        if _INLINE_ENV_RE.search(text):
            offenders.append(str(path.relative_to(_SRC_ROOT)))
    assert not offenders, (
        "These modules read AGENTIC_DATA_DIR inline instead of using the central "
        f"helper (default can drift): {offenders}"
    )


# ── No split-brain: functional guarantee for representative subsystems ─────

@pytest.mark.parametrize(
    "module_name, attr",
    [
        ("src.services.telegram_outbox", "DATA_DIR"),
        ("src.core.agentic.news_momentum_ml_engine", "DATA_DIR"),
        ("src.core.company_name_resolver", "DATA_DIR"),
        ("src.core.agentic.news_momentum_shadow_logger", "DATA_DIR"),
    ],
)
def test_representative_modules_resolve_under_configured_dir(
    monkeypatch, tmp_path, module_name, attr
):
    """Every consumer must land under the same configured directory."""
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "agentic"))
    importlib.reload(data_paths)
    module = importlib.import_module(module_name)
    importlib.reload(module)
    resolved = Path(getattr(module, attr)).resolve()
    expected = (tmp_path / "agentic").resolve()
    assert resolved == expected or expected in resolved.parents, (
        f"{module_name}.{attr} = {resolved}, expected under {expected}"
    )


# ── Railway startup guard ──────────────────────────────────────────────────

def _clear_railway(monkeypatch):
    for var in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
        "RAILWAY_VOLUME_MOUNT_PATH",
        "ORACLE_ALLOW_EPHEMERAL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_verify_guard_noop_off_railway(monkeypatch, tmp_path):
    _clear_railway(monkeypatch)
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "ephemeral"))
    # Not on Railway: ephemeral is fine, must not raise.
    data_paths.verify_persistent_data_dir()


def test_verify_guard_raises_on_railway_without_volume(monkeypatch, tmp_path):
    _clear_railway(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "ephemeral"))
    with pytest.raises(RuntimeError, match="(?i)volume"):
        data_paths.verify_persistent_data_dir()


def test_verify_guard_raises_when_data_dir_outside_volume(monkeypatch, tmp_path):
    _clear_railway(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "vol"))
    # data dir is NOT under the mounted volume -> still ephemeral -> raise
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "elsewhere" / "agentic"))
    with pytest.raises(RuntimeError, match="(?i)volume"):
        data_paths.verify_persistent_data_dir()


def test_verify_guard_passes_with_volume_backed_dir(monkeypatch, tmp_path):
    _clear_railway(monkeypatch)
    vol = tmp_path / "vol"
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(vol))
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(vol / "agentic"))
    data_paths.verify_persistent_data_dir()  # must not raise


def test_verify_guard_allows_explicit_ephemeral_escape(monkeypatch, tmp_path):
    _clear_railway(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "ephemeral"))
    monkeypatch.setenv("ORACLE_ALLOW_EPHEMERAL", "true")
    data_paths.verify_persistent_data_dir()  # explicit opt-out, must not raise


def test_verify_guard_fallback_to_proc_mounts(monkeypatch, tmp_path):
    """Railway sometimes mounts the volume without injecting the env var."""
    from unittest.mock import patch
    _clear_railway(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "ephemeral"))
    monkeypatch.setattr(data_paths, "_is_mounted_volume", lambda p: True)

    with patch.object(Path, "exists", return_value=True):
        data_paths.verify_persistent_data_dir()  # must not raise


# ── Seeding baseline artifacts (copy-if-absent, never overwrite) ───────────

def test_seed_copies_baseline_when_target_absent(monkeypatch, tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "company_name_ticker_map.json").write_text('{"apple": "AAPL"}', encoding="utf-8")
    target = tmp_path / "agentic"
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(target))

    seeded = data_paths.seed_agentic_data_dir(seed_dir=seed)

    assert "company_name_ticker_map.json" in seeded
    assert (target / "company_name_ticker_map.json").read_text(encoding="utf-8") == '{"apple": "AAPL"}'


def test_seed_never_overwrites_existing_state(monkeypatch, tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "company_name_ticker_map.json").write_text('{"apple": "AAPL"}', encoding="utf-8")
    target = tmp_path / "agentic"
    target.mkdir()
    # Existing live state must win over the baseline seed.
    (target / "company_name_ticker_map.json").write_text('{"live": "DATA"}', encoding="utf-8")
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(target))

    seeded = data_paths.seed_agentic_data_dir(seed_dir=seed)

    assert "company_name_ticker_map.json" not in seeded
    assert (target / "company_name_ticker_map.json").read_text(encoding="utf-8") == '{"live": "DATA"}'


def test_seed_is_noop_when_seed_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(tmp_path / "agentic"))
    assert data_paths.seed_agentic_data_dir(seed_dir=tmp_path / "does_not_exist") == []


def test_seed_skips_docs_and_dotfiles(monkeypatch, tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "README.md").write_text("# docs", encoding="utf-8")
    (seed / ".gitkeep").write_text("", encoding="utf-8")
    (seed / "model.joblib").write_text("binary", encoding="utf-8")
    target = tmp_path / "agentic"
    monkeypatch.setenv("AGENTIC_DATA_DIR", str(target))

    seeded = data_paths.seed_agentic_data_dir(seed_dir=seed)

    assert seeded == ["model.joblib"]
    assert not (target / "README.md").exists()
    assert not (target / ".gitkeep").exists()
