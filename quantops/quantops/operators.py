"""算子注册表：80 个算子的实现与 ``OPERATORS`` 字典。

实现从 custom_bt/expressions.py 原样搬出（逐行等价）。每个算子都是
``Callable[..., pd.Series]``，第一个参数为 MultiIndex(date, code) 的 Series。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

import numpy as np
import pandas as pd

from quantops.core import (
    _add,
    _as_series,
    _bucket,
    _days_from_last_change,
    _delay,
    _delta,
    _densify,
    _divide,
    _group_backfill,
    _group_mean,
    _group_neutralize,
    _group_rank,
    _group_scale,
    _group_zscore,
    _hump,
    _kth_element,
    _last_diff_value,
    _max_fn,
    _min_fn,
    _multiply,
    _normalize,
    _quantile,
    _rank,
    _rolling,
    _rolling_apply,
    _scale,
    _signed_power,
    _subtract,
    _trade_when,
    _ts_arg,
    _ts_corr,
    _ts_covariance,
    _ts_decay_linear,
    _ts_ema,
    _ts_mad,
    _ts_quantile,
    _ts_rank,
    _ts_scale,
    _ts_wma,
    _where,
    _winsorize,
    _zscore,
)
from quantops.errors import ExpressionError
from quantops.registry import list_operator_definitions


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    category: str
    description: str
    func: Callable[..., Any]


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


# 注意：合并规则是「已在字面量里的算子优先」。22 个 canonical 定义里只有 3 个
# （sub / mul / div）不在上面的 OPERATORS 中，会采用定义里的 category / description；
# 其余 19 个（例如 max 用的是字面量的 "Element-wise maximum across inputs."）保留字面量文案。
# 动这段会直接改变 /api/operators 的输出 —— 不要当成"重复定义"顺手清理。
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
    """注册自定义算子：立刻可在表达式里使用（``name`` 必须是合法标识符）。"""
    if not name.isidentifier():
        raise ExpressionError(f"Invalid operator name: {name}")
    if name in {"date", "code"}:
        raise ExpressionError(f"Reserved operator name: {name}")
    OPERATORS[name] = OperatorSpec(name, category, description, func)


def list_operators() -> List[Dict[str, str]]:
    """算子清单（name / category / description，按分类和名字排序）。"""
    return [
        {"name": spec.name, "category": spec.category, "description": spec.description}
        for spec in sorted(OPERATORS.values(), key=lambda item: (item.category, item.name))
    ]
