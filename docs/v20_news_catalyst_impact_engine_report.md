# V20 — News Catalyst Impact Engine

**Status:** Implemented · 37 unit tests passing · Advisory-only (no auto-trading)

The News Catalyst Impact Engine extends Oracle Agentic Mode by classifying news headlines into specific catalyst types, scoring their potential price impact (0–100), estimating plausible move ranges, and producing plain-English bull/bear case explanations.

---

## 1. Architecture

```
                ┌───────────────────────────────────────────────┐
News Detection │ CatalystScanner (Finviz + StockTitan + RSS)    │
                └────────────────────┬──────────────────────────┘
                                     │ headline + ticker + source
                                     ▼
       ┌─────────────────────────────────────────────────────────┐
V20    │  News Catalyst Impact Engine                            │
       │  ─────────────────────────────────                      │
       │  1. Classify catalyst type (regex)                      │
       │  2. Detect sector hype                                  │
       │  3. Score 9 components → composite (0-100)              │
       │  4. Build estimated move range                          │
       │  5. Decide IGNORE / WATCH / TRADEABLE / HIGH_IMPACT /   │
       │     EXPLOSIVE / DANGEROUS_TRAP                          │
       │  6. Generate bull / bear case + risks + reasons         │
       └────────────────────┬────────────────────────────────────┘
                            │
                            ▼
       Pre-News History → Agentic Probability → Risk Rules →
       ABCD Confirmation → Entry Timing → ML Advisory →
       Final Alert Decision
```

The engine attaches a `NewsImpactModel` to every `AgenticCandidate` and is invoked in `AgenticOrchestrator._run_pipeline()` after the Pre-News bridge and before the ML advisory, so ML predictions can use catalyst context where useful.

### File map

| Layer | Path |
|-------|------|
| Engine | `src/core/agentic/news_impact_engine.py` |
| Persistence/Learning | `src/core/agentic/news_impact_learning.py` |
| Pydantic models | `src/core/agentic/models.py` (`NewsImpactModel`, `EstimatedMoveRangeModel`) |
| Orchestrator integration | `src/core/agentic/orchestrator.py` (`_evaluate_news_impact`, alert helpers) |
| API routes | `src/api/routes/agentic.py` (`/agentic/news-impact/*`) |
| Frontend API | `frontend/src/api.js` (`newsImpact*` helpers) |
| Frontend UI | `frontend/src/pages/Agentic.jsx` (`newsImpact` tab + panel) |
| Tests | `tests/test_news_impact_engine.py`, `tests/test_news_impact_learning.py` |

---

## 2. Catalyst Hierarchy

The engine recognises 30+ distinct catalyst types, ordered by raw materiality:

| Tier | Score | Catalyst types |
|------|-------|----------------|
| Tier 1 (90–95) | Explosive | FDA approval, Phase 3 readout, buyout offer |
| Tier 2 (80–85) | High impact | Phase 2, breakthrough therapy, M&A, profitability inflection, hyperscaler partnership, guidance raise |
| Tier 3 (65–75) | Tradeable | Earnings beat, government contract, major contract, AI partnership, FDA clearance, PDUFA date |
| Tier 4 (50–60) | Secondary | Crypto treasury, patent win, licensing, Phase 1, fast-track, orphan drug, insider buying |
| Tier 5 (40–55) | Watch | Analyst upgrade, Nasdaq compliance regained, debt restructuring, strategic review |
| Bearish | 5–25 | Offering / dilution, ATM, warrants, reverse split, delisting, vague PR |

Materiality is a *raw* impact value before context (float, market cap, sector, position) is applied.

---

## 3. Scoring Logic

### 9 components (each 0–100)

| Component | Weight | What it measures |
|-----------|-------:|------------------|
| `materiality` | 0.28 | Catalyst-type raw impact |
| `volume` | 0.13 | RVOL confirmation |
| `market_cap` | 0.10 | Smaller cap → higher score |
| `float` | 0.10 | Lower float → higher momentum potential |
| `price_position` | 0.10 | Downgrades parabolic moves |
| `dilution` | 0.10 | Penalises offering / warrant filings |
| `pre_news` | 0.08 | Suspicion score from Pre-News V2 |
| `surprise` | 0.06 | Already-priced-in penalty |
| `short_squeeze` | 0.05 | Short interest |

### Sector hype overlay

If the headline contains a known hype keyword (biotech, AI, quantum, crypto, defense, uranium, obesity, etc.), the composite is multiplied by 1.05–1.25.

### Hard caps & floors

| Condition | Effect |
|-----------|--------|
| Bearish catalyst (offering, ATM, warrant, reverse split, delisting) | Score capped at 35 |
| Vague PR (corporate update, conference attendance) | Score capped at 25 |
| Unconfirmed source | Score × 0.85 |

---

## 4. Decision Logic

