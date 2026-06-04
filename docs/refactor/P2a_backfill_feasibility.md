# P2a Outcome Back-fill Feasibility Note

**Generated:** 2026-05-28  
**Scope:** Determine whether historical shadow-alert and candidate records can have their MFE/MAE outcomes back-filled using existing market-data providers.  
**Constraint:** Read-only assessment. No back-fill execution.

---

## 1. Corrected Data Inventory (per-file date ranges)

The initial audit combined all sources and reported a single earliest/latest date. Per-file inspection shows a very different picture:

| File | Records | Date Range | Days Spanned |
|---|---|---|---|
| `news_momentum_shadow_alerts.json` | 65,480 | 2026-05-25 → 2026-05-27 | **3 days** |
| `news_momentum_telegram_alerts.json` | 11,801 | 2025-01-01 → 2026-05-27 | 17 months |
| `news_momentum_candidates.json` | 20,847 | 2026-05-22 → 2026-05-27 | **6 days** |

**Shadow and candidates are rolling buffers.** The 65,480 shadow records are not a 17-month history — they are three days of dense shadow logging. The candidate file is six days.

This dramatically changes feasibility: **all shadow and candidate records fall well within the free-tier look-back windows of every provider.**

---

## 2. Provider Capabilities and Cutoffs

### 2.1 yfinance (currently configured)

- **API key:** None required (free, unofficial endpoints).
- **Minute-bar look-back:** ~60 days for most tickers; some sources report 7 days for 1-minute, but 5-minute bars are reliably available for 60 days.
- **Coverage of our data:** Shadow (3 days) and candidates (6 days) are fully inside the window. The oldest Telegram alerts (Jan 2025) are **outside** the window.
- **Rate limits:** Yahoo throttles aggressively. The codebase already has a global semaphore (`_QUOTE_SEMAPHORE = 2`), backoff logic (`_MIN_GLOBAL_BACKOFF = 15 s`), and retry-with-jitter.
- **Pre/after hours:** Supported via `prepost=True`.

### 2.2 Polygon.io

- **API key:** `POLYGON_API_KEY` is present in `.env`.
- **Tier:** The module docstring says "free tier" (`polygon_provider.py:1`).
- **Free-tier limits:** 5 API calls / minute, 2 years of historical minute aggregates.
- **Current codebase coverage:** Only `fetch_premarket_bars()` and `fetch_afterhours_bars()` exist. There is **no general `get_ohlcv(start, end)`** in the Polygon provider. Extending it would be required to use Polygon for arbitrary-date back-fill.
- **Relevance:** Not needed for shadow/candidates (all recent), but would be the **only** option for resolving Telegram alerts older than ~60 days.

### 2.3 Alpaca

