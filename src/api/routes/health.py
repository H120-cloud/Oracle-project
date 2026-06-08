"""
Health check endpoint.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    from src.main import _startup_ready
    return {
        "status": "ok",
        "version": "5.0.0",
        "phase": "V5",
        "ready": _startup_ready,
    }
