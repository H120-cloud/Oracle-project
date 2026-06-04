import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from src.core.agentic.news_momentum_models import (
    BullBearCase,
    CatalystCategory,
    CatalystSubType,
    MultiDayClass,
    NewsEvent,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    OracleAction,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


def _candidate(ticker: str) -> NewsMomentumCandidate:
    return NewsMomentumCandidate(
        ticker=ticker,
        headline=f"{ticker} wins approval",
        source=NewsSource.FINVIZ,
        published_at=datetime.now(timezone.utc),
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        session=SessionType.REGULAR,
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
        current_price=5.0,
        news_impact_score=80.0,
        expected_return_score=80.0,
        continuation_probability=80.0,
    )


def _fresh_bullish_candidate(ticker: str = "FAST") -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    candidate = _candidate(ticker)
    candidate.headline = f"{ticker} announces FDA approval for breakthrough therapy"
    candidate.published_at = now - timedelta(seconds=60)
    candidate.detected_at = now - timedelta(seconds=30)
    candidate.news_impact_score = 10.0
    candidate.expected_return_score = 10.0
    candidate.continuation_probability = 10.0
    candidate.trap_risk = 0.0
    candidate.dilution_risk = 0.0
    return candidate


def _minimal_gate_orchestrator() -> NewsMomentumOrchestrator:
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    return orch


def test_old_published_headline_detected_now_does_not_get_first_mover_boost():
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("OLDNEWS")
    candidate.published_at = datetime.now(timezone.utc) - timedelta(hours=2)
    candidate.detected_at = datetime.now(timezone.utc) - timedelta(seconds=20)

    orch._should_send_telegram_impl(candidate, adaptive={})

    assert getattr(candidate, "_first_mover", False) is False
    assert candidate.freshness_confidence == "HIGH"
    assert candidate.published_age_seconds is not None
    assert candidate.detected_age_seconds is not None


def test_fresh_published_and_detected_headline_gets_first_mover_boost():
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("FRESH")

    orch._should_send_telegram_impl(candidate, adaptive={})

    assert getattr(candidate, "_first_mover", False) is True
    assert candidate.freshness_confidence == "HIGH"


def test_missing_published_at_does_not_get_first_mover_boost():
    orch = _minimal_gate_orchestrator()
    candidate = _fresh_bullish_candidate("NOPUB")
    candidate.published_at = None

    orch._should_send_telegram_impl(candidate, adaptive={})

    assert getattr(candidate, "_first_mover", False) is False
    assert candidate.freshness_confidence == "LOW"


def test_scan_sends_fresh_candidates_before_refreshing_old_candidates(monkeypatch):
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._scan_counter = 1
    orch._candidate_by_ticker = {"OLD": _candidate("OLD")}
    orch._candidate_by_ticker["OLD"].last_refresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    orch._catalyst_learning = type(
        "CatalystLearning",
        (),
        {"get_catalyst_type_stats": lambda self: {}},
    )()
    orch._telegram_learning = type(
        "TelegramLearning",
        (),
        {"get_adaptive_thresholds": lambda self: {}},
    )()
    orch._sector_hype = None

    order = []
    fresh = _candidate("SPRC")

    monkeypatch.setattr(orch, "_detect_session", lambda: SessionType.REGULAR)
    monkeypatch.setattr(orch, "_merge_event_velocity", lambda event: event)
    monkeypatch.setattr(orch, "_check_duplicate", lambda event: event)
    monkeypatch.setattr(orch, "_save_candidates", lambda: None)
    monkeypatch.setattr(orch, "_prune_old_candidates", lambda: None)

    async def process_event(event, session, hist_dict, adaptive):
        order.append("process_fresh")
        return fresh

    async def refresh_candidate(candidate, hist_dict):
        order.append(f"refresh_{candidate.ticker}")

    async def send_candidates(candidates, adaptive):
        order.append(f"send_{','.join(c.ticker for c in candidates)}")
        for candidate in candidates:
            candidate.telegram_sent = True
        return len(candidates)

    monkeypatch.setattr(orch, "_process_event", process_event)
    monkeypatch.setattr(orch, "_refresh_candidate", refresh_candidate)
    monkeypatch.setattr(orch, "_send_telegram_for_candidates", send_candidates)

    event = NewsEvent(
        ticker="SPRC",
        headline="SciSparc receives conditional approval",
        source=NewsSource.FINVIZ,
        published_at=datetime.now(timezone.utc),
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
    )

    result = asyncio.run(orch.scan([event]))

    assert result.telegram_alerts_sent >= 1
    assert order.index("send_SPRC") < order.index("refresh_OLD")


def test_send_telegram_success_survives_learning_record_failure(monkeypatch):
    orch = object.__new__(NewsMomentumOrchestrator)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._telegram_learning = type(
        "TelegramLearning",
        (),
        {"record_alert": lambda self, record: (_ for _ in ()).throw(RuntimeError("boom"))},
    )()

    monkeypatch.setattr(orch, "_format_telegram_message", lambda candidate: "alert")
    monkeypatch.setattr(orch, "_headline_hash", lambda headline: "hash")
    monkeypatch.setattr(orch, "_save_cooldowns", lambda: None)
    monkeypatch.setattr(orch, "_save_headline_cooldowns", lambda: None)
    monkeypatch.setattr(orch, "_sec_record_fields", lambda candidate: {})
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.send_telegram_alert",
        lambda *args, **kwargs: _async_true(),
    )

    candidate = _candidate("SPRC")

    assert asyncio.run(orch._send_telegram_alert(candidate)) is True
    assert candidate.telegram_sent is True
    assert "SPRC" in orch._alert_cooldown


