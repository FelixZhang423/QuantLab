"""FastAPI 应用：把 custom_bt 现有的数据 / 结果入口暴露给 React 原型。

覆盖数据总览、数据字段、股票列表、操作符、股票池、因子回测、手动回测、结果详情，
以及股票池候选（/api/universe/*）与建池任务（POST /api/pools + /api/jobs/{job_id}）。

数据总览 / 数据字段 / 股票列表 / 股票池候选 / 建池 / 因子面板 / 回测面板
全部走公司 ClickHouse 实时查询（api/live_db.py、custom_bt/company_source.py），
不再依赖本地 data_cache/master；股票池列表/详情优先读 MySQL，连不上时回退本地
data_cache/pools；算子、因子运行与回测结果仍读本地 factor_runs / outputs。
建池、因子回测和手动回测任务在后台子进程里执行（api/job_runner.py），
状态写 outputs/jobs/*/status.json。

所有响应统一走 _sanitize：把 NaN / Infinity 转成 null，
否则 Starlette 序列化会直接抛错（allow_nan=False）。
"""
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
from datetime import date, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api import live_db  # noqa: E402
from api.job_runner import spawn_platform_job  # noqa: E402
from custom_bt import company_source, mysql_store  # noqa: E402
from custom_bt.data import load_meta, normalize_code  # noqa: E402
from custom_bt.docs import enrich_operators  # noqa: E402
from custom_bt.expressions import (  # noqa: E402
    ExpressionError,
    _validate_ast,
    list_operators,
)
from custom_bt.factor_backtest import factor_id as factor_id_for  # noqa: E402
from custom_bt.jobs import update_job_status  # noqa: E402
from custom_bt.manual_backtest import (  # noqa: E402
    normalize_manual_expression,
    validate_run_name,
)
from custom_bt.platform_jobs import create_platform_job  # noqa: E402
from custom_bt.results import list_runs  # noqa: E402

MASTER_DIR = PROJECT_ROOT / "data_cache" / "master"
POOLS_ROOT = PROJECT_ROOT / "data_cache" / "pools"
JOBS_ROOT = PROJECT_ROOT / "outputs" / "jobs"
RESULTS_ROOT = PROJECT_ROOT / "outputs" / "saved_backtests"
# 与 configs/factor_generation.yaml 的 ../factor_runs 保持一致
FACTOR_RUNS_ROOT = Path(
    os.environ.get("QL_FACTOR_RUNS_ROOT", str(WORKSPACE_ROOT / "factor_runs"))
).expanduser()
FIELD_DOC_PATH = next(
    iter(WORKSPACE_ROOT.glob("v_stock_daily_full_*.md")),
    WORKSPACE_ROOT / "v_stock_daily_full_字段说明.md",
)
# 数据字段页的 123 条目录（行情 60 + 财务原始 58 + 估值 5）
FIELD_CATALOG_PATH = PROJECT_ROOT / "configs" / "field_catalog.json"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 后台预热实时查询缓存（无密码 / 不在公司网络时静默跳过）
    live_db.prewarm()
    yield


app = FastAPI(title="QuantLab Custom Backtester API", version="0.1.0", lifespan=_lifespan)
# 本地开发：原型 dev server 通过 vite proxy 访问，这里放开跨域方便直接调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


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
        raise HTTPException(status_code=404, detail=f"invalid name: {name}")
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise HTTPException(status_code=404, detail=f"invalid name: {name}")
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
        raise HTTPException(status_code=404, detail=f"invalid path: {relative}")
    root_path = root.resolve()
    path = (root_path / Path(*parts)).resolve()
    try:
        path.relative_to(root_path)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"invalid path: {relative}") from None
    return path


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "quantlab-backend-api"}


# ---------- 数据（ClickHouse 实时） ----------


def _live_error(exc: live_db.LiveDBError) -> HTTPException:
    """实时数据源异常 → HTTP 状态码（缺配置 / 连不上 / 认证失败 = 503，查询失败 = 502）。"""
    if isinstance(exc, (live_db.LiveDBConfigError, live_db.LiveDBUnavailable)):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


_CATALOG_CACHE: Dict[str, Any] = {}


