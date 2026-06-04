# P2a Data Audit

**Generated:** 2026-05-28
**Scope:** Historical data inventory for backtest feasibility assessment.

---

## 1. Date Range (per file)

| File | Earliest | Latest | Records |
|---|---|---|---|
| news_momentum_shadow_alerts.json | 2026-05-25T04:00:51.189580+00:00 | 2026-05-28T00:48:07.707941+00:00 | 66,770 |
| news_momentum_telegram_alerts.json | 2025-01-01T08:20:00+00:00 | 2026-05-27T20:31:32.079523+00:00 | 11,801 |
| news_momentum_candidates.json | 2026-05-22T18:00:00+00:00 | 2026-05-27T19:50:13.297274+00:00 | 20,847 |

## 2. Total Candidate Count

- **Shadow alerts:** 66,770
- **Telegram alerts:** 11,801
- **Candidates:** 20,847
- **Combined shadow + telegram (alert-relevant):** 78,571

## 3. Resolution Coverage

Backfill run: `run_20260528_002942`

### Before backfill

| Source | Total | Resolved | Fraction |
|---|---|---|---|
| Shadow alerts | 66,770 | 0 | 0.00% |
| Telegram alerts | 11,801 | 516 | 4.37% |
| Candidates | 20,847 | 0 | 0.00% |

### After backfill

| Source | Total | Resolved | Fraction |
|---|---|---|---|
| Shadow alerts | 66,770 | 44,741 | 67.01% |
| Telegram alerts | 11,801 | 516 | 4.37% |
| Candidates | 20,847 | 19,238 | 92.28% |

**Combined resolved (all sources): 64,495**
(44,741 shadow + 516 telegram + 19,238 candidates)

### Per-month resolution fraction (Telegram only)

| Month | Resolved | Fraction (of alerts that month) |
|---|---|---|
| 2025-01 | 0 | 0.00% |
| 2025-02 | 0 | 0.00% |
| 2025-03 | 0 | 0.00% |
| 2025-04 | 0 | 0.00% |
| 2025-05 | 9 | 1.28% |
| 2025-06 | 20 | 3.09% |
| 2025-07 | 25 | 2.89% |
| 2025-08 | 23 | 2.28% |
| 2025-09 | 32 | 3.16% |
| 2025-10 | 28 | 2.27% |
| 2025-11 | 27 | 2.01% |
| 2025-12 | 30 | 2.17% |
| 2026-01 | 36 | 100.00% |
| 2026-02 | 33 | 100.00% |
| 2026-03 | 25 | 100.00% |
| 2026-04 | 34 | 100.00% |
| 2026-05 | 194 | 0.29% |

## 4. Per-month Resolved Count

| Month | Resolved Count | Status |
|---|---|---|
| 2025-05 | 9 | ⚠️ SPARSE (< 50) |
| 2025-06 | 20 | ⚠️ SPARSE (< 50) |
| 2025-07 | 25 | ⚠️ SPARSE (< 50) |
| 2025-08 | 23 | ⚠️ SPARSE (< 50) |
| 2025-09 | 32 | ⚠️ SPARSE (< 50) |
| 2025-10 | 28 | ⚠️ SPARSE (< 50) |
| 2025-11 | 27 | ⚠️ SPARSE (< 50) |
| 2025-12 | 30 | ⚠️ SPARSE (< 50) |
| 2026-01 | 36 | ⚠️ SPARSE (< 50) |
| 2026-02 | 33 | ⚠️ SPARSE (< 50) |
| 2026-03 | 25 | ⚠️ SPARSE (< 50) |
| 2026-04 | 34 | ⚠️ SPARSE (< 50) |
| 2026-05 | 194 | OK |

## 5. Catalyst Subtype Distribution (Resolved Only)

| Subtype | Count | Status |
|---|---|---|
| other | 245 | OK |
| phase_1 | 101 | OK |
| earnings_beat | 62 | OK |
| acquisition | 24 | OK |
| phase_2 | 14 | OK |
| fda_approval | 14 | OK |
| phase_3 | 13 | OK |
| fast_track | 13 | OK |
| government_contract | 13 | OK |
| ai_partnership | 12 | OK |
| profitability_inflection | 2 | ⚠️ RARE (< 5) |
| nvidia_partnership | 2 | ⚠️ RARE (< 5) |
| merger | 1 | ⚠️ RARE (< 5) |

## 6. Walk-forward Window Recommendation

⚠️ **Sparse months detected:** 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04. These months have fewer than 50 resolved records and are unsuitable as standalone validation windows. Consider merging adjacent sparse months or excluding them.

**Recommended approach:**
- Window size: 2–3 months of training data per fold (density-dependent).
- Step size: 1 month forward.
- Minimum validation size: 1 month, but only if that month has ≥ 50 resolved records.
- If the trailing months are sparse, use a cumulative expanding window (all prior data) instead of a fixed-size rolling window.

## 7. Memory Pressure Notes

- Shadow file size: 127.0 MB. Loaded fully with `json.load`; peak working set ~600–800 MB. Acceptable for a one-off audit on a modern workstation.
- Telegram file: 23.5 MB. Loaded fully; trivial memory footprint.
- Candidates file: 51.1 MB. Loaded fully; acceptable for current data volume but should be streamed if it grows > 200 MB.
- **Proposed streaming approach for harness:** If shadow file grows past ~200 MB on disk, switch to `ijson` (after explicit approval) or incremental chunked `json.loads`. Telegram and candidates can remain fully-loaded until they exceed 100 MB each.
