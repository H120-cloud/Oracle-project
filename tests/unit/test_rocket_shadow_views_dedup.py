"""Rocket-shadow diagnostics views must show one row per ticker.

The shadow scorer appends a prediction row for the same ticker on every scan
cycle, so the raw JSONL holds many rows per ticker. The top-10 views ranked raw
rows, so 2-3 hot tickers' repeated rows filled all 10 slots.
"""

import json

import pytest

from src.services.admin_diagnostics import read_rocket_shadow


def _write_rows(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _row(ticker, score, logged_at, monster=0.1, major=0.2, conf="HIGH"):
    return {
        "ticker": ticker,
        "rocket_rank_score": score,
        "binary_monster_plus_probability": monster,
        "binary_major_plus_probability": major,
        "prediction_confidence": conf,
        "logged_at": logged_at,
    }


@pytest.mark.unit
def test_top_views_dedupe_repeated_ticker_rows(tmp_path):
    path = tmp_path / "shadow.jsonl"
    rows = []
    # 3 hot tickers re-logged 10x each (as the shadow scorer does every cycle)
    for i in range(10):
        ts = f"2026-06-10T12:{i:02d}:00+00:00"
        rows.append(_row("AAA", 0.9, ts))
        rows.append(_row("BBB", 0.8, ts))
        rows.append(_row("CCC", 0.7, ts))
    # plus two single-logged tickers that should appear in a top-10
    rows.append(_row("DDD", 0.6, "2026-06-10T12:00:00+00:00"))
    rows.append(_row("EEE", 0.5, "2026-06-10T12:00:00+00:00"))
    _write_rows(path, rows)

    result = read_rocket_shadow(path=path)

    for view_name in ("top_rank", "highest_monster", "highest_major", "highest_confidence"):
        view = result["views"][view_name]
        tickers = [r["ticker"] for r in view]
        assert len(tickers) == len(set(tickers)), (
            f"view {view_name!r} repeats tickers: {tickers}"
        )

    top = [r["ticker"] for r in result["views"]["top_rank"]]
    assert top[:5] == ["AAA", "BBB", "CCC", "DDD", "EEE"]


@pytest.mark.unit
def test_top_views_use_latest_row_per_ticker(tmp_path):
    path = tmp_path / "shadow.jsonl"
    _write_rows(path, [
        _row("AAA", 0.9, "2026-06-10T10:00:00+00:00"),  # stale high
        _row("AAA", 0.3, "2026-06-10T12:00:00+00:00"),  # current prediction
        _row("BBB", 0.5, "2026-06-10T12:00:00+00:00"),
    ])

    result = read_rocket_shadow(path=path)
    top = result["views"]["top_rank"]

    aaa = next(r for r in top if r["ticker"] == "AAA")
    # The leaderboard must reflect the CURRENT prediction, not a stale high.
    assert aaa["rocket_rank_score"] == 0.3
    assert [r["ticker"] for r in top][:1] == ["BBB"]
