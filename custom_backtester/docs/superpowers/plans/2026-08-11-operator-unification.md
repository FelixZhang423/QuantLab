# Operator Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PPO generation, manual backtests, factor backtests, composite backtests, and Streamlit results use one user-facing operator grammar backed by one registry, then move results into one saved-results center.

**Architecture:** Add a metadata-only canonical operator registry with lazy AlphaGen class bindings and local evaluator bindings. Serialize PPO ASTs directly to canonical expressions such as `max`, `min`, `delay`, and `ts_mean`; make the local evaluator accept those same names. Store canonical expressions and PPO/backtest metrics in recursive result manifests under `outputs/saved_backtests/`, and migrate the current factor results before deleting legacy manual runs.

**Tech Stack:** Python, dataclasses, Pandas, PyTorch/Tensor AlphaGen backend, Streamlit, unittest/pytest, existing Parquet/CSV result artifacts.

---

### Task 1: Add the canonical operator registry

**Files:**
- Create: `custom_backtester/custom_bt/operator_registry.py`
- Create: `custom_backtester/tests/test_operator_registry.py`
- Modify: `custom_backtester/custom_bt/docs.py`

- [x] **Step 1: Write the failing registry tests**

```python
from custom_bt.operator_registry import (
    get_operator,
    list_operator_definitions,
    load_alphagen_operator_classes,
)


def test_canonical_definitions_include_shared_core_operators():
    names = {item.canonical_name for item in list_operator_definitions()}
    assert {"abs", "max", "min", "delay", "ts_mean", "ts_max", "ts_corr"} <= names


def test_greater_and_max_have_different_canonical_semantics():
    assert get_operator("max").alphagen_name == "Greater"
    assert get_operator("ts_max").alphagen_name == "Max"
    assert get_operator("max").category != get_operator("ts_max").category


def test_alphagen_operator_loader_returns_only_generation_enabled_classes():
    classes = load_alphagen_operator_classes()
    names = {item.__name__ for item in classes}
    assert {"Abs", "Greater", "Less", "Ref", "Mean", "Max", "Corr"} <= names
```

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest custom_backtester/tests/test_operator_registry.py -q`

Expected: FAIL because `custom_bt.operator_registry` does not exist.

- [x] **Step 3: Implement the registry contract**

Define `OperatorDefinition` with `canonical_name`, `category`, `description`, `example`, `arity`, `alphagen_name`, `local_impl`, `generation_enabled`, `manual_enabled`, and `aliases`. Register the currently enabled PPO operators with these canonical names:

```python
"max" -> "Greater"
"min" -> "Less"
"delay" -> "Ref"
"ts_mean" -> "Mean"
"ts_sum" -> "Sum"
"ts_std" -> "Std"
"ts_var" -> "Var"
"ts_max" -> "Max"
"ts_min" -> "Min"
"ts_median" -> "Med"
"ts_mad" -> "Mad"
"delta" -> "Delta"
"ts_wma" -> "WMA"
"ts_ema" -> "EMA"
"ts_covariance" -> "Cov"
"ts_corr" -> "Corr"
```

Implement case-sensitive alias lookup for legacy AlphaGen spellings (`Greater`, `Less`, `Ref`, `Mean`) and legacy local spellings (`ts_mean`, `delay`). Implement `load_alphagen_operator_classes()` with a lazy import of `single_factor._vendor.alphagen.data.expression` so importing the registry does not initialize the PPO runtime.

- [x] **Step 4: Make documentation use registry metadata**

Update `custom_bt.docs.enrich_operators()` so canonical descriptions and examples are read from the registry. Preserve existing Chinese documentation for manual-only operators, but add `generation_enabled` and `manual_enabled` fields to the returned rows.

- [x] **Step 5: Run the focused tests and verify they pass**

Run: `python -m pytest custom_backtester/tests/test_operator_registry.py custom_backtester/tests/test_docs.py -q`

Expected: PASS.

### Task 2: Use canonical names in PPO serialization and local evaluation

**Files:**
- Create: `custom_backtester/custom_bt/canonical_expression.py`
- Modify: `custom_backtester/custom_bt/expressions.py`
- Modify: `custom_backtester/custom_bt/factor_adapter.py`
- Modify: `single_factor/evaluator.py`
- Modify: `single_factor/_vendor/alphagen/config.py`
- Create: `custom_backtester/tests/test_canonical_expression.py`
- Modify: `custom_backtester/tests/test_factor_adapter.py`

- [x] **Step 1: Write failing canonical serialization tests**

```python
import pandas as pd

