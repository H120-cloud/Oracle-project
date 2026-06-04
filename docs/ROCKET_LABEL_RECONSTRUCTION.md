# Historical Runner Reconstruction Engine

## Purpose

`src/core/agentic/rocket_label_reconstructor.py` increases historical runner
label coverage without fetching new bars and without changing production alert
or Telegram behavior.

The engine reads an existing Rocket CSV or Parquet export, copies the input
rows, and writes separate reconstructed exports:

- `data/agentic/rocket_training_dataset_reconstructed.csv`
- `data/agentic/rocket_training_dataset_reconstructed.parquet`
- `docs/rocket_label_reconstruction_report.md`

The original `rocket_training_dataset.csv` and
`rocket_training_dataset.parquet` files are not overwritten.

## Run

```powershell
python -m src.core.agentic.rocket_label_reconstructor `
  --input data\agentic\rocket_training_dataset.parquet `
  --include-provisional
```

Omit `--include-provisional` when the output should contain exact labels only.

## Output Columns

| Column | Purpose |
|---|---|
| `reconstructed_runner_tier` | Deterministic reconstructed label or `UNKNOWN` |
| `training_runner_tier` | Training-facing copy of the effective label |
| `label_source` | Existing, exact reconstruction, provisional reconstruction, or insufficient evidence |
| `label_confidence` | `HIGH`, `MEDIUM`, or `LOW` |
| `label_reason_code` | Stable rule outcome code |
| `label_reason` | Human-readable explanation |
| `label_provenance` | JSON with source columns, values, rule ID, audit reference, and reconstruction version |
| `label_reconstruction_version` | `rocket_labels_v1_no_fetch` |

The original `runner_tier` column remains unchanged.

## Historical Field Aliases

The engine accepts equivalent historical fields for each audited window:

| Window | Accepted Fields |
|---|---|
| Next day | `return_next_day_high_pct`, `next_day_high_pct`, `mfe_1d` |
| Two day | `return_two_day_high_pct`, `two_day_high_pct`, `mfe_2d` |
| Five day | `return_five_day_high_pct`, `five_day_high_pct`, `mfe_5d` |

If aliases for the same window contain conflicting values, the row remains
`UNKNOWN`. The engine does not silently choose one.

The audit also identified aggregate `mfe_pct` and `mae_pct` fields. They are
inspected as available historical evidence but are intentionally not used to
assign exact tiers: `mfe_pct` does not encode a specific audited time window,
and `mae_pct` does not prove a runner threshold. They remain available in the
output for later diagnostics.

## Exact Rules

Exact reconstruction requires complete next-day, two-day, and five-day
windows. Highest-tier precedence applies:

| Rule ID | Label | Rule |
|---|---|---|
| `RLR_EXACT_LEGENDARY_V1` | `LEGENDARY_RUNNER` | Five-day move >= 300% |
| `RLR_EXACT_MONSTER_V1` | `MONSTER_RUNNER` | Five-day move >= 100% |
| `RLR_EXACT_MAJOR_V1` | `MAJOR_RUNNER` | Two-day move >= 30% |
| `RLR_EXACT_STANDARD_V1` | `STANDARD_WIN` | Next-day move >= 10% |
| `RLR_EXACT_NON_RUNNER_V1` | `NON_RUNNER` | Complete windows and no threshold reached |

Trusted existing runner tiers are preserved with
`RLR_EXISTING_TRUSTED_V1`.

## Provisional Rules

Partial windows cannot prove an exact final tier because a later missing
window may promote the row. With `--include-provisional`, observed threshold
hits receive separate lower-bound labels:

| Rule ID | Label | Rule |
|---|---|---|
| `RLR_PROVISIONAL_MONSTER_V1` | `PROVISIONAL_MONSTER_RUNNER` | Observed five-day move >= 100% |
| `RLR_PROVISIONAL_MAJOR_V1` | `PROVISIONAL_MAJOR_RUNNER` | Observed two-day move >= 30% |
| `RLR_PROVISIONAL_STANDARD_V1` | `PROVISIONAL_STANDARD_WIN` | Observed next-day move >= 10% |

Provisional labels use `MEDIUM` confidence and must remain separate from exact
training labels.

## Limitations

- `drawdown_quality` is not reconstructed. Aggregate return fields do not
  preserve the price path required to distinguish clean runners, dirty
  runners, and traps.
- Partial rows below observed thresholds remain `UNKNOWN`; they cannot be
  assigned `NON_RUNNER`.
- The engine does not fetch external data, import market-data clients, train
  models, or modify production alert logic.

## Next Step

Repair forward-pricing enrichment for rows that remain `UNKNOWN`, persist
path-preserving data for drawdown labels, rerun the coverage audit, and only
then evaluate whether ML training has enough label coverage.
