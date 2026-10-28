import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.factor_generation import prepare_factor_runtime, run_factor_generation
from custom_bt.pools import create_pool


class FactorGenerationTests(unittest.TestCase):
    def test_prepare_factor_runtime_creates_pool_bound_split_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=5, freq="D"):
                for code, amount in [("000001", 1000.0), ("000002", 2000.0)]:
                    rows.append(
                        {
                            "code": code,
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 10.0,
                            "close": 10.2 + date.day,
                            "high": 10.3,
                            "low": 9.8,
                            "vol": 1000.0,
                            "amount": amount,
                            "Ifsuspend": 0,
                        }
                    )
            csv_path = root / "daily.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            master_dir = root / "master"
            build_master_store(csv_path, master_dir, fields=[])
            pool = create_pool(
                master_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-05",
                top_n=2,
                min_coverage=1.0,
            )

            result = prepare_factor_runtime(
                master_store=master_dir,
                pools_root=root / "pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "factor_runtime",
                fields=["close", "volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-04"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-05"},
                },
            )

            self.assertEqual(result["pool_id"], pool["pool_id"])
            self.assertTrue((Path(result["processed_dir"]) / "panel.parquet").exists())
            self.assertTrue((Path(result["splits"]["train"]["cache_dir"]) / "manifest.json").exists())
            self.assertTrue((Path(result["splits"]["valid"]["cache_dir"]) / "manifest.json").exists())
            self.assertTrue((Path(result["runtime_dir"]) / "runtime_manifest.json").exists())

    def test_run_factor_generation_binds_runner_to_pool_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=6, freq="D"):
                for code, amount in [("000001", 1000.0), ("000002", 2000.0)]:
                    rows.append(
                        {
                            "code": code,
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 10.0,
                            "close": 10.2 + date.day,
                            "high": 10.3,
                            "low": 9.8,
                            "vol": 1000.0,
                            "amount": amount,
                            "Ifsuspend": 0,
                        }
                    )
            csv_path = root / "daily.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            master_dir = root / "master"
            build_master_store(csv_path, master_dir, fields=[])
            pool = create_pool(
                master_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-06",
                top_n=2,
                min_coverage=1.0,
            )
            calls = []

            class FakeRunnerResult:
                accepted_count = 0
                attempts = 0
                target_reached = False
                attempts_exhausted = False

            def fake_runner(**kwargs):
                calls.append(kwargs)
                return FakeRunnerResult()

            result = run_factor_generation(
                master_store=master_dir,
                pools_root=root / "pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "factor_runtime",
                factor_runs_root=root / "factor_runs",
                fields=["close", "volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-05"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-06"},
                },
                max_backtrack_days=1,
                target_horizon=1,
                max_future_days=1,
                generation_config={"target_factor_count": 1, "max_attempts": 2},
                ppo_runner=fake_runner,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["storage_metadata"]["pool_id"], pool["pool_id"])
            self.assertEqual(result["pool_id"], pool["pool_id"])
            self.assertTrue((Path(result["factor_run_dir"]) / "factor_run.json").exists())

    def test_run_factor_generation_defaults_to_new_run_id_each_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=6, freq="D"):
                for code, amount in [("000001", 1000.0), ("000002", 2000.0)]:
                    rows.append(
                        {
                            "code": code,
                            "timestamps": date.strftime("%Y-%m-%d"),
                            "open": 10.0,
                            "close": 10.2 + date.day,
                            "high": 10.3,
                            "low": 9.8,
                            "vol": 1000.0,
                            "amount": amount,
                            "Ifsuspend": 0,
                        }
                    )
            csv_path = root / "daily.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            master_dir = root / "master"
            build_master_store(csv_path, master_dir, fields=[])
            pool = create_pool(
                master_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-06",
                top_n=2,
                min_coverage=1.0,
            )

            class FakeRunnerResult:
                accepted_count = 0
                attempts = 0
                target_reached = False
                attempts_exhausted = False

            def fake_runner(**kwargs):
                return FakeRunnerResult()

            common = {
                "master_store": master_dir,
                "pools_root": root / "pools",
                "pool_id": pool["pool_id"],
                "runtime_root": root / "factor_runtime",
                "factor_runs_root": root / "factor_runs",
                "fields": ["close", "volume", "amount"],
                "splits": {
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-05"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-06"},
                },
                "max_backtrack_days": 1,
                "target_horizon": 1,
                "max_future_days": 1,
                "generation_config": {"target_factor_count": 1, "max_attempts": 2},
                "ppo_runner": fake_runner,
            }

            first = run_factor_generation(**common)
            second = run_factor_generation(**common)

            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertNotEqual(first["factor_run_dir"], second["factor_run_dir"])
            self.assertTrue(Path(first["factor_run_dir"]).exists())
            self.assertTrue(Path(second["factor_run_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
