"""因子运行与批量因子回测查询/提交。"""
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
    _parse_ymd,
    _read_json,
    _safe_child,
    _sanitize,
    logger,
)

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
        raise make_error(status_code=404, detail=f"{label} not found: {run_dir.name}")
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise make_error(status_code=500, detail=f"读取 {label} 失败：{exc}") from None
    if not isinstance(manifest, dict):
        raise make_error(status_code=500, detail=f"{label} 格式无效：{path}")
    return manifest

def _factor_run_summary(run_dir: Path) -> Dict[str, Any]:
    manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    confirmation_path = run_dir / "confirmation_manifest.json"
    confirmation_status = _read_json(confirmation_path).get("status", "pending") if confirmation_path.is_file() else "pending"
    accepted_count = len(_confirmed_records(run_dir)) if confirmation_status == "finished" else 0
    created_at = manifest.get("created_at")
    if not created_at:
        created_at = datetime.fromtimestamp(
            (run_dir / "factor_run.json").stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
    hyperparameters = manifest.get("hyperparameters")
    hyperparameters = hyperparameters if isinstance(hyperparameters, dict) else {}
    quality = hyperparameters.get("quality")
    return {
        "run_id": run_dir.name,
        "pool_id": manifest.get("pool_id"),
        "data_source": manifest.get("data_source") or "local",
        "source_signature": manifest.get("source_signature"),
        "snapshot_id": manifest.get("snapshot_id"),
        "runtime_id": manifest.get("runtime_id"),
        "created_at": created_at,
        "accepted_count": int(accepted_count or 0),
        "confirmed_count": int(accepted_count or 0),
        "candidate_count": len(_read_jsonl(run_dir / "candidate_factors.jsonl")),
        "confirmation_status": confirmation_status,
        "attempts": manifest.get("attempts"),
        "target_reached": manifest.get("target_reached"),
        "attempts_exhausted": manifest.get("attempts_exhausted"),
        "factor_run_dir": str(run_dir),
        "has_accepted": confirmation_status == "finished" and accepted_count > 0,
        "run_name": manifest.get("run_name"),
        "job_id": manifest.get("job_id"),
        "device": manifest.get("device"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "duration_seconds": manifest.get("duration_seconds"),
        "training_seconds": manifest.get("training_seconds"),
        "timesteps": manifest.get("timesteps"),
        "target_factor_count": hyperparameters.get("target_factor_count", manifest.get("target_factor_count")),
        "max_attempts": hyperparameters.get("max_attempts", manifest.get("max_attempts")),
        "rollout_timesteps": hyperparameters.get("rollout_timesteps"),
        "seed": hyperparameters.get("seed"),
        "target_horizon": hyperparameters.get("target_horizon"),
        "max_backtrack_days": hyperparameters.get("max_backtrack_days", manifest.get("max_backtrack_days")),
        "max_future_days": hyperparameters.get("max_future_days", manifest.get("max_future_days")),
        "split_days": manifest.get("split_days"),
        "hyperparameters": hyperparameters or None,
        "fields": manifest.get("fields"),
        "operators": manifest.get("operators"),
        "operator_mode": manifest.get("operator_mode"),
        "n_stocks": manifest.get("n_stocks"),
        "quality": quality if isinstance(quality, dict) else None,
        "storage": "local",
        "local_available": True,
    }

def _factor_run_db_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 MySQL factor_runs 行转成前端使用的 summary。"""
    keys = (
        "run_id",
        "pool_id",
        "data_source",
        "source_signature",
        "runtime_id",
        "created_at",
        "accepted_count",
        "candidate_count",
        "confirmed_count",
        "confirmation_status",
        "attempts",
        "target_reached",
        "attempts_exhausted",
        "factor_run_dir",
        "has_accepted",
        "run_name",
        "job_id",
        "device",
        "started_at",
        "finished_at",
        "duration_seconds",
        "training_seconds",
        "timesteps",
        "target_factor_count",
        "max_attempts",
        "rollout_timesteps",
        "seed",
        "target_horizon",
        "max_backtrack_days",
        "max_future_days",
        "split_days",
        "hyperparameters",
        "fields",
        "operators",
        "operator_mode",
        "n_stocks",
        "quality",
    )
    summary = {key: row.get(key) for key in keys}
    summary["data_source"] = summary.get("data_source") or "mysql"
    summary["storage"] = "mysql"
    summary["local_available"] = False
    return summary

def _merge_factor_run_rows(
    local_runs: List[Dict[str, Any]], mysql_runs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """合并本地与 MySQL 记录：MySQL 提供训练元数据，本地提供文件可访问性。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for row in mysql_runs:
        summary = _factor_run_db_summary(row)
        merged[str(summary.get("run_id"))] = summary
    for row in local_runs:
        run_id = str(row.get("run_id"))
        item = dict(merged.get(run_id) or {})
        for key, value in row.items():
            if value not in (None, "", [], {}) or key not in item:
                item[key] = value
        item["local_available"] = True
        item["storage"] = "mysql+local" if run_id in merged else "local"
        merged[run_id] = item
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )

def _factor_run_dir(run_id: str) -> Path:
    run_dir = _safe_child(common.FACTOR_RUNS_ROOT, run_id)
    if not (run_dir / "factor_run.json").is_file():
        raise make_error(status_code=404, detail=f"factor run not found: {run_id}")
    return run_dir

def _confirmed_records(run_dir: Path) -> List[Dict[str, Any]]:
    from repositories.factor_run_store import confirmed_records
    path = run_dir / "confirmation_manifest.json"
    if not path.is_file() or _read_json(path).get("status") != "finished":
        return []
    try:
        return confirmed_records(run_dir)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None


def _accepted_factor_rows(run_dir: Path, file_name: str = "confirmed_factors.jsonl") -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    records = _confirmed_records(run_dir) if file_name == "confirmed_factors.jsonl" else _read_jsonl(run_dir / file_name)
    for index, record in enumerate(records, start=1):
        expression = str(record.get("expression") or "").strip()
        canonical = record.get("canonical_expression")
        if not canonical and expression:
            try:
                canonical = normalize_expression(expression) or expression
            except Exception:  # noqa: BLE001 - 无法规范化的表达式保留原文
                canonical = expression
        backtest = record.get("backtest_expression") or canonical
        rows.append(
            {
                "factor_id": record.get("factor_id") or (factor_id_for(index, expression) if expression else f"factor_{index:04d}"),
                "expression": expression,
                "canonical_expression": canonical,
                "backtest_expression": backtest,
                "ic": record.get("ic"),
                "rank_ic": record.get("rank_ic"),
                "icir": record.get("icir"),
                "coverage": record.get("coverage"),
                "score": record.get("score"),
                "reason": record.get("reason"),
                "segments": record.get("segments") or {},
            }
        )
    return rows

def _factor_batch_dir(factor_run_id: str, backtest_id: str, pool_id: Optional[str] = None) -> Path:
    run_dir = _factor_run_dir(factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    run_pool_id = str(run_manifest.get("pool_id") or "").strip()
    if not run_pool_id:
        raise make_error(status_code=422, detail="该因子运行缺少 pool_id，无法定位回测结果")
    if pool_id and pool_id != run_pool_id:
        raise make_error(
            status_code=422,
            detail=f"factor run 的 pool_id {run_pool_id!r} 与请求的 pool_id {pool_id!r} 不一致",
        )
    pool_dir = _safe_child(common.RESULTS_ROOT / "factor", run_pool_id)
    run_result_dir = _safe_child(pool_dir, factor_run_id)
    batch_dir = _safe_child(run_result_dir, backtest_id)
    if not (batch_dir / "factor_backtest_manifest.json").is_file():
        raise make_error(status_code=404, detail=f"factor backtest not found: {backtest_id}")
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
        "snapshot_id": manifest.get("snapshot_id"),
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
        raise make_error(status_code=500, detail=f"读取 {path.name} 失败：{exc}") from None

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

def _accepted_factor_rows_from_db(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        expression = str(record.get("expression") or "").strip()
        rows.append(
            {
                "factor_id": record.get("factor_id")
                or (factor_id_for(index, expression) if expression else f"factor_{index:04d}"),
                "expression": expression,
                "canonical_expression": record.get("canonical_expression"),
                "backtest_expression": record.get("backtest_expression"),
                "ic": record.get("ic"),
                "rank_ic": record.get("rank_ic"),
                "icir": record.get("icir"),
                "coverage": record.get("coverage"),
                "score": record.get("score"),
                "reason": record.get("reason"),
                "segments": record.get("segments") or {},
            }
        )
    return rows

def get_factor_runs(
    pool_id: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """列出因子运行：MySQL 历史记录 + 本地目录合并。"""
    local_runs: List[Dict[str, Any]] = []
    if common.FACTOR_RUNS_ROOT.is_dir():
        for run_dir in common.FACTOR_RUNS_ROOT.iterdir():
            if not run_dir.is_dir() or not (run_dir / "factor_run.json").is_file():
                continue
            try:
                summary = _factor_run_summary(run_dir)
            except DomainError:
                continue
            if pool_id and summary.get("pool_id") != pool_id:
                continue
            local_runs.append(summary)

    mysql_runs: List[Dict[str, Any]] = []
    mysql_error: Optional[str] = None
    try:
        mysql_runs = mysql_store.fetch_factor_runs(pool_id=pool_id, limit=500)
    except Exception as exc:  # noqa: BLE001 - MySQL 不可用时退回本地
        mysql_error = f"{type(exc).__name__}: {exc}"
        logger.warning("读取 MySQL 因子运行列表失败：%s", mysql_error)

    runs = _merge_factor_run_rows(local_runs, mysql_runs)
    total = len(runs)
    try:
        limit_value = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit_value = 100
    return _sanitize(
        {
            "total": total,
            "runs": runs[:limit_value],
            "source": "mysql" if mysql_error is None else "local",
            "mysql_error": mysql_error,
        }
    )

def get_factor_run(run_id: str) -> Dict[str, Any]:
    """因子运行详情 + 合格因子清单（本地优先，缺失时回退 MySQL）。"""
    run_dir = _safe_child(common.FACTOR_RUNS_ROOT, run_id)
    if (run_dir / "factor_run.json").is_file():
        summary = _factor_run_summary(run_dir)
        accepted = _accepted_factor_rows(run_dir)
        candidates = _accepted_factor_rows(run_dir, "candidate_factors.jsonl")
        evaluations = _read_jsonl(run_dir / "test_evaluations.jsonl")
        manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
        db_row = None
        try:
            db_row = mysql_store.fetch_factor_run(run_id)
        except Exception as exc:  # noqa: BLE001 - 本地详情不依赖 MySQL
            logger.warning("读取因子运行 %s 的 MySQL 元数据失败：%s", run_id, exc)
        if db_row:
            merged = _merge_factor_run_rows([summary], [db_row])[0]
            merged["manifest"] = manifest
            merged["candidate_factors"] = candidates
            merged["test_evaluations"] = evaluations
            merged["confirmed_factors"] = accepted
            merged["accepted_factors"] = accepted
            merged["accepted_count"] = len(accepted)
            return _sanitize(merged)
        return _sanitize(
            {
                **summary,
                "accepted_count": len(accepted),
                "manifest": manifest,
                "accepted_factors": accepted,
                "confirmed_factors": accepted,
                "candidate_factors": candidates,
                "test_evaluations": evaluations,
            }
        )

    try:
        db_row = mysql_store.fetch_factor_run(run_id)
    except Exception as exc:  # noqa: BLE001
        raise make_error(
            status_code=503, detail=f"本地因子运行不存在，且 MySQL 不可用：{exc}"
        ) from None
    if not db_row:
        raise make_error(status_code=404, detail=f"factor run not found: {run_id}")
    summary = _factor_run_db_summary(db_row)
    manifest = db_row.get("raw") if isinstance(db_row.get("raw"), dict) else {}
    records = manifest.get("confirmed_factors") or []
    accepted = _accepted_factor_rows_from_db(records)
    historical = []
    if not any(key in manifest for key in ("policy_version", "candidate_factors", "confirmed_factors")):
        historical = mysql_store.fetch_factor_run_factors(run_id, accepted_only=True)
    return _sanitize(
        {
            **summary,
            "accepted_count": len(accepted),
            "manifest": manifest,
            "accepted_factors": accepted,
            "confirmed_factors": accepted,
            "candidate_factors": manifest.get("candidate_factors") or [],
            "historical_factors": historical,
            "test_evaluations": manifest.get("test_evaluations") or [],
        }
    )

def create_factor_backtest(request: FactorBacktestRequest) -> Dict[str, Any]:
    """把某个因子运行的全部/选定合格因子提交为后台批量回测任务。"""
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
        if value is not None and not 0.0 <= value <= 0.1:
            raise make_error(status_code=422, detail=f"{name} 必须在 0 到 0.1 之间")
    if not math.isfinite(request.min_cost) or request.min_cost < 0:
        raise make_error(status_code=422, detail="min_cost 不能为负数")
    if request.rebalance_freq not in {"1D", "1W", "2W", "1M"}:
        raise make_error(status_code=422, detail="rebalance_freq 必须是 1D、1W、2W 或 1M")
    if not 0.0 < request.max_weight_per_stock <= 1.0:
        raise make_error(status_code=422, detail="max_weight_per_stock 必须在 0 到 1 之间")

    run_dir = _factor_run_dir(request.factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    pool_id = str(run_manifest.get("pool_id") or "").strip()
    if not pool_id:
        raise make_error(status_code=422, detail="该因子运行缺少 pool_id，无法回测")
    pool_dir = _safe_child(common.POOLS_ROOT, pool_id)
    pool_manifest = _manifest_or_404(pool_dir, "manifest.json", "pool")
    try:
        source = company_source.resolve_data_source(None, pool_manifest)
        company_source.resolve_data_source(None, run_manifest)
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None
    effective_snapshot_id = request.snapshot_id or run_manifest.get("snapshot_id")
    try:
        source_meta = (snapshot_manifest(effective_snapshot_id, snapshot_root=common.SNAPSHOT_ROOT)
                       if effective_snapshot_id else company_source.meta())
    except live_db.LiveDBError as exc:
        from common import _live_error
        raise _live_error(exc) from None
    except (ValueError, OSError) as exc:
        raise make_error(status_code=422, detail=f"快照不可用：{exc}") from None
    source_signature = source_meta.get("source_signature")
    if pool_manifest.get("source_signature") != source_signature:
        raise make_error(
            status_code=422,
            detail="股票池与数据源签名不一致，请重新建池后再回测",
        )
    run_signature = run_manifest.get("source_signature")
    if run_signature not in (None, source_signature):
        raise make_error(
            status_code=422,
            detail="因子运行与数据源签名不一致，请重新生成因子后再回测",
        )

    confirmation_path = run_dir / "confirmation_manifest.json"
    if not confirmation_path.is_file() or _read_json(confirmation_path).get("status", "finished") != "finished":
        raise make_error(status_code=422, detail="请先完成因子确认任务，再回测 confirmed 因子")
    accepted = _accepted_factor_rows(run_dir)
    if not accepted:
        raise make_error(
            status_code=422,
            detail="该因子运行没有合格因子（confirmed_factors.jsonl 为空），请先生成因子",
        )
    available_ids = [row["factor_id"] for row in accepted]
    selected_ids: Optional[List[str]] = None
    if request.factor_ids is not None:
        requested = {str(value).strip() for value in request.factor_ids if str(value).strip()}
        if not requested:
            raise make_error(status_code=422, detail="请至少选择一个因子")
        unknown = sorted(requested - set(available_ids))
        if unknown:
            raise make_error(
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
        raise make_error(
            status_code=422,
            detail="无法确定回测区间：数据源缺少日期范围，请显式传入 start_date/end_date",
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
        "factor_run_dir": str(run_dir),
        "outputs_root": str(common.RESULTS_ROOT),
        "backtest_config": backtest_config,
        "expected_pool_id": pool_id,
    }
    if selected_ids is not None:
        payload["factor_ids"] = selected_ids

    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "backtest_factors", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise make_error(status_code=500, detail=f"创建因子回测任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise make_error(
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
                **backtest_config,
            },
        }
    )

def get_factor_backtests(
    factor_run_id: str ,
    pool_id: Optional[str] = None,
) -> Dict[str, Any]:
    """列出某个因子运行下所有批次回测（按创建时间倒序）。"""
    run_dir = _factor_run_dir(factor_run_id)
    run_manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    run_pool_id = str(run_manifest.get("pool_id") or "").strip()
    if pool_id and pool_id != run_pool_id:
        raise make_error(status_code=422, detail="factor run 与 pool_id 不匹配")
    batches: List[Dict[str, Any]] = []
    if run_pool_id:
        try:
            pool_dir = _safe_child(common.RESULTS_ROOT / "factor", run_pool_id)
            run_result_dir = _safe_child(pool_dir, factor_run_id)
        except DomainError:
            raise
        if run_result_dir.is_dir():
            for batch_dir in run_result_dir.iterdir():
                if not batch_dir.is_dir() or not (batch_dir / "factor_backtest_manifest.json").is_file():
                    continue
                try:
                    batches.append(_batch_summary(batch_dir))
                except DomainError:
                    continue
    batches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return _sanitize({"total": len(batches), "batches": batches})

def get_factor_backtest(
    backtest_id: str,
    factor_run_id: str ,
    pool_id: Optional[str] = None,
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

def download_factor_backtest_file(
    backtest_id: str,
    file_name: str,
    factor_run_id: str ,
    pool_id: Optional[str] = None,
) -> Path:
    batch_dir = _factor_batch_dir(factor_run_id, backtest_id, pool_id)
    allowed = {"factor_backtest_summary.csv", "factor_backtest_failures.csv", "factor_backtest_manifest.json"}
    if file_name not in allowed:
        raise make_error(status_code=404, detail=f"file not allowed: {file_name}")
    file_path = _safe_child(batch_dir, file_name)
    if not file_path.is_file():
        raise make_error(status_code=404, detail=f"file not found: {file_name}")
    return file_path


def create_factor_confirmation(run_id: str) -> Dict[str, Any]:
    """Submit the frozen candidate set for a single resumable holdout pass."""
    run_dir = _factor_run_dir(run_id)
    manifest = _manifest_or_404(run_dir, "factor_run.json", "factor run")
    if manifest.get("generation_status") != "finished":
        raise make_error(status_code=422, detail="PPO 生成尚未完成或为旧运行，请先生成并冻结候选集合")
    if not (run_dir / "candidate_factors.jsonl").is_file():
        raise make_error(status_code=422, detail="缺少 candidate_factors.jsonl，无法确认")
    payload = {"factor_run_dir": str(run_dir), "snapshot_root": str(common.SNAPSHOT_ROOT)}
    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "confirm_factors", payload)
    except Exception as exc:
        raise make_error(status_code=500, detail=f"创建因子确认任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:
        update_job_status(job_dir, "failed", f"因子确认任务启动失败：{exc}")
        raise make_error(status_code=500, detail=f"因子确认任务启动失败：{exc}") from None
    return {"job_id": job_dir.name, "status": "queued", "operation": "confirm_factors", "run_id": run_id}
