from __future__ import annotations

from datetime import datetime, timezone

from src.core import sharecast_news
from src.core.sharecast_news import parse_sharecast_press_note_html


def test_sharecast_parser_prefers_explicit_symbol_before_name_resolution(monkeypatch):
    monkeypatch.setattr(sharecast_news, "_resolve_name_ticker", lambda _headline: "WRONG")
    html = """
    <html><body>
      <span>05 Jun</span>
      <a href="/press_note/market_reports/story">Bio Green Med (BGMS) to acquire Future NRG in share exchange</a>
    </body></html>
    """

    items = parse_sharecast_press_note_html(
        html,
        now=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].tickers == ["BGMS"]


def test_sharecast_parser_falls_back_to_company_name_resolution(monkeypatch):
    def fake_resolve(headline: str) -> str | None:
        if headline.startswith("Bitmine Immersion Technologies"):
            return "BMNR"
        return None

    monkeypatch.setattr(sharecast_news, "_resolve_name_ticker", fake_resolve)
    html = """
    <html><body>
      <span>05 Jun</span>
      <a href="/press_note/market_reports/bitmine">Bitmine Immersion Technologies announces strategic Ethereum treasury update</a>
    </body></html>
    """

    items = parse_sharecast_press_note_html(
        html,
        now=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].source == "Sharecast"
    assert items[0].tickers == ["BMNR"]


def test_sharecast_name_resolution_ignores_exchange_content_update_prefix(monkeypatch):
    from src.core import company_name_resolver

    def fake_resolve(headline: str) -> str | None:
        if headline.startswith("AstraZeneca"):
            return "AZN"
        return None

    monkeypatch.setattr(company_name_resolver, "resolve_company_ticker", fake_resolve)
    html = """
    <html><body>
      <span>05 Jun</span>
      <a href="/press_note/market_reports/azn">NYSE Content Update: AstraZeneca announces clinical supply agreement</a>
    </body></html>
    """

    items = parse_sharecast_press_note_html(
        html,
        now=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].tickers == ["AZN"]


def test_sharecast_parser_drops_name_that_cannot_resolve(monkeypatch):
    monkeypatch.setattr(sharecast_news, "_resolve_name_ticker", lambda _headline: None)
    html = """
    <html><body>
      <span>05 Jun</span>
      <a href="/press_note/market_reports/capricorn">Capricorn Energy updates shareholders</a>
    </body></html>
    """

    items = parse_sharecast_press_note_html(
        html,
        now=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    assert items == []


def test_sharecast_parser_ignores_nav_links(monkeypatch):
    monkeypatch.setattr(sharecast_news, "_resolve_name_ticker", lambda _headline: "NAV")
    html = """
    <html><body>
      <a href="/press_note/all">All</a>
      <a href="/press_note/market_reports/real">Real Company announces contract award</a>
    </body></html>
    """

    items = parse_sharecast_press_note_html(html)

    assert len(items) == 1
    assert items[0].headline == "Real Company announces contract award"
