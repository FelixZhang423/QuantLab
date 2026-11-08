"""股票池列表、详情、删除与建池任务。"""
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
    _parse_ymd,
    _read_json,
    _safe_child,
    _sanitize,
    _values,
    logger,
)

from services.data_service import (
    _filtered_universe,
    _live_universe,
)


_POOL_NAME_RE = re.compile(r"[A-Za-z0-9_.\-一-鿿]+")


def _pool_summary_from_manifest(
    manifest: Dict[str, Any], created_at: Optional[str]
) -> Dict[str, Any]:
    stats = [item for item in (manifest.get("selected_stats") or []) if isinstance(item, dict)]
    coverage = (
        sum(float(item.get("coverage") or 0.0) for item in stats) / len(stats) if stats else None
    )
    avg_amount = (
        sum(float(item.get("average_amount") or 0.0) for item in stats) / len(stats)
        if stats
        else None
    )
    return {
        "pool_id": manifest.get("pool_id"),
        "name": manifest.get("name"),
        "data_source": manifest.get("data_source") or "local",
        "n_stocks": manifest.get("n_stocks"),
        "selection_start": manifest.get("selection_start"),
        "selection_end": manifest.get("selection_end"),
        "top_n": manifest.get("top_n"),
        "min_listed_days": manifest.get("min_listed_days"),
        "min_coverage": manifest.get("min_coverage"),
        "exclude_suspended": manifest.get("exclude_suspended"),
        "category": manifest.get("category"),
        "market_code": manifest.get("market_code"),
        "source_signature": manifest.get("source_signature"),
        "selection_days": manifest.get("selection_days"),
        "coverage": coverage,
        "avg_amount": avg_amount,
        "created_at": created_at,
        "status": "active",
        "strict_top_n": manifest.get("strict_top_n"),
        "provenance": manifest.get("provenance"),
    }

def _pool_summary(pool_dir: Path) -> Optional[Dict[str, Any]]:
    manifest_path = pool_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    manifest.setdefault("pool_id", pool_dir.name)
    created_at = datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return _pool_summary_from_manifest(manifest, created_at)

def _local_pool_summaries() -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    if common.POOLS_ROOT.is_dir():
        for pool_dir in common.POOLS_ROOT.iterdir():
            if not pool_dir.is_dir():
                continue
            summary = _pool_summary(pool_dir)
            if summary is not None:
                summary["storage"] = "local"
                summaries.append(summary)
    return summaries

def _mysql_pool_summaries() -> Optional[List[Dict[str, Any]]]:
    try:
        rows = mysql_store.fetch_pools()
    except Exception:
        logger.warning("读取 MySQL 股票池失败，回退本地文件", exc_info=True)
        return None
    if rows is None:
        return None
    summaries: List[Dict[str, Any]] = []
    for row in rows:
        manifest = row.get("manifest") if isinstance(row.get("manifest"), dict) else {}
        manifest = dict(manifest)
        manifest.setdefault("pool_id", row.get("pool_id"))
        summary = _pool_summary_from_manifest(manifest, row.get("created_at"))
        summary["storage"] = "mysql"
        summaries.append(summary)
    return summaries