from custom_bt.canonical_expression import canonicalize_alphagen, serialize_alphagen_expression
from custom_bt.expressions import evaluate_expression


def make_small_panel():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "code": ["000001", "000002"],
            "close": [10.0, 20.0],
            "open": [11.0, 19.0],
        }
    )


def test_alphagen_names_serialize_to_user_friendly_names():
    assert canonicalize_alphagen("Greater($close,$open)") == "max(close,open)"
    assert canonicalize_alphagen("Less($close,$open)") == "min(close,open)"
    assert canonicalize_alphagen("Ref($close,20d)") == "delay(close,20)"
    assert canonicalize_alphagen("Mean($close,20d)") == "ts_mean(close,20)"


def test_canonical_max_and_time_series_max_are_distinct():
    assert canonicalize_alphagen("Greater($close,$open)") == "max(close,open)"
    assert canonicalize_alphagen("Max($close,20d)") == "ts_max(close,20)"


def test_local_evaluator_accepts_canonical_expression():
    panel = make_small_panel()
    result = evaluate_expression("max(close,open)", panel)
    assert result["alpha"].notna().any()
```

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest custom_backtester/tests/test_canonical_expression.py -q`

Expected: FAIL because canonical serialization and the canonical evaluator bindings are not implemented.

- [x] **Step 3: Implement the canonical serializer and migration parser**

Implement two separate functions in `custom_bt.canonical_expression`:

- `serialize_alphagen_expression(expr)` walks the vendored AlphaGen AST and uses the registry class binding to emit canonical names.
- `canonicalize_alphagen(expression)` parses a serialized AlphaGen expression with the existing safe token parser and emits canonical names for one-time migration of accepted-factor files.

The serializer must preserve `$`-prefixed feature names internally and remove the prefix only in the canonical stored expression. It must normalize `20d` to `20`, retain constants, and reject unknown AlphaGen classes with `ExpressionAdapterError`.

- [x] **Step 4: Make local evaluation use canonical operator names**

Replace the hand-maintained AlphaGen-to-local map in `factor_adapter.py` with registry lookup for migration only. Build `custom_bt.expressions.OPERATORS` from registry definitions and existing local implementation functions so `max`, `min`, `delay`, `ts_mean`, and all enabled canonical names are parsed directly. Keep old spellings available only through an explicit compatibility path and never emit them.

- [x] **Step 5: Make PPO use the registry operator list and canonical expression output**

Change `single_factor/_vendor/alphagen/config.py` to obtain its enabled class list from `load_alphagen_operator_classes()`. In `single_factor/evaluator.py`, replace `str(expr)` with `serialize_alphagen_expression(expr)` when filling `SingleFactorMetrics.expression`. This keeps PPO internals Tensor-based while making generated factor records canonical at creation time.

- [x] **Step 6: Run the focused tests and verify they pass**

Run: `python -m pytest custom_backtester/tests/test_canonical_expression.py custom_backtester/tests/test_factor_adapter.py custom_backtester/tests/test_expressions.py -q`

Expected: PASS, including existing safety and expression-evaluation tests.

### Task 3: Make factor and composite backtests consume canonical expressions

**Files:**
- Modify: `custom_backtester/custom_bt/factor_backtest.py`
- Modify: `custom_backtester/custom_bt/alpha.py`
- Modify: `custom_backtester/custom_bt/results.py`
- Modify: `custom_backtester/tests/test_factor_backtest.py`
- Modify: `custom_backtester/tests/test_results.py`

- [x] **Step 1: Add failing canonical factor-backtest assertions**

```python
def test_factor_backtest_records_canonical_expression(tmp_path):
    factor_run_dir = build_factor_run_fixture(tmp_path / "factor_run")
    result = backtest_accepted_factors(
        master_store=fixture_master_store,
        pools_root=fixture_pools_root,
        factor_run_dir=factor_run_dir,
        outputs_root=tmp_path / "outputs",
        backtest_config=fixture_backtest_config,
    )
    summary = pd.read_csv(Path(result["output_dir"]) / "factor_backtest_summary.csv")
    assert "canonical_expression" in summary.columns
    assert not summary["canonical_expression"].str.contains("Greater|Less|Ref|Mean").any()
```

