import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml

from repositories.job_store import load_job_status, update_job_status
from services.backtest_service import create_backtest_job, run_backtest_job
from snapshot_fixtures import write_company_fixture, fixture_pool, fake_panel_writer
from unittest.mock import patch



class JobTests(unittest.TestCase):
    def test_create_backtest_job_writes_config_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = create_backtest_job(
                jobs_root=Path(tmp),
                snapshot_id="data_cache/stock_daily",
                outputs_path="outputs",
                run_name="unit_job",
                expr="rank(close)",
                backtest={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                    "top_k": 10,
                    "initial_cash": 1000000.0,
                    "buy_cost": 0.001,
                    "sell_cost": 0.001,
                    "slippage": 0.0,
                    "min_cost": 5.0,
                    "max_weight_per_stock": 0.1,
                },
            )

            status = load_job_status(job_dir)
            config = yaml.safe_load((job_dir / "config.yaml").read_text(encoding="utf-8"))

            self.assertEqual(status["status"], "queued")
            self.assertEqual(status["run_name"], "unit_job")
            self.assertEqual(config["alphas"][0]["expr"], "rank(close)")
            self.assertEqual(config["backtest"]["top_k"], 10)

    def test_update_job_status_merges_extra_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = create_backtest_job(
                jobs_root=Path(tmp),
                snapshot_id="data",
                outputs_path="outputs",
                run_name="unit_job",
                expr="rank(close)",
                backtest={"start_date": "2024-01-01", "end_date": "2024-01-02"},
            )

            update_job_status(job_dir, "running", "正在计算 alpha", {"pid": 123})
            status = load_job_status(job_dir)

            self.assertEqual(status["status"], "running")
            self.assertEqual(status["message"], "正在计算 alpha")
            self.assertEqual(status["pid"], 123)

    def test_update_job_status_clears_stale_failure_fields_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = create_backtest_job(
                jobs_root=Path(tmp),
                snapshot_id="data",
                outputs_path="outputs",
                run_name="unit_job",
                expr="rank(close)",
                backtest={"start_date": "2024-01-01", "end_date": "2024-01-02"},
            )

            update_job_status(
                job_dir,
                "failed",
                "boom",
                {"traceback": "old-traceback", "result": {"ok": False}, "progress": {"rows_read": 10}},
            )
            update_job_status(job_dir, "running", "restarting")
            status = load_job_status(job_dir)

            self.assertEqual(status["status"], "running")
            self.assertNotIn("traceback", status)
            self.assertNotIn("result", status)
            self.assertNotIn("progress", status)

    def test_run_backtest_job_updates_status_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel_path = root / "panel.parquet"
            outputs_path = root / "outputs"
            rows = []
            for date in pd.date_range("2024-01-01", periods=4, freq="D"):
                for idx, code in enumerate(["000001", "000002", "000003"]):
                    price = 10.0 + idx + date.day * 0.1
                    rows.append(
                        {
                            "date": date,
                            "code": code,
                            "open": price,
                            "close": price + 0.2,
                            "high": price + 0.3,
                            "low": price - 0.1,
                            "volume": 1000.0,
                            "amount": price * 1000.0,
                            "Ifsuspend": 0,
                            "if_up": 0,
                            "if_down": 0,
                        }
                    )
            pd.DataFrame(rows).to_parquet(panel_path, index=False)
            write_company_fixture(panel_path, root / "snapshots")
            pool = fixture_pool(root / "snapshots", root / "pools", "all", "2024-01-01", "2024-01-04", top_n=3)
            job_dir = create_backtest_job(
                jobs_root=root / "jobs",
                snapshot_id=pool["snapshot_id"],
                snapshot_root=root / "snapshots",
                outputs_path=str(outputs_path),
                run_name="unit_e2e",
                expr="rank(close)",
                backtest={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-04",
                    "top_k": 2,
                    "initial_cash": 1000000.0,
                    "buy_cost": 0.001,
                    "sell_cost": 0.001,
                    "slippage": 0.0,
                    "min_cost": 1.0,
                    "max_weight_per_stock": 0.5,
                },
            )

            out_dir = run_backtest_job(job_dir)
            status = load_job_status(job_dir)

            self.assertEqual(status["status"], "finished")
            self.assertEqual(out_dir, outputs_path / "unit_e2e")
            self.assertTrue((out_dir / "daily_report.csv").exists())
            self.assertTrue((out_dir / "trades.csv").exists())
            self.assertTrue((out_dir / "summary.json").exists())



if __name__ == "__main__":
    unittest.main()

