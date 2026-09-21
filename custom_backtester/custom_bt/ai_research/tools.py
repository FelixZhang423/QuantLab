from __future__ import annotations

import ast
from typing import Any, Mapping, Sequence

import pandas as pd

from custom_bt.expressions import ExpressionError, evaluate_expression


_STRING_CONSTANTS = {"gaussian", "uniform", "cauchy"}


def validate_candidate_expression(
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    expression = str(candidate.get("expression", "")).strip()
    candidate_id = str(candidate.get("candidate_id", "")).strip()
    allowed_fields = set(str(item) for item in context.get("master_store", {}).get("fields", []))
    allowed_operators = _operator_set(context.get("operators", []))

    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "expression": expression,
        "status": "invalid",
        "used_fields": [],
        "used_operators": [],
        "unknown_fields": [],
        "unknown_operators": [],
        "errors": [],
    }
    if not expression:
        result["errors"].append("expression is required")
        return result

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        result["errors"].append(str(exc))
        return result

    used_fields, used_operators = _collect_names(tree, allowed_operators)
    unknown_fields = sorted(used_fields - allowed_fields)
    unknown_operators = sorted(used_operators - allowed_operators)
    result["used_fields"] = sorted(used_fields)
    result["used_operators"] = sorted(used_operators)
    result["unknown_fields"] = unknown_fields
    result["unknown_operators"] = unknown_operators
    if unknown_fields:
        result["errors"].append("unknown fields: " + ", ".join(unknown_fields))
    if unknown_operators:
        result["errors"].append("unknown operators: " + ", ".join(unknown_operators))

    if not result["errors"]:
        try:
            evaluate_expression(expression, _synthetic_panel(sorted(allowed_fields)))
        except ExpressionError as exc:
            result["errors"].append(str(exc))

    if not result["errors"]:
        result["status"] = "valid"
    return result


def validate_candidate_expressions(
    candidates: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [validate_candidate_expression(candidate, context) for candidate in candidates]


def _operator_set(operators: Any) -> set[str]:
    names: set[str] = set()
    for item in operators or []:
        if isinstance(item, Mapping):
            name = item.get("name")
        else:
            name = item
        if name:
            names.add(str(name))
    return names


def _collect_names(tree: ast.AST, allowed_operators: set[str]) -> tuple[set[str], set[str]]:
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_names.add(node.func.id)

    field_names: set[str] = set()
    operator_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        if node.id in _STRING_CONSTANTS:
            continue
        if node.id in call_names or node.id in allowed_operators:
            operator_names.add(node.id)
        else:
            field_names.add(node.id)
    return field_names, operator_names


def _synthetic_panel(fields: Sequence[str]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    rows = []
    for day_index, date in enumerate(dates):
        for code_index, code in enumerate(["000001", "000002", "000003"]):
            row: dict[str, Any] = {"date": date, "code": code}
            for field_index, field in enumerate(fields):
                row[field] = float(day_index + code_index + field_index + 1)
            rows.append(row)
    return pd.DataFrame(rows)
