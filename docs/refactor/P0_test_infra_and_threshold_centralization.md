# P0 — Test Infrastructure + Threshold Centralization

**Status:** ready for review
**Date:** 2026-05-28
**Scope:** non-functional — no Telegram alert behavior change
**Successor work blocked on this:** Priority 2a (baseline backtest)

---

## What changed

### A. Test infrastructure (new)

| Path | Purpose |
|---|---|
| `pytest.ini` | Test runner config: `tests/` discovery, strict markers, no cache, deterministic warnings filter |
| `tests/__init__.py`, `tests/unit/`, `tests/regression/` | Two-tier suite layout |
| `tests/conftest.py` | Sys-path bootstrap, autouse fixed RNG seed (42), factory fixtures for `NewsMomentumCandidate` / `TelegramAlertRecord` / `ShadowAlertRecord`, `tmp_data_dir` for isolating any test that touches `data/agentic/` |
| `tests/fixtures/historical_misses.json` | Golden-file fixture — IMRN + LNKS regression cases |
| `tests/regression/test_classifier_historical_misses.py` | Parametrized regression suite over the golden file. Honors `xfail_today` flag for target-behavior entries |
| `tests/unit/test_fixtures_smoke.py` | Smoke-tests for the test infra itself |
| `tests/unit/test_config_threshold_centralization.py` | Pins every centralized threshold to its pre-refactor literal value |
| `scripts/test.ps1`, `scripts/test.sh` | One-line "run the suite" wrappers |
| `scripts/ci_check.ps1`, `scripts/ci_check.sh` | CI placeholder — `py_compile` + `pytest`. Mirrors what any future CI service should run |

### B. Threshold centralization (`NewsMomentumConfig`)

Added 28 fields to `src/core/agentic/news_momentum_models.py::NewsMomentumConfig`. All defaults match the literal values they replaced. Replaced inline literals at the call sites in `src/core/agentic/news_momentum_orchestrator.py::_should_send_telegram`.

| Group | Fields | Replaced literal in |
|---|---|---|
| ML hard floor / veto | `ml_min_win_probability`, `ml_veto_win_probability`, `ml_veto_min_confidence`, `ml_amplify_win_probability`, `ml_bypass_impact_threshold` | orchestrator gate |
| Sub-$10 leniency | `under_1_lenient_step_down`, `under_1_min_floor`, `under_1_max_price` | orchestrator gate |
| High-conviction step-down | `high_conviction_step_down`, `high_conviction_min_floor` | orchestrator gate |
| First-mover speed tier | `first_mover_max_age_seconds`, `first_mover_min_impact`, `first_mover_min_return`, `first_mover_min_continuation`, `first_mover_min_multi_day`, `first_mover_impact_floor` | orchestrator gate |
| Price-action breakout | `breakout_mega_move_pct`, `breakout_mega_rvol`, `breakout_strong_move_pct`, `breakout_strong_rvol`, `breakout_mega_impact_floor`, `breakout_strong_impact_floor`, `breakout_relax_min_impact`, `breakout_relax_min_continuation` | orchestrator gate |
| Impact floor base | `impact_floor_default`, `impact_floor_under_1` | orchestrator gate |
| Risk gates | `high_dilution_block_threshold`, `high_trap_block_threshold` | orchestrator gate |
| Winner ML tier bands | `ml_band_p85`, `ml_band_p95`, `ml_band_p99`, `ml_tier_high_conviction_adjust`, `ml_tier_watch_adjust` | snapshot only — `_ML_PERCENTILE_BANDS` in `news_momentum_winners.py` is left as a mutable global because it has a hot-recalibration setter (`set_ml_percentile_bands`). The new test asserts the seed values match the config defaults |

---

## How "no behavior change" is enforced

1. **Equivalence test** (`tests/unit/test_config_threshold_centralization.py`) — 30 parametrized assertions, one per centralized field. Any drift fails the build.
2. **Production sanity check** — re-ran the LNKS `warrant_overhang_removal` case from the previous session against the post-refactor orchestrator. `ALERT` with identical `news_impact_score=64.3`. Captured in the chat log; not a unit test because it depends on `yfinance` reachability.
3. **Regression suite** — 9 historical-miss entries (8 confirmed-passing, 1 `xfail` target). Any classifier change that breaks these fails CI.

---

## Test suite results

```
50 passed, 1 xfailed in 4.99s
```

The single `xfail` is `lnks_004_neg` — `"... 1-for-250 Reverse Share Split..."` — which the current classifier returns as `(unknown, unknown)`. Marked `xfail(strict=True)` so when P1's semantic classifier fixes it, the test surfaces as `XPASS` and forces the maintainer to flip the flag, promoting it to a hard regression.

---

## Open questions for review

These came up during P0; **none block P0 merging** but each needs your call before subsequent priorities can land cleanly.

### Q-A. Golden labels are marked `"status": "proposed"`

