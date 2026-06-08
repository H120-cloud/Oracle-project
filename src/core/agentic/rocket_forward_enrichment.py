"""
Resumable historical forward-pricing enrichment for Rocket dataset rows.

The CLI is smoke-only unless --allow-full-run is supplied explicitly. It never
changes production alerts or Telegram behavior and never overwrites prior
Rocket exports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from src.core.agentic.rocket_dataset_builder import (
    compute_drawdown_quality,
    compute_mfe_mae_profiles,
    compute_peak_metrics,
)
from src.core.agentic.rocket_label_reconstructor import reconstruct_labels
from src.core.agentic.rocket_ticker_integrity import (
    SYNTHETIC_REJECTION_REASON,
    partition_synthetic_rows,
)
from src.utils.atomic_json import load_json_file, save_json_file

logger = logging.getLogger(__name__)

ENGINE_VERSION = "rocket_forward_enrichment_v2"
DEFAULT_STATE_DIR = agentic_path("rocket_forward_enrichment")
DEFAULT_INPUT = agentic_path("rocket_training_dataset_reconstructed.parquet")
DEFAULT_SMOKE_ROWS = 30


def _aware(value: Any) -> datetime:
    dt = pd.Timestamp(value).to_pydatetime()
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _bar_dict(bar: Any) -> Dict[str, Any]:
    def get(name: str, default: Any = None) -> Any:
        return bar.get(name, default) if isinstance(bar, dict) else getattr(bar, name, default)

    return {
        "timestamp": _aware(get("timestamp")).isoformat(),
        "open": float(get("open", 0) or 0),
        "high": float(get("high", 0) or 0),
        "low": float(get("low", 0) or 0),
        "close": float(get("close", 0) or 0),
        "volume": float(get("volume", 0) or 0),
    }


def _deserialize_bars(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**row, "timestamp": _aware(row["timestamp"])} for row in rows]


def _group_key(ticker: str, alert_time: Any) -> str:
    return f"{str(ticker).upper()}|{_aware(alert_time).date().isoformat()}"


def _cache_filename(group_key: str) -> str:
    digest = hashlib.sha256(group_key.encode("utf-8")).hexdigest()[:16]
    safe = group_key.replace("|", "_")
    return f"{safe}_{digest}.json"


def select_smoke_rows(df: pd.DataFrame, *, limit: int = DEFAULT_SMOKE_ROWS) -> pd.DataFrame:
    """Select a deterministic mixed-ticker, mixed-date unknown-row smoke batch."""
    if limit < 1:
        raise ValueError("limit must be positive")
    working, _ = partition_synthetic_rows(df)
    if "training_runner_tier" in working.columns:
        working = working[working["training_runner_tier"].fillna("UNKNOWN") == "UNKNOWN"]
    working["_alert_dt"] = pd.to_datetime(working["alert_time"], utc=True, errors="coerce")
    working = working.dropna(subset=["ticker", "_alert_dt"])
    working["_ticker"] = working["ticker"].astype(str).str.upper()
    working["_date"] = working["_alert_dt"].dt.date.astype(str)
    working = working.sort_values(["_date", "_ticker", "row_id"])
    if len(working) <= limit:
        return working.drop(columns=["_alert_dt", "_ticker", "_date"])

    positions = sorted({round(i * (len(working) - 1) / (limit - 1)) for i in range(limit)})
    selected = working.iloc[positions].copy()
    if len(selected) < limit:
        extras = working.drop(selected.index).head(limit - len(selected))
        selected = pd.concat([selected, extras])
    return selected.drop(columns=["_alert_dt", "_ticker", "_date"])


class RateLimiter:
    def __init__(self, requests_per_minute: float, sleep_fn=time.sleep) -> None:
        self.minimum_interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self.sleep_fn = sleep_fn
        self.last_request_at = 0.0

    def wait(self) -> None:
        if self.minimum_interval <= 0:
            return
        delay = self.minimum_interval - (time.time() - self.last_request_at)
        if delay > 0:
            self.sleep_fn(delay)
        self.last_request_at = time.time()


class RocketForwardEnricher:
    """Enrich unknown Rocket rows from a provider chain with durable state."""

    def __init__(
        self,
        *,
        providers: Sequence[Any],
        state_dir: Path | str = DEFAULT_STATE_DIR,
        requests_per_minute: Optional[Dict[str, float]] = None,
        max_retries: int = 2,
        sleep_fn=time.sleep,
    ) -> None:
        self.providers = list(providers)
        self.state_dir = Path(state_dir)
        self.cache_dir = self.state_dir / "cache"
        self.checkpoint_path = self.state_dir / "checkpoint.json"
        self.failures_path = self.state_dir / "failures.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max(1, max_retries)
        self.sleep_fn = sleep_fn
        rpm = requests_per_minute or {}
        self.limiters = {
            self._provider_name(provider): RateLimiter(
                rpm.get(self._provider_name(provider), 0.0),
                sleep_fn=sleep_fn,
            )
            for provider in self.providers
        }
        checkpoint = load_json_file(self.checkpoint_path, default={}) or {}
        self.completed_groups = set(checkpoint.get("completed_groups", []))

    @staticmethod
    def _provider_name(provider: Any) -> str:
        return str(getattr(provider, "name", provider.__class__.__name__)).lower()

    def _save_checkpoint(self) -> None:
        save_json_file(
            self.checkpoint_path,
            {
                "engine_version": ENGINE_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_groups": sorted(self.completed_groups),
            },
        )

    def _log_failure(self, **payload: Any) -> None:
        row = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
        with self.failures_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str, sort_keys=True) + "\n")

    def _cache_path(self, group_key: str) -> Path:
        return self.cache_dir / _cache_filename(group_key)

    def _load_cache(self, group_key: str) -> Optional[Dict[str, Any]]:
        data = load_json_file(self._cache_path(group_key), default=None)
        if not data:
            return None
        return {
            **data,
            "intraday_bars": _deserialize_bars(data.get("intraday_bars", [])),
            "daily_bars": _deserialize_bars(data.get("daily_bars", [])),
        }

    def _save_cache(self, group_key: str, payload: Dict[str, Any]) -> None:
        save_json_file(
            self._cache_path(group_key),
            {
                **payload,
                "engine_version": ENGINE_VERSION,
                "group_key": group_key,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "intraday_bars": [_bar_dict(bar) for bar in payload.get("intraday_bars", [])],
                "daily_bars": [_bar_dict(bar) for bar in payload.get("daily_bars", [])],
            },
        )

    def _request(
        self,
        provider: Any,
        ticker: str,
        *,
        start: str,
        end: str,
        interval: str,
        prepost: bool,
        stats: Dict[str, Any],
        group_key: str,
    ) -> List[Any]:
        name = self._provider_name(provider)
        for attempt in range(1, self.max_retries + 1):
            self.limiters[name].wait()
            stats["provider_stats"][name]["api_calls"] += 1
            try:
                bars = provider.get_ohlcv(
                    ticker,
                    start=start,
                    end=end,
                    interval=interval,
                    prepost=prepost,
                ) or []
                if bars:
                    return list(bars)
                stats["failure_reason_breakdown"][f"{name}:{interval}:empty_bars"] += 1
                self._log_failure(
                    group_key=group_key,
                    provider=name,
                    interval=interval,
                    attempt=attempt,
                    reason="empty_bars",
                )
            except Exception as exc:
                stats["failure_reason_breakdown"][f"{name}:{interval}:{exc}"] += 1
                self._log_failure(
                    group_key=group_key,
                    provider=name,
                    interval=interval,
                    attempt=attempt,
                    reason=str(exc),
                )
            if attempt < self.max_retries:
                self.sleep_fn(min(2 ** (attempt - 1), 4))
        return []

    def _fetch_group(
        self,
        group_key: str,
        stats: Dict[str, Any],
        initial: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        ticker, date_text = group_key.split("|", 1)
        start_dt = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
        intraday_end = start_dt + timedelta(days=9)
        daily_end = start_dt + timedelta(days=12)
        initial = initial or {}
        intraday: List[Any] = list(initial.get("intraday_bars", []))
        daily: List[Any] = list(initial.get("daily_bars", []))
        intraday_provider = initial.get("intraday_provider") or ""
        daily_provider = initial.get("daily_provider") or ""

        for provider in self.providers:
            name = self._provider_name(provider)
            before_intraday = bool(intraday)
            before_daily = bool(daily)
            if not intraday:
                intraday = self._request(
                    provider,
                    ticker,
                    start=start_dt.date().isoformat(),
                    end=intraday_end.date().isoformat(),
                    interval="5m",
                    prepost=True,
                    stats=stats,
                    group_key=group_key,
                )
                if intraday:
                    intraday_provider = name
            if not daily:
                daily = self._request(
                    provider,
                    ticker,
                    start=start_dt.date().isoformat(),
                    end=daily_end.date().isoformat(),
                    interval="1d",
                    prepost=False,
                    stats=stats,
                    group_key=group_key,
                )
                if daily:
                    daily_provider = name

            if (intraday and not before_intraday) or (daily and not before_daily):
                stats["provider_stats"][name]["successful_groups"] += 1
            elif not intraday and not daily:
                stats["provider_stats"][name]["failed_groups"] += 1
            if intraday and daily:
                break

        if not intraday and not daily:
            return None
        return {
            "intraday_bars": intraday,
            "daily_bars": daily,
            "intraday_provider": intraday_provider or None,
            "daily_provider": daily_provider or None,
            "provider": intraday_provider or daily_provider,
        }

    @staticmethod
    def _apply_bars(result: pd.DataFrame, indexes: Sequence[Any], payload: Dict[str, Any]) -> None:
        intraday = payload.get("intraday_bars", [])
        daily = payload.get("daily_bars", [])
        quality = "intraday_exact" if intraday else ("daily_proxy" if daily else "missing")
        provider = payload.get("provider")
        for index in indexes:
            alert_time = _aware(result.at[index, "alert_time"])
            price = float(result.at[index, "price_at_alert"])
            profiles = compute_mfe_mae_profiles(intraday, daily, price, alert_time)
            if intraday and daily:
                daily_profiles = compute_mfe_mae_profiles(None, daily, price, alert_time)
                for window in ("1d", "2d", "5d"):
                    mfe_field = f"mfe_{window}"
                    mae_field = f"mae_{window}"
                    intraday_mfe = getattr(profiles, mfe_field)
                    daily_mfe = getattr(daily_profiles, mfe_field)
                    intraday_mae = getattr(profiles, mae_field)
                    daily_mae = getattr(daily_profiles, mae_field)
                    if daily_mfe is not None:
                        setattr(profiles, mfe_field, max(v for v in (intraday_mfe, daily_mfe) if v is not None))
                    if daily_mae is not None:
                        setattr(profiles, mae_field, min(v for v in (intraday_mae, daily_mae) if v is not None))
            peak = compute_peak_metrics(intraday, daily, price, alert_time)
            for field, value in profiles.model_dump().items():
                result.at[index, field] = value
            for field, value in peak.model_dump().items():
                if field != "outcome_source":
                    result.at[index, field] = value
            result.at[index, "outcome_source"] = "bars" if intraday else "daily_proxy"
            result.at[index, "drawdown_data_quality"] = quality
            result.at[index, "forward_enrichment_provider"] = provider
            result.at[index, "forward_enrichment_version"] = ENGINE_VERSION

    def enrich(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Enrich rows in *df* and return a copied frame plus run statistics."""
        eligible, rejected = partition_synthetic_rows(df)
        result = pd.concat([eligible, rejected]).sort_index()
        for column in ("forward_enrichment_provider", "forward_enrichment_version"):
            if column not in result.columns:
                result[column] = None

        grouped: Dict[str, List[Any]] = defaultdict(list)
        for index, row in eligible.iterrows():
            grouped[_group_key(row["ticker"], row["alert_time"])].append(index)

        stats: Dict[str, Any] = {
            "rows_examined": len(result),
            "synthetic_rejected_rows": len(rejected),
            "groups_examined": len(grouped),
            "completed_groups": 0,
            "failed_groups": 0,
            "cache_hits": 0,
            "checkpoint_skips": 0,
            "provider_stats": defaultdict(lambda: {"api_calls": 0, "successful_groups": 0, "failed_groups": 0}),
            "failure_reason_breakdown": Counter(),
        }

        total_groups = len(grouped)
        for position, (group_key, indexes) in enumerate(sorted(grouped.items()), start=1):
            cached = self._load_cache(group_key)
            if cached and cached.get("intraday_bars") and cached.get("daily_bars"):
                stats["cache_hits"] += 1
                if group_key in self.completed_groups:
                    stats["checkpoint_skips"] += 1
                self._apply_bars(result, indexes, cached)
                logger.info(
                    "Rocket enrichment progress %d/%d: %s restored from cache",
                    position,
                    total_groups,
                    group_key,
                )
                continue

            if cached:
                stats["cache_hits"] += 1
            payload = self._fetch_group(group_key, stats, initial=cached)
            if payload is None:
                stats["failed_groups"] += 1
                stats["failure_reason_breakdown"]["all_providers_failed"] += 1
                self._log_failure(group_key=group_key, reason="all_providers_failed")
                logger.warning(
                    "Rocket enrichment progress %d/%d: %s failed across all providers",
                    position,
                    total_groups,
                    group_key,
                )
                continue
            self._save_cache(group_key, payload)
            self.completed_groups.add(group_key)
            self._save_checkpoint()
            stats["completed_groups"] += 1
            self._apply_bars(result, indexes, payload)
            logger.info(
                "Rocket enrichment progress %d/%d: %s cached via %s",
                position,
                total_groups,
                group_key,
                payload.get("provider") or "unknown",
            )

        result = reconstruct_labels(result, include_provisional=True)
        if len(rejected):
            result.loc[rejected.index, "training_runner_tier"] = "UNKNOWN"
            result.loc[rejected.index, "label_source"] = "rejected"
            result.loc[rejected.index, "label_confidence"] = None
        for index, row in result.iterrows():
            if row.get("rejection_reason") == SYNTHETIC_REJECTION_REASON:
                continue
            tier = row.get("training_runner_tier")
            if tier not in {"STANDARD_WIN", "MAJOR_RUNNER", "MONSTER_RUNNER", "LEGENDARY_RUNNER"}:
                continue
            group_key = _group_key(row["ticker"], row["alert_time"])
            cached = self._load_cache(group_key)
            if not cached:
                continue
            result.at[index, "drawdown_quality"] = compute_drawdown_quality(
                cached.get("intraday_bars"),
                cached.get("daily_bars"),
                float(row["price_at_alert"]),
                tier,
                row.get("drawdown_data_quality") or "missing",
                alert_time=_aware(row["alert_time"]),
            )

        stats["provider_stats"] = {
            name: dict(values) for name, values in sorted(stats["provider_stats"].items())
        }
        stats["failure_reason_breakdown"] = dict(sorted(stats["failure_reason_breakdown"].items()))
        return result, stats


