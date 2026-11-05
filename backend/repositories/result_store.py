"""回测结果文件落盘：CSV / summary.json / manifest.json 与结果列表。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from custom_bt.engine import BacktestResult

SUPPORTED_RESULT_TYPES = {"manual", "factor", "composite"}

_RESULT_FILES = [
    "daily_report.csv",
    "positions.csv",
    "trades.csv",
    "annual_metrics.csv",
    "summary.json",
    "summary.png",
]


def write_result_files(
    result: BacktestResult,
    output_root: str | Path,
    run_name: str,
    config: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """写回测产物的数据文件与 manifest；PNG 由调用方（report service）生成。"""
    output_root = Path(output_root)
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    result.daily_report.to_csv(run_dir / "daily_report.csv", index=False)
    result.positions.to_csv(run_dir / "positions.csv", index=False)
    result.trades.to_csv(run_dir / "trades.csv", index=False)
    result.annual.to_csv(run_dir / "annual_metrics.csv", index=False)
    (run_dir / "summary.json").write_text(json.dumps(result.summary, indent=2), encoding="utf-8")
    manifest = {
        "run_name": run_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": list(_RESULT_FILES),
        "config": config or {},
    }
    if metadata:
        manifest.update(metadata)
    # MySQL 主键：调用方可传 metadata["run_key"] 带上股票池/因子运行前缀；
    # 否则退回结果目录相对输出根目录的路径，避免不同来源的同名结果互相覆盖。
    if not manifest.get("run_key"):
        try:
            manifest["run_key"] = run_dir.resolve().relative_to(output_root.resolve()).as_posix()
        except ValueError:  # pragma: no cover - run_dir 总是位于 output_root 下
            manifest["run_key"] = run_name
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return run_dir


def list_runs(output_root: str | Path) -> List[Dict[str, Any]]:
    output_root = Path(output_root)
    if not output_root.exists():
        return []
    runs = []
    manifest_paths = sorted(
        output_root.rglob("manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for manifest_path in manifest_paths:
        child = manifest_path.parent
        summary_path = child / "summary.json"
        if not summary_path.exists() or not (child / "daily_report.csv").exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("result_type") not in SUPPORTED_RESULT_TYPES:
            continue
        item: Dict[str, Any] = {"run_name": child.name, "path": str(child.resolve())}
        item.update(manifest)
        if not item.get("run_key"):
            try:
                item["run_key"] = child.resolve().relative_to(output_root.resolve()).as_posix()
            except ValueError:  # pragma: no cover - rglob 结果应总在根目录下
                item["run_key"] = child.name
        item["summary"] = summary
        runs.append(item)
    return runs
