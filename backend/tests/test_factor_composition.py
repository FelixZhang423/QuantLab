import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from snapshot_fixtures import write_company_fixture, fixture_pool, fake_panel_writer, publish_confirmed
from unittest.mock import patch
from custom_bt.factor_composition import (
    CompositionCandidate,
    SelectedComponent,
    WeightOptimizationResult,
    _combine_weighted_alphas,
    evaluate_alpha_target_metrics,
    make_forward_return_target,
    daily_mutual_ic,
    daily_cross_section_zscore,
    load_composition_candidates,
    select_composition_pool,
    compose_factors,
)
from repositories.result_store import list_runs


def _toy_panel() -> pd.DataFrame:
    rows = []
    codes = ["000001", "000002", "000003", "000004"]
    for day, date in enumerate(pd.date_range("2024-01-01", periods=8, freq="D")):
        for idx, code in enumerate(codes):
            base = 10.0 + idx + day * 0.2
            rows.append(
                {
                    "code": code,
                    "timestamps": date.strftime("%Y-%m-%d"),
                    "open": base,
                    "close": base + idx * 0.3,
                    "high": base + 0.5,
                    "low": base - 0.5,
                    "vol": 1000.0 + idx * 100.0,
                    "amount": (1000.0 + idx * 100.0) * base,
                    "ChangePCT": [0.01, -0.02, 0.03, -0.01][(idx + day) % 4],
                    "ma5": [3.0, 1.0, 4.0, 2.0][(idx + day) % 4],
                    "Ifsuspend": 0,
                    "if_up": 0,
                    "if_down": 0,
                }
            )
    return pd.DataFrame(rows)


def _targeted_panel() -> pd.DataFrame:
    rows = []
    codes = ["000001", "000002", "000003", "000004"]
    patterns = [
        [-0.03, -0.01, 0.01, 0.03],
        [-0.02, 0.00, 0.02, 0.04],
        [-0.04, -0.02, 0.00, 0.02],
        [-0.01, 0.01, 0.03, 0.05],
        [-0.03, -0.01, 0.01, 0.03],
    ]
    close = {code: 100.0 for code in codes}
    for day, date in enumerate(pd.date_range("2024-01-01", periods=6, freq="D")):
        if day > 0:
            for idx, code in enumerate(codes):
                close[code] = close[code] * (1.0 + patterns[day - 1][idx])
        for idx, code in enumerate(codes):
            signal = patterns[day][idx] if day < len(patterns) else 0.0
            rows.append(
                {
                    "code": code,
                    "date": date,
                    "open": close[code],
                    "close": close[code],
                    "high": close[code] * 1.01,
                    "low": close[code] * 0.99,
                    "volume": 1000.0 + idx,
                    "amount": close[code] * (1000.0 + idx),
                    "ChangePCT": signal,
                    "good_signal": signal,
                    "noise_signal": [0.03, -0.01, 0.02, -0.02][idx],
                    "Ifsuspend": 0,
                    "if_up": 0,
                    "if_down": 0,
                }
            )
    return pd.DataFrame(rows)


