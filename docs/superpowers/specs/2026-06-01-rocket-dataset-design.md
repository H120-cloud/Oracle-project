# Rocket Dataset Builder — Design Spec
**Date:** 2026-06-01
**dataset_version:** `rocket_v1`
**builder_version:** `1.0.0`
**Status:** Approved — ready for implementation

---

## 1. Goal

Transform raw and resolved alert streams into a unified, leak-free training dataset containing multi-tier velocity labels, MFE/MAE window profiles, and drawdown-quality classifications based on forward pricing data.

**Critical constraints (non-negotiable):**
- No ML model training, tuning, or building.
- No modification to `OutcomeResolver`, Telegram alert logic, or production gates.
- No forward-pricing data in feature columns (strict anti-leakage).
- No imputation inside the builder — leave that to the ML training pipeline.

---

## 2. Module Layout

```
src/core/agentic/
  rocket_dataset_builder.py     ← new module

tests/unit/
  test_rocket_labeler.py        ← new test file

data/agentic/
  rocket_training_dataset.csv       ← exported labeled dataset
  rocket_training_dataset.parquet   ← same, Parquet/snappy
  rocket_rejected_rows.csv          ← audit log of rejected rows

docs/
  rocket_dataset_report.md      ← calibration report (output artifact)
```

No other files are created or modified.

---

## 3. Architecture

`RocketDatasetBuilder` runs a four-stage sequential pipeline. `build()` is the only public method and returns a `BuildSummary`.

```
RocketDatasetBuilder.build() → BuildSummary
  ├── _ingest()    → List[RocketRecord]   (5 sources → unified model + anchor validation)
  ├── _enrich()    → List[RocketRecord]   (fetch missing forward pricing, best-effort)
  ├── _label()     → List[RocketRecord]   (apply pure label functions)
  └── _assemble()  → BuildSummary         (leakage filter, export, report)
```

All four label functions live at **module level** (not on the class) — pure, no I/O, directly importable for unit tests:

```python
compute_peak_metrics(bars, alert_price, alert_time) → PeakMetrics
compute_runner_tier(peak_move_pct, time_to_peak_minutes, use_trading_time) → str | None
compute_mfe_mae_profiles(bars, alert_price, alert_time) → MFEMAEProfiles
compute_drawdown_quality(bars, alert_price, tier, drawdown_data_quality) → str | None
```

---

## 4. Data Models

### 4.1 RocketRecord

Fields are grouped into three explicit zones enforced by the leakage manifest.

