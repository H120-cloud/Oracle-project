"""
P2a back-fill entry point.

Resolves MFE/MAE outcomes for all unresolved shadow alerts and candidates,
writing results to sidecar JSONL files under data/agentic/backfill_runs/.

Usage:
    python scripts/p2a_backfill.py
"""

import sys
from pathlib import Path

# Add project root to path so src imports resolve
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.core.agentic.news_momentum_backfill import main

if __name__ == "__main__":
    # Entry point wrapper; actual politeness is configured in BackfillDriver
    main()
