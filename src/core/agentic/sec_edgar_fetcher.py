"""
SEC EDGAR Fetcher (V23)

Lightweight client for SEC EDGAR public endpoints.

Key endpoints used:
- https://data.sec.gov/submissions/CIK{cik10}.json — recent filings index
- https://www.sec.gov/cgi-bin/browse-edgar?...&output=atom — RSS / Atom feed
- https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc} — filing docs

SEC requires a descriptive User-Agent. We do best-effort fetching with
graceful degradation: if any network call fails, callers fall back to
heuristics or cached data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.core.agentic.sec_filing_models import FilingType, SECFiling

logger = logging.getLogger(__name__)

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "Oracle Research oracle-research@example.com",
)

DATA_DIR = Path("data/agentic/sec")
DATA_DIR.mkdir(parents=True, exist_ok=True)

TICKER_CIK_CACHE_FILE = DATA_DIR / "ticker_cik_map.json"


# ── Ticker → CIK resolution ──────────────────────────────────────────────────


_TICKER_CIK_MAP: Dict[str, str] = {}


def _load_ticker_cik_cache() -> Dict[str, str]:
    global _TICKER_CIK_MAP
    if _TICKER_CIK_MAP:
        return _TICKER_CIK_MAP
    if TICKER_CIK_CACHE_FILE.exists():
        try:
            _TICKER_CIK_MAP = json.loads(TICKER_CIK_CACHE_FILE.read_text())
        except Exception:
            _TICKER_CIK_MAP = {}
    return _TICKER_CIK_MAP


def _save_ticker_cik_cache() -> None:
    try:
        TICKER_CIK_CACHE_FILE.write_text(json.dumps(_TICKER_CIK_MAP))
    except Exception as e:
        logger.debug("CIK cache save failed: %s", e)


async def resolve_ticker_to_cik(ticker: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Return zero-padded 10-digit CIK or None."""
    ticker = ticker.upper().strip()
    cache = _load_ticker_cik_cache()
    if ticker in cache:
        return cache[ticker]

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": SEC_USER_AGENT})
    try:
        # Pull the full ticker list once and cache it
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                for _, row in data.items():
                    t = str(row.get("ticker", "")).upper()
                    cik = str(row.get("cik_str", "")).zfill(10)
                    if t and cik:
                        cache[t] = cik
                _save_ticker_cik_cache()
                return cache.get(ticker)
        except Exception as e:
            logger.debug("ticker_to_cik fetch failed: %s", e)
    finally:
        if own_client:
            await client.aclose()
    return None


# ── Filing type parser ──────────────────────────────────────────────────────


_FILING_TYPE_MAP = {ft.value.upper(): ft for ft in FilingType}


def parse_filing_type(form: str) -> FilingType:
    if not form:
        return FilingType.UNKNOWN
    key = form.upper().strip()
    if key in _FILING_TYPE_MAP:
        return _FILING_TYPE_MAP[key]
    # Loose matching
    if key.startswith("424B"):
        return FilingType.F_424B5 if key == "424B5" else FilingType(_FILING_TYPE_MAP.get(key, FilingType.UNKNOWN))
    if key.startswith("S-1"):
        return FilingType.S_1
    if key.startswith("S-3"):
        return FilingType.S_3
    if key.startswith("8-K"):
        return FilingType.EIGHT_K
    if key.startswith("10-Q"):
        return FilingType.TEN_Q
    if key.startswith("10-K"):
        return FilingType.TEN_K
    if "14A" in key:
        return FilingType.DEF_14A
    return FilingType.UNKNOWN


# ── Recent filings fetcher ──────────────────────────────────────────────────


