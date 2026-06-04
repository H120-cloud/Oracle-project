"""Inject synthetic TRAP and GREAT records to teach the model the pattern."""
import sys, os, math, random
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
from src.core.agentic.news_momentum_telegram_learning import TelegramAlertRecord
from src.core.agentic.news_momentum_models import (
    CatalystCategory, CatalystSubType, AlertOutcome, PriceBucket,
    FloatCategory, MarketCapCategory, SessionType, NewsSource,
)


def _make_record(
    ticker: str,
    headline: str,
    price: float,
    outcome: AlertOutcome,
    is_negative: bool = False,
    is_vague: bool = False,
    cat: CatalystCategory = CatalystCategory.CORPORATE,
    sub: CatalystSubType = CatalystSubType.OTHER,
    rvol: float = 2.0,
    spread: float = 1.5,
    float_cat: FloatCategory = FloatCategory.MEDIUM,
    mcap_cat: MarketCapCategory = MarketCapCategory.SMALL,
    impact: float = 50.0,
    expected: float = 50.0,
    cont: float = 50.0,
    multi_day: float = 50.0,
    trap: float = 50.0,
    dilution: float = 50.0,
    velocity: float = 0.0,
    sources: int = 1,
    mfe: float = 0.0,
    mae: float = 0.0,
    move_pct: float = 0.0,
    volume: int = 1_000_000,
) -> TelegramAlertRecord:
    """Build a realistic TelegramAlertRecord with specified outcome."""
    now = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 365))
    return TelegramAlertRecord(
        alert_id=str(now.timestamp()) + f"_{ticker}",
        ticker=ticker,
        catalyst_type=sub,
        session_type=SessionType.REGULAR,
        price_at_alert=price,
        news_impact_score=impact,
        expected_return_score=expected,
        continuation_probability=cont,
        multi_day_score=multi_day,
        # Optional fields
        sent_at=now,
        catalyst_category=cat.value,
        float_category=float_cat.value,
        market_cap_category=mcap_cat.value,
        move_pct_at_alert=move_pct,
        rvol_at_alert=rvol,
        volume_at_alert=volume,
        spread_pct_at_alert=spread,
        trap_risk_at_alert=trap,
        dilution_risk_at_alert=dilution,
        velocity_score_at_alert=velocity,
        sources_seen_count=sources,
        is_negative=is_negative,
        is_vague=is_vague,
        is_delayed_reaction=False,
        prenews_anomaly_score=0.0,
        outcome=outcome,
        mfe_pct=mfe,
        mae_pct=mae,
    )


