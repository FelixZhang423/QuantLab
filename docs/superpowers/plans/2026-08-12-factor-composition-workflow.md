# Factor Composition Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate AlphaGen-style factor-composition workflow that consumes accepted single factors, applies a mutual-IC gate, optimizes deterministic weights, backtests each requested pool size, and stores every composite result in the unified saved-result center.

**Architecture:** A new `custom_bt.factor_composition` module owns candidate loading, cross-sectional normalization, mutual-IC filtering, deterministic MSE/L1 weight optimization, composite expression construction, and composite backtesting. The existing platform job dispatcher calls this module, the CLI exposes `compose-factors`, and Streamlit adds a dedicated composition tab while reusing `save_result`/`list_runs`.

**Tech Stack:** Python 3.11+, pandas, NumPy, existing expression evaluator, existing backtest engine, Streamlit, unittest/pytest.

---

### Task 1: Lock the composition contract with failing tests

**Files:**
- Create: `custom_backtester/tests/test_factor_composition.py`
- Create: `custom_backtester/custom_bt/factor_composition.py` (only the importable public names needed by the tests)

- [x] **Step 1: Write tests for deterministic candidate filtering, mutual-IC rejection, non-random weights, and sweep output.**

  The tests will construct a small in-memory panel with `date`, `code`, `close`, `open`, `high`, `low`, `volume`, `amount`, and three factor expressions. They will assert that:
  - candidates are filtered by `pool_id`, `accepted`, and the selected metric;
  - a factor whose daily cross-sectional values are almost identical to an already selected factor is rejected at the mutual-IC threshold;
  - the optimizer returns finite, deterministic weights that are not forced equal;
  - `compose_factors` creates one result directory per requested size containing `manifest.json`, `factor_weights.json`, `composition_summary.csv`, and normal backtest files.

- [x] **Step 2: Run the new tests before implementation.**

  Run from `custom_backtester`:

  ```powershell
  python -m pytest tests/test_factor_composition.py -q
  ```

  Expected: collection or assertion failures because `custom_bt.factor_composition` does not yet provide the requested APIs.

### Task 2: Implement AlphaGen-style composition core

**Files:**
- Create: `custom_backtester/custom_bt/factor_composition.py`
- Modify: `custom_backtester/custom_bt/__init__.py` only if the package currently exports public modules
- Test: `custom_backtester/tests/test_factor_composition.py`

- [x] **Step 1: Implement candidate normalization and loading.**

  Provide:

  ```python
  load_composition_candidates(records, pool_id, selection_metric="score",
                              min_score=None, min_ic=None,
                              min_rank_ic=None, min_coverage=None,
                              min_backtest_sharpe=None)
  ```

  Normalize each accepted record to `factor_id`, canonical expression, backtest expression, pool ID, source signature, and numeric metrics. Sort descending by the requested metric and then by factor ID for reproducibility.

- [x] **Step 2: Implement daily cross-sectional z-scoring and mutual IC.**

  Provide:

  ```python
  daily_cross_section_zscore(values)
  daily_mutual_ic(left, right)
  ```

  Align on `date`/`code`, z-score within each date, compute Pearson correlation per date over finite pairs, and return the mean correlation plus the number of usable dates. Preserve the sign of correlation by default so negative factors remain available.

- [x] **Step 3: Implement deterministic MSE/L1 weight optimization.**

  Provide:

  ```python
  optimize_mse_weights(ic_vector, mutual_ic_matrix,
                       l1_alpha=0.001, ridge_alpha=1e-8,
                       iterations=800, learning_rate=0.05,
                       initial_weights=None)
  ```

  Minimize `w.T @ M @ w - 2 * w.T @ ic + l1_alpha * sum(abs(w))` with deterministic proximal gradient updates. Use the AlphaGen-style initial rule (`max(ic, 0.01)` for the first factor and current mean for later factors) in the composition loop. Return weights, objective value, and convergence metadata.

- [x] **Step 4: Implement expression construction and candidate admission.**

  Use the existing canonical expression semantics and render:

  ```text
  (weight1)*(expr1) + (weight2)*(expr2) + ...
  ```

  Reject a new factor when `mutual_ic > mutual_ic_threshold` with any factor already in the pool. When capacity is exceeded, re-optimize and remove the component with the smallest absolute optimized weight.

- [x] **Step 5: Re-run the targeted tests.**

  Run:

  ```powershell
  python -m pytest tests/test_factor_composition.py -q
  ```

  Expected: all core composition tests pass.

### Task 3: Add candidate/result loading and composite backtest orchestration

**Files:**
- Modify: `custom_backtester/custom_bt/factor_composition.py`
- Modify: `custom_backtester/custom_bt/results.py` only if composite metadata needs a backward-compatible field
- Test: `custom_backtester/tests/test_factor_composition.py`

