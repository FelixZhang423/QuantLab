"""quantops —— 80 个 Alpha101 风格因子算子 + 表达式引擎。

只依赖 numpy / pandas。四种用法：

    import quantops as qo

    # 1) 函数式（输入输出都是 MultiIndex(date, code) 的 Series）
    close = qo.to_series(panel, "close")
    qo.ts_mean(close, 20); qo.rank(close)

    # 2) 方法式（pandas 访问器）
    close.qo.ts_mean(20).qo.rank()

    # 3) 表达式字符串
    qo.evaluate("rank(ts_mean(close, 20))", panel)   # -> DataFrame[date, code, alpha]

    # 4) 类式（一个类装下全部算子，可绑定面板、字段名直接当参数）
    ops = qo.OperatorSet(panel)
    ops.rank(ops.ts_mean("close", 20))
    ops.eval("rank(ts_mean(close, 20))")

注意：算子名（abs / min / max / rank / where …）会占据包的命名空间，
请用 ``qo.abs(...)`` 限定调用，避免 ``from quantops import *`` 覆盖内置函数。
"""
from __future__ import annotations

from quantops import accessor as _accessor
from quantops.errors import ExpressionError
from quantops.expression import ALLOWED_NODES, DISTRIBUTION_DRIVERS, _validate_ast, evaluate_expression
from quantops.metadata import (
    CATEGORY_CN,
    OPERATOR_CN_DESCRIPTIONS,
    OPERATOR_EXAMPLES,
    catalog,
    categories,
    describe,
)
from quantops.operators import OPERATORS, OperatorSpec, list_operators, register_operator
from quantops.opset import OperatorSet
from quantops.panel import (
    align,
    available_fields,
    build_variables,
    prepare_panel,
    to_frame,
    to_series,
)
from quantops.registry import (
    OperatorDefinition,
    canonical_name,
    generation_operator_names,
    get_operator,
    list_operator_definitions,
)

__version__ = "0.1.0"

evaluate = evaluate_expression

# 把全部算子摊平到包顶层：qo.ts_mean(close, 20)、qo.rank(close)……
for _name, _spec in OPERATORS.items():
    if _name.isidentifier() and _name not in globals():
        globals()[_name] = _spec.func
del _name, _spec

_accessor.register_accessor()

__all__ = sorted(
    set(OPERATORS)
    | {
        "ALLOWED_NODES",
        "CATEGORY_CN",
        "DISTRIBUTION_DRIVERS",
        "ExpressionError",
        "OPERATORS",
        "OPERATOR_CN_DESCRIPTIONS",
        "OPERATOR_EXAMPLES",
        "OperatorDefinition",
        "OperatorSet",
        "OperatorSpec",
        "__version__",
        "align",
        "available_fields",
        "build_variables",
        "canonical_name",
        "catalog",
        "categories",
        "describe",
        "evaluate",
        "evaluate_expression",
        "generation_operator_names",
        "get_operator",
        "list_operator_definitions",
        "list_operators",
        "prepare_panel",
        "register_operator",
        "to_frame",
        "to_series",
    }
)
