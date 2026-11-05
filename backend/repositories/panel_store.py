"""因子/回测面板加载：按数据源选择公司 ClickHouse 或本地主缓存。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from repositories import company_source
from repositories.local_store import load_pool_panel
from custom_bt.engine import BacktestConfig


def load_panel_for_pool(
    source: str,
    master_store: Optional[str | Path],
    codes: list[str],
    config: BacktestConfig,
) -> pd.DataFrame:
    if source == "clickhouse":
        return company_source.load_panel(codes, config.start_date, config.end_date)
    if not master_store:
        raise ValueError("local pool requires master_store")
    return load_pool_panel(master_store, codes, config.start_date, config.end_date)
