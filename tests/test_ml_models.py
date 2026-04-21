"""Tests for ML models and feature engineering."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ml.feature_engineer import FeatureEngineer
from src.ml.model_store import ModelStore
from src.ml.dip_model import DipModel
from src.ml.bounce_model import BounceModel
from src.models.schemas import DipFeatures, BounceFeatures, ScannedStock


# ── Feature Engineer ─────────────────────────────────────────────────────────

def test_dip_to_array():
    features = DipFeatures(
        vwap_distance_pct=-1.0, ema9_distance_pct=-0.5, ema20_distance_pct=-0.3,
        drop_from_high_pct=3.0, consecutive_red_candles=2,
        red_candle_volume_ratio=1.5, lower_highs_count=3, momentum_decay=-0.02,
    )
    arr = FeatureEngineer.dip_to_array(features)
    assert arr.shape == (8,)
    assert arr[0] == -1.0  # vwap_distance_pct


def test_bounce_to_array():
    features = BounceFeatures(
        support_distance_pct=0.5, selling_pressure_change=-0.3,
        buying_pressure_ratio=1.5, higher_low_formed=True,
        key_level_reclaimed=False, rsi=32.0, macd_histogram_slope=0.1,
    )
    arr = FeatureEngineer.bounce_to_array(features)
    assert arr.shape == (7,)
    assert arr[3] == 1.0  # higher_low_formed = True → 1.0
    assert arr[4] == 0.0  # key_level_reclaimed = False → 0.0


def test_combined_vector():
    dip = DipFeatures(
        vwap_distance_pct=-1.0, ema9_distance_pct=-0.5, ema20_distance_pct=-0.3,
        drop_from_high_pct=3.0, consecutive_red_candles=2,
        red_candle_volume_ratio=1.5, lower_highs_count=3, momentum_decay=-0.02,
    )
    bounce = BounceFeatures(
        support_distance_pct=0.5, selling_pressure_change=-0.3,
        buying_pressure_ratio=1.5, higher_low_formed=True,
        key_level_reclaimed=True, rsi=32.0, macd_histogram_slope=0.1,
    )
    stock = ScannedStock(
        ticker="TEST", price=100.0, volume=2_000_000,
        rvol=2.5, change_percent=5.0, scan_type="test",
    )
    vec = FeatureEngineer.combined_vector(dip, bounce, stock, 60.0, 70.0)
    # 8 dip + 7 bounce + 4 context + 2 rule probs = 21
    assert vec.shape == (21,)
    assert vec[-1] == 70.0  # rule_bounce_prob
    assert vec[-2] == 60.0  # rule_dip_prob


def test_combined_vector_handles_none():
    vec = FeatureEngineer.combined_vector(None, None, None, 50.0, 40.0)
    assert vec.shape == (21,)
    assert vec[-1] == 40.0


# ── Model Store ──────────────────────────────────────────────────────────────

def test_model_store_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        store.save({"fake": "model"}, "test_model", {"accuracy": 0.85})
        assert store.exists("test_model")

        loaded = store.load("test_model")
        assert loaded is not None
        assert loaded["model"]["fake"] == "model"
        assert loaded["metadata"]["accuracy"] == 0.85


def test_model_store_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        assert not store.exists("nonexistent")
        assert store.load("nonexistent") is None


# ── Dip Model (cold-start) ──────────────────────────────────────────────────

def test_dip_model_cold_start():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        model = DipModel(model_store=store)
        assert not model.is_trained

        features = DipFeatures(
            vwap_distance_pct=-1.0, ema9_distance_pct=-0.5, ema20_distance_pct=-0.3,
            drop_from_high_pct=3.0, consecutive_red_candles=2,
            red_candle_volume_ratio=1.5, lower_highs_count=3, momentum_decay=-0.02,
        )
        # Cold start should return rule-based value
        result = model.predict(features, rule_based_prob=65.0)
        assert result == 65.0


def test_dip_model_train_and_predict():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        model = DipModel(model_store=store)

        # Create synthetic training data
        rng = np.random.RandomState(42)
        X = rng.randn(100, 8)
        y = (X[:, 0] < 0).astype(int)  # negative vwap_distance → dip

        # Split into train/test (80/20)
        split_idx = int(0.8 * len(X))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        result = model.train(X_train, y_train, X_test, y_test)
        assert result["status"] == "trained"
        assert model.is_trained
        assert "test_accuracy" in result

        # Predict should now blend ML + rule-based
        features = DipFeatures(
            vwap_distance_pct=-2.0, ema9_distance_pct=-1.0, ema20_distance_pct=-0.5,
            drop_from_high_pct=5.0, consecutive_red_candles=4,
            red_candle_volume_ratio=1.8, lower_highs_count=3, momentum_decay=-0.05,
        )
        prob = model.predict(features, rule_based_prob=70.0)
        assert 0 <= prob <= 100


# ── Bounce Model (cold-start) ───────────────────────────────────────────────

def test_bounce_model_cold_start():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        model = BounceModel(model_store=store)
        assert not model.is_trained

        features = BounceFeatures(
            support_distance_pct=0.5, selling_pressure_change=-0.3,
            buying_pressure_ratio=1.5, higher_low_formed=True,
            key_level_reclaimed=True, rsi=32.0, macd_histogram_slope=0.1,
        )
        result = model.predict(features, rule_based_prob=55.0)
        assert result == 55.0


def test_dip_model_insufficient_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        model = DipModel(model_store=store)

        X = np.random.randn(10, 8)
        y = np.array([0, 1] * 5)

        # For insufficient data, use same data for train and test
        result = model.train(X, y, X, y)
        assert result["status"] == "insufficient_data"
        assert not model.is_trained
