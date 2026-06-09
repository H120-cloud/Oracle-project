"""Telegram one-time-code authentication for the Oracle frontend."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.utils.atomic_json import load_json_file, save_json_file
from src.utils.data_paths import agentic_path

logger = logging.getLogger(__name__)


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
        persist_path: Optional[str | Path] = None,
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
        # Sessions persist to disk so they survive backend restarts (uvicorn
        # --reload on save, Railway crash-restart/redeploy). Without this, every
        # restart wiped the in-memory store and the browser's replayed token —
        # still held in sessionStorage — got 401 on every panel at once.
        self._persist_path = Path(persist_path) if persist_path is not None else None
        # Only sessions are persisted. The pending OTP challenge, brute-force
        # counter, and rate-limit window are intentionally in-memory: they live
        # for at most ~5 min, and a restart mid-login just means the user clicks
        # "Send code" again — self-healing, not worth the persistence complexity.
        self._latest_challenge: Optional[FrontendAuthChallenge] = None
        self._sessions: dict[str, FrontendSession] = {}
        self._verify_attempts = 0
        self._code_request_times: list[datetime] = []
        if self._persist_path is not None:
            self._load_sessions()

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
        self._save_sessions()
        return token

    def verify_token(self, token: str) -> bool:
        self._purge_expired_sessions()
        session = self._sessions.get(str(token or "").strip())
        return bool(session and self._now() < session.expires_at)

    def revoke_token(self, token: str) -> None:
        if self._sessions.pop(str(token or "").strip(), None) is not None:
            self._save_sessions()

    def _purge_expired_sessions(self) -> None:
        now = self._now()
        expired = [token for token, session in self._sessions.items() if now >= session.expires_at]
        for token in expired:
            self._sessions.pop(token, None)
        if expired:
            self._save_sessions()

    def _load_sessions(self) -> None:
        """Restore non-expired sessions from disk (best-effort)."""
        raw = load_json_file(self._persist_path, default={})
        if not isinstance(raw, dict):
            return
        now = self._now()
        restored: dict[str, FrontendSession] = {}
        for token, info in raw.items():
            if not isinstance(info, dict):
                continue
            try:
                expires_at = datetime.fromisoformat(info["expires_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now < expires_at:
                restored[token] = FrontendSession(token=token, expires_at=expires_at)
        self._sessions = restored

    def _save_sessions(self) -> None:
        """Persist the current sessions to disk (best-effort)."""
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - filesystem edge case
            logger.warning("Could not create session store dir %s: %s", self._persist_path.parent, exc)
            return
        payload = {
            token: {"expires_at": session.expires_at.isoformat()}
            for token, session in self._sessions.items()
        }
        save_json_file(self._persist_path, payload)


# The session store is persisted to the agentic data dir (the Railway volume),
# so it survives restarts/redeploys — see FrontendAuthService docstring above.
# CONSTRAINT: this file-backed store assumes a SINGLE worker process. If the
# deployment is ever scaled to multiple uvicorn/gunicorn workers, concurrent
# writes from different processes will lose updates (last-writer-wins), silently
# dropping freshly-issued tokens and reviving the 401 problem. Before scaling
# out, move sessions to a shared store (Redis/Postgres). The startCommand in
# railway.toml currently runs one worker, so this holds today.
frontend_auth_service = FrontendAuthService(
    persist_path=agentic_path("frontend_auth_sessions.json"),
)
