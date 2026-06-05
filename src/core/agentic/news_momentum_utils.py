"""
Shared utilities for the news-momentum pipeline.

No external dependencies beyond stdlib.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import List

from src.core.finviz_news import FinvizNewsItem


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_headline(headline: str) -> str:
    """Normalize a headline for deduplication comparison.

    - Lowercase
    - Strip leading/trailing whitespace
    - Remove " | TICKER Stock News" suffix
    - Collapse multiple spaces
    """
    h = headline.lower().strip()
    h = re.sub(r"\s*\|\s*[a-z]{1,5}\s+stock\s+news\s*$", "", h, flags=re.IGNORECASE)
    h = re.sub(r"\s+", " ", h)
    return h


def deduplicate_news_items(
    items: List[FinvizNewsItem],
    window_hours: float = 24.0,
) -> List[FinvizNewsItem]:
    """Remove duplicate headlines across sources within a bounded time window.

    Dedup key is ``(primary_ticker, normalized_headline)`` so that a generic
    press-release headline (e.g. "Company Announces Strategic Review") that
    legitimately appears for two different tickers in the same window is
    preserved as two distinct items — collapsing them would silently drop
    the second ticker's catalyst from every downstream consumer.

    When two items share the key and fall within ``window_hours``, the one
    with the EARLIEST verifiable timestamp is kept (it represents the first
    confirmed publish of that catalyst). Items lacking a timestamp lose to
    timestamped ones, so a Finviz row with a fabricated/None time can't
    outrank a fresh StockTitan publish.

    On exact timestamp ties, the historically-faster source (StockTitan) is
    preferred over Finviz.

    Args:
        items: Raw items from one or more scrapers.
        window_hours: Maximum time delta (in hours) for considering two items
            as the same event. Defaults to 24 hours.

    Returns:
        Deduplicated list preserving original order for first-seen items.
    """
    window = timedelta(hours=window_hours)

    def _primary_ticker(it: FinvizNewsItem) -> str:
        # FinvizNewsItem.tickers can be empty; key on '' rather than crashing
        # so the dedup still applies for headlines we couldn't tag.
        return (it.tickers[0].upper() if it.tickers else "")

    def _merge_metadata(preferred: FinvizNewsItem, other: FinvizNewsItem) -> FinvizNewsItem:
        """Keep preferred timing/source while preserving richer duplicate payload."""
        for ticker in getattr(other, "tickers", []) or []:
            ticker_u = str(ticker).upper()
            if ticker_u and ticker_u not in preferred.tickers:
                preferred.tickers.append(ticker_u)

        preferred_desc = getattr(preferred, "description", "") or ""
        other_desc = getattr(other, "description", "") or ""
        if len(other_desc) > len(preferred_desc):
            preferred.description = other_desc

        if (not preferred.url) and getattr(other, "url", ""):
            preferred.url = other.url
        if getattr(preferred, "sentiment", "neutral") == "neutral" and getattr(other, "sentiment", "neutral") != "neutral":
            preferred.sentiment = other.sentiment
        return preferred

    # List of (key, item, first_index) for kept items
    kept: list[tuple[tuple[str, str], FinvizNewsItem, int]] = []

    for idx, item in enumerate(items):
        key = (_primary_ticker(item), _normalize_headline(item.headline))
        item_ts = _aware_utc(item.timestamp) if item.timestamp else None

        merged = False
        for i, (k, existing, first_idx) in enumerate(kept):
            if k != key:
                continue
            existing_ts = _aware_utc(existing.timestamp) if existing.timestamp else None

            # Without a real timestamp on either side, we can't enforce the
            # window — treat as duplicate and keep whichever has a real ts.
            if item_ts is None and existing_ts is None:
                kept[i] = (key, _merge_metadata(existing, item), first_idx)
                merged = True
                break
            if existing_ts is None:
                kept[i] = (key, _merge_metadata(item, existing), first_idx)
                merged = True
                break
            if item_ts is None:
                kept[i] = (key, _merge_metadata(existing, item), first_idx)
                merged = True
                break

            if abs((item_ts - existing_ts).total_seconds()) <= window.total_seconds():
                if item_ts < existing_ts:
                    kept[i] = (key, _merge_metadata(item, existing), first_idx)
                elif item_ts == existing_ts:
                    # Prefer historically-faster source (StockTitan) on ties
                    if item.source == "StockTitan" and existing.source != "StockTitan":
                        kept[i] = (key, _merge_metadata(item, existing), first_idx)
                    else:
                        kept[i] = (key, _merge_metadata(existing, item), first_idx)
                else:
                    kept[i] = (key, _merge_metadata(existing, item), first_idx)
                merged = True
                break

        if not merged:
            kept.append((key, item, idx))

    # Sort by original first index to preserve order
    kept.sort(key=lambda x: x[2])
    return [item for _, item, _ in kept]
