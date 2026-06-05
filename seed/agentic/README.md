# Baseline seed artifacts (`seed/agentic/`)

Files placed here are **copied into `AGENTIC_DATA_DIR` at startup only when the
target file does not already exist** (see `seed_agentic_data_dir()` in
`src/utils/data_paths.py`). They give a fresh or restored Railway volume a warm
baseline so the system is not cold-started after a wipe. **Live state is never
overwritten.**

## What to put here

Drop a known-good copy of any of these (directory layout mirrors
`data/agentic/`):

- `news_momentum_ml_model.joblib` + `news_momentum_ml_meta.json` — alert ranker
- `news_momentum_big_winner_model.joblib` + `news_momentum_big_winner_meta.json`
- `news_momentum_nlp_model.joblib` + `news_momentum_nlp_meta.json`
- `rocket_catboost_baseline_shadow.joblib` — Rocket shadow scorer
- `company_name_ticker_map.json` — SEC name→ticker cache (avoids a cold-start
  SEC fetch and the coverage gap until it rebuilds)

Example:

```
seed/agentic/
  news_momentum_ml_model.joblib
  news_momentum_ml_meta.json
  company_name_ticker_map.json
```

## Notes

- These paths are re-included in `.gitignore` via `!seed/**`, so model/parquet
  artifacts here CAN be committed (the global `*.joblib`/`*.parquet` ignores do
  not apply under `seed/`).
- `.dockerignore` does not exclude `seed/`, so contents ship in the image.
- If you prefer **not** to bake artifacts into the image, leave this empty and
  instead restore the Railway volume from a backup — see
  `docs/railway_persistence_fix_report.md`.
