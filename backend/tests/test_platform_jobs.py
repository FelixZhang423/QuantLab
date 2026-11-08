import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from repositories.job_store import update_job_status
from workers.job_dispatcher import create_platform_job, run_platform_job


class PlatformJobTests(unittest.TestCase):


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

    def test_generate_factor_job_uses_run_name_as_run_id_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = create_platform_job(
                root / "jobs",
                "generate_factors",
                {
                    "pool_id": "pool_a",
                    "fields": ["close"],
                    "splits": {
                        "train": {"cache_start": "2024-01-01", "cache_end": "2024-02-01"},
                    },
                    "max_backtrack_days": 1,
                    "target_horizon": 1,
                    "max_future_days": 1,
                    "generation_config": {
                        "target_factor_count": 1,
                        "run_name": "daily_alpha",
                    },
                },
            )

            config = json.loads((job_dir / "platform_job.json").read_text(encoding="utf-8"))
            run_id = config["payload"]["generation_config"]["run_id"]
            self.assertTrue(run_id.startswith("daily_alpha_"))
            self.assertNotEqual(run_id, "daily_alpha")

    def test_generate_factor_job_persists_training_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = create_platform_job(
                root / "jobs",
                "generate_factors",
                {
                    "pool_id": "pool_a",
                    "fields": ["close"],
                    "splits": {
                        "train": {"cache_start": "2024-01-01", "cache_end": "2024-02-01"},
                    },
                    "max_backtrack_days": 1,
                    "target_horizon": 1,
                    "max_future_days": 1,
                    "generation_config": {"target_factor_count": 5, "max_attempts": 20},
                },
            )
            snapshots = []

            def read_status():
                return json.loads((job_dir / "status.json").read_text(encoding="utf-8"))

            def fake_generate(**kwargs):
                callback = kwargs["progress_callback"]
                callback({"stage": "preparing_runtime", "fields": 1})
                snapshots.append(read_status())
                callback(
                    {
                        "stage": "training",
                        "attempts": 10,
                        "accepted_count": 2,
                        "target_count": 5,
                        "max_attempts": 20,
                    }
                )
                snapshots.append(read_status())
                # 同一阶段 2 秒内的第二次上报应被节流掉
                callback(
                    {
                        "stage": "training",
                        "attempts": 11,
                        "accepted_count": 2,
                        "target_count": 5,
                        "max_attempts": 20,
                    }
                )
                snapshots.append(read_status())
                callback(
                    {
                        "stage": "finished",
                        "attempts": 20,
                        "accepted_count": 4,
                        "target_count": 5,
                        "max_attempts": 20,
                    }
                )
                snapshots.append(read_status())
                return {"run_id": "run_x", "accepted_count": 4, "attempts": 20}

            with patch("workers.job_dispatcher.run_factor_generation", side_effect=fake_generate):
                result = run_platform_job(job_dir)

            self.assertEqual(result["run_id"], "run_x")
            self.assertIn("导出股票池 pool_a", snapshots[0]["message"])
            self.assertIn("已尝试 10 / 20 次", snapshots[1]["message"])
            self.assertEqual(snapshots[1]["progress"]["attempts"], 10)
            # 被节流的第二次上报不改变已落盘的进度
            self.assertEqual(snapshots[2]["progress"]["attempts"], 10)
            self.assertIn("PPO 生成完成", snapshots[3]["message"])
            self.assertEqual(snapshots[3]["progress"]["stage"], "finished")
            self.assertEqual(read_status()["status"], "finished")


    def test_create_pool_job_dispatches_to_company_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = create_platform_job(
                root / "jobs",
                "create_pool",
                {
                    "data_source": "clickhouse",
                    "pools_root": str(root / "pools"),
                    "name": "company_pool",
                    "selection_start": "2024-01-01",
                    "selection_end": "2024-01-03",
                    "codes": ["000001"],
                },
            )

            with patch(
                "workers.job_dispatcher.create_pool_from_company",
                return_value={"pool_id": "company_pool_abc"},
            ) as company:
                result = run_platform_job(job_dir)

            self.assertEqual(result["pool_id"], "company_pool_abc")
            company.assert_called_once()
            kwargs = company.call_args.kwargs
            self.assertEqual(kwargs["pools_root"], str(root / "pools"))
            self.assertEqual(kwargs["codes"], ["000001"])
            self.assertNotIn("store_dir", kwargs)
            self.assertNotIn("data_source", kwargs)


    def test_backtest_factors_platform_job_injects_batch_id_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "snapshot_root": "snapshots",
                "pools_root": "pools",
                "factor_run_dir": "factor_run",
                "outputs_root": "outputs",
                "backtest_config": {},
            }
            job_dir = create_platform_job(root / "jobs", "backtest_factors", payload)
            captured = {}

            def fake_backtest(**kwargs):
                captured.update(kwargs)
                callback = kwargs["progress_callback"]
                callback(
                    {
                        "stage": "running",
                        "selected_count": 3,
                        "processed": 1,
                        "completed": 1,
                        "failed": 0,
                    }
                )
                callback(
                    {
                        "stage": "finished",
                        "selected_count": 3,
                        "processed": 3,
                        "completed": 2,
                        "failed": 1,
                        "backtest_id": job_dir.name,
                    }
                )
                return {"backtest_id": job_dir.name, "completed": 2, "failed": 1}

            with patch("workers.job_dispatcher.backtest_accepted_factors", side_effect=fake_backtest):
                result = run_platform_job(job_dir)

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(captured["backtest_id"], job_dir.name)
            self.assertEqual(status["status"], "finished")
            self.assertEqual(status["progress"]["processed"], 3)
            self.assertEqual(status["progress"]["completed"], 2)
            self.assertEqual(status["progress"]["failed"], 1)
            self.assertEqual(result["backtest_id"], job_dir.name)

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

            with patch("workers.job_dispatcher.compose_factors", side_effect=fake_compose_factors) as mocked:
                result = run_platform_job(job_dir)

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "finished")
            self.assertEqual(status["progress"]["candidate_count"], 5)
            self.assertEqual(result["completed_sizes"], [2])
            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()


def test_removed_master_operation_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unsupported"):
        create_platform_job(tmp_path, "prepare_master", {})


def test_pool_job_defaults_to_company_and_rejects_local(tmp_path):
    import pytest
    payload = {"pools_root": str(tmp_path / "pools"), "name": "pool",
               "selection_start": "2024-01-01", "selection_end": "2024-01-03"}
    job = create_platform_job(tmp_path / "jobs", "create_pool", payload)
    with patch("workers.job_dispatcher.create_pool_from_company", return_value={"pool_id": "p"}) as company:
        assert run_platform_job(job) == {"pool_id": "p"}
    company.assert_called_once()
    payload["data_source"] = "local"
    job = create_platform_job(tmp_path / "jobs", "create_pool", payload)
    with pytest.raises(ValueError):
        run_platform_job(job)
