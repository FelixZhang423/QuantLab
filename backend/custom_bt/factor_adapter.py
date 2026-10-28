from __future__ import annotations

import re
from typing import Any, Dict, List

import pandas as pd

from custom_bt.expressions import evaluate_expression
from custom_bt.operator_registry import list_operator_definitions


class ExpressionAdapterError(ValueError):
    """Raised when an AlphaGen expression cannot be translated safely."""


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<ident>\$?[A-Za-z_][A-Za-z0-9_]*)|(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?)|(?P<symbol>[(),]))"
)

_OPERATOR_MAP: Dict[str, str] = {
    definition.alphagen_name: definition.local_impl
    for definition in list_operator_definitions()
    if definition.alphagen_name is not None
}


class _Parser:
    def __init__(self, expression: str) -> None:
        self.tokens = self._tokenize(expression)
        self.position = 0

    @staticmethod
    def _tokenize(expression: str) -> List[str]:
        tokens: List[str] = []
        position = 0
        while position < len(expression):
            match = _TOKEN_RE.match(expression, position)
            if match is None:
                raise ExpressionAdapterError(
                    f"invalid token at position {position}: {expression[position:position + 20]!r}"
                )
            tokens.append(match.group("ident") or match.group("number") or match.group("symbol"))
            position = match.end()
        return tokens

    def _peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None:
            raise ExpressionAdapterError("unexpected end of expression")
        if expected is not None and token != expected:
            raise ExpressionAdapterError(f"expected {expected!r}, got {token!r}")
        self.position += 1
        return token

    def parse(self) -> str:
        if not self.tokens:
            raise ExpressionAdapterError("expression must not be empty")
        result = self._value()
        if self._peek() is not None:
            raise ExpressionAdapterError(f"unexpected token: {self._peek()!r}")
        return result

    def _value(self) -> str:
        token = self._take()
        if token == "(" or token == ")" or token == ",":
            raise ExpressionAdapterError(f"unexpected token: {token!r}")
        if token.startswith("$"):
            name = token[1:]
            if not name:
                raise ExpressionAdapterError("empty field name")
            return name
        if self._is_number(token):
            return self._normalize_number(token)
        if self._peek() != "(":
            return token

        self._take("(")
        args: List[str] = []
        if self._peek() != ")":
            while True:
                args.append(self._value())
                if self._peek() != ",":
                    break
                self._take(",")
        self._take(")")
        if token not in _OPERATOR_MAP:
            raise ExpressionAdapterError(f"unsupported AlphaGen operator: {token}")
        return f"{_OPERATOR_MAP[token]}({','.join(args)})"

    @staticmethod
    def _is_number(token: str) -> bool:
        return bool(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?", token))

    @staticmethod
    def _normalize_number(token: str) -> str:
        if token.endswith("d"):
            return str(int(float(token[:-1])))
        return token


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