def build_provider_chain() -> Tuple[List[Any], Dict[str, float]]:
    """Build Polygon -> Alpaca -> yfinance providers when configured."""
    from src.config import get_settings

    settings = get_settings()
    providers: List[Any] = []
    rpm: Dict[str, float] = {}
    if os.getenv("POLYGON_API_KEY") or settings.polygon_api_key:
        from src.services.polygon_provider import PolygonProvider

        provider = PolygonProvider()
        provider.name = "polygon"
        providers.append(provider)
        rpm["polygon"] = float(os.getenv("POLYGON_REQUESTS_PER_MINUTE", "5") or 5)
    if (
        (os.getenv("ALPACA_API_KEY") or settings.alpaca_api_key)
        and (os.getenv("ALPACA_SECRET_KEY") or settings.alpaca_secret_key)
    ):
        from src.services.alpaca_provider import AlpacaProvider

        provider = AlpacaProvider()
        provider.name = "alpaca"
        providers.append(provider)
        rpm["alpaca"] = float(os.getenv("ALPACA_REQUESTS_PER_MINUTE", "180") or 180)
    try:
        import yfinance  # noqa: F401
        from src.services.market_data import YFinanceProvider

        provider = YFinanceProvider()
        provider.name = "yfinance"
        providers.append(provider)
        rpm["yfinance"] = float(os.getenv("YFINANCE_REQUESTS_PER_MINUTE", "30") or 30)
    except Exception as exc:
        logger.warning("yfinance fallback unavailable: %s", exc)
    if not providers:
        raise RuntimeError("No historical market-data providers are available")
    return providers, rpm


