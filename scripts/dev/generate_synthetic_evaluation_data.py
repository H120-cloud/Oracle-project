#!/usr/bin/env python3
"""
Generate synthetic Pre-News evaluation data for testing the success-rate analysis.

Creates ~150 realistic detection snapshots across multiple sessions with varied
outcomes, anomaly types, alert qualities, and forward metrics.

Usage:
    python scripts/generate_synthetic_evaluation_data.py

Output:
    Overwrites data/agentic/pre_news_evaluation_snapshots.json
    Creates daily CSV reports in data/agentic/evaluation_reports/
"""

import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

random.seed(42)

BASE_DIR = Path("data/agentic")
SNAPSHOTS_FILE = BASE_DIR / "pre_news_evaluation_snapshots.json"
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

ANOMALY_TYPES = [
    "quiet_volume_build", "hidden_accumulation", "early_breakout_positioning",
    "breakout_building", "unusual_volume_no_news", "volume_before_news",
    "suspicious_pump_risk", "already_extended", "rejection", "failed_spike",
    "distribution",
]

ALERT_QUALITIES = ["early", "caution", "late", "trap_risk", "suppressed"]
CANDIDATE_TYPES = ["quiet_accumulation", "early_breakout", "late_chase", "trap_risk", "normal_momentum"]
WYCKOFF_STAGES = ["accumulation_phase_c", "accumulation_phase_d", "markup_phase_d", "markup_phase_e",
                  "buying_climax", "distribution", "early_markdown"]
CANDLE_SUMMARIES = ["accumulation", "breakout", "rejection", "distribution", "failed_spike", "neutral"]
NEWS_STATUSES = ["no_news_found", "old_catalyst_present", "public_catalyst_visible",
                 "news_appeared_after_detection", "unknown"]
CATALYST_BUCKETS = ["within_2h", "within_24h", "within_7d", "within_30d", "older_than_30d", "none"]
OUTCOME_LABELS = [
    "clean_pre_news_winner", "news_lag_confirmed_winner", "failed_spike",
    "distribution_trap", "late_chase_signal", "no_follow_through",
    "unresolved",
]


