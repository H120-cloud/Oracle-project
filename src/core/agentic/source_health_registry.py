"""Shared live source-health tracker for scanner loops and API routes."""

from __future__ import annotations

from src.core.agentic.source_health import SourceHealthTracker


source_health_tracker = SourceHealthTracker()
