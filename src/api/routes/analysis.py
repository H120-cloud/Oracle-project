"""
V3 Analysis API routes — volume profile, regime, segmentation, stage.
"""

from datetime import datetime
from fastapi import APIRouter, Query

from src.services.market_data import get_market_data_provider
from src.core.volume_profile import VolumeProfileEngine
from src.core.regime_detector import RegimeDetector
from src.core.stock_segmenter import StockSegmenter
from src.core.stage_detector import StageDetector
from src.core.bearish_detector import BearishDetector
from src.models.schemas import ScannedStock

router = APIRouter(prefix="/analysis", tags=["analysis"])

_provider = get_market_data_provider()


@router.get("/volume-profile/{ticker}")
def get_volume_profile(ticker: str):
    """Compute volume profile for a ticker."""
    try:
        bars = _provider.get_ohlcv(ticker.upper(), period="1d", interval="1m")
        if len(bars) < 10:
            return {"error": "Not enough data", "bars_available": len(bars)}
        engine = VolumeProfileEngine()
        result = engine.compute(bars)
        if result is None:
            return {"error": "Could not compute volume profile"}
        return result.model_dump()
    except Exception as e:
        return {"error": f"Volume profile failed: {str(e)}"}


@router.get("/regime/{ticker}")
def get_regime(ticker: str):
    """Detect market regime for a ticker."""
    try:
        bars = _provider.get_ohlcv(ticker.upper(), period="5d", interval="5m")
        if len(bars) < 30:
            return {"error": "Not enough data", "bars_available": len(bars)}
        detector = RegimeDetector()
        result = detector.detect(bars)
        if result is None:
            return {"error": "Could not detect regime"}
        return result.model_dump()
    except Exception as e:
        return {"error": f"Regime detection failed: {str(e)}"}


@router.get("/stage/{ticker}")
def get_stage(ticker: str):
    """Detect stage of move for a ticker."""
    try:
        bars = _provider.get_ohlcv(ticker.upper(), period="1d", interval="5m")
        if len(bars) < 15:
            return {"error": "Not enough data", "bars_available": len(bars)}
        detector = StageDetector()
        result = detector.detect(ticker.upper(), bars)
        if result is None:
            return {"error": "Could not detect stage"}
        return result.model_dump()
    except Exception as e:
        return {"error": f"Stage detection failed: {str(e)}"}


@router.get("/segment/{ticker}")
def get_segment(ticker: str):
    """Classify the stock type/segment."""
    try:
        # Fetch basic info using provider
        quote = _provider.get_live_quote(ticker.upper())
        
        stock = ScannedStock(
            ticker=ticker.upper(),
            price=quote.get("price", 0),
            volume=quote.get("volume", 0),
            rvol=None,
            market_cap=quote.get("market_cap"),
            float_shares=None,
            scan_type="segment_check",
        )
        segmenter = StockSegmenter()
        result = segmenter.classify(stock)
        return result.model_dump()
    except Exception as e:
        return {"error": f"Segment classification failed: {str(e)}"}


@router.get("/live-quote/{ticker}")
def get_live_quote(ticker: str):
    """Get fast live quote with premarket + afterhours data."""
    return _provider.get_live_quote(ticker.upper())


@router.get("/complete/{ticker}")
def get_complete_analysis(ticker: str):
    """Get complete analysis for a ticker (price, regime, stage, volume profile, features)."""
    ticker = ticker.upper()

    try:
        # Single fast live quote call for price + premarket + afterhours
        quote = _provider.get_live_quote(ticker)
        current_price = quote.get("price", 0)

        # Fetch bars ONCE with prepost=True, reuse everywhere
        bars_1m = _provider.get_ohlcv(ticker, period="1d", interval="1m", prepost=True)
        bars_5m = _provider.get_ohlcv(ticker, period="5d", interval="5m")

        result = {
            "ticker": ticker,
            "price": current_price,
            "timestamp": datetime.utcnow().isoformat(),
            "quote": quote,
        }

        # Volume Profile (uses 1m bars we already fetched)
        try:
            if len(bars_1m) >= 10:
                vp_engine = VolumeProfileEngine()
                vp = vp_engine.compute(bars_1m)
                if vp:
                    result["volume_profile"] = vp.model_dump()
        except Exception:
            pass

        # Regime (uses 5m bars we already fetched)
        try:
            if len(bars_5m) >= 30:
                regime_detector = RegimeDetector()
                regime = regime_detector.detect(bars_5m)
                if regime:
                    result["regime"] = regime.model_dump()
        except Exception:
            pass

        # Stage (reuses 1m bars)
        try:
            if len(bars_1m) >= 30:
                stage_detector = StageDetector()
                stage = stage_detector.detect(ticker, bars_1m)
                if stage:
                    result["stage"] = stage.model_dump()
        except Exception:
            pass

        # Dip Features — compute from bars we already have
        try:
            dip = _provider.compute_dip_features(ticker)
            if dip:
                result["dip_features"] = dip.model_dump()
        except Exception:
            pass

        # Bounce Features
        try:
            bounce_result = _provider.compute_bounce_features(ticker)
            if bounce_result and bounce_result[0]:
                result["bounce_features"] = bounce_result[0].model_dump()
        except Exception:
            pass

        return result

    except Exception as e:
        return {
            "ticker": ticker,
            "price": 0,
            "error": str(e)
        }


@router.get("/bearish/{ticker}")
def get_bearish_analysis(ticker: str):
    """Get bearish transition / exit warning analysis for a ticker."""
    ticker = ticker.upper()
    
    try:
        # Get OHLCV data for analysis
        bars_1m = _provider.get_ohlcv(ticker, period="1d", interval="1m")
        
        # Get volume profile for support level analysis
        volume_profile = None
        try:
            if len(bars_1m) >= 10:
                vp_engine = VolumeProfileEngine()
                volume_profile = vp_engine.compute(bars_1m)
        except Exception:
            pass
        
        # Run bearish detection
        detector = BearishDetector()
        result = detector.detect(ticker, bars_1m, volume_profile)
        
        if result:
            return result.model_dump()
        
        return {
            "ticker": ticker,
            "bearish_state": "unknown",
            "bearish_probability": 0,
            "exit_warning": "none",
            "error": "Insufficient data for analysis"
        }
        
    except Exception as e:
        return {
            "ticker": ticker,
            "bearish_state": "unknown",
            "bearish_probability": 0,
            "exit_warning": "none",
            "error": str(e)
        }
