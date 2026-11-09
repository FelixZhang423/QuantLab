"""PPO 因子生成参数默认值与提交。"""
from __future__ import annotations

from repositories.snapshot_store import snapshot_manifest
from errors import DomainError, make_error

import common
from services.data_service import _field_catalog


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
    _read_json,
    _safe_child,
    _sanitize,
    logger,
)


_FACTOR_GENERATION_DEFAULTS_CACHE: Dict[str, Any] = {}
_GENERATION_SPLIT_NAMES = ("train", "valid", "test")
_DEFAULT_GENERATION_SPLIT_RATIOS = {"train": 0.6, "valid": 0.2, "test": 0.2}
_GENERATION_QUALITY_KEYS = {
    "min_coverage",
    "min_train_ic",
    "min_train_rank_ic",
    "min_valid_rank_ic",
    "min_valid_icir",
    "min_test_rank_ic",
    "min_test_icir",
    "min_test_coverage",
    "min_valid_ic",
    "min_test_ic",
    "min_icir",
    "score_ic_weight",
    "score_rank_ic_weight",
    "score_icir_weight",
}


def _factor_generation_defaults() -> Dict[str, Any]:
    """读取 configs/factor_generation.yaml，文件变化时刷新。"""
    path = common.FACTOR_GENERATION_CONFIG_PATH
    try:
        stat = path.stat()
    except OSError as exc:
        raise make_error(
            status_code=500, detail=f"因子生成默认配置不可用：{exc}"
        ) from None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _FACTOR_GENERATION_DEFAULTS_CACHE.get("key") != key:
        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise make_error(
                status_code=500, detail=f"读取因子生成默认配置失败：{exc}"
            ) from None
        if not isinstance(config, dict):
            raise make_error(status_code=500, detail="因子生成默认配置格式无效")
        _FACTOR_GENERATION_DEFAULTS_CACHE["key"] = key
        _FACTOR_GENERATION_DEFAULTS_CACHE["data"] = config
    return dict(_FACTOR_GENERATION_DEFAULTS_CACHE["data"])

def _generation_split_ratios(defaults: Dict[str, Any]) -> Dict[str, float]:
    """默认切分比例；优先读 YAML 的 split_ratios，缺失/非法时用 60/20/20。"""
    raw = defaults.get("split_ratios")
    if not isinstance(raw, dict):
        return dict(_DEFAULT_GENERATION_SPLIT_RATIOS)
    values: Dict[str, float] = {}
    for name in _GENERATION_SPLIT_NAMES:
        try:
            value = float(raw.get(name))
        except (TypeError, ValueError):
            return dict(_DEFAULT_GENERATION_SPLIT_RATIOS)
        if value <= 0:
            return dict(_DEFAULT_GENERATION_SPLIT_RATIOS)
        values[name] = value
    total = sum(values.values())
    return {name: value / total for name, value in values.items()}

def _pool_generation_window(
    manifest: Dict[str, Any],
) -> Optional[tuple[date, date]]:
    """股票池真实时间跨度：建池时的 selection_start ~ selection_end。"""
    start = _cache_ymd(manifest.get("selection_start"))
    end = _cache_ymd(manifest.get("selection_end"))
    if start is None or end is None or start > end:
        return None
    return start, end

