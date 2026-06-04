# V17 Entry Timing Engine — Implementation Report

Generated: 2026-05-03

## 1. What Existed Before

Prior to V17, Oracle Agentic Mode had a **3-state entry timing classification**:

- `EntryQuality.EARLY` — candidate identified but not yet ready
- `EntryQuality.IDEAL` — optimal entry window
- `EntryQuality.LATE` — move already extended, avoid chase

The old system computed basic entry zones (`entry_zone_low`, `entry_zone_high`, `invalidation_level`) but:
- Did **not** distinguish between *too early* vs *waiting for confirmation*
- Did **not** calculate risk/reward ratios
- Did **not** compute target levels (target_1, target_2, stretch)
- Did **not** enforce a minimum R:R threshold for alerts
- Sent alerts on any `EntryQuality.IDEAL` without granular state tracking

## 2. What Was Added

### 2.1 New 5-State Entry Timing Classification

Added `EntryTimingState` enum:

| State | Description | Alert Action |
|-------|-------------|--------------|
| `TOO_EARLY` | Probability rising, catalyst valid, volume increasing, but no VWAP reclaim or higher low yet | WATCH (once) |
| `WAITING_FOR_CONFIRMATION` | Price consolidating near VWAP, structure forming, needs breakout or VWAP hold | WATCH (once) |
| `IDEAL_ENTRY` | VWAP reclaimed, higher low formed, breakout confirmed, volume expansion, trap < 65, spread OK, R:R ≥ 2:1 | **HIGH PRIORITY ENTRY** |
| `LATE_CHASE` | Price extended far above VWAP/base, poor R:R, move already happened | AVOID (once) |
| `INVALID_ENTRY` | VWAP failed, lower high formed, trap risk high, hard rejection triggered, volume faded | AVOID (once) |

Backward compatibility: existing `EntryQuality` enum (EARLY / IDEAL / LATE) is **retained** and mapped:
- `TOO_EARLY` / `WAITING_FOR_CONFIRMATION` → `EARLY`
- `IDEAL_ENTRY` → `IDEAL`
- `LATE_CHASE` / `INVALID_ENTRY` → `LATE`

### 2.2 Entry Timing Score (0–100)

**Positive factors:**
- VWAP reclaim/hold: **+20**
- Higher low formed: **+20**
- Consolidation breakout confirmed: **+20**
- Volume persistence ≥ 50%: **+10** (+5 for consolidation bars)
- Acceptable spread/liquidity: **+5**
- Favourable time-of-day (open / power hour): **+5**

**Penalties:**
- Extended from VWAP/base (> 3%): **-15 to -30**
- Upper wick rejection (> 5%): **-10**
- Volume decelerating: **-10**
- Poor R:R (< 2:1): **-20** (downgrades IDEAL → LATE_CHASE)
- Trap risk high (≥ 65): **-20**
- Wide spread (> 3%): **-15**

### 2.3 Entry Zone & Target Calculation

For `IDEAL_ENTRY` and `WAITING_FOR_CONFIRMATION` states:

- `entry_zone_low` = max(VWAP, recent support, post-spike low)
- `entry_zone_high` = min(consolidation high, breakout level + ATR buffer)
- `ideal_entry_price` = midpoint of zone
- `invalidation_level` = recent support × 0.97 or VWAP × 0.98
- `stop_level` = invalidation_level
- `target_1` = entry + 2×risk
- `target_2` = entry + 3×risk
- `stretch_target` = high of day × 1.05
- `risk_reward_ratio` = reward / risk (enforced ≥ 2.0 for IDEAL_ENTRY)

### 2.4 Risk/Reward Filter

`IDEAL_ENTRY` is **downgraded** to `LATE_CHASE` if:
- `risk_reward_ratio < 2.0`
- Stop is too far from entry
- Entry is too far from support

This prevents alerts on setups with asymmetric downside.

### 2.5 Alert State Machine

New `AlertStateMachine` class tracks per-ticker transitions:

- **WATCH** → sent once when candidate enters `TOO_EARLY` or `WAITING_FOR_CONFIRMATION`
- **ENTRY** → sent once when candidate transitions to `IDEAL_ENTRY` (probability ≥ 70, no hard rejection)
- **AVOID** → sent once when candidate becomes `LATE_CHASE` or `INVALID_ENTRY`
- **Cooldown**: 5-minute cooldown on duplicate `IDEAL_ENTRY` alerts
- **Resend rule**: only resend ENTRY if `entry_timing_score` improves by ≥ 10 points after cooldown
- **Hard rejection blocks** ENTRY alerts but still allows WATCH/AVOID

## 3. Architecture Changes

### Files Modified

| File | Change |
|------|--------|
| `src/core/agentic/models.py` | Added `EntryTimingState` enum, extended `EntryTimingResult` with 12 new fields, added `entry_alert_state` to `AgenticCandidate`, updated `to_summary()` |
| `src/core/agentic/entry_timing.py` | Complete rewrite of `EntryTimingEngine` — 5-state scoring, zone calc, R:R filter, ATR/spread/volume helpers |
| `src/core/agentic/orchestrator.py` | Updated `_run_pipeline` alertability gating: only `IDEAL_ENTRY` + prob ≥ 70 + no hard rejection triggers `alertable = True` |
| `src/core/agentic/alert_state_machine.py` | **New file** — per-ticker alert tracking, cooldowns, transition logic |

