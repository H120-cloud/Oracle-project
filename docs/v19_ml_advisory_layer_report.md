# V19 ML Advisory Layer Report

## Executive Summary

V19 introduces a **supervised machine learning advisory layer** to the Agentic learning engine. It uses historical feature snapshots and outcomes to train predictive models that estimate:
- Probability of clean continuation
- Probability of false alert
- Expected MFE (Max Favorable Excursion)
- Expected MAE (Max Adverse Excursion)

The ML layer **does not replace** existing rule-based logic. It operates as an advisory-only system with full manual approval, drift monitoring, and graceful fallback.

---

## Architecture

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **MLAdvisoryEngine** | `src/core/agentic/ml_advisory.py` | Training, prediction, drift monitoring |
| **FeatureEngineer** | `src/core/agentic/ml_advisory.py` | Feature extraction + interaction engineering |
| **MLPrediction** | `src/core/agentic/ml_advisory.py` | Prediction output dataclass |
| **ModelVersion** | `src/core/agentic/ml_advisory.py` | Versioned model metadata |
| **DriftReport** | `src/core/agentic/ml_advisory.py` | Drift detection results |

### Models

| Model | Type | Purpose | Interpretability |
|-------|------|---------|------------------|
| **Logistic Regression** | Baseline | Continuation / False alert probability | High (coefficients) |
| **XGBoost** | Ensemble | Captures non-linear interactions | Medium (feature importance) |
| **Stacked Ensemble** | Meta-learner | Combines LR + XGB predictions | Medium (SHAP) |
| **Ridge Regression** | Regressor | Expected MFE / MAE | High |

### Feature Engineering

**Core features (9):**
- `probability` — second-leg probability score
- `trap_risk` — trap detector score
- `volume_persistence` — volume persistence %
- `higher_low_formed` — boolean, encoded as int
- `catalyst_strength` — catalyst strength score
- `rejected` / `alertable` — boolean flags
- `vwap_held` — boolean
- `entry_quality` — encoded (early=0, late=1, ideal=2)

**Interaction features (5):**
- `prob_x_trap` — probability × trap risk
- `prob_x_vol` — probability × volume persistence
- `prob_x_catalyst` — probability × catalyst strength
- `trap_x_float` — trap risk × float category
- `catalyst_x_time` — catalyst strength × time of day

---

## Training Pipeline

### Temporal Walk-Forward Cross-Validation

```
Fold 1: Train [0-3],  Validate [4]
Fold 2: Train [0-7],  Validate [8]
Fold 3: Train [0-11], Validate [12]
Fold 4: Train [0-15], Validate [16]
Fold 5: Train [0-19], Validate [20]
```

- **No look-ahead bias**: validation always occurs after training
- **Class imbalance handling**: `scale_pos_weight` = 3.0 × (negatives/positives)
- **Calibration**: Isotonic calibration applied to final ensemble

### Evaluation Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| AUC-ROC | > 0.65 | Discrimination ability |
| F-beta (β=0.5) | > 0.50 | Penalizes false alerts heavily |
| Brier Score | < 0.25 | Probability calibration quality |
| Log Loss | < 0.50 | Overall probability accuracy |
| Calibration Slope | ~1.0 | Linear calibration check |

---

## Safety Protocols

### Manual Approval Workflow

```
1. Train model → creates new version (shadow mode)
2. Review metrics → AUC, F-beta, Brier score
3. Manual approve → via API or frontend
4. Model goes live → predictions marked as "LIVE"
5. Previous version → automatically deactivated
```

### Drift Monitoring

| Check | Threshold | Action |
|-------|-----------|--------|
| PSI (Population Stability Index) | > 0.2 | Flag degraded |
| KS Statistic (per feature) | > 0.3 | Flag feature drift |
| Brier Degradation | > 0.1 | Flag calibration decay |
| **Auto-fallback** | Any threshold breached | Fallback to rule-based |

### Graceful Degradation

- If model fails to load → fallback to rule-based
- If prediction fails → fallback with logged reason
- If drift detected → predictions continue but flagged as "SHADOW"

---

## Integration Points

### Orchestrator (`orchestrator.py`)

ML prediction is generated for every candidate during pipeline run:
```python
# After ABCD detection, before alertable decision
cand.ml_prediction = self.learning.predict_ml(cand)
```

