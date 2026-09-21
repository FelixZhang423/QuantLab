import ast
import tempfile
import unittest
from pathlib import Path


class StreamlitAppTests(unittest.TestCase):
    def _load_streamlit_app_module(self):
        import importlib.util
        import sys
        import types

        class FakeStreamlit(types.ModuleType):
            def __init__(self, name):
                super().__init__(name)
                self.sidebar = self
                self.session_state = {}
                self.column_config = self

            def __getattr__(self, name):
                def _noop(*args, **kwargs):
                    class _Context:
                        def __enter__(self):
                            return self

                        def __exit__(self, exc_type, exc, tb):
                            return False

                    if name == "text_input":
                        return args[1] if len(args) > 1 else ""
                    if name == "cache_data":
                        def _decorator(func):
                            return func

                        return _decorator
                    if name == "number_input":
                        return kwargs.get("value", args[1] if len(args) > 1 else 0)
                    if name == "text_area":
                        return args[1] if len(args) > 1 else ""
                    if name == "button":
                        return False
                    if name == "selectbox":
                        options = args[1] if len(args) > 1 else []
                        return options[0] if options else None
                    if name == "tabs":
                        labels = args[0] if args else []
                        return [_Context() for _ in labels]
                    if name == "expander":
                        return _Context()
                    if name == "columns":
                        count = args[0] if args else 1
                        return [self for _ in range(int(count))]
                    if name in {"TextColumn", "NumberColumn"}:
                        return None
                    return None

                return _noop

        original_streamlit = sys.modules.get("streamlit")
        sys.modules["streamlit"] = FakeStreamlit("streamlit")
        try:
            spec = importlib.util.spec_from_file_location("streamlit_app_for_test", "app/streamlit_app.py")
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
        finally:
            if original_streamlit is None:
                sys.modules.pop("streamlit", None)
            else:
                sys.modules["streamlit"] = original_streamlit

    def test_download_buttons_use_explicit_keys(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "download_button"
        ]

        self.assertGreater(len(calls), 0)
        for call in calls:
            self.assertIn("key", {keyword.arg for keyword in call.keywords})

    def test_text_areas_use_explicit_keys(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "text_area"
        ]

        self.assertGreater(len(calls), 0)
        for call in calls:
            self.assertIn("key", {keyword.arg for keyword in call.keywords})

    def test_dataframes_do_not_use_string_width_for_older_streamlit(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"dataframe", "data_editor"}
        ]

        self.assertGreater(len(calls), 0)
        for call in calls:
            for keyword in call.keywords:
                self.assertFalse(
                    keyword.arg == "width"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str),
                    "Streamlit in the alphagen env expects dataframe width to be an int; use use_container_width=True",
                )

    def test_saved_runs_table_contains_expression_and_core_metrics(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            module._save_note(tmp, "这是一个备注")
            table = module._saved_runs_table(
                [
                    {
                        "run_name": "demo",
                        "created_at": "2026-07-03T08:45:09",
                        "path": tmp,
                        "config": {
                            "alphas": [{"expr": "rank(close)"}],
                            "backtest": {"start_date": "2025-01-01", "end_date": "2025-12-31", "top_k": 50},
                        },
                        "summary": {
                            "sharpe": 1.2,
                            "average_turnover": 0.34,
                            "max_drawdown": -0.12,
                            "annual_return": 0.56,
                            "total_return": 0.78,
                        },
                    }
                ]
            )

        self.assertEqual(table.loc[0, "表达式"], "rank(close)")
        self.assertEqual(table.loc[0, "夏普比"], 1.2)
        self.assertAlmostEqual(table.loc[0, "换手率"], 34.0)
        self.assertAlmostEqual(table.loc[0, "最大回撤"], -12.0)
        self.assertAlmostEqual(table.loc[0, "年化收益"], 56.0)
        self.assertAlmostEqual(table.loc[0, "总收益"], 78.0)
        self.assertEqual(table.loc[0, "备注"], "这是一个备注")

    def test_saved_runs_table_exposes_canonical_expression_and_ppo_metrics(self):
        module = self._load_streamlit_app_module()
        table = module._saved_runs_table(
            [
                {
                    "run_name": "factor_0001",
                    "canonical_expression": "ts_mean(close,20)",
                    "generation_metrics": {
                        "ic": 0.04,
                        "rank_ic": 0.05,
                        "icir": 0.3,
                        "coverage": 0.9,
                        "score": 0.2,
                    },
                    "summary": {"sharpe": 1.0},
                }
            ]
        )

        self.assertEqual(table.loc[0, "canonical_expression"], "ts_mean(close,20)")
        self.assertAlmostEqual(table.loc[0, "PPO IC"], 0.04)
        self.assertAlmostEqual(table.loc[0, "PPO Rank IC"], 0.05)

    def test_saved_runs_table_reads_legacy_generation_metrics_on_python38(self):
        class Python38String(str):
            def __getattribute__(self, name):
                if name == "removeprefix":
                    raise AttributeError("'str' object has no attribute 'removeprefix'")
                return super().__getattribute__(name)

        module = self._load_streamlit_app_module()
        try:
            table = module._saved_runs_table(
                [
                    {
                        Python38String("generation_ic"): 0.04,
                        Python38String("generation_rank_ic"): 0.05,
                        Python38String("generation_score"): 0.2,
                        "summary": {"sharpe": 1.0},
                    }
                ]
            )
        except AttributeError as exc:
            self.fail(f"_saved_runs_table should support Python 3.8 strings: {exc}")

        self.assertAlmostEqual(table.loc[0, "PPO IC"], 0.04)
        self.assertAlmostEqual(table.loc[0, "PPO Rank IC"], 0.05)
        self.assertAlmostEqual(table.loc[0, "PPO Score"], 0.2)

    def test_saved_runs_table_keeps_topk_arrow_compatible(self):
        module = self._load_streamlit_app_module()
        table = module._saved_runs_table(
            [
                {
                    "run_name": "manual",
                    "config": {"backtest": {"top_k": 50}},
                    "summary": {"sharpe": 1.0},
                },
                {
                    "run_name": "factor_without_backtest_config",
                    "config": {},
                    "summary": {"sharpe": 0.5},
                },
            ]
        )

        self.assertEqual(table["TopK"].tolist(), ["50", ""])
        self.assertEqual(str(table["TopK"].dtype), "object")
        __import__("pyarrow").Table.from_pandas(table[["TopK"]])

    def test_saved_runs_table_is_arrow_compatible_with_mixed_result_types(self):
        module = self._load_streamlit_app_module()
        table = module._saved_runs_table(
            [
                {
                    "run_name": "manual",
                    "result_type": "manual",
                    "config": {"backtest": {"top_k": 50}},
                    "summary": {"sharpe": 1.0},
                },
                {
                    "run_name": "composite",
                    "result_type": "composite",
                    "max_factors": 10,
                    "selection_metric": "rank_ic",
                    "mutual_ic_threshold": 0.99,
                    "weight_method": "alphagen_l1",
                    "factor_preprocess": {"method": "daily_zscore"},
                    "composition_metrics": {"ic": 0.03, "rank_ic": 0.04},
                    "summary": {"sharpe": 0.5},
                },
            ]
        )

        self.assertEqual(table["组合规模"].tolist(), ["", "10"])
        self.assertEqual(table["mutual IC 阈值"].tolist(), ["", "0.99"])
        __import__("pyarrow").Table.from_pandas(table)

    def test_factor_result_discovery_uses_nested_saved_result_center(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "saved_backtests"
            run_dir = root / "factor" / "liquid_500" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_backtest_summary.csv").write_text(
                "factor_id,canonical_expression\nfactor_0001,close\n",
                encoding="utf-8",
            )

            result_dirs = module._list_factor_backtest_result_dirs(root)

        self.assertEqual(result_dirs, [run_dir])

    def test_result_detail_reads_saved_manifest_metrics(self):
        module = self._load_streamlit_app_module()
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("generation_metrics", source)
        self.assertIn("canonical_expression", source)

    def test_result_detail_exposes_composite_weight_method_and_preprocess(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("weight_method", source)
        self.assertIn("factor_preprocess", source)

    def test_result_detail_renders_manifest_and_summary_together(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "manifest.json").write_text(
                '{"result_type":"factor","canonical_expression":"ts_mean(close,20)","generation_metrics":{"ic":0.04}}',
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text('{"sharpe":1.2}', encoding="utf-8")

            module._render_result_dir(run_dir, "unit")

    def test_summary_frame_displays_rates_as_percentages(self):
        module = self._load_streamlit_app_module()
        frame = module._summary_frame(
            {
                "annual_return": 0.1234,
                "max_drawdown": -0.0567,
                "average_turnover": 0.8,
                "sharpe": 1.23456,
                "calmar": 2.5,
            }
        )
        values = dict(zip(frame["指标"], frame["值"]))

        self.assertEqual(values["年化收益"], "12.34%")
        self.assertEqual(values["最大回撤"], "-5.67%")
        self.assertEqual(values["平均换手"], "80.00%")
        self.assertEqual(values["夏普比率"], "1.2346")
        self.assertEqual(values["Calmar"], "2.5000")

    def test_operator_table_includes_examples(self):
        module = self._load_streamlit_app_module()
        table = module._format_operators()

        self.assertIn("示例", table.columns)
        rank = table[table["操作符"] == "rank"].iloc[0]
        self.assertEqual(rank["示例"], "rank(close)")

    def test_stock_table_uses_chinese_columns(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            pd = __import__("pandas")
            pd.DataFrame(
                [
                    {
                        "code": "000001",
                        "rows": 1,
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-01",
                        "latest_date": "2024-01-01",
                        "latest_open": 10.0,
                        "latest_close": 11.0,
                        "latest_volume": 1000.0,
                        "latest_amount": 11000.0,
                    }
                ]
            ).to_csv(Path(tmp) / "stock_list.csv", index=False, encoding="utf-8-sig")

            table = module._load_stock_table_cached(tmp, 1.0)

        self.assertIn("股票代码", table.columns)
        self.assertIn("最近收盘价", table.columns)
        self.assertEqual(table.loc[0, "股票代码"], "000001")

    def test_summary_cards_expose_label_and_value(self):
        module = self._load_streamlit_app_module()
        cards = module._summary_cards({"annual_return": 0.1234, "calmar": 2.5})

        self.assertEqual(cards[0], {"label": "年化收益", "value": "12.34%"})
        self.assertEqual(cards[1], {"label": "Calmar", "value": "2.5000"})

    def test_run_notes_round_trip(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(module._load_note(tmp), "")
            module._save_note(tmp, "观察一下这个因子")

            self.assertEqual(module._load_note(tmp), "观察一下这个因子")
            self.assertEqual(module._note_preview("  观察一下\n这个因子  "), "观察一下 这个因子")


    def test_platform_tables_load_pool_and_factor_run_manifests(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool_dir = root / "pools" / "liquid_500_abc12345"
            pool_dir.mkdir(parents=True)
            (pool_dir / "manifest.json").write_text(
                '{"pool_id":"liquid_500_abc12345","name":"liquid_500","n_stocks":500}',
                encoding="utf-8",
            )
            run_dir = root / "factor_runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "factor_run.json").write_text(
                '{"run_id":"run_a","pool_id":"liquid_500_abc12345","accepted_count":3}',
                encoding="utf-8",
            )

            pools = module._load_pool_manifests(root / "pools")
            runs = module._load_factor_run_manifests(root / "factor_runs")

        self.assertEqual(pools.loc[0, "pool_id"], "liquid_500_abc12345")
        self.assertEqual(int(pools.loc[0, "n_stocks"]), 500)
        self.assertEqual(runs.loc[0, "run_id"], "run_a")
        self.assertEqual(int(runs.loc[0, "accepted_count"]), 3)

    def test_latest_active_job_dir_prefers_running_job(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            finished = root / "20260811_000000_done"
            finished.mkdir(parents=True)
            (finished / "status.json").write_text('{"status":"finished"}', encoding="utf-8")
            running = root / "20260811_010000_run"
            running.mkdir(parents=True)
            (running / "status.json").write_text('{"status":"running"}', encoding="utf-8")

            active = module._latest_active_job_dir(root)

        self.assertEqual(active, running)

    def test_factor_generation_progress_uses_run_state(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "jobs" / "20260811_123000_abcd1234"
            job_dir.mkdir(parents=True)
            payload = {
                "pool_id": "liquid_500_864dc25f",
                "factor_runs_root": str(root / "factor_runs"),
                "fields": ["close", "volume", "amount"],
                "splits": {
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-05"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-06"},
                },
                "max_backtrack_days": 100,
                "target_horizon": 20,
                "max_future_days": 20,
                "generation_config": {"target_factor_count": 100},
            }
            (job_dir / "platform_job.json").write_text(
                __import__("json").dumps({"operation": "generate_factors", "payload": payload}),
                encoding="utf-8",
            )
            progress_dir = module._factor_generation_run_dir(job_dir)
            assert progress_dir is not None
            progress_dir.mkdir(parents=True)
            (progress_dir / "run_state.json").write_text(
                '{"attempts": 12, "accepted_count": 7, "target_count": 100, "max_attempts": 100000}',
                encoding="utf-8",
            )

            progress = module._load_factor_generation_progress(job_dir)

        self.assertEqual(progress["attempts"], 12)
        self.assertEqual(progress["accepted_count"], 7)
        self.assertEqual(progress["target_count"], 100)

    def test_factor_generation_progress_prefers_explicit_run_id(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "jobs" / "20260812_100000_abcd1234"
            job_dir.mkdir(parents=True)
            payload = {
                "pool_id": "liquid_500_864dc25f",
                "factor_runs_root": str(root / "factor_runs"),
                "fields": ["close", "volume", "amount"],
                "splits": {
                    "train": {"cache_start": "2024-01-01", "cache_end": "2024-01-05"},
                    "valid": {"cache_start": "2024-01-02", "cache_end": "2024-01-06"},
                },
                "max_backtrack_days": 100,
                "target_horizon": 20,
                "max_future_days": 20,
                "generation_config": {
                    "run_id": "liquid_500_864dc25f_730ff0fa73_20260812_100000_fresh",
                    "target_factor_count": 100,
                },
            }
            (job_dir / "platform_job.json").write_text(
                __import__("json").dumps({"operation": "generate_factors", "payload": payload}),
                encoding="utf-8",
            )

            progress_dir = module._factor_generation_run_dir(job_dir)

        assert progress_dir is not None
        self.assertEqual(progress_dir.name, "liquid_500_864dc25f_730ff0fa73_20260812_100000_fresh")
        self.assertEqual(progress_dir.parent.name, "factor_runs")

    def test_factor_generation_progress_labels_are_readable(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        for text in ["已读取行数", "已保留行数", "已处理股票数", "合格因子", "目标数", "尝试次数", "最新检查点"]:
            self.assertIn(text, source)
        for broken in ["宸茶鍙栬鏁?", "宸蹭繚鐣欒鏁?", "宸插鐞嗚偂绁ㄦ暟", "鍚堟牸鍥犲瓙", "鐩爣鏁?", "灏濊瘯娆℃暟"]:
            self.assertNotIn(broken, source)

    def test_parse_multiline_values_removes_blanks_and_duplicates(self):
        module = self._load_streamlit_app_module()

        values = module._parse_multiline_values("close, open\nclose\n\namount")

        self.assertEqual(values, ["close", "open", "amount"])

    def test_master_store_ready_requires_metadata_and_stock_directory(self):
        module = self._load_streamlit_app_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(module._master_store_ready(root))
            (root / "meta.json").write_text("{}", encoding="utf-8")
            self.assertFalse(module._master_store_ready(root))
            (root / "stocks").mkdir()
            self.assertTrue(module._master_store_ready(root))

    def test_job_status_has_no_automatic_sleep_refresh(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        render_job_status = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_job_status"
        )
        called_names = {
            node.func.attr
            for node in ast.walk(render_job_status)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertNotIn("sleep", called_names)

    def test_default_saved_results_path_is_canonical_result_center(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("outputs/saved_backtests"), 2)

    def test_manual_backtest_exposes_pool_selector_and_passes_selection(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        selectbox_labels = []
        create_backtest_keywords = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "selectbox"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                selectbox_labels.append(str(node.args[0].value))
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "create_backtest_job":
                create_backtest_keywords.append({keyword.arg for keyword in node.keywords})

        self.assertIn("手动回测股票池", selectbox_labels)
        self.assertTrue(
            any({"pool_id", "pools_root"} <= keywords for keywords in create_backtest_keywords)
        )

    def test_factor_composition_tab_exposes_platform_operation(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn("因子组合", source)
        self.assertIn('"compose_factors"', source)
        self.assertIn("mutual IC 阈值", source)
        self.assertIn("组合规模扫描", source)
        self.assertIn("启动因子组合", source)

    def test_factor_composition_tab_exposes_marginal_contribution_controls(self):
        source = Path("app/streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn("target_horizon", source)
        self.assertIn("min_marginal_ic_improvement", source)
        self.assertIn("min_marginal_rank_ic_improvement", source)
        self.assertIn("min_marginal_icir_improvement", source)
        self.assertIn("composition_metrics", source)
        self.assertIn("组合 IC", source)


if __name__ == "__main__":
    unittest.main()
