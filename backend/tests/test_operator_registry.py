import unittest

from custom_bt.docs import enrich_operators
from adapters.expressions import list_operators
from adapters.operator_registry import (
    canonical_name,
    get_operator,
    list_operator_definitions,
    load_alphagen_operator_classes,
)
from quantops.registry import generation_operator_names


class OperatorRegistryTests(unittest.TestCase):
    def test_canonical_definitions_include_shared_core_operators(self):
        names = {item.canonical_name for item in list_operator_definitions()}
        self.assertTrue(
            {"abs", "max", "min", "delay", "ts_mean", "ts_max", "ts_corr"} <= names
        )

    def test_greater_and_max_have_different_canonical_semantics(self):
        self.assertEqual(get_operator("max").alphagen_name, "Greater")
        self.assertEqual(get_operator("ts_max").alphagen_name, "Max")
        self.assertNotEqual(get_operator("max").category, get_operator("ts_max").category)

    def test_alphagen_operator_loader_returns_only_generation_enabled_classes(self):
        classes = load_alphagen_operator_classes()
        names = {item.__name__ for item in classes}
        self.assertTrue({"Abs", "Greater", "Less", "Ref", "Mean", "Max", "Corr"} <= names)
        self.assertTrue(
            {
                "Sign", "CSRank", "Pow", "Skew", "Kurt", "Rank",
                "Inverse", "Reverse", "Sqrt", "SignedPower",
                "ZScore", "Scale", "Winsorize", "Normalize", "Quantile",
                "DaysFromLastChange", "Hump",
                "TSArgMax", "TSArgMin", "TSAvDiff", "TSBackfill",
                "TSCountNans", "TSDecayLinear", "TSQuantile",
                "TSScale", "TSZScore", "KthElement", "LastDiffValue",
                "TSRegression",
                "And", "Or", "Not", "Equal", "NotEqual",
                "GreaterThan", "GreaterEqual", "LessThan", "LessEqual",
                "IsNan", "IfElse",
            } <= names
        )
        self.assertEqual(len(classes), 62)
        self.assertNotIn("TSProduct", names)
        self.assertNotIn("TSStep", names)

    def test_new_alphagen_classes_map_to_local_implementations(self):
        expected = {
            "Sign": "sign",
            "CSRank": "rank",
            "Pow": "power",
            "Skew": "ts_skew",
            "Kurt": "ts_kurt",
            "Rank": "ts_rank",
            "Inverse": "inverse",
            "Reverse": "reverse",
            "Sqrt": "sqrt",
            "SignedPower": "signed_power",
            "ZScore": "zscore",
            "Scale": "scale",
            "Winsorize": "winsorize",
            "Normalize": "normalize",
            "Quantile": "quantile",
            "DaysFromLastChange": "days_from_last_change",
            "Hump": "hump",
            "TSStep": "ts_step",
            "TSArgMax": "ts_arg_max",
            "TSArgMin": "ts_arg_min",
            "TSAvDiff": "ts_av_diff",
            "TSBackfill": "ts_backfill",
            "TSCountNans": "ts_count_nans",
            "TSDecayLinear": "ts_decay_linear",
            "TSProduct": "ts_product",
            "TSQuantile": "ts_quantile",
            "TSScale": "ts_scale",
            "TSZScore": "ts_zscore",
            "KthElement": "kth_element",
            "LastDiffValue": "last_diff_value",
            "TSRegression": "ts_regression",
            "And": "and_",
            "Or": "or_",
            "Not": "not_",
            "Equal": "equal",
            "NotEqual": "not_equal",
            "GreaterThan": "greater",
            "GreaterEqual": "greater_equal",
            "LessThan": "less",
            "LessEqual": "less_equal",
            "IsNan": "is_nan",
            "IfElse": "if_else",
        }
        for alphagen_name, local_impl in expected.items():
            with self.subTest(alphagen_name=alphagen_name):
                definition = get_operator(alphagen_name)
                self.assertEqual(definition.local_impl, local_impl)

    def test_generation_flags_match_registry_definitions(self):
        enriched = enrich_operators(list_operators())
        generation = {item["name"] for item in enriched if item["generation_enabled"]}
        # 别名（add/divide/...）也标记为可生成，按 canonical 名与注册表对齐
        self.assertEqual({canonical_name(name) for name in generation}, set(generation_operator_names()))
        self.assertTrue(all(item["manual_enabled"] for item in enriched))


if __name__ == "__main__":
    unittest.main()
