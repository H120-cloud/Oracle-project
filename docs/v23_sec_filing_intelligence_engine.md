# SEC Filing Intelligence & Dilution Risk Engine (V23)

## Overview

Oracle now understands **structural quality**.

A stock with an FDA approval and a clean balance sheet is fundamentally different from a stock with the same FDA approval but an active ATM program, toxic convertibles, and a history of reverse splits. The SEC Filing Intelligence Engine analyses SEC filings to produce structural scores that feed directly into the momentum pipeline — boosting clean plays and vetoing structural traps before they ever reach your Telegram.

## Architecture

```
EDGAR RSS Feed  ──>  SEC EDGAR Fetcher  ──>  NLP Analyzer  ──>  Scoring Engine
                                                             │
                                                             ├─> Dilution History
                                                             └─> Cross-Analysis
                                                              (momentum adjustments)
```

### Modules

| Module | Role | File |
|---|---|---|
| Models | Enums + Pydantic structs | `src/core/agentic/sec_filing_models.py` |
| EDGAR Fetcher | Ticker→CIK + filings + text | `src/core/agentic/sec_edgar_fetcher.py` |
| NLP Analyzer | Regex/keyword classification | `src/core/agentic/sec_filing_analyzer.py` |
| Dilution History | Aggregated stats + behaviour class | `src/core/agentic/sec_dilution_history.py` |
| Scoring Engine | 9 structural scores + action | `src/core/agentic/sec_scoring_engine.py` |
| Orchestrator | Top-level controller + persistence + learning | `src/core/agentic/sec_intelligence_orchestrator.py` |
| API Routes | REST endpoints | `src/api/routes/sec_intelligence.py` |
| Frontend | Dashboard panel | `frontend/src/pages/SECIntelligence.jsx` |

## Supported Filings

- S-1, S-3, S-3ASR, F-1, F-3
- 424B5, 424B4, 424B3, 424B2
- 8-K, 6-K, 10-Q, 10-K, 20-F
- DEF 14A, PRE 14A
- Schedule 13D / 13G
- Form 3 / 4
- NT 10-K / NT 10-Q

## NLP Detection Categories

### Dilution Events

- ATM Offering
- Direct Offering / Public Offering
- PIPE Financing
- Warrant Issuance / Exercise
- Convertible Note
- Equity Line Financing
- Toxic Financing (variable conversion, reset features)
- Shelf Registration
- Share Authorization Increase
- Reverse Split
- Bankruptcy

### Survival Signals

- Going Concern warning
- Low Cash Runway
- Covenant Risk
- Debt Restructuring
- Bankruptcy Risk
- Auditor Warning
- Nasdaq Deficiency

### Positive Structure Signals

- Debt Payoff
- Insider Buying
- Financing Completed
- Warrant Cleanup
- Reduced Liabilities
- Improved Cash Position
- Buyback Authorization

## Structural Scores (0–100)

| Score | Higher = | Derived from |
|---|---|---|
| `dilution_probability_score` | Worse | ATM / shelf / PIPE / share auth / low runway |
| `toxic_financing_score` | Worse | Variable conversion / reset / equity line |
| `warrant_overhang_score` | Worse | Warrant issuances (minus cleanups) |
| `cash_runway_score` | Better | Going concern / low runway / positive cash signals |
| `survival_risk_score` | Worse | Going concern / auditor / covenant / Nasdaq |
| `balance_sheet_quality_score` | Better | Debt payoff / buyback / reduced liabilities vs going concern |
| `offering_risk_score` | Worse | 424B5 / S-3 / active ATM in last 90 days |
| `capital_raise_probability` | Worse | Dilution probability + survival risk composite |
| `reverse_split_risk_score` | Worse | Reverse split filings + Nasdaq deficiency |
| `structural_trap_risk_score` | Worse | Weighted composite of the above |
| `historical_dilution_behavior_score` | Worse | Offerings frequency / RS history / share growth / toxic history |

## Dilution Behavior Classification

| Label | Score Range | Meaning |
|---|---|---|
| CLEAN_STRUCTURE | 0–20 | No history of offerings; likely safe |
| OCCASIONAL_DILUTION | 20–45 | Some dilution; caution warranted |
| SERIAL_DILUTER | 45–70 | Frequent offerings; likely sells into spikes |
| TOXIC_DILUTION_PATTERN | 70–100 | Repeated toxic financing; high shareholder destruction |

## Oracle Structural Action

| Action | Trigger | Effect on Momentum |
|---|---|---|
| **TRADEABLE** | Clean balance sheet + positive sentiment + no dilution | Boost expected return + continuation |
| **SWING_WATCH** | Minor structural flags or neutral | Small caution |
| **CAUTION** | Moderate dilution probability / warrant overhang | Reduced multi-day continuation |
| **AVOID_CHASE** | Imminent offering / high trap risk | Heavy penalties; may veto alert if trap >80 |
| **STRUCTURAL_TRAP** | Going concern + toxic financing | Vetoes the alert entirely |

