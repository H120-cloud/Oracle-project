"""
Unknown-Catalyst Auto-Learner (V23.2)

When the catalyst classifier returns `unknown / other` but the stock subsequently
delivers a big move (>= 25%), we record the headline so the system can:

  1. Surface a daily report of "missed catalyst patterns" — phrases that
     repeatedly precede big moves but aren't yet in the classifier.
  2. Suggest concrete keyword additions to the maintainer.
  3. Build a corpus for future ML-based catalyst extraction.

The intent: turn ASTC-style misses into a feedback loop so the classifier
gets smarter over time WITHOUT needing manual reaction to each event.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.atomic_json import load_json_file, save_json_file

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
UNKNOWN_LOG = DATA_DIR / "news_momentum_unknown_catalyst_log.json"

# A small list of generic stop-words so we focus on meaningful tokens
STOP = {
    "the","a","an","of","to","and","or","in","on","for","with","by",
    "from","at","as","is","are","be","new","its","into","up","down",
    "will","has","have","had","this","that","these","those","it",
    "company","corp","inc","ltd","plc","holdings","group","limited",
    "announces","announce","announced","reports","report","said",
    "filed","filing","files","says","say","saying",
}


class UnknownCatalystLearner:
    """Tracks headlines classified as `unknown` and flags those that
    later produced strong price reactions for review."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        data = load_json_file(UNKNOWN_LOG, default=[]) or []
        if isinstance(data, list):
            self._records = data
        else:
            self._records = []

    def _save(self) -> None:
        # Keep only the last 5,000 entries to bound size
        if len(self._records) > 5000:
            self._records = self._records[-5000:]
        save_json_file(UNKNOWN_LOG, self._records)

    def record_unknown(
        self,
        ticker: str,
        headline: str,
        price_at_detection: Optional[float] = None,
        move_pct_at_detection: float = 0.0,
        rvol_at_detection: float = 0.0,
    ) -> None:
        """Called by the orchestrator when a candidate scans as unknown."""
        if not headline:
            return
        self._records.append({
            "ticker": ticker,
            "headline": headline,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "price": price_at_detection,
            "move_pct": move_pct_at_detection,
            "rvol": rvol_at_detection,
            "max_move_pct": move_pct_at_detection,  # will be updated by resolver
            "resolved": False,
        })
        self._save()

    def update_outcome(self, ticker: str, max_move_pct: float) -> None:
        """Called by the outcome resolver to mark how far the stock moved.
        Updates the most recent unresolved record for this ticker."""
        for rec in reversed(self._records):
            if rec.get("ticker") == ticker and not rec.get("resolved"):
                rec["max_move_pct"] = max_move_pct
                rec["resolved"] = True
                break
        self._save()

    # ── Analysis ─────────────────────────────────────────────────────────
    def extract_keywords(self, text: str, n: int = 4) -> List[str]:
        """Pull n-grams (unigrams + bigrams) from a headline, lower-cased."""
        text = text.lower()
        # Keep alphanumeric + spaces
        tokens = re.findall(r"[a-z][a-z0-9\-]+", text)
        tokens = [t for t in tokens if t not in STOP and len(t) >= 4]
        out = list(tokens)
        # Bigrams of meaningful tokens
        for i in range(len(tokens) - 1):
            out.append(f"{tokens[i]} {tokens[i+1]}")
        return out

    def missed_patterns(self, min_move: float = 25.0, min_count: int = 2) -> List[Dict[str, Any]]:
        """
        Return the most common keywords/bigrams that appear in headlines
        which were unknown-classified but later produced moves >= min_move%.
        These are candidate additions to the catalyst classifier.
        """
        big_movers = [
            r for r in self._records
            if r.get("resolved") and (r.get("max_move_pct") or 0.0) >= min_move
        ]
        if not big_movers:
            return []

        counter: Counter = Counter()
        examples: Dict[str, List[str]] = {}
        for rec in big_movers:
            kws = self.extract_keywords(rec.get("headline", ""))
            seen = set()
            for kw in kws:
                if kw in seen:
                    continue
                seen.add(kw)
                counter[kw] += 1
                examples.setdefault(kw, []).append(
                    f"{rec.get('ticker')}: {rec.get('headline', '')[:80]}"
                )

        results = []
        for kw, cnt in counter.most_common(50):
            if cnt < min_count:
                continue
            results.append({
                "pattern": kw,
                "occurrences": cnt,
                "examples": examples[kw][:3],
            })
        return results

    def get_status(self) -> Dict[str, Any]:
        big = [r for r in self._records if r.get("resolved") and (r.get("max_move_pct") or 0) >= 25.0]
        return {
            "total_unknown_records": len(self._records),
            "resolved": sum(1 for r in self._records if r.get("resolved")),
            "big_movers_missed": len(big),
            "top_missed_patterns": self.missed_patterns(min_move=25.0, min_count=2)[:10],
        }
