# Rocket Forward Enrichment Smoke Report

## Scope

Small resumable smoke batch only. The full historical run was not started.
No ML model was trained and no production alert or Telegram logic was modified.

## Smoke Coverage

| Metric | Value |
|---|---:|
| Rows examined | 25 |
| Mixed ticker/date groups | 25 |
| Unknown rows before smoke enrichment | 25 |
| Unknown rows after smoke enrichment | 0 |
| Unknown rows newly labeled | 25 |
| Durable cache hits | 0 |
| Checkpoint resume skips | 0 |
| Failed groups | 0 |

## Final Runner Distribution

| Label | Rows |
|---|---:|
| `LEGENDARY_RUNNER` | 1 |
| `NON_RUNNER` | 24 |

## Provider Results

| Provider | API Calls | Successful Groups | Failed Groups | Success Rate |
|---|---:|---:|---:|---:|
| `polygon` | 50 | 25 | 0 | 100.0% |

## Failure Reasons

- No provider exceptions were recorded.

## Full-Run Estimate

- Remaining unknown rows before a full run: **25,765**.
- Distinct unknown ticker/date groups: **4,367**.
- Smoke API calls per group: **2.00**.
- Estimated total API calls at the observed rate: **8,734**.
- Polygon-only free-tier lower-bound runtime at 5 requests/minute: **29.1 hours**.
- Actual runtime can improve when cache reuse is high or Alpaca fills missing modalities, and can increase when retries are required.

## Risk Assessment

- Polygon free tier is the primary rate-limit risk. Keep the default at 5 requests/minute unless the account tier is confirmed.
- Alpaca fallback reduces missing data but historical feed entitlements may limit older or non-exchange symbols.
- yfinance remains a final fallback only. SSL failures and historical intraday retention limits are logged per group.
- Failed groups remain resumable; successful groups are cached locally and are not refetched.

## Recommended Full-Run Settings

- Review this smoke report before starting a full run.
- Keep `POLYGON_REQUESTS_PER_MINUTE=5` for free tier.
- Keep `ALPACA_REQUESTS_PER_MINUTE=180` unless account limits require a lower value.
- Keep `YFINANCE_REQUESTS_PER_MINUTE=30` and treat it as a final fallback.
- Resume with the same state directory so cached and completed groups are reused.
