"""Shared ticker extraction for news sources.

This module is intentionally conservative: prefer explicit exchange, cashtag,
URL, and source-specific ticker hints over guessing random uppercase words.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

SKIP_TICKERS = {
    "AI", "API", "CEO", "CFO", "ETF", "ET", "FDA", "IPO", "LLC", "NAV",
    "PLC", "RSS", "SEC", "USA", "USD", "LIVE", "NEWS", "TODAY",
    "NASDAQ", "NYSE", "AMEX", "OTC", "TSX", "TSXV", "CSE", "LSE", "AIM",
}

_EXCHANGES = (
    r"NASDAQ(?:CM|GM|GS)?|NYSE(?:AMERICAN|MKT)?|NYSE\s+American|AMEX|"
    r"OTC(?:QB|QX|MKTS|ID)?|CSE|TSXV?|NEO|LSE|AIM"
)
_TICKER = r"(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})"

EXCHANGE_TICKER_RE = re.compile(
    rf"(?:\(|\[)?\s*(?:{_EXCHANGES})\s*[:：]\s*{_TICKER}\s*(?:\)|\])?",
    re.IGNORECASE,
)
CASHTAG_RE = re.compile(r"(?<![A-Z0-9])\$(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?![A-Z0-9])")
TITLE_SUFFIX_RE = re.compile(r"\|\s*(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})\s+Stock\s+News", re.IGNORECASE)
DASH_SUFFIX_RE = re.compile(r"\s[-–—]\s(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})\s*$")
QUOTED_SYMBOL_RE = re.compile(
    r"(?:ticker|symbol)\s+(?:symbol\s+)?[\"'](?P<ticker>[A-Z][A-Z0-9.\-]{0,6})[\"']",
    re.IGNORECASE,
)
PLAIN_PARENS_RE = re.compile(r"\((?P<ticker>[A-Z]{2,6})\)")


def normalize_extracted_ticker(value: str) -> str:
    ticker = (value or "").strip().upper()
    ticker = ticker.strip(" .,:;()[]{}")
    return ticker


def _valid(ticker: str) -> bool:
    if not ticker or ticker in SKIP_TICKERS:
        return False
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", ticker):
        return False
    return True


def _add(tickers: list[str], ticker: str) -> None:
    ticker = normalize_extracted_ticker(ticker)
    if _valid(ticker) and ticker not in tickers:
        tickers.append(ticker)


def extract_tickers_from_url(url: str) -> list[str]:
    """Extract source-path tickers from common finance-news URLs."""
    if not url:
        return []
    parsed = urlparse(url)
    path = parsed.path or ""
    tickers: list[str] = []
    patterns = [
        r"/news/(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?:/|$)",
        r"/sec-filings/(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?:/|$)",
        r"/quote/(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?:/|$)",
        r"/stocks/(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?:/|$)",
        r"/symbol/(?P<ticker>[A-Z][A-Z0-9.\-]{0,6})(?:/|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path, flags=re.IGNORECASE)
        if match:
            _add(tickers, match.group("ticker"))
    return tickers


def extract_tickers(
    *texts: str,
    url: str = "",
    include_plain_parens: bool = False,
) -> list[str]:
    """Extract tickers from explicit source text and optional URL."""
    tickers = extract_tickers_from_url(url)
    joined = " ".join(t for t in texts if t)

    for regex in (EXCHANGE_TICKER_RE, CASHTAG_RE, TITLE_SUFFIX_RE, DASH_SUFFIX_RE, QUOTED_SYMBOL_RE):
        for match in regex.finditer(joined):
            _add(tickers, match.group("ticker"))

    if include_plain_parens:
        for match in PLAIN_PARENS_RE.finditer(joined):
            _add(tickers, match.group("ticker"))

    return tickers


__all__ = [
    "EXCHANGE_TICKER_RE",
    "SKIP_TICKERS",
    "extract_tickers",
    "extract_tickers_from_url",
    "normalize_extracted_ticker",
]