- **API key:** `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are present in `.env`.
- **Tier:** Free IEX feed (module comment at `alpaca_provider.py:431`).
- **Historical minute bars:** Available via `get_stock_bars()` with explicit `start`/`end`. The `AlpacaProvider.get_ohlcv()` already accepts `start` and `end`.
- **Extended hours:** Free IEX feed does **not** include pre/after-hours. The `_fetch_extended_hours()` method already falls back to Polygon → Yahoo for AH/PM.
- **Relevance:** Could serve as a fallback for recent shadow/candidate records, but adds no value over yfinance for data inside the 60-day window.

### 2.4 AlphaVantage

- **API key:** `ALPHAVANTAGE_API_KEY` is present in `.env`.
- **Free-tier limits:** 5 calls / minute, 500 calls / day.
- **Intraday look-back:** Recent ~2 months for 1min/5min/15min/30min/60min.
- **Relevance:** The 500/day cap makes it unsuitable for a bulk back-fill of 3,000+ fetches.

### 2.5 Finnhub

- **API key:** `FINNHUB_API_KEY` is blank in `.env`.
- **Relevance:** Not available.

---

## 3. Effective Date Cutoff Summary

| Provider | Minute-bar look-back | Can resolve shadow/candidates? | Can resolve old Telegram alerts? |
|---|---|---|---|
| yfinance (active) | ~60 days | **Yes** — all records are ≤ 6 days old | No — only last ~60 days |
| Polygon.io (has key) | 2 years | Yes (if provider extended) | **Yes** (if provider extended) |
| Alpaca (has key) | Varies by tier | Yes (recent only, no AH/PM) | Partial |
| AlphaVantage (has key) | ~2 months | Yes (but 500/day cap) | Partial (500/day cap) |
| Finnhub | N/A (no key) | No | No |

**Conclusion:** For shadow alerts and candidates, **yfinance is sufficient** because every record is < 7 days old. For Telegram alerts older than ~60 days, only Polygon.io (with provider extension) or a paid data tier can help.

---

## 4. Resolution Rate Estimate

### 4.1 For shadow alerts (65,480 records, 3 days)

- **Data freshness:** All records are from 2026-05-25 to 2026-05-27. Today is 2026-05-28. These are 1–3 days old — well inside yfinance's window.
- **Expected resolution rate:** High. The main failure modes are:
  - Delisted / renamed tickers (rare for 3-day-old data).
  - Penny stocks / OTC with no yfinance coverage.
  - Temporary yfinance 429 rate-limit blocks.
- **Best estimate:** ~85–95% resolvable for intraday bars (5m), ~95%+ for daily bars.

### 4.2 For candidates (20,847 records, 6 days)

- **Same conditions as shadow.** All records are 1–6 days old.
- **Expected resolution rate:** ~85–95%.

### 4.3 For Telegram alerts > 60 days old

- **Not resolvable with the current provider.**
- The 516 already-resolved Telegram alerts are presumably the ones that fell inside the resolver's 7-day chase window and were resolved in real time.
- For the remaining ~11,300 Telegram alerts older than 60 days, yfinance cannot provide minute bars.

---

## 5. Estimated Runtime and API Cost

### 5.1 Unique fetch units

Fetching per-record is wasteful. Many records share the same ticker on the same day. After deduplication by (ticker, date):

| Source | Unique (ticker, date) |
|---|---|
| Shadow alerts | 2,832 |
| Candidates | 1,332 |
| **Combined** | **3,099** |

### 5.2 yfinance throughput

- The codebase limits itself to **2 concurrent requests** with a 15-second global backoff after a 429.
- In practice, yfinance returns minute bars for a single ticker in ~0.5–2 seconds when not rate-limited.
- With the existing semaphore and polite 0.2s sleep in the resolver, throughput is roughly **1–2 fetches per second** sustained.
- **Estimated time:** 3,099 fetches × ~1.5 s ≈ **4,650 s ≈ 1.3 hours**.
- Add daily-bar fetches (can be batched per ticker across multiple dates): ~30 minutes.
- **Total wall-clock estimate:** **~2 hours** for shadow + candidates.

### 5.3 API cost

- yfinance: Free (but subject to IP-level throttling; aggressive use risks temporary bans).
- Polygon.io: Free tier (no cost, but 5/minute rate limit if extended).
- Alpaca: Free tier (no cost).
- AlphaVantage: Free tier (500/day limit would be exhausted quickly; not recommended).

---

## 6. Recommendation for Unresolvable Records

| Bucket | Action |
|---|---|
| Shadow alerts & candidates (all recent) | **Back-fill using yfinance.** No records need exclusion on age grounds. |
| Telegram alerts ≤ 60 days old | Back-fill using yfinance if desired. |
| Telegram alerts > 60 days old | **Flag as permanently unresolvable with current provider.** Do not silently skip. Options: (a) extend Polygon provider for 2-year history, (b) upgrade to a paid data tier, (c) accept the 516 resolved samples as the only labeled historical set. |

**Important:** The audit script should be updated to report per-file date ranges so future readers are not misled by the combined earliest/latest dates.

---

## 7. Proposed Back-fill Batch Structure

### 7.1 Design principles

- **Do not modify original JSON files in place.**
- **Checkpoint to disk** so an interrupted run resumes without re-fetching.
- **Group by (ticker, date)** to minimize redundant API calls.
- **No silent exceptions.** Data-unavailability failures log a structured reason. Unexpected errors raise.

### 7.2 Suggested batch driver

```text
data/agentic/backfill_runs/
  <run_id>/
    checkpoint.json          # Which (ticker, date) groups are done
    failures.jsonl           # Structured failure log
    shadow_resolved.jsonl    # Resolved shadow outcomes (sidecar)
    candidate_resolved.jsonl # Resolved candidate outcomes (sidecar)
