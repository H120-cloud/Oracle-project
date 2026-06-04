"""Delete old model and retrain to force-promote the new one."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from pathlib import Path
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

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
print(f"AUC: {result.auc}")
print(f"Promoted: {result.promoted}")

status = orch.get_ml_engine().get_status()
print(f"\nModel version: {status['model_version']}")
print(f"Samples: {status['samples_trained_on']}")
print(f"AUC: {status['auc']}")
