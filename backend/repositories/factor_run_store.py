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
