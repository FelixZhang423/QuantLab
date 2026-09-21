import unittest

import pandas as pd

from custom_bt.factor_adapter import (
    ExpressionAdapterError,
    translate_expression,
    validate_backtest_expression,
)


class FactorAdapterTests(unittest.TestCase):
    def test_translates_nested_alphagen_expression(self):
        self.assertEqual(
            translate_expression("Add(Ref($close,20d),$volume)"),
            "add(delay(close,20),volume)",
        )

    def test_translates_rolling_expression(self):
        self.assertEqual(translate_expression("Mean($close,5d)"), "ts_mean(close,5)")

    def test_preserves_case_sensitive_feature_names(self):
        self.assertEqual(translate_expression("Ref($TurnoverRate,5d)"), "delay(TurnoverRate,5)")

    def test_rejects_unknown_operator(self):
        with self.assertRaises(ExpressionAdapterError):
            translate_expression("Unknown($close)")

    def test_rejects_unclosed_expression(self):
        with self.assertRaises(ExpressionAdapterError):
            translate_expression("Add($close,$volume")

    def test_validation_rejects_missing_field(self):
        panel = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=2).repeat(2),
                "code": ["000001", "000002"] * 2,
                "close": [10.0, 11.0, 10.5, 11.5],
            }
        )
        with self.assertRaises(ValueError):
            validate_backtest_expression("Add($missing,1)", panel)


if __name__ == "__main__":
    unittest.main()