def main():
    orch = NewsMomentumOrchestrator()
    alerts = orch._telegram_learning._alerts
    by_cat = orch._telegram_learning._by_catalyst

    # ── 100 GREAT_ALERT records (big runners, low price, high float, positive catalysts) ──
    print("Generating 100 GREAT records...")
    great_templates = [
        ("FDA approval for novel therapy", CatalystSubType.FDA_APPROVAL, 0.80, 1.2),
        ("positive Phase 3 topline data", CatalystSubType.PHASE_3, 2.50, 3.8),
        ("receives breakthrough therapy designation", CatalystSubType.FAST_TRACK, 1.20, 2.5),
        ("wins $100M government contract", CatalystSubType.GOVERNMENT_CONTRACT, 1.50, 3.0),
        ("signs AI partnership with hyperscaler", CatalystSubType.AI_PARTNERSHIP, 3.00, 5.5),
        ("acquisition offer at 50% premium", CatalystSubType.ACQUISITION, 4.00, 8.0),
        ("reports blockbuster earnings beat", CatalystSubType.EARNINGS_BEAT, 5.00, 9.0),
        ("Phase 2 data shows 90% efficacy", CatalystSubType.PHASE_2, 1.80, 4.2),
    ]

    for i in range(100):
        tmpl = great_templates[i % len(great_templates)]
        hl, sub, price, mfe = tmpl
        ticker = f"GREAT{i:03d}"
        record = _make_record(
            ticker=ticker,
            headline=f"{ticker} announces {hl}",
            price=price,
            outcome=AlertOutcome.GREAT_ALERT,
            cat=CatalystCategory.CORPORATE,
            sub=sub,
            is_negative=False,
            is_vague=False,
            rvol=random.uniform(3.0, 8.0),
            spread=random.uniform(0.5, 2.0),
            float_cat=random.choice([FloatCategory.LOW, FloatCategory.MEDIUM]),
            mcap_cat=MarketCapCategory.SMALL,
            impact=random.uniform(70.0, 95.0),
            expected=random.uniform(65.0, 90.0),
            cont=random.uniform(60.0, 85.0),
            multi_day=random.uniform(60.0, 85.0),
            trap=random.uniform(5.0, 20.0),
            dilution=random.uniform(5.0, 20.0),
            velocity=random.uniform(5.0, 15.0),
            sources=random.randint(2, 5),
            mfe=mfe,
            mae=random.uniform(-0.5, -0.1),
            move_pct=random.uniform(15.0, 50.0),
            volume=random.randint(500_000, 5_000_000),
        )
        alerts.append(record)
        by_cat[record.catalyst_type.value].append(record)

    # ── 100 TRAP_ALERT records (offerings, failed trials, delays — high price risk) ──
    print("Generating 100 TRAP records...")
    trap_templates = [
        ("files $50M mixed shelf offering", CatalystSubType.OTHER, 2.00, -25.0),
        ("reports patient death in Phase 2 trial", CatalystSubType.OTHER, 1.50, -40.0),
        ("announces reverse stock split 1-for-20", CatalystSubType.OTHER, 0.30, -15.0),
        ("delays PDUFA date by 6 months", CatalystSubType.OTHER, 3.50, -20.0),
        ("receives complete response letter from FDA", CatalystSubType.OTHER, 4.00, -35.0),
        ("files ATM offering for $30M", CatalystSubType.OTHER, 1.20, -18.0),
        ("announces workforce reduction of 50%", CatalystSubType.OTHER, 2.50, -12.0),
        ("discontinues pivotal trial due to futility", CatalystSubType.OTHER, 1.80, -30.0),
    ]

    for i in range(100):
        tmpl = trap_templates[i % len(trap_templates)]
        hl, sub, price, mfe = tmpl
        ticker = f"TRAP{i:03d}"
        record = _make_record(
            ticker=ticker,
            headline=f"{ticker} {hl}",
            price=price,
            outcome=AlertOutcome.TRAP_ALERT,
            cat=CatalystCategory.NEGATIVE,
            sub=sub,
            is_negative=True,
            is_vague=False,
            rvol=random.uniform(1.5, 4.0),
            spread=random.uniform(2.0, 5.0),
            float_cat=random.choice([FloatCategory.HIGH, FloatCategory.MEDIUM]),
            mcap_cat=MarketCapCategory.MICRO,
            impact=random.uniform(30.0, 55.0),
            expected=random.uniform(20.0, 45.0),
            cont=random.uniform(10.0, 30.0),
            multi_day=random.uniform(10.0, 30.0),
            trap=random.uniform(60.0, 90.0),
            dilution=random.uniform(70.0, 95.0),
            velocity=random.uniform(0.0, 3.0),
            sources=1,
            mfe=mfe,
            mae=random.uniform(-5.0, -0.5),
            move_pct=random.uniform(-30.0, -5.0),
            volume=random.randint(100_000, 1_000_000),
        )
        alerts.append(record)
        by_cat[record.catalyst_type.value].append(record)

    # ── 100 GOOD_ALERT records (moderate winners) ──
    print("Generating 100 GOOD records...")
    for i in range(100):
        ticker = f"GOOD{i:03d}"
        record = _make_record(
            ticker=ticker,
            headline=f"{ticker} announces positive Phase 1 data",
            price=random.uniform(1.0, 5.0),
            outcome=AlertOutcome.GOOD_ALERT,
            sub=CatalystSubType.PHASE_1,
            impact=random.uniform(55.0, 75.0),
            expected=random.uniform(50.0, 70.0),
            cont=random.uniform(45.0, 65.0),
            mfe=random.uniform(2.0, 5.0),
            mae=random.uniform(-1.0, -0.2),
            move_pct=random.uniform(5.0, 15.0),
            volume=random.randint(300_000, 2_000_000),
        )
        alerts.append(record)
        by_cat[record.catalyst_type.value].append(record)

    # ── 50 LATE_ALERT records ──
    print("Generating 50 LATE records...")
    for i in range(50):
        ticker = f"LATE{i:03d}"
        record = _make_record(
            ticker=ticker,
            headline=f"{ticker} reports earnings in line with expectations",
            price=random.uniform(5.0, 20.0),
            outcome=AlertOutcome.LATE_ALERT,
            sub=CatalystSubType.EARNINGS_BEAT,
            impact=random.uniform(40.0, 60.0),
            expected=random.uniform(35.0, 55.0),
            cont=random.uniform(30.0, 50.0),
            mfe=random.uniform(0.5, 1.5),
            mae=random.uniform(-1.5, -0.3),
            move_pct=random.uniform(2.0, 8.0),
            volume=random.randint(200_000, 1_500_000),
        )
        alerts.append(record)
        by_cat[record.catalyst_type.value].append(record)

    print(f"\nTotal synthetic records added: 350")
    print(f"Total alerts in DB: {len(alerts)}")

    # Save
    orch._telegram_learning._save()
    print("Saved.")

    # Delete old model and retrain
    for f in [Path("data/agentic/news_momentum_ml_model.joblib"),
              Path("data/agentic/news_momentum_ml_model_meta.json")]:
        if f.exists():
            f.unlink()

    print("\nRetraining ML model...")
    result = orch.retrain_ml()
    print(f"Success: {result.success}")
    print(f"Samples: {result.samples}")
    print(f"AUC: {result.auc:.3f}")
    print(f"Promoted: {result.promoted}")
    print(f"Reason: {result.reason}")

    status = orch.get_ml_engine().get_status()
    print(f"\nModel: {status['model_version']} | Samples: {status['samples_trained_on']} | AUC: {status['auc']:.3f}")

    # Test
    print("\n=== TESTING ===")
    from src.core.agentic.news_momentum_models import NewsMomentumCandidate
    from src.core.agentic.news_momentum_catalyst_classifier import classify_headline

    def _make_cand(headline, ticker, price, volume=1_000_000):
        cat, sub, is_neg, is_vague = classify_headline(headline)
        return NewsMomentumCandidate(
            ticker=ticker, headline=headline, source=NewsSource.ORACLE_SCANNER,
            published_at=datetime.now(timezone.utc), session=SessionType.REGULAR,
            catalyst_category=cat, catalyst_sub_type=sub,
            is_negative=is_neg, is_vague=is_vague,
            current_price=price, volume=volume, rvol=2.0, spread_pct=1.5,
            float_shares=50_000_000, market_cap=500_000_000,
            price_bucket=PriceBucket.UNDER_5 if price < 5 else PriceBucket.MID_CAP,
            float_category=FloatCategory.MEDIUM, market_cap_category=MarketCapCategory.SMALL,
            news_impact_score=random.uniform(60, 90) if "FDA" in headline or "Phase" in headline else 50,
            expected_return_score=random.uniform(55, 85) if "FDA" in headline or "Phase" in headline else 45,
            continuation_probability=random.uniform(50, 80) if "FDA" in headline or "Phase" in headline else 40,
            multi_day_continuation_score=random.uniform(50, 80) if "FDA" in headline or "Phase" in headline else 40,
            trap_risk=random.uniform(5, 15) if "FDA" in headline or "Phase" in headline else 70,
            dilution_risk=random.uniform(5, 15) if "FDA" in headline or "Phase" in headline else 80,
            velocity_score=random.uniform(5, 15) if "FDA" in headline or "Phase" in headline else 1,
            sources_seen_count=random.randint(2, 4) if "FDA" in headline or "Phase" in headline else 1,
        )

    ml = orch.get_ml_engine()
    cases = [
        ("AAPL announces record Q1 earnings beat", "AAPL", 180.0),
        ("Microcap biotech VKTX announces positive Phase 3 data", "VKTX", 3.50),
        ("Rigetti Computing files $200M mixed shelf offering", "RGTI", 1.20),
        ("EDITAS Medicine reports patient death in clinical trial", "EDIT", 1.50),
        ("BTCY announces FDA approval for novel cancer therapy", "BTCY", 0.80),
        ("WULF announces $50M ATM offering", "WULF", 2.00),
        ("XYZ files reverse stock split 1-for-20", "XYZ", 0.30),
        ("ABC receives complete response letter from FDA", "ABC", 4.00),
    ]
    print(f"{'Headline':<50} {'Ticker':<6} {'Price':>6} {'Win%':>6} {'Conf':>5}")
    print("-" * 75)
    for headline, ticker, price in cases:
        cand = _make_cand(headline, ticker, price)
        pred = ml.predict(cand)
        print(f"{headline[:48]:<48} {ticker:<6} ${price:>5.2f} {pred.win_probability*100:>5.1f}% {pred.confidence:>4.2f}")

    print("\n=== RESULT ===")
    print("TRAP events (offering, death, split, CRL) should now score LOWER than")
    print("GREAT events (FDA, Phase 3, partnership).")


if __name__ == "__main__":
    main()
