"""因子运行/批量回测的本地文件读取与路径规则。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

_BACKTEST_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def confirmed_records(run_dir: str | Path) -> List[Dict[str, Any]]:
    """Consumers only trust a completed, checksummed confirmation; never evaluate test here."""
    import hashlib
    root = Path(run_dir)
    manifest_path = root / "confirmation_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("请先执行因子确认；candidate/旧 accepted 因子不能直接回测或组合")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "finished":
        raise ValueError("因子确认尚未完成，请等待确认任务结束")
    path = root / "confirmed_factors.jsonl"
    if not path.is_file():
        raise ValueError("已确认因子文件不存在，请检查确认任务产物")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.get("confirmed_sha256") != digest:
        raise ValueError("已确认因子校验失败，不能替换确认产物后执行回测")
    rows = read_jsonl(path)
    if any(row.get("status") != "confirmed" or row.get("confirmed") is not True for row in rows):
        raise ValueError("确认产物中包含非 confirmed 因子")
    return rows


def saved_results_root(outputs_root: str | Path) -> Path:
    root = Path(outputs_root).expanduser().resolve()
    if root.name == "saved_backtests":
        return root
    if root.name == "factor_backtests":
        return root.parent / "saved_backtests"
    return root / "saved_backtests"


def validate_backtest_id(backtest_id: str | None) -> str | None:
    if backtest_id is None:
        return None
    text = str(backtest_id).strip()
    if not text or not _BACKTEST_ID_RE.fullmatch(text):
        raise ValueError(f"invalid backtest_id: {backtest_id!r}")
    return text
