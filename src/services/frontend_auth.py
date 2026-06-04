"""Telegram one-time-code authentication for the Oracle frontend."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


@dataclass
class FrontendAuthChallenge:
    code: str
    expires_at: datetime
    used: bool = False


@dataclass
class FrontendSession:
    token: str
    expires_at: datetime


class FrontendAuthService:
    """Small in-memory OTP/session store for a single-user Oracle deployment."""

    def __init__(
        self,
        *,
        code_ttl_seconds: int = 300,
        session_ttl_seconds: int = 8 * 60 * 60,
        code_generator: Optional[Callable[[], str]] = None,
        token_generator: Optional[Callable[[], str]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.code_ttl_seconds = code_ttl_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self._code_generator = code_generator or self._generate_code
        self._token_generator = token_generator or self._generate_token
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._latest_challenge: Optional[FrontendAuthChallenge] = None
        self._sessions: dict[str, FrontendSession] = {}

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(32)

    def create_challenge(self) -> FrontendAuthChallenge:
        challenge = FrontendAuthChallenge(
            code=self._code_generator(),
            expires_at=self._now() + timedelta(seconds=self.code_ttl_seconds),
        )
        self._latest_challenge = challenge
        return challenge

    def verify_code(self, code: str) -> Optional[str]:
        challenge = self._latest_challenge
        if challenge is None or challenge.used:
            return None
        if self._now() >= challenge.expires_at:
            return None
        if not secrets.compare_digest(str(code).strip(), challenge.code):
            return None

        challenge.used = True
        token = self._token_generator()
        self._sessions[token] = FrontendSession(
            token=token,
            expires_at=self._now() + timedelta(seconds=self.session_ttl_seconds),
        )
        return token

    def verify_token(self, token: str) -> bool:
        self._purge_expired_sessions()
        session = self._sessions.get(str(token or "").strip())
        return bool(session and self._now() < session.expires_at)

    def revoke_token(self, token: str) -> None:
        self._sessions.pop(str(token or "").strip(), None)

    def _purge_expired_sessions(self) -> None:
        now = self._now()
        expired = [token for token, session in self._sessions.items() if now >= session.expires_at]
        for token in expired:
            self._sessions.pop(token, None)


frontend_auth_service = FrontendAuthService()