```python
class RocketRecord(BaseModel):
    # ── Identity ──────────────────────────────────────────
    row_id: str                       # "{source_type}_{alert_id}"
    source_type: str                  # "telegram"|"shadow"|"backfill"|"missed"|"prenews"
    rejection_reason: str | None = None
    dataset_version: str = "rocket_v1"
    builder_version: str = "1.0.0"

    # ── AT-ALERT FEATURES (exported — leakage-safe) ───────
    ticker: str
    alert_time: datetime
    price_at_alert: float
    catalyst_type: str | None
    catalyst_subtype: str | None
    catalyst_category: str | None
    session_type: str | None
    float_category: str | None
    market_cap_category: str | None
    move_pct_at_alert: float | None
    rvol_at_alert: float | None
    volume_at_alert: int | None
    spread_pct_at_alert: float | None
    trap_risk_at_alert: float | None
    dilution_risk_at_alert: float | None
    velocity_score_at_alert: float | None
    sources_seen_count: int | None
    is_negative: bool | None
    is_vague: bool | None
    is_delayed_reaction: bool | None
    prenews_anomaly_score: float | None
    ml_predicted_win_prob: float | None
    news_impact_score: float | None
    expected_return_score: float | None
    continuation_probability: float | None
    multi_day_score: float | None
    sec_dilution_probability: float | None
    sec_toxic_financing_score: float | None
    sec_warrant_overhang_score: float | None
    sec_cash_runway_score: float | None
    sec_survival_risk_score: float | None
    sec_balance_sheet_quality_score: float | None
    sec_offering_risk_score: float | None
    sec_reverse_split_risk_score: float | None
    sec_structural_trap_risk_score: float | None
    sec_historical_dilution_behavior_score: float | None
    sec_dilution_behavior: str | None
    sec_oracle_action: str | None
    sec_atm_active: bool | None
    sec_going_concern_active: bool | None

    # ── FORWARD PRICING (internal only — not in manifest, never exported) ──
    intraday_bars: list | None = None
    daily_bars: list | None = None
    # Fallback resolved fields carried over from existing JSON records.
    # Used only as label-engine inputs when bar data is unavailable.
    # Excluded from FEATURE_COLUMNS and LABEL_COLUMNS — never exported.
    stored_mfe_pct: float | None = None
    stored_mae_pct: float | None = None
    stored_return_next_day_high_pct: float | None = None
    stored_return_two_day_high_pct: float | None = None
    stored_return_five_day_high_pct: float | None = None

    # Dedup tracking (internal only)
    duplicate_of: str | None = None
    dropped_source_type: str | None = None
    kept_source_type: str | None = None
    dedup_reason: str | None = None

    # ── LABELS (exported) ─────────────────────────────────
    outcome_window_start: datetime | None = None
    peak_move_pct: float | None = None
    peak_timestamp: datetime | None = None
    calendar_time_to_peak_minutes: float | None = None
    trading_time_to_peak_minutes: float | None = None
    mfe_15m: float | None = None
    mfe_60m: float | None = None
    mfe_1d: float | None = None
    mfe_2d: float | None = None
    mfe_5d: float | None = None
    mae_15m: float | None = None
    mae_60m: float | None = None
    mae_1d: float | None = None
    mae_2d: float | None = None
    mae_5d: float | None = None
    runner_tier: str | None = None
    drawdown_quality: str | None = None
    drawdown_data_quality: str | None = None   # "intraday_exact"|"daily_proxy"|"missing"
    outcome_source: str | None = None          # "bars"|"stored_resolved"|"daily_proxy"|"missing"
    data_quality_score: float | None = None    # 0–100, explicit weights
```

### 4.2 BuildSummary

```python
class BuildSummary(BaseModel):
    total_ingested: int
    total_rejected: int
    total_exported: int
    runner_tier_counts: dict[str, int]
    drawdown_quality_counts: dict[str, int]
    null_rate_by_feature: dict[str, float]
    rejection_reasons: dict[str, int]
    output_paths: dict[str, str]
    pricing_fetch_stats: dict[str, int]   # "fetched"/"cache_hit"/"unavailable"
    dataset_version: str
    builder_version: str
    created_at: datetime
```

### 4.3 String Constants (not Python Enum — avoids pandas serialisation friction)

```python
RUNNER_TIERS   = {"STANDARD_WIN", "MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}
DRAWDOWN_QUAL  = {"CLEAN_RUNNER", "DIRTY_RUNNER", "TRAP"}
DRAWDOWN_DQ    = {"intraday_exact", "daily_proxy", "missing"}
OUTCOME_SOURCE = {"bars", "stored_resolved", "daily_proxy", "missing"}
SOURCE_TYPES   = {"telegram", "shadow", "backfill", "missed", "prenews"}
```

---

## 5. Ingestion Layer (`_ingest`)

### 5.1 Source → RocketRecord Field Mapping

| Source file | `source_type` | `alert_time` | `price_at_alert` | catalyst |
|---|---|---|---|---|
| `news_momentum_telegram_alerts.json` | `"telegram"` | `sent_at` | `price_at_alert` | `catalyst_type` |
| `news_momentum_shadow_alerts.json` | `"shadow"` | `sent_at` | `price_at_alert` | `catalyst_type` |
| `news_momentum_backfill_records.json` | `"backfill"` | `sent_at` | `price_at_alert` | `catalyst_type` |
| `news_momentum_missed_winners.json` | `"missed"` | `news_time` | `price_at_news` | `catalyst_sub_type` |
| `pre_news_shadow_v2.json` | `"prenews"` | `detection_time` | `price_at_detection` | `null` (allowed) |

