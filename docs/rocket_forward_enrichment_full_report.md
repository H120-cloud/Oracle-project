# Rocket Forward Enrichment Smoke Report

## Scope

Small resumable smoke batch only. The full historical run was not started.
No ML model was trained and no production alert or Telegram logic was modified.

## Smoke Coverage

| Metric | Value |
|---|---:|
| Rows examined | 25,390 |
| Synthetic rows excluded before fetch | 0 |
| Mixed ticker/date groups | 4,016 |
| Unknown rows before smoke enrichment | 25,390 |
| Unknown rows after smoke enrichment | 659 |
| Unknown rows newly labeled | 24,731 |
| Durable cache hits | 2,470 |
| Checkpoint resume skips | 2,468 |
| Failed groups | 73 |

## Final Runner Distribution

| Label | Rows |
|---|---:|
| `LEGENDARY_RUNNER` | 171 |
| `MAJOR_RUNNER` | 1,052 |
| `MONSTER_RUNNER` | 276 |
| `NON_RUNNER` | 20,313 |
| `STANDARD_WIN` | 2,919 |
| `UNKNOWN` | 659 |

## Provider Results

| Provider | API Calls | Successful Groups | Failed Groups | Success Rate |
|---|---:|---:|---:|---:|
| `alpaca` | 356 | 32 | 73 | 30.5% |
| `polygon` | 3,314 | 1,449 | 97 | 93.7% |
| `yfinance` | 300 | 0 | 73 | 0.0% |

## Failure Reasons

- `all_providers_failed`: 73
- `alpaca:1d:empty_bars`: 148
- `alpaca:5m:empty_bars`: 152
- `polygon:1d:empty_bars`: 206
- `polygon:5m:empty_bars`: 220
- `yfinance:1d:empty_bars`: 148
- `yfinance:5m:empty_bars`: 152

## Full-Run Estimate

- Remaining unknown rows before a full run: **25,390**.
- Distinct unknown ticker/date groups: **4,016**.
- Smoke API calls per group: **0.99**.
- Estimated total API calls at the observed rate: **3,970**.
- Polygon-only free-tier lower-bound runtime at 5 requests/minute: **13.2 hours**.
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
