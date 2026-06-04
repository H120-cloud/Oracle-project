"""Force-promote new model and re-test predictions."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from pathlib import Path
from datetime import datetime, timezone
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate, NewsSource, SessionType, PriceBucket,
    FloatCategory, MarketCapCategory,
)
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline

MODEL_FILE = Path("data/agentic/news_momentum_ml_model.joblib")
META_FILE = Path("data/agentic/news_momentum_ml_model_meta.json")

# Delete old model
for f in [MODEL_FILE, META_FILE]:
    if f.exists():
        print(f"Removing old {f}")
        f.unlink()

print("Retraining...")
orch = NewsMomentumOrchestrator()
result = orch.retrain_ml()
print(f"Success: {result.success}")
print(f"Samples: {result.samples}")
print(f"AUC: {result.auc:.3f}")
print(f"Promoted: {result.promoted}")

status = orch.get_ml_engine().get_status()
print(f"\nModel: {status['model_version']} | Samples: {status['samples_trained_on']} | AUC: {status['auc']:.3f}")

# Re-test
def _make_cand(headline, ticker, price, volume=1_000_000):
    engine = HistoricalBackfillEngine()
    cat, sub, is_neg, is_vague = classify_headline(headline)
    sim = engine._simulate_pipeline(headline, price)
    now = datetime.now(timezone.utc)
    return NewsMomentumCandidate(
        ticker=ticker, headline=headline, source=NewsSource.ORACLE_SCANNER,
        published_at=now, session=SessionType.REGULAR,
        catalyst_category=cat, catalyst_sub_type=sub,
        is_negative=is_neg, is_vague=is_vague,
        current_price=price, volume=volume, rvol=2.0, spread_pct=1.5,
        float_shares=50_000_000, market_cap=500_000_000,
        price_bucket=PriceBucket.UNDER_5 if price < 5 else PriceBucket.MID_CAP,
        float_category=FloatCategory.MEDIUM, market_cap_category=MarketCapCategory.SMALL,
        news_impact_score=sim["news_impact_score"],
        expected_return_score=sim["expected_return_score"],
        continuation_probability=sim["continuation_probability"],
        multi_day_continuation_score=sim["multi_day_score"],
        trap_risk=sim["trap_risk_at_alert"],
        dilution_risk=sim["dilution_risk_at_alert"],
        velocity_score=sim["velocity_score_at_alert"],
        sources_seen_count=sim["sources_seen_count"],
    )

print("\n=== RE-TESTING (new model) ===")
ml = orch.get_ml_engine()

test_cases = [
    ("AAPL announces record Q1 earnings beat", "AAPL", 180.0),
    ("Tesla secures massive AI partnership with Nvidia", "TSLA", 250.0),
    ("Microcap biotech VKTX announces positive Phase 3 data", "VKTX", 3.50),
    ("Rigetti Computing files $200M mixed shelf offering", "RGTI", 1.20),
    ("EDITAS Medicine reports patient death in clinical trial", "EDIT", 1.50),
    ("BTCY announces FDA approval for novel cancer therapy", "BTCY", 0.80),
    ("SOUN wins $500M government contract for voice AI", "SOUN", 8.0),
    ("QuantumScape delays commercialization by 2 years", "QBTS", 1.80),
    ("ASTS announces buyout offer at 40% premium", "ASTS", 25.0),
    ("BBAI awarded $1.2B defense contract", "BBAI", 4.50),
    ("WULF announces $50M ATM offering", "WULF", 2.0),
    ("MARA mines 500 BTC in single month record", "MARA", 15.0),
]

print(f"{'Headline':<50} {'Ticker':<6} {'Price':>6} {'Win%':>6} {'Conf':>5}")
print("-" * 75)
for headline, ticker, price in test_cases:
    try:
        cand = _make_cand(headline, ticker, price)
        pred = ml.predict(cand)
        print(f"{headline[:48]:<48} {ticker:<6} ${price:>5.2f} {pred.win_probability*100:>5.1f}% {pred.confidence:>4.2f}")
    except Exception as exc:
        print(f"ERROR: {exc}")

print("\n=== MODEL EFFECTIVENESS SUMMARY ===")
print("Check: do negative events at low price now score LOWER than positive events?")
print("Compare RGTI/EDIT/WULF/QBTS (should be LOW) vs VKTX/BTCY/SOUN/BBAI (should be HIGH)")
