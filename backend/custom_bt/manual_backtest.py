"""手动回测：按股票池 + 用户输入的 Alpha 表达式执行一次 TopK 回测。

数据源跟随股票池 manifest：
- 公司库池（``data_source: clickhouse``）→ :mod:`repositories.company_source` 实时读面板；
- 旧本地池不再支持执行，必须在公司库上重建。

结果写入 ``outputs/saved_backtests/manual/<backtest_id>/<run_name>/``，
``run_key`` 也按该相对路径生成，与因子回测共用结果列表 / 详情 / 下载接口。
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

import pandas as pd

from repositories import company_source
from custom_bt.canonical_expression import normalize_expression
from repositories.panel_store import expression_fields, expression_lookback
from custom_bt.engine import BacktestConfig, attach_benchmark, equal_weight_benchmark, run_backtest
from adapters.expressions import evaluate_expression
from custom_bt.pools import load_pool_codes, load_pool_manifest
from services.report_service import save_result

logger = logging.getLogger(__name__)

_RUN_NAME_RE = re.compile(r"[A-Za-z0-9_.\-一-鿿]+")
_POOL_ID_RE = re.compile(r"[A-Za-z0-9_.\-一-鿿]+")
_BACKTEST_ID_RE = re.compile(r"[A-Za-z0-9_.\-]+")
ProgressCallback = Callable[[Dict[str, Any]], None]


def _emit(callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:  # noqa: BLE001 - 进度上报失败不能中断回测
        logger.warning("manual backtest progress callback failed", exc_info=True)


def validate_run_name(value: Any) -> str:
    """运行名称会进结果目录名，限制字符集与长度。"""
    text = str(value or "").strip()
    if not text or len(text) > 64 or not _RUN_NAME_RE.fullmatch(text):
        raise ValueError(
            "run_name 只能包含中英文、数字、下划线、点和短横线，且不超过 64 个字符"
        )
    return text


def validate_pool_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or not _POOL_ID_RE.fullmatch(text):
        raise ValueError(f"invalid pool_id: {value!r}")
    return text


def normalize_manual_expression(expression: Any) -> str:
    """统一算子别名并保留中缀写法（与因子回测的 AlphaGen 表达式不同）。"""
    text = str(expression or "").strip()
    if not text:
        raise ValueError("expression must not be empty")
    if len(text) > 2000:
        raise ValueError("expression is too long (max 2000 characters)")
    normalized = normalize_expression(text)
    if not normalized:
        raise ValueError("expression must not be empty")
    return normalized


def _validate_backtest_id(backtest_id: Optional[str]) -> Optional[str]:
    if backtest_id is None:
        return None
    text = str(backtest_id).strip()
    if not text or not _BACKTEST_ID_RE.fullmatch(text):
        raise ValueError(f"invalid backtest_id: {backtest_id!r}")
    return text


from repositories.panel_store import load_panel_for_pool as _load_panel  # noqa: E402


def run_manual_backtest(
    pools_root: str | Path,
    output_root: str | Path,
    run_name: str,
    expression: str,
    backtest_config: Mapping[str, Any],
    pool_id: str,
    data_source: Optional[str] = None,
    backtest_id: Optional[str] = None,
    snapshot_root: Optional[str | Path] = None,
    snapshot_id: Optional[str] = None,
    as_of: Optional[str] = None,
    pool_manifest: Optional[Mapping[str, Any]] = None,
    pool_codes: Optional[Iterable[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """执行一次手动回测，返回可写入任务状态的摘要。"""
    run_name = validate_run_name(run_name)
    pool_id = validate_pool_id(pool_id)
    backtest_id = _validate_backtest_id(backtest_id)
    if not isinstance(backtest_config, Mapping):
        raise ValueError("backtest_config must be a mapping")
    config = BacktestConfig(**dict(backtest_config))

    pool_manifest = (
        dict(pool_manifest)
        if pool_manifest is not None
        else load_pool_manifest(pools_root, pool_id)
    )
    source = company_source.resolve_data_source(data_source, pool_manifest)
    source_signature = company_source.source_signature()
    if pool_manifest.get("source_signature") != source_signature:
        raise ValueError("pool source signature does not match data source")

    codes = (
        [str(code).strip() for code in pool_codes if str(code).strip()]
        if pool_codes is not None
        else load_pool_codes(pools_root, pool_id)
    )
    if not codes:
        raise ValueError("pool has no stock codes")
    _emit(
        progress_callback,
        {
            "stage": "loading_panel",
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
            "n_codes": len(codes),
            "start_date": config.start_date,
            "end_date": config.end_date,
        },
    )
    normalized = normalize_manual_expression(expression)
    panel = _load_panel(source, codes, config, pool_id=pool_id, fields=expression_fields([normalized]),
                        snapshot_root=snapshot_root, snapshot_id=snapshot_id, as_of=as_of,
                        lookback_days=expression_lookback([normalized]))
    snapshot_id = panel.attrs["snapshot_id"]
    if panel.empty:
        raise ValueError("no panel rows remain for manual backtest")

    normalized = normalize_manual_expression(expression)
    _emit(
        progress_callback,
        {
            "stage": "evaluating",
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
            "expression": normalized,
            "rows": int(len(panel)),
            "n_stocks": int(panel["code"].nunique()),
        },
    )
    alpha = evaluate_expression(normalized, panel, output_name="alpha")
    if alpha["alpha"].notna().sum() == 0:
        raise ValueError("expression produced no valid alpha values on the pool panel")

    _emit(
        progress_callback,
        {
            "stage": "running",
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
            "rows": int(len(panel)),
            "n_stocks": int(panel["code"].nunique()),
        },
    )
    result = run_backtest(panel, alpha, config)
    attach_benchmark(result, equal_weight_benchmark(panel, config))

    outputs_root = Path(output_root).expanduser().resolve()
    saves_root = outputs_root / "manual"
    if backtest_id:
        saves_root = saves_root / backtest_id
    run_key = saves_root.joinpath(run_name).relative_to(outputs_root).as_posix()
    output_dir = save_result(
        result,
        saves_root,
        run_name,
        config={
            "backtest": asdict(config),
            "expression": normalized,
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
        },
        metadata={
            "result_type": "manual",
            "run_key": run_key,
            "canonical_expression": normalized,
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
            "source_signature": source_signature,
            "backtest_id": backtest_id,
        },
    )

    payload: Dict[str, Any] = {
        "run_key": run_key,
        "run_name": run_name,
        "output_dir": str(output_dir),
        "pool_id": pool_id,
        "data_source": source,
            "snapshot_id": snapshot_id,
        "backtest_id": backtest_id,
        "expression": normalized,
        "start_date": config.start_date,
        "end_date": config.end_date,
        "top_k": config.top_k,
        "initial_cash": config.initial_cash,
        "rows": int(len(panel)),
        "n_stocks": int(panel["code"].nunique()),
        "summary": result.summary,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _emit(progress_callback, {"stage": "finished", **payload})
    return payload
