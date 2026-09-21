import unittest

import pandas as pd

from custom_bt.canonical_expression import (
    canonicalize_alphagen,
    normalize_expression,
    serialize_alphagen_expression,
)
from custom_bt.operator_registry import load_alphagen_operator_classes
from custom_bt.expressions import evaluate_expression


def make_small_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]),
            "code": ["000001", "000002", "000001", "000002"],
            "close": [10.0, 20.0, 11.0, 18.0],
            "open": [11.0, 19.0, 10.0, 17.0],
        }
    )


class CanonicalExpressionTests(unittest.TestCase):
    def test_alphagen_names_serialize_to_user_friendly_names(self):
        self.assertEqual(canonicalize_alphagen("Greater($close,$open)"), "max(close,open)")
        self.assertEqual(canonicalize_alphagen("Less($close,$open)"), "min(close,open)")
        self.assertEqual(canonicalize_alphagen("Ref($close,20d)"), "delay(close,20)")
        self.assertEqual(canonicalize_alphagen("Mean($close,20d)"), "ts_mean(close,20)")

    def test_canonical_max_and_time_series_max_are_distinct(self):
        self.assertEqual(canonicalize_alphagen("Greater($close,$open)"), "max(close,open)")
        self.assertEqual(canonicalize_alphagen("Max($close,20d)"), "ts_max(close,20)")

    def test_normalize_expression_preserves_manual_only_operator_names(self):
        self.assertEqual(normalize_expression("subtract(close,open)"), "sub(close,open)")
        self.assertEqual(normalize_expression("rank(close)"), "rank(close)")

    def test_normalize_expression_rewrites_nested_legacy_aliases_in_composites(self):
        expression = "(0.5)*(divide(close,open)) + (0.5)*(Greater(close,open))"
        normalized = normalize_expression(expression)
        self.assertIn("div(close,open)", normalized)
        self.assertIn("max(close,open)", normalized)
        self.assertNotIn("divide(", normalized)
        self.assertNotIn("Greater(", normalized)

    def test_local_evaluator_accepts_canonical_expression(self):
        result = evaluate_expression("max(close,open)", make_small_panel())
        self.assertTrue(result["alpha"].notna().any())

    def test_local_evaluator_accepts_all_canonical_arithmetic_names(self):
        panel = make_small_panel()
        for expression in ("add(close,open)", "sub(close,open)", "mul(close,open)", "div(close,open)"):
            with self.subTest(expression=expression):
                result = evaluate_expression(expression, panel)
                self.assertEqual(len(result), len(panel))

    def test_vendor_ast_serializes_to_canonical_expression(self):
        load_alphagen_operator_classes()
        from single_factor.expression import NamedFeature
        from single_factor._vendor.alphagen.data.expression import Greater, Mean

        expression = Mean(Greater(NamedFeature("close"), NamedFeature("open")), 20)
        self.assertEqual(
            serialize_alphagen_expression(expression),
            "ts_mean(max(close,open),20)",
        )


if __name__ == "__main__":
    unittest.main()
