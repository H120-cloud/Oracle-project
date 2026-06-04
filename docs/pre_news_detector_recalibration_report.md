# Pre-News Detector Recalibration — Validation Report

**Status:** SHADOW / VALIDATION ONLY. No production behavior changed.
**Date:** 2026-05-29
**Reproduce:** `python scripts/prenews_recalibration_audit.py`

---

## TL;DR

The current alert gate `suspicion_score >= 75` fires on **6** of 144 resolved
detections, the **worst-performing** band (17% real-move). A type+safety gate
("V2") would fire on **128** at **68% real-move**. The signal is real, but the
**dataset is too small for statistical promotion** — the high-suspicion bands
have N<30. **Recommendation: shadow-test V2 in parallel; do not promote yet.**

---

## Phase 1 — Data Audit (verified from raw, not assumed)

| Item | Value |
|---|---|
| Source | `data/agentic/pre_news_outcomes.json` |
| Total records | 151 |
| Resolved (have MFE) | 144 |

**Field availability** (what the plan's metrics can actually use):

| Field | Populated |
|---|---|
| suspicion_score, anomaly_type, was_real_move, was_pump, entry_price | 100% |
| max_favorable_excursion_pct (MFE), peak_price | 95% |
| max_adverse_excursion_pct (MAE) | 94% (but median = 0.0% — see below) |
| news_appeared_minutes_after | 79% |
| **time_to_peak_minutes** | **0% (NOT populated)** |

**⚠ Data gaps that block parts of the plan (Phase 2):**
- **No windowed MFE/MAE** (60-min / same-session / 2-day) is stored — only a
  *single aggregate* `max_favorable_excursion_pct` / `max_adverse_excursion_pct`.
- **MAE is effectively empty** — median MAE is 0.0% across every band, so the
  field is present but not meaningfully recorded. Therefore the plan's risk
  metrics and `WIN_20 = MFE>=20 BEFORE MAE<=-10` (sequence-dependent) are
  **NOT computable**. We fall back to aggregate-MFE / `was_real_move` only.
- `time_to_peak_minutes` is 0% populated → no timing analysis possible.
- `MONSTER (>=100%)` within pre-news outcomes: **0** reach it (max in-window
  MFE ≈ 93%) — monsters are captured as *early entries*; the full multi-day
  run is not in this window.

## Phase 1 — Suspicion-band re-derivation (Wilson 95% CI) — VERIFIED

Re-derived from raw via `scripts/prenews_recalibration_audit.py`:

| band | n | win% | 95% CI | med MFE | +20% | +50% |
|---|---|---|---|---|---|---|
| 0-50 | **121** | 73% | [64-80] | 13.2% | 38% | 7% |
| 50-75 | 17 | 59% | [36-78] | 6.0% | 6% | 0% |
| 75-101 | **6** | 17% | [3-56] | 1.5% | 0% | 0% |

(MAE column dropped — median MAE ≈ 0% across all bands, not meaningfully
populated. "win%" = `was_real_move` rate. 50-75 & 75-101 are N<30 → unreliable;
their CIs ([36-78], [3-56]) are so wide they overlap the 0-50 band.)

**Statistical honesty:**
- The 0-50 band (N=121) is solid: 73% real-move, CI [64-80].
- The 50-75 (N=17) and 75-101 (N=6) bands are **below 30 — NOT RELIABLE.**
- The 75+ band's CI [4-48] is enormous; "17%" could plausibly be anywhere in
  that range. We can say there is **no evidence high suspicion helps**, but we
  **cannot** confidently claim it's *worse* on N=6.
- 84% of all detections sit in 0-50 → the score barely discriminates.

## Phase 6 — BASELINE vs V2

| Gate | n | real-move | 95% CI | med MFE | +20% | +50% |
|---|---|---|---|---|---|---|
| BASELINE (`suspicion>=75`) | 6 | 17% | [3-56] | 1.5% | 0% | 0 |
| V2 (anomaly-type + drop pump) | 128 | 68% | [59-75] | 10.3% | 30% | 8 |

V2 alerts on 21× more detections at dramatically higher real-move rate. Caveat:
BASELINE's N=6 makes the comparison directional, not conclusive.

## Phase 5 — Monster Analysis (news-path MFE>=100 cross-ref)

17 monster tickers (eventual move via the news path). Did pre-news see them early?

| ticker | eventual | pre-seen | susp | alert_q | BASELINE? | V2? |
|---|---|---|---|---|---|---|
| WGRX | +5000% | YES | 11 | **early** | no | **YES** |
| VCIG | +526% | YES | 20 | late | no | **YES** |
| QTEX | +430% | YES | 10 | trap_risk | no | **YES** |
| RGTI | +133% | YES | 52 | caution | no | **YES** |
| NAKA, BCTX, VSA, IPW, ARLYF, YMAT, IINN, KZIA, CIRX, WKEY, APLM, COMCF, URGN | +108–4644% | **never** | — | — | — | — |

**Detection: 4/17 (23%)** by pre-news; **0** by the news-path anomaly signal.

### WGRX case study (the headline finding)
The pre-news detector flagged WGRX at `suspicion=11`, `alert_quality=early` —
i.e. it caught the single biggest monster (+5000%) **early**. BASELINE silenced
it (11 < 75). V2 would have surfaced it. This is the strongest single piece of
evidence for V2 — but it is **one event**, not a distribution.

## Phase 7 — Alert Volume (estimate)

Over the ~7-day resolved window: BASELINE ≈ 6 alerts; V2 ≈ 128 → **~18/day vs
<1/day**. Operationally meaningful; needs live confirmation (the resolved set
under-counts total detections).

## Phases 3/8 — Shadow Mode & Promotion (NOT done — requires forward run)

Historical replay alone is insufficient (small N, no windowed outcomes,
selection bias: these are only detections the system chose to track). Per the
plan's own guardrail:

**Promotion blocked until EITHER:**
1. ≥30 days parallel shadow logging of BASELINE vs V2 decisions + outcomes, OR
2. A larger historical replay with windowed MFE/MAE captured at detection time.

## Recommendation

1. **Do NOT promote V2 to production yet.** The direction is strongly favorable
   (WGRX early catch, 0-50 band 73% on N=121) but the decisive cells (high-
   suspicion bands, BASELINE) are N<30.
2. **Build the shadow logger**: at every detection, record BOTH gate decisions
   and capture windowed MFE/MAE forward (60m/session/2d) so the next analysis
   has the metrics this one couldn't compute.
3. **Reassess after ~30 days** (or ~100+ resolved detections with windowed
   outcomes), then promote if V2 holds higher monster-capture without a
   precision collapse.

## Guardrails honored
- suspicion_score treated as a hypothesis, not inverted automatically.
- No claim that "low is better / high is worse" beyond what CIs support.
- All N<30 cells explicitly flagged as unreliable.
