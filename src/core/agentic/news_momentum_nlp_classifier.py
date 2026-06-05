"""
NLP Semantic Classifier for News Momentum (V23)

TF-IDF-based semantic classification layer that supplements regex keyword
matching. Falls back to regex when no strong signal exists.

No new dependencies — uses sklearn TfidfVectorizer + LogisticRegression
(checked at runtime; gracefully degraded to regex-only if unavailable).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.agentic.news_momentum_models import CatalystSubType
from src.utils.atomic_json import save_json_file, load_json_file

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
NLP_MODEL_FILE = DATA_DIR / "news_momentum_nlp_model.joblib"
NLP_META_FILE = DATA_DIR / "news_momentum_nlp_meta.json"

# Label mapping
LABEL_MAP = {
    "fda_approval": 0,
    "merger_acquisition": 1,
    "partnership": 2,
    "earnings": 3,
    "ai_ml": 4,
    "government_contract": 5,
    "supply_agreement": 6,
    "share_buyback": 7,
    "insider_purchase": 8,
    "debt_restructuring": 9,
    "offering": 10,
    "reverse_split": 11,
    "delisting_notice": 12,
    "vague_pr": 13,
}

# Inverse mapping
INV_LABEL = {v: k for k, v in LABEL_MAP.items()}

# NLP label strings map to coarse buckets that don't all exist 1:1 as
# CatalystSubType values. This explicit map translates them to REAL enum
# members so the main pipeline (SUBTYPE_TO_CATEGORY, _HIGH_CONVICTION_CATALYSTS)
# routes them correctly. Without it, "merger_acquisition"/"partnership"/"ai_ml"/
# "insider_purchase" either crashed (AttributeError) or silently became VAGUE_PR.
_NLP_LABEL_TO_SUBTYPE: Dict[str, CatalystSubType] = {
    "fda_approval": CatalystSubType.FDA_APPROVAL,
    "merger_acquisition": CatalystSubType.ACQUISITION,
    "partnership": CatalystSubType.MAJOR_PARTNERSHIP,
    "earnings": CatalystSubType.EARNINGS_BEAT,
    "ai_ml": CatalystSubType.AI_PARTNERSHIP,
    "government_contract": CatalystSubType.GOVERNMENT_CONTRACT,
    "supply_agreement": CatalystSubType.SUPPLY_AGREEMENT,
    "share_buyback": CatalystSubType.SHARE_BUYBACK,
    "insider_purchase": CatalystSubType.INSIDER_BUYING,
    "debt_restructuring": CatalystSubType.DEBT_RESTRUCTURING,
    "offering": CatalystSubType.OFFERING,
    "reverse_split": CatalystSubType.REVERSE_SPLIT,
    "delisting_notice": CatalystSubType.DELISTING_NOTICE,
    "vague_pr": CatalystSubType.VAGUE_PR,
}

# Training seed data (headline patterns) — massively expanded for better differentiation
SEED_TRAINING_DATA: List[Tuple[str, str]] = [
    # ── FDA / Biotech bullish ────────────────────────────────────────────────
    ("FDA approves new treatment for rare disease", "fda_approval"),
    ("Company receives FDA clearance for medical device", "fda_approval"),
    ("FDA grants fast track designation to drug candidate", "fda_approval"),
    ("FDA approves orphan drug designation for pediatric cancer therapy", "fda_approval"),
    ("FDA clears breakthrough therapy for Alzheimer's", "fda_approval"),
    ("Company submits NDA for novel oncology drug", "fda_approval"),
    ("Positive topline data from Phase 3 trial announced", "fda_approval"),
    ("Phase 2 interim data shows strong efficacy signal", "fda_approval"),
    ("Drug launches in European market following approval", "fda_approval"),
    ("Label expansion approved for existing therapy", "fda_approval"),
    ("Commercialization agreement signed for newly approved drug", "fda_approval"),
    ("SNDA accepted by FDA for priority review", "fda_approval"),

    # ── M&A bullish ─────────────────────────────────────────────────────────
    ("Merger announcement between two pharma companies", "merger_acquisition"),
    ("Acquisition deal valued at $2 billion", "merger_acquisition"),
    ("Company to be acquired in all-cash transaction", "merger_acquisition"),
    ("Buyout offer at 40% premium to market price", "merger_acquisition"),
    ("Strategic acquisition expands market presence", "merger_acquisition"),
    ("Company acquires competitor for $500 million", "merger_acquisition"),
    ("Takeover bid receives board approval", "merger_acquisition"),
    ("Spin-off of semiconductor division announced", "merger_acquisition"),
    ("Joint venture formed with Chinese EV maker", "merger_acquisition"),

    # ── Partnerships bullish ──────────────────────────────────────────────────
    ("Strategic partnership with leading tech firm", "partnership"),
    ("Collaboration agreement signed with biotech partner", "partnership"),
    ("Joint venture announced with global pharma", "partnership"),
    ("Exclusive licensing agreement with top university", "partnership"),
    ("Distribution partnership with Walmart announced", "partnership"),
    ("Strategic alliance formed with NASA for space tech", "partnership"),
    ("Partnership with Pfizer for drug development", "partnership"),
    ("AI partnership with Microsoft transforms healthcare", "partnership"),
    ("Nvidia collaboration accelerates GPU deployment", "partnership"),
    ("OpenAI deal unlocks enterprise AI capabilities", "partnership"),

    # ── Earnings bullish ────────────────────────────────────────────────────
    ("Q4 earnings beat analyst expectations by wide margin", "earnings"),
    ("Revenue exceeds guidance by 20%", "earnings"),
    ("Strong quarterly results driven by core business", "earnings"),
    ("EPS beats consensus by $0.15", "earnings"),
    ("Company raises full-year guidance after strong Q3", "earnings"),
    ("Profitability inflection achieved in Q2", "earnings"),
    ("First profitable quarter since IPO", "earnings"),
    ("EBITDA margin expands 500 basis points", "earnings"),
    ("Revenue growth accelerates to 45% year-over-year", "earnings"),

    # ── AI/Tech bullish ─────────────────────────────────────────────────────
    ("AI-powered platform launches new features", "ai_ml"),
    ("Machine learning breakthrough announced", "ai_ml"),
    ("Company integrates generative AI into products", "ai_ml"),
    ("Quantum computing chip achieves breakthrough", "ai_ml"),
    ("Deploys 10,000 GPUs for AI training cluster", "ai_ml"),
    ("New product launch exceeds initial demand forecast", "ai_ml"),
    ("Platform expansion into European markets announced", "ai_ml"),
    ("Next-generation chip enters production", "ai_ml"),

    # ── Government/Defense bullish ──────────────────────────────────────────
    ("Wins $50 million government contract", "government_contract"),
    ("Awarded Department of Defense contract", "government_contract"),
    ("Selected for federal procurement program", "government_contract"),
    ("NASA awards $200M contract for lunar lander", "government_contract"),
    ("Pentagon selects company for drone program", "government_contract"),
    ("Receives $1B Army contract for vehicle systems", "government_contract"),
    ("Subsidy approved for domestic chip manufacturing", "government_contract"),
    ("Tariff exemption granted for imported components", "government_contract"),

    # ── Supply/Operational bullish ──────────────────────────────────────────
    ("Supply agreement with major automaker signed", "supply_agreement"),
    ("Distribution deal with global retailer", "supply_agreement"),
    ("Exclusive supply contract signed", "supply_agreement"),
    ("Long-term offtake agreement with European utility", "supply_agreement"),
    ("Power purchase agreement executed for solar farm", "supply_agreement"),
    ("OEM partnership with German automaker confirmed", "supply_agreement"),

    # ── Financial/Capital Structure bullish ─────────────────────────────────
    ("Board authorizes $100 million buyback", "share_buyback"),
    ("Share repurchase program announced", "share_buyback"),
    ("Dividend increased by 15% quarterly", "share_buyback"),
    ("2-for-1 stock split approved by shareholders", "share_buyback"),
    ("Credit rating upgraded to investment grade", "share_buyback"),
    ("Revolving credit facility expanded to $500M", "share_buyback"),
    ("Series B funding round closes at $75M valuation", "share_buyback"),
    ("CEO purchases 50,000 shares in open market", "insider_purchase"),
    ("Director buys shares in open market", "insider_purchase"),
    ("Debt restructuring extends maturities to 2030", "debt_restructuring"),
    ("Company refinances existing debt at lower rate", "debt_restructuring"),

    # ── Negative / Bearish ──────────────────────────────────────────────────
    ("Public offering of common stock priced at discount", "offering"),
    ("Registered direct offering announced at $0.50", "offering"),
    ("ATM filing authorizes up to $50M in sales", "offering"),
    ("Shelf registration for $200M mixed securities", "offering"),
    ("Reverse stock split effective at 1-for-20", "reverse_split"),
    ("1-for-10 reverse split to maintain listing compliance", "reverse_split"),
    ("Receives delisting notice from Nasdaq", "delisting_notice"),
    ("Non-compliance with continued listing standards", "delisting_notice"),
    ("Bid price deficiency notice received", "delisting_notice"),
    ("FDA issues complete response letter for NDA", "offering"),
    ("Clinical hold placed on Phase 2 study", "offering"),
    ("Trial fails to meet primary endpoint", "offering"),
    ("Patient death triggers safety review", "offering"),
    ("Workforce reduction of 25% announced", "offering"),
    ("Company files for Chapter 11 bankruptcy protection", "offering"),
    ("SEC subpoena received regarding revenue recognition", "offering"),
    ("Class action lawsuit filed by shareholders", "offering"),
    ("CEO resigns amid accounting investigation", "offering"),
    ("Product recall affects 100,000 units", "offering"),
    ("Data breach exposes customer information", "offering"),
    ("Analyst downgrades to sell on weak guidance", "offering"),
    ("Short seller report alleges fraud", "offering"),
    ("Trading suspension pending investigation", "offering"),
    ("Margin pressure from rising input costs", "offering"),
    ("Guidance cut on supply chain disruption", "offering"),
    ("Earnings miss sends stock down 30%", "offering"),
    ("Dividend suspended to preserve cash", "offering"),
    ("Credit downgraded to junk status by S&P", "offering"),
    ("Toxic convertible note with 50% discount", "offering"),

    # ── Vague / Non-specific ────────────────────────────────────────────────
    ("Update on ongoing business operations", "vague_pr"),
    ("Company announces strategic initiative", "vague_pr"),
    ("CEO to present at industry conference", "vague_pr"),
    ("Provides corporate update on Q3 progress", "vague_pr"),
    ("Comments on market speculation", "vague_pr"),
    ("Letter to shareholders outlines vision", "vague_pr"),
    ("Monitoring situation closely", "vague_pr"),
]


class NewsMomentumNLPClassifier:
    """Semantic classifier for news headlines using TF-IDF + LogisticRegression.

    Falls back to regex-based classification when:
      - sklearn is unavailable
      - model is untrained
      - prediction confidence is below threshold
    """

    def __init__(self) -> None:
        self._model: Optional[Any] = None
        self._vectorizer: Optional[Any] = None
        self._trained = False
        self._last_trained: Optional[datetime] = None
        self._meta: Dict[str, Any] = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self._meta = load_json_file(NLP_META_FILE, default={})
        self._last_trained = None
        if self._meta.get("last_trained"):
            try:
                self._last_trained = datetime.fromisoformat(self._meta["last_trained"])
            except Exception:
                pass
        # Try loading sklearn model
        try:
            import joblib
            if NLP_MODEL_FILE.exists():
                bundle = joblib.load(NLP_MODEL_FILE)
                self._vectorizer = bundle.get("vectorizer")
                self._model = bundle.get("model")
                self._trained = self._model is not None and self._vectorizer is not None
        except Exception as exc:
            logger.debug("NLP: could not load model: %s", exc)
            self._trained = False

    def _save(self) -> None:
        try:
            import joblib
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {"vectorizer": self._vectorizer, "model": self._model},
                NLP_MODEL_FILE,
            )
            self._meta["last_trained"] = datetime.now(timezone.utc).isoformat()
            save_json_file(NLP_META_FILE, self._meta)
        except Exception as exc:
            logger.warning("NLP: save failed: %s", exc)

    # ── Training ───────────────────────────────────────────────────────────────

    def train(self, additional_data: Optional[List[Tuple[str, str]]] = None) -> bool:
        """Train on seed data + optional additional labeled headlines."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
        except ImportError:
            logger.warning("NLP: sklearn unavailable, regex fallback only")
            return False

        data = list(SEED_TRAINING_DATA)
        if additional_data:
            data.extend(additional_data)

        texts = [d[0] for d in data]
        labels = [LABEL_MAP.get(d[1], LABEL_MAP["vague_pr"]) for d in data]

        # Need at least 2 classes
        if len(set(labels)) < 2:
            logger.warning("NLP: only one class in training data, skipping")
            return False

        self._vectorizer = TfidfVectorizer(
            max_features=500,
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.95,
            stop_words="english",
        )
        X = self._vectorizer.fit_transform(texts)

        self._model = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            C=0.5,  # stronger regularization for small seed data
            random_state=42,
        )
        self._model.fit(X, labels)
        self._trained = True
        self._last_trained = datetime.now(timezone.utc)
        self._meta["classes"] = list(LABEL_MAP.keys())
        self._save()
        logger.info("NLP: trained on %d headlines (%d classes)", len(data), len(set(labels)))
        return True

    # ── Prediction ─────────────────────────────────────────────────────────────

    def predict(self, headline: str) -> Tuple[CatalystSubType, float]:
        """Classify a headline. Returns (subtype, confidence).

        Confidence < 0.45 means the model is uncertain — caller should fall
        back to regex classification.
        """
        headline = (headline or "").strip()
        if not headline:
            return CatalystSubType.VAGUE_PR, 0.0

        # Try ML prediction first if trained
        if self._trained and self._model is not None and self._vectorizer is not None:
            try:
                X = self._vectorizer.transform([headline])
                proba = self._model.predict_proba(X)[0]
                pred_idx = int(self._model.predict(X)[0])
                confidence = float(proba[pred_idx])

                if confidence >= 0.45:
                    label = INV_LABEL.get(pred_idx, "vague_pr")
                    subtype = _NLP_LABEL_TO_SUBTYPE.get(label, CatalystSubType.VAGUE_PR)
                    return subtype, confidence
            except Exception as exc:
                logger.debug("NLP: prediction failed: %s", exc)

        # Regex fallback
        return self._regex_fallback(headline)

    def _regex_fallback(self, headline: str) -> Tuple[CatalystSubType, float]:
        """Fallback regex classifier for when ML is unavailable or uncertain."""
        h = headline.lower()

        patterns: List[Tuple[CatalystSubType, List[str], float]] = [
            (CatalystSubType.FDA_APPROVAL, ["fda approv", "fda clear", "fda grant", "fast track", "breakthrough therapy"], 0.80),
            (CatalystSubType.ACQUISITION, ["merger", "acquisition", "to acquire", "to be acquired", "buyout", "takeover"], 0.80),
            (CatalystSubType.MAJOR_PARTNERSHIP, ["partnership", "collaboration", "joint venture", "strategic alliance"], 0.75),
            (CatalystSubType.AI_PARTNERSHIP, ["ai-powered", "artificial intelligence", "machine learning", "generative ai", "llm", "neural network"], 0.70),
            (CatalystSubType.GOVERNMENT_CONTRACT, ["government contract", "defense contract", "federal contract", "pentagon", "dod contract", "army contract", "navy contract"], 0.80),
            (CatalystSubType.SUPPLY_AGREEMENT, ["supply agreement", "distribution agreement", "supply contract", "distribution deal", "exclusive supply"], 0.75),
            (CatalystSubType.EARNINGS_BEAT, ["earnings beat", "beats estimate", "revenue exceed", "strong quarterly", "q1 beat", "q2 beat", "q3 beat", "q4 beat"], 0.75),
            (CatalystSubType.SHARE_BUYBACK, ["buyback", "share repurchase", "stock repurchase"], 0.80),
            (CatalystSubType.INSIDER_BUYING, ["insider purchas", "director buy", "ceo purchas", "officer purchas"], 0.75),
            (CatalystSubType.DEBT_RESTRUCTURING, ["debt restructuring", "refinance", "debt exchange"], 0.70),
            (CatalystSubType.OFFERING, ["public offering", "registered direct", "atm offering", "equity offering"], 0.80),
            (CatalystSubType.REVERSE_SPLIT, ["reverse split", "reverse stock split"], 0.90),
            (CatalystSubType.DELISTING_NOTICE, ["delisting", "continued listing", "non-compliance"], 0.85),
        ]

        for subtype, keywords, conf in patterns:
            for kw in keywords:
                if kw in h:
                    return subtype, conf

        return CatalystSubType.VAGUE_PR, 0.40

    # ── Auto-train on startup ─────────────────────────────────────────────────

    def ensure_trained(self) -> bool:
        """Train if not already trained or model is stale (>30 days)."""
        if not self._trained:
            return self.train()
        if self._last_trained:
            age = datetime.now(timezone.utc) - self._last_trained
            if age > timedelta(days=30):
                logger.info("NLP: model stale (>30d), retraining")
                return self.train()
        return True


# Singleton for module-level import
_nlp_classifier: Optional[NewsMomentumNLPClassifier] = None


def get_nlp_classifier() -> NewsMomentumNLPClassifier:
    global _nlp_classifier
    if _nlp_classifier is None:
        _nlp_classifier = NewsMomentumNLPClassifier()
    return _nlp_classifier


def classify_headline(headline: str) -> Tuple[CatalystSubType, float]:
    """Convenience function: classify a single headline."""
    clf = get_nlp_classifier()
    clf.ensure_trained()
    return clf.predict(headline)
