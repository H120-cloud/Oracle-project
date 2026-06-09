from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_auth_service_issues_single_use_code_and_token(monkeypatch):
    from src.services.frontend_auth import FrontendAuthService

    service = FrontendAuthService(
        code_ttl_seconds=300,
        session_ttl_seconds=900,
        code_generator=lambda: "123456",
        token_generator=lambda: "session-token",
    )

    challenge = service.create_challenge()

    assert challenge.code == "123456"
    assert challenge.expires_at > datetime.now(timezone.utc)

    token = service.verify_code("123456")
    assert token == "session-token"
    assert service.verify_token("session-token")
    assert service.verify_code("123456") is None


def test_auth_service_rejects_expired_code():
    from src.services.frontend_auth import FrontendAuthService

    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    service = FrontendAuthService(
        code_ttl_seconds=1,
        now=lambda: now,
        code_generator=lambda: "111111",
    )

    service.create_challenge()
    service._now = lambda: now + timedelta(seconds=2)

    assert service.verify_code("111111") is None


def test_verify_code_locks_out_after_max_failed_attempts():
    from src.services.frontend_auth import FrontendAuthService

    service = FrontendAuthService(
        code_generator=lambda: "123456",
        token_generator=lambda: "tok",
        max_verify_attempts=3,
    )
    service.create_challenge()

    for _ in range(3):
        assert service.verify_code("000000") is None

    # Locked out: even the correct code is rejected once attempts are exhausted.
    assert service.verify_code("123456") is None


def test_new_challenge_resets_verify_attempts():
    from src.services.frontend_auth import FrontendAuthService

    service = FrontendAuthService(
        code_generator=lambda: "123456",
        token_generator=lambda: "tok",
        max_verify_attempts=3,
    )
    service.create_challenge()
    for _ in range(3):
        service.verify_code("000000")

    # A fresh code resets the failed-attempt counter.
    service.create_challenge()
    assert service.verify_code("123456") == "tok"


def test_create_challenge_rate_limited_after_max_requests():
    from src.services.frontend_auth import FrontendAuthService, RateLimitedError

    service = FrontendAuthService(
        code_generator=lambda: "123456",
        max_code_requests=3,
        request_window_seconds=300,
    )
    for _ in range(3):
        service.create_challenge()

    with pytest.raises(RateLimitedError):
        service.create_challenge()


def test_create_challenge_allowed_after_window_elapses():
    from src.services.frontend_auth import FrontendAuthService, RateLimitedError

    clock = {"now": datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)}
    service = FrontendAuthService(
        code_generator=lambda: "123456",
        max_code_requests=2,
        request_window_seconds=300,
        now=lambda: clock["now"],
    )
    service.create_challenge()
    service.create_challenge()
    with pytest.raises(RateLimitedError):
        service.create_challenge()

    # Once the window passes, requests are allowed again.
    clock["now"] = clock["now"] + timedelta(seconds=301)
    assert service.create_challenge() is not None


def test_request_code_route_returns_429_when_rate_limited(monkeypatch):
    import asyncio

    import src.api.routes.frontend_auth as fa
    from src.services.frontend_auth import RateLimitedError
    from fastapi import HTTPException

    def _raise_rate_limited():
        raise RateLimitedError(retry_after_seconds=42)

    monkeypatch.setattr(fa.frontend_auth_service, "create_challenge", _raise_rate_limited)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(fa.request_frontend_code())
    assert excinfo.value.status_code == 429


def test_frontend_auth_middleware_blocks_api_without_token():
    from src.middleware.frontend_auth import FrontendAuthMiddleware
    from src.services.frontend_auth import FrontendAuthService

    service = FrontendAuthService(token_generator=lambda: "valid-token")
    app = FastAPI()
    app.add_middleware(FrontendAuthMiddleware, auth_service=service, enabled=True)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/api/v1/auth/request-code")
    def request_code():
        return {"ok": True}

    @app.get("/api/v1/news/all")
    def protected():
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/auth/request-code").status_code == 200
    assert client.get("/api/v1/news/all").status_code == 401