Define `build_factor_run_fixture()` in the test module to write a minimal `factor_run.json` and one `accepted_factors.jsonl` record with `Greater($close,$open)`. Define `fixture_master_store`, `fixture_pools_root`, and `fixture_backtest_config` at module scope using the existing small Parquet/pool fixtures already used by `test_factor_backtest.py`; do not use the 20 GB source CSV.

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest custom_backtester/tests/test_factor_backtest.py custom_backtester/tests/test_results.py -q`

Expected: FAIL because factor summaries and manifests currently store `expression` and `backtest_expression` separately without a canonical result field.

- [x] **Step 3: Store canonical expression and PPO metrics in result manifests**

Update `save_result()` to accept a `metadata` mapping and merge it into `manifest.json`. Update factor backtests to evaluate canonical expressions directly, attach `result_type="factor"`, `pool_id`, `factor_run_id`, `canonical_expression`, and all generation metrics to each result. Apply the same contract to composite results with `result_type="composite"` and the list of component factor IDs and weights.

- [x] **Step 4: Update manual backtest output to the same contract**

Make `custom_bt.alpha` and the CLI pass `result_type="manual"` and the canonical input expression to `save_result()`. The saved manifest must contain the same metric keys as factor results, using null values for PPO-only fields when the result is manual.

- [x] **Step 5: Run the focused tests and verify they pass**

Run: `python -m pytest custom_backtester/tests/test_factor_backtest.py custom_backtester/tests/test_results.py custom_backtester/tests/test_engine_small.py -q`

Expected: PASS.

### Task 4: Make the saved-results center recursive and visible in Streamlit

**Files:**
- Modify: `custom_backtester/custom_bt/results.py`
- Modify: `custom_backtester/app/streamlit_app.py`
- Modify: `custom_backtester/tests/test_streamlit_app.py`
- Modify: `custom_backtester/tests/test_results.py`

- [x] **Step 1: Write failing result-center and UI tests**

```python
def test_list_runs_finds_nested_saved_results(tmp_path):
    manifest_dir = tmp_path / "factor" / "pool" / "run" / "factor_0001"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"result_type": "factor", "run_name": "factor_0001"}),
        encoding="utf-8",
    )
    (manifest_dir / "summary.json").write_text("{}", encoding="utf-8")
    (manifest_dir / "daily_report.csv").write_text("date,account\n", encoding="utf-8")
    runs = list_runs(tmp_path)
    assert len(runs) == 1


def test_saved_result_table_exposes_ppo_metrics():
    table = _saved_runs_table([{"canonical_expression": "ts_mean(close,20)", "generation_ic": 0.04}])
    assert "规范表达式" in table.columns
    assert "PPO IC" in table.columns
```

- [x] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest custom_backtester/tests/test_results.py custom_backtester/tests/test_streamlit_app.py -q`

Expected: FAIL because `list_runs()` scans only direct children and the UI does not expose PPO metrics in the saved-results table.

- [x] **Step 3: Implement recursive result discovery**

Change `list_runs()` to scan `rglob("manifest.json")`, accept only manifests with a supported `result_type`, load `summary.json`, and return the result directory as `path`. Exclude `jobs`, group manifests, and incomplete directories without the required chart/data files.

- [x] **Step 4: Point Streamlit to the result center**

Change the default `outputs_path` and factor-output path to `outputs/saved_backtests`. Update `_saved_runs_table()` and `_render_result_dir()` to display the canonical expression, result type, pool/factor run, PPO IC/Rank IC/ICIR/Coverage/Score, Sharpe, annual return, maximum drawdown, turnover, cost, and win rate. Keep download buttons for all saved artifacts.

- [x] **Step 5: Run the focused tests and verify they pass**

Run: `python -m pytest custom_backtester/tests/test_results.py custom_backtester/tests/test_streamlit_app.py -q`

Expected: PASS.

### Task 5: Migrate current factor results into the result center

**Files:**
- Create: `custom_backtester/custom_bt/migrate_results.py`
- Modify: `custom_backtester/custom_bt/cli.py`
- Create: `custom_backtester/tests/test_migrate_results.py`

- [x] **Step 1: Write failing migration tests**

```python
def test_migrate_factor_result_writes_canonical_manifest(tmp_path):
    source_dir = build_current_factor_result_fixture(tmp_path / "source")
    migrated = migrate_factor_results(source_dir, tmp_path / "saved_backtests")
    manifest = json.loads((Path(migrated[0]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result_type"] in {"factor", "composite"}
    assert "canonical_expression" in manifest
```

Define `build_current_factor_result_fixture()` in the test module to create one source factor directory with `manifest.json`, `summary.json`, `daily_report.csv`, and a factor summary row containing `Greater($close,$open)`. The fixture must also include one composite directory so the migration code is tested against both result types.

