"""
Top-level pytest configuration for the Oracle project.

Goals:
    - Make the project root importable as the package root for `src.*` imports.
    - Provide reusable fixtures for the news-momentum pipeline that DO NOT
      touch the production data files under data/agentic/.
    - Pin the random seed so tests are deterministic.
    - Surface — never swallow — exceptions during fixture construction.

This file is loaded automatically by pytest. Do not add behavior that
imports the live orchestrator here; orchestrator construction touches
disk and is too heavy for unit tests.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Path setup ─────────────────────────────────────────────────────────────
# Ensure the project root is on sys.path so `import src.core.agentic...`
# works regardless of the cwd pytest is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ── Determinism ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fixed_random_seed() -> None:
    """Pin RNG seed for every test. Eliminates flake from any code path
    that calls random.* without specifying a seed."""
    random.seed(42)
    try:
        import numpy as np
        np.random.seed(42)
    except ImportError:
        pass


# ── Golden-file loader ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def golden_historical_misses() -> List[Dict[str, Any]]:
    """
    Load the golden-file fixture of historical misses.

    Each entry is a dict with at minimum:
        ticker, headline, expected_category, expected_sub_type, source,
        notes, label_provenance, status (proposed | confirmed)

    These are the regression tests for the catalyst classifier. They
    define the contract: any change to the classifier MUST keep these
    classifications correct or be deliberately blessed by updating the
    fixture file.
    """
    path = FIXTURES_DIR / "historical_misses.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Golden fixture not found at {path}. "
            "This file is mandatory — do not skip the suite."
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Lightweight model fixtures ─────────────────────────────────────────────

@pytest.fixture
def make_candidate():
    """
    Factory for building a NewsMomentumCandidate with sensible defaults.
    Caller overrides only the fields they need. Keeps test setup terse.

    Usage:
        c = make_candidate(ticker="LNKS", headline="...", catalyst_sub_type=...)
    """
    from src.core.agentic.news_momentum_models import (
        NewsMomentumCandidate,
        CatalystCategory,
        CatalystSubType,
        SessionType,
        NewsSource,
        FloatCategory,
        MarketCapCategory,
    )

    def _factory(
        *,
        ticker: str = "TEST",
        headline: str = "Test Company Reports Q1 Earnings Beat",
        source: NewsSource = NewsSource.STOCKTITAN,
        catalyst_category: CatalystCategory = CatalystCategory.FINANCIAL,
        catalyst_sub_type: CatalystSubType = CatalystSubType.EARNINGS_BEAT,
        is_negative: bool = False,
        is_vague: bool = False,
        current_price: float = 5.00,
        market_cap: int = 50_000_000,
        float_shares: int = 5_000_000,
        move_pct: float = 12.0,
        rvol: float = 3.5,
        session: SessionType = SessionType.REGULAR,
        float_category: FloatCategory = FloatCategory.LOW,
        market_cap_category: MarketCapCategory = MarketCapCategory.MICRO,
        published_at: datetime | None = None,
        **overrides: Any,
    ) -> NewsMomentumCandidate:
        return NewsMomentumCandidate(
            ticker=ticker,
            headline=headline,
            source=source,
            published_at=published_at or datetime.now(timezone.utc),
            session=session,
            catalyst_category=catalyst_category,
            catalyst_sub_type=catalyst_sub_type,
            is_negative=is_negative,
            is_vague=is_vague,
            current_price=current_price,
            market_cap=market_cap,
            float_shares=float_shares,
            move_pct=move_pct,
            rvol=rvol,
            float_category=float_category,
            market_cap_category=market_cap_category,
            **overrides,
        )

    return _factory


@pytest.fixture
def make_telegram_record():
    """Factory for TelegramAlertRecord with reasonable defaults."""
    from src.core.agentic.news_momentum_models import (
        TelegramAlertRecord,
        CatalystSubType,
        SessionType,
    )

    def _factory(
        *,
        alert_id: str = "test_alert_001",
        ticker: str = "TEST",
        catalyst_type: CatalystSubType = CatalystSubType.EARNINGS_BEAT,
        session_type: SessionType = SessionType.REGULAR,
        price_at_alert: float = 5.00,
        news_impact_score: float = 65.0,
        expected_return_score: float = 60.0,
        continuation_probability: float = 70.0,
        multi_day_score: float = 60.0,
        sent_at: datetime | None = None,
        **overrides: Any,
    ) -> TelegramAlertRecord:
        return TelegramAlertRecord(
            alert_id=alert_id,
            ticker=ticker,
            sent_at=sent_at or datetime.now(timezone.utc),
            catalyst_type=catalyst_type,
            session_type=session_type,
            price_at_alert=price_at_alert,
            news_impact_score=news_impact_score,
            expected_return_score=expected_return_score,
            continuation_probability=continuation_probability,
            multi_day_score=multi_day_score,
            **overrides,
        )

    return _factory


@pytest.fixture
def make_shadow_record(make_telegram_record):
    """
    A shadow record is just a TelegramAlertRecord with `was_blocked` flagged
    and `block_reason` populated. Returns a factory mirroring that contract.
    """
    def _factory(*, was_blocked: bool = True, block_reason: str = "score_gate", **kw):
        rec = make_telegram_record(**kw)
        rec.was_blocked = was_blocked
        rec.block_reason = block_reason
        rec.alert_id = f"shadow_{rec.ticker}_{int(rec.sent_at.timestamp())}"
        return rec
    return _factory


# ── Isolation ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """
    Redirect the agentic DATA_DIR to a tmp path for any test that needs
    to exercise persistence without touching production JSON files.
    Yields the redirected path.
    """
    fake_data = tmp_path / "agentic"
    fake_data.mkdir(parents=True, exist_ok=True)
    # Modules read DATA_DIR at import time, so we patch each module's symbol.
    for modname in (
        "src.core.agentic.news_momentum_shadow_logger",
        "src.core.agentic.news_momentum_missed_learning",
    ):
        try:
            mod = __import__(modname, fromlist=["DATA_DIR"])
            monkeypatch.setattr(mod, "DATA_DIR", fake_data, raising=False)
        except ImportError:
            pass
    return fake_data
