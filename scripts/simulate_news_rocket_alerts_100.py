from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.rocket_model_shadow import RocketModelShadowScorer


RNG = random.Random(42)


ROCKET_HEADLINES = [
    "{ticker} announces FDA approval for breakthrough cancer therapy",
    "{ticker} reports positive Phase 2 topline data with statistically significant endpoint",
    "{ticker} signs strategic NVIDIA AI partnership for commercial rollout",
    "{ticker} to be acquired in all-cash transaction at major premium",
    "{ticker} announces commercial launch of first FDA-cleared product",
    "{ticker} wins $75 million government contract for immediate deployment",
]

STANDARD_HEADLINES = [
    "{ticker} announces new distribution agreement",
    "{ticker} expands partnership with healthcare network",
    "{ticker} receives purchase order from enterprise customer",
    "{ticker} launches upgraded platform for commercial customers",
]

NEGATIVE_HEADLINES = [
    "{ticker} prices registered direct offering with warrants",
    "{ticker} announces 1-for-20 reverse stock split",
    "{ticker} receives Nasdaq minimum bid deficiency notice",
    "{ticker} files mixed shelf registration statement",
]

WEAK_HEADLINES = [
    "{ticker} provides corporate update",
    "{ticker} announces investor presentation",
    "{ticker} comments on recent market activity",
    "{ticker} schedules annual shareholder meeting",
]


def _orch() -> NewsMomentumOrchestrator:
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    return orch


def _case(index: int) -> dict:
    if index < 40:
        group = "rocket_positive"
        template = RNG.choice(ROCKET_HEADLINES)
        expected_alert = True
        expected_rocket = True
        published_age = RNG.randint(20, 240)
        scores = (RNG.uniform(72, 96), RNG.uniform(68, 94), RNG.uniform(64, 92), RNG.uniform(62, 90))
        move_pct = RNG.uniform(8, 45)
        rvol = RNG.uniform(8, 120)
        price = RNG.uniform(0.35, 6.0)
        float_shares = RNG.uniform(1_000_000, 18_000_000)
    elif index < 60:
        group = "standard_positive"
        template = RNG.choice(STANDARD_HEADLINES)
        expected_alert = True
        expected_rocket = False
        published_age = RNG.randint(30, 260)
        scores = (RNG.uniform(55, 78), RNG.uniform(52, 76), RNG.uniform(50, 74), RNG.uniform(45, 70))
        move_pct = RNG.uniform(3.5, 15)
        rvol = RNG.uniform(2.5, 18)
        price = RNG.uniform(1.0, 9.5)
        float_shares = RNG.uniform(12_000_000, 80_000_000)
    elif index < 80:
        group = "negative_or_dilutive"
        template = RNG.choice(NEGATIVE_HEADLINES)
        expected_alert = False
        expected_rocket = False
        published_age = RNG.randint(20, 260)
        scores = (RNG.uniform(10, 45), RNG.uniform(5, 35), RNG.uniform(5, 30), RNG.uniform(5, 25))
        move_pct = RNG.uniform(-12, 8)
        rvol = RNG.uniform(1, 12)
        price = RNG.uniform(0.5, 8.0)
        float_shares = RNG.uniform(20_000_000, 180_000_000)
    elif index < 90:
        group = "stale_positive"
        template = RNG.choice(ROCKET_HEADLINES)
        expected_alert = False
        expected_rocket = True
        published_age = RNG.randint(2_000, 9_000)
        scores = (RNG.uniform(15, 35), RNG.uniform(15, 35), RNG.uniform(15, 35), RNG.uniform(15, 35))
        move_pct = RNG.uniform(0, 2.5)
        rvol = RNG.uniform(1, 3)
        price = RNG.uniform(1.0, 7.0)
        float_shares = RNG.uniform(2_000_000, 25_000_000)
    else:
        group = "weak_vague"
        template = RNG.choice(WEAK_HEADLINES)
        expected_alert = False
        expected_rocket = False
        published_age = RNG.randint(20, 260)
        scores = (RNG.uniform(5, 35), RNG.uniform(5, 35), RNG.uniform(5, 35), RNG.uniform(5, 30))
        move_pct = RNG.uniform(-3, 3)
        rvol = RNG.uniform(0.5, 3)
        price = RNG.uniform(0.5, 10.0)
        float_shares = RNG.uniform(20_000_000, 200_000_000)

    ticker = f"SIM{index:03d}"
    return {
        "ticker": ticker,
        "headline": template.format(ticker=ticker),
        "group": group,
        "expected_alert": expected_alert,
        "expected_rocket": expected_rocket,
        "published_age": published_age,
        "detected_age": RNG.randint(5, 120),
        "scores": scores,
        "move_pct": move_pct,
        "rvol": rvol,
        "price": price,
        "float_shares": float_shares,
    }


