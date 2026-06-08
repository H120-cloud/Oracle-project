"""Telegram one-time-code authentication for the Oracle frontend."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional


class RateLimitedError(Exception):
    """Raised when login-code requests exceed the allowed rate."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Rate limited; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


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
        max_verify_attempts: int = 5,
        max_code_requests: int = 3,
        request_window_seconds: int = 300,
        code_generator: Optional[Callable[[], str]] = None,
        token_generator: Optional[Callable[[], str]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.code_ttl_seconds = code_ttl_seconds
        self.session_ttl_seconds = session_ttl_seconds
        # Brute-force guard: after this many wrong codes the challenge is burned.
        self.max_verify_attempts = max_verify_attempts
        # Spam/DoS guard: at most this many code requests per rolling window.
        self.max_code_requests = max_code_requests
        self.request_window_seconds = request_window_seconds
        self._code_generator = code_generator or self._generate_code
        self._token_generator = token_generator or self._generate_token
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._latest_challenge: Optional[FrontendAuthChallenge] = None
        self._sessions: dict[str, FrontendSession] = {}
        self._verify_attempts = 0
        self._code_request_times: list[datetime] = []

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(32)

    def create_challenge(self) -> FrontendAuthChallenge:
        now = self._now()
        # Prune requests outside the rolling window, then enforce the cap.
        window_start = now - timedelta(seconds=self.request_window_seconds)
        self._code_request_times = [t for t in self._code_request_times if t > window_start]
        if len(self._code_request_times) >= self.max_code_requests:
            oldest = min(self._code_request_times)
            retry_after = int((oldest + timedelta(seconds=self.request_window_seconds) - now).total_seconds())
            raise RateLimitedError(retry_after_seconds=max(1, retry_after))
        self._code_request_times.append(now)

        challenge = FrontendAuthChallenge(
            code=self._code_generator(),
            expires_at=now + timedelta(seconds=self.code_ttl_seconds),
        )
        self._latest_challenge = challenge
        self._verify_attempts = 0  # fresh code resets the brute-force counter
        return challenge

    def verify_code(self, code: str) -> Optional[str]:
        challenge = self._latest_challenge
        if challenge is None or challenge.used:
            return None
        if self._now() >= challenge.expires_at:
            return None
        if self._verify_attempts >= self.max_verify_attempts:
            challenge.used = True  # burn it — too many wrong guesses
            return None
        if not secrets.compare_digest(str(code).strip(), challenge.code):
            self._verify_attempts += 1
            if self._verify_attempts >= self.max_verify_attempts:
                challenge.used = True  # lock out further attempts on this code
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
