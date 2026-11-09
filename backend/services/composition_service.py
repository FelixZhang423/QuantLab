"""因子组合任务提交与结果查询。"""
from __future__ import annotations

import logging
import math
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import common
from common import _cache_ymd, _live_error, _parse_ymd, _read_json, _safe_child, _sanitize
from errors import make_error
from repositories import clickhouse as live_db
from repositories import company_source
from repositories.factor_run_store import confirmed_records
from repositories.job_store import update_job_status
from repositories.snapshot_store import snapshot_manifest
from schemas import FactorCompositionRequest
from services.generation_service import _generation_pool_source
from workers.job_dispatcher import create_platform_job
from workers.job_runner import spawn_platform_job


_REBALANCE_FREQS = {"1D", "1W", "2W", "1M"}

logger = logging.getLogger(__name__)

# 选股清单的股票名称只用于展示，按 TTL 缓存；查询失败时短暂负缓存，
# 避免公司库不可用时每个 /screen 请求都等一次连接超时。
_NAME_CACHE_TTL = 600.0
_NAME_FAILURE_TTL = 60.0
_name_cache: Optional[tuple[float, Dict[str, str]]] = None
_name_failed_at = 0.0


def _saved_results_root() -> Path:
    root = Path(common.RESULTS_ROOT).expanduser().resolve()
    return root if root.name == "saved_backtests" else root / "saved_backtests"


def _composite_root() -> Path:
    return _saved_results_root() / "composite"


def _factor_run_dir(run_id: str) -> Path:
    run_dir = _safe_child(common.FACTOR_RUNS_ROOT, run_id)
    if not (run_dir / "factor_run.json").is_file():
        raise make_error(status_code=404, detail=f"因子运行不存在：{run_id}")
    return run_dir


def _run_manifest(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "factor_run.json"
    try:
        manifest = _read_json(path)
    except (OSError, ValueError) as exc:
        raise make_error(status_code=500, detail=f"读取因子运行清单失败：{exc}") from None
    if not isinstance(manifest, dict):
        raise make_error(status_code=500, detail=f"因子运行清单格式无效：{path}")
    return manifest


def _confirmed_factor_rows(run_dir: Path) -> List[Dict[str, Any]]:
    path = run_dir / "confirmation_manifest.json"
    status = _read_json(path).get("status") if path.is_file() else None
    if status != "finished":
        raise make_error(
            status_code=422,
            detail=f"因子运行 {run_dir.name} 尚未完成测试集确认，请先执行确认任务",
        )
    try:
        rows = confirmed_records(run_dir)
    except ValueError as exc:
        raise make_error(status_code=422, detail=f"因子运行 {run_dir.name}：{exc}") from None
    if not rows:
        raise make_error(
            status_code=422,
            detail=f"因子运行 {run_dir.name} 没有 confirmed 因子，请先生成并确认因子",
        )
    return rows


def _validate_composition_parameters(request: FactorCompositionRequest) -> Dict[str, Any]:
    if request.top_k < 1 or request.top_k > 1000:
        raise make_error(status_code=422, detail="top_k 必须在 1 到 1000 之间")
    if not math.isfinite(request.initial_cash) or request.initial_cash <= 0:
        raise make_error(status_code=422, detail="initial_cash 必须大于 0")
    for name, value in (
        ("buy_cost", request.buy_cost),
        ("sell_cost", request.sell_cost),
        ("slippage", request.slippage),
        ("commission", request.commission),
        ("transfer_fee", request.transfer_fee),
        ("stamp_duty", request.stamp_duty),
    ):
        if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 0.1):
            raise make_error(status_code=422, detail=f"{name} 必须在 0 到 0.1 之间")
    if not math.isfinite(request.min_cost) or request.min_cost < 0:
        raise make_error(status_code=422, detail="min_cost 不能为负数")
    if request.rebalance_freq not in _REBALANCE_FREQS:
        raise make_error(status_code=422, detail="rebalance_freq 必须是 1D、1W、2W 或 1M")
    if not 0.0 < request.max_weight_per_stock <= 1.0:
        raise make_error(status_code=422, detail="max_weight_per_stock 必须在 0 到 1 之间")
    if request.max_factors < 1 or request.max_factors > 500:
        raise make_error(status_code=422, detail="max_factors 必须在 1 到 500 之间")
    if not math.isfinite(request.mutual_ic_threshold) or not 0.0 <= request.mutual_ic_threshold <= 1.0:
        raise make_error(status_code=422, detail="mutual_ic_threshold 必须在 0 到 1 之间")
    if request.z_clip is not None and (
        not math.isfinite(request.z_clip) or not 0.0 < request.z_clip <= 10.0
    ):
        raise make_error(status_code=422, detail="z_clip 必须在 0 到 10 之间")
    if request.target_horizon < 1 or request.target_horizon > 250:
        raise make_error(status_code=422, detail="target_horizon 必须在 1 到 250 之间")

    sizes = sorted({int(size) for size in request.sweep_sizes})
    if not sizes:
        raise make_error(status_code=422, detail="sweep_sizes 至少需要一个组合规模")
    if any(size < 1 for size in sizes):
        raise make_error(status_code=422, detail="sweep_sizes 必须全部为正整数")
    if any(size > request.max_factors for size in sizes):
        raise make_error(status_code=422, detail="sweep_sizes 不能大于 max_factors")
    return {
        "sweep_sizes": sizes,
        "max_factors": int(request.max_factors),
    }


