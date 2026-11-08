"""手动表达式回测提交。"""
from __future__ import annotations

from repositories.snapshot_store import snapshot_manifest
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

from repositories.local_store import normalize_code  # noqa: E402

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


from common import (
    _cache_ymd,
    _live_error,
    _parse_ymd,
    _sanitize,
)

from services.generation_service import (
    _generation_pool_source,
)

def _validate_manual_expression(expression: str) -> str:
    """统一算子别名，并在提交时先做语法 / 字段 / 算子校验。"""
    try:
        normalized = normalize_manual_expression(expression)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None
    try:
        _validate_ast(
            normalized,
            {name: None for name in company_source.panel_field_names()},
        )
    except ExpressionError as exc:
        raise make_error(status_code=422, detail=f"Alpha 表达式无效：{exc}") from None
    return normalized

def create_manual_backtest(request: ManualBacktestRequest) -> Dict[str, Any]:
    """按股票池 + Alpha 表达式提交一次手动回测（后台任务）。"""
    if request.top_k < 1 or request.top_k > 1000:
        raise make_error(status_code=422, detail="top_k 必须在 1 到 1000 之间")
    if request.initial_cash <= 0:
        raise make_error(status_code=422, detail="initial_cash 必须大于 0")
    for name, value in (
        ("buy_cost", request.buy_cost),
        ("sell_cost", request.sell_cost),
        ("slippage", request.slippage),
    ):
        if not 0.0 <= value <= 0.1:
            raise make_error(status_code=422, detail=f"{name} 必须在 0 到 0.1 之间")
    if request.min_cost < 0:
        raise make_error(status_code=422, detail="min_cost 不能为负数")
    if not 0.0 < request.max_weight_per_stock <= 1.0:
        raise make_error(status_code=422, detail="max_weight_per_stock 必须在 0 到 1 之间")

    try:
        run_name = validate_run_name(request.run_name)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None
    expression = _validate_manual_expression(request.expression)

    pool_manifest, pool_codes, _pool_storage = _generation_pool_source(request.pool_id)
    try:
        source = company_source.resolve_data_source(None, pool_manifest)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None
    if source == "clickhouse":
        try:
            source_meta = (snapshot_manifest(request.snapshot_id, snapshot_root=common.SNAPSHOT_ROOT)
                           if request.snapshot_id else company_source.meta())
        except live_db.LiveDBError as exc:
            raise _live_error(exc) from None
        except (ValueError, OSError) as exc:
            raise make_error(status_code=422, detail=f"快照不可用：{exc}") from None
    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise make_error(
            status_code=422,
            detail="股票池与数据源签名不一致，请重新建池后再回测",
        )

    source_start = _cache_ymd(source_meta.get("date_min"))
    source_end = _cache_ymd(source_meta.get("date_max"))
    default_start = _cache_ymd(pool_manifest.get("selection_start")) or source_start
    default_end = _cache_ymd(pool_manifest.get("selection_end")) or source_end
    start = _parse_ymd(request.start_date, "start_date") if request.start_date else default_start
    end = _parse_ymd(request.end_date, "end_date") if request.end_date else default_end
    if start is None or end is None:
        raise make_error(
            status_code=422,
            detail="无法确定回测区间：股票池或数据源缺少日期范围，请显式传入 start_date/end_date",
        )
    if start > end:
        raise make_error(status_code=422, detail="start_date 不能晚于 end_date")
    if source_start and source_end and (end < source_start or start > source_end):
        raise make_error(
            status_code=422,
            detail=(
                f"回测区间与数据源（{source_start.isoformat()} ~ {source_end.isoformat()}）"
                "没有交集"
            ),
        )

    warnings: List[str] = []
    if source_start and start < source_start:
        warnings.append(f"回测起点早于数据源 {source_start.isoformat()}，将按数据源可用区间计算")
    if source_end and end > source_end:
        warnings.append(f"回测终点晚于数据源 {source_end.isoformat()}，将按数据源可用区间计算")

    backtest_config = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "top_k": request.top_k,
        "initial_cash": request.initial_cash,
        "buy_cost": request.buy_cost,
        "sell_cost": request.sell_cost,
        "slippage": request.slippage,
        "min_cost": request.min_cost,
        "max_weight_per_stock": request.max_weight_per_stock,
    }
    payload = {
        "pools_root": str(common.POOLS_ROOT),
        "output_root": str(common.RESULTS_ROOT),
        "snapshot_root": str(common.SNAPSHOT_ROOT),
        "snapshot_id": request.snapshot_id,
        "as_of": request.as_of,
        "pool_id": request.pool_id,
        "data_source": source,
        "run_name": run_name,
        "expression": expression,
        "backtest_config": backtest_config,
        "pool_manifest": pool_manifest,
        "pool_codes": pool_codes,
    }

    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "manual_backtest", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise make_error(status_code=500, detail=f"创建手动回测任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise make_error(
            status_code=500, detail=f"手动回测任务已创建但启动失败：{exc}"
        ) from None

    return _sanitize(
        {
            "job_id": job_dir.name,
            "status": "queued",
            "operation": "manual_backtest",
            "pool_id": request.pool_id,
            "data_source": source,
            "run_name": run_name,
            "expression": expression,
            "warnings": warnings,
            "request_summary": {
                "pool_id": request.pool_id,
                "run_name": run_name,
                "expression": expression,
                **backtest_config,
            },
        }
    )
