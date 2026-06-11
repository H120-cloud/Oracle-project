# Production Late-Alert Root Cause Audit

**Date:** 2026-06-11
**Input:** Railway production trace (`news-latency_20260611T030258Z.jsonl`,
12,317 rows, 2026-06-10 00:50 → 06-11 02:49 UTC). Evidence-only — no code,
scoring, or Telegram changes. Local dev trace backed up to
`news_alert_latency_trace.local-dev-backup.jsonl`.

---

## Executive answer

**Yes — Oracle was late, in two distinct, fixable ways, stacked on top of
genuine source lag:**

1. **The production scan loop is freezing.** 44 silent windows >15 min in 26
   hours; **13 of them during market hours (13:00–21:00 UTC), totalling 5.6
   hours of silence** — on a loop that should tick every 20–60 s. The silences
   chain back-to-back (15:07→15:23→15:34→15:49→16:11→16:37→16:48→17:12…),
   the signature of the **event-loop blocking bugs fixed locally on Jun 8–10
   but evidently NOT yet deployed to Railway**.
2. **A systemic ~14-minute internal confirmation delay**: across **all 75
   alerted rows**, fetch → Telegram-sent median is **13.9 min (p90 24.4 min,
   min 0.1 min)**. The fast path can fire in seconds (`min=0.1m`) but
   `is_fast_watch` fired only **9 times in 12,317 rows** — because anything
   first seen after a loop freeze is already >300 s "old", fails the breaking
   /obsolescence window, loses FAST WATCH eligibility, and enters the slow
   confirmation path.

**The freezes therefore hurt twice:** +20–40 min before detection, and then
they strip fast-path treatment so the gate adds another ~10–15 min.

## Root-cause percentages

**BGM-class band (15–60 min late, 1,741 unique stories — the band the
complaint is about):**

| Root cause | share | evidence |
|---|---|---|
| **ORACLE_LATE — loop frozen** | **36%** (624/1741) | story detected immediately after a silent window that covers its publish time |
| SOURCE_LATE — aggregator carried late (upper bound) | ~64% (1117) | loop demonstrably alive; note 687/1741 have relative-derived `published_at` ("30 min ago"-style), so true publish time is bounded, not exact |
| PRICE_MOVED_BEFORE_NEWS (pre-news cross-ref) | 0 confirmed | no pre-news anomaly preceded any late headline (local pre-news file) |
| + systemic GATE adder on every alert | **+13.9 min median** | all 75 alerted rows |

**Extreme set (top-100 worst, audit script output):** ORACLE_LATE 53%,
SOURCE_LATE 42%, GATE_DELAY 4%, SUSPECT_TIMESTAMP 1%. This set is dominated by
**overnight SEC 8-K / GNW items** (filed evenings, surfaced next session,
mostly blocked as `stale_published` — i.e. correctly suppressed, not missed
alerts).

## What happened with BGM specifically (question answered)

| Stage | Time (UTC) | Delta |
|---|---|---|
| Headline (Finviz displayed "30 min ago" at fetch; sub-second match proves relative stamp) | ~18:02:17 | — |
| Scan loop **silent window 18:01 → 18:32** | — | loop frozen the entire interval |
| Oracle fetch/detection | 18:32:17 | **+30.0 min** (freeze) |
| Gate: first evaluation blocked `score_gate(imp=48.7/30 ✓, ret=31.5/35 ✗)` — waiting for reaction confirmation | — | — |
| Telegram sent | 18:47:57 | **+15.7 min** (gate) |
| **Total publish → alert** | | **~45.7 min** |