class FactorCompositionTests(unittest.TestCase):
    def setUp(self):
        writer = patch("repositories.company_source.write_pool_panel", side_effect=fake_panel_writer)
        writer.start()
        self.addCleanup(writer.stop)

    def test_candidate_loader_filters_and_sorts_by_selected_metric(self):
        records = [
            {"factor_id": "bad_pool", "pool_id": "other", "accepted": True, "expression": "close", "score": 9.0},
            {"factor_id": "rejected", "pool_id": "pool_a", "accepted": False, "expression": "open", "score": 8.0},
            {"factor_id": "low", "pool_id": "pool_a", "accepted": True, "expression": "low", "score": 0.2},
            {
                "factor_id": "best",
                "pool_id": "pool_a",
                "accepted": True,
                "expression": "close",
                "canonical_expression": "close",
                "score": 1.4,
                "ic": 0.05,
                "rank_ic": 0.03,
                "coverage": 0.99,
            },
            {
                "factor_id": "second",
                "pool_id": "pool_a",
                "accepted": True,
                "expression": "open",
                "score": 0.9,
                "ic": 0.04,
                "rank_ic": 0.02,
                "coverage": 0.95,
            },
        ]

        candidates = load_composition_candidates(
            records,
            pool_id="pool_a",
            selection_metric="score",
            min_score=0.5,
            min_ic=0.01,
            min_coverage=0.9,
        )

        self.assertEqual([item.factor_id for item in candidates], ["best", "second"])
        self.assertEqual(candidates[0].canonical_expression, "close")
        self.assertEqual(candidates[0].metric("score"), 1.4)

    def test_mutual_ic_uses_daily_cross_section_and_rejects_duplicate_factor(self):
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"] * 4 + ["2024-01-02"] * 4),
                "code": ["000001", "000002", "000003", "000004"] * 2,
                "a": [1.0, 2.0, 3.0, 4.0, 2.0, 3.0, 4.0, 5.0],
                "b": [1.1, 2.1, 3.1, 4.1, 2.1, 3.1, 4.1, 5.1],
                "c": [4.0, 1.0, 3.0, 2.0, 1.0, 4.0, 2.0, 3.0],
            }
        )
        a = panel[["date", "code", "a"]].rename(columns={"a": "alpha"})
        b = panel[["date", "code", "b"]].rename(columns={"b": "alpha"})
        c = panel[["date", "code", "c"]].rename(columns={"c": "alpha"})

        z = daily_cross_section_zscore(a)
        self.assertAlmostEqual(float(z.groupby("date")["alpha"].mean().abs().max()), 0.0, places=10)
        self.assertGreater(daily_mutual_ic(a, b)["mutual_ic"], 0.99)
        self.assertLess(daily_mutual_ic(a, c)["mutual_ic"], 0.99)

    def test_daily_cross_section_zscore_matches_alphagen_normalize_by_day(self):
        values = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"] * 4 + ["2024-01-02"] * 4),
                "code": ["000001", "000002", "000003", "000004"] * 2,
                "alpha": [1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, np.nan],
            }
        )

        normalized = daily_cross_section_zscore(values)

        first_day = normalized[normalized["date"] == pd.Timestamp("2024-01-01")]["alpha"]
        self.assertAlmostEqual(float(first_day.mean()), 0.0, places=10)
        self.assertAlmostEqual(float(first_day.std(ddof=0)), 1.0, places=10)
        second_day = normalized[normalized["date"] == pd.Timestamp("2024-01-02")]["alpha"]
        self.assertTrue(np.isfinite(second_day).all())
        np.testing.assert_allclose(second_day.to_numpy(), np.zeros(4), atol=1e-12)

    def test_daily_cross_section_zscore_clips_outliers(self):
        values = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"] * 4),
                "code": ["000001", "000002", "000003", "000004"],
                "alpha": [1.0, 2.0, 3.0, 100.0],
            }
        )

        normalized = daily_cross_section_zscore(values, clip=1.0)

        self.assertLessEqual(float(normalized["alpha"].abs().max()), 1.0 + 1e-12)
        self.assertEqual(int((normalized["alpha"] == 1.0).sum()), 1)

    def test_select_pool_equal_weight_uses_one_over_n_without_optimizer(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
            {"factor_id": "f2", "pool_id": "pool_a", "accepted": True, "expression": "ma5", "score": 0.9, "ic": 0.06},
            {"factor_id": "f3", "pool_id": "pool_a", "accepted": True, "expression": "ChangePCT", "score": 0.8, "ic": 0.04},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")

        selected = select_composition_pool(
            panel,
            candidates,
            max_factors=3,
            z_clip=3.0,
        )

        self.assertEqual([item.factor_id for item in selected.components], ["f1", "f2", "f3"])
        np.testing.assert_allclose(
            [item.weight for item in selected.components],
            np.full(3, 1.0 / 3.0),
            atol=1e-12,
        )
        self.assertEqual(selected.optimization.method, "equal_weight")
        self.assertEqual(selected.optimization.iterations, 0)
        self.assertTrue(selected.optimization.converged)

    def test_select_pool_equal_weight_rejects_extra_candidates_at_capacity(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
            {"factor_id": "f2", "pool_id": "pool_a", "accepted": True, "expression": "ma5", "score": 0.9, "ic": 0.06},
            {"factor_id": "f3", "pool_id": "pool_a", "accepted": True, "expression": "ChangePCT", "score": 0.8, "ic": 0.04},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")

        selected = select_composition_pool(panel, candidates, max_factors=2)

        self.assertEqual([item.factor_id for item in selected.components], ["f1", "f2"])
        np.testing.assert_allclose([item.weight for item in selected.components], [0.5, 0.5])
        capacity_rejections = [row for row in selected.rejections if row.get("reason") == "capacity_limit"]
        self.assertEqual([row["factor_id"] for row in capacity_rejections], ["f3"])

    def test_select_pool_equal_weight_deduplicates_on_absolute_mutual_ic(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
            {"factor_id": "f2", "pool_id": "pool_a", "accepted": True, "expression": "-close", "score": 0.9, "ic": 0.10},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")

        selected = select_composition_pool(
            panel,
            candidates,
            max_factors=2,
            mutual_ic_threshold=0.8,
        )

        self.assertEqual([item.factor_id for item in selected.components], ["f1"])
        self.assertEqual(selected.rejections[0]["reason"], "mutual_ic")
        self.assertEqual(selected.rejections[0]["comparison"], "abs")
        self.assertLess(selected.rejections[0]["mutual_ic"], -0.99)
        self.assertGreater(selected.rejections[0]["gate_value"], 0.99)

    def test_latest_screen_skips_untradable_names_and_reports_contributions(self):
        from custom_bt.composition_screen import build_latest_screen

        panel = pd.DataFrame(
            [
                {"date": "2024-01-02", "code": "000001", "open": 10.0, "Ifsuspend": 0, "if_up": 0},
                {"date": "2024-01-02", "code": "000002", "open": 20.0, "Ifsuspend": 0, "if_up": 0},
                {"date": "2024-01-02", "code": "000003", "open": 30.0, "Ifsuspend": 0, "if_up": 0},
                {"date": "2024-01-03", "code": "000001", "open": 10.0, "Ifsuspend": 1, "if_up": 0},
                {"date": "2024-01-03", "code": "000002", "open": 20.0, "Ifsuspend": 0, "if_up": 0},
                {"date": "2024-01-03", "code": "000003", "open": 30.0, "Ifsuspend": 0, "if_up": 1},
            ]
        )
        signal = pd.Timestamp("2024-01-02")
        z1 = pd.DataFrame({"date": [signal] * 3, "code": ["000001", "000002", "000003"], "alpha": [2.0, 0.0, -2.0]})
        z2 = pd.DataFrame({"date": [signal] * 3, "code": ["000001", "000002", "000003"], "alpha": [0.0, 2.0, -2.0]})
        composite = pd.DataFrame({"date": [signal] * 3, "code": ["000001", "000002", "000003"], "alpha": [1.0, 1.0, -2.0]})
        candidate_1 = CompositionCandidate("f1", "close", "close", "close", "pool_a", None, {}, {})
        candidate_2 = CompositionCandidate("f2", "ma5", "ma5", "ma5", "pool_a", None, {}, {})
        components = [
            SelectedComponent(candidate_1, z1, z1, 0.5),
            SelectedComponent(candidate_2, z2, z2, 0.5),
        ]

        screen = build_latest_screen(composite, components, panel, top_k=2, row_limit=10)

        self.assertEqual(screen["signal_date"], "2024-01-02")
        self.assertEqual(screen["execution_date"], "2024-01-03")
        self.assertFalse(screen["execution_pending"])
        self.assertEqual(screen["selected_count"], 1)
        self.assertEqual(screen["buyable_count"], 1)
        by_code = {row["code"]: row for row in screen["rows"]}
        self.assertEqual(by_code["000001"]["blocked_reason"], "next_open_suspended")
        self.assertFalse(by_code["000001"]["selected"])
        self.assertEqual(by_code["000002"]["status"], "buyable")
        self.assertTrue(by_code["000002"]["selected"])
        self.assertEqual(by_code["000003"]["blocked_reason"], "next_open_limit_up")
        self.assertAlmostEqual(
            sum(item["contribution"] for item in by_code["000001"]["contributions"]),
            by_code["000001"]["composite_score"],
        )
        self.assertEqual(len(screen["flat_rows"]), 3)

    def test_latest_screen_marks_execution_pending_without_next_trading_day(self):
        from custom_bt.composition_screen import build_latest_screen

        panel = pd.DataFrame(
            [
                {"date": "2024-01-02", "code": "000001", "open": 10.0, "Ifsuspend": 0, "if_up": 0},
                {"date": "2024-01-02", "code": "000002", "open": 20.0, "Ifsuspend": 0, "if_up": 0},
            ]
        )
        signal = pd.Timestamp("2024-01-02")
        z = pd.DataFrame({"date": [signal] * 2, "code": ["000001", "000002"], "alpha": [1.0, -1.0]})
        composite = pd.DataFrame({"date": [signal] * 2, "code": ["000001", "000002"], "alpha": [1.0, -1.0]})
        candidate = CompositionCandidate("f1", "close", "close", "close", "pool_a", None, {}, {})

        screen = build_latest_screen(
            composite,
            [SelectedComponent(candidate, z, z, 1.0)],
            panel,
            top_k=1,
            max_weight_per_stock=1.0,
        )

        self.assertTrue(screen["execution_pending"])
        self.assertIsNone(screen["execution_date"])
        self.assertIsNone(screen["buyable_count"])
        self.assertEqual(screen["selected_count"], 1)
        selected = [row for row in screen["rows"] if row["selected"]]
        self.assertEqual([row["code"] for row in selected], ["000001"])
        self.assertEqual(selected[0]["status"], "pending_next_open")
        self.assertIsNone(selected[0]["buyable_next_open"])
        self.assertAlmostEqual(selected[0]["target_weight"], 1.0)

    def test_composite_combination_applies_weights_to_preprocessed_alphas(self):
        base = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"] * 4),
                "code": ["000001", "000002", "000003", "000004"],
                "alpha": [1.0, 2.0, 3.0, 4.0],
            }
        )
        scaled = base.copy()
        scaled["alpha"] = scaled["alpha"] * 1000.0
        candidate_a = CompositionCandidate("f1", "close", "close", "close", "pool_a", None, {"ic": 0.05}, {})
        candidate_b = CompositionCandidate("f2", "1000*close", "multiply(close,1000)", "multiply(close,1000)", "pool_a", None, {"ic": 0.05}, {})
        components = [
            SelectedComponent(candidate_a, base, daily_cross_section_zscore(base), 1.0),
            SelectedComponent(candidate_b, scaled, daily_cross_section_zscore(scaled), 1.0),
        ]

        combined = _combine_weighted_alphas(components)
        expected = daily_cross_section_zscore(base)
        expected["alpha"] = expected["alpha"] * 2.0

        pd.testing.assert_series_equal(
            combined.sort_values(["date", "code"])["alpha"].reset_index(drop=True),
            expected.sort_values(["date", "code"])["alpha"].reset_index(drop=True),
            check_names=False,
        )

    def test_forward_return_target_and_composite_metrics_follow_single_factor_horizon(self):
        panel = _targeted_panel()
        alpha = panel[["date", "code", "good_signal"]].rename(columns={"good_signal": "alpha"})

        target = make_forward_return_target(panel, horizon=1)
        metrics = evaluate_alpha_target_metrics(daily_cross_section_zscore(alpha), target)

        self.assertGreater(metrics["ic"], 0.99)
        self.assertGreater(metrics["rank_ic"], 0.99)
        self.assertGreater(metrics["icir"], 10.0)
        self.assertEqual(metrics["valid_days"], 5)

    def test_select_pool_applies_mutual_ic_gate_before_admission(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
            {"factor_id": "f2", "pool_id": "pool_a", "accepted": True, "expression": "close + 0.001", "score": 0.9, "ic": 0.09},
            {"factor_id": "f3", "pool_id": "pool_a", "accepted": True, "expression": "ma5", "score": 0.8, "ic": 0.04},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")

        selected = select_composition_pool(panel, candidates, max_factors=3, mutual_ic_threshold=0.99)

        self.assertEqual([item.factor_id for item in selected.components], ["f1", "f3"])
        self.assertEqual(selected.rejections[0]["factor_id"], "f2")
        self.assertEqual(selected.rejections[0]["reason"], "mutual_ic")

    def test_select_pool_reports_candidate_before_expensive_evaluation(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")
        events = []

        def fake_evaluate_expression(expr, input_panel, output_name="alpha"):
            self.assertTrue(any(event.get("stage") == "evaluating" for event in events))
            return input_panel[["date", "code", "close"]].rename(columns={"close": output_name})

        with patch("custom_bt.factor_composition.evaluate_expression", side_effect=fake_evaluate_expression):
            select_composition_pool(panel, candidates, max_factors=1, progress_callback=events.append)

        self.assertEqual(events[0]["stage"], "evaluating")
        self.assertEqual(events[0]["candidate_index"], 1)

    def test_select_pool_rejects_candidate_when_marginal_ic_does_not_improve(self):
        records = [
            {"factor_id": "good", "pool_id": "pool_a", "accepted": True, "expression": "good_signal", "score": 1.0, "ic": 0.10},
            {"factor_id": "noise", "pool_id": "pool_a", "accepted": True, "expression": "noise_signal", "score": 0.9, "ic": 0.01},
        ]
        panel = _targeted_panel()
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")

        selected = select_composition_pool(
            panel,
            candidates,
            max_factors=2,
            mutual_ic_threshold=0.99,
            target_horizon=1,
            min_marginal_ic_improvement=0.001,
        )

        self.assertEqual([item.factor_id for item in selected.components], ["good"])
        self.assertEqual(selected.rejections[-1]["factor_id"], "noise")
        self.assertEqual(selected.rejections[-1]["reason"], "marginal_contribution")
        self.assertLess(selected.rejections[-1]["marginal"]["delta"]["ic"], 0.001)
        self.assertEqual(selected.admission_log[0]["factor_id"], "good")
        self.assertGreater(selected.admission_log[0]["after"]["ic"], 0.99)

    def test_select_pool_reports_final_equal_weight_stage(self):
        records = [
            {"factor_id": "f1", "pool_id": "pool_a", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.10},
            {"factor_id": "f2", "pool_id": "pool_a", "accepted": True, "expression": "ma5", "score": 0.9, "ic": 0.06},
        ]
        panel = _toy_panel().rename(columns={"timestamps": "date", "vol": "volume"})
        candidates = load_composition_candidates(records, "pool_a", selection_metric="score")
        events = []

        selected = select_composition_pool(panel, candidates, max_factors=2, progress_callback=events.append)

        self.assertIn("optimizing_weights", [event.get("stage") for event in events])
        np.testing.assert_allclose([item.weight for item in selected.components], [0.5, 0.5])

    def test_compose_factors_saves_each_sweep_size_as_unified_composite_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "daily.parquet"
            _toy_panel().to_parquet(source, index=False)
            write_company_fixture(source, root / "snapshots", fields=["ma5"], chunksize=16, overwrite=True)
            pool_manifest = fixture_pool(
                root / "snapshots",
                root / "pools",
                name="toy",
                selection_start="2024-01-01",
                selection_end="2024-01-08",
                top_n=4,
                min_coverage=1.0,
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            factor_manifest = {
                "run_id": "run_a",
                "pool_id": pool_manifest["pool_id"],
                "data_source": "clickhouse", "snapshot_id": pool_manifest["snapshot_id"], "source_signature": pool_manifest["source_signature"],
                "accepted_count": 3,
            }
            (run_dir / "factor_run.json").write_text(json.dumps(factor_manifest), encoding="utf-8")
            accepted = [
                {"factor_id": "f1", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.08, "coverage": 1.0},
                {"factor_id": "f2", "accepted": True, "expression": "ma5", "score": 0.8, "ic": 0.04, "coverage": 1.0},
                {"factor_id": "f3", "accepted": True, "expression": "ChangePCT", "score": 0.6, "ic": 0.02, "coverage": 1.0},
            ]
            (run_dir / "confirmed_factors.jsonl").write_text(
                "\n".join(json.dumps(row) for row in accepted),
                encoding="utf-8",
            )
            publish_confirmed(run_dir)

            result = compose_factors(
                snapshot_root=root / "snapshots",
                pools_root=root / "pools",
                pool_id=pool_manifest["pool_id"],
                factor_run_dirs=[run_dir],
                outputs_root=root / "outputs" / "saved_backtests",
                backtest_config={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-08",
                    "top_k": 2,
                    "initial_cash": 1_000_000.0,
                },
                selection_metric="score",
                min_score=0.0,
                mutual_ic_threshold=0.99,
                target_horizon=1,
                min_marginal_ic_improvement=-1.0,
                sweep_sizes=[2, 3],
                max_factors=3,
            )

            self.assertEqual(result["completed_sizes"], [2, 3])
            for output_dir in result["output_dirs"]:
                path = Path(output_dir)
                self.assertTrue((path / "manifest.json").exists())
                self.assertTrue((path / "factor_weights.json").exists())
                self.assertTrue((path / "composition_summary.csv").exists())
                self.assertTrue((path / "daily_report.csv").exists())
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["factor_preprocess"]["method"], "alphagen_normalize_by_day")
                weights = json.loads((path / "factor_weights.json").read_text(encoding="utf-8"))
                self.assertEqual(weights[0]["preprocess"]["method"], "alphagen_normalize_by_day")
                self.assertEqual(weights[0]["applied_to"], "preprocessed_alpha")
                self.assertTrue(weights[0]["preprocessed_expression"].startswith("zscore("))
                self.assertIn("marginal", weights[0])
                self.assertIn("composition_metrics", manifest)
                self.assertIn("ic", manifest["composition_metrics"])
                self.assertEqual(manifest["target_horizon"], 1)
                self.assertTrue((path / "composition_admission_log.json").exists())
                self.assertTrue((path / "latest_screen.json").exists())
                self.assertTrue((path / "latest_screen.csv").exists())
                screen = json.loads((path / "latest_screen.json").read_text(encoding="utf-8"))
                self.assertEqual(screen["signal_date"], "2024-01-08")
                self.assertIn("rows", screen)
                self.assertNotIn("flat_rows", screen)
            root_manifest = json.loads(
                (Path(result["manifest_path"])).read_text(encoding="utf-8")
            )
            self.assertEqual(root_manifest["composition_id"], result["composition_id"])
            self.assertEqual(root_manifest["completed_sizes"], [2, 3])
            self.assertEqual(root_manifest["default_size"], 3)
            self.assertEqual([entry["size"] for entry in root_manifest["sizes"]], [2, 3])
            runs = list_runs(root / "outputs" / "saved_backtests")
            self.assertEqual({run["result_type"] for run in runs}, {"composite"})
            self.assertEqual(len(runs), 2)

    def test_compose_factors_can_rank_candidates_by_saved_single_factor_backtest_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "daily.parquet"
            _toy_panel().to_parquet(source, index=False)
            write_company_fixture(source, root / "snapshots", fields=["ma5"], chunksize=16, overwrite=True)
            pool_manifest = fixture_pool(
                root / "snapshots",
                root / "pools",
                name="toy",
                selection_start="2024-01-01",
                selection_end="2024-01-08",
                top_n=4,
                min_coverage=1.0,
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_a",
                        "pool_id": pool_manifest["pool_id"],
                        "data_source": "clickhouse", "snapshot_id": pool_manifest["snapshot_id"], "source_signature": pool_manifest["source_signature"],
                        "accepted_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "confirmed_factors.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"factor_id": "f1", "accepted": True, "expression": "close", "score": 0.2, "ic": 0.01, "coverage": 1.0},
                        {"factor_id": "f2", "accepted": True, "expression": "ma5", "score": 1.0, "ic": 0.02, "coverage": 1.0},
                    ]
                ),
                encoding="utf-8",
            )
            publish_confirmed(run_dir)
            factor_result_dir = root / "outputs" / "saved_backtests" / "factor" / pool_manifest["pool_id"] / "run_a"
            factor_result_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"factor_id": "f1", "expression": "close", "backtest_sharpe": 1.5},
                    {"factor_id": "f2", "expression": "ma5", "backtest_sharpe": 0.2},
                ]
            ).to_csv(factor_result_dir / "factor_backtest_summary.csv", index=False)

            result = compose_factors(
                snapshot_root=root / "snapshots",
                pools_root=root / "pools",
                pool_id=pool_manifest["pool_id"],
                factor_run_dirs=[run_dir],
                outputs_root=root / "outputs" / "saved_backtests",
                backtest_config={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-08",
                    "top_k": 2,
                    "initial_cash": 1_000_000.0,
                },
                selection_metric="backtest_sharpe",
                min_backtest_sharpe=1.0,
                mutual_ic_threshold=0.99,
                sweep_sizes=[1],
                max_factors=1,
            )

            weights = json.loads((Path(result["output_dirs"][0]) / "factor_weights.json").read_text(encoding="utf-8"))
            self.assertEqual([item["factor_id"] for item in weights], ["f1"])

    def test_compose_factors_saves_underfilled_final_size_when_no_requested_size_is_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "daily.parquet"
            _toy_panel().to_parquet(source, index=False)
            write_company_fixture(source, root / "snapshots", fields=["ma5"], chunksize=16, overwrite=True)
            pool_manifest = fixture_pool(
                root / "snapshots",
                root / "pools",
                name="toy",
                selection_start="2024-01-01",
                selection_end="2024-01-08",
                top_n=4,
                min_coverage=1.0,
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_a",
                        "pool_id": pool_manifest["pool_id"],
                        "data_source": "clickhouse", "snapshot_id": pool_manifest["snapshot_id"], "source_signature": pool_manifest["source_signature"],
                        "accepted_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "confirmed_factors.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"factor_id": "f1", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.08, "coverage": 1.0},
                        {"factor_id": "f2", "accepted": True, "expression": "ma5", "score": 0.8, "ic": 0.04, "coverage": 1.0},
                    ]
                ),
                encoding="utf-8",
            )
            publish_confirmed(run_dir)

            result = compose_factors(
                snapshot_root=root / "snapshots",
                pools_root=root / "pools",
                pool_id=pool_manifest["pool_id"],
                factor_run_dirs=[run_dir],
                outputs_root=root / "outputs" / "saved_backtests",
                backtest_config={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-08",
                    "top_k": 2,
                    "initial_cash": 1_000_000.0,
                },
                selection_metric="score",
                mutual_ic_threshold=0.99,
                sweep_sizes=[10, 20, 30],
                max_factors=30,
            )

            self.assertEqual(result["selected_count"], 2)
            self.assertEqual(result["completed_sizes"], [2])
            self.assertEqual(result["underfilled_final_size"], 2)
            manifest = json.loads((Path(result["output_dirs"][0]) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["max_factors"], 2)

    def test_compose_factors_equal_weight_with_manual_ids_and_z_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "daily.parquet"
            _toy_panel().to_parquet(source, index=False)
            write_company_fixture(source, root / "snapshots", fields=["ma5"], chunksize=16, overwrite=True)
            pool_manifest = fixture_pool(
                root / "snapshots",
                root / "pools",
                name="toy",
                selection_start="2024-01-01",
                selection_end="2024-01-08",
                top_n=4,
                min_coverage=1.0,
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_a",
                        "pool_id": pool_manifest["pool_id"],
                        "data_source": "clickhouse", "snapshot_id": pool_manifest["snapshot_id"], "source_signature": pool_manifest["source_signature"],
                        "accepted_count": 3,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "confirmed_factors.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"factor_id": "f1", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.08, "coverage": 1.0},
                        {"factor_id": "f2", "accepted": True, "expression": "ma5", "score": 0.8, "ic": 0.04, "coverage": 1.0},
                        {"factor_id": "f3", "accepted": True, "expression": "ChangePCT", "score": 0.6, "ic": 0.02, "coverage": 1.0},
                    ]
                ),
                encoding="utf-8",
            )
            publish_confirmed(run_dir)

            result = compose_factors(
                snapshot_root=root / "snapshots",
                pools_root=root / "pools",
                pool_id=pool_manifest["pool_id"],
                factor_run_dirs=[run_dir],
                outputs_root=root / "outputs" / "saved_backtests",
                backtest_config={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-08",
                    "top_k": 2,
                    "initial_cash": 1_000_000.0,
                },
                factor_ids=["f2"],
                z_clip=1.5,
                mutual_ic_threshold=0.8,
                sweep_sizes=[1],
                max_factors=1,
            )

            self.assertEqual(result["weight_method"], "equal")
            self.assertEqual(result["completed_sizes"], [1])
            out_dir = Path(result["output_dirs"][0])
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["weight_method"], "equal")
            self.assertEqual(manifest["optimization"]["method"], "equal_weight")
            self.assertEqual(manifest["selected_factor_ids"], ["f2"])
            self.assertEqual(manifest["requested_factor_ids"], ["f2"])
            self.assertEqual(manifest["z_clip"], 1.5)
            self.assertEqual(manifest["factor_preprocess"]["clip"], 1.5)
            weights = json.loads((out_dir / "factor_weights.json").read_text(encoding="utf-8"))
            self.assertEqual(len(weights), 1)
            self.assertEqual(weights[0]["factor_id"], "f2")
            self.assertEqual(weights[0]["weight"], 1.0)
            self.assertEqual(weights[0]["weight_method"], "equal")
            self.assertEqual(weights[0]["preprocess"]["clip"], 1.5)
            root_manifest = json.loads(
                (Path(result["manifest_path"])).read_text(encoding="utf-8")
            )
            self.assertEqual(root_manifest["weight_method"], "equal")
            self.assertEqual(root_manifest["z_clip"], 1.5)
            self.assertEqual(root_manifest["requested_factor_ids"], ["f2"])
            self.assertEqual(root_manifest["default_size"], 1)
            self.assertEqual(root_manifest["sizes"][0]["screen"]["signal_date"], "2024-01-08")


if __name__ == "__main__":
    unittest.main()
