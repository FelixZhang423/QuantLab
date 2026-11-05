"""数据总览 / 字段 / 股票 / 候选股票池 / 算子查询。"""
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
    _field_catalog,
    _live_error,
    _parse_ymd,
    _sanitize,
)

def _field_metadata():
    """从 system.columns 取 (表, 列) → 类型/注释；库不可用时返回 (None, 错误)。"""
    tables = sorted({str(entry["source_table"]) for entry in _field_catalog()})
    metadata: Dict[Any, Dict[str, str]] = {}
    try:
        client = live_db._client(live_db.resolve_settings())
        for table in tables:
            database, name = table.split(".", 1)
            rows = client.query(
                "SELECT name, type, comment FROM system.columns "
                f"WHERE database = '{database}' AND table = '{name}'"
            )
            for row in rows:
                metadata[(table, str(row.get("name", "")))] = {
                    "dtype": str(row.get("type", "")),
                    "comment": str(row.get("comment", "") or ""),
                }
    except (live_db.LiveDBError, OSError, ValueError) as exc:
        return None, str(exc)
    return metadata, None

def _catalog_status(entry: Dict[str, Any], found: Optional[bool]) -> str:
    """usable = 当前能写进表达式；pending = 财务待接入；unavailable = 文本/标识/库中缺失。"""
    if found is False:
        return "unavailable"
    category = entry.get("category")
    if category == "估值":
        return "usable"
    if category == "财务原始":
        return "usable" if entry.get("panel_alias") else "pending"
    if category == "财务衍生":
        return "usable" if entry.get("panel_alias") else "pending"
    field = entry.get("panel_alias") or entry.get("name", "")
    return "usable" if company_source.is_expression_field(field) else "unavailable"

def _live_universe() -> live_db.LiveResult:
    try:
        return live_db.live_stock_rows()
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None

def _filtered_universe(live: live_db.LiveResult, **filters: Any) -> List[Dict[str, Any]]:
    try:
        return live_db.filter_universe(live.data, **filters)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None

def get_master_info() -> Dict[str, Any]:
    try:
        stats = live_db.live_master_stats()
        catalog = live_db.live_field_catalog()
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None
    return _sanitize(
        {
            "ready": True,
            "data_source": "clickhouse",
            "store_dir": live_db.target_label(),
            "rows": stats.data["rows"],
            "n_stocks": stats.data["n_stocks"],
            "date_min": stats.data["date_min"],
            "date_max": stats.data["date_max"],
            "layout": "clickhouse-live",
            "source_signature": company_source.source_signature(),
            "n_fields": len(catalog.data),
            "fields": [item["name"] for item in catalog.data],
            "cached": stats.cached and catalog.cached,
            "queried_at": max(stats.queried_at, catalog.queried_at),
        }
    )

def get_fields() -> Dict[str, Any]:
    catalog = _field_catalog()
    metadata, metadata_error = _field_metadata()
    fields: List[Dict[str, Any]] = []
    for entry in catalog:
        table = str(entry.get("source_table"))
        column = str(entry.get("column"))
        found = None if metadata is None else (table, column) in metadata
        meta = metadata.get((table, column), {}) if metadata is not None else {}
        status = _catalog_status(entry, found)
        description = str(entry.get("description") or "").strip() or str(meta.get("comment") or "").strip() or "暂无说明"
        fields.append(
            {
                "name": entry.get("name"),
                "dtype": meta.get("dtype") if found else None,
                "source": table,
                "description": description,
                "panel": status == "usable",
                "expression": status == "usable",
                "category": entry.get("category"),
                "status": status,
                "panel_alias": entry.get("panel_alias"),
                "found_in_db": found,
                "period_type": entry.get("period_type"),
                "theme": entry.get("theme"),
                "unit": entry.get("unit"),
                "dimension": entry.get("dimension"),
                "derived": bool(entry.get("derived")),
                "derived_from": entry.get("derived_from"),
            }
        )
    counts = Counter(field["status"] for field in fields)
    return _sanitize(
        {
            "total": len(fields),
            "fields": fields,
            "offline": metadata is None,
            "metadata_error": metadata_error,
            "status_counts": dict(counts),
        }
    )

def get_stocks(
    q: str = "",
    limit: int = 0,
    offset: int = 0,
) -> Dict[str, Any]:
    try:
        live = live_db.live_stock_rows()
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None
    items = [dict(item) for item in live.data]
    keyword = q.strip().lower()
    if keyword:
        items = [
            item
            for item in items
            if keyword in item["code"] or keyword in str(item.get("name") or "").lower()
        ]
    total = len(items)
    total_rows = sum(item["rows"] for item in items)
    page = items[offset:] if limit <= 0 else items[offset : offset + limit]
    return _sanitize(
        {
            "total": total,
            "total_rows": total_rows,
            "n_stocks_all": len(live.data),
            "items": page,
            "cached": live.cached,
            "queried_at": live.queried_at,
        }
    )

def get_universe_options() -> Dict[str, Any]:
    """全库行业/市场/板块分布（候选全部来自公司库）。"""
    live = _live_universe()
    data = live_db.aggregate_universe(live.data, [item["code"] for item in live.data])
    return _sanitize(
        {
            **data,
            "data_source": "clickhouse",
            "ready": True,
            "cached": live.cached,
            "queried_at": live.queried_at,
        }
    )

def get_universe_stocks(
    industries: Optional[List[str]] = None,
    exchanges: Optional[List[str]] = None,
    boards: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    listed_states: Optional[List[str]] = None,
    q: str = "",
    min_listed_days: int = 0,
    as_of: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    live = _live_universe()
    as_of_date = _parse_ymd(as_of, "as_of") if as_of.strip() else date.today()
    matched = _filtered_universe(
        live,
        industries=industries,
        exchanges=exchanges,
        boards=boards,
        sectors=sectors,
        listed_states=listed_states,
        q=q,
        min_listed_days=min_listed_days,
        as_of=as_of_date.isoformat(),
    )
    page = [{**item, "creatable": True} for item in matched[offset : offset + limit]]
    return _sanitize(
        {
            "total": len(matched),
            "matched_total": len(matched),
            "items": page,
            "data_source": "clickhouse",
            "as_of": as_of_date.isoformat(),
            "cached": live.cached,
            "queried_at": live.queried_at,
        }
    )

def get_universe_codes(
    industries: Optional[List[str]] = None,
    exchanges: Optional[List[str]] = None,
    boards: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    listed_states: Optional[List[str]] = None,
    q: str = "",
    min_listed_days: int = 0,
    as_of: str = "",
) -> Dict[str, Any]:
    """当前筛选下的全部股票代码（轻量响应，供预览表格跨页全选/反选）。"""
    live = _live_universe()
    as_of_date = _parse_ymd(as_of, "as_of") if as_of.strip() else date.today()
    matched = _filtered_universe(
        live,
        industries=industries,
        exchanges=exchanges,
        boards=boards,
        sectors=sectors,
        listed_states=listed_states,
        q=q,
        min_listed_days=min_listed_days,
        as_of=as_of_date.isoformat(),
    )
    return _sanitize(
        {
            "codes": sorted(item["code"] for item in matched),
            "total": len(matched),
            "matched_total": len(matched),
            "data_source": "clickhouse",
            "as_of": as_of_date.isoformat(),
            "cached": live.cached,
            "queried_at": live.queried_at,
        }
    )

def get_operators() -> Dict[str, Any]:
    items = enrich_operators(list_operators())
    return _sanitize({"total": len(items), "operators": items})
