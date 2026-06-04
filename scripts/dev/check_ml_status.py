"""Quick check of ML model status after backfill + train."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

orch = NewsMomentumOrchestrator()
status = orch.get_ml_engine().get_status()

print("=== ML MODEL STATUS ===")
print(f"Model loaded: {status['model_loaded']}")
print(f"Backend: {status['backend']}")
print(f"Model version: {status['model_version']}")
print(f"Samples trained on: {status['samples_trained_on']}")
print(f"AUC: {status['auc']}")
print(f"Test accuracy: {status['test_accuracy']}")
print(f"Trained at: {status['trained_at']}")
if status['top_features']:
    print("\nTop features:")
    for name, score in status['top_features']:
        print(f"  {name}: {score:.4f}")
