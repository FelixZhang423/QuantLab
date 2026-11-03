"""算子元数据注册表：canonical 名、分类、arity、示例与 BRAIN/AlphaGen 对应关系。

从 custom_bt/operator_registry.py 原样搬出，只去掉了依赖本仓库 single_factor/_vendor
的 ``load_alphagen_operator_classes``（它留在 custom_bt 里）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OperatorDefinition:
    canonical_name: str
    category: str
    description: str
    example: str
    arity: int
    alphagen_name: Optional[str]
    local_impl: str
    generation_enabled: bool = False
    manual_enabled: bool = True
    aliases: Tuple[str, ...] = ()


_CORE_DEFINITIONS: Tuple[OperatorDefinition, ...] = (
    OperatorDefinition("abs", "arithmetic", "Absolute value.", "abs(close)", 1, "Abs", "abs", True, True, ("Abs",)),
    OperatorDefinition("sign", "arithmetic", "Sign of a value.", "sign(close)", 1, "Sign", "sign", True, True, ("Sign",)),
    OperatorDefinition("inverse", "arithmetic", "Reciprocal value, 1 / x.", "inverse(close)", 1, "Inverse", "inverse", True, True, ("Inverse",)),
    OperatorDefinition("reverse", "arithmetic", "Reverse signal direction, -x.", "reverse(close)", 1, "Reverse", "reverse", True, True, ("Reverse",)),
    OperatorDefinition("sqrt", "arithmetic", "Square root for non-negative values.", "sqrt(close)", 1, "Sqrt", "sqrt", True, True, ("Sqrt",)),
    OperatorDefinition("log", "arithmetic", "Natural logarithm for positive values.", "log(close)", 1, "Log", "log", True, True, ("Log",)),
    OperatorDefinition("add", "arithmetic", "Element-wise addition.", "add(close,volume)", 2, "Add", "add", True, True, ("Add",)),
    OperatorDefinition("power", "arithmetic", "Element-wise power.", "power(close,2)", 2, "Pow", "power", True, True, ("Pow",)),
    OperatorDefinition("signed_power", "arithmetic", "Power transform preserving input sign.", "signed_power(close,2)", 2, "SignedPower", "signed_power", True, True, ("SignedPower",)),
    OperatorDefinition("sub", "arithmetic", "Subtract the right operand from the left.", "sub(close,open)", 2, "Sub", "subtract", True, True, ("Sub", "subtract")),
    OperatorDefinition("mul", "arithmetic", "Element-wise multiplication.", "mul(close,volume)", 2, "Mul", "multiply", True, True, ("Mul", "multiply")),
    OperatorDefinition("div", "arithmetic", "Element-wise division.", "div(close,volume)", 2, "Div", "divide", True, True, ("Div", "divide")),
    OperatorDefinition("max", "arithmetic", "Element-wise maximum across two expressions.", "max(close,open)", 2, "Greater", "max", True, True, ("Greater",)),
    OperatorDefinition("min", "arithmetic", "Element-wise minimum across two expressions.", "min(close,open)", 2, "Less", "min", True, True, ("Less",)),
    OperatorDefinition("rank", "cross_section", "Cross-sectional percentile rank by date.", "rank(close)", 1, "CSRank", "rank", True, True, ("CSRank",)),
    OperatorDefinition("quantile", "cross_section", "Map cross-sectional ranks to a gaussian distribution.", "quantile(close)", 1, "Quantile", "quantile", True, True, ("Quantile",)),
    OperatorDefinition("zscore", "cross_section", "Cross-sectional z-score by date.", "zscore(close)", 1, "ZScore", "zscore", True, True, ("ZScore",)),
    OperatorDefinition("scale", "cross_section", "Scale cross-section so sum(abs(x)) equals one.", "scale(close)", 1, "Scale", "scale", True, True, ("Scale",)),
    OperatorDefinition("winsorize", "cross_section", "Clamp cross-sectional outliers by standard deviations.", "winsorize(close)", 1, "Winsorize", "winsorize", True, True, ("Winsorize",)),
    OperatorDefinition("normalize", "cross_section", "Cross-sectional de-mean by date.", "normalize(close)", 1, "Normalize", "normalize", True, True, ("Normalize",)),
    OperatorDefinition("and_", "logic", "Element-wise logical and.", "and_(greater(close,open), greater(volume,0))", 2, "And", "and_", True, True, ("And",)),
    OperatorDefinition("or_", "logic", "Element-wise logical or.", "or_(greater(close,open), less(close,open))", 2, "Or", "or_", True, True, ("Or",)),
    OperatorDefinition("not_", "logic", "Element-wise logical not.", "not_(is_nan(close))", 1, "Not", "not_", True, True, ("Not",)),
    OperatorDefinition("equal", "logic", "Element-wise equality.", "equal(close,open)", 2, "Equal", "equal", True, True, ("Equal",)),
    OperatorDefinition("not_equal", "logic", "Element-wise inequality.", "not_equal(close,open)", 2, "NotEqual", "not_equal", True, True, ("NotEqual",)),
    OperatorDefinition("greater", "logic", "Element-wise greater-than comparison.", "greater(close,open)", 2, "GreaterThan", "greater", True, True, ("GreaterThan",)),
    OperatorDefinition("greater_equal", "logic", "Element-wise greater-than-or-equal comparison.", "greater_equal(close,open)", 2, "GreaterEqual", "greater_equal", True, True, ("GreaterEqual",)),
    OperatorDefinition("less", "logic", "Element-wise less-than comparison.", "less(close,open)", 2, "LessThan", "less", True, True, ("LessThan",)),
    OperatorDefinition("less_equal", "logic", "Element-wise less-than-or-equal comparison.", "less_equal(close,open)", 2, "LessEqual", "less_equal", True, True, ("LessEqual",)),
    OperatorDefinition("is_nan", "logic", "Element-wise NaN check.", "is_nan(close)", 1, "IsNan", "is_nan", True, True, ("IsNan",)),
    OperatorDefinition("if_else", "logic", "Vectorized conditional selection.", "if_else(greater(close,open),close,open)", 3, "IfElse", "if_else", True, True, ("IfElse", "where")),
    OperatorDefinition("delay", "time_series", "Historical value delayed by n rows per stock.", "delay(close,20)", 2, "Ref", "delay", True, True, ("Ref", "ts_delay")),
    OperatorDefinition("days_from_last_change", "time_series", "Days since the value last changed per stock.", "days_from_last_change(close)", 1, "DaysFromLastChange", "days_from_last_change", True, True, ("DaysFromLastChange",)),
    OperatorDefinition("hump", "time_series", "Limit day-to-day signal changes per stock.", "hump(close)", 1, "Hump", "hump", True, True, ("Hump",)),
    OperatorDefinition("ts_mean", "time_series", "Rolling mean per stock.", "ts_mean(close,20)", 2, "Mean", "ts_mean", True, True, ("Mean",)),
    OperatorDefinition("ts_sum", "time_series", "Rolling sum per stock.", "ts_sum(close,20)", 2, "Sum", "ts_sum", True, True, ("Sum",)),
    OperatorDefinition("ts_std", "time_series", "Rolling standard deviation per stock.", "ts_std(close,20)", 2, "Std", "ts_std", True, True, ("Std", "ts_std_dev")),
    OperatorDefinition("ts_var", "time_series", "Rolling variance per stock.", "ts_var(close,20)", 2, "Var", "ts_var", True, True, ("Var",)),
    OperatorDefinition("ts_skew", "time_series", "Rolling skewness per stock.", "ts_skew(close,20)", 2, "Skew", "ts_skew", True, True, ("Skew",)),
    OperatorDefinition("ts_kurt", "time_series", "Rolling excess kurtosis per stock.", "ts_kurt(close,20)", 2, "Kurt", "ts_kurt", True, True, ("Kurt",)),
    OperatorDefinition("ts_max", "time_series", "Rolling maximum per stock.", "ts_max(close,20)", 2, "Max", "ts_max", True, True, ("Max",)),
    OperatorDefinition("ts_min", "time_series", "Rolling minimum per stock.", "ts_min(close,20)", 2, "Min", "ts_min", True, True, ("Min",)),
    OperatorDefinition("ts_median", "time_series", "Rolling median per stock.", "ts_median(close,20)", 2, "Med", "ts_median", True, True, ("Med",)),
    OperatorDefinition("ts_mad", "time_series", "Rolling mean absolute deviation per stock.", "ts_mad(close,20)", 2, "Mad", "ts_mad", True, True, ("Mad",)),
    OperatorDefinition("ts_rank", "time_series", "Rolling percentile rank of current value per stock.", "ts_rank(close,20)", 2, "Rank", "ts_rank", True, True, ("Rank",)),
    OperatorDefinition("ts_arg_max", "time_series", "Days since the rolling maximum occurred.", "ts_arg_max(close,20)", 2, "TSArgMax", "ts_arg_max", True, True, ("TSArgMax",)),
    OperatorDefinition("ts_arg_min", "time_series", "Days since the rolling minimum occurred.", "ts_arg_min(close,20)", 2, "TSArgMin", "ts_arg_min", True, True, ("TSArgMin",)),
    OperatorDefinition("ts_av_diff", "time_series", "Current value minus the rolling mean.", "ts_av_diff(close,20)", 2, "TSAvDiff", "ts_av_diff", True, True, ("TSAvDiff",)),
    OperatorDefinition("ts_backfill", "time_series", "Forward-fill missing values per stock with limit n.", "ts_backfill(close,5)", 2, "TSBackfill", "ts_backfill", True, True, ("TSBackfill",)),
    OperatorDefinition("ts_count_nans", "time_series", "Rolling count of NaN values per stock.", "ts_count_nans(close,20)", 2, "TSCountNans", "ts_count_nans", True, True, ("TSCountNans",)),
    OperatorDefinition("ts_decay_linear", "time_series", "Linearly weighted rolling mean per stock.", "ts_decay_linear(close,10)", 2, "TSDecayLinear", "ts_decay_linear", True, True, ("TSDecayLinear",)),
    # PPO 禁用：长窗口乘积数值爆炸；人工表达式仍可使用。
    OperatorDefinition("ts_product", "time_series", "Rolling product per stock.", "ts_product(close,5)", 2, "TSProduct", "ts_product", False, True, ("TSProduct",)),
    OperatorDefinition("ts_quantile", "time_series", "Map rolling rank to a gaussian distribution.", "ts_quantile(close,20)", 2, "TSQuantile", "ts_quantile", True, True, ("TSQuantile",)),
    OperatorDefinition("ts_scale", "time_series", "Rolling min-max scale per stock.", "ts_scale(close,20)", 2, "TSScale", "ts_scale", True, True, ("TSScale",)),
    OperatorDefinition("ts_zscore", "time_series", "Rolling z-score per stock.", "ts_zscore(close,20)", 2, "TSZScore", "ts_zscore", True, True, ("TSZScore",)),
    OperatorDefinition("kth_element", "time_series", "K-th most recent valid value in a rolling window.", "kth_element(close,20)", 2, "KthElement", "kth_element", True, True, ("KthElement",)),
    OperatorDefinition("last_diff_value", "time_series", "Most recent previous value different from current value.", "last_diff_value(close,20)", 2, "LastDiffValue", "last_diff_value", True, True, ("LastDiffValue",)),
    OperatorDefinition("delta", "time_series", "Current value minus the delayed value.", "delta(close,20)", 2, "Delta", "delta", True, True, ("Delta", "ts_delta")),
    OperatorDefinition("ts_wma", "time_series", "Rolling weighted moving average per stock.", "ts_wma(close,20)", 2, "WMA", "ts_wma", True, True, ("WMA",)),
    OperatorDefinition("ts_ema", "time_series", "Rolling exponential moving average per stock.", "ts_ema(close,20)", 2, "EMA", "ts_ema", True, True, ("EMA",)),
    OperatorDefinition("ts_covariance", "time_series", "Rolling covariance per stock.", "ts_covariance(close,volume,20)", 3, "Cov", "ts_covariance", True, True, ("Cov",)),
    OperatorDefinition("ts_corr", "time_series", "Rolling correlation per stock.", "ts_corr(close,volume,20)", 3, "Corr", "ts_corr", True, True, ("Corr",)),
    OperatorDefinition("ts_regression", "time_series", "Rolling regression slope of y on x per stock.", "ts_regression(close,volume,20)", 3, "TSRegression", "ts_regression", True, True, ("TSRegression",)),
    # PPO 禁用：每只股票的时间序号与横截面 IC 无关，只会稀释搜索。
    OperatorDefinition("ts_step", "time_series", "Per-stock row number starting from 0.", "ts_step(close)", 1, "TSStep", "ts_step", False, True, ("TSStep",)),
)


_BY_CANONICAL: Dict[str, OperatorDefinition] = {
    item.canonical_name: item for item in _CORE_DEFINITIONS
}
_BY_ALIAS: Dict[str, OperatorDefinition] = {}
for _item in _CORE_DEFINITIONS:
    _BY_ALIAS[_item.canonical_name] = _item
    for _alias in _item.aliases:
        _BY_ALIAS[_alias] = _item


def list_operator_definitions() -> List[OperatorDefinition]:
    return list(_CORE_DEFINITIONS)


def get_operator(name: str) -> OperatorDefinition:
    try:
        return _BY_CANONICAL[name]
    except KeyError:
        try:
            return _BY_ALIAS[name]
        except KeyError as exc:
            raise KeyError(f"unknown canonical operator: {name}") from exc


def canonical_name(name: str) -> str:
    return get_operator(name).canonical_name


def generation_operator_names() -> Tuple[str, ...]:
    return tuple(item.canonical_name for item in _CORE_DEFINITIONS if item.generation_enabled)
