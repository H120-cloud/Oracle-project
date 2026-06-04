# V13 Risk Rules Replay Validation Report

Generated: 2026-05-03T03:18:36.565519+00:00

---

## Overall Metrics Comparison

| Metric | Base | +QS | +QS+HR | +QS+HR+ASYM |
|--------|------|-----|--------|-------------|
| Total Alerts | 70 | 70 | 45 | 45 |
| False Alerts | 25 | 25 | 0 | 0 |
| Clean Continuations | 45 | 45 | 45 | 45 |
| Missed Runners (blocked winners) | 0 | 0 | 0 | 0 |
| Blocked by Hard Rules | 0 | 0 | 35 | 35 |
| Improved by Asymmetric Scoring | 0 | 0 | 0 | 25 |

## Key Rates

| Metric | Base | +QS | +QS+HR | +QS+HR+ASYM |
|--------|------|-----|--------|-------------|
| False Alert Rate | 35.7% | 35.7% | 0.0% | 0.0% |

## MFE / MAE (per alerted trade)

| Mode | Avg MFE | Avg MAE | MFE/MAE Ratio |
|------|---------|---------|---------------|
| base | 4.46 | -0.43 | 10.42 |
| qs | 4.46 | -0.43 | 10.42 |
| qs_hr | 6.94 | -0.67 | 10.42 |
| qs_hr_asym | 6.94 | -0.67 | 10.42 |

## 60-80 Probability Band Performance

| Mode | Alerts in Band | False in Band | False Rate |
|------|----------------|---------------|------------|
| base | 70 | 25 | 35.7% |
| qs | 70 | 25 | 35.7% |
| qs_hr | 45 | 0 | 0.0% |
| qs_hr_asym | 20 | 0 | 0.0% |

## Hard Rejection Rule Breakdown

| Rule | Blocks |
|------|--------|
| late_extended_move | 25 |
| failed_second_leg | 10 |
| distribution_pattern | 10 |
| **Total** | **35** |

## Sample Blocked Candidates (Hard Rejection)

- **ATRAP** (alertable_trap) — base_prob=78.0, final_prob=78.0
- **ATRAP** (alertable_trap) — base_prob=78.0, final_prob=78.0
- **TRAP** (trap) — base_prob=35.0, final_prob=35.0
- **ATRAP** (alertable_trap) — base_prob=78.0, final_prob=78.0
- **ATRAP** (alertable_trap) — base_prob=78.0, final_prob=78.0
- **TRAP** (trap) — base_prob=35.0, final_prob=35.0
- **AFAIL** (alertable_failed) — base_prob=76.0, final_prob=76.0
- **AFAIL** (alertable_failed) — base_prob=76.0, final_prob=76.0

## Sample Asymmetric Improvements

- **WIN** (clean_winner) — base_prob=78.0, final_prob=90.0, reasons=['asym_boost']

## Conclusions

- **False alert reduction**: 100.0% (25 → 0)

- **Overall alert reduction**: 35.7% (70 → 45)

- **Missed runners**: 0 (winners blocked by new layers)

- **Clean continuation preservation**: 45 / 45 winners still alerted
