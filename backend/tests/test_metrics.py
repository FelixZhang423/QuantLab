import unittest

import pandas as pd

from custom_bt.metrics import annual_metrics, max_drawdown, performance_summary


class MetricsTests(unittest.TestCase):
    def test_drawdown_and_summary_metrics(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                "return": [0.10, -0.05, 0.02],
                "cost": [0.001, 0.001, 0.001],
                "turnover": [1.0, 0.5, 0.2],
                "account": [110.0, 104.5, 106.59],
            }
        )

        dd = max_drawdown(pd.Series([1.0, 1.1, 1.0, 1.2]))
        summary = performance_summary(daily, initial_cash=100.0)

        self.assertAlmostEqual(dd, -0.090909, places=5)
        self.assertIn("total_return", summary)
        self.assertIn("sharpe", summary)
        self.assertIn("max_drawdown", summary)
        self.assertGreater(summary["average_turnover"], 0)

    def test_annual_metrics_shape(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2025-01-02"]),
                "return": [0.01, 0.02, -0.01],
                "cost": [0.0, 0.0, 0.0],
                "turnover": [0.1, 0.2, 0.3],
                "account": [101.0, 103.02, 101.9898],
            }
        )

        out = annual_metrics(daily)

        self.assertEqual(set(out["year"].tolist()), {2024, 2025})
        self.assertIn("return", out.columns)
        self.assertIn("max_drawdown", out.columns)

    def test_summary_does_not_create_complex_annual_return_when_account_is_nonpositive(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
                "return": [0.0, 0.0, 0.0, 0.0, -1.2],
                "cost": [0.0, 0.0, 0.0, 0.0, 0.0],
                "turnover": [0.0, 0.0, 0.0, 0.0, 0.0],
                "account": [100.0, 100.0, 100.0, 100.0, -20.0],
            }
        )

        summary = performance_summary(daily, initial_cash=100.0)

        self.assertEqual(summary["total_return"], -1.2)
        self.assertTrue(pd.isna(summary["annual_return"]))


if __name__ == "__main__":
    unittest.main()
