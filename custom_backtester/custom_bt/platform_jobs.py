from __future__ import annotations

import hashlib
import json
import traceback
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping
from uuid import uuid4

from custom_bt.data import build_master_store
from custom_bt.factor_composition import compose_factors
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.factor_generation import new_factor_run_id, run_factor_generation
from custom_bt.jobs import update_job_status
from custom_bt.pools import create_pool


SUPPORTED_OPERATIONS = {
    "prepare_master",
    "create_pool",
    "generate_factors",
    "backtest_factors",
    "compose_factors",
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
        generation_config["run_id"] = new_factor_run_id(pool_id, _runtime_id_from_generation_payload(prepared))
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
    if operation == "prepare_master" and root.exists():
        for existing_dir in root.iterdir():
            if not existing_dir.is_dir():
                continue
            status_path = existing_dir / "status.json"
            if not status_path.exists():
                continue
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                status.get("operation") == "prepare_master"
                and status.get("status") in {"queued", "running"}
            ):
                raise RuntimeError(
                    "a prepare_master job is already running: "
                    f"{status.get('job_id', existing_dir.name)}"
                )
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
    if operation == "prepare_master":
        options = dict(payload)
        if job_dir is not None:
            last_update = 0.0

            def report(progress: Dict[str, object]) -> None:
                nonlocal last_update
                now = time.monotonic()
                if last_update and now - last_update < 2.0:
                    return
                last_update = now
                rows_read = int(progress.get("rows_read", 0))
                rows_written = int(progress.get("rows_written", 0))
                stocks_touched = int(progress.get("stocks_touched", 0))
                update_job_status(
                    job_dir,
                    "running",
                    f"主缓存导入中：已读取 {rows_read:,} 行，已保留 {rows_written:,} 行，已处理 {stocks_touched:,} 只股票",
                    {"progress": _jsonable(progress)},
                )

            options["progress_callback"] = report
        return build_master_store(**options)
    if operation == "create_pool":
        return create_pool(**dict(payload))
    if operation == "generate_factors":
        return run_factor_generation(**dict(payload))
    if operation == "backtest_factors":
        return backtest_accepted_factors(**dict(payload))
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
