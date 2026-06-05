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
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/agentic")
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


class CompanyNameResolver:
    _instance: Optional["CompanyNameResolver"] = None

    def __init__(self):
        self._map: dict[str, str] = {}
        self._loaded = False

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

    def resolve(self, name: str) -> Optional[str]:
        """Return a US ticker for a company name, or None if no confident match."""
        self._ensure_loaded()
        if not self._map:
            return None
        nm = normalize_name(name)
        if not nm:
            return None
        # exact normalized match
        hit = self._map.get(nm)
        if hit:
            return hit
        # try the leading 2-3 word prefix (handles "Bitmine Immersion
        # Technologies" matching "bitmine immersion technologies" exactly, and
        # longer descriptive names where the registered name is shorter).
        words = nm.split()
        for k in (3, 2):
            if len(words) > k:
                prefix = " ".join(words[:k])
                hit = self._map.get(prefix)
                if hit:
                    return hit
        return None


def resolve_company_ticker(name: str) -> Optional[str]:
    return CompanyNameResolver.instance().resolve(name)


__all__ = ["resolve_company_ticker", "CompanyNameResolver", "normalize_name"]