def test_process_event_existing_ticker_refreshes_without_name_error(monkeypatch):
    orch = object.__new__(NewsMomentumOrchestrator)
    existing = _candidate("SPRC")
    existing.detected_at = datetime.now(timezone.utc)
    orch._candidate_by_ticker = {"SPRC": existing}

    refreshed = []

    async def refresh_candidate(candidate, hist_dict):
        refreshed.append(candidate.ticker)

    monkeypatch.setattr(orch, "_refresh_candidate", refresh_candidate)

    event = NewsEvent(
        ticker="SPRC",
        headline="SciSparc receives conditional approval",
        source=NewsSource.FINVIZ,
        published_at=datetime.now(timezone.utc),
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.FDA_APPROVAL,
    )

    result = asyncio.run(
        orch._process_event(
            event,
            SessionType.REGULAR,
            historical_stats=None,
            adaptive={},
        )
    )

    assert result is existing
    assert refreshed == ["SPRC"]


def test_process_event_promotes_existing_candidate_when_catalyst_becomes_high_conviction(monkeypatch):
    orch = object.__new__(NewsMomentumOrchestrator)
    detected_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    existing = NewsMomentumCandidate(
        ticker="PRFX",
        headline="PainReform provides corporate update",
        source=NewsSource.STOCKTITAN,
        published_at=detected_at,
        detected_at=detected_at,
        session=SessionType.PREMARKET,
        catalyst_category=CatalystCategory.UNKNOWN,
        catalyst_sub_type=CatalystSubType.OTHER,
        current_price=2.31,
        prior_price=2.24,
        move_pct=2.95,
        news_impact_score=43.4,
        expected_return_score=45.0,
        continuation_probability=45.0,
    )
    orch._candidate_by_ticker = {"PRFX": existing}
    orch._candidates = [existing]
    orch._telegram_learning = type(
        "TelegramLearning",
        (),
        {"get_catalyst_quality": lambda self, sub_type: {"insufficient": True}},
    )()
    orch._big_winner_ml = type(
        "BigWinner",
        (),
        {
            "predict": lambda self, candidate: SimpleNamespace(
                rocket_probability=0.0,
                used_model=False,
            )
        },
    )()

    refreshed = []

    async def enrich(candidate):
        candidate.current_price = 2.31
        candidate.prior_price = 2.24
        candidate.move_pct = 2.95

    async def refresh_candidate(candidate, hist_dict):
        refreshed.append(candidate.ticker)

    monkeypatch.setattr(orch, "_enrich_with_market_data", enrich)
    monkeypatch.setattr(orch, "_refresh_candidate", refresh_candidate)
    monkeypatch.setattr(orch, "_compute_impact_score", lambda candidate: 61.0)
    monkeypatch.setattr(orch, "_compute_reaction_score", lambda candidate: 20.0)
    monkeypatch.setattr(orch, "_apply_sec_intelligence", lambda candidate: None)
    monkeypatch.setattr(orch, "_generate_bull_bear", lambda candidate: BullBearCase())
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.compute_expected_return_score",
        lambda candidate, stats: SimpleNamespace(score=60.0),
    )
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.compute_continuation_probability",
        lambda candidate, stats: SimpleNamespace(same_day_continuation=60.0),
    )
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.compute_multi_day_continuation",
        lambda candidate, cp, stats: SimpleNamespace(
            multi_day_score=60.0,
            next_day_continuation_probability=60.0,
            two_day_continuation_probability=55.0,
            five_day_continuation_probability=50.0,
            next_day_gap_up_probability=45.0,
            swing_trade_quality_score=60.0,
            exhaustion_probability=10.0,
            classification=MultiDayClass.POSSIBLE_CONTINUATION,
        ),
    )
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.determine_oracle_action",
        lambda candidate, cp, md: OracleAction.WATCH,
    )
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.estimate_move_range",
        lambda candidate: {
            "conservative_pct": 15.0,
            "bullish_pct": 35.0,
            "extreme_pct": 80.0,
        },
    )

    event = NewsEvent(
        ticker="PRFX",
        headline="PainReform announces commercial launch of its lead drug",
        source=NewsSource.STOCKTITAN,
        published_at=detected_at,
        detected_at=detected_at,
        catalyst_category=CatalystCategory.BIOTECH,
        catalyst_sub_type=CatalystSubType.DRUG_LAUNCH,
        is_negative=False,
        is_vague=False,
    )

    result = asyncio.run(
        orch._process_event(
            event,
            SessionType.PREMARKET,
            historical_stats=None,
            adaptive={},
        )
    )

    assert refreshed == []
    assert result is not existing
    assert result.catalyst_sub_type == CatalystSubType.DRUG_LAUNCH
    assert result.news_impact_score == 61.0
    assert orch._candidate_by_ticker["PRFX"] is result