def _candidate(case: dict) -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    cat, sub, neg, vague = classify_headline(case["headline"])
    impact, expected, cont, multi = case["scores"]
    price = case["price"]
    prior_price = price / (1 + case["move_pct"] / 100) if case["move_pct"] > -99 else price
    return NewsMomentumCandidate(
        ticker=case["ticker"],
        headline=case["headline"],
        source=NewsSource.FINVIZ,
        source_url="https://example.test/news",
        published_at=now - timedelta(seconds=case["published_age"]),
        detected_at=now - timedelta(seconds=case["detected_age"]),
        session=SessionType.REGULAR,
        catalyst_category=cat if cat else CatalystCategory.UNKNOWN,
        catalyst_sub_type=sub if sub else CatalystSubType.OTHER,
        is_negative=neg,
        is_vague=vague,
        prior_price=round(prior_price, 4),
        current_price=round(price, 4),
        move_pct=round(case["move_pct"], 2),
        volume=int(case["rvol"] * 1_000_000),
        rvol=round(case["rvol"], 2),
        float_shares=round(case["float_shares"]),
        market_cap=round(case["float_shares"] * price),
        news_impact_score=round(impact, 2),
        expected_return_score=round(expected, 2),
        continuation_probability=round(cont, 2),
        multi_day_continuation_score=round(multi, 2),
        dilution_risk=85.0 if "offering" in case["headline"].lower() or "shelf" in case["headline"].lower() else 10.0,
        trap_risk=75.0 if "reverse stock split" in case["headline"].lower() or "deficiency" in case["headline"].lower() else 10.0,
    )


def main() -> None:
    orch = _orch()
    rocket = RocketModelShadowScorer(enabled=True)
    rows = []
    for index in range(100):
        case = _case(index)
        candidate = _candidate(case)
        would_alert = orch._should_send_telegram_impl(candidate, adaptive={})
        pred = rocket.predict_candidate(candidate, source_pipeline="simulation")
        rank = (pred or {}).get("rocket_rank_score")
        major_plus = (pred or {}).get("binary_major_plus_probability")
        monster_plus = (pred or {}).get("binary_monster_plus_probability")
        rocket_detected = bool(rank is not None and rank >= 0.50)
        rows.append({
            **case,
            "catalyst_category": candidate.catalyst_category.value,
            "catalyst_sub_type": candidate.catalyst_sub_type.value,
            "is_negative": candidate.is_negative,
            "is_vague": candidate.is_vague,
            "would_alert": would_alert,
            "block_reason": getattr(candidate, "_block_reason", None),
            "first_mover": bool(getattr(candidate, "_first_mover", False)),
            "freshness_confidence": candidate.freshness_confidence,
            "rocket_rank_score": rank,
            "major_plus_probability": major_plus,
            "monster_plus_probability": monster_plus,
            "rocket_detected": rocket_detected,
        })

    def pct(n: int, d: int) -> float:
        return round((n / d) * 100, 1) if d else 0.0

    expected_alerts = [r for r in rows if r["expected_alert"]]
    expected_non_alerts = [r for r in rows if not r["expected_alert"]]
    expected_rockets = [r for r in rows if r["expected_rocket"]]
    expected_non_rockets = [r for r in rows if not r["expected_rocket"]]
    alerted = [r for r in rows if r["would_alert"]]
    rocket_detected = [r for r in rows if r["rocket_detected"]]
    alerted_rockets = [r for r in rows if r["expected_rocket"] and r["would_alert"]]

    summary = {
        "total_cases": len(rows),
        "news_alert_recall": pct(sum(r["would_alert"] for r in expected_alerts), len(expected_alerts)),
        "news_alert_precision": pct(sum(r["expected_alert"] for r in alerted), len(alerted)),
        "rocket_alert_recall": pct(len(alerted_rockets), len(expected_rockets)),
        "non_alert_specificity": pct(sum(not r["would_alert"] for r in expected_non_alerts), len(expected_non_alerts)),
        "rocket_shadow_recall_at_rank_0_50": pct(sum(r["rocket_detected"] for r in expected_rockets), len(expected_rockets)),
        "rocket_shadow_specificity_at_rank_0_50": pct(sum(not r["rocket_detected"] for r in expected_non_rockets), len(expected_non_rockets)),
        "would_alert_count": len(alerted),
        "rocket_detected_count": len(rocket_detected),
        "avg_rocket_rank_expected_rockets": round(mean([r["rocket_rank_score"] or 0 for r in expected_rockets]), 4),
        "avg_rocket_rank_expected_non_rockets": round(mean([r["rocket_rank_score"] or 0 for r in expected_non_rockets]), 4),
    }

    by_group = {}
    for group in sorted({r["group"] for r in rows}):
        subset = [r for r in rows if r["group"] == group]
        by_group[group] = {
            "cases": len(subset),
            "would_alert": sum(r["would_alert"] for r in subset),
            "alert_rate_pct": pct(sum(r["would_alert"] for r in subset), len(subset)),
            "rocket_detected": sum(r["rocket_detected"] for r in subset),
            "avg_rocket_rank": round(mean([r["rocket_rank_score"] or 0 for r in subset]), 4),
            "top_block_reasons": sorted({r["block_reason"] for r in subset if r["block_reason"]}),
        }

    misses = [
        {
            "ticker": r["ticker"],
            "group": r["group"],
            "headline": r["headline"],
            "block_reason": r["block_reason"],
            "rocket_rank_score": r["rocket_rank_score"],
            "major_plus_probability": r["major_plus_probability"],
        }
        for r in rows
        if r["expected_alert"] and not r["would_alert"]
    ]
    false_alerts = [
        {
            "ticker": r["ticker"],
            "group": r["group"],
            "headline": r["headline"],
            "block_reason": r["block_reason"],
            "rocket_rank_score": r["rocket_rank_score"],
        }
        for r in rows
        if not r["expected_alert"] and r["would_alert"]
    ]

    print(json.dumps({
        "summary": summary,
        "by_group": by_group,
        "misses": misses[:20],
        "false_alerts": false_alerts[:20],
        "model_available": rocket.artifact is not None,
        "model_version": rocket.model_version(),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