def _resolve_composition_window(
    request: FactorCompositionRequest,
    pool_manifest: Dict[str, Any],
    source_meta: Dict[str, Any],
) -> tuple[date, date, List[str]]:
    source_start = _cache_ymd(source_meta.get("date_min"))
    source_end = _cache_ymd(source_meta.get("date_max"))
    default_start = _cache_ymd(pool_manifest.get("selection_start")) or source_start
    default_end = _cache_ymd(pool_manifest.get("selection_end")) or source_end
    start = _parse_ymd(request.start_date, "start_date") if request.start_date else default_start
    end = _parse_ymd(request.end_date, "end_date") if request.end_date else default_end
    if start is None or end is None:
        raise make_error(
            status_code=422,
            detail="无法确定组合回测区间：股票池或数据源缺少日期范围，请显式传入 start_date/end_date",
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
    return start, end, warnings


def create_factor_composition(request: FactorCompositionRequest) -> Dict[str, Any]:
    """提交等权因子组合 + TopK 选股回测任务。"""
    validated = _validate_composition_parameters(request)
    run_ids = list(dict.fromkeys(str(item).strip() for item in request.factor_run_ids if str(item).strip()))
    if not run_ids:
        raise make_error(status_code=422, detail="请至少选择一个因子运行")

    requested_factor_ids: Optional[List[str]] = None
    if request.factor_ids is not None:
        requested_factor_ids = list(
            dict.fromkeys(str(item).strip() for item in request.factor_ids if str(item).strip())
        )
        if not requested_factor_ids:
            raise make_error(status_code=422, detail="factor_ids 不能为空列表；不传表示自动选择")
        if len(requested_factor_ids) > validated["max_factors"]:
            raise make_error(
                status_code=422,
                detail="max_factors 不能小于手动选择的因子数量",
            )

    pool_manifest, _pool_codes, _pool_storage = _generation_pool_source(request.pool_id)
    try:
        source = company_source.resolve_data_source(None, pool_manifest)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None

    run_manifests: List[Dict[str, Any]] = []
    run_dirs: List[Path] = []
    available_factor_ids: set[str] = set()
    run_snapshots: set[str] = set()
    for run_id in run_ids:
        run_dir = _factor_run_dir(run_id)
        manifest = _run_manifest(run_dir)
        try:
            company_source.resolve_data_source(None, manifest)
        except ValueError as exc:
            raise make_error(status_code=422, detail=f"因子运行 {run_id}：{exc}") from None
        manifest_pool_id = str(manifest.get("pool_id") or "").strip()
        if manifest_pool_id != request.pool_id:
            raise make_error(
                status_code=422,
                detail=f"因子运行 {run_id} 属于股票池 {manifest_pool_id or '未知'}，与请求的 {request.pool_id} 不一致",
            )
        rows = _confirmed_factor_rows(run_dir)
        available_factor_ids.update(
            str(row.get("factor_id") or "").strip()
            for row in rows
            if str(row.get("factor_id") or "").strip()
        )
        if manifest.get("snapshot_id"):
            run_snapshots.add(str(manifest["snapshot_id"]))
        run_dirs.append(run_dir)
        run_manifests.append(manifest)

    if not available_factor_ids:
        raise make_error(status_code=422, detail="所选因子运行没有可组合的 confirmed 因子")
    if requested_factor_ids is not None:
        missing = [factor_id for factor_id in requested_factor_ids if factor_id not in available_factor_ids]
        if missing:
            preview = "、".join(missing[:5])
            suffix = " 等" if len(missing) > 5 else ""
            raise make_error(
                status_code=422,
                detail=f"{len(missing)} 个因子不在所选运行中（示例：{preview}{suffix}），请刷新后重试",
            )

    if len(run_snapshots) > 1 and not request.snapshot_id:
        raise make_error(
            status_code=422,
            detail="所选因子运行使用了不同快照，请显式传入 snapshot_id",
        )
    effective_snapshot_id = request.snapshot_id or (next(iter(run_snapshots)) if run_snapshots else None)
    try:
        source_meta = (
            snapshot_manifest(effective_snapshot_id, snapshot_root=common.SNAPSHOT_ROOT)
            if source == "clickhouse" and effective_snapshot_id
            else company_source.meta()
        )
    except live_db.LiveDBError as exc:
        raise _live_error(exc) from None
    except (ValueError, OSError) as exc:
        raise make_error(status_code=422, detail=f"快照不可用：{exc}") from None

    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise make_error(
            status_code=422,
            detail="股票池与数据源签名不一致，请重新建池后再组合",
        )
    for run_id, manifest in zip(run_ids, run_manifests):
        run_signature = manifest.get("source_signature")
        if run_signature not in (None, source_signature):
            raise make_error(
                status_code=422,
                detail=f"因子运行 {run_id} 与数据源签名不一致，请重新生成因子后再组合",
            )

    start, end, warnings = _resolve_composition_window(request, pool_manifest, source_meta)
    if request.max_weight_per_stock * request.top_k < 1.0:
        warnings.append(
            "max_weight_per_stock 小于 1/top_k：TopK 组合无法满仓，"
            f"单票上限 {request.max_weight_per_stock:.2%}，目标仓位约 "
            f"{min(1.0 / request.top_k, request.max_weight_per_stock) * request.top_k:.0%}"
        )
    if request.mutual_ic_threshold > 0.9:
        warnings.append(
            "等权组合建议把 mutual_ic_threshold 设为 0.8 左右；"
            "当前阈值较高，相关性很强的因子可能同时入池"
        )
    if len(available_factor_ids) < validated["max_factors"]:
        warnings.append(
            f"候选 confirmed 因子只有 {len(available_factor_ids)} 个，"
            f"低于 max_factors={validated['max_factors']}，组合将按实际数量收敛"
        )

    backtest_config = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "top_k": request.top_k,
        "initial_cash": request.initial_cash,
        "rebalance_freq": request.rebalance_freq,
        "commission": request.commission,
        "transfer_fee": request.transfer_fee,
        "stamp_duty": request.stamp_duty,
        **({"buy_cost": request.buy_cost} if request.buy_cost is not None else {}),
        **({"sell_cost": request.sell_cost} if request.sell_cost is not None else {}),
        "slippage": request.slippage,
        "min_cost": request.min_cost,
        "max_weight_per_stock": request.max_weight_per_stock,
    }
    payload: Dict[str, Any] = {
        "snapshot_root": str(common.SNAPSHOT_ROOT),
        "snapshot_id": effective_snapshot_id,
        "as_of": request.as_of,
        "data_source": source,
        "pools_root": str(common.POOLS_ROOT),
        "pool_id": request.pool_id,
        "factor_run_dirs": [str(path) for path in run_dirs],
        "outputs_root": str(common.RESULTS_ROOT),
        "backtest_config": backtest_config,
        "selection_metric": request.selection_metric,
        "min_score": request.min_score,
        "min_ic": request.min_ic,
        "min_rank_ic": request.min_rank_ic,
        "min_coverage": request.min_coverage,
        "min_backtest_sharpe": request.min_backtest_sharpe,
        "mutual_ic_threshold": request.mutual_ic_threshold,
        "sweep_sizes": validated["sweep_sizes"],
        "max_factors": validated["max_factors"],
        "z_clip": request.z_clip,
        "target_horizon": request.target_horizon,
    }
    if requested_factor_ids is not None:
        payload["factor_ids"] = requested_factor_ids

    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "compose_factors", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise make_error(status_code=500, detail=f"创建因子组合任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise make_error(
            status_code=500, detail=f"因子组合任务已创建但启动失败：{exc}"
        ) from None

    return _sanitize(
        {
            "job_id": job_dir.name,
            "status": "queued",
            "operation": "compose_factors",
            "pool_id": request.pool_id,
            "data_source": source,
            "factor_run_ids": run_ids,
            "factor_ids": requested_factor_ids,
            "candidate_total": len(available_factor_ids),
            "selected_total": len(requested_factor_ids) if requested_factor_ids is not None else None,
            "warnings": warnings,
            "request_summary": {
                "pool_id": request.pool_id,
                "factor_run_ids": run_ids,
                "factor_ids": requested_factor_ids,
                "mutual_ic_threshold": request.mutual_ic_threshold,
                "z_clip": request.z_clip,
                "sweep_sizes": validated["sweep_sizes"],
                "max_factors": validated["max_factors"],
                "target_horizon": request.target_horizon,
                **backtest_config,
            },
        }
    )


