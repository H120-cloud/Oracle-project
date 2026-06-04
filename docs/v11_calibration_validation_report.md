# Historical Catalyst Training Engine — Validation Report
**Generated:** 2026-05-02T21:06:13.428165+00:00 UTC

## 1. Before/After Scoring (5 Sample Candidates)

| Candidate | Baseline Prob | Calibrated Prob | Baseline Trap | Calibrated Trap | Baseline TOD | Calibrated TOD | Baseline Float | Calibrated Float |
|-----------|--------------|-----------------|---------------|-----------------|--------------|----------------|----------------|------------------|
| C1 | 84.9 | 100.0 | 45.0 | 49.5 | -15.0 | -13.5 | 95.0 | 95.0 |
| C2 | 39.7 | 49.1 | 45.0 | 49.5 | -15.0 | -13.5 | 55.0 | 55.0 |
| C3 | 84.9 | 100.0 | 45.0 | 49.5 | -15.0 | -13.5 | 95.0 | 95.0 |
| C4 | 13.9 | 17.3 | 45.0 | 49.5 | -15.0 | -13.5 | 40.0 | 40.0 |
| C5 | 76.2 | 93.0 | 45.0 | 49.5 | -15.0 | -13.5 | 70.0 | 70.0 |

## 2. Engines That Applied Calibrated Weights

- **SecondLegEngine**
- **TimeOfDayEngine**
- **TrapDetector**

## 3. Guardrail Status

- :white_check_mark: OK: second_leg_probability_w = 1.15 (within ±15%)
- :white_check_mark: OK: float_bucket_w = 1.08 (within ±15%)
- :white_check_mark: OK: time_of_day_w = 0.9 (within ±15%)
- :white_check_mark: OK: trap_risk_w = 1.1 (within ±15%)

## 4. Test Results

**Overall status:** PASS :white_check_mark:

```
tests/test_historical_training_integration.py::TestScoreValidation::test_before_after_scores PASSED [ 94%]
tests/test_historical_training_integration.py::TestScoreValidation::test_guardrail_max_drift PASSED [ 97%]
tests/test_historical_training_integration.py::TestScoreValidation::test_all_tests_pass PASSED [100%]

============================= 39 passed in 4.25s ==============================
```

## 5. Notes
- Calibration weights are manually approved only (`is_approved=True`).
- Fallback to default weights occurs when no approved weights exist.
- Max drift guardrail: ±15% (0.85–1.15 multiplier range).
- No single feature may exceed 40% of total weight dominance.
- Orchestrator no longer double-applies calibration; individual engines handle their own multipliers.
