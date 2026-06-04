"""Frontend Telegram one-time-code auth routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.services.frontend_auth import frontend_auth_service
from src.services.telegram_service import send_telegram_alert

router = APIRouter(prefix="/auth", tags=["frontend-auth"])


class RequestCodeResponse(BaseModel):
    sent: bool
    expires_at: datetime


class VerifyCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class VerifyCodeResponse(BaseModel):
    token: str
    expires_in_seconds: int


@router.post("/request-code", response_model=RequestCodeResponse)
async def request_frontend_code():
    challenge = frontend_auth_service.create_challenge()
    message = (
        "<b>Oracle frontend login code</b>\n\n"
        f"Code: <code>{challenge.code}</code>\n"
        "This code expires in 5 minutes and can be used once."
    )
    sent = await send_telegram_alert(
        message,
        parse_mode="HTML",
        alert_id=f"frontend-auth-{int(challenge.expires_at.timestamp())}",
        ticker="ORACLE",
        alert_type="frontend_auth",
        priority=100,
        enqueue_on_failure=False,
    )
    if not sent:
        raise HTTPException(status_code=503, detail="Unable to send Telegram login code")
    return RequestCodeResponse(sent=True, expires_at=challenge.expires_at)


@router.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_frontend_code(payload: VerifyCodeRequest):
    token = frontend_auth_service.verify_code(payload.code)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired login code")
    return VerifyCodeResponse(token=token, expires_in_seconds=frontend_auth_service.session_ttl_seconds)


@router.post("/logout")
async def logout_frontend():
    # Frontend removes the token locally; this endpoint exists for a stable API surface.
    return {"ok": True, "logged_out_at": datetime.now(timezone.utc)}
