from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_expected_return_engine import compute_expected_return_score
from src.core.agentic.news_momentum_models import (
    CatalystCategory,
    CatalystSubType,
    FloatCategory,
    MarketCapCategory,
    NewsMomentumCandidate,
    NewsMomentumConfig,
    NewsSource,
    PriceBucket,
    SessionType,
)
from src.core.agentic.news_momentum_orchestrator import NewsMomentumOrchestrator


@dataclass(frozen=True)
class FakeCase:
    ticker: str
    headline: str
    actual_outcome: str
    published_age_seconds: int
    current_price: float
    prior_price: float
    volume: int
    rvol: float
    float_shares: int
    market_cap: int
    continuation_probability: float
    multi_day_score: float
    expected_alert: bool


FAKE_CASES: list[FakeCase] = [
    FakeCase(
        "ORCK", "ORCK wins $240 million government contract for immediate deployment",
        "ROCKET", 45, 2.40, 2.05, 12_000_000, 18.0, 9_000_000, 21_600_000, 72.0, 68.0, True,
    ),
    FakeCase(
        "LGD1", "LGD1 announces FDA approval for breakthrough oncology therapy",
        "LEGENDARY", 55, 1.20, 0.82, 34_000_000, 64.0, 2_500_000, 3_000_000, 86.0, 88.0, True,
    ),
    FakeCase(
        "LGD2", "LGD2 to be acquired in all-cash transaction at 310 percent premium",
        "LEGENDARY", 70, 3.10, 1.90, 28_000_000, 42.0, 4_800_000, 14_880_000, 84.0, 86.0, True,
    ),
    FakeCase(
        "LGD3", "LGD3 secures NVIDIA AI partnership for commercial robotics rollout",
        "LEGENDARY", 80, 4.60, 3.20, 30_500_000, 51.0, 6_200_000, 28_520_000, 82.0, 84.0, True,
    ),
    FakeCase(
        "NRN1", "NRN1 announces investor presentation at upcoming conference",
        "NON_RUNNER", 50, 6.10, 6.05, 180_000, 0.8, 92_000_000, 561_200_000, 18.0, 12.0, False,
    ),
    FakeCase(
        "NRN2", "NRN2 prices registered direct offering with warrants",
        "NON_RUNNER", 60, 1.30, 1.45, 4_600_000, 7.0, 70_000_000, 91_000_000, 12.0, 8.0, False,
    ),
    FakeCase(
        "NRN3", "NRN3 announces one-for-twenty reverse stock split",
        "NON_RUNNER", 65, 0.42, 0.48, 2_800_000, 5.0, 110_000_000, 46_200_000, 10.0, 6.0, False,
    ),
    FakeCase(
        "NRN4", "NRN4 provides corporate update",
        "NON_RUNNER", 75, 2.20, 2.18, 350_000, 1.1, 88_000_000, 193_600_000, 20.0, 14.0, False,
    ),
    FakeCase(
        "NRN5", "NRN5 receives Nasdaq minimum bid deficiency notice",
        "NON_RUNNER", 90, 0.77, 0.82, 2_100_000, 3.5, 64_000_000, 49_280_000, 8.0, 5.0, False,
    ),
    FakeCase(
        "NRN6", "NRN6 schedules annual shareholder meeting",
        "NON_RUNNER", 95, 8.40, 8.37, 90_000, 0.6, 150_000_000, 1_260_000_000, 16.0, 10.0, False,
    ),
]


class FakeSiteHandler(BaseHTTPRequestHandler):
    cases: list[FakeCase] = FAKE_CASES
    now: datetime = datetime.now(timezone.utc)

    def log_message(self, *_args: Any) -> None:
        return

    def _send(self, body: str, content_type: str = "text/html") -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/news"):
            articles = []
            for case in self.cases:
                published = self.now - timedelta(seconds=case.published_age_seconds)
                articles.append(
                    '<article class="news-card" '
                    f'data-ticker="{case.ticker}" '
                    f'data-published-at="{published.isoformat()}" '
                    f'data-url="/story/{case.ticker}">'
                    f"<h2>{html.escape(case.headline)}</h2>"
                    f"<p>Outcome label for offline audit: {case.actual_outcome}</p>"
                    "</article>"
                )
            self._send("<html><body>" + "\n".join(articles) + "</body></html>")
            return

        if self.path.startswith("/quote/"):
            ticker = self.path.rsplit("/", 1)[-1].upper()
            case = next((item for item in self.cases if item.ticker == ticker), None)
            if case is None:
                self.send_response(404)
                self.end_headers()
                return
            self._send(json.dumps({
                "ticker": case.ticker,
                "current_price": case.current_price,
                "prior_price": case.prior_price,
                "volume": case.volume,
                "rvol": case.rvol,
                "float_shares": case.float_shares,
                "market_cap": case.market_cap,
                "continuation_probability": case.continuation_probability,
                "multi_day_score": case.multi_day_score,
                "actual_outcome": case.actual_outcome,
                "expected_alert": case.expected_alert,
            }), content_type="application/json")
            return

        self.send_response(404)
        self.end_headers()


class NewsHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._inside_headline = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "article" and attrs_dict.get("data-ticker"):
            self._current = {
                "ticker": attrs_dict["data-ticker"],
                "published_at": attrs_dict.get("data-published-at"),
                "url": attrs_dict.get("data-url"),
                "headline": "",
            }
        elif tag == "h2" and self._current is not None:
            self._inside_headline = True

    def handle_data(self, data: str) -> None:
        if self._inside_headline and self._current is not None:
            self._current["headline"] += data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._inside_headline = False
        elif tag == "article" and self._current is not None:
            self.items.append(self._current)
            self._current = None


def price_bucket(price: float) -> PriceBucket:
    if price < 0.01:
        return PriceBucket.SUB_PENNY
    if price < 1:
        return PriceBucket.UNDER_1
    if price < 5:
        return PriceBucket.UNDER_5
    if price < 10:
        return PriceBucket.UNDER_10
    return PriceBucket.MID_CAP


def float_category(float_shares: int) -> FloatCategory:
    if float_shares < 5_000_000:
        return FloatCategory.ULTRA_LOW
    if float_shares < 20_000_000:
        return FloatCategory.LOW
    if float_shares < 100_000_000:
        return FloatCategory.MEDIUM
    return FloatCategory.HIGH


def market_cap_category(market_cap: int) -> MarketCapCategory:
    if market_cap < 50_000_000:
        return MarketCapCategory.NANO
    if market_cap < 300_000_000:
        return MarketCapCategory.MICRO
    if market_cap < 2_000_000_000:
        return MarketCapCategory.SMALL
    return MarketCapCategory.ALL


def minimal_orchestrator() -> NewsMomentumOrchestrator:
    orch = object.__new__(NewsMomentumOrchestrator)
    orch.config = NewsMomentumConfig(learning_enabled=False)
    orch._alert_cooldown = {}
    orch._headline_alert_cooldown = {}
    orch._unknown_learner = None
    return orch


def fetch_fake_news(base_url: str) -> list[dict[str, Any]]:
    with urlopen(f"{base_url}/news", timeout=5) as response:
        html_body = response.read().decode("utf-8")
    parser = NewsHTMLParser()
    parser.feed(html_body)
    return parser.items


