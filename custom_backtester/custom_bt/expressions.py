from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Callable, Dict, List

import numpy as np
import pandas as pd

from custom_bt.operator_registry import list_operator_definitions


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    category: str
    description: str
    func: Callable[..., Any]


RESERVED_OPERATOR_ALIASES = {
    "and": "and_",
    "or": "or_",
    "not": "not_",
}


def _as_series(value: Any, index: pd.MultiIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value
    return pd.Series(value, index=index, dtype="float64")


def _preprocess_expression(expr: str) -> str:
    for source, target in RESERVED_OPERATOR_ALIASES.items():
        expr = re.sub(rf"\b{source}\s*\(", f"{target}(", expr)
    return expr


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


OPERATORS: Dict[str, OperatorSpec] = {
    "abs": OperatorSpec("abs", "arithmetic", "Absolute value.", lambda x: x.abs()),
    "add": OperatorSpec("add", "arithmetic", "Element-wise addition.", _add),
    "densify": OperatorSpec("densify", "arithmetic", "Map sparse labels to dense integer labels.", _densify),
    "divide": OperatorSpec("divide", "arithmetic", "Element-wise division.", _divide),
    "inverse": OperatorSpec("inverse", "arithmetic", "Reciprocal value, 1 / x.", lambda x: 1.0 / x.replace(0, np.nan)),
    "log": OperatorSpec("log", "arithmetic", "Natural logarithm for positive values.", lambda x: np.log(x.where(x > 0))),
    "max": OperatorSpec("max", "arithmetic", "Element-wise maximum across inputs.", _max_fn),
    "min": OperatorSpec("min", "arithmetic", "Element-wise minimum across inputs.", _min_fn),
    "multiply": OperatorSpec("multiply", "arithmetic", "Element-wise multiplication.", _multiply),
    "power": OperatorSpec("power", "arithmetic", "Element-wise power.", lambda x, y: np.power(x, y)),
    "reverse": OperatorSpec("reverse", "arithmetic", "Reverse signal direction, -x.", lambda x: -x),
    "sign": OperatorSpec("sign", "arithmetic", "Sign of a value.", lambda x: np.sign(x)),
    "signed_power": OperatorSpec("signed_power", "arithmetic", "Power transform preserving input sign.", _signed_power),
    "sqrt": OperatorSpec("sqrt", "arithmetic", "Square root for non-negative values.", lambda x: np.sqrt(x.where(x >= 0))),
    "subtract": OperatorSpec("subtract", "arithmetic", "Subtract inputs from left to right.", _subtract),
    "normalize": OperatorSpec("normalize", "cross_section", "Cross-sectional de-mean, optionally z-score and clamp.", _normalize),
    "quantile": OperatorSpec("quantile", "cross_section", "Map cross-sectional ranks to gaussian, uniform, or cauchy distribution.", _quantile),
    "rank": OperatorSpec("rank", "cross_section", "Cross-sectional percentile rank by date.", _rank),
    "scale": OperatorSpec("scale", "cross_section", "Scale cross-section so sum(abs(x)) equals target scale.", _scale),
    "winsorize": OperatorSpec("winsorize", "cross_section", "Clamp cross-sectional outliers by standard deviations.", _winsorize),
    "zscore": OperatorSpec("zscore", "cross_section", "Cross-sectional z-score by date.", _zscore),
    "group_backfill": OperatorSpec("group_backfill", "group", "Fill missing values using same-date group mean, then time-series ffill.", _group_backfill),
    "group_mean": OperatorSpec("group_mean", "group", "Weighted group mean by date.", _group_mean),
    "group_neutralize": OperatorSpec("group_neutralize", "group", "Subtract same-date group mean.", _group_neutralize),
    "group_rank": OperatorSpec("group_rank", "group", "Rank within each same-date group.", _group_rank),
    "group_scale": OperatorSpec("group_scale", "group", "Scale within each same-date group.", _group_scale),
    "group_zscore": OperatorSpec("group_zscore", "group", "Z-score within each same-date group.", _group_zscore),
    "and_": OperatorSpec("and_", "logic", "Element-wise logical and. Alias for BRAIN and().", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index).astype(bool) & _as_series(y, x.index if isinstance(x, pd.Series) else y.index).astype(bool)),
    "equal": OperatorSpec("equal", "logic", "Element-wise equality.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) == _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "greater": OperatorSpec("greater", "logic", "Element-wise greater-than comparison.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) > _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "greater_equal": OperatorSpec("greater_equal", "logic", "Element-wise greater-than-or-equal comparison.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) >= _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "if_else": OperatorSpec("if_else", "logic", "Vectorized conditional selection.", _where),
    "is_nan": OperatorSpec("is_nan", "logic", "Element-wise NaN check.", lambda x: pd.isna(x)),
    "less": OperatorSpec("less", "logic", "Element-wise less-than comparison.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) < _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "less_equal": OperatorSpec("less_equal", "logic", "Element-wise less-than-or-equal comparison.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) <= _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "not_": OperatorSpec("not_", "logic", "Element-wise logical not. Alias for BRAIN not().", lambda x: ~_as_series(x, x.index).astype(bool)),
    "not_equal": OperatorSpec("not_equal", "logic", "Element-wise inequality.", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index) != _as_series(y, x.index if isinstance(x, pd.Series) else y.index)),
    "or_": OperatorSpec("or_", "logic", "Element-wise logical or. Alias for BRAIN or().", lambda x, y: _as_series(x, y.index if isinstance(y, pd.Series) else x.index).astype(bool) | _as_series(y, x.index if isinstance(x, pd.Series) else y.index).astype(bool)),
    "delay": OperatorSpec("delay", "time_series", "Lag a series by n trading rows per stock.", _delay),
    "delta": OperatorSpec("delta", "time_series", "Current value minus delayed value.", _delta),
    "days_from_last_change": OperatorSpec("days_from_last_change", "time_series", "Days since value last changed per stock.", _days_from_last_change),
    "hump": OperatorSpec("hump", "time_series", "Limit day-to-day signal changes per stock.", _hump),
    "kth_element": OperatorSpec("kth_element", "time_series", "K-th most recent valid value in a rolling window.", _kth_element),
    "last_diff_value": OperatorSpec("last_diff_value", "time_series", "Most recent previous value different from current value.", _last_diff_value),
    "ts_arg_max": OperatorSpec("ts_arg_max", "time_series", "Days since rolling maximum occurred.", lambda x, n: _ts_arg(x, n, "max")),
    "ts_arg_min": OperatorSpec("ts_arg_min", "time_series", "Days since rolling minimum occurred.", lambda x, n: _ts_arg(x, n, "min")),
    "ts_av_diff": OperatorSpec("ts_av_diff", "time_series", "Current value minus rolling mean.", lambda x, n: x - _rolling(x, n, "mean")),
    "ts_backfill": OperatorSpec("ts_backfill", "time_series", "Forward-fill missing values per stock with limit n.", lambda x, n: x.groupby(level="code").ffill(limit=int(n))),
    "ts_corr": OperatorSpec("ts_corr", "time_series", "Rolling correlation per stock.", _ts_corr),
    "ts_count_nans": OperatorSpec("ts_count_nans", "time_series", "Rolling count of NaN values per stock.", lambda x, n: _rolling_apply(x, n, lambda arr: float(np.isnan(arr).sum()))),
    "ts_covariance": OperatorSpec("ts_covariance", "time_series", "Rolling covariance per stock.", _ts_covariance),
    "ts_decay_linear": OperatorSpec("ts_decay_linear", "time_series", "Linearly weighted rolling mean per stock.", _ts_decay_linear),
    "ts_wma": OperatorSpec("ts_wma", "time_series", "AlphaGen-compatible weighted moving average.", _ts_wma),
    "ts_ema": OperatorSpec("ts_ema", "time_series", "AlphaGen-compatible weighted exponential moving average.", _ts_ema),
    "ts_delay": OperatorSpec("ts_delay", "time_series", "Alias of delay.", _delay),
    "ts_delta": OperatorSpec("ts_delta", "time_series", "Alias of delta.", _delta),
    "ts_mean": OperatorSpec("ts_mean", "time_series", "Rolling mean per stock.", lambda x, n: _rolling(x, n, "mean")),
    "ts_var": OperatorSpec("ts_var", "time_series", "Rolling variance per stock.", lambda x, n: _rolling(x, n, "var")),
    "ts_median": OperatorSpec("ts_median", "time_series", "Rolling median per stock.", lambda x, n: _rolling(x, n, "median")),
    "ts_mad": OperatorSpec("ts_mad", "time_series", "Rolling mean absolute deviation per stock.", _ts_mad),
    "ts_product": OperatorSpec("ts_product", "time_series", "Rolling product per stock.", lambda x, n: _rolling_apply(x, n, lambda arr: float(np.prod(arr)))),
    "ts_quantile": OperatorSpec("ts_quantile", "time_series", "Map rolling rank to gaussian, uniform, or cauchy distribution.", _ts_quantile),
    "ts_rank": OperatorSpec("ts_rank", "time_series", "Rolling percentile rank of current value per stock.", _ts_rank),
    "ts_regression": OperatorSpec("ts_regression", "time_series", "Rolling regression slope of y on x per stock.", lambda y, x, n: _ts_covariance(y, x, n) / _rolling(x, n, "var").replace(0, np.nan)),
    "ts_scale": OperatorSpec("ts_scale", "time_series", "Rolling min-max scale per stock.", _ts_scale),
    "ts_step": OperatorSpec("ts_step", "time_series", "Per-stock row number starting from 0.", lambda x: pd.Series(np.arange(len(x)), index=x.index).groupby(level="code").cumcount().astype(float)),
    "ts_std": OperatorSpec("ts_std", "time_series", "Rolling std per stock.", lambda x, n: _rolling(x, n, "std")),
    "ts_std_dev": OperatorSpec("ts_std_dev", "time_series", "Alias of ts_std.", lambda x, n: _rolling(x, n, "std")),
    "ts_min": OperatorSpec("ts_min", "time_series", "Rolling min per stock.", lambda x, n: _rolling(x, n, "min")),
    "ts_max": OperatorSpec("ts_max", "time_series", "Rolling max per stock.", lambda x, n: _rolling(x, n, "max")),
    "ts_sum": OperatorSpec("ts_sum", "time_series", "Rolling sum per stock.", lambda x, n: _rolling(x, n, "sum")),
    "ts_zscore": OperatorSpec("ts_zscore", "time_series", "Rolling z-score per stock.", lambda x, n: (x - _rolling(x, n, "mean")) / _rolling(x, n, "std").replace(0, np.nan)),
    "bucket": OperatorSpec("bucket", "transformational", "Bucket numeric values using a range string like '0,1,0.1'.", _bucket),
    "trade_when": OperatorSpec("trade_when", "transformational", "Stateful trade switch per stock.", _trade_when),
    "vec_avg": OperatorSpec("vec_avg", "vector", "Daily scalar data passthrough for vector average compatibility.", lambda x: x),
    "vec_sum": OperatorSpec("vec_sum", "vector", "Daily scalar data passthrough for vector sum compatibility.", lambda x: x),
    "where": OperatorSpec("where", "logic", "Vectorized conditional selection.", _where),
}


