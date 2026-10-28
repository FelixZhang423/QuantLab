from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from custom_bt.canonical_expression import normalize_expression
from custom_bt.expressions import evaluate_expression


def combine_alphas(panel: pd.DataFrame, alpha_defs: List[Dict[str, Any]]) -> pd.DataFrame:
    frames = []
    for item in alpha_defs:
        name = item.get("name", "alpha")
        expr = normalize_expression(item["expr"])
        weight = float(item.get("weight", 1.0))
        cur = evaluate_expression(expr, panel, output_name=name)
        cur[name] = cur[name] * weight
        frames.append(cur)
    if not frames:
        raise ValueError("alpha config must contain at least one alpha expression")
    merged = frames[0]
    value_cols = [frames[0].columns[-1]]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=["date", "code"], how="outer")
        value_cols.append(frame.columns[-1])
    merged["alpha"] = merged[value_cols].sum(axis=1, min_count=1)
    return merged[["date", "code", "alpha"]]


def normalize_alpha_defs(alpha_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in alpha_defs:
        current = dict(item)
        current["expr"] = normalize_expression(item.get("expr", ""))
        current["weight"] = float(item.get("weight", 1.0))
        normalized.append(current)
    return normalized


def canonical_alpha_expression(alpha_defs: List[Dict[str, Any]]) -> str:
    normalized = normalize_alpha_defs(alpha_defs)
    if len(normalized) == 1 and normalized[0]["weight"] == 1.0:
        return str(normalized[0]["expr"])
    return " + ".join(f"({item['weight']:.12g})*({item['expr']})" for item in normalized)


def alpha_components(alpha_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = normalize_alpha_defs(alpha_defs)
    return [
        {
            "factor_id": item.get("factor_id") or item.get("id") or item.get("name"),
            "expression": item["expr"],
            "weight": item["weight"],
        }
        for item in normalized
    ]
