"""SEC EDGAR real-time 8-K firehose — V12 (Phase 2).

Polls EDGAR's global "current filings" feed (action=getcurrent) for freshly
filed 8-Ks across ALL companies. Material events (M&A, FDA actions, big
contracts, earnings) frequently hit EDGAR as an 8-K *before* the PR newswire
crosses, so this is a low-latency catalyst source that complements the Alpaca
news stream.

Endpoint:
  https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom

Design notes:
- Resolves filer CIK -> ticker using SEC's company_tickers.json (reverse of the
  ticker->CIK map the fetcher already builds). Filings whose CIK has no ticker
  (funds, trusts, foreign private issuers) are dropped — they aren't tradable.
- Dedups by accession number so each filing is emitted exactly once.
- Zero extra deps: regex Atom parsing, matching sec_edgar_fetcher's style.
"""

from __future__ import annotations

import json
import logging
import re
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

from src.core.agentic.sec_edgar_fetcher import SEC_USER_AGENT, DATA_DIR
from src.core.agentic.sec_filing_analyzer import apply_analysis_to_filing
from src.core.agentic.sec_filing_models import FilingType, SECFiling

logger = logging.getLogger(__name__)

CIK_TICKER_CACHE_FILE = DATA_DIR / "cik_ticker_map.json"
GETCURRENT_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type={form}&company=&dateb=&owner=include&count={count}&output=atom"
)

_CIK_TICKER_MAP: Dict[str, str] = {}


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def build_sec_event_headline(filing: Dict[str, Any], content_text: str = "") -> str:
    """Build a more specific SEC event headline when filing text allows it."""
    company = filing.get("company") or filing.get("ticker") or "Company"
    form = filing.get("form") or "8-K"
    fallback = f"{company} filed SEC Form {form}"
    text = (content_text or filing.get("summary") or "").strip()
    if not text:
        return fallback

    sec_filing = SECFiling(
        accession_number=filing.get("accession") or "",
        ticker=filing.get("ticker") or "",
        cik=filing.get("cik"),
        filing_type=FilingType.EIGHT_K if str(form).upper() == "8-K" else FilingType.UNKNOWN,
        filing_date=filing.get("published_at") or datetime.now(timezone.utc),
        title=fallback,
        summary=text[:1000],
        url=filing.get("url"),
    )
    analyzed = apply_analysis_to_filing(sec_filing, text)
    lower = text.lower()

    if re.search(r"\b(merger|merge|acquisition|acquire[sd]?|definitive agreement|all-cash transaction|business combination)\b", lower):
        return f"{company} filed SEC Form {form}: M&A / acquisition update"
    if analyzed.dilution_events or re.search(r"\b(registered direct|public offering|pipe financing|convertible note|warrant|atm offering)\b", lower):
        return f"{company} filed SEC Form {form}: financing / dilution update"
    if re.search(r"\b(delisting|nasdaq deficiency|minimum bid|compliance notice|listing rule)\b", lower):
        return f"{company} filed SEC Form {form}: Nasdaq compliance / delisting update"
    if analyzed.positive_signals:
        return f"{company} filed SEC Form {form}: balance-sheet improvement update"
    return fallback


async def enrich_filing_content(filing: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, Any]:
    """Fetch lightweight filing content/title when available and enrich headline."""
    content = filing.get("summary") or ""
    url = filing.get("url") or ""
    if url:
        try:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code == 200:
                content = f"{content} {_strip_tags(resp.text)[:5000]}".strip()
        except Exception as exc:
            logger.debug("SEC firehose content fetch failed for %s: %s", filing.get("accession"), exc)
    enriched = dict(filing)
    enriched["content_excerpt"] = content[:3000]
    enriched["headline"] = build_sec_event_headline(filing, content)
    return enriched