- [x] **Step 1: Implement factor-run and factor-backtest-summary loaders.**

  Read `accepted_factors.jsonl` and optional `factor_backtest_summary.csv`, merge matching `factor_id`/expression rows, and reject records whose pool/source signature does not match the requested stock pool/master store.

- [x] **Step 2: Implement `compose_factors(...)`.**

  The function will accept `master_store`, `pools_root`, `pool_id`, candidate source paths or factor run IDs, selection thresholds, mutual IC threshold, objective options, sweep sizes, and `BacktestConfig` data. It will:
  1. load the selected stock-pool panel once;
  2. evaluate accepted factor expressions once each;
  3. build the selected pool incrementally;
  4. run each requested size in `10,20,...,100` or the user-provided sweep;
  5. save results under `outputs/saved_backtests/composite/<pool_id>/<composition_id>/<size>/`.

- [x] **Step 3: Save the full composite manifest and audit files.**

  Each size directory must contain `manifest.json`, `factor_weights.json`, `composition_summary.csv`, `daily_report.csv`, `positions.csv`, `trades.csv`, `annual_metrics.csv`, `summary.json`, and `summary.png`. Manifest fields include `result_type`, `pool_id`, `composition_id`, `source_factor_run_ids`, `selected_factor_ids`, `selection_metric`, `mutual_ic_threshold`, `objective_type`, `max_factors`, `canonical_expression`, and `components`.

- [x] **Step 4: Re-run composition tests including saved-result discovery.**

  ```powershell
  python -m pytest tests/test_factor_composition.py tests/test_results.py -q
  ```

### Task 4: Integrate platform jobs and CLI

**Files:**
- Modify: `custom_backtester/custom_bt/platform_jobs.py`
- Modify: `custom_backtester/custom_bt/cli.py`
- Modify: `custom_backtester/tests/test_platform_jobs.py`
- Modify: `custom_backtester/tests/test_cli.py`

- [x] **Step 1: Add `compose_factors` to supported platform operations and dispatch it.**

  Preserve queued/running/finished/failed status behavior and include composition progress fields (`candidate_count`, `accepted_count`, `completed_sizes`, `current_size`) in `status.json`.

- [x] **Step 2: Add the `compose-factors` CLI command.**

  The command reads the existing platform YAML plus command-line `--pool`, `--factor-run`, and optional sweep/threshold arguments, then calls the same composition function used by the platform job.

- [x] **Step 3: Add platform-job and CLI contract tests, then run them.**

  ```powershell
  python -m pytest tests/test_platform_jobs.py tests/test_cli.py -q
  ```

### Task 5: Add the Streamlit composition workflow

**Files:**
- Modify: `custom_backtester/app/streamlit_app.py`
- Modify: `custom_backtester/tests/test_streamlit_app.py`

- [x] **Step 1: Add a dedicated `因子组合` tab.**

  Expose stock-pool selection, factor-run/source selection, selection metric, single-factor thresholds, mutual-IC threshold, objective type, maximum factor count, sweep sizes, and a submit button. Disable submission until the master cache and selected pool exist.

- [x] **Step 2: Show composition task progress and saved composite results.**

  Reuse the existing manual-refresh task status view and display candidate count, mutual-IC rejections, current sweep size, completed sizes, canonical expression, weights, metrics, and PNL/drawdown curve. The existing `已保存结果` tab must list `result_type = composite` without a second storage path.

- [x] **Step 3: Run Streamlit source/import tests and compile checks.**

  ```powershell
  python -m pytest tests/test_streamlit_app.py -q
  python -m compileall -q custom_bt app
  ```

### Task 6: Full verification and handoff

**Files:**
- Modify: `docs/superpowers/plans/2026-08-12-factor-composition-workflow.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [x] **Step 1: Run the complete test suite.**

  ```powershell
  python -m pytest tests -q
  ```

- [x] **Step 2: Run CLI and compilation smoke checks.**

  ```powershell
  python -m custom_bt.cli --help
  python -m compileall -q custom_bt app
  ```

- [x] **Step 3: Verify the requirement checklist from the design.**

  Confirm that single-factor generation remains separate, mutual IC is a pre-admission gate, weights are deterministic and optimized, sweep sizes are bounded by 100, operators remain canonical, and saved composite results appear in `list_runs`.

- [x] **Step 4: Record exact test output and any unresolved limitations in the progress files.**

## Verification record

- `python -m pytest tests -q`: 94 passed, 84 subtests passed, 1 external torch warning.
- `python -m custom_bt.cli --help`: passed and lists `compose-factors`.
- `python -m compileall -q custom_bt app`: passed.