for _definition in list_operator_definitions():
    if _definition.canonical_name in OPERATORS:
        continue
    _implementation = OPERATORS.get(_definition.local_impl)
    if _implementation is None:
        raise ExpressionError(
            f"canonical operator {_definition.canonical_name!r} has no local implementation "
            f"{_definition.local_impl!r}"
        )
    OPERATORS[_definition.canonical_name] = OperatorSpec(
        _definition.canonical_name,
        _definition.category,
        _definition.description,
        _implementation.func,
    )


def register_operator(name: str, category: str, description: str, func: Callable[..., Any]) -> None:
    if not name.isidentifier():
        raise ExpressionError(f"Invalid operator name: {name}")
    if name in {"date", "code"}:
        raise ExpressionError(f"Reserved operator name: {name}")
    OPERATORS[name] = OperatorSpec(name, category, description, func)


ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.keyword,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Mod,
    ast.Compare,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
    ast.BoolOp,
    ast.And,
    ast.Or,
)


def list_operators() -> List[Dict[str, str]]:
    return [
        {"name": spec.name, "category": spec.category, "description": spec.description}
        for spec in sorted(OPERATORS.values(), key=lambda item: (item.category, item.name))
    ]


def available_fields(panel: pd.DataFrame) -> List[Dict[str, str]]:
    skip = {"date", "code"}
    fields = []
    for col in panel.columns:
        if col in skip:
            continue
        dtype = str(panel[col].dtype)
        fields.append({"name": col, "dtype": dtype})
    return fields


