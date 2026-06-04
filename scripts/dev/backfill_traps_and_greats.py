"""
Backfill tickers specifically selected to generate TRAP and GREAT outcomes.
These are known volatile/problematic tickers and big runners from 2025.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import asyncio
from datetime import datetime, timezone
from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

# Tickers selected to produce TRAP outcomes (offerings, failed trials, delistings, reverse splits)
TRAP_TICKERS = [
    # Known 2025 offering/dilution traps
    "TPET", "WULF", "BTBT", "HIVE", "MARA", "RIOT",  # Crypto miners (constant dilution)
    "LTRX", "GDC", "GSIT", "JAGX", "AVTX", "KTRA",   # Biotechs with frequent offerings
    "BCTX", "AGEN", "KZIA", "LPCN", "MDIA", "NBRV",  # Microcap biotechs
    "PROC", "REVB", "STTK", "TCRT", "VLON", "WKEY",   # More microcap offerings
    "HKIT", "GLMD", "VYGR", "AXLA", "FBRX", "IMVT",   # Failed trials / delisting risk
    "ADIL", "ALDX", "ALT", "ARAV", "ATOS", "BLPH",    # Low-float traps
    "CPIX", "DFFN", "EDSA", "FENC", "GTXI", "HTGM",   # Penny stock offerings
]

# Tickers selected to produce GREAT outcomes (100%+ runners on catalysts in 2025)
GREAT_TICKERS = [
    # Known 2025 big runners on news
    "AIMD", "BTCY", "SBFM", "LGVN", "ISPC", "DBGI",   # Microcap momentum
    "SLNH", "ATLX", "APVO", "TPST", "CALC", "ENSC",   # Biotech runners
    "NRXP", "SONN", "SNTI", "PLRX", "XFOR", "ALXO",   # More biotech
    "CHRS", "EPRX", "IOVA", "KRON", "MRSN", "PMVP",   # Clinical data runners
    "PSTX", "RAIN", "SNDX", "STRO", "TERN", "THTX",   # PDUFA / FDA runners
    "TRDA", "URGN", "VIRX", "WVE", "ZURA", "APLM",    # High-volatility micros
]

ALL_TICKERS = TRAP_TICKERS + GREAT_TICKERS
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"
NEWS_LIMIT = 50
MAX_CONCURRENT = 2


async def main():
    engine = HistoricalBackfillEngine(rate_limit_delay=12.0)

    print(f"=== TARGETED BACKFILL: TRAPS + GREATS ===")
    print(f"TRAP-target tickers: {len(TRAP_TICKERS)}")
    print(f"GREAT-target tickers: {len(GREAT_TICKERS)}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Already completed tickers will be skipped\n")

    result = await engine.backfill_range(
        tickers=ALL_TICKERS,
        start_date=START_DATE,
        end_date=END_DATE,
        news_limit=NEWS_LIMIT,
        max_concurrent=MAX_CONCURRENT,
        force=False,
    )

    print(f"\n=== BACKFILL COMPLETE ===")
    print(f"Total added this run: {result['total_added']}")
    print(f"Tickers processed: {result['tickers_processed']}")
    print(f"Total records in DB: {result['total_records']}")

    summary = engine.get_summary()
    print(f"\nOutcome breakdown:")
    for outcome, count in summary["by_outcome"].items():
        print(f"  {outcome}: {count}")

    # Inject and train
    print(f"\n=== INJECT & TRAIN ===")
    orch = NewsMomentumOrchestrator()

    # Fast batch inject
    alerts = orch._telegram_learning._alerts
    by_catalyst = orch._telegram_learning._by_catalyst
    for record in engine._records:
        alerts.append(record)
        by_catalyst[record.catalyst_type.value].append(record)
    orch._telegram_learning._save()
    print(f"Injected {len(engine._records)} records")

    train_result = orch.retrain_ml()
    print(f"\nTraining success: {train_result.success}")
    print(f"Samples: {train_result.samples}")
    print(f"AUC: {train_result.auc:.3f}")
    print(f"Promoted: {train_result.promoted}")
    print(f"Reason: {train_result.reason}")

    status = orch.get_ml_engine().get_status()
    print(f"\nModel: {status['model_version']} | AUC: {status['auc']:.3f} | Samples: {status['samples_trained_on']}")

    # Re-run the test
    print("\n=== RE-TESTING ===")
    from src.core.agentic.news_momentum_models import NewsMomentumCandidate, NewsSource, SessionType, PriceBucket, FloatCategory, MarketCapCategory
    from src.core.agentic.news_momentum_catalyst_classifier import classify_headline

    def _make_cand(headline, ticker, price, volume=1_000_000):
        cat, sub, is_neg, is_vague = classify_headline(headline)
        sim = engine._simulate_pipeline(headline, price)
        now = datetime.now(timezone.utc)
        return NewsMomentumCandidate(
            ticker=ticker, headline=headline, source=NewsSource.ORACLE_SCANNER,
            published_at=now, session=SessionType.REGULAR,
            catalyst_category=cat, catalyst_sub_type=sub,
            is_negative=is_neg, is_vague=is_vague,
            current_price=price, volume=volume, rvol=2.0, spread_pct=1.5,
            float_shares=50_000_000, market_cap=500_000_000,
            price_bucket=PriceBucket.UNDER_5 if price < 5 else PriceBucket.MID_CAP,
            float_category=FloatCategory.MEDIUM, market_cap_category=MarketCapCategory.SMALL,
            news_impact_score=sim["news_impact_score"],
            expected_return_score=sim["expected_return_score"],
            continuation_probability=sim["continuation_probability"],
            multi_day_continuation_score=sim["multi_day_score"],
            trap_risk=sim["trap_risk_at_alert"],
            dilution_risk=sim["dilution_risk_at_alert"],
            velocity_score=sim["velocity_score_at_alert"],
            sources_seen_count=sim["sources_seen_count"],
        )

    ml = orch.get_ml_engine()
    test_cases = [
        ("AAPL announces record Q1 earnings beat", "AAPL", 180.0),
        ("Microcap biotech VKTX announces positive Phase 3 data", "VKTX", 3.50),
        ("Rigetti Computing files $200M mixed shelf offering", "RGTI", 1.20),
        ("EDITAS Medicine reports patient death in clinical trial", "EDIT", 1.50),
        ("BTCY announces FDA approval for novel cancer therapy", "BTCY", 0.80),
    ]
    print(f"{'Headline':<50} {'Ticker':<6} {'Price':>6} {'Win%':>6} {'Conf':>5}")
    print("-" * 75)
    for headline, ticker, price in test_cases:
        try:
            cand = _make_cand(headline, ticker, price)
            pred = ml.predict(cand)
            print(f"{headline[:48]:<48} {ticker:<6} ${price:>5.2f} {pred.win_probability*100:>5.1f}% {pred.confidence:>4.2f}")
        except Exception as exc:
            print(f"ERROR: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
