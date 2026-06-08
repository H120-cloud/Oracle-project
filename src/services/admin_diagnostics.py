"""Read-only Admin Diagnostics service.

Parses the diagnostics JSONL artifacts (news latency trace, Rocket shadow
predictions, Telegram outbox) into filtered, paginated, derived views for the
admin dashboard. This module is strictly read-only — it never writes, mutates,
scores, gates, or otherwise touches production alert logic.

All readers accept an explicit ``path`` (defaulting to the agentic data dir) so
they are trivially testable against temp files.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from src.core.agentic.news_alert_latency_trace import aware_utc, iso, seconds_between
from src.utils.data_paths import agentic_path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Default artifact locations ─────────────────────────────────────────────

def news_latency_path() -> Path:
    return agentic_path("news_alert_latency_trace.jsonl")


def rocket_shadow_path() -> Path:
    return agentic_path("rocket_model_shadow_predictions.jsonl")


def telegram_outbox_path() -> Path:
    return agentic_path("telegram_outbox.jsonl")


# ── Generic helpers ────────────────────────────────────────────────────────

def _load_jsonl(path: Optional[Path]) -> list[dict[str, Any]]:
    if path is None or not Path(path).exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue  # tolerate partial/corrupt lines
    return rows


def _match_ticker(row: dict, ticker: Optional[str]) -> bool:
    if not ticker:
        return True
    return ticker.strip().upper() in str(row.get("ticker") or "").upper()


def _match_source(row: dict, field: str, source: Optional[str]) -> bool:
    if not source:
        return True
    return source.strip().lower() in str(row.get(field) or "").lower()


def _in_range(value: Any, start: Optional[str], end: Optional[str]) -> bool:
    if not start and not end:
        return True
    dt = aware_utc(value)
    if dt is None:
        return False
    if start:
        start_dt = aware_utc(start)
        if start_dt is None:
            return False
        if dt < start_dt:
            return False
    if end:
        end_dt = aware_utc(end)
        if end_dt is None:
            return False
        if dt > end_dt:
            return False
    return True


def _paginate(rows: list, page: int, page_size: int) -> tuple[list, int, int, int]:
    total = len(rows)
    page = max(1, int(page or 1))
    # Ceiling is generous so full-dataset exports can request every row; the
    # public list endpoints separately cap page_size at 1000 via Query(le=1000).
    page_size = max(1, min(int(page_size or 50), 100_000))
    start = (page - 1) * page_size
    return rows[start:start + page_size], total, page, page_size


def _envelope(items: list, total: int, page: int, page_size: int, **extra) -> dict:
    out = {"total": total, "page": page, "page_size": page_size, "items": items}
    out.update(extra)
    return out


# ── News latency ───────────────────────────────────────────────────────────

_FRESHNESS_MARKERS = ("stale", "fresh", "publish", "obsolet", "expired")
_TICKER_MARKERS = ("ticker", "unresolved", "no_price", "delisted")
_DUP_MARKERS = ("dup",)


def _blocked_category(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    r = str(reason).lower()
    if any(m in r for m in _DUP_MARKERS):
        return "duplicate"
    if any(m in r for m in _FRESHNESS_MARKERS):
        return "freshness"
    if "cooldown" in r:
        return "cooldown"
    if "bad_ticker" in r or "unresolved" in r:
        return "unresolved_ticker"
    if any(m in r for m in _TICKER_MARKERS):
        return "unresolved_ticker"
    if "ml" in r:
        return "ml_veto"
    return "other"


def _latency_derived(row: dict) -> dict:
    pub = row.get("published_at")
    fetched = row.get("fetched_at")
    classified = row.get("classified_at")
    gate = row.get("gate_decision_at") or row.get("scored_at")
    telegram = row.get("telegram_sent_at") or row.get("telegram_enqueue_at")
    total = row.get("total_latency_seconds")
    if total is None:
        total = seconds_between(pub, telegram or gate)
    return {
        "source_fetch_latency_seconds": seconds_between(pub, fetched),
        "classification_latency_seconds": seconds_between(fetched, classified),
        "gate_latency_seconds": seconds_between(classified or fetched, gate),
        "telegram_latency_seconds": seconds_between(gate, telegram),
        "total_latency_seconds": total,
    }


def _latency_enrich(row: dict) -> dict:
    derived = _latency_derived(row)
    alert_sent = bool(row.get("alert_sent"))
    reason = row.get("blocked_reason")
    category = _blocked_category(reason)
    total = derived["total_latency_seconds"]
    is_delayed = total is not None and total > 60
    is_blocked = bool(reason) and not alert_sent
    if is_blocked:
        status = "blocked"
    elif alert_sent:
        status = "delayed" if is_delayed else "alerted"
    else:
        status = "incomplete"
    enriched = dict(row)
    enriched["derived"] = derived
    enriched["status"] = status
    enriched["blocked_category"] = category
    enriched["is_delayed"] = is_delayed
    enriched["is_blocked"] = is_blocked
    enriched["is_fast_watch"] = bool(row.get("fast_path"))
    return enriched


_STATUS_ALIASES = {
    "duplicate_blocked": ("blocked_category", "duplicate"),
    "freshness_blocked": ("blocked_category", "freshness"),
    "unresolved_ticker": ("blocked_category", "unresolved_ticker"),
    "cooldown_blocked": ("blocked_category", "cooldown"),
}


def _latency_status_match(item: dict, status: Optional[str]) -> bool:
    if not status:
        return True
    s = status.strip().lower()
    if s in _STATUS_ALIASES:
        field, value = _STATUS_ALIASES[s]
        return item.get(field) == value
    if s == "delayed":
        return bool(item.get("is_delayed"))
    if s == "blocked":
        return bool(item.get("is_blocked"))
    if s == "alerted":
        return item.get("status") == "alerted"
    return item.get("status") == s


def _sort_key_latency(item: dict) -> str:
    return str(item.get("published_at") or item.get("telegram_sent_at")
               or item.get("gate_decision_at") or "")


def read_news_latency(
    *, path: Optional[Path] = None, ticker: Optional[str] = None,
    source: Optional[str] = None, status: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
    page: int = 1, page_size: int = 50,
) -> dict:
    path = path if path is not None else news_latency_path()
    rows = [_latency_enrich(r) for r in _load_jsonl(path)]
    rows = [
        r for r in rows
        if _match_ticker(r, ticker)
        and _match_source(r, "source", source)
        and _in_range(r.get("published_at"), start, end)
        and _latency_status_match(r, status)
    ]
    rows.sort(key=_sort_key_latency, reverse=True)

    # Summary + chart aggregates computed over the filtered set.
    summary = {
        "total": len(rows),
        "alerted": sum(1 for r in rows if r.get("alert_sent")),
        "delayed": sum(1 for r in rows if r["is_delayed"]),
        "blocked": sum(1 for r in rows if r["is_blocked"]),
        "fast_watch": sum(1 for r in rows if r["is_fast_watch"]),
    }
    alerts_by_source: Counter = Counter()
    blocked_reason_distribution: Counter = Counter()
    latency_acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        src = str(r.get("source") or "unknown")
        alerts_by_source[src] += 1
        if r["is_blocked"] and r["blocked_category"]:
            blocked_reason_distribution[r["blocked_category"]] += 1
        tot = r["derived"]["total_latency_seconds"]
        if tot is not None:
            latency_acc[src].append(tot)
    avg_latency_by_source = {
        src: round(sum(v) / len(v), 3) for src, v in latency_acc.items() if v
    }
    charts = {
        "alerts_by_source": dict(alerts_by_source),
        "avg_latency_by_source": avg_latency_by_source,
        "blocked_reason_distribution": dict(blocked_reason_distribution),
    }

    items, total, page, page_size = _paginate(rows, page, page_size)
    return _envelope(items, total, page, page_size, summary=summary, charts=charts)


def read_blocked_alerts(**kwargs) -> dict:
    kwargs.setdefault("status", "blocked")
    return read_news_latency(**kwargs)


def read_fast_watch_alerts(
    *, path: Optional[Path] = None, ticker: Optional[str] = None,
    source: Optional[str] = None, start: Optional[str] = None,
    end: Optional[str] = None, page: int = 1, page_size: int = 50,
) -> dict:
    path = path if path is not None else news_latency_path()
    rows = [_latency_enrich(r) for r in _load_jsonl(path)]
    rows = [
        r for r in rows
        if r["is_fast_watch"]
        and _match_ticker(r, ticker)
        and _match_source(r, "source", source)
        and _in_range(r.get("published_at"), start, end)
    ]
    rows.sort(key=_sort_key_latency, reverse=True)
    items, total, page, page_size = _paginate(rows, page, page_size)
    return _envelope(items, total, page, page_size)


def read_source_health(
    *, path: Optional[Path] = None, start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    path = path if path is not None else news_latency_path()
    rows = [_latency_enrich(r) for r in _load_jsonl(path)]
    rows = [r for r in rows if _in_range(r.get("published_at"), start, end)]
    by_source: dict[str, dict] = {}
    latency_acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        src = str(r.get("source") or "unknown")
        rec = by_source.setdefault(src, {
            "source": src, "total": 0, "alerted": 0, "delayed": 0,
            "blocked": 0, "fast_watch": 0,
        })
        rec["total"] += 1
        rec["alerted"] += 1 if r.get("alert_sent") else 0
        rec["delayed"] += 1 if r["is_delayed"] else 0
        rec["blocked"] += 1 if r["is_blocked"] else 0
        rec["fast_watch"] += 1 if r["is_fast_watch"] else 0
        tot = r["derived"]["total_latency_seconds"]
        if tot is not None:
            latency_acc[src].append(tot)
    for src, rec in by_source.items():
        vals = latency_acc.get(src) or []
        rec["avg_latency_seconds"] = round(sum(vals) / len(vals), 3) if vals else None
    items = sorted(by_source.values(), key=lambda r: r["total"], reverse=True)
    return _envelope(items, len(items), 1, len(items) or 1)


# ── Rocket shadow ──────────────────────────────────────────────────────────

def _rule_score(row: dict) -> Optional[float]:
    """Rule-based (non-CatBoost) priority signal, for rank comparison."""
    parts = [row.get("expected_return_score"), row.get("news_impact_score")]
    vals = [float(p) for p in parts if isinstance(p, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _rank(rows: list[dict], key, attr: str) -> None:
    ordered = sorted(rows, key=lambda r: (key(r) is None, -(key(r) or 0)))
    for i, r in enumerate(ordered):
        r[attr] = i + 1


def read_rocket_shadow(
    *, path: Optional[Path] = None, ticker: Optional[str] = None,
    source: Optional[str] = None, status: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
    page: int = 1, page_size: int = 50, view: Optional[str] = None,
) -> dict:
    path = path if path is not None else rocket_shadow_path()
    rows = [dict(r) for r in _load_jsonl(path)]
    for r in rows:
        r["rule_score"] = _rule_score(r)
    rows = [
        r for r in rows
        if _match_ticker(r, ticker)
        and _match_source(r, "source_pipeline", source)
        and (not status or str(r.get("prediction_confidence") or "").upper() == status.strip().upper())
        and _in_range(r.get("logged_at"), start, end)
    ]

    # Rank by CatBoost (rocket_rank_score) and by the rule signal.
    _rank(rows, lambda r: r.get("rocket_rank_score"), "catboost_rank")
    _rank(rows, lambda r: r.get("rule_score"), "rule_rank")

    def _top(metric: str, n: int = 10) -> list[dict]:
        return sorted(
            rows, key=lambda r: (r.get(metric) is None, -(r.get(metric) or 0))
        )[:n]

    views = {
        "top_rank": _top("rocket_rank_score"),
        "highest_monster": _top("binary_monster_plus_probability"),
        "highest_major": _top("binary_major_plus_probability"),
        "highest_confidence": sorted(
            rows,
            key=lambda r: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(
                str(r.get("prediction_confidence") or "").upper(), 3),
                -(r.get("rocket_rank_score") or 0)),
        )[:10],
    }

    # Divergence between CatBoost and rule ordering.
    divergent = [r for r in rows if r.get("rule_score") is not None]
    catboost_high_rules_low = sorted(
        divergent, key=lambda r: (r["rule_rank"] - r["catboost_rank"]), reverse=True
    )
    rules_high_catboost_low = sorted(
        divergent, key=lambda r: (r["catboost_rank"] - r["rule_rank"]), reverse=True
    )
    comparison = {
        "catboost_high_rules_low": [r for r in catboost_high_rules_low
                                    if r["rule_rank"] - r["catboost_rank"] > 0][:10],
        "rules_high_catboost_low": [r for r in rules_high_catboost_low
                                    if r["catboost_rank"] - r["rule_rank"] > 0][:10],
    }

    summary = {
        "total": len(rows),
        "high_confidence": sum(1 for r in rows if str(r.get("prediction_confidence") or "").upper() == "HIGH"),
        "avg_rank_score": round(
            sum(r.get("rocket_rank_score") or 0 for r in rows) / len(rows), 4
        ) if rows else None,
    }

    selected = views.get(view) if view else None
    base = selected if selected is not None else sorted(
        rows, key=lambda r: str(r.get("logged_at") or ""), reverse=True
    )
    items, total, page, page_size = _paginate(base, page, page_size)
    return _envelope(items, total, page, page_size,
                     summary=summary, views=views, comparison=comparison)


# ── Telegram outbox ────────────────────────────────────────────────────────

def _outbox_send_latency(row: dict) -> Optional[float]:
    """created_at -> the telegram_response date, when present (sent items)."""
    resp = row.get("telegram_response")
    sent_date = None
    if isinstance(resp, dict):
        result = resp.get("result")
        if isinstance(result, dict):
            sent_date = result.get("date")
    if sent_date is None:
        return None
    if isinstance(sent_date, (int, float)):
        sent_dt = datetime.fromtimestamp(sent_date, tz=timezone.utc).isoformat()
    else:
        sent_dt = sent_date
    return seconds_between(row.get("created_at"), sent_dt)


def read_telegram_outbox(
    *, path: Optional[Path] = None, ticker: Optional[str] = None,
    status: Optional[str] = None, alert_type: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
    page: int = 1, page_size: int = 50,
) -> dict:
    path = path if path is not None else telegram_outbox_path()
    rows = [dict(r) for r in _load_jsonl(path)]
    for r in rows:
        r["send_latency_seconds"] = _outbox_send_latency(r)
    filtered = [
        r for r in rows
        if _match_ticker(r, ticker)
        and (not status or str(r.get("status") or "").lower() == status.strip().lower())
        and _match_source(r, "alert_type", alert_type)
        and _in_range(r.get("created_at"), start, end)
    ]
    filtered.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)

    status_counts: Counter = Counter(str(r.get("status") or "unknown").lower() for r in filtered)
    sent = status_counts.get("sent", 0)
    total = len(filtered)
    send_latencies = [r["send_latency_seconds"] for r in filtered if r.get("send_latency_seconds") is not None]
    summary = {
        "total": total,
        "pending": status_counts.get("pending", 0),
        "retrying": status_counts.get("failed", 0),  # failed-with-retries pending
        "sent": sent,
        "failed": status_counts.get("dead_letter", 0),
        "dead_letter": status_counts.get("dead_letter", 0),
        "success_rate": round(sent / total, 4) if total else 0.0,
        "total_retries": sum(int(r.get("attempts") or 0) for r in filtered),
        "average_send_latency_seconds": round(sum(send_latencies) / len(send_latencies), 3) if send_latencies else None,
    }

    items, total_n, page, page_size = _paginate(filtered, page, page_size)
    return _envelope(items, total_n, page, page_size, summary=summary)


# ── Download / export ───────────────────────────────────────────────────────

_EXPORT_READERS = {
    "news-latency": read_news_latency,
    "rocket-shadow": read_rocket_shadow,
    "telegram-outbox": read_telegram_outbox,
}
_EXPORT_FORMATS = {"csv", "jsonl", "json"}


def _flatten_row(row: dict) -> dict:
    """One-level flatten; nested dicts -> prefixed keys, lists/objs -> JSON text."""
    flat: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            for sub, sub_val in value.items():
                flat[f"{key}_{sub}"] = (
                    json.dumps(sub_val, default=str)
                    if isinstance(sub_val, (dict, list)) else sub_val
                )
        elif isinstance(value, list):
            flat[key] = json.dumps(value, default=str)
        else:
            flat[key] = value
    return flat


def rows_to_csv(rows: list[dict]) -> str:
    flat_rows = [_flatten_row(r) for r in rows]
    columns: list[str] = []
    seen: set[str] = set()
    for r in flat_rows:
        for key in r:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in flat_rows:
        writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    return buf.getvalue()


def rows_to_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)


def rows_to_json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


def export_diagnostics(kind: str, fmt: str = "csv", *, filters: Optional[dict] = None) -> dict:
    """Render a filtered diagnostics dataset as CSV / JSONL / JSON.

    Returns ``{"content", "media_type", "filename"}``. Raises ValueError on an
    unknown kind/format (the route maps that to HTTP 400).
    """
    if kind not in _EXPORT_READERS:
        raise ValueError(f"unknown export kind: {kind}")
    fmt = (fmt or "csv").lower()
    if fmt not in _EXPORT_FORMATS:
        raise ValueError(f"unsupported format: {fmt}")

    reader = _EXPORT_READERS[kind]
    data = reader(page=1, page_size=100_000, **(filters or {}))
    rows = data.get("items", [])

    if fmt == "jsonl":
        content, media = rows_to_jsonl(rows), "application/x-ndjson"
    elif fmt == "json":
        content, media = rows_to_json(rows), "application/json"
    else:
        content, media = rows_to_csv(rows), "text/csv"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "content": content,
        "media_type": media,
        "filename": f"{kind}_{stamp}.{fmt}",
    }


# ── Report catalog (allowlisted file downloads) ─────────────────────────────

def docs_dir() -> Path:
    return _PROJECT_ROOT / "docs"


def report_files() -> dict[str, tuple[Path, str]]:
    """Allowlist: report basename -> (resolved path, type).

    Keys are plain basenames (no path separators) so the download route can use
    a non-greedy path param. This is the primary path-traversal defense: a name
    is only servable if it is an exact key here.
    """
    docs = docs_dir()
    return {
        "news_alert_latency_trace.jsonl": (agentic_path("news_alert_latency_trace.jsonl"), "jsonl"),
        "rocket_model_shadow_predictions.jsonl": (agentic_path("rocket_model_shadow_predictions.jsonl"), "jsonl"),
        "telegram_outbox.jsonl": (agentic_path("telegram_outbox.jsonl"), "jsonl"),
        "news_alert_latency_failure_audit.md": (docs / "news_alert_latency_failure_audit.md", "markdown"),
        "rocket_catboost_baseline_report.md": (docs / "rocket_catboost_baseline_report.md", "markdown"),
        "rocket_model_shadow_report.md": (docs / "rocket_model_shadow_report.md", "markdown"),
        "telegram_outbox_reliability.md": (docs / "telegram_outbox_reliability.md", "markdown"),
        "admin_diagnostics_dashboard_report.md": (docs / "admin_diagnostics_dashboard_report.md", "markdown"),
    }


_REPORT_MEDIA = {"markdown": "text/markdown", "jsonl": "application/x-ndjson"}


def list_reports() -> dict:
    items = []
    for name, (path, rtype) in report_files().items():
        exists = path.exists()
        stat = path.stat() if exists else None
        items.append({
            "name": name,
            "type": rtype,
            "exists": exists,
            "size_bytes": stat.st_size if stat else 0,
            "last_modified": iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)) if stat else None,
        })
    return {"total": len(items), "items": items}


def resolve_report(name: str) -> Optional[dict]:
    """Return download info for an allowlisted report, or None if not allowed.

    A name not present in :func:`report_files` (including any path-traversal
    attempt) returns None. A name that is allowlisted but whose file is not yet
    generated returns ``{"missing": True}``.
    """
    files = report_files()
    if name not in files:
        return None
    path, rtype = files[name]
    if not path.exists():
        return {"name": name, "type": rtype, "missing": True}
    return {
        "name": name,
        "type": rtype,
        "missing": False,
        "content": path.read_text(encoding="utf-8"),
        "media_type": _REPORT_MEDIA.get(rtype, "application/octet-stream"),
    }


__all__ = [
    "read_news_latency", "read_rocket_shadow", "read_telegram_outbox",
    "read_source_health", "read_blocked_alerts", "read_fast_watch_alerts",
    "news_latency_path", "rocket_shadow_path", "telegram_outbox_path",
    "export_diagnostics", "rows_to_csv", "rows_to_jsonl", "rows_to_json",
    "list_reports", "resolve_report", "report_files", "docs_dir",
]
