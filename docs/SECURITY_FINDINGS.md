# Security Findings — News Scraper & API Audit

Date: 2026-05-28
Scope: `FinvizNewsScraper`, `StockTitanScraper`, related API routes, and frontend rendering paths.

---

## 1. XSS (Cross-Site Scripting) — CONFIRMED, MEDIUM SEVERITY

### Finding
`frontend/src/pages/Watchlist.jsx:550` renders scraped news headlines via `dangerouslySetInnerHTML`:

```jsx
<div
  className="text-gray-300 leading-tight"
  dangerouslySetInnerHTML={{ __html: highlightKeywords(n.headline) }}
/>
```

`highlightKeywords` wraps regex-matched words in `<span>` tags and returns raw HTML. If a scraped headline contains `<script>`, `<img onerror=...>`, or other HTML/JS payloads, it will execute in the user's browser.

### Risk
- Scraped headlines originate from Finviz and StockTitan RSS — **untrusted external sources**.
- Even though Finviz likely sanitizes its own HTML, the system should not rely on third-party sanitization.
- A compromised news source or a malicious PR newswire submission could inject arbitrary JavaScript.

### Recommended Fix
Replace `dangerouslySetInnerHTML` with a safe text-rendering approach:

1. **Option A (preferred)**: Split the headline into text segments and render each keyword in a `<span>` via React JSX, avoiding raw HTML injection entirely.
2. **Option B**: Pre-sanitize the headline with a library like `DOMPurify` before passing it to `dangerouslySetInnerHTML`.

### Status
**Open** — requires frontend change in `Watchlist.jsx`.

---

## 2. SSRF (Server-Side Request Forgery) — NOT EXPLOITABLE, LOW RISK

### Finding
`FinvizNewsScraper.fetch_ticker_news(ticker)` constructs a request URL using user-provided ticker input:

```python
QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}&p=d"
html = await self._get(self.QUOTE_URL.format(ticker=ticker.upper()))
```

This is called from:
- `src/api/routes/watchlist.py` — `/{ticker}/news` endpoint (direct user input)
- `src/main.py` — background news scan (indirect, ticker derived from scraped news)

### Risk Assessment
- **Host cannot be manipulated**: The base URL is hardcoded to `finviz.com`.
- **Path cannot be manipulated**: The ticker is inserted into a query parameter, not the path.
- **URL encoding**: `httpx` URL-encodes special characters (e.g., `../` becomes `%2F..%2F`), so path-traversal sequences are harmless.
- A ticker like `AAPL&url=http://evil.com` would be encoded to `AAPL%26url%3Dhttp%3A%2F%2Fevil.com` and treated by Finviz as a single invalid ticker string.

### Defense-in-Depth Recommendation
Add ticker format validation to API routes that accept ticker parameters:

```python
import re
from fastapi import HTTPException

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

def _validate_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker format")
    return t
```

Apply this to `watchlist.py` and any other route that passes tickers to scrapers.

### Status
**Mitigated by architecture** — no immediate code change required, but ticker validation is recommended.

---

## 3. Certificate Validation — NO ISSUE

### Finding
Both scrapers use `httpx.AsyncClient` with **default SSL settings**:

- `src/core/finviz_news.py:100`
  ```python
  async with httpx.AsyncClient(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
  ```
- `src/core/stocktitan_news.py:94`
  ```python
  async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
  ```

No `verify=False`, `ssl=False`, `CERT_NONE`, or similar overrides were found anywhere in `src/`.

### Status
**No action required.**

---

## Summary Table

| Finding | Severity | Status | Action Required |
|---------|----------|--------|-----------------|
| XSS in Watchlist headline rendering | Medium | **Open** | Replace `dangerouslySetInnerHTML` with safe JSX rendering or sanitize with DOMPurify |
| SSRF via ticker parameter | Low | **Mitigated** | Add ticker regex validation to API routes (defense-in-depth) |
| Disabled certificate validation | N/A | **No issue** | None |
