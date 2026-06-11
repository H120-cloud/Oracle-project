"""Finnhub profile enrichment for Rocket shadow feature rows.

Fills market_cap_category / float_category (the model's two most important
missing categoricals, hardcoded None on the pre-news branch) from Finnhub's
company profile. Cached, telemetered, and isolated from alert gating.
"""

from types import SimpleNamespace

import pytest

import src.core.agentic.rocket_feature_enrichment as rfe
from src.core.agentic.rocket_feature_enrichment import (
    FinnhubProfileEnricher,
    derive_float_category,
    derive_market_cap_category,
    enrich_feature_row,
)


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def company_profile2(self, symbol):
        self.calls += 1
        return self.payload


# ── category derivation (must mirror orchestrator thresholds exactly) ───────

@pytest.mark.unit
def test_derive_categories_match_canonical_thresholds():
    assert derive_float_category(4_900_000) == "ultra_low"
    assert derive_float_category(5_000_000) == "low"
    assert derive_float_category(50_000_000) == "medium"
    assert derive_float_category(150_000_000) == "high"
    assert derive_float_category(None) is None  # never fabricate

    assert derive_market_cap_category(49_000_000) == "nano"
    assert derive_market_cap_category(50_000_000) == "micro"
    assert derive_market_cap_category(1_000_000_000) == "small"
    assert derive_market_cap_category(5_000_000_000) == "all"
    assert derive_market_cap_category(None) is None


# ── successful enrichment ────────────────────────────────────────────────────

@pytest.mark.unit
def test_successful_enrichment_fills_missing_categories():
    # Finnhub profile2 reports both fields in MILLIONS.
    client = _Client({"marketCapitalization": 120.0, "shareOutstanding": 8.0,
                      "exchange": "NASDAQ", "country": "US", "finnhubIndustry": "Biotechnology"})
    enricher = FinnhubProfileEnricher(client=client)
    row = {"market_cap_category": None, "float_category": None, "ticker": "AAA"}

    profile = enrich_feature_row(row, "AAA", enricher=enricher)

    assert profile is not None
    assert row["market_cap_category"] == "micro"   # 120M USD
    assert row["float_category"] == "low"          # 8M shares
    assert profile["exchange"] == "NASDAQ"
    assert enricher.stats()["success_rate"] == 1.0


@pytest.mark.unit
def test_enrichment_never_overwrites_existing_categories():
    client = _Client({"marketCapitalization": 120.0, "shareOutstanding": 8.0})
    row = {"market_cap_category": "nano", "float_category": "ultra_low"}
    enrich_feature_row(row, "AAA", enricher=FinnhubProfileEnricher(client=client))
    assert row["market_cap_category"] == "nano"
    assert row["float_category"] == "ultra_low"


# ── missing Finnhub data ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_missing_profile_leaves_row_unchanged():
    enricher = FinnhubProfileEnricher(client=_Client({}))
    row = {"market_cap_category": None, "float_category": None}
    profile = enrich_feature_row(row, "ZZZQ", enricher=enricher)
    assert profile is None
    assert row["market_cap_category"] is None
    assert row["float_category"] is None
    assert enricher.stats()["success_rate"] == 0.0


# ── cache behaviour ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_profile_cached_per_ticker():
    client = _Client({"marketCapitalization": 120.0, "shareOutstanding": 8.0})
    enricher = FinnhubProfileEnricher(client=client)
    enricher.get_profile("AAA")
    enricher.get_profile("AAA")
    assert client.calls == 1
    assert enricher.stats()["cache_hits"] == 1


@pytest.mark.unit
def test_empty_profile_negatively_cached():
    client = _Client({})
    enricher = FinnhubProfileEnricher(client=client)
    enricher.get_profile("ZZZQ")
    enricher.get_profile("ZZZQ")
    assert client.calls == 1, "unknown tickers must not be re-fetched every scan"


# ── integration with the shadow scorer + gating isolation ───────────────────

class _StubModel:
    def predict_proba(self, X):
        return [[0.4, 0.6]]


@pytest.mark.unit
def test_predict_enriches_and_records_null_counts(tmp_path, monkeypatch):
    from src.core.agentic.rocket_model_shadow import RocketModelShadowScorer
    import src.core.agentic.rocket_model_shadow as rms

    client = _Client({"marketCapitalization": 120.0, "shareOutstanding": 8.0,
                      "exchange": "NASDAQ", "country": "US"})
    monkeypatch.setattr(rfe, "_default_enricher", FinnhubProfileEnricher(client=client))

    artifact = {
        "models": {t: _StubModel() for t in rms._TARGETS},
        "feature_columns": ["price_at_alert", "ticker", "market_cap_category", "float_category"],
        "categorical_columns": ["ticker", "market_cap_category", "float_category"],
    }
    scorer = RocketModelShadowScorer(
        model_path=tmp_path / "missing.joblib",
        predictions_path=tmp_path / "p.jsonl",
        artifact=artifact,
    )
    candidate = SimpleNamespace(ticker="AAA", detected_at=None, price=2.5,
                                anomaly_type="volume_spike")
    record = scorer.predict_candidate(candidate, source_pipeline="pre_news")

    assert record is not None
    assert record["enriched"] is True
    assert record["feature_null_count_before"] > record["feature_null_count"]
    # gating isolation: the candidate object itself must NOT be mutated
    assert not hasattr(candidate, "market_cap_category")
    assert not hasattr(candidate, "float_category")
