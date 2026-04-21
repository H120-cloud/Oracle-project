"""Tests for V8 Higher Timeframe Bias Detector."""
import pytest
import numpy as np
from datetime import datetime
from src.core.higher_timeframe_bias import HigherTimeframeBiasDetector, HTFAlignmentEvaluator, HTFBias, AlignmentStatus, TradeType, HTFBiasResult
from src.models.schemas import OHLCVBar, ICTFeatures

def create_bars(prices):
    return [OHLCVBar(timestamp=datetime(2024, 1, 1, 12, 0, i), open=p*0.995, high=p*1.01, low=p*0.99, close=p, volume=1000000) for i, p in enumerate(prices)]

def create_bullish_bars(count=60):
    return create_bars([100 + i*0.5 + np.sin(i*0.5)*2 for i in range(count)])

def create_bearish_bars(count=60):
    return create_bars([150 - i*0.6 + np.sin(i*0.4)*2 for i in range(count)])

class TestHigherTimeframeBiasDetector:
    def test_detects_bullish_bias(self):
        result = HigherTimeframeBiasDetector().detect_bias("TEST", create_bullish_bars(60))
        assert result.bias == HTFBias.BULLISH and result.strength_score >= 70

    def test_detects_bearish_bias(self):
        result = HigherTimeframeBiasDetector().detect_bias("TEST", create_bearish_bars(60))
        assert result.bias == HTFBias.BEARISH and result.strength_score < 40

    def test_insufficient_data_returns_neutral(self):
        result = HigherTimeframeBiasDetector().detect_bias("TEST", create_bullish_bars(30))
        assert result.bias == HTFBias.NEUTRAL

class TestHTFAlignmentEvaluator:
    def test_case_1_bullish_aligned(self):
        htf = HTFBiasResult("TEST", HTFBias.BULLISH, 75.0, [], 80, 70, 75, 80, 100, 95, 62, 28, 105)
        ict = ICTFeatures(liquidity_sweep=True, structure_reclaimed=True, structure_break_confirmed=True)
        result = HTFAlignmentEvaluator().evaluate_alignment("TEST", htf, True, ict, False)
        assert result.allowed and result.alignment_status == AlignmentStatus.ALIGNED and result.confidence_adjustment == 15

    def test_case_3_bearish_blocked(self):
        htf = HTFBiasResult("TEST", HTFBias.BEARISH, 25.0, [], 20, 25, 20, 30, 90, 100, 38, 30, 85)
        result = HTFAlignmentEvaluator().evaluate_alignment("TEST", htf, True, ICTFeatures(), False)
        assert not result.allowed and result.alignment_status == AlignmentStatus.COUNTER_TREND

    def test_weak_htf_as_neutral(self):
        htf = HTFBiasResult("TEST", HTFBias.BULLISH, 35.0, [], 30, 35, 35, 40, 100, 95, 52, 18, 98)
        result = HTFAlignmentEvaluator(min_htf_strength=40.0).evaluate_alignment("TEST", htf, True, ICTFeatures(), False)
        assert result.htf_bias == HTFBias.NEUTRAL

    def test_early_warning_blocks_exception(self):
        htf = HTFBiasResult("TEST", HTFBias.BEARISH, 30.0, [], 25, 30, 35, 30, 90, 100, 42, 24, 88)
        ict = ICTFeatures(liquidity_sweep=True, structure_reclaimed=True)
        result = HTFAlignmentEvaluator().evaluate_alignment("TEST", htf, True, ict, True)
        assert not result.allowed

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
