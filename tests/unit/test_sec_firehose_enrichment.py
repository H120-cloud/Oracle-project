from __future__ import annotations

from datetime import datetime, timezone

from src.core.agentic.sec_edgar_firehose import build_sec_event_headline


def _filing():
    return {
        "ticker": "TEST",
        "company": "Test Corp",
        "form": "8-K",
        "accession": "0000000000-26-000001",
        "published_at": datetime.now(timezone.utc),
        "url": "https://www.sec.gov/example",
    }


def test_8k_with_financing_language_becomes_financing_catalyst():
    headline = build_sec_event_headline(
        _filing(),
        "The company entered into a registered direct offering with warrants.",
    )

    assert "financing / dilution" in headline


def test_8k_with_ma_language_becomes_ma_catalyst():
    headline = build_sec_event_headline(
        _filing(),
        "The company entered into a definitive agreement to be acquired in an all-cash transaction.",
    )

    assert "M&A / acquisition" in headline


def test_unavailable_filing_content_falls_back_safely():
    headline = build_sec_event_headline(_filing(), "")

    assert headline == "Test Corp filed SEC Form 8-K"

