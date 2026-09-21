from typing import Type
from .data.expression import *

from custom_bt.operator_registry import load_alphagen_operator_classes


MAX_EXPR_LENGTH = 15
MAX_EPISODE_LENGTH = 256

OPERATORS: List[Type[Operator]] = load_alphagen_operator_classes()

DELTA_TIMES = [1, 5, 10, 20, 40]

CONSTANTS = [-30., -10., -5., -2., -1., -0.5, -0.01, 0.01, 0.5, 1., 2., 5., 10., 30.]

REWARD_PER_STEP = 0.
