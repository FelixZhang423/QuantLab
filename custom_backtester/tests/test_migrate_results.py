import json
import tempfile
import unittest
from pathlib import Path

from custom_bt.migrate_results import migrate_factor_results


def _write_result(directory: Path, config: dict) -> None:
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"run_name": directory.name, "config": config}),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(json.dumps({"sharpe": 1.0}), encoding="utf-8")
    (directory / "daily_report.csv").write_text("date,account\n", encoding="utf-8")
    (directory / "positions.csv").write_text("date,code\n", encoding="utf-8")
    (directory / "trades.csv").write_text("date,code\n", encoding="utf-8")
    (directory / "annual_metrics.csv").write_text("year,return\n", encoding="utf-8")
    (directory / "summary.png").write_bytes(b"png")
    if config.get("composite_expression"):
        (directory / "factor_weights.json").write_text(
            json.dumps(
                [
                    {
                        "rank": 1,
                        "factor_id": "accepted_0001",
                        "expression": "Div($close,$open)",
                        "backtest_expression": "divide(close,open)",
                        "generation_score": 0.2,
                        "weight": 1.0,
                    }
                ]
            ),
            encoding="utf-8",
        )


class MigrateResultsTests(unittest.TestCase):
    def test_migrate_factor_and_composite_results_writes_canonical_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            _write_result(
                source / "liquid_500" / "run_a" / "factor_0001",
                {
                    "pool_id": "liquid_500",
                    "factor_run_id": "run_a",
                    "factor": {"expression": "Greater($close,$open)", "ic": 0.04},
                },
            )
            _write_result(
                source / "liquid_500" / "run_a" / "composites" / "top_010",
                {
                    "pool_id": "liquid_500",
                    "factor_run_id": "run_a",
                    "composite_expression": "max(close,open)",
                },
            )

            report = migrate_factor_results(source, Path(tmp) / "saved_backtests")

            self.assertEqual(len(report["migrated"]), 2)
            manifests = list((Path(tmp) / "saved_backtests").rglob("manifest.json"))
            self.assertEqual(len(manifests), 2)
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in manifests]
            self.assertIn("max(close,open)", {item["canonical_expression"] for item in payloads})
            self.assertEqual({item["result_type"] for item in payloads}, {"factor", "composite"})
            composite = next(item for item in payloads if item["result_type"] == "composite")
            self.assertEqual(composite["components"][0]["factor_id"], "accepted_0001")
            self.assertEqual(composite["components"][0]["expression"], "div(close,open)")
            weights_path = next((Path(tmp) / "saved_backtests" / "composite").rglob("factor_weights.json"))
            weights = json.loads(weights_path.read_text(encoding="utf-8"))
            self.assertEqual(weights[0]["backtest_expression"], "div(close,open)")

            second = migrate_factor_results(source, Path(tmp) / "saved_backtests")
            self.assertEqual(len(second["migrated"]), 0)
            self.assertEqual(len(second["skipped"]), 2)


if __name__ == "__main__":
    unittest.main()
