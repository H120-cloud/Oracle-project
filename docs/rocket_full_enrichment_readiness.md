# Rocket Full Enrichment Readiness

## Recommendation

**GO for the resumable full enrichment run.**

**NO-GO for ML training until the full enrichment run completes and its final
class distribution is audited.**

No ML model was built. No production alert or Telegram logic was modified.

## Provider Symbol Normalization

A centralized formatter now lives in
`src/services/ticker_normalization.py`. Internal symbols keep their stable
hyphen form. Translation happens only at provider boundaries.

| Provider | Class-share format |
|---|---|
| Polygon | dot, for example `BRK.A` |
| Alpaca | dot, for example `BRK.A` |
| Finnhub | dot, for example `BRK.A` |
| Alpha Vantage | dot, for example `BRK.A` |
| Yahoo chart API | hyphen, for example `BRK-A` |
| yfinance | hyphen, for example `BRK-A` |

The historical dataset contains four class-share symbols:

- `BRK-A`
- `BRK-B`
- `HEI-A`
- `PBR-A`

All four are explicitly mapped. Arbitrary hyphenated symbols are intentionally
left unchanged so warrant-style tickers are not rewritten accidentally.

## Final Cold Smoke Validation

The final validation used an isolated empty state directory:

`data/agentic/rocket_forward_enrichment/smoke_v3_final`

It processed 25 mixed ticker/date rows. The sample deliberately included all
four observed class-share symbols, common names, runner-style names, and
previously troublesome names.

| Metric | Value |
|---|---:|
| Rows examined | 25 |
| Mixed ticker/date groups | 25 |
| Rows newly labeled | 25 |
| Remaining unknown rows in batch | 0 |
| Success rate | 100.0% |
| Enrichment latency | 589.0 seconds |
| Average latency per group | 23.6 seconds |
| Provider failures | 0 |
| Normalization failures | 0 |
| Drawdown quality: `intraday_exact` | 25 |

The cold sample included:

`BRK-B`, `BRK-A`, `PBR-A`, `HEI-A`, `AEHL`, `ALGN`, `BAND`, `CIEN`, `DKS`,
`FLEX`, `HLLY`, `KMPR`, `MLKN`, `NWSA`, `PZZA`, `SHEL`, `TCOM`, `VNET`,
`AEMD`, `CWBK`, `JBLU`, `PODD`, `USB`, `HOOD`, `ZVRA`.

### Provider Results

| Provider | API calls | Successful groups | Failed groups |
|---|---:|---:|---:|
| Polygon | 50 | 25 | 0 |
| Alpaca fallback | 0 | 0 | 0 |
| yfinance fallback | 0 | 0 | 0 |

Polygon supplied both required paths for every row. The fallback chain remains
covered by the enrichment regression suite and by the earlier live smoke run,
where Alpaca filled Polygon misses and failures were logged per provider.

## Checkpoint And Cache Safety

A second run used the same isolated state directory.

| Metric | Value |
|---|---:|
| Cache hits | 25 |
| Checkpoint skips | 25 |
| Provider API calls | 0 |
| Resume latency | 2.0 seconds |

The engine writes one durable JSON cache record per successful ticker/date
group and an atomic checkpoint. Partial cache records are refillable. Failed
groups remain resumable and are not marked complete.

## Full-Run Estimate

After merging the representative smoke rows without overwriting the original
dataset:

| Metric | Value |
|---|---:|
| Remaining unknown rows | 25,740 |
| Remaining unknown ticker/date groups | 4,366 |
| Remaining unknown tickers | 2,448 |
| Expected Polygon calls per group | 2 |
| Expected Polygon calls | 8,732 |
| Polygon free-tier runtime at 5 requests/minute | 29.1 hours |

Budget **30 to 40 hours** for the first full pass. The lower bound assumes
Polygon behaves like the final cold smoke. Retries and fallbacks can extend
runtime. The earlier pre-fix upper-bound measurement was approximately 68
hours.

## Expected Label Recovery

The final representative cold batch recovered 100% of its labels. The earlier
mixed smoke recovered 96%. A prudent planning range is **90% to 98%** of the
remaining unknown rows, or approximately **23,166 to 25,225** additional
labels. The exact result must be measured after the resumable run; unsupported
OTC symbols and provider history gaps remain the main uncertainty.

## Recommended Full-Run Settings

```text
POLYGON_REQUESTS_PER_MINUTE=5
ALPACA_REQUESTS_PER_MINUTE=180
YFINANCE_REQUESTS_PER_MINUTE=30
```

Use a dedicated full-run state directory. Reuse that directory for every
resume. Do not delete it until the final exports and audit have been checked.

## Verification

- Focused normalization tests: **6 passed**
- Rocket enrichment and reconstruction tests: **32 passed**
- Full repository suite: **280 passed, 1 expected xfail**
- Cold representative smoke: **25/25 groups labeled**
- Warm checkpoint resume: **25/25 groups skipped, 0 API calls**

