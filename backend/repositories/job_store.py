"""后台任务状态文件（status.json）的读写。"""
from __future__ import annotations

import json
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(payload)
    try:
        for attempt in range(10):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(min(0.1 * (attempt + 1), 1.0))
    finally:
        tmp.unlink(missing_ok=True)


def load_job_status(job_dir: str | Path) -> Dict[str, Any]:
    path = Path(job_dir) / "status.json"
    if not path.exists():
        return {"status": "missing", "message": "任务状态文件不存在"}
    return json.loads(path.read_text(encoding="utf-8"))


def update_job_status(
    job_dir: str | Path,
    status: str,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job_dir = Path(job_dir)
    current = load_job_status(job_dir)
    if status in {"queued", "running"}:
        current.pop("traceback", None)
        current.pop("result", None)
        current.pop("progress", None)
    current.update({"status": status, "message": message, "updated_at": now()})
    if extra:
        current.update(extra)
    atomic_write_json(job_dir / "status.json", current)
    return current


# 兼容旧名（jobs.py 内部曾用下划线前缀）
_now = now
_atomic_write_json = atomic_write_json
