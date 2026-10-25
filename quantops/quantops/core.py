"""算子底层原语：Series 助手函数。

约定：算子输入输出都是 ``pd.Series``，索引为 ``MultiIndex(date, code)``——
时间序列算子按 ``code`` 分组滚动，横截面算子按 ``date`` 分组计算。

本模块从 custom_bt/expressions.py 原样搬出（逐行等价），只把 ExpressionError
换成 quantops.errors 里的同名异常。
"""
from __future__ import annotations

from statistics import NormalDist
from typing import Any, Callable, List

import numpy as np
import pandas as pd

from quantops.errors import ExpressionError


def _as_series(value: Any, index: pd.MultiIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value
    return pd.Series(value, index=index, dtype="float64")


def _as_numeric_series(value: Any, index: pd.MultiIndex) -> pd.Series:
    return pd.to_numeric(_as_series(value, index), errors="coerce")


def _date_level(x: pd.Series) -> pd.Index:
    return x.index.get_level_values("date")


def _code_level(x: pd.Series) -> pd.Index:
    return x.index.get_level_values("code")


def _rank(x: pd.Series) -> pd.Series:
    return x.groupby(level="date").rank(pct=True)


def _zscore(x: pd.Series) -> pd.Series:
    def transform(group: pd.Series) -> pd.Series:
        std = group.std(ddof=0)
        if std == 0 or pd.isna(std):
            return group * np.nan
        return (group - group.mean()) / std

    return x.groupby(level="date").transform(transform)


def _delay(x: pd.Series, n: int) -> pd.Series:
    return x.groupby(level="code").shift(int(n))


def _delta(x: pd.Series, n: int) -> pd.Series:
    return x - _delay(x, int(n))


def _rolling(x: pd.Series, n: int, method: str) -> pd.Series:
    n = int(n)
    grouped = x.groupby(level="code")
    rolled = getattr(grouped.rolling(n, min_periods=n), method)()
    return rolled.reset_index(level=0, drop=True).sort_index()


def _rolling_apply(x: pd.Series, n: int, func: Callable[[np.ndarray], float]) -> pd.Series:
    n = int(n)
    grouped = x.groupby(level="code")
    rolled = grouped.rolling(n, min_periods=n).apply(func, raw=True)
    return rolled.reset_index(level=0, drop=True).sort_index()


def _where(cond: pd.Series, a: Any, b: Any) -> pd.Series:
    index = cond.index
    left = _as_series(a, index)
    right = _as_series(b, index)
    return pd.Series(np.where(cond, left, right), index=index)


def _filter_args(args: tuple[Any, ...], index: pd.MultiIndex, filter: bool) -> List[pd.Series]:
    out = [_as_numeric_series(arg, index) for arg in args]
    return [item.fillna(0.0) for item in out] if filter else out


def _add(*args: Any, filter: bool = False) -> pd.Series:
    index = next(arg.index for arg in args if isinstance(arg, pd.Series))
    items = _filter_args(args, index, filter)
    return pd.concat(items, axis=1).sum(axis=1, min_count=1)


def _subtract(x: Any, *args: Any, filter: bool = False) -> pd.Series:
    index = x.index if isinstance(x, pd.Series) else next(arg.index for arg in args if isinstance(arg, pd.Series))
    items = _filter_args((x,) + args, index, filter)
    result = items[0]
    for item in items[1:]:
        result = result - item
    return result


def _multiply(*args: Any, filter: bool = False) -> pd.Series:
    index = next(arg.index for arg in args if isinstance(arg, pd.Series))
    items = _filter_args(args, index, filter)
    result = items[0]
    for item in items[1:]:
        result = result * item
    return result


def _divide(x: Any, y: Any) -> pd.Series:
    index = x.index if isinstance(x, pd.Series) else y.index
    left = _as_numeric_series(x, index)
    right = _as_numeric_series(y, index)
    return left / right.replace(0, np.nan)


def _max_fn(*args: Any) -> pd.Series:
    index = next(arg.index for arg in args if isinstance(arg, pd.Series))
    return pd.concat([_as_numeric_series(arg, index) for arg in args], axis=1).max(axis=1)


def _min_fn(*args: Any) -> pd.Series:
    index = next(arg.index for arg in args if isinstance(arg, pd.Series))
    return pd.concat([_as_numeric_series(arg, index) for arg in args], axis=1).min(axis=1)


def _densify(x: pd.Series) -> pd.Series:
    codes = pd.Categorical(x).codes.astype(float)
    codes[codes < 0] = np.nan
    return pd.Series(codes, index=x.index)


def _signed_power(x: pd.Series, y: Any) -> pd.Series:
    return np.sign(x) * np.power(np.abs(x), y)


def _normalize(x: pd.Series, useStd: bool = False, limit: float = 0.0) -> pd.Series:
    centered = x - x.groupby(level="date").transform("mean")
    if useStd:
        std = x.groupby(level="date").transform(lambda group: group.std(ddof=0))
        centered = centered / std.replace(0, np.nan)
    limit = float(limit)
    return centered.clip(-limit, limit) if limit > 0 else centered


def _scale(x: pd.Series, scale: float = 1.0, longscale: float = 1.0, shortscale: float = 1.0) -> pd.Series:
    def transform(group: pd.Series) -> pd.Series:
        pos = group.clip(lower=0)
        neg = group.clip(upper=0)
        if longscale != 1 or shortscale != 1:
            pos_sum = pos.sum()
            neg_sum = neg.abs().sum()
            return pos / pos_sum * longscale if neg_sum == 0 else (pos / pos_sum * longscale).fillna(0) + (neg / neg_sum * shortscale).fillna(0)
        denom = group.abs().sum()
        return group * np.nan if denom == 0 else group / denom * scale

    return x.groupby(level="date").transform(transform)


def _winsorize(x: pd.Series, std: float = 4.0) -> pd.Series:
    mean = x.groupby(level="date").transform("mean")
    sigma = x.groupby(level="date").transform(lambda group: group.std(ddof=0))
    lower = mean - float(std) * sigma
    upper = mean + float(std) * sigma
    return x.clip(lower, upper)


def _quantile(x: pd.Series, driver: str = "gaussian", sigma: float = 1.0) -> pd.Series:
    ranked = _rank(x).clip(1e-6, 1 - 1e-6)
    driver = str(driver).lower()
    if driver == "uniform":
        return ranked - 0.5
    if driver == "cauchy":
        return float(sigma) * np.tan(np.pi * (ranked - 0.5))
    dist = NormalDist()
    return ranked.map(dist.inv_cdf) * float(sigma)


def _bucket(x: pd.Series, range: str = "0,1,0.1") -> pd.Series:
    start, end, step = [float(part.strip()) for part in str(range).split(",")]
    bucket = np.floor((x - start) / step)
    max_bucket = np.ceil((end - start) / step) - 1
    return bucket.clip(0, max_bucket)


def _group_keys(x: pd.Series, group: pd.Series) -> List[Any]:
    return [_date_level(x), group.reindex(x.index)]


def _group_rank(x: pd.Series, group: pd.Series) -> pd.Series:
    return x.groupby(_group_keys(x, group)).rank(pct=True)


def _group_neutralize(x: pd.Series, group: pd.Series) -> pd.Series:
    return x - x.groupby(_group_keys(x, group)).transform("mean")


def _group_zscore(x: pd.Series, group: pd.Series) -> pd.Series:
    mean = x.groupby(_group_keys(x, group)).transform("mean")
    std = x.groupby(_group_keys(x, group)).transform(lambda item: item.std(ddof=0))
    return (x - mean) / std.replace(0, np.nan)


def _group_scale(x: pd.Series, group: pd.Series, scale: float = 1.0) -> pd.Series:
    denom = x.abs().groupby(_group_keys(x, group)).transform("sum")
    return x / denom.replace(0, np.nan) * float(scale)


def _group_mean(x: pd.Series, weight: Any, group: pd.Series) -> pd.Series:
    w = _as_numeric_series(weight, x.index)
    wx = x * w
    keys = _group_keys(x, group)
    return wx.groupby(keys).transform("sum") / w.groupby(keys).transform("sum").replace(0, np.nan)


def _group_backfill(x: pd.Series, group: pd.Series, d: int, std: float = 4.0) -> pd.Series:
    filled = x.copy()
    group_mean = _winsorize(x, std).groupby(_group_keys(x, group)).transform("mean")
    filled = filled.fillna(group_mean)
    return filled.groupby(level="code").ffill(limit=int(d))


def _ts_rank(x: pd.Series, n: int) -> pd.Series:
    return _rolling_apply(x, n, lambda arr: pd.Series(arr).rank(pct=True).iloc[-1])


def _ts_quantile(x: pd.Series, n: int, driver: str = "gaussian", sigma: float = 1.0) -> pd.Series:
    ranked = _ts_rank(x, n).clip(1e-6, 1 - 1e-6)
    driver = str(driver).lower()
    if driver == "uniform":
        return ranked - 0.5
    if driver == "cauchy":
        return float(sigma) * np.tan(np.pi * (ranked - 0.5))
    dist = NormalDist()
    return ranked.map(dist.inv_cdf) * float(sigma)


def _ts_scale(x: pd.Series, n: int) -> pd.Series:
    low = _rolling(x, n, "min")
    high = _rolling(x, n, "max")
    return (x - low) / (high - low).replace(0, np.nan)


def _ts_arg(x: pd.Series, n: int, mode: str) -> pd.Series:
    func = np.nanargmax if mode == "max" else np.nanargmin

    def apply(arr: np.ndarray) -> float:
        if np.isnan(arr).all():
            return np.nan
        return len(arr) - 1 - float(func(arr))

    return _rolling_apply(x, n, apply)


def _ts_corr(x: pd.Series, y: pd.Series, n: int) -> pd.Series:
    data = pd.DataFrame({"x": x, "y": y})
    return data.groupby(level="code").apply(lambda g: g["x"].rolling(int(n), min_periods=int(n)).corr(g["y"])).droplevel(0).sort_index()


def _ts_covariance(x: pd.Series, y: pd.Series, n: int) -> pd.Series:
    data = pd.DataFrame({"x": x, "y": y})
    return data.groupby(level="code").apply(lambda g: g["x"].rolling(int(n), min_periods=int(n)).cov(g["y"])).droplevel(0).sort_index()


def _ts_decay_linear(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    weights = np.arange(1, n + 1, dtype=float)
    weights = weights / weights.sum()
    return _rolling_apply(x, n, lambda arr: float(np.dot(arr, weights)) if not np.isnan(arr).any() else np.nan)


def _ts_wma(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 0:
        raise ExpressionError("ts_wma window must be positive")
    weights = np.arange(n, dtype=float)
    if weights.sum() == 0:
        return _rolling(x, n, "mean")
    weights = weights / weights.sum()
    return _rolling_apply(x, n, lambda arr: float(np.dot(arr, weights)) if not np.isnan(arr).any() else np.nan)


def _ts_ema(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 0:
        raise ExpressionError("ts_ema window must be positive")
    alpha = 1.0 - 2.0 / (1.0 + n)
    weights = alpha ** np.arange(n, 0, -1, dtype=float)
    weights = weights / weights.sum()
    return _rolling_apply(x, n, lambda arr: float(np.dot(arr, weights)) if not np.isnan(arr).any() else np.nan)


def _ts_mad(x: pd.Series, n: int) -> pd.Series:
    return _rolling_apply(
        x,
        int(n),
        lambda arr: float(np.abs(arr - np.mean(arr)).mean()) if not np.isnan(arr).any() else np.nan,
    )


def _kth_element(x: pd.Series, n: int, k: int) -> pd.Series:
    k = int(k)

    def apply(arr: np.ndarray) -> float:
        valid = arr[~np.isnan(arr)]
        return np.nan if len(valid) < k or k <= 0 else valid[-k]

    return _rolling_apply(x, n, apply)


def _last_diff_value(x: pd.Series, n: int) -> pd.Series:
    def apply(arr: np.ndarray) -> float:
        cur = arr[-1]
        for value in arr[-2::-1]:
            if pd.isna(cur) != pd.isna(value) or value != cur:
                return value
        return np.nan

    return _rolling_apply(x, n, apply)


def _days_from_last_change(x: pd.Series) -> pd.Series:
    def transform(group: pd.Series) -> pd.Series:
        result = []
        days = 0
        prev = object()
        for value in group:
            if value != prev and not (pd.isna(value) and pd.isna(prev)):
                days = 0
            else:
                days += 1
            result.append(days)
            prev = value
        return pd.Series(result, index=group.index, dtype="float64")

    return x.groupby(level="code").apply(transform).droplevel(0).sort_index()


def _hump(x: pd.Series, hump: float = 0.01) -> pd.Series:
    limit = float(hump)

    def transform(group: pd.Series) -> pd.Series:
        values = []
        prev = np.nan
        for value in group:
            if pd.isna(prev) or pd.isna(value):
                cur = value
            else:
                cur = prev + np.clip(value - prev, -limit, limit)
            values.append(cur)
            prev = cur
        return pd.Series(values, index=group.index, dtype="float64")

    return x.groupby(level="code").apply(transform).droplevel(0).sort_index()


def _trade_when(x: pd.Series, y: pd.Series, z: Any) -> pd.Series:
    exit_signal = _as_series(z, x.index)

    def transform(frame: pd.DataFrame) -> pd.Series:
        held = np.nan
        values = []
        for _, row in frame.iterrows():
            if row["z"] > 0:
                held = np.nan
            elif row["x"] > 0:
                held = row["y"]
            values.append(held)
        return pd.Series(values, index=frame.index, dtype="float64")

    data = pd.DataFrame({"x": x, "y": y, "z": exit_signal})
    return data.groupby(level="code").apply(transform).droplevel(0).sort_index()
