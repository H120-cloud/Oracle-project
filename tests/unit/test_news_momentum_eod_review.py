from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.core.agentic import news_momentum_eod_review as eod
from src.core.agentic.news_momentum_eod_review import NewsMomentumEODReviewer
from src.utils.atomic_json import save_json_file


pytestmark = [pytest.mark.unit]


class _Orchestrator:
    _candidates = []

    def get_active_candidates(self):
        return []


def test_eod_review_uses_persisted_report_as_restart_guard(tmp_path, monkeypatch):
    report_file = tmp_path / "news_momentum_eod_reports.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_json_file(report_file, [{"date": today, "summary": {"total_big_movers": 1}}])

    monkeypatch.setattr(eod, "EOD_REPORT_FILE", report_file)

    called = {"fetch": 0}

    def fetch_snapshot(max_results=30):
        called["fetch"] += 1
        return []

    monkeypatch.setattr(
        "src.core.agentic.finviz_universe.fetch_finviz_top_gainers_snapshot",
        fetch_snapshot,
    )

    result = asyncio.run(NewsMomentumEODReviewer(_Orchestrator()).run_review(force=False))

    assert result == {"status": "already_ran", "date": today}
    assert called["fetch"] == 0


def test_eod_review_persists_no_movers_marker(tmp_path, monkeypatch):
    report_file = tmp_path / "news_momentum_eod_reports.json"
    monkeypatch.setattr(eod, "EOD_REPORT_FILE", report_file)
    monkeypatch.setattr(
        "src.core.agentic.finviz_universe.fetch_finviz_top_gainers_snapshot",
        lambda max_results=30: [],
    )

    result = asyncio.run(NewsMomentumEODReviewer(_Orchestrator()).run_review(force=False))

    assert result["status"] == "no_movers"
    assert eod.load_json_file(report_file, default=[])[0]["date"] == result["date"]


def test_eod_summary_uses_stable_telegram_alert_id(tmp_path, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        eod,
        "EOD_TELEGRAM_SENT_FILE",
        tmp_path / "news_momentum_eod_telegram_sent.json",
    )

    async def fake_send(message, **kwargs):
        sent["message"] = message
        sent.update(kwargs)
        return True

    monkeypatch.setattr("src.services.telegram_service.send_telegram_alert", fake_send)

    report = {
        "date": "2026-06-05",
        "missed_discovery": [],
        "missed_alert": [],
        "summary": {
            "total_big_movers": 1,
            "caught_count": 1,
            "alert_rate_pct": 100.0,
            "missed_alert_count": 0,
            "missed_discovery_count": 0,
            "discovery_rate_pct": 100.0,
        },
    }

    asyncio.run(NewsMomentumEODReviewer(_Orchestrator())._send_summary_telegram(report))

    assert sent["alert_id"] == "news_momentum_eod_2026-06-05"
    assert sent["alert_type"] == "news_momentum_eod"
    assert sent["ticker"] == "EOD"


def test_eod_summary_telegram_only_sends_once_per_date(tmp_path, monkeypatch):
    sent = []
    marker_file = tmp_path / "news_momentum_eod_telegram_sent.json"
    monkeypatch.setattr(eod, "EOD_TELEGRAM_SENT_FILE", marker_file)

    async def fake_send(message, **kwargs):
        sent.append(kwargs["alert_id"])
        return True

    monkeypatch.setattr("src.services.telegram_service.send_telegram_alert", fake_send)

    report = {
        "date": "2026-06-05",
        "missed_discovery": [{"ticker": "SPRC", "change_pct": 25.0}],
        "missed_alert": [],
        "summary": {
            "total_big_movers": 1,
            "caught_count": 0,
            "alert_rate_pct": 0.0,
            "missed_alert_count": 0,
            "missed_discovery_count": 1,
            "discovery_rate_pct": 0.0,
        },
    }

    reviewer = NewsMomentumEODReviewer(_Orchestrator())
    asyncio.run(reviewer._send_summary_telegram(report))
    asyncio.run(reviewer._send_summary_telegram(report))
    asyncio.run(reviewer._send_summary_telegram(report))

    assert sent == ["news_momentum_eod_2026-06-05"]
    marker = eod.load_json_file(marker_file, default={})
    assert marker["2026-06-05"]["alert_id"] == "news_momentum_eod_2026-06-05"


def test_eod_summary_existing_marker_blocks_send(tmp_path, monkeypatch):
    marker_file = tmp_path / "news_momentum_eod_telegram_sent.json"
    monkeypatch.setattr(eod, "EOD_TELEGRAM_SENT_FILE", marker_file)
    save_json_file(
        marker_file,
        {"2026-06-05": {"alert_id": "news_momentum_eod_2026-06-05"}},
    )

    async def fake_send(message, **kwargs):
        raise AssertionError("existing marker must block duplicate EOD Telegram")

    monkeypatch.setattr("src.services.telegram_service.send_telegram_alert", fake_send)

    report = {
        "date": "2026-06-05",
        "missed_discovery": [],
        "missed_alert": [],
        "summary": {
            "total_big_movers": 1,
            "caught_count": 0,
            "alert_rate_pct": 0.0,
            "missed_alert_count": 0,
            "missed_discovery_count": 1,
            "discovery_rate_pct": 0.0,
        },
    }

    asyncio.run(NewsMomentumEODReviewer(_Orchestrator())._send_summary_telegram(report))