def _distribution(df: pd.DataFrame) -> Dict[str, int]:
    return dict(sorted(Counter(df["training_runner_tier"].fillna("UNKNOWN").astype(str)).items()))


def render_smoke_report(
    *,
    before: pd.DataFrame,
    after: pd.DataFrame,
    stats: Dict[str, Any],
    total_unknown_rows: int,
    total_unknown_groups: int,
) -> str:
    before_unknown = int((before["training_runner_tier"] == "UNKNOWN").sum())
    after_unknown = int((after["training_runner_tier"] == "UNKNOWN").sum())
    newly_labeled = before_unknown - after_unknown
    api_calls = sum(item["api_calls"] for item in stats["provider_stats"].values())
    calls_per_group = api_calls / stats["groups_examined"] if stats["groups_examined"] else 0
    estimated_calls = round(calls_per_group * total_unknown_groups)
    polygon_rpm = float(os.getenv("POLYGON_REQUESTS_PER_MINUTE", "5") or 5)
    estimated_minutes = estimated_calls / polygon_rpm if polygon_rpm else 0
    lines = [
        "# Rocket Forward Enrichment Smoke Report",
        "",
        "## Scope",
        "",
        "Small resumable smoke batch only. The full historical run was not started.",
        "No ML model was trained and no production alert or Telegram logic was modified.",
        "",
        "## Smoke Coverage",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Rows examined | {stats['rows_examined']:,} |",
        f"| Synthetic rows excluded before fetch | {stats['synthetic_rejected_rows']:,} |",
        f"| Mixed ticker/date groups | {stats['groups_examined']:,} |",
        f"| Unknown rows before smoke enrichment | {before_unknown:,} |",
        f"| Unknown rows after smoke enrichment | {after_unknown:,} |",
        f"| Unknown rows newly labeled | {newly_labeled:,} |",
        f"| Durable cache hits | {stats['cache_hits']:,} |",
        f"| Checkpoint resume skips | {stats['checkpoint_skips']:,} |",
        f"| Failed groups | {stats['failed_groups']:,} |",
        "",
        "## Final Runner Distribution",
        "",
        "| Label | Rows |",
        "|---|---:|",
    ]
    lines.extend(f"| `{label}` | {count:,} |" for label, count in _distribution(after).items())
    lines.extend(["", "## Provider Results", "", "| Provider | API Calls | Successful Groups | Failed Groups | Success Rate |", "|---|---:|---:|---:|---:|"])
    for name, item in stats["provider_stats"].items():
        attempts = item["successful_groups"] + item["failed_groups"]
        success_rate = item["successful_groups"] / attempts * 100.0 if attempts else 0.0
        lines.append(f"| `{name}` | {item['api_calls']:,} | {item['successful_groups']:,} | {item['failed_groups']:,} | {success_rate:.1f}% |")
    lines.extend(["", "## Failure Reasons", ""])
    if stats["failure_reason_breakdown"]:
        lines.extend(
            f"- `{reason}`: {count:,}"
            for reason, count in stats["failure_reason_breakdown"].items()
        )
    else:
        lines.append("- No provider exceptions were recorded.")
    lines.extend(
        [
            "",
            "## Full-Run Estimate",
            "",
            f"- Remaining unknown rows before a full run: **{total_unknown_rows:,}**.",
            f"- Distinct unknown ticker/date groups: **{total_unknown_groups:,}**.",
            f"- Smoke API calls per group: **{calls_per_group:.2f}**.",
            f"- Estimated total API calls at the observed rate: **{estimated_calls:,}**.",
            f"- Polygon-only free-tier lower-bound runtime at {polygon_rpm:g} requests/minute: **{estimated_minutes / 60:.1f} hours**.",
            "- Actual runtime can improve when cache reuse is high or Alpaca fills missing modalities, and can increase when retries are required.",
            "",
            "## Risk Assessment",
            "",
            "- Polygon free tier is the primary rate-limit risk. Keep the default at 5 requests/minute unless the account tier is confirmed.",
            "- Alpaca fallback reduces missing data but historical feed entitlements may limit older or non-exchange symbols.",
            "- yfinance remains a final fallback only. SSL failures and historical intraday retention limits are logged per group.",
            "- Failed groups remain resumable; successful groups are cached locally and are not refetched.",
            "",
            "## Recommended Full-Run Settings",
            "",
            "- Review this smoke report before starting a full run.",
            "- Keep `POLYGON_REQUESTS_PER_MINUTE=5` for free tier.",
            "- Keep `ALPACA_REQUESTS_PER_MINUTE=180` unless account limits require a lower value.",
            "- Keep `YFINANCE_REQUESTS_PER_MINUTE=30` and treat it as a final fallback.",
            "- Resume with the same state directory so cached and completed groups are reused.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setLevel(logging.DEBUG)
    _handler.addFilter(lambda rec: rec.levelno < logging.WARNING)
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    _err_handler = logging.StreamHandler(sys.stderr)
    _err_handler.setLevel(logging.WARNING)
    _err_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[_handler, _err_handler])
    # Authenticated market-data URLs can include API keys in their query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--smoke-rows", type=int, default=DEFAULT_SMOKE_ROWS)
    parser.add_argument("--allow-full-run", action="store_true")
    parser.add_argument("--output-prefix", default="rocket_training_dataset_reconstructed_v2_smoke")
    parser.add_argument("--report", default="docs/rocket_forward_enrichment_report.md")
    args = parser.parse_args(list(argv) if argv is not None else None)

    source = pd.read_parquet(args.input) if str(args.input).lower().endswith(".parquet") else pd.read_csv(args.input, low_memory=False)
    eligible_source, synthetic_rejections = partition_synthetic_rows(source)
    unknown = eligible_source[eligible_source["training_runner_tier"].fillna("UNKNOWN") == "UNKNOWN"].copy()
    selected = unknown if args.allow_full_run else select_smoke_rows(unknown, limit=args.smoke_rows)
    providers, rpm = build_provider_chain()
    enricher = RocketForwardEnricher(providers=providers, state_dir=args.state_dir, requests_per_minute=rpm)
    enriched_selected, stats = enricher.enrich(selected)

    output = eligible_source.copy(deep=True)
    for column in enriched_selected.columns:
        if column not in output.columns:
            output[column] = None
    output.loc[enriched_selected.index, enriched_selected.columns] = enriched_selected
    data_dir = agentic_data_dir()
    csv_path = data_dir / f"{args.output_prefix}.csv"
    parquet_path = data_dir / f"{args.output_prefix}.parquet"
    rejection_csv_path = data_dir / f"{args.output_prefix}_synthetic_rejections.csv"
    rejection_parquet_path = data_dir / f"{args.output_prefix}_synthetic_rejections.parquet"
    output.to_csv(csv_path, index=False, encoding="utf-8")
    output.to_parquet(parquet_path, index=False, compression="snappy")
    synthetic_rejections.to_csv(rejection_csv_path, index=False, encoding="utf-8")
    synthetic_rejections.to_parquet(rejection_parquet_path, index=False, compression="snappy")
    total_groups = len({_group_key(row.ticker, row.alert_time) for row in unknown.itertuples()})
    report_text = render_smoke_report(
        before=selected,
        after=enriched_selected,
        stats=stats,
        total_unknown_rows=len(unknown),
        total_unknown_groups=total_groups,
    )
    Path(args.report).write_text(report_text, encoding="utf-8")
    print(json.dumps({
        "csv": str(csv_path),
        "parquet": str(parquet_path),
        "synthetic_rejections_csv": str(rejection_csv_path),
        "synthetic_rejections_parquet": str(rejection_parquet_path),
        "report": args.report,
        "stats": stats,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
