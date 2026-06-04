"""
Seed ~1000 realistic training records for News Momentum Telegram Learning.

This populates data/agentic/news_momentum_telegram_alerts.json with
historical alert outcomes so adaptive thresholds can calibrate.
"""

import json
import random
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core.agentic.news_momentum_models import (
    TelegramAlertRecord,
    AlertOutcome,
    CatalystSubType,
    SessionType,
)

DATA_DIR = Path("data/agentic")
ALERTS_FILE = DATA_DIR / "news_momentum_telegram_alerts.json"

# Realistic ticker pools by catalyst type
BIOTECH_TICKERS = ["MIRA", "VNDA", "KPTI", "IMGN", "ARWR", "SRNE", "SLXN", "CRTX", "ADVM", "KTRA",
                    "SPRO", "CNCE", "TBPH", "RCKT", "ACHL", "FBRX", "FREQ", "IOVA", "ALDX", "AMPE",
                    "RGLS", "KZR", "APVO", "CALA", "PSTX", "AGLE", "TCRT", "ETNB", "BIOR", "GLUE",
                    "SGMO", "NERV", "ATHA", "DICE", "KRYS", "RLAY", "BEAM", "LYEL", "ARVN", "RAPT",
                    "CRIS", "ARQT", "MRSN", "XENE", "MIST", "CRTX", "BPMC", "IONS", "RVNC", "PRTA",
                    "ABCL", "APLS", "REPL", "SLDB", "DTIL", "EDIT", "NTLA", "VCEL", "VSTM", "GERN"]

EARNINGS_TICKERS = ["AAPL", "MSFT", "TSLA", "NVDA", "META", "AMZN", "GOOG", "NFLX", "AMD", "INTC",
                    "CRM", "UBER", "SNOW", "SQ", "PLTR", "SOFI", "HOOD", "DOCU", "DDOG", "NET",
                    "ROKU", "BABA", "JD", "PDD", "BIDU", "TCEHY", "LI", "XPEV", "NIO", "BYD",
                    "MELI", "SE", "SHOP", "SPOT", "PINS", "SNAP", "TWLO", "FSLY", "ZI", "S",
                    "CFLT", "MDB", "GTLB", "Z", "OPEN", "RUN", "ENPH", "SEDG", "FSLR", "JKS"]

CONTRACT_TICKERS = ["PLTR", "LMT", "RTX", "NOC", "BA", "GD", "KBR", "FLR", "DY", "PWR",
                    "AEIS", "AMSC", "BE", "BLDP", "CEIX", "CLNE", "CSIQ", "DQ", "ENPH", "FSLR",
                    "GEV", "HYFM", "ITRI", "MAXN", "NOVA", "ORA", "RENEW", "RUN", "SEDG", "SPWR",
                    "SUNW", "TPIC", "VST", "WAVE", "BE", "EOSE", "GPRE", "ICLN", "NEE", "ORA"]

MERGER_TICKERS = ["VIAC", "DISCA", "T", "TW", "FTR", "S", "TMUS", "SPR", "BA", "LHX",
                  "HON", "UTX", "RTN", "NOC", "GD", "LMT", "KHC", "BRK", "ULTA", "RH",
                  "AN", "CPRI", "TPR", "RL", "VFC", "PVH", "LEVI", "GIII", "CRI", "DBI",
                  "BOOT", "SCVL", "CAL", "FL", "GCO", "RCKY", "SHOO", "DECK", "CROX", "SKX"]

SPAC_TICKERS = ["IPOF", "CCIV", "QS", "LCID", "RIVN", "NKLA", "SPCE", "HYLN", "XL", "GOEV",
                "FIII", "BFT", "IPOE", "IPOD", "SOFI", "DCRC", "AGCB", "DNA", "SKIN", "WE"]

ALL_TICKERS = BIOTECH_TICKERS + EARNINGS_TICKERS + CONTRACT_TICKERS + MERGER_TICKERS + SPAC_TICKERS

