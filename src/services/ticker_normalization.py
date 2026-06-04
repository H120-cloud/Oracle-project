"""Provider-specific ticker formatting without changing internal symbols."""

from __future__ import annotations

from enum import Enum


class SymbolProvider(str, Enum):
    """External services with distinct class-share symbol conventions."""

    ALPACA = "alpaca"
    ALPHA_VANTAGE = "alpha_vantage"
    FINNHUB = "finnhub"
    POLYGON = "polygon"
    YAHOO = "yahoo"
    YFINANCE = "yfinance"


_DOT_CLASS_SHARE_PROVIDERS = {
    SymbolProvider.ALPACA,
    SymbolProvider.ALPHA_VANTAGE,
    SymbolProvider.FINNHUB,
    SymbolProvider.POLYGON,
}
_HYPHEN_CLASS_SHARE_PROVIDERS = {
    SymbolProvider.YAHOO,
    SymbolProvider.YFINANCE,
}

# Keep this allowlist narrow. A hyphen can carry meanings other than a US
# class-share separator, so provider conversion must not rewrite arbitrary
# symbols.
_CLASS_SHARE_SYMBOLS = {
    "BF-A",
    "BF-B",
    "BRK-A",
    "BRK-B",
    "HEI-A",
    "PBR-A",
}


def canonicalize_ticker(ticker: str) -> str:
    """Return the stable internal ticker representation."""
    return str(ticker or "").strip().upper()


def normalize_ticker_for_provider(
    ticker: str,
    provider: SymbolProvider | str,
) -> str:
    """Translate a canonical ticker only where a provider requires it."""
    canonical = canonicalize_ticker(ticker)
    provider_name = provider if isinstance(provider, SymbolProvider) else SymbolProvider(str(provider).lower())

    hyphen_symbol = canonical.replace(".", "-")
    if hyphen_symbol not in _CLASS_SHARE_SYMBOLS:
        return canonical

    if provider_name in _DOT_CLASS_SHARE_PROVIDERS:
        return hyphen_symbol.replace("-", ".")
    if provider_name in _HYPHEN_CLASS_SHARE_PROVIDERS:
        return hyphen_symbol
    return canonical
