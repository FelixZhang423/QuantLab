from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Type


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
    OperatorDefinition("log", "arithmetic", "Natural logarithm for positive values.", "log(close)", 1, "Log", "log", True, True, ("Log",)),
    OperatorDefinition("add", "arithmetic", "Element-wise addition.", "add(close,volume)", 2, "Add", "add", True, True, ("Add",)),
    OperatorDefinition("sub", "arithmetic", "Subtract the right operand from the left.", "sub(close,open)", 2, "Sub", "subtract", True, True, ("Sub", "subtract")),
    OperatorDefinition("mul", "arithmetic", "Element-wise multiplication.", "mul(close,volume)", 2, "Mul", "multiply", True, True, ("Mul", "multiply")),
    OperatorDefinition("div", "arithmetic", "Element-wise division.", "div(close,volume)", 2, "Div", "divide", True, True, ("Div", "divide")),
    OperatorDefinition("max", "arithmetic", "Element-wise maximum across two expressions.", "max(close,open)", 2, "Greater", "max", True, True, ("Greater",)),
    OperatorDefinition("min", "arithmetic", "Element-wise minimum across two expressions.", "min(close,open)", 2, "Less", "min", True, True, ("Less",)),
    OperatorDefinition("delay", "time_series", "Historical value delayed by n rows per stock.", "delay(close,20)", 2, "Ref", "delay", True, True, ("Ref",)),
    OperatorDefinition("ts_mean", "time_series", "Rolling mean per stock.", "ts_mean(close,20)", 2, "Mean", "ts_mean", True, True, ("Mean",)),
    OperatorDefinition("ts_sum", "time_series", "Rolling sum per stock.", "ts_sum(close,20)", 2, "Sum", "ts_sum", True, True, ("Sum",)),
    OperatorDefinition("ts_std", "time_series", "Rolling standard deviation per stock.", "ts_std(close,20)", 2, "Std", "ts_std", True, True, ("Std",)),
    OperatorDefinition("ts_var", "time_series", "Rolling variance per stock.", "ts_var(close,20)", 2, "Var", "ts_var", True, True, ("Var",)),
    OperatorDefinition("ts_max", "time_series", "Rolling maximum per stock.", "ts_max(close,20)", 2, "Max", "ts_max", True, True, ("Max",)),
    OperatorDefinition("ts_min", "time_series", "Rolling minimum per stock.", "ts_min(close,20)", 2, "Min", "ts_min", True, True, ("Min",)),
    OperatorDefinition("ts_median", "time_series", "Rolling median per stock.", "ts_median(close,20)", 2, "Med", "ts_median", True, True, ("Med",)),
    OperatorDefinition("ts_mad", "time_series", "Rolling mean absolute deviation per stock.", "ts_mad(close,20)", 2, "Mad", "ts_mad", True, True, ("Mad",)),
    OperatorDefinition("delta", "time_series", "Current value minus the delayed value.", "delta(close,20)", 2, "Delta", "delta", True, True, ("Delta",)),
    OperatorDefinition("ts_wma", "time_series", "Rolling weighted moving average per stock.", "ts_wma(close,20)", 2, "WMA", "ts_wma", True, True, ("WMA",)),
    OperatorDefinition("ts_ema", "time_series", "Rolling exponential moving average per stock.", "ts_ema(close,20)", 2, "EMA", "ts_ema", True, True, ("EMA",)),
    OperatorDefinition("ts_covariance", "time_series", "Rolling covariance per stock.", "ts_covariance(close,volume,20)", 3, "Cov", "ts_covariance", True, True, ("Cov",)),
    OperatorDefinition("ts_corr", "time_series", "Rolling correlation per stock.", "ts_corr(close,volume,20)", 3, "Corr", "ts_corr", True, True, ("Corr",)),
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


def load_alphagen_operator_classes() -> List[Type]:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    module = import_module("single_factor._vendor.alphagen.data.expression")
    classes: List[Type] = []
    for definition in _CORE_DEFINITIONS:
        if not definition.generation_enabled or definition.alphagen_name is None:
            continue
        classes.append(getattr(module, definition.alphagen_name))
    return classes


def generation_operator_names() -> Tuple[str, ...]:
    return tuple(item.canonical_name for item in _CORE_DEFINITIONS if item.generation_enabled)