- [x] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest custom_backtester/tests/test_migrate_results.py -q`

Expected: FAIL because no migration command exists.

- [x] **Step 3: Implement an idempotent migration command**

Read the existing `factor_backtest_summary.csv`, each factor manifest, each factor result directory, and each composite result directory under `outputs/factor_backtests/liquid_500_864dc25f/liquid_500_864dc25f_af3e199fe8`. Copy artifacts into `outputs/saved_backtests/factor/...` and `outputs/saved_backtests/composite/...`, add canonical expressions and PPO metrics, and skip a destination whose manifest already has the same source signature and result ID. Do not touch the master cache or factor checkpoints.

- [x] **Step 4: Add a CLI entry point**

Add `python -m custom_bt.cli migrate-results --source outputs/factor_backtests --destination outputs/saved_backtests` and print counts for migrated, skipped, and failed results.

- [x] **Step 5: Run migration tests and a dry run**

Run: `python -m pytest custom_backtester/tests/test_migrate_results.py -q`

Then run: `python -m custom_bt.cli migrate-results --source outputs/factor_backtests --destination outputs/saved_backtests`

Expected: 54 factor results and 6 composite results are registered; a second run reports all results as skipped.

### Task 6: Remove legacy result directories after migration

**Files:**
- Modify: `custom_backtester/tests/test_results.py`
- Modify: `custom_backtester/task_plan.md`
- Modify: `custom_backtester/progress.md`

- [x] **Step 1: Verify exact legacy targets read-only**

Run: `Get-ChildItem custom_backtester\outputs\dif_dea_spread,custom_backtester\outputs\job_smoke,custom_backtester\outputs\low_turnover60,custom_backtester\outputs\macd_momentum,custom_backtester\outputs\sample_demo,custom_backtester\outputs\sample_demo_v2,custom_backtester\outputs\slow_mom120,custom_backtester\outputs\web_run -Directory`

Expected: only the eight explicitly approved legacy directories are listed.

- [x] **Step 2: Archive only the verified legacy directories**

Run one PowerShell command with the explicit literal paths:

```powershell
Remove-Item -LiteralPath @(
  "custom_backtester\outputs\dif_dea_spread",
  "custom_backtester\outputs\job_smoke",
  "custom_backtester\outputs\low_turnover60",
  "custom_backtester\outputs\macd_momentum",
  "custom_backtester\outputs\sample_demo",
  "custom_backtester\outputs\sample_demo_v2",
  "custom_backtester\outputs\slow_mom120",
  "custom_backtester\outputs\web_run"
) -Recurse -Force
```

Expected: the eight legacy directories are gone; `data_cache`, `factor_runs`, `outputs/factor_backtests`, and `outputs/saved_backtests` remain.

- [x] **Step 3: Add a regression test for legacy exclusion**

Assert that `list_runs("outputs")` returns no deleted legacy path and that every returned result is under `outputs/saved_backtests`.

- [x] **Step 4: Update progress files**

Record the migration counts, deletion targets, and any failures in `custom_backtester/progress.md`; mark the prior factor-result migration and operator-unification phases completed in `custom_backtester/task_plan.md`.

### Task 7: Run the complete verification suite

**Files:**
- Modify: `custom_backtester/tests/test_docs.py` if documentation assertions need canonical fields.

- [x] **Step 1: Run focused operator and result tests**

Run: `python -m pytest custom_backtester/tests/test_operator_registry.py custom_backtester/tests/test_canonical_expression.py custom_backtester/tests/test_factor_adapter.py custom_backtester/tests/test_expressions.py custom_backtester/tests/test_factor_backtest.py custom_backtester/tests/test_results.py custom_backtester/tests/test_migrate_results.py custom_backtester/tests/test_streamlit_app.py -q`

Expected: all focused tests pass.

- [x] **Step 2: Run the full test suite**

Run: `python -m pytest custom_backtester/tests -q`

Expected: all tests pass with no legacy result discovery failures.

- [x] **Step 3: Run a compile check**

Run: `python -m compileall -q custom_backtester/custom_bt custom_backtester/app single_factor`

Expected: exit code 0.

- [x] **Step 4: Verify the actual saved-result inventory**

Run: `python -m custom_bt.cli runs --outputs outputs/saved_backtests`

Expected: the output lists 54 factor results and 6 composite results, each with a canonical expression and PPO/backtest metrics where applicable.

- [x] **Step 5: Verify the Streamlit entry point imports**

Run: `python -c "import app.streamlit_app; print('streamlit import ok')"` from `custom_backtester`.

Expected: `streamlit import ok`.
