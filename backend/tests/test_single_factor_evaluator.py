"""退化表达式必须在进入 IC 计算前被判负。"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from single_factor.data import PanelData
from single_factor.evaluator import SingleFactorEvaluator
from single_factor._vendor.alphagen.data.expression import Constant, Div


def make_evaluator() -> SingleFactorEvaluator:
    rng = np.random.default_rng(0)
    panel = PanelData(
        {"close": rng.normal(10, 1, (30, 5))},
        dates=pd.bdate_range("2024-01-01", periods=30),
        stock_ids=[f"{index:06d}" for index in range(5)],
        max_backtrack_days=0,
        max_future_days=2,
    )
    return SingleFactorEvaluator(panel, target_horizon=1)


class DegenerateExpressionTests(unittest.TestCase):
    def test_constant_factor_has_zero_score_and_is_rejected(self):
        metrics = make_evaluator().evaluate(Constant(1.0))
        self.assertEqual(metrics.score, 0.0)
        self.assertFalse(metrics.accepted)
        self.assertIn("degenerate cross-section", metrics.reason)
        self.assertTrue(np.isnan(metrics.ic))

    def test_infinite_factor_has_zero_score_and_is_rejected(self):
        metrics = make_evaluator().evaluate(Div(Constant(1.0), Constant(0.0)))
        self.assertEqual(metrics.score, 0.0)
        self.assertFalse(metrics.accepted)
        self.assertIn("inf_ratio=1.00", metrics.reason)
        self.assertTrue(np.isnan(metrics.ic))


if __name__ == "__main__":
    unittest.main()
