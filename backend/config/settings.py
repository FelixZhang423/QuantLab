"""集中路径配置。

默认以 `backend/` 为代码根、仓库根 `var/` 为运行期数据根；
部署或迁移目录时用 ``QL_PROJECT_ROOT`` / ``QL_VAR_ROOT`` 覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("QL_PROJECT_ROOT", str(Path(__file__).resolve().parents[1]))
).expanduser().resolve()

WORKSPACE_ROOT = PROJECT_ROOT.parent

# 所有运行期产物统一放在仓库根 var/ 下。
VAR_ROOT = Path(
    os.environ.get("QL_VAR_ROOT", str(WORKSPACE_ROOT / "var"))
).expanduser().resolve()

MASTER_DIR = VAR_ROOT / "data_cache" / "master"

POOLS_ROOT = VAR_ROOT / "data_cache" / "pools"

JOBS_ROOT = VAR_ROOT / "outputs" / "jobs"

RESULTS_ROOT = VAR_ROOT / "outputs" / "saved_backtests"

FACTOR_RUNTIME_ROOT = Path(
    os.environ.get("QL_FACTOR_RUNTIME_ROOT", str(VAR_ROOT / "data_cache" / "factor_runtime"))
).expanduser()

FACTOR_GENERATION_CONFIG_PATH = Path(
    os.environ.get(
        "QL_FACTOR_GENERATION_CONFIG", str(PROJECT_ROOT / "configs" / "factor_generation.yaml")
    )
).expanduser()

FACTOR_RUNS_ROOT = Path(
    os.environ.get("QL_FACTOR_RUNS_ROOT", str(VAR_ROOT / "factor_runs"))
).expanduser()

FIELD_DOC_PATH = next(
    iter(WORKSPACE_ROOT.glob("v_stock_daily_full_*.md")),
    WORKSPACE_ROOT / "v_stock_daily_full_字段说明.md",
)

FIELD_CATALOG_PATH = PROJECT_ROOT / "configs" / "field_catalog.json"
