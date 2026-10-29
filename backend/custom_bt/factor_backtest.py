from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd

from custom_bt import company_source
from custom_bt.canonical_expression import canonicalize_alphagen
from custom_bt.data import load_meta, load_pool_panel
from custom_bt.engine import BacktestConfig, run_backtest
from custom_bt.factor_adapter import validate_backtest_expression
from custom_bt.pools import load_pool_codes, load_pool_manifest
from custom_bt.results import save_result

logger = logging.getLogger(__name__)

_BACKTEST_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
ProgressCallback = Callable[[Dict[str, Any]], None]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def factor_id(index: int, expression: str) -> str:
    """因子在批次内的稳定 ID；预览与回测都使用同一算法。"""
    digest = hashlib.sha256(expression.encode("utf-8")).hexdigest()[:10]
    return f"factor_{index:04d}_{digest}"


def _factor_id(index: int, expression: str) -> str:
    return factor_id(index, expression)


def _saved_results_root(outputs_root: str | Path) -> Path:
    root = Path(outputs_root).expanduser().resolve()
    if root.name == "saved_backtests":
        return root
    if root.name == "factor_backtests":
        return root.parent / "saved_backtests"
    return root / "saved_backtests"


def _validate_backtest_id(backtest_id: str | None) -> str | None:
    if backtest_id is None:
        return None
    text = str(backtest_id).strip()
    if not text or not _BACKTEST_ID_RE.fullmatch(text):
        raise ValueError(f"invalid backtest_id: {backtest_id!r}")
    return text


