"""
Weekly retrain script for the News Momentum ML model.

Workflow:
  1. Load shadow alert records (every candidate evaluated — sent + blocked).
  2. Load existing sent-alert records.
  3. Resolve outcomes for any unresolved records using the existing
     NewsMomentumOutcomeResolver pattern (fetches post-news prices).
  4. Merge both pools into a single training set.
  5. Inject the combined records into the orchestrator's telegram_learning
     store and call retrain_ml() to refit the XGBoost model.
  6. Promote the new model if it beats the current one on AUC.

Run weekly:
    python weekly_retrain.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("weekly_retrain")


async def main() -> None:
    from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator
    from src.core.agentic.news_momentum_shadow_logger import ShadowAlertLogger
    from src.core.agentic.news_momentum_outcome_resolver import NewsMomentumOutcomeResolver

    logger.info("=" * 70)
    logger.info("WEEKLY RETRAIN — News Momentum ML Model")
    logger.info("=" * 70)

    # ── 1. Load orchestrator (auto-loads sent alerts) ────────────────────
    orch = NewsMomentumOrchestrator()
    sent_count = len(orch._telegram_learning._alerts)
    logger.info("Loaded %d sent alert records", sent_count)

    # ── 2. Load shadow records ───────────────────────────────────────────
    shadow = ShadowAlertLogger()
    shadow_count = len(shadow.records)
    blocked_count = sum(1 for r in shadow.records if r.was_blocked)
    logger.info(
        "Loaded %d shadow records (%d blocked, %d would-have-sent)",
        shadow_count, blocked_count, shadow_count - blocked_count,
    )

    # ── 3. Resolve outcomes for shadow records ───────────────────────────
    resolver = NewsMomentumOutcomeResolver(orch._telegram_learning)
    unresolved = shadow.get_unresolved(min_age_minutes=30)
    logger.info("Resolving outcomes for %d unresolved shadow records...", len(unresolved))

    resolved = 0
    failed = 0
    for i, rec in enumerate(unresolved, 1):
        try:
            ok = await resolver.resolve_one(rec)
            if ok:
                resolved += 1
            else:
                failed += 1
        except Exception as exc:
            logger.debug("Resolve failed for %s: %s", rec.ticker, exc)
            failed += 1
        if i % 25 == 0:
            logger.info("  progress: %d/%d resolved=%d failed=%d", i, len(unresolved), resolved, failed)
            shadow.flush()
    shadow.flush()
    logger.info("Outcome resolution done: %d resolved, %d failed", resolved, failed)

    # ── 4. Inject shadow records into telegram_learning store ────────────
    # The ML engine trains off `_telegram_learning._alerts`, so we just append
    # the shadow ones with resolved outcomes.
    injected = 0
    existing_ids = {a.alert_id for a in orch._telegram_learning._alerts}
    for rec in shadow.records:
        if rec.alert_id in existing_ids:
            continue
        if rec.outcome is None:
            continue  # only train on records with known outcomes
        orch._telegram_learning._alerts.append(rec)
        orch._telegram_learning._by_catalyst[rec.catalyst_type.value].append(rec)
        injected += 1
    if injected:
        orch._telegram_learning._save()
    logger.info("Injected %d shadow records into training pool", injected)

    # ── 5. Retrain ML model ─────────────────────────────────────────────
    total_pool = len(orch._telegram_learning._alerts)
    resolved_pool = sum(1 for a in orch._telegram_learning._alerts if a.outcome is not None)
    logger.info("Training pool: %d total, %d with resolved outcomes", total_pool, resolved_pool)

    if resolved_pool < 30:
        logger.warning("Only %d resolved samples — need >=30 to retrain. Skipping.", resolved_pool)
        return

    logger.info("Retraining ML model...")
    result = orch.retrain_ml()
    logger.info("=" * 70)
    logger.info("RETRAIN RESULT")
    logger.info("=" * 70)
    if result.get("trained"):
        logger.info("  Samples used:   %d", result.get("samples", 0))
        logger.info("  Accuracy:       %.3f", result.get("accuracy", 0))
        logger.info("  AUC:            %.3f", result.get("auc", 0))
        logger.info("  Model version:  %s", result.get("model_version", "n/a"))
        logger.info("  Promoted:       %s", result.get("promoted", False))
        top_feats = result.get("top_features", [])[:10]
        if top_feats:
            logger.info("  Top features:")
            for name, imp in top_feats:
                logger.info("    %-30s %.4f", name, imp)
    else:
        logger.warning("  Training failed or skipped: %s", result.get("reason", "unknown"))


if __name__ == "__main__":
    asyncio.run(main())