`outcome_window_start` is always set to `alert_time` during ingestion.

### 5.2 Anchor Validation

A row is rejected (not crashed) if any anchor is absent or invalid. The `rejection_reason` field records why.

| Anchor | Rule | Applies to |
|---|---|---|
| `ticker` | Non-empty string | All |
| `alert_time` | Parseable aware UTC datetime | All |
| `price_at_alert` | float > 0 | All |
| `catalyst_type OR catalyst_subtype` | At least one non-null, non-empty | All except `prenews` |

`peak_move_pct` is **not** validated at ingestion — it is a label computed in Stage 3.

### 5.3 Deduplication

After all five sources are loaded, deduplicate on `(ticker, alert_time_rounded_to_minute)`.

Priority (highest wins): **telegram > missed > prenews > shadow > backfill**

Dropped duplicates are not discarded — they are retained with dedup metadata populated:
```
duplicate_of:         row_id of the kept record
dropped_source_type:  source_type of the dropped record
kept_source_type:     source_type of the kept record
dedup_reason:         "priority_order"
```
These appear in the calibration report's Duplicate Summary section.

### 5.4 Stored Outcome Forwarding

Existing resolved fields on telegram/backfill records (`mfe_pct`, `mae_pct`, `return_*_pct`) are mapped to internal `_stored_*` fields during ingestion. These are used as fallback inputs by the label engine when bar data is unavailable. They are **never exported** as features or labels.

---

## 6. Enrichment Layer (`_enrich`)

For each record where both `intraday_bars` and `daily_bars` are absent:

```python
provider = get_market_data_provider()
intraday_bars = provider.get_ohlcv(ticker, period="30d", interval="5m")   # best-effort
daily_bars    = provider.get_ohlcv(ticker, period="30d", interval="1d")   # best-effort
```

- Rate-limited at **0.25s between calls**.
- Failures logged at `DEBUG` level. Never raised. Record continues with whatever was retrieved.
- Records that already have `five_day_high` populated **skip the daily fetch** (not re-fetched).

After fetching, `drawdown_data_quality` is set:
- `"intraday_exact"` — 5m bars fetched successfully and cover the alert window.
- `"daily_proxy"` — only daily bars available.
- `"missing"` — neither available; stored resolved fields used as fallback.

---

## 7. Label Engine (`_label`) — Pure Functions

### 7.1 `compute_peak_metrics(bars, alert_price, alert_time) → PeakMetrics`

Scans all bars in the 5-day observation window for the bar with the highest `high`.

Returns:
- `peak_move_pct` = `(peak_high / alert_price − 1) × 100`
- `peak_timestamp` = bar timestamp of that high
- `calendar_time_to_peak_minutes` = actual wall-clock minutes from `alert_time` to `peak_timestamp`
- `trading_time_to_peak_minutes` = minutes during active market sessions only (excludes overnight gaps); falls back to `calendar_time_to_peak_minutes` when session data is unavailable

Fallback (no bars): if `stored_return_five_day_high_pct` is populated, uses it as `peak_move_pct` with all timestamp fields `null`.

### 7.2 `compute_runner_tier(peak_move_pct, time_to_peak_minutes, use_trading_time) → str | None`

Evaluated sequentially at descending milestones. A 400% mover is checked against LEGENDARY first — it cannot be compressed into MONSTER.

```
peak_window_days = time_to_peak_minutes / (60 × 6.5)   [trading-normalised]

if peak_move_pct >= 300 and peak_window_days <= 5:  → "LEGENDARY_RUNNER"
elif peak_move_pct >= 100 and peak_window_days <= 5: → "MONSTER_RUNNER"
elif peak_move_pct >= 30  and peak_window_days <= 2: → "MAJOR_RUNNER"
elif peak_move_pct >= 10  and peak_window_days <= 1: → "STANDARD_WIN"
else:                                                → None
```

Uses `trading_time_to_peak_minutes` when available; falls back to `calendar_time_to_peak_minutes`.

### 7.3 `compute_mfe_mae_profiles(bars, alert_price, alert_time) → MFEMAEProfiles`

