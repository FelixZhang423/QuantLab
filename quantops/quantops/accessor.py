"""pandas 访问器：把算子挂成 Series 的方法，写链式调用。

    close.qo.ts_mean(20).qo.rank()

等价于 ``rank(ts_mean(close, 20))``。方法在 import 时按 ``OPERATORS`` 动态生成；
之后用 ``register_operator`` 新注册的算子请走 ``series.qo.apply("名字", ...)``。
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quantops.errors import ExpressionError
from quantops.operators import OPERATORS, OperatorSpec


class QuantOpsAccessor:
    """``series.qo`` 的名字空间；方法由 ``OPERATORS`` 动态挂载。

    算子按约定要求 MultiIndex(date, code)，这里先校验一次：给普通 Series 调用时
    抛出明确的 ExpressionError，而不是在后面 groupby(level="date") 处报 KeyError。
    """

    def __init__(self, pandas_obj: pd.Series) -> None:
        names = list(pandas_obj.index.names)
        if not isinstance(pandas_obj.index, pd.MultiIndex) or names[:2] != ["date", "code"]:
            raise ExpressionError(
                "quantops 算子要求索引为 MultiIndex(date, code)："
                "请先用 qo.to_series(panel, 字段名) 或 qo.prepare_panel(panel) 准备数据"
            )
        self._obj = pandas_obj

    def apply(self, name: str, *args: Any, **kwargs: Any) -> pd.Series:
        """按名字调用算子（包含导入之后才注册的自定义算子）。"""
        try:
            spec = OPERATORS[name]
        except KeyError as exc:
            raise KeyError(f"unknown operator: {name}") from exc
        return spec.func(self._obj, *args, **kwargs)


def _make_method(name: str, spec: OperatorSpec) -> Callable[..., pd.Series]:
    def method(self: "QuantOpsAccessor", *args: Any, **kwargs: Any) -> pd.Series:
        return spec.func(self._obj, *args, **kwargs)

    method.__name__ = name
    method.__qualname__ = f"QuantOpsAccessor.{name}"
    method.__doc__ = f"等价于 quantops.{name}(series, ...)。{spec.description}"
    return method


def register_accessor() -> bool:
    """注册 ``Series.qo`` 访问器；已被占用则返回 False（不会抛错）。"""
    if hasattr(pd.Series, "qo"):
        return False
    for name, spec in OPERATORS.items():
        if name.isidentifier() and name not in vars(QuantOpsAccessor):
            setattr(QuantOpsAccessor, name, _make_method(name, spec))
    pd.api.extensions.register_series_accessor("qo")(QuantOpsAccessor)
    return True
