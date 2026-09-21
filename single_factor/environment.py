from typing import Optional, Sequence

try:
    import gymnasium as gym
except ImportError:  # pragma: no cover - used only in minimal local environments
    import gym
import numpy as np

from ._vendor.alphagen.config import CONSTANTS, DELTA_TIMES, MAX_EXPR_LENGTH, OPERATORS
from ._vendor.alphagen.data.expression import (
    BinaryOperator,
    PairRollingOperator,
    RollingOperator,
    UnaryOperator,
)
from ._vendor.alphagen.data.tokens import (
    BEG_TOKEN,
    SEP_TOKEN,
    ConstantToken,
    DeltaTimeToken,
    OperatorToken,
    SequenceIndicatorToken,
    SequenceIndicatorType,
    Token,
)

from .evaluator import SingleFactorEvaluator, SingleFactorMetrics
from .expression import NamedFeatureToken, SingleFactorExpressionBuilder


class SingleFactorEnvCore(gym.Env):
    def __init__(
        self,
        feature_names: Sequence[str],
        evaluator: SingleFactorEvaluator,
        print_expr: bool = False,
    ) -> None:
        super().__init__()
        self.feature_names = tuple(feature_names)
        self.evaluator = evaluator
        self.print_expr = print_expr
        self.last_metrics: Optional[SingleFactorMetrics] = None
        self.last_expression: Optional[str] = None
        self._completed_metrics: list[SingleFactorMetrics] = []
        self.reset()

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self._tokens = [BEG_TOKEN]
        self._builder = SingleFactorExpressionBuilder()
        self.last_metrics = None
        self.last_expression = None
        return self._tokens, self._valid_action_types()

    def step(self, action: Token):
        if isinstance(action, SequenceIndicatorToken) and action.indicator == SequenceIndicatorType.SEP:
            if not self._builder.is_valid():
                return self._tokens, -1.0, True, False, {"reason": "invalid expression"}
            expression = self._builder.get_tree()
            if self.print_expr:
                print(expression)
            metrics = self.evaluator.evaluate(expression)
            self.last_metrics = metrics
            self.last_expression = metrics.expression
            self._completed_metrics.append(metrics)
            return self._tokens, metrics.score, True, False, {"metrics": metrics}

        if len(self._tokens) >= MAX_EXPR_LENGTH:
            if not self._builder.is_valid():
                return self._tokens, -1.0, True, False, {"reason": "expression too long"}
            expression = self._builder.get_tree()
            metrics = self.evaluator.evaluate(expression)
            self.last_metrics = metrics
            self.last_expression = metrics.expression
            self._completed_metrics.append(metrics)
            return self._tokens, metrics.score, True, False, {"metrics": metrics}

        self._tokens.append(action)
        self._builder.add_token(action)
        return self._tokens, 0.0, False, False, self._valid_action_types()

    def _valid_action_types(self) -> dict:
        valid_op_unary = self._builder.validate_op(UnaryOperator)
        valid_op_binary = self._builder.validate_op(BinaryOperator)
        valid_op_rolling = self._builder.validate_op(RollingOperator)
        valid_op_pair_rolling = self._builder.validate_op(PairRollingOperator)
        valid_op = (
            valid_op_unary
            or valid_op_binary
            or valid_op_rolling
            or valid_op_pair_rolling
        )
        return {
            "select": [
                valid_op,
                self._builder.validate_featured_expr(),
                self._builder.validate_const(),
                self._builder.validate_dt(),
                self._builder.is_valid(),
            ],
            "op": {
                UnaryOperator: valid_op_unary,
                BinaryOperator: valid_op_binary,
                RollingOperator: valid_op_rolling,
                PairRollingOperator: valid_op_pair_rolling,
            },
        }

    def valid_action_types(self) -> dict:
        return self._valid_action_types()

    def drain_completed_metrics(self) -> list[SingleFactorMetrics]:
        completed = list(self._completed_metrics)
        self._completed_metrics.clear()
        return completed


class SingleFactorEnvWrapper(gym.Wrapper):
    def __init__(self, env: SingleFactorEnvCore) -> None:
        super().__init__(env)
        self.env: SingleFactorEnvCore
        self.size_op = len(OPERATORS)
        self.size_feature = len(env.feature_names)
        self.size_constant = len(CONSTANTS)
        self.size_delta_time = len(DELTA_TIMES)
        self.size_action = (
            self.size_op
            + self.size_feature
            + self.size_constant
            + self.size_delta_time
            + 1
        )
        self.action_space = gym.spaces.Discrete(self.size_action)
        self.observation_space = gym.spaces.Box(
            low=0,
            high=self.size_action,
            shape=(MAX_EXPR_LENGTH,),
            dtype=np.int32,
        )
        self.state = np.zeros(MAX_EXPR_LENGTH, dtype=np.int32)
        self.counter = 0

    def reset(self, **kwargs):
        self.counter = 0
        self.state.fill(0)
        self.env.reset(**kwargs)
        return self.state.copy(), {}

    def step(self, action: int):
        if not self.action_space.contains(action):
            raise ValueError(f"invalid action: {action}")
        _, reward, done, truncated, info = self.env.step(self.action_to_token(action))
        if not done:
            self.state[self.counter] = action + 1
            self.counter += 1
        return self.state.copy(), reward, done, truncated, info

    def action_masks(self) -> np.ndarray:
        valid = self.env.valid_action_types()
        result = np.zeros(self.size_action, dtype=bool)
        offset = 0
        for operator_index, operator in enumerate(OPERATORS):
            result[offset + operator_index] = valid["op"].get(
                operator.category_type(), False
            )
        offset += self.size_op
        if valid["select"][1]:
            result[offset : offset + self.size_feature] = True
        offset += self.size_feature
        if valid["select"][2]:
            result[offset : offset + self.size_constant] = True
        offset += self.size_constant
        if valid["select"][3]:
            result[offset : offset + self.size_delta_time] = True
        offset += self.size_delta_time
        if valid["select"][4]:
            result[offset] = True
        return result

    def action_to_token(self, action: int) -> Token:
        if action < self.size_op:
            return OperatorToken(OPERATORS[action])
        action -= self.size_op
        if action < self.size_feature:
            return NamedFeatureToken(self.env.feature_names[action])
        action -= self.size_feature
        if action < self.size_constant:
            return ConstantToken(CONSTANTS[action])
        action -= self.size_constant
        if action < self.size_delta_time:
            return DeltaTimeToken(DELTA_TIMES[action])
        action -= self.size_delta_time
        if action == 0:
            return SEP_TOKEN
        raise ValueError(f"invalid action: {action}")


def SingleFactorEnv(
    feature_names: Sequence[str],
    evaluator: SingleFactorEvaluator,
    **kwargs,
) -> SingleFactorEnvWrapper:
    return SingleFactorEnvWrapper(
        SingleFactorEnvCore(feature_names=feature_names, evaluator=evaluator, **kwargs)
    )
