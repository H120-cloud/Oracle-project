from datetime import datetime, timezone


def test_candidate_integer_like_float_fields_serialize_as_ints():
    from src.core.agentic.news_momentum_models import (
        CatalystCategory,
        CatalystSubType,
        NewsMomentumCandidate,
        NewsSource,
        SessionType,
    )

    candidate = NewsMomentumCandidate(
        ticker="TEST",
        headline="Test headline",
        source=NewsSource.FINVIZ,
        published_at=datetime.now(timezone.utc),
        session=SessionType.REGULAR,
        catalyst_category=CatalystCategory.UNKNOWN,
        catalyst_sub_type=CatalystSubType.OTHER,
        volume=36458.0,
        rank=2.0,
        sources_seen_count=3.0,
    )

    dumped = candidate.model_dump()

    assert dumped["volume"] == 36458
    assert dumped["rank"] == 2
    assert dumped["sources_seen_count"] == 3
    assert isinstance(dumped["volume"], int)
