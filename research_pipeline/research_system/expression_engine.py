"""Independent evaluator for the expression language used by generated factors."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd


class ExpressionError(ValueError):
    """Raised when a factor expression is invalid or cannot be evaluated."""


@dataclass(frozen=True)
class _Call:
    name: str
    args: tuple[ast.AST, ...]


def _as_series(value: Any, index: pd.MultiIndex) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index)
    return pd.Series(value, index=index, dtype="float64")


def _numeric(value: Any, index: pd.MultiIndex) -> pd.Series:
    return pd.to_numeric(_as_series(value, index), errors="coerce").astype(float)


def _rolling(value: pd.Series, window: int, method: str) -> pd.Series:
    if window <= 0:
        raise ExpressionError("rolling window must be positive")
    grouped = value.groupby(level="code", sort=False)
    rolled = getattr(grouped.rolling(window, min_periods=window), method)()
    return rolled.reset_index(level=0, drop=True).reindex(value.index)


def _rolling_apply(value: pd.Series, window: int, func: Callable[[np.ndarray], float]) -> pd.Series:
    if window <= 0:
        raise ExpressionError("rolling window must be positive")
    grouped = value.groupby(level="code", sort=False)
    rolled = grouped.rolling(window, min_periods=window).apply(func, raw=True)
    return rolled.reset_index(level=0, drop=True).reindex(value.index)


def _binary(values: tuple[Any, ...], index: pd.MultiIndex, operation: Callable[[pd.Series, pd.Series], pd.Series]) -> pd.Series:
    if len(values) < 2:
        raise ExpressionError("binary operator needs at least two operands")
    result = _numeric(values[0], index)
    for value in values[1:]:
        result = operation(result, _numeric(value, index))
    return result


def _evaluate_call(name: str, values: tuple[Any, ...], index: pd.MultiIndex) -> Any:
    aliases = {
        "Abs": "abs", "Add": "add", "Sub": "sub", "Mul": "mul", "Div": "div",
        "Greater": "max", "Less": "min", "Mean": "ts_mean", "Med": "ts_median",
        "Std": "ts_std", "Sum": "ts_sum", "Max": "ts_max", "Min": "ts_min",
        "Var": "ts_var", "WMA": "ts_wma", "EMA": "ts_ema", "Cov": "ts_covariance",
        "Corr": "ts_corr", "Mad": "ts_mad", "Delta": "delta", "Ref": "delay",
    }
    name = aliases.get(name, name)
    if name == "abs":
        return _numeric(values[0], index).abs()
    if name == "add":
        return _binary(values, index, lambda left, right: left + right)
    if name in {"sub", "subtract"}:
        return _binary(values, index, lambda left, right: left - right)
    if name in {"mul", "multiply"}:
        return _binary(values, index, lambda left, right: left * right)
    if name in {"div", "divide"}:
        return _binary(values, index, lambda left, right: left / right.replace(0, np.nan))
    if name == "max":
        return pd.concat([_numeric(value, index) for value in values], axis=1).max(axis=1)
    if name == "min":
        return pd.concat([_numeric(value, index) for value in values], axis=1).min(axis=1)
    if name == "log":
        value = _numeric(values[0], index)
        return np.log(value.where(value > 0))
    if name == "rank":
        return _numeric(values[0], index).groupby(level="date").rank(pct=True)
    if name in {"delay", "ts_delay"}:
        return _numeric(values[0], index).groupby(level="code", sort=False).shift(_integer(values[1]))
    if name in {"delta", "ts_delta"}:
        value = _numeric(values[0], index)
        return value - value.groupby(level="code", sort=False).shift(_integer(values[1]))
    if name in {"ts_mean", "ts_sum", "ts_std", "ts_var", "ts_min", "ts_max", "ts_median"}:
        return _rolling(_numeric(values[0], index), _integer(values[1]), {
            "ts_mean": "mean", "ts_sum": "sum", "ts_std": "std", "ts_var": "var",
            "ts_min": "min", "ts_max": "max", "ts_median": "median",
        }[name])
    if name == "ts_mad":
        return _rolling_apply(_numeric(values[0], index), _integer(values[1]), lambda arr: float(np.abs(arr - np.mean(arr)).mean()))
    if name in {"ts_wma", "ts_ema"}:
        window = _integer(values[1])
        weights = np.arange(1, window + 1, dtype=float)
        if name == "ts_ema":
            decay = 1.0 - 2.0 / (1.0 + window)
            weights = decay ** np.arange(window, 0, -1, dtype=float)
        weights /= weights.sum()
        return _rolling_apply(_numeric(values[0], index), window, lambda arr: float(np.dot(arr, weights)))
    if name in {"ts_corr", "ts_covariance"}:
        left = _numeric(values[0], index)
        right = _numeric(values[1], index)
        window = _integer(values[2])
        frame = pd.DataFrame({"left": left, "right": right})
        method = "corr" if name == "ts_corr" else "cov"
        result = frame.groupby(level="code", sort=False).apply(
            lambda group: getattr(group["left"].rolling(window, min_periods=window), method)(group["right"])
        )
        return result.reset_index(level=0, drop=True).reindex(index)
    raise ExpressionError(f"unknown operator: {name}")


def _integer(value: Any) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"window or delay must be numeric: {value!r}") from exc
    return result


def _validate(node: ast.AST, fields: set[str]) -> None:
    allowed = (ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)
    for item in ast.walk(node):
        if not isinstance(item, allowed):
            raise ExpressionError(f"unsupported expression syntax: {type(item).__name__}")
        if isinstance(item, ast.Name) and item.id not in fields and not _is_operator(item.id):
            raise ExpressionError(f"unknown field: {item.id}")
        if isinstance(item, ast.Call):
            if not isinstance(item.func, ast.Name) or not _is_operator(item.func.id):
                raise ExpressionError("only registered operators may be called")
            if item.keywords:
                raise ExpressionError("keyword arguments are not supported")


def _is_operator(name: str) -> bool:
    return name in {
        "abs", "Abs", "add", "Add", "sub", "Sub", "subtract", "mul", "Mul", "multiply", "div", "Div", "divide",
        "max", "Max", "Greater", "min", "Min", "Less", "log", "Log", "rank", "delay", "Ref", "delta", "Delta",
        "ts_mean", "Mean", "ts_sum", "Sum", "ts_std", "Std", "ts_var", "Var", "ts_min", "Min", "ts_max", "Max",
        "ts_median", "Med", "ts_mad", "Mad", "ts_wma", "WMA", "ts_ema", "EMA", "ts_corr", "Corr", "ts_covariance", "Cov",
    }


def _evaluate(node: ast.AST, variables: dict[str, Any], index: pd.MultiIndex) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, variables, index)
    if isinstance(node, ast.Name):
        return variables[node.id]
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ExpressionError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.UnaryOp):
        value = _numeric(_evaluate(node.operand, variables, index), index)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _numeric(_evaluate(node.left, variables, index), index)
        right = _numeric(_evaluate(node.right, variables, index), index)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right.replace(0, np.nan)
        if isinstance(node.op, ast.Pow):
            return np.power(left, right)
        if isinstance(node.op, ast.Mod):
            return left % right
    if isinstance(node, ast.Call):
        values = tuple(_evaluate(argument, variables, index) for argument in node.args)
        return _evaluate_call(node.func.id, values, index)
    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")


def evaluate_expression(expression: str, panel: pd.DataFrame) -> pd.DataFrame:
    if not {"date", "code"}.issubset(panel.columns):
        raise ExpressionError("panel must include date and code columns")
    data = panel.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["code"] = data["code"].astype(str).str.zfill(6)
    data = data.dropna(subset=["date"]).sort_values(["date", "code"])
    if data.duplicated(["date", "code"]).any():
        raise ExpressionError("panel contains duplicate date/code rows")
    indexed = data.set_index(["date", "code"])
    variables = {
        column: indexed[column].astype(float)
        for column in indexed.columns
        if column not in {"date", "code"} and pd.api.types.is_numeric_dtype(indexed[column])
    }
    source = re.sub(r"\bLog\s*\(", "log(", str(expression).strip())
    source = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r"\1", source)
    source = re.sub(r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)d(?![A-Za-z0-9_])", r"\1", source)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(str(exc)) from exc
    _validate(tree, set(variables))
    value = _evaluate(tree, variables, indexed.index)
    result = _numeric(value, indexed.index).rename("value").reset_index()
    return result[["date", "code", "value"]]
