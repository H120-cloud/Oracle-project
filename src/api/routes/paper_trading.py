"""Paper Trading & Validation API Routes — V10"""

import logging
from fastapi import APIRouter, Query, BackgroundTasks
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper", tags=["V10 Paper Trading"])

# Singletons (lazy init)
_broker = None
_calibrator = None
_last_validation = None


def _get_broker():
    global _broker
    if _broker is None:
        from src.services.broker_service import BrokerService
        _broker = BrokerService(use_alpaca=False)
    return _broker


def _get_calibrator():
    global _calibrator
    if _calibrator is None:
        from src.core.confidence_calibrator import ConfidenceCalibrator
        _calibrator = ConfidenceCalibrator()
    return _calibrator


# ------------------------------------------------------------------
# Paper Trading Endpoints
# ------------------------------------------------------------------

@router.get("/positions")
def get_positions():
    """Get all open paper positions."""
    broker = _get_broker()
    return {
        "positions": [
            {
                "ticker": p.ticker,
                "qty": p.qty,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "stop_price": p.stop_price,
                "initial_stop": p.initial_stop,
                "targets": p.target_prices,
                "confidence": p.signal_confidence,
                "grade": p.signal_grade,
                "htf_bias": p.htf_bias,
                "highest_price_reached": p.highest_price_reached,
                "moved_to_breakeven": p.moved_to_breakeven,
                "trailing_active": p.trailing_active,
            }
            for p in broker.positions.values()
        ],
        "count": len(broker.positions),
    }


@router.get("/trades")
def get_closed_trades(limit: int = Query(50, ge=1, le=500)):
    """Get closed paper trades."""
    broker = _get_broker()
    trades = broker.closed_trades[-limit:]
    return {
        "trades": [
            {
                "ticker": t.ticker,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_dollars": t.pnl_dollars,
                "pnl_pct": t.pnl_pct,
                "hold_minutes": t.hold_duration_minutes,
                "exit_reason": t.exit_reason,
                "confidence": t.signal_confidence,
                "grade": t.signal_grade,
                "htf_bias": t.htf_bias,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "moved_to_breakeven": t.moved_to_breakeven,
                "trailing_activated": t.trailing_activated,
                "highest_price_reached": t.highest_price_reached,
                "max_r_reached": t.max_r_reached,
                "realized_r": t.realized_r,
            }
            for t in trades
        ],
        "total_closed": len(broker.closed_trades),
    }


@router.get("/performance")
def get_performance():
    """Get comprehensive paper trading performance metrics."""
    broker = _get_broker()
    return broker.get_performance()


@router.post("/close/{ticker}")
def close_position(ticker: str, exit_price: float = Query(...)):
    """Manually close a paper position."""
    broker = _get_broker()
    trade = broker.close_position(ticker.upper(), exit_price, reason="manual")
    if trade:
        return {"status": "closed", "pnl_pct": trade.pnl_pct, "pnl_dollars": trade.pnl_dollars}
    return {"status": "not_found", "message": f"No open position for {ticker}"}


@router.post("/execute-signal")
def execute_signal_manually(
    ticker: str = Query(...),
    price: float = Query(...),
    qty: int = Query(10),
    stop_pct: float = Query(3.0, description="Stop loss percent below entry"),
    target_pct: float = Query(6.0, description="Take profit percent above entry"),
    confidence: float = Query(70.0),
    grade: str = Query("C"),
):
    """Manually create a paper trade (for testing)."""
    from src.services.broker_service import PaperOrder
    from datetime import datetime
    from types import SimpleNamespace

    broker = _get_broker()
    if ticker.upper() in broker.positions:
        return {"status": "error", "message": f"Already in {ticker}"}

    order_id = f"MANUAL-{len(broker.orders)+1:06d}"
    stop = round(price * (1 - stop_pct / 100), 2)
    target = round(price * (1 + target_pct / 100), 2)

    order = PaperOrder(
        order_id=order_id, ticker=ticker.upper(), side="buy", qty=qty,
        order_type="market", stop_price=stop, take_profit_price=target,
        status="filled", filled_price=price,
        filled_at=datetime.utcnow().isoformat(),
        created_at=datetime.utcnow().isoformat(),
        signal_confidence=confidence, signal_grade=grade,
    )
    broker.orders.append(order)
    # Use _open_position to properly initialize trailing stop state
    fake_signal = SimpleNamespace(atr_value=price * (stop_pct / 100))
    broker._open_position(order, stop, [target], fake_signal)
    broker._save_state()
    return {"status": "filled", "order_id": order_id, "stop": stop, "target": target}


# ------------------------------------------------------------------
# Validation Endpoints
# ------------------------------------------------------------------