def _generation_pool_source(
    pool_id: str,
) -> tuple[Dict[str, Any], List[str], str]:
    """读取因子生成/手动回测所需的池清单与代码：本地目录优先，MySQL 兜底。

    股票池列表以 MySQL 为准并合并本地池，因此仅存在于 MySQL 的池也必须能生成因子或回测。
    """
    pool_dir = _safe_child(common.POOLS_ROOT, pool_id)
    manifest_path = pool_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = _read_json(manifest_path)
        codes_file = pool_dir / str(manifest.get("codes_file", "codes.txt"))
        if not codes_file.is_file():
            raise make_error(
                status_code=422,
                detail="该股票池缺少本地 codes.txt，无法生成因子；请重新建池后再试",
            )
        codes = [
            line.strip()
            for line in codes_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not codes:
            raise make_error(status_code=422, detail="该股票池没有股票代码，无法生成因子")
        return manifest, codes, "local"

    try:
        detail = mysql_store.fetch_pool(pool_id)
    except Exception:  # noqa: BLE001 - MySQL 不可用时按池不存在处理
        logger.warning("读取 MySQL 股票池 %s 失败", pool_id, exc_info=True)
        detail = None
    if detail is None:
        raise make_error(status_code=404, detail=f"pool not found: {pool_id}")
    manifest = detail.get("manifest") if isinstance(detail.get("manifest"), dict) else {}
    codes = [
        str(code).strip()
        for code in (detail.get("codes") or [])
        if str(code).strip()
    ]
    if not codes:
        raise make_error(status_code=422, detail="该股票池没有股票代码，无法生成因子")
    return dict(manifest), codes, "mysql"

def _generation_splits_for_window(
    start: date, end: date, ratios: Dict[str, float], target_horizon: int = 20
) -> Dict[str, Dict[str, str]]:
    """把股票池时间跨度按比例切成连续的 train / valid / test。"""
    # Preview uses a conservative calendar margin; the worker verifies actual sessions.
    gap_days = 3 * target_horizon + 14
    span_days = (end - start).days + 1
    total_days = span_days - 2 * gap_days
    if total_days < len(_GENERATION_SPLIT_NAMES):
        raise make_error(
            status_code=422,
            detail=(
                f"股票池真实时间跨度只有 {span_days} 天，预留两段隔离后剩余 {max(total_days, 0)} 天"
                f"（{start.isoformat()} ~ {end.isoformat()}），不足以切分 train/valid/test"
            ),
        )
    lengths: Dict[str, int] = {}
    remaining = total_days
    for index, name in enumerate(_GENERATION_SPLIT_NAMES):
        if index == len(_GENERATION_SPLIT_NAMES) - 1:
            length = remaining
        else:
            length = max(1, int(round(total_days * ratios[name])))
            length = min(length, remaining - (len(_GENERATION_SPLIT_NAMES) - index - 1))
        lengths[name] = length
        remaining -= length

    splits: Dict[str, Dict[str, str]] = {}
    cursor = start
    for name in _GENERATION_SPLIT_NAMES:
        split_end = cursor + timedelta(days=lengths[name] - 1)
        splits[name] = {
            "cache_start": cursor.isoformat(),
            "cache_end": split_end.isoformat(),
        }
        cursor = split_end + timedelta(days=gap_days + 1)
    return splits

def _generation_field_aliases() -> Dict[str, str]:
    """字段目录里的原始名 / 面板列名 → 面板列名。"""
    aliases: Dict[str, str] = {}
    for entry in _field_catalog():
        alias = str(entry.get("panel_alias") or "").strip()
        if not alias:
            continue
        aliases[alias] = alias
        name = str(entry.get("name") or "").strip()
        if name:
            aliases[name] = alias
    return aliases

def _normalize_generation_fields(
    requested: Optional[List[str]], defaults: Dict[str, Any]
) -> tuple[List[str], int]:
    raw = (
        list(defaults.get("fields") or [])
        if requested is None
        else [str(value).strip() for value in requested if str(value).strip()]
    )
    if not raw:
        raise make_error(status_code=422, detail="请至少选择一个因子字段")
    aliases = _generation_field_aliases()
    normalized: List[str] = []
    unknown: List[str] = []
    renamed = 0
    for value in raw:
        text = str(value).strip()
        alias = aliases.get(text)
        if alias is None:
            unknown.append(text)
            continue
        if alias != text:
            renamed += 1
        if alias not in normalized:
            normalized.append(alias)
    if unknown:
        preview = "、".join(unknown[:10])
        suffix = " 等" if len(unknown) > 10 else ""
        raise make_error(
            status_code=422,
            detail=f"以下字段不能用于因子生成：{preview}{suffix}",
        )
    if not normalized:
        raise make_error(status_code=422, detail="请至少选择一个可用于因子生成的字段")
    try:
        fundamental_period_mode(normalized)
    except ValueError as exc:
        raise make_error(
            status_code=422, detail=f"财务流量字段口径冲突：{exc}"
        ) from None
    return normalized, renamed

def _normalize_generation_operators(values: Optional[List[str]]) -> List[str]:
    """规范化算子别名；空列表 = 使用全部 PPO 支持算子。"""
    if values is None:
        return []
    resolved: List[str] = []
    unknown: List[str] = []
    disabled: List[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        try:
            definition = get_operator(text)
        except KeyError:
            unknown.append(text)
            continue
        if not definition.generation_enabled:
            disabled.append(text)
            continue
        if definition.canonical_name not in resolved:
            resolved.append(definition.canonical_name)
    if unknown or disabled:
        parts: List[str] = []
        if unknown:
            parts.append("未知算子：" + "、".join(sorted(set(unknown))))
        if disabled:
            parts.append("PPO 不支持：" + "、".join(sorted(set(disabled))))
        raise make_error(status_code=422, detail="；".join(parts))
    return resolved

def _normalize_generation_quality(
    defaults: Dict[str, Any], overrides: Optional[Dict[str, Optional[float]]]
) -> Dict[str, Any]:
    from custom_bt.factor_generation import _single_factor_root
    _single_factor_root()
    from single_factor.config import QualityConfig
    from dataclasses import asdict
    base = defaults if isinstance(defaults, dict) else {}
    provided = dict(overrides or {})
    unknown = sorted(set(provided) - _GENERATION_QUALITY_KEYS)
    if unknown:
        raise make_error(status_code=422, detail=f"未知的质量阈值字段：{'、'.join(unknown)}")
    try:
        values = {key: float(value) for key, value in {**base, **provided}.items()
                  if key in _GENERATION_QUALITY_KEYS}
        return asdict(QualityConfig(**values))
    except (TypeError, ValueError) as exc:
        raise make_error(status_code=422, detail=f"质量门槛无效：{exc}") from None


def _normalize_generation_splits(
    defaults: Dict[str, Any],
    requested: Optional[Dict[str, "FactorGenerationSplit"]],
    source_start: Optional[date],
    source_end: Optional[date],
    max_backtrack_days: int,
    max_future_days: int,
    target_horizon: Optional[int] = None,
) -> tuple[Dict[str, Dict[str, str]], List[str]]:
    if requested is None:
        raw = dict(defaults.get("splits") or {})
    else:
        raw = {
            name: {"cache_start": value.cache_start, "cache_end": value.cache_end}
            for name, value in requested.items()
        }
    if not raw:
        raise make_error(status_code=422, detail="因子生成必须包含 train、valid、test 三个数据切分")
    unknown = sorted(set(raw) - set(_GENERATION_SPLIT_NAMES))
    if unknown:
        raise make_error(
            status_code=422, detail=f"未知的数据切分：{'、'.join(unknown)}"
        )
    if set(raw) != set(_GENERATION_SPLIT_NAMES):
        raise make_error(status_code=422, detail="因子生成必须包含 train、valid、test 三个数据切分")
    splits: Dict[str, Dict[str, str]] = {}
    warnings: List[str] = []
    minimum_days = max_backtrack_days + max_future_days + 1
    for name in _GENERATION_SPLIT_NAMES:
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, FactorGenerationSplit):
            start_text, end_text = value.cache_start, value.cache_end
        else:
            start_text = str((value or {}).get("cache_start", ""))
            end_text = str((value or {}).get("cache_end", ""))
        start = _parse_ymd(start_text, f"splits.{name}.cache_start")
        end = _parse_ymd(end_text, f"splits.{name}.cache_end")
        if start > end:
            raise make_error(
                status_code=422,
                detail=f"splits.{name}.cache_start 不能晚于 cache_end",
            )
        if source_start and source_end and (end < source_start or start > source_end):
            raise make_error(
                status_code=422,
                detail=(
                    f"{name} 切分（{start.isoformat()} ~ {end.isoformat()}）"
                    f"与数据源（{source_start.isoformat()} ~ {source_end.isoformat()}）没有交集"
                ),
            )
        if (end - start).days + 1 < minimum_days:
            warnings.append(
                f"{name} 切分只有 {(end - start).days + 1} 天，"
                f"少于回溯 {max_backtrack_days} 天 + 未来 {max_future_days} 天，可能无法评估"
            )
        if source_start and start < source_start:
            warnings.append(
                f"{name} 切分起点早于数据源 {source_start.isoformat()}，将按数据源可用区间计算"
            )
        if source_end and end > source_end:
            warnings.append(
                f"{name} 切分终点晚于数据源 {source_end.isoformat()}，将按数据源可用区间计算"
            )
        splits[name] = {"cache_start": start.isoformat(), "cache_end": end.isoformat()}
    horizon = target_horizon if target_horizon is not None else max_future_days
    for left, right in (("train", "valid"), ("valid", "test")):
        end = date.fromisoformat(splits[left]["cache_end"])
        start = date.fromisoformat(splits[right]["cache_start"])
        if end >= start:
            raise make_error(status_code=422, detail=f"{left}/{right} 切分重叠或顺序错误")
        if (start - end).days - 1 < horizon:
            raise make_error(status_code=422, detail=f"{left}/{right} 隔离不足，至少保留 target_horizon={horizon} 个交易日；运行时还会校验实际交易日")
    return splits, warnings

def get_factor_generation_defaults(pool_id: Optional[str] = None) -> Dict[str, Any]:
    """因子生成页的默认参数；传 pool_id 时切分日期跟随股票池真实时间跨度。"""
    config = _factor_generation_defaults()
    fields = [str(value) for value in (config.get("fields") or [])]
    quality = _normalize_generation_quality(config.get("quality") or {}, None)
    ratios = _generation_split_ratios(config)
    splits = config.get("splits") or {}
    split_source = "config"
    pool_window: Optional[Dict[str, str]] = None
    warnings: List[str] = []
    selected_pool = str(pool_id or "").strip()
    if selected_pool:
        manifest, _, _ = _generation_pool_source(selected_pool)
        window = _pool_generation_window(manifest)
        if window is None:
            warnings.append(
                "股票池缺少有效的 selection_start / selection_end，"
                "数据切分回退到 configs/factor_generation.yaml"
            )
        else:
            splits = _generation_splits_for_window(window[0], window[1], ratios, int(config.get("target_horizon", 20)))
            split_source = "pool"
            pool_window = {
                "start": window[0].isoformat(),
                "end": window[1].isoformat(),
            }
    return _sanitize(
        {
            "data_source": "clickhouse",
            "fields": fields,
            "field_count": len(fields),
            "splits": splits,
            "split_source": split_source,
            "split_ratios": ratios,
            "pool_window": pool_window,
            "warnings": warnings,
            "quality": quality,
            "max_backtrack_days": int(config.get("max_backtrack_days", 100)),
            "target_horizon": int(config.get("target_horizon", 20)),
            "max_future_days": int(config.get("max_future_days", 20)),
            "target_factor_count": int(config.get("target_factor_count", 50)),
            "max_attempts": int(config.get("max_attempts", 100000)),
            "rollout_timesteps": int(config.get("rollout_timesteps", 2048)),
            "seed": int(config.get("seed", 0)),
            "device": str(config.get("device", "auto")),
        }
    )

def create_factor_generation(request: FactorGenerationRequest) -> Dict[str, Any]:
    """按真实股票池提交一次 PPO 因子生成任务（后台子进程执行）。"""
    pool_id = str(request.pool_id or "").strip()
    if not pool_id:
        raise make_error(status_code=422, detail="请选择股票池")
    try:
        run_name = (
            validate_run_name(request.run_name)
            if request.run_name and str(request.run_name).strip()
            else None
        )
    except ValueError as exc:
        raise make_error(status_code=422, detail=str(exc)) from None

    pool_manifest, pool_codes, pool_storage = _generation_pool_source(pool_id)

    defaults = _factor_generation_defaults()
    fields, renamed_fields = _normalize_generation_fields(request.fields, defaults)
    operators = _normalize_generation_operators(request.operators)

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
    if pool_manifest.get("source_signature") != source_meta.get("source_signature"):
        raise make_error(
            status_code=422,
            detail="股票池与数据源签名不一致，请重新建池后再生成因子",
        )

    source_start = _cache_ymd(source_meta.get("date_min"))
    source_end = _cache_ymd(source_meta.get("date_max"))
    pool_window = _pool_generation_window(pool_manifest)
    generation_defaults = dict(defaults)
    split_source = "request" if request.splits is not None else "config"
    split_warnings: List[str] = []
    if request.splits is None and pool_window is not None:
        generation_defaults["splits"] = _generation_splits_for_window(
            pool_window[0], pool_window[1], _generation_split_ratios(defaults),
            int(request.target_horizon if request.target_horizon is not None else defaults.get("target_horizon", 20))
        )
        split_source = "pool"
    elif request.splits is None:
        split_warnings.append(
            "股票池缺少有效的 selection_start / selection_end，"
            "数据切分回退到 configs/factor_generation.yaml"
        )

    max_backtrack_days = int(
        request.max_backtrack_days
        if request.max_backtrack_days is not None
        else defaults.get("max_backtrack_days", 100)
    )
    if not 0 <= max_backtrack_days <= 1000:
        raise make_error(status_code=422, detail="max_backtrack_days 必须在 0 到 1000 之间")
    target_horizon = int(
        request.target_horizon
        if request.target_horizon is not None
        else defaults.get("target_horizon", 20)
    )
    if not 1 <= target_horizon <= 250:
        raise make_error(status_code=422, detail="target_horizon 必须在 1 到 250 之间")
    default_future = int(defaults.get("max_future_days", target_horizon))
    max_future_days = int(
        request.max_future_days
        if request.max_future_days is not None
        else max(default_future, target_horizon)
    )
    if not target_horizon <= max_future_days <= 250:
        raise make_error(
            status_code=422,
            detail="max_future_days 必须在 target_horizon 到 250 之间",
        )
    target_factor_count = int(
        request.target_factor_count
        if request.target_factor_count is not None
        else defaults.get("target_factor_count", 50)
    )
    if not 1 <= target_factor_count <= 10000:
        raise make_error(status_code=422, detail="target_factor_count 必须在 1 到 10000 之间")
    max_attempts = int(
        request.max_attempts
        if request.max_attempts is not None
        else defaults.get("max_attempts", 100000)
    )
    if not target_factor_count <= max_attempts <= 10_000_000:
        raise make_error(
            status_code=422,
            detail="max_attempts 必须不小于 target_factor_count，且不超过 10000000",
        )
    rollout_timesteps = int(
        request.rollout_timesteps
        if request.rollout_timesteps is not None
        else defaults.get("rollout_timesteps", 2048)
    )
    if not 64 <= rollout_timesteps <= 1_000_000:
        raise make_error(status_code=422, detail="rollout_timesteps 必须在 64 到 1000000 之间")
    seed = int(request.seed if request.seed is not None else defaults.get("seed", 0))
    if not 0 <= seed <= 2_147_483_647:
        raise make_error(status_code=422, detail="seed 必须在 0 到 2147483647 之间")
    device = str(
        request.device if request.device is not None else defaults.get("device", "auto")
    ).strip().lower()
    if device not in {"auto", "cpu", "cuda"}:
        raise make_error(status_code=422, detail="device 只能是 auto、cpu 或 cuda")
    if device == "cuda":
        try:
            resolve_generation_device("cuda")
        except ValueError as exc:
            raise make_error(status_code=422, detail=str(exc)) from None

    quality = _normalize_generation_quality(defaults.get("quality") or {}, request.quality)
    splits, normalized_split_warnings = _normalize_generation_splits(
        generation_defaults,
        request.splits,
        source_start,
        source_end,
        max_backtrack_days,
        max_future_days,
        target_horizon,
    )
    if request.splits is not None and pool_window is not None:
        for name, value in splits.items():
            start = _parse_ymd(value["cache_start"], f"splits.{name}.cache_start")
            end = _parse_ymd(value["cache_end"], f"splits.{name}.cache_end")
            if start < pool_window[0] or end > pool_window[1]:
                raise make_error(
                    status_code=422,
                    detail=(
                        f"{name} 切分（{start.isoformat()} ~ {end.isoformat()}）"
                        f"超出股票池真实时间跨度"
                        f"（{pool_window[0].isoformat()} ~ {pool_window[1].isoformat()}）"
                    ),
                )

    warnings: List[str] = []
    if renamed_fields:
        warnings.append(f"已将 {renamed_fields} 个字段名规范化为面板列名")
    warnings.extend(split_warnings)
    warnings.extend(normalized_split_warnings)

    generation_config: Dict[str, Any] = {
        "target_factor_count": target_factor_count,
        "max_attempts": max_attempts,
        "rollout_timesteps": rollout_timesteps,
        "seed": seed,
        "device": device,
        "quality": quality,
    }
    if run_name:
        generation_config["run_name"] = run_name
    payload = {
        "snapshot_root": str(common.SNAPSHOT_ROOT),
        "snapshot_id": request.snapshot_id,
        "as_of": request.as_of,
        "pools_root": str(common.POOLS_ROOT),
        "pool_id": pool_id,
        "runtime_root": str(common.FACTOR_RUNTIME_ROOT),
        "factor_runs_root": str(common.FACTOR_RUNS_ROOT),
        "fields": fields,
        "operators": operators,
        "splits": splits,
        "max_backtrack_days": max_backtrack_days,
        "target_horizon": target_horizon,
        "max_future_days": max_future_days,
        "generation_config": generation_config,
        "data_source": source,
    }
    if pool_storage == "mysql":
        # 子进程默认读 data_cache/pools；仅 MySQL 的池需要把清单与代码随任务传入。
        payload["pool_manifest"] = pool_manifest
        payload["pool_codes"] = pool_codes
    try:
        job_dir = create_platform_job(common.JOBS_ROOT, "generate_factors", payload)
    except Exception as exc:  # noqa: BLE001 - 原样带出失败原因
        raise make_error(status_code=500, detail=f"创建因子生成任务失败：{exc}") from None
    try:
        spawn_platform_job(job_dir)
    except Exception as exc:  # noqa: BLE001 - 任务目录已建好，先落失败状态
        update_job_status(job_dir, "failed", f"任务启动失败：{exc}")
        raise make_error(
            status_code=500, detail=f"因子生成任务已创建但启动失败：{exc}"
        ) from None

    run_id: Optional[str] = None
    try:
        created = _read_json(job_dir / "platform_job.json")
        run_id = (
            (created.get("payload") or {})
            .get("generation_config", {})
            .get("run_id")
        )
    except (OSError, json.JSONDecodeError, AttributeError):
        logger.warning("读取因子生成任务的 run_id 失败", exc_info=True)

    return _sanitize(
        {
            "job_id": job_dir.name,
            "status": "queued",
            "operation": "generate_factors",
            "pool_id": pool_id,
            "pool_name": pool_manifest.get("name"),
            "pool_storage": pool_storage,
            "run_id": run_id,
            "run_name": run_name,
            "data_source": source,
            "warnings": warnings,
            "request_summary": {
                "pool_id": pool_id,
                "pool_name": pool_manifest.get("name"),
                "pool_storage": pool_storage,
                "n_stocks": len(pool_codes),
                "run_id": run_id,
                "run_name": run_name,
                "data_source": source,
                "field_count": len(fields),
                "operators": operators,
                "operator_mode": "selected" if operators else "all",
                "splits": splits,
                "split_source": split_source,
                "pool_window": (
                    {
                        "start": pool_window[0].isoformat(),
                        "end": pool_window[1].isoformat(),
                    }
                    if pool_window is not None
                    else None
                ),
                "max_backtrack_days": max_backtrack_days,
                "target_horizon": target_horizon,
                "max_future_days": max_future_days,
                "target_factor_count": target_factor_count,
                "max_attempts": max_attempts,
                "rollout_timesteps": rollout_timesteps,
                "seed": seed,
                "device": device,
                "quality": quality,
            },
        }
    )
