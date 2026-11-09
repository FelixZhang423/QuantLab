# Single Factor Generator

The PPO engine consumes train/valid/test memmaps derived from immutable company ClickHouse Parquet snapshots. CSV preprocessing and local stock-pool selection commands have been removed. Create pools and snapshots through the backend Web/API/CLI.

## Recommended flow

```text
ClickHouse -> immutable Parquet snapshot -> train/valid/test memmaps -> masked PPO
```

Use the backend `generate-factors` command for the complete workflow. It binds the snapshot identity to the factor runtime and results. The package imports backend expression helpers, so the repository and backend must be available on `PYTHONPATH`.

For low-level materialization, set `processed_dir` to an existing snapshot directory containing `panel.parquet`, set the feature fields and split dates in a runtime JSON, then run:

```powershell
python -m single_factor.cli materialize-splits --config single_factor/runtime.json
python -m single_factor.cli run --config single_factor/runtime.json
```

`runtime.json` is a template: replace `REPLACE_WITH_SNAPSHOT_ID` with the snapshot ID produced by the backend. It does not contain bundled market data. `pool_codes` can restrict the snapshot universe; null keeps all codes. Cache windows must include rolling lookback and forward-target periods. Memmaps contain per-field `.npy`, `dates.npy`, `codes.json`, `feature_index.json` and `manifest.json`.

The runner saves candidate/rejected records and checkpoints. Restarting with the same compatible runtime reuses them. `run_server.ps1` launches only training on prepared memmaps and adds the backend to `PYTHONPATH`; it never queries raw CSV. For production supervision, provide the generated runtime configuration and output directory explicitly.

## Holdout evaluation

PPO uses train/valid only and writes `candidate_factors.jsonl`. After the generation finishes and freezes, run backend `confirm-factors` (or the Web confirmation task) to evaluate test once. All outcomes are journaled; only confirmed candidates enter `confirmed_factors.jsonl`, which is the sole source for platform factor backtests and composition. Test metrics never enter PPO reward. See backend/docs/factor_confirmation.md for thresholds, same-sign checks, actual-session split isolation and recovery rules.
