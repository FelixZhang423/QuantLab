import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml

from custom_bt.jobs import create_backtest_job, load_job_status, run_backtest_job, update_job_status
from custom_bt.data import build_master_store, normalize_code
from custom_bt.pools import create_pool, load_pool_codes


class JobTests(unittest.TestCase):
    def test_create_backtest_job_writes_config_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = create_backtest_job(
                jobs_root=Path(tmp),
                data_path="data_cache/stock_daily",
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
                data_path="data",
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
                data_path="data",
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
            job_dir = create_backtest_job(
                jobs_root=root / "jobs",
                data_path=str(panel_path),
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

    def test_run_backtest_job_respects_selected_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "daily.csv"
            rows = []
            for date in pd.date_range("2024-01-01", periods=4, freq="D"):
                rows.extend(
                    [
                        {
                            "code": "000001",
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 10.0,
                            "close": 10.1,
                            "high": 10.2,
                            "low": 9.9,
                            "vol": 1000.0,
                            "amount": 3000.0,
                            "Ifsuspend": 0,
                            "if_up": 0,
                            "if_down": 0,
                        },
                        {
                            "code": "000002",
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 20.0,
                            "close": 20.1,
                            "high": 20.2,
                            "low": 19.9,
                            "vol": 1000.0,
                            "amount": 2000.0,
                            "Ifsuspend": 0,
                            "if_up": 0,
                            "if_down": 0,
                        },
                        {
                            "code": "000003",
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 30.0,
                            "close": 30.1,
                            "high": 30.2,
                            "low": 29.9,
                            "vol": 1000.0,
                            "amount": 1000.0,
                            "Ifsuspend": 0,
                            "if_up": 0,
                            "if_down": 0,
                        },
                    ]
                )
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            master_dir = root / "master"
            build_master_store(csv_path, master_dir, fields=[])
            pool = create_pool(
                master_dir,
                root / "pools",
                "liquid_2",
                "2024-01-01",
                "2024-01-04",
                top_n=2,
                min_coverage=1.0,
            )
            selected_codes = load_pool_codes(root / "pools", pool["pool_id"])
            self.assertEqual(selected_codes, ["000001", "000002"])
            job_dir = create_backtest_job(
                jobs_root=root / "jobs",
                data_path=str(master_dir),
                outputs_path=str(root / "outputs"),
                run_name="pool_bound_run",
                expr="rank(close)",
                backtest={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-04",
                    "top_k": 1,
                    "initial_cash": 1000000.0,
                    "buy_cost": 0.001,
                    "sell_cost": 0.001,
                    "slippage": 0.0,
                    "min_cost": 1.0,
                    "max_weight_per_stock": 1.0,
                },
                pool_id=pool["pool_id"],
                pools_root=str(root / "pools"),
            )

            out_dir = run_backtest_job(job_dir)
            positions = pd.read_csv(out_dir / "positions.csv")
            trades = pd.read_csv(out_dir / "trades.csv")
            position_codes = {normalize_code(code) for code in positions["code"].astype(str)}
            trade_codes = {normalize_code(code) for code in trades["code"].astype(str)}

            self.assertTrue(position_codes <= set(selected_codes))
            self.assertTrue(trade_codes <= set(selected_codes))
            self.assertNotIn("000003", position_codes | trade_codes)


if __name__ == "__main__":
    unittest.main()

