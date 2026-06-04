from datetime import datetime, timedelta, timezone

from src.core.agentic.pre_news_detector import _compute_volume_metrics
from src.core.finviz_scanner import FinvizScanner
from src.models.schemas import OHLCVBar


def test_scrape_finviz_tickers_supports_new_stock_link_markup(monkeypatch):
    html = """
    <html><body>
      <a href="stock?t=ASTC&ty=c&p=d&b=1">1</a>
      <td data-boxover-ticker="ASTC">
        <a href="stock?t=ASTC&ty=c&p=d&b=1" class="tab-link">ASTC</a>
      </td>
      <a href="quote.ashx?t=CRCL&p=d">CRCL</a>
    </body></html>
    """

    class Response:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.core.finviz_scanner.httpx.get", lambda *a, **k: Response())
    monkeypatch.setattr(FinvizScanner, "_validate_tickers", lambda self, tickers: tickers)

    tickers = FinvizScanner()._scrape_finviz_tickers()

    assert tickers == ["ASTC", "CRCL"]


def test_volume_metrics_still_scores_when_average_volume_missing():
    start = datetime(2026, 5, 28, 13, 30, tzinfo=timezone.utc)
    volumes = [1000, 1100, 900, 1200, 1000, 900, 1200, 1100, 1000, 25000]
    bars = [
        OHLCVBar(
            timestamp=start + timedelta(minutes=5 * idx),
            open=1.0,
            high=1.1,
            low=0.95,
            close=1.05,
            volume=volume,
        )
        for idx, volume in enumerate(volumes)
    ]

    metrics = _compute_volume_metrics(bars, avg_volume=0)

    assert metrics.current_volume == sum(volumes)
    assert metrics.rvol_current == 1.0
    assert metrics.abnormal_volume_score > 0
