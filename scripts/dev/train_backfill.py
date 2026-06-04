"""Inject existing backfill records into orchestrator and retrain ML."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


def main():
    print("Loading backfill records...")
    engine = HistoricalBackfillEngine()
    summary = engine.get_summary()
    print(f"Loaded {summary['total_records']} records")
    print(f"Outcomes: {summary['by_outcome']}")
    print(f"Tickers: {summary['tickers']}")

    print("\nInjecting into orchestrator...")
    orch = NewsMomentumOrchestrator()
    injected = engine.inject_into_orchestrator(orch)
    print(f"Injected {injected} records into orchestrator")

    print("\nRetraining ML model...")
    result = orch.retrain_ml()
    print(f"Training success: {result.success}")
    print(f"Samples: {result.samples}")
    print(f"Train accuracy: {result.train_accuracy}")
    print(f"Test accuracy: {result.test_accuracy}")
    print(f"AUC: {result.auc}")
    print(f"Win rate baseline: {result.win_rate_baseline}")
    print(f"Promoted: {result.promoted}")
    print(f"Reason: {result.reason}")
    if result.feature_importance:
        print("\nTop features:")
        for name, score in result.feature_importance[:10]:
            print(f"  {name}: {score:.4f}")


if __name__ == "__main__":
    main()
