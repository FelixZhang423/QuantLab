import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.pools import create_pool


class FactorBacktestTests(unittest.TestCase):
    def test_backtest_rejects_cli_pool_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "factor_run"
            run_dir.mkdir()
            (run_dir / "factor_run.json").write_text(
                json.dumps({"pool_id": "actual-pool"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "pool_id"):
                backtest_accepted_factors(
                    master_store="missing-master",
                    pools_root="missing-pools",
                    factor_run_dir=run_dir,
                    outputs_root="missing-output",
                    backtest_config={},
                    expected_pool_id="different-pool",
                )

    def test_backtest_accepted_factors_skips_rejected_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=5, freq="D"):
                for code, amount in [("000001", 1000.0), ("000002", 2000.0), ("000003", 3000.0)]:
                    price = 10.0 + int(code[-1]) + date.day * 0.1
                    rows.append(
                        {
                            "code": code,
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": price,
                            "close": price + 0.2,
                            "high": price + 0.3,
                            "low": price - 0.1,
                            "vol": 1000.0,
                            "amount": amount,
                            "Ifsuspend": 0,
                            "if_up": 0,
                            "if_down": 0,
                        }
                    )
            csv_path = root / "daily.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            master_dir = root / "master"
            build_master_store(csv_path, master_dir, fields=[])
            pool = create_pool(
                master_dir,
                root / "pools",
                "liquid_2",
                "2024-01-01",
                "2024-01-05",
                top_n=2,
                min_coverage=1.0,
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_run.json").write_text(
                json.dumps({"pool_id": pool["pool_id"], "source_signature": pool["source_signature"]}),
                encoding="utf-8",
            )
            accepted = {
                "expression": "$close",
                "accepted": True,
                "pool_id": pool["pool_id"],
                "source_signature": pool["source_signature"],
            }
            rejected = {
                "expression": "$missing",
                "accepted": False,
                "pool_id": pool["pool_id"],
                "source_signature": pool["source_signature"],
            }
            (run_dir / "accepted_factors.jsonl").write_text(json.dumps(accepted) + "\n", encoding="utf-8")
            (run_dir / "rejected_candidates.jsonl").write_text(json.dumps(rejected) + "\n", encoding="utf-8")

            result = backtest_accepted_factors(
                master_store=master_dir,
                pools_root=root / "pools",
                factor_run_dir=run_dir,
                outputs_root=root / "outputs",
                backtest_config={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-05",
                    "top_k": 1,
                    "initial_cash": 1000000.0,
                    "buy_cost": 0.001,
                    "sell_cost": 0.001,
                    "slippage": 0.0,
                    "min_cost": 1.0,
                    "max_weight_per_stock": 1.0,
                },
            )

            self.assertEqual(result["completed"], 1)
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(
                Path(result["output_dir"]),
                (root / "outputs" / "saved_backtests" / "factor" / pool["pool_id"] / "run_a").resolve(),
            )
            self.assertTrue((Path(result["output_dir"]) / "factor_backtest_summary.csv").exists())
            self.assertEqual(len(list(Path(result["output_dir"]).glob("factor_*/summary.json"))), 1)
            summary = pd.read_csv(Path(result["output_dir"]) / "factor_backtest_summary.csv")
            self.assertIn("canonical_expression", summary.columns)
            self.assertEqual(summary.iloc[0]["canonical_expression"], "close")


if __name__ == "__main__":
    unittest.main()
