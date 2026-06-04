from __future__ import annotations

from src.services.polygon_provider import PolygonProvider


def test_polygon_daily_bars_are_not_removed_by_intraday_session_filter(monkeypatch):
    provider = PolygonProvider.__new__(PolygonProvider)
    provider.api_key = "test"
    provider._ohlcv_cache = {}
    provider._quote_cache = {}
    provider._ttl_seconds = 30.0

    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: {
            "results": [
                {
                    "t": 1767657600000,  # daily candle timestamped at midnight UTC
                    "o": 10.0,
                    "h": 12.0,
                    "l": 9.5,
                    "c": 11.0,
                    "v": 1000,
                }
            ]
        },
    )

    bars = provider.get_ohlcv(
        "TEST",
        start="2026-01-05",
        end="2026-01-06",
        interval="1d",
        prepost=False,
    )

    assert len(bars) == 1
    assert bars[0].high == 12.0


def test_polygon_class_share_symbol_is_normalized_in_request_path(monkeypatch):
    provider = PolygonProvider.__new__(PolygonProvider)
    provider.api_key = "test"
    provider._ohlcv_cache = {}
    provider._quote_cache = {}
    provider._ttl_seconds = 30.0
    paths = []

    def fake_get(path, *args, **kwargs):
        paths.append(path)
        return {"results": []}

    monkeypatch.setattr(provider, "_get", fake_get)

    provider.get_ohlcv(
        "BRK-A",
        start="2026-01-05",
        end="2026-01-06",
        interval="1d",
    )

    assert paths == ["/v2/aggs/ticker/BRK.A/range/1/day/2026-01-05/2026-01-06"]