def _composition_dir(pool_id: str, composition_id: str) -> tuple[Path, Dict[str, Any]]:
    pool_dir = _safe_child(_composite_root(), pool_id)
    composition_dir = _safe_child(pool_dir, composition_id)
    manifest_path = composition_dir / "composition_manifest.json"
    if not manifest_path.is_file():
        raise make_error(
            status_code=404, detail=f"因子组合结果不存在：{composition_id}"
        )
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError) as exc:
        raise make_error(status_code=500, detail=f"读取组合清单失败：{exc}") from None
    if not isinstance(manifest, dict):
        raise make_error(status_code=500, detail="组合清单格式无效")
    return composition_dir, manifest


def _size_entry(
    composition_dir: Path,
    manifest: Dict[str, Any],
    size: Optional[int],
) -> tuple[int, Dict[str, Any], Path]:
    entries = manifest.get("sizes")
    if not isinstance(entries, list) or not entries:
        raise make_error(status_code=404, detail="该组合没有可用规模结果")
    if size is None:
        size = manifest.get("default_size")
        if size is None:
            size = max(int(entry.get("size") or 0) for entry in entries)
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise make_error(status_code=422, detail="size 必须是整数") from None
    entry = next(
        (item for item in entries if int(item.get("size") or 0) == size),
        None,
    )
    if entry is None:
        available = sorted(int(item.get("size") or 0) for item in entries)
        raise make_error(
            status_code=404,
            detail=f"组合规模 {size} 不存在；可用规模：{available}",
        )
    output_dir = Path(str(entry.get("output_dir") or "")).expanduser().resolve()
    try:
        output_dir.relative_to(composition_dir.resolve())
    except ValueError:
        raise make_error(status_code=500, detail="组合结果路径不在预期目录内") from None
    if not output_dir.is_dir():
        raise make_error(status_code=404, detail=f"组合规模 {size} 的结果目录不存在")
    return size, entry, output_dir