For each window `[15m, 60m, 1d, 2d, 5d]`, scans bars in `[alert_time, alert_time + window]`:
- `mfe_Xw` = max `(high / alert_price − 1) × 100` in window
- `mae_Xw` = min `(low / alert_price − 1) × 100` in window (negative = adverse)

**Daily proxy fallback:** when only daily bars available, `mfe_15m`, `mae_15m`, `mfe_60m`, `mae_60m` are set to `null`; daily-granularity windows (1d, 2d, 5d) are populated from daily bar highs/lows.

**Stored-fields fallback** (no bars at all):
```
stored_return_next_day_high_pct → mfe_1d
stored_return_two_day_high_pct  → mfe_2d
stored_return_five_day_high_pct → mfe_5d
```
All MAE fields stay `null` in this case.

### 7.4 `compute_drawdown_quality(bars, alert_price, tier, drawdown_data_quality) → str | None`

Target thresholds by tier:
```
STANDARD_WIN    → +10%
MAJOR_RUNNER    → +30%
MONSTER_RUNNER  → +100%
LEGENDARY_RUNNER → +300%
```

Evaluation (chronological bar scan):

**TRAP triggers if either rule fires:**
- Rule 1: price rises ≥ +20% from alert, then later falls to ≤ −20% from alert price.
- Rule 2: price rises ≥ +20% from alert, then loses ≥ 40% from that peak (catches pump-and-dump structures that never return below alert price).

**If target never reached:** returns `null` (not a runner — no drawdown quality assigned).

**If target reached:**
- Rolling MAE ≤ −15% occurred **before** target was first breached → `"DIRTY_RUNNER"`
- Rolling MAE never reached −15% before target → `"CLEAN_RUNNER"`

**`drawdown_data_quality` behaviour:**
- `"intraday_exact"` — full classification available.
- `"daily_proxy"` — classification proceeds with daily-bar lows; result is labelled `CLEAN_RUNNER` or `DIRTY_RUNNER` but report flags these rows as lower-confidence.
- `"missing"` — returns `null`.

### 7.5 `data_quality_score` Weights (sum = 100, capped at 100)

| Component | Points |
|---|---|
| Intraday bars available | 30 |
| Peak timestamp available | 10 |
| Runner tier assigned | 10 |
| Drawdown quality assigned | 10 |
| MFE/MAE windows populated (8 pts × 5 windows) | 40 |
| **Maximum** | **100** |

---

## 8. Assembly & Export (`_assemble`)

### 8.1 Leakage Manifest

**FEATURE_COLUMNS** (exported — at-alert only):
```
row_id, source_type, ticker, alert_time, price_at_alert,
catalyst_type, catalyst_subtype, catalyst_category, session_type,
float_category, market_cap_category, move_pct_at_alert, rvol_at_alert,
volume_at_alert, spread_pct_at_alert, trap_risk_at_alert, dilution_risk_at_alert,
velocity_score_at_alert, sources_seen_count, is_negative, is_vague,
is_delayed_reaction, prenews_anomaly_score, ml_predicted_win_prob,
news_impact_score, expected_return_score, continuation_probability, multi_day_score,
sec_dilution_probability, sec_toxic_financing_score, sec_warrant_overhang_score,
sec_cash_runway_score, sec_survival_risk_score, sec_balance_sheet_quality_score,
sec_offering_risk_score, sec_reverse_split_risk_score, sec_structural_trap_risk_score,
sec_historical_dilution_behavior_score, sec_dilution_behavior, sec_oracle_action,
sec_atm_active, sec_going_concern_active,
dataset_version, builder_version
```

**LABEL_COLUMNS** (exported — forward-derived):
```
outcome_window_start, peak_move_pct, peak_timestamp,
calendar_time_to_peak_minutes, trading_time_to_peak_minutes,
mfe_15m, mfe_60m, mfe_1d, mfe_2d, mfe_5d,
mae_15m, mae_60m, mae_1d, mae_2d, mae_5d,
runner_tier, drawdown_quality, drawdown_data_quality,
outcome_source, data_quality_score
```