def _field_catalog() -> List[Dict[str, Any]]:
    """读取 123 条字段目录；文件变化时重新加载。"""
    stat = FIELD_CATALOG_PATH.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    if _CATALOG_CACHE.get("key") != key:
        _CATALOG_CACHE["key"] = key
        _CATALOG_CACHE["data"] = json.loads(FIELD_CATALOG_PATH.read_text(encoding="utf-8"))
    return _CATALOG_CACHE["data"]


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


# ---------- 股票池候选 / 建池辅助 ----------

_POOL_NAME_RE = re.compile(r"[A-Za-z0-9_.\-一-鿿]+")


def _parse_ymd(value: str, field: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field} 必须是 YYYY-MM-DD 格式") from None


def _validate_pool_name(name: str) -> str:
    """池名最终会进目录名，限制字符集 + 长度防路径穿越。"""
    text = str(name or "").strip()
    if not text or len(text) > 64 or not _POOL_NAME_RE.fullmatch(text):
        raise HTTPException(
            status_code=422,
            detail="股票池名称只能包含中英文、数字、下划线、点和短横线，且不超过 64 个字符",
        )
    return text


def _values(values: List[str]) -> List[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _live_universe() -> live_db.LiveResult:
    try:
        return live_db.live_stock_rows()
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None


def _filtered_universe(live: live_db.LiveResult, **filters: Any) -> List[Dict[str, Any]]:
    try:
        return live_db.filter_universe(live.data, **filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class PoolCreateRequest(BaseModel):
    name: str
    selection_start: str
    selection_end: str
    industries: List[str] = Field(default_factory=list)
    exchanges: List[str] = Field(default_factory=list)
    boards: List[str] = Field(default_factory=list)
    sectors: List[str] = Field(default_factory=list)
    listed_states: List[str] = Field(default_factory=list)
    q: str = ""
    min_listed_days: int = 0
    top_n: Optional[int] = None
    min_coverage: float = 0.0
    exclude_suspended: bool = True
    overwrite: bool = False
    # 预览表格手动勾选的代码；None = 使用筛选结果中的全部可建池股票。
    # 空列表是显式「一只都没选」，返回 422，避免静默退化成全选。
    selected_codes: Optional[List[str]] = None


@app.get("/api/data/master")
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


@app.get("/api/data/fields")
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


@app.get("/api/data/stocks")
def get_stocks(
    q: str = Query("", description="按股票代码或名称匹配"),
    limit: int = Query(0, ge=0, description="0 表示不截断"),
    offset: int = Query(0, ge=0),
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


# ---------- 股票池候选（公司库） ----------


@app.get("/api/universe/options")
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


@app.get("/api/universe/stocks")
def get_universe_stocks(
    industries: List[str] = Query(default=[], description="行业（可重复）"),
    exchanges: List[str] = Query(default=[], description="SH/SZ/BJ/OTHER（可重复）"),
    boards: List[str] = Query(default=[], description="上市板块（可重复）"),
    sectors: List[str] = Query(default=[], description="库内 ListedSector 原值（可重复）"),
    listed_states: List[str] = Query(default=[], description="库内 ListedState 原值（可重复）"),
    q: str = Query("", description="按代码或名称匹配"),
    min_listed_days: int = Query(0, ge=0),
    as_of: str = Query("", description="上市天数截止日 YYYY-MM-DD，缺省今天"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
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


@app.get("/api/universe/codes")
def get_universe_codes(
    industries: List[str] = Query(default=[], description="行业（可重复）"),
    exchanges: List[str] = Query(default=[], description="SH/SZ/BJ/OTHER（可重复）"),
    boards: List[str] = Query(default=[], description="上市板块（可重复）"),
    sectors: List[str] = Query(default=[], description="库内 ListedSector 原值（可重复）"),
    listed_states: List[str] = Query(default=[], description="库内 ListedState 原值（可重复）"),
    q: str = Query("", description="按代码或名称匹配"),
    min_listed_days: int = Query(0, ge=0),
    as_of: str = Query("", description="上市天数截止日 YYYY-MM-DD，缺省今天"),
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


@app.get("/api/operators")
def get_operators() -> Dict[str, Any]:
    items = enrich_operators(list_operators())
    return _sanitize({"total": len(items), "operators": items})


# ---------- 股票池 ----------


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
    if POOLS_ROOT.is_dir():
        for pool_dir in POOLS_ROOT.iterdir():
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
    if FACTOR_RUNS_ROOT.is_dir():
        for run_dir in FACTOR_RUNS_ROOT.iterdir():
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
    if (RESULTS_ROOT / "factor" / pool_id).is_dir():
        warnings.append(
            "该池的历史因子回测结果仍保留在 outputs/saved_backtests/factor/<pool_id>，未删除"
        )
    return warnings


@app.get("/api/pools")
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


@app.get("/api/pools/{pool_id}")
def get_pool(pool_id: str) -> Dict[str, Any]:
    """股票池详情：MySQL 优先，找不到或连不上时回退本地 manifest。"""
    pool_dir = _safe_child(POOLS_ROOT, pool_id)
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
        raise HTTPException(status_code=404, detail=f"pool not found: {pool_id}")
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


@app.delete("/api/pools/{pool_id}")
def delete_pool(
    pool_id: str,
    confirm: bool = Query(False, description="必须显式传 true 才会删除"),
) -> Dict[str, Any]:
    """删除股票池：本地目录 + MySQL 记录；因子运行与历史回测结果保留。"""
    if not confirm:
        raise HTTPException(status_code=400, detail="删除不可恢复：请带 confirm=true 再次请求")
    pool_dir = _safe_child(POOLS_ROOT, pool_id)
    had_local = (pool_dir / "manifest.json").is_file()

    try:
        deleted_mysql = mysql_store.delete_pool(pool_id)
    except Exception:
        logger.warning("删除 MySQL 股票池 %s 失败", pool_id, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="MySQL 股票池删除失败，本地文件未改动；请确认数据库可用后重试",
        ) from None
    mysql_configured = deleted_mysql is not None
    deleted_mysql = bool(deleted_mysql)

    if not had_local and not deleted_mysql:
        raise HTTPException(status_code=404, detail=f"pool not found: {pool_id}")

    deleted_local = False
    if had_local:
        try:
            shutil.rmtree(pool_dir)
            deleted_local = True
        except OSError as exc:
            logger.warning("删除本地股票池 %s 失败", pool_id, exc_info=True)
            raise HTTPException(
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


@app.post("/api/pools", status_code=202)
def create_pool(request: PoolCreateRequest) -> Dict[str, Any]:
    """按公司库筛选结果建池：候选与选样统计全部来自公司 ClickHouse。"""
    name = _validate_pool_name(request.name)
    start = _parse_ymd(request.selection_start, "selection_start")
    end = _parse_ymd(request.selection_end, "selection_end")
    if start > end:
        raise HTTPException(status_code=422, detail="selection_start 不能晚于 selection_end")
    if request.top_n is not None and request.top_n < 1:
        raise HTTPException(status_code=422, detail="top_n 必须为正整数")
    if not 0.0 <= request.min_coverage <= 1.0:
        raise HTTPException(status_code=422, detail="min_coverage 必须在 0 到 1 之间")
    if request.min_listed_days < 0:
        raise HTTPException(status_code=422, detail="min_listed_days 不能为负数")

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
        raise HTTPException(status_code=422, detail="没有股票匹配当前筛选条件")

    # 预览表格手动勾选：只接受当前筛选结果中的代码。
    # None = 未手动选择（沿用全部匹配股票）；空列表 = 显式一只都没选，必须报错。
    selection_mode = "all"
    selection_requested: Optional[set[str]] = None
    selected = matched
    if request.selected_codes is not None:
        selection_mode = "manual"
        if not any(str(value).strip() for value in request.selected_codes):
            raise HTTPException(status_code=422, detail="请至少勾选一只股票")
        selection_requested = {
            code
            for code in (normalize_code(value) for value in request.selected_codes)
            if code
        }
        if not selection_requested:
            raise HTTPException(status_code=422, detail="勾选的股票代码无效")
        selected = [item for item in matched if item["code"] in selection_requested]
        if not selected:
            raise HTTPException(
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
        "pools_root": str(POOLS_ROOT),
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
        job_dir = create_platform_job(JOBS_ROOT, "create_pool", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise HTTPException(status_code=500, detail=f"创建建池任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise HTTPException(
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


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    """平台任务状态（create_pool 等），前端轮询用。"""
    job_dir = _safe_child(JOBS_ROOT, job_id)
    status_path = job_dir / "status.json"
    if not status_path.is_file():
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    try:
        status = _read_json(status_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"读取任务状态失败：{exc}") from None
    status.setdefault("job_id", job_id)
    return _sanitize(status)


# ---------- 因子运行 / 因子批量回测 ----------


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            rows.append(record)
    return rows


def _manifest_or_404(run_dir: Path, file_name: str, label: str) -> Dict[str, Any]:
    path = run_dir / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} not found: {run_dir.name}")
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"读取 {label} 失败：{exc}") from None
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=500, detail=f"{label} 格式无效：{path}")
    return manifest


def _factor_run_summary(run_dir: Path) -> Dict[str, Any]:
    manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    accepted_path = run_dir / "accepted_factors.jsonl"
    accepted_count = manifest.get("accepted_count")
    if accepted_path.is_file():
        accepted_count = sum(1 for line in accepted_path.read_text(encoding="utf-8").splitlines() if line.strip())
    created_at = manifest.get("created_at")
    if not created_at:
        created_at = datetime.fromtimestamp(
            (run_dir / "factor_run.json").stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
    return {
        "run_id": run_dir.name,
        "pool_id": manifest.get("pool_id"),
        "data_source": manifest.get("data_source") or "local",
        "source_signature": manifest.get("source_signature"),
        "runtime_id": manifest.get("runtime_id"),
        "created_at": created_at,
        "accepted_count": int(accepted_count or 0),
        "attempts": manifest.get("attempts"),
        "target_reached": manifest.get("target_reached"),
        "attempts_exhausted": manifest.get("attempts_exhausted"),
        "factor_run_dir": str(run_dir),
        "has_accepted": (run_dir / "accepted_factors.jsonl").is_file(),
    }


def _factor_run_dir(run_id: str) -> Path:
    run_dir = _safe_child(FACTOR_RUNS_ROOT, run_id)
    if not (run_dir / "factor_run.json").is_file():
        raise HTTPException(status_code=404, detail=f"factor run not found: {run_id}")
    return run_dir


def _accepted_factor_rows(run_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(_read_jsonl(run_dir / "accepted_factors.jsonl"), start=1):
        expression = str(record.get("expression") or "").strip()
        rows.append(
            {
                "factor_id": factor_id_for(index, expression) if expression else f"factor_{index:04d}",
                "expression": expression,
                "canonical_expression": record.get("canonical_expression"),
                "backtest_expression": record.get("backtest_expression"),
                "ic": record.get("ic"),
                "rank_ic": record.get("rank_ic"),
                "icir": record.get("icir"),
                "coverage": record.get("coverage"),
                "score": record.get("score"),
                "reason": record.get("reason"),
            }
        )
    return rows


def _factor_batch_dir(factor_run_id: str, backtest_id: str, pool_id: Optional[str] = None) -> Path:
    run_dir = _factor_run_dir(factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    run_pool_id = str(run_manifest.get("pool_id") or "").strip()
    if not run_pool_id:
        raise HTTPException(status_code=422, detail="该因子运行缺少 pool_id，无法定位回测结果")
    if pool_id and pool_id != run_pool_id:
        raise HTTPException(
            status_code=422,
            detail=f"factor run 的 pool_id {run_pool_id!r} 与请求的 pool_id {pool_id!r} 不一致",
        )
    pool_dir = _safe_child(RESULTS_ROOT / "factor", run_pool_id)
    run_result_dir = _safe_child(pool_dir, factor_run_id)
    batch_dir = _safe_child(run_result_dir, backtest_id)
    if not (batch_dir / "factor_backtest_manifest.json").is_file():
        raise HTTPException(status_code=404, detail=f"factor backtest not found: {backtest_id}")
    return batch_dir


def _batch_summary(batch_dir: Path) -> Dict[str, Any]:
    manifest = _manifest_or_404(batch_dir, "factor_backtest_manifest.json", "factor backtest")
    created_at = manifest.get("created_at")
    if not created_at:
        created_at = datetime.fromtimestamp(
            (batch_dir / "factor_backtest_manifest.json").stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
    return {
        "backtest_id": manifest.get("backtest_id") or batch_dir.name,
        "job_id": manifest.get("job_id"),
        "factor_run_id": manifest.get("factor_run_id") or batch_dir.parent.name,
        "pool_id": manifest.get("pool_id"),
        "data_source": manifest.get("data_source") or "local",
        "created_at": created_at,
        "accepted_count": manifest.get("accepted_count"),
        "selected_count": manifest.get("selected_count"),
        "completed": manifest.get("completed"),
        "failed": manifest.get("failed"),
        "start_date": manifest.get("start_date"),
        "end_date": manifest.get("end_date"),
        "top_k": manifest.get("top_k"),
        "initial_cash": manifest.get("initial_cash"),
        "run_key_prefix": manifest.get("run_key_prefix"),
        "summary_file": manifest.get("summary_file") or "factor_backtest_summary.csv",
        "failures_file": manifest.get("failures_file") or "factor_backtest_failures.csv",
        "output_dir": str(batch_dir),
    }


def _csv_records(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        frame = pd.read_csv(path)
        return json.loads(frame.to_json(orient="records", force_ascii=False))
    except pd.errors.EmptyDataError:
        # 没有失败因子时 pandas 写出的 failures.csv 只有一个空行
        return []
    except Exception as exc:  # noqa: BLE001 - 损坏的 CSV 直接带出原因
        raise HTTPException(status_code=500, detail=f"读取 {path.name} 失败：{exc}") from None


class FactorBacktestRequest(BaseModel):
    factor_run_id: str
    factor_ids: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top_k: int = 50
    initial_cash: float = 100_000_000.0
    buy_cost: float = 0.0015
    sell_cost: float = 0.0015
    slippage: float = 0.0005
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.02


def _cache_ymd(value: Any) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _factor_run_panel_bounds(run_manifest: Dict[str, Any]) -> tuple[Optional[date], Optional[date]]:
    """因子运行实际用到的面板日期区间（优先于全库区间，避免默认回测跑到 1990 年）。"""
    path = str(run_manifest.get("runtime_manifest") or "").strip()
    if not path:
        return None, None
    try:
        runtime = _read_json(Path(path))
    except (OSError, json.JSONDecodeError):
        return None, None
    panel = runtime.get("panel") if isinstance(runtime, dict) else None
    if not isinstance(panel, dict):
        return None, None
    return _cache_ymd(panel.get("date_min")), _cache_ymd(panel.get("date_max"))


@app.get("/api/factor-runs")
def get_factor_runs(pool_id: Optional[str] = Query(None, description="按股票池过滤")) -> Dict[str, Any]:
    """列出本地 factor_runs 目录下已完成的因子生成运行。"""
    runs: List[Dict[str, Any]] = []
    if FACTOR_RUNS_ROOT.is_dir():
        for run_dir in FACTOR_RUNS_ROOT.iterdir():
            if not run_dir.is_dir() or not (run_dir / "factor_run.json").is_file():
                continue
            try:
                summary = _factor_run_summary(run_dir)
            except HTTPException:
                continue
            if pool_id and summary.get("pool_id") != pool_id:
                continue
            runs.append(summary)
    runs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return _sanitize({"total": len(runs), "runs": runs})


@app.get("/api/factor-runs/{run_id}")
def get_factor_run(run_id: str) -> Dict[str, Any]:
    """因子运行详情 + 合格因子清单（factor_id 与回测批次保持一致）。"""
    run_dir = _factor_run_dir(run_id)
    summary = _factor_run_summary(run_dir)
    accepted = _accepted_factor_rows(run_dir)
    manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    return _sanitize(
        {
            **summary,
            "accepted_count": len(accepted),
            "manifest": manifest,
            "accepted_factors": accepted,
        }
    )


@app.post("/api/factor-backtests", status_code=202)
def create_factor_backtest(request: FactorBacktestRequest) -> Dict[str, Any]:
    """把某个因子运行的全部/选定合格因子提交为后台批量回测任务。"""
    if request.top_k < 1 or request.top_k > 1000:
        raise HTTPException(status_code=422, detail="top_k 必须在 1 到 1000 之间")
    if request.initial_cash <= 0:
        raise HTTPException(status_code=422, detail="initial_cash 必须大于 0")
    for name, value in (
        ("buy_cost", request.buy_cost),
        ("sell_cost", request.sell_cost),
        ("slippage", request.slippage),
    ):
        if not 0.0 <= value <= 0.1:
            raise HTTPException(status_code=422, detail=f"{name} 必须在 0 到 0.1 之间")
    if request.min_cost < 0:
        raise HTTPException(status_code=422, detail="min_cost 不能为负数")
    if not 0.0 < request.max_weight_per_stock <= 1.0:
        raise HTTPException(status_code=422, detail="max_weight_per_stock 必须在 0 到 1 之间")

    run_dir = _factor_run_dir(request.factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    pool_id = str(run_manifest.get("pool_id") or "").strip()
    if not pool_id:
        raise HTTPException(status_code=422, detail="该因子运行缺少 pool_id，无法回测")
    pool_dir = _safe_child(POOLS_ROOT, pool_id)
    pool_manifest = _manifest_or_404(pool_dir, "manifest.json", "pool")
    source = company_source.resolve_data_source(
        run_manifest.get("data_source") or pool_manifest.get("data_source")
    )
    if source == "clickhouse":
        source_meta = company_source.meta()
    else:
        source_meta = load_meta(MASTER_DIR) or {}
        if not source_meta:
            raise HTTPException(
                status_code=503,
                detail="本地主缓存未就绪：请先运行 prepare_master 导入 data_cache/master",
            )
    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise HTTPException(
            status_code=422,
            detail="股票池与数据源签名不一致，请重新建池后再回测",
        )
    run_signature = run_manifest.get("source_signature")
    if run_signature not in (None, source_signature):
        raise HTTPException(
            status_code=422,
            detail="因子运行与数据源签名不一致，请重新生成因子后再回测",
        )

    accepted = _accepted_factor_rows(run_dir)
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail="该因子运行没有合格因子（accepted_factors.jsonl 为空），请先生成因子",
        )
    available_ids = [row["factor_id"] for row in accepted]
    selected_ids: Optional[List[str]] = None
    if request.factor_ids is not None:
        requested = {str(value).strip() for value in request.factor_ids if str(value).strip()}
        if not requested:
            raise HTTPException(status_code=422, detail="请至少选择一个因子")
        unknown = sorted(requested - set(available_ids))
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"{len(unknown)} 个因子不在该运行中（示例：{'、'.join(unknown[:5])}），请刷新后重试",
            )
        selected_ids = [factor_id for factor_id in available_ids if factor_id in requested]

    source_start = _cache_ymd(source_meta.get("date_min"))
    source_end = _cache_ymd(source_meta.get("date_max"))
    panel_start, panel_end = _factor_run_panel_bounds(run_manifest)
    default_start = panel_start or source_start
    default_end = panel_end or source_end
    start = _parse_ymd(request.start_date, "start_date") if request.start_date else default_start
    end = _parse_ymd(request.end_date, "end_date") if request.end_date else default_end
    if start is None or end is None:
        raise HTTPException(
            status_code=422,
            detail="无法确定回测区间：数据源缺少日期范围，请显式传入 start_date/end_date",
        )
    if start > end:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    if source_start and source_end and (end < source_start or start > source_end):
        raise HTTPException(
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
    payload: Dict[str, Any] = {
        "master_store": str(MASTER_DIR),
        "data_source": source,
        "pools_root": str(POOLS_ROOT),
        "factor_run_dir": str(run_dir),
        "outputs_root": str(RESULTS_ROOT),
        "backtest_config": backtest_config,
        "expected_pool_id": pool_id,
    }
    if selected_ids is not None:
        payload["factor_ids"] = selected_ids

    try:
        job_dir = create_platform_job(JOBS_ROOT, "backtest_factors", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise HTTPException(status_code=500, detail=f"创建因子回测任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise HTTPException(
            status_code=500, detail=f"因子回测任务已创建但启动失败：{exc}"
        ) from None

    return _sanitize(
        {
            "job_id": job_dir.name,
            "backtest_id": job_dir.name,
            "status": "queued",
            "operation": "backtest_factors",
            "factor_run_id": request.factor_run_id,
            "pool_id": pool_id,
            "data_source": source,
            "accepted_total": len(accepted),
            "selected_total": len(selected_ids) if selected_ids is not None else len(accepted),
            "warnings": warnings,
            "request_summary": {
                "factor_run_id": request.factor_run_id,
                "pool_id": pool_id,
                "factor_ids": selected_ids,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "top_k": request.top_k,
                "initial_cash": request.initial_cash,
                "buy_cost": request.buy_cost,
                "sell_cost": request.sell_cost,
                "slippage": request.slippage,
                "min_cost": request.min_cost,
                "max_weight_per_stock": request.max_weight_per_stock,
            },
        }
    )


@app.get("/api/factor-backtests")
def get_factor_backtests(
    factor_run_id: str = Query(..., description="因子运行目录名"),
    pool_id: Optional[str] = Query(None, description="可选：校验股票池"),
) -> Dict[str, Any]:
    """列出某个因子运行下所有批次回测（按创建时间倒序）。"""
    run_dir = _factor_run_dir(factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    run_pool_id = str(run_manifest.get("pool_id") or "").strip()
    if pool_id and pool_id != run_pool_id:
        raise HTTPException(status_code=422, detail="factor run 与 pool_id 不匹配")
    batches: List[Dict[str, Any]] = []
    if run_pool_id:
        try:
            pool_dir = _safe_child(RESULTS_ROOT / "factor", run_pool_id)
            run_result_dir = _safe_child(pool_dir, factor_run_id)
        except HTTPException:
            raise
        if run_result_dir.is_dir():
            for batch_dir in run_result_dir.iterdir():
                if not batch_dir.is_dir() or not (batch_dir / "factor_backtest_manifest.json").is_file():
                    continue
                try:
                    batches.append(_batch_summary(batch_dir))
                except HTTPException:
                    continue
    batches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return _sanitize({"total": len(batches), "batches": batches})


@app.get("/api/factor-backtests/{backtest_id}")
def get_factor_backtest(
    backtest_id: str,
    factor_run_id: str = Query(..., description="因子运行目录名"),
    pool_id: Optional[str] = Query(None, description="可选：校验股票池"),
) -> Dict[str, Any]:
    """批次详情：汇总行 + 失败行；每行带可打开的单因子结果 run_key。"""
    batch_dir = _factor_batch_dir(factor_run_id, backtest_id, pool_id)
    batch = _batch_summary(batch_dir)
    prefix = str(batch.get("run_key_prefix") or f"factor/{batch.get('pool_id')}/{factor_run_id}/{backtest_id}")
    rows = _csv_records(batch_dir / str(batch["summary_file"]))
    for row in rows:
        factor_value = row.get("factor_id")
        if factor_value:
            row["run_key"] = f"{prefix}/{factor_value}"
    failures = _csv_records(batch_dir / str(batch["failures_file"]))
    return _sanitize(
        {
            "batch": batch,
            "rows": rows,
            "failures": failures,
        }
    )


@app.get("/api/factor-backtests/{backtest_id}/files/{file_name}")
def download_factor_backtest_file(
    backtest_id: str,
    file_name: str,
    factor_run_id: str = Query(..., description="因子运行目录名"),
    pool_id: Optional[str] = Query(None, description="可选：校验股票池"),
) -> FileResponse:
    batch_dir = _factor_batch_dir(factor_run_id, backtest_id, pool_id)
    allowed = {"factor_backtest_summary.csv", "factor_backtest_failures.csv", "factor_backtest_manifest.json"}
    if file_name not in allowed:
        raise HTTPException(status_code=404, detail=f"file not allowed: {file_name}")
    file_path = _safe_child(batch_dir, file_name)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {file_name}")
    return FileResponse(file_path, filename=file_name)


# ---------- 手动回测 ----------


class ManualBacktestRequest(BaseModel):
    expression: str
    pool_id: str
    run_name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    top_k: int = 50
    initial_cash: float = 100_000_000.0
    buy_cost: float = 0.0015
    sell_cost: float = 0.0015
    slippage: float = 0.0005
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.02


def _validate_manual_expression(expression: str) -> str:
    """统一算子别名，并在提交时先做语法 / 字段 / 算子校验。"""
    try:
        normalized = normalize_manual_expression(expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        _validate_ast(
            normalized,
            {name: None for name in company_source.panel_field_names()},
        )
    except ExpressionError as exc:
        raise HTTPException(status_code=422, detail=f"Alpha 表达式无效：{exc}") from None
    return normalized


@app.post("/api/manual-backtests", status_code=202)
def create_manual_backtest(request: ManualBacktestRequest) -> Dict[str, Any]:
    """按股票池 + Alpha 表达式提交一次手动回测（后台任务）。"""
    if request.top_k < 1 or request.top_k > 1000:
        raise HTTPException(status_code=422, detail="top_k 必须在 1 到 1000 之间")
    if request.initial_cash <= 0:
        raise HTTPException(status_code=422, detail="initial_cash 必须大于 0")
    for name, value in (
        ("buy_cost", request.buy_cost),
        ("sell_cost", request.sell_cost),
        ("slippage", request.slippage),
    ):
        if not 0.0 <= value <= 0.1:
            raise HTTPException(status_code=422, detail=f"{name} 必须在 0 到 0.1 之间")
    if request.min_cost < 0:
        raise HTTPException(status_code=422, detail="min_cost 不能为负数")
    if not 0.0 < request.max_weight_per_stock <= 1.0:
        raise HTTPException(status_code=422, detail="max_weight_per_stock 必须在 0 到 1 之间")

    try:
        run_name = validate_run_name(request.run_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    expression = _validate_manual_expression(request.expression)

    pool_dir = _safe_child(POOLS_ROOT, request.pool_id)
    pool_manifest = _manifest_or_404(pool_dir, "manifest.json", "pool")
    source = company_source.resolve_data_source(None, pool_manifest)
    if source == "clickhouse":
        try:
            source_meta = company_source.meta()
        except live_db.LiveDBError as exc:
            raise _live_error(exc) from None
    else:
        source_meta = load_meta(MASTER_DIR)
        if not source_meta:
            raise HTTPException(
                status_code=503,
                detail="本地主缓存未就绪：请先运行 prepare_master 导入 data_cache/master",
            )
    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise HTTPException(
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
        raise HTTPException(
            status_code=422,
            detail="无法确定回测区间：股票池或数据源缺少日期范围，请显式传入 start_date/end_date",
        )
    if start > end:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    if source_start and source_end and (end < source_start or start > source_end):
        raise HTTPException(
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
        "pools_root": str(POOLS_ROOT),
        "output_root": str(RESULTS_ROOT),
        "master_store": str(MASTER_DIR),
        "pool_id": request.pool_id,
        "data_source": source,
        "run_name": run_name,
        "expression": expression,
        "backtest_config": backtest_config,
    }

    try:
        job_dir = create_platform_job(JOBS_ROOT, "manual_backtest", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise HTTPException(status_code=500, detail=f"创建手动回测任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise HTTPException(
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


# ---------- 结果 ----------


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


@app.get("/api/results")
def get_results() -> Dict[str, Any]:
    runs = list_runs(RESULTS_ROOT)
    return _sanitize({"total": len(runs), "results": [_result_summary(run) for run in runs]})


def _result_detail_payload(run_dir: Path, run_key: str) -> Dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"result not found: {run_key}")
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"读取结果 manifest 失败：{exc}") from None
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


def _result_file(run_dir: Path, run_key: str, file_name: str) -> FileResponse:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"result not found: {run_key}")
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"读取结果 manifest 失败：{exc}") from None
    if file_name not in (manifest.get("files") or []):
        raise HTTPException(status_code=404, detail=f"file not allowed: {file_name}")
    file_path = _safe_child(run_dir, file_name)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {file_name}")
    return FileResponse(file_path, filename=file_name)


# 静态子路径必须声明在 /api/results/{run_name} 之前，否则会被当作 run_name
@app.get("/api/results/detail")
def get_result_by_key(run_key: str = Query(..., description="结果相对路径，如 factor/pool/run/backtest_id/factor_xxx")) -> Dict[str, Any]:
    run_dir = _safe_relative(RESULTS_ROOT, run_key)
    return _result_detail_payload(run_dir, run_key)


@app.get("/api/results/file")
def download_result_file_by_key(
    run_key: str = Query(..., description="结果相对路径"),
    file_name: str = Query(..., description="manifest 中列出的文件名"),
) -> FileResponse:
    run_dir = _safe_relative(RESULTS_ROOT, run_key)
    return _result_file(run_dir, run_key, file_name)


@app.get("/api/results/{run_name}")
def get_result(run_name: str) -> Dict[str, Any]:
    """兼容旧的扁平结果名（如 web_run）；嵌套因子结果请用 /api/results/detail?run_key=。"""
    run_dir = _safe_child(RESULTS_ROOT, run_name)
    return _result_detail_payload(run_dir, run_name)


@app.get("/api/results/{run_name}/files/{file_name}")
def download_result_file(run_name: str, file_name: str) -> FileResponse:
    run_dir = _safe_child(RESULTS_ROOT, run_name)
    return _result_file(run_dir, run_name, file_name)
