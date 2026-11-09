"""Freeze long-only orientation using training IC alone, never validation or test."""
from __future__ import annotations

import math
from typing import Any, Mapping


def direction_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    train = (record.get("segments") or {}).get("train") or {}
    value = train.get("ic")
    source = "segments.train.ic"
    try:
        ic = float(value)
    except (TypeError, ValueError):
        ic = float("nan")
    if not math.isfinite(ic):
        value = record.get("ic", record.get("generation_ic"))
        source = "ic"
        try:
            ic = float(value)
        except (TypeError, ValueError):
            ic = float("nan")
    if not math.isfinite(ic):
        return {"direction": 1, "training_ic": None, "direction_source": "missing_train_ic_preserve_expression"}
    return {"direction": -1 if ic < 0 else 1, "training_ic": ic,
            "direction_source": source if ic else "zero_train_ic_preserve_expression"}


def orient_expression(expression: str, record: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = direction_metadata(record)
    original = str(record.get("original_backtest_expression") or expression)
    effective = f"-({original})" if metadata["direction"] < 0 else original
    return effective, {**metadata, "original_backtest_expression": original,
                       "effective_expression": effective, "direction_applied": True}
