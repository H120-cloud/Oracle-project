"""
News Momentum Backtest Engine (V22)

Runs the full scoring pipeline against historical news events and
compares predictions with actual price outcomes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

import pandas as pd
import yfinance as yf

from src.core.agentic.news_momentum_models import (
    NewsMomentumCandidate,
    NewsEvent,
    NewsSource,
    SessionType,
)
from src.core.agentic.news_momentum_catalyst_classifier import classify_headline
from src.core.agentic.news_momentum_impact_scorer import score_news_impact
from src.core.agentic.news_momentum_reaction_engine import compute_reaction_metrics, score_news_reaction
from src.core.agentic.news_momentum_expected_return_engine import compute_expected_return_score
from src.core.agentic.news_momentum_continuation_engine import (
    compute_continuation_probability,
    compute_multi_day_continuation,
    determine_oracle_action,
)

logger = logging.getLogger(__name__)


def fetch_historical_prices(ticker: str, event_date: str, days: int = 5) -> Optional[Dict]:
    """Fetch OHLCV around the event date. Returns dict with pre/post prices."""
    try:
        date = datetime.strptime(event_date, "%Y-%m-%d")
        start = (date - timedelta(days=2)).strftime("%Y-%m-%d")
        end = (date + timedelta(days=days + 2)).strftime("%Y-%m-%d")

        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty:
            return None

        # Flatten multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Find the closest trading day on or after event date
        event_dt = pd.Timestamp(date)
        mask = df.index >= event_dt
        if not mask.any():
            return None

        event_idx = df.index[mask][0]
        event_row = df.loc[event_idx]

        # Get prices
        pre_close = df["Close"].shift(1).loc[event_idx] if event_idx in df.index else None
        day_open = event_row["Open"]
        day_high = event_row["High"]
        day_low = event_row["Low"]
        day_close = event_row["Close"]
        volume = event_row["Volume"]

        # Next day
        next_day_mask = df.index > event_idx
        next_day_open = df["Open"][next_day_mask].iloc[0] if next_day_mask.any() else None
        next_day_high = df["High"][next_day_mask].iloc[0] if next_day_mask.any() else None
        next_day_close = df["Close"][next_day_mask].iloc[0] if next_day_mask.any() else None

        # 2-day and 5-day highs
        future_mask = df.index > event_idx
        future = df[future_mask]
        two_day_high = future["High"].iloc[:2].max() if len(future) >= 2 else None
        five_day_high = future["High"].iloc[:5].max() if len(future) >= 5 else None

        # 30-day average volume for RVOL calculation
        past = df[df.index < event_idx].tail(30)
        avg_volume = past["Volume"].mean() if len(past) >= 10 else None

        return {
            "pre_close": float(pre_close) if pre_close is not None else None,
            "day_open": float(day_open),
            "day_high": float(day_high),
            "day_low": float(day_low),
            "day_close": float(day_close),
            "volume": int(volume),
            "avg_volume": float(avg_volume) if avg_volume is not None else None,
            "next_day_open": float(next_day_open) if next_day_open is not None else None,
            "next_day_high": float(next_day_high) if next_day_high is not None else None,
            "next_day_close": float(next_day_close) if next_day_close is not None else None,
            "two_day_high": float(two_day_high) if two_day_high is not None else None,
            "five_day_high": float(five_day_high) if five_day_high is not None else None,
        }
    except Exception as exc:
        logger.debug("Backtest fetch error for %s: %s", ticker, exc)
        return None


def run_backtest(events: List[Dict]) -> List[Dict]:
    """Run full pipeline on historical events and compare with actual outcomes."""
    import pandas as pd

    results = []
    for event in events:
        ticker = event["ticker"]
        headline = event["headline"]
        date = event["date"]
        expected = event["expected"]

        logger.info("Backtest: %s on %s", ticker, date)

        prices = fetch_historical_prices(ticker, date)
        if not prices or prices["pre_close"] is None:
            logger.warning("Backtest: no price data for %s on %s", ticker, date)
            continue

        # Build candidate
        cat, sub, neg, vague = classify_headline(headline)
        c = NewsMomentumCandidate(
            ticker=ticker,
            headline=headline,
            source=NewsSource.FINVIZ,
            published_at=datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            session=SessionType.REGULAR,
            catalyst_category=cat,
            catalyst_sub_type=sub,
            is_negative=neg,
            is_vague=vague,
            current_price=prices["day_open"],
            prior_price=prices["pre_close"],
            move_pct=round(((prices["day_open"] - prices["pre_close"]) / prices["pre_close"]) * 100, 2) if prices["pre_close"] > 0 else 0,
            volume=prices["volume"],
            rvol=round(prices["volume"] / prices["avg_volume"], 2) if prices["avg_volume"] and prices["avg_volume"] > 0 else 3.0,
            float_category="low",
            market_cap_category="micro",
        )

        # Impact score
        impact = score_news_impact(
            catalyst_sub_type=c.catalyst_sub_type,
            catalyst_category=c.catalyst_category,
            float_cat=c.float_category,
            market_cap_cat=c.market_cap_category,
            move_pct=c.move_pct,
            is_negative=c.is_negative,
            is_vague=c.is_vague,
        )
        c.news_impact_score = impact.composite_score

        # Reaction score
        m = compute_reaction_metrics(
            price_before=c.prior_price,
            price_current=c.current_price,
            volume_before=prices["volume"] // 2,
            volume_current=prices["volume"],
            high=prices["day_high"],
            low=prices["day_low"],
        )
        reaction = score_news_reaction(m)
        c.news_reaction_score = reaction.composite_score
        c.trap_risk = min(reaction.composite_score * 0.3 + (100 - reaction.continuation_quality) * 0.7, 100.0)

        # Expected return
        er = compute_expected_return_score(c)
        c.expected_return_score = er.score

        # Continuation
        cp = compute_continuation_probability(c)
        c.continuation_probability = cp.same_day_continuation

        # Multi-day
        md = compute_multi_day_continuation(c, cp)
        c.multi_day_continuation_score = md.multi_day_score
        c.next_day_continuation_probability = md.next_day_continuation_probability
        c.next_day_gap_up_probability = md.next_day_gap_up_probability

        # Oracle action
        c.oracle_action = determine_oracle_action(c, cp, md)

        # Actual outcomes
        actual_day_move = round(((prices["day_high"] - prices["pre_close"]) / prices["pre_close"]) * 100, 2) if prices["pre_close"] > 0 else 0
        actual_next_day_move = round(((prices["next_day_high"] - prices["pre_close"]) / prices["pre_close"]) * 100, 2) if prices["next_day_high"] and prices["pre_close"] > 0 else None
        actual_two_day_move = round(((prices["two_day_high"] - prices["pre_close"]) / prices["pre_close"]) * 100, 2) if prices["two_day_high"] and prices["pre_close"] > 0 else None

        # Classify actual outcome
        actual = "no_follow_through"
        if actual_day_move > 20:
            actual = "continuation"
        elif actual_day_move < -10 or (actual_next_day_move and actual_next_day_move < -10):
            actual = "fade"
        elif abs(actual_day_move) < 5:
            actual = "no_follow_through"

        # Did we predict correctly?
        predicted_continuation = c.continuation_probability > 55 or c.expected_return_score > 60
        predicted_fade = c.trap_risk > 60 or c.dilution_risk > 50 or c.is_negative
        predicted_noft = c.expected_return_score < 40 and c.continuation_probability < 40

        correct = False
        if expected == "continuation" and predicted_continuation:
            correct = True
        elif expected == "fade" and predicted_fade:
            correct = True
        elif expected == "no_follow_through" and predicted_noft:
            correct = True

        results.append({
            "ticker": ticker,
            "date": date,
            "headline": headline,
            "catalyst": sub.value,
            "category": cat.value,
            "expected": expected,
            "actual": actual,
            "actual_day_move_pct": actual_day_move,
            "actual_next_day_move_pct": actual_next_day_move,
            "actual_two_day_move_pct": actual_two_day_move,
            "news_impact": c.news_impact_score,
            "expected_return": c.expected_return_score,
            "continuation_prob": c.continuation_probability,
            "multi_day_score": c.multi_day_continuation_score,
            "trap_risk": c.trap_risk,
            "oracle_action": c.oracle_action.value,
            "predicted_continuation": predicted_continuation,
            "predicted_fade": predicted_fade,
            "correct": correct,
        })

    return results


def generate_report(results: List[Dict]) -> Dict:
    """Generate summary statistics from backtest results."""
    if not results:
        return {"error": "No results"}

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = round(correct / total * 100, 1) if total > 0 else 0

    # Breakdown by expected category
    by_expected = {}
    for r in results:
        cat = r["expected"]
        if cat not in by_expected:
            by_expected[cat] = {"total": 0, "correct": 0, "avg_move": []}
        by_expected[cat]["total"] += 1
        if r["correct"]:
            by_expected[cat]["correct"] += 1
        by_expected[cat]["avg_move"].append(r["actual_day_move_pct"])

    for cat in by_expected:
        data = by_expected[cat]
        data["accuracy"] = round(data["correct"] / data["total"] * 100, 1)
        data["avg_move"] = round(sum(data["avg_move"]) / len(data["avg_move"]), 2)
        del data["avg_move"]  # rename key

    # Top performers (highest actual moves)
    top_movers = sorted(results, key=lambda x: x["actual_day_move_pct"] or 0, reverse=True)[:10]

    # False positives (predicted continuation but faded)
    false_pos = [r for r in results if r["predicted_continuation"] and r["actual"] == "fade"]

    # Missed runs (predicted fade/noft but actually continued)
    missed = [r for r in results if not r["predicted_continuation"] and r["actual"] == "continuation"]

    # Correlation between predicted score and actual move
    import statistics
    scores = [r["expected_return"] for r in results if r["actual_day_move_pct"] is not None]
    moves = [r["actual_day_move_pct"] for r in results if r["actual_day_move_pct"] is not None]
    correlation = None
    if len(scores) > 2:
        try:
            mean_s, std_s = statistics.mean(scores), statistics.stdev(scores)
            mean_m, std_m = statistics.mean(moves), statistics.stdev(moves)
            if std_s > 0 and std_m > 0:
                n = len(scores)
                correlation = round(sum((s - mean_s) * (m - mean_m) for s, m in zip(scores, moves)) / ((n - 1) * std_s * std_m), 3)
        except Exception:
            pass

    return {
        "total_events": total,
        "correct_predictions": correct,
        "overall_accuracy_pct": accuracy,
        "by_category": by_expected,
        "top_movers": [{"ticker": r["ticker"], "date": r["date"], "move": r["actual_day_move_pct"], "catalyst": r["catalyst"]} for r in top_movers],
        "false_positives": len(false_pos),
        "missed_runs": len(missed),
        "score_move_correlation": correlation,
        "avg_news_impact": round(sum(r["news_impact"] for r in results) / total, 1),
        "avg_expected_return": round(sum(r["expected_return"] for r in results) / total, 1),
        "avg_actual_move": round(sum(r["actual_day_move_pct"] or 0 for r in results) / total, 1),
    }


def run_and_print():
    from src.core.agentic.news_momentum_historical_dataset import HISTORICAL_EVENTS
    results = run_backtest(HISTORICAL_EVENTS)
    report = generate_report(results)

    print("=" * 60)
    print("NEWS MOMENTUM BACKTEST REPORT")
    print("=" * 60)
    print(f"Total Events Tested: {report['total_events']}")
    print(f"Correct Predictions: {report['correct_predictions']}")
    print(f"Overall Accuracy: {report['overall_accuracy_pct']}%")
    print(f"Score-Move Correlation: {report['score_move_correlation']}")
    print(f"False Positives: {report['false_positives']}")
    print(f"Missed Runs: {report['missed_runs']}")
    print(f"\nAvg News Impact: {report['avg_news_impact']}")
    print(f"Avg Expected Return: {report['avg_expected_return']}")
    print(f"Avg Actual Move: {report['avg_actual_move']}%")
    print("\n--- By Category ---")
    for cat, data in report["by_category"].items():
        print(f"  {cat}: {data['correct']}/{data['total']} correct ({data['accuracy']}%), avg move: {data.get('avg_move', 'N/A')}%")
    print("\n--- Top Movers ---")
    for r in report["top_movers"]:
        print(f"  {r['ticker']} ({r['date']}): +{r['move']}% | {r['catalyst']}")

    return results, report


if __name__ == "__main__":
    run_and_print()
