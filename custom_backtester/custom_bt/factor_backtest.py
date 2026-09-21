from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from custom_bt.canonical_expression import canonicalize_alphagen
from custom_bt.data import load_meta, load_pool_panel
from custom_bt.engine import BacktestConfig, run_backtest
from custom_bt.factor_adapter import validate_backtest_expression
from custom_bt.pools import load_pool_codes, load_pool_manifest
from custom_bt.results import save_result


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _factor_id(index: int, expression: str) -> str:
    digest = hashlib.sha256(expression.encode("utf-8")).hexdigest()[:10]
    return f"factor_{index:04d}_{digest}"


def _saved_results_root(outputs_root: str | Path) -> Path:
    root = Path(outputs_root).expanduser().resolve()
    if root.name == "saved_backtests":
        return root
    if root.name == "factor_backtests":
        return root.parent / "saved_backtests"
    return root / "saved_backtests"


def backtest_accepted_factors(
    master_store: str | Path,
    pools_root: str | Path,
    factor_run_dir: str | Path,
    outputs_root: str | Path,
    backtest_config: Dict[str, Any],
    expected_pool_id: str | None = None,
) -> dict:
    """Backtest only accepted factors against the exact generation pool."""
    factor_path = Path(factor_run_dir).expanduser().resolve()
    run_manifest_path = factor_path / "factor_run.json"
    if not run_manifest_path.exists():
        raise FileNotFoundError(f"factor run manifest is missing: {run_manifest_path}")
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    pool_id = run_manifest.get("pool_id")
    if not pool_id:
        raise ValueError("factor run is missing pool_id")
    if expected_pool_id is not None and pool_id != expected_pool_id:
        raise ValueError(
            f"factor run pool_id {pool_id!r} does not match requested pool_id {expected_pool_id!r}"
        )
    pool_manifest = load_pool_manifest(pools_root, pool_id)
    source_signature = load_meta(master_store).get("source_signature")
    if source_signature != pool_manifest.get("source_signature"):
        raise ValueError("pool source signature does not match master store")
    if run_manifest.get("source_signature") not in (None, source_signature):
        raise ValueError("factor run source signature does not match master store")

    codes = load_pool_codes(pools_root, pool_id)
    panel = load_pool_panel(master_store, codes, backtest_config.get("start_date"), backtest_config.get("end_date"))
    if panel.empty:
        raise ValueError("no panel rows remain for factor backtest")
    config = BacktestConfig(**backtest_config)
    output_dir = _saved_results_root(outputs_root) / "factor" / pool_id / factor_path.name
    output_dir.mkdir(parents=True, exist_ok=True)
    accepted = _read_jsonl(factor_path / "accepted_factors.jsonl")
    summary_rows: List[Dict[str, Any]] = []
    completed = 0
    failed = 0
    failure_rows: List[Dict[str, Any]] = []
    for index, record in enumerate(accepted, start=1):
        expression = str(record.get("expression", "")).strip()
        if not expression:
            failed += 1
            failure_rows.append({"factor_id": f"factor_{index:04d}", "error": "empty expression"})
            continue
        factor_id = _factor_id(index, expression)
        try:
            canonical_expression = str(
                record.get("canonical_expression") or canonicalize_alphagen(expression)
            )
            translated = str(record.get("backtest_expression") or canonical_expression)
            validate_backtest_expression(canonical_expression, panel)
            alpha = __import__("custom_bt.expressions", fromlist=["evaluate_expression"]).evaluate_expression(
                translated,
                panel,
                output_name="alpha",
            )
            result = run_backtest(panel, alpha, config)
            save_result(
                result,
                output_dir,
                factor_id,
                config={**backtest_config, "factor": record},
                metadata={
                    "result_type": "factor",
                    "canonical_expression": canonical_expression,
                    "pool_id": pool_id,
                    "factor_run_id": factor_path.name,
                    "generation_metrics": {
                        key: record.get(key)
                        for key in ("ic", "rank_ic", "icir", "coverage", "score")
                    },
                },
            )
            row: Dict[str, Any] = {
                "factor_id": factor_id,
                "expression": expression,
                "canonical_expression": canonical_expression,
                "backtest_expression": translated,
                "pool_id": pool_id,
                "accepted": True,
            }
            row.update({f"generation_{key}": value for key, value in record.items() if key in {"ic", "rank_ic", "icir", "coverage", "score"}})
            row.update({f"backtest_{key}": value for key, value in result.summary.items()})
            summary_rows.append(row)
            completed += 1
        except Exception as exc:
            failed += 1
            failure_rows.append({"factor_id": factor_id, "expression": expression, "error": f"{type(exc).__name__}: {exc}"})

    pd.DataFrame(summary_rows).to_csv(output_dir / "factor_backtest_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failure_rows).to_csv(output_dir / "factor_backtest_failures.csv", index=False, encoding="utf-8-sig")
    result = {
        "pool_id": pool_id,
        "factor_run_dir": str(factor_path),
        "output_dir": str(output_dir),
        "accepted_count": len(accepted),
        "completed": completed,
        "failed": failed,
        "skipped": failed,
    }
    (output_dir / "factor_backtest_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