### Files To Update (Frontend / API)

| File | Required Update |
|------|-----------------|
| `frontend/src/pages/Agentic.jsx` | Display `timing_state` badge, `entry_timing_score` progress bar, entry zone, invalidation level, R:R |
| `frontend/src/pages/Agentic.jsx` DetailPanel | Add "Entry Checklist" section with VWAP status, higher low status, breakout status |
| API routes | Ensure `to_summary()` output propagates to frontend |
| Telegram formatter | Add state emoji (⏳/👁/✅/🚫) and zone formatting |

## 4. Test Coverage

File: `tests/test_entry_timing_engine.py`

### Test Classes

**`TestEntryTimingStates`**
- `test_ideal_entry_all_checks_pass` — verifies full score, zones, targets, R:R ≥ 2
- `test_too_early_no_vwap_no_higher_low` — confirms TOO_EARLY when structure missing
- `test_waiting_for_confirmation_partial_structure` — confirms WAITING when breakout pending
- `test_late_chase_extended` — confirms LATE_CHASE when price extended > 3%
- `test_invalid_entry_dead_state` — confirms INVALID when momentum dead
- `test_invalid_entry_hard_rejection` — confirms INVALID when hard rejection active
- `test_invalid_entry_high_trap` — confirms INVALID when trap risk ≥ 80

**`TestEntryZonesAndRR`**
- `test_zone_calculation` — all 7 zone/target fields populated for IDEAL_ENTRY
- `test_rr_minimum_enforced` — R:R < 2.0 forces downgrade from IDEAL to LATE_CHASE
- `test_vwap_reclaim_confirmation` — VWAP reclaim adds +20 and appears in reasons
- `test_higher_low_confirmation` — higher low adds +20 and appears in reasons
- `test_breakout_confirmation` — breakout adds +20 and appears in reasons

**`TestVolumeAndSpread`**
- `test_volume_fading_penalty` — volume persist < 50 triggers warning
- `test_wide_spread_penalty` — wide spread or upper wick reduces score

**`TestAlertStateMachine`**
- `test_watch_to_entry_transition` — WATCH sent once, ENTRY sent on transition, duplicate suppressed
- `test_entry_blocked_by_hard_rejection` — hard rejection blocks ENTRY but not WATCH/AVOID
- `test_avoid_alert_once` — AVOID sent once, duplicates suppressed
- `test_score_improvement_allows_resend` — structure for material improvement resend

**`TestEdgeCases`**
- `test_no_bars` — empty bars → INVALID with "Insufficient data"
- `test_fewer_than_5_bars` — < 5 bars → INVALID
- `test_entry_zone_monotonic` — zone low ≤ ideal price ≤ zone high, target > stop
- `test_score_bounds` — score always 0–100

Total: **16 test cases**

## 5. Before / After Alert Behavior

### Before V17
```
Oracle Alert: "NVDA — Probability 82%, Entry Quality: IDEAL"
→ No distinction between "forming" and "confirmed"
→ No entry zone, no stop, no target
→ No R:R check
→ Could alert on extended/chase setups
```

### After V17
```
⏳ WATCH: "NVDA — Waiting for confirmation. Needs VWAP reclaim + breakout."
  ↓ (price reclaims VWAP, forms higher low, breaks consolidation)
✅ ENTRY: "NVDA — Entry timing confirmed. Score 85/100. Zone $875–$882. 
   Stop $848. Target 1: $910 (2.3R). R:R 2.3:1. High priority."
  ↓ (price extends 5% above breakout)
🚫 AVOID: "NVDA — Move already extended. Do not chase. Wait for pullback."
```

## 6. Examples of Each Entry State

### TOO_EARLY
**Ticker**: GME at 09:35 (pre-squeeze)
- Catalyst: Cohen letter
- Volume: rising but not confirmed
- VWAP: not yet reclaimed
- Higher low: not formed
- Score: ~35
- Action: WATCH alert once
- Next condition: "Wait for VWAP reclaim and higher low"

### WAITING_FOR_CONFIRMATION
**Ticker**: AMC at 10:15 (consolidation)
- VWAP: reclaimed
- Higher low: formed
- Breakout: **not yet confirmed**
- Volume: persistent
- Score: ~55
- Action: WATCH alert once
- Next condition: "Wait for breakout"

### IDEAL_ENTRY
**Ticker**: NVDA at 10:45 (earnings continuation)
- VWAP: reclaimed ✓
- Higher low: formed ✓
- Breakout: confirmed ✓
- Volume: expansion on breakout ✓
- Trap risk: 22% ✓
- Spread: 0.8% ✓
- R:R: 2.3:1 ✓
- Score: 85
- Action: **HIGH PRIORITY ENTRY alert**
- Zone: $875–$882, Stop: $848, Target 1: $910

