# FJET Delayed Alert Audit

## Finding

The FJET alert pattern was delayed because Oracle was seeing a secondary recap headline after the move, not the original company catalyst.

The original FJET catalyst was a BusinessWire / company IR release at 6:00 AM EDT on June 3, 2026:

`Starfighters Space (NYSE: FJET) Added to Membership of Russell 3000 Index`

The screenshot headline was retrospective:

`Russell 3000 inclusion announcement drives 16% FJET surge`

That wording means the move had already happened by the time the headline was emitted.

## Local Evidence

Local persisted records showed FJET candidates with a synthetic/recap-style headline:

`FJET+27.35%`

Those records were classified as:

- catalyst category: `unknown`
- catalyst subtype: `other`
- block reason: `impact_floor(42.4<45.0)`
- repeated shadow entries over several hours

This proves the local pipeline was not receiving a clean early primary catalyst for FJET. It was discovering the ticker through late price-action / ticker-page paths.

## Root Causes

1. Primary BusinessWire ingestion was not reliable enough.
   - A live read-only check of the configured BusinessWire RSS URL timed out.
   - If BusinessWire fails, the pipeline falls back to Finviz / StockTitan / recap headlines.

2. Source-health did not surface repeated parse/fetch errors strongly enough.
   - `record_parse_error()` increased a counter, but heartbeat `evaluate()` did not return parse-error warnings.
   - This means a primary source could quietly fail without an admin Telegram warning.

3. Recap headlines could still pass after the move.
   - Headlines such as `shares surge`, `stock jumps`, or `drives 16% FJET surge` describe a move that already happened.
   - The breakout override could convert that already-moved price action into a late alert.

## Fixes Applied

1. Added parse-error health warnings.
   - Repeated parser/fetch failures now appear in `SourceHealthTracker.evaluate()`.
   - This makes source outages visible in the existing Telegram source-health warning path.

2. Added a late reaction headline guard.
   - Recap headlines that explicitly report an already-happened move are blocked when the stock is already up at least 10%.
   - Block reason: `late_reaction_headline`.
   - This specifically prevents FJET-style after-the-surge alerts.

## What This Does Not Solve Alone

This prevents late recap alerts, but the early-alert side still depends on receiving the original source fast enough.

The next highest-impact source upgrade is to strengthen primary-wire ingestion for:

- BusinessWire
- company IR RSS feeds where available
- SEC 8-K exhibits when companies file the press release

## Verification

Added regression coverage:

- FJET-style recap headline is blocked as `late_reaction_headline`.
- Repeated BusinessWire parser errors surface from source-health evaluation.
