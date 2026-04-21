"""
Model Management API routes — V2

Endpoints for training ML models, checking model status, and listing models.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.ml.trainer import ModelTrainer
from src.ml.model_store import ModelStore
from src.ml.dip_model import DipModel
from src.ml.bounce_model import BounceModel

router = APIRouter(prefix="/models", tags=["models"])


@router.post("/train")
def train_models(db: Session = Depends(get_db)):
    """Trigger training of dip and bounce ML models from historical data."""
    trainer = ModelTrainer(db)
    result = trainer.train_all()
    return {"status": "ok", "results": result}


@router.post("/train/dip")
def train_dip_model(db: Session = Depends(get_db)):
    """Train only the dip prediction model."""
    trainer = ModelTrainer(db)
    result = trainer.train_dip_model()
    return {"status": "ok", "result": result}


@router.post("/train/bounce")
def train_bounce_model(db: Session = Depends(get_db)):
    """Train only the bounce prediction model."""
    trainer = ModelTrainer(db)
    result = trainer.train_bounce_model()
    return {"status": "ok", "result": result}


@router.get("/status")
def model_status():
    """Check which models are trained and available."""
    store = ModelStore()
    dip = DipModel(store)
    bounce = BounceModel(store)
    return {
        "dip_model": {"trained": dip.is_trained},
        "bounce_model": {"trained": bounce.is_trained},
        "available_models": store.list_models(),
    }
