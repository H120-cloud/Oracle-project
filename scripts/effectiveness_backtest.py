"""
Effectiveness backtest — how good is the tool, really?

Uses the system's own ground truth: resolved Telegram-alert records with known
realized returns (mfe_pct = max favorable excursion, the "how high did it run"
metric). Answers the questions that matter:

  1. Hit rate — what fraction of alerts actually ran?
  2. Big-mover capture — how many alerts hit +50/+100/+300%?
  3. Score DISCRIMINATION — do higher scores actually predict bigger runs?
     (If not, the scores are noise and the gate is filtering blind.)
  4. Which catalyst types deliver.
  5. Strategy sim — expected return trading ALL alerts vs only top-scored.

Run: python scripts/effectiveness_backtest.py
"""

from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ALERTS = Path("data/agentic/news_momentum_telegram_alerts.json")
WIN_OUTCOMES = {"GOOD_ALERT", "GREAT_ALERT"}
RESOLVED = {"GOOD_ALERT", "GREAT_ALERT", "TRAP_ALERT", "LATE_ALERT", "NO_FOLLOW_THROUGH"}


def _load():
    d = json.loads(ALERTS.read_text())
    rows = d if isinstance(d, list) else d.get("alerts", [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("outcome") not in RESOLVED:
            continue
        mfe = r.get("mfe_pct")
        if mfe is None:
            continue
        out.append(r)
    return out


def _pct(n, d):
    return f"{100*n/d:.1f}%" if d else "—"


def _med(xs):
    return st.median(xs) if xs else 0.0


def main():
    rows = _load()
    n = len(rows)
    print(f"\n{'='*72}\nEFFECTIVENESS BACKTEST — {n} resolved alerts\n{'='*72}")

    # ── 1. Overall hit rate + outcome mix ──────────────────────────────────
    outc = defaultdict(int)
    for r in rows:
        outc[r["outcome"]] += 1
    wins = sum(outc[o] for o in WIN_OUTCOMES)
    print("\n1. OUTCOME MIX")
    for o in ["GREAT_ALERT", "GOOD_ALERT", "LATE_ALERT", "TRAP_ALERT", "NO_FOLLOW_THROUGH"]:
        print(f"   {o:20} {outc[o]:6}  {_pct(outc[o], n)}")
    print(f"   {'-> WIN (GOOD+GREAT)':20} {wins:6}  {_pct(wins, n)}")

    # ── 2. Big-mover capture (by mfe) ──────────────────────────────────────
    mfes = [r["mfe_pct"] for r in rows]
    print("\n2. BIG-MOVER CAPTURE (max favorable excursion after alert)")
    for thr in [20, 50, 100, 200, 500]:
        c = sum(1 for m in mfes if m >= thr)
        print(f"   reached +{thr:>4}%:  {c:6}  {_pct(c, n)}")
    print(f"   median mfe: {_med(mfes):.1f}%   mean mfe: {sum(mfes)/n:.1f}%")

    # ── 3. Score discrimination ────────────────────────────────────────────
    # Does a higher score actually mean a bigger run? Bucket by score, show
    # win-rate + median mfe per bucket. If flat/inverted, the score is noise.
    def discrimination(field):
        print(f"\n3. DISCRIMINATION by {field}")
        buckets = [(0, 30), (30, 45), (45, 55), (55, 70), (70, 101)]
        print(f"   {'band':>10} {'n':>6} {'win%':>7} {'med_mfe':>9} {'>=100%':>7}")
        for lo, hi in buckets:
            sub = [r for r in rows if lo <= (r.get(field) or 0) < hi]
            if not sub:
                continue
            w = sum(1 for r in sub if r["outcome"] in WIN_OUTCOMES)
            big = sum(1 for r in sub if r["mfe_pct"] >= 100)
            print(f"   {f'{lo}-{hi}':>10} {len(sub):>6} {_pct(w,len(sub)):>7} "
                  f"{_med([r['mfe_pct'] for r in sub]):>8.1f}% {_pct(big,len(sub)):>7}")

    discrimination("news_impact_score")
    discrimination("expected_return_score")
    # ML win prob (may be sparse on old records)
    ml_rows = [r for r in rows if r.get("ml_predicted_win_prob") is not None]
    if len(ml_rows) > 100:
        print(f"\n3b. DISCRIMINATION by ml_predicted_win_prob ({len(ml_rows)} w/ prediction)")
        for lo, hi in [(0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.01)]:
            sub = [r for r in ml_rows if lo <= r["ml_predicted_win_prob"] < hi]
            if not sub: continue
            w = sum(1 for r in sub if r["outcome"] in WIN_OUTCOMES)
            big = sum(1 for r in sub if r["mfe_pct"] >= 100)
            print(f"   {lo:.1f}-{hi:.1f}  n={len(sub):>5}  win={_pct(w,len(sub)):>6}  "
                  f"med_mfe={_med([r['mfe_pct'] for r in sub]):>7.1f}%  >=100%={_pct(big,len(sub))}")
    else:
        print(f"\n3b. ml_predicted_win_prob: only {len(ml_rows)} records have it — too sparse")

    # ── 4. By catalyst type ─────────────────────────────────────────────────
    print("\n4. BY CATALYST TYPE (min 20 alerts)")
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[(r.get("catalyst_type") or "?")].append(r)
    print(f"   {'catalyst':22} {'n':>5} {'win%':>7} {'med_mfe':>9} {'>=100%':>7}")
    cat_stats = []
    for cat, sub in by_cat.items():
        if len(sub) < 20:
            continue
        w = sum(1 for r in sub if r["outcome"] in WIN_OUTCOMES)
        big = sum(1 for r in sub if r["mfe_pct"] >= 100)
        cat_stats.append((100*w/len(sub), cat, len(sub), w, big))
    for winrate, cat, ln, w, big in sorted(cat_stats, reverse=True):
        print(f"   {cat:22} {ln:>5} {_pct(w,ln):>7} "
              f"{_med([r['mfe_pct'] for r in by_cat[cat]]):>8.1f}% {_pct(big,ln):>7}")

    # ── 5. Strategy simulation ──────────────────────────────────────────────
    # Naive: buy at alert, sell at next_day_high (best case) and at +30% target
    # or next_day_close (realistic). Compare trading ALL vs top-quartile by impact.
    print("\n5. STRATEGY SIM (buy at alert price)")
    def sim(subset, label):
        rr = [r.get("return_next_day_high_pct") for r in subset if r.get("return_next_day_high_pct") is not None]
        rc = [r.get("return_next_day_close_pct") for r in subset if r.get("return_next_day_close_pct") is not None]
        if not rr:
            print(f"   {label}: no return data"); return
        # Realistic: capped exit at +30% target, else next-day close
        capped = []
        for r in subset:
            high = r.get("return_next_day_high_pct")
            close = r.get("return_next_day_close_pct")
            if high is None or close is None:
                continue
            capped.append(30.0 if high >= 30 else close)
        print(f"   {label}: n={len(rr)}  med_nextday_high={_med(rr):.1f}%  "
              f"med_nextday_close={_med(rc):.1f}%  +30%-target-hit={_pct(sum(1 for x in rr if x>=30),len(rr))}")
        if capped:
            print(f"      realistic (+30% target or next close): avg={sum(capped)/len(capped):+.1f}% med={_med(capped):+.1f}%")
    sim(rows, "ALL alerts")
    impacts = sorted((r.get("news_impact_score") or 0) for r in rows)
    q75 = impacts[int(len(impacts)*0.75)]
    sim([r for r in rows if (r.get("news_impact_score") or 0) >= q75], f"TOP quartile (impact>={q75:.0f})")
    print()


if __name__ == "__main__":
    main()
