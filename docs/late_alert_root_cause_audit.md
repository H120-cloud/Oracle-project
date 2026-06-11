# Late Alert Root Cause Audit (Evidence-Only)

> **CORRIGENDUM (2026-06-11):** §2 originally attributed the whole-hour
> latency clusters to timezone misparsing (UTC parsed as ET). A follow-up
> minute/second-level analysis disproved this: every suspect row has
> `published_at = fetched_at − N hours (±1s)` — the signature of Finviz's
> **relative timestamps** ("4 hours ago"), parsed *correctly* but at hour
> granularity, on a cold-start fetch of an overnight feed. A timezone audit
> (Amsterdam server context) confirmed all six news parsers normalize to UTC
> via the source's true timezone with no host-timezone dependency
> (`tests/unit/test_news_timestamp_timezones.py`, 13 regression tests, incl.
> DST edges). The real defect was **precision dishonesty**: hour-granular
> relative times carried HIGH (second-precision) confidence. Fixed: Finviz
> timestamps are now graded — minute-precise → HIGH, hour/day-granular or
> date-only → LOW — so coarse stamps can no longer pollute latency metrics or
> freshness treatment. The §2 impact chain (fresh items mis-treated as stale)
> remains plausible only for genuinely-old-in-feed items, which is
> source-side lag (§5 ordering unchanged).

**Date:** 2026-06-11
**Question:** Are 20–30+ minute-late alerts caused by Oracle processing, source
feeds, late news, or price moving before public news?
**Method:** `scripts/late_alert_audit.py` over
`news_alert_latency_trace.jsonl` (1,251 rows → 104 unique stories → 88 late
cases after dedup), cross-referenced with `pre_news_shadow_v2.json`
(208 anomaly records, 128 tickers). Results:
`data/agentic/late_alert_audit_results.json`. No production behavior changed.

---

## ⚠️ 0. Critical data limitation (read first)

The locally available trace covers **one 16-minute run session**
(2026-06-08 08:05–08:22 UTC — a dev run), because the production trace lives
on Railway's volume. Consequences:

- "ORACLE_LATE" below means *the app was not running when the story published* —
  true for the dev snapshot, **not representative of the 24/7 Railway deployment**.
- The BGM example (published 18:02, detected 18:32) is **not in this trace** —
  it was handled by the Railway instance.
- `telegram_sent_at` is absent for every late row (no prod alert stamps locally),
  so GATE_DELAY / TELEGRAM_DELAY cannot be assessed from this snapshot.
- Exchange intraday bars were unreachable from this machine (yfinance
  hard-blocked, Stooq 404, Finnhub candles premium-only), so bar-derived
  move-before-news fields are null; market-move evidence comes from Oracle's
  own pre-news anomaly detections.

**To complete the audit on real production data:** Diagnostics → News Latency →
Download **JSONL**, place it at `data/agentic/news_alert_latency_trace.jsonl`
(or point the script at it) and re-run `python scripts/late_alert_audit.py`.

## 1. Summary by root cause (88 late cases, local snapshot)

| Root cause | n | % | Reading |
|---|---|---|---|
| **SUSPECT_TIMESTAMP** | 46 | 52% | Latency is an exact whole-hour multiple → **parser backdating, not real lag** |
| ORACLE_LATE (app offline) | 38 | 43% | Story published while the dev app wasn't running — snapshot artifact |
| SOURCE_LATE | 2 | 2% | Loop demonstrably alive during the gap; feed carried the story late |
| UNKNOWN | 2 | 2% | No parseable published_at |
| NEWS_LATE / PRICE_MOVED_BEFORE_NEWS | 0 | 0% | No pre-news anomaly preceded any late headline (see §4) |
| GATE_DELAY / TELEGRAM_DELAY | 0 | 0% | Not assessable from this snapshot (no sent stamps) |

## 2. The robust finding: systematic timestamp backdating (the one result that survives the snapshot limitation)

The 46 SUSPECT_TIMESTAMP cases cluster at **exactly** +1h (14), +2h (8),
+3h (7), +4h (14) — overwhelmingly **Finviz** rows (44/46). Whole-hour offsets
are the signature of display times in other timezones being parsed as
US/Eastern (+4h = UTC parsed as ET in June; +1h/+2h = European-sourced items).
The same parsers run in production, so **production latency measurements carry
the same contamination** — and worse, the backdating has a *behavioral* impact
chain that directly produces late alerts:

1. A fresh headline parsed as "published 1–4h ago" **fails the 300s
   breaking/obsolescence window** → loses first-mover / FAST WATCH treatment
   (the logs show exactly this: *"obsolete feed item for STI — published
   12388s ago … suppressing breaking/first-mover treatment"*).
2. It then alerts only via the slow confirmation path — or is **dropped
   entirely** by the `news_max_age_hours` freshness cutoff.
3. The alert that finally fires looks "20–30+ minutes late" even though the
   feed delivered the story promptly.

**This is an Oracle-side root cause that masquerades as SOURCE_LATE/NEWS_LATE.**

## 3. Top 20 worst late cases

| Ticker | Source | Latency | Class | Headline |
|---|---|---|---|---|
| AMGN | stocktitan | 681m | ORACLE_LATE | AMGEN PRESENTS NEW DATA ACROSS ITS CARDIOMETAB |
| VNRX | stocktitan | 576m | ORACLE_LATE | VolitionRx Announces Pricing of $4.6 Million P |
| NVDA | stocktitan | 546m | ORACLE_LATE | SK Telecom and NVIDIA Build AI Infrastructure |
| NVDA | stocktitan | 546m | ORACLE_LATE | NVIDIA and SK hynix Announce Multiyear Technol |
| ODYS | stocktitan | 531m | ORACLE_LATE | Odysight.ai Establishes At-The-Market (ATM) P |
| ATM | stocktitan | 531m | ORACLE_LATE | Odysight.ai Establishes At-The-Market (ATM) P |
| FFAI | stocktitan | 516m | ORACLE_LATE | Faraday Future Founder and Global CEO YT Jia S |
| LENZ | stocktitan | 516m | ORACLE_LATE | LENZ Therapeutics Announces Everest Medicines |
| BLA | globenewswire | 486m | ORACLE_LATE | Alvotech announces FDA acceptance of Biologics |
| WTW | globenewswire | 486m | ORACLE_LATE | Willis expands its international property faci |
| EEST | globenewswire | 486m | ORACLE_LATE | Decisions taken by Suominen Corporation's Extr |
| STI | stocktitan | 377m | ORACLE_LATE | Solidion Technology Announces $35 Million Priv |
| BTGO | stocktitan | 246m | ORACLE_LATE | BitGo MENA Launches Regulated Electronic Tradi |
| IBM | stocktitan | 245m | ORACLE_LATE | New IBM Study Finds CIOs and CTOs Face Growing |
| RUM | stocktitan | 245m | ORACLE_LATE | Rumble Announces Final Results of Exchange Off |
| NVDA | finviz | 240m | SUSPECT_TIMESTAMP | Exclusive: Nvidia drops dual-piece cooling arc |
| GOOGL | finviz | 240m | SUSPECT_TIMESTAMP | SpaceX's Google deal highlights shift from AI |
| NBIS | finviz | 240m | SUSPECT_TIMESTAMP | Why Is NBIS Stock Rising Over 1% In Overnight |
| NVDA | finviz | 240m | SUSPECT_TIMESTAMP | Weekly news roundup: Taiwan ecosystem strength |
| SHAK | finviz | 240m | SUSPECT_TIMESTAMP | LULU, ELF, SHAK Stocks Hit 52-Week Lows Last W |

(ORACLE_LATE rows here = published overnight before the 08:05 dev session —
the deployed instance's classification for the same stories would differ.)

### Timeline example — SUSPECT_TIMESTAMP (NBIS, finviz, +240m exactly)
"Why Is NBIS Stock Rising Over 1% In Overnight…" fetched 08:0x, parsed
published_at exactly 4h00m earlier. A headline *about an overnight move in
progress* is not 4 hours old — the displayed time was UTC, parsed as ET.

### Timeline example — SOURCE_LATE (finviz, loop alive)
Two finviz rows where the scan loop demonstrably fetched other items
throughout the publish→fetch gap (>15m): the aggregator carried the story late.

## 4. Requested case sections

- **Pre-News detected activity before news:** 0 of 88. The 128 pre-news
  tickers and the late-headline set simply don't overlap within 24h windows
  in this snapshot (different ticker universes: pre-news watches screener
  movers; the late set is dominated by large-cap PR). No evidence either way
  about production — re-run on the Railway trace.
- **Oracle detected quickly but Telegram late:** not assessable (no
  telegram_sent stamps in the snapshot). Note the outbox race/backoff fixes
  already shipped earlier this week reduce this class going forward.
- **Finviz/aggregator carried news late:** 2 confirmed (loop-alive) + the BGM
  pattern from the prior audit (genuine 12–50m aggregator band for small caps).
- **Price moved before any public catalyst:** 0 confirmable from local data
  (intraday bars unreachable; see §0).

## 5. Recommended fixes (per the recommendation rules, in evidence order)

1. **Fix the timestamp parsing first** (Oracle-side, highest-confidence
   finding): validate parsed `published_at` against `fetched_at` on the
   item's *first appearance* — a headline first seen at the top of a feed
   whose parsed publish time is an exact 1–4h multiple earlier should be
   distrusted (clamp to fetched_at with `timestamp_confidence=LOW`, or detect
   per-item timezone). This restores FAST WATCH eligibility for fresh news
   currently being suppressed as "obsolete" and un-poisons every latency
   metric. *(Not implemented — this audit is evidence-only.)*
2. **Re-run this audit on the production trace** (download via Diagnostics)
   to get the true ORACLE/SOURCE/GATE/TELEGRAM split, including BGM. The
   script is reusable as-is.
3. Only after 1–2: if production data shows PRICE_MOVED_BEFORE_NEWS dominates,
   strengthen Pre-News discovery; if SOURCE_LATE dominates, the fast-source
   prioritization shipped 2026-06-10 already addresses ordering, and the
   Alpaca/Benzinga stream remains the structural sub-minute option.

**Bottom line:** from the available evidence, the most defensible root cause
of "alerts 20–30+ minutes after the move" is **not** slow polling and **not
proven** to be slow feeds — it is (a) fresh headlines being **backdated by
whole hours by the timestamp parser** and consequently stripped of fast-path
treatment, compounded by (b) genuine aggregator lag in the 12–50m band for
small caps. Confirm proportions with the production trace before any further
source work.
