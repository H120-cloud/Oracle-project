"""Late Alert Root Cause Audit — evidence-only, no production changes.

Classifies late alerts (published->fetch > 900s or total > 900s) into:
ORACLE_LATE / SOURCE_LATE / NEWS_LATE / PRICE_MOVED_BEFORE_NEWS /
GATE_DELAY / TELEGRAM_DELAY / SUSPECT_TIMESTAMP / UNKNOWN
using the latency trace, pre-news shadow data, and 5m market bars.
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRACE = "data/agentic/news_alert_latency_trace.jsonl"
PRENEWS = "data/agentic/pre_news_shadow_v2.json"
OUT = "data/agentic/late_alert_audit_results.json"

LATE_THRESHOLD_S = 900
PRE_MOVE_WINDOW_S = 600  # move >=10min before publish => PRICE_MOVED_BEFORE_NEWS


def dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def norm_headline(h):
    return " ".join(str(h or "").lower().split())[:120]


def main():
    rows = [json.loads(l) for l in open(TRACE, encoding="utf-8") if l.strip()]

    # ── dedup to unique stories, keeping earliest fetch + any telegram stamp ──
    stories = {}
    for r in rows:
        key = (r.get("ticker"), norm_headline(r.get("headline")))
        cur = stories.get(key)
        if cur is None or (dt(r.get("fetched_at")) or datetime.max.replace(tzinfo=timezone.utc)) < (
            dt(cur.get("fetched_at")) or datetime.max.replace(tzinfo=timezone.utc)
        ):
            merged = dict(cur or {})
            merged.update({k: v for k, v in r.items() if v is not None})
            stories[key] = merged
        else:
            for f in ("telegram_sent_at", "telegram_enqueue_at", "gate_decision_at"):
                if r.get(f) and not stories[key].get(f):
                    stories[key][f] = r[f]
            if r.get("alert_sent"):
                stories[key]["alert_sent"] = True

    late = []
    for s in stories.values():
        lat = s.get("latency_seconds_from_published_to_fetch")
        tot = s.get("total_latency_seconds")
        if (lat or 0) > LATE_THRESHOLD_S or (tot or 0) > LATE_THRESHOLD_S:
            late.append(s)
    late.sort(key=lambda s: -(s.get("latency_seconds_from_published_to_fetch") or 0))
    late = late[:100]
    print(f"unique stories: {len(stories)} | late (deduped, capped 100): {len(late)}")

    # ── pre-news shadow detections by ticker (Oracle's own intraday
    #    volume-anomaly evidence: detection_time + price_at_detection) ──
    prenews_by_ticker = defaultdict(list)
    try:
        pn = json.load(open(PRENEWS, encoding="utf-8"))
        records = pn if isinstance(pn, list) else (pn.get("records") or pn.get("entries") or [])
        for rec in records:
            t = (rec.get("ticker") or "").upper()
            d = dt(rec.get("detection_time"))
            if t and d:
                prenews_by_ticker[t].append((d, rec.get("price_at_detection"), rec.get("anomaly_type")))
    except Exception as exc:
        print("prenews load failed:", exc)
    print("prenews tickers with detections:", len(prenews_by_ticker))

    # ── loop-alive index: every fetched_at minute across ALL rows ──
    fetch_times = sorted(t for t in (dt(r.get("fetched_at")) for r in rows) if t)

    def loop_alive_between(start, end):
        """True if the scan loop demonstrably fetched anything in the window."""
        if not start or not end or end <= start:
            return False
        return any(start <= t <= end for t in fetch_times)

    # NOTE: exchange intraday bars were NOT reachable from this machine
    # (yfinance hard-blocked, stooq 404, Finnhub candles premium). Market-move
    # evidence therefore comes from Oracle's own pre-news volume-anomaly
    # detections; bar-derived fields are left null and flagged in the report.
    results = []
    for s in late:
        ticker = (s.get("ticker") or "").upper()
        pub = dt(s.get("published_at"))
        fetched = dt(s.get("fetched_at"))
        sent = dt(s.get("telegram_sent_at"))
        gate = dt(s.get("gate_decision_at")) or dt(s.get("scored_at"))
        lat = s.get("latency_seconds_from_published_to_fetch") or 0

        case = {
            "ticker": ticker, "headline": str(s.get("headline"))[:100],
            "source": s.get("source"), "published_at": s.get("published_at"),
            "detected_at": s.get("fetched_at"), "telegram_sent_at": s.get("telegram_sent_at"),
            "alert_sent": bool(s.get("alert_sent")), "blocked_reason": s.get("blocked_reason"),
            "source_latency_seconds": lat,
        }

        # suspect timestamp: latency within 120s of an exact hour multiple (>=1h)
        if lat >= 3480 and abs(lat - round(lat / 3600) * 3600) <= 120:
            case["root_cause"] = "SUSPECT_TIMESTAMP"
            results.append(case)
            continue

        if pub is None:
            case["root_cause"] = "UNKNOWN"
            results.append(case)
            continue

        # Oracle's own intraday evidence: pre-news anomaly detections within
        # 24h before the headline's published_at.
        pn_hits = sorted(
            (d, price, kind) for d, price, kind in prenews_by_ticker.get(ticker, [])
            if d < pub and (pub - d) <= timedelta(hours=24)
        )
        case["prenews_detected_before_news"] = bool(pn_hits)
        if pn_hits:
            first = pn_hits[0]
            case["first_unusual_volume_time"] = first[0].isoformat()
            case["price_at_first_volume_spike"] = first[1]
            case["prenews_anomaly_type"] = first[2]
            case["prenews_lead_minutes"] = round((pub - first[0]).total_seconds() / 60, 1)

        if sent and fetched and (sent - fetched).total_seconds() > 600 and gate and (sent - gate).total_seconds() > 600:
            case["root_cause"] = "TELEGRAM_DELAY"
        elif case["alert_sent"] and gate and fetched and (gate - fetched).total_seconds() > 600:
            case["root_cause"] = "GATE_DELAY"
        elif pn_hits and (pub - pn_hits[0][0]).total_seconds() > PRE_MOVE_WINDOW_S:
            case["root_cause"] = "PRICE_MOVED_BEFORE_NEWS"
        elif pn_hits:
            case["root_cause"] = "NEWS_LATE"
        elif lat > LATE_THRESHOLD_S:
            # Oracle polls every 20-60s. If the loop demonstrably fetched other
            # items during the publish->fetch gap, the carrier delivered late.
            if loop_alive_between(pub + timedelta(seconds=120), fetched - timedelta(seconds=60) if fetched else None):
                case["root_cause"] = "SOURCE_LATE"
            else:
                case["root_cause"] = "ORACLE_LATE"
        else:
            case["root_cause"] = "UNKNOWN"
        results.append(case)

    counts = Counter(c["root_cause"] for c in results)
    print("\nROOT CAUSE SUMMARY:")
    for k, v in counts.most_common():
        print(f"  {k:24} {v:>3}  ({v / len(results) * 100:.0f}%)")
    pn_before = [c for c in results if c.get("prenews_detected_before_news")]
    print(f"\npre-news fired before news: {len(pn_before)} cases")
    sent_cases = [c for c in results if c["alert_sent"]]
    print(f"late cases that actually alerted: {len(sent_cases)}")

    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1, default=str)
    print(f"\nwrote {len(results)} cases -> {OUT}")


if __name__ == "__main__":
    main()
