"""
Production missed-alert audit.

Mines `data/agentic/news_momentum_shadow_alerts.json` (every gate decision the
system has logged, ~75K records) for patterns that historically caused real
misses, and reports them so they can be reviewed BEFORE we get blindsided
again by a stock like PRFX or OLOX.

Audit categories:
  1. NEAR_MISS_SCORE_GATE — high-conviction catalyst blocked by score_gate
     within 5 points of clearing.
  2. BLOCKED_AT_NO_PRICE — strong-headline candidates rejected for missing
     a live quote (the fix is now in place; this counts how many would
     have been recovered).
  3. STALE_AFTER_RECLASSIFICATION — same ticker re-appears with a much
     better catalyst score later (PRFX pattern: detected wrong, classified
     right too late).
  4. SMALL_MOVE_KILLED_HIGH_CONVICTION — high-conviction catalyst killed
     by the small_move gate (PRFX exact pattern).

Run: python scripts/audit_missed_alerts.py
     python scripts/audit_missed_alerts.py --top 30
     python scripts/audit_missed_alerts.py --since 2026-05-20
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SHADOW_PATH = Path("data/agentic/news_momentum_shadow_alerts.json")

# Catalyst types that historically print > 40% wins — same set the orchestrator
# uses for high-conviction step-down. Misses here are the most costly.
HIGH_CONVICTION = {
    "fda_approval", "fda_clearance", "phase_1", "phase_2", "phase_3", "pdufa",
    "breakthrough_therapy", "fast_track", "orphan_drug", "topline_data",
    "snda_submission", "nda_approval", "label_expansion", "drug_launch",
    "commercialization", "government_contract", "strategic_review",
    "ai_partnership", "nvidia_partnership", "openai_partnership",
    "hyperscaler_contract", "new_product_launch", "product_upgrade",
    "platform_expansion", "bitcoin_treasury", "share_buyback",
    "major_partnership", "supply_agreement", "oem_partnership",
    "spin_off", "joint_venture", "analyst_upgrade", "tariff_exemption",
    "trade_deal", "subsidy_award", "warrant_overhang_removal",
    "listing_compliance", "guidance_raise", "profitability_inflection",
    "earnings_beat", "dividend_increase", "stock_split_forward",
    "credit_upgrade", "financing_positive", "ev_battery", "renewable_energy",
    "merger", "acquisition", "buyout",
}


def _load_records(path: Path = SHADOW_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Shadow log not found: {path}")
    data = json.loads(path.read_text())
    rows = data if isinstance(data, list) else (
        data.get("alerts") or data.get("records") or list(data.values())
    )
    return [r for r in rows if isinstance(r, dict)]


def _parse_dt(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def find_near_miss_score_gate(records: list[dict], margin: float = 5.0) -> list[dict]:
    """High-conviction catalysts blocked by score_gate within `margin` points
    of clearing. These are the most costly misses — a small floor relaxation
    would have surfaced them."""
    out = []
    for r in records:
        if not r.get("was_blocked"):
            continue
        reason = r.get("block_reason") or ""
        if not reason.startswith("score_gate"):
            continue
        cat = (r.get("catalyst_type") or "").lower()
        if cat not in HIGH_CONVICTION:
            continue
        # Parse "score_gate(imp=57.3/45,ret=49.9/50)"
        m = re.match(r"score_gate\(imp=([\d.]+)/([\d.]+),ret=([\d.]+)/([\d.]+)\)", reason)
        if not m:
            continue
        imp, imp_floor, ret, ret_floor = (float(g) for g in m.groups())
        imp_gap = imp_floor - imp  # >0 = failed by this much
        ret_gap = ret_floor - ret
        # OLOX pattern: the WORST failed dimension still missed by <= margin.
        # max() picks the most-failed; restricting it to >0 keeps only true fails.
        worst_gap = max(imp_gap, ret_gap)
        if worst_gap <= 0 or worst_gap > margin:
            continue
        out.append({
            "ticker": r.get("ticker"), "sent_at": r.get("sent_at"),
            "catalyst": cat, "imp": imp, "imp_floor": imp_floor,
            "ret": ret, "ret_floor": ret_floor, "worst_gap": worst_gap,
            "price": r.get("price_at_alert"), "move": r.get("move_pct_at_alert"),
        })
    # Dedupe (ticker, catalyst, worst_gap rounded) — repeats are just rescans
    seen: set[tuple] = set()
    unique = []
    for x in sorted(out, key=lambda x: x["worst_gap"]):
        key = (x["ticker"], x["catalyst"], round(x["worst_gap"], 1))
        if key in seen:
            continue
        seen.add(key)
        unique.append(x)
    return unique


def find_small_move_killed_high_conviction(records: list[dict]) -> list[dict]:
    """The exact PRFX failure mode: high-conviction catalyst, blocked by the
    small_move gate. These now alert post-fix; counting them quantifies the
    recovered alert volume."""
    out = []
    for r in records:
        if not (r.get("was_blocked") and (r.get("block_reason") or "").startswith("small_move")):
            continue
        cat = (r.get("catalyst_type") or "").lower()
        if cat not in HIGH_CONVICTION:
            continue
        out.append({
            "ticker": r.get("ticker"), "sent_at": r.get("sent_at"),
            "catalyst": cat, "impact": r.get("news_impact_score"),
            "move": r.get("move_pct_at_alert"),
        })
    # Dedupe per ticker+catalyst
    seen: set[tuple] = set()
    unique = []
    for x in out:
        key = (x["ticker"], x["catalyst"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(x)
    return unique


def find_blocked_at_no_price_strong(records: list[dict]) -> list[dict]:
    """Strong-impact candidates blocked just for missing a live quote — the
    no-price bypass would now save these."""
    out = []
    for r in records:
        if not (r.get("was_blocked") and (r.get("block_reason") or "") == "no_price"):
            continue
        impact = r.get("news_impact_score") or 0
        if impact < 50:  # Only count plausible hits
            continue
        out.append({
            "ticker": r.get("ticker"), "sent_at": r.get("sent_at"),
            "catalyst": r.get("catalyst_type"), "impact": impact,
            "exp_ret": r.get("expected_return_score"),
        })
    # Dedupe per ticker+catalyst
    seen: set[tuple] = set()
    unique = []
    for x in sorted(out, key=lambda x: -(x["impact"] or 0)):
        key = (x["ticker"], x["catalyst"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(x)
    return unique


def find_stale_after_reclassification(records: list[dict]) -> list[dict]:
    """PRFX exact pattern: a ticker's classification IMPROVED over its scan
    history (impact_score went up by ≥15, or catalyst went OTHER→high-conviction)
    but the better version was blocked as stale or never fired. These are the
    re-classification gap I called out earlier."""
    by_ticker = defaultdict(list)
    for r in records:
        if not r.get("ticker"):
            continue
        by_ticker[r["ticker"]].append(r)
    out = []
    for ticker, recs in by_ticker.items():
        recs.sort(key=lambda r: r.get("sent_at") or "")
        if len(recs) < 2:
            continue
        earliest = recs[0]
        best_later = max(
            recs[1:], key=lambda r: float(r.get("news_impact_score") or 0)
        )
        first_imp = float(earliest.get("news_impact_score") or 0)
        best_imp = float(best_later.get("news_impact_score") or 0)
        first_cat = (earliest.get("catalyst_type") or "").lower()
        best_cat = (best_later.get("catalyst_type") or "").lower()
        promoted = first_cat not in HIGH_CONVICTION and best_cat in HIGH_CONVICTION
        impact_jumped = (best_imp - first_imp) >= 15
        if (promoted or impact_jumped) and best_later.get("was_blocked"):
            reason = best_later.get("block_reason") or ""
            if "stale" in reason or "cooldown" in reason or "small_move" in reason:
                out.append({
                    "ticker": ticker,
                    "first_seen": earliest.get("sent_at"),
                    "first_imp": first_imp, "first_cat": first_cat,
                    "best_seen": best_later.get("sent_at"),
                    "best_imp": best_imp, "best_cat": best_cat,
                    "block_reason": reason,
                    "n_records": len(recs),
                })
    out.sort(key=lambda x: -(x["best_imp"] - x["first_imp"]))
    return out


def _filter_since(records: list[dict], since: datetime) -> list[dict]:
    out = []
    for r in records:
        dt = _parse_dt(r.get("sent_at"))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= since:
            out.append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=15, help="rows to print per category")
    p.add_argument("--since", type=str, help="ISO date, e.g. 2026-05-20")
    p.add_argument("--margin", type=float, default=5.0,
                   help="score_gate near-miss margin in points (default 5)")
    args = p.parse_args()

    records = _load_records()
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        records = _filter_since(records, since)
    print(f"\nAudit input: {len(records)} shadow records"
          f"{' since ' + args.since if args.since else ''}\n")

    print("=" * 78)
    print("1. NEAR-MISS SCORE GATE (high-conviction, within "
          f"{args.margin} pts of clearing)")
    print("=" * 78)
    near = find_near_miss_score_gate(records, margin=args.margin)
    print(f"Total: {len(near)}")
    for x in near[:args.top]:
        print(f"  {x['ticker']:6} {x['sent_at'][:19]:19}  {x['catalyst']:20}  "
              f"imp={x['imp']:5.1f}/{x['imp_floor']:.0f} "
              f"ret={x['ret']:5.1f}/{x['ret_floor']:.0f} "
              f"(missed by {x['worst_gap']:.1f})")

    print("\n" + "=" * 78)
    print("2. SMALL_MOVE KILLED HIGH-CONVICTION (PRFX exact pattern)")
    print("=" * 78)
    small = find_small_move_killed_high_conviction(records)
    print(f"Total: {len(small)}   (these now alert post-fix)")
    for x in small[:args.top]:
        print(f"  {x['ticker']:6} {x['sent_at'][:19]:19}  {x['catalyst']:20}  "
              f"impact={x['impact']:5.1f}  move={x['move']}")

    print("\n" + "=" * 78)
    print("3. BLOCKED AT NO_PRICE WITH STRONG IMPACT (>=50)")
    print("=" * 78)
    np_ = find_blocked_at_no_price_strong(records)
    print(f"Total: {len(np_)}   (these now alert post-fix when headline is fresh+bullish)")
    for x in np_[:args.top]:
        print(f"  {x['ticker']:6} {x['sent_at'][:19]:19}  {x['catalyst']:20}  "
              f"impact={x['impact']:.1f} exp_ret={x['exp_ret']}")

    print("\n" + "=" * 78)
    print("4. STALE AFTER RE-CLASSIFICATION (PRFX root pattern)")
    print("=" * 78)
    stale = find_stale_after_reclassification(records)
    print(f"Total: {len(stale)}   (UNFIXED — would need a re-classification re-alert lane)")
    for x in stale[:args.top]:
        print(f"  {x['ticker']:6}  imp {x['first_imp']:5.1f}->{x['best_imp']:5.1f}"
              f"  ({x['first_cat']!r:25} -> {x['best_cat']!r:25})  block={x['block_reason']}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