def _available_sizes(manifest: Dict[str, Any]) -> List[int]:
    entries = manifest.get("sizes")
    if not isinstance(entries, list):
        return []
    return sorted(int(item.get("size") or 0) for item in entries if item.get("size"))


def get_factor_composition(
    composition_id: str,
    pool_id: str,
    size: Optional[int] = None,
) -> Dict[str, Any]:
    """读取一次组合的清单、指定规模的指标与因子权重。"""
    composition_dir, manifest = _composition_dir(pool_id, composition_id)
    resolved_size, entry, output_dir = _size_entry(composition_dir, manifest, size)
    weights_path = output_dir / "factor_weights.json"
    weights: List[Dict[str, Any]] = []
    if weights_path.is_file():
        try:
            raw_weights = _read_json(weights_path)
            if isinstance(raw_weights, list):
                weights = raw_weights
        except (OSError, ValueError):
            weights = []
    return _sanitize(
        {
            "composition_id": composition_id,
            "pool_id": pool_id,
            "size": resolved_size,
            "available_sizes": _available_sizes(manifest),
            "manifest": manifest,
            "result": entry,
            "weights": weights,
        }
    )


def _screen_name_map() -> Dict[str, str]:
    """code → 股票简称；仅用于展示，失败时返回空表而不是让选股接口报错。"""
    global _name_cache, _name_failed_at
    now = time.monotonic()
    if _name_cache is not None and now - _name_cache[0] < _NAME_CACHE_TTL:
        return _name_cache[1]
    if _name_failed_at and now - _name_failed_at < _NAME_FAILURE_TTL:
        return {}
    try:
        profiles = live_db.live_dim_profiles().data
    except Exception as exc:  # noqa: BLE001 - 名称是展示信息，不阻塞选股结果
        _name_failed_at = now
        logger.warning("读取股票名称失败，选股清单将不显示名称：%s", exc)
        return {}
    names: Dict[str, str] = {}
    for code, profile in profiles.items():
        name = str((profile or {}).get("name") or "").strip()
        if name:
            names[str(code).zfill(6)] = name
    _name_cache = (now, names)
    _name_failed_at = 0.0
    return names