```
DANGEROUS_TRAP   ← bearish catalyst OR (parabolic AND non-tier-1)
IGNORE           ← vague PR OR score < 35
WATCH            ← unconfirmed AND score < 60, or score 35-54
TRADEABLE        ← score 55-69
HIGH_IMPACT      ← score 70-79
EXPLOSIVE        ← score ≥ 80 AND RVOL ≥ 2 (or ≥ 85 with pre-news accumulation)
```

Tier-1 catalysts (FDA approval / Phase 3 / buyout) are **not** downgraded for parabolic moves.

### Oracle Action

| Decision | Action |
|----------|--------|
| EXPLOSIVE / HIGH_IMPACT | `WAIT_FOR_RETEST` |
| TRADEABLE / WATCH | `WATCH` |
| DANGEROUS_TRAP (dilution) | `AVOID_TRAP` |
| DANGEROUS_TRAP (parabolic) | `AVOID_CHASING` |
| IGNORE | `IGNORE` |

---

## 5. Estimated Move Range

The engine produces three plausible upside targets and one downside:

```
estimated_move_range = {
    conservative_move_pct: float,   # base case
    bullish_move_pct: float,        # if catalyst plays out
    extreme_squeeze_pct: float,     # tail-case low-float blow-off
    bearish_move_pct: float,        # for bearish catalysts only
    rationale: str,                 # human-readable reasoning
}
```

Examples:

- **FDA approval, micro-cap (<$50M, <5M float):** +30% / +100% / +300%
- **Phase 3, small-cap (<$250M):** +20% / +60% / +150%
- **Earnings beat + guidance raise (small-cap):** +10% / +30% / +80%
- **Public offering (low float):** -10% / -50% (bearish)

Sector hype and pre-news accumulation apply multiplicative boosts.

---

## 6. Telegram Integration

### High-impact alert (`🔥 HIGH IMPACT NEWS — {ticker}`)

Sent when **all** are true:
- `news_impact_score ≥ 70`
- decision in `{TRADEABLE, HIGH_IMPACT, EXPLOSIVE}`
- candidate trap risk < 65
- entry timing not `late_chase`
- not flagged as dilution
- RVOL ≥ 2 (if available)
- 30-min ticker cooldown not active

Body fields: ticker, headline, news type, decision, score, estimated move range, pre-news accumulation, RVOL, float, market cap, entry timing, ABCD state, ML position size, oracle action, summary, why-it-matters, bull case, bear case, key risks, impact reasons, impact warnings.

### Trap warning (`⚠️ DANGEROUS TRAP DETECTED — {ticker}`)

Sent when `news_decision == DANGEROUS_TRAP` AND any of (`trap_warning`, `is_dilution`, `is_parabolic`). Lists trap reasons + recommendation `AVOID_CHASING` / `AVOID_TRAP`. Adds an `(active Agentic candidate)` suffix if the ticker is already tracked.

Both message types are sent via the existing `src.services.telegram_service.send_telegram_alert_sync` helper.

---

## 7. Backend API

