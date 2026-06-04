from datetime import datetime, timedelta, timezone

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
