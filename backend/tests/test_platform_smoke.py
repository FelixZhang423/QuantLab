import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from snapshot_fixtures import write_company_fixture, fixture_pool, fake_panel_writer
from unittest.mock import patch
from custom_bt.factor_backtest import backtest_accepted_factors
from custom_bt.factor_generation import prepare_factor_runtime


class PlatformSmokeTests(unittest.TestCase):
    def setUp(self):
        writer = patch("repositories.company_source.write_pool_panel", side_effect=fake_panel_writer)
        writer.start()
        self.addCleanup(writer.stop)

    def test_source_to_pool_runtime_and_accepted_backtest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=8, freq="D"):
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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots = root / "snapshots"
            write_company_fixture(fixture_path, snapshots, fields=[])
            pool = fixture_pool(snapshots, root / "pools", "liquid_2", "2024-01-01", "2024-01-08", top_n=2, min_coverage=1.0)
            runtime = prepare_factor_runtime(
                pools_root=root / "pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "runtime",
                fields=["close", "volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-06"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-08"},
                },
                snapshot_root=snapshots,
                max_backtrack_days=1,
                target_horizon=1,
                max_future_days=1,
            )
            self.assertEqual(runtime["pool_id"], pool["pool_id"])

            factor_run = root / "factor_runs" / "run_smoke"
            factor_run.mkdir(parents=True)
            run_manifest = {"pool_id": pool["pool_id"], "data_source": "clickhouse", "snapshot_id": pool["snapshot_id"], "source_signature": pool["source_signature"]}
            (factor_run / "factor_run.json").write_text(json.dumps(run_manifest), encoding="utf-8")
            factor = {
                "expression": "$close",
                "accepted": True,
                "pool_id": pool["pool_id"],
                "data_source": "clickhouse", "snapshot_id": pool["snapshot_id"], "source_signature": pool["source_signature"],
            }
            (factor_run / "accepted_factors.jsonl").write_text(json.dumps(factor) + "\n", encoding="utf-8")

            result = backtest_accepted_factors(
                root / "pools",
                factor_run,
                root / "outputs",
                {
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-08",
                    "top_k": 1,
                    "initial_cash": 1000000.0,
                    "buy_cost": 0.001,
                    "sell_cost": 0.001,
                    "slippage": 0.0,
                    "min_cost": 1.0,
                    "max_weight_per_stock": 1.0,
                },
                snapshot_root=snapshots,
            )

            self.assertEqual(result["pool_id"], pool["pool_id"])
            self.assertEqual(result["completed"], 1)
            self.assertTrue((Path(result["output_dir"]) / "factor_backtest_summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
