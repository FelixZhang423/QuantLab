"""共享常量与通用工具（路由/服务/仓储都可依赖）。"""
from __future__ import annotations


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

from errors import DomainError, make_error

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

from config.settings import (  # noqa: E402  (再导出，兼容既有 import)
    FACTOR_GENERATION_CONFIG_PATH,
    FACTOR_RUNS_ROOT,
    FACTOR_RUNTIME_ROOT,
    FIELD_CATALOG_PATH,
    FIELD_DOC_PATH,
    JOBS_ROOT,
    MASTER_DIR,
    POOLS_ROOT,
    PROJECT_ROOT,
    RESULTS_ROOT,
    VAR_ROOT,
    WORKSPACE_ROOT,
)

_CATALOG_CACHE: Dict[str, Any] = {}

logger = logging.getLogger(__name__)

def _sanitize(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value

def _safe_child(root: Path, name: str) -> Path:
    """把 URL 里的 id 解析为 root 下的直接子路径，拒绝路径穿越。"""
    if not re.fullmatch(r"[A-Za-z0-9_.\-一-鿿]+", name):
        raise make_error(status_code=404, detail=f"invalid name: {name}")
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise make_error(status_code=404, detail=f"invalid name: {name}")
    return path

def _safe_relative(root: Path, relative: str) -> Path:
    """把 run_key 之类的多级相对路径解析到 root 下，拒绝绝对路径与 ..。"""
    text = str(relative or "").strip().replace("\\", "/")
    parts = text.split("/")
    if (
        not text
        or text.startswith("/")
        or "\x00" in text
        or any(not part or part in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.\-一-鿿]+", part) for part in parts)
    ):
        raise make_error(status_code=404, detail=f"invalid path: {relative}")
    root_path = root.resolve()
    path = (root_path / Path(*parts)).resolve()
    try:
        path.relative_to(root_path)
    except ValueError:
        raise make_error(status_code=404, detail=f"invalid path: {relative}") from None
    return path

def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _live_error(exc: live_db.LiveDBError) -> DomainError:
    """实时数据源异常 → HTTP 状态码（缺配置 / 连不上 / 认证失败 = 503，查询失败 = 502）。"""
    if isinstance(exc, (live_db.LiveDBConfigError, live_db.LiveDBUnavailable)):
        return make_error(status_code=503, detail=str(exc))
    return make_error(status_code=502, detail=str(exc))

def _parse_ymd(value: str, field: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise make_error(status_code=422, detail=f"{field} 必须是 YYYY-MM-DD 格式") from None

def _values(values: List[str]) -> List[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})

def _cache_ymd(value: Any) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None

def _field_catalog() -> List[Dict[str, Any]]:
    """读取 123 条字段目录；文件变化时重新加载。"""
    stat = FIELD_CATALOG_PATH.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    if _CATALOG_CACHE.get("key") != key:
        _CATALOG_CACHE["key"] = key
        _CATALOG_CACHE["data"] = json.loads(FIELD_CATALOG_PATH.read_text(encoding="utf-8"))
    return _CATALOG_CACHE["data"]