Any column on `RocketRecord` not in either manifest is **dropped and reported** in the "Dropped Non-Manifest Columns" section of the calibration report — never silently discarded.

### 8.2 Row Filtering

- Only rows passing all anchor checks **and** having at least one non-null label are exported to the main dataset.
- Rejected rows go to `data/agentic/rocket_rejected_rows.csv` (contains `row_id`, `source_type`, `ticker`, `rejection_reason` only — no pricing fields).

### 8.3 Output Files

```
data/agentic/rocket_training_dataset.csv      (UTF-8, pandas to_csv)
data/agentic/rocket_training_dataset.parquet  (snappy compression)
data/agentic/rocket_rejected_rows.csv         (audit log)
docs/rocket_dataset_report.md                 (calibration report)
```

---

## 9. Calibration Report Structure (`docs/rocket_dataset_report.md`)

```markdown
## Run Metadata
dataset_version / builder_version / created_at / total runtime

## Row Counts
ingested / exported / rejected — broken down by source_type

## Rejection Summary
rejection_reason → count → % of ingested

## Duplicate Summary
kept_source_type / dropped_source_type / dedup_reason → count

## Pricing & Enrichment
Fetch stats: fetched / unavailable
outcome_source distribution

## Runner Tier Distribution
STANDARD_WIN / MAJOR_RUNNER / MONSTER_RUNNER / LEGENDARY_RUNNER / unlabeled + %

## Drawdown Quality Distribution
CLEAN_RUNNER / DIRTY_RUNNER / TRAP / null + %
⚠️ daily_proxy rows counted separately — lower-confidence classification

## Feature Null Rates
feature column → null count → null %

## Segmentation Breakdowns
- By catalyst_category
- By float_category
- By market_cap_category
- By price bucket (<$1 / $1–5 / $5–10 / >$10, derived from price_at_alert)

## Dropped Non-Manifest Columns
column_name → reason ("not in FEATURE_COLUMNS or LABEL_COLUMNS")
```

---

## 10. Test Coverage (`tests/unit/test_rocket_labeler.py`)

| Test | Verifies |
|---|---|
| `test_runner_tier_boundaries` | Exact thresholds at 10/30/100/300%; boundary values (9.99%, 10.0%, 29.99%, 30.0%) |
| `test_legendary_not_compressed` | 400% peak within 3 trading days → `LEGENDARY_RUNNER`, not `MONSTER_RUNNER` |
| `test_clean_vs_dirty_runner` | MAE hits −15% after target → `CLEAN`; MAE hits −15% before target → `DIRTY` |
| `test_trap_rule_1` | +20% then −21% from alert → `TRAP` |
| `test_trap_rule_2` | +120% then +40% (66.7% peak loss) → `TRAP` |
| `test_trap_rule_2_not_triggered` | +35% then +25% (28.6% peak loss) → not `TRAP` |
| `test_missing_pricing_safe` | Empty bars list → all label fields `null`, no exception raised |
| `test_data_quality_score_bounds` | Score always in [0, 100] for any input combination |
| `test_data_quality_score_deterministic` | Same input → identical score on repeated calls |
| `test_daily_proxy_never_intraday_exact` | Records with only daily bars → `drawdown_data_quality != "intraday_exact"` |

---

## 11. Constraints Checklist

- [ ] `OutcomeResolver` unchanged
- [ ] Telegram alert logic unchanged
- [ ] Production gate logic unchanged
- [ ] No ML model training or tuning
- [ ] No imputation inside the builder
- [ ] No forward-pricing fields in FEATURE_COLUMNS
- [ ] All label functions are pure (no I/O, no global state)
- [ ] `data_quality_score` bounded 0–100
- [ ] `drawdown_data_quality` uses 3-value string enum (no None ambiguity)
- [ ] `outcome_source` uses 4-value string enum
- [ ] `daily_proxy` rows flagged in report with lower-confidence note
- [ ] Dropped non-manifest columns reported, not silently discarded
- [ ] Rejected rows written to audit CSV, not dropped silently
