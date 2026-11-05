"""回测结果列表、详情与文件下载。"""
from __future__ import annotations

from errors import DomainError, make_error

import common


import json

import logging

import math

import os

import re

import shutil

import sys

from collections import Counter

from contextlib import asynccontextmanager

from datetime import date, datetime, timedelta

from pathlib import Path

from typing import Any, AsyncIterator, Dict, List, Optional

import pandas as pd

import yaml




from schemas import (  # noqa: E402
    FactorBacktestRequest,
    FactorGenerationRequest,
    FactorGenerationSplit,
    ManualBacktestRequest,
    PoolCreateRequest,
)

from repositories import clickhouse as live_db  # noqa: E402

from workers.job_runner import spawn_platform_job  # noqa: E402

from repositories import company_source, mysql_store  # noqa: E402

from custom_bt.canonical_expression import normalize_expression  # noqa: E402

from repositories.local_store import load_meta, normalize_code  # noqa: E402

from custom_bt.docs import enrich_operators  # noqa: E402

from adapters.expressions import (  # noqa: E402
    ExpressionError,
    _validate_ast,
    list_operators,
)

from custom_bt.factor_backtest import factor_id as factor_id_for  # noqa: E402

from custom_bt.factor_generation import (  # noqa: E402
    fundamental_period_mode,
    resolve_generation_device,
)

from repositories.job_store import update_job_status  # noqa: E402

from custom_bt.manual_backtest import (  # noqa: E402
    normalize_manual_expression,
    validate_run_name,
)

from adapters.operator_registry import get_operator  # noqa: E402

from workers.job_dispatcher import create_platform_job  # noqa: E402

from repositories.result_store import list_runs  # noqa: E402

from common import (
    _read_json,
    _safe_child,
    _safe_relative,
    _sanitize,
)

def _result_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    config = run.get("config") or {}
    # 手动回测参数在 config.backtest；因子/旧版结果是扁平 config
    nested = config.get("backtest") if isinstance(config, dict) else None
    backtest = nested if isinstance(nested, dict) else config
    if not isinstance(backtest, dict):
        backtest = {}
    return {
        "run_name": run.get("run_name"),
        "run_key": run.get("run_key"),
        "created_at": run.get("created_at"),
        "result_type": run.get("result_type"),
        "canonical_expression": run.get("canonical_expression"),
        "components": run.get("components"),
        "pool_id": run.get("pool_id"),
        "factor_run_id": run.get("factor_run_id"),
        "backtest_id": run.get("backtest_id"),
        "data_source": run.get("data_source") or config.get("data_source"),
        "summary": run.get("summary"),
        "start_date": backtest.get("start_date"),
        "end_date": backtest.get("end_date"),
        "top_k": backtest.get("top_k"),
        "initial_cash": backtest.get("initial_cash"),
    }