I drafted the IMRN + LNKS labels from the previous session's work. They are flagged as proposed and your prompt explicitly said *"I'll provide raw headlines + expected classifications"*. **Please review `tests/fixtures/historical_misses.json` and either confirm `status` → `"confirmed"` or send corrections.** Specific items I'm unsure about:

- `imrn_004` "Immuron IMM-529 IND approved by FDA" — labeled `fda_approval`. **Should `IND_APPROVAL` become its own `CatalystSubType`?** IND ≠ NDA approval; they're different milestones with different magnitudes.
- `lnks_004_neg` "Reverse Share Split" — labeled `negative` / `reverse_split`. **Are reverse splits *always* bearish?** Some pre-uplisting ones are neutral or even bullish. If the answer is "depends on context," that's another job for the semantic classifier.

### Q-B. `0.75 / 0.25 / 0.10` ML amplify formula

Lines ~1598–1603 of `news_momentum_orchestrator.py`:

```python
elif ml_pred.win_probability > 0.75:
    boost = 1.0 - ((ml_pred.win_probability - 0.75) / 0.25) * 0.10
    min_impact = max(min_impact * boost, min_impact * 0.90)
    ...
```

`0.75` is `ml_amplify_win_probability` in the config now, but the `0.25` denominator and `0.10` coefficient are still inline. Centralizing them risks a subtle floating-point drift in the boost calculation. **Want me to centralize them in P0 (with a strict-equality test on the boost output) or leave for P1?**

### Q-C. Inline keyword lists not yet centralized

`STRONG_POSITIVE` and `HARD_NEGATIVE` (orchestrator lines ~1320–1349) and `HIGH_CONVICTION_CATALYSTS` (lines ~1251–1298) remain inline. Per your Q8 answer, the keyword lists go away in P1 entirely. Per the spirit of P0, the catalyst set could move to `NewsMomentumConfig` now — but it has 70 entries and would clutter the config. **Confirm: leave both inline until P1?**

### Q-D. Feature-flag mechanism (Q4)

You approved the JSON-config-with-watcher approach. **It is NOT in P0.** P0 only centralizes constants. The flag mechanism is a small but real piece of new code; I propose landing it as the *first* commit of Priority 2a (baseline backtest) so the flag exists before any new code path needs it.

### Q-E. Pytest version drift

`requirements.txt` pins `pytest==8.3.3`, but the local install is `pytest==9.0.3`. The suite passes on 9.x but `requirements.txt` is out of date. **Want me to bump the pin or downgrade the local install?** I lean toward bumping the pin in this PR.

### Q-F. New file size discovery

`data/agentic/news_momentum_shadow_alerts.json` is **122 MB** and `news_momentum_candidates.json` is **53 MB**. Both are loaded fully into memory by their respective modules at import. This will become a problem for the backtest (Priority 2). I propose adding a streaming reader as part of Priority 2a, but flagging it now so it's not a surprise.

---

## What was deferred (not in this PR)

- Feature-flag infrastructure (Q-D above) → first commit of P2a
- Streaming JSON reader for shadow / candidates (Q-F) → P2a
- ML amplify formula constants (Q-B) → pending decision
- Inline keyword lists / `HIGH_CONVICTION_CATALYSTS` set (Q-C) → P1
- Removal of broad `try/except Exception: pass` blocks in the orchestrator gate (your "never silently catch" rule) → flagged for a separate hardening PR; touching them here would risk the no-behavior-change contract

---

## What surprised me

- **There were zero tests in this project.** Every test in this PR is the first of its kind for this codebase.
- **`HIGH_CONVICTION_CATALYSTS` has ~70 entries**, many for sub-types I doubt have ever fired (e.g. `EV_BATTERY`, `BITCOIN_TREASURY`). The deprecation audit you asked for in Q2 will probably trim this aggressively.
- **The shadow logger is already running and has a 122MB log.** That's a hidden asset for Priority 2 — we don't need to build a baseline from scratch, we already have ~weeks of comparison data sitting on disk. This may compress the P2a timeline meaningfully.
- **`_ML_PERCENTILE_BANDS` is a *mutable module-level global* with a setter.** Any future calibration job that calls `set_ml_percentile_bands` makes the equivalence test snapshot stale. I left this as-is because rewriting calibration is out of scope, but flagged the divergence-risk in the test docstring.

---

## What I need from you to proceed

1. **Approve P0 to merge** — or push back on any of the open questions above.
2. **Review the golden labels** in `tests/fixtures/historical_misses.json`. Specifically blessed labels for the IMRN/LNKS entries and a call on Q-A.
3. **Decision on Q-B** (ML amplify formula centralization).
4. **Decision on Q-E** (pytest version pin).
5. **Confirm:** I should still ask before opening Priority 2a, per your prior instruction.

---

## How to run

```powershell
# Full suite
.\scripts\test.ps1

# Just regression
.\scripts\test.ps1 -m regression

# Full CI placeholder (py_compile + pytest)
.\scripts\ci_check.ps1
```

Bash equivalents at `scripts/test.sh` and `scripts/ci_check.sh`.
