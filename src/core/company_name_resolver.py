"""
Company name -> ticker resolver.

Some sources (e.g. Sharecast press notes) publish headlines with a company
NAME but no ticker symbol. This resolver maps a normalized company name to a
US-listed ticker using SEC's company_tickers.json (ticker + title), which the
SEC firehose already relies on.

Design:
- Builds a {normalized_name: ticker} map once, cached to disk (refreshed if the
  cache is missing or older than 30 days).
- Conservative matching: exact normalized-name match only (no fuzzy), so we
  never mis-attribute a headline to the wrong company. Names that don't resolve
  to a US ticker return None and the caller drops the item -- which is correct
  for UK-only funds/trusts that aren't US-tradeable.
"""
from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

from src.utils.data_paths import AGENTIC_DATA_DIR as DATA_DIR
NAME_MAP_CACHE = DATA_DIR / "company_name_ticker_map.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "Oracle research oracle@example.com"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days

# Corporate suffixes stripped during normalization (so "Apple Inc" == "Apple").
_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|"
    r"holdings|holding|group|sa|nv|ag|the|class|common|stock|ord|ordinary|"
    r"shares|adr|ads)\b",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r"[.,&/()'\"]", " ", n)
    n = _SUFFIXES.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


# Generic financial markers / corporate designators that must NEVER drive a
# match on their own. A name made only of these (e.g. "Global Holdings Group")
# resolves to nothing. Distinct from _SUFFIXES (which is about normalization);
# this set is about *significance* of the remaining tokens.
_GENERIC_TOKENS = frozenset({
    "global", "international", "technologies", "technology", "holdings",
    "holding", "group", "groupe", "corp", "corporation", "inc", "incorporated",
    "company", "co", "partners", "partner", "industries", "systems", "solutions",
    "enterprises", "enterprise", "capital", "financial", "ventures", "venture",
    "labs", "laboratories", "resources", "acquisition", "acquisitions", "trust",
    "fund", "funds", "limited", "ltd", "plc", "llc", "lp", "sa", "nv", "ag",
    "the", "class", "common", "stock", "ord", "ordinary", "shares", "adr",
    "ads", "new", "american", "us", "usa", "national", "associates", "company",
})

# Minimum difflib similarity ratio for a non-exact (fuzzy) match. Chosen to
# accept benign designator drift ("Technology" vs "Technologies": ~0.97;
# "Apple Hospitality" vs "Apple Hospitality REIT": ~0.87) while rejecting
# prefix-magnet false matches ("Plug Power Solutions ..." vs "Plug Power":
# ~0.48; "Apple Hospitality" vs "Apple": 0.5).
_MIN_FUZZY_RATIO = 0.85


def _significant_tokens(normalized: str) -> list[str]:
    """Tokens of a normalized name that carry company identity (non-generic)."""
    return [t for t in normalized.split() if t and t not in _GENERIC_TOKENS]


class CompanyNameResolver:
    _instance: Optional["CompanyNameResolver"] = None

    def __init__(self):
        self._map: dict[str, str] = {}
        self._loaded = False
        # first-significant-token -> list of normalized map keys (built lazily).
        self._index: Optional[dict[str, list[str]]] = None

    @classmethod
    def instance(cls) -> "CompanyNameResolver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_cache(self) -> bool:
        if not NAME_MAP_CACHE.exists():
            return False
        try:
            if (time.time() - NAME_MAP_CACHE.stat().st_mtime) > CACHE_MAX_AGE_SECONDS:
                return False
            self._map = json.loads(NAME_MAP_CACHE.read_text())
            self._index = None
            return bool(self._map)
        except Exception:
            return False

    def _build_from_sec(self) -> None:
        try:
            r = httpx.get(SEC_TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT}, timeout=20)
            if r.status_code != 200:
                logger.warning("CompanyNameResolver: SEC fetch %s", r.status_code)
                return
            data = r.json()
            mapping: dict[str, str] = {}
            for row in data.values():
                t = str(row.get("ticker", "")).upper()
                nm = normalize_name(row.get("title", ""))
                # First ticker wins for a given normalized name (primary listing).
                if t and nm and nm not in mapping:
                    mapping[nm] = t
            self._map = mapping
            self._index = None
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                NAME_MAP_CACHE.write_text(json.dumps(mapping))
            except Exception as exc:
                logger.debug("CompanyNameResolver: cache save failed: %s", exc)
            logger.info("CompanyNameResolver: built %d name->ticker entries", len(mapping))
        except Exception as exc:
            logger.warning("CompanyNameResolver: build failed: %s", exc)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._load_cache():
            self._build_from_sec()
        self._loaded = True

    def _ensure_index(self) -> None:
        """Bucket map keys by their first significant token for fast, scoped
        fuzzy lookup. Rebuilt whenever the map identity changes."""
        if self._index is not None:
            return
        index: dict[str, list[str]] = {}
        for key in self._map:
            sig = _significant_tokens(key)
            if not sig:
                continue
            index.setdefault(sig[0], []).append(key)
        self._index = index

    def resolve(self, name: str) -> Optional[str]:
        """Return a US ticker for a company name, or None if no confident match.

        Resolution is strict and deterministic — it never guesses a high-cap
        ticker from a shared prefix:

        1. Exact normalized match wins.
        2. Otherwise, candidates are limited to map entries sharing the query's
           first *significant* (non-generic) token, and the best one must clear
           a string-distance threshold AND be token-compatible (one name's
           significant tokens a subset of the other's).
        3. Names that are entirely generic ("Global Holdings Group") or fall
           below the threshold return None.
        """
        self._ensure_loaded()
        if not self._map:
            return None
        nm = normalize_name(name)
        if not nm:
            return None

        # 1. Exact normalized match — highest confidence.
        hit = self._map.get(nm)
        if hit:
            return hit

        # 2. Fuzzy, scoped to a single first-significant-token bucket.
        query_sig = _significant_tokens(nm)
        if not query_sig:
            logger.debug("CompanyNameResolver: '%s' is all-generic — dropping", name)
            return None

        self._ensure_index()
        candidates = (self._index or {}).get(query_sig[0], [])
        query_set = set(query_sig)

        best_key: Optional[str] = None
        best_ratio = 0.0
        for key in candidates:
            key_set = set(_significant_tokens(key))
            # Token-compatibility: one name must be contained in the other.
            if not (query_set <= key_set or key_set <= query_set):
                continue
            ratio = SequenceMatcher(None, nm, key).ratio()
            if ratio > best_ratio:
                best_ratio, best_key = ratio, key

        if best_key is not None and best_ratio >= _MIN_FUZZY_RATIO:
            return self._map[best_key]

        logger.debug(
            "CompanyNameResolver: no confident match for '%s' (best=%.3f) — dropping",
            name, best_ratio,
        )
        return None


def resolve_company_ticker(name: str) -> Optional[str]:
    return CompanyNameResolver.instance().resolve(name)


__all__ = ["resolve_company_ticker", "CompanyNameResolver", "normalize_name"]
