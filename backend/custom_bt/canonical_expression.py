from __future__ import annotations

import re
from typing import Any, List

from custom_bt.expression_parser import BaseExpressionParser, ExpressionAdapterError
from adapters.operator_registry import get_operator, list_operator_definitions


class _CanonicalParser(BaseExpressionParser):
    def _operator(self, token: str, args: List[str]) -> str:
        try:
            definition = get_operator(token)
        except KeyError as exc:
            raise ExpressionAdapterError(f"unsupported AlphaGen operator: {token}") from exc
        if len(args) != definition.arity:
            raise ExpressionAdapterError(
                f"{token} expects {definition.arity} operand(s), got {len(args)}"
            )
        return f"{definition.canonical_name}({','.join(args)})"


def canonicalize_alphagen(expression: str) -> str:
    return _CanonicalParser(expression).parse()


def normalize_expression(expression: str) -> str:
    expression = str(expression).strip()
    if not expression:
        return expression
    try:
        return canonicalize_alphagen(expression)
    except ExpressionAdapterError:
        normalized = expression.replace("$", "")
        for definition in list_operator_definitions():
            aliases = set(definition.aliases) | {definition.local_impl}
            for alias in aliases:
                if alias == definition.canonical_name:
                    continue
                normalized = re.sub(
                    rf"\b{re.escape(alias)}\s*\(",
                    f"{definition.canonical_name}(",
                    normalized,
                )
        return normalized


def serialize_alphagen_expression(expression: Any) -> str:
    class_name = type(expression).__name__
    if class_name == "NamedFeature":
        return str(expression.name)
    if class_name == "Feature":
        feature = getattr(expression, "_feature", None)
        return str(getattr(feature, "name", feature)).lower()
    if class_name == "Constant":
        return str(expression.value)
    if class_name == "DeltaTime":
        return str(expression._delta_time)

    try:
        definition = get_operator(class_name)
    except KeyError as exc:
        raise ExpressionAdapterError(f"unsupported AlphaGen expression node: {class_name}") from exc
    operands = tuple(getattr(expression, "operands", ()))
    if len(operands) != definition.arity:
        raise ExpressionAdapterError(
            f"{class_name} expects {definition.arity} operand(s), got {len(operands)}"
        )
    return f"{definition.canonical_name}({','.join(serialize_alphagen_expression(item) for item in operands)})"