async def _load_cik_ticker_map(client: httpx.AsyncClient) -> Dict[str, str]:
    """Build/return the CIK(10-digit) -> ticker map from SEC's master list."""
    global _CIK_TICKER_MAP
    if _CIK_TICKER_MAP:
        return _CIK_TICKER_MAP
    if CIK_TICKER_CACHE_FILE.exists():
        try:
            _CIK_TICKER_MAP = json.loads(CIK_TICKER_CACHE_FILE.read_text())
            if _CIK_TICKER_MAP:
                return _CIK_TICKER_MAP
        except Exception:
            _CIK_TICKER_MAP = {}
    try:
        r = await client.get("https://www.sec.gov/files/company_tickers.json")
        if r.status_code == 200:
            data = r.json()
            mapping: Dict[str, str] = {}
            for _, row in data.items():
                t = str(row.get("ticker", "")).upper()
                cik = str(row.get("cik_str", "")).zfill(10)
                # First ticker wins for a given CIK (primary listing).
                if t and cik and cik not in mapping:
                    mapping[cik] = t
            _CIK_TICKER_MAP = mapping
            try:
                CIK_TICKER_CACHE_FILE.write_text(json.dumps(mapping))
            except Exception as exc:
                logger.debug("CIK->ticker cache save failed: %s", exc)
    except Exception as exc:
        logger.debug("CIK->ticker map fetch failed: %s", exc)
    return _CIK_TICKER_MAP


def _parse_updated(value: str) -> datetime:
    """Parse an Atom <updated> ISO timestamp to aware UTC."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


async def fetch_current_filings(
    seen_accessions: Set[str],
    form: str = "8-K",
    count: int = 100,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Poll EDGAR getcurrent for `form`, return NEW filings resolved to tickers.

    `seen_accessions` is mutated in place with every accession observed, so
    repeated calls only ever return filings not previously emitted.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": SEC_USER_AGENT}
        )
    out: List[Dict[str, Any]] = []
    try:
        cik_map = await _load_cik_ticker_map(client)
        url = GETCURRENT_URL.format(form=form.replace(" ", "+"), count=count)
        r = await client.get(url)
        if r.status_code != 200:
            logger.debug("EDGAR getcurrent %s returned %s", form, r.status_code)
            return out

        entries = re.findall(r"<entry>(.+?)</entry>", r.text, flags=re.DOTALL)
        first_run = not seen_accessions
        for e in entries:
            title_m = re.search(r"<title>(.+?)</title>", e, flags=re.DOTALL)
            summary_m = re.search(r"<summary>(.+?)</summary>", e, flags=re.DOTALL)
            updated_m = re.search(r"<updated>(.+?)</updated>", e, flags=re.DOTALL)
            id_m = re.search(r"accession-number=(\S+?)<", e)
            link_m = re.search(r'<link[^>]+href="([^"]+)"', e)
            title = (title_m.group(1) if title_m else "").strip()
            accession = (id_m.group(1) if id_m else "").strip()
            if not accession or accession in seen_accessions:
                continue
            seen_accessions.add(accession)
            # On the very first poll we only seed the dedup set — we don't want
            # to fire a burst of alerts for filings that are already old.
            if first_run:
                continue

            cik_m = re.search(r"\((\d{10})\)", title)
            cik = cik_m.group(1) if cik_m else None
            ticker = cik_map.get(cik) if cik else None
            if not ticker:
                continue

            # Company name = title minus the "FORM - " prefix and "(CIK) (Filer)" suffix.
            company = re.sub(r"^\S+\s*-\s*", "", title)
            company = re.sub(r"\s*\(\d{10}\).*$", "", company).strip()

            out.append({
                "ticker": ticker,
                "company": company or ticker,
                "form": form,
                "accession": accession,
                "published_at": _parse_updated(updated_m.group(1) if updated_m else ""),
                "url": link_m.group(1) if link_m else "",
                "summary": _strip_tags(summary_m.group(1) if summary_m else ""),
            })
    except Exception as exc:
        logger.debug("EDGAR firehose error for %s: %s", form, exc)
    finally:
        if own_client:
            await client.aclose()
    return out


__all__ = ["build_sec_event_headline", "enrich_filing_content", "fetch_current_filings"]