def _pool_reference_warnings(pool_id: str) -> List[str]:
    """列出仍引用该池、但不会随池删除的本地产物（因子运行 / 历史回测）。"""
    warnings: List[str] = []
    run_total = 0
    if common.FACTOR_RUNS_ROOT.is_dir():
        for run_dir in common.FACTOR_RUNS_ROOT.iterdir():
            manifest_path = run_dir / "factor_run.json"
            if not run_dir.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest = _read_json(manifest_path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(manifest, dict) and manifest.get("pool_id") == pool_id:
                run_total += 1
    if run_total:
        warnings.append(f"{run_total} 个因子运行仍引用该池（因子运行文件未删除）")
    if (common.RESULTS_ROOT / "factor" / pool_id).is_dir():
        warnings.append(
            "该池的历史因子回测结果仍保留在 outputs/saved_backtests/factor/<pool_id>，未删除"
        )
    return warnings

def _validate_pool_name(name: str) -> str:
    """池名最终会进目录名，限制字符集 + 长度防路径穿越。"""
    text = str(name or "").strip()
    if not text or len(text) > 64 or not _POOL_NAME_RE.fullmatch(text):
        raise make_error(
            status_code=422,
            detail="股票池名称只能包含中英文、数字、下划线、点和短横线，且不超过 64 个字符",
        )
    return text

def get_pools() -> Dict[str, Any]:
    """股票池列表：MySQL 优先，合并仅存在于本地的池。"""
    mysql_summaries = _mysql_pool_summaries()
    local_summaries = _local_pool_summaries()
    if mysql_summaries is None:
        summaries = local_summaries
        storage = "local"
    else:
        seen = {item.get("pool_id") for item in mysql_summaries}
        summaries = mysql_summaries + [
            item for item in local_summaries if item.get("pool_id") not in seen
        ]
        storage = "mysql" if len(summaries) == len(seen) else "mysql+local"
    summaries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return _sanitize({"total": len(summaries), "pools": summaries, "storage": storage})

def get_pool(pool_id: str) -> Dict[str, Any]:
    """股票池详情：MySQL 优先，找不到或连不上时回退本地 manifest。"""
    pool_dir = _safe_child(common.POOLS_ROOT, pool_id)
    mysql_detail = None
    try:
        mysql_detail = mysql_store.fetch_pool(pool_id)
    except Exception:
        logger.warning("读取 MySQL 股票池 %s 失败，回退本地文件", pool_id, exc_info=True)

    if mysql_detail is not None:
        manifest = mysql_detail.get("manifest") or {}
        summary = _pool_summary_from_manifest(manifest, mysql_detail.get("created_at"))
        return _sanitize(
            {
                **summary,
                "requested_codes": manifest.get("requested_codes"),
                "minimum_valid_rows": manifest.get("minimum_valid_rows"),
                "codes": mysql_detail.get("codes") or [],
                "storage": "mysql",
            }
        )

    manifest_path = pool_dir / "manifest.json"
    if not manifest_path.is_file():
        raise make_error(status_code=404, detail=f"pool not found: {pool_id}")
    manifest = _read_json(manifest_path)
    summary = _pool_summary(pool_dir) or {}
    codes: List[str] = []
    codes_file = pool_dir / str(manifest.get("codes_file", "codes.txt"))
    if codes_file.is_file():
        codes = [line.strip() for line in codes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return _sanitize(
        {
            **summary,
            "requested_codes": manifest.get("requested_codes"),
            "minimum_valid_rows": manifest.get("minimum_valid_rows"),
            "codes": codes,
            "storage": "local",
        }
    )

def delete_pool(
    pool_id: str,
    confirm: bool = False,
) -> Dict[str, Any]:
    """删除股票池：本地目录 + MySQL 记录；因子运行与历史回测结果保留。"""
    if not confirm:
        raise make_error(status_code=400, detail="删除不可恢复：请带 confirm=true 再次请求")
    pool_dir = _safe_child(common.POOLS_ROOT, pool_id)
    had_local = (pool_dir / "manifest.json").is_file()

    try:
        deleted_mysql = mysql_store.delete_pool(pool_id)
    except Exception:
        logger.warning("删除 MySQL 股票池 %s 失败", pool_id, exc_info=True)
        raise make_error(
            status_code=502,
            detail="MySQL 股票池删除失败，本地文件未改动；请确认数据库可用后重试",
        ) from None
    mysql_configured = deleted_mysql is not None
    deleted_mysql = bool(deleted_mysql)

    if not had_local and not deleted_mysql:
        raise make_error(status_code=404, detail=f"pool not found: {pool_id}")

    deleted_local = False
    if had_local:
        try:
            shutil.rmtree(pool_dir)
            deleted_local = True
        except OSError as exc:
            logger.warning("删除本地股票池 %s 失败", pool_id, exc_info=True)
            raise make_error(
                status_code=500,
                detail=(
                    f"MySQL 记录已删除，但本地目录删除失败：{exc}；"
                    f"请关闭占用后手动删除 {pool_dir}"
                ),
            ) from None

    warnings = _pool_reference_warnings(pool_id)
    if not mysql_configured:
        warnings.insert(0, "MySQL 未配置或连接不可用，本次只删除了本地文件")

    return _sanitize(
        {
            "pool_id": pool_id,
            "deleted_local": deleted_local,
            "deleted_mysql": deleted_mysql,
            "mysql_configured": mysql_configured,
            "warnings": warnings,
        }
    )

def create_pool(request: PoolCreateRequest) -> Dict[str, Any]:
    """按公司库筛选结果建池：候选与选样统计全部来自公司 ClickHouse。"""
    name = _validate_pool_name(request.name)
    start = _parse_ymd(request.selection_start, "selection_start")
    end = _parse_ymd(request.selection_end, "selection_end")
    if start > end:
        raise make_error(status_code=422, detail="selection_start 不能晚于 selection_end")
    if request.top_n is not None and request.top_n < 1:
        raise make_error(status_code=422, detail="top_n 必须为正整数")
    if not 0.0 <= request.min_coverage <= 1.0:
        raise make_error(status_code=422, detail="min_coverage 必须在 0 到 1 之间")
    if request.min_listed_days < 0:
        raise make_error(status_code=422, detail="min_listed_days 不能为负数")

    live = _live_universe()
    filters = {
        "industries": _values(request.industries),
        "exchanges": sorted({value.upper() for value in _values(request.exchanges)}),
        "boards": _values(request.boards),
        "sectors": _values(request.sectors),
        "listed_states": _values(request.listed_states),
        "q": request.q.strip(),
        "min_listed_days": request.min_listed_days,
    }
    matched = _filtered_universe(live, **filters, as_of=end.isoformat())
    if not matched:
        raise make_error(status_code=422, detail="没有股票匹配当前筛选条件")

    # 预览表格手动勾选：只接受当前筛选结果中的代码。
    # None = 未手动选择（沿用全部匹配股票）；空列表 = 显式一只都没选，必须报错。
    selection_mode = "all"
    selection_requested: Optional[set[str]] = None
    selected = matched
    if request.selected_codes is not None:
        selection_mode = "manual"
        if not any(str(value).strip() for value in request.selected_codes):
            raise make_error(status_code=422, detail="请至少勾选一只股票")
        selection_requested = {
            code
            for code in (normalize_code(value) for value in request.selected_codes)
            if code
        }
        if not selection_requested:
            raise make_error(status_code=422, detail="勾选的股票代码无效")
        selected = [item for item in matched if item["code"] in selection_requested]
        if not selected:
            raise make_error(
                status_code=422,
                detail="勾选的股票都不在当前筛选结果中，请刷新预览后重试",
            )

    warnings: List[str] = []
    if selection_mode == "manual" and selection_requested is not None:
        matched_codes = {item["code"] for item in matched}
        stale = selection_requested - matched_codes
        if stale:
            warnings.append(
                f"{len(stale)} 只已勾选股票不在当前筛选结果中，已忽略（请刷新预览后重试）"
            )
    if request.top_n is not None and len(selected) < request.top_n:
        warnings.append(
            f"本次候选 {len(selected)} 只，少于 TopN {request.top_n}；"
            "将按实际可建数量创建"
        )

    provenance = {
        "source": "clickhouse",
        "daily_table": live_db.DAILY_TABLE,
        "dim_table": live_db.DIM_TABLE,
        "endpoint": live_db.target_label(),
        "queried_at": live.queried_at,
        "as_of": end.isoformat(),
        "filters": {**filters, "exclude_suspended": request.exclude_suspended},
        "universe_total": len(live.data),
        "matched_total": len(matched),
        "selection_mode": selection_mode,
        "selected_total": len(selected),
    }
    payload = {
        "data_source": "clickhouse",
        "pools_root": str(common.POOLS_ROOT),
        "name": name,
        "selection_start": start.isoformat(),
        "selection_end": end.isoformat(),
        "top_n": request.top_n,
        "min_listed_days": request.min_listed_days,
        "min_coverage": request.min_coverage,
        "exclude_suspended": request.exclude_suspended,
        "category": "stock",
        "codes": sorted(item["code"] for item in selected),
        "overwrite": request.overwrite,
        "strict_top_n": False,
        "provenance": provenance,
    }
    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "create_pool", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise make_error(status_code=500, detail=f"创建建池任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise make_error(
            status_code=500, detail=f"建池任务已创建但启动失败：{exc}"
        ) from None

    return _sanitize(
        {
            "job_id": job_dir.name,
            "status": "queued",
            "operation": "create_pool",
            "warnings": warnings,
            "request_summary": {
                "name": name,
                "selection_start": start.isoformat(),
                "selection_end": end.isoformat(),
                "filters": filters,
                "top_n": request.top_n,
                "min_coverage": request.min_coverage,
                "exclude_suspended": request.exclude_suspended,
                "matched_total": len(matched),
                "selection_mode": selection_mode,
                "selected_total": len(selected),
                "universe_queried_at": live.queried_at,
            },
        }
    )
