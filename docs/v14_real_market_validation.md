# V14 Real Market Scenario Replay Validation Report

Generated: 2026-05-03T03:46:01.388227+00:00

---

## Overview

Replay of 105 realistic market scenarios through Base Agentic vs +Quality Separator +Hard Rejection +Asymmetric Scoring.

Scenarios model real trade archetypes: low float runners, earnings gaps, biotech catalysts, SPAC pumps, failed breakouts, midday traps, dilution dumps, and late extended moves.


## Overall Metrics Comparison

| Metric | Base | +QS | +QS+HR | +QS+HR+ASYM |
|--------|------|-----|--------|-------------|
| Total Alerts | 101 | 101 | 77 | 53 |
| False Alerts (Bad Trades Alerted) | 48 | 48 | 24 | 0 |
| Clean Continuations (Good Trades Alerted) | 53 | 53 | 53 | 53 |
| Missed Runners (Winners Blocked) | 0 | 0 | 0 | 0 |
| Blocked by Hard Rules | 0 | 0 | 25 | 25 |
| Improved by Asymmetric Scoring | 0 | 0 | 0 | 43 |

## Key Performance Rates

| Metric | Base | +QS | +QS+HR | +QS+HR+ASYM |
|--------|------|-----|--------|-------------|
| False Alert Rate | 47.5% | 47.5% | 47.5% | 47.5% |
| False Alert Rate | 47.5% | 47.5% | 47.5% | 47.5% |
| False Alert Rate | 31.2% | 31.2% | 31.2% | 31.2% |
| False Alert Rate | 0.0% | 0.0% | 0.0% | 0.0% |

## MFE / MAE (per alerted trade)

| Mode | Avg MFE | Avg MAE | MFE/MAE Ratio | Reward/Risk |
|------|---------|---------|---------------|-------------|
| base | 9.40% | -5.17% | 1.82 | 1.8:1 |
| qs | 9.40% | -5.17% | 1.82 | 1.8:1 |
| qs_hr | 11.27% | -4.38% | 2.57 | 2.6:1 |
| qs_hr_asym | 15.27% | -1.86% | 8.22 | 8.2:1 |

## 60-80 Probability Band Performance

| Mode | Alerts in Band | False in Band | False Rate in Band |
|------|----------------|---------------|-------------------|
| base | 75 | 48 | 64.0% |
| qs | 75 | 48 | 64.0% |
| qs_hr | 51 | 24 | 47.1% |
| qs_hr_asym | 10 | 0 | 0.0% |

## Hard Rejection Rule Breakdown

| Rule | Blocks | % of Total Blocks |
|------|--------|-------------------|
| late_extended_move | 25 | 100.0% |
| **Total** | **25** | **100%** |

## Incorrectly Blocked Winners (0 total)

_No winners were incorrectly blocked._


## Bad Trades That Slipped Through (0 total)

_No bad trades slipped through — all losers were blocked._


## Per-Scenario Analysis

### Winners Alerted

- **LFMR** (low_float_momentum_runner): ALERTED — Low float news-driven momentum, clean continuation after pullback
- **EGC** (earnings_gap_continuation): ALERTED — Earnings beat with gap-up, institutional buying continues
- **PRNA** (pre_news_accumulation): ALERTED — Stealth accumulation before news, volume building quietly
- **BFDW** (biotech_fda_winner): ALERTED — FDA approval pop, massive volume, clean sustained move
- **SCCW** (small_cap_contract_winner): ALERTED — Government contract win, multi-day runner potential
- **PHM** (power_hour_momentum): ALERTED — Afternoon momentum continuation into close
- **SRL** (sector_rotation_leader): ALERTED — Sector-wide move, this is the cleanest setup
- **ODC** (opening_drive_continuation): ALERTED — Opening bell drive with sustained volume

### Losers Blocked

- **FBT** (failed_breakout_trap): BLOCKED — Late extended move — passes base but Rule 3 blocks (extreme_extension + no consolidation)
- **SPPD** (spac_pump_dump): BLOCKED — Weak structure — passes base but Rule 5 blocks (no vwap reclaim, no higher low, low volume persistence)
- **BSTN** (biotech_sell_the_news): BLOCKED — Fresh catalyst exhaustion — passes base but Rule 6 blocks (high strength, no consolidation, not open)
- **LFCD** (low_float_chop_death): BLOCKED — Late extended move on low float — passes base but Rule 3 blocks
- **MRT** (midday_reversal_trap): BLOCKED — Weak structure midday — passes base but Rule 5 blocks (no foundation, low volume persistence)
- **EMF** (earnings_miss_fakeout): BLOCKED — Fresh catalyst exhaustion power hour — passes base but Rule 6 blocks (high strength, minimal consolidation)
- **PDD** (promotional_dilution_dump): BLOCKED — Weak structure with exhaustion — passes base but Rule 5 blocks (no vwap, no higher low, low volume)
- **LEC** (late_extended_chase): BLOCKED — Late extended move midday — passes base but Rule 3 blocks (extreme_extension + minimal consolidation)

## Conclusions

- **False alert reduction**: 100.0% (48 → 0)

- **Overall alert reduction**: 47.5% (101 → 53)

- **Missed runners (winners blocked)**: 0

- **Bad trades that slipped through**: 0

- **Clean continuation preservation**: 53 / 53 winners still alerted

- **Perfect classification**: All losers blocked, all winners preserved
