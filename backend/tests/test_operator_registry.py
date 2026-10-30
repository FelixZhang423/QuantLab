import unittest

from custom_bt.docs import enrich_operators
from custom_bt.expressions import list_operators
from custom_bt.operator_registry import (
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

    def test_generation_flags_match_registry_definitions(self):
        enriched = enrich_operators(list_operators())
        generation = {item["name"] for item in enriched if item["generation_enabled"]}
        # 别名（add/divide/...）也标记为可生成，按 canonical 名与注册表对齐
        self.assertEqual({canonical_name(name) for name in generation}, set(generation_operator_names()))
        self.assertTrue(all(item["manual_enabled"] for item in enriched))


if __name__ == "__main__":
    unittest.main()