def fetch_fake_quote(base_url: str, ticker: str) -> dict[str, Any]:
    with urlopen(f"{base_url}/quote/{ticker}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def build_candidate(item: dict[str, Any], quote: dict[str, Any], base_url: str) -> NewsMomentumCandidate:
    now = datetime.now(timezone.utc)
    category, subtype, is_negative, is_vague = classify_headline(item["headline"])
    current = float(quote["current_price"])
    prior = float(quote["prior_price"])
    move_pct = ((current - prior) / prior) * 100 if prior else 0.0
    return NewsMomentumCandidate(
        ticker=item["ticker"],
        headline=item["headline"],
        source=NewsSource.ORACLE_SCANNER,
        source_url=f"{base_url}{item['url']}",
        raw_text=item["headline"],
        published_at=datetime.fromisoformat(item["published_at"]),
        detected_at=now,
        fetched_at=now,
        parsed_at=now,
        classified_at=now,
        session=SessionType.REGULAR,
        catalyst_category=category or CatalystCategory.UNKNOWN,
        catalyst_sub_type=subtype or CatalystSubType.OTHER,
        is_negative=is_negative,
        is_vague=is_vague,
        current_price=current,
        prior_price=prior,
        move_pct=round(move_pct, 2),
        volume=int(quote["volume"]),
        rvol=float(quote["rvol"]),
        float_shares=int(quote["float_shares"]),
        market_cap=int(quote["market_cap"]),
        price_bucket=price_bucket(current),
        float_category=float_category(int(quote["float_shares"])),
        market_cap_category=market_cap_category(int(quote["market_cap"])),
        continuation_probability=float(quote["continuation_probability"]),
        multi_day_continuation_score=float(quote["multi_day_score"]),
        dilution_risk=90.0 if subtype in {CatalystSubType.OFFERING, CatalystSubType.ATM_FILING, CatalystSubType.TOXIC_FINANCING} else 5.0,
        trap_risk=85.0 if subtype in {CatalystSubType.REVERSE_SPLIT, CatalystSubType.DELISTING_NOTICE} else 8.0,
        price_status="fake_site",
    )


def evaluate_candidate(orch: NewsMomentumOrchestrator, candidate: NewsMomentumCandidate) -> bool:
    candidate.news_impact_score = orch._compute_impact_score(candidate)
    candidate.news_reaction_score = orch._compute_reaction_score(candidate)
    candidate.expected_return_score = compute_expected_return_score(candidate).score
    return orch._should_send_telegram_impl(candidate, adaptive={})


def run_simulation(base_url: str) -> dict[str, Any]:
    orch = minimal_orchestrator()
    rows = []
    telegram_messages: list[dict[str, str]] = []

    for item in fetch_fake_news(base_url):
        quote = fetch_fake_quote(base_url, item["ticker"])
        candidate = build_candidate(item, quote, base_url)
        would_alert = evaluate_candidate(orch, candidate)
        if would_alert:
            telegram_messages.append({
                "ticker": candidate.ticker,
                "headline": candidate.headline,
                "alert_type": "dry_run_news_momentum",
            })
        rows.append({
            "ticker": candidate.ticker,
            "headline": candidate.headline,
            "actual_outcome": quote["actual_outcome"],
            "expected_alert": bool(quote["expected_alert"]),
            "would_alert": would_alert,
            "block_reason": getattr(candidate, "_block_reason", None),
            "catalyst_category": candidate.catalyst_category.value,
            "catalyst_sub_type": candidate.catalyst_sub_type.value,
            "is_negative": candidate.is_negative,
            "is_vague": candidate.is_vague,
            "move_pct": candidate.move_pct,
            "rvol": candidate.rvol,
            "news_impact_score": candidate.news_impact_score,
            "news_reaction_score": candidate.news_reaction_score,
            "expected_return_score": candidate.expected_return_score,
            "continuation_probability": candidate.continuation_probability,
            "telegram_dry_run_sent": would_alert,
        })

    positives = [row for row in rows if row["expected_alert"]]
    negatives = [row for row in rows if not row["expected_alert"]]
    alerts = [row for row in rows if row["would_alert"]]
    misses = [row for row in positives if not row["would_alert"]]
    false_alerts = [row for row in negatives if row["would_alert"]]
    return {
        "base_url": base_url,
        "total_cases": len(rows),
        "expected_positive_cases": len(positives),
        "expected_non_runner_cases": len(negatives),
        "dry_run_telegram_alerts": len(alerts),
        "positive_alert_recall_pct": round((len(positives) - len(misses)) / len(positives) * 100, 1) if positives else 0.0,
        "non_runner_suppression_pct": round((len(negatives) - len(false_alerts)) / len(negatives) * 100, 1) if negatives else 0.0,
        "misses": misses,
        "false_alerts": false_alerts,
        "telegram_messages": telegram_messages,
        "rows": rows,
    }


def run_with_local_fake_site() -> dict[str, Any]:
    FakeSiteHandler.now = datetime.now(timezone.utc)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        return run_simulation(f"http://{host}:{port}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Run Oracle against a fake local rocket-news website.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    args = parser.parse_args()
    result = run_with_local_fake_site()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Oracle fake rocket-news website simulation")
        print(f"Cases: {result['total_cases']}")
        print(f"Dry-run Telegram alerts: {result['dry_run_telegram_alerts']}")
        print(f"Positive alert recall: {result['positive_alert_recall_pct']}%")
        print(f"Non-runner suppression: {result['non_runner_suppression_pct']}%")
        print(f"Misses: {len(result['misses'])}")
        print(f"False alerts: {len(result['false_alerts'])}")
        if result["misses"]:
            print("Missed positives:")
            for row in result["misses"]:
                print(f"  - {row['ticker']}: {row['block_reason']} | {row['headline']}")
        if result["false_alerts"]:
            print("False alerts:")
            for row in result["false_alerts"]:
                print(f"  - {row['ticker']}: {row['actual_outcome']} | {row['headline']}")


if __name__ == "__main__":
    asyncio.run(_main())
