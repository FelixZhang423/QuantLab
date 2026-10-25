"""类式入口：`OperatorSet` 把 80 个算子包成一个类，可选绑定一张面板。

与函数式（``quantops.ts_mean``）、访问器式（``series.qo.ts_mean``）完全等价 ——
底层是同一份实现，这里只是把它们挂成实例方法，并支持字段名直接当参数：

    import quantops as qo

    ops = qo.OperatorSet(panel)                  # 绑定面板（date/code + 字段列）

    ops.rank(ops.ts_mean("close", 20))           # 字段名直接当参数
    ops.eval("rank(ts_mean(close, 20))")         # 表达式字符串 -> DataFrame[date, code, alpha]
    ops.to_frame(ops.rank("close"))              # MultiIndex Series -> 面板 DataFrame

    ops = qo.OperatorSet()                       # 不绑面板：方法直接吃 Series
    ops.ts_mean(close, 20)

设计说明：

- 方法按 ``OPERATORS`` 注册表**动态生成**，不复制实现。``register_operator`` 注册的
  新算子也能立刻用 ``ops.<name>(...)`` 或 ``ops.apply("<name>", ...)`` 调（走 ``__getattr__``）。
- 参数里的字符串只有**恰好是面板字段名**时才转成 Series；其它字符串
  （``bucket(x, "0,1,0.1")`` 的区间、``ts_quantile(x, 20, "gaussian")`` 的 driver）
  原样传给算子，不会被误当成字段。
- 字段名与算子名撞车时算子优先（``ops.rank`` 是方法），取字段请用 ``ops.field("rank")``。
- 每个方法的 ``__doc__`` 是中文说明 + 示例，``__signature__`` 与底层函数一致，
  所以 ``help(ops.ts_mean)`` 和 IDE 补全都能用。
"""
from __future__ import annotations

import difflib
import inspect
from functools import partial
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from quantops.errors import ExpressionError
from quantops.expression import evaluate_expression
from quantops.metadata import (
    CATEGORY_CN,
    OPERATOR_CN_DESCRIPTIONS,
    OPERATOR_EXAMPLES,
    catalog as operator_catalog,
    categories as list_categories,
    describe as describe_operator,
)
from quantops.operators import OPERATORS, OperatorSpec
from quantops.panel import available_fields, prepare_panel, to_frame as series_to_frame


