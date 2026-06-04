"""
Pre-News Shadow V2 -- BASELINE vs V2_SHADOW comparison report.

READ-ONLY. Reads data/agentic/pre_news_shadow_v2.json and prints/writes a
side-by-side comparison. Promotion is gated (see PROMOTION RULE below).

Run: python scripts/pre_news_shadow_v2_report.py
     python scripts/pre_news_shadow_v2_report.py --write   # also writes the .md
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SHADOW = Path("data/agentic/pre_news_shadow_v2.json")
REPORT = Path("docs/pre_news_shadow_v2_report.md")

MIN_RESOLVED = 100
MIN_DAYS = 30


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / d
    return (max(0.0, c-h)*100, min(1.0, c+h)*100)


def load():
    if not SHADOW.exists():
        return []
    return json.loads(SHADOW.read_text()).get("records", [])


def _metrics(recs):
    """Always returns a dict with every key (zeros when no resolved data)."""
    recs = recs or []
    resolved = [r for r in recs if r.get("resolved")]
    n_all, n_res = len(recs), len(resolved)
    empty = dict(n_all=n_all, n_res=0, win_rate=0, win_ci=(0, 0), hit20=0,
                 hit50=0, hit100=0, monster=0, monster_rate=0, fp_rate=0,
                 avg_mfe=0, med_mfe=0, avg_mae=0, med_mae=0, trap_rate=0)
    if n_res == 0:
        return empty

    def best_mfe(r):
        return max([m for m in [r.get("mfe_15m"), r.get("mfe_60m"),
                                r.get("mfe_session"), r.get("mfe_2d")] if m is not None] or [0])

    def worst_mae(r):
        return min([m for m in [r.get("mae_15m"), r.get("mae_60m"),
                                r.get("mae_session"), r.get("mae_2d")] if m is not None] or [0])

    mfes = [best_mfe(r) for r in resolved]
    maes = [worst_mae(r) for r in resolved]
    h20 = sum(1 for r in resolved if r.get("hit_20"))
    h50 = sum(1 for r in resolved if r.get("hit_50"))
    h100 = sum(1 for r in resolved if r.get("hit_100"))
    traps = sum(1 for r in resolved if r.get("became_trap"))
    wins = h20
    return dict(
        n_all=n_all, n_res=n_res,
        win_rate=100*wins/n_res, win_ci=wilson(wins, n_res),
        hit20=100*h20/n_res, hit50=100*h50/n_res, hit100=100*h100/n_res,
        monster=h100, monster_rate=100*h100/n_res,
        fp_rate=100*(n_res - wins)/n_res,
        avg_mfe=sum(mfes)/n_res, med_mfe=st.median(mfes),
        avg_mae=sum(maes)/n_res, med_mae=st.median(maes),
        trap_rate=100*traps/n_res,
    )


def _fmt(m, label):
    if not m or m.get("n_res", 0) == 0:
        n_all = m.get("n_all", 0) if m else 0
        return "%-14s alerts=%4d  resolved=0  (no forward data yet)" % (label, n_all)
    flag = "  [N<30]" if m["n_res"] < 30 else ""
    return ("%-14s alerts=%4d resolved=%4d win+20%%=%4.0f%% CI[%.0f-%.0f] "
            "+50%%=%3.0f%% +100%%=%3.0f%% monsters=%d medMFE=%5.1f%% medMAE=%5.1f%% trap=%3.0f%%%s" %
            (label, m["n_all"], m["n_res"], m["win_rate"], m["win_ci"][0], m["win_ci"][1],
             m["hit50"], m["hit100"], m["monster"], m["med_mfe"], m["med_mae"], m["trap_rate"], flag))


def build(records):
    base = [r for r in records if r.get("baseline_would_alert")]
    v2 = [r for r in records if r.get("v2_would_alert")]
    mb, mv = _metrics(base), _metrics(v2)

    dts = [datetime.fromisoformat(r["detection_time"].replace("Z", "+00:00"))
           for r in records if r.get("detection_time")]
    days = max(1, (max(dts) - min(dts)).days) if len(dts) > 1 else 1
    span = "%s -> %s" % (min(dts).date(), max(dts).date()) if dts else "n/a"

    lines = []

    def P(s=""):
        lines.append(s)
        print(s)

    P("=" * 74)
    P("PRE-NEWS SHADOW V2 REPORT -- BASELINE vs V2_SHADOW")
    P("=" * 74)
    P("Records: %d  span: %s  (~%d days)" % (len(records), span, days))
    P("Resolved: %d" % sum(1 for r in records if r.get("resolved")))
    P("")
    P("OVERALL COMPARISON")
    P("  " + _fmt(mb, "BASELINE"))
    P("  " + _fmt(mv, "V2_SHADOW"))
    P("")
    P("ALERT VOLUME/DAY:  BASELINE=%.1f  V2_SHADOW=%.1f" % (mb["n_all"]/days, mv["n_all"]/days))

    P("\nBY ANOMALY TYPE (resolved only)")
    by = defaultdict(list)
    for r in records:
        if r.get("resolved"):
            by[r.get("anomaly_type") or "?"].append(r)
    for t, sub in sorted(by.items(), key=lambda x: -len(x[1])):
        m = _metrics(sub)
        if m.get("n_res"):
            P("  %-26s n=%3d +20%%=%3.0f%% +50%%=%3.0f%% medMFE=%5.1f%%" %
              (t, m["n_res"], m["hit20"], m["hit50"], m["med_mfe"]))

    P("\nBY SUSPICION BAND (resolved only)")
    for lo, hi in [(0, 50), (50, 75), (75, 101)]:
        sub = [r for r in records if r.get("resolved") and lo <= (r.get("suspicion_score") or 0) < hi]
        m = _metrics(sub)
        if m.get("n_res"):
            fl = " [N<30]" if m["n_res"] < 30 else ""
            P("  %d-%d: n=%3d +20%%=%3.0f%% +100%%=%3.0f%% medMFE=%5.1f%%%s" %
              (lo, hi, m["n_res"], m["hit20"], m["hit100"], m["med_mfe"], fl))

    n_res = sum(1 for r in records if r.get("resolved"))
    P("\n" + "=" * 74)
    P("PROMOTION VERDICT")
    P("=" * 74)
    gate_ok = n_res >= MIN_RESOLVED or days >= MIN_DAYS
    if not gate_ok:
        P("  HOLD -- insufficient data. Need >= %d resolved (have %d) OR >= %d days (have ~%d)."
          % (MIN_RESOLVED, n_res, MIN_DAYS, days))
        P("  V2 stays in SHADOW. No production change.")
    else:
        better = (mv.get("hit100", 0) >= mb.get("hit100", 0)
                  and mv.get("win_rate", 0) >= mb.get("win_rate", 0) - 5)
        if better:
            P("  DATA SUFFICIENT + V2 improves monster capture without precision collapse.")
            P("  -> ELIGIBLE for promotion review (human sign-off still required).")
        else:
            P("  DATA SUFFICIENT but V2 does NOT clearly beat BASELINE. Keep in shadow.")
    return "\n".join(lines), {"base": mb, "v2": mv, "days": days, "n_res": n_res, "span": span}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="also write docs/.md")
    args = ap.parse_args()
    records = load()
    if not records:
        print("No shadow records yet at %s. Run the capture loop first." % SHADOW)
        return
    text, _ = build(records)
    if args.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            "# Pre-News Shadow V2 Report\n\n"
            "_Generated %s - READ-ONLY, no production change._\n\n```\n%s\n```\n"
            % (datetime.now().isoformat(timespec="seconds"), text),
            encoding="utf-8",
        )
        print("\nWrote %s" % REPORT)


if __name__ == "__main__":
    main()
