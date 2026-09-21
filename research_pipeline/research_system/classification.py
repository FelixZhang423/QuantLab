"""Explainable first-pass factor classification from expression structure."""

from __future__ import annotations

import re
from typing import Any


FIELD_FAMILIES = {
    "price": {"open", "close", "high", "low", "ycp", "HighestPrice", "LowestPrice", "max_high_9", "min_low_9"},
    "liquidity": {"volume", "amount", "TurnoverRate"},
    "volatility": {"RangePCT", "ts_std", "ts_var", "ts_mad", "volatility"},
    "trend": {"ema12", "ema26", "dif", "dea", "macd", "ma4", "ma5", "ma8", "ma12", "ma16", "ma20", "ma47", "RisingUpDays", "FallingDownDays"},
    "technical": {"RSV", "kdj_k", "kdj_d", "kdj_j", "if_up", "if_flat", "if_down"},
}


def infer_category(expression: str) -> dict[str, Any]:
    text = str(expression or "")
    families: list[str] = []
    for family, names in FIELD_FAMILIES.items():
        if any(re.search(rf"(?<![A-Za-z0-9_])\$?{re.escape(name)}(?![A-Za-z0-9_])", text) for name in names):
            families.append(family)
    operators = sorted(set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)))
    operator_text = {item.lower() for item in operators}
    volatility_ops = {"ts_std", "std", "ts_var", "var", "ts_mad", "mad"}
    trend_ops = {"ts_mean", "mean", "ts_ema", "ema", "ts_wma", "wma", "delta", "ts_delta", "delay", "ref"}
    if operator_text & volatility_ops:
        category = "volatility"
    elif operator_text & trend_ops and "trend" not in families:
        category = "trend"
        if "trend" not in families:
            families.append("trend")
    elif not families:
        category = "other"
    elif len(families) == 1:
        category = families[0]
    else:
        category = "mixed"
    return {
        "category": category,
        "category_source": "expression_structure",
        "families": families,
        "operators": operators,
    }
