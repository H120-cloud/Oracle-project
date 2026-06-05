# Oracle Scraper Health Dashboard

## What Changed

Oracle now exposes live scraper diagnostics through:

- Backend: `GET /api/v1/news-momentum/source-health`
- Frontend: `News Feed -> Scraper Health`

This is read-only observability. It does not change alert scoring, Telegram gating, Pre-News scoring, Rocket shadow scoring, or production alert behavior.

## Metrics

Per source, the dashboard reports:

- `headlines_fetched`: total headlines successfully parsed from the source.
- `tickered_headline_count`: fetched headlines that contained at least one usable ticker.
- `untickered_headline_count`: fetched headlines dropped because no usable ticker was extracted.
- `dropped_headline_count`: headlines dropped before News Momentum because they had no usable ticker or were stale.
- `missing_timestamp_count`: ticker-bearing headlines dropped because no publish time could be parsed.
- `parse_error_count`: fetch/parser failures recorded for the source.
- `last_successful_parse_time`: latest successful parse with at least one headline.
- `last_successful_parse_age_seconds`: how long since the source last parsed successfully.
- `avg_latency_seconds`: average delay between `published_at` and scanner detection.
- `max_latency_seconds`: worst observed delay.
- `warnings`: recent source-health warnings.

## Status Values

- `ok`: source is parsing normally.
- `warning`: high missing timestamp rate or recent warning.
- `stale`: source has not produced a successful parse inside the stale window.
- `error`: parser errors have reached the configured threshold.

## How To Use It

Check the panel when Oracle feels quiet or when a stock appears late:

1. If `parse_error_count` rises, the source parser or network path is failing.
2. If `missing_timestamp_count` rises, old news may be dropped because freshness cannot be trusted.
3. If `dropped_headline_count` rises unusually, ticker extraction may be failing for that source.
4. If `avg_latency_seconds` or `max_latency_seconds` jumps, the source is delivering delayed headlines or Oracle is detecting them late.
5. If status is `stale`, the source is no longer producing successful parses.

## Operational Note

The scanner already sends admin Telegram warnings for source-health problems. The dashboard is the visual audit trail so you can inspect whether missed alerts are caused by scraping, timestamp parsing, ticker extraction, or downstream classification/gating.