## Momentum Integration

The SEC engine is wired into `NewsMomentumOrchestrator`:

1. **Score adjustment** (`_apply_sec_intelligence`): After momentum scores are computed, the SEC profile is fetched. If structural data exists:
   - High dilution → `expected_return -= 15`, `trap_risk += 18`
   - Toxic financing → `expected_return -= 20`, `multi_day -= 25`
   - Clean balance sheet + no dilution → `expected_return += 8`, `multi_day += 12`

2. **Telegram gating** (`_should_send_telegram`): If SEC says `STRUCTURAL_TRAP` or very high structural trap risk, the alert is **vetoed** — no matter how good the news looks.

3. **Telegram message** (`_format_telegram_message`): A new SEC Intelligence section is appended to every Telegram alert showing:
   - Structure quality label
   - Dilution probability / offering risk / cash runway / balance sheet quality
   - Structural trap risk
   - Flags (active ATM, going concern, toxic financing, etc.)

4. **Learning loop**: Every Telegram alert record now captures 14 SEC structural fields (`sec_dilution_probability`, `sec_toxic_financing_score`, etc.) so the ML model and future learning loops can train on structural data too.

## Background Loop

`_sec_intelligence_scan_loop()` runs every hour:
- Scans up to 25 active candidate tickers
- Refreshes latest SEC filings from EDGAR
- Re-analyses text and re-scores
- Safe on network failures (graceful degradation)

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/sec-intelligence/candidates` | All analysed tickers |
| GET | `/api/v1/sec-intelligence/candidates/{ticker}` | Full profile for one ticker |
| GET | `/api/v1/sec-intelligence/filings` | Recent filings across all tickers |
| GET | `/api/v1/sec-intelligence/dilution-risk` | Ranked by dilution probability |
| GET | `/api/v1/sec-intelligence/structural-traps` | AVOID_CHASE / STRUCTURAL_TRAP |
| GET | `/api/v1/sec-intelligence/clean-watchlist` | Clean balance sheet tickers |
| GET | `/api/v1/sec-intelligence/serial-diluters` | Serial / toxic diluters |
| GET | `/api/v1/sec-intelligence/history/{ticker}` | Share count + offering history |
| POST | `/api/v1/sec-intelligence/scan-now` | Ad-hoc scan for tickers |
| GET | `/api/v1/sec-intelligence/stats` | Shadow-mode learning stats |

## Telegram Alert Examples

### Clean Structure Example

```
🚨 HIGH IMPACT NEWS MOMENTUM
...

✅ CLEAN STRUCTURE
Structure: CLEAN_STRUCTURE | Dilution Risk: LOW
Dilution Prob: 10/100 | Offering Risk: 5/100
Cash Runway: 85/100 | Balance Sheet: 82/100
Struct. Trap Risk: 12/100
SEC Action: TRADEABLE
Flags: no structural flags
```

### Structural Trap Warning

```
🚨 HIGH IMPACT NEWS MOMENTUM
...

⚠️ STRUCTURAL RISK FLAGGED
Structure: SERIAL_DILUTER | Dilution Risk: HIGH
Dilution Prob: 75/100 | Offering Risk: 80/100
Cash Runway: 22/100 | Balance Sheet: 30/100
Struct. Trap Risk: 78/100
SEC Action: AVOID_CHASE
Flags: active ATM, going concern, toxic financing, 4 offerings/12mo
Why: Active ATM — every spike likely sold into. Toxic financing terms detected.
```

## Learning Loop & Shadow Mode

The SEC engine tracks its own outcomes via `StructuralAlertOutcome`:
- Did dilution occur within 30 days?
- Was an offering announced?
- Did a reverse split follow?
- Did the assessed trap risk accurately predict failure?

Promotion gate:
- Requires **100 resolved outcomes** before live weight changes
- Requires **30 examples per filing category**
- Compares old vs new scoring before auto-promotion

## Tests

Run:
```bash
python -m pytest tests/test_sec_intelligence.py
```

Coverage:
- ATM / PIPE / warrant / convertible / reverse split / going concern / toxic financing / buyback detection
- Materiality scoring
- Filing sentiment derivation
- Dilution history aggregation + behaviour classification
- All 9 structural scores
- Oracle structural action derivation
- Cross-analysis adjustments (penalties + bonuses + vetoes)
- Orchestrator persistence round-trip
- Telegram formatting with SEC section

## Future Roadmap

- **Share count graph**: Visualise `share_history` growth over time
- **CIK-to-ticker fallback**: Direct EDGAR search when CIK cache misses
- **Inline 10-Q/10-K parsing**: Extract cash balance and quarterly burn rates directly from financial statements
- **Peer comparison**: Benchmark structural scores against industry averages
- **Convertible pricing model**: Estimate implied dilution from conversion price + stock price
- **ATM pace tracker**: Estimate how fast an ATM program is draining float
- **Nasdaq compliance timeline**: Days-to-compliance for deficiency letters
