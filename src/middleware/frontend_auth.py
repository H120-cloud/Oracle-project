"""Frontend session-token enforcement for Oracle API routes."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.services.frontend_auth import FrontendAuthService, frontend_auth_service


PUBLIC_PREFIXES = (
    "/api/v1/auth/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class FrontendAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        auth_service: FrontendAuthService = frontend_auth_service,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.auth_service = auth_service
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if not self.enabled or self._is_public(request.url.path):
            return await call_next(request)

        if not request.url.path.startswith("/api/v1"):
            return await call_next(request)

        token = self._bearer_token(request.headers.get("authorization", ""))
        if token and self.auth_service.verify_token(token):
            return await call_next(request)

        return JSONResponse(
            {"detail": "Oracle frontend authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _is_public(path: str) -> bool:
        return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

    @staticmethod
    def _bearer_token(header: str) -> str | None:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return token.strip()
