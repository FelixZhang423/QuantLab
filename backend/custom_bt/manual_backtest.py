"""手动回测：按股票池 + 用户输入的 Alpha 表达式执行一次 TopK 回测。

数据源跟随股票池 manifest：
- 公司库池（``data_source: clickhouse``）→ :mod:`custom_bt.company_source` 实时读面板；
- 旧本地池（无 ``data_source``）→ 兼容读取 ``data_cache/master``。

结果写入 ``outputs/saved_backtests/manual/<backtest_id>/<run_name>/``，
``run_key`` 也按该相对路径生成，与因子回测共用结果列表 / 详情 / 下载接口。
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import pandas as pd

from custom_bt import company_source
from custom_bt.canonical_expression import normalize_expression
from custom_bt.data import load_meta, load_pool_panel
from custom_bt.engine import BacktestConfig, run_backtest
from custom_bt.expressions import evaluate_expression
from custom_bt.pools import load_pool_codes, load_pool_manifest
from custom_bt.results import save_result

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


def _load_panel(
    source: str,
    master_store: Optional[str | Path],
    codes: list[str],
    config: BacktestConfig,
) -> pd.DataFrame:
    if source == "clickhouse":
        return company_source.load_panel(codes, config.start_date, config.end_date)
    if not master_store:
        raise ValueError("local pool requires master_store")
    return load_pool_panel(master_store, codes, config.start_date, config.end_date)


def run_manual_backtest(
    pools_root: str | Path,
    output_root: str | Path,
    run_name: str,
    expression: str,
    backtest_config: Mapping[str, Any],
    pool_id: str,
    data_source: Optional[str] = None,
    backtest_id: Optional[str] = None,
    master_store: Optional[str | Path] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """执行一次手动回测，返回可写入任务状态的摘要。"""
    run_name = validate_run_name(run_name)
    pool_id = validate_pool_id(pool_id)
    backtest_id = _validate_backtest_id(backtest_id)
    if not isinstance(backtest_config, Mapping):
        raise ValueError("backtest_config must be a mapping")
    config = BacktestConfig(**dict(backtest_config))

    pool_manifest = load_pool_manifest(pools_root, pool_id)
    source = company_source.resolve_data_source(data_source, pool_manifest)
    if source == "clickhouse":
        source_meta = company_source.meta()
    else:
        source_meta = load_meta(master_store) if master_store else {}
    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise ValueError("pool source signature does not match data source")

    codes = load_pool_codes(pools_root, pool_id)
    _emit(
        progress_callback,
        {
            "stage": "loading_panel",
            "pool_id": pool_id,
            "data_source": source,
            "n_codes": len(codes),
            "start_date": config.start_date,
            "end_date": config.end_date,
        },
    )
    panel = _load_panel(source, master_store, codes, config)
    if panel.empty:
        raise ValueError("no panel rows remain for manual backtest")

    normalized = normalize_manual_expression(expression)
    _emit(
        progress_callback,
        {
            "stage": "evaluating",
            "pool_id": pool_id,
            "data_source": source,
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
            "rows": int(len(panel)),
            "n_stocks": int(panel["code"].nunique()),
        },
    )
    result = run_backtest(panel, alpha, config)

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
        },
        metadata={
            "result_type": "manual",
            "run_key": run_key,
            "canonical_expression": normalized,
            "pool_id": pool_id,
            "data_source": source,
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
