from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from src.core.agentic import sec_edgar_firehose
from src.core.agentic.sec_edgar_firehose import build_sec_event_headline, fetch_current_filings


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


def test_8k_with_clinical_supply_agreement_becomes_specific_catalyst():
    headline = build_sec_event_headline(
        {"ticker": "VERU", "company": "Veru Inc.", "form": "8-K", "accession": "x"},
        "Veru Inc. entered into a clinical supply agreement with Novo Nordisk A/S "
        "to support its Phase 2b PLATEAU obesity study using Wegovy.",
    )

    assert "clinical supply agreement" in headline
    assert "major pharma partner" in headline


class _Response:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, text: str):
        self.text = text

    async def get(self, url: str):
        return _Response(self.text)


def _entry(accession: str, updated: datetime) -> str:
    return f"""
    <entry>
      <title>8-K - VERU INC. (0000863894) (Filer)</title>
      <updated>{updated.isoformat()}</updated>
      <id>accession-number={accession}&lt;</id>
      <link href="https://www.sec.gov/Archives/edgar/data/863894/{accession}/veru-8k.htm"/>
      <summary>Veru entered into a clinical supply agreement with Novo Nordisk.</summary>
    </entry>
    """


def test_first_poll_emits_fresh_filing_instead_of_silently_seeding(monkeypatch):
    monkeypatch.setattr(sec_edgar_firehose, "_CIK_TICKER_MAP", {"0000863894": "VERU"})
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    text = f"<feed>{_entry('0000000000-26-000001', fresh)}</feed>"
    seen: set[str] = set()

    filings = asyncio.run(
        fetch_current_filings(
            seen,
            client=_Client(text),
            initial_emit_lookback_minutes=30,
        )
    )

    assert [f["ticker"] for f in filings] == ["VERU"]
    assert "0000000000-26-000001" in seen


def test_first_poll_only_seeds_old_filings(monkeypatch):
    monkeypatch.setattr(sec_edgar_firehose, "_CIK_TICKER_MAP", {"0000863894": "VERU"})
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    text = f"<feed>{_entry('0000000000-26-000002', old)}</feed>"
    seen: set[str] = set()

    filings = asyncio.run(
        fetch_current_filings(
            seen,
            client=_Client(text),
            initial_emit_lookback_minutes=30,
        )
    )

    assert filings == []
    assert "0000000000-26-000002" in seen


def test_max_to_emit_does_not_mark_overflow_accessions_seen(monkeypatch):
    monkeypatch.setattr(sec_edgar_firehose, "_CIK_TICKER_MAP", {"0000863894": "VERU"})
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    text = (
        "<feed>"
        f"{_entry('0000000000-26-000010', fresh)}"
        f"{_entry('0000000000-26-000011', fresh)}"
        "</feed>"
    )
    seen: set[str] = set()

    filings = asyncio.run(
        fetch_current_filings(
            seen,
            client=_Client(text),
            max_to_emit=1,
            initial_emit_lookback_minutes=30,
        )
    )

    assert [f["accession"] for f in filings] == ["0000000000-26-000010"]
    assert "0000000000-26-000010" in seen
    assert "0000000000-26-000011" not in seen