class OperatorSet:
    """80 个算子的类式入口；可选绑定一张面板，让字段名可以直接当参数用。"""

    def __init__(self, panel: Optional[pd.DataFrame] = None) -> None:
        self._panel = panel
        if panel is None:
            self._indexed: Optional[pd.DataFrame] = None
            self._field_names: List[str] = []
        else:
            self._indexed = prepare_panel(panel)
            self._field_names = [item["name"] for item in available_fields(self._indexed)]
        self._field_set = set(self._field_names)

    # ---------- 面板与字段 ----------

    @property
    def panel(self) -> Optional[pd.DataFrame]:
        """绑定的原始面板（没绑则为 None）。"""
        return self._panel

    @property
    def fields(self) -> List[str]:
        """面板字段名（不含 date / code），顺序同面板列顺序。"""
        return list(self._field_names)

    @property
    def names(self) -> List[str]:
        """全部算子名（80 个，按字母序）。"""
        return sorted(OPERATORS)

    def field(self, name: str) -> pd.Series:
        """按字段名取 MultiIndex(date, code) 的 Series（数值列转 float）。"""
        if self._indexed is None:
            raise ExpressionError(
                "OperatorSet 还没绑定面板：先用 OperatorSet(panel) 构造，或直接传 Series"
            )
        if name not in self._field_set:
            raise ExpressionError(
                f"panel has no field: {name!r}；可用字段：{_preview(self._field_names)}"
            )
        series = self._indexed[name]
        if pd.api.types.is_numeric_dtype(series):
            series = series.astype(float)
        series = series.copy()
        series.name = name
        return series

    # ---------- 调用算子 ----------

    def apply(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """按名字调用算子，例如 ``ops.apply("ts_mean", "close", 20)``。"""
        spec = OPERATORS.get(name)
        if spec is None:
            matches = difflib.get_close_matches(name, OPERATORS, n=3)
            hint = f"；相近的算子：{', '.join(matches)}" if matches else ""
            raise ExpressionError(f"未知算子 {name!r}{hint}")
        resolved = tuple(self._resolve(arg) for arg in args)
        resolved_kwargs = {key: self._resolve(value) for key, value in kwargs.items()}
        return spec.func(*resolved, **resolved_kwargs)

    def __getitem__(self, name: str) -> Callable[..., Any]:
        """``ops["ts_mean"]("close", 20)``：按名字取一个已绑定字段解析的调用器。"""
        if name not in OPERATORS:
            raise KeyError(f"unknown operator: {name}")
        return partial(self.apply, name)

    def __getattr__(self, name: str) -> Any:
        # 只有正常属性查找失败才会走到这里
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.__dict__.get("_field_set", ()):
            return self.field(name)
        spec = OPERATORS.get(name)
        if spec is not None:  # register_operator 之后注册的算子：现生成一个方法
            return _make_method(spec).__get__(self, type(self))
        matches = difflib.get_close_matches(name, OPERATORS, n=3)
        hint = f"；相近的算子：{', '.join(matches)}" if matches else ""
        raise AttributeError(
            f"{type(self).__name__} 没有属性 {name!r}：不是算子名，也不是面板字段名{hint}"
        )

    # ---------- 表达式与结果 ----------

    def eval(self, expression: str) -> pd.DataFrame:
        """执行表达式字符串（需要绑定面板），返回 ``DataFrame[date, code, alpha]``。"""
        if self._panel is None:
            raise ExpressionError("eval() 需要面板：用 OperatorSet(panel) 构造")
        return evaluate_expression(expression, self._panel)

    evaluate = eval

    def to_frame(self, series: pd.Series, name: str = "alpha") -> pd.DataFrame:
        """算子输出（MultiIndex Series）转成 ``date / code / name`` 三列的面板。"""
        return series_to_frame(series, name)

    # ---------- 元数据 ----------

    def list_operators(self) -> List[Dict[str, object]]:
        """完整算子目录（与 ``quantops.list_operators()`` 相同，中文优先）。"""
        return operator_catalog()

    def describe(self, name: str) -> Dict[str, object]:
        """单个算子的分类 / 中文说明 / 示例。"""
        return describe_operator(name)

    def categories(self) -> List[Dict[str, object]]:
        """分类清单：``[{"key": ..., "label": ..., "count": ...}, ...]``。"""
        return list_categories()

    # ---------- 杂项 ----------

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, str) and value in self._field_set:
            return self.field(value)
        return value

    def __repr__(self) -> str:
        if self._indexed is None:
            return f"<OperatorSet: {len(OPERATORS)} operators, no panel>"
        return f"<OperatorSet: {len(OPERATORS)} operators, {len(self._field_names)} fields>"

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | self._field_set)


def _preview(names: List[str], limit: int = 12) -> str:
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" …（共 {len(names)} 个）"


def _operator_doc(spec: OperatorSpec) -> str:
    description = OPERATOR_CN_DESCRIPTIONS.get(spec.name, spec.description)
    category = CATEGORY_CN.get(spec.category, spec.category)
    lines = [description, "", f"分类：{category}"]
    example = OPERATOR_EXAMPLES.get(spec.name)
    if example:
        lines.append(f"示例：{example}")
    lines.append(f"等价的函数式写法：quantops.{spec.name}(...)")
    return "\n".join(lines)


def _make_method(spec: OperatorSpec) -> Callable[..., Any]:
    """按算子名生成一个实例方法：参数先按字段名解析，再转给底层函数。"""

    def method(self: "OperatorSet", *args: Any, **kwargs: Any) -> Any:
        return self.apply(spec.name, *args, **kwargs)

    method.__name__ = spec.name
    method.__qualname__ = f"OperatorSet.{spec.name}"
    method.__module__ = __name__
    method.__doc__ = _operator_doc(spec)
    try:
        signature = inspect.signature(spec.func)
    except (TypeError, ValueError):  # pragma: no cover - 纯 Python 函数不会触发
        pass
    else:
        parameters = [inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        parameters.extend(signature.parameters.values())
        method.__signature__ = signature.replace(parameters=parameters)
    return method


for _name, _spec in OPERATORS.items():
    if _name.isidentifier() and not hasattr(OperatorSet, _name):
        setattr(OperatorSet, _name, _make_method(_spec))
del _name, _spec
