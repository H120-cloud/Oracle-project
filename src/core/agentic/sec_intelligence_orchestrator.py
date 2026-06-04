"""
SEC Intelligence Orchestrator (V23)

Top-level controller for the SEC Filing Intelligence & Dilution Risk Engine.

Responsibilities:
- Scan a ticker (or a list of tickers) and produce a SECIntelligenceCandidate
- Persist candidates + filings to disk (JSON)
- Provide quick lookups for the momentum orchestrator
- Compute cross-analysis adjustments (momentum × SEC) via `apply_to_momentum`
- Manage learning outcomes (shadow-mode promotion gate)
- Provide manual scan + background-loop entrypoints

Network calls are isolated to `sec_edgar_fetcher` and are wrapped in
try/except so the rest of Oracle keeps working even if SEC is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.core.agentic.sec_dilution_history import summarize_history
from src.core.agentic.sec_edgar_fetcher import (
    SEC_USER_AGENT,
    fetch_filing_text,
    fetch_recent_filings,
    resolve_ticker_to_cik,
)
from src.core.agentic.sec_filing_analyzer import apply_analysis_to_filing
from src.core.agentic.sec_filing_models import (
    DilutionBehavior,
    DilutionEvent,
    FilingSentiment,
    FilingType,
    OracleStructuralAction,
    PositiveStructureSignal,
    SECFiling,
    SECIntelligenceCandidate,
    StructuralAdjustment,
    StructuralAlertOutcome,
    StructuralScores,
    SurvivalSignal,
)
from src.core.agentic.sec_scoring_engine import (
    compute_all_scores,
    derive_action_and_sentiment,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic/sec")
DATA_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATES_FILE = DATA_DIR / "candidates.json"
FILINGS_FILE = DATA_DIR / "filings.json"
OUTCOMES_FILE = DATA_DIR / "outcomes.json"
SHADOW_FILE = DATA_DIR / "shadow_scores.json"


# ── Persistence helpers ─────────────────────────────────────────────────────


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.debug("Failed to load %s: %s", path, e)
        return default


def _save_json(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, default=str, indent=2))
    except Exception as e:
        logger.debug("Failed to save %s: %s", path, e)


# ── Cross-analysis: SEC → momentum score adjustments ────────────────────────


def compute_adjustment(candidate: SECIntelligenceCandidate) -> StructuralAdjustment:
    """Translate structural scores into deltas applied to momentum scores."""
    s = candidate.scores
    adj = StructuralAdjustment()
    reasons: List[str] = []

    # ── Penalties (dilution / survival risks) ──────────────────────────────
    if s.dilution_probability_score >= 60:
        adj.expected_return_delta -= 15
        adj.continuation_probability_delta -= 12
        adj.multi_day_continuation_delta -= 20
        adj.trap_risk_delta += 18
        adj.exhaustion_probability_delta += 15
        adj.dilution_risk_delta += 25
        reasons.append("High active dilution probability")

    if s.toxic_financing_score >= 50:
        adj.expected_return_delta -= 20
        adj.continuation_probability_delta -= 15
        adj.multi_day_continuation_delta -= 25
        adj.trap_risk_delta += 25
        adj.dilution_risk_delta += 30
        reasons.append("Toxic financing structure present")

    if s.warrant_overhang_score >= 50:
        adj.multi_day_continuation_delta -= 15
        adj.exhaustion_probability_delta += 12
        reasons.append("Significant warrant overhang caps continuation")

    if s.survival_risk_score >= 60:
        adj.expected_return_delta -= 25
        adj.multi_day_continuation_delta -= 30
        adj.trap_risk_delta += 25
        reasons.append("Going-concern / survival risk flagged")

    if s.offering_risk_score >= 60:
        adj.continuation_probability_delta -= 15
        adj.multi_day_continuation_delta -= 18
        adj.trap_risk_delta += 18
        adj.dilution_risk_delta += 20
        reasons.append("Imminent offering risk (S-3 / 424B5 / active ATM)")

    if s.reverse_split_risk_score >= 50:
        adj.expected_return_delta -= 15
        adj.multi_day_continuation_delta -= 20
        adj.trap_risk_delta += 15
        reasons.append("Reverse split risk detected")

    if candidate.dilution_behavior == DilutionBehavior.SERIAL_DILUTER:
        adj.expected_return_delta -= 10
        adj.multi_day_continuation_delta -= 12
        adj.trap_risk_delta += 10
        reasons.append("Serial diluter — history of frequent offerings")
    elif candidate.dilution_behavior == DilutionBehavior.TOXIC_DILUTION_PATTERN:
        adj.expected_return_delta -= 20
        adj.multi_day_continuation_delta -= 25
        adj.trap_risk_delta += 22
        reasons.append("Toxic dilution pattern — historical shareholder destruction")

    # ── Bonuses (clean structure) ─────────────────────────────────────────
    if s.balance_sheet_quality_score >= 75 and s.dilution_probability_score <= 20:
        adj.expected_return_delta += 8
        adj.continuation_probability_delta += 8
        adj.multi_day_continuation_delta += 12
        adj.dilution_risk_delta -= 15
        reasons.append("Clean balance sheet + no active dilution → boosted")

    if s.cash_runway_score >= 80:
        adj.multi_day_continuation_delta += 8
        reasons.append("Strong cash runway supports multi-day continuation")

    if candidate.overall_filing_sentiment == FilingSentiment.VERY_POSITIVE:
        adj.expected_return_delta += 6
        reasons.append("Filings sentiment very positive (debt payoff / buyback)")

    # ── Veto: structural trap or going concern ────────────────────────────
    if candidate.oracle_action == OracleStructuralAction.STRUCTURAL_TRAP:
        adj.veto_alert = True
        adj.veto_reason = "STRUCTURAL_TRAP — going concern or toxic financing"
    elif (
        candidate.oracle_action == OracleStructuralAction.AVOID_CHASE
        and s.structural_trap_risk_score >= 80
    ):
        adj.veto_alert = True
        adj.veto_reason = "AVOID_CHASE — very high structural trap risk"

    adj.reasons = reasons
    return adj


# ── Orchestrator ────────────────────────────────────────────────────────────


class SECIntelligenceOrchestrator:
    """Manage SEC intelligence for the tickers we care about."""

    def __init__(self, shadow_mode_min_samples: int = 100):
        self._candidates: Dict[str, SECIntelligenceCandidate] = {}
        self._outcomes: List[StructuralAlertOutcome] = []
        self.shadow_mode_min_samples = shadow_mode_min_samples
        self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_state(self) -> None:
        raw_cands = _load_json(CANDIDATES_FILE, [])
        for item in raw_cands:
            try:
                c = SECIntelligenceCandidate(**item)
                self._candidates[c.ticker.upper()] = c
            except Exception:
                continue
        raw_outs = _load_json(OUTCOMES_FILE, [])
        for item in raw_outs:
            try:
                self._outcomes.append(StructuralAlertOutcome(**item))
            except Exception:
                continue

    def _save_state(self) -> None:
        _save_json(
            CANDIDATES_FILE,
            [c.model_dump(mode="json") for c in self._candidates.values()],
        )
        _save_json(
            OUTCOMES_FILE,
            [o.model_dump(mode="json") for o in self._outcomes],
        )

    # ── Public API ────────────────────────────────────────────────────────

    def get_candidate(self, ticker: str) -> Optional[SECIntelligenceCandidate]:
        return self._candidates.get(ticker.upper())

    def all_candidates(self) -> List[SECIntelligenceCandidate]:
        return list(self._candidates.values())

    def upsert_candidate(self, candidate: SECIntelligenceCandidate) -> None:
        self._candidates[candidate.ticker.upper()] = candidate
        self._save_state()

    def structural_traps(self) -> List[SECIntelligenceCandidate]:
        return [
            c for c in self._candidates.values()
            if c.oracle_action in {
                OracleStructuralAction.AVOID_CHASE,
                OracleStructuralAction.STRUCTURAL_TRAP,
            }
        ]

    def clean_watchlist(self) -> List[SECIntelligenceCandidate]:
        return [
            c for c in self._candidates.values()
            if c.dilution_behavior == DilutionBehavior.CLEAN_STRUCTURE
            and c.scores.balance_sheet_quality_score >= 70
        ]

    def serial_diluters(self) -> List[SECIntelligenceCandidate]:
        return [
            c for c in self._candidates.values()
            if c.dilution_behavior in {
                DilutionBehavior.SERIAL_DILUTER,
                DilutionBehavior.TOXIC_DILUTION_PATTERN,
            }
        ]

    # ── Core: scan a single ticker ────────────────────────────────────────

    async def scan_ticker(
        self,
        ticker: str,
        max_filings: int = 15,
        analyze_text: bool = True,
        client: Optional[httpx.AsyncClient] = None,
    ) -> SECIntelligenceCandidate:
        """Fetch latest filings, analyze each, score, and persist."""
        ticker = ticker.upper().strip()
        own_client = client is None
        if own_client:
            client = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": SEC_USER_AGENT})
        try:
            cik: Optional[str] = None
            existing = self._candidates.get(ticker)
            if existing and existing.cik:
                cik = existing.cik
            else:
                try:
                    cik = await resolve_ticker_to_cik(ticker, client)
                except Exception as e:
                    logger.debug("CIK resolve failed for %s: %s", ticker, e)

            filings: List[SECFiling] = []
            if cik:
                try:
                    filings = await fetch_recent_filings(ticker, cik, max_filings, client)
                except Exception as e:
                    logger.debug("Recent filings fetch failed for %s: %s", ticker, e)

            # Analyze text for the most material filings only (cap cost)
            material_forms = {
                FilingType.S_1, FilingType.S_3, FilingType.S_3_ASR,
                FilingType.F_424B5, FilingType.F_424B4, FilingType.F_424B3,
                FilingType.EIGHT_K, FilingType.TEN_Q, FilingType.TEN_K,
                FilingType.DEF_14A, FilingType.NT_10K, FilingType.NT_10Q,
            }
            if analyze_text:
                for f in filings:
                    if f.filing_type not in material_forms:
                        continue
                    try:
                        text = await fetch_filing_text(f, client=client)
                        apply_analysis_to_filing(f, text)
                    except Exception as e:
                        logger.debug("Analyze text failed for %s: %s", f.accession_number, e)

            # If we got no filings, preserve whatever exists
            share_history = existing.share_history if existing else {}
            history = summarize_history(filings, share_history)
            scores = compute_all_scores(filings, history)
            sentiment, action = derive_action_and_sentiment(filings, scores)

            candidate = SECIntelligenceCandidate(
                ticker=ticker,
                cik=cik,
                company_name=existing.company_name if existing else "",
                scores=scores,
                dilution_behavior=history["dilution_behavior"],
                overall_filing_sentiment=sentiment,
                oracle_action=action,
                recent_filings=filings,
                share_history=share_history,
                offerings_last_12mo=history["offerings_last_12mo"],
                reverse_splits_last_36mo=history["reverse_splits_last_36mo"],
                share_growth_pct_12mo=history["share_growth_pct_12mo"],
                atm_active=history["atm_active"],
                going_concern_active=history["going_concern_active"],
                sec_summary=_build_summary(filings, scores, history["dilution_behavior"], action),
                why_it_matters=_build_why_it_matters(filings, scores, action),
                last_updated=datetime.now(timezone.utc),
            )

            self.upsert_candidate(candidate)
            return candidate
        finally:
            if own_client:
                await client.aclose()

    async def scan_tickers(self, tickers: List[str], concurrency: int = 4) -> List[SECIntelligenceCandidate]:
        """Scan multiple tickers concurrently."""
        results: List[SECIntelligenceCandidate] = []
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(timeout=25.0, headers={"User-Agent": SEC_USER_AGENT}) as client:
            async def _one(t: str):
                async with sem:
                    try:
                        r = await self.scan_ticker(t, client=client)
                        results.append(r)
                    except Exception as e:
                        logger.warning("scan_ticker(%s) failed: %s", t, e)
            await asyncio.gather(*[_one(t) for t in tickers])
        return results

    # ── Learning ──────────────────────────────────────────────────────────

    def record_outcome(self, outcome: StructuralAlertOutcome) -> None:
        self._outcomes.append(outcome)
        self._save_state()

    def get_outcomes(self) -> List[StructuralAlertOutcome]:
        return list(self._outcomes)

    def get_stats(self) -> Dict[str, Any]:
        resolved = [o for o in self._outcomes if o.resolved]
        accurate = sum(
            1 for o in resolved
            if (
                o.assessed_action in {OracleStructuralAction.AVOID_CHASE, OracleStructuralAction.STRUCTURAL_TRAP}
                and (o.dilution_occurred_within_30d or o.offering_announced_within_30d)
            )
            or (
                o.assessed_action in {OracleStructuralAction.TRADEABLE, OracleStructuralAction.SWING_WATCH}
                and not (o.dilution_occurred_within_30d or o.offering_announced_within_30d)
            )
        )
        accuracy = accurate / len(resolved) if resolved else 0.0
        return {
            "candidates_tracked": len(self._candidates),
            "outcomes_total": len(self._outcomes),
            "outcomes_resolved": len(resolved),
            "structural_accuracy": round(accuracy, 3),
            "shadow_mode_min_samples": self.shadow_mode_min_samples,
            "ready_for_promotion": len(resolved) >= self.shadow_mode_min_samples,
        }


# ── Summary builders ────────────────────────────────────────────────────────


def _build_summary(
    filings: List[SECFiling],
    scores: StructuralScores,
    behavior: DilutionBehavior,
    action: OracleStructuralAction,
) -> str:
    flags: List[str] = []
    if scores.dilution_probability_score >= 60:
        flags.append("active dilution")
    if scores.toxic_financing_score >= 50:
        flags.append("toxic financing")
    if scores.warrant_overhang_score >= 50:
        flags.append("warrant overhang")
    if scores.survival_risk_score >= 60:
        flags.append("survival risk")
    if scores.offering_risk_score >= 60:
        flags.append("offering risk")
    if scores.reverse_split_risk_score >= 50:
        flags.append("reverse split risk")
    if scores.balance_sheet_quality_score >= 75 and not flags:
        flags.append("clean balance sheet")
    behavior_label = behavior.value.replace("_", " ")
    action_label = action.value.replace("_", " ").upper()
    if flags:
        return f"{action_label} — {', '.join(flags)} | history: {behavior_label}"
    return f"{action_label} — no significant structural flags | history: {behavior_label}"


def _build_why_it_matters(
    filings: List[SECFiling],
    scores: StructuralScores,
    action: OracleStructuralAction,
) -> str:
    parts: List[str] = []
    for f in sorted(filings, key=lambda x: x.filing_date, reverse=True)[:3]:
        if f.why_it_matters and f.filing_materiality_score >= 50:
            parts.append(f"[{f.filing_type.value}] {f.why_it_matters}")
    if not parts:
        if action == OracleStructuralAction.TRADEABLE:
            parts.append("No material dilution risks detected in recent filings.")
        else:
            parts.append("No recent material filings found.")
    return " ".join(parts[:3])


__all__ = [
    "SECIntelligenceOrchestrator",
    "compute_adjustment",
]
