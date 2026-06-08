"""Tests for the read-only Admin Diagnostics service layer.

These exercise the pure parse/filter/paginate/derive functions against
temp JSONL files (no production data, no app startup). The service must never
write — it only reads diagnostics artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services import admin_diagnostics as ad

pytestmark = pytest.mark.unit


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# ── Shared helpers ─────────────────────────────────────────────────────────

def test_missing_file_returns_empty(tmp_path):
    out = ad.read_news_latency(path=tmp_path / "nope.jsonl")
    assert out["total"] == 0
    assert out["items"] == []


def test_pagination(tmp_path):
    rows = [{"ticker": f"T{i}", "published_at": f"2026-06-0{1}T00:0{i}:00+00:00",
             "source": "Finviz", "alert_sent": True} for i in range(9)]
    p = _write_jsonl(tmp_path / "lat.jsonl", rows)
    out = ad.read_news_latency(path=p, page=2, page_size=4)
    assert out["total"] == 9
    assert out["page"] == 2
    assert out["page_size"] == 4
    assert len(out["items"]) == 4


# ── News latency ───────────────────────────────────────────────────────────

def _lat_row(ticker="AAPL", source="StockTitan", pub=None, sent=True,
             blocked=None, fast=False, total=None):
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    pub = pub or now
    fetched = pub + timedelta(seconds=2)
    classified = fetched + timedelta(seconds=1)
    gate = classified + timedelta(seconds=1)
    sent_at = gate + timedelta(seconds=1) if sent else None
    return {
        "ticker": ticker,
        "headline": f"{ticker} announces something",
        "source": source,
        "published_at": pub.isoformat(),
        "fetched_at": fetched.isoformat(),
        "parsed_at": fetched.isoformat(),
        "candidate_created_at": fetched.isoformat(),
        "classified_at": classified.isoformat(),
        "scored_at": gate.isoformat(),
        "gate_decision_at": gate.isoformat(),
        "telegram_enqueue_at": gate.isoformat() if sent else None,
        "telegram_sent_at": sent_at.isoformat() if sent_at else None,
        "blocked_reason": blocked,
        "alert_sent": sent,
        "fast_path": fast,
        "total_latency_seconds": total if total is not None else 5.0,
    }


def test_latency_ticker_filter(tmp_path):
    p = _write_jsonl(tmp_path / "lat.jsonl", [_lat_row("AAPL"), _lat_row("TSLA")])
    out = ad.read_news_latency(path=p, ticker="tsla")
    assert out["total"] == 1
    assert out["items"][0]["ticker"] == "TSLA"


def test_latency_derived_metrics(tmp_path):
    p = _write_jsonl(tmp_path / "lat.jsonl", [_lat_row("AAPL")])
    item = ad.read_news_latency(path=p)["items"][0]
    d = item["derived"]
    assert d["source_fetch_latency_seconds"] == 2.0
    assert d["classification_latency_seconds"] == 1.0
    assert d["telegram_latency_seconds"] == 1.0
    assert d["total_latency_seconds"] == 5.0


def test_latency_delayed_flag_over_60s(tmp_path):
    p = _write_jsonl(tmp_path / "lat.jsonl", [
        _lat_row("FAST", total=5.0),
        _lat_row("SLOW", total=120.0),
    ])
    out = ad.read_news_latency(path=p, status="delayed")
    tickers = {i["ticker"] for i in out["items"]}
    assert tickers == {"SLOW"}


def test_latency_blocked_categories(tmp_path):
    rows = [
        _lat_row("DUP", sent=False, blocked="duplicate"),
        _lat_row("OLD", sent=False, blocked="stale_published(13.0h)"),
        _lat_row("BAD", sent=False, blocked="bad_ticker"),
        _lat_row("OK", sent=True, blocked=None),
    ]
    p = _write_jsonl(tmp_path / "lat.jsonl", rows)

    assert {i["ticker"] for i in ad.read_news_latency(path=p, status="duplicate_blocked")["items"]} == {"DUP"}
    assert {i["ticker"] for i in ad.read_news_latency(path=p, status="freshness_blocked")["items"]} == {"OLD"}
    assert {i["ticker"] for i in ad.read_news_latency(path=p, status="unresolved_ticker")["items"]} == {"BAD"}
    assert {i["ticker"] for i in ad.read_news_latency(path=p, status="blocked")["items"]} == {"DUP", "OLD", "BAD"}


def test_latency_summary_and_charts(tmp_path):
    rows = [
        _lat_row("A", source="StockTitan", sent=True, total=5.0),
        _lat_row("B", source="Finviz", sent=False, blocked="duplicate"),
        _lat_row("C", source="Finviz", sent=True, total=90.0),
    ]
    p = _write_jsonl(tmp_path / "lat.jsonl", rows)
    out = ad.read_news_latency(path=p)
    s = out["summary"]
    assert s["total"] == 3
    assert s["alerted"] == 2
    assert s["blocked"] == 1
    assert s["delayed"] == 1
    charts = out["charts"]
    assert charts["alerts_by_source"]["Finviz"] == 2
    assert charts["blocked_reason_distribution"]["duplicate"] == 1
    assert "Finviz" in charts["avg_latency_by_source"]


# ── Rocket shadow ──────────────────────────────────────────────────────────

def _rocket_row(ticker, runner, major, monster, rank, conf="HIGH",
                er=50.0, ni=50.0, logged="2026-06-05T12:00:00+00:00"):
    return {
        "logged_at": logged,
        "source_pipeline": "shadow",
        "ticker": ticker,
        "headline": f"{ticker} news",
        "binary_runner_probability": runner,
        "binary_major_plus_probability": major,
        "binary_monster_plus_probability": monster,
        "rocket_rank_score": rank,
        "model_version": "rocket_catboost_baseline_shadow:v1",
        "feature_null_count": 3,
        "prediction_confidence": conf,
        "expected_return_score": er,
        "news_impact_score": ni,
    }


def test_rocket_top_monster_view(tmp_path):
    rows = [
        _rocket_row("A", 0.5, 0.4, 0.10, 0.3),
        _rocket_row("B", 0.6, 0.5, 0.80, 0.6),
        _rocket_row("C", 0.4, 0.3, 0.40, 0.35),
    ]
    p = _write_jsonl(tmp_path / "rk.jsonl", rows)
    out = ad.read_rocket_shadow(path=p)
    top_monster = out["views"]["highest_monster"]
    assert top_monster[0]["ticker"] == "B"


def test_rocket_confidence_filter(tmp_path):
    rows = [_rocket_row("A", 0.5, 0.5, 0.5, 0.5, conf="HIGH"),
            _rocket_row("B", 0.2, 0.2, 0.2, 0.2, conf="LOW")]
    p = _write_jsonl(tmp_path / "rk.jsonl", rows)
    out = ad.read_rocket_shadow(path=p, status="HIGH")
    assert {i["ticker"] for i in out["items"]} == {"A"}


def test_rocket_rank_comparison_divergence(tmp_path):
    # A: CatBoost loves it (rank .9) but rules hate it (er 10) -> catboost_high_rules_low
    # B: rules love it (er 95) but CatBoost low (rank .1) -> rules_high_catboost_low
    rows = [
        _rocket_row("A", 0.9, 0.9, 0.9, 0.90, er=10.0, ni=10.0),
        _rocket_row("B", 0.1, 0.1, 0.1, 0.10, er=95.0, ni=95.0),
    ]
    p = _write_jsonl(tmp_path / "rk.jsonl", rows)
    cmp = ad.read_rocket_shadow(path=p)["comparison"]
    assert "A" in {i["ticker"] for i in cmp["catboost_high_rules_low"]}
    assert "B" in {i["ticker"] for i in cmp["rules_high_catboost_low"]}


# ── Telegram outbox ────────────────────────────────────────────────────────

def _outbox_row(alert_id, ticker, status, attempts=0, created="2026-06-05T12:00:00+00:00",
                sent_at=None, last_error=""):
    resp = {"ok": True, "result": {"date": sent_at}} if sent_at else None
    return {
        "alert_id": alert_id,
        "ticker": ticker,
        "alert_type": "news_momentum",
        "created_at": created,
        "status": status,
        "attempts": attempts,
        "next_retry_at": created,
        "last_error": last_error,
        "telegram_response": resp,
    }


def test_outbox_status_filter_and_summary(tmp_path):
    rows = [
        _outbox_row("a", "AAA", "sent", attempts=1),
        _outbox_row("b", "BBB", "failed", attempts=3, last_error="timeout"),
        _outbox_row("c", "CCC", "pending", attempts=0),
        _outbox_row("d", "DDD", "dead_letter", attempts=6, last_error="429"),
    ]
    p = _write_jsonl(tmp_path / "ob.jsonl", rows)

    out = ad.read_telegram_outbox(path=p, status="dead_letter")
    assert {i["ticker"] for i in out["items"]} == {"DDD"}

    s = ad.read_telegram_outbox(path=p)["summary"]
    assert s["sent"] == 1
    assert s["failed"] == 1
    assert s["pending"] == 1
    assert s["dead_letter"] == 1
    assert s["total"] == 4
    assert s["retrying"] == 1
    assert s["success_rate"] == pytest.approx(0.25)


def test_in_range_rejects_invalid_date_strings():
    assert ad._in_range("2026-06-05T12:00:00+00:00", "not-a-date", None) is False
    assert ad._in_range("2026-06-05T12:00:00+00:00", None, "also-bad") is False
    assert ad._in_range("2026-06-05T12:00:00+00:00", "bad", "worse") is False
    # valid dates still work
    assert ad._in_range("2026-06-05T12:00:00+00:00", "2026-06-01T00:00:00+00:00", "2026-06-10T00:00:00+00:00") is True


def test_unprocessed_item_marked_incomplete(tmp_path):
    row = _lat_row("UNPROC", sent=False, blocked=None)
    # Remove gate/scored/telegram timestamps so total is None
    row.pop("scored_at", None)
    row.pop("gate_decision_at", None)
    row.pop("telegram_sent_at", None)
    row.pop("telegram_enqueue_at", None)
    p = _write_jsonl(tmp_path / "lat.jsonl", [row])
    out = ad.read_news_latency(path=p)
    assert out["items"][0]["status"] == "incomplete"
    assert out["items"][0]["is_delayed"] is False


# ── Optional endpoints reuse the latency reader ────────────────────────────

def test_blocked_and_fast_watch_views(tmp_path):
    rows = [
        _lat_row("OK", sent=True, fast=False),
        _lat_row("BLK", sent=False, blocked="duplicate"),
        _lat_row("FAST", sent=True, fast=True),
    ]
    p = _write_jsonl(tmp_path / "lat.jsonl", rows)
    assert {i["ticker"] for i in ad.read_blocked_alerts(path=p)["items"]} == {"BLK"}
    assert {i["ticker"] for i in ad.read_fast_watch_alerts(path=p)["items"]} == {"FAST"}


def test_source_health_aggregates(tmp_path):
    rows = [
        _lat_row("A", source="Finviz", sent=True, total=5.0),
        _lat_row("B", source="Finviz", sent=False, blocked="duplicate"),
        _lat_row("C", source="SEC", sent=True, total=10.0),
    ]
    p = _write_jsonl(tmp_path / "lat.jsonl", rows)
    out = ad.read_source_health(path=p)
    by_source = {s["source"]: s for s in out["items"]}
    assert by_source["Finviz"]["total"] == 2
    assert by_source["Finviz"]["blocked"] == 1
    assert by_source["SEC"]["alerted"] == 1


# ── Route layer (read-only GET endpoints, no app lifespan) ─────────────────

def _client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routes import admin_diagnostics as route

    lat = _write_jsonl(tmp_path / "lat.jsonl", [_lat_row("AAPL"), _lat_row("TSLA", sent=False, blocked="duplicate")])
    rk = _write_jsonl(tmp_path / "rk.jsonl", [_rocket_row("AAPL", 0.5, 0.5, 0.5, 0.5)])
    ob = _write_jsonl(tmp_path / "ob.jsonl", [_outbox_row("a", "AAA", "sent", attempts=1)])
    monkeypatch.setattr(ad, "news_latency_path", lambda: lat)
    monkeypatch.setattr(ad, "rocket_shadow_path", lambda: rk)
    monkeypatch.setattr(ad, "telegram_outbox_path", lambda: ob)

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "admin_diagnostics_dashboard_report.md").write_text("# Admin Diagnostics\nhello world", encoding="utf-8")
    monkeypatch.setattr(ad, "docs_dir", lambda: docs)

    app = FastAPI()
    app.include_router(route.router, prefix="/api/v1")
    return TestClient(app)


def test_route_news_latency_ok(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/news-latency")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert "summary" in body and "charts" in body


def test_route_news_latency_ticker_filter(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/news-latency", params={"ticker": "tsla"})
    assert r.status_code == 200
    assert {i["ticker"] for i in r.json()["items"]} == {"TSLA"}


def test_route_rocket_and_outbox_ok(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    rk = client.get("/api/v1/admin/rocket-shadow")
    assert rk.status_code == 200
    assert "views" in rk.json() and "comparison" in rk.json()
    ob = client.get("/api/v1/admin/telegram-outbox")
    assert ob.status_code == 200
    assert ob.json()["summary"]["sent"] == 1


def test_route_optional_endpoints_ok(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for path in ("/api/v1/admin/source-health",
                 "/api/v1/admin/blocked-alerts",
                 "/api/v1/admin/fast-watch-alerts"):
        assert client.get(path).status_code == 200


def test_route_is_read_only_no_post(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # No write verbs are defined -> 405 Method Not Allowed.
    assert client.post("/api/v1/admin/news-latency").status_code == 405
    assert client.delete("/api/v1/admin/telegram-outbox").status_code == 405


# ── Download feature ────────────────────────────────────────────────────────

def test_download_csv_export_works(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/download/news-latency", params={"format": "csv"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in r.headers["content-disposition"]
    body = r.text
    assert "ticker" in body.splitlines()[0]  # header row
    assert "AAPL" in body


def test_download_jsonl_works(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/download/rocket-shadow", params={"format": "jsonl"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert json.loads(lines[0])["ticker"] == "AAPL"


def test_download_bad_format_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/admin/download/news-latency", params={"format": "exe"}).status_code == 400


def test_reports_listing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/reports")
    assert r.status_code == 200
    by_name = {i["name"]: i for i in r.json()["items"]}
    assert "admin_diagnostics_dashboard_report.md" in by_name
    rep = by_name["admin_diagnostics_dashboard_report.md"]
    assert rep["exists"] is True
    assert rep["type"] == "markdown"
    assert rep["size_bytes"] > 0


def test_valid_report_download_works(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/v1/admin/download/report/admin_diagnostics_dashboard_report.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="admin_diagnostics_dashboard_report.md"' in r.headers["content-disposition"]
    assert "hello world" in r.text


def test_invalid_report_name_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/v1/admin/download/report/secret.md").status_code == 404
    assert client.get("/api/v1/admin/download/report/oracle.db").status_code == 404


def test_path_traversal_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for evil in (
        "..%2F..%2F.env",
        "..%2F..%2Foracle.db",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "....//....//.env",
    ):
        assert client.get(f"/api/v1/admin/download/report/{evil}").status_code in (404, 400)


def test_allowlisted_but_missing_report_is_404(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # allowlisted name, but the doc file was never generated in this temp docs dir
    assert client.get("/api/v1/admin/download/report/telegram_outbox_reliability.md").status_code == 404


# ── Service-level export helpers ────────────────────────────────────────────

def test_rows_to_csv_and_jsonl_pure():
    rows = [{"ticker": "AAPL", "derived": {"total_latency_seconds": 5.0}, "tags": ["a", "b"]}]
    csv_out = ad.rows_to_csv(rows)
    assert "derived_total_latency_seconds" in csv_out.splitlines()[0]
    assert "AAPL" in csv_out
    jsonl_out = ad.rows_to_jsonl(rows)
    assert json.loads(jsonl_out.strip())["ticker"] == "AAPL"


def test_export_unknown_kind_or_format_raises():
    with pytest.raises(ValueError):
        ad.export_diagnostics("nope", "csv")
    with pytest.raises(ValueError):
        ad.export_diagnostics("news-latency", "pdf")


def test_resolve_report_rejects_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(ad, "docs_dir", lambda: tmp_path)
    assert ad.resolve_report("../../etc/passwd") is None
    assert ad.resolve_report("anything.md") is None
