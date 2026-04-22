"""
Backtesting & Performance API routes — V4
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.backtester import Backtester
from src.core.self_learner import SelfLearner
from src.core.order_flow import OrderFlowAnalyzer
from src.services.market_data import get_market_data_provider
from src.models.schemas import BacktestConfig

router = APIRouter(tags=["backtest"])

_provider = get_market_data_provider()


@router.post("/backtest")
def run_backtest(config: BacktestConfig):
    """Run a walk-forward backtest on a ticker."""
    bt = Backtester(market_data=_provider)
    result = bt.run(config)
    return result.model_dump()


@router.get("/performance")
def get_performance(last_n: int = 100, db: Session = Depends(get_db)):
    """Get aggregate performance metrics from historical signals."""
    learner = SelfLearner(db)
    snapshot = learner.get_performance(last_n=last_n)
    return snapshot.model_dump()


@router.get("/performance/adjustments")
def get_adjustments(db: Session = Depends(get_db)):
    """Get self-learning threshold adjustment suggestions."""
    learner = SelfLearner(db)
    adjustments = learner.suggest_adjustments()
    return {"adjustments": [a.model_dump() for a in adjustments]}


@router.get("/order-flow/{ticker}")
def get_order_flow(ticker: str):
    """Get order flow analysis for a ticker."""
    try:
        bars = _provider.get_ohlcv(ticker.upper(), period="1d", interval="5m")
        if len(bars) < 10:
            return {"error": "Not enough data", "bars_available": len(bars)}
        analyzer = OrderFlowAnalyzer()
        result = analyzer.analyze(bars)
        if result is None:
            return {"error": "Could not analyze order flow"}
        return result.model_dump()
    except Exception as e:
        return {"error": f"Order flow analysis failed: {str(e)}"}