def test_gate_allows_prfx_style_high_conviction_before_three_percent_move(monkeypatch):
    orch = _gate_orchestrator(monkeypatch)
    candidate = _candidate("PRFX")
    candidate.headline = "PainReform announces commercial launch of its lead drug"
    candidate.catalyst_category = CatalystCategory.BIOTECH
    candidate.catalyst_sub_type = CatalystSubType.DRUG_LAUNCH
    candidate.current_price = 2.31
    candidate.prior_price = 2.24
    candidate.move_pct = 2.95
    candidate.news_impact_score = 61.0
    candidate.expected_return_score = 50.0
    candidate.continuation_probability = 50.0
    candidate.detected_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    assert orch._should_send_telegram(candidate, adaptive={}) is True


def test_gate_allows_olox_style_borderline_acquisition_score(monkeypatch):
    orch = _gate_orchestrator(monkeypatch)
    candidate = _candidate("OLOX")
    candidate.headline = "Olenox to be acquired in all-cash transaction at premium"
    candidate.catalyst_category = CatalystCategory.CORPORATE
    candidate.catalyst_sub_type = CatalystSubType.ACQUISITION
    candidate.current_price = 2.40
    candidate.prior_price = 2.20
    candidate.move_pct = 9.09
    candidate.news_impact_score = 57.3
    candidate.expected_return_score = 49.9
    candidate.continuation_probability = 50.0
    candidate.detected_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    assert orch._should_send_telegram(candidate, adaptive={}) is True


def _gate_orchestrator(monkeypatch):
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    orch._sector_hype = None
    orch._shadow_logger = type(
        "ShadowLogger",
        (),
        {"log_candidate": lambda self, *args, **kwargs: None},
    )()
    orch._ml_engine = type(
        "MLEngine",
        (),
        {
            "predict": lambda self, candidate: SimpleNamespace(
                win_probability=0.5,
                confidence=0.0,
                used_model=False,
                model_version=None,
            )
        },
    )()
    orch._big_winner_ml = type(
        "BigWinner",
        (),
        {
            "predict": lambda self, candidate: SimpleNamespace(
                rocket_probability=0.0,
                used_model=False,
            )
        },
    )()

    monkeypatch.setattr(orch, "_is_bad_ticker", lambda ticker: False)
    monkeypatch.setattr(
        "src.core.agentic.news_momentum_orchestrator.assess_winner",
        lambda *args, **kwargs: SimpleNamespace(
            should_alert=True,
            block_reason=None,
            ml_tier=SimpleNamespace(label="STANDARD"),
            runner=SimpleNamespace(score=3),
            priority_score=50.0,
            sector_multiplier=1.0,
        ),
    )
    return orch


async def _async_true():
    return True
