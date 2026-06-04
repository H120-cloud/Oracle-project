"""
Agentic Orchestrator — ties all engines together into a single pipeline.

Pipeline:
  CatalystScanner → FloatIntelEngine → MomentumClassifier →
  FailureVelocityEngine → SecondLegEngine → TrapDetector →
  TimeOfDayEngine → EntryTimingEngine → final scoring → alerts
"""

import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional

from src.utils.atomic_json import save_json_file, load_json_file

import yfinance as yf

from src.models.market_data import OHLCVBar
from src.core.agentic.models import (
    AgenticCandidate, AgenticAlert, ConfidenceLevel,
    MomentumState, EntryQuality, ABCDState,
)
from src.core.agentic.catalyst_scanner import CatalystScanner
from src.core.agentic.float_intel import FloatIntelEngine
from src.core.agentic.momentum_classifier import MomentumClassifier
from src.core.agentic.second_leg_engine import SecondLegEngine
from src.core.agentic.trap_detector import TrapDetector
from src.core.agentic.time_of_day import TimeOfDayEngine
from src.core.agentic.failure_velocity import FailureVelocityEngine
from src.core.agentic.entry_timing import EntryTimingEngine
from src.core.agentic.market_regime_service import apply_regime_to_candidate
from src.core.agentic.pre_news_bridge import apply_pre_news_to_candidate
from src.core.agentic.pre_news_validation import PreNewsValidationTracker
from src.core.agentic.calibration_provider import get_calibration_weights
from src.core.agentic.quality_separator import QualitySeparatorEngine
from src.core.agentic.risk_rules import HardRejectionEngine, AsymmetricScoringEngine
from src.core.agentic.abcd_detector import ABCDDetector
from src.core.agentic.news_impact_engine import NewsImpactEngine, NewsDecision
from src.core.agentic.news_impact_learning import NewsImpactLearningEngine

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "agentic")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _fetch_intraday_bars(ticker: str, period: str = "1d", interval: str = "1m") -> list[OHLCVBar]:
    """Fetch intraday bars via yfinance."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, prepost=True)
        if df.empty:
            return []
        bars = []
        for ts, row in df.iterrows():
            bars.append(OHLCVBar(
                timestamp=ts.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            ))
        return bars
    except Exception as e:
        logger.warning("Failed to fetch bars for %s: %s", ticker, e)
        return []


class AgenticOrchestrator:
    """
    Main pipeline controller for Agentic Catalyst Momentum Mode.

    Usage:
        orch = AgenticOrchestrator()
        candidates = orch.run_scan()          # Full discovery + analysis
        candidate = orch.refresh(candidate)   # Update a single candidate
    """

    def __init__(self):
        self.catalyst_scanner = CatalystScanner()
        self.float_engine = FloatIntelEngine()
        self.momentum_engine = MomentumClassifier()
        self.second_leg_engine = SecondLegEngine()
        self.trap_engine = TrapDetector()
        self.tod_engine = TimeOfDayEngine()
        self.fv_engine = FailureVelocityEngine()
        self.entry_engine = EntryTimingEngine()

        # V18 ABCD Pattern Confirmation Layer
        self.abcd_engine = ABCDDetector()

        # V20 News Catalyst Impact Engine
        self.news_impact_engine = NewsImpactEngine()
        try:
            self.news_impact_learning = NewsImpactLearningEngine()
        except Exception as exc:
            logger.warning("NewsImpactLearningEngine init failed: %s", exc)
            self.news_impact_learning = None
        self._news_impact_alert_cooldowns: dict[str, datetime] = {}

        # In-memory candidate store
        self._candidates: dict[str, AgenticCandidate] = {}
        self._alerts: list[AgenticAlert] = []
        self._alert_cooldowns: dict[str, datetime] = {}

        # Historical calibration weights (approved only)
        self._calibration_weights = get_calibration_weights()
        if self._calibration_weights:
            logger.info("Orchestrator loaded approved calibration weights v%s", self._calibration_weights.version)

        self.quality_engine = QualitySeparatorEngine()
        qs_status = self.quality_engine.get_profiles_summary()
        if qs_status.get("status") == "ready":
            logger.info("Quality Separator loaded with %d historical outcomes", qs_status.get("total_outcomes", 0))
        else:
            logger.info("Quality Separator insufficient data: %s outcomes", qs_status.get("total_outcomes", 0))

        self.hard_rejection_engine = HardRejectionEngine()
        self.asymmetric_engine = AsymmetricScoringEngine()

        _ensure_data_dir()

    @property
    def candidates(self) -> dict[str, AgenticCandidate]:
        return self._candidates

    @property
    def alerts(self) -> list[AgenticAlert]:
        return self._alerts

    # ── Full Scan Pipeline ───────────────────────────────────────────────

    def run_scan(self) -> list[AgenticCandidate]:
        """
        Full discovery pipeline:
        1. Scan for catalyst candidates
        2. Enrich with float intelligence
        3. Fetch bars and classify momentum
        4. Compute second-leg probability, trap risk, timing
        5. Final scoring and alert decision
        """
        logger.info("Agentic scan starting...")

        # Step 1: Discover catalyst candidates
        raw_candidates = self.catalyst_scanner.scan(min_change_pct=3.0, min_rvol=1.5)
        logger.info("Discovered %d raw candidates", len(raw_candidates))

        results = []
        for cand in raw_candidates:
            try:
                cand = self._run_pipeline(cand)
                self._candidates[cand.ticker] = cand
                results.append(cand)
            except Exception as e:
                logger.error("Pipeline failed for %s: %s", cand.ticker, e)

        # Sort by final probability descending
        results.sort(key=lambda c: c.final_probability, reverse=True)

        # Generate alerts for qualifying candidates
        for cand in results:
            self._maybe_alert(cand)

        self._persist_state()
        logger.info(
            "Agentic scan complete: %d candidates, %d alertable",
            len(results),
            sum(1 for c in results if c.alertable),
        )
        return results

    def refresh(self, ticker: str) -> Optional[AgenticCandidate]:
        """Re-analyze a single candidate with fresh bars."""
        cand = self._candidates.get(ticker)
        if not cand:
            return None
        try:
            cand = self._run_pipeline(cand)
            self._candidates[ticker] = cand
            self._maybe_alert(cand)
            return cand
        except Exception as e:
            logger.error("Refresh failed for %s: %s", ticker, e)
            return cand

    def refresh_all(self) -> list[AgenticCandidate]:
        """Re-analyze all active candidates."""
        updated = []
        for ticker in list(self._candidates.keys()):
            cand = self._candidates[ticker]
            if not cand.active:
                continue
            try:
                cand = self._run_pipeline(cand)
                self._candidates[ticker] = cand
                self._maybe_alert(cand)
                updated.append(cand)
            except Exception as e:
                logger.error("Refresh failed for %s: %s", ticker, e)
        return updated

    def deactivate(self, ticker: str) -> bool:
        """Mark a candidate as inactive (dead/failed)."""
        if ticker in self._candidates:
            self._candidates[ticker].active = False
            return True
        return False

    # ── Pre-News V2 Handoff ─────────────────────────────────────────────

    def handoff_from_pre_news(self, anomalies: list) -> dict:
        """
        V2 handoff: convert qualifying pre-news anomalies into AgenticCandidates.

        Dedup rules:
          - If ticker already tracked AND existing source tag is "pre_news_v2":
                update the existing candidate (refresh score + fields)
          - If ticker already tracked with different source (catalyst, etc):
                skip — do NOT overwrite a richer candidate
          - Otherwise: create new candidate with source="PRE_NEWS_V2"

        Returns dict with counts: {created, updated, skipped}
        """
        from src.core.agentic.models import (
            AgenticCandidate, CatalystInfo, CatalystType, ConfidenceLevel,
        )

        tracker = PreNewsValidationTracker()
        created = 0
        updated = 0
        skipped = 0

        for a in anomalies:
            ticker = a.ticker
            existing = self._candidates.get(ticker)

            # Dedup: skip if an Agentic candidate already exists from a different source
            if existing is not None:
                existing_source = (existing.catalyst.source or "").lower()
                if existing_source != "pre_news_v2":
                    skipped += 1
                    continue
                # Update path — refresh fields but preserve ID / discovered_at
                existing.updated_at = datetime.now(timezone.utc)
                existing.catalyst.strength_score = a.pre_news_suspicion_score
                existing.catalyst.headline = self._build_pre_news_headline(a)
                existing.last_price = a.price
                existing.final_probability = a.pre_news_suspicion_score
                existing.final_confidence = self._confidence_for_score(a.pre_news_suspicion_score)
                existing.alertable = (
                    a.pre_news_suspicion_score >= 75
                    and not a.late_detection_flag
                    and a.offering_risk_score < 60
                    and a.data_quality_state.value != "degraded"
                )
                if a.float_shares:
                    existing.float_intel.float_shares = a.float_shares
                if a.market_cap:
                    existing.float_intel.market_cap = a.market_cap
                updated += 1
                # ── Validation tracking ────────────────────────────────
                try:
                    tracker.record_handoff(a, existing, telegram_alert_sent=False)
                except Exception:
                    pass
                continue

            # Create new candidate
            try:
                cand = AgenticCandidate(ticker=ticker)
                cand.catalyst = CatalystInfo(
                    catalyst_type=CatalystType.OTHER,
                    headline=self._build_pre_news_headline(a),
                    source="PRE_NEWS_V2",
                    strength_score=a.pre_news_suspicion_score,
                    sentiment="bullish" if a.price_behaviour.vwap_distance_pct >= 0 else "neutral",
                )
                cand.last_price = a.price
                if a.float_shares:
                    cand.float_intel.float_shares = a.float_shares
                if a.market_cap:
                    cand.float_intel.market_cap = a.market_cap

                # Alertable gating — be conservative
                cand.alertable = (
                    a.pre_news_suspicion_score >= 75
                    and not a.late_detection_flag
                    and a.offering_risk_score < 60
                    and a.data_quality_state.value != "degraded"
                )
                cand.final_probability = a.pre_news_suspicion_score
                cand.final_confidence = self._confidence_for_score(a.pre_news_suspicion_score)

                # Populate minimal entry timing zones so _maybe_alert works
                cand.entry_timing.entry_zone_low = a.price * 0.98
                cand.entry_timing.entry_zone_high = a.price * 1.02
                cand.entry_timing.invalidation_level = a.price * 0.95

                self._candidates[ticker] = cand
                created += 1
                # ── Validation tracking ────────────────────────────────
                try:
                    tracker.record_handoff(a, cand, telegram_alert_sent=False)
                except Exception:
                    pass
            except Exception as e:
                logger.debug("handoff_from_pre_news: failed to create %s: %s", ticker, e)

        if created or updated:
            self._persist_state()
            logger.info(
                "PreNews V2 handoff: created=%d updated=%d skipped=%d (total candidates=%d)",
                created, updated, skipped, len(self._candidates),
            )

        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    def _build_pre_news_headline(a) -> str:
        """Build a V2-aware headline for the AgenticCandidate catalyst."""
        rvol = a.volume_metrics.rvol_current or 0
        sm = a.smart_money_score
        atype = a.anomaly_type.value
        parts = [
            f"[PRE-NEWS V2] {atype}",
            f"suspicion {a.pre_news_suspicion_score:.0f}",
            f"smart-money {sm:.0f}",
            f"RVOL {rvol:.1f}x",
            f"stage {a.timing_stage.value}",
        ]
        return " · ".join(parts)

    @staticmethod
    def _confidence_for_score(score: float) -> "ConfidenceLevel":
        from src.core.agentic.models import ConfidenceLevel
        if score >= 75:
            return ConfidenceLevel.HIGH
        if score >= 60:
            return ConfidenceLevel.WATCH
        return ConfidenceLevel.LOW

    def _resolve_confidence(self, cand: "AgenticCandidate") -> "ConfidenceLevel":
        """Map a candidate's final_probability + state to a ConfidenceLevel."""
        from src.core.agentic.models import ConfidenceLevel
        if getattr(cand, "rejected", False):
            return ConfidenceLevel.LOW
        return self._confidence_for_score(getattr(cand, "final_probability", 0) or 0)

    # ── Internal Pipeline ────────────────────────────────────────────────

    def _run_pipeline(self, cand: AgenticCandidate) -> AgenticCandidate:
        """Run all engines on a single candidate."""
        ticker = cand.ticker

        # Reset mutable state from prior runs so stale flags don't persist
        cand.rejected = False
        cand.rejection_reasons = []
        cand.alertable = False

        # Enrich float (expensive — only if not yet populated)
        if cand.float_intel.float_shares is None:
            cand = self.float_engine.enrich(cand)

        # Fetch fresh intraday bars
        bars = _fetch_intraday_bars(ticker)
        if not bars or len(bars) < 5:
            cand.rejected = True
            cand.rejection_reasons = ["No intraday data available"]
            cand.final_probability = 0
            cand.final_confidence = ConfidenceLevel.LOW
            return cand

        # Update price
        cand.last_price = bars[-1].close
        cand.last_volume = bars[-1].volume

        # Classify momentum state
        cand = self.momentum_engine.classify(cand, bars)

        # V18 ABCD Pattern Confirmation Layer
        cand.abcd = self.abcd_engine.analyze(cand, bars)
        if cand.abcd.abcd_state not in (ABCDState.NO_PATTERN, ABCDState.BASE_FORMING, ABCDState.FAILED_PATTERN):
            cand.rejection_reasons.append(
                f"ABCD: {cand.abcd.abcd_state.value} (score={cand.abcd.abcd_score}, phase={cand.abcd.abcd_phase.value})"
            )

        # Failure velocity
        cand = self.fv_engine.analyze(cand, bars)

        # Second-leg probability
        cand = self.second_leg_engine.compute(cand)

        # Trap detection
        cand = self.trap_engine.analyze(cand, bars)

        # Time of day adjustment
        cand = self.tod_engine.classify(cand)

        # Entry timing — V17 five-state engine
        cand = self.entry_engine.classify(cand, bars)

        # ── Final probability composition ────────────────────────────────
        prob = cand.second_leg.probability

        # Apply time-of-day adjustment (already calibrated by TimeOfDayEngine)
        prob += cand.time_of_day.probability_adjustment

        # Trap risk penalty (already calibrated by TrapDetector)
        trap_threshold = 65
        trap_warn_threshold = 40
        if cand.trap.trap_risk_score >= trap_threshold:
            prob *= 0.4
            cand.rejection_reasons.append(f"Trap risk {cand.trap.trap_risk_score:.0f}%")
        elif cand.trap.trap_risk_score >= trap_warn_threshold:
            prob *= 0.7

        # Failure velocity penalty
        if cand.failure_velocity.is_distribution:
            prob *= 0.5
            cand.rejection_reasons.append("Distribution detected")

        prob = round(max(0, min(100, prob)), 1)
        cand.final_probability = prob

        # ── 1. Hard Rejection Rules ─────────────────────────────────────
        hard_result = self.hard_rejection_engine.evaluate(cand)
        from src.core.agentic.models import HardRejectionTriggerModel, HardRejectionResultModel
        cand.hard_rejection = HardRejectionResultModel(
            triggered=hard_result.triggered,
            triggers=[
                HardRejectionTriggerModel(rule=t.rule.value, description=t.description)
                for t in hard_result.triggers
            ],
            rejection_reasons=hard_result.rejection_reasons,
        )
        if hard_result.triggered:
            cand.rejected = True
            cand.rejection_reasons.extend(hard_result.rejection_reasons)
            cand.alertable = False
            cand.final_confidence = self._resolve_confidence(cand)
            cand.updated_at = datetime.now(timezone.utc)
            return cand

        # ── 2. Quality Separator Layer ──────────────────────────────────
        qs_result = self.quality_engine.evaluate(cand, prob)
        cand.quality_separator = qs_result

        # Apply quality adjustment
        prob_after_quality = prob + qs_result.quality_adjustment
        prob_after_quality = round(max(0, min(100, prob_after_quality)), 1)

        # ── 3. Asymmetric Scoring Layer ────────────────────────────────
        asym_result = self.asymmetric_engine.score(cand, base_probability=prob_after_quality)
        from src.core.agentic.models import ScoreAdjustmentModel, AsymmetricScoringResultModel
        cand.asymmetric_scoring = AsymmetricScoringResultModel(
            penalties=[
                ScoreAdjustmentModel(name=p.name, value=p.value, reason=p.reason)
                for p in asym_result.penalties
            ],
            boosts=[
                ScoreAdjustmentModel(name=b.name, value=b.value, reason=b.reason)
                for b in asym_result.boosts
            ],
            raw_penalty_sum=asym_result.raw_penalty_sum,
            raw_boost_sum=asym_result.raw_boost_sum,
            final_penalty=asym_result.final_penalty,
            final_boost=asym_result.final_boost,
            final_adjustment=asym_result.final_adjustment,
            base_probability=asym_result.base_probability,
            final_probability=asym_result.final_probability,
        )
        cand.final_probability = asym_result.final_probability

        # Calibration status flag
        if self._calibration_weights:
            cand.rejection_reasons.append(f"Calibrated v{self._calibration_weights.version}")
        else:
            cand.rejection_reasons.append("Uncalibrated")

        # Quality separator logging
        if qs_result.data_sufficient:
            logger.debug(
                "QualitySep %s: base=%.1f → final=%.1f (%s adj=%.1f) q=%.0f w=%.0f l=%.0f",
                cand.ticker, prob, cand.final_probability,
                qs_result.quality_decision, qs_result.quality_adjustment,
                qs_result.quality_separator_score,
                qs_result.winner_similarity_score,
                qs_result.loser_similarity_score,
            )

        # ── V19.1 Market Regime ──────────────────────────────────────
        # Attach SPY trend, VIX, sector RSI for ML feature population
        try:
            apply_regime_to_candidate(cand)
        except Exception as e:
            logger.warning("Market regime failed for %s: %s", cand.ticker, e)

        # ── V19.1 Pre-News Bridge ────────────────────────────────────
        # Adjust trap/catalyst if pre-news anomaly detected for this ticker
        try:
            apply_pre_news_to_candidate(cand)
        except Exception as e:
            logger.warning("Pre-news bridge failed for %s: %s", cand.ticker, e)

        # ── V20 News Catalyst Impact Engine ──────────────────────────
        # Classify catalyst, score impact, generate bull/bear case explanations.
        # Advisory only — does NOT auto-trigger trades.
        try:
            self._evaluate_news_impact(cand)
        except Exception as e:
            logger.warning("News impact engine failed for %s: %s", cand.ticker, e)

        # ── V19 ML Advisory Layer ─────────────────────────────────────
        # Generate ML prediction for advisory use (does NOT gate alerts)
        try:
            cand.ml_prediction = self.learning.predict_ml(cand)
        except Exception as e:
            logger.warning("ML prediction failed for %s: %s", cand.ticker, e)

        # ── Confidence resolution ───────────────────────────────────────
        cand.final_confidence = self._resolve_confidence(cand)

        # Alertable decision
        # V18: ABCD acts as confirmation filter, not a standalone signal
        abcd_confirmed = cand.abcd.abcd_state in (
            ABCDState.RETEST_CONFIRMED, ABCDState.CONTINUATION_READY
        )

        cand.alertable = (
            cand.final_probability >= 70
            and cand.entry_timing.quality == EntryQuality.IDEAL
            and cand.trap.trap_risk_score < 65
            and not cand.failure_velocity.is_distribution
            and cand.momentum.state not in (MomentumState.DEAD, MomentumState.FAILED)
            and qs_result.quality_decision != "block"
            and not hard_result.triggered
            and abcd_confirmed
        )

        cand.updated_at = datetime.now(timezone.utc)
        return cand

    # ── V20 News Catalyst Impact Engine ──────────────────────────────────

    def _evaluate_news_impact(self, cand: AgenticCandidate) -> None:
        """Run the V20 News Catalyst Impact Engine for a candidate.

        Populates `cand.news_impact` with classification, score, decision,
        estimated move range and explanations. Optionally fires a Telegram
        alert (high-impact) or trap-warning alert (DANGEROUS_TRAP).

        Advisory only — does NOT change `cand.alertable` or `cand.final_probability`.
        """
        from src.core.agentic.models import NewsImpactModel, EstimatedMoveRangeModel

        if not cand.catalyst.headline:
            # No headline → nothing to evaluate
            cand.news_impact = NewsImpactModel(has_evaluation=False)
            return

        result = self.news_impact_engine.evaluate_for_candidate(cand)
        cand.news_impact = NewsImpactModel(
            has_evaluation=True,
            catalyst_type=result.catalyst_type.value,
            catalyst_tier=result.catalyst_tier,
            news_impact_score=result.news_impact_score,
            news_decision=result.news_decision.value,
            oracle_action=result.oracle_action.value,
            component_scores=result.component_scores,
            estimated_move_range=EstimatedMoveRangeModel(
                conservative_move_pct=result.estimated_move_range.conservative_move_pct,
                bullish_move_pct=result.estimated_move_range.bullish_move_pct,
                extreme_squeeze_pct=result.estimated_move_range.extreme_squeeze_pct,
                bearish_move_pct=result.estimated_move_range.bearish_move_pct,
                rationale=result.estimated_move_range.rationale,
            ),
            is_dilution=result.is_dilution,
            is_parabolic=result.is_parabolic,
            is_unconfirmed=result.is_unconfirmed,
            trap_warning=result.trap_warning,
            trap_reasons=result.trap_reasons,
            pre_news_accumulation_detected=result.pre_news_accumulation_detected,
            pre_news_suspicion_score=result.pre_news_suspicion_score,
            news_summary=result.news_summary,
            why_it_matters=result.why_it_matters,
            bull_case=result.bull_case,
            bear_case=result.bear_case,
            key_risks=result.key_risks,
            impact_reasons=result.impact_reasons,
            impact_warnings=result.impact_warnings,
            sector_hype_multiplier=result.sector_hype_multiplier,
            rvol_at_detection=result.rvol_at_detection,
            pre_news_runup_pct=result.pre_news_runup_pct,
            market_cap_at_detection=result.market_cap_at_detection,
            float_shares_at_detection=result.float_shares_at_detection,
        )

        # Persist to learning loop (price-at-detection snapshot)
        try:
            if self.news_impact_learning is not None:
                self.news_impact_learning.record(result, price_at_detection=cand.last_price)
        except Exception as exc:
            logger.debug("News impact learning record failed: %s", exc)

        # Send Telegram alerts (advisory only)
        try:
            self._maybe_news_impact_alert(cand, result)
        except Exception as exc:
            logger.debug("News impact telegram alert failed: %s", exc)

    def _maybe_news_impact_alert(self, cand: AgenticCandidate, result) -> None:
        """Fire Telegram alert for high-impact news or dangerous trap.

        Cooldown: 30 minutes per ticker per alert kind.
        """
        from src.core.agentic.news_impact_engine import NewsDecision as ND

        decision = result.news_decision
        score = result.news_impact_score
        ticker = cand.ticker

        # Cooldown
        now = datetime.now(timezone.utc)
        last = self._news_impact_alert_cooldowns.get(ticker)
        if last and (now - last).total_seconds() < 1800:
            return

        # Trap warning
        if decision == ND.DANGEROUS_TRAP and (result.trap_warning or result.is_dilution or result.is_parabolic):
            msg = self._format_trap_alert(cand, result)
            self._send_telegram(msg)
            self._news_impact_alert_cooldowns[ticker] = now
            return

        # High-impact alert gate
        if score < 70:
            return
        if decision not in (ND.TRADEABLE, ND.HIGH_IMPACT, ND.EXPLOSIVE):
            return
        # Trap risk acceptable from agentic side
        if cand.trap.trap_risk_score >= 65:
            return
        # Entry timing not late chase
        if cand.entry_timing.timing_state.value == "late_chase":
            return
        # Dilution / offering risk not severe
        if result.is_dilution:
            return
        # Volume confirms (RVOL >= 2 if available)
        if result.rvol_at_detection > 0 and result.rvol_at_detection < 2.0:
            return

        msg = self._format_news_impact_alert(cand, result)
        self._send_telegram(msg)
        self._news_impact_alert_cooldowns[ticker] = now

    def _format_news_impact_alert(self, cand: AgenticCandidate, result) -> str:
        """Build the high-impact news Telegram message (V20 spec)."""
        em = result.estimated_move_range
        move_str = f"+{em.conservative_move_pct:.0f}% / +{em.bullish_move_pct:.0f}% / +{em.extreme_squeeze_pct:.0f}%"
        float_str = f"{result.float_shares_at_detection/1e6:.1f}M" if result.float_shares_at_detection else "N/A"
        cap_str = f"${result.market_cap_at_detection/1e6:.0f}M" if result.market_cap_at_detection else "N/A"

        ml_size = cand.ml_prediction.suggested_position_size or "NONE"
        et_state = cand.entry_timing.timing_state.value if cand.entry_timing else "n/a"
        abcd_state = cand.abcd.abcd_state.value if cand.abcd else "n/a"

        lines = [
            f"🔥 HIGH IMPACT NEWS — {cand.ticker}",
            "",
            f"Ticker: {cand.ticker}",
            f"Headline: {(cand.catalyst.headline or '')[:200]}",
            f"News Type: {result.catalyst_type.value}",
            f"News Decision: {result.news_decision.value}",
            f"News Impact Score: {result.news_impact_score:.0f}/100",
            f"Estimated Move Range: {move_str} (cons / bull / extreme)",
            f"Pre-News Accumulation: {'YES' if result.pre_news_accumulation_detected else 'NO'}",
            f"Current RVOL: {result.rvol_at_detection:.1f}x",
            f"Float: {float_str}",
            f"Market Cap: {cap_str}",
            f"Entry Timing: {et_state}",
            f"ABCD State: {abcd_state}",
            f"ML Position Size: {ml_size}",
            f"Oracle Action: {result.oracle_action.value}",
            "",
            f"Catalyst Summary: {result.news_summary}",
            f"Why It Matters: {result.why_it_matters}",
            f"Bull Case: {result.bull_case}",
            f"Bear Case: {result.bear_case}",
        ]
        if result.key_risks:
            lines.append(f"Key Risks: {', '.join(result.key_risks)}")
        if result.impact_reasons:
            lines.append(f"Impact Reasons: {'; '.join(result.impact_reasons)}")
        if result.impact_warnings:
            lines.append(f"Impact Warnings: {'; '.join(result.impact_warnings)}")
        return "\n".join(lines)

    def _format_trap_alert(self, cand: AgenticCandidate, result) -> str:
        """Build the trap-warning Telegram message (V20 spec)."""
        reasons = list(result.trap_reasons)
        if not reasons:
            if result.is_dilution:
                reasons.append("offering / warrant filing")
            if result.is_parabolic:
                reasons.append(f"parabolic exhaustion (+{result.pre_news_runup_pct:.0f}%)")

        # Ticker on watchlist or active candidate is more urgent
        on_watch_note = ""
        try:
            existing = self._candidates.get(cand.ticker)
            if existing and existing.active:
                on_watch_note = " (active Agentic candidate)"
        except Exception:
            pass

        lines = [
            f"⚠️ DANGEROUS TRAP DETECTED — {cand.ticker}{on_watch_note}",
            "",
            f"Headline: {(cand.catalyst.headline or '')[:200]}",
            f"News Type: {result.catalyst_type.value}",
            f"Score: {result.news_impact_score:.0f}/100",
            "",
            "Reason:",
        ]
        for r in reasons[:5]:
            lines.append(f"  • {r}")
        lines.append("")
        lines.append("Oracle Recommendation:")
        lines.append(f"  {result.oracle_action.value}")
        return "\n".join(lines)

    def _send_telegram(self, message: str) -> None:
        """Best-effort sync Telegram send; swallows errors."""
        try:
            from src.services.telegram_service import send_telegram_alert_sync
            send_telegram_alert_sync(message, parse_mode="HTML")
        except Exception as exc:
            logger.debug("Telegram send failed: %s", exc)

    # ── Alert Generation ─────────────────────────────────────────────────

    def _maybe_alert(self, cand: AgenticCandidate):
        """Send Telegram alert if candidate is alertable and not in cooldown."""
        if not cand.alertable:
            return
        # Check cooldown
        now = datetime.now(timezone.utc)
        last_alert = self._alert_cooldowns.get(cand.ticker)
        if last_alert and (now - last_alert).total_seconds() < 300:
            return

        et = cand.entry_timing
        state = et.timing_state
        # Emoji prefix based on timing state
        emoji_map = {
            "too_early": "⏳",
            "waiting_for_confirmation": "👁",
            "ideal_entry": "🎯",
            "late_chase": "🚫",
            "invalid_entry": "❌",
        }
        emoji = emoji_map.get(state.value, "📊")
        alert_type = state.value

        # Build headline with V17 fields
        headline_parts = [
            f"{emoji} {cand.ticker} | Probability {cand.final_probability:.1f}%",
            f"Timing: {state.value.upper().replace('_', ' ')}",
            f"Score: {et.entry_timing_score}/100",
        ]

        if et.entry_zone_low and et.entry_zone_high:
            headline_parts.append(f"Zone ${et.entry_zone_low:.2f}–${et.entry_zone_high:.2f}")
        if et.risk_reward_ratio and et.risk_reward_ratio > 0:
            headline_parts.append(f"R:R {et.risk_reward_ratio:.1f}:1")

        headline = " | ".join(headline_parts)

        # Build detail lines
        reasons = list(et.reasons)
        warnings = list(et.entry_warnings)
        next_cond = et.next_entry_condition

        # V18 ABCD details
        abcd = cand.abcd
        reasons.append(
            f"ABCD {abcd.abcd_phase.value}: {abcd.abcd_state.value.replace('_', ' ')} (score {abcd.abcd_score})"
        )
        if abcd.abcd_key_level:
            reasons.append(f"Key level: ${abcd.abcd_key_level:.2f}")
        if abcd.abcd_retest_level:
            reasons.append(f"Retest level: ${abcd.abcd_retest_level:.2f}")
        if abcd.abcd_invalidation_level:
            reasons.append(f"Invalidation: ${abcd.abcd_invalidation_level:.2f}")
        for r in abcd.abcd_reasons[:3]:
            reasons.append(r)
        for w in abcd.abcd_warnings[:2]:
            warnings.append(w)

        if et.stop_level and et.target_1:
            reasons.append(f"Stop ${et.stop_level:.2f} → Target 1 ${et.target_1:.2f}")
        if et.target_2:
            reasons.append(f"Target 2 ${et.target_2:.2f}")
        if et.stretch_target:
            reasons.append(f"Stretch ${et.stretch_target:.2f}")

        if next_cond:
            reasons.append(f"Next: {next_cond}")
        if warnings:
            reasons.append(f"Warnings: {', '.join(warnings)}")

        alert = AgenticAlert(
            ticker=cand.ticker,
            alert_type=alert_type,
            timing_state=state.value,
            timing_score=et.entry_timing_score,
            headline=headline,
            probability=cand.final_probability,
            entry_zone_low=et.entry_zone_low,
            entry_zone_high=et.entry_zone_high,
            ideal_entry_price=et.ideal_entry_price,
            invalidation_level=et.invalidation_level,
            stop_level=et.stop_level,
            target_1=et.target_1,
            target_2=et.target_2,
            stretch_target=et.stretch_target,
            risk_reward_ratio=et.risk_reward_ratio,
            next_entry_condition=next_cond,
            warnings=warnings,
            reasons=reasons,
        )
        self._alerts.append(alert)
        self._alert_cooldowns[cand.ticker] = now
        try:
            send_telegram_alert_sync(alert.headline + "\n" + "\n".join(reasons))
        except Exception as e:
            logger.error("Telegram alert failed: %s", e)

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist_state(self):
        """Save current candidates and alerts to disk for crash recovery."""
        cand_path = os.path.join(DATA_DIR, "candidates.json")
        alert_path = os.path.join(DATA_DIR, "alerts.json")

        cand_data = {t: c.model_dump(mode="json") for t, c in self._candidates.items()}
        # Defensive: _alerts may not exist if instance was created via __new__ (e.g. in tests)
        alerts = getattr(self, "_alerts", [])
        alert_data = [a.model_dump(mode="json") for a in alerts[-100:]]  # Keep last 100

        save_json_file(cand_path, cand_data)
        save_json_file(alert_path, alert_data)

    def load_state(self):
        """Load persisted state from disk."""
        cand_path = os.path.join(DATA_DIR, "candidates.json")
        alert_path = os.path.join(DATA_DIR, "alerts.json")

        cand_data = load_json_file(cand_path, default={})
        for ticker, cand_dict in cand_data.items():
            try:
                self._candidates[ticker] = AgenticCandidate.model_validate(cand_dict)
            except Exception:
                pass
        if self._candidates:
            logger.info("Loaded %d persisted agentic candidates", len(self._candidates))

        alert_data = load_json_file(alert_path, default=[])
        for alert_dict in alert_data:
            try:
                self._alerts.append(AgenticAlert.model_validate(alert_dict))
            except Exception:
                pass
