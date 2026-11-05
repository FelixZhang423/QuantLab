"""AlphaGen 表达式词法/语法解析的公共实现。

``factor_adapter`` 与 ``canonical_expression`` 只保留各自的操作符映射差异。
"""
from __future__ import annotations

import re
from typing import List


class ExpressionAdapterError(ValueError):
    """Raised when an AlphaGen expression cannot be translated safely."""


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<ident>\$?[A-Za-z_][A-Za-z0-9_]*)|(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?)|(?P<symbol>[(),]))"
)


class BaseExpressionParser:
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
            return self._field(token)
        if self._is_number(token):
            return self._normalize_number(token)
        if self._peek() != "(":
            return token
        return self._operator(token, self._parse_args())

    def _parse_args(self) -> List[str]:
        self._take("(")
        args: List[str] = []
        if self._peek() != ")":
            while True:
                args.append(self._value())
                if self._peek() != ",":
                    break
                self._take(",")
        self._take(")")
        return args

    @staticmethod
    def _field(token: str) -> str:
        name = token[1:]
        if not name:
            raise ExpressionAdapterError("empty field name")
        return name

    def _operator(self, token: str, args: List[str]) -> str:
        raise NotImplementedError

    @staticmethod
    def _is_number(token: str) -> bool:
        return bool(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:d)?", token))

    @staticmethod
    def _normalize_number(token: str) -> str:
        if token.endswith("d"):
            return str(int(float(token[:-1])))
        return token
