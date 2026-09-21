import unittest

import pandas as pd

from custom_bt.expressions import ExpressionError, evaluate_expression, list_operators, register_operator


class ExpressionTests(unittest.TestCase):
    def setUp(self):
        self.panel = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]
                ),
                "code": ["000001", "000002", "000001", "000002"],
                "close": [10.0, 20.0, 11.0, 18.0],
                "TurnoverRate": [0.1, 0.2, 0.3, 0.4],
                "volume": [100.0, 200.0, 120.0, 180.0],
                "industry": [1, 1, 1, 1],
            }
        )

    def test_operator_registry_exposes_categories(self):
        operators = list_operators()
        names = {item["name"] for item in operators}
        categories = {item["category"] for item in operators}

        self.assertIn("rank", names)
        self.assertIn("delay", names)
        self.assertIn("cross_section", categories)
        self.assertIn("time_series", categories)

    def test_evaluates_rank_and_delay(self):
        out = evaluate_expression("rank(close) + delay(close, 1)", self.panel)
        values = out.sort_values(["date", "code"])["alpha"].tolist()

        self.assertTrue(pd.isna(values[0]))
        self.assertTrue(pd.isna(values[1]))
        self.assertEqual(values[2], 10.5)
        self.assertEqual(values[3], 21.0)

    def test_rejects_unsafe_expression(self):
        with self.assertRaises(ExpressionError):
            evaluate_expression("__import__('os').system('echo bad')", self.panel)

    def test_can_register_custom_operator_with_category(self):
        register_operator("double_test", "custom", "Double a numeric series.", lambda x: x * 2)

        out = evaluate_expression("double_test(close)", self.panel)
        operators = list_operators()

        self.assertEqual(out.sort_values(["date", "code"])["alpha"].tolist(), [20.0, 40.0, 22.0, 36.0])
        self.assertIn(
            {"name": "double_test", "category": "custom", "description": "Double a numeric series."},
            operators,
        )

    def test_brain_arithmetic_and_logical_operators(self):
        out = evaluate_expression("if_else(greater(close, 15), reverse(close), signed_power(close, 0.5))", self.panel)
        values = out.sort_values(["date", "code"])["alpha"].round(6).tolist()

        self.assertEqual(values, [3.162278, -20.0, 3.316625, -18.0])

    def test_brain_cross_sectional_operators(self):
        out = evaluate_expression("scale(normalize(close))", self.panel)
        values = out.sort_values(["date", "code"])["alpha"].tolist()

        self.assertEqual(values, [-0.5, 0.5, -0.5, 0.5])

    def test_brain_time_series_operators(self):
        out = evaluate_expression("ts_rank(close, 2) + ts_corr(close, volume, 2)", self.panel)
        values = out.sort_values(["date", "code"])["alpha"].round(6).tolist()

        self.assertTrue(pd.isna(values[0]))
        self.assertTrue(pd.isna(values[1]))
        self.assertEqual(values[2:], [2.0, 1.5])

    def test_alphagen_rolling_operator_aliases_are_available(self):
        out = evaluate_expression(
            "ts_var(close, 2) + ts_median(close, 2) + ts_mad(close, 2) + ts_wma(close, 2) + ts_ema(close, 2)",
            self.panel,
        )
        values = out.sort_values(["date", "code"])['alpha'].tolist()

        self.assertTrue(pd.isna(values[0]))
        self.assertTrue(pd.isna(values[1]))
        self.assertTrue(pd.notna(values[2]))
        self.assertTrue(pd.notna(values[3]))

    def test_brain_group_operators(self):
        panel = self.panel.copy()
        panel["industry"] = [1, 2, 1, 2]
        out = evaluate_expression("group_neutralize(close, industry) + group_rank(close, industry)", panel)
        values = out.sort_values(["date", "code"])["alpha"].tolist()

        self.assertEqual(values, [1.0, 1.0, 1.0, 1.0])

    def test_brain_reserved_logical_names_are_rewritten(self):
        out = evaluate_expression("if_else(and(greater(close, 10), not(is_nan(close))), 1, 0)", self.panel)
        values = out.sort_values(["date", "code"])["alpha"].tolist()

        self.assertEqual(values, [0.0, 1.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
