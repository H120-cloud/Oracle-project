from __future__ import annotations

from src.services.ticker_normalization import (
    SymbolProvider,
    canonicalize_ticker,
    normalize_ticker_for_provider,
)


def test_canonicalize_ticker_preserves_internal_hyphen_format():
    assert canonicalize_ticker("  brk-a ") == "BRK-A"


def test_dot_class_share_providers_receive_dot_symbols():
    assert normalize_ticker_for_provider("BRK-A", "polygon") == "BRK.A"
    assert normalize_ticker_for_provider("BRK-B", SymbolProvider.ALPACA) == "BRK.B"
    assert normalize_ticker_for_provider("BF-B", "alpha_vantage") == "BF.B"
    assert normalize_ticker_for_provider("HEI-A", "polygon") == "HEI.A"
    assert normalize_ticker_for_provider("PBR-A", "alpaca") == "PBR.A"
    assert normalize_ticker_for_provider("BRK-A", "finnhub") == "BRK.A"


def test_yahoo_providers_receive_hyphen_symbols():
    assert normalize_ticker_for_provider("BRK.A", "yahoo") == "BRK-A"
    assert normalize_ticker_for_provider("BRK.B", "yfinance") == "BRK-B"


def test_unknown_symbols_are_not_rewritten():
    assert normalize_ticker_for_provider("ABC-WS", "polygon") == "ABC-WS"
    assert normalize_ticker_for_provider("AAPL", "yfinance") == "AAPL"