All under `/api/v1/agentic/news-impact/`:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/evaluate` | One-shot evaluation of a headline (no persistence) |
| GET | `/candidates?min_score=&decision=` | List active candidates with evaluations |
| GET | `/{ticker}` | Full detail view + related Pre-News + historical outcomes |
| GET | `/learning/summary` | Outcome counts, best/worst catalysts |
| GET | `/learning/recommendations` | Calibration suggestions (advisory only) |

The `/learning/*` routes are registered before the `/{ticker}` catch-all so FastAPI resolves them correctly.

---

## 8. Frontend Integration

A new tab **News Impact** is added to the Agentic dashboard between Alerts and Pre-News.

Each evaluated candidate renders as a card showing:
- Ticker + decision badge (colour-coded: explosive purple, high-impact green, tradeable blue, watch yellow, dangerous-trap red)
- Trap / dilution / parabolic / pre-news flags
- Catalyst type + impact score
- Headline (clamped to two lines)
- Estimated move range, RVOL, float, market cap
- Oracle action

Clicking a card opens a detail panel with: summary, why-it-matters, bull case, bear case, impact reasons, warnings, key risks, related Pre-News linkage, historical outcomes for that catalyst type, and the full estimated move range with rationale.

Filter controls: decision dropdown + minimum-score dropdown.

Stats strip: total outcomes tracked / completed / calibration-ready (≥100 completed).

---

## 9. Learning Loop

Each candidate evaluation is recorded to `data/agentic/news_impact_outcomes.json` with:
- ticker, headline, catalyst type, detected_at, price at detection
- impact score, decision, estimated bullish move
- pre-news / dilution / parabolic flags

A separate update path (`update_price_snapshot`) lets the system fill in:
- price at +15m / +1h / +4h / next day
- MFE / MAE
- continuation quality (`clean / partial / failed / dead / trap`)
- VWAP reclaimed?
- ABCD confirmed?

After ≥100 completed outcomes the engine produces calibration recommendations:

- High trap rate + negative avg move → suggest -10 to materiality
- Strong win rate + positive avg move → suggest +5 to materiality

Recommendations are **never auto-applied**.

---

## 10. Pipeline Position & Guardrails

The engine sits between Pre-News and ML Advisory in `_run_pipeline`:

```python
# orchestrator._run_pipeline (excerpt)
apply_regime_to_candidate(cand)
apply_pre_news_to_candidate(cand)
self._evaluate_news_impact(cand)        # ← V20
cand.ml_prediction = self.learning.predict_ml(cand)
cand.alertable = (
    cand.final_probability >= 70
    and cand.entry_timing.quality == EntryQuality.IDEAL
    and cand.trap.trap_risk_score < 65
    and not cand.failure_velocity.is_distribution
    and abcd_confirmed
)
```

### Guardrails honoured

- Never auto-trades on news alone — `cand.alertable` is unchanged.
- Vague PR is hard-capped at 25.
- Dilution is flagged aggressively and surfaces a `DANGEROUS_TRAP`.
- Reverse-split / delisting catalysts are bearish-tagged.
- Already-parabolic setups are downgraded except for tier-1 catalysts.
- Source-quality drop (unconfirmed) reduces score by 15%.
- `is_unconfirmed` is exposed in the API + UI.
- Late-stage chases are blocked at the alert layer (`entry_timing.late_chase`).

---

## 11. Examples

### Example 1 — Explosive

Input: `ABCD receives FDA approval for new oncology biotech therapy`, market cap $40M, float 4M, RVOL 8×, pre-news suspicion 80.

Output:
- `catalyst_type = fda_approval`
- `news_impact_score ≈ 95`
- `news_decision = EXPLOSIVE`
- `estimated_move_range = +30% / +100% / +300%`
- `oracle_action = WAIT_FOR_RETEST`
- Alert text: *"This is high-impact FDA news on a low-float biotech with pre-news accumulation and strong RVOL confirmation."*

### Example 2 — Dangerous trap

Input: `DILUTE prices public offering of 20M shares`, market cap $50M, float 10M, RVOL 3×.

Output:
- `catalyst_type = offering_dilution`
- `is_dilution = True`
- `news_impact_score ≤ 35`
- `news_decision = DANGEROUS_TRAP`
- `oracle_action = AVOID_TRAP`
- `estimated_move_range.bearish_move_pct ≈ -50%`

### Example 3 — Vague PR

Input: `XYZ provides corporate update on operations`.

Output:
- `catalyst_type = vague_pr`
- `news_impact_score ≤ 25`
- `news_decision = IGNORE`
- `oracle_action = IGNORE`

---

## 12. Tests

**37 tests passing** across two files:

| File | Coverage |
|------|----------|
| `test_news_impact_engine.py` (32 tests) | Classification (FDA, phase trials, M&A, earnings, AI, hyperscaler, crypto, offerings, ATM, reverse split, vague PR), sector hype detection, scoring scenarios (FDA explosive, dilution trap, parabolic downgrade, tier-1 override, pre-news boost, vague-PR cap, unconfirmed reduction, low-volume penalty, micro vs large cap), explanation population, dict serialization, alert-format field availability, bearish catalyst set sanity. |
| `test_news_impact_learning.py` (5 tests) | Record + persist, snapshot updates, per-catalyst stats aggregation, calibration thresholds, empty-state recommendations. |

Run with:

```powershell
python -m pytest tests/test_news_impact_engine.py tests/test_news_impact_learning.py -v
```

---

## 13. Future Calibration Plan

Once ≥100 completed outcomes accumulate (one snapshot per catalyst per scan), the system can recommend:

1. **Materiality nudges** per catalyst type — based on trap rate vs win rate.
2. **Component-weight rebalancing** — if `volume` consistently predicts trap behaviour better than `materiality`, raise its weight.
3. **Move-range calibration** — compare predicted vs realised MFE/MAE, narrow ranges that consistently overshoot.
4. **Sector multiplier refresh** — collapse hype multipliers in sectors that no longer justify them.

All suggestions are surfaced through `GET /agentic/news-impact/learning/recommendations` and the dashboard. They are **never auto-applied**; an operator must approve.

---

## 14. Out of Scope (deliberate)

- Live news verification / source-quality scoring (only `is_unconfirmed` flag is honoured today).
- Short-interest data feed — `short_interest_pct` is accepted as input but never auto-fetched.
- News deduplication across providers — handled by the existing CatalystScanner.
- Auto-trading on catalysts — explicitly forbidden by guardrail #1.

---

## 15. Final Goal Achieved

Oracle no longer says only “News found.” For each catalyst it now produces:

> *“This is high-impact FDA news on a low-float biotech with pre-news accumulation and strong RVOL confirmation. Estimated move potential +80% to +250%. Wait for ABCD retest and IDEAL_ENTRY.”*

Or, when warranted:

> *“This is a dilution-heavy warrant offering after a parabolic move. Failed VWAP reclaim detected. High trap risk. Avoid chasing.”*

Every candidate now carries a fully-explained catalyst impact assessment, surfaced both in the dashboard and in Telegram alerts.
