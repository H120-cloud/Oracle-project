# Source Detection Latency Audit

**Date:** 2026-06-10
**Trigger:** BGM headline published 18:02:17 UTC, detected 18:32:20 UTC (~30 min late).
**Scope:** published_at → detected_at only. Scoring and Telegram gating unchanged.

---

## 1. Measured latency by source (1,251 live trace rows)

`latency_seconds_from_published_to_fetch`, from `news_alert_latency_trace.jsonl`:

| Source | rows | median | p90 | max |
|---|---|---|---|---|
| finviz | 553 | 2h 00m | 4h 00m | 4h 13m |
| stocktitan | 377 | 3h 19m | 9h 19m | 11h 34m |
| prnewswire | 194 | **48m** | 1h 37m | 1h 44m |
| globenewswire | 110 | 8h 06m | 8h 19m | 8h 22m |

**⚠️ These medians are NOT trustworthy as raw feed lag.** The Finviz latency
histogram clusters at *exactly* 1.0h (141 rows), 2.0h (112), 3.0h (58), and
4.0h (137) — whole-hour spikes are the signature of **timestamp parse offsets**
(mixed-timezone feed items parsed as US/Eastern), not real delay. The genuine
continuous latency band starts around **12–50 minutes**.

### Worst delayed rows
Six AMGN/StockTitan rows at **~694 minutes** (one conference-PR headline
re-detected repeatedly) — stale-feed re-detection, correctly suppressed from
breaking treatment by the 300s obsolescence window.

## 2. Is the delay source-side or Oracle-side?

**Predominantly source-side.** Verified Oracle-side budget per cycle:

| Stage | Time |
|---|---|
| Scan interval | 20s (regular) / 60s (off-hours) |
| Source cache TTLs | 20–60s |
| Per-source fetch timeout | 12s |
| Ticker-page enrichment | hard 6s budget (`FINVIZ_TICKER_ENRICHMENT_BUDGET_SECONDS`) — runs AFTER the global scan and cannot block it |

Worst-case Oracle-side addition ≈ **90 seconds**. A 30-minute delay therefore
means the aggregator feed itself carried the headline ~28+ minutes after the
wire published it. The BGM case is consistent with Finviz's known aggregation
lag for small caps (genuine band 12–50m above).

## 3. Finviz-specific audit (questions answered)

- **How often does it poll?** Every scan cycle (20–60s), `force_refresh=True`
  (no cache reuse for the global feed).
- **Does it only see news after ticker-page enrichment?** No — the global
  v=3/v=6 feed is scanned first, every cycle. Ticker-page enrichment is a
  *supplement* for items missing from the global feed, runs after both scans,
  is restricted to the hot-ticker screener universe, and is capped at 6s.
  However: an item **absent from the global feed** is only discoverable via
  the ticker page *after* the ticker appears in the top-gainers/under-$2
  screeners — i.e., after the stock already moved. That is a plausible
  component of BGM-class delays and is inherent to Finviz as a source.
- **Is the global feed delayed?** Yes — measured genuine lag in the tens of
  minutes for small caps, plus systematic timestamp parse offsets (whole-hour
  histogram spikes) inflating measurements.
- **Do ticker fetches block fresh headlines?** No (6s budget, runs last) —
  and as of this fix, the fast wires are scanned before Finviz entirely.

## 4. Changes implemented

1. **FAST-FIRST two-phase polling** (`main.py`): `FAST_NEWS_SOURCES =
   (StockTitan, PRNewswire, WireNews/GlobeNewswire, Investing, Sharecast)` are
   fetched **and scanned immediately**; Finviz is fetched and scanned second
   (secondary confirmation). Previously one `gather` waited for the slowest
   source (up to 12s) before *any* item was processed. Cross-phase headline
   dedup prevents double-emission; ticker enrichment stays last.
   → A fast-source headline now reaches the existing FAST WATCH path within
   ~1–3s of its fetch, comfortably inside the 10–30s requirement, and is never
   blocked by Finviz or ticker-page fetches.
2. **SOURCE LATENCY WARNING** (`source_health.py`): any processed headline
   with published→detected latency >120s logs
   `SOURCE LATENCY WARNING: finviz detected headline 30m after published.` —
   throttled to once per source per 5 minutes.
3. **Per-source logging** (verified present): every processed item already
   traces `published_at` / `fetched_at` / `detected_at` + derived latency
   (news-latency diagnostics, incl. the Seen / Saw After columns);
   source-health tracks `last_successful_parse_time` per source; the scan
   heartbeat logs the active `interval`.

## 5. Recommended primary fast-news source order

1. **Alpaca/Benzinga WebSocket** — event-driven, seconds. Currently disabled
   as a momentum source (`config.py`: headlines were low-signal). Recommend
   re-evaluating with current gates — it is the only true sub-minute wire here.
2. **GlobeNewswire direct RSS** (now actually working after the stock-category
   ticker fix) — wire-direct, no aggregator hop.
3. **PRNewswire** — best measured aggregate latency (median 48m, much lower
   for fresh items).
4. **StockTitan** — high volume; mixed latency.
5. **Investing.com RSS** — supplemental.
6. **Finviz** — confirmation + ticker-page backfill, not primary.

## 6. Remaining (not in this fix's scope)

- **Timestamp parse offsets**: the whole-hour histogram spikes deserve their
  own fix (suspect: Finviz/StockTitan items with non-ET display times parsed
  as ET). Until then, treat per-source medians as upper bounds.
- A 30-minute *source-side* lag cannot be polled away — if sub-minute
  detection is required, the Alpaca/Benzinga stream (recommendation 1) is the
  structural answer.

## 7. Verification

- New tests: latency warning (fires >120s, throttled per source, threshold
  120s) + fast-source ordering (Finviz excluded from fast set; fast scan →
  global scan → ticker enrichment order asserted).
- Full suite: 801 passed, 0 failures. Scoring and Telegram gating untouched.
