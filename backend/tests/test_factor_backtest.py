import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.data import build_master_store
from custom_bt.factor_backtest import backtest_accepted_factors, factor_id
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
            pool, run_dir, config = _prepare_factor_case(root)

            result = backtest_accepted_factors(
                master_store=root / "master",
                pools_root=root / "pools",
                factor_run_dir=run_dir,
                outputs_root=root / "outputs",
                backtest_config=config,
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
            expected_key = f"factor/{pool['pool_id']}/run_a/{summary.iloc[0]['factor_id']}"
            self.assertEqual(summary.iloc[0]["run_key"], expected_key)
            manifest = json.loads(
                (Path(result["output_dir"]) / "factor_backtest_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["run_key_prefix"], result["run_key_prefix"])
            self.assertIsNone(manifest["backtest_id"])

    def test_backtest_writes_versioned_batch_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool, run_dir, config = _prepare_factor_case(root, expressions=("$close", "$open"))
            second_id = factor_id(2, "$open")
            progress = []

            result = backtest_accepted_factors(
                master_store=root / "master",
                pools_root=root / "pools",
                factor_run_dir=run_dir,
                outputs_root=root / "outputs",
                backtest_config=config,
                backtest_id="job_123",
                factor_ids=[second_id],
                progress_callback=progress.append,
            )

            output_dir = Path(result["output_dir"])
            self.assertEqual(
                output_dir,
                (root / "outputs" / "saved_backtests" / "factor" / pool["pool_id"] / "run_a" / "job_123").resolve(),
            )
            self.assertEqual(result["backtest_id"], "job_123")
            self.assertEqual(result["accepted_count"], 2)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["run_key_prefix"], f"factor/{pool['pool_id']}/run_a/job_123")
            self.assertEqual(len(list(output_dir.glob("factor_*/summary.json"))), 1)
            summary = pd.read_csv(output_dir / "factor_backtest_summary.csv")
            self.assertEqual(summary.iloc[0]["factor_id"], second_id)
            self.assertEqual(
                summary.iloc[0]["run_key"],
                f"factor/{pool['pool_id']}/run_a/job_123/{second_id}",
            )
            result_manifest = json.loads(
                (output_dir / second_id / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result_manifest["run_key"], summary.iloc[0]["run_key"])
            self.assertEqual(result_manifest["backtest_id"], "job_123")

            self.assertEqual(progress[0]["stage"], "running")
            self.assertEqual(progress[0]["processed"], 0)
            self.assertEqual(progress[0]["selected_count"], 1)
            self.assertEqual(progress[-1]["stage"], "finished")
            self.assertEqual(progress[-1]["processed"], 1)
            self.assertEqual(progress[-1]["completed"], 1)
            self.assertEqual(progress[-1]["current_factor_id"], second_id)

    def test_backtest_rejects_unknown_factor_ids_and_invalid_backtest_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, run_dir, config = _prepare_factor_case(root)

            with self.assertRaisesRegex(ValueError, "unknown factor_ids"):
                backtest_accepted_factors(
                    master_store=root / "master",
                    pools_root=root / "pools",
                    factor_run_dir=run_dir,
                    outputs_root=root / "outputs",
                    backtest_config=config,
                    factor_ids=["factor_9999_missing"],
                )
            with self.assertRaisesRegex(ValueError, "factor_ids is empty"):
                backtest_accepted_factors(
                    master_store=root / "master",
                    pools_root=root / "pools",
                    factor_run_dir=run_dir,
                    outputs_root=root / "outputs",
                    backtest_config=config,
                    factor_ids=[],
                )
            with self.assertRaisesRegex(ValueError, "invalid backtest_id"):
                backtest_accepted_factors(
                    master_store=root / "master",
                    pools_root=root / "pools",
                    factor_run_dir=run_dir,
                    outputs_root=root / "outputs",
                    backtest_config=config,
                    backtest_id="../escape",
                )


def _prepare_factor_case(root: Path, expressions=("$close",)):
    """构造最小可回测的 master / pool / factor run。"""
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
    accepted_lines = [
        json.dumps(
            {
                "expression": expression,
                "accepted": True,
                "pool_id": pool["pool_id"],
                "source_signature": pool["source_signature"],
            }
        )
        for expression in expressions
    ]
    rejected = {
        "expression": "$missing",
        "accepted": False,
        "pool_id": pool["pool_id"],
        "source_signature": pool["source_signature"],
    }
    (run_dir / "accepted_factors.jsonl").write_text("\n".join(accepted_lines) + "\n", encoding="utf-8")
    (run_dir / "rejected_candidates.jsonl").write_text(json.dumps(rejected) + "\n", encoding="utf-8")
    config = {
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "top_k": 1,
        "initial_cash": 1000000.0,
        "buy_cost": 0.001,
        "sell_cost": 0.001,
        "slippage": 0.0,
        "min_cost": 1.0,
        "max_weight_per_stock": 1.0,
    }
    return pool, run_dir, config


if __name__ == "__main__":
    unittest.main()