async def fetch_recent_filings(
    ticker: str,
    cik: Optional[str] = None,
    limit: int = 25,
    client: Optional[httpx.AsyncClient] = None,
) -> List[SECFiling]:
    """Fetch the most recent filings for a ticker (metadata + URLs)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": SEC_USER_AGENT})
    try:
        if cik is None:
            cik = await resolve_ticker_to_cik(ticker, client)
        if cik is None:
            return []

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            r = await client.get(url)
            if r.status_code != 200:
                logger.debug("EDGAR submissions %s -> %d", ticker, r.status_code)
                return []
            data = r.json()
        except Exception as e:
            logger.debug("EDGAR submissions fetch failed for %s: %s", ticker, e)
            return []

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        titles = recent.get("primaryDocDescription", []) or []

        results: List[SECFiling] = []
        for i in range(min(limit, len(forms))):
            form = forms[i]
            try:
                fdate = datetime.fromisoformat(dates[i]).replace(tzinfo=timezone.utc)
            except Exception:
                fdate = datetime.now(timezone.utc)
            acc = accs[i]
            acc_nodash = acc.replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""
            title = titles[i] if i < len(titles) else form
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}"
                if doc else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            )

            results.append(SECFiling(
                accession_number=acc,
                ticker=ticker.upper(),
                cik=cik,
                filing_type=parse_filing_type(form),
                filing_date=fdate,
                title=title or form,
                url=doc_url,
            ))
        return results
    finally:
        if own_client:
            await client.aclose()


# ── Filing body fetcher ─────────────────────────────────────────────────────


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text or "")
    return _WHITESPACE_RE.sub(" ", text).strip()


async def fetch_filing_text(
    filing: SECFiling,
    max_chars: int = 60_000,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Fetch and strip the filing's primary document HTML to plain text.

    Returns empty string on failure. Truncates to `max_chars` so we don't
    blow up memory on giant 10-Ks.
    """
    if not filing.url:
        return ""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": SEC_USER_AGENT})
    try:
        try:
            r = await client.get(filing.url)
            if r.status_code != 200:
                return ""
            text = strip_html(r.text)
            return text[:max_chars]
        except Exception as e:
            logger.debug("Filing text fetch failed for %s: %s", filing.accession_number, e)
            return ""
    finally:
        if own_client:
            await client.aclose()


# ── RSS feed (latest filings for tickers we care about) ─────────────────────


async def fetch_filings_rss(
    forms: Optional[List[str]] = None,
    limit: int = 40,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Fetch the latest filings firehose by form type.

    Used by the background loop to surface NEW filings the moment they hit.
    """
    forms = forms or ["S-1", "S-3", "424B5", "8-K", "DEF 14A"]
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": SEC_USER_AGENT})
    out: List[Dict[str, Any]] = []
    try:
        for form in forms:
            url = (
                "https://www.sec.gov/cgi-bin/browse-edgar?"
                f"action=getcompany&type={form.replace(' ', '+')}&dateb=&owner=include"
                f"&count={limit}&output=atom"
            )
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                # Naive Atom parsing — keep dependency footprint zero
                entries = re.findall(r"<entry>(.+?)</entry>", r.text, flags=re.DOTALL)
                for e in entries[:limit]:
                    title_m = re.search(r"<title>(.+?)</title>", e, flags=re.DOTALL)
                    updated_m = re.search(r"<updated>(.+?)</updated>", e, flags=re.DOTALL)
                    link_m = re.search(r'<link[^>]+href="([^"]+)"', e)
                    out.append({
                        "form": form,
                        "title": (title_m.group(1) if title_m else "").strip(),
                        "updated": (updated_m.group(1) if updated_m else "").strip(),
                        "link": link_m.group(1) if link_m else "",
                    })
            except Exception as exc:
                logger.debug("RSS fetch failed for %s: %s", form, exc)
    finally:
        if own_client:
            await client.aclose()
    return out


__all__ = [
    "SEC_USER_AGENT",
    "resolve_ticker_to_cik",
    "parse_filing_type",
    "fetch_recent_filings",
    "fetch_filing_text",
    "fetch_filings_rss",
    "strip_html",
]
