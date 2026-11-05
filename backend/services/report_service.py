"""回测结果报告：文件落盘 + 图表 + MySQL 存档的编排层。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from custom_bt.engine import BacktestResult
from infra.plotting import save_summary_png
from repositories.result_store import write_result_files

logger = logging.getLogger(__name__)


def save_result(
    result: BacktestResult,
    output_root: str | Path,
    run_name: str,
    config: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    run_dir = write_result_files(result, output_root, run_name, config=config, metadata=metadata)
    try:
        save_summary_png(result.daily_report, result.annual, run_dir / "summary.png")
    except Exception:
        logger.warning("summary png failed for backtest %s", run_name, exc_info=True)
    try:
        from repositories.mysql_store import persist_backtest

        persist_backtest(run_dir)
    except Exception:
        logger.warning("MySQL persist failed for backtest %s", run_name, exc_info=True)
    return run_dir
