#!/usr/bin/env python3
"""Generate synthetic baseline snapshots for testing the baseline comparison system."""

import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

random.seed(43)

BASE_DIR = Path("data/agentic")
BASELINE_FILE = BASE_DIR / "pre_news_baseline_snapshots.json"
REPORTS_DIR = BASE_DIR / "evaluation_reports"

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX",
    "AMD", "CRM", "UBER", "COIN", "PLTR", "RIVN", "LCID", "SOFI",
    "SPCE", "MRNA", "ARKK", "IWM", "QQQ", "SPY", "XBI", "XLF",
    "MARA", "RIOT", "HOOD", "DKNG", "PTON", "ZM", "DOCU", "SQ",
    "PYPL", "SHOP", "ROKU", "TWLO", "NET", "DDOG", "SNOW", "CRWD",
    "OKTA", "ZI", "ASAN", "MDB", "FSLY", "DDOG", "S", "PLUG",
    "FCEL", "BLNK", "QS", "SPWR", "ENPH", "SEDG", "RUN", "NOVA",
]

BASELINE_TYPES = [
    "TOP_GAINERS_BASELINE", "HIGH_RVOL_BASELINE", "BREAKOUT_ONLY_BASELINE",
    "RANDOM_SAME_UNIVERSE_BASELINE", "QUIET_VOLUME_BASELINE",
]


