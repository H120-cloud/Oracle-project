"""Guards the WebSocket exposure posture.

`/ws/signals` and `/ws/watchlist` are registered only when their legacy gating
flags are enabled. In the deployed posture (ORACLE_LEAN_MODE=true) both flags
resolve False, so the endpoints are never registered — see
docs/websocket_auth_fix_report.md for the full audit. These tests lock that in
so the unauthenticated WebSockets can't be silently re-exposed.
"""

import pytest

from src.config import Settings


@pytest.mark.unit
def test_lean_mode_disables_websocket_gating_flags():
    s = Settings(oracle_lean_mode=True, enable_legacy_signals=None, enable_watchlist=None)
    assert s.legacy_signals_enabled is False  # gates @app.websocket("/ws/signals")
    assert s.watchlist_enabled is False       # gates @app.websocket("/ws/watchlist")


@pytest.mark.unit
def test_non_lean_mode_enables_websocket_gating_flags():
    # Documents the residual risk: running non-lean re-registers both endpoints
    # (and they are currently unauthenticated). If ever revived, add token auth
    # at the handshake — see the report.
    s = Settings(oracle_lean_mode=False, enable_legacy_signals=None, enable_watchlist=None)
    assert s.legacy_signals_enabled is True
    assert s.watchlist_enabled is True
