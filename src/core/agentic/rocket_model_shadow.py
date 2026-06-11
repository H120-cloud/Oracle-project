"""Live shadow scoring for the offline Rocket CatBoost baseline.

This module is intentionally passive: it never changes alert eligibility,
ranking, Telegram content, or trading behavior. It only writes model
predictions to JSONL so the Rocket model can be validated live before any
production use.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from src.utils.data_paths import agentic_data_dir, agentic_path
from typing import Any, Mapping, Optional

import joblib
import pandas as pd

from src.core.agentic.rocket_dataset_builder import (
    BUILDER_VERSION,
    DATASET_VERSION,
    FEATURE_COLUMNS,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = agentic_path("rocket_catboost_baseline_shadow.joblib")
DEFAULT_PREDICTIONS_PATH = agentic_path("rocket_model_shadow_predictions.jsonl")

# Process-wide artifact cache keyed by path -> (mtime, artifact). The artifact
# is ~26MB; several call sites construct fresh scorer instances (pre-news scan
# every cycle, diagnostics status per dashboard view), and without this each
# one re-loaded the file from disk. mtime-keyed so a newly deployed model file
# invalidates the cache automatically.
_ARTIFACT_CACHE: dict[str, tuple[float, Any]] = {}


def enforce_monotonic_probabilities(
    runner: float, major: float, monster: float
) -> tuple[float, float, float]:
    """Clamp the three nested-tier probabilities to be logically consistent.

    The targets are nested (monster ⊂ major ⊂ runner), so
    P(>=10%) >= P(>=30%) >= P(>=100%) must always hold. Three independently
    trained binaries can violate this; clamp to the implied envelope.
    """
    runner2 = max(runner, major, monster)
    major2 = min(max(major, monster), runner2)
    monster2 = min(monster, major2)
    return runner2, major2, monster2

_TARGETS = ("binary_runner", "binary_major_plus", "binary_monster_plus")
_CATEGORICAL_DEFAULTS = {
    "row_id",
    "source_type",
    "ticker",
    "catalyst_type",
    "catalyst_subtype",
    "catalyst_category",
    "session_type",
    "float_category",
    "market_cap_category",
    "sec_dilution_behavior",
    "sec_oracle_action",
    "dataset_version",
    "builder_version",
}


def _enum_value(value: Any) -> Any:
    if value is None:
        return None
    return getattr(value, "value", value)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = pd.to_datetime(value, utc=True, errors="coerce").to_pydatetime()
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _int(value: Any) -> Optional[int]:
    numeric = _num(value)
    if numeric is None:
        return None
    return int(numeric)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def build_shadow_feature_row(candidate: Any, *, source_pipeline: str) -> dict[str, Any]:
    """Convert a live candidate/anomaly to leakage-safe Rocket features only."""
    is_pre_news = source_pipeline.lower().startswith("pre")
    detected_at = getattr(candidate, "detected_at", None) or getattr(candidate, "updated_at", None)
    row_id = getattr(candidate, "id", None) or f"{getattr(candidate, 'ticker', 'UNKNOWN')}:{_iso(detected_at) or ''}"

    volume_metrics = getattr(candidate, "volume_metrics", None)
    price_behaviour = getattr(candidate, "price_behaviour", None)

    ml_prediction = getattr(candidate, "_ml_prediction", None)
    ml_predicted_win_prob = _num(getattr(ml_prediction, "win_probability", None))

    if is_pre_news:
        row = {
            "row_id": str(row_id),
            "source_type": "prenews",
            "ticker": getattr(candidate, "ticker", None),
            "alert_time": _iso(detected_at),
            "price_at_alert": _num(getattr(candidate, "price", None)),
            "catalyst_type": _enum_value(getattr(candidate, "anomaly_type", None)),
            "catalyst_subtype": _enum_value(getattr(candidate, "candidate_type", None)),
            "catalyst_category": "pre_news_volume",
            "session_type": _enum_value(getattr(candidate, "session", None)),
            "float_category": None,
            "market_cap_category": None,
            "move_pct_at_alert": _num(getattr(price_behaviour, "price_change_pct", None)),
            "rvol_at_alert": _num(getattr(volume_metrics, "rvol_current", None)),
            "volume_at_alert": _int(getattr(volume_metrics, "current_volume", None)),
            "spread_pct_at_alert": None,
            "trap_risk_at_alert": _num(getattr(candidate, "offering_risk_score", None)),
            "dilution_risk_at_alert": _num(getattr(candidate, "offering_risk_score", None)),
            "velocity_score_at_alert": _num(getattr(volume_metrics, "volume_acceleration_score", None)),
            "sources_seen_count": 1,
            "is_negative": False,
            "is_vague": False,
            "is_delayed_reaction": bool(getattr(candidate, "late_detection_flag", False)),
            "prenews_anomaly_score": _num(getattr(candidate, "pre_news_suspicion_score", None)),
            "ml_predicted_win_prob": None,
            "news_impact_score": _num(getattr(candidate, "catalyst_relevance_score", None)),
            "expected_return_score": _num(getattr(candidate, "pre_news_suspicion_score", None)),
            "continuation_probability": _num(getattr(price_behaviour, "score", None)),
            "multi_day_score": _num(getattr(candidate, "winner_similarity_score", None)),
        }
    else:
        row = {
            "row_id": str(row_id),
            "source_type": "shadow",
            "ticker": getattr(candidate, "ticker", None),
            "alert_time": _iso(detected_at),
            "price_at_alert": _num(getattr(candidate, "current_price", None)),
            # Training rows store the SUBTYPE here (TelegramAlertRecord is built
            # with catalyst_type=c.catalyst_sub_type) — mirror that exactly, or
            # the model sees unseen category values in its key categorical.
            "catalyst_type": _enum_value(getattr(candidate, "catalyst_sub_type", None)),
            "catalyst_subtype": _enum_value(getattr(candidate, "catalyst_sub_type", None)),
            "catalyst_category": _enum_value(getattr(candidate, "catalyst_category", None)),
            "session_type": _enum_value(getattr(candidate, "session", None)),
            "float_category": _enum_value(getattr(candidate, "float_category", None)),
            "market_cap_category": _enum_value(getattr(candidate, "market_cap_category", None)),
            "move_pct_at_alert": _num(getattr(candidate, "move_pct", None)),
            "rvol_at_alert": _num(getattr(candidate, "rvol", None)),
            "volume_at_alert": _int(getattr(candidate, "volume", None)),
            "spread_pct_at_alert": _num(getattr(candidate, "spread_pct", None)),
            "trap_risk_at_alert": _num(getattr(candidate, "trap_risk", None)),
            "dilution_risk_at_alert": _num(getattr(candidate, "dilution_risk", None)),
            "velocity_score_at_alert": _num(getattr(candidate, "velocity_score", None)),
            "sources_seen_count": _int(getattr(candidate, "sources_seen_count", None)),
            "is_negative": bool(getattr(candidate, "is_negative", False)),
            "is_vague": bool(getattr(candidate, "is_vague", False)),
            "is_delayed_reaction": bool(getattr(candidate, "is_delayed_reaction", False)),
            "prenews_anomaly_score": None,
            "ml_predicted_win_prob": ml_predicted_win_prob,
            "news_impact_score": _num(getattr(candidate, "news_impact_score", None)),
            "expected_return_score": _num(getattr(candidate, "expected_return_score", None)),
            "continuation_probability": _num(getattr(candidate, "continuation_probability", None)),
            "multi_day_score": _num(getattr(candidate, "multi_day_continuation_score", None)),
        }

    sec = getattr(candidate, "sec_intelligence", None) or getattr(candidate, "_sec_candidate", None)
    row.update(
        {
            "sec_dilution_probability": _num(getattr(sec, "dilution_probability", None)),
            "sec_toxic_financing_score": _num(getattr(sec, "toxic_financing_score", None)),
            "sec_warrant_overhang_score": _num(getattr(sec, "warrant_overhang_score", None)),
            "sec_cash_runway_score": _num(getattr(sec, "cash_runway_score", None)),
            "sec_survival_risk_score": _num(getattr(sec, "survival_risk_score", None)),
            "sec_balance_sheet_quality_score": _num(getattr(sec, "balance_sheet_quality_score", None)),
            "sec_offering_risk_score": _num(getattr(sec, "offering_risk_score", None)),
            "sec_reverse_split_risk_score": _num(getattr(sec, "reverse_split_risk_score", None)),
            "sec_structural_trap_risk_score": _num(getattr(sec, "structural_trap_risk_score", None)),
            "sec_historical_dilution_behavior_score": _num(getattr(sec, "historical_dilution_behavior_score", None)),
            "sec_dilution_behavior": _enum_value(getattr(sec, "dilution_behavior", None)),
            "sec_oracle_action": _enum_value(getattr(sec, "oracle_action", None)),
            "sec_atm_active": getattr(sec, "atm_active", None),
            "sec_going_concern_active": getattr(sec, "going_concern_active", None),
            "dataset_version": DATASET_VERSION,
            "builder_version": BUILDER_VERSION,
        }
    )
    return {column: row.get(column) for column in FEATURE_COLUMNS}


def prediction_confidence(*, feature_null_count: int, max_probability: float) -> str:
    """Coarse confidence label for operator review, not live gating."""
    if feature_null_count <= 6 and max_probability >= 0.65:
        return "HIGH"
    if feature_null_count <= 16:
        return "MEDIUM"
    return "LOW"


def rocket_rank_score(
    *,
    binary_runner_probability: float,
    binary_major_plus_probability: float,
    binary_monster_plus_probability: float,
) -> float:
    """Single shadow ranking score biased toward larger runners."""
    return round(
        0.20 * binary_runner_probability
        + 0.45 * binary_major_plus_probability
        + 0.35 * binary_monster_plus_probability,
        6,
    )


class RocketModelShadowScorer:
    """Append-only live shadow scorer for Rocket CatBoost models."""

    def __init__(
        self,
        *,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        predictions_path: Path | str = DEFAULT_PREDICTIONS_PATH,
        artifact: Optional[Mapping[str, Any]] = None,
        enabled: Optional[bool] = None,
        max_predictions_bytes: Optional[int] = None,
    ) -> None:
        env_enabled = os.getenv("ROCKET_MODEL_SHADOW_ENABLED", "1").strip().lower()
        self.enabled = enabled if enabled is not None else env_enabled not in {"0", "false", "no", "off"}
        self.model_path = Path(model_path)
        self.predictions_path = Path(predictions_path)
        # Retention cap for the append-only predictions log (compacted to the
        # newest half once exceeded) so it can't grow without bound.
        if max_predictions_bytes is None:
            max_predictions_bytes = int(
                os.getenv("ROCKET_SHADOW_MAX_PREDICTIONS_BYTES", str(16 * 1024 * 1024)) or 16 * 1024 * 1024
            )
        self.max_predictions_bytes = max_predictions_bytes
        self._artifact: Optional[Mapping[str, Any]] = artifact
        self._load_attempted = artifact is not None
        self._last_load_error: Optional[str] = None

    @property
    def artifact(self) -> Optional[Mapping[str, Any]]:
        if not self.enabled:
            self._last_load_error = "shadow scorer disabled (ROCKET_MODEL_SHADOW_ENABLED)"
            return None
        if self._artifact is not None:
            return self._artifact
        if self._load_attempted:
            return None
        self._load_attempted = True
        if not self.model_path.exists():
            self._last_load_error = f"model file not found: {self.model_path}"
            logger.info("Rocket shadow model unavailable: %s does not exist", self.model_path)
            return None
        cache_key = str(self.model_path)
        try:
            mtime = self.model_path.stat().st_mtime
        except OSError:
            mtime = None
        cached = _ARTIFACT_CACHE.get(cache_key)
        if cached is not None and mtime is not None and cached[0] == mtime:
            self._artifact = cached[1]
            self._last_load_error = None
            return self._artifact
        try:
            self._artifact = joblib.load(self.model_path)
            self._last_load_error = None
            if mtime is not None:
                _ARTIFACT_CACHE[cache_key] = (mtime, self._artifact)
        except Exception as exc:
            # e.g. ModuleNotFoundError: No module named 'catboost'
            self._last_load_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Rocket shadow model load failed: %s", exc)
            self._artifact = None
        return self._artifact

    def model_version(self) -> str:
        artifact = self.artifact or {}
        created = artifact.get("created_at") or artifact.get("model_version") or "unknown"
        return f"rocket_catboost_baseline_shadow:{created}"

    def status(self) -> dict[str, Any]:
        """Read-only operational status for the diagnostics dashboard.

        Triggers a lazy load so ``model_loaded`` reflects whether the model can
        actually be used (file present AND its dependencies importable, e.g.
        catboost). Never affects gating — this is telemetry only.
        """
        artifact = self.artifact  # lazy load; populates _last_load_error on failure
        loaded = artifact is not None
        count = 0
        last_at: Optional[str] = None
        try:
            if self.predictions_path.exists():
                last_line = None
                for line in self.predictions_path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped:
                        count += 1
                        last_line = stripped
                if last_line:
                    try:
                        last_at = json.loads(last_line).get("logged_at")
                    except Exception:
                        last_at = None
        except Exception as exc:
            logger.debug("Rocket shadow status: predictions read failed: %s", exc)
        return {
            "enabled": self.enabled,
            "model_loaded": loaded,
            "model_path": str(self.model_path),
            "model_version": self.model_version() if loaded else None,
            "last_load_error": self._last_load_error,
            "prediction_count": count,
            "last_prediction_at": last_at,
        }

    def _prepare_features(self, row: Mapping[str, Any]) -> pd.DataFrame:
        artifact = self.artifact or {}
        columns = list(artifact.get("feature_columns") or FEATURE_COLUMNS)
        encoding = str(artifact.get("alert_time_encoding") or "epoch_v1")
        features = pd.DataFrame([{column: row.get(column) for column in columns}])
        for column in features.columns:
            if column == "alert_time":
                dt = pd.to_datetime(features[column], utc=True, errors="coerce")
                if encoding == "weekly_v2":
                    # Weekly position (dow*24 + hour, 0..167): removes the
                    # absolute-time monotonicity a tree could use to memorize
                    # calendar regimes; -1 marks missing timestamps cleanly.
                    values = dt.dt.dayofweek * 24 + dt.dt.hour
                    features[column] = values.fillna(-1.0).astype(float)
                else:
                    features[column] = dt.astype("int64")
            elif features[column].dtype == bool:
                features[column] = features[column].astype("float")

        categorical_columns = set(artifact.get("categorical_columns") or _CATEGORICAL_DEFAULTS)
        for column in categorical_columns & set(features.columns):
            features[column] = features[column].fillna("__MISSING__").astype(str)
        return features

    def predict_candidate(self, candidate: Any, *, source_pipeline: str) -> Optional[dict[str, Any]]:
        artifact = self.artifact
        if artifact is None:
            return None
        models = artifact.get("models") or {}
        if not all(target in models for target in _TARGETS):
            logger.warning("Rocket shadow model artifact missing required targets")
            return None

        row = build_shadow_feature_row(candidate, source_pipeline=source_pipeline)
        feature_null_count_before = sum(1 for value in row.values() if _is_missing(value))
        # Fill missing market_cap/float categories from the Finnhub company
        # profile (cached). Operates on the row copy only — candidates and
        # gating are never touched; failures degrade to the un-enriched row.
        profile = None
        try:
            from src.core.agentic.rocket_feature_enrichment import enrich_feature_row
            profile = enrich_feature_row(row, getattr(candidate, "ticker", None))
        except Exception as exc:
            logger.debug("Rocket shadow enrichment skipped: %s", exc)
        features = self._prepare_features(row)
        calibrators = artifact.get("calibrators") or {}
        probabilities: dict[str, float] = {}
        for target in _TARGETS:
            proba = models[target].predict_proba(features)
            p = float(proba[0][1])
            calibrator = calibrators.get(target)
            if calibrator is not None:
                try:
                    p = float(calibrator.predict([p])[0])
                except Exception as exc:
                    logger.debug("Rocket shadow calibrator failed for %s: %s", target, exc)
            probabilities[target] = p
        runner, major, monster = enforce_monotonic_probabilities(
            probabilities["binary_runner"],
            probabilities["binary_major_plus"],
            probabilities["binary_monster_plus"],
        )
        probabilities = {
            "binary_runner": round(runner, 6),
            "binary_major_plus": round(major, 6),
            "binary_monster_plus": round(monster, 6),
        }

        feature_null_count = sum(1 for value in row.values() if _is_missing(value))
        rank_score = rocket_rank_score(
            binary_runner_probability=probabilities["binary_runner"],
            binary_major_plus_probability=probabilities["binary_major_plus"],
            binary_monster_plus_probability=probabilities["binary_monster_plus"],
        )
        detected_at = getattr(candidate, "detected_at", None) or getattr(candidate, "updated_at", None)
        published_at = getattr(candidate, "published_at", None) or getattr(candidate, "first_news_timestamp", None)
        return {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "source_pipeline": source_pipeline,
            "candidate_id": getattr(candidate, "id", None),
            "ticker": getattr(candidate, "ticker", None),
            "headline": getattr(candidate, "headline", None) or getattr(candidate, "first_news_headline", None) or getattr(candidate, "matched_headline", None),
            "detected_at": _iso(detected_at),
            "published_at": _iso(published_at),
            # Anchor price so the outcome resolver can compute forward returns.
            "price_at_alert": row.get("price_at_alert"),
            "binary_runner_probability": probabilities["binary_runner"],
            "binary_major_plus_probability": probabilities["binary_major_plus"],
            "binary_monster_plus_probability": probabilities["binary_monster_plus"],
            "rocket_rank_score": rank_score,
            "model_version": self.model_version(),
            "feature_null_count": feature_null_count,
            "feature_null_count_before": feature_null_count_before,
            "enriched": profile is not None,
            "profile_exchange": (profile or {}).get("exchange"),
            "profile_country": (profile or {}).get("country"),
            "profile_industry": (profile or {}).get("industry"),
            "prediction_confidence": prediction_confidence(
                feature_null_count=feature_null_count,
                max_probability=max(probabilities.values()),
            ),
            "expected_return_score": row.get("expected_return_score"),
            "news_impact_score": row.get("news_impact_score"),
            "continuation_probability": row.get("continuation_probability"),
            "multi_day_score": row.get("multi_day_score"),
        }

    def append_prediction(self, record: Mapping[str, Any]) -> None:
        self.predictions_path.parent.mkdir(parents=True, exist_ok=True)
        with self.predictions_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._compact_if_oversized()

    def _compact_if_oversized(self) -> None:
        """Keep the newest half of the log once it exceeds the retention cap."""
        try:
            if not self.max_predictions_bytes:
                return
            if self.predictions_path.stat().st_size <= self.max_predictions_bytes:
                return
            lines = [
                line for line in self.predictions_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            keep = lines[len(lines) // 2:]
            tmp = self.predictions_path.with_suffix(".tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            os.replace(tmp, self.predictions_path)
            logger.info(
                "Rocket shadow predictions compacted: kept newest %d of %d rows",
                len(keep), len(lines),
            )
        except Exception as exc:
            logger.debug("Rocket shadow predictions compaction skipped: %s", exc)

    def predict_and_log_candidate(self, candidate: Any, *, source_pipeline: str) -> Optional[dict[str, Any]]:
        try:
            record = self.predict_candidate(candidate, source_pipeline=source_pipeline)
            if record is None:
                return None
            self.append_prediction(record)
            return record
        except Exception as exc:
            logger.debug(
                "Rocket shadow prediction failed for %s/%s: %s",
                source_pipeline,
                getattr(candidate, "ticker", "?"),
                exc,
            )
            return None


# ── Outcome resolution (the live scoreboard) ─────────────────────────────────

def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def resolve_shadow_outcomes(
    *,
    provider: Any = None,
    path: Path | str = DEFAULT_PREDICTIONS_PATH,
    now: Optional[datetime] = None,
    max_tickers: int = 20,
    min_age_days: float = 5.0,
) -> dict[str, int]:
    """Join logged shadow predictions to realized forward returns.

    Without this the model's offline AUC is unverifiable live. Rows older than
    *min_age_days* get stamped with fwd_high_2d_pct / fwd_high_5d_pct and the
    realized runner/major/monster flags (same tier definitions as training:
    runner >=10% within 5d, major >=30% within 2d, monster >=100% within 5d).
    Never touches gating — telemetry only.
    """
    path = Path(path)
    now = now or datetime.now(timezone.utc)
    stats = {"resolved": 0, "pending": 0, "no_data": 0}
    if not path.exists():
        return stats

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    eligible: list[tuple[dict[str, Any], datetime]] = []
    for r in rows:
        if r.get("outcome_resolved") or not r.get("ticker"):
            continue
        if not (_num(r.get("price_at_alert")) or 0) > 0:
            continue
        logged = _aware(r.get("logged_at"))
        if logged is None:
            continue
        if (now - logged).total_seconds() >= min_age_days * 86400:
            eligible.append((r, logged))
        else:
            stats["pending"] += 1
    if not eligible:
        return stats

    if provider is None:
        from src.services.market_data import get_market_data_provider
        provider = get_market_data_provider()

    bars_by_ticker: dict[str, list] = {}
    for r, logged in eligible:
        ticker = str(r["ticker"]).upper()
        if ticker not in bars_by_ticker:
            if len(bars_by_ticker) >= max_tickers:
                stats["pending"] += 1
                continue
            try:
                bars_by_ticker[ticker] = provider.get_ohlcv(
                    ticker, period="1mo", interval="1d", prepost=False
                ) or []
            except Exception as exc:
                logger.debug("RocketShadow outcomes: bars fetch failed for %s: %s", ticker, exc)
                bars_by_ticker[ticker] = []

        forward = sorted(
            (b for b in bars_by_ticker[ticker]
             if _aware(getattr(b, "timestamp", None)) and _aware(b.timestamp) > logged),
            key=lambda b: b.timestamp,
        )
        if not forward:
            # Old enough that bars should exist; after 14 days call it no-data
            # (delisted/halted/symbol gone) so it stops being re-fetched.
            if (now - logged).days >= 14:
                r["outcome_resolved"] = True
                r["outcome_status"] = "no_data"
                stats["no_data"] += 1
            else:
                stats["pending"] += 1
            continue

        price = float(r["price_at_alert"])
        high_2d = max(float(b.high) for b in forward[:2])
        high_5d = max(float(b.high) for b in forward[:5])
        fwd_2d = (high_2d / price - 1.0) * 100.0
        fwd_5d = (high_5d / price - 1.0) * 100.0
        r.update({
            "outcome_resolved": True,
            "outcome_status": "resolved",
            "resolved_at": now.isoformat(),
            "fwd_high_2d_pct": round(fwd_2d, 2),
            "fwd_high_5d_pct": round(fwd_5d, 2),
            "realized_runner": fwd_5d >= 10.0,
            "realized_major": fwd_2d >= 30.0,
            "realized_monster": fwd_5d >= 100.0,
        })
        stats["resolved"] += 1

    if stats["resolved"] or stats["no_data"]:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        logger.info("RocketShadow outcomes: %s", stats)
    return stats