def _gen_baseline(bl_type: str, session_date: str) -> dict:
    """Generate one synthetic baseline snapshot."""
    ticker = random.choice(TICKERS)
    price = round(random.uniform(5.0, 200.0), 2)
    
    # Outcome bias based on baseline type
    if bl_type == "HIGH_RVOL_BASELINE":
        # Higher raw volatility = more big moves but also more drawdown
        m1h = round(random.uniform(2.0, 12.0), 2)
        dd = round(random.uniform(2.0, 10.0), 2)
        eff = round(m1h / max(dd, 1.0), 2)
    elif bl_type == "TOP_GAINERS_BASELINE":
        # Already moved, often late
        m1h = round(random.uniform(-1.0, 6.0), 2)
        dd = round(random.uniform(3.0, 12.0), 2)
        eff = round(m1h / max(dd, 1.0), 2)
    elif bl_type == "BREAKOUT_ONLY_BASELINE":
        # Breakout chasing
        m1h = round(random.uniform(1.0, 8.0), 2)
        dd = round(random.uniform(2.0, 9.0), 2)
        eff = round(m1h / max(dd, 1.0), 2)
    elif bl_type == "RANDOM_SAME_UNIVERSE_BASELINE":
        # Random = poor efficiency, high variance
        m1h = round(random.uniform(-2.0, 7.0), 2)
        dd = round(random.uniform(1.0, 8.0), 2)
        eff = round(m1h / max(dd, 1.0), 2)
    else:  # QUIET_VOLUME_BASELINE
        # Quiet volume can work but less consistently
        m1h = round(random.uniform(1.0, 7.0), 2)
        dd = round(random.uniform(1.5, 6.0), 2)
        eff = round(m1h / max(dd, 1.0), 2)

    m2h = round(m1h + random.uniform(-1.0, 3.0), 2)
    msd = round(m2h + random.uniform(-1.5, 2.5), 2)
    
    # Determine outcome label
    if m2h >= 10.0 and dd <= 5.0 and eff >= 2.0:
        outcome = "clean_baseline_winner"
    elif m1h >= 5.0:
        outcome = "baseline_moved_up"
    elif m1h < 3.0 and dd > 5.0:
        outcome = "baseline_failed"
    else:
        outcome = "baseline_no_follow_through"

    return {
        "baseline_id": f"BL_{session_date}_{ticker}_{random.randint(1000,9999)}",
        "baseline_type": bl_type,
        "ticker": ticker,
        "scan_time": f"{session_date}T{random.randint(10,15):02d}:{random.randint(0,59):02d}:00Z",
        "session_date": session_date,
        "scan_source": random.choice(["finviz_gainers", "volume_spike", "random"]),
        "price_at_scan": price,
        "open_price": round(price * 0.98, 2),
        "previous_close": round(price * 0.97, 2),
        "day_high_at_scan": round(price * 1.03, 2),
        "day_low_at_scan": round(price * 0.96, 2),
        "vwap_at_scan": round(price * 0.99, 2),
        "vwap_distance": round(random.uniform(-3.0, 15.0), 2),
        "price_change_pct": round(random.uniform(-2.0, 8.0), 2),
        "price_change_from_open_pct": round(random.uniform(-1.0, 5.0), 2),
        "current_volume": round(random.uniform(500000, 15000000), 0),
        "average_volume": round(random.uniform(1000000, 8000000), 0),
        "relative_volume": round(random.uniform(1.0, 6.0), 2),
        "time_of_day_rvol": round(random.uniform(1.2, 5.0), 2),
        "intraday_volume_curve_deviation": round(random.uniform(-15.0, 35.0), 1),
        "current_5m_volume_zscore": round(random.uniform(-0.5, 4.0), 2),
        "volume_acceleration_score": round(random.uniform(30.0, 85.0), 1),
        "latest_5candle_summary": random.choice(["accumulation", "breakout", "rejection", "distribution", "neutral"]),
        "buying_pressure": round(random.uniform(20.0, 75.0), 1),
        "selling_pressure": round(random.uniform(15.0, 60.0), 1),
        "upper_wick_pct": round(random.uniform(8.0, 40.0), 1),
        "absorption_quality_score": round(random.uniform(25.0, 80.0), 1),
        "news_status": random.choice(["no_news_found", "old_catalyst_present", "public_catalyst_visible"]),
        "catalyst_age_bucket": random.choice(["within_2h", "within_24h", "within_7d", "none"]),
        "offering_risk_score": round(random.uniform(5.0, 70.0), 1),
        "market_cap": round(random.uniform(100_000_000, 3_000_000_000), 0),
        "float_shares": round(random.uniform(10_000_000, 150_000_000), 0),
        "max_price_30m": round(price * (1 + random.uniform(0.5, 8.0) / 100), 4),
        "max_price_1h": round(price * (1 + m1h / 100), 4),
        "max_price_2h": round(price * (1 + m2h / 100), 4),
        "max_price_same_day": round(price * (1 + msd / 100), 4),
        "min_price_after_scan": round(price * (1 - dd / 100), 4),
        "drawdown_before_max_move_pct": dd,
        "efficiency_ratio": eff,
        "first_vwap_loss_time": None,
        "vwap_hold_after_scan": random.choice([True, False]),
        "final_baseline_outcome_label": outcome,
        "outcome_notes": [],
        "max_move_30m_pct": round(random.uniform(0.5, 8.0), 2),
        "max_move_1h_pct": m1h,
        "max_move_2h_pct": m2h,
        "max_move_same_day_pct": msd,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main():
    print("Generating synthetic baseline data...")
    baselines = {}
    sessions = [
        "2024-01-15", "2024-01-16", "2024-01-17",
        "2024-01-18", "2024-01-19", "2024-01-22",
        "2024-01-23", "2024-01-24", "2024-01-25",
        "2024-01-26",
    ]

    for session in sessions:
        for bl_type in BASELINE_TYPES:
            n = random.randint(3, 8)
            for _ in range(n):
                bl = _gen_baseline(bl_type, session)
                baselines[bl["baseline_id"]] = bl

    # Write master file
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baselines, f, indent=2, default=str)

    total = len(baselines)
    resolved = sum(1 for b in baselines.values() if b["final_baseline_outcome_label"] != "unresolved")
    by_type = {}
    for b in baselines.values():
        by_type[b["baseline_type"]] = by_type.get(b["baseline_type"], 0) + 1

    print(f"\nDone. Total baselines: {total}")
    print(f"Resolved: {resolved}")
    print(f"Sessions: {len(sessions)}")
    print("By type:")
    for bl_type, count in sorted(by_type.items()):
        print(f"  {bl_type}: {count}")
    print(f"File written to: {BASELINE_FILE}")


if __name__ == "__main__":
    main()
