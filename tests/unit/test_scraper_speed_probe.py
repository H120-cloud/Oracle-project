"""Tests for the on-demand news-scraper speed probe (offline, mocked sources)."""

import asyncio

import pytest

import src.services.scraper_speed_probe as probe

pytestmark = pytest.mark.unit


class _Summary:
    def __init__(self, news=0, blogs=0):
        self.news_items = [{} for _ in range(news)]
        self.blog_items = [{} for _ in range(blogs)]


def _fake_sources():
    async def fast():
        return _Summary(news=3, blogs=1)

    async def slow():
        await asyncio.sleep(0.05)
        return _Summary(news=1)

    async def boom():
        raise RuntimeError("feed down")

    return [("Fast", fast), ("Slow", slow), ("Boom", boom)]


def test_probe_reports_per_source_timing_and_errors(monkeypatch):
    monkeypatch.setattr(probe, "_build_sources", _fake_sources)
    out = asyncio.run(probe.probe_scraper_speeds(timeout=5))

    assert out["sources_tested"] == 3
    assert out["sources_ok"] == 2  # Boom failed
    by = {r["source"]: r for r in out["items"]}

    assert by["Fast"]["ok"] is True
    assert by["Fast"]["total_items"] == 4  # 3 news + 1 blog
    assert by["Boom"]["ok"] is False
    assert "feed down" in by["Boom"]["error"]

    # Results are sorted slowest-first so the bottleneck is at the top.
    durations = [r["duration_seconds"] for r in out["items"]]
    assert durations == sorted(durations, reverse=True)
    assert out["slowest_source"] == out["items"][0]["source"]


def test_probe_marks_timeouts(monkeypatch):
    async def hang():
        await asyncio.sleep(10)
        return _Summary()

    monkeypatch.setattr(probe, "_build_sources", lambda: [("Hang", hang)])
    out = asyncio.run(probe.probe_scraper_speeds(timeout=0.05))

    row = out["items"][0]
    assert row["ok"] is False
    assert "timed out" in row["error"]
