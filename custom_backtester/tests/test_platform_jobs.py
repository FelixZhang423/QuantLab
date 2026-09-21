import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.jobs import update_job_status
from custom_bt.platform_jobs import create_platform_job, run_platform_job


class PlatformJobTests(unittest.TestCase):
    def test_duplicate_master_jobs_are_rejected_while_one_is_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = create_platform_job(root / "jobs", "prepare_master", {"store_dir": "one"})
            update_job_status(first, "running", "importing")

            with self.assertRaisesRegex(RuntimeError, "already running"):
                create_platform_job(root / "jobs", "prepare_master", {"store_dir": "two"})

    def test_master_job_persists_import_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "daily.csv"
            pd.DataFrame(
                {
                    "code": ["1", "2"],
                    "timestamps": ["2024-01-01", "2024-01-01"],
                    "open": [10.0, 20.0],
                    "close": [10.2, 20.2],
                    "high": [10.3, 20.3],
                    "low": [9.8, 19.8],
                    "vol": [1000.0, 2000.0],
                    "amount": [10000.0, 40000.0],
                }
            ).to_csv(source, index=False)
            job_dir = create_platform_job(
                root / "jobs",
                "prepare_master",
                {
                    "csv_path": str(source),
                    "store_dir": str(root / "master"),
                    "fields": [],
                    "chunksize": 2,
                    "overwrite": True,
                },
            )

            run_platform_job(job_dir)

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "finished")
            self.assertEqual(status["progress"]["rows_read"], 2)
            self.assertEqual(status["progress"]["stocks_touched"], 2)

    def test_generate_factor_jobs_get_unique_default_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "pool_id": "pool_a",
                "fields": ["close", "volume"],
                "splits": {
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-02-01"},
                },
                "max_backtrack_days": 1,
                "target_horizon": 1,
                "max_future_days": 1,
                "generation_config": {"target_factor_count": 5},
            }

            first = create_platform_job(root / "jobs", "generate_factors", payload)
            second = create_platform_job(root / "jobs", "generate_factors", payload)

            first_config = json.loads((first / "platform_job.json").read_text(encoding="utf-8"))
            second_config = json.loads((second / "platform_job.json").read_text(encoding="utf-8"))
            first_run_id = first_config["payload"]["generation_config"]["run_id"]
            second_run_id = second_config["payload"]["generation_config"]["run_id"]

            self.assertTrue(first_run_id.startswith("pool_a_"))
            self.assertTrue(second_run_id.startswith("pool_a_"))
            self.assertNotEqual(first_run_id, second_run_id)
            self.assertNotIn("run_id", payload["generation_config"])

    def test_create_and_run_pool_job_updates_status_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=3, freq="D"):
                for code, amount in [("000001", 1000.0), ("000002", 2000.0)]:
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
                        }
                    )
            source = root / "daily.csv"
            pd.DataFrame(rows).to_csv(source, index=False)
            build_master_store(source, root / "master", fields=[], chunksize=10, overwrite=True)

            job_dir = create_platform_job(
                root / "jobs",
                "create_pool",
                {
                    "store_dir": str(root / "master"),
                    "pools_root": str(root / "pools"),
                    "name": "liquid_2",
                    "selection_start": "2024-01-01",
                    "selection_end": "2024-01-03",
                    "top_n": 2,
                    "min_coverage": 1.0,
                    "exclude_suspended": True,
                },
            )

            result = run_platform_job(job_dir)

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "finished")
            self.assertEqual(result["n_stocks"], 2)
            self.assertTrue((root / "pools" / result["pool_id"] / "manifest.json").exists())

    def test_compose_factors_platform_job_dispatches_and_persists_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"pool_id": "pool_a", "factor_run_dirs": ["run_a"]}
            job_dir = create_platform_job(root / "jobs", "compose_factors", payload)

            def fake_compose_factors(**kwargs):
                callback = kwargs.get("progress_callback")
                if callback:
                    callback(
                        {
                            "stage": "backtesting",
                            "candidate_count": 5,
                            "accepted_count": 3,
                            "current_size": 2,
                            "completed_sizes": [2],
                        }
                    )
                return {"completed_sizes": [2], "output_dirs": ["out"]}

            with patch("custom_bt.platform_jobs.compose_factors", side_effect=fake_compose_factors) as mocked:
                result = run_platform_job(job_dir)

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "finished")
            self.assertEqual(status["progress"]["candidate_count"], 5)
            self.assertEqual(result["completed_sizes"], [2])
            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
