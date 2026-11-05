"""后台任务状态查询。"""
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


from common import (
    _read_json,
    _safe_child,
    _sanitize,
)

def get_job(job_id: str) -> Dict[str, Any]:
    """平台任务状态（create_pool 等），前端轮询用。"""
    job_dir = _safe_child(common.JOBS_ROOT, job_id)
    status_path = job_dir / "status.json"
    if not status_path.is_file():
        raise make_error(status_code=404, detail=f"job not found: {job_id}")
    try:
        status = _read_json(status_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise make_error(status_code=500, detail=f"读取任务状态失败：{exc}") from None
    status.setdefault("job_id", job_id)
    return _sanitize(status)