def _result_detail_payload(run_dir: Path, run_key: str) -> Dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise make_error(status_code=404, detail=f"result not found: {run_key}")
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise make_error(status_code=500, detail=f"读取结果 manifest 失败：{exc}") from None
    config = manifest.get("config") or {}
    # 手动回测把参数放在 config.backtest 下；因子/旧版结果直接是扁平 config
    nested = config.get("backtest") if isinstance(config, dict) else None
    backtest = nested if isinstance(nested, dict) else config
    if not isinstance(backtest, dict):
        backtest = {}

    summary: Dict[str, Any] = {}
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        try:
            summary = _read_json(summary_path)
        except (OSError, json.JSONDecodeError):
            summary = {}

    def _pct(key: str) -> Optional[float]:
        value = summary.get(key)
        return None if value is None else float(value) * 100.0

    daily_path = run_dir / "daily_report.csv"
    equity: List[Dict[str, Any]] = []
    if daily_path.is_file():
        daily = pd.read_csv(daily_path)
        initial_cash = float(backtest.get("initial_cash") or 1.0)
        for row in daily.to_dict("records"):
            equity.append(
                {
                    "date": str(row.get("date", "")),
                    "equity": round(float(row.get("account") or 0.0) / initial_cash, 4),
                    "drawdown": round(float(row.get("drawdown") or 0.0) * 100.0, 2),
                }
            )

    annual_path = run_dir / "annual_metrics.csv"
    yearly: List[Dict[str, Any]] = []
    if annual_path.is_file():
        annual = pd.read_csv(annual_path)
        for row in annual.to_dict("records"):
            # 注意列名 "return" 是 Python 关键字，只能按字典键取值
            yearly.append(
                {
                    "year": str(row.get("year", "")),
                    "returns": round(float(row.get("return") or 0.0) * 100.0, 2),
                    "sharpe": round(float(row.get("sharpe") or 0.0), 2),
                    "drawdown": round(float(row.get("max_drawdown") or 0.0) * 100.0, 2),
                    "turnover": round(float(row.get("turnover") or 0.0) * 100.0, 2),
                    "cost": round(float(row.get("cost") or 0.0) * 100.0, 2),
                    "winRate": round(float(row.get("win_rate") or 0.0) * 100.0, 2),
                }
            )

    files = []
    for item in manifest.get("files") or []:
        file_path = run_dir / item
        if file_path.is_file():
            files.append(
                {
                    "name": item,
                    "size": file_path.stat().st_size,
                    "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                }
            )

    return _sanitize(
        {
            "run_name": manifest.get("run_name", run_dir.name),
            "run_key": manifest.get("run_key") or run_key,
            "created_at": manifest.get("created_at"),
            "result_type": manifest.get("result_type"),
            "canonical_expression": manifest.get("canonical_expression"),
            "components": manifest.get("components"),
            "pool_id": manifest.get("pool_id"),
            "factor_run_id": manifest.get("factor_run_id"),
            "backtest_id": manifest.get("backtest_id"),
            "data_source": manifest.get("data_source") or config.get("data_source"),
            "config": config,
            "summary": summary,
            "metrics": {
                "annual": _pct("annual_return"),
                "sharpe": summary.get("sharpe"),
                "drawdown": _pct("max_drawdown"),
                "turnover": _pct("average_turnover"),
                "cost": _pct("total_cost"),
                "winRate": _pct("win_rate"),
            },
            "equity": equity,
            "yearly": yearly,
            "files": files,
        }
    )

def _result_file(run_dir: Path, run_key: str, file_name: str) -> Path:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise make_error(status_code=404, detail=f"result not found: {run_key}")
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise make_error(status_code=500, detail=f"读取结果 manifest 失败：{exc}") from None
    if file_name not in (manifest.get("files") or []):
        raise make_error(status_code=404, detail=f"file not allowed: {file_name}")
    file_path = _safe_child(run_dir, file_name)
    if not file_path.is_file():
        raise make_error(status_code=404, detail=f"file not found: {file_name}")
    return file_path

def get_results() -> Dict[str, Any]:
    runs = list_runs(common.RESULTS_ROOT)
    return _sanitize({"total": len(runs), "results": [_result_summary(run) for run in runs]})

def get_result_by_key(run_key: str ) -> Dict[str, Any]:
    run_dir = _safe_relative(common.RESULTS_ROOT, run_key)
    return _result_detail_payload(run_dir, run_key)

def download_result_file_by_key(
    run_key: str ,
    file_name: str ,
) -> Path:
    run_dir = _safe_relative(common.RESULTS_ROOT, run_key)
    return _result_file(run_dir, run_key, file_name)

def get_result(run_name: str) -> Dict[str, Any]:
    """兼容旧的扁平结果名（如 web_run）；嵌套因子结果请用 /api/results/detail?run_key=。"""
    run_dir = _safe_child(common.RESULTS_ROOT, run_name)
    return _result_detail_payload(run_dir, run_name)

def download_result_file(run_name: str, file_name: str) -> Path:
    run_dir = _safe_child(common.RESULTS_ROOT, run_name)
    return _result_file(run_dir, run_name, file_name)
