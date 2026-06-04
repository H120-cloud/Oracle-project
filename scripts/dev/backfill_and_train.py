"""
Backfill diverse tickers for full 2025 + inject into orchestrator + retrain ML.
No server needed — runs the engine directly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import asyncio
from src.core.agentic.news_momentum_historical_backfill import HistoricalBackfillEngine
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator

# Diverse universe: large-caps + mid/small-caps + biotech + AI + meme/momentum
TICKERS = [
    # Large caps (baseline, mostly NO_FOLLOW_THROUGH)
    "AAPL", "TSLA", "NVDA", "AMD", "MSFT",
    # Mid-caps (more movement)
    "SMCI", "PLTR", "COIN", "DKNG", "RIVN",
    # Small/volatile (high movement, potential GREAT/TRAP)
    "SOUN", "BBAI", "RGTI", "QBTS", "LUNR",
    "ASTS", "IONQ", "RXRX", "DNA", "CLS",
    # Biotech (FDA catalysts = big moves)
    "VKTX", "CYTK", "SRRK", "CRSP", "BEAM",
    "NTLA", "EDIT", "SRPT", "ARWR",
]

START_DATE = "2025-01-01"
END_DATE = "2025-12-31"
NEWS_LIMIT = 50  # per ticker (Polygon free tier = ~5 calls/min)
MAX_CONCURRENT = 2


async def main():
    engine = HistoricalBackfillEngine(rate_limit_delay=12.0)

    print(f"=== BACKFILL START ===")
    print(f"Tickers: {len(TICKERS)}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"News limit per ticker: {NEWS_LIMIT}")
    print()

    result = await engine.backfill_range(
        tickers=TICKERS,
        start_date=START_DATE,
        end_date=END_DATE,
        news_limit=NEWS_LIMIT,
        max_concurrent=MAX_CONCURRENT,
        force=False,  # skip already-completed to save time
    )

    print(f"\n=== BACKFILL COMPLETE ===")
    print(f"Total added: {result['total_added']}")
    print(f"Tickers processed: {result['tickers_processed']}")
    print(f"Total records in DB: {result['total_records']}")

    summary = engine.get_summary()
    print(f"\nOutcome breakdown:")
    for outcome, count in summary["by_outcome"].items():
        print(f"  {outcome}: {count}")
    print(f"Tickers with records: {summary['tickers']}")

    # Inject and train
    print(f"\n=== INJECT & TRAIN ===")
    orch = NewsMomentumOrchestrator()
    injected = engine.inject_into_orchestrator(orch)
    print(f"Injected {injected} records into orchestrator")

    train_result = orch.retrain_ml()
    print(f"\nTraining success: {train_result.success}")
    print(f"Samples: {train_result.samples}")
    print(f"Train accuracy: {train_result.train_accuracy}")
    print(f"Test accuracy: {train_result.test_accuracy}")
    print(f"AUC: {train_result.auc}")
    print(f"Win rate baseline: {train_result.win_rate_baseline}")
    print(f"Promoted: {train_result.promoted}")
    print(f"Reason: {train_result.reason}")
    if train_result.feature_importance:
        print(f"\nTop features:")
        for name, score in train_result.feature_importance[:10]:
            print(f"  {name}: {score:.4f}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