def get_factor_composition_screen(
    composition_id: str,
    pool_id: str,
    size: Optional[int] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """读取最新信号日的选股清单（按综合分排序）。"""
    composition_dir, manifest = _composition_dir(pool_id, composition_id)
    resolved_size, _entry, output_dir = _size_entry(composition_dir, manifest, size)
    screen_path = output_dir / "latest_screen.json"
    if not screen_path.is_file():
        raise make_error(
            status_code=404,
            detail=f"组合规模 {resolved_size} 还没有选股清单，请重跑组合任务",
        )
    try:
        screen = _read_json(screen_path)
    except (OSError, ValueError) as exc:
        raise make_error(status_code=500, detail=f"读取选股清单失败：{exc}") from None
    if not isinstance(screen, dict):
        raise make_error(status_code=500, detail="选股清单格式无效")
    rows = screen.get("rows") if isinstance(screen.get("rows"), list) else []
    limit_value = max(1, min(int(limit), 1000))
    payload = dict(screen)
    payload["rows"] = rows[:limit_value]
    payload["returned_rows"] = len(payload["rows"])
    payload["total_returned_rows"] = len(rows)
    # 组合产物只落股票代码；名称在 API 读取时补齐，旧结果也能立即显示。
    if any(isinstance(row, dict) and not row.get("name") for row in payload["rows"]):
        names = _screen_name_map()
        for row in payload["rows"]:
            if isinstance(row, dict) and not row.get("name"):
                row["name"] = names.get(str(row.get("code") or "").zfill(6))
    return _sanitize(
        {
            "composition_id": composition_id,
            "pool_id": pool_id,
            "size": resolved_size,
            "screen": payload,
        }
    )


def get_factor_compositions(pool_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """列出组合历史，按创建时间倒序。"""
    root = _composite_root()
    compositions: List[Dict[str, Any]] = []
    if not root.is_dir():
        return {"total": 0, "compositions": []}
    if pool_id:
        pool_dirs = [_safe_child(root, pool_id)]
    else:
        pool_dirs = [path for path in root.iterdir() if path.is_dir()]
    for pool_dir in pool_dirs:
        if not pool_dir.is_dir():
            continue
        for composition_dir in pool_dir.iterdir():
            manifest_path = composition_dir / "composition_manifest.json"
            if not composition_dir.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest = _read_json(manifest_path)
            except (OSError, ValueError):
                continue
            if not isinstance(manifest, dict):
                continue
            compositions.append(
                {
                    "composition_id": manifest.get("composition_id") or composition_dir.name,
                    "pool_id": manifest.get("pool_id") or pool_dir.name,
                    "created_at": manifest.get("created_at"),
                    "weight_method": manifest.get("weight_method"),
                    "candidate_count": manifest.get("candidate_count"),
                    "selected_count": manifest.get("selected_count"),
                    "completed_sizes": manifest.get("completed_sizes") or [],
                    "default_size": manifest.get("default_size"),
                    "z_clip": manifest.get("z_clip"),
                    "source_factor_run_ids": manifest.get("source_factor_run_ids") or [],
                    "mutual_ic_threshold": manifest.get("mutual_ic_threshold"),
                }
            )
    compositions.sort(
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("composition_id") or "")),
        reverse=True,
    )
    total = len(compositions)
    return _sanitize({"total": total, "compositions": compositions[: max(1, min(int(limit), 500))]})
