"""Chronological split isolation checked against the immutable market calendar."""
from __future__ import annotations

import pandas as pd

SPLIT_NAMES = ("train", "valid", "test")


def validate_splits(splits, dates, target_horizon: int, *, require_all=False) -> dict:
    if require_all and set(splits) != set(SPLIT_NAMES):
        raise ValueError("因子生成和确认必须包含 train、valid、test 三个切分")
    calendar = pd.DatetimeIndex(pd.to_datetime(dates)).drop_duplicates().sort_values()
    windows = []
    for name in SPLIT_NAMES:
        if name not in splits:
            continue
        value = splits[name]
        start, end = pd.Timestamp(value["cache_start"]), pd.Timestamp(value["cache_end"])
        if start > end:
            raise ValueError(f"{name} 切分起点晚于终点")
        actual = calendar[(calendar >= start) & (calendar <= end)]
        if actual.empty:
            raise ValueError(f"{name} 切分没有交易日")
        windows.append((name, start, end))
    gaps = {}
    for (left, _, end), (right, start, _) in zip(windows, windows[1:]):
        if end >= start:
            raise ValueError(f"{left}/{right} 切分重叠或顺序错误")
        gap = int(((calendar > end) & (calendar < start)).sum())
        if gap < target_horizon:
            raise ValueError(f"{left}/{right} 隔离不足：{gap} 个交易日，至少需要 target_horizon={target_horizon}")
        gaps[f"{left}_{right}"] = gap
    return {"gap_trading_days": gaps, "required_gap": target_horizon,
            "label_policy": "forward targets stay inside each disjoint cache window"}
