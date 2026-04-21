"""Tests for StockSegmenter."""

import pytest

from src.core.stock_segmenter import StockSegmenter
from src.models.schemas import ScannedStock, StockType


@pytest.fixture
def segmenter():
    return StockSegmenter()


def _stock(ticker="TEST", price=50.0, volume=1_000_000, rvol=1.5,
           market_cap=None, float_shares=None):
    return ScannedStock(
        ticker=ticker, price=price, volume=volume, rvol=rvol,
        market_cap=market_cap, float_shares=float_shares, scan_type="test",
    )


def test_biotech_detection(segmenter):
    stock = _stock(ticker="MRNA")
    result = segmenter.classify(stock)
    assert result.stock_type == StockType.BIOTECH_NEWS


def test_low_float_momentum(segmenter):
    stock = _stock(float_shares=20_000_000, rvol=3.0)
    result = segmenter.classify(stock)
    assert result.stock_type == StockType.LOW_FLOAT_MOMENTUM


def test_mid_cap_liquid(segmenter):
    stock = _stock(market_cap=10_000_000_000)  # 10B
    result = segmenter.classify(stock)
    assert result.stock_type == StockType.MID_CAP_LIQUID


def test_unknown_segment(segmenter):
    stock = _stock()  # no market_cap, no float, not biotech
    result = segmenter.classify(stock)
    assert result.stock_type == StockType.UNKNOWN


def test_threshold_adjustments():
    adj = StockSegmenter.get_threshold_adjustments(StockType.LOW_FLOAT_MOMENTUM)
    assert adj["dip_sensitivity"] > 1.0
    assert adj["stop_multiplier"] > 1.0

    adj_normal = StockSegmenter.get_threshold_adjustments(StockType.MID_CAP_LIQUID)
    assert adj_normal["dip_sensitivity"] == 1.0
