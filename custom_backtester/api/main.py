"""FastAPI 应用：把 custom_bt 现有的数据 / 结果入口暴露给 React 原型。

覆盖数据总览、数据字段、股票列表、操作符、股票池、结果详情，以及股票池候选
（/api/universe/*）与建池任务（POST /api/pools + /api/jobs/{job_id}）。

数据总览 / 数据字段 / 股票列表 / 股票池候选走 ClickHouse 实时查询
（api/live_db.py）；算子、股票池文件、回测结果与回测链路仍读本地 data_cache / outputs。
建池任务在后台子进程里执行（api/job_runner.py），状态写 outputs/jobs/*/status.json。

所有响应统一走 _sanitize：把 NaN / Infinity 转成 null，
否则 Starlette 序列化会直接抛错（allow_nan=False）。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
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
from custom_bt.data import load_meta, normalize_code  # noqa: E402
from custom_bt.docs import enrich_fields, enrich_operators  # noqa: E402
from custom_bt.expressions import list_operators  # noqa: E402
from custom_bt.factor_backtest import factor_id as factor_id_for  # noqa: E402
from custom_bt.jobs import update_job_status  # noqa: E402
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
    allow_methods=["GET", "POST"],
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
    return {"ok": True, "service": "custom-backtester-api"}


# ---------- 数据（ClickHouse 实时） ----------


def _live_error(exc: live_db.LiveDBError) -> HTTPException:
    """实时数据源异常 → HTTP 状态码（缺配置 / 连不上 / 认证失败 = 503，查询失败 = 502）。"""
    if isinstance(exc, (live_db.LiveDBConfigError, live_db.LiveDBUnavailable)):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _local_field_names() -> set:
    """本地主缓存里的字段名集合（用于给字段打「面板可用」标记）。"""
    meta = load_meta(MASTER_DIR) or {}
    return {str(name) for name in (meta.get("fields") or [])}


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


def _master_code_set() -> set[str]:
    """本地主缓存里实际有 parquet 的股票代码集合。"""
    stock_dir = MASTER_DIR / "stocks"
    if not stock_dir.is_dir():
        return set()
    return {normalize_code(path.stem) for path in stock_dir.glob("*.parquet")}


def _master_snapshot() -> tuple[Dict[str, Any], set[str]]:
    return load_meta(MASTER_DIR) or {}, _master_code_set()


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


def _excluded_examples(
    matched: List[Dict[str, Any]], master_codes: set[str], limit: int = 10
) -> List[Dict[str, Any]]:
    examples = [
        {"code": item["code"], "name": item.get("name")}
        for item in matched
        if item["code"] not in master_codes
    ]
    return examples[:limit]


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
    # 回测 / 股票池仍用本地主缓存快照，这里附带缓存口径，避免「区间 1990 起」被误读
    cache_meta = load_meta(MASTER_DIR) or {}
    return _sanitize(
        {
            "ready": True,
            "store_dir": live_db.target_label(),
            "rows": stats.data["rows"],
            "n_stocks": stats.data["n_stocks"],
            "date_min": stats.data["date_min"],
            "date_max": stats.data["date_max"],
            "layout": "clickhouse-live",
            "source_signature": None,
            "n_fields": len(catalog.data),
            "fields": [item["name"] for item in catalog.data],
            "cached": stats.cached and catalog.cached,
            "queried_at": max(stats.queried_at, catalog.queried_at),
            "cache_date_min": cache_meta.get("date_min"),
            "cache_date_max": cache_meta.get("date_max"),
            "cache_rows": cache_meta.get("rows"),
            "cache_n_stocks": cache_meta.get("n_stocks"),
        }
    )


@app.get("/api/data/fields")
def get_fields() -> Dict[str, Any]:
    try:
        catalog = live_db.live_field_catalog()
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None
    local_fields = _local_field_names()
    enriched = enrich_fields(
        [{"name": item["name"], "dtype": item["dtype"]} for item in catalog.data],
        FIELD_DOC_PATH,
    )
    fields: List[Dict[str, Any]] = []
    for item, entry in zip(enriched, catalog.data):
        description = item["description"]
        if description == "暂无字段说明" and entry["comment"]:
            description = entry["comment"]  # 文档没写时用库内注释兜底
        if entry["name"] == "vol":
            description = f"{description}（回测面板中名为 volume）"
        fields.append(
            {
                "name": item["name"],
                "dtype": item["dtype"],
                "source": live_db.source_label(item["source"], entry["table"]),
                "description": description,
                "panel": live_db.panel_alias(entry["name"]) in local_fields,
            }
        )
    return _sanitize(
        {
            "total": len(fields),
            "fields": fields,
            "cached": catalog.cached,
            "queried_at": catalog.queried_at,
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
    """全库行业/市场/板块分布 + 本地主缓存覆盖统计。"""
    live = _live_universe()
    meta, master_codes = _master_snapshot()
    data = live_db.aggregate_universe(live.data, master_codes)
    return _sanitize(
        {
            **data,
            "master_ready": bool(master_codes) and bool(meta),
            "cache_date_min": meta.get("date_min"),
            "cache_date_max": meta.get("date_max"),
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
    master_only: bool = Query(False, description="只返回本地主缓存可建池的股票"),
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
    meta, master_codes = _master_snapshot()
    creatable = [item for item in matched if item["code"] in master_codes]
    base = creatable if master_only else matched
    page = [
        {**item, "creatable": item["code"] in master_codes}
        for item in base[offset : offset + limit]
    ]
    return _sanitize(
        {
            "total": len(base),
            "matched_total": len(matched),
            "n_creatable": len(creatable),
            "n_excluded": len(matched) - len(creatable),
            "excluded_examples": _excluded_examples(matched, master_codes),
            "items": page,
            "master_ready": bool(master_codes) and bool(meta),
            "master_total": len(master_codes),
            "cache_date_min": meta.get("date_min"),
            "cache_date_max": meta.get("date_max"),
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
    master_only: bool = Query(True, description="只返回本地主缓存可建池的股票"),
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
    meta, master_codes = _master_snapshot()
    creatable = [item for item in matched if item["code"] in master_codes]
    base = creatable if master_only else matched
    return _sanitize(
        {
            "codes": sorted(item["code"] for item in base),
            "total": len(base),
            "matched_total": len(matched),
            "n_creatable": len(creatable),
            "master_ready": bool(master_codes) and bool(meta),
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


def _pool_summary(pool_dir: Path) -> Optional[Dict[str, Any]]:
    manifest_path = pool_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return None
    stats = manifest.get("selected_stats") or []
    coverage = (
        sum(float(item.get("coverage") or 0.0) for item in stats) / len(stats) if stats else None
    )
    avg_amount = (
        sum(float(item.get("average_amount") or 0.0) for item in stats) / len(stats)
        if stats
        else None
    )
    created_at = datetime.fromtimestamp(manifest_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return {
        "pool_id": manifest.get("pool_id", pool_dir.name),
        "name": manifest.get("name"),
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


@app.get("/api/pools")
def get_pools() -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    if POOLS_ROOT.is_dir():
        for pool_dir in POOLS_ROOT.iterdir():
            if not pool_dir.is_dir():
                continue
            summary = _pool_summary(pool_dir)
            if summary is not None:
                summaries.append(summary)
    summaries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return _sanitize({"total": len(summaries), "pools": summaries})


@app.get("/api/pools/{pool_id}")
def get_pool(pool_id: str) -> Dict[str, Any]:
    pool_dir = _safe_child(POOLS_ROOT, pool_id)
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
        }
    )


@app.post("/api/pools", status_code=202)
def create_pool(request: PoolCreateRequest) -> Dict[str, Any]:
    """按公司库筛选结果建池：候选与本地主缓存取交集后提交平台任务。"""
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

    meta, master_codes = _master_snapshot()
    if not meta or not master_codes:
        raise HTTPException(
            status_code=503,
            detail="本地主缓存未就绪：请先运行 prepare_master 导入 data_cache/master",
        )
    cache_start_text = live_db.parse_listed_date(meta.get("date_min"))
    cache_end_text = live_db.parse_listed_date(meta.get("date_max"))
    cache_start = date.fromisoformat(cache_start_text) if cache_start_text else None
    cache_end = date.fromisoformat(cache_end_text) if cache_end_text else None
    if cache_start and cache_end and (end < cache_start or start > cache_end):
        raise HTTPException(
            status_code=422,
            detail=(
                f"筛选窗口与本地主缓存（{cache_start_text} ~ {cache_end_text}）没有交集；"
                "回测数据仍使用本地快照"
            ),
        )

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
    creatable = [item for item in matched if item["code"] in master_codes]
    if not creatable:
        samples = "、".join(item["code"] for item in matched[:10])
        raise HTTPException(
            status_code=422,
            detail=(
                f"匹配的 {len(matched)} 只股票都不在本地主缓存中"
                f"（示例：{samples}）；请先导入主缓存或放宽筛选"
            ),
        )

    # 预览表格手动勾选：只接受当前筛选结果 ∩ 本地主缓存中的代码。
    # None = 未手动选择（沿用全部可建池股票）；空列表 = 显式一只都没选，必须报错。
    selection_mode = "all"
    selection_requested: Optional[set[str]] = None
    selected = creatable
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
        selected = [item for item in creatable if item["code"] in selection_requested]
        if not selected:
            matched_codes = {item["code"] for item in matched}
            if not (selection_requested & matched_codes):
                raise HTTPException(
                    status_code=422,
                    detail="勾选的股票都不在当前筛选结果中，请刷新预览后重试",
                )
            raise HTTPException(
                status_code=422,
                detail="勾选的股票都不在本地主缓存中，无法建池",
            )

    examples = _excluded_examples(matched, master_codes)
    excluded_total = len(matched) - len(creatable)
    warnings: List[str] = []
    if excluded_total:
        sample_text = "、".join(
            f"{item['code']} {item.get('name') or ''}".strip() for item in examples[:5]
        )
        warnings.append(
            f"{excluded_total} 只匹配股票不在本地主缓存，已自动排除"
            + (f"（示例：{sample_text}）" if sample_text else "")
        )
    if selection_mode == "manual" and selection_requested is not None:
        matched_codes = {item["code"] for item in matched}
        creatable_codes = {item["code"] for item in creatable}
        stale = selection_requested - matched_codes
        no_cache = (selection_requested & matched_codes) - creatable_codes
        if stale:
            warnings.append(
                f"{len(stale)} 只已勾选股票不在当前筛选结果中，已忽略（请刷新预览后重试）"
            )
        if no_cache:
            warnings.append(f"{len(no_cache)} 只已勾选股票不在本地主缓存，已排除")
    if request.top_n is not None and len(selected) < request.top_n:
        warnings.append(
            f"本次候选 {len(selected)} 只，少于 TopN {request.top_n}；"
            "将按实际可建数量创建"
        )
    if cache_end and end > cache_end:
        warnings.append(
            f"筛选窗口末端 {end.isoformat()} 晚于本地主缓存最新日期 {cache_end_text}，"
            f"回测数据只到 {cache_end_text}"
        )
    if cache_start and start < cache_start:
        warnings.append(
            f"筛选窗口起始 {start.isoformat()} 早于本地主缓存最早日期 {cache_start_text}，"
            "将按缓存可用区间计算"
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
        "creatable_total": len(creatable),
        "excluded_total": excluded_total,
        "excluded_examples": examples,
        "selection_mode": selection_mode,
        "selected_total": len(selected),
    }
    payload = {
        "store_dir": str(MASTER_DIR),
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
                "creatable_total": len(creatable),
                "excluded_total": excluded_total,
                "excluded_examples": examples,
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
    meta = load_meta(MASTER_DIR) or {}
    if not meta:
        raise HTTPException(
            status_code=503,
            detail="本地主缓存未就绪：请先运行 prepare_master 导入 data_cache/master",
        )
    master_signature = meta.get("source_signature")
    if pool_manifest.get("source_signature") != master_signature:
        raise HTTPException(
            status_code=422,
            detail="股票池与本地主缓存数据签名不一致，请重新建池后再回测",
        )
    run_signature = run_manifest.get("source_signature")
    if run_signature not in (None, master_signature):
        raise HTTPException(
            status_code=422,
            detail="因子运行与本地主缓存数据签名不一致，请重新生成因子后再回测",
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

    cache_start = _cache_ymd(meta.get("date_min"))
    cache_end = _cache_ymd(meta.get("date_max"))
    start = _parse_ymd(request.start_date, "start_date") if request.start_date else cache_start
    end = _parse_ymd(request.end_date, "end_date") if request.end_date else cache_end
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="无法确定回测区间：主缓存缺少日期范围，请显式传入 start_date/end_date")
    if start > end:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    if cache_start and cache_end and (end < cache_start or start > cache_end):
        raise HTTPException(
            status_code=422,
            detail=(
                f"回测区间与本地主缓存（{cache_start.isoformat()} ~ {cache_end.isoformat()}）"
                "没有交集"
            ),
        )
    warnings: List[str] = []
    if cache_start and start < cache_start:
        warnings.append(f"回测起点早于本地主缓存 {cache_start.isoformat()}，将按缓存可用区间计算")
    if cache_end and end > cache_end:
        warnings.append(f"回测终点晚于本地主缓存 {cache_end.isoformat()}，将按缓存可用区间计算")

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


# ---------- 结果 ----------


def _result_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    config = run.get("config") or {}
    backtest = config.get("backtest") or {}
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
    backtest = config.get("backtest") or {}

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
