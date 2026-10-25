"""表达式引擎：把 ``rank(ts_mean(close, 20))`` 这类字符串安全地求值成因子序列。

安全模型（从 custom_bt/expressions.py 原样保留）：
- 只允许白名单 AST 节点：算术 / 比较 / 逻辑 / 常量 / 已注册算子调用；
- 求值时 ``__builtins__`` 为空字典，变量表里只有面板字段和算子函数；
- 任何未注册的名字、属性访问、下标、lambda、import 都会抛 ``ExpressionError``。
"""
from __future__ import annotations

import ast
import re
from typing import Any, Dict

from quantops.core import _as_series
from quantops.errors import ExpressionError
from quantops.operators import OPERATORS
from quantops.panel import build_variables

RESERVED_OPERATOR_ALIASES = {
    "and": "and_",
    "or": "or_",
    "not": "not_",
}

# 表达式里可直接写这些名字当作分布参数（quantile / ts_quantile 的 driver=…）
DISTRIBUTION_DRIVERS = ("gaussian", "uniform", "cauchy")


def _preprocess_expression(expr: str) -> str:
    for source, target in RESERVED_OPERATOR_ALIASES.items():
        expr = re.sub(rf"\b{source}\s*\(", f"{target}(", expr)
    return expr


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


def evaluate_expression(expr: str, panel, output_name: str = "alpha"):
    """求值表达式并返回面板 DataFrame（date / code / ``output_name`` 三列）。

    例：``evaluate("rank(ts_mean(close, 20))", panel)``。
    """
    indexed, variables = build_variables(panel)
    variables.update({name: name for name in DISTRIBUTION_DRIVERS})
    variables.update({name: spec.func for name, spec in OPERATORS.items()})
    tree = _validate_ast(expr, variables)
    try:
        value = eval(compile(tree, "<alpha-expression>", "eval"), {"__builtins__": {}}, variables)
    except Exception as exc:
        raise ExpressionError(str(exc)) from exc
    alpha = _as_series(value, indexed.index).rename(output_name)
    return alpha.reset_index()[["date", "code", output_name]]