def _validate_ast(expr: str, variables: Dict[str, Any]) -> ast.Expression:
    try:
        tree = ast.parse(_preprocess_expression(expr), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(str(exc)) from exc
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ExpressionError(f"Unsupported expression syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in OPERATORS:
                raise ExpressionError("Only registered operator calls are allowed")
        if isinstance(node, ast.Name) and node.id not in variables and node.id not in OPERATORS:
            raise ExpressionError(f"Unknown field or operator: {node.id}")
    return tree


def evaluate_expression(expr: str, panel: pd.DataFrame, output_name: str = "alpha") -> pd.DataFrame:
    required = {"date", "code"}
    if not required.issubset(panel.columns):
        raise ExpressionError("panel must include date and code columns")
    data = panel.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    data = data.sort_values(["date", "code"])
    indexed = data.set_index(["date", "code"], drop=False)
    variables: Dict[str, Any] = {}
    for col in indexed.columns:
        if col in {"date", "code"}:
            continue
        if pd.api.types.is_numeric_dtype(indexed[col]):
            variables[col] = indexed[col].astype(float)
        else:
            variables[col] = indexed[col]
    variables.update({"gaussian": "gaussian", "uniform": "uniform", "cauchy": "cauchy"})
    variables.update({name: spec.func for name, spec in OPERATORS.items()})
    tree = _validate_ast(expr, variables)
    try:
        value = eval(compile(tree, "<alpha-expression>", "eval"), {"__builtins__": {}}, variables)
    except Exception as exc:
        raise ExpressionError(str(exc)) from exc
    alpha = _as_series(value, indexed.index).rename(output_name)
    return alpha.reset_index()[["date", "code", output_name]]
