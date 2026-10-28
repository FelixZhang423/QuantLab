import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from custom_bt import company_source
from custom_bt.expressions import ExpressionError
from custom_bt.manual_backtest import (
    normalize_manual_expression,
    run_manual_backtest,
    validate_pool_id,
    validate_run_name,
)


def _panel() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-01", periods=25, freq="D")
    for index, date in enumerate(dates):
        for code, base in (("000001", 10.0), ("600000", 20.0)):
            price = base + index * 0.1 + (index % 3) * 0.05
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": price,
                    "close": price + 0.05,
                    "high": price + 0.2,
                    "low": price - 0.1,
                    "volume": 1000.0,
                    "amount": 20000.0,
                    "Ifsuspend": 0,
                    "if_up": 0,
                    "if_down": 0,
                }
            )
    return pd.DataFrame(rows)


def _company_pool(root: Path, signature: str = company_source.SOURCE_SIGNATURE) -> Path:
    pools_root = root / "pools"
    pool_dir = pools_root / "pool_a"
    pool_dir.mkdir(parents=True)
    (pool_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pool_id": "pool_a",
                "name": "pool_a",
                "data_source": "clickhouse",
                "source_signature": signature,
                "selection_start": "2024-01-01",
                "selection_end": "2024-01-25",
            }
        ),
        encoding="utf-8",
    )
    (pool_dir / "codes.txt").write_text("000001\n600000\n", encoding="utf-8")
    return pools_root


def _config() -> dict:
    return {
        "start_date": "2024-01-01",
        "end_date": "2024-01-25",
        "top_k": 1,
        "initial_cash": 1_000_000.0,
    }


class ManualBacktestTests(unittest.TestCase):
    def test_normalize_expression_accepts_infix_and_keeps_aliases(self):
        self.assertEqual(
            normalize_manual_expression("close / delay(close, 20) - 1"),
            "close / delay(close, 20) - 1",
        )
        with self.assertRaisesRegex(ValueError, "empty"):
            normalize_manual_expression("   ")
        with self.assertRaises(ValueError):
            validate_run_name("../escape")
        # 池 ID 由「名称 + 参数哈希」生成，中文名称必须能通过校验
        self.assertEqual(validate_pool_id("测试股票池_a9883be5"), "测试股票池_a9883be5")
        with self.assertRaises(ValueError):
            validate_pool_id("../escape")

    def test_run_manual_backtest_from_company_pool_writes_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pools_root = _company_pool(root)
            outputs = root / "outputs"
            progress = []
            with patch.object(
                company_source,
                "meta",
                return_value={
                    "data_source": "clickhouse",
                    "source_signature": company_source.SOURCE_SIGNATURE,
                    "date_min": "2024-01-01",
                    "date_max": "2024-01-25",
                },
            ), patch.object(company_source, "load_panel", return_value=_panel()) as load_panel:
                result = run_manual_backtest(
                    pools_root,
                    outputs,
                    "momentum_20",
                    "close / delay(close, 1) - 1",
                    _config(),
                    "pool_a",
                    backtest_id="job_42",
                    progress_callback=progress.append,
                )

            self.assertEqual(result["run_key"], "manual/job_42/momentum_20")
            self.assertEqual(result["data_source"], "clickhouse")
            self.assertEqual(result["pool_id"], "pool_a")
            self.assertEqual(result["n_stocks"], 2)
            self.assertIn("annual_return", result["summary"])
            load_panel.assert_called_once()
            self.assertEqual(load_panel.call_args.args[0], ["000001", "600000"])

            run_dir = outputs / "manual" / "job_42" / "momentum_20"
            for name in ("manifest.json", "summary.json", "daily_report.csv", "annual_metrics.csv"):
                self.assertTrue((run_dir / name).is_file(), name)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result_type"], "manual")
            self.assertEqual(manifest["run_key"], "manual/job_42/momentum_20")
            self.assertEqual(manifest["canonical_expression"], "close / delay(close, 1) - 1")
            self.assertEqual(manifest["data_source"], "clickhouse")
            self.assertEqual(manifest["backtest_id"], "job_42")
            self.assertEqual(
                [item["stage"] for item in progress],
                ["loading_panel", "evaluating", "running", "finished"],
            )

    def test_local_pool_falls_back_to_master_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pools_root = root / "pools"
            pool_dir = pools_root / "pool_local"
            pool_dir.mkdir(parents=True)
            (pool_dir / "manifest.json").write_text(
                json.dumps({"pool_id": "pool_local", "source_signature": "local_sig"}),
                encoding="utf-8",
            )
            (pool_dir / "codes.txt").write_text("000001\n", encoding="utf-8")
            master = root / "master"
            master.mkdir()
            (master / "meta.json").write_text(
                json.dumps({"source_signature": "local_sig"}), encoding="utf-8"
            )
            with patch(
                "custom_bt.manual_backtest.load_pool_panel", return_value=_panel().query("code == '000001'")
            ) as load_panel:
                result = run_manual_backtest(
                    pools_root,
                    root / "outputs",
                    "local_run",
                    "close",
                    _config(),
                    "pool_local",
                    master_store=master,
                    backtest_id="job_local",
                )

            self.assertEqual(result["data_source"], "local")
            self.assertEqual(load_panel.call_args.args[0], master)
            self.assertTrue((root / "outputs" / "manual" / "job_local" / "local_run").is_dir())

    def test_rejects_source_signature_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pools_root = _company_pool(root, signature="other")
            with patch.object(
                company_source,
                "meta",
                return_value={"source_signature": company_source.SOURCE_SIGNATURE},
            ):
                with self.assertRaisesRegex(ValueError, "signature"):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "close",
                        _config(),
                        "pool_a",
                        backtest_id="job_1",
                    )

    def test_rejects_invalid_or_unknown_expression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pools_root = _company_pool(root)
            with patch.object(
                company_source,
                "meta",
                return_value={"source_signature": company_source.SOURCE_SIGNATURE},
            ), patch.object(company_source, "load_panel", return_value=_panel()):
                with self.assertRaises(ExpressionError):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "not_a_field + 1",
                        _config(),
                        "pool_a",
                        backtest_id="job_1",
                    )
                with self.assertRaises(ExpressionError):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "close +",
                        _config(),
                        "pool_a",
                        backtest_id="job_2",
                    )

    def test_rejects_empty_panel_and_invalid_backtest_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pools_root = _company_pool(root)
            with patch.object(
                company_source,
                "meta",
                return_value={"source_signature": company_source.SOURCE_SIGNATURE},
            ), patch.object(company_source, "load_panel", return_value=pd.DataFrame()):
                with self.assertRaisesRegex(ValueError, "no panel rows"):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "close",
                        _config(),
                        "pool_a",
                        backtest_id="job_1",
                    )
                with self.assertRaisesRegex(ValueError, "invalid backtest_id"):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "close",
                        _config(),
                        "pool_a",
                        backtest_id="../escape",
                    )
                with self.assertRaisesRegex(ValueError, "invalid pool_id"):
                    run_manual_backtest(
                        pools_root,
                        root / "outputs",
                        "demo",
                        "close",
                        _config(),
                        "../escape",
                        backtest_id="job_1",
                    )


if __name__ == "__main__":
    unittest.main()