### Learning Engine (`learning.py`)

New methods added:
- `predict_ml(candidate)` → generate ML prediction
- `train_ml()` → trigger model training
- `get_ml_status()` → get version info
- `approve_ml_model(version, user)` → manual approval
- `check_ml_drift()` → drift detection

### API Routes (`agentic.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/agentic/ml/train` | POST | Trigger model training |
| `/agentic/ml/status` | GET | Get model versions + status |
| `/agentic/ml/approve` | POST | Approve a model version |
| `/agentic/ml/drift` | GET | Check prediction drift |
| `/agentic/ml/predict/{ticker}` | GET | Get ML prediction for ticker |

### Frontend (`Agentic.jsx`)

- **ML tab** in dashboard — shows version list, train/approve buttons, metrics
- **Candidate row** — small ML continuation probability badge
- **Detail panel** — full ML prediction with SHAP explanations

---

## Audit Trail

Every prediction is logged to `data/agentic/ml_audit_log.jsonl`:
```json
{
  "timestamp": "2026-05-05T05:00:00Z",
  "ticker": "AAPL",
  "candidate_id": "...",
  "model_version": "20260505_050000",
  "continuation_prob": 0.72,
  "false_alert_prob": 0.18,
  "expected_mfe": 12.5,
  "expected_mae": 2.1,
  "confidence": "HIGH",
  "top_shap": [
    {"feature": "probability", "shap_value": 0.15, "feature_value": 80.0},
    ...
  ]
}
```

---

## Files Added / Modified

### New Files
- `src/core/agentic/ml_advisory.py` — Core ML engine (~600 lines)
- `tests/test_ml_advisory.py` — Comprehensive test suite
- `docs/v19_ml_advisory_layer_report.md` — This report

### Modified Files
- `src/core/agentic/models.py` — Added `MLPredictionResult` model + field on `AgenticCandidate`
- `src/core/agentic/learning.py` — Integrated ML methods into `LearningEngine`
- `src/core/agentic/orchestrator.py` — Added ML prediction to pipeline
- `src/api/routes/agentic.py` — Added ML API endpoints
- `frontend/src/api.js` — Added ML API functions
- `frontend/src/pages/Agentic.jsx` — Added ML tab, panel, candidate indicators
- `requirements.txt` — Added `xgboost==2.1.3`, `shap==0.46.0`

---

## Test Results

```
pytest tests/test_ml_advisory.py -v

TestFeatureEngineer::test_extract_basic PASSED
TestFeatureEngineer::test_interaction_features PASSED
TestMLAdvisoryEngine::test_predict_without_model PASSED
TestMLAdvisoryEngine::test_train_insufficient_samples PASSED
TestMLAdvisoryEngine::test_train_and_predict PASSED
TestMLAdvisoryEngine::test_drift_without_model PASSED
TestMLAdvisoryEngine::test_model_versioning PASSED
TestMLAdvisoryEngine::test_approve_model PASSED
TestMLAdvisoryEngine::test_list_versions PASSED
TestIntegration::test_full_pipeline SKIPPED (insufficient samples)
TestIntegration::test_feature_engineer_empty PASSED

10 passed, 1 skipped in 4.47s
```

---

## Deployment Checklist

- [ ] Run `pip install -r requirements.txt` to install XGBoost + SHAP
- [ ] Verify model directory exists (`data/agentic/ml_models/`)
- [ ] Train initial model with 80+ historical outcomes
- [ ] Review metrics (AUC > 0.65, F-beta > 0.50)
- [ ] Approve model manually via `/agentic/ml/approve`
- [ ] Monitor drift weekly via `/agentic/ml/drift`
- [ ] Review audit trail in `data/agentic/ml_audit_log.jsonl`

---

## Future Enhancements

1. **A/B Testing Framework** — Shadow-mode comparison of ML vs rule-based
2. **Online Learning** — Incremental model updates as new outcomes arrive
3. **Deep Learning** — Neural network for capturing complex feature interactions
4. **Sector-specific Models** — Per-sector model specialization
5. **Real-time Feature Store** — Prevent training-serving skew

---

*Report generated: 2026-05-05 05:00 UTC*
*V19 ML Advisory Layer*
