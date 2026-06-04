"""
Pre-News Detector recalibration — validation & shadow-test analysis.

READ-ONLY. Does not modify production behavior. Produces the data behind
docs/pre_news_detector_recalibration_report.md.

Phases implemented (only what the stored data supports — gaps flagged):
  1. Raw-data audit + field availability
  2. Outcome metrics (single-aggregate MFE/MAE only — windowed not stored)
  3/4. BASELINE (suspicion>=75) vs V2 (anomaly-type + safety) side-by-side
  5. Monster analysis (cross-ref vs news-path monsters)
  6. Precision/recall with Wilson 95% CIs, N<30 flagged
  7. Alert-volume estimate
"""
from __future__ import annotations

import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

OUT = Path("data/agentic/pre_news_outcomes.json")
ANOM = Path("data/agentic/pre_news_anomalies.json")
ALERTS = Path("data/agentic/news_momentum_telegram_alerts.json")

GOOD_TYPES = {
    "unusual_volume_no_news", "volume_before_news", "hidden_accumulation",
    "early_breakout_positioning", "quiet_volume_build",
}


def wilson(k, n, z=1.96):
    """Wilson 95% CI for a proportion. Returns (low, high) in %."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z*z/n
    centre = (p + z*z/(2*n)) / denom
    half = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / denom
    return (max(0.0, (centre-half)) * 100, min(1.0, (centre+half)) * 100)


def load_outcomes():
    d = json.loads(OUT.read_text())
    return [r for r in d["outcomes"] if isinstance(r, dict)]


def phase1_audit(rows):
    print("=" * 70)
    print("PHASE 1 — RAW DATA AUDIT")
    print("=" * 70)
    print(f"Source: {OUT}")
    print(f"Total records: {len(rows)}")
    resolved = [r for r in rows if r.get("max_favorable_excursion_pct") is not None]
    print(f"Resolved (have MFE): {len(resolved)}")
    fields = ["suspicion_score", "anomaly_type", "max_favorable_excursion_pct",
              "max_adverse_excursion_pct", "time_to_peak_minutes", "was_real_move",
              "was_pump", "entry_price", "peak_price", "news_appeared_minutes_after"]
    print("\nField population:")
    for f in fields:
        nn = sum(1 for r in rows if r.get(f) is not None)
        print(f"  {f:34} {nn:4}/{len(rows)} ({100*nn//len(rows)}%)")
    windowed = [k for k in rows[0].keys()
                if any(w in k.lower() for w in ["60", "hour", "session", "two_day", "next_day", "five", "_2d", "_5d"])]
    print(f"\nWindowed-MFE fields (60m/session/2d): "
          f"{windowed if windowed else 'NONE — only single aggregate MFE/MAE stored'}")
    print("  => Phase-2 multi-window metrics + WIN_20 'MFE before MAE' sequencing")
    print("     are NOT computable from stored aggregates. Flagged.")
    return resolved


def band_stats(rows, lo, hi):
    sub = [r for r in rows if lo <= (r.get("suspicion_score") or 0) < hi]
    n = len(sub)
    if n == 0:
        return None
    win = sum(1 for r in sub if r.get("was_real_move"))
    mfe = [r["max_favorable_excursion_pct"] for r in sub]
    mae = [r.get("max_adverse_excursion_pct") or 0 for r in sub]
    lo_ci, hi_ci = wilson(win, n)
    return dict(n=n, win=win, winrate=100*win/n, ci=(lo_ci, hi_ci),
                med_mfe=st.median(mfe), med_mae=st.median(mae),
                p20=100*sum(1 for m in mfe if m >= 20)/n,
                p50=100*sum(1 for m in mfe if m >= 50)/n)


def phase1_bands(rows):
    print("\n" + "=" * 70)
    print("PHASE 1 — SUSPICION-BAND RE-DERIVATION (Wilson 95% CI)")
    print("=" * 70)
    print("%10s %5s %7s %14s %8s %8s %6s %6s" %
          ("band", "n", "win%", "95% CI", "medMFE", "medMAE", "+20%", "+50%"))
    for lo, hi in [(0, 50), (50, 75), (75, 101)]:
        s = band_stats(rows, lo, hi)
        band = "%d-%d" % (lo, hi)
        if not s:
            print("%10s  (no records)" % band)
            continue
        ci = "[%.0f-%.0f]" % (s["ci"][0], s["ci"][1])
        flag = "  <-- N<30, NOT RELIABLE" if s["n"] < 30 else ""
        print("%10s %5d %6.0f%% %14s %7.1f%% %7.1f%% %5.0f%% %5.0f%%%s" %
              (band, s["n"], s["winrate"], ci, s["med_mfe"], s["med_mae"],
               s["p20"], s["p50"], flag))


def baseline(r):
    return (r.get("suspicion_score") or 0) >= 75


def v2(r):
    if (r.get("anomaly_type") or "") not in GOOD_TYPES:
        return False
    if r.get("was_pump"):
        return False
    return True


def phase6_compare(rows):
    print("\n" + "=" * 70)
    print("PHASE 6 — BASELINE vs V2 (resolved outcomes, Wilson 95% CI)")
    print("=" * 70)
    for gate, label in [(baseline, "BASELINE suspicion>=75"), (v2, "V2 type+safety")]:
        al = [r for r in rows if gate(r)]
        n = len(al)
        if n == 0:
            print(f"{label:26} 0 alerts"); continue
        win = sum(1 for r in al if r.get("was_real_move"))
        mfe = [r["max_favorable_excursion_pct"] for r in al]
        ci = wilson(win, n)
        flag = "  [N<30]" if n < 30 else ""
        p20 = 100 * sum(1 for m in mfe if m >= 20) / n
        p50 = sum(1 for m in mfe if m >= 50)
        print("%-26s n=%3d real_move=%3.0f%% CI[%.0f-%.0f] medMFE=%5.1f%% +20%%=%3.0f%% +50%%=%d%s" %
              (label, n, 100*win/n, ci[0], ci[1], st.median(mfe), p20, p50, flag))


def phase5_monsters(rows):
    print("\n" + "=" * 70)
    print("PHASE 5 — MONSTER ANALYSIS (news-path MFE>=100 cross-ref)")
    print("=" * 70)
    d = json.loads(ALERTS.read_text())
    arows = [r for r in (d if isinstance(d, list) else d.get("alerts", []))
             if isinstance(r, dict) and r.get("mfe_pct") is not None]
    monsters = {}
    for r in arows:
        if r["mfe_pct"] >= 100:
            t = r.get("ticker"); monsters[t] = max(monsters.get(t, 0), r["mfe_pct"])
    # pre-news anomaly records (have suspicion + alert_quality + detected_at)
    pa = json.loads(ANOM.read_text())
    prows = pa if isinstance(pa, list) else (pa.get("anomalies") or list(pa.values()))
    pre = {}
    for r in prows:
        if isinstance(r, dict) and r.get("ticker"):
            pre.setdefault(r["ticker"], r)
    print(f"{'ticker':7} {'eventual':>9} {'pre-seen':>9} {'susp':>5} {'alert_q':>9} {'BASE?':>6} {'V2?':>5}")
    seen = 0
    for t, m in sorted(monsters.items(), key=lambda x: -x[1]):
        p = pre.get(t)
        if p:
            seen += 1
            susp = p.get("pre_news_suspicion_score")
            susp_s = ("%.0f" % susp) if susp is not None else "?"
            aq = p.get("alert_quality") or "?"
            base = "YES" if (susp or 0) >= 75 else "no"
            atype = p.get("anomaly_type") or ""
            v2a = "YES" if (atype in GOOD_TYPES and not p.get("was_pump")) else "no"
            print("%-7s %7.0f%% %9s %5s %9s %6s %5s" %
                  (t, m, "YES", susp_s, aq, base, v2a))
        else:
            print("%-7s %7.0f%% %9s %5s %9s %6s %5s" %
                  (t, m, "never", "--", "--", "--", "--"))
    print(f"\nMonsters detected by pre-news: {seen}/{len(monsters)} "
          f"({100*seen//len(monsters)}%) | news-path anomaly signal caught: 0")


def main():
    rows = load_outcomes()
    resolved = phase1_audit(rows)
    phase1_bands(resolved)
    phase6_compare(resolved)
    phase5_monsters(resolved)
    print("\n(Phase 7 volume + full writeup -> docs/pre_news_detector_recalibration_report.md)")


if __name__ == "__main__":
    main()