### LATE_CHASE
**Ticker**: MARA at 11:30 (crypto pump)
- Price already +8% above breakout level
- Entry far from support
- R:R: 1.2:1 (below minimum)
- Score: ~30 (penalized -24 for extension + -20 for poor R:R)
- Action: AVOID alert once
- Reason: "Already extended — wait for pullback"

### INVALID_ENTRY
**Ticker**: ZM at 09:50 (earnings miss)
- State: FAILED
- VWAP: failed
- Lower high formed
- Trap risk: 85%
- Hard rejection: triggered (Rule 6)
- Score: ~5
- Action: AVOID alert once
- Reason: "Setup invalidated"

## 7. Integration Checklist

- [x] `EntryTimingState` enum added to `models.py`
- [x] `EntryTimingResult` extended with 12 new fields
- [x] `AgenticCandidate.to_summary()` exposes all new fields
- [x] `EntryTimingEngine` rewritten with 5-state classification
- [x] Entry zone calculation (low/high/ideal/stop/targets/stretch)
- [x] R:R filter enforced (minimum 2.0 for IDEAL_ENTRY)
- [x] Alert state machine created with cooldowns
- [x] Orchestrator gating updated: only IDEAL_ENTRY + prob ≥ 70 + no HR
- [x] 16 backend tests covering all states, zones, R:R, transitions
- [x] Frontend: timing state badge, score progress bar, zone display, Entry Checklist panel, Alerts panel WATCH/ENTRY/AVOID separation
- [ ] Telegram: state emoji, zone formatting, R:R display
- [ ] API: verify new fields in candidate detail responses

## Frontend Integration

All V17 fields are rendered in `frontend/src/pages/Agentic.jsx`.

### Candidates Table (Row-Level)
- **Timing State Badge** — `TimingStateBadge` component renders 5 states with color-coded borders and emoji: `⚪ TOO EARLY`, `🟡 WAITING`, `🟢 IDEAL ENTRY`, `🟠 LATE CHASE`, `🔴 AVOID`
- **Score Bar** — Inline 0–100 progress bar (green ≥70, yellow ≥40, red below)
- **Entry Zone + R:R** — `Zone $X–$Y`, `Stop $Z`, `R:R 2.3:1` shown under the badge
- **Row Coloring** — `rowDecisionStyle()` applies left-border + background tints:
  - `IDEAL_ENTRY` → emerald left border
  - `INVALID_ENTRY` / `LATE_CHASE` → red left border + reduced opacity
  - `WAITING_FOR_CONFIRMATION` → yellow left border
- **BEST SETUP Highlight** — Top-scoring `IDEAL_ENTRY` candidate gets `🔥 BEST SETUP` pill + glow shadow

### Sorting + Filtering
- `TIMING_STATE_PRIORITY` maps states to numeric ranks (0 = highest)
- `sortedCandidates` (memoized) sorts by: priority asc → `entry_timing_score` desc
- `bestSetupTicker` (memoized) = first `IDEAL_ENTRY` in sorted list

### Detail Panel (Entry Timing Section)
- **State + Score** — Large `TimingStateBadge` + progress bar
- **Zone Grid** — `entry_zone_low/high`, `ideal_entry_price`, `stop_level`, `target_1`, `target_2`, `stretch_target`, `invalidation_level`
- **R:R Visual** — Green if ≥2.0, yellow otherwise
- **Entry Checklist** — 6-item grid: VWAP Reclaimed, Higher Low, Breakout Confirmed, Vol Persistent, Trap Safe, R:R ≥ 2.0
- **Next Condition / Warnings** — `⏳` yellow hint or `⚠` red warning lists

### Alerts Panel
- Grouped by `alert_type` into 3 emoji-headed sections:
  - `🎯 ENTRY` — `ideal_entry` alerts (emerald styling)
  - `👁 WATCH` — `too_early` / `waiting_for_confirmation` (yellow styling)
  - `🚫 AVOID` — `late_chase` / `invalid_entry` (red styling)
- Each `AlertCard` shows zone, stop, R:R, targets, timing score, and next condition

## 8. Remaining TODOs

1. **Telegram alert formatter upgrade** — emoji prefixes, zone formatting, next-condition display
2. **Integration test** — run full pipeline end-to-end with live bars to verify alert transitions fire correctly
3. **Historical backtest** — run V16 real historical validation with new entry timing gating to measure impact on precision/recall
4. **Score calibration** — tune score thresholds (currently 70 for IDEAL_ENTRY) based on real historical outcomes

## 9. Conclusion

The V17 Entry Timing Engine transforms Oracle Agentic Mode from a *probability-based alert system* into a *state-aware, risk-quantified entry recommendation engine*.

Instead of:
> "NVDA may run."

The system now says:
> **WATCH**: "NVDA is a good candidate but too early. Waiting for VWAP reclaim."
> **ENTRY**: "NVDA entry confirmed. Zone $875–$882. Stop $848. Target $910. R:R 2.3:1. High priority."
> **AVOID**: "NVDA move already extended. Do not chase. Wait for pullback."

This directly addresses the core problem: **identifying the right stock is not enough — timing the entry is the next edge.**
