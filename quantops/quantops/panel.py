"""面板 <-> MultiIndex Series 互转。

量化面板约定：
- **宽表面板**：``pd.DataFrame``，至少含 ``date`` / ``code`` 两列，其余列是字段；
- **算子输入**：``pd.Series``，索引为 ``MultiIndex(date, code)``。

``evaluate_expression`` 内部也是先走这里的 ``prepare_panel`` / ``build_variables``，
保证「表达式字符串」和「直接调用算子」两条路的面板口径完全一致。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from quantops.errors import ExpressionError


def prepare_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """校验并归一化面板：date 转 datetime、code 补足 6 位、按 (date, code) 排序并设索引。"""
    required = {"date", "code"}
    if not required.issubset(panel.columns):
        raise ExpressionError("panel must include date and code columns")
    data = panel.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    data = data.sort_values(["date", "code"])
    return data.set_index(["date", "code"], drop=False)


def build_variables(panel: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """把面板拆成「索引面板 + 表达式变量表」（数值列转 float，其余原样）。"""
    indexed = prepare_panel(panel)
    variables: Dict[str, Any] = {}
    for col in indexed.columns:
        if col in {"date", "code"}:
            continue
        if pd.api.types.is_numeric_dtype(indexed[col]):
            variables[col] = indexed[col].astype(float)
        else:
            variables[col] = indexed[col]
    return indexed, variables


def to_series(panel: pd.DataFrame, field: str, name: str | None = None) -> pd.Series:
    """取面板里的一个字段，转成 MultiIndex(date, code) 的 Series。"""
    indexed = prepare_panel(panel)
    if field not in indexed.columns:
        raise ExpressionError(f"panel has no field: {field}")
    series = indexed[field]
    if pd.api.types.is_numeric_dtype(series):
        series = series.astype(float)
    series = series.copy()
    series.name = name or field
    return series


def to_frame(series: pd.Series, name: str = "alpha") -> pd.DataFrame:
    """MultiIndex(date, code) 的 Series 还原成面板 DataFrame（date, code, name 三列）。"""
    names = list(series.index.names)
    if not isinstance(series.index, pd.MultiIndex) or names[:2] != ["date", "code"]:
        raise ExpressionError("series index must be a (date, code) MultiIndex")
    frame = series.rename(name).reset_index()
    return frame[["date", "code", name]]


def align(*series: pd.Series, join: str = "outer") -> List[pd.Series]:
    """把多个 Series 对齐到同一索引：``join="outer"`` 取并集，``"inner"`` 取交集。"""
    if not series:
        raise ExpressionError("align 至少需要一个 Series")
    index = series[0].index
    for other in series[1:]:
        index = index.union(other.index) if join == "outer" else index.intersection(other.index)
    return [item.reindex(index) for item in series]


def available_fields(panel: pd.DataFrame) -> List[Dict[str, str]]:
    """面板字段清单（``[{"name": ..., "dtype": ...}]``，不含 date / code）。"""
    skip = {"date", "code"}
    fields = []
    for col in panel.columns:
        if col in skip:
            continue
        dtype = str(panel[col].dtype)
        fields.append({"name": col, "dtype": dtype})
    return fields
