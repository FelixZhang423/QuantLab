"""Platform job dispatcher: create/run jobs and persist status.json."""
from __future__ import annotations

import hashlib
import json
import traceback
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping
from uuid import uuid4

from custom_bt.factor_composition import compose_factors
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.factor_generation import new_factor_run_id, run_factor_generation
from repositories.job_store import update_job_status
from custom_bt.manual_backtest import run_manual_backtest
from custom_bt.pools import create_pool_from_company


SUPPORTED_OPERATIONS = {
    "create_pool",
    "generate_factors",
    "confirm_factors",
    "backtest_factors",
    "compose_factors",
    "manual_backtest",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _runtime_id_from_generation_payload(payload: Mapping[str, Any]) -> str:
    runtime_key = {
        "pool_id": str(payload.get("pool_id") or "").strip(),
        "fields": list(payload.get("fields") or []),
        "splits": {
            name: {
                "cache_start": str(value.get("cache_start", "")),
                "cache_end": str(value.get("cache_end", "")),
            }
            for name, value in sorted((payload.get("splits") or {}).items())
        },
        "max_backtrack_days": int(payload.get("max_backtrack_days", 100)),
        "target_horizon": int(payload.get("target_horizon", 20)),
        "max_future_days": int(payload.get("max_future_days", 20)),
    }
    return hashlib.sha256(json.dumps(runtime_key, sort_keys=True).encode("utf-8")).hexdigest()[:10]


def _with_default_factor_run_id(operation: str, payload: Mapping[str, Any]) -> dict:
    prepared = dict(payload)
    if operation != "generate_factors":
        return prepared
    generation_config = dict(prepared.get("generation_config") or {})
    if not str(generation_config.get("run_id") or "").strip():
        pool_id = str(prepared.get("pool_id") or "pool").strip() or "pool"
        prefix = str(generation_config.get("run_name") or "").strip() or None
        generation_config["run_id"] = new_factor_run_id(
            pool_id,
            _runtime_id_from_generation_payload(prepared),
            prefix=prefix,
        )
    prepared["generation_config"] = generation_config
    return prepared


def create_platform_job(
    jobs_root: str | Path,
    operation: str,
    payload: Mapping[str, Any],
) -> Path:
    """Create a resumable background job for a platform-level operation."""
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported platform operation: {operation}")
    root = Path(jobs_root).expanduser().resolve()
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    prepared_payload = _with_default_factor_run_id(operation, payload)
    config = {
        "job_id": job_id,
        "operation": operation,
        "payload": _jsonable(prepared_payload),
        "created_at": _now(),
    }
    (job_dir / "platform_job.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    update_job_status(
        job_dir,
        "queued",
        f"platform job created: {operation}",
        {"job_id": job_id, "operation": operation, "job_dir": str(job_dir)},
    )
    return job_dir


def _run_operation(operation: str, payload: Mapping[str, Any], job_dir: Path | None = None) -> dict:
    if operation == "create_pool":
        from repositories.company_source import resolve_data_source
        options = dict(payload)
        resolve_data_source(options.pop("data_source", None))
        return create_pool_from_company(**options)
    if operation == "confirm_factors":
        from custom_bt.factor_confirmation import confirm_factor_run
        options = dict(payload)
        if job_dir is not None:
            def report(progress):
                update_job_status(job_dir, "running", "正在确认测试集因子", {"progress": _jsonable(progress)})
            options["progress_callback"] = report
        return confirm_factor_run(**options)
    if operation == "generate_factors":
        options = dict(payload)
        if job_dir is not None:
            generation_config = dict(options.get("generation_config") or {})
            generation_config.setdefault("job_id", job_dir.name)
            options["generation_config"] = generation_config
            last_update = 0.0
            last_stage = ""
            pool_id = str(options.get("pool_id") or "")

            def report(progress: Dict[str, object]) -> None:
                nonlocal last_update, last_stage
                stage = str(progress.get("stage") or "running")
                now = time.monotonic()
                # 训练阶段回调很密，2 秒内同一阶段只落一次盘。
                if (
                    stage == last_stage
                    and stage not in {"preparing_runtime", "finished"}
                    and last_update
                    and now - last_update < 2.0
                ):
                    return
                last_update = now
                last_stage = stage
                attempts = int(progress.get("attempts") or 0)
                max_attempts = int(progress.get("max_attempts") or 0)
                accepted = int(progress.get("candidate_count", progress.get("accepted_count")) or 0)
                target = int(progress.get("target_count") or 0)
                if stage == "preparing_runtime":
                    message = f"因子生成准备中：导出股票池 {pool_id} 面板并构建训练缓存"
                elif stage == "loading_panels":
                    message = "因子面板已就绪，正在加载 train / valid / test 数据"
                elif stage == "initializing":
                    message = "正在初始化 PPO 训练环境"
                elif stage == "training":
                    message = (
                        f"PPO 因子生成中：已尝试 {attempts:,} / {max_attempts:,} 次，"
                        f"候选 {accepted:,} / {target:,} 个因子"
                    )
                elif stage == "finished":
                    message = (
                        f"PPO 生成完成：共尝试 {attempts:,} 次，"
                        f"候选 {accepted:,} 个因子，正在写入运行清单"
                    )
                else:
                    message = f"因子生成任务运行中：{stage}"
                update_job_status(
                    job_dir,
                    "running",
                    message,
                    {"progress": _jsonable(progress)},
                )

            options["progress_callback"] = report
        return run_factor_generation(**options)
    if operation == "backtest_factors":
        options = dict(payload)
        if job_dir is not None:
            # 批次输出按 job_id 版本化，重复回测不会覆盖旧结果
            options["backtest_id"] = job_dir.name

            def report(progress: Dict[str, object]) -> None:
                selected = int(progress.get("selected_count") or 0)
                processed = int(progress.get("processed") or 0)
                completed = int(progress.get("completed") or 0)
                failed = int(progress.get("failed") or 0)
                stage = str(progress.get("stage") or "running")
                if stage == "finished":
                    message = f"因子回测完成：成功 {completed} 个，失败 {failed} 个"
                else:
                    message = (
                        f"因子回测中：已处理 {processed}/{selected}，"
                        f"成功 {completed} 个，失败 {failed} 个"
                    )
                update_job_status(
                    job_dir,
                    "running",
                    message,
                    {"progress": _jsonable(progress)},
                )

            options["progress_callback"] = report
        return backtest_accepted_factors(**options)
    if operation == "compose_factors":
        options = dict(payload)
        if job_dir is not None:

            def report(progress: Dict[str, object]) -> None:
                stage = str(progress.get("stage") or "running")
                candidate_count = progress.get("candidate_count")
                accepted_count = progress.get("accepted_count")
                current_size = progress.get("current_size")
                completed_sizes = progress.get("completed_sizes") or []
                parts = [f"因子组合任务运行中：{stage}"]
                if candidate_count is not None:
                    parts.append(f"候选 {int(candidate_count):,} 个")
                if accepted_count is not None:
                    parts.append(f"入池 {int(accepted_count):,} 个")
                if current_size is not None:
                    parts.append(f"当前组合规模 {int(current_size)}")
                if completed_sizes:
                    parts.append("已完成规模 " + ",".join(str(item) for item in completed_sizes))
                update_job_status(
                    job_dir,
                    "running",
                    "，".join(parts),
                    {"progress": _jsonable(progress)},
                )

            options["progress_callback"] = report
        return compose_factors(**options)
    if operation == "manual_backtest":
        options = dict(payload)
        if job_dir is not None:
            # 结果按 job_id 版本化：同一运行名称重复提交不会互相覆盖
            options["backtest_id"] = job_dir.name

            def report(progress: Dict[str, object]) -> None:
                stage = str(progress.get("stage") or "running")
                if stage == "loading_panel":
                    message = (
                        f"读取 {progress.get('data_source', '')} 面板："
                        f"{int(progress.get('n_codes') or 0):,} 只股票，"
                        f"{progress.get('start_date')} ~ {progress.get('end_date')}"
                    )
                elif stage == "evaluating":
                    message = (
                        f"计算 Alpha：{progress.get('expression')}，"
                        f"{int(progress.get('rows') or 0):,} 行"
                    )
                elif stage == "running":
                    message = (
                        f"回测执行中：{int(progress.get('n_stocks') or 0):,} 只股票，"
                        f"{int(progress.get('rows') or 0):,} 行面板"
                    )
                elif stage == "finished":
                    message = f"手动回测完成：{progress.get('run_key')}"
                else:
                    message = f"手动回测任务运行中：{stage}"
                update_job_status(
                    job_dir,
                    "running",
                    message,
                    {"progress": _jsonable(progress)},
                )

            options["progress_callback"] = report
        return run_manual_backtest(**options)
    raise ValueError(f"unsupported platform operation: {operation}")


def run_platform_job(job_dir: str | Path) -> dict:
    """Execute one platform job and persist queued/running/finished state."""
    path = Path(job_dir).expanduser().resolve()
    config_path = path / "platform_job.json"
    if not config_path.exists():
        raise FileNotFoundError(f"platform job config is missing: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    operation = str(config.get("operation", ""))
    payload = config.get("payload", {})
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported platform operation: {operation}")
    try:
        update_job_status(path, "running", f"running platform operation: {operation}")
        result = _run_operation(operation, payload, path)
        result = _jsonable(result)
        update_job_status(path, "finished", "platform operation finished", {"result": result})
        return result
    except Exception as exc:
        update_job_status(
            path,
            "failed",
            str(exc),
            {"traceback": traceback.format_exc()},
        )
        raise