def test_frontend_auth_middleware_allows_valid_bearer_token():
    from src.middleware.frontend_auth import FrontendAuthMiddleware
    from src.services.frontend_auth import FrontendAuthService

    service = FrontendAuthService(token_generator=lambda: "valid-token")
    service.create_challenge()
    service._latest_challenge.code = "654321"
    token = service.verify_code("654321")

    app = FastAPI()
    app.add_middleware(FrontendAuthMiddleware, auth_service=service, enabled=True)

    @app.get("/api/v1/news/all")
    def protected():
        return {"ok": True}

    client = TestClient(app)

    response = client.get("/api/v1/news/all", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_frontend_auth_middleware_allows_cors_preflight():
    from src.middleware.frontend_auth import FrontendAuthMiddleware

    app = FastAPI()
    app.add_middleware(FrontendAuthMiddleware, enabled=True)

    @app.options("/api/v1/news/all")
    def preflight():
        return {"ok": True}

    client = TestClient(app)

    assert client.options("/api/v1/news/all").status_code == 200


def test_fetch_json_attaches_frontend_session_token():
    source = open("frontend/src/api_shared.js", encoding="utf-8").read()

    assert "ORACLE_FRONTEND_SESSION_TOKEN" in source
    assert "Authorization" in source
    assert "Bearer" in source
    assert "oracle-auth-expired" in source


def test_frontend_gate_validates_token_before_rendering_children():
    source = open("frontend/src/components/FrontendAuthGate.jsx", encoding="utf-8").read()

    assert "getFrontendAuthSession" in source
    assert "checkingSession" in source
    assert "setAuthenticated(true)" in source
    assert "clearFrontendSessionToken()" in source


def test_frontend_gate_surfaces_session_expiry_notice():
    """On 401 the gate should explain the expiry, not silently bounce to login."""
    source = open("frontend/src/components/FrontendAuthGate.jsx", encoding="utf-8").read()

    assert "oracle-auth-expired" in source
    assert "sessionExpired" in source
    assert "session expired" in source.lower()


def test_sessions_survive_service_restart_when_persisted(tmp_path):
    """A token must remain valid after the process restarts.

    The in-memory-only store invalidated every token on each backend restart
    (uvicorn --reload, Railway crash-restart/redeploy), producing 401 bursts on
    every panel. Persisting sessions to disk fixes this at the root.
    """
    from src.services.frontend_auth import FrontendAuthService

    persist_path = tmp_path / "frontend_auth_sessions.json"

    service = FrontendAuthService(
        code_generator=lambda: "123456",
        token_generator=lambda: "persisted-token",
        persist_path=persist_path,
    )
    service.create_challenge()
    token = service.verify_code("123456")
    assert token == "persisted-token"

    # Simulate a process restart: a brand-new instance reading the same file.
    restarted = FrontendAuthService(persist_path=persist_path)
    assert restarted.verify_token("persisted-token") is True


def test_expired_sessions_are_not_restored(tmp_path):
    from src.services.frontend_auth import FrontendAuthService

    persist_path = tmp_path / "frontend_auth_sessions.json"
    clock = {"now": datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)}

    service = FrontendAuthService(
        code_generator=lambda: "123456",
        token_generator=lambda: "stale-token",
        session_ttl_seconds=900,
        now=lambda: clock["now"],
        persist_path=persist_path,
    )
    service.create_challenge()
    assert service.verify_code("123456") == "stale-token"

    # Advance past the session TTL, then "restart".
    clock["now"] = clock["now"] + timedelta(seconds=901)
    restarted = FrontendAuthService(
        now=lambda: clock["now"],
        persist_path=persist_path,
    )
    assert restarted.verify_token("stale-token") is False


def test_revoked_token_does_not_return_after_restart(tmp_path):
    from src.services.frontend_auth import FrontendAuthService

    persist_path = tmp_path / "frontend_auth_sessions.json"
    service = FrontendAuthService(
        code_generator=lambda: "123456",
        token_generator=lambda: "revoked-token",
        persist_path=persist_path,
    )
    service.create_challenge()
    token = service.verify_code("123456")
    service.revoke_token(token)

    restarted = FrontendAuthService(persist_path=persist_path)
    assert restarted.verify_token("revoked-token") is False
