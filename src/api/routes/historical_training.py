"""API routes for Historical Catalyst Training Engine"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.agentic.historical_models import TrainingMode
from src.core.agentic.historical_training import HistoricalTrainingController

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agentic/training/historical", tags=["Historical Catalyst Training"])

# Singleton controller instance
_training_controller: Optional[HistoricalTrainingController] = None

def get_controller() -> HistoricalTrainingController:
    global _training_controller
    if _training_controller is None:
        _training_controller = HistoricalTrainingController()
    return _training_controller

# ── Pydantic request/response models ────────────────────────────────────────────

class RunTrainingRequest(BaseModel):
    mode: str = Field(default="recommend_only")
    approved_features: List[str] = Field(default_factory=list)
    dry_run: bool = False

class LabelEventRequest(BaseModel):
    event_id: str
    price_path: Optional[List[Dict[str, Any]]] = None

class LabelBatchRequest(BaseModel):
    event_price_paths: Dict[str, Optional[List[Dict[str, Any]]]]

class ApplyApprovedRequest(BaseModel):
    approved_features: List[str] = Field(default_factory=list)

class AddEventRequest(BaseModel):
    ticker: str
    catalyst_type: str
    catalyst_headline: str = ""
    catalyst_source: str = ""
    price_at_news: float = 0.0
    float_shares: Optional[float] = None
    market_cap: Optional[float] = None
    is_premarket: bool = False
    time_of_day_bucket: Optional[str] = None
    rvol_before_news: Optional[float] = None
    volume_acceleration_before_news: Optional[float] = None

# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_training(req: RunTrainingRequest) -> Dict[str, Any]:
    """Run the full historical catalyst training pipeline."""
    try:
        mode = TrainingMode(req.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode}")
    controller = get_controller()
    report = controller.run_training(mode=mode, approved_features=req.approved_features, dry_run=req.dry_run)
    return {"success": True, "report": report}

@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Get current training dataset status, weights, and recommendations."""
    return get_controller().get_status()

@router.get("/insights")
async def get_insights() -> Dict[str, Any]:
    """Get pattern insights and top/worst performing patterns."""
    return get_controller().get_insights()

@router.get("/recommendations")
async def get_recommendations() -> List[Dict[str, Any]]:
    """Get current calibration recommendations."""
    return get_controller().get_recommendations()

@router.post("/apply-approved")
async def apply_approved(req: ApplyApprovedRequest) -> Dict[str, Any]:
    """Manually approve and apply selected calibration recommendations."""
    result = get_controller().apply_approved(req.approved_features)
    return {"success": True, "result": result}

@router.post("/rollback")
async def rollback() -> Dict[str, Any]:
    """Rollback to previous calibration weights."""
    ok = get_controller().rollback()
    return {"success": ok, "message": "Rolled back" if ok else "No rollback available"}

@router.get("/report/{run_id}")
async def get_report(run_id: str) -> Dict[str, Any]:
    """Retrieve a specific training run report by ID."""
    report = get_controller().get_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {run_id} not found")
    return {"success": True, "report": report}

@router.get("/events")
async def list_events(
    ticker: Optional[str] = None,
    catalyst_type: Optional[str] = None,
    has_outcome: Optional[bool] = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    """List historical catalyst events with optional filters."""
    from src.core.agentic.models import CatalystType
    controller = get_controller()
    ct = CatalystType(catalyst_type) if catalyst_type else None
    events = controller.dataset_builder.get_events(
        ticker=ticker, catalyst_type=ct, has_outcome=has_outcome, limit=limit)
    return {
        "success": True,
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }

@router.post("/events")
async def add_event(req: AddEventRequest) -> Dict[str, Any]:
    """Add a new historical catalyst event to the dataset."""
    from src.core.agentic.models import CatalystType
    try:
        ct = CatalystType(req.catalyst_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid catalyst_type: {req.catalyst_type}")
    controller = get_controller()
    event = controller.dataset_builder.add_event(
        ticker=req.ticker,
        catalyst_type=ct,
        headline=req.catalyst_headline,
        source=req.catalyst_source,
        price_at_news=req.price_at_news,
        float_shares=req.float_shares,
        market_cap=req.market_cap,
        is_premarket=req.is_premarket,
        time_of_day_bucket=req.time_of_day_bucket,
        rvol_before_news=req.rvol_before_news,
        volume_acceleration_before_news=req.volume_acceleration_before_news,
    )
    return {"success": True, "event_id": event.id}

@router.post("/events/{event_id}/label")
async def label_event(event_id: str, req: LabelEventRequest) -> Dict[str, Any]:
    """Label a single event with outcome data."""
    outcome = get_controller().label_event(event_id, req.price_path)
    if outcome is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return {"success": True, "outcome": outcome.model_dump(mode="json")}

@router.post("/events/label-batch")
async def label_batch(req: LabelBatchRequest) -> Dict[str, Any]:
    """Label multiple events in batch."""
    results = {}
    for event_id, price_path in req.event_price_paths.items():
        outcome = get_controller().label_event(event_id, price_path)
        results[event_id] = {
            "outcome_class": outcome.outcome_class.value if outcome else None,
            "move_pct": outcome.move_after_news_pct if outcome else None,
        }
    return {"success": True, "results": results}


@router.post("/build-dataset")
async def build_dataset() -> Dict[str, Any]:
    """Trigger a dataset rebuild from available sources."""
    controller = get_controller()
    events = controller.dataset_builder.get_events(limit=5000)
    return {
        "success": True,
        "total_events": len(events),
        "resolved": sum(1 for e in events if e.outcome is not None),
        "message": "Dataset is current. Add events via POST /events to grow the dataset.",
    }


@router.get("/results")
async def get_results() -> Dict[str, Any]:
    """Get the most recent training run results."""
    controller = get_controller()
    report = controller._last_run_report
    if not report:
        return {"success": True, "has_results": False, "message": "No training run completed yet"}
    return {"success": True, "has_results": True, "report": report}


@router.post("/missed-opportunities")
async def analyze_missed_opportunities(req: Dict[str, Any]) -> Dict[str, Any]:
    """Cross-reference missed runners against historical winning patterns."""
    missed = req.get("missed", [])
    insights = get_controller().analyze_missed_opportunities(missed)
    return {"success": True, "count": len(insights), "insights": insights}