def _gen_detection_time(session_date: str) -> str:
    """Generate a random detection time between 09:30 and 16:00 ET."""
    base = datetime.strptime(session_date, "%Y-%m-%d")
    minutes_after_open = random.randint(0, 390)  # 0 to 6.5 hours
    dt = base + timedelta(hours=9, minutes=30) + timedelta(minutes=minutes_after_open)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _gen_snapshot(session_date: str, ticker: str, outcome_bias: str = "mixed") -> dict:
    """Generate one synthetic snapshot with realistic field distributions."""
    detection_time = _gen_detection_time(session_date)
    price = round(random.uniform(0.5, 250.0), 2)
    if price < 1.0:
        price = round(random.uniform(1.0, 50.0), 2)  # avoid too many pennies

    # Detection-time fields
    rvol = round(random.uniform(1.0, 8.0), 2)
    vwap_dist = round(random.uniform(-5.0, 25.0), 2)
    absorption = round(random.uniform(20.0, 95.0), 1)
    suspicion = round(random.uniform(40.0, 98.0), 1)
    buying_p = round(random.uniform(10.0, 80.0), 1)
    selling_p = round(random.uniform(5.0, 70.0), 1)
    upper_wick = round(random.uniform(5.0, 55.0), 1)
    lower_wick = round(random.uniform(2.0, 20.0), 1)
    accel = round(random.uniform(30.0, 90.0), 1)
    abnormal_vol = round(random.uniform(40.0, 95.0), 1)

    # Determine anomaly type and alert quality based on outcome bias
    if outcome_bias == "winner":
        anomaly_type = random.choice(["quiet_volume_build", "hidden_accumulation",
                                      "early_breakout_positioning", "volume_before_news"])
        alert_quality = random.choices(["early", "caution", "late"], weights=[60, 30, 10])[0]
        candidate_type = random.choices(["quiet_accumulation", "early_breakout", "normal_momentum"],
                                        weights=[40, 35, 25])[0]
        wyckoff = random.choice(["accumulation_phase_c", "accumulation_phase_d", "markup_phase_d"])
        candle = random.choices(["accumulation", "breakout", "neutral"], weights=[40, 40, 20])[0]
        vwap_hold = random.choices([True, False], weights=[75, 25])[0]
        outcome = random.choices(
            ["clean_pre_news_winner", "news_lag_confirmed_winner", "no_follow_through"],
            weights=[55, 25, 20]
        )[0]
    elif outcome_bias == "loser":
        anomaly_type = random.choice(["failed_spike", "distribution", "already_extended",
                                      "suspicious_pump_risk", "rejection"])
        alert_quality = random.choices(["late", "trap_risk", "suppressed", "early"],
                                       weights=[35, 30, 20, 15])[0]
        candidate_type = random.choices(["late_chase", "trap_risk", "normal_momentum"],
                                        weights=[40, 35, 25])[0]
        wyckoff = random.choice(["buying_climax", "distribution", "early_markdown"])
        candle = random.choices(["rejection", "failed_spike", "distribution"], weights=[40, 35, 25])[0]
        vwap_hold = random.choices([True, False], weights=[20, 80])[0]
        outcome = random.choices(
            ["failed_spike", "distribution_trap", "late_chase_signal", "no_follow_through"],
            weights=[30, 25, 25, 20]
        )[0]
    else:
        anomaly_type = random.choice(ANOMALY_TYPES)
        alert_quality = random.choice(ALERT_QUALITIES)
        candidate_type = random.choice(CANDIDATE_TYPES)
        wyckoff = random.choice(WYCKOFF_STAGES)
        candle = random.choice(CANDLE_SUMMARIES)
        vwap_hold = random.choice([True, False])
        outcome = random.choice(OUTCOME_LABELS)

    # Forward metrics based on outcome
    if outcome in ("clean_pre_news_winner", "news_lag_confirmed_winner"):
        max_30m = round(random.uniform(3.0, 15.0), 2)
        max_1h = round(max_30m + random.uniform(2.0, 12.0), 2)
        max_2h = round(max_1h + random.uniform(1.0, 10.0), 2)
        max_sd = round(max_2h + random.uniform(0.0, 8.0), 2)
        dd = round(random.uniform(0.5, 4.0), 2)
        eff = round(random.uniform(1.5, 5.0), 2)
    elif outcome in ("failed_spike", "distribution_trap", "late_chase_signal"):
        max_30m = round(random.uniform(0.5, 4.0), 2)
        max_1h = round(max_30m + random.uniform(-1.0, 2.0), 2)
        max_2h = round(max_1h + random.uniform(-1.5, 1.5), 2)
        max_sd = round(max_2h + random.uniform(-2.0, 2.0), 2)
        dd = round(random.uniform(3.0, 12.0), 2)
        eff = round(random.uniform(0.2, 1.2), 2)
    else:
        max_30m = round(random.uniform(1.0, 8.0), 2)
        max_1h = round(max_30m + random.uniform(-2.0, 5.0), 2)
        max_2h = round(max_1h + random.uniform(-2.0, 4.0), 2)
        max_sd = round(max_2h + random.uniform(-2.0, 3.0), 2)
        dd = round(random.uniform(1.0, 8.0), 2)
        eff = round(random.uniform(0.5, 2.5), 2)

    # News fields
    news_status = random.choice(NEWS_STATUSES)
    catalyst_age = random.choice(CATALYST_BUCKETS)
    catalyst_relevance = round(random.uniform(0.0, 95.0), 1)

    # Suppression
    suppressed = alert_quality == "suppressed" or random.random() < 0.15
    suppression_reasons = []
    if suppressed:
        reasons = ["price_extended", "low_absorption", "high_offering_risk",
                   "old_catalyst", "vwap_distance_excessive", "selling_pressure_dominant"]
        suppression_reasons = random.sample(reasons, k=random.randint(1, 3))

    offering_risk = round(random.uniform(5.0, 85.0), 1)
    mcap = round(random.uniform(50_000_000, 5_000_000_000), 0)

    sid = f"{ticker}_{session_date}_{random.randint(1000, 9999)}"

    return {
        "ticker": ticker,
        "detection_id": sid,
        "detection_time": detection_time,
        "session_date": session_date,
        "detection_source": "scan",
        "discovery_bucket": random.choice(["finviz_gainers", "volume_spike", "quiet_build"]),
        "detection_price": price,
        "open_price": round(price * (1 - random.uniform(-0.03, 0.05)), 2),
        "previous_close": round(price * (1 - random.uniform(-0.05, 0.05)), 2),
        "day_high_at_detection": round(price * (1 + random.uniform(0.0, 0.08)), 2),
        "day_low_at_detection": round(price * (1 - random.uniform(0.0, 0.05)), 2),
        "vwap_at_detection": round(price * (1 - random.uniform(-0.02, 0.02)), 2),
        "vwap_distance": vwap_dist,
        "price_change_pct": round(random.uniform(-1.5, 8.0), 2),
        "price_change_from_open_pct": round(random.uniform(-2.0, 10.0), 2),
        "current_volume": round(random.uniform(500_000, 20_000_000), 0),
        "average_volume": round(random.uniform(1_000_000, 8_000_000), 0),
        "relative_volume": rvol,
        "time_of_day_rvol": rvol,
        "intraday_volume_curve_deviation": round(random.uniform(-20.0, 40.0), 1),
        "current_5m_volume_zscore": round(random.uniform(-1.0, 5.0), 2),
        "session_progress_adjusted_volume_score": round(random.uniform(30.0, 95.0), 1),
        "volume_acceleration_score": accel,
        "abnormal_volume_score": abnormal_vol,
        "float_rotation": round(random.uniform(0.01, 0.25), 3),
        "float_pressure": round(random.uniform(10.0, 90.0), 1),
        "pre_news_suspicion_score": suspicion,
        "anomaly_type": anomaly_type,
        "price_behaviour": candidate_type.replace("_", " "),
        "wyckoff_stage": wyckoff,
        "alert_quality": alert_quality,
        "candidate_type": candidate_type,
        "quiet_accumulation_candidate": candidate_type == "quiet_accumulation",
        "early_breakout_candidate": candidate_type == "early_breakout",
        "latest_5candle_summary": candle,
        "buying_pressure": buying_p,
        "selling_pressure": selling_p,
        "wick_dominance": random.choice(["upper", "lower", "neutral"]),
        "upper_wick_pct": upper_wick,
        "lower_wick_pct": lower_wick,
        "absorption_quality_score": absorption,
        "absorption_score": absorption,
        "supply_rejection_score": round(random.uniform(0.0, 50.0), 1),
        "vwap_hold_count": random.randint(0, 5),
        "vwap_loss_count": random.randint(0, 3),
        "news_status": news_status,
        "catalyst_age_bucket": catalyst_age,
        "catalyst_relevance_score": catalyst_relevance,
        "catalyst_source": random.choice(["finviz", "stocktitan", "benzinga", ""]),
        "matched_headline": None,
        "matched_headline_time": None,
        "catalyst_age_minutes": None,
        "offering_risk_score": offering_risk,
        "dilution_risk_tag": random.choice(["low", "medium", "high"]),
        "market_cap": mcap,
        "float_shares": round(random.uniform(5_000_000, 200_000_000), 0),
        "liquidity_score": round(random.uniform(30.0, 95.0), 1),
        "data_quality_score": round(random.uniform(70.0, 100.0), 1),
        "suppression_reasons": suppression_reasons,
        "was_alert_suppressed": suppressed,
        "alert_sent": not suppressed and alert_quality != "suppressed",
        "max_price_30m": round(price * (1 + max_30m / 100), 4) if max_30m > 0 else round(price * (1 + max_30m / 100), 4),
        "max_price_1h": round(price * (1 + max_1h / 100), 4),
        "max_price_2h": round(price * (1 + max_2h / 100), 4),
        "max_price_same_day": round(price * (1 + max_sd / 100), 4),
        "min_price_after_detection": round(price * (1 - random.uniform(0.0, 0.08)), 4),
        "drawdown_before_max_move": round(price * dd / 100, 4),
        "drawdown_before_max_move_pct": dd,
        "first_vwap_loss_time": None,
        "vwap_hold_after_detection": vwap_hold,
        "time_gap_detection_to_news": None,
        "pre_news_high": round(price * (1 + random.uniform(0.0, 0.05)), 4),
        "post_news_high": round(price * (1 + random.uniform(0.0, 0.12)), 4) if news_status in ("news_appeared_after_detection",) else None,
        "final_outcome_label": outcome,
        "outcome_notes": [],
        "max_move_30m_pct": max_30m,
        "max_move_1h_pct": max_1h,
        "max_move_2h_pct": max_2h,
        "max_move_same_day_pct": max_sd,
        "lowest_price_before_max": round(price * (1 - random.uniform(0.0, 0.05)), 4),
        "efficiency_ratio": eff,
        "vwap_closes_below_count": random.randint(0, 3),
        "vwap_reclaimed": random.choice([True, False]),
        "clean_or_choppy": random.choice(["clean", "choppy", ""]),
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def generate_session(session_date: str, n_detections: int) -> list[dict]:
    """Generate ~n_detections snapshots for a session with realistic outcome distribution."""
    snapshots = []
    # Mix: 40% winners, 35% losers, 25% mixed/unresolved
    winners = int(n_detections * 0.40)
    losers = int(n_detections * 0.35)
    mixed = n_detections - winners - losers

    for _ in range(winners):
        snapshots.append(_gen_snapshot(session_date, random.choice(TICKERS), "winner"))
    for _ in range(losers):
        snapshots.append(_gen_snapshot(session_date, random.choice(TICKERS), "loser"))
    for _ in range(mixed):
        snapshots.append(_gen_snapshot(session_date, random.choice(TICKERS), "mixed"))

    random.shuffle(snapshots)
    return snapshots


def main():
    print("Generating synthetic Pre-News evaluation data...")

    all_snapshots = {}
    sessions = [
        "2024-01-15", "2024-01-16", "2024-01-17",
        "2024-01-18", "2024-01-19", "2024-01-22",
        "2024-01-23", "2024-01-24", "2024-01-25",
        "2024-01-26",
    ]

    for session in sessions:
        n = random.randint(12, 25)
        for snap in generate_session(session, n):
            all_snapshots[snap["detection_id"]] = snap

    # Also generate daily CSV reports for a few sessions
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for session in sessions[:3]:
        session_snaps = [s for s in all_snapshots.values() if s["session_date"] == session]
        # Write JSON report envelope
        report_json = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "session_date": session,
            "total_snapshots": len(session_snaps),
            "snapshots": session_snaps,
        }
        json_path = REPORTS_DIR / f"{session}_pre_news_eval.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=2, default=str)
        print(f"  Wrote {json_path} ({len(session_snaps)} snapshots)")

    # Write master snapshots file
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_snapshots, f, indent=2, default=str)

    total = len(all_snapshots)
    resolved = sum(1 for s in all_snapshots.values() if s["final_outcome_label"] != "unresolved")
    print(f"\nDone. Total snapshots: {total}")
    print(f"Resolved outcomes: {resolved}")
    print(f"Sessions: {len(sessions)}")
    print(f"Files written to: {BASE_DIR}")


if __name__ == "__main__":
    main()
