import unittest

import pandas as pd

from custom_bt.engine import BacktestConfig, run_backtest


class EngineSmallTests(unittest.TestCase):
    def test_topk_backtest_generates_reports(self):
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-01-01",
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-02",
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-03",
                        "2024-01-03",
                    ]
                ),
                "code": ["000001", "000002", "000003"] * 3,
                "open": [10, 20, 30, 11, 19, 31, 12, 18, 32],
                "close": [10, 20, 30, 11, 19, 31, 12, 18, 32],
                "high": [10, 20, 30, 11, 19, 31, 12, 18, 32],
                "low": [10, 20, 30, 11, 19, 31, 12, 18, 32],
                "Ifsuspend": [0] * 9,
                "if_up": [0] * 9,
                "if_down": [0] * 9,
                "alpha": [3, 2, 1, 1, 3, 2, 1, 2, 3],
            }
        )
        cfg = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-03",
            top_k=2,
            initial_cash=10000.0,
            buy_cost=0.0,
            sell_cost=0.0,
            slippage=0.0,
        )

        result = run_backtest(panel, panel[["date", "code", "alpha"]], cfg)

        self.assertFalse(result.daily_report.empty)
        self.assertFalse(result.positions.empty)
        self.assertFalse(result.trades.empty)
        self.assertIn("account", result.daily_report.columns)
        self.assertIn("total_return", result.summary)


if __name__ == "__main__":
    unittest.main()
