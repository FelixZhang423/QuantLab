import tempfile
import unittest
from pathlib import Path

import pandas as pd

from custom_bt.docs import enrich_fields, enrich_operators, parse_field_markdown
from custom_bt.expressions import evaluate_expression, list_operators


class DocsTests(unittest.TestCase):
    def test_parse_field_markdown_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fields.md"
            path.write_text(
                """
## 来源：`daily`
| 字段 | 解释 |
|------|------|
| `timestamps` | 时间戳 |
| `vol` | 成交量 |
| `close` | 收盘价 |
""",
                encoding="utf-8",
            )

            docs = parse_field_markdown(path)
            enriched = enrich_fields(
                [{"name": "date", "dtype": "datetime64[ns]"}, {"name": "volume", "dtype": "float64"}],
                path,
            )

            self.assertEqual(docs["close"]["description"], "收盘价")
            self.assertEqual(enriched[0]["description"], "时间戳")
            self.assertEqual(enriched[1]["description"], "成交量")

    def test_all_registered_operators_have_chinese_descriptions(self):
        enriched = enrich_operators(list_operators())

        self.assertEqual(len(enriched), len(list_operators()))
        self.assertTrue(all(item["description_cn"] for item in enriched))
        ts_rank = next(item for item in enriched if item["name"] == "ts_rank")
        self.assertNotEqual(ts_rank["description_cn"], "Rolling percentile rank of current value per stock.")

    def test_all_registered_operators_have_examples(self):
        enriched = enrich_operators(list_operators())

        self.assertTrue(all(item["example"] for item in enriched))
        examples = {item["name"]: item["example"] for item in enriched}
        self.assertEqual(examples["rank"], "rank(close)")
        self.assertEqual(examples["delay"], "delay(close, 5)")
        self.assertEqual(examples["group_neutralize"], "group_neutralize(rank(close), industry)")

    def test_shared_operator_rows_expose_canonical_support_metadata(self):
        enriched = enrich_operators(list_operators())
        max_item = next(item for item in enriched if item["name"] == "max")

        self.assertEqual(max_item["canonical_name"], "max")
        self.assertTrue(max_item["generation_enabled"])
        self.assertTrue(max_item["manual_enabled"])

    def test_operator_examples_are_valid_expressions(self):
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03", "2024-01-04", "2024-01-04", "2024-01-05", "2024-01-05"]),
                "code": ["000001", "000002"] * 5,
                "open": [10, 20, 11, 19, 12, 18, 13, 17, 14, 16],
                "close": [11, 19, 12, 18, 13, 17, 14, 16, 15, 15],
                "volume": [100, 200, 120, 180, 130, 170, 140, 160, 150, 150],
                "amount": [1100, 3800, 1440, 3240, 1690, 2890, 1960, 2560, 2250, 2250],
                "TurnoverRate": [0.01, 0.06, 0.02, 0.05, 0.03, 0.04, 0.04, 0.03, 0.05, 0.02],
                "industry": [1, 2] * 5,
                "ma20": [10, 20, 10, 20, 10, 20, 10, 20, 10, 20],
                "if_flat": [0, 1] * 5,
                "if_up": [0, 1, 0, 0, 1, 0, 0, 0, 0, 0],
                "if_down": [0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
                "Ifsuspend": [0] * 10,
                "ChangePCT": [0.01, -0.02, 0.02, -0.01, 0.01, -0.02, 0.03, -0.01, 0.01, 0.0],
            }
        )

        for item in enrich_operators(list_operators()):
            with self.subTest(operator=item["name"]):
                out = evaluate_expression(item["example"], panel)
                self.assertEqual(set(out.columns), {"date", "code", "alpha"})


if __name__ == "__main__":
    unittest.main()