@router.post("/validate")
def run_validation(
    background_tasks: BackgroundTasks,
    tickers: str = Query("AAPL,MSFT,NVDA,TSLA,AMD", description="Comma-separated tickers"),
    start: str = Query("2024-06-01"),
    end: str = Query("2024-12-31"),
    interval: str = Query("5m", enum=["1m", "5m", "15m", "1h", "1d"]),
    use_htf: bool = Query(True),
):
    """
    Run full backtest validation (background task).
    Results available at GET /paper/validation-results.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    def _run():
        global _last_validation
        try:
            from src.core.backtest_validator import BacktestValidator
            validator = BacktestValidator(max_hold_bars=60, use_htf=use_htf)
            result = validator.validate(ticker_list, start, end, interval)
            _last_validation = result.summary()

            # Auto-calibrate confidence from results
            if result.trades:
                cal = _get_calibrator()
                cal.calibrate_from_trades(result.trades)
                _last_validation["calibration_applied"] = True
        except Exception as e:
            logger.error("Validation failed: %s", e)
            _last_validation = {"error": str(e)}

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "tickers": ticker_list,
        "period": f"{start} to {end}",
        "interval": interval,
        "message": "Validation running in background. Check GET /api/v1/paper/validation-results",
    }


@router.get("/validation-results")
def get_validation_results():
    """Get latest validation results."""
    if _last_validation is None:
        return {"status": "no_results", "message": "Run POST /paper/validate first"}
    return _last_validation


_last_walkforward = None

@router.post("/walk-forward")
def run_walk_forward(
    background_tasks: BackgroundTasks,
    tickers: str = Query("AAPL,MSFT,NVDA,TSLA,AMD"),
    start: str = Query("2022-01-01"),
    end: str = Query("2024-12-31"),
    interval: str = Query("1d", enum=["1h", "1d"]),
    train_months: int = Query(6, ge=2, le=12),
    test_months: int = Query(2, ge=1, le=6),
):
    """Run walk-forward validation (background). Results at GET /paper/walk-forward-results."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    def _run():
        global _last_walkforward
        try:
            from src.core.backtest_validator import BacktestValidator
            validator = BacktestValidator(max_hold_bars=20, use_htf=False)
            _last_walkforward = validator.walk_forward_validate(
                ticker_list, start, end, interval, train_months, test_months,
            )
        except Exception as e:
            logger.error("Walk-forward failed: %s", e)
            _last_walkforward = {"error": str(e)}

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "tickers": ticker_list,
        "period": f"{start} to {end}",
        "train_months": train_months,
        "test_months": test_months,
        "message": "Walk-forward running. Check GET /api/v1/paper/walk-forward-results",
    }


@router.get("/walk-forward-results")
def get_walk_forward_results():
    """Get latest walk-forward validation results."""
    if _last_walkforward is None:
        return {"status": "no_results", "message": "Run POST /paper/walk-forward first"}
    return _last_walkforward


# ------------------------------------------------------------------
# Calibration Endpoints
# ------------------------------------------------------------------

@router.get("/calibration")
def get_calibration():
    """Get current confidence calibration profile."""
    return _get_calibrator().get_profile()


@router.post("/calibrate-confidence")
def calibrate_from_paper_trades():
    """Recalibrate confidence using closed paper trades."""
    broker = _get_broker()
    if len(broker.closed_trades) < 10:
        return {"status": "insufficient_data",
                "message": f"Need 10+ closed trades, have {len(broker.closed_trades)}"}

    cal = _get_calibrator()
    profile = cal.calibrate_from_trades(broker.closed_trades)
    return {
        "status": "calibrated",
        "trades_used": profile.total_trades_used,
        "buckets": len(profile.buckets),
        "grade_adjustments": profile.grade_adjustments,
        "htf_adjustments": profile.htf_adjustments,
    }


@router.get("/adjust-confidence")
def adjust_confidence(
    raw: float = Query(..., description="Raw confidence score"),
    grade: str = Query(None),
    htf_bias: str = Query(None),
):
    """Preview calibrated confidence for a given raw score."""
    cal = _get_calibrator()
    adjusted = cal.adjust(raw, grade, htf_bias)
    return {
        "raw_confidence": raw,
        "calibrated_confidence": adjusted,
        "grade": grade,
        "htf_bias": htf_bias,
        "is_calibrated": cal.profile.is_calibrated,
    }


# ------------------------------------------------------------------
# Data Provider Switch
# ------------------------------------------------------------------

@router.get("/data-provider")
def get_data_provider_status():
    """Check which market data provider is active and available."""
    import os
    alpaca_key = os.getenv("ALPACA_API_KEY", "")
    alpaca_available = bool(alpaca_key)

    try:
        from src.services.alpaca_provider import _alpaca_available as sdk_available
    except ImportError:
        sdk_available = False

    return {
        "current_provider": "alpaca" if alpaca_available and sdk_available else "yfinance",
        "alpaca_sdk_installed": sdk_available,
        "alpaca_key_set": alpaca_available,
        "yfinance_available": True,
        "recommendation": (
            "Using Alpaca (low-latency) ✓" if alpaca_available and sdk_available
            else "Set ALPACA_API_KEY + ALPACA_SECRET_KEY in .env for real-time data. "
                 "Get free keys at https://app.alpaca.markets/signup"
        ),
    }