Three stacked causes: (a) the headline itself is reactive ("BGM **surges ~20%**
on momentum following $12M placement") — the news documents a move already
underway; (b) the **frozen loop** ate 30 minutes; (c) the **confirmation gate**
ate another 15.7. A second evaluation at 19:01 was `ticker_cooldown` (correct).

## Did FAST WATCH fail because timestamp_confidence was LOW?

**No.** The deployed build predates the `timestamp_confidence` grading
(every production row has `conf=None`). FAST WATCH failed for a different
reason: 9 firings / 12,317 rows, because post-freeze items exceed the 300 s
breaking window and lose eligibility. The confidence grading shipped this week
is *not yet* a production factor.

## Did Telegram delay alerts?

**No.** Where alerts were sent, gate→Telegram legs were small; the 9–13 min
fetch→sent times are gate/confirmation time, not outbox time. (4 cases
classified GATE_DELAY; 0 TELEGRAM_DELAY.)

## Did price move before public news?

Not confirmable from available data: 0 pre-news-shadow detections preceded any
late headline, and intraday exchange bars were unreachable from the audit
machine. For BGM the headline *content* implies yes (it reports a surge in
progress) — that class is inherent to aggregator "why is it moving" articles.

## Top 20 worst late alerts (production)

| Ticker | Source | Lat | Class | Outcome | Headline |
|---|---|---|---|---|---|
| HUT | sec | 12.6h | SOURCE_LATE | bad_ticker | Hut 8 Corp. filed SEC Form 8-K: M&A / |
| MOBX | sec | 12.6h | SOURCE_LATE | stale_published | MOBIX LABS, INC filed SEC Form 8-K |
| PIII | sec | 12.5h | SOURCE_LATE | stale_published | P3 Health Partners Inc. filed SEC Form |
| ELVN | sec | 12.5h | SOURCE_LATE | stale_published | Enliven Therapeutics, Inc. filed SEC F |
| VTS | sec | 12.4h | SOURCE_LATE | stale_published | Vitesse Energy, Inc. filed SEC Form 8- |
| MGX | sec | 12.2h | SOURCE_LATE | stale_published | Metagenomi Therapeutics, Inc. filed SE |
| REBN | sec | 12.1h | SOURCE_LATE | stale_published | Reborn Coffee, Inc. filed SEC Form 8-K |
| NUVL | finviz | 11.8h | SOURCE_LATE | late_reaction | Nuvalent Stock Soars on $10.6 Billion |
| BFH | globenewswire | 11.8h | SOURCE_LATE | impact_floor | Bread Financial Provides Performance U |
| CREX | globenewswire | 11.8h | SOURCE_LATE | no_price | Creative Realities to Participate in U |
| FIGR | globenewswire | 11.8h | SOURCE_LATE | score_gate | Figure Enters into Agreement to Acquir |
| TCEC | globenewswire | 11.8h | SOURCE_LATE | no_price | Terra Clean Energy Corp. Files NI 43-1 |
| TF | globenewswire | 11.8h | SOURCE_LATE | impact_floor | Timbercreek Financial Corp. announces |
| NUVL | finviz | 11.7h | SOURCE_LATE | impact_floor | GSK Agrees $10.6 Billion Nuvalent Deal |
| NUVL | finviz | 11.6h | SOURCE_LATE | impact_floor | Nuvalent Catapults To Record High On G |
| NUVL | finviz | 11.5h | SOURCE_LATE | impact_floor | Toll Brothers upgraded, Lennar downgra |
| NWSA | sec | 11.3h | SOURCE_LATE | no_price | NEWS CORP filed SEC Form 8-K |
| BRWXF | globenewswire | 11.3h | SOURCE_LATE | impact_floor | Brunswick Exploration Increases Anais |
| GANX | globenewswire | 11.3h | SOURCE_LATE | score_gate | Gain Therapeutics to Present at H.C. W |
| GCT | globenewswire | 11.3h | SOURCE_LATE | no_price | GigaCloud Technology Inc to Present at |

(All overnight items, mostly correctly suppressed — the *damaging* lateness
lives in the 15–60 min market-hours band analyzed above.)

## Recommended actions (evidence-ranked)

1. **Deploy the pending fixes to Railway.** The freeze fixes (event-loop
   blocking: `_fetch_post_news_prices`, pre-news startup refresh, sync Finviz
   universe fetches) plus fast-first polling and the Finnhub quote fallback
   are all committed locally but the 06-10 trace shows the freezes still
   occurring in production. This single action addresses the **36%
   ORACLE_LATE** band *and* restores FAST WATCH eligibility (fresh items will
   be seen inside the 300 s window again). `no_price` blocks in the top-20
   also disappear once `FINNHUB_API_KEY` is set.
2. **After deploy, re-export the trace and re-run this audit** — expect the
   silent windows to vanish; whatever lateness remains is true source lag.
3. **Then** address the ~14-min confirmation adder (FAST WATCH expansion /
   gate tuning) — out of scope here, and only worth tuning once detection is
   no longer frozen; the post-deploy numbers will show how much of it remains.
4. Source work (Benzinga/Alpaca stream etc.) only after 1–3, per the earlier
   audit — it is the remedy for the residual SOURCE_LATE share, not for the
   current dominant causes.
