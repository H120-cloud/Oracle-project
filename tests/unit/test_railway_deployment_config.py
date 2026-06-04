from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_railway_secret_templates_are_git_safe():
    gitignore = _read(".gitignore")
    railway_env = _read(".env.railway")
    dockerignore = _read(".dockerignore")

    assert ".env.railway" in gitignore or ".env.*" in gitignore
    assert ".env.railway" in dockerignore
    assert "ORACLE_LEAN_MODE=true" in railway_env
    assert "TELEGRAM_BOT_TOKEN=" in railway_env
    assert "TELEGRAM_CHAT_ID=" in railway_env

    forbidden_secret_patterns = [
        r"PK[A-Z0-9]{16,}",
        r"POLYGON_API_KEY=[A-Za-z0-9]{12,}",
        r"ALPHAVANTAGE_API_KEY=[A-Za-z0-9]{12,}",
        r"ALPACA_SECRET_KEY=[A-Za-z0-9]{20,}",
    ]
    for pattern in forbidden_secret_patterns:
        assert not re.search(pattern, railway_env), pattern


def test_railway_startup_binds_to_port_without_code_volume_config():
    railway = _read("railway.toml")
    dockerfile = _read("Dockerfile")

    assert "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}" in railway
    assert "[[mounts]]" not in railway
    assert "ENV PORT=" not in dockerfile
    assert 'CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"' in dockerfile
    assert "npm ci" in dockerfile
