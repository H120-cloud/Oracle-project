# Rocket Feature Enrichment Report — Finnhub Company Profiles

**Date:** 2026-06-10
**Change:** Shadow-prediction feature rows are now enriched from Finnhub's
`company_profile2` endpoint (cached, telemetered) to fill the model's two most
informative missing categoricals.
**Isolation:** telemetry-side only — candidates, Telegram alerts, News-Momentum
gating, and the Rocket shadow-only contract are untouched.

---

## 1. What was missing and why it mattered

- `market_cap_category` and `float_category` are **hardcoded `None` on the
  pre-news pipeline** (`build_shadow_feature_row`) and frequently missing on
  news candidates.
- They are among the model's highest-importance features (float/market-cap
  sensitivity is central to the runner thesis), so the model saw `__MISSING__`
  for exactly the signal it cares most about.
- Every missing field also raises `feature_null_count`, which drives
  `prediction_confidence` to LOW (HIGH requires ≤6 nulls, MEDIUM ≤16).

## 2. Implementation

- **`src/core/agentic/rocket_feature_enrichment.py`**
  - `FinnhubProfileEnricher.get_profile(ticker)` → `market_cap`,
    `shares_outstanding` (converted from Finnhub's millions), `exchange`,
    `country`, `industry`.
  - **Caching:** per-ticker TTL cache (default 6h, env-tunable via
    `FINNHUB_PROFILE_CACHE_TTL_SECONDS`); unknown tickers are negatively
    cached so they are not re-fetched every scan. Free-tier safe (60 req/min).
  - **Category derivation** reuses the *exact* orchestrator thresholds that
    labelled the training data (float: <5M/<20M/<100M; mcap: <50M/<300M/<2B) —
    avoiding a train/live distribution mismatch. When data is unavailable the
    category stays `None`; we never fabricate a default.
  - **Telemetry:** `stats()` → requests, successes, cache_hits, success_rate.
- **`rocket_model_shadow.predict_candidate`** enriches the feature-row *copy*
  (never the candidate object), and records per prediction:
  `feature_null_count_before`, `feature_null_count` (after), `enriched`,
  `profile_exchange/country/industry`.
- **Diagnostics** (`/api/v1/admin/rocket-shadow` → `summary.quality` + cards):
  avg feature_null_count (before/after), HIGH-confidence %, enrichment
  coverage rate, and live enricher stats.

## 3. Measured impact (real trained artifact, local experiment)

Synthetic nano-cap pre-news candidate (price $2.10, RVOL 6.5, suspicion 78),
scored by the production CatBoost artifact with and without an enriched
profile (mcap $42M → `nano`, shares 12.5M → `low`):

| | feature_null_count | confidence | runner | major | monster | rank |
|---|---|---|---|---|---|---|
| **Without enrichment** | 22 | LOW | 0.892 | 0.793 | 0.793 | 0.8127 |
| **With enrichment** | **20** | LOW | 0.840 | 0.678 | **0.654** | 0.7023 |

### Reading the numbers honestly

- **feature_null_count: −2 per enriched row** — exactly the two filled
  categories. Pre-news rows carry many other nulls (SEC features, spread,
  sources), so this alone does not flip a pre-news row out of LOW.
- **Confidence distribution:** the tier gains land on rows near the
  boundaries — news rows at 17–18 nulls cross into **MEDIUM** (≤16), and
  well-populated news rows at 7–8 nulls cross into **HIGH** (≤6). Live
  before/after averages now accumulate in the diagnostics
  (`avg_feature_null_count_before` vs `avg_feature_null_count`).
- **The probabilities moved materially** (monster 0.793 → 0.654). This is the
  real win: with `__MISSING__` the model leaned on priors learned from rows
  that *happened* to lack data; with true categories it conditions on the
  actual float/cap regime. Predictions become better-informed — in this
  example more conservative, which is the desired behaviour for an
  un-validated nano-cap.

## 4. Estimated impact on Rocket model input quality

- **Pre-news pipeline:** 100% of rows previously had both categories missing →
  with a working Finnhub key, coverage is bounded only by Finnhub's symbol
  coverage (US-listed: high). Expect ~2-null reduction on every pre-news row
  and the model's float/cap interactions to activate for the first time on
  that pipeline.
- **News pipeline:** fills the subset of candidates where the yfinance-based
  enrichment failed (cloud-blocked) — previously a major gap on Railway.
- **Training feedback loop:** future shadow rows logged with real categories
  make the next retrain's dataset richer for the same features.
- Live numbers to watch on the Rocket Shadow tab: *Avg Missing Features*
  (expect ≈2 lower than `avg_feature_null_count_before`), *Enrichment
  Coverage* (expect >0.8 with a valid key), *HIGH Confidence %* (expect a
  modest rise as boundary rows cross).

## 5. Examples of enriched candidates

- `DEMO` (experiment above): profile NASDAQ/US/Biotechnology, mcap $42M →
  `market_cap_category=nano`, shares 12.5M → `float_category=low`;
  nulls 22→20; monster probability corrected 0.793→0.654.
- Live examples will appear in the predictions JSONL with
  `"enriched": true` and `profile_*` fields from the first deploy with
  `FINNHUB_API_KEY` set.

## 6. Tests (all watched fail first — TDD)

`tests/unit/test_rocket_feature_enrichment.py` (7 tests):
successful enrichment · never-overwrite existing categories · missing Finnhub
data degrades cleanly · per-ticker cache (1 API call) · negative caching of
unknown tickers · canonical threshold derivation (incl. None → None) ·
end-to-end predict integration asserting `feature_null_count_before > after`
**and that the candidate object is never mutated** (gating isolation).

## 7. Verification

- Full suite: **797 passed, 1 xfailed, 0 failures** (see session log).
- Frontend `vite build`: ✅
- Requires `FINNHUB_API_KEY` on Railway (already recommended for quotes);
  without it the enricher is a silent no-op and rows behave exactly as before.