```

**Workflow:**

1. **Load** `shadow_alerts.json` and `candidates.json`.
2. **Group** by `(ticker, date)`.
3. **For each group:**
   a. Check checkpoint — skip if already done.
   b. Fetch 5-day 5m intraday bars + 10-day daily bars via `get_market_data_provider()`.
   c. For each record in the group, compute `_bar_close_at()` and `_max_high_in_range()` using the existing resolver's helper functions.
   d. Compute MFE/MAE using the same math as `AdaptiveTelegramLearning.resolve_outcome()`.
   e. Write resolved fields to the sidecar.
   f. Update checkpoint.
4. **On failure:** Log `(ticker, date, record_id, reason)` to `failures.jsonl` and continue. On unexpected exception, raise.

### 7.3 Candidate-specific mapping

Candidates are `NewsMomentumCandidate`, not `TelegramAlertRecord`. The batch driver must map:

- `published_at` → `sent_at`
- `current_price` → `price_at_alert`
- `ticker` → `ticker`

All other resolution math remains identical.

### 7.4 Shadow-specific handling

Shadow alerts **are** `TelegramAlertRecord` objects with `was_blocked=True`. They parse cleanly into the model. The batch driver can either:

- (Option A) Load them into a temporary `AdaptiveTelegramLearning` instance and call the existing `resolve_one()` method unchanged, then extract the resolved fields.
- (Option B) Extract the resolution math into a pure function and call it directly.

**Recommendation:** Option A requires fewer code changes and guarantees the back-fill uses the exact same logic as live resolution. The resolved fields are then written to the sidecar.

---

## 8. Side Items (deferred, recorded only)

- **Audit script date-range bug:** `scripts/p2a_data_audit.py` combined all sources and reported a single earliest/latest date, which masked the fact that shadow and candidates are rolling buffers. This should be fixed in a follow-up so the audit clearly shows per-file ranges.
- **Streaming parser under-count:** The custom brace-counting JSON streamer was abandoned in favor of `json.load` because nested objects broke it. The dead streaming code should be removed from `scripts/p2a_data_audit.py` to avoid future confusion.
- **13 rare subtypes** (< 5 resolved instances) partially overlap with the P1 semantic-classifier work. List preserved for the P1 audit but no deprecation action taken here.

---

## 9. Go / No-Go Decision Matrix

| Question | Answer |
|---|---|
| Can we resolve shadow alerts? | **Yes.** All 65,480 are ≤ 3 days old. yfinance can fetch minute bars. |
| Can we resolve candidates? | **Yes.** All 20,847 are ≤ 6 days old. yfinance can fetch minute bars. |
| Can we resolve old Telegram alerts? | **No** with current provider. Would need Polygon extension or paid tier. |
| Is the runtime acceptable? | **Yes.** ~2 hours for shadow + candidates, with checkpoint resume. |
| Is there any API cost? | **No.** All viable providers are free tier. |
| Do we need new pip dependencies? | **No.** Existing `yfinance` + `pandas` are sufficient. |

---

## 10. Recommendation

**Proceed with back-fill for shadow alerts and candidates only.**

1. Build the batch driver described in §7.
2. Run it against shadow + candidates using the existing yfinance provider.
3. Re-audit and update `P2a_data_audit.md` with before/after numbers.
4. For the ~11,300 unresolved old Telegram alerts, do **not** attempt back-fill with the current provider. Surface the gap and decide separately whether to extend Polygon or provision a paid tier.

**STOP for owner sign-off before writing any back-fill code.**
