"""
Pre-News Shadow Logger V2 -- observe-only A/B of alert gates.

PURPOSE
    Run the CURRENT production alert gate (BASELINE: suspicion_score >= 75 +
    safety) and a PROPOSED gate (V2_SHADOW: qualifying anomaly type + safety,
    NO suspicion threshold) side-by-side for every pre-news detection, and log
    both decisions plus forward outcomes -- so we can prove, on clean forward
    data, whether the suspicion gate should be replaced.

GUARANTEE
    This module NEVER sends an alert and NEVER mutates production state. It only
    READS persisted anomalies and WRITES its own file:
        data/agentic/pre_news_shadow_v2.json
    It does not import or call any Telegram/alert sending code.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
SHADOW_FILE = DATA_DIR / "pre_news_shadow_v2.json"

# Qualifying accumulation/early-volume archetypes for the V2 gate (strings, to
# avoid coupling shadow logic to production enums).
V2_QUALIFYING_TYPES = {
    "unusual_volume_no_news",
    "volume_before_news",
    "hidden_accumulation",
    "early_breakout_positioning",
    "quiet_volume_build",
}

V2_MAX_OFFERING_RISK = 70.0
V2_ACCEPTABLE_DATA_QUALITY = {"full", "partial"}
BASELINE_SUSPICION_THRESHOLD = 75.0


def _g(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _enum_val(v):
    return v.value if hasattr(v, "value") else v


def _aware(dt) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# -- Gate decisions (PURE functions) -----------------------------------------

def baseline_decision(a: Any) -> tuple[bool, str]:
    """Replicate production should_alert() core: suspicion>=75 + quality guards."""
    susp = _g(a, "pre_news_suspicion_score", 0) or 0
    if susp < BASELINE_SUSPICION_THRESHOLD:
        return False, "suspicion<%.0f(%.0f)" % (BASELINE_SUSPICION_THRESHOLD, susp)
    aq = _enum_val(_g(a, "alert_quality")) or ""
    if aq in ("suppressed", "trap_risk"):
        return False, "alert_quality=%s" % aq
    if aq == "late" and susp < 85:
        return False, "late_and_susp<85"
    return True, ""


def v2_decision(a: Any) -> tuple[bool, str]:
    """Proposed gate: qualifying anomaly type + safety, NO suspicion threshold."""
    atype = _enum_val(_g(a, "anomaly_type")) or ""
    if atype not in V2_QUALIFYING_TYPES:
        return False, "anomaly_type=%s" % atype
    aq = _enum_val(_g(a, "alert_quality")) or ""
    if aq in ("suppressed", "trap_risk"):
        return False, "alert_quality=%s" % aq
    offering = _g(a, "offering_risk_score", 0) or 0
    if offering >= V2_MAX_OFFERING_RISK:
        return False, "offering_risk=%.0f" % offering
    dq = _enum_val(_g(a, "data_quality")) or _enum_val(_g(a, "data_quality_state")) or "full"
    if str(dq).lower() not in V2_ACCEPTABLE_DATA_QUALITY:
        return False, "data_quality=%s" % dq
    return True, ""


# -- Shadow record -----------------------------------------------------------

@dataclass
class ShadowRecord:
    shadow_id: str
    ticker: str
    detection_time: str
    anomaly_type: str
    suspicion_score: float
    alert_quality: str
    price_at_detection: float
    offering_risk: float
    data_quality: str
    float_shares: Optional[float]
    market_cap: Optional[float]
    volume_anomaly: float
    vwap_distance_pct: Optional[float]
    volume_acceleration: Optional[float]
    baseline_would_alert: bool
    v2_would_alert: bool
    baseline_block_reason: str
    v2_block_reason: str
    resolved: bool = False
    resolved_at: Optional[str] = None
    price_15m: Optional[float] = None
    price_60m: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    two_day_high: Optional[float] = None
    two_day_low: Optional[float] = None
    mfe_15m: Optional[float] = None
    mfe_60m: Optional[float] = None
    mfe_session: Optional[float] = None
    mfe_2d: Optional[float] = None
    mae_15m: Optional[float] = None
    mae_60m: Optional[float] = None
    mae_session: Optional[float] = None
    mae_2d: Optional[float] = None
    hit_20: Optional[bool] = None
    hit_50: Optional[bool] = None
    hit_100: Optional[bool] = None
    hit_300: Optional[bool] = None
    hit_1000: Optional[bool] = None
    next_day_continuation: Optional[bool] = None
    became_trap: Optional[bool] = None


class PreNewsShadowV2:
    """Observe-only shadow A/B logger. Reads anomalies, writes its own file."""

    def __init__(self, path: Path = SHADOW_FILE):
        self.path = path
        self._records: dict[str, ShadowRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
            for rec in raw.get("records", []):
                sr = ShadowRecord(**{k: rec.get(k) for k in ShadowRecord.__dataclass_fields__})
                self._records[sr.shadow_id] = sr
            logger.debug("ShadowV2: loaded %d records", len(self._records))
        except Exception as exc:
            logger.warning("ShadowV2: load failed: %s", exc)

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(self._records),
            "records": [asdict(r) for r in self._records.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1, default=str))
        tmp.replace(self.path)

    @staticmethod
    def _shadow_id(a: Any) -> str:
        ticker = _g(a, "ticker", "?")
        dt = _aware(_g(a, "detected_at")) or datetime.now(timezone.utc)
        return "%s:%s" % (ticker, dt.strftime("%Y%m%d%H"))

    def capture_from_anomalies(self, anomalies: list) -> int:
        """Log baseline + V2 decisions for each anomaly. Idempotent per
        ticker+detection-hour. Returns # new records."""
        new = 0
        for a in anomalies:
            sid = self._shadow_id(a)
            if sid in self._records:
                continue
            b_alert, b_reason = baseline_decision(a)
            v_alert, v_reason = v2_decision(a)
            vm = _g(a, "volume_metrics")
            pb = _g(a, "price_behaviour")
            dq = _enum_val(_g(a, "data_quality")) or _enum_val(_g(a, "data_quality_state")) or "full"
            rec = ShadowRecord(
                shadow_id=sid,
                ticker=_g(a, "ticker", "?"),
                detection_time=(_aware(_g(a, "detected_at")) or datetime.now(timezone.utc)).isoformat(),
                anomaly_type=_enum_val(_g(a, "anomaly_type")) or "",
                suspicion_score=float(_g(a, "pre_news_suspicion_score", 0) or 0),
                alert_quality=_enum_val(_g(a, "alert_quality")) or "",
                price_at_detection=float(_g(a, "price", 0) or 0),
                offering_risk=float(_g(a, "offering_risk_score", 0) or 0),
                data_quality=str(dq),
                float_shares=_g(a, "float_shares"),
                market_cap=_g(a, "market_cap"),
                volume_anomaly=float(_g(a, "volume_anomaly_score", 0) or 0),
                vwap_distance_pct=_g(pb, "vwap_distance_pct") if pb is not None else None,
                volume_acceleration=_g(vm, "volume_acceleration") if vm is not None else None,
                baseline_would_alert=b_alert,
                v2_would_alert=v_alert,
                baseline_block_reason=b_reason,
                v2_block_reason=v_reason,
            )
            self._records[sid] = rec
            new += 1
        if new:
            self._save()
            logger.info("ShadowV2: captured %d new records (total %d)", new, len(self._records))
        return new

    def open_records(self, min_age_hours: float = 2.0) -> list[ShadowRecord]:
        now = datetime.now(timezone.utc)
        out = []
        for r in self._records.values():
            if r.resolved:
                continue
            dt = _aware(r.detection_time)
            if dt and (now - dt) >= timedelta(hours=min_age_hours):
                out.append(r)
        return out

    @staticmethod
    def _excursions(entry: float, highs: list, lows: list) -> tuple[float, float]:
        if not entry or entry <= 0:
            return 0.0, 0.0
        mfe = (max(highs) - entry) / entry * 100 if highs else 0.0
        mae = (min(lows) - entry) / entry * 100 if lows else 0.0
        return round(mfe, 2), round(mae, 2)

    def resolve_record(self, r: ShadowRecord, bars: dict) -> bool:
        """Fill forward outcomes from pre-fetched OHLCV bars.
        bars = {"intraday": [(ts,h,l,c)...], "daily": [(ts,h,l,c)...]}"""
        entry = r.price_at_detection
        if not entry or entry <= 0:
            return False
        det = _aware(r.detection_time)
        if det is None:
            return False

        intraday = bars.get("intraday") or []
        daily = bars.get("daily") or []

        def after(mins):
            cutoff = det + timedelta(minutes=mins)
            return [(ts, h, l, c) for (ts, h, l, c) in intraday if det <= _aware(ts) <= cutoff]

        b15 = after(15)
        b60 = after(60)
        sess_cut = det.replace(hour=21, minute=0, second=0, microsecond=0)
        sess = [(ts, h, l, c) for (ts, h, l, c) in intraday if det <= _aware(ts) <= sess_cut]
        two_day_cut = det + timedelta(days=2)
        d2 = [(ts, h, l, c) for (ts, h, l, c) in intraday if det <= _aware(ts) <= two_day_cut]

        if not (b15 or b60 or sess or daily):
            return False

        if b15:
            r.price_15m = round(b15[-1][3], 4)
            r.mfe_15m, r.mae_15m = self._excursions(entry, [x[1] for x in b15], [x[2] for x in b15])
        if b60:
            r.price_60m = round(b60[-1][3], 4)
            r.mfe_60m, r.mae_60m = self._excursions(entry, [x[1] for x in b60], [x[2] for x in b60])
        if sess:
            r.session_high = round(max(x[1] for x in sess), 4)
            r.session_low = round(min(x[2] for x in sess), 4)
            r.mfe_session, r.mae_session = self._excursions(entry, [x[1] for x in sess], [x[2] for x in sess])
        if d2:
            highs2, lows2 = [x[1] for x in d2], [x[2] for x in d2]
        elif daily:
            highs2 = [x[1] for x in daily[:2]]
            lows2 = [x[2] for x in daily[:2]]
        else:
            highs2, lows2 = [], []
        if highs2:
            r.two_day_high = round(max(highs2), 4)
            r.two_day_low = round(min(lows2), 4)
            r.mfe_2d, r.mae_2d = self._excursions(entry, highs2, lows2)

        best_mfe = max([m for m in [r.mfe_15m, r.mfe_60m, r.mfe_session, r.mfe_2d] if m is not None] or [0])
        r.hit_20 = best_mfe >= 20
        r.hit_50 = best_mfe >= 50
        r.hit_100 = best_mfe >= 100
        r.hit_300 = best_mfe >= 300
        r.hit_1000 = best_mfe >= 1000
        if r.session_high and r.two_day_high:
            r.next_day_continuation = r.two_day_high > r.session_high
        worst_mae = min([m for m in [r.mae_60m, r.mae_session] if m is not None] or [0])
        r.became_trap = bool(best_mfe >= 20 and worst_mae <= -15)

        r.resolved = True
        r.resolved_at = datetime.now(timezone.utc).isoformat()
        return True

    async def resolve_open(self, provider, min_age_hours: float = 2.0) -> int:
        """Fetch bars per open record and resolve. Per-ticker isolated."""
        import asyncio
        resolved = 0
        for r in self.open_records(min_age_hours=min_age_hours):
            try:
                intraday = await asyncio.to_thread(
                    provider.get_ohlcv, r.ticker, period="5d", interval="5m", prepost=True
                ) or []
                daily = await asyncio.to_thread(
                    provider.get_ohlcv, r.ticker, period="10d", interval="1d", prepost=False
                ) or []
            except Exception as exc:
                logger.debug("ShadowV2: fetch failed for %s: %s", r.ticker, exc)
                continue
            bars = {
                "intraday": [(_bar_ts(b), _bar_h(b), _bar_l(b), _bar_c(b)) for b in intraday],
                "daily": [(_bar_ts(b), _bar_h(b), _bar_l(b), _bar_c(b)) for b in daily],
            }
            if self.resolve_record(r, bars):
                resolved += 1
        if resolved:
            self._save()
            logger.info("ShadowV2: resolved %d records", resolved)
        return resolved

    @property
    def records(self) -> list:
        return list(self._records.values())


def _bar_ts(b):
    return (b.get("timestamp") or b.get("date") or b.get("t")) if isinstance(b, dict) else b[0]


def _bar_h(b):
    return float(b.get("high", b.get("h", 0)) if isinstance(b, dict) else b[2])


def _bar_l(b):
    return float(b.get("low", b.get("l", 0)) if isinstance(b, dict) else b[3])


def _bar_c(b):
    return float(b.get("close", b.get("c", 0)) if isinstance(b, dict) else b[4])


__all__ = ["PreNewsShadowV2", "ShadowRecord", "baseline_decision", "v2_decision",
           "V2_QUALIFYING_TYPES", "SHADOW_FILE"]