def _emit(callback: ProgressCallback | None, payload: Dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:  # noqa: BLE001 - 进度上报失败不能中断回测
        logger.warning("factor backtest progress callback failed", exc_info=True)


def backtest_accepted_factors(
    master_store: str | Path,
    pools_root: str | Path,
    factor_run_dir: str | Path,
    outputs_root: str | Path,
    backtest_config: Dict[str, Any],
    expected_pool_id: str | None = None,
    backtest_id: str | None = None,
    factor_ids: Iterable[str] | None = None,
    progress_callback: ProgressCallback | None = None,
    data_source: str | None = None,
) -> dict:
    """Backtest accepted factors against the exact generation pool.

    ``backtest_id`` 用作输出目录的版本后缀（平台任务传入 job_id），避免同一
    因子运行用不同参数重复回测时互相覆盖；不传时保持旧的 ``factor/<pool>/<run>``
    目录结构。``factor_ids`` 为空表示回测全部合格因子。
    """
    factor_path = Path(factor_run_dir).expanduser().resolve()
    backtest_id = _validate_backtest_id(backtest_id)
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
    source = company_source.resolve_data_source(data_source, pool_manifest)
    source_meta = company_source.meta() if source == "clickhouse" else load_meta(master_store)
    source_signature = source_meta.get("source_signature")
    if source_signature != pool_manifest.get("source_signature"):
        raise ValueError("pool source signature does not match data source")
    if run_manifest.get("source_signature") not in (None, source_signature):
        raise ValueError("factor run source signature does not match data source")

    codes = load_pool_codes(pools_root, pool_id)
    if source == "clickhouse":
        # 因子运行里用到的财务/估值字段要一起加载，否则表达式解析不到。
        run_fields = [str(field) for field in (run_manifest.get("fields") or [])]
        fund_fields = [
            field[len(company_source.FUNDAMENTAL_PREFIX):]
            for field in run_fields
            if field.startswith(company_source.FUNDAMENTAL_PREFIX)
        ]
        val_fields = [
            field[len(company_source.VALUATION_PREFIX):]
            for field in run_fields
            if field.startswith(company_source.VALUATION_PREFIX)
        ]
        panel = company_source.load_panel(
            codes,
            backtest_config.get("start_date"),
            backtest_config.get("end_date"),
            fundamentals=fund_fields or None,
            valuation=val_fields or None,
        )
    else:
        panel = load_pool_panel(master_store, codes, backtest_config.get("start_date"), backtest_config.get("end_date"))
    if panel.empty:
        raise ValueError("no panel rows remain for factor backtest")
    config = BacktestConfig(**backtest_config)
    output_dir = _saved_results_root(outputs_root) / "factor" / pool_id / factor_path.name
    if backtest_id:
        output_dir = output_dir / backtest_id
    output_dir.mkdir(parents=True, exist_ok=True)
    run_key_prefix = f"factor/{pool_id}/{factor_path.name}"
    if backtest_id:
        run_key_prefix = f"{run_key_prefix}/{backtest_id}"

    accepted = _read_jsonl(factor_path / "accepted_factors.jsonl")
    indexed: List[Dict[str, Any]] = []
    for index, record in enumerate(accepted, start=1):
        expression = str(record.get("expression", "")).strip()
        current_id = _factor_id(index, expression) if expression else f"factor_{index:04d}"
        indexed.append(
            {"index": index, "record": record, "expression": expression, "factor_id": current_id}
        )

    requested_ids: set[str] | None = None
    if factor_ids is not None:
        requested_ids = {str(value).strip() for value in factor_ids if str(value).strip()}
        if not requested_ids:
            raise ValueError("factor_ids is empty; nothing to backtest")
        available_ids = {item["factor_id"] for item in indexed}
        missing = sorted(requested_ids - available_ids)
        if missing:
            raise ValueError(f"unknown factor_ids: {', '.join(missing[:5])}")
        selected = [item for item in indexed if item["factor_id"] in requested_ids]
    else:
        selected = indexed

    _emit(
        progress_callback,
        {
            "stage": "running",
            "pool_id": pool_id,
            "factor_run_id": factor_path.name,
            "backtest_id": backtest_id,
            "accepted_count": len(accepted),
            "selected_count": len(selected),
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "current_factor_id": None,
        },
    )

    summary_rows: List[Dict[str, Any]] = []
    completed = 0
    failed = 0
    failure_rows: List[Dict[str, Any]] = []
    for position, item in enumerate(selected, start=1):
        index = item["index"]
        record = item["record"]
        expression = item["expression"]
        factor_id_value = item["factor_id"]
        if not expression:
            failed += 1
            failure_rows.append({"factor_id": factor_id_value, "error": "empty expression"})
        else:
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
                run_key = f"{run_key_prefix}/{factor_id_value}"
                save_result(
                    result,
                    output_dir,
                    factor_id_value,
                    config={**backtest_config, "factor": record},
                    metadata={
                        "result_type": "factor",
                        "run_key": run_key,
                        "canonical_expression": canonical_expression,
                        "pool_id": pool_id,
                        "data_source": source,
                        "factor_run_id": factor_path.name,
                        "backtest_id": backtest_id,
                        "generation_metrics": {
                            key: record.get(key)
                            for key in ("ic", "rank_ic", "icir", "coverage", "score")
                        },
                    },
                )
                row: Dict[str, Any] = {
                    "factor_id": factor_id_value,
                    "expression": expression,
                    "canonical_expression": canonical_expression,
                    "backtest_expression": translated,
                    "pool_id": pool_id,
                    "accepted": True,
                    "run_key": run_key,
                }
                row.update({f"generation_{key}": value for key, value in record.items() if key in {"ic", "rank_ic", "icir", "coverage", "score"}})
                row.update({f"backtest_{key}": value for key, value in result.summary.items()})
                summary_rows.append(row)
                completed += 1
            except Exception as exc:
                failed += 1
                failure_rows.append({"factor_id": factor_id_value, "expression": expression, "error": f"{type(exc).__name__}: {exc}"})

        _emit(
            progress_callback,
            {
                "stage": "running" if position < len(selected) else "finished",
                "pool_id": pool_id,
                "factor_run_id": factor_path.name,
                "backtest_id": backtest_id,
                "accepted_count": len(accepted),
                "selected_count": len(selected),
                "processed": position,
                "completed": completed,
                "failed": failed,
                "current_factor_id": factor_id_value,
            },
        )

    pd.DataFrame(summary_rows).to_csv(output_dir / "factor_backtest_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failure_rows).to_csv(output_dir / "factor_backtest_failures.csv", index=False, encoding="utf-8-sig")
    result = {
        "backtest_id": backtest_id,
        "job_id": backtest_id,
        "pool_id": pool_id,
        "data_source": source,
        "factor_run_id": factor_path.name,
        "factor_run_dir": str(factor_path),
        "output_dir": str(output_dir),
        "run_key_prefix": run_key_prefix,
        "accepted_count": len(accepted),
        "selected_count": len(selected),
        "completed": completed,
        "failed": failed,
        "skipped": failed,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": config.start_date,
        "end_date": config.end_date,
        "top_k": config.top_k,
        "initial_cash": config.initial_cash,
        "backtest_config": dict(backtest_config),
        "summary_file": "factor_backtest_summary.csv",
        "failures_file": "factor_backtest_failures.csv",
    }
    (output_dir / "factor_backtest_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        from custom_bt.mysql_store import persist_factor_backtest_run

        persist_factor_backtest_run(output_dir, job_id=backtest_id)
    except Exception:
        logger.warning("MySQL persist failed for factor backtest %s", backtest_id or output_dir, exc_info=True)
    return result
