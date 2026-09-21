from __future__ import annotations

import re
from typing import Any, List

from custom_bt.factor_adapter import ExpressionAdapterError
from custom_bt.operator_registry import get_operator, list_operator_definitions


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<ident>\$?[A-Za-z_][A-Za-z0-9_]*)|(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?)|(?P<symbol>[(),]))"
)


class _CanonicalParser:
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
        if token in {"(", ")", ","}:
            raise ExpressionAdapterError(f"unexpected token: {token!r}")
        if token.startswith("$"):
            return token[1:]
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
        try:
            definition = get_operator(token)
        except KeyError as exc:
            raise ExpressionAdapterError(f"unsupported AlphaGen operator: {token}") from exc
        if len(args) != definition.arity:
            raise ExpressionAdapterError(
                f"{token} expects {definition.arity} operand(s), got {len(args)}"
            )
        return f"{definition.canonical_name}({','.join(args)})"

    @staticmethod
    def _is_number(token: str) -> bool:
        return bool(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?", token))

    @staticmethod
    def _normalize_number(token: str) -> str:
        if token.endswith("d"):
            return str(int(float(token[:-1])))
        return token


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