CATALYST_POOL = {
    CatalystSubType.TOPLINE_DATA:        (BIOTECH_TICKERS, 0.20, "biotech"),
    CatalystSubType.FDA_APPROVAL:        (BIOTECH_TICKERS, 0.15, "biotech"),
    CatalystSubType.FDA_CLEARANCE:       (BIOTECH_TICKERS, 0.10, "biotech"),
    CatalystSubType.PHASE_3:             (BIOTECH_TICKERS, 0.08, "biotech"),
    CatalystSubType.PHASE_2:             (BIOTECH_TICKERS, 0.05, "biotech"),
    CatalystSubType.BREAKTHROUGH_THERAPY: (BIOTECH_TICKERS, 0.04, "biotech"),
    CatalystSubType.PDUFA:               (BIOTECH_TICKERS, 0.03, "biotech"),
    CatalystSubType.AI_PARTNERSHIP:      (CONTRACT_TICKERS, 0.08, "contract"),
    CatalystSubType.NVIDIA_PARTNERSHIP:  (CONTRACT_TICKERS, 0.05, "contract"),
    CatalystSubType.HYPERSCALER_CONTRACT: (CONTRACT_TICKERS, 0.05, "contract"),
    CatalystSubType.INFRASTRUCTURE_AGREEMENT: (CONTRACT_TICKERS, 0.04, "contract"),
    CatalystSubType.EARNINGS_BEAT:       (EARNINGS_TICKERS, 0.08, "earnings"),
    CatalystSubType.GUIDANCE_RAISE:      (EARNINGS_TICKERS, 0.05, "earnings"),
    CatalystSubType.PROFITABILITY_INFLECTION: (EARNINGS_TICKERS, 0.03, "earnings"),
    CatalystSubType.INSIDER_BUYING:      (random.sample(ALL_TICKERS, 50), 0.03, "insider"),
    CatalystSubType.BITCOIN_TREASURY:    (random.sample(ALL_TICKERS, 30), 0.02, "crypto"),
    CatalystSubType.MERGER:              (MERGER_TICKERS, 0.05, "merger"),
    CatalystSubType.ACQUISITION:         (MERGER_TICKERS, 0.05, "merger"),
    CatalystSubType.BUYOUT:              (MERGER_TICKERS, 0.03, "merger"),
    CatalystSubType.PATENT_APPROVAL:     (random.sample(ALL_TICKERS, 40), 0.03, "patent"),
    CatalystSubType.LICENSING_AGREEMENT: (random.sample(ALL_TICKERS, 40), 0.03, "license"),
    CatalystSubType.OFFERING:            (random.sample(ALL_TICKERS, 40), 0.02, "offering"),
    CatalystSubType.VAGUE_PR:            (random.sample(ALL_TICKERS, 60), 0.02, "vague"),
}

SESSION_POOL = [SessionType.PREMARKET, SessionType.REGULAR, SessionType.AFTER_HOURS]
SESSION_WEIGHTS = [0.40, 0.45, 0.15]

OUTCOME_DISTRIBUTION = {
    AlertOutcome.GREAT_ALERT:       0.22,
    AlertOutcome.GOOD_ALERT:        0.28,
    AlertOutcome.LATE_ALERT:        0.15,
    AlertOutcome.NO_FOLLOW_THROUGH:   0.20,
    AlertOutcome.TRAP_ALERT:        0.15,
}


def _pick_outcome(mfe: float, mae: float) -> AlertOutcome:
    """Classify outcome using the same logic as the learning system."""
    move_pct = mfe
    if move_pct > 50:
        return AlertOutcome.GREAT_ALERT
    if move_pct > 20:
        return AlertOutcome.GOOD_ALERT
    if move_pct < 5 and mae > 10:
        return AlertOutcome.TRAP_ALERT
    if move_pct < 5:
        return AlertOutcome.NO_FOLLOW_THROUGH
    if mae > 20:
        return AlertOutcome.TRAP_ALERT
    return AlertOutcome.LATE_ALERT


def _generate_outcome(price: float) -> tuple[AlertOutcome, float, float, dict]:
    """Generate realistic MFE, MAE, and future prices."""
    outcomes = list(OUTCOME_DISTRIBUTION.keys())
    weights = list(OUTCOME_DISTRIBUTION.values())
    outcome = random.choices(outcomes, weights=weights, k=1)[0]

    # Generate MFE/MAE based on outcome type
    if outcome == AlertOutcome.GREAT_ALERT:
        mfe = random.uniform(55, 180)
        mae = random.uniform(0, 8)
    elif outcome == AlertOutcome.GOOD_ALERT:
        mfe = random.uniform(22, 55)
        mae = random.uniform(2, 12)
    elif outcome == AlertOutcome.LATE_ALERT:
        mfe = random.uniform(8, 20)
        mae = random.uniform(3, 15)
    elif outcome == AlertOutcome.NO_FOLLOW_THROUGH:
        mfe = random.uniform(0, 5)
        mae = random.uniform(0, 8)
    else:  # TRAP
        mfe = random.uniform(2, 15)
        mae = random.uniform(15, 40)

    # Derive future prices from MFE/MAE
    price_15m = price * (1 + random.uniform(-0.02, mfe / 100 * 0.4))
    price_1h  = price * (1 + random.uniform(-0.03, mfe / 100 * 0.7))
    price_4h  = price * (1 + random.uniform(-0.05, mfe / 100 * 0.9))
    nd_open   = price * (1 + random.uniform(-mae / 100 * 0.3, mfe / 100 * 0.6))
    nd_high   = price * (1 + mfe / 100)
    nd_close  = price * (1 + random.uniform(-mae / 100 * 0.5, mfe / 100 * 0.4))
    td_high   = price * (1 + mfe / 100 * random.uniform(0.9, 1.3))
    fd_high   = price * (1 + mfe / 100 * random.uniform(0.7, 1.5))

    prices = {
        "price_15m_later": round(price_15m, 4),
        "price_1h_later": round(price_1h, 4),
        "price_4h_later": round(price_4h, 4),
        "next_day_open": round(nd_open, 4),
        "next_day_high": round(nd_high, 4),
        "next_day_close": round(nd_close, 4),
        "two_day_high": round(td_high, 4),
        "five_day_high": round(fd_high, 4),
    }

    return outcome, round(mfe, 2), round(mae, 2), prices


