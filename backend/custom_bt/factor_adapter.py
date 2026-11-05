from __future__ import annotations

from typing import Dict, List

import pandas as pd

from custom_bt.expression_parser import BaseExpressionParser, ExpressionAdapterError
from adapters.expressions import evaluate_expression
from adapters.operator_registry import list_operator_definitions

_OPERATOR_MAP: Dict[str, str] = {
    definition.alphagen_name: definition.local_impl
    for definition in list_operator_definitions()
    if definition.alphagen_name is not None
}


class _Parser(BaseExpressionParser):
    def _operator(self, token: str, args: List[str]) -> str:
        if token not in _OPERATOR_MAP:
            raise ExpressionAdapterError(f"unsupported AlphaGen operator: {token}")
        return f"{_OPERATOR_MAP[token]}({','.join(args)})"


def translate_expression(expression: str) -> str:
    """Translate a serialized AlphaGen expression to custom expression syntax."""
    return _Parser(expression).parse()


def validate_backtest_expression(expression: str, panel: pd.DataFrame) -> str:
    """Translate and execute an expression once to validate fields and operators."""
    from custom_bt.canonical_expression import canonicalize_alphagen

    attempts: List[str] = []
    errors: List[str] = []
    try:
        attempts.append(canonicalize_alphagen(expression))
    except ExpressionAdapterError as exc:
        errors.append(str(exc))
    try:
        attempts.append(translate_expression(expression))
    except ExpressionAdapterError as exc:
        errors.append(str(exc))
    attempts.append(str(expression).replace("$", ""))

    seen: set[str] = set()
    for translated in attempts:
        if translated in seen:
            continue
        seen.add(translated)
        try:
            evaluate_expression(translated, panel, output_name="_validation_alpha")
            return translated
        except Exception as exc:
            errors.append(f"{translated}: {type(exc).__name__}: {exc}")

    raise ExpressionAdapterError("; ".join(errors))


__all__ = [
    "ExpressionAdapterError",
    "translate_expression",
    "validate_backtest_expression",
]
