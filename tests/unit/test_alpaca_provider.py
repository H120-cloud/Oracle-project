from types import SimpleNamespace


def test_alpaca_provider_defaults_requests_to_iex_feed(monkeypatch):
    from src.services import alpaca_provider as module

    class FakeDataFeed:
        IEX = "iex"
        SIP = "sip"

    class FakeSnapshotRequest:
        last_feed = None

        def __init__(self, symbol_or_symbols, feed=None):
            self.symbol_or_symbols = symbol_or_symbols
            FakeSnapshotRequest.last_feed = feed

    class FakeBarsRequest:
        last_feed = None

        def __init__(self, symbol_or_symbols, timeframe, start, end, feed=None):
            self.symbol_or_symbols = symbol_or_symbols
            self.timeframe = timeframe
            self.start = start
            self.end = end
            FakeBarsRequest.last_feed = feed

    class FakeDataClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_stock_snapshot(self, request):
            return {}

        def get_stock_bars(self, request):
            return SimpleNamespace(
                data={
                    "AAPL": [
                        SimpleNamespace(
                            timestamp="2026-05-29T13:30:00Z",
                            open=10,
                            high=11,
                            low=9,
                            close=10.5,
                            volume=12345,
                        )
                    ]
                }
            )

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(module, "_alpaca_available", True)
    monkeypatch.setattr(module, "DataFeed", FakeDataFeed, raising=False)
    monkeypatch.setattr(module, "StockSnapshotRequest", FakeSnapshotRequest, raising=False)
    monkeypatch.setattr(module, "StockBarsRequest", FakeBarsRequest, raising=False)
    monkeypatch.setattr(module, "StockHistoricalDataClient", FakeDataClient, raising=False)
    monkeypatch.setattr(module, "TradingClient", FakeTradingClient, raising=False)
    monkeypatch.setattr(module, "TimeFrame", lambda amount, unit: (amount, unit), raising=False)
    monkeypatch.setattr(
        module,
        "TimeFrameUnit",
        SimpleNamespace(Minute="minute", Hour="hour", Day="day", Week="week"),
        raising=False,
    )
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.delenv("ALPACA_DATA_FEED", raising=False)

    provider = module.AlpacaProvider(universe=["AAPL"])

    assert provider.data_feed == FakeDataFeed.IEX
    provider.get_scan_universe()
    assert FakeSnapshotRequest.last_feed == FakeDataFeed.IEX
    bars = provider.get_ohlcv("AAPL", period="1d", interval="1m")
    assert FakeBarsRequest.last_feed == FakeDataFeed.IEX
    assert len(bars) == 1
    assert bars[0].close == 10.5
