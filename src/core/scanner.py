"""
Market Scanner — V1 (rule-based)

Scans for the most active stocks by volume, relative volume, and % change.
Applies price/liquidity filters. Supports custom watchlist overlay.
"""

import logging
from typing import Optional

import pandas as pd

from src.models.schemas import ScanFilter, ScannedStock

logger = logging.getLogger(__name__)


class MarketScanner:
    """Scans market data to find active momentum candidates."""

    def __init__(self, filters: Optional[ScanFilter] = None):
        self.filters = filters or ScanFilter()

    # ── public API ───────────────────────────────────────────────────────

    def scan_top_volume(self, market_data: pd.DataFrame) -> list[ScannedStock]:
        """Return top N stocks sorted by raw volume."""
        df = self._apply_filters(market_data)
        df = df.sort_values("volume", ascending=False).head(self.filters.max_results)
        return self._to_scanned_stocks(df, scan_type="volume")

    def scan_top_rvol(self, market_data: pd.DataFrame) -> list[ScannedStock]:
        """Return top N stocks sorted by relative volume (RVOL)."""
        df = self._apply_filters(market_data)
        if "rvol" not in df.columns or df["rvol"].isna().all():
            logger.warning("RVOL data not available; falling back to volume scan")
            return self.scan_top_volume(market_data)
        df = df.sort_values("rvol", ascending=False).head(self.filters.max_results)
        return self._to_scanned_stocks(df, scan_type="rvol")

    def scan_top_gainers(self, market_data: pd.DataFrame) -> list[ScannedStock]:
        """Return top N stocks sorted by % change (gainers)."""
        df = self._apply_filters(market_data)
        if "change_percent" not in df.columns:
            logger.warning("change_percent column missing")
            return []
        df = df.sort_values("change_percent", ascending=False).head(
            self.filters.max_results
        )
        return self._to_scanned_stocks(df, scan_type="gainers")

    def scan_watchlist(
        self, market_data: pd.DataFrame, tickers: list[str]
    ) -> list[ScannedStock]:
        """Return data for specific watchlist tickers."""
        upper = [t.upper() for t in tickers]
        df = market_data[market_data["ticker"].str.upper().isin(upper)].copy()
        df = self._apply_filters(df)
        return self._to_scanned_stocks(df, scan_type="watchlist")

    # ── internals ────────────────────────────────────────────────────────

    def _apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        filtered = df.copy()

        if "price" in filtered.columns:
            filtered = filtered[
                (filtered["price"] >= self.filters.min_price)
                & (filtered["price"] <= self.filters.max_price)
            ]

        if "volume" in filtered.columns:
            filtered = filtered[filtered["volume"] >= self.filters.min_volume]

        if self.filters.min_rvol and "rvol" in filtered.columns:
            filtered = filtered[filtered["rvol"] >= self.filters.min_rvol]

        return filtered

    @staticmethod
    def _to_scanned_stocks(df: pd.DataFrame, scan_type: str) -> list[ScannedStock]:
        results: list[ScannedStock] = []
        for _, row in df.iterrows():
            results.append(
                ScannedStock(
                    ticker=row.get("ticker", ""),
                    price=float(row.get("price", 0)),
                    volume=float(row.get("volume", 0)),
                    rvol=float(row["rvol"]) if pd.notna(row.get("rvol")) else None,
                    change_percent=(
                        float(row["change_percent"])
                        if pd.notna(row.get("change_percent"))
                        else None
                    ),
                    market_cap=(
                        float(row["market_cap"])
                        if pd.notna(row.get("market_cap"))
                        else None
                    ),
                    float_shares=(
                        float(row["float_shares"])
                        if pd.notna(row.get("float_shares"))
                        else None
                    ),
                    scan_type=scan_type,
                )
            )
        return results
