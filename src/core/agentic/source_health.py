"""Source-health diagnostics for news parser reliability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SourceHealthSnapshot:
    source: str
    headlines_fetched: int = 0
    tickered_headline_count: int = 0
    untickered_headline_count: int = 0
    missing_timestamp_count: int = 0
    parse_error_count: int = 0
    dropped_headline_count: int = 0
    latency_sample_count: int = 0
    latency_total_seconds: float = 0.0
    latency_max_seconds: float = 0.0
    last_successful_parse_time: Optional[datetime] = None
    last_parse_error_at: Optional[datetime] = None
    last_warning_at: Optional[datetime] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def missing_timestamp_rate(self) -> float:
        if self.headlines_fetched <= 0:
            return 0.0
        return self.missing_timestamp_count / self.headlines_fetched

    @property
    def avg_latency_seconds(self) -> float:
        if self.latency_sample_count <= 0:
            return 0.0
        return self.latency_total_seconds / self.latency_sample_count

    @property
    def dropped_headline_rate(self) -> float:
        if self.headlines_fetched <= 0:
            return 0.0
        return self.dropped_headline_count / self.headlines_fetched


class SourceHealthTracker:
    def __init__(
        self,
        *,
        missing_timestamp_rate_threshold: float = 0.35,
        parse_error_threshold: int = 3,
        stale_after_seconds: int = 900,
        warning_cooldown_seconds: int = 900,
    ) -> None:
        self.missing_timestamp_rate_threshold = missing_timestamp_rate_threshold
        self.parse_error_threshold = max(1, int(parse_error_threshold or 1))
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.warning_cooldown = timedelta(seconds=warning_cooldown_seconds)
        self._snapshots: Dict[str, SourceHealthSnapshot] = {}

    def snapshot(self, source: str) -> SourceHealthSnapshot:
        key = source.lower().strip() or "unknown"
        if key not in self._snapshots:
            self._snapshots[key] = SourceHealthSnapshot(source=source)
        return self._snapshots[key]

    def reset(self) -> None:
        self._snapshots.clear()

    def record_fetch(self, source: str, headlines_fetched: int, *, now: Optional[datetime] = None) -> None:
        snap = self.snapshot(source)
        snap.headlines_fetched += max(0, int(headlines_fetched or 0))
        if headlines_fetched > 0:
            snap.last_successful_parse_time = now or _now()

    def record_parse_error(self, source: str, *, now: Optional[datetime] = None) -> None:
        snap = self.snapshot(source)
        snap.parse_error_count += 1
        snap.last_parse_error_at = now or _now()

    def record_missing_timestamp(self, source: str, count: int = 1) -> None:
        self.snapshot(source).missing_timestamp_count += max(0, int(count or 0))

    def record_dropped_headline(self, source: str, count: int = 1) -> None:
        self.snapshot(source).dropped_headline_count += max(0, int(count or 0))

    def record_tickered_headline(self, source: str, count: int = 1) -> None:
        self.snapshot(source).tickered_headline_count += max(0, int(count or 0))

    def record_untickered_headline(self, source: str, count: int = 1) -> None:
        count = max(0, int(count or 0))
        snap = self.snapshot(source)
        snap.untickered_headline_count += count
        snap.dropped_headline_count += count

    def record_latency(
        self,
        source: str,
        published_at: Optional[datetime],
        *,
        detected_at: Optional[datetime] = None,
    ) -> None:
        if published_at is None:
            return
        detected_at = detected_at or _now()
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        else:
            published_at = published_at.astimezone(timezone.utc)
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=timezone.utc)
        else:
            detected_at = detected_at.astimezone(timezone.utc)
        latency = max(0.0, (detected_at - published_at).total_seconds())
        snap = self.snapshot(source)
        snap.latency_sample_count += 1
        snap.latency_total_seconds += latency
        snap.latency_max_seconds = max(snap.latency_max_seconds, latency)

    def evaluate(self, *, now: Optional[datetime] = None) -> list[str]:
        now = now or _now()
        warnings: list[str] = []
        for snap in self._snapshots.values():
            if (
                snap.headlines_fetched >= 10
                and snap.missing_timestamp_rate >= self.missing_timestamp_rate_threshold
            ):
                warning = (
                    f"{snap.source} missing timestamp rate is {snap.missing_timestamp_rate:.0%} "
                    f"({snap.missing_timestamp_count}/{snap.headlines_fetched})"
                )
                if self._maybe_warn(snap, warning, now):
                    warnings.append(warning)

            if snap.last_successful_parse_time and now - snap.last_successful_parse_time >= self.stale_after:
                age = int((now - snap.last_successful_parse_time).total_seconds())
                warning = f"{snap.source} source stale for {age}s"
                if self._maybe_warn(snap, warning, now):
                    warnings.append(warning)

            if snap.parse_error_count >= self.parse_error_threshold:
                warning = (
                    f"{snap.source} parser errors reached {snap.parse_error_count} "
                    f"(threshold={self.parse_error_threshold})"
                )
                if self._maybe_warn(snap, warning, now):
                    warnings.append(warning)
        return warnings

    def to_dict(self, *, now: Optional[datetime] = None) -> dict[str, dict[str, object]]:
        now = now or _now()
        return {
            key: {
                "source": snap.source,
                "status": self._status_for_snapshot(snap, now),
                "headlines_fetched": snap.headlines_fetched,
                "tickered_headline_count": snap.tickered_headline_count,
                "untickered_headline_count": snap.untickered_headline_count,
                "missing_timestamp_count": snap.missing_timestamp_count,
                "parse_error_count": snap.parse_error_count,
                "dropped_headline_count": snap.dropped_headline_count,
                "dropped_headline_rate": round(snap.dropped_headline_rate, 4),
                "last_successful_parse_time": (
                    snap.last_successful_parse_time.isoformat()
                    if snap.last_successful_parse_time
                    else None
                ),
                "last_successful_parse_age_seconds": (
                    max(0, int((now - snap.last_successful_parse_time).total_seconds()))
                    if snap.last_successful_parse_time
                    else None
                ),
                "last_warning_at": snap.last_warning_at.isoformat() if snap.last_warning_at else None,
                "last_parse_error_at": snap.last_parse_error_at.isoformat() if snap.last_parse_error_at else None,
                "warnings": list(snap.warnings[-5:]),
                "missing_timestamp_rate": snap.missing_timestamp_rate,
                "avg_latency_seconds": round(snap.avg_latency_seconds, 2),
                "max_latency_seconds": round(snap.latency_max_seconds, 2),
                "latency_sample_count": snap.latency_sample_count,
                "problem_count": (
                    snap.missing_timestamp_count
                    + snap.parse_error_count
                    + snap.dropped_headline_count
                ),
            }
            for key, snap in self._snapshots.items()
        }

    def _status_for_snapshot(self, snap: SourceHealthSnapshot, now: datetime) -> str:
        if (
            snap.parse_error_count > 0
            and snap.last_parse_error_at is not None
            and (
                snap.last_successful_parse_time is None
                or snap.last_parse_error_at > snap.last_successful_parse_time
            )
        ):
            return "error"
        if snap.last_successful_parse_time and now - snap.last_successful_parse_time >= self.stale_after:
            return "stale"
        if (
            snap.headlines_fetched >= 10
            and snap.missing_timestamp_rate >= self.missing_timestamp_rate_threshold
        ):
            return "warning"
        if snap.warnings:
            return "warning"
        return "ok"

    def _maybe_warn(self, snap: SourceHealthSnapshot, warning: str, now: datetime) -> bool:
        if snap.last_warning_at and now - snap.last_warning_at < self.warning_cooldown:
            return False
        snap.last_warning_at = now
        snap.warnings.append(warning)
        return True
