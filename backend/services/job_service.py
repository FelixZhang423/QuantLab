"""后台任务状态查询。"""
from __future__ import annotations

import json
from typing import Any, Dict

import common
from common import _read_json, _safe_child, _sanitize
from errors import make_error


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


def list_jobs() -> list[Dict[str, Any]]:
    """Return task summaries from the same files used by worker polling."""
    jobs = []
    if not common.JOBS_ROOT.is_dir():
        return jobs
    for job_dir in sorted(common.JOBS_ROOT.iterdir(), reverse=True):
        if job_dir.is_symlink() or not (job_dir / "status.json").is_file():
            continue
        try:
            status = _read_json(job_dir / "status.json")
            config = _read_json(job_dir / "platform_job.json")
        except (OSError, ValueError):
            continue
        if not isinstance(status, dict) or not isinstance(config, dict):
            continue
        result = status.get("result") or {}
        payload = config.get("payload") or {}
        progress = status.get("progress") or {}
        if not all(isinstance(value, dict) for value in (result, payload, progress)):
            continue
        params = payload.get("config")
        if isinstance(params, dict):
            payload = {**params, **payload}
        jobs.append({
            "job_id": job_dir.name,
            "created_at": config.get("created_at"),
            **{key: status.get(key) for key in ("operation", "status", "message", "updated_at")},
            "stage": progress.get("stage"),
            "parameters": {key: payload[key] for key in ("pool_id", "run_id", "start_date", "end_date", "expression", "topk") if key in payload},
            "result": {key: result[key] for key in ("run_key", "run_id", "pool_id", "composition_id", "backtest_id") if key in result},
        })
    return _sanitize(jobs)
