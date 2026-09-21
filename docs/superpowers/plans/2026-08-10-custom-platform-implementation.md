# Unified Custom Factor Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `custom_backtester` the single platform that streams the 20GB source CSV into a reusable master cache, manages named stock pools, runs PPO factor generation on a selected pool, and backtests only accepted factors from that same pool.

**Architecture:** Keep the existing `custom_bt` backtest engine and Streamlit app as the platform shell. Reuse the tested `single_factor` PPO/AlphaGen implementation through a focused adapter instead of rewriting the RL engine. Use immutable pool manifests and data signatures to bind generation and backtest to identical stock-universe data.

**Tech Stack:** Python 3.11, pandas, PyArrow, Parquet, NumPy memmap, PyTorch, Gymnasium, Stable-Baselines3, Streamlit, unittest/pytest.

---

## File map

- Modify `custom_backtester/custom_bt/data.py`: preserve metadata types and add streaming master-cache and pool-panel readers.
- Create `custom_backtester/custom_bt/pools.py`: create/load named stock pools from the master cache.
- Create `custom_backtester/custom_bt/factor_adapter.py`: translate and validate AlphaGen expressions for the pandas evaluator.
- Create `custom_backtester/custom_bt/factor_generation.py`: export selected-pool panels, build train/valid/test caches, and invoke the existing PPO runner.
- Create `custom_backtester/custom_bt/factor_backtest.py`: load accepted factor records and run pool-bound batch backtests.
- Modify `custom_backtester/custom_bt/cli.py`: add `prepare-master`, `create-pool`, `generate-factors`, and `backtest-factors` commands.
- Modify `single_factor/storage.py` and `single_factor/runner.py`: attach pool/runtime metadata to generated factor records without changing existing callers.
- Create `custom_backtester/tests/test_pools.py`, `test_factor_adapter.py`, `test_factor_generation.py`, and `test_factor_backtest.py`.
- Modify `custom_backtester/tests/test_data_store.py` for metadata preservation and master-cache behavior.
- Modify `custom_backtester/app/streamlit_app.py`: add pool, factor-run, accepted-factor, and batch-result views after CLI/core APIs are stable.
- Add `custom_backtester/configs/platform.yaml` and `custom_backtester/configs/factor_generation.yaml` with safe small-pool defaults.

### Task 1: Preserve source metadata and add the master-cache API

**Files:**
- Modify: `custom_backtester/custom_bt/data.py`
- Test: `custom_backtester/tests/test_data_store.py`

- [ ] Write a failing test proving `prepare_chunk` keeps `category`, `ListedDate`, and `ListedSector` usable while numeric fields remain numeric:

```python
def test_prepare_chunk_preserves_pool_metadata_types(self):
    chunk = pd.DataFrame({
        "code": ["1"], "timestamps": ["2024-01-02"],
        "open": [10.0], "close": [11.0], "high": [12.0], "low": [9.0],
        "vol": [1000.0], "amount": [10000.0], "Ifsuspend": [0],
        "category": ["stock"], "ListedDate": ["1991-04-03"],
        "ListedSector": ["main"],
    })
    out = prepare_chunk(chunk)
    self.assertEqual(out.loc[0, "category"], "stock")
    self.assertEqual(pd.Timestamp(out.loc[0, "ListedDate"]), pd.Timestamp("1991-04-03"))
    self.assertEqual(out.loc[0, "ListedSector"], "main")
    self.assertEqual(float(out.loc[0, "close"]), 11.0)
```

- [ ] Run `pytest tests/test_data_store.py::DataStoreTests::test_prepare_chunk_preserves_pool_metadata_types -q` from `custom_backtester`; confirm it fails because metadata is currently coerced to numeric.
- [ ] Add explicit metadata/date column sets and convert only numeric columns in `prepare_chunk`; keep the existing `date`, `code`, `volume`, and `vwap` normalization.
- [ ] Add `build_master_store(csv_path, store_dir, fields, chunksize=200_000, limit_rows=None, overwrite=False)` that streams only `CORE_COLUMNS`, pool metadata, and requested factor fields into per-stock Parquet files and writes `meta.json` with source signature and selected fields.
- [ ] Add `load_store_codes(store_dir)` and `load_pool_panel(store_dir, codes, start_date=None, end_date=None, columns=None)`; read files one stock at a time and concatenate only the selected pool.
- [ ] Run the focused test and the existing `pytest tests/test_data_store.py -q`; expected result is all tests passing.

### Task 2: Add named stock-pool creation

