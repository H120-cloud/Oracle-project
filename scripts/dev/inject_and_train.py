"""Bulk-inject backfill records into orchestrator and retrain ML (fast path)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


def main():
    print("Loading backfill engine...")
    engine = HistoricalBackfillEngine()
    summary = engine.get_summary()
    print(f"Records: {summary['total_records']}")
    print(f"Outcomes: {summary['by_outcome']}")

    print("\nInjecting into orchestrator (batch mode)...")
    orch = NewsMomentumOrchestrator()

    # Fast path: extend the internal list directly, save once at the end
    alerts = orch._telegram_learning._alerts
    by_catalyst = orch._telegram_learning._by_catalyst

    added = 0
    for record in engine._records:
        alerts.append(record)
        by_catalyst[record.catalyst_type.value].append(record)
        added += 1

    # Single save after all inserts
    orch._telegram_learning._save()
    print(f"Injected {added} records")

    print("\nRetraining ML model...")
    result = orch.retrain_ml()
    print(f"Success: {result.success}")
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

    # Verify
    status = orch.get_ml_engine().get_status()
    print(f"\nModel version now: {status['model_version']}")
    print(f"Samples: {status['samples_trained_on']}")
    print(f"AUC: {status['auc']}")


if __name__ == "__main__":
    main()
