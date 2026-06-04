#!/usr/bin/env python3
import json
from pathlib import Path

path = Path("data/agentic/evaluation_reports/pre_news_success_rate_report.json")
r = json.load(open(path))

print("=" * 60)
print("PRE-NEWS DETECTOR V3 — LIVE EFFECTIVENESS REPORT")
print("=" * 60)

print("\n--- EXECUTIVE SUMMARY ---")
dq = r['data_quality']
print(f"Total detections loaded:    {dq['total_detections']}")
print(f"Usable for analysis:        {dq['usable_for_success_rate']} ({dq['usable_percentage']}%)")
print(f"Unique tickers:             {dq['unique_tickers']}")
print(f"Trading sessions:           {dq['trading_sessions']}")

om = r['overall_metrics']
print(f"\nClean success rate:         {om['clean_success_rate']}%")
print(f"High-quality success rate:  {om['high_quality_success_rate']}%")
print(f"Basic success rate:         {om['basic_success_rate']}%")
print(f"Pre-news success rate:      {om['pre_news_success_rate']}%")
print(f"News-lag success rate:      {om['news_lag_success_rate']}%")
print(f"Avoidance success rate:     {om['avoidance_success_rate']}%")

print(f"\nAvg 1h move:                {om['avg_max_move_1h_pct']}%")
print(f"Median 1h move:             {om['median_max_move_1h_pct']}%")
print(f"Avg 2h move:                {om['avg_max_move_2h_pct']}%")
print(f"Avg drawdown:               {om['avg_drawdown_before_max_move_pct']}%")
print(f"Median drawdown:            {om['median_drawdown_before_max_move_pct']}%")
print(f"Avg efficiency ratio:       {om['avg_efficiency_ratio']}")
print(f"Median efficiency ratio:    {om['median_efficiency_ratio']}")
print(f"VWAP hold rate:             {om['vwap_hold_rate']}%")

print("\n--- DETECTOR vs BASELINES ---")
bc = r['baseline_comparison']
if 'note' in bc:
    print(bc['note'])
else:
    print(f"{'Baseline Type':<35} {'n':>5} {'B-Clean':>8} {'D-Clean':>8} {'B-Eff':>7} {'D-Eff':>7} {'Verdict':<40}")
    print("-" * 105)
    for c in bc['comparisons']:
        v = bc['verdicts'].get(c['baseline_type'], 'UNKNOWN')
        print(f"{c['baseline_type']:<35} {c['usable']:>5} {c['baseline_clean_success_rate']:>7.1f}% {c['detector_clean_success_rate']:>7.1f}% {c['baseline_avg_efficiency']:>7.2f} {c['detector_avg_efficiency']:>7.2f} {v:<40}")

print("\n--- TOP 3 ALERT QUALITIES ---")
for b in sorted(r['buckets']['alert_quality'], key=lambda x: x['clean_success_rate'] or 0, reverse=True)[:3]:
    print(f"  {b['bucket']:<15} clean={b['clean_success_rate']:>5.1f}%  n={b['count']:>3}  conf={b['confidence_level']}")

print("\n--- TOP 3 ANOMALY TYPES ---")
for b in sorted(r['buckets']['anomaly_type'], key=lambda x: x['clean_success_rate'] or 0, reverse=True)[:3]:
    print(f"  {b['bucket']:<25} clean={b['clean_success_rate']:>5.1f}%  n={b['count']:>3}  conf={b['confidence_level']}")

print("\n--- CALIBRATION RECOMMENDATIONS ---")
for rec in r['recommendations'][:5]:
    print(f"  [{rec['recommendation_type']}] {rec['affected_bucket']}: {rec['suggested_change']}")

print("\n" + "=" * 60)
print("VERDICT:", end=" ")
if om['clean_success_rate'] >= 40:
    print("STRONG EVIDENCE — Detector is finding high-quality pre-news setups.")
elif om['clean_success_rate'] >= 25:
    print("MODERATE EVIDENCE — Shows promise but needs refinement.")
elif om['clean_success_rate'] >= 10:
    print("WEAK EVIDENCE — Some signals work but many fail.")
else:
    print("POOR — Success rate is too low.")
print("=" * 60)
