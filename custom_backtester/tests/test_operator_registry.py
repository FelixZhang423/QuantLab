import unittest

from custom_bt.operator_registry import (
    get_operator,
    list_operator_definitions,
    load_alphagen_operator_classes,
)


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


if __name__ == "__main__":
    unittest.main()