**Files:**
- Create: `custom_backtester/custom_bt/pools.py`
- Create: `custom_backtester/tests/test_pools.py`

- [ ] Write failing tests for a 2-stock liquidity pool, a minimum-listed-days filter, and a pool manifest that records the source signature and exact codes.
- [ ] Run `pytest tests/test_pools.py -q`; confirm failure because `custom_bt.pools` does not exist.
- [ ] Implement `create_pool(store_dir, pools_root, name, selection_start, selection_end, top_n=None, min_listed_days=0, min_coverage=0.0, exclude_suspended=True, category=None, market_code=None, codes=None)`.
- [ ] Iterate per-stock Parquet files instead of calling `load_store` on the full universe; aggregate valid-row counts and average `amount` inside the selection window, then sort by `average_amount` descending and code ascending.
- [ ] Write `codes.txt`, `selection_summary.csv`, and a JSON manifest containing a deterministic `pool_id`, source signature, filters, selected count, and selected codes.
- [ ] Implement `load_pool_manifest(pools_root, pool_id)` and `load_pool_codes(pools_root, pool_id)` with clear errors for missing or inconsistent files.
- [ ] Run the new tests and existing data tests; expected result is green.

### Task 3: Make generated factor records pool-aware

**Files:**
- Modify: `single_factor/storage.py`
- Modify: `single_factor/runner.py`
- Create: `custom_backtester/tests/test_factor_storage_metadata.py`

- [ ] Write a failing test that constructs `FactorStorage(root, metadata={"pool_id": "pool_a"})`, records a `SingleFactorMetrics`, and asserts the JSONL row includes `pool_id`.
- [ ] Run the focused test and confirm the optional metadata API is missing.
- [ ] Add an optional `metadata: Optional[Dict[str, Any]] = None` argument to `FactorStorage`; merge it into serialized records without changing deduplication by expression.
- [ ] Add an optional `storage_metadata` argument to `run_with_ppo` and pass it to `FactorStorage`.
- [ ] Run the focused test and all existing `single_factor` tests if available; expected result is green.

### Task 4: Implement AlphaGen-to-custom expression adaptation

**Files:**
- Create: `custom_backtester/custom_bt/factor_adapter.py`
- Create: `custom_backtester/tests/test_factor_adapter.py`

- [ ] Write failing tests for:

```python
assert translate_expression("Add(Ref($close,20d),$volume)") == "add(delay(close,20),volume)"
assert translate_expression("Mean($close,5d)") == "ts_mean(close,5)"
```

  and a test that rejects unknown fields/operators before evaluation.
- [ ] Run `pytest tests/test_factor_adapter.py -q`; confirm the module is missing.
- [ ] Implement a small recursive parser for identifiers, `$field` names, numeric constants, `Nd` time constants, commas, and nested calls; do not use Python `eval` for translation.
- [ ] Implement the operator map for the current AlphaGen set: arithmetic, `Ref`, rolling statistics, `Delta`, `Cov`, and `Corr`; map only to registered custom operators and raise `ExpressionAdapterError` when semantics are unavailable.
- [ ] Add `validate_backtest_expression(expr, panel)` that calls the existing AST validator/evaluator on a small panel without silently accepting missing fields.
- [ ] Run focused adapter tests and existing expression tests; expected result is green.

### Task 5: Add pool-bound factor-generation orchestration

**Files:**
- Create: `custom_backtester/custom_bt/factor_generation.py`
- Create: `custom_backtester/tests/test_factor_generation.py`

- [ ] Write failing tests for `prepare_factor_runtime` using a small master store: it must create `processed/panel.parquet`, train/valid/test memmap manifests, and a runtime manifest containing `pool_id`.
- [ ] Run `pytest tests/test_factor_generation.py -q`; confirm the API is missing.
- [ ] Implement `export_pool_panel(master_store, pool_codes, fields, output_path, start_date, end_date)` using per-stock reads and a Parquet writer so a 20GB CSV is never rescanned for each candidate factor.
- [ ] Implement `prepare_factor_runtime(...)` by calling the existing `single_factor.preprocess.materialize_memmap` for the exported pool panel and each configured split; include required lookback and target-horizon dates.
- [ ] Implement `run_factor_generation(...)` that imports the existing `single_factor` package from the workspace root, builds `PanelData`, `FeatureRegistry`, and `SingleFactorEvaluator`, then calls `run_with_ppo(..., storage_metadata=...)`.
- [ ] Save `runtime_manifest.json` and `factor_run.json` next to `accepted_factors.jsonl`, `rejected_candidates.jsonl`, and checkpoints; resume from the existing state file.
- [ ] In tests, use a deterministic fake runner only at the PPO boundary and exercise real panel export/runtime creation; run focused tests and existing single-factor tests.

