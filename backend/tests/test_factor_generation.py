import tempfile
import unittest
from pathlib import Path

import pandas as pd

from snapshot_fixtures import write_company_fixture, fixture_pool, fake_panel_writer
from unittest.mock import patch
from custom_bt.factor_generation import (
    fundamental_period_mode,
    prepare_factor_runtime,
    resolve_generation_device,
    resolve_generation_operators,
    run_factor_generation,
)
from quantops.registry import generation_operator_names


class FactorGenerationTests(unittest.TestCase):
    def setUp(self):
        writer = patch("repositories.company_source.write_pool_panel", side_effect=fake_panel_writer)
        writer.start()
        self.addCleanup(writer.stop)

    def test_fundamental_period_mode_rejects_mixed_basis(self):
        self.assertEqual(
            fundamental_period_mode(["close", "fund_OperatingReenue"]),
            "cumulative",
        )
        self.assertEqual(
            fundamental_period_mode(["close", "fund_OperatingReenue_q"]),
            "single_quarter",
        )
        with self.assertRaises(ValueError):
            fundamental_period_mode([
                "close", "fund_OperatingReenue", "fund_OperatingReenue_q",
            ])

    def test_resolve_generation_device_handles_auto_and_invalid(self):
        self.assertEqual(resolve_generation_device("cpu"), "cpu")
        self.assertEqual(resolve_generation_device(" CPU "), "cpu")

        try:
            import torch
        except ImportError:
            torch = None
        expected_auto = "cuda" if torch is not None and torch.cuda.is_available() else "cpu"
        self.assertEqual(resolve_generation_device("auto"), expected_auto)
        self.assertEqual(resolve_generation_device(None), expected_auto)

        if expected_auto == "cuda":
            self.assertEqual(resolve_generation_device("cuda"), "cuda")
        else:
            with self.assertRaisesRegex(ValueError, "CUDA"):
                resolve_generation_device("cuda")

        with self.assertRaisesRegex(ValueError, "auto"):
            resolve_generation_device("tpu")

    def test_resolve_generation_operators_normalizes_aliases(self):
        classes, names = resolve_generation_operators(["add", "divide", "Add"])
        self.assertEqual(names, ["add", "div"])
        self.assertEqual(len(classes), 2)

        default_classes, default_names = resolve_generation_operators(None)
        self.assertIsNone(default_classes)
        self.assertEqual(len(default_names), len(generation_operator_names()))
        self.assertIn("ts_corr", default_names)

        with self.assertRaisesRegex(ValueError, "unsupported"):
            resolve_generation_operators(["not_an_operator"])
        with self.assertRaisesRegex(ValueError, "not enabled"):
            resolve_generation_operators(["ts_product"])

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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots_dir = root / "snapshots"
            write_company_fixture(fixture_path, snapshots_dir, fields=[])
            pool = fixture_pool(
                snapshots_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-05",
                top_n=2,
                min_coverage=1.0,
            )

            result = prepare_factor_runtime(
                snapshot_root=snapshots_dir,
                pools_root=root / "pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "factor_runtime",
                fields=["volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-04"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-05"},
                },
            )

            self.assertEqual(result["pool_id"], pool["pool_id"])
            self.assertEqual(result["fields"], ["volume", "amount"])
            self.assertIn("close", result["panel_fields"])
            self.assertTrue((Path(result["processed_dir"]) / "panel.parquet").exists())
            self.assertTrue((Path(result["splits"]["train"]["cache_dir"]) / "manifest.json").exists())
            self.assertTrue((Path(result["splits"]["valid"]["cache_dir"]) / "manifest.json").exists())
            self.assertTrue((Path(result["runtime_dir"]) / "runtime_manifest.json").exists())

    def test_prepare_factor_runtime_accepts_pool_payload_without_local_dir(self):
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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots_dir = root / "snapshots"
            write_company_fixture(fixture_path, snapshots_dir, fields=[])
            pool = fixture_pool(
                snapshots_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-05",
                top_n=2,
                min_coverage=1.0,
            )
            codes = (
                root / "pools" / pool["pool_id"] / "codes.txt"
            ).read_text(encoding="utf-8").split()

            result = prepare_factor_runtime(
                snapshot_root=snapshots_dir,
                pools_root=root / "missing_pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "factor_runtime",
                fields=["volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-04"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-05"},
                },
                pool_manifest=pool,
                pool_codes=codes,
            )

            self.assertEqual(result["pool_codes"], codes)
            self.assertTrue((Path(result["processed_dir"]) / "panel.parquet").exists())
            self.assertTrue((Path(result["splits"]["train"]["cache_dir"]) / "manifest.json").exists())

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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots_dir = root / "snapshots"
            write_company_fixture(fixture_path, snapshots_dir, fields=[])
            pool = fixture_pool(
                snapshots_dir,
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

            progress = []
            result = run_factor_generation(
                snapshot_root=snapshots_dir,
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
                operators=["abs", "subtract"],
                progress_callback=progress.append,
                ppo_runner=fake_runner,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["storage_metadata"]["pool_id"], pool["pool_id"])
            self.assertEqual(calls[0]["storage_metadata"]["operators"], ["abs", "sub"])
            self.assertEqual(calls[0]["storage_metadata"]["operator_mode"], "selected")
            self.assertEqual(len(calls[0]["operators"]), 2)
            self.assertIn(calls[0]["device"], {"cpu", "cuda"})
            self.assertEqual(result["device"], calls[0]["device"])
            self.assertEqual(
                [item["stage"] for item in progress[:3]],
                ["preparing_runtime", "loading_panels", "initializing"],
            )
            self.assertEqual(result["operators"], ["abs", "sub"])
            self.assertEqual(result["operator_mode"], "selected")
            self.assertEqual(result["pool_id"], pool["pool_id"])
            self.assertTrue((Path(result["factor_run_dir"]) / "factor_run.json").exists())

    def test_run_factor_generation_clamps_lookback_for_short_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for date in pd.date_range("2024-01-01", periods=12, freq="D"):
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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots_dir = root / "snapshots"
            write_company_fixture(fixture_path, snapshots_dir, fields=[])
            pool = fixture_pool(
                snapshots_dir,
                root / "pools",
                "all",
                "2024-01-01",
                "2024-01-12",
                top_n=2,
                min_coverage=1.0,
            )

            class FakeRunnerResult:
                accepted_count = 0
                attempts = 0
                target_reached = False
                attempts_exhausted = False

            result = run_factor_generation(
                snapshot_root=snapshots_dir,
                pools_root=root / "pools",
                pool_id=pool["pool_id"],
                runtime_root=root / "factor_runtime",
                factor_runs_root=root / "factor_runs",
                fields=["close", "volume", "amount"],
                splits={
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-10"},
                    "valid": {"cache_start": "2024-01-04", "cache_end": "2024-01-12"},
                },
                max_backtrack_days=100,
                target_horizon=1,
                max_future_days=2,
                generation_config={"target_factor_count": 1, "max_attempts": 1},
                ppo_runner=lambda **kwargs: FakeRunnerResult(),
            )

            assert result["requested_max_backtrack_days"] == 100
            assert result["max_backtrack_days"] == 2
            assert result["split_days"]["valid"] == 9

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
            fixture_path = root / "daily.parquet"
            pd.DataFrame(rows).to_parquet(fixture_path, index=False)
            snapshots_dir = root / "snapshots"
            write_company_fixture(fixture_path, snapshots_dir, fields=[])
            pool = fixture_pool(
                snapshots_dir,
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
                "snapshot_root": snapshots_dir,
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
