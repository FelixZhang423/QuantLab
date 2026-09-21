# Single Factor Generator

This package is independent from the original combination-oriented AlphaGen scripts. It preprocesses the large custom daily CSV once, creates a configurable stock pool, and evaluates each generated expression as a single factor.

## Recommended flow

```text
raw CSV
  -> preprocess to Parquet
  -> materialize selected stocks and fields to NumPy memmaps
  -> run masked PPO
  -> save accepted/rejected factor records
```

The raw file is `F:\my_code_file\因子构建\数据\daily_with_maindata_v2.csv`. Do not scan it once per candidate factor.

## Configuration example

```json
{
  "source_csv": "F:/my_code_file/因子构建/数据/daily_with_maindata_v2.csv",
  "processed_dir": "out/single_factor/processed",
  "cache_dir": "out/single_factor/cache",
  "fields": ["close", "volume", "amount", "ma5", "ma20", "macd"],
  "point_in_time_fields": [],
  "cache_start": "2020-07-01",
  "cache_end": "2025-12-31",
  "max_backtrack_days": 100,
  "target_horizon": 20,
  "max_future_days": 20,
  "target_factor_count": 50,
  "max_attempts": 100000,
  "output_dir": "out/single_factor/run",
  "rollout_timesteps": 2048,
  "seed": 0,
  "device": "cpu",
  "quality": {
    "min_coverage": 0.8,
    "min_train_ic": 0.03,
    "min_valid_ic": 0.02,
    "min_icir": 0.2
  }
}
```

Before production use, add a point-in-time industry mapping and configure the stock-pool filter. `ListedSector` is not automatically treated as industry.

## Commands

```powershell
python -m single_factor.cli preprocess --config single_factor_config.json
python -m single_factor.cli materialize --config single_factor_config.json
python -m single_factor.cli materialize-splits --config single_factor_runtime_500_liquid.json
python -m single_factor.cli inspect-pool --config single_factor_config.json
python -m single_factor.cli run --config single_factor_config.json
```

To filter during the one-time raw-file scan, put one normalized stock code per
line in a text file and set `preprocess_codes_file` in the config. This keeps
only those stocks in `panel.parquet`; `materialize` can still apply a second,
date-range-specific pool filter later.

The preprocessing output contains `panel.parquet` and `metadata.json`. The later panel cache contains one `.npy` memmap per field, `dates.npy`, `codes.json`, `feature_index.json`, and `manifest.json`.

The runtime config keeps train, validation, and test caches separate. Build them
once with `materialize-splits`; after that, `run` can be restarted with the same
output directory because `run_state.json` and PPO checkpoints are reused.

For the current 500-stock pool:

```powershell
python -m single_factor.cli materialize-splits --config single_factor_runtime_500_liquid.json
python -m single_factor.cli run --config single_factor_runtime_500_liquid.json
```

For automatic restart after a server interruption, run from PowerShell:

```powershell
.un_single_factor_server.ps1
```

The script writes timestamped logs under the run output directory and reuses
the same `run_state.json` and checkpoint files after a restart.

## Portable Bundle

The whole `single_factor` directory is now self-contained for deployment. It
contains the selected Parquet panel, train/valid/test caches, stock-code list,
runtime config, vendored AlphaGen expression/PPO primitives, and the launcher.
The original 19.8 GB raw CSV is not required for `run`; it is only needed if
the data is rebuilt from scratch.

From the directory that contains `single_factor`:

```powershell
python -m single_factor --help
python -m single_factor.cli run --config single_factor/runtime.json
powershell -ExecutionPolicy Bypass -File .\single_factor\run_server.ps1
```

To rebuild the three caches from the bundled Parquet panel:

```powershell
python -m single_factor.cli materialize-splits --config single_factor/runtime.json
```

`cache_start` must include at least 100 trading days before the formal training start so rolling expressions such as `Mean(close,20)` can be evaluated at the boundary. `cache_end` must include the target horizon after the final evaluation date.

The runner writes `accepted_factors.jsonl`, `rejected_candidates.jsonl`, `expression_index.json`, `run_state.json`, and PPO checkpoints. It stops at the target count or the maximum attempt count and can be resumed from the same output directory.

For a server, install the existing project requirements plus `pyarrow`, `gymnasium`, `stable-baselines3`, and `sb3-contrib`. Run the command under a process supervisor so a restart reuses `run_state.json` and the output directory.
