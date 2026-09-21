import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.engine import BacktestResult
from custom_bt.results import list_runs, save_result


class ResultsTests(unittest.TestCase):
    def test_save_result_writes_expected_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            result = BacktestResult(
                daily_report=pd.DataFrame(
                    {
                        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                        "account": [100.0, 101.0],
                        "return": [0.0, 0.01],
                        "cost": [0.0, 0.001],
                        "turnover": [0.0, 0.2],
                        "pnl": [0.0, 1.0],
                        "drawdown": [0.0, 0.0],
                    }
                ),
                positions=pd.DataFrame({"date": ["2024-01-02"], "code": ["000001"]}),
                trades=pd.DataFrame({"date": ["2024-01-02"], "code": ["000001"], "side": ["buy"]}),
                summary={"total_return": 0.01},
                annual=pd.DataFrame({"year": [2024], "return": [0.01], "sharpe": [1.0]}),
            )

            run_dir = save_result(
                result,
                output_root,
                "unit_run",
                config={"expr": "close"},
                metadata={
                    "result_type": "manual",
                    "canonical_expression": "close",
                    "generation_ic": None,
                },
            )
            runs = list_runs(output_root)

            self.assertTrue((run_dir / "daily_report.csv").exists())
            self.assertTrue((run_dir / "annual_metrics.csv").exists())
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "manifest.json").exists())
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result_type"], "manual")
            self.assertEqual(manifest["canonical_expression"], "close")
            self.assertEqual(runs[0]["run_name"], "unit_run")

    def test_list_runs_finds_nested_saved_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "saved_backtests" / "factor" / "pool" / "run" / "factor_0001"
            root.mkdir(parents=True)
            (root / "manifest.json").write_text(
                json.dumps({"result_type": "factor", "run_name": "factor_0001"}),
                encoding="utf-8",
            )
            (root / "summary.json").write_text("{}", encoding="utf-8")
            (root / "daily_report.csv").write_text("date,account\n", encoding="utf-8")

            runs = list_runs(Path(tmp) / "saved_backtests")

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["run_name"], "factor_0001")

    def test_list_runs_ignores_manifests_without_supported_result_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "legacy"
            root.mkdir(parents=True)
            (root / "manifest.json").write_text(json.dumps({"run_name": "legacy"}), encoding="utf-8")
            (root / "summary.json").write_text("{}", encoding="utf-8")
            (root / "daily_report.csv").write_text("date,account\n", encoding="utf-8")

            self.assertEqual(list_runs(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
