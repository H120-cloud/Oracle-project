"""
News Momentum Orchestrator (V22)

Wires together:
- Catalyst classification
- News impact scoring
- News reaction tracking
- Expected return ML ranking
- Continuation probability
- Multi-day continuation
- Adaptive Telegram learning
- Catalyst learning
- Telegram alerts

Runs as a background scan loop in main.py.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import html
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsMomentumScanResult,
    NewsEvent,
    NewsVelocity,
    SessionType,
    PriceBucket,
    FloatCategory,
    MarketCapCategory,
    OracleAction,
    TelegramAlertRecord,
    MultiDayClass,
    NewsSource,
    CatalystSubType,
    CatalystCategory,
)
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.bullish_catalyst_flash import assess_bullish_flash
from src.core.agentic.news_momentum_impact_scorer import score_news_impact
from src.core.agentic.news_momentum_reaction_engine import (
    compute_reaction_metrics,
    score_news_reaction,
)
from src.core.agentic.news_momentum_expected_return_engine import compute_expected_return_score
from src.core.agentic.news_momentum_continuation_engine import (
    compute_continuation_probability,
    compute_multi_day_continuation,
    determine_oracle_action,
    estimate_move_range,
)
from src.core.agentic.news_momentum_telegram_learning import AdaptiveTelegramLearning
from src.core.agentic.news_momentum_catalyst_learning import CatalystLearningEngine
from src.utils.atomic_json import save_json_file, load_json_file
from src.services.telegram_service import send_telegram_alert
from src.core.agentic.news_momentum_missed_learning import MissedCatalystLearningEngine
from src.core.agentic.news_momentum_ml_engine import NewsMomentumMLEngine, MLPrediction
from src.core.agentic.news_momentum_winners import (
    SectorHypeTracker,
    assess_winner,
    headline_strength_score,
    set_ml_percentile_bands,
)
from src.core.agentic.news_momentum_big_winner_model import BigWinnerMLEngine
from src.core.agentic.news_momentum_unknown_learner import UnknownCatalystLearner
from src.core.agentic.sec_intelligence_orchestrator import (
    SECIntelligenceOrchestrator,
    compute_adjustment as _sec_compute_adjustment,
)
from src.core.agentic.sec_filing_models import (
    SECIntelligenceCandidate as _SECCandidate,
)
from src.core.agentic.news_alert_latency_trace import trace_candidate

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
CANDIDATES_FILE = DATA_DIR / "news_momentum_candidates.json"

# Catalyst sub-types historically printing > 40% win rate. Used both by the
# Telegram gate (high-conviction threshold relaxation) and by the stacking
# score (one of the signals counted toward concurrent positives).
_HIGH_CONVICTION_CATALYSTS = frozenset({
    CatalystSubType.PHASE_1, CatalystSubType.PHASE_2, CatalystSubType.PHASE_3,
    CatalystSubType.FDA_APPROVAL, CatalystSubType.FDA_CLEARANCE,
    CatalystSubType.PDUFA, CatalystSubType.BREAKTHROUGH_THERAPY,
    CatalystSubType.FAST_TRACK, CatalystSubType.ORPHAN_DRUG,
    CatalystSubType.TOPLINE_DATA, CatalystSubType.SNDA_SUBMISSION,
    CatalystSubType.NDA_APPROVAL, CatalystSubType.LABEL_EXPANSION,
    CatalystSubType.DRUG_LAUNCH, CatalystSubType.COMMERCIALIZATION,
    CatalystSubType.GOVERNMENT_CONTRACT, CatalystSubType.STRATEGIC_REVIEW,
    CatalystSubType.AI_PARTNERSHIP, CatalystSubType.NVIDIA_PARTNERSHIP,
    CatalystSubType.OPENAI_PARTNERSHIP, CatalystSubType.HYPERSCALER_CONTRACT,
    CatalystSubType.NEW_PRODUCT_LAUNCH, CatalystSubType.PRODUCT_UPGRADE,
    CatalystSubType.PLATFORM_EXPANSION, CatalystSubType.BITCOIN_TREASURY,
    CatalystSubType.SHARE_BUYBACK, CatalystSubType.MAJOR_PARTNERSHIP,
    CatalystSubType.SUPPLY_AGREEMENT, CatalystSubType.OEM_PARTNERSHIP,
    CatalystSubType.SPIN_OFF, CatalystSubType.JOINT_VENTURE,
    # M&A — among the most reliable big-mover catalysts; previously omitted,
    # which let OLOX (acquisition, impact 57.3) miss the alert by 0.1 points
    # because it got no high-conviction threshold relaxation.
    CatalystSubType.MERGER, CatalystSubType.ACQUISITION, CatalystSubType.BUYOUT,
    CatalystSubType.ANALYST_UPGRADE, CatalystSubType.TARIFF_EXEMPTION,
    CatalystSubType.TRADE_DEAL, CatalystSubType.SUBSIDY_AWARD,
    CatalystSubType.WARRANT_OVERHANG_REMOVAL, CatalystSubType.LISTING_COMPLIANCE,
    CatalystSubType.GUIDANCE_RAISE, CatalystSubType.PROFITABILITY_INFLECTION,
    CatalystSubType.EARNINGS_BEAT, CatalystSubType.DIVIDEND_INCREASE,
    CatalystSubType.STOCK_SPLIT_FORWARD, CatalystSubType.CREDIT_UPGRADE,
    CatalystSubType.FINANCING_POSITIVE, CatalystSubType.DEBT_RESTRUCTURING,
    CatalystSubType.EV_BATTERY,
    CatalystSubType.RENEWABLE_ENERGY,
})

_FAST_PATH_VERIFIED_SOURCES = frozenset({
    NewsSource.STOCKTITAN,
    NewsSource.ALPACA,
    NewsSource.SEC,
    NewsSource.GLOBE_NEWSWIRE,
    NewsSource.BUSINESS_WIRE,
    NewsSource.PR_NEWSWIRE,
    NewsSource.ACCESSWIRE,
    NewsSource.NEWSFILE,
    NewsSource.COMPANY_PRESS,
    NewsSource.FINVIZ,
})

_FAST_PATH_HIGH_IMPACT_CATALYSTS = frozenset({
    CatalystSubType.FDA_APPROVAL,
    CatalystSubType.FDA_CLEARANCE,
    CatalystSubType.NDA_APPROVAL,
    CatalystSubType.PDUFA,
    CatalystSubType.TOPLINE_DATA,
    CatalystSubType.PHASE_2,
    CatalystSubType.PHASE_3,
    CatalystSubType.MERGER,
    CatalystSubType.ACQUISITION,
    CatalystSubType.BUYOUT,
    CatalystSubType.GOVERNMENT_CONTRACT,
    CatalystSubType.HYPERSCALER_CONTRACT,
    CatalystSubType.SUPPLY_AGREEMENT,
    CatalystSubType.OEM_PARTNERSHIP,
    CatalystSubType.INFRASTRUCTURE_AGREEMENT,
    CatalystSubType.MAJOR_PARTNERSHIP,
    CatalystSubType.AI_PARTNERSHIP,
    CatalystSubType.NVIDIA_PARTNERSHIP,
    CatalystSubType.OPENAI_PARTNERSHIP,
    CatalystSubType.EARNINGS_BEAT,
    CatalystSubType.GUIDANCE_RAISE,
    CatalystSubType.PROFITABILITY_INFLECTION,
    CatalystSubType.LISTING_COMPLIANCE,
    CatalystSubType.WARRANT_OVERHANG_REMOVAL,
    CatalystSubType.FINANCING_POSITIVE,
    CatalystSubType.DEBT_RESTRUCTURING,
})


# Headline language used by the first-mover speed tier (and the no-price
# bypass). Module-level so both paths share one source of truth.
_STRONG_POSITIVE_KW = (
    "approves", "approval", "approved", "wins", "won", "secures",
    "secured", "awarded", "awards", "signs", "signed", "launches",
    "launched", "completes", "completed", "selected",
    "selects", "chosen", "exclusive", "breakthrough", "first-in-class",
    "milestone", "acquires", "acquired", "merger", "acquisition",
    "partnership", "collaboration", "agreement", "contract",
    "raises guidance", "beat", "exceeds", "record", "all-time",
    "fda", "phase 3", "phase 1", "phase 2", "clearance",
    "patent", "buyback", "dividend increase", "spinoff",
    "raises", "raised", "raise", "upgrade", "upgraded", "upgrades",
    "price target", "strong buy", "outperform", "overweight",
    "buy rating", "flash report", "initiates coverage",
    "sales growth", "revenue growth", "profit growth",
    "double digit", "double-digit", "record sales", "record revenue",
    "launches new", "new product", "product launch",
    "award", "strategic reset", "strategic review", "strategic plan",
    "cashless warrant", "warrant redemption", "regains compliance",
    "regain compliance", "nasdaq compliance", "listing compliance",
    "purchase order", "orphan drug", "fast track",
)
_HARD_NEGATIVE_KW = (
    "offering", "dilution", "downgrade", "lawsuit", "investigation",
    "subpoena", "delisting", "bankruptcy", "going concern", "fraud",
    "halts", "halted", "withdraws", "withdrawn", "terminates",
    "terminated", "misses", "missed", "decline", "declines",
    "falls", "down", "loss", "losses", "warning", "guides down",
    "minimum bid", "deficiency notice", "non-compliance", "noncompliance",
)
_RETROSPECTIVE_MOVE_RE = re.compile(
    r"("
    r"\b(?:[A-Z]{1,6}\s+)?(shares?|stock)\s+"
    r"(surges?|soars?|jumps?|rall(?:y|ies)|gains?|rises?|climbs?|advances?)\b"
    r"|"
    r"\b(surges?|soars?|jumps?|rall(?:y|ies)|gains?|rises?|climbs?|advances?)\s+"
    r"(after|as|on|following)\b"
    r"|"
    r"\bdrives?\s+(?:\d+(?:\.\d+)?%\s+)?[A-Z]{1,6}\s+"
    r"(?:surge|rally|jump|gain|rise|climb|advance)\b"
    r"|"
    r"\b(?:\d+(?:\.\d+)?%)\s+[A-Z]{1,6}\s+"
    r"(?:surge|rally|jump|gain|rise|climb|advance)\b"
    r")",
    re.IGNORECASE,
)


def _headline_is_fresh_bullish(headline: str, is_negative: bool,
                               trap_risk: float, dilution_risk: float) -> bool:
    """True if a headline looks like a fresh, strongly-positive catalyst with no
    hard-negative language and acceptable risk. Price-independent — used to let
    speed-tier candidates through even before a live quote is available."""
    hl = (headline or "").lower()
    if not hl:
        return False
    if any(kw in hl for kw in _HARD_NEGATIVE_KW):
        return False
    if not any(kw in hl for kw in _STRONG_POSITIVE_KW):
        return False
    return (not is_negative) and (trap_risk or 0.0) < 70.0 and (dilution_risk or 0.0) < 70.0


def _is_late_reaction_headline(headline: str) -> bool:
    """True when the headline is mainly reporting a move that already happened."""
    return bool(_RETROSPECTIVE_MOVE_RE.search(headline or ""))


def _compute_stacking_score(c) -> tuple[int, list]:
    """Count concurrent positive signals firing on a candidate.

    Rocket-class moves historically need MULTIPLE positive signals firing
    in concert — single strong signals are common but mostly produce noise.
    This count is used as (a) a secondary ranker after BigWinner probability
    and (b) a tiebreaker among candidates with similar BigWinner scores.

    Returns ``(count, [signal_names])`` so the gate log can show why a
    candidate ranked where it did.
    """
    fired: list = []
    # Score signals — each contributes 1 point when its threshold is cleared
    if c.news_impact_score >= 70:
        fired.append("impact>=70")
    if c.expected_return_score >= 60:
        fired.append("return>=60")
    if c.continuation_probability >= 60:
        fired.append("cont>=60")
    if c.multi_day_continuation_score >= 60:
        fired.append("multi_day>=60")
    # Catalyst signals
    if c.catalyst_sub_type in _HIGH_CONVICTION_CATALYSTS and not c.is_negative:
        fired.append("high_conviction_catalyst")
    if (c.sources_seen_count or 1) >= 2:
        fired.append("multi_source")
    if c.velocity_score and c.velocity_score >= 5:
        fired.append("fast_velocity")
    # Market-data signals
    if c.rvol is not None and c.rvol >= 3.0:
        fired.append("rvol>=3x")
    if c.float_category in (FloatCategory.LOW, FloatCategory.ULTRA_LOW):
        fired.append("low_float")
    # Risk-clean signals (absence of structural overhang is a positive)
    if c.dilution_risk <= 30 and c.trap_risk <= 30:
        fired.append("risk_clean")
    if not c.is_negative and not c.is_vague:
        fired.append("clean_headline")
    # Model signals
    bw_prob = getattr(c, "_big_winner_probability", None) or 0.0
    if bw_prob >= 0.50:
        fired.append("big_winner_model>=0.5")
    ml_pred = getattr(c, "_ml_prediction", None)
    if ml_pred is not None and getattr(ml_pred, "win_probability", 0) >= 0.50:
        fired.append("ml_win>=0.5")
    return (len(fired), fired)
CONFIG_FILE = DATA_DIR / "news_momentum_config.json"
COOLDOWN_FILE = DATA_DIR / "news_momentum_cooldowns.json"
HEADLINE_COOLDOWN_FILE = DATA_DIR / "news_momentum_headline_cooldowns.json"
EVENT_REGISTRY_FILE = DATA_DIR / "news_momentum_event_registry.json"
ALERT_MEMORY_FILE = DATA_DIR / "news_momentum_alert_memory.json"


def _aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class NewsMomentumOrchestrator:
    """Main controller for the news momentum intelligence system."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
        self._candidates: List[NewsMomentumCandidate] = []
        self._candidate_by_ticker: Dict[str, NewsMomentumCandidate] = {}
        self._alert_cooldown: Dict[str, datetime] = {}
        # Persistent cooldown by (ticker, headline_hash) to prevent re-alerting
        # on the same news event even if event_registry expires. Lives 4 hours.
        self._headline_alert_cooldown: Dict[str, datetime] = {}
        self._alert_memory: Dict[str, dict] = {}
        self._telegram_learning = AdaptiveTelegramLearning()
        from src.core.agentic.news_momentum_shadow_logger import ShadowAlertLogger
        self._shadow_logger = ShadowAlertLogger()
        self._catalyst_learning = CatalystLearningEngine()
        self._missed_learning = MissedCatalystLearningEngine(self.config)
        self._scan_counter = 0
        self._lock = asyncio.Lock()
        self._load_candidates()
        self._load_cooldowns()
        self._load_headline_cooldowns()
        self._load_alert_memory()
        self._hydrate_cooldowns_from_alert_history()
        # Track events for cross-source velocity and duplicate detection
        self._event_registry: Dict[str, NewsEvent] = {}
        self._load_event_registry()
        self._prune_old_candidates()
        # EOD reviewer (lazy-init to avoid circular import at module load)
        self._eod_reviewer = None
        # ML engine — self-training scorer for alert quality
        self._ml_engine = NewsMomentumMLEngine()
        try:
            self._ml_engine.load()
        except Exception as exc:
            logger.warning("NewsMomentum: ML engine load failed: %s", exc)
        # Unknown-catalyst auto-learner (V23.2) — flags missed patterns
        try:
            self._unknown_learner = UnknownCatalystLearner()
        except Exception as exc:
            logger.warning("NewsMomentum: UnknownLearner init failed: %s", exc)
            self._unknown_learner = None
        # Big-Winner ML — dedicated rocket (>25% move) classifier (V23.1)
        self._big_winner_ml = BigWinnerMLEngine()
        try:
            self._big_winner_ml.load()
        except Exception as exc:
            logger.warning("NewsMomentum: BigWinner ML load failed: %s", exc)
        # Calibrate percentile bands for the main ML model from historical
        # predictions. Falls back to safe defaults if calibration fails.
        try:
            self._calibrate_ml_percentiles()
        except Exception as exc:
            logger.warning("NewsMomentum: ML percentile calibration failed: %s", exc)
        # Outcome resolver (lazy-init)
        self._outcome_resolver = None
        # Sector hype tracker — boosts hot sectors, dampens cold ones
        try:
            self._sector_hype = SectorHypeTracker()
        except Exception as exc:
            logger.warning("NewsMomentum: SectorHypeTracker init failed: %s", exc)
            self._sector_hype = None
        # SEC Filing Intelligence Engine (V23)
        try:
            self._sec_intel = SECIntelligenceOrchestrator()
        except Exception as exc:
            logger.warning("NewsMomentum: SEC intelligence init failed: %s", exc)
            self._sec_intel = None
        # Offline Rocket CatBoost shadow scorer. This is append-only telemetry
        # and must never feed Telegram gating, alert ranking, or trade logic.
        try:
            from src.core.agentic.rocket_model_shadow import RocketModelShadowScorer
            self._rocket_shadow_scorer = RocketModelShadowScorer()
        except Exception as exc:
            logger.warning("NewsMomentum: Rocket shadow scorer init failed: %s", exc)
            self._rocket_shadow_scorer = None
        self._polygon_provider = None

    def _get_polygon_provider(self):
        """Lazy Polygon provider for fast quote fallback without losing cache."""
        if self._polygon_provider is not None:
            return self._polygon_provider
        from src.config import get_settings
        settings = get_settings()
        if not settings.polygon_api_key:
            return None
        from src.services.polygon_provider import PolygonProvider
        self._polygon_provider = PolygonProvider(api_key=settings.polygon_api_key)
        return self._polygon_provider

    def _calibrate_ml_percentiles(self) -> None:
        """
        Run the trained ML model over recent resolved alerts to compute
        p15/p50/p85 probability cutoffs. These are then used by the winner
        layer to bucket alerts into percentile-based tiers instead of
        absolute probabilities (which never exceed ~30% on a 5% base rate).
        """
        if self._ml_engine._model is None:
            return
        try:
            import numpy as np
            recent = [a for a in self._telegram_learning._alerts if a.outcome is not None]
            recent = recent[-2000:] if len(recent) > 2000 else recent
            if len(recent) < 100:
                logger.info("NewsMomentum: not enough resolved alerts for ML percentile calibration (have %d)", len(recent))
                return
            probs = []
            for a in recent:
                try:
                    p = self._ml_engine.predict(a).win_probability
                    probs.append(p)
                except Exception:
                    continue
            if len(probs) < 50:
                return
            p85 = float(np.percentile(probs, 85))
            p95 = float(np.percentile(probs, 95))
            p99 = float(np.percentile(probs, 99))
            set_ml_percentile_bands(p85, p95, p99)
            logger.info(
                "NewsMomentum: ML percentile bands calibrated — p85=%.3f p95=%.3f p99=%.3f (from %d samples)",
                p85, p95, p99, len(probs),
            )
        except Exception as exc:
            logger.warning("NewsMomentum: percentile calibration error: %s", exc)

    def get_eod_reviewer(self):
        """Lazy-init EOD reviewer."""
        if self._eod_reviewer is None:
            from src.core.agentic.news_momentum_eod_review import NewsMomentumEODReviewer
            self._eod_reviewer = NewsMomentumEODReviewer(self)
        return self._eod_reviewer

    def get_outcome_resolver(self):
        """Lazy-init outcome resolver to close the alert feedback loop."""
        if self._outcome_resolver is None:
            from src.core.agentic.news_momentum_outcome_resolver import NewsMomentumOutcomeResolver
            self._outcome_resolver = NewsMomentumOutcomeResolver(self._telegram_learning)
        return self._outcome_resolver

    def get_ml_engine(self) -> NewsMomentumMLEngine:
        """Return the self-training ML engine."""
        return self._ml_engine

    def get_sec_intelligence(self) -> Optional[SECIntelligenceOrchestrator]:
        """Return the SEC Filing Intelligence orchestrator (may be None)."""
        return self._sec_intel

    def _apply_sec_intelligence(self, c: NewsMomentumCandidate) -> None:
        """Cross-analyse momentum candidate against SEC structural data.

        Reads the cached SEC profile for the ticker (if any) and applies
        the recommended deltas to expected_return, continuation, multi-day
        continuation, trap_risk, exhaustion, and dilution_risk. Also caches
        the SEC candidate + adjustment on the momentum candidate so the
        Telegram message and gate can read them later.

        Safe to call unconditionally — no-op if SEC engine unavailable or
        no profile exists yet for the ticker.
        """
        c._sec_candidate = None  # type: ignore[attr-defined]
        c._sec_adjustment = None  # type: ignore[attr-defined]
        if self._sec_intel is None:
            return
        try:
            sec_c: Optional[_SECCandidate] = self._sec_intel.get_candidate(c.ticker)
            if sec_c is None:
                return
            adj = _sec_compute_adjustment(sec_c)
            c._sec_candidate = sec_c  # type: ignore[attr-defined]
            c._sec_adjustment = adj  # type: ignore[attr-defined]

            # Apply deltas (clamp 0..100)
            def _clamp(x: float) -> float:
                return float(max(0.0, min(100.0, x)))

            c.expected_return_score = _clamp(c.expected_return_score + adj.expected_return_delta)
            c.continuation_probability = _clamp(c.continuation_probability + adj.continuation_probability_delta)
            c.multi_day_continuation_score = _clamp(
                c.multi_day_continuation_score + adj.multi_day_continuation_delta
            )
            c.trap_risk = _clamp(c.trap_risk + adj.trap_risk_delta)
            c.exhaustion_probability = _clamp(c.exhaustion_probability + adj.exhaustion_probability_delta)
            c.dilution_risk = _clamp(c.dilution_risk + adj.dilution_risk_delta)
        except Exception as exc:
            logger.debug("SEC cross-analysis failed for %s: %s", c.ticker, exc)

    def _sec_record_fields(self, c: NewsMomentumCandidate) -> Dict:
        """Build the SEC fields dict for TelegramAlertRecord (safe with no SEC)."""
        sec_c = getattr(c, "_sec_candidate", None)
        if sec_c is None:
            return {}
        s = sec_c.scores
        return {
            "sec_dilution_probability": s.dilution_probability_score,
            "sec_toxic_financing_score": s.toxic_financing_score,
            "sec_warrant_overhang_score": s.warrant_overhang_score,
            "sec_cash_runway_score": s.cash_runway_score,
            "sec_survival_risk_score": s.survival_risk_score,
            "sec_balance_sheet_quality_score": s.balance_sheet_quality_score,
            "sec_offering_risk_score": s.offering_risk_score,
            "sec_reverse_split_risk_score": s.reverse_split_risk_score,
            "sec_structural_trap_risk_score": s.structural_trap_risk_score,
            "sec_historical_dilution_behavior_score": s.historical_dilution_behavior_score,
            "sec_dilution_behavior": sec_c.dilution_behavior.value,
            "sec_oracle_action": sec_c.oracle_action.value,
            "sec_atm_active": sec_c.atm_active,
            "sec_going_concern_active": sec_c.going_concern_active,
        }

    async def scan_sec_for_candidates(self, max_tickers: int = 25) -> int:
        """Background helper: scan SEC filings for current candidate tickers.

        Runs filings analysis for the top active candidates so the next
        scoring cycle can use up-to-date structural data. Returns the
        number of tickers scanned.
        """
        if self._sec_intel is None:
            return 0
        tickers = [c.ticker for c in self._candidates if c.is_active][:max_tickers]
        if not tickers:
            return 0
        try:
            await self._sec_intel.scan_tickers(tickers)
            return len(tickers)
        except Exception as exc:
            logger.warning("SEC background scan failed: %s", exc)
            return 0

    def retrain_ml(self):
        """Trigger an ML retrain on all resolved alert records.

        Also feeds missed-winner records as synthetic positive examples
        to reduce selection bias. Returns the TrainingResult.
        """
        try:
            records = list(self._telegram_learning._alerts)
            # Missed winners scored high but were blocked — inject them
            # as positive training examples so the model learns why they
            # were good even if we didn't alert.
            missed = [r for r in self._missed_learning._records if r.missed]
            return self._ml_engine.train(records, missed_records=missed)
        except Exception as exc:
            logger.error("NewsMomentum: ML retrain failed: %s", exc, exc_info=True)
            from src.core.agentic.news_momentum_ml_engine import TrainingResult
            return TrainingResult(success=False, reason=f"exception: {exc}")

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> NewsMomentumConfig:
        raw = load_json_file(CONFIG_FILE, default=None)
        if raw:
            try:
                return NewsMomentumConfig(**raw)
            except Exception:
                pass
        return NewsMomentumConfig()

    def _save_config(self) -> None:
        save_json_file(CONFIG_FILE, self.config.model_dump())

    def update_config(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self._save_config()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_candidates(self) -> None:
        raw = load_json_file(CANDIDATES_FILE, default=None)
        if raw is None:
            return
        skipped = 0
        for item in raw:
            try:
                c = NewsMomentumCandidate(**item)
                self._candidates.append(c)
                self._candidate_by_ticker[c.ticker] = c
            except Exception as exc:
                skipped += 1
                logger.debug("NewsMomentum: skipped corrupt candidate record: %s", exc)
        if skipped:
            logger.warning("NewsMomentum: skipped %d corrupt candidate records", skipped)
        logger.info("NewsMomentum: loaded %d candidates", len(self._candidates))

    def _save_candidates(self) -> None:
        data = [c.model_dump(mode="json") for c in self._candidates if c.is_active]
        save_json_file(CANDIDATES_FILE, data)

    # ── Cooldown Persistence ────────────────────────────────────────────────

    def _load_cooldowns(self) -> None:
        raw = load_json_file(COOLDOWN_FILE, default=None)
        if raw:
            for t, ts_str in raw.items():
                try:
                    self._alert_cooldown[t] = _aware_utc(datetime.fromisoformat(ts_str))
                except Exception as exc:
                    logger.debug("NewsMomentum: skipped corrupt cooldown for %s: %s", t, exc)
            logger.debug("NewsMomentum: loaded %d ticker cooldowns", len(self._alert_cooldown))

    def _save_cooldowns(self) -> None:
        data = {
            t: ts.isoformat() for t, ts in self._alert_cooldown.items()
        }
        save_json_file(COOLDOWN_FILE, data)

    def _load_headline_cooldowns(self) -> None:
        raw = load_json_file(HEADLINE_COOLDOWN_FILE, default=None)
        if raw:
            for k, ts_str in raw.items():
                try:
                    self._headline_alert_cooldown[k] = _aware_utc(datetime.fromisoformat(ts_str))
                except Exception as exc:
                    logger.debug("NewsMomentum: skipped corrupt headline cooldown: %s", exc)
            logger.debug("NewsMomentum: loaded %d headline cooldowns", len(self._headline_alert_cooldown))

    def _save_headline_cooldowns(self) -> None:
        data = {
            k: ts.isoformat() for k, ts in self._headline_alert_cooldown.items()
        }
        save_json_file(HEADLINE_COOLDOWN_FILE, data)

    def _alert_memory_key(self, ticker: str, headline: str) -> str:
        return f"{ticker.upper()}:{self._headline_hash(headline)}"

    def _stable_alert_id(self, c: NewsMomentumCandidate) -> str:
        published = (_aware_utc(c.published_at) or datetime.min.replace(tzinfo=timezone.utc)).isoformat()
        raw = f"news_momentum|{c.ticker.upper()}|{self._headline_hash(c.headline)}|{published}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"news_momentum_{c.ticker.upper()}_{digest}"

    def _load_alert_memory(self) -> None:
        raw = load_json_file(ALERT_MEMORY_FILE, default=None)
        if isinstance(raw, dict):
            self._alert_memory = raw
            logger.debug("NewsMomentum: loaded %d alert memory entries", len(self._alert_memory))

    def _save_alert_memory(self) -> None:
        save_json_file(ALERT_MEMORY_FILE, self._alert_memory)

    def _hydrate_cooldowns_from_alert_history(self) -> None:
        """Rebuild suppression state from durable alert records on restart.

        This is a second line of defence for Railway redeploys/crashes where the
        explicit cooldown files are missing, empty, or stale but the alert
        history still exists.
        """
        now = datetime.now(timezone.utc)
        ticker_window = timedelta(minutes=self.config.telegram_cooldown_minutes)
        headline_window = timedelta(hours=max(24.0, float(self.config.news_max_age_hours or 0)))
        hydrated = 0

        for key, item in list(self._alert_memory.items()):
            try:
                sent_at = _aware_utc(datetime.fromisoformat(str(item.get("sent_at"))))
                ticker = str(item.get("ticker") or key.split(":", 1)[0]).upper()
            except Exception:
                continue
            if sent_at is None:
                continue
            if now - sent_at <= ticker_window:
                current = _aware_utc(self._alert_cooldown.get(ticker))
                if current is None or sent_at > current:
                    self._alert_cooldown[ticker] = sent_at
                    hydrated += 1
            if now - sent_at <= headline_window:
                current = _aware_utc(self._headline_alert_cooldown.get(key))
                if current is None or sent_at > current:
                    self._headline_alert_cooldown[key] = sent_at

        for alert in getattr(self._telegram_learning, "_alerts", []):
            try:
                sent_at = _aware_utc(alert.sent_at)
                ticker = alert.ticker.upper()
            except Exception:
                continue
            if sent_at and now - sent_at <= ticker_window:
                current = _aware_utc(self._alert_cooldown.get(ticker))
                if current is None or sent_at > current:
                    self._alert_cooldown[ticker] = sent_at
                    hydrated += 1
            headline = getattr(alert, "headline", None)
            if sent_at and headline and now - sent_at <= headline_window:
                key = self._alert_memory_key(ticker, headline)
                current = _aware_utc(self._headline_alert_cooldown.get(key))
                if current is None or sent_at > current:
                    self._headline_alert_cooldown[key] = sent_at

        if hydrated:
            self._save_cooldowns()
            self._save_headline_cooldowns()
            logger.info("NewsMomentum: hydrated %d cooldown entries from alert history", hydrated)

    def _remember_sent_alert(self, c: NewsMomentumCandidate, sent_at: datetime) -> None:
        key = self._alert_memory_key(c.ticker, c.headline)
        if not hasattr(self, "_alert_memory"):
            self._alert_memory = {}
        self._alert_memory[key] = {
            "ticker": c.ticker.upper(),
            "headline_hash": self._headline_hash(c.headline),
            "headline": c.headline,
            "source": c.source.value if hasattr(c.source, "value") else str(c.source),
            "published_at": (_aware_utc(c.published_at) or sent_at).isoformat(),
            "sent_at": sent_at.isoformat(),
            "alert_id": c.telegram_alert_id or self._stable_alert_id(c),
        }
        config = getattr(self, "config", None)
        news_max_age_hours = getattr(config, "news_max_age_hours", 24.0)
        cutoff = sent_at - timedelta(hours=max(24.0, float(news_max_age_hours or 0)))
        kept: Dict[str, dict] = {}
        for k, v in self._alert_memory.items():
            try:
                item_sent_at = _aware_utc(datetime.fromisoformat(str(v.get("sent_at"))))
            except Exception:
                continue
            if item_sent_at and item_sent_at >= cutoff:
                kept[k] = v
        self._alert_memory = kept
        self._save_alert_memory()

    def _sent_alerts_today_for_ticker(self, ticker: str, now: datetime) -> int:
        today = now.astimezone(timezone.utc).date()
        count = 0
        for item in getattr(self, "_alert_memory", {}).values():
            if str(item.get("ticker", "")).upper() != ticker.upper():
                continue
            try:
                sent_at = _aware_utc(datetime.fromisoformat(str(item.get("sent_at"))))
            except Exception:
                continue
            if sent_at and sent_at.astimezone(timezone.utc).date() == today:
                count += 1
        return count

    def _load_event_registry(self) -> None:
        raw = load_json_file(EVENT_REGISTRY_FILE, default=None)
        if raw:
            for k, event_dict in raw.items():
                try:
                    self._event_registry[k] = NewsEvent(**event_dict)
                except Exception as exc:
                    logger.debug("NewsMomentum: skipped corrupt event registry entry %s: %s", k, exc)
            logger.debug("NewsMomentum: loaded %d event registry entries", len(self._event_registry))

    def _save_event_registry(self) -> None:
        data = {
            k: v.model_dump(mode="json") for k, v in self._event_registry.items()
        }
        save_json_file(EVENT_REGISTRY_FILE, data)

    def _prune_old_candidates(self, max_age_hours: int = 48, max_total: int = 500) -> None:
        """Drop inactive candidates older than max_age_hours; cap total list size."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_age_hours)
        news_age_cutoff = None
        if self.config.news_max_age_hours:
            news_age_cutoff = now - timedelta(hours=float(self.config.news_max_age_hours))
        before = len(self._candidates)

        kept = []
        for c in self._candidates:
            published = _aware_utc(c.published_at)
            detected = _aware_utc(c.detected_at) if c.detected_at else now
            if c.is_active and (
                (published is not None and news_age_cutoff is not None and published < news_age_cutoff)
                or detected < cutoff
            ):
                c.is_active = False

            # Keep active candidates that are still within freshness windows.
            if c.is_active:
                kept.append(c)
                continue
            # Keep recent inactive (for missed-winner / EOD analysis)
            if detected >= cutoff:
                kept.append(c)

        # Hard cap to prevent runaway growth even within window
        if len(kept) > max_total:
            kept.sort(key=lambda c: _aware_utc(c.detected_at) or now, reverse=True)
            kept = kept[:max_total]

        # Rebuild ticker index (keep most recent per ticker)
        self._candidates = kept
        self._candidate_by_ticker = {}
        for c in sorted(kept, key=lambda c: _aware_utc(c.detected_at) or now):
            if c.is_active:
                self._candidate_by_ticker[c.ticker] = c

        # Prune cooldown dicts and event registry
        cooldown_cutoff = now - timedelta(hours=max_age_hours)
        alert_cooldown = getattr(self, "_alert_cooldown", {}) or {}
        headline_alert_cooldown = getattr(self, "_headline_alert_cooldown", {}) or {}
        event_registry = getattr(self, "_event_registry", {}) or {}
        self._alert_cooldown = {
            t: ts for t, ts in alert_cooldown.items()
            if (_aware_utc(ts) or now) >= cooldown_cutoff
        }
        self._headline_alert_cooldown = {
            k: ts for k, ts in headline_alert_cooldown.items()
            if (_aware_utc(ts) or now) >= cooldown_cutoff
        }
        dup_window = timedelta(hours=2)
        self._event_registry = {
            k: v for k, v in event_registry.items()
            if (_aware_utc(v.detected_at) or now) >= (now - dup_window)
        }

        # Persist pruned state
        self._save_candidates()
        self._save_cooldowns()
        self._save_headline_cooldowns()
        self._save_event_registry()

        dropped = before - len(self._candidates)
        if dropped > 0:
            logger.info("NewsMomentum: pruned %d old candidates (kept %d)", dropped, len(self._candidates))

    # ── Session Detection ─────────────────────────────────────────────────────

    def _get_et_hour(self) -> float:
        """Get current ET hour as float (e.g. 9.5 = 9:30 AM)."""
        now = datetime.now(timezone.utc)
        et_offset = timedelta(hours=-4)
        et_time = now.astimezone(timezone(et_offset))
        return et_time.hour + et_time.minute / 60.0

    def _detect_session(self) -> SessionType:
        """Detect current market session based on ET time."""
        hour = self._get_et_hour()
        if 4.0 <= hour < 9.5:
            return SessionType.PREMARKET
        elif 9.5 <= hour < 16.0:
            return SessionType.REGULAR
        elif 16.0 <= hour < 20.0:
            return SessionType.AFTER_HOURS
        else:
            return SessionType.PREMARKET

    def _get_session_thresholds(self) -> Tuple[float, float, float, float]:
        """Return (impact, expected_return, continuation, multi_day) thresholds for current session."""
        hour = self._get_et_hour()
        cfg = self.config
        if 4.0 <= hour < 7.0:
            # Early premarket (4-7 AM) — lowest thresholds
            return (
                cfg.premarket_impact_threshold,
                cfg.premarket_expected_return_threshold,
                cfg.premarket_continuation_threshold,
                cfg.multi_day_threshold,
            )
        elif 7.0 <= hour < 9.5:
            # Late premarket (7-9:30 AM) — slightly higher
            return (
                cfg.premarket_impact_threshold + 3,
                cfg.premarket_expected_return_threshold + 3,
                cfg.premarket_continuation_threshold + 3,
                cfg.multi_day_threshold,
            )
        elif 9.5 <= hour < 10.5:
            # Market open (9:30-10:30 AM)
            return (
                cfg.open_impact_threshold,
                cfg.open_expected_return_threshold,
                cfg.open_continuation_threshold,
                cfg.multi_day_threshold,
            )
        elif 10.5 <= hour < 15.0:
            # Midday (10:30 AM - 3:00 PM) — highest thresholds
            return (
                cfg.midday_impact_threshold,
                cfg.midday_expected_return_threshold,
                cfg.midday_continuation_threshold,
                cfg.multi_day_threshold,
            )
        elif 15.0 <= hour < 16.0:
            # Power hour (3:00-4:00 PM)
            return (
                cfg.power_hour_impact_threshold,
                cfg.power_hour_expected_return_threshold,
                cfg.power_hour_continuation_threshold,
                cfg.multi_day_threshold,
            )
        else:
            # After hours — use premarket thresholds
            return (
                cfg.premarket_impact_threshold,
                cfg.premarket_expected_return_threshold,
                cfg.premarket_continuation_threshold,
                cfg.multi_day_threshold,
            )

    # ── Cross-Source Velocity ─────────────────────────────────────────────────

    def _headline_hash(self, headline: str) -> str:
        """Create a simple hash for duplicate detection."""
        text = headline.lower()
        # Remove common filler words
        for word in ["announces", "reports", "provides", "update on", "regarding"]:
            text = text.replace(word, "")
        return f"{text.strip()[:80]}"

    def _headline_similarity(self, a: str, b: str) -> float:
        """Return similarity ratio between two headlines (0.0-1.0)."""
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _merge_event_velocity(self, event: NewsEvent) -> NewsEvent:
        """Track how fast news spreads across sources. Merge with existing if same ticker."""
        h = self._headline_hash(event.headline)
        key = f"{event.ticker}:{h}"
        now = datetime.now(timezone.utc)
        window = timedelta(seconds=self.config.velocity_time_window_seconds)

        # Look for existing event for same ticker
        existing_key = None
        for reg_key, reg_event in self._event_registry.items():
            if not reg_key.startswith(f"{event.ticker}:"):
                continue
            # Check time window
            reg_detected_at = _aware_utc(reg_event.detected_at) or now
            if now - reg_detected_at > window:
                continue
            # Check headline similarity
            sim = self._headline_similarity(event.headline, reg_event.headline)
            if sim > 0.65:
                existing_key = reg_key
                break

        if existing_key:
            existing = self._event_registry[existing_key]
            # Merge sources
            if event.source not in existing.velocity.sources_seen:
                existing.velocity.sources_seen.append(event.source)
                existing.velocity.source_count = len(existing.velocity.sources_seen)
                # Calculate velocity: time from first to this source
                first_detected_at = _aware_utc(existing.velocity.first_detected_at) or now
                elapsed_ms = (now - first_detected_at).total_seconds() * 1000
                existing.velocity.velocity_ms = elapsed_ms
                # Confidence boost based on source count and speed
                count_bonus = min(existing.velocity.source_count * 3, 9)
                speed_bonus = 0.0
                if elapsed_ms < 60000:  # Under 1 minute
                    speed_bonus = 8.0
                elif elapsed_ms < 300000:  # Under 5 minutes
                    speed_bonus = 4.0
                existing.velocity.confidence_boost = min(count_bonus + speed_bonus, self.config.velocity_bonus_max)
            # Update event to reflect merged velocity
            event.velocity = existing.velocity
            return event

        # New event — register it
        event.velocity.first_detected_at = now
        event.velocity.sources_seen = [event.source]
        event.velocity.source_count = 1
        self._event_registry[key] = event
        # Clean old registry entries
        self._clean_event_registry()
        self._save_event_registry()
        return event

    def _clean_event_registry(self) -> None:
        """Remove registry entries older than the duplicate-detection window.

        Use the LARGER of the velocity window and the dup window so that
        _check_duplicate (2h window) actually finds prior events.
        Previously this used only the velocity window (5min), causing the
        registry to expire too fast and the same news headline to be
        re-classified as "new" on every subsequent scan — leading to
        repeat alerts every cooldown cycle.
        """
        now = datetime.now(timezone.utc)
        velocity_window = timedelta(seconds=self.config.velocity_time_window_seconds)
        dup_window = timedelta(hours=2)
        window = max(velocity_window, dup_window)
        expired = [
            k for k, v in self._event_registry.items()
            if now - (_aware_utc(v.detected_at) or now) > window
        ]
        for k in expired:
            del self._event_registry[k]

    # ── Duplicate Filtering ───────────────────────────────────────────────────

    def _check_duplicate(self, event: NewsEvent) -> NewsEvent:
        """Mark event as duplicate if same ticker had similar headline within 2 hours."""
        now = datetime.now(timezone.utc)
        dup_window = timedelta(hours=2)
        h = self._headline_hash(event.headline)

        for reg_key, reg_event in self._event_registry.items():
            if not reg_key.startswith(f"{event.ticker}:"):
                continue
            # Skip checking against itself (same source + same time = same event)
            reg_detected_at = _aware_utc(reg_event.detected_at) or now
            event_detected_at = _aware_utc(event.detected_at) or now
            if event.source == reg_event.source and event_detected_at == reg_detected_at:
                continue
            if now - reg_detected_at > dup_window:
                continue
            sim = self._headline_similarity(event.headline, reg_event.headline)
            if sim > 0.80:  # High similarity = duplicate
                event.duplicate_of_id = reg_detected_at.isoformat()
                return event
        return event

    # ── News-to-Price Lag Detection ───────────────────────────────────────────

    def _detect_news_to_price_lag(self, c: NewsMomentumCandidate, old_move_pct: float) -> None:
        """Detect if a stock had a delayed reaction to news and enable aggressive refresh."""
        now = datetime.now(timezone.utc)
        # Only check if we have a significant new move
        move_delta = c.move_pct - old_move_pct
        if move_delta < 15:  # Need at least 15% new move to count
            return

        if c.first_volume_reaction_at is None:
            c.first_volume_reaction_at = now
            # Calculate lag from news detection to first meaningful move
            if c.detected_at:
                detected_at = _aware_utc(c.detected_at) or now
                lag = (now - detected_at).total_seconds()
                c.news_to_price_lag_seconds = lag
                # If lag > 5 minutes, flag as delayed reaction
                if lag > 300:
                    c.is_delayed_reaction = True
                    # Enable aggressive refresh for next 10 minutes
                    c.aggressive_refresh_until = now + timedelta(minutes=10)
                    logger.info(
                        "NewsMomentum: %s delayed reaction detected — %.0fs after news. "
                        "Aggressive refresh enabled until %s",
                        c.ticker, lag, c.aggressive_refresh_until.strftime("%H:%M:%S"),
                    )

    # ── Price Bucket ──────────────────────────────────────────────────────────

    @staticmethod
    def _price_bucket(price: float) -> PriceBucket:
        if price < 0.01:
            return PriceBucket.SUB_PENNY
        elif price < 1.0:
            return PriceBucket.UNDER_1
        elif price < 5.0:
            return PriceBucket.UNDER_5
        elif price < 10.0:
            return PriceBucket.UNDER_10
        else:
            return PriceBucket.MID_CAP

    @staticmethod
    def _float_category(float_shares: Optional[float]) -> FloatCategory:
        if float_shares is None:
            return FloatCategory.LOW
        if float_shares < 5_000_000:
            return FloatCategory.ULTRA_LOW
        elif float_shares < 20_000_000:
            return FloatCategory.LOW
        elif float_shares < 100_000_000:
            return FloatCategory.MEDIUM
        else:
            return FloatCategory.HIGH

    @staticmethod
    def _market_cap_category(mcap: Optional[float]) -> MarketCapCategory:
        if mcap is None:
            return MarketCapCategory.MICRO
        if mcap < 50_000_000:
            return MarketCapCategory.NANO
        elif mcap < 300_000_000:
            return MarketCapCategory.MICRO
        elif mcap < 2_000_000_000:
            return MarketCapCategory.SMALL
        else:
            return MarketCapCategory.ALL

    # ── Scanning ──────────────────────────────────────────────────────────────

    async def scan(self, news_events: List[NewsEvent]) -> NewsMomentumScanResult:
        """
        Process a batch of news events into scored candidates.
        Called from the background loop in main.py.
        """
        if not self.config.enabled:
            return NewsMomentumScanResult(scan_time=datetime.now(timezone.utc), session=self._detect_session())

        session = self._detect_session()
        result = NewsMomentumScanResult(scan_time=datetime.now(timezone.utc), session=session)

        # Get historical stats for ML
        historical_stats = self._catalyst_learning.get_catalyst_type_stats()
        hist_dict = {k: v.model_dump() for k, v in historical_stats.items()} if historical_stats else None

        # Get adaptive thresholds
        adaptive = self._telegram_learning.get_adaptive_thresholds()

        for event in news_events:
            # Cross-source velocity: merge with earlier event for same ticker if within window
            event = self._merge_event_velocity(event)
            # Duplicate check: suppress reworded headlines for same ticker within 2 hours
            event = self._check_duplicate(event)
            if event.duplicate_of_id:
                if not self._duplicate_event_should_refresh_existing_candidate(event):
                    continue  # Skip pure duplicates
                event.duplicate_of_id = None

            candidate = await self._process_event(event, session, hist_dict, adaptive)
            if candidate:
                # Apply velocity bonus to impact score
                candidate.velocity_score = event.velocity.confidence_boost
                candidate.news_impact_score = min(100.0, candidate.news_impact_score + candidate.velocity_score)
                result.candidates.append(candidate)

        # Fresh news must alert before the slower active-candidate refresh pass.
        # This is the first-mover path: if a new Finviz/StockTitan headline
        # qualifies, do not wait behind older candidates.
        if self.config.telegram_enabled and result.candidates:
            result.telegram_alerts_sent += await self._send_telegram_for_candidates(
                result.candidates, adaptive
            )
            if result.telegram_alerts_sent > 0:
                self._save_candidates()
        elif result.candidates:
            logger.info("NewsMomentum: Telegram alerts disabled by config")

        # Proactive refresh: re-evaluate ALL active candidates with live market data
        # This catches delayed moves (news at 5:31 AM, stock moves at 9:05 AM)
        now = datetime.now(timezone.utc)
        stale_deactivated = 0
        for c in list(self._candidate_by_ticker.values()):
            if not c.is_active or c.telegram_sent:
                continue
            detected_at = _aware_utc(c.detected_at)
            age_hours = (now - detected_at).total_seconds() / 3600 if detected_at else 999
            if age_hours > 24.0:
                c.is_active = False
                stale_deactivated += 1
                continue
            # Check if aggressive refresh is active (for delayed reactions)
            aggressive_until = _aware_utc(c.aggressive_refresh_until)
            refresh_interval = 15 if (aggressive_until and now < aggressive_until) else 45
            # Only refresh if enough time has passed since last refresh
            last_refresh = _aware_utc(c.last_refresh or c.detected_at)
            if last_refresh and (now - last_refresh).total_seconds() < refresh_interval:
                continue
            try:
                old_move = c.move_pct
                await self._refresh_candidate(c, hist_dict)
                c.last_refresh = now
                # Detect news-to-price lag on this refresh
                self._detect_news_to_price_lag(c, old_move)
                # If now qualifies, include in result for this scan
                if c not in result.candidates:
                    result.candidates.append(c)
            except Exception as exc:
                logger.debug("Refresh error for %s: %s", c.ticker, exc)

        # Rank candidates — BigWinner rocket_probability first, expected_return
        # as the tiebreaker. The BigWinner model (auc=0.995 on 126 rockets)
        # is the strongest discriminator of substantial winners we have;
        # ordering by it ensures the highest-rocket-probability candidates
        # are evaluated for Telegram first and take precedence in the
        # per-ticker cooldown when multiple headlines compete.
        def _rank_key(c: NewsMomentumCandidate) -> tuple:
            bw_prob = getattr(c, "_big_winner_probability", None) or 0.0
            stack = getattr(c, "_stacking_count", None) or 0
            return (bw_prob, stack, c.expected_return_score)
        result.candidates.sort(key=_rank_key, reverse=True)
        for i, c in enumerate(result.candidates):
            c.rank = i + 1

        result.top_expected_return = [c for c in result.candidates if c.expected_return_score >= 70][:20]
        result.top_continuation = [c for c in result.candidates if c.continuation_probability >= 70][:20]
        result.top_multiday = [c for c in result.candidates if c.multi_day_continuation_score >= 70][:20]
        result.trap_warnings = [c for c in result.candidates if c.trap_risk >= 70 or c.dilution_risk >= 70][:10]

        # Alert any refreshed/delayed candidates that now pass. Fresh candidates
        # were already handled above, so cooldowns prevent duplicate sends here.
        if self.config.telegram_enabled:
            result.telegram_alerts_sent += await self._send_telegram_for_candidates(
                result.candidates, adaptive
            )
            # Persist candidate state immediately so a crash doesn't lose telegram_sent flags
            if result.telegram_alerts_sent > 0:
                self._save_candidates()
        elif result.candidates:
            logger.info("NewsMomentum: Telegram alerts disabled by config")

        # Missed winner retrospective check (every 5 scans)
        if self._scan_counter % 5 == 0 and self.config.learning_enabled:
            await self._check_missed_winners()

        self._scan_counter += 1
        if self._scan_counter % 10 == 0:
            self._save_candidates()
        elif stale_deactivated > 0:
            self._save_candidates()
            logger.info(
                "NewsMomentum: deactivated %d stale unsent candidates before refresh",
                stale_deactivated,
            )
        # Prune memory every 50 scans (~25-50 minutes depending on interval)
        if self._scan_counter % 50 == 0:
            self._prune_old_candidates()

        return result

    async def _send_telegram_for_candidates(
        self,
        candidates: List[NewsMomentumCandidate],
        adaptive: dict,
    ) -> int:
        """Send Telegram alerts for candidates that pass the gate."""
        sent_count = 0
        for candidate in candidates:
            if self._should_send_telegram(candidate, adaptive):
                sent = await self._send_telegram_alert(candidate)
                if sent:
                    sent_count += 1
                    # Record sector move for hype tracking
                    try:
                        if self._sector_hype and candidate.move_pct is not None:
                            self._sector_hype.record_move(
                                candidate.catalyst_category, candidate.move_pct,
                            )
                    except Exception:
                        pass
        return sent_count

    def _mark_if_obsolete_on_arrival(
        self, c: NewsMomentumCandidate, now: Optional[datetime] = None
    ) -> bool:
        """Flag a candidate whose news was published outside the obsolescence
        window, so the breaking/first-mover speed tiers are suppressed.

        Deterministic: compares the provider's publication time against the
        current UTC clock. Returns True if the candidate is stale-on-arrival.
        The candidate is NOT dropped — it still flows through the normal
        delayed-reaction path and the 12h freshness gates.
        """
        now = now or datetime.now(timezone.utc)
        published_at = _aware_utc(c.published_at)
        if published_at is None:
            return False
        config = getattr(self, "config", None)
        window = int(getattr(config, "breaking_obsolescence_window_seconds", 300) or 300)
        age_seconds = (now - published_at).total_seconds()
        if age_seconds > window:
            c._stale_on_arrival = True  # type: ignore[attr-defined]
            logger.warning(
                "NewsMomentum: obsolete feed item for %s — published %.0fs ago "
                "(> %ds obsolescence window); suppressing breaking/first-mover "
                "treatment. source=%s headline=%r",
                c.ticker, age_seconds, window,
                getattr(c.source, "value", c.source), (c.headline or "")[:160],
            )
            return True
        return False

    async def _process_event(
        self,
        event: NewsEvent,
        session: SessionType,
        historical_stats: Optional[dict],
        adaptive: dict,
    ) -> Optional[NewsMomentumCandidate]:
        """Process a single news event into a scored candidate."""
        now = datetime.now(timezone.utc)

        # Check if already tracking
        if event.ticker in self._candidate_by_ticker:
            existing = self._candidate_by_ticker[event.ticker]
            # Update if newer news with better catalyst
            event_detected_at = _aware_utc(event.detected_at) or now
            existing_detected_at = _aware_utc(existing.detected_at) or now
            should_replace = (
                event_detected_at > existing_detected_at
                or self._event_upgrades_existing_candidate(event, existing)
            )
            if should_replace:
                existing.is_active = False
                try:
                    self._candidates = [
                        candidate for candidate in self._candidates
                        if candidate.ticker != event.ticker
                    ]
                except Exception:
                    pass
                logger.info(
                    "NewsMomentum: %s existing candidate promoted/replaced (%s -> %s)",
                    event.ticker,
                    existing.catalyst_sub_type.value,
                    event.catalyst_sub_type.value,
                )
            else:
                # Same news — refresh market data and recompute scores
                # This catches delayed moves (e.g. news at 5:31 AM, move at 9:05 AM)
                self._merge_event_metadata_into_candidate(existing, event)
                await self._refresh_candidate(existing, historical_stats)
                return existing

        # Build candidate
        c = NewsMomentumCandidate(
            ticker=event.ticker,
            headline=event.headline,
            source=event.source,
            source_url=event.source_url,
            raw_text=event.raw_text or event.headline,
            published_at=event.published_at,
            timestamp_confidence=event.timestamp_confidence,
            detected_at=event.detected_at,
            fetched_at=event.fetched_at,
            parsed_at=event.parsed_at,
            classified_at=event.classified_at,
            candidate_created_at=now,
            session=session,
            catalyst_category=event.catalyst_category,
            catalyst_sub_type=event.catalyst_sub_type,
            is_negative=event.is_negative,
            is_vague=event.is_vague,
        )

        # Obsolescence gate (upstream-feed delay): a headline served long after
        # its publication time must not masquerade as a fresh breaking catalyst.
        # This runs BEFORE fast-path WATCH / enrichment / classification.
        self._mark_if_obsolete_on_arrival(c, now)

        await self._send_fast_path_watch(c)

        # Fetch market data (async)
        await self._enrich_with_market_data(c)

        # Note: Price filter is NOT applied here — we track ALL candidates
        # so that sub-$0.20 stocks which gap up on news can still alert
        # when they cross the threshold (e.g. SLXN at $0.12 → $1.00).
        # Price filter is enforced in _should_send_telegram instead.

        # Compute all scores
        c.news_impact_score = self._compute_impact_score(c)
        c.news_reaction_score = self._compute_reaction_score(c)
        er = compute_expected_return_score(c, historical_stats)
        c.expected_return_score = er.score
        cp = compute_continuation_probability(c, historical_stats)
        c.continuation_probability = cp.same_day_continuation
        md = compute_multi_day_continuation(c, cp, historical_stats)
        c.multi_day_continuation_score = md.multi_day_score
        c.next_day_continuation_probability = md.next_day_continuation_probability
        c.two_day_continuation_probability = md.two_day_continuation_probability
        c.five_day_continuation_probability = md.five_day_continuation_probability
        c.next_day_gap_up_probability = md.next_day_gap_up_probability
        c.swing_trade_quality_score = md.swing_trade_quality_score
        c.exhaustion_probability = md.exhaustion_probability
        c.multi_day_class = md.classification
        c.oracle_action = determine_oracle_action(c, cp, md)

        # SEC Filing Intelligence — adjust scores based on structural data
        self._apply_sec_intelligence(c)

        # Estimated move
        move = estimate_move_range(c)
        c.estimated_move.conservative_pct = move["conservative_pct"]
        c.estimated_move.bullish_pct = move["bullish_pct"]
        c.estimated_move.extreme_pct = move["extreme_pct"]
        if c.current_price:
            c.estimated_move.conservative_target = round(c.current_price * (1 + move["conservative_pct"] / 100), 4)
            c.estimated_move.bullish_target = round(c.current_price * (1 + move["bullish_pct"] / 100), 4)
            c.estimated_move.extreme_target = round(c.current_price * (1 + move["extreme_pct"] / 100), 4)

        # Adaptive Telegram quality score
        cat_stats = self._telegram_learning.get_catalyst_quality(c.catalyst_sub_type)
        if not cat_stats.get("insufficient", True):
            c.telegram_alert_quality_score = cat_stats.get("quality_score", 50.0)

        # BigWinner ML — run predict NOW so its rocket_probability is available
        # to the ranking step (line ~827) instead of being computed lazily
        # inside the Telegram gate. With auc=0.995 on the 126-rocket training
        # set, this is the strongest single signal for "substantial winner"
        # candidates; previously it was only consulted as a tier-band
        # amplifier and the primary sort was expected_return_score, which is
        # heavily price-dependent and lags rocket conditions.
        try:
            bw_pred = self._big_winner_ml.predict(c)
            c._big_winner_prediction = bw_pred  # type: ignore[attr-defined]
            c._big_winner_probability = bw_pred.rocket_probability  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("BigWinner predict failed for %s: %s", c.ticker, exc)
            c._big_winner_probability = 0.0  # type: ignore[attr-defined]

        # Co-catalyst stacking — count how many positive signals fire
        # concurrently. Used as a secondary ranker and surfaced to the
        # Telegram message so the operator can see WHY a candidate scored
        # high. Historically rockets fire 5-7 signals; non-rockets fire 0-2.
        stacking_count, stacking_signals = _compute_stacking_score(c)
        c._stacking_count = stacking_count  # type: ignore[attr-defined]
        c._stacking_signals = stacking_signals  # type: ignore[attr-defined]

        # Bull/bear cases
        c.bull_bear = self._generate_bull_bear(c)
        c.scored_at = datetime.now(timezone.utc)

        self._log_rocket_shadow_prediction(c, source_pipeline="news_momentum")

        # Store
        self._candidates.append(c)
        self._candidate_by_ticker[c.ticker] = c

        return c

    def _is_fast_path_watch_eligible(self, c: NewsMomentumCandidate) -> bool:
        if c.fast_path_watch_sent or c.telegram_sent:
            return False
        # Obsolescence gate: a stale-on-arrival headline is never a fast WATCH.
        if getattr(c, "_stale_on_arrival", False):
            return False
        if c.source not in _FAST_PATH_VERIFIED_SOURCES:
            return False
        if c.is_negative or c.is_vague:
            return False
        if c.catalyst_sub_type not in _FAST_PATH_HIGH_IMPACT_CATALYSTS:
            return False
        if (getattr(c, "timestamp_confidence", "HIGH") or "HIGH").upper() != "HIGH":
            return False

        now = datetime.now(timezone.utc)
        published_at = _aware_utc(c.published_at)
        detected_at = _aware_utc(c.detected_at)
        if not published_at or not detected_at:
            return False
        published_age = (now - published_at).total_seconds()
        detected_age = (now - detected_at).total_seconds()
        c.published_age_seconds = round(published_age, 3)
        c.detected_age_seconds = round(detected_age, 3)
        if published_age < 0 or detected_age < 0:
            return False
        max_age = max(60, int(self.config.first_mover_max_age_seconds or 300))
        return published_age <= max_age and detected_age <= max_age

    def _format_fast_path_watch_message(self, c: NewsMomentumCandidate) -> str:
        source = c.source.value if hasattr(c.source, "value") else str(c.source)
        published = _aware_utc(c.published_at)
        age = ""
        if published:
            age_seconds = max(0, int((datetime.now(timezone.utc) - published).total_seconds()))
            age = f"\nFreshness: {age_seconds}s from publish"
        return (
            "<b>ORACLE FAST WATCH</b>\n"
            f"<b>{html.escape(c.ticker)}</b> - high-impact catalyst detected\n"
            f"Type: <b>{html.escape(c.catalyst_sub_type.value)}</b>\n"
            f"Source: {html.escape(source)}{age}\n\n"
            f"{html.escape(c.headline)}\n\n"
            "Scores/price enrichment are still running."
        )

    async def _send_fast_path_watch(self, c: NewsMomentumCandidate) -> bool:
        if not self._is_fast_path_watch_eligible(c):
            return False
        c.telegram_alert_id = c.telegram_alert_id or self._stable_alert_id(c)
        fast_alert_id = f"{c.telegram_alert_id}:fast_watch"
        c.telegram_enqueue_at = datetime.now(timezone.utc)
        try:
            sent = await send_telegram_alert(
                self._format_fast_path_watch_message(c),
                parse_mode="HTML",
                alert_id=fast_alert_id,
                ticker=c.ticker,
                alert_type="news_momentum_fast_watch",
                priority=1,
            )
            if sent:
                c.fast_path_watch_sent = True
                c.fast_path_watch_sent_at = datetime.now(timezone.utc)
                c.telegram_sent_at = c.fast_path_watch_sent_at
                logger.info("NewsMomentum: fast WATCH sent for %s before enrichment", c.ticker)
            else:
                logger.warning("NewsMomentum: fast WATCH queued/failed for %s before enrichment", c.ticker)
            trace_candidate(
                c,
                alert_sent=sent,
                blocked_reason=None if sent else "telegram_fast_watch_send_failed",
                alert_type="news_momentum_fast_watch",
                fast_path=True,
            )
            # Reset normal alert delivery fields so the later scored alert can
            # still pass the existing Telegram gate if it qualifies.
            c.telegram_enqueue_at = None
            c.telegram_sent_at = None
            return sent
        except Exception as exc:
            logger.warning("NewsMomentum: fast WATCH failed for %s: %s", c.ticker, exc)
            trace_candidate(
                c,
                alert_sent=False,
                blocked_reason=f"telegram_fast_watch_exception:{exc}",
                alert_type="news_momentum_fast_watch",
                fast_path=True,
            )
            c.telegram_enqueue_at = None
            c.telegram_sent_at = None
            return False

    @staticmethod
    def _merge_event_metadata_into_candidate(c: NewsMomentumCandidate, event: NewsEvent) -> None:
        """Preserve richer source text when a same-ticker candidate is refreshed."""
        event_raw = event.raw_text or event.headline or ""
        if len(event_raw) > len(c.raw_text or c.headline or ""):
            c.raw_text = event_raw
        if (not c.source_url) and event.source_url:
            c.source_url = event.source_url
        # Only upgrade confidence, never downgrade
        _CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        existing_rank = _CONFIDENCE_RANK.get((getattr(c, "timestamp_confidence", "HIGH") or "HIGH").upper(), 0)
        event_rank = _CONFIDENCE_RANK.get((event.timestamp_confidence or "HIGH").upper(), 0)
        if event_rank > existing_rank:
            c.timestamp_confidence = event.timestamp_confidence
        if not c.fetched_at and event.fetched_at:
            c.fetched_at = event.fetched_at
        if not c.parsed_at and event.parsed_at:
            c.parsed_at = event.parsed_at
        if not c.classified_at and event.classified_at:
            c.classified_at = event.classified_at
        if c.is_vague and not event.is_vague:
            c.is_vague = False

    def _log_rocket_shadow_prediction(
        self,
        c: NewsMomentumCandidate,
        *,
        source_pipeline: str,
    ) -> None:
        scorer = getattr(self, "_rocket_shadow_scorer", None)
        if scorer is None:
            return
        try:
            scorer.predict_and_log_candidate(c, source_pipeline=source_pipeline)
        except Exception as exc:
            logger.debug("NewsMomentum: Rocket shadow log failed for %s: %s", c.ticker, exc)

    def _event_upgrades_existing_candidate(
        self,
        event: NewsEvent,
        existing: NewsMomentumCandidate,
    ) -> bool:
        """Return True when a same-ticker event materially improves catalyst quality."""
        if event.is_negative:
            return False

        event_high_conviction = event.catalyst_sub_type in _HIGH_CONVICTION_CATALYSTS
        existing_high_conviction = existing.catalyst_sub_type in _HIGH_CONVICTION_CATALYSTS
        if event_high_conviction and not existing_high_conviction:
            return True

        if (
            existing.catalyst_category == CatalystCategory.UNKNOWN
            and event.catalyst_category != CatalystCategory.UNKNOWN
            and not event.is_vague
        ):
            return True

        if existing.is_vague and not event.is_vague and event_high_conviction:
            return True

        return False

    def _duplicate_event_should_refresh_existing_candidate(self, event: NewsEvent) -> bool:
        """Allow duplicate-looking events through when they improve an active candidate."""
        existing = self._candidate_by_ticker.get(event.ticker)
        if existing is None:
            return False
        if self._event_upgrades_existing_candidate(event, existing):
            return True
        event_raw = event.raw_text or event.headline or ""
        existing_raw = existing.raw_text or existing.headline or ""
        return len(event_raw) > len(existing_raw)

    async def _enrich_with_market_data(self, c: NewsMomentumCandidate) -> None:
        """Fetch live market data for a candidate."""
        deadline = asyncio.get_running_loop().time() + float(
            os.environ.get("NEWS_MARKET_DATA_CANDIDATE_BUDGET_SECONDS", "8") or 8
        )

        async def _run_with_budget(func, *, timeout: float = 2.5):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                c.price_status = "pending"
                raise asyncio.TimeoutError("market data candidate budget exhausted")
            return await asyncio.wait_for(
                asyncio.to_thread(func),
                timeout=max(0.1, min(timeout, remaining)),
            )

        def _apply_quote(quote: Optional[dict]) -> None:
            if not quote:
                return
            price = quote.get("price")
            last = quote.get("last")
            if price is not None and price > 0:
                c.current_price = price
            elif last is not None and last > 0:
                c.current_price = last
            c.volume = quote.get("volume") or c.volume
            c.prior_price = (
                quote.get("previous_close")
                or quote.get("prev_close")
                or quote.get("prior_close")
                or c.prior_price
            )
            avg_volume = quote.get("average_volume") or quote.get("avg_volume")
            if c.volume and avg_volume and avg_volume > 0:
                c.rvol = round(c.volume / avg_volume, 2)
            if c.prior_price and c.current_price and c.prior_price > 0:
                c.move_pct = round(((c.current_price - c.prior_price) / c.prior_price) * 100, 2)
            c.spread_pct = quote.get("spread_pct") or c.spread_pct

        try:
            from src.services.market_data import get_market_data_provider
            provider = get_market_data_provider()
            quote = await _run_with_budget(lambda: provider.get_live_quote(c.ticker))
            _apply_quote(quote)
        except Exception as exc:
            if isinstance(exc, asyncio.TimeoutError):
                c.price_status = "pending"
            logger.debug("NewsMomentum: market data fetch failed for %s: %s", c.ticker, exc)

        if not c.current_price or not c.prior_price:
            try:
                polygon_provider = self._get_polygon_provider()
                if polygon_provider is not None:
                    quote = await _run_with_budget(lambda: polygon_provider.get_live_quote(c.ticker))
                    _apply_quote(quote)
            except Exception as exc:
                if isinstance(exc, asyncio.TimeoutError):
                    c.price_status = "pending"
                logger.debug("NewsMomentum: Polygon fallback failed for %s: %s", c.ticker, exc)

        # Try to get float / market cap / short interest AND fallback price/RVOL
        try:
            import yfinance as yf
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                c.price_status = "pending"
                raise asyncio.TimeoutError("market data candidate budget exhausted")
            t = await asyncio.wait_for(
                asyncio.to_thread(lambda: yf.Ticker(c.ticker)),
                timeout=max(0.1, min(5.0, remaining)),
            )
            # Use fast_info as a lightweight fallback for price / prior / volume / RVOL
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    c.price_status = "pending"
                    raise asyncio.TimeoutError("market data candidate budget exhausted")
                fi = await asyncio.wait_for(
                    asyncio.to_thread(lambda: t.fast_info),
                    timeout=max(0.1, min(5.0, remaining)),
                )
                if not c.current_price or c.current_price <= 0:
                    fb_price = getattr(fi, "last_price", None)
                    if fb_price and fb_price > 0:
                        c.current_price = round(fb_price, 4)
                if not c.prior_price or c.prior_price <= 0:
                    fb_prev = getattr(fi, "previous_close", None)
                    if fb_prev and fb_prev > 0:
                        c.prior_price = round(fb_prev, 4)
                if not c.volume:
                    fb_vol = getattr(fi, "last_volume", None)
                    if fb_vol and fb_vol > 0:
                        c.volume = int(fb_vol)
                # Compute RVOL = today's volume / 3-month average daily volume
                avg_daily = getattr(fi, "three_month_average_volume", None)
                if c.volume and avg_daily and avg_daily > 0:
                    c.rvol = round(c.volume / avg_daily, 2)
            except Exception as exc:
                logger.debug("NewsMomentum: yfinance fast_info fallback failed for %s: %s", c.ticker, exc)

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                c.price_status = "pending"
                raise asyncio.TimeoutError("market data candidate budget exhausted")
            info = await asyncio.wait_for(
                asyncio.to_thread(lambda: t.info),
                timeout=max(0.1, min(5.0, remaining)),
            )
            c.float_shares = info.get("floatShares")
            c.market_cap = info.get("marketCap")
            c.short_interest = info.get("shortPercentOfFloat")
        except Exception as exc:
            if isinstance(exc, asyncio.TimeoutError):
                c.price_status = "pending"
            logger.debug("NewsMomentum: yfinance info fetch failed for %s: %s", c.ticker, exc)

        # Recompute move_pct now that we may have fetched fallback price/prior
        if c.prior_price and c.current_price and c.prior_price > 0:
            c.move_pct = round(((c.current_price - c.prior_price) / c.prior_price) * 100, 2)

        # Set derived categories
        if c.current_price:
            c.price_bucket = self._price_bucket(c.current_price)
            if c.price_status != "pending":
                c.price_status = "complete"
        elif c.price_status != "pending":
            c.price_status = "missing"
        c.float_category = self._float_category(c.float_shares)
        c.market_cap_category = self._market_cap_category(c.market_cap)

    async def _refresh_candidate(self, c: NewsMomentumCandidate, historical_stats: Optional[dict]) -> None:
        """Refresh an existing candidate with live market data and recompute scores.

        This is critical for catching delayed moves — e.g. news drops at 5:31 AM
        but the stock doesn't move until 9:05 AM premarket.
        """
        # Re-fetch current price/volume
        await self._enrich_with_market_data(c)

        # Recompute move percentage from prior close
        if c.prior_price and c.prior_price > 0 and c.current_price:
            c.move_pct = round(((c.current_price - c.prior_price) / c.prior_price) * 100, 2)

        # Recompute all scores
        c.news_impact_score = self._compute_impact_score(c)
        # Re-apply velocity bonus that was earned from cross-source detection
        if c.velocity_score:
            c.news_impact_score = min(100.0, c.news_impact_score + c.velocity_score)
        c.news_reaction_score = self._compute_reaction_score(c)
        er = compute_expected_return_score(c, historical_stats)
        c.expected_return_score = er.score
        cp = compute_continuation_probability(c, historical_stats)
        c.continuation_probability = cp.same_day_continuation
        md = compute_multi_day_continuation(c, cp, historical_stats)
        c.multi_day_continuation_score = md.multi_day_score
        c.next_day_continuation_probability = md.next_day_continuation_probability
        c.two_day_continuation_probability = md.two_day_continuation_probability
        c.five_day_continuation_probability = md.five_day_continuation_probability
        c.next_day_gap_up_probability = md.next_day_gap_up_probability
        # estimate_move_range returns a dict; update fields on the existing model
        move = estimate_move_range(c)
        c.estimated_move.conservative_pct = move["conservative_pct"]
        c.estimated_move.bullish_pct = move["bullish_pct"]
        c.estimated_move.extreme_pct = move["extreme_pct"]
        if c.current_price:
            c.estimated_move.conservative_target = round(c.current_price * (1 + move["conservative_pct"] / 100), 4)
            c.estimated_move.bullish_target = round(c.current_price * (1 + move["bullish_pct"] / 100), 4)
            c.estimated_move.extreme_target = round(c.current_price * (1 + move["extreme_pct"] / 100), 4)
        c.bull_bear = self._generate_bull_bear(c)
        c.oracle_action = determine_oracle_action(c, cp, md)
        c.scored_at = datetime.now(timezone.utc)
        self._log_rocket_shadow_prediction(c, source_pipeline="news_momentum_refresh")

    def _compute_impact_score(self, c: NewsMomentumCandidate) -> float:
        from src.core.agentic.news_momentum_impact_scorer import score_news_impact
        s = score_news_impact(
            catalyst_sub_type=c.catalyst_sub_type,
            catalyst_category=c.catalyst_category,
            float_cat=c.float_category,
            market_cap_cat=c.market_cap_category,
            rvol=c.rvol,
            spread_pct=c.spread_pct,
            move_pct=c.move_pct,
            is_negative=c.is_negative,
            is_vague=c.is_vague,
            short_interest=c.short_interest,
        )
        return s.composite_score

    def _compute_reaction_score(self, c: NewsMomentumCandidate) -> float:
        from src.core.agentic.news_momentum_reaction_engine import compute_reaction_metrics, score_news_reaction
        m = compute_reaction_metrics(
            price_before=c.prior_price,
            price_current=c.current_price,
            volume_before=None,
            volume_current=c.volume,
        )
        s = score_news_reaction(m, c.rvol)
        c.trap_risk = min(s.composite_score * 0.3 + (100 - s.continuation_quality) * 0.7, 100.0)
        return s.composite_score

    def _generate_bull_bear(self, c: NewsMomentumCandidate):
        from src.core.agentic.news_momentum_models import BullBearCase
        bb = BullBearCase()

        # Why it matters
        bb.why_it_matters = f"{c.ticker} has {c.catalyst_sub_type.value.replace('_', ' ')} news with a {c.news_impact_score} impact score."

        # Bull case
        bull_parts = []
        if c.float_category.value in ("ultra_low", "low"):
            bull_parts.append("Low float means explosive moves possible.")
        if c.news_impact_score > 70:
            bull_parts.append("High-impact catalyst has strong historical continuation.")
        if c.continuation_probability > 60:
            bull_parts.append("Price action shows continuation signals.")
        if c.dilution_risk < 20:
            bull_parts.append("No dilution risk detected.")
        bb.bull_case = " ".join(bull_parts) if bull_parts else "Bull case depends on market reaction."

        # Bear case
        bear_parts = []
        if c.trap_risk > 50:
            bear_parts.append("High trap risk — potential bull trap.")
        if c.dilution_risk > 40:
            bear_parts.append("Dilution risk present.")
        if c.move_pct > 100:
            bear_parts.append("Already extended — chasing is dangerous.")
        if c.exhaustion_probability > 50:
            bear_parts.append("Exhaustion signals detected.")
        bb.bear_case = " ".join(bear_parts) if bear_parts else "Bear case limited if catalyst is genuine."

        return bb

    # ── Telegram ──────────────────────────────────────────────────────────────

    def _get_thresholds_for_session(self, session: SessionType) -> Tuple[float, float, float, float]:
        """Return thresholds for a specific session (not current time)."""
        cfg = self.config
        if session == SessionType.PREMARKET:
            return (
                cfg.premarket_impact_threshold,
                cfg.premarket_expected_return_threshold,
                cfg.premarket_continuation_threshold,
                cfg.multi_day_threshold,
            )
        elif session == SessionType.REGULAR:
            # Regular session spans open/midday/power-hour; use open thresholds
            # as the most lenient within regular hours (candidates should alert
            # when detected, not wait for threshold to drop at session change)
            return (
                cfg.open_impact_threshold,
                cfg.open_expected_return_threshold,
                cfg.open_continuation_threshold,
                cfg.multi_day_threshold,
            )
        elif session == SessionType.AFTER_HOURS:
            return (
                cfg.premarket_impact_threshold,
                cfg.premarket_expected_return_threshold,
                cfg.premarket_continuation_threshold,
                cfg.multi_day_threshold,
            )
        else:
            return (
                cfg.premarket_impact_threshold,
                cfg.premarket_expected_return_threshold,
                cfg.premarket_continuation_threshold,
                cfg.multi_day_threshold,
            )

    def _is_bad_ticker(self, ticker: str) -> bool:
        """Check if ticker is in the shared bad_tickers list (delisted/invalid)."""
        try:
            import json
            bad_path = DATA_DIR / "bad_tickers.json"
            if not bad_path.exists():
                return False
            with open(bad_path, encoding="utf-8") as f:
                bad = set(json.load(f))
            return ticker.upper() in bad
        except Exception:
            return False

    def _should_send_telegram(self, c: NewsMomentumCandidate, adaptive: dict) -> bool:
        """Wrapper: log blocked gate decisions to the shadow logger, then return."""
        c._block_reason = None  # type: ignore[attr-defined]
        allowed = self._should_send_telegram_impl(c, adaptive)
        c.gate_decision_at = datetime.now(timezone.utc)
        # Skip allowed candidates here. A passed gate is not the same thing as
        # a delivered Telegram alert; sent alerts are recorded by the learning
        # tracker, and send failures are logged in _send_telegram_alert.
        if not allowed and not c.telegram_sent:
            reason = getattr(c, "_block_reason", None)
            try:
                self._shadow_logger.log_candidate(c, was_blocked=(not allowed), block_reason=reason)
            except Exception as exc:
                logger.debug("Shadow log failed for %s: %s", c.ticker, exc)
            # Trace a blocked candidate only the first time it is blocked for a
            # given reason. A blocked-but-active candidate is re-gated on every
            # refresh (~45s, up to 24h), so tracing each pass floods the latency
            # log with duplicate rows whose published->gate "latency" merely
            # tracks the headline ageing — which reads as ever-growing alert
            # latency in the diagnostics view. The eventual pass/send is recorded
            # separately by the learning tracker, so this loses no signal.
            if reason != getattr(c, "_last_traced_block_reason", None):
                c._last_traced_block_reason = reason  # type: ignore[attr-defined]
                try:
                    trace_candidate(
                        c,
                        alert_sent=False,
                        blocked_reason=reason,
                        alert_type="news_momentum_gate",
                        fast_path=False,
                    )
                except Exception as exc:
                    logger.debug("Latency trace failed for blocked %s: %s", c.ticker, exc)
        return allowed

    def _should_send_telegram_impl(self, c: NewsMomentumCandidate, adaptive: dict) -> bool:
        """Determine if a candidate should trigger a Telegram alert."""
        now = datetime.now(timezone.utc)

        # Already alerted — never re-alert the same candidate
        if c.telegram_sent:
            logger.debug("Telegram gate: %s already alerted", c.ticker)
            c._block_reason = "already_alerted"  # type: ignore[attr-defined]
            return False

        # Skip tickers known to be delisted / unfetchable. This block is terminal
        # — a ticker on the persistent bad-list won't become valid on a refresh —
        # so deactivate it to drop it from the ~45s refresh/re-gate loop. Left
        # active, it would be re-enriched and re-evaluated for up to 24h, wasting
        # market-data calls with no possible upside.
        if self._is_bad_ticker(c.ticker):
            logger.debug("Telegram gate: %s is bad ticker", c.ticker)
            c._block_reason = "bad_ticker"  # type: ignore[attr-defined]
            c.is_active = False
            return False

        # Reject if we have no live price data (e.g. delisted ticker or rate-limit failure).
        # MAX-SPEED exception: a fresh strongly-positive catalyst alerts even without a
        # live quote — missing the move while waiting on a rate-limited price fetch is
        # worse than alerting with price "pending". Known-bad/delisted tickers are
        # already filtered by _is_bad_ticker above, so this won't fire on junk.
        if c.current_price is None or c.current_price <= 0:
            if _headline_is_fresh_bullish(c.headline, c.is_negative, c.trap_risk, c.dilution_risk):
                logger.info("Telegram gate: %s ⚡ no live price but fresh bullish catalyst — allowing", c.ticker)
            else:
                logger.debug("Telegram gate: %s has no price", c.ticker)
                c._block_reason = "no_price"  # type: ignore[attr-defined]
                return False

        # Check ticker-level cooldown (default 4h)
        last_alert = _aware_utc(self._alert_cooldown.get(c.ticker))
        if last_alert and (now - last_alert).total_seconds() < self.config.telegram_cooldown_minutes * 60:
            logger.debug("Telegram gate: %s on ticker cooldown", c.ticker)
            c._block_reason = "ticker_cooldown"  # type: ignore[attr-defined]
            return False

        # Check headline-level cooldown (4h) — prevents repeat alerts on the same news
        headline_key = f"{c.ticker}:{self._headline_hash(c.headline)}"
        last_headline_alert = _aware_utc(self._headline_alert_cooldown.get(headline_key))
        if last_headline_alert and (now - last_headline_alert).total_seconds() < 4 * 3600:
            logger.debug("Telegram gate: %s headline on cooldown", c.ticker)
            c._block_reason = "headline_cooldown"  # type: ignore[attr-defined]
            return False

        memory_key = self._alert_memory_key(c.ticker, c.headline)
        memory = getattr(self, "_alert_memory", {}).get(memory_key)
        if memory:
            try:
                last_seen = _aware_utc(datetime.fromisoformat(str(memory.get("sent_at"))))
            except Exception:
                last_seen = None
            memory_window = max(
                self.config.telegram_cooldown_minutes * 60,
                int(max(24.0, float(self.config.news_max_age_hours or 0)) * 3600),
            )
            if last_seen and (now - last_seen).total_seconds() < memory_window:
                logger.debug("Telegram gate: %s suppressed by alert memory", c.ticker)
                c._block_reason = "alert_memory"  # type: ignore[attr-defined]
                return False

        # Stale candidate guard: don't alert on candidates > 24 hours old.
        # News momentum can play out over a full session — premarket news at 5am
        # often runs at 9:30am open, and overnight news from prior session can
        # still drive moves the next morning. We were previously hard-blocking
        # at 4h which silently killed alerts for genuinely-still-running plays.
        detected_at = _aware_utc(c.detected_at)
        age_hours = (now - detected_at).total_seconds() / 3600 if detected_at else 0
        if age_hours > 24.0:
            aggressive_until = _aware_utc(c.aggressive_refresh_until)
            if not (aggressive_until and now < aggressive_until):
                if not (c.velocity_score and c.velocity_score >= 8):
                    logger.debug("Telegram gate: %s stale (>24h)", c.ticker)
                    c._block_reason = f"stale({age_hours:.1f}h)"  # type: ignore[attr-defined]
                    return False

        published_at_for_stale_guard = _aware_utc(c.published_at)
        if published_at_for_stale_guard and self.config.news_max_age_hours:
            published_age_hours = (now - published_at_for_stale_guard).total_seconds() / 3600
            if published_age_hours > float(self.config.news_max_age_hours):
                logger.info(
                    "Telegram gate: %s stale published_at (%.1fh > %.1fh)",
                    c.ticker, published_age_hours, float(self.config.news_max_age_hours),
                )
                c._block_reason = f"stale_published({published_age_hours:.1f}h)"  # type: ignore[attr-defined]
                return False

        flash_assessment = assess_bullish_flash(c, self.config, now=now)
        bullish_flash = flash_assessment.should_flash
        if bullish_flash:
            c._bullish_flash = flash_assessment  # type: ignore[attr-defined]
            if (c.catalyst_category == CatalystCategory.UNKNOWN
                    and flash_assessment.suggested_category is not None):
                c.catalyst_category = flash_assessment.suggested_category
            if (c.catalyst_sub_type in {CatalystSubType.OTHER, CatalystSubType.VAGUE_PR}
                    and flash_assessment.suggested_sub_type is not None):
                c.catalyst_sub_type = flash_assessment.suggested_sub_type
            logger.info(
                "Telegram gate: %s BULLISH FLASH candidate score=%.1f reasons=%s",
                c.ticker, flash_assessment.score, ",".join(flash_assessment.reasons),
            )

        # Use the candidate's ORIGINAL session thresholds
        sess_impact, sess_return, sess_cont, sess_multi = self._get_thresholds_for_session(c.session)

        # Adaptive thresholds can only LOWER session thresholds (relax when
        # historical quality is high). They MUST NOT raise them — historical
        # outcome classification is overly strict (avg MFE=+9% but >80% classified
        # as no_follow_through because the 5% bar is too low for slow-developing
        # premarket news), which produced 77.9/82.9 thresholds and silently
        # blocked every legitimate alert.
        if adaptive.get("adapted"):
            min_impact = min(sess_impact, adaptive.get("news_impact", sess_impact))
            min_return = min(sess_return, adaptive.get("expected_return", sess_return))
            min_cont = min(sess_cont, adaptive.get("continuation", sess_cont))
            min_multi = min(sess_multi, adaptive.get("multi_day", sess_multi))
        else:
            min_impact = sess_impact
            min_return = sess_return
            min_cont = sess_cont
            min_multi = sess_multi

        # Under-$10 leniency: lower-priced stocks move differently; lower the
        # bars when the user wants sub-$10 alerts so real catalysts don't get
        # silently dropped due to low float / low volume scores.
        under_1_lenient = (
            self.config.under_1_only
            and c.current_price is not None
            and c.current_price < self.config.under_1_max_price
        )
        if under_1_lenient:
            _u_floor = self.config.under_1_min_floor
            _u_step = self.config.under_1_lenient_step_down
            min_impact = max(_u_floor, min_impact - _u_step)
            min_return = max(_u_floor, min_return - _u_step)
            min_cont = max(_u_floor, min_cont - _u_step)
            min_multi = max(_u_floor, min_multi - _u_step)

        # ── High-conviction catalyst fast-path ───────────────────────────
        # Historical win rates show these catalyst types print > 40% wins:
        #   phase_1 (86%), fda_approval (67%), government_contract (52%),
        #   ai_partnership (44%), nvidia_partnership, openai_partnership,
        #   bitcoin_treasury, fda_clearance, breakthrough_therapy,
        #   pdufa, fast_track, share_buyback.
        # When the news is one of these, drop the bar by another 10 points
        # so we alert quickly on real catalysts before price fully runs.
        # Set lifted to module-level _HIGH_CONVICTION_CATALYSTS so the
        # stacking-score helper can reference the same source of truth.
        high_conviction = c.catalyst_sub_type in _HIGH_CONVICTION_CATALYSTS and not c.is_negative
        if high_conviction:
            _hc_floor = self.config.high_conviction_min_floor
            _hc_step = self.config.high_conviction_step_down
            min_impact = max(_hc_floor, min_impact - _hc_step)
            min_return = max(_hc_floor, min_return - _hc_step)
            min_cont = max(_hc_floor, min_cont - _hc_step)
            logger.debug(
                "Telegram gate: %s high-conviction catalyst (%s) — thresholds lowered",
                c.ticker, c.catalyst_sub_type.value if c.catalyst_sub_type else "?",
            )

        # ── FIRST-MOVER SPEED TIER (V23.3) ───────────────────────────────
        # The whole point of this system is to alert BEFORE the wave hits.
        # If we just saw the news (< 90 seconds old) AND the headline has
        # strong positive language AND the catalyst is recognized AND there
        # are no negative red-flags — ALERT IMMEDIATELY without waiting for
        # price confirmation. By the time price moves +20%, the trade is over.
        #
        # This is intentionally aggressive on the FAST path because the cost
        # of a missed +500% mover is far higher than a small false-positive rate.
        if bullish_flash:
            min_impact = min(min_impact, self.config.bullish_flash_min_impact)
            min_return = min(min_return, self.config.bullish_flash_min_return)
            min_cont = min(min_cont, self.config.bullish_flash_min_continuation)
            min_multi = min(min_multi, self.config.bullish_flash_min_multi_day)

        first_mover: bool = False
        published_age_secs: Optional[float] = None
        detected_age_secs: Optional[float] = None
        try:
            published_at = _aware_utc(c.published_at)
            detected_at = _aware_utc(c.detected_at)
            published_age_secs = (now - published_at).total_seconds() if published_at else None
            detected_age_secs = (now - detected_at).total_seconds() if detected_at else None
            c.published_age_seconds = published_age_secs
            c.detected_age_seconds = detected_age_secs
            timestamp_confidence = (getattr(c, "timestamp_confidence", "HIGH") or "HIGH").upper()
            c.freshness_confidence = "HIGH" if (
                timestamp_confidence == "HIGH"
                and published_age_secs is not None
                and detected_age_secs is not None
            ) else "LOW"
            # Speed tier fires when the news is fresh (within the configured
            # window) by both publication time and detection time. This avoids
            # treating old headlines as breaking merely because a parser saw
            # them late. Missing published_at is intentionally not eligible.
            # Keyword lists + safety live in _headline_is_fresh_bullish so the
            # no-price bypass above uses the exact same definition.
            max_age = self.config.first_mover_max_age_seconds
            if (published_age_secs is not None
                    and detected_age_secs is not None
                    and 0 <= published_age_secs <= max_age
                    and 0 <= detected_age_secs <= max_age
                    and c.freshness_confidence == "HIGH"
                    and not getattr(c, "_stale_on_arrival", False)
                    and _headline_is_fresh_bullish(c.headline, c.is_negative,
                                                   c.trap_risk, c.dilution_risk)):
                first_mover = True
        except Exception as exc:
            logger.debug("first-mover check failed for %s: %s", c.ticker, exc)
            first_mover = False

        if first_mover:
            logger.info(
                "Telegram gate: %s ⚡ FIRST-MOVER SPEED TIER — news_age=%.0fs "
                "(bypassing impact_floor & ML veto)",
                c.ticker, published_age_secs if published_age_secs is not None else -1,
            )
            c._first_mover = True  # type: ignore[attr-defined]
            # Aggressive threshold relaxation — we're racing the market
            min_impact = min(min_impact, self.config.first_mover_min_impact)
            min_return = min(min_return, self.config.first_mover_min_return)
            min_cont = min(min_cont, self.config.first_mover_min_continuation)
            min_multi = min(min_multi, self.config.first_mover_min_multi_day)

        if (
            (not bullish_flash)
            and (not first_mover)
            and c.move_pct is not None
            and c.move_pct >= 10.0
            and _is_late_reaction_headline(c.headline)
        ):
            logger.info(
                "Telegram gate: %s late reaction headline suppressed "
                "(move=%.1f%% headline=%s)",
                c.ticker, c.move_pct or 0.0, c.headline,
            )
            c._block_reason = "late_reaction_headline"  # type: ignore[attr-defined]
            return False

        # ── PRICE-ACTION BREAKOUT OVERRIDE (V23.2) ───────────────────────
        # The market is the ultimate catalyst classifier. If a stock is moving
        # violently (>=20% move) with elevated volume (RVOL >= 3x) on a news
        # event, ALERT IT regardless of whether our hardcoded catalyst keywords
        # recognized the headline. This is how we catch novel catalysts like
        # "lunar semiconductor manufacturing" (ASTC, +497%) that no regex
        # will ever pre-match.
        #
        # Two tiers:
        #   - MEGA breakout  (move >= 35% AND rvol >= 5)  → HIGH_CONVICTION
        #   - Strong breakout (move >= 20% AND rvol >= 3) → STANDARD
        #
        # Safety guards:
        #   - Skip if the headline is explicitly negative (offering, going concern)
        #   - Skip if trap_risk is high (likely a pump)
        #   - Skip if dilution_risk is high
        breakout_tier: Optional[str] = None
        try:
            move = abs(c.move_pct or 0.0)
            rvol = c.rvol or 0.0
            high_trap = (c.trap_risk or 0.0) >= self.config.high_trap_block_threshold
            high_dilution = (c.dilution_risk or 0.0) >= self.config.high_dilution_block_threshold
            safe = (not c.is_negative) and (not high_trap) and (not high_dilution)
            if safe and move >= self.config.breakout_mega_move_pct and rvol >= self.config.breakout_mega_rvol:
                breakout_tier = "MEGA"
            elif safe and move >= self.config.breakout_strong_move_pct and rvol >= self.config.breakout_strong_rvol:
                breakout_tier = "STRONG"
        except Exception:
            breakout_tier = None

        # Record unknown-catalyst candidates so we can learn missed patterns
        if (self._unknown_learner is not None
                and c.catalyst_category == CatalystCategory.UNKNOWN):
            try:
                self._unknown_learner.record_unknown(
                    ticker=c.ticker,
                    headline=c.headline,
                    price_at_detection=c.current_price,
                    move_pct_at_detection=c.move_pct or 0.0,
                    rvol_at_detection=c.rvol or 0.0,
                )
            except Exception as exc:
                logger.debug("UnknownLearner record failed: %s", exc)

        if breakout_tier:
            logger.info(
                "Telegram gate: %s PRICE BREAKOUT OVERRIDE — tier=%s "
                "(move=%.1f%% rvol=%.1fx) bypassing impact_floor",
                c.ticker, breakout_tier, c.move_pct or 0.0, c.rvol or 0.0,
            )
            c._breakout_tier = breakout_tier  # type: ignore[attr-defined]
            # Lower the impact floor dramatically — the market has confirmed
            # something is happening even if our classifier missed it.
            min_impact = min(min_impact, self.config.breakout_relax_min_impact)
            min_return = min(min_return, self.config.breakout_relax_min_impact)
            min_cont = min(min_cont, self.config.breakout_relax_min_continuation)

        # News impact score is the PRIMARY gate — must always clear a floor.
        # Large-cap stocks can have artificially high continuation probability
        # from liquidity alone; we don't alert on weak-news large caps.
        impact_floor = max(
            self.config.impact_floor_under_1 if under_1_lenient else self.config.impact_floor_default,
            min_impact - 10,
        )
        # Breakout override: relax impact floor when market has confirmed the move
        if breakout_tier == "MEGA":
            impact_floor = self.config.breakout_mega_impact_floor
        elif breakout_tier == "STRONG":
            impact_floor = self.config.breakout_strong_impact_floor
        # First-mover: aggressively low floor — we're racing the market
        if first_mover:
            impact_floor = min(impact_floor, self.config.first_mover_impact_floor)
        if bullish_flash:
            impact_floor = min(impact_floor, self.config.bullish_flash_impact_floor)
        if (not bullish_flash) and c.news_impact_score < impact_floor:
            logger.info(
                "Telegram gate: %s impact=%.1f < floor=%.1f (under_10=%s)",
                c.ticker, c.news_impact_score, impact_floor, under_1_lenient,
            )
            c._block_reason = f"impact_floor({c.news_impact_score:.1f}<{impact_floor:.1f})"  # type: ignore[attr-defined]
            return False

        # BOTH impact and expected return must clear their thresholds.
        # This removes weak single-score pass-throughs that generate low-quality noise.
        # Speed-tier alerts (bullish_flash / first_mover) bypass — those scores
        # are inflated by price reaction, which by definition hasn't happened yet
        # when we want to be first.
        score_ok = (
            c.news_impact_score >= min_impact and
            c.expected_return_score >= min_return
        )
        if (not bullish_flash) and (not first_mover) and not score_ok:
            logger.info(
                "Telegram gate: %s score gate failed "
                "(impact=%.1f/%.1f return=%.1f/%.1f)",
                c.ticker, c.news_impact_score, min_impact,
                c.expected_return_score, min_return,
            )
            c._block_reason = f"score_gate(imp={c.news_impact_score:.1f}/{min_impact:.0f},ret={c.expected_return_score:.1f}/{min_return:.0f})"  # type: ignore[attr-defined]
            return False

        # Require material price movement — no 0.1% blips.
        # BUT: speed-tier alerts (bullish_flash / first_mover) intentionally
        # fire BEFORE price confirmation. Requiring a 3% move first defeats
        # the entire point of getting in early; observed today, median
        # move_at_alert was already 22.7% because we waited for price
        # before any gate would pass.
        # High-conviction catalysts (FDA, drug_launch, M&A, contracts...) bypass
        # this too: requiring a 3% move before alerting on a known-explosive
        # catalyst defeats "alert before the spike". PRFX (drug_launch, impact 61)
        # was blocked here at only +2.95% — exactly the move we wanted to front-run.
        if (
            (not bullish_flash)
            and (not first_mover)
            and (not high_conviction)
            and c.move_pct is not None
            and abs(c.move_pct) < 3.0
        ):
            logger.info(
                "Telegram gate: %s move too small (%.2f%% < 3%%)", c.ticker, c.move_pct
            )
            c._block_reason = f"small_move({c.move_pct:.2f}%)"  # type: ignore[attr-defined]
            return False

        # ── Catalyst-quality precision filter (V24, backtest-driven) ──────
        # 11,785-alert backtest: recognized catalysts win 59%, the unrecognized
        # "other"/vague bucket (96% of volume) wins 3.8%. Suppress unrecognized
        # catalysts UNLESS corroborated by a real market signal — that's exactly
        # how the rare "other"-bucket monsters (VSA +1083%) reveal themselves, so
        # precision rises without losing explosion-catching. Speed tiers and
        # confirmed breakouts already carry their own conviction and bypass.
        if (
            self.config.require_catalyst_or_confirmation
            and not bullish_flash and not first_mover and not breakout_tier
        ):
            weak_catalyst = (
                c.catalyst_sub_type in {CatalystSubType.OTHER, CatalystSubType.VAGUE_PR}
                or c.catalyst_category == CatalystCategory.UNKNOWN
            )
            if weak_catalyst:
                corroborated = (
                    (c.rvol or 0) >= self.config.weak_catalyst_min_rvol
                    or abs(c.move_pct or 0) >= self.config.weak_catalyst_min_move_pct
                    or (getattr(c, "prenews_anomaly_score", 0) or 0) >= self.config.weak_catalyst_min_anomaly
                    or (c.velocity_score or 0) >= 8
                )
                if not corroborated:
                    logger.info(
                        "Telegram gate: %s weak catalyst (%s) with no confirmation "
                        "(rvol=%.1f move=%.1f%%) — suppressed",
                        c.ticker, c.catalyst_sub_type.value, c.rvol or 0, c.move_pct or 0,
                    )
                    c._block_reason = "weak_catalyst_unconfirmed"  # type: ignore[attr-defined]
                    return False

        # ── Chase-the-spike guard (V23.4) ─────────────────────────────────
        # If the stock has ALREADY moved past the chase cap, the alert is
        # arriving after the bulk of the move and entries are usually traps.
        # Only fresh/strong catalyst paths bypass this. A breakout by itself can
        # still be too late to chase after the move is already extended.
        late_chase_cap = min(self.config.chase_spike_max_move_pct, self.config.late_chase_block_move_pct)
        high_conviction_recent = (
            high_conviction
            and published_age_secs is not None
            and detected_age_secs is not None
            and 0 <= published_age_secs <= self.config.high_conviction_late_chase_max_age_seconds
            and 0 <= detected_age_secs <= self.config.high_conviction_late_chase_max_age_seconds
        )
        is_early_enough_for_chase = (
            first_mover
            or bullish_flash
            or (high_conviction_recent and (c.move_pct is None or c.move_pct <= late_chase_cap))
        )
        if (
            not is_early_enough_for_chase
            and c.move_pct is not None
            and c.move_pct > late_chase_cap
        ):
            logger.info(
                "Telegram gate: %s late-chase suppressed (move=%.1f%% > cap=%.1f%%)",
                c.ticker, c.move_pct, late_chase_cap,
            )
            c._block_reason = f"late_chase({c.move_pct:.1f}%)"  # type: ignore[attr-defined]
            return False

        daily_cap = int(getattr(self.config, "daily_standard_alert_cap_per_ticker", 1) or 0)
        daily_cap_bypass = first_mover or bullish_flash or high_conviction_recent
        if daily_cap > 0 and not daily_cap_bypass:
            sent_today = self._sent_alerts_today_for_ticker(c.ticker, now)
            if sent_today >= daily_cap:
                logger.info(
                    "Telegram gate: %s daily standard alert cap reached (%d/%d)",
                    c.ticker, sent_today, daily_cap,
                )
                c._block_reason = f"daily_ticker_cap({sent_today}/{daily_cap})"  # type: ignore[attr-defined]
                return False

        # Price filter — explicit rejection for out-of-range prices.
        # BUT: breakout and first-mover candidates bypass the MAX price check
        # because rockets frequently run from $2 → $15+ and we must alert them.
        effective_max = 10.0 if self.config.under_1_only else self.config.max_price
        # When under_1_only is on, user wants ALL sub-$10 stocks including $0.05; ignore min_price floor
        effective_min = 0.01 if self.config.under_1_only else self.config.min_price

        # Check MIN price (always enforce — avoid sub-penny trash)
        if c.current_price is not None and c.current_price < effective_min:
            logger.info(
                "Telegram gate: %s price=$%.2f below min %.2f",
                c.ticker, c.current_price, effective_min,
            )
            c._block_reason = f"price_too_low(${c.current_price:.2f}<{effective_min:.2f})"  # type: ignore[attr-defined]
            return False

        # Check MAX price — SKIP for breakout/first-mover rockets
        is_rocket = bool(breakout_tier) or first_mover or bullish_flash
        if not is_rocket and c.current_price is not None and c.current_price > effective_max:
            logger.info(
                "Telegram gate: %s price=$%.2f above max %.2f (non-breakout)",
                c.ticker, c.current_price, effective_max,
            )
            c._block_reason = f"price_too_high(${c.current_price:.2f}>{effective_max:.2f})"  # type: ignore[attr-defined]
            return False

        # Risk filters
        if c.dilution_risk > 70 or c.trap_risk > 80:
            logger.info("Telegram gate: %s risk too high (dilution=%.1f trap=%.1f)", c.ticker, c.dilution_risk, c.trap_risk)
            c._block_reason = f"risk(dil={c.dilution_risk:.0f},trap={c.trap_risk:.0f})"  # type: ignore[attr-defined]
            return False
        if c.is_negative:
            logger.info("Telegram gate: %s classified as negative", c.ticker)
            c._block_reason = "negative_news"  # type: ignore[attr-defined]
            return False
        if (not bullish_flash) and c.is_vague and c.news_impact_score < 80:
            logger.info("Telegram gate: %s vague + low impact", c.ticker)
            c._block_reason = "vague_low_impact"  # type: ignore[attr-defined]
            return False

        # ── UNKNOWN-catalyst gate (V23.4) ─────────────────────────────────
        # If the classifier couldn't identify the catalyst type we have no
        # category-specific calibration to lean on. For aged candidates this
        # is noise; for FRESH news the classifier just hasn't had enough
        # context yet — so we let speed-tier and breakout-confirmed paths
        # through even when category is UNKNOWN. Otherwise require BOTH a
        # strong impact score AND cross-source confirmation.
        if (
            (not bullish_flash)
            and (not first_mover)
            and (not breakout_tier)
            and self.config.block_unknown_catalyst
            and c.catalyst_category == CatalystCategory.UNKNOWN
        ):
            high_impact = c.news_impact_score >= self.config.unknown_catalyst_min_impact
            multi_source = (c.sources_seen_count or 1) >= self.config.unknown_catalyst_min_sources
            if not (high_impact and multi_source):
                logger.info(
                    "Telegram gate: %s UNKNOWN catalyst (impact=%.1f sources=%d)",
                    c.ticker, c.news_impact_score, c.sources_seen_count or 1,
                )
                c._block_reason = (
                    f"unknown_catalyst(imp={c.news_impact_score:.1f},src={c.sources_seen_count or 1})"
                )  # type: ignore[attr-defined]
                return False

        # ── Cheap-stock multi-source guard (V23.4) ────────────────────────
        # Sub-$2 tickers are disproportionately involved in pump/manipulation
        # patterns. Require cross-source confirmation OR a high-conviction
        # catalyst before alerting. Confirmed rockets bypass — they already
        # have price-action confirmation.
        if (
            (not bullish_flash)
            and not (bool(breakout_tier) or first_mover)
            and not high_conviction
            and c.current_price is not None
            and c.current_price < self.config.cheap_stock_max_price
            and (c.sources_seen_count or 1) < self.config.cheap_stock_min_sources
        ):
            logger.info(
                "Telegram gate: %s cheap-stock single-source (price=$%.2f sources=%d)",
                c.ticker, c.current_price, c.sources_seen_count or 1,
            )
            c._block_reason = (
                f"cheap_stock_single_source(${c.current_price:.2f},src={c.sources_seen_count or 1})"
            )  # type: ignore[attr-defined]
            return False

        # ── SEC Structural Intelligence gate ─────────────────────────────
        # If SEC engine flagged this ticker as a structural trap (going
        # concern, toxic financing, very high trap risk), veto the alert
        # entirely — regardless of how exciting the news is.
        try:
            sec_adj = getattr(c, "_sec_adjustment", None)
            if sec_adj is not None and sec_adj.veto_alert:
                logger.info(
                    "Telegram gate: %s blocked by SEC veto — %s",
                    c.ticker, sec_adj.veto_reason,
                )
                c._block_reason = f"sec_veto({sec_adj.veto_reason})"  # type: ignore[attr-defined]
                return False
        except Exception as exc:
            logger.debug("SEC gate skipped for %s: %s", c.ticker, exc)

        # ── ML-aware gate ────────────────────────────────────────────────
        # The self-trained model can both VETO (confident junk) and AMPLIFY
        # (confident winner). Veto blocks bad alerts; Amplify lowers
        # thresholds for borderline gems the model recognizes.
        if bullish_flash:
            logger.info(
                "Telegram gate: %s PASSED via BULLISH CATALYST FLASH "
                "(score=%.1f reasons=%s)",
                c.ticker, flash_assessment.score, ",".join(flash_assessment.reasons),
            )
            return True

        ml_boost_applied = False
        try:
            ml_pred: MLPrediction = self._ml_engine.predict(c)
            # Stash on candidate for later use (record creation, telegram message)
            c._ml_prediction = ml_pred  # type: ignore[attr-defined]
            # HARD FLOOR: when the model is in use, win_prob must be > 25%
            # regardless of confidence. This filters out 5–15% "noise" alerts
            # and ensures every Telegram alert has a meaningful upside expectancy.
            # BUT: breakout/first-mover candidates bypass this — the market has
            # already confirmed the move with price action (move >= 20%).
            MIN_WIN_PROB = self.config.ml_min_win_probability
            is_confirmed_rocket = bool(breakout_tier) or first_mover
            # High-conviction catalysts bypass ML hard floor — the model may not
            # have been trained on newer sub-types yet (e.g. warrant_overhang_removal)
            ml_bypass = high_conviction and c.news_impact_score >= self.config.ml_bypass_impact_threshold
            if (ml_pred.used_model and ml_pred.win_probability < MIN_WIN_PROB
                    and not is_confirmed_rocket and not ml_bypass):
                logger.info(
                    "Telegram gate: %s blocked by ML hard floor "
                    "(win_prob=%.2f < %.2f, conf=%.2f, model=%s)",
                    c.ticker, ml_pred.win_probability, MIN_WIN_PROB,
                    ml_pred.confidence, ml_pred.model_version,
                )
                c._block_reason = f"ml_hard_floor(win={ml_pred.win_probability:.2f})"  # type: ignore[attr-defined]
                return False
            if ml_pred.used_model and ml_pred.confidence >= self.config.ml_veto_min_confidence:
                if ml_pred.win_probability < self.config.ml_veto_win_probability:
                    # VETO: model is confident this is a loser
                    # BUT: breakout/first-mover OR high-conviction candidates bypass
                    if not is_confirmed_rocket and not ml_bypass:
                        logger.info(
                            "Telegram gate: %s blocked by ML (win_prob=%.2f conf=%.2f model=%s)",
                            c.ticker, ml_pred.win_probability, ml_pred.confidence,
                            ml_pred.model_version,
                        )
                        c._block_reason = f"ml_veto(win={ml_pred.win_probability:.2f})"  # type: ignore[attr-defined]
                        return False
                    else:
                        logger.info(
                            "Telegram gate: %s ML veto OVERRIDDEN — confirmed rocket (breakout=%s first_mover=%s)",
                            c.ticker, bool(breakout_tier), first_mover,
                        )
                elif ml_pred.win_probability > 0.75:
                    # AMPLIFY: model is confident this is a winner — lower bars
                    boost = 1.0 - ((ml_pred.win_probability - 0.75) / 0.25) * 0.10
                    min_impact = max(min_impact * boost, min_impact * 0.90)
                    min_return = max(min_return * boost, min_return * 0.90)
                    min_cont = max(min_cont * boost, min_cont * 0.90)
                    ml_boost_applied = True
                    logger.info(
                        "Telegram gate: %s ML boost applied (win_prob=%.2f conf=%.2f) "
                        "thresholds lowered to impact=%.1f return=%.1f cont=%.1f",
                        c.ticker, ml_pred.win_probability, ml_pred.confidence,
                        min_impact, min_return, min_cont,
                    )
        except Exception as exc:
            logger.debug("ML gate skipped for %s: %s", c.ticker, exc)

        # Re-evaluate score gate if ML boost was applied
        if ml_boost_applied:
            score_ok = (
                c.news_impact_score >= min_impact and
                c.expected_return_score >= min_return
            )
            if not score_ok:
                logger.info(
                    "Telegram gate: %s still failed after ML boost "
                    "(impact=%.1f/%.1f return=%.1f/%.1f)",
                    c.ticker, c.news_impact_score, min_impact,
                    c.expected_return_score, min_return,
                )
                c._block_reason = f"score_gate_after_ml(imp={c.news_impact_score:.1f}/{min_impact:.0f},ret={c.expected_return_score:.1f}/{min_return:.0f})"  # type: ignore[attr-defined]
                return False

        # ── Winner Targeting Layer (V23) ─────────────────────────────────
        # All base gates have passed. Now run the 7 winner filters:
        # runner profile, ML tier, catalyst×market-cap band, reaction confirm,
        # sector hype boost, headline strength. Each can veto OR amplify.
        try:
            ml_pred = getattr(c, "_ml_prediction", None)
            win_prob = ml_pred.win_probability if ml_pred else 0.5
            used_model = bool(ml_pred and ml_pred.used_model)

            # Reaction confirmation is only meaningful in regular session
            # (premarket has thin volume and gappy moves; force-confirming
            # would silently kill alerts on news that's seconds old).
            # SPEED-PATH BYPASS: when first-mover, bullish-flash, breakout, or
            # the no-price bypass already fired, the candidate is explicitly
            # an "alert BEFORE confirmation" decision. Re-imposing the 120s
            # "let it cook" window here re-introduces the exact small_move /
            # too_fresh failure mode that historically killed PRFX-class
            # alerts during regular session.
            no_price_bypass_active = c.current_price is None or c.current_price <= 0
            speed_path = (
                bullish_flash
                or first_mover
                or bool(breakout_tier)
                or no_price_bypass_active
            )
            require_confirm = c.session == SessionType.REGULAR and not speed_path

            if self._sector_hype is None:
                self._sector_hype = SectorHypeTracker()
            assessment = assess_winner(
                c, win_prob, used_model, self._sector_hype,
                require_reaction_confirmation=require_confirm,
            )

            # PRICE-ACTION BREAKOUT OVERRIDE (V23.2):
            # If price already confirmed (>=20% move + RVOL >=3), the ML veto
            # is wrong. The market has spoken. Promote and force-alert.
            bo_tier = getattr(c, "_breakout_tier", None)
            if bo_tier:
                from src.core.agentic.news_momentum_winners import MLTier
                target = "HIGH_CONVICTION" if bo_tier == "MEGA" else "STANDARD"
                if assessment.ml_tier.label in {"VETO", "WATCH"}:
                    assessment.ml_tier = MLTier(target, "🚀", 15.0, True)
                    assessment.should_alert = True
                    assessment.block_reason = None
                    assessment.priority_score += 50.0 if bo_tier == "MEGA" else 25.0
                    assessment.promotion_reason = f"price_breakout_{bo_tier}"  # type: ignore[attr-defined]
                    logger.info(
                        "Winner layer: %s rescued by PRICE BREAKOUT (%s) → %s",
                        c.ticker, bo_tier, target,
                    )

            # FIRST-MOVER SPEED TIER (V23.3):
            # When news is fresh (<= 90s) and has strong positive language,
            # ML veto is unreliable (the model can't see what the market will
            # do in the next 5 minutes). Force-alert to beat the wave.
            if getattr(c, "_first_mover", False):
                from src.core.agentic.news_momentum_winners import MLTier
                if assessment.ml_tier.label in {"VETO", "WATCH"}:
                    assessment.ml_tier = MLTier("STANDARD", "⚡", 15.0, True)
                    assessment.should_alert = True
                    assessment.block_reason = None
                    assessment.priority_score += 35.0
                    assessment.promotion_reason = "first_mover_speed"  # type: ignore[attr-defined]
                    logger.info(
                        "Winner layer: %s rescued by FIRST-MOVER SPEED TIER",
                        c.ticker,
                    )

            # HIGH-CONVICTION CATALYST RESCUE:
            # When a known strong catalyst (e.g. warrant_overhang_removal,
            # listing_compliance, analyst_upgrade) is blocked by ML veto because
            # the model hasn't been trained on that sub-type yet, rescue it.
            if (high_conviction and c.news_impact_score >= 50.0
                    and assessment.ml_tier.label in {"VETO", "WATCH"}):
                from src.core.agentic.news_momentum_winners import MLTier
                assessment.ml_tier = MLTier("STANDARD", "🔥", 10.0, True)
                assessment.should_alert = True
                assessment.block_reason = None
                assessment.priority_score += 20.0
                assessment.promotion_reason = "high_conviction_rescue"  # type: ignore[attr-defined]
                logger.info(
                    "Winner layer: %s rescued by HIGH-CONVICTION catalyst rescue (%s)",
                    c.ticker, c.catalyst_sub_type.value,
                )

            # UPGRADE #4 — Big-Winner model: if dedicated rocket model says
            # this looks like a 25%+ mover, promote to HIGH_CONVICTION.
            try:
                # Reuse the prediction computed during scoring (where it now
                # drives the candidate ranking) instead of re-predicting.
                bw_pred = getattr(c, "_big_winner_prediction", None)
                if bw_pred is None:
                    bw_pred = self._big_winner_ml.predict(c)
                    c._big_winner_prediction = bw_pred  # type: ignore[attr-defined]
                # Only promote when the rocket model is highly confident AND
                # the candidate isn't already vetoed (we don't rescue trash).
                if (bw_pred.used_model
                        and bw_pred.rocket_probability >= 0.70
                        and assessment.ml_tier.label in {"STANDARD", "WATCH"}):
                    from src.core.agentic.news_momentum_winners import MLTier
                    assessment.ml_tier = MLTier(
                        "HIGH_CONVICTION", "🚀", 15.0, True,
                    )
                    assessment.should_alert = True
                    assessment.block_reason = None
                    assessment.priority_score += 30.0
                    assessment.promotion_reason = (  # type: ignore[attr-defined]
                        f"big_winner_model({bw_pred.rocket_probability:.2f})"
                    )
            except Exception as exc:
                logger.debug("BigWinner predict skipped for %s: %s", c.ticker, exc)

            # Stash on candidate so the telegram message and shadow log can use it
            c._winner_assessment = assessment  # type: ignore[attr-defined]

            if not assessment.should_alert:
                logger.info(
                    "Telegram gate: %s blocked by winner layer — %s",
                    c.ticker, assessment.block_reason,
                )
                c._block_reason = assessment.block_reason  # type: ignore[attr-defined]
                return False

            logger.info(
                "Telegram gate: %s PASSED — tier=%s runner=%d/4 priority=%.1f hype=%.2fx",
                c.ticker, assessment.ml_tier.label, assessment.runner.score,
                assessment.priority_score, assessment.sector_multiplier,
            )
        except Exception as exc:
            logger.debug("Winner layer skipped for %s: %s", c.ticker, exc)
            logger.info("Telegram gate: %s PASSED — alerting", c.ticker)
        return True

    async def _send_telegram_alert(self, c: NewsMomentumCandidate) -> bool:
        """Send a formatted Telegram alert."""
        text = self._format_telegram_message(c)
        try:
            c.telegram_alert_id = c.telegram_alert_id or self._stable_alert_id(c)
            c.telegram_enqueue_at = datetime.now(timezone.utc)
            sent = await send_telegram_alert(
                text,
                parse_mode="HTML",
                alert_id=c.telegram_alert_id,
                ticker=c.ticker,
                alert_type="news_momentum",
                priority=2 if getattr(c, "_first_mover", False) else 5,
            )
            now_ts = datetime.now(timezone.utc)
            # Always record cooldown + alert memory, even when the direct send
            # fails and the message is enqueued for outbox retry. Without this,
            # the next scan sees no suppression state and can spam the same
            # ticker again before the outbox delivers.
            self._alert_cooldown[c.ticker] = now_ts
            # Record headline cooldown so the same news can't re-alert
            headline_key = f"{c.ticker}:{self._headline_hash(c.headline)}"
            self._headline_alert_cooldown[headline_key] = now_ts
            self._remember_sent_alert(c, now_ts)
            # Prune old headline cooldowns (keep 24h — must exceed the
            # news-freshness window so the same headline can't re-alert
            # within its own fresh lifetime).
            cutoff = now_ts - timedelta(hours=24)
            self._headline_alert_cooldown = {
                k: v for k, v in self._headline_alert_cooldown.items()
                if (_aware_utc(v) or now_ts) >= cutoff
            }
            # Persist cooldowns immediately so a crash/restart doesn't lose them
            self._save_cooldowns()
            self._save_headline_cooldowns()
            if sent:
                c.telegram_sent = True
                c.telegram_sent_at = now_ts
                try:
                    self._save_candidates()
                except Exception as persist_exc:
                    logger.debug("NewsMomentum: candidate persistence after alert failed: %s", persist_exc)

                try:
                    # Record for learning — capture ALL features for future ML training
                    ml_pred = getattr(c, "_ml_prediction", None)
                    record = TelegramAlertRecord(
                        alert_id=c.telegram_alert_id,
                        ticker=c.ticker,
                        sent_at=datetime.now(timezone.utc),
                        headline=c.headline,
                        source=c.source.value if hasattr(c.source, "value") else str(c.source),
                        published_at=c.published_at,
                        catalyst_type=c.catalyst_sub_type,
                        session_type=c.session,
                        price_at_alert=c.current_price or 0.0,
                        news_impact_score=c.news_impact_score,
                        expected_return_score=c.expected_return_score,
                        continuation_probability=c.continuation_probability,
                        multi_day_score=c.multi_day_continuation_score,
                        # Extended ML features — captured at alert time so retrains use
                        # the exact same data the gate saw.
                        catalyst_category=c.catalyst_category.value if c.catalyst_category else None,
                        float_category=c.float_category.value if c.float_category else None,
                        market_cap_category=c.market_cap_category.value if c.market_cap_category else None,
                        move_pct_at_alert=c.move_pct,
                        rvol_at_alert=c.rvol,
                        volume_at_alert=c.volume,
                        spread_pct_at_alert=c.spread_pct,
                        trap_risk_at_alert=c.trap_risk,
                        dilution_risk_at_alert=c.dilution_risk,
                        velocity_score_at_alert=c.velocity_score,
                        sources_seen_count=c.sources_seen_count,
                        is_negative=c.is_negative,
                        is_vague=c.is_vague,
                        is_delayed_reaction=c.is_delayed_reaction,
                        ml_predicted_win_prob=ml_pred.win_probability if ml_pred else None,
                        ml_model_version=ml_pred.model_version if ml_pred else None,
                        **self._sec_record_fields(c),
                    )
                    self._telegram_learning.record_alert(record)
                except Exception as exc:
                    logger.warning(
                        "NewsMomentum: Telegram sent for %s but learning record failed: %s",
                        c.ticker, exc,
                    )
                logger.info("NewsMomentum: Telegram alert sent for %s", c.ticker)
            else:
                try:
                    self._shadow_logger.log_candidate(
                        c,
                        was_blocked=True,
                        block_reason="telegram_send_failed",
                    )
                    self._shadow_logger.flush()
                except Exception as exc:
                    logger.debug("Telegram send-failure shadow log failed for %s: %s", c.ticker, exc)
                logger.warning(
                    "NewsMomentum: Telegram service returned false for %s; "
                    "check TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID and Telegram API warnings",
                    c.ticker,
                )
            try:
                trace_candidate(
                    c,
                    alert_sent=sent,
                    blocked_reason=None if sent else "telegram_send_failed",
                    alert_type="news_momentum",
                    fast_path=False,
                )
            except Exception as trace_exc:
                logger.debug("Latency trace failed for Telegram %s: %s", c.ticker, trace_exc)
            return sent
        except Exception as exc:
            logger.warning("NewsMomentum: Telegram send failed for %s: %s", c.ticker, exc)
            try:
                trace_candidate(
                    c,
                    alert_sent=False,
                    blocked_reason=f"telegram_send_exception:{exc}",
                    alert_type="news_momentum",
                    fast_path=False,
                )
            except Exception as trace_exc:
                logger.debug("Latency trace failed for Telegram exception %s: %s", c.ticker, trace_exc)
            return False

    def _format_telegram_message(self, c: NewsMomentumCandidate) -> str:
        """Format a rich Telegram HTML message."""
        action = c.oracle_action.value.replace("_", " ")
        multi_class = c.multi_day_class.value.replace("_", " ")

        # Format published timestamp
        published_str = "Unknown"
        if c.published_at:
            if isinstance(c.published_at, str):
                published_str = c.published_at
            else:
                published_str = c.published_at.strftime("%Y-%m-%d %H:%M:%S %Z")

        # Format time frame badge
        session_emoji = {"premarket": "🌅", "regular": "☀️", "after_hours": "🌙"}.get(c.session.value, "📅")
        session_label = c.session.value.replace("_", " ").title()

        # Adaptive insight
        cat_stats = self._telegram_learning.get_catalyst_quality(c.catalyst_sub_type)
        adaptive_text = ""
        if not cat_stats.get("insufficient", True):
            cont_rate = cat_stats.get("continuation_rate", 50)
            adaptive_text = f"\n📊 Similar alerts historically continued {cont_rate}% of the time."

        # ── Winner Targeting header (V23) ─────────────────────────────────
        winner_text = ""
        try:
            wa = getattr(c, "_winner_assessment", None)
            if wa is not None:
                runner_traits = []
                if wa.runner.low_float: runner_traits.append("low-float")
                if wa.runner.cheap_price: runner_traits.append("cheap")
                if wa.runner.early_gap: runner_traits.append("gapping")
                if wa.runner.high_rvol: runner_traits.append("hi-RVOL")
                traits_line = ", ".join(runner_traits) if runner_traits else "—"
                hype_line = ""
                if wa.sector_multiplier > 1.0:
                    hype_line = f" | 🔥 sector hot ({wa.sector_multiplier:.2f}x)"
                winner_text = (
                    f"\n{wa.ml_tier.emoji} <b>{wa.ml_tier.label.replace('_', ' ')}</b> "
                    f"(priority {wa.priority_score:.0f})\n"
                    f"<b>Runner:</b> {wa.runner.score}/4 [{traits_line}]"
                    f"{hype_line}\n"
                    f"<b>Headline strength:</b> {wa.headline_strength:.0f}/100"
                )
        except Exception:
            pass

        # ── SEC Structural Intelligence section ────────────────────────────
        flash_text = ""
        try:
            flash = getattr(c, "_bullish_flash", None)
            if flash is not None and getattr(flash, "should_flash", False):
                reasons = ", ".join(getattr(flash, "reasons", [])[:5]) or "fresh bullish catalyst"
                flash_text = (
                    f"\n<b>BULLISH CATALYST FLASH</b> "
                    f"(score {getattr(flash, 'score', 0):.0f}/100)\n"
                    f"<b>Why:</b> {reasons}"
                )
        except Exception:
            pass

        sec_text = ""
        try:
            sec_c = getattr(c, "_sec_candidate", None)
            if sec_c is not None:
                s = sec_c.scores
                structure_label = sec_c.dilution_behavior.value.replace("_", " ").upper()
                action_label = sec_c.oracle_action.value.replace("_", " ").upper()
                # Dilution risk classification
                if s.dilution_probability_score >= 60:
                    dil_word = "HIGH"
                elif s.dilution_probability_score >= 30:
                    dil_word = "MODERATE"
                else:
                    dil_word = "LOW"
                # Header — warning vs healthy
                if action_label in {"STRUCTURAL TRAP", "AVOID CHASE"}:
                    sec_header = "⚠️ <b>STRUCTURAL RISK FLAGGED</b>"
                elif s.balance_sheet_quality_score >= 70 and s.dilution_probability_score <= 25:
                    sec_header = "✅ <b>CLEAN STRUCTURE</b>"
                else:
                    sec_header = "📋 <b>SEC INTELLIGENCE</b>"

                flags = []
                if sec_c.atm_active:
                    flags.append("active ATM")
                if sec_c.going_concern_active:
                    flags.append("going concern")
                if s.toxic_financing_score >= 50:
                    flags.append("toxic financing")
                if s.warrant_overhang_score >= 50:
                    flags.append("warrant overhang")
                if s.reverse_split_risk_score >= 50:
                    flags.append("reverse split risk")
                if sec_c.offerings_last_12mo >= 3:
                    flags.append(f"{sec_c.offerings_last_12mo} offerings/12mo")
                flags_line = ", ".join(flags) if flags else "no structural flags"

                sec_text = (
                    f"\n\n{sec_header}\n"
                    f"<b>Structure:</b> {structure_label} | <b>Dilution Risk:</b> {dil_word}\n"
                    f"<b>Dilution Prob:</b> {s.dilution_probability_score:.0f}/100 | "
                    f"<b>Offering Risk:</b> {s.offering_risk_score:.0f}/100\n"
                    f"<b>Cash Runway:</b> {s.cash_runway_score:.0f}/100 | "
                    f"<b>Balance Sheet:</b> {s.balance_sheet_quality_score:.0f}/100\n"
                    f"<b>Struct. Trap Risk:</b> {s.structural_trap_risk_score:.0f}/100\n"
                    f"<b>SEC Action:</b> {action_label}\n"
                    f"<b>Flags:</b> {flags_line}"
                )
                if sec_c.why_it_matters:
                    sec_text += f"\n<b>Why:</b> {sec_c.why_it_matters[:200]}"
        except Exception as exc:
            logger.debug("SEC telegram section failed for %s: %s", c.ticker, exc)

        return (
            f"<b>🚨 HIGH IMPACT NEWS MOMENTUM</b>\n\n"
            f"<b>📅 Published:</b> {published_str}\n"
            f"<b>⏰ Time Frame:</b> {session_emoji} {session_label}\n"
            f"<b>🔔 Detected:</b> {c.detected_at.strftime('%H:%M:%S') if c.detected_at else 'N/A'}\n"
            f"{winner_text}"
            f"{flash_text}\n\n"
            f"<b>Ticker:</b> {c.ticker}\n"
            f"<b>Headline:</b> {c.headline[:200]}\n"
            f"<b>Source:</b> {c.source.value}\n\n"
            f"<b>Price:</b> ${c.current_price or 'N/A'} | <b>Move:</b> {c.move_pct}%\n"
            f"<b>Volume:</b> {c.volume or 'N/A'} | <b>RVOL:</b> {c.rvol or 'N/A'}\n"
            f"<b>Float:</b> {c.float_category.value} | <b>MCap:</b> {c.market_cap_category.value}\n\n"
            f"<b>Catalyst:</b> {c.catalyst_sub_type.value.replace('_', ' ').title()}\n"
            f"<b>News Impact:</b> {c.news_impact_score}/100\n"
            f"<b>Reaction Score:</b> {c.news_reaction_score}/100\n"
            f"<b>Expected Return:</b> {c.expected_return_score}/100\n"
            f"<b>Continuation:</b> {c.continuation_probability}%\n"
            f"<b>Multi-Day Score:</b> {c.multi_day_continuation_score}/100\n"
            f"<b>Next-Day Cont:</b> {c.next_day_continuation_probability}%\n"
            f"<b>2-Day Cont:</b> {c.two_day_continuation_probability}%\n"
            f"<b>5-Day Cont:</b> {c.five_day_continuation_probability}%\n\n"
            f"<b>Trap Risk:</b> {c.trap_risk}/100 | <b>Dilution:</b> {c.dilution_risk}/100\n"
            f"<b>Exhaustion:</b> {c.exhaustion_probability}/100\n\n"
            f"<b>Oracle Action:</b> {action}\n"
            f"<b>Multi-Day Class:</b> {multi_class}\n\n"
            f"<b>Est. Moves:</b>\n"
            f"  Conservative: +{c.estimated_move.conservative_pct}%\n"
            f"  Bullish: +{c.estimated_move.bullish_pct}%\n"
            f"  Extreme: +{c.estimated_move.extreme_pct}%\n\n"
            f"<b>Bull Case:</b> {c.bull_bear.bull_case[:150]}\n\n"
            f"<b>Bear Case:</b> {c.bull_bear.bear_case[:150]}"
            f"{adaptive_text}"
            f"{sec_text}"
        )

    # ── Trap Warning ──────────────────────────────────────────────────────────

    async def send_trap_warning(self, c: NewsMomentumCandidate) -> bool:
        """Send a trap warning Telegram alert."""
        text = (
            f"<b>⚠️ MOMENTUM TRAP WARNING</b>\n\n"
            f"<b>Ticker:</b> {c.ticker}\n"
            f"<b>Headline:</b> {c.headline[:200]}\n\n"
            f"<b>Trap Risk:</b> {c.trap_risk}/100\n"
            f"<b>Dilution Risk:</b> {c.dilution_risk}/100\n"
            f"<b>Exhaustion:</b> {c.exhaustion_probability}/100\n\n"
            f"<b>Oracle Recommendation:</b> DO NOT CHASE\n\n"
            f"<b>Why:</b> {c.bull_bear.bear_case[:200]}"
        )
        try:
            return await send_telegram_alert(text, parse_mode="HTML")
        except Exception:
            return False

    # ── Missed Winner Detection ────────────────────────────────────────────

    async def _check_missed_winners(self) -> None:
        """Retrospectively check recent candidates for missed winners."""
        if not self.config.learning_enabled:
            return

        # Check candidates from last 2 hours that haven't been resolved
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        recent = [
            c for c in self._candidates
            if (_aware_utc(c.detected_at) or datetime.min.replace(tzinfo=timezone.utc)) > cutoff
            and not c.resolved
        ]

        for c in recent:
            try:
                prices = await self._fetch_post_news_prices(c)
                if prices:
                    alert_sent = c.telegram_sent
                    record = self._missed_learning.analyze_candidate(c, alert_sent, prices)
                    if record and record.missed:
                        await self._send_missed_winner_alert(record)
                        # Mark as resolved so we don't re-check
                        c.resolved = True
            except Exception as exc:
                logger.debug("Missed winner check error for %s: %s", c.ticker, exc)

    async def _fetch_post_news_prices(self, c: NewsMomentumCandidate) -> Optional[dict]:
        """Fetch prices after news to calculate actual moves."""
        try:
            import yfinance as yf
            import pandas as pd

            def _fetch_hist():
                return yf.Ticker(c.ticker).history(period="5d", interval="1h")

            # Run the blocking yfinance call OFF the event loop with a hard
            # timeout. Inline, it froze the entire async server for minutes when
            # yfinance was throttled (e.g. on cloud hosts like Railway).
            try:
                hist = await asyncio.wait_for(asyncio.to_thread(_fetch_hist), timeout=15.0)
            except asyncio.TimeoutError:
                logger.debug("Post-news price fetch timed out for %s", c.ticker)
                return None
            if hist.empty:
                return None

            # Find index after news time
            news_time = _aware_utc(c.published_at or c.detected_at)
            if not news_time:
                return None
            # yfinance returns naive timestamps; strip tz so pandas compares cleanly
            news_time_naive = news_time.replace(tzinfo=None)

            mask = hist.index > pd.Timestamp(news_time_naive)
            post = hist[mask]
            if post.empty:
                return None

            price_at_news = c.current_price or hist.iloc[0]["Close"]

            # Get prices at different time frames
            price_1h = post.iloc[0]["High"] if len(post) >= 1 else None
            price_same_day = post.iloc[:7]["High"].max() if len(post) >= 1 else None
            price_2day = post.iloc[:14]["High"].max() if len(post) >= 1 else None
            price_5day = post["High"].max() if len(post) >= 1 else None

            return {
                "price_at_news": float(price_at_news) if price_at_news else None,
                "price_1h": float(price_1h) if price_1h else None,
                "price_same_day": float(price_same_day) if price_same_day else None,
                "price_2day": float(price_2day) if price_2day else None,
                "price_5day": float(price_5day) if price_5day else None,
                "max_price": float(price_5day) if price_5day else None,
            }
        except Exception as exc:
            logger.debug("Price fetch error for %s: %s", c.ticker, exc)
            return None

    async def _send_missed_winner_alert(self, record: "MissedWinnerRecord") -> bool:
        """Send admin Telegram alert for a missed winner."""
        try:
            text = self._missed_learning.format_admin_alert(record)
            return await send_telegram_alert(text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Missed winner admin alert failed: %s", exc)
            return False

    # ── Public API ──────────────────────────────────────────────────────────

    def get_active_candidates(self) -> List[NewsMomentumCandidate]:
        return [c for c in self._candidates if c.is_active]

    def get_candidate(self, ticker: str) -> Optional[NewsMomentumCandidate]:
        return self._candidate_by_ticker.get(ticker.upper())

    def get_top_ranked(self, limit: int = 20) -> List[NewsMomentumCandidate]:
        active = self.get_active_candidates()
        active.sort(key=lambda c: c.expected_return_score, reverse=True)
        return active[:limit]

    def get_top_by_category(self, category: str, limit: int = 10) -> List[NewsMomentumCandidate]:
        active = [c for c in self.get_active_candidates() if c.catalyst_category.value == category]
        active.sort(key=lambda c: c.expected_return_score, reverse=True)
        return active[:limit]

    def deactivate_candidate(self, ticker: str) -> bool:
        c = self._candidate_by_ticker.get(ticker.upper())
        if c:
            c.is_active = False
            self._save_candidates()
            return True
        return False

    def get_stats(self) -> dict:
        return {
            "total_candidates": len(self._candidates),
            "active_candidates": len([c for c in self._candidates if c.is_active]),
            "telegram_alerts_sent": len(self._telegram_learning._alerts),
            "telegram_quality": self._telegram_learning.get_overall_quality().model_dump(),
            "catalyst_stats": self._catalyst_learning.get_all_stats(),
            "adaptive_thresholds": self._telegram_learning.get_adaptive_thresholds(),
            "ml_engine": self._ml_engine.get_status(),
        }