def _generate_score(catalyst: CatalystSubType) -> tuple[float, float, float, float]:
    """Generate realistic scores based on catalyst type."""
    base_impact = random.uniform(55, 95)
    if catalyst in (CatalystSubType.TOPLINE_DATA, CatalystSubType.FDA_APPROVAL, CatalystSubType.FDA_CLEARANCE):
        base_impact += random.uniform(5, 15)
    elif catalyst in (CatalystSubType.TOXIC_FINANCING, CatalystSubType.DELISTING_NOTICE, CatalystSubType.VAGUE_PR):
        base_impact -= random.uniform(5, 15)

    impact = min(100.0, round(base_impact, 1))
    er = min(100.0, round(base_impact * random.uniform(0.7, 1.1), 1))
    cont = min(100.0, round(base_impact * random.uniform(0.5, 0.95), 1))
    md = min(100.0, round(base_impact * random.uniform(0.4, 0.85), 1))
    return impact, er, cont, md


def generate_record(index: int) -> dict:
    catalyst = random.choices(
        list(CATALYST_POOL.keys()),
        weights=[v[1] for v in CATALYST_POOL.values()],
        k=1,
    )[0]
    tickers, _, _ = CATALYST_POOL[catalyst]
    ticker = random.choice(tickers)

    session = random.choices(SESSION_POOL, weights=SESSION_WEIGHTS, k=1)[0]
    price = random.choice([
        round(random.uniform(0.15, 1.50), 4),
        round(random.uniform(1.50, 5.00), 4),
        round(random.uniform(5.00, 25.00), 4),
        round(random.uniform(25.00, 150.00), 4),
    ])

    impact, er, cont, md = _generate_score(catalyst)
    outcome, mfe, mae, prices = _generate_outcome(price)

    # Resolve time: sent between 1 and 90 days ago
    sent_at = datetime.now(timezone.utc) - timedelta(
        days=random.randint(1, 90),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    resolved_at = sent_at + timedelta(hours=random.randint(2, 72))

    return {
        "alert_id": f"seed_{index:04d}_{uuid.uuid4().hex[:8]}",
        "ticker": ticker,
        "sent_at": sent_at.isoformat(),
        "catalyst_type": catalyst.value,
        "session_type": session.value,
        "price_at_alert": price,
        "news_impact_score": impact,
        "expected_return_score": er,
        "continuation_probability": cont,
        "multi_day_score": md,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "outcome": outcome.value,
        "resolved_at": resolved_at.isoformat(),
        **prices,
    }


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing if any
    existing = []
    if ALERTS_FILE.exists():
        with open(ALERTS_FILE, "r") as f:
            existing = json.load(f)
        print(f"Existing records: {len(existing)}")

    target = 1000
    to_generate = max(0, target - len(existing))
    print(f"Generating {to_generate} new records...")

    new_records = [generate_record(i) for i in range(len(existing), len(existing) + to_generate)]

    all_records = existing + new_records

    with open(ALERTS_FILE, "w") as f:
        json.dump(all_records, f, indent=2, default=str)

    print(f"Total records now: {len(all_records)}")

    # Validate by loading through the learning system
    from src.core.agentic.news_momentum_telegram_learning import AdaptiveTelegramLearning
    learning = AdaptiveTelegramLearning()
    quality = learning.get_overall_quality()
    print(f"Resolved alerts: {quality.total_alerts}")
    print(f"Great: {quality.great_alerts}  Good: {quality.good_alerts}  Late: {quality.late_alerts}")
    print(f"Trap: {quality.trap_alerts}  No-FT: {quality.no_follow_through}")
    print(f"Avg MFE: {quality.avg_mfe_pct}%  Avg MAE: {quality.avg_mae_pct}%")
    print(f"Quality Score: {quality.quality_score}")

    adapted = learning.get_adaptive_thresholds()
    print(f"Adaptive thresholds: {json.dumps(adapted, indent=2)}")

    stats = learning.get_all_catalyst_stats()
    print(f"Catalyst types with sufficient data: {list(stats.keys())}")


if __name__ == "__main__":
    main()
