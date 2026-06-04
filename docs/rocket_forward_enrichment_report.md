# Rocket Forward Enrichment Smoke Report

## Scope

This report covers a 25-row mixed-ticker, mixed-date smoke batch only. The full
historical run was not started. No ML model was trained. Production alert and
Telegram logic were not modified.

The smoke run used:

1. Polygon first
2. Alpaca fallback
3. yfinance final fallback
4. Existing stored outcome fields when fetched bars were unavailable

## Implemented Engine

`src/core/agentic/rocket_forward_enrichment.py` provides:

- durable JSON bar cache under `data/agentic/rocket_forward_enrichment/`
- atomic checkpoint resume
- structured provider failure logs
- safe retries with backoff
- provider-specific rate limiting
- mixed ticker/date smoke selection
- CSV and Parquet v2 smoke exports without overwriting prior datasets
- label reconstruction after enrichment
- preserved `drawdown_data_quality`: `intraday_exact`, `daily_proxy`, or `missing`

## Smoke Coverage

| Metric | Value |
|---|---:|
| Rows examined | 25 |
| Mixed ticker/date groups | 25 |
| Unknown rows before smoke enrichment | 25 |
| Unknown rows after smoke enrichment | 1 |
| Unknown rows newly labeled | 24 |
| Smoke success rate | 96.0% |
| Cached groups written | 24 |
| New drawdown labels | 1 |

The full v2 smoke export remains row-aligned with the 29,085-row reconstructed
dataset:

| Label | Before Smoke | After Smoke |
|---|---:|---:|
| `STANDARD_WIN` | 222 | 222 |
| `MAJOR_RUNNER` | 40 | 40 |
| `MONSTER_RUNNER` | 11 | 11 |
| `LEGENDARY_RUNNER` | 10 | 11 |
| `NON_RUNNER` | 2,994 | 3,017 |
| Provisional labels | 43 | 43 |
| `UNKNOWN` | 25,765 | 25,741 |

## Cold Run Measurements

The first cold-cache smoke run completed in approximately 15 minutes.

| Provider | API Calls | Successful Groups | Failed Groups | Success Rate |
|---|---:|---:|---:|---:|
| Polygon | 76 | 24 | 1 | 96.0% |
| Alpaca | 31 | 21 | 1 | 95.5% |
| yfinance | 10 | 0 | 1 | 0.0% |
| **Total** | **117** | - | - | - |

This run exposed a Polygon parser defect: valid daily candles timestamped at
midnight were incorrectly removed by an intraday regular-session filter.
`src/services/polygon_provider.py` now applies that filter only to intraday
candles.

Because the cold run occurred before that parser correction, its 117-call count
is a conservative upper-bound measurement rather than the expected steady-state
cost.

## Resume Proof

The same checkpoint was resumed after the Polygon daily-bar fix. It completed
in 87 seconds.

| Metric | Value |
|---|---:|
| Durable cache hits | 24 |
| Checkpoint skips | 21 |
| Partial cache entries upgraded | 3 |
| Failed groups retried | 1 |
| API calls during resume | 15 |

The resume run proves successful groups are cached locally, completed work is
not repeated, and partial cache records can be upgraded after a provider fix.

## Failure Reasons

The remaining unresolved smoke group was `BRK-A|2026-05-27`.

- Polygon returned empty bars.
- Alpaca rejected `BRK-A` as an invalid symbol.
- yfinance returned empty bars.
- A provider-specific class-share normalization pass such as `BRK-A` to
  `BRK.A` should be implemented and tested before a full run.
- yfinance also emitted an SSL certificate failure for `GUYGF`, confirming it
  must remain a final fallback.

## Full-Run Estimate

The remaining workload contains:

| Metric | Value |
|---|---:|
| Unknown rows | 25,765 |
| Distinct ticker/date groups | 4,367 |
| Distinct tickers | 2,448 |

Measured and projected API-cost bounds:

| Scenario | Calls Per Group | Estimated API Calls | Polygon Free-Tier Runtime at 5 Calls/Minute |
|---|---:|---:|---:|
| Observed pre-fix cold upper bound | 4.68 | 20,438 | 68.1 hours |
| Expected post-fix baseline: intraday + daily Polygon calls | 2.00 | 8,734 | 29.1 hours |
| Warm-cache resume example | 0.60 | 2,620 | 8.7 hours |

The expected post-fix baseline is a projection, not a completed cold-cache
measurement. A fresh post-fix cold-cache rerun was attempted but could not be
started because the desktop execution allowance was exhausted.

## Cost And Rate-Limit Risk

- Polygon free tier is the main runtime constraint. Keep
  `POLYGON_REQUESTS_PER_MINUTE=5` unless the account tier is confirmed.
- The engine retries transient failures, logs provider failures, and resumes
  from checkpoint, so interruption does not lose completed work.
- Alpaca fallback reduces missing data, but historical feed entitlements and
  symbol formatting can still reject some rows.
- yfinance SSL is unreliable in this environment and historical intraday
  retention is limited. Keep it as the final fallback only.
- A full free-tier run is likely to take approximately 29 to 68 hours,
  depending on fallback usage and retries.

## Recommended Full-Run Settings

Do not start the full historical run yet.

Before approval:

1. Add and test provider-specific class-share normalization for symbols such as
   `BRK-A`.
2. Run one fresh 25-row cold-cache smoke batch after execution allowance is
   available.
3. Confirm the post-fix cold call count is close to the projected two Polygon
   requests per group.

Recommended settings after that check:

```text
POLYGON_REQUESTS_PER_MINUTE=5
ALPACA_REQUESTS_PER_MINUTE=180
YFINANCE_REQUESTS_PER_MINUTE=30
```

Use a dedicated full-run state directory so cache and checkpoint state remain
separate from smoke evidence.

## Verification Status

Completed before the desktop execution allowance was exhausted:

- focused forward-enrichment and Polygon tests: 10 passed
- relevant Rocket test set: 64 passed
- full repository suite: 275 passed, 1 expected xfail
- live 25-row cold smoke batch: completed
- live checkpoint resume: completed

The full historical enrichment run has not been started.
