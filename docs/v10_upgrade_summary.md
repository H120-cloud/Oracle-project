# V10 Upgrade: Paper Trading, Validation & Calibration

## Problem Addressed
The system had impressive infrastructure but lacked the 3 things needed to go from "looks professional" to "actually makes money":
1. **No validated edge** — no backtest with real metrics
2. **Uncalibrated confidence** — "75% confidence" didn't mean 75% win rate
3. **No execution** — signals couldn't be acted on
4. **Delayed data** — yfinance has ~15min delay

## What Was Built

### 1. Alpaca Market Data Provider (`src/services/alpaca_provider.py`)
- Drop-in replacement for `YFinanceProvider` implementing `IMarketDataProvider`
- Near-real-time data (IEX: ~seconds, SIP: real-time)
- Free tier available at https://app.alpaca.markets/signup
- Auto-selected when `ALPACA_API_KEY` is set and `MARKET_DATA_PROVIDER=alpaca`
- Falls back gracefully to yfinance if keys not set

### 2. Broker Execution Service (`src/services/broker_service.py`)
- Paper trading with full position tracking
- Local JSON persistence (works without any API keys)
- Optional Alpaca paper trading API integration
- Automatic stop-loss and take-profit monitoring
- Comprehensive P/L tracking per trade
- Performance analytics: win rate, profit factor, Sharpe, drawdown
- Breakdowns by confidence bucket, grade, and HTF bias

### 3. Backtest Validator (`src/core/backtest_validator.py`)
- Runs the **full live pipeline** on historical data
- Produces real metrics: win rate, profit factor, Sharpe ratio, max drawdown
- Confidence calibration check (does 75% confidence actually win 75%?)
- Grade performance analysis (do A-grade signals outperform?)
- HTF impact analysis (does HTF filtering improve results?)
- Rejection analysis (were blocked trades correct blocks?)
- Automated verdict: "has edge" or "does NOT have edge"

### 4. Confidence Calibrator (`src/core/confidence_calibrator.py`)
- Maps raw confidence scores to actual historical win rates
- Builds calibration curve from backtest/paper trade results
- Grade-based adjustments (A-grade adds X%, F-grade subtracts Y%)
- HTF bias adjustments (BULLISH adds X%, BEARISH subtracts Y%)
- Integrated into `DecisionEngine.decide()` — applied automatically
- Persists calibration data in `data/calibration/calibration.json`

### 5. Paper Trading Dashboard (`frontend/src/pages/PaperTrading.jsx`)
- Open positions with real-time P/L
- Closed trade history with exit reasons
- Performance metrics dashboard
- Backtest validation runner with configurable tickers/dates
- Confidence calibration visualization

## New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/paper/positions` | Open paper positions |
| GET | `/api/v1/paper/trades` | Closed trade history |
| GET | `/api/v1/paper/performance` | Performance metrics |
| POST | `/api/v1/paper/close/{ticker}` | Manual position close |
| POST | `/api/v1/paper/execute-signal` | Manual paper trade |
| POST | `/api/v1/paper/validate` | Run backtest validation |
| GET | `/api/v1/paper/validation-results` | Get validation results |
| GET | `/api/v1/paper/calibration` | Calibration profile |
| POST | `/api/v1/paper/calibrate-confidence` | Recalibrate from paper trades |
| GET | `/api/v1/paper/adjust-confidence` | Preview calibrated score |
| GET | `/api/v1/paper/data-provider` | Check active data provider |

## Files Created/Modified

### New Files
- `src/services/alpaca_provider.py` — Alpaca market data provider
- `src/services/broker_service.py` — Paper trading broker
- `src/core/backtest_validator.py` — Full pipeline validation
- `src/core/confidence_calibrator.py` — Score calibration
- `src/api/routes/paper_trading.py` — API routes
- `frontend/src/pages/PaperTrading.jsx` — Frontend dashboard

### Modified Files
- `src/main.py` — Registered paper_trading router, updated version
- `src/config.py` — Added Alpaca + paper trading settings
- `src/services/signal_service.py` — Auto-select Alpaca provider
- `src/core/decision_engine.py` — Integrated confidence calibration
- `src/services/htf_alert_service.py` — Fixed import (AlignmentStatus)
- `src/services/watchlist_service.py` — Fixed missing List import
- `frontend/src/App.jsx` — Added Paper Trading nav + route
- `requirements.txt` — Added alpaca-py
- `.env.example` — Added Alpaca + paper trading vars

## How to Use

### Step 1: Run Validation (No API Keys Needed)
```
POST /api/v1/paper/validate?tickers=AAPL,MSFT,NVDA&start=2024-06-01&end=2024-12-31
```
This runs the full pipeline on historical data and auto-calibrates confidence.

### Step 2: Check Results
```
GET /api/v1/paper/validation-results
```
Look at: win_rate, profit_factor, sharpe, and the verdict.

### Step 3: Paper Trade (Optional Alpaca Keys)
Set `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `.env` for Alpaca paper trading.
Or use local simulation (works out of the box).

### Step 4: Go Live (Only After Validation)
Only proceed to live trading if:
- Win rate > 50%
- Profit factor > 1.2
- Sharpe > 0.5
- 30+ validated trades
- 3-6 months of paper trading
