"""库内异常类型（放在最底层模块，避免 core / operators / expression 循环依赖）。"""
from __future__ import annotations


class ExpressionError(ValueError):
    """表达式非法、算子参数错误或求值失败时抛出。"""
