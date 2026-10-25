"""因子表达式引擎（转发层）。

实现已抽到独立库 **quantops**（仓库根 ``quantops/``，可 ``pip install -e`` 复用）：
算子实现 ``quantops.operators``、底层 Series 助手 ``quantops.core``、
表达式求值 ``quantops.expression``、面板互转 ``quantops.panel``。

这里只做转发，保持 ``from custom_bt.expressions import evaluate_expression`` 等
既有 import 路径与返回值不变；本模块不再包含任何算子实现。
"""
from __future__ import annotations

from custom_bt import _quantops_boot  # noqa: F401  （未安装 quantops 时补 sys.path）
from quantops.errors import ExpressionError  # noqa: F401
from quantops.expression import (  # noqa: F401
    ALLOWED_NODES,
    RESERVED_OPERATOR_ALIASES,
    _validate_ast,
    evaluate_expression,
)
from quantops.operators import (  # noqa: F401
    OPERATORS,
    OperatorSpec,
    list_operators,
    register_operator,
)
from quantops.panel import available_fields  # noqa: F401

__all__ = [
    "ALLOWED_NODES",
    "ExpressionError",
    "OPERATORS",
    "OperatorSpec",
    "RESERVED_OPERATOR_ALIASES",
    "available_fields",
    "evaluate_expression",
    "list_operators",
    "register_operator",
]