### Task 6: Add accepted-factor batch backtesting

**Files:**
- Create: `custom_backtester/custom_bt/factor_backtest.py`
- Create: `custom_backtester/tests/test_factor_backtest.py`

- [ ] Write a failing test with a temporary pool and factor-run directory containing one accepted and one rejected JSONL row; assert only the accepted expression creates a result directory and summary row.
- [ ] Run `pytest tests/test_factor_backtest.py -q`; confirm the module is missing.
- [ ] Implement `backtest_accepted_factors(master_store, pools_root, factor_run_dir, outputs_root, backtest_config)`:
  - load and verify `pool_id` and source signature;
  - load only the pool panel for the backtest date range;
  - translate and validate each accepted expression;
  - call `combine_alphas`/`run_backtest` with one alpha at a time;
  - save per-factor outputs and `factor_backtest_summary.csv`;
  - record adapter or engine failures without aborting other factors.
- [ ] Run focused batch tests and existing backtest/job tests; expected result is green.

### Task 7: Integrate CLI commands and configuration

**Files:**
- Modify: `custom_backtester/custom_bt/cli.py`
- Create: `custom_backtester/configs/platform.yaml`
- Create: `custom_backtester/configs/factor_generation.yaml`
- Modify: `custom_backtester/tests/test_cli.py` or create it if absent

- [ ] Write failing parser tests asserting the four new commands and required arguments exist.
- [ ] Run the focused CLI tests and confirm the commands are absent.
- [ ] Add commands:

```text
prepare-master --config configs/platform.yaml
create-pool --config configs/pools/<name>.yaml
generate-factors --pool <pool_id> --config configs/factor_generation.yaml
backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml
```

- [ ] Make all relative paths resolve relative to the config file, not the current shell directory.
- [ ] Set the safe default generation pool to 500 stocks and the current runtime technical fields; expose `top_n`, split dates, target horizon, quality thresholds, and output roots in YAML.
- [ ] Run CLI parser tests and `python -m custom_bt.cli --help`; expected result is successful help output.

### Task 8: Add Streamlit platform controls and views

**Files:**
- Modify: `custom_backtester/app/streamlit_app.py`
- Modify: `custom_backtester/tests/test_streamlit_app.py`

- [x] Write a failing helper/UI test for loading pool manifests and factor-run summaries without requiring a live Streamlit server.
- [x] Run the focused test and confirm the helper is absent.
- [x] Add sidebar controls for master store, pool root, factor-run root, and output root.
- [x] Add sections for master-cache import, pool creation/status, factor-generation task submission, accepted-factor table, and batch-backtest summary download.
- [x] Keep the existing manual-expression backtest tab unchanged as a debugging path.
- [x] Run all Streamlit tests; expected result is green.

### Task 9: End-to-end smoke verification and safe cleanup

**Files:**
- Create: `custom_backtester/tests/test_platform_smoke.py`
- Modify: `custom_backtester/README.md`
- Modify: `custom_backtester/task_plan.md` or root `task_plan.md` as applicable

- [ ] Add a fixture-based smoke test covering source CSV -> master store -> pool -> runtime manifest -> accepted-factor batch backtest with a tiny deterministic dataset.
- [ ] Run the smoke test, all project tests, and `python -m compileall custom_bt`.
- [ ] Run a limited real-source import using `limit_rows` and inspect metadata types and fields.
- [ ] Run a 500-stock pool creation against the built master cache; do not launch the full PPO run until cache signatures and date ranges are correct.
- [ ] Run one real or bounded factor-generation task and one accepted-factor backtest; verify outputs contain matching `pool_id` and source signatures.
- [ ] Only after those checks pass, archive or remove the exact old targets `custom_backtester/data_cache/sample_store`, `custom_backtester/data_cache/stock_daily`, and `custom_backtester/data_cache/sample_200k.csv`; preserve source CSV, code, `outputs`, and factor runs.
- [ ] Update README with the new commands and the required “full master cache, selected pool for computation” workflow.

## Verification commands

Run from `F:\my_code_file\因子构建\生成因子＋回测系统\custom_backtester`:

```powershell
pytest -q
python -m compileall custom_bt
python -m custom_bt.cli --help
```

The final handoff must report the exact test command and result. Do not claim completion until the full suite and the bounded end-to-end smoke test pass.
