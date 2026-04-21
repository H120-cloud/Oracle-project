"""
News Intelligence Engine — Part 1 + 2

Detects, classifies, and ranks news catalysts with:
- Freshness classification (BREAKING → DEAD)
- Market reaction evaluation (NO_REACTION → EXHAUSTED)
- Catalyst tier ranking (Tier 1–3)
- Catalyst score (0–100)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
from enum import Enum

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Enums ─────────────────────────────────────────────────────────────────────

class FreshnessLabel(str, Enum):
    BREAKING = "BREAKING"          # 0–30 min
    FRESH = "FRESH"                # 30 min – 4 hours
    SAME_DAY_ACTIVE = "SAME_DAY"   # 4 hours – market close
    AGING = "AGING"                # 1 day old
    STALE = "STALE"                # 2–3 days
    DEAD = "DEAD"                  # > 3 days

class ReactionState(str, Enum):
    NO_REACTION = "NO_REACTION"
    INITIAL = "INITIAL"
    ACTIVE = "ACTIVE"
    FADING = "FADING"
    EXHAUSTED = "EXHAUSTED"

class CatalystTier(str, Enum):
    TIER_1 = "TIER_1"  # Earnings, FDA, mergers, major contracts
    TIER_2 = "TIER_2"  # Partnerships, upgrades, product launches
    TIER_3 = "TIER_3"  # Minor PR, general mentions


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class NewsIntelligence:
    """Full intelligence output for a single news item."""
    headline: str
    source: str
    ticker: str
    timestamp_utc: Optional[datetime] = None
    timestamp_uk: Optional[str] = None

    # Classification
    catalyst_type: str = "unknown"
    catalyst_tier: CatalystTier = CatalystTier.TIER_3
    catalyst_score: float = 0.0        # 0–100

    # Freshness
    freshness_label: FreshnessLabel = FreshnessLabel.DEAD
    minutes_since_publish: float = 9999

    # Reaction (requires price data to evaluate)
    reaction_state: ReactionState = ReactionState.NO_REACTION
    reaction_volume_ratio: float = 0.0  # volume vs avg
    reaction_price_change: float = 0.0  # % move since news

    # Sentiment
    sentiment: str = "neutral"          # positive / negative / neutral
    sentiment_score: float = 0.0        # -1 to +1

    # Raw URL
    url: Optional[str] = None


@dataclass
class TickerNewsSummary:
    """Aggregated news intelligence for a single ticker."""
    ticker: str
    total_headlines: int = 0
    strongest_catalyst: Optional[NewsIntelligence] = None
    catalyst_score: float = 0.0
    catalyst_tier: CatalystTier = CatalystTier.TIER_3
    freshness_label: FreshnessLabel = FreshnessLabel.DEAD
    reaction_state: ReactionState = ReactionState.NO_REACTION
    headlines: List[NewsIntelligence] = field(default_factory=list)
    has_breaking_news: bool = False
    has_tier1_catalyst: bool = False


# ── Catalyst Classification ──────────────────────────────────────────────────

CATALYST_PATTERNS: Dict[str, dict] = {
    # Tier 1 — Major market movers
    "earnings": {
        "patterns": [r"\bearnings\b", r"\bEPS\b", r"\brevenue\b", r"\bquarterly\sresults?\b",
                     r"\bbeats?\s+estimates?\b", r"\bmisses?\s+estimates?\b", r"\bguidance\b",
                     r"\bprofit\b", r"\bnet\s+income\b"],
        "tier": CatalystTier.TIER_1, "base_score": 85,
    },
    "fda": {
        "patterns": [r"\bFDA\b", r"\bapproval\b", r"\bPDUFA\b", r"\bclinical\s+trial\b",
                     r"\bphase\s+[123]\b", r"\bNDA\b", r"\bBLA\b", r"\bbiopharma\b"],
        "tier": CatalystTier.TIER_1, "base_score": 90,
    },
    "merger_acquisition": {
        "patterns": [r"\bmerger\b", r"\bacquisition\b", r"\bacquire[sd]?\b", r"\bbuyout\b",
                     r"\btakeover\b", r"\bbid\b.*\bper\s+share\b", r"\bdeal\b"],
        "tier": CatalystTier.TIER_1, "base_score": 92,
    },
    "major_contract": {
        "patterns": [r"\bcontract\b.*\b(billion|million)\b", r"\baward\b.*\bcontract\b",
                     r"\bmajor\s+deal\b", r"\bgovernment\s+contract\b"],
        "tier": CatalystTier.TIER_1, "base_score": 80,
    },
    "sec_filing": {
        "patterns": [r"\bSEC\b.*\bfiling\b", r"\b13[DFG]\b", r"\bS-1\b", r"\bIPO\b",
                     r"\boffering\b", r"\bsecondary\b.*\boffering\b"],
        "tier": CatalystTier.TIER_1, "base_score": 75,
    },

    # Tier 2 — Moderate movers
    "partnership": {
        "patterns": [r"\bpartnership\b", r"\bcollaboration\b", r"\bjoint\s+venture\b",
                     r"\bstrategic\s+alliance\b", r"\bagreement\b"],
        "tier": CatalystTier.TIER_2, "base_score": 60,
    },
    "upgrade_downgrade": {
        "patterns": [r"\bupgrade[sd]?\b", r"\bdowngrade[sd]?\b", r"\bprice\s+target\b",
                     r"\banalyst\b.*\brating\b", r"\binitiat\w+\s+coverage\b",
                     r"\boverweight\b", r"\bunderweight\b", r"\boutperform\b"],
        "tier": CatalystTier.TIER_2, "base_score": 55,
    },
    "product_launch": {
        "patterns": [r"\blaunch\w*\b", r"\bnew\s+product\b", r"\brelease[sd]?\b",
                     r"\bannounce[sd]?\b.*\bproduct\b"],
        "tier": CatalystTier.TIER_2, "base_score": 50,
    },
    "insider_activity": {
        "patterns": [r"\binsider\b.*\b(buy|sell|purchase)\b", r"\bCEO\b.*\b(buy|sell)\b",
                     r"\bboard\b.*\b(buy|sell)\b"],
        "tier": CatalystTier.TIER_2, "base_score": 55,
    },

    # Tier 3 — Minor
    "general_mention": {
        "patterns": [r"\bstock\b", r"\bshares?\b", r"\btrading\b", r"\bmarket\b"],
        "tier": CatalystTier.TIER_3, "base_score": 15,
    },
}

POSITIVE_WORDS = frozenset([
    'beat', 'beats', 'surge', 'surges', 'rally', 'rallies', 'gain', 'gains',
    'jump', 'jumps', 'soar', 'soars', 'bull', 'bullish', 'upgrade', 'upgrades',
    'strong', 'growth', 'profit', 'exceed', 'outperform', 'raise', 'raises',
    'record', 'positive', 'approve', 'approved', 'breakthrough', 'win', 'wins',
])

NEGATIVE_WORDS = frozenset([
    'drop', 'drops', 'fall', 'falls', 'plunge', 'crash', 'bear', 'bearish',
    'downgrade', 'miss', 'misses', 'loss', 'losses', 'decline', 'sell',
    'selling', 'cut', 'cuts', 'weak', 'warning', 'delay', 'fail', 'fails',
    'reject', 'rejected', 'lawsuit', 'fraud', 'investigation', 'recall',
])


class NewsIntelligenceEngine:
    """
    Full news intelligence pipeline:
    1. Fetch headlines for ticker(s)
    2. Classify catalyst type and tier
    3. Compute freshness
    4. Evaluate market reaction
    5. Score and rank
    """

    def __init__(self):
        self.client = httpx.Client(headers=HEADERS, timeout=30)

    def analyze_ticker(
        self,
        ticker: str,
        bars: Optional[list] = None,
        avg_volume: float = 0,
    ) -> TickerNewsSummary:
        """Full news intelligence for a single ticker."""
        headlines = self._fetch_headlines(ticker)

        news_items = []
        for h in headlines:
            item = self._classify_headline(h, ticker)
            item.freshness_label = self._compute_freshness(item.timestamp_utc)
            item.sentiment, item.sentiment_score = self._compute_sentiment(item.headline)

            # Evaluate reaction if bars provided
            if bars and avg_volume > 0:
                item.reaction_state = self._evaluate_reaction(bars, avg_volume)
                item.reaction_volume_ratio = self._volume_ratio(bars, avg_volume)
                if len(bars) > 0:
                    item.reaction_price_change = self._price_change_since(bars)

            # Adjust catalyst score for freshness + sentiment
            item.catalyst_score = self._adjust_score(item)
            news_items.append(item)

        # Sort by catalyst score descending
        news_items.sort(key=lambda x: x.catalyst_score, reverse=True)

        summary = TickerNewsSummary(
            ticker=ticker,
            total_headlines=len(news_items),
            headlines=news_items[:10],  # Keep top 10
        )

        if news_items:
            best = news_items[0]
            summary.strongest_catalyst = best
            summary.catalyst_score = best.catalyst_score
            summary.catalyst_tier = best.catalyst_tier
            summary.freshness_label = best.freshness_label
            summary.reaction_state = best.reaction_state
            summary.has_breaking_news = any(
                n.freshness_label == FreshnessLabel.BREAKING for n in news_items
            )
            summary.has_tier1_catalyst = any(
                n.catalyst_tier == CatalystTier.TIER_1 for n in news_items
            )

        return summary

    def analyze_batch(
        self, tickers: List[str], bars_map: Optional[Dict] = None, volume_map: Optional[Dict] = None
    ) -> Dict[str, TickerNewsSummary]:
        """Analyze news for multiple tickers."""
        results = {}
        for ticker in tickers:
            bars = bars_map.get(ticker) if bars_map else None
            avg_vol = volume_map.get(ticker, 0) if volume_map else 0
            try:
                results[ticker] = self.analyze_ticker(ticker, bars, avg_vol)
            except Exception as exc:
                logger.warning("News analysis failed for %s: %s", ticker, exc)
                results[ticker] = TickerNewsSummary(ticker=ticker)
        return results

    # ── Headline Fetching ─────────────────────────────────────────────────

    def _fetch_headlines(self, ticker: str, max_items: int = 15) -> List[dict]:
        """Fetch news headlines from Yahoo Finance."""
        headlines = []
        try:
            url = f"https://finance.yahoo.com/quote/{ticker.upper()}/news"
            response = self.client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                href = link.get("href", "")
                if len(text) > 20 and ("/news/" in href or href.startswith("https://")):
                    headlines.append({
                        "headline": text,
                        "url": href if href.startswith("http") else f"https://finance.yahoo.com{href}",
                        "source": self._extract_source(href),
                        "timestamp_utc": datetime.now(timezone.utc),
                    })
                    if len(headlines) >= max_items:
                        break

        except Exception as exc:
            logger.error("Failed to fetch news for %s: %s", ticker, exc)

        return headlines

    # ── Classification ────────────────────────────────────────────────────

    def _classify_headline(self, headline_data: dict, ticker: str) -> NewsIntelligence:
        """Classify a headline into catalyst type and tier."""
        headline = headline_data.get("headline", "")
        best_type = "general_mention"
        best_tier = CatalystTier.TIER_3
        best_score = 15

        for cat_type, config in CATALYST_PATTERNS.items():
            for pattern in config["patterns"]:
                if re.search(pattern, headline, re.IGNORECASE):
                    if config["base_score"] > best_score:
                        best_type = cat_type
                        best_tier = config["tier"]
                        best_score = config["base_score"]
                    break

        ts_utc = headline_data.get("timestamp_utc")
        ts_uk = None
        if ts_utc:
            uk_offset = timedelta(hours=1)  # BST approximation
            ts_uk = (ts_utc + uk_offset).strftime("%Y-%m-%d %H:%M UK")

        return NewsIntelligence(
            headline=headline,
            source=headline_data.get("source", "Unknown"),
            ticker=ticker,
            timestamp_utc=ts_utc,
            timestamp_uk=ts_uk,
            catalyst_type=best_type,
            catalyst_tier=best_tier,
            catalyst_score=best_score,
            url=headline_data.get("url"),
        )

    # ── Freshness ─────────────────────────────────────────────────────────

    def _compute_freshness(self, timestamp: Optional[datetime]) -> FreshnessLabel:
        """Classify news freshness."""
        if timestamp is None:
            return FreshnessLabel.DEAD

        now = datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        diff = now - timestamp
        minutes = diff.total_seconds() / 60

        if minutes <= 30:
            return FreshnessLabel.BREAKING
        elif minutes <= 240:
            return FreshnessLabel.FRESH
        elif minutes <= 720:
            return FreshnessLabel.SAME_DAY_ACTIVE
        elif minutes <= 1440:
            return FreshnessLabel.AGING
        elif minutes <= 4320:
            return FreshnessLabel.STALE
        return FreshnessLabel.DEAD

    # ── Market Reaction ───────────────────────────────────────────────────

    def _evaluate_reaction(self, bars: list, avg_volume: float) -> ReactionState:
        """Evaluate how the market is reacting to news."""
        if not bars or len(bars) < 5:
            return ReactionState.NO_REACTION

        recent_vol = sum(getattr(b, 'volume', 0) for b in bars[-5:])
        avg_recent = recent_vol / 5 if recent_vol else 0
        vol_ratio = avg_recent / avg_volume if avg_volume > 0 else 0

        # Price momentum — last 5 bars
        closes = [float(getattr(b, 'close', 0)) for b in bars[-10:]]
        if len(closes) >= 10:
            first_half_avg = sum(closes[:5]) / 5
            second_half_avg = sum(closes[5:]) / 5
            momentum = (second_half_avg - first_half_avg) / first_half_avg * 100 if first_half_avg > 0 else 0
        else:
            momentum = 0

        if vol_ratio < 1.2 and abs(momentum) < 0.5:
            return ReactionState.NO_REACTION
        elif vol_ratio >= 3.0 and abs(momentum) >= 2.0:
            return ReactionState.ACTIVE
        elif vol_ratio >= 2.0:
            if abs(momentum) >= 1.0:
                return ReactionState.ACTIVE
            return ReactionState.INITIAL
        elif vol_ratio >= 1.5 and abs(momentum) < 0.5:
            return ReactionState.FADING
        elif vol_ratio < 1.0 and abs(momentum) < 0.3:
            return ReactionState.EXHAUSTED

        return ReactionState.INITIAL

    def _volume_ratio(self, bars: list, avg_volume: float) -> float:
        """Compute current volume vs average."""
        if not bars or avg_volume <= 0:
            return 0
        recent_vol = sum(getattr(b, 'volume', 0) for b in bars[-5:]) / 5
        return round(recent_vol / avg_volume, 2)

    def _price_change_since(self, bars: list) -> float:
        """Compute % price change over recent bars."""
        if not bars or len(bars) < 2:
            return 0
        first = float(getattr(bars[0], 'open', 0))
        last = float(getattr(bars[-1], 'close', 0))
        return round((last - first) / first * 100, 2) if first > 0 else 0

    # ── Sentiment ─────────────────────────────────────────────────────────

    def _compute_sentiment(self, headline: str) -> tuple:
        """Keyword-based sentiment scoring."""
        words = set(re.findall(r'\b\w+\b', headline.lower()))
        pos = len(words & POSITIVE_WORDS)
        neg = len(words & NEGATIVE_WORDS)

        if pos > neg:
            return "positive", min(1.0, pos * 0.3)
        elif neg > pos:
            return "negative", max(-1.0, -neg * 0.3)
        return "neutral", 0.0

    # ── Score Adjustment ──────────────────────────────────────────────────

    def _adjust_score(self, item: NewsIntelligence) -> float:
        """Adjust catalyst score based on freshness, reaction, and sentiment."""
        score = item.catalyst_score

        # Freshness multiplier
        freshness_mult = {
            FreshnessLabel.BREAKING: 1.3,
            FreshnessLabel.FRESH: 1.15,
            FreshnessLabel.SAME_DAY_ACTIVE: 1.0,
            FreshnessLabel.AGING: 0.7,
            FreshnessLabel.STALE: 0.4,
            FreshnessLabel.DEAD: 0.1,
        }
        score *= freshness_mult.get(item.freshness_label, 0.5)

        # Reaction multiplier
        reaction_mult = {
            ReactionState.ACTIVE: 1.3,
            ReactionState.INITIAL: 1.1,
            ReactionState.NO_REACTION: 0.6,
            ReactionState.FADING: 0.5,
            ReactionState.EXHAUSTED: 0.3,
        }
        score *= reaction_mult.get(item.reaction_state, 0.8)

        # Sentiment boost
        if item.sentiment == "positive":
            score *= 1.1
        elif item.sentiment == "negative":
            score *= 0.8  # Still valuable — could be short catalyst

        return round(min(100, max(0, score)), 1)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _extract_source(self, url: str) -> str:
        sources = {
            "yahoo.com": "Yahoo Finance", "bloomberg.com": "Bloomberg",
            "reuters.com": "Reuters", "cnbc.com": "CNBC",
            "marketwatch.com": "MarketWatch", "seekingalpha.com": "Seeking Alpha",
            "wsj.com": "WSJ", "barrons.com": "Barron's",
        }
        for domain, name in sources.items():
            if domain in url:
                return name
        return "News"

    def close(self):
        self.client.close()
