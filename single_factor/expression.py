import re
from typing import List, Optional, Sequence, Type

from ._vendor.alphagen.data.expression import (
    BinaryOperator,
    Constant,
    DeltaTime,
    Expression,
    Greater,
    Less,
    Operators,
    PairRollingOperator,
    RollingOperator,
    UnaryOperator,
)
from ._vendor.alphagen.data.parser import ExpressionParser, ExpressionParsingError
from ._vendor.alphagen.data.tokens import (
    ConstantToken,
    DeltaTimeToken,
    ExpressionToken,
    OperatorToken,
    SequenceIndicatorToken,
    SequenceIndicatorType,
    Token,
)
from ._vendor.alphagen.data.tree import InvalidExpressionException


_NUMERIC = re.compile(r"[+-]?[\d.]+")


class NamedFeature(Expression):
    def __init__(self, name: str) -> None:
        self.name = name

    def evaluate(self, data, period=slice(0, 1)):
        return data.feature(self.name, period)

    @property
    def is_featured(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"${self.name}"


class NamedFeatureToken(Token):
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f"${self.name}"


class SingleFactorParser(ExpressionParser):
    """Expression parser whose feature vocabulary is supplied at runtime."""

    def __init__(
        self,
        feature_names: Sequence[str],
        operators: Optional[List[Type]] = None,
        ignore_case: bool = True,
    ) -> None:
        super().__init__(
            operators or Operators,
            ignore_case=ignore_case,
            non_positive_time_deltas_allowed=False,
            additional_operator_mapping={
                "Max": [Greater],
                "Min": [Less],
            },
        )
        self._named_features = {name.lower(): name for name in feature_names}

    def _get_next_item(self):
        top = self._pop_token()
        if top == "$":
            name = self._pop_token()
            if name not in self._named_features:
                raise ExpressionParsingError(f"Can't find the feature {name}")
            return NamedFeature(self._named_features[name])
        if self._tokens_eq(top, "Constant"):
            if self._pop_token() != "(":
                raise ExpressionParsingError("Constant should be followed by a left parenthesis")
            value = self._to_float(self._pop_token())
            if self._pop_token() != ")":
                raise ExpressionParsingError("Constant should be closed by a right parenthesis")
            return Constant(value)
        if _NUMERIC.fullmatch(top) is not None:
            value = self._to_float(top)
            if self._peek_token() == "d":
                self._pop_token()
                return self._as_delta_time(value)
            return Constant(value)
        if top in self._named_features:
            return NamedFeature(self._named_features[top])
        if (operators := self._operators.get(top)) is not None:
            return operators
        raise ExpressionParsingError(f"Cannot find the operator/feature name {top}")


class SingleFactorExpressionBuilder:
    def __init__(self) -> None:
        self.stack: List[Expression] = []

    def get_tree(self) -> Expression:
        if len(self.stack) != 1:
            raise InvalidExpressionException(
                f"Expected only one tree, got {len(self.stack)}"
            )
        return self.stack[0]

    def add_token(self, token: Token) -> None:
        if not self.validate(token):
            raise InvalidExpressionException(
                f"Token {token} not allowed here, stack: {self.stack}"
            )
        if isinstance(token, OperatorToken):
            children = [self.stack.pop() for _ in range(token.operator.n_args())]
            self.stack.append(token.operator(*reversed(children)))
        elif isinstance(token, (NamedFeatureToken,)):
            self.stack.append(NamedFeature(token.name))
        elif isinstance(token, ConstantToken):
            self.stack.append(Constant(token.constant))
        elif isinstance(token, DeltaTimeToken):
            self.stack.append(DeltaTime(token.delta_time))
        elif isinstance(token, ExpressionToken):
            self.stack.append(token.expression)
        else:
            raise TypeError(f"unsupported token: {token}")

    def is_valid(self) -> bool:
        return len(self.stack) == 1 and self.stack[0].is_featured

    def validate(self, token: Token) -> bool:
        if isinstance(token, OperatorToken):
            return self.validate_op(token.operator)
        if isinstance(token, DeltaTimeToken):
            return self.validate_dt()
        if isinstance(token, ConstantToken):
            return self.validate_const()
        if isinstance(token, (NamedFeatureToken, ExpressionToken)):
            return self.validate_featured_expr()
        return False

    def validate_op(self, op: Type) -> bool:
        if len(self.stack) < op.n_args():
            return False
        if issubclass(op, UnaryOperator):
            return self.stack[-1].is_featured
        if issubclass(op, BinaryOperator):
            return (
                self.stack[-1].is_featured or self.stack[-2].is_featured
            ) and not isinstance(self.stack[-1], DeltaTime) \
                and not isinstance(self.stack[-2], DeltaTime)
        if issubclass(op, RollingOperator):
            return (
                isinstance(self.stack[-1], DeltaTime)
                and self.stack[-2].is_featured
            )
        if issubclass(op, PairRollingOperator):
            return (
                isinstance(self.stack[-1], DeltaTime)
                and self.stack[-2].is_featured
                and self.stack[-3].is_featured
            )
        return False

    def validate_dt(self) -> bool:
        return bool(self.stack) and self.stack[-1].is_featured

    def validate_const(self) -> bool:
        return not self.stack or self.stack[-1].is_featured

    def validate_featured_expr(self) -> bool:
        return not (self.stack and isinstance(self.stack[-1], DeltaTime))
