"""quantops 与 custom_bt/docs.py 的中文元数据一致性。

docs.py 的 CATEGORY_CN / OPERATOR_CN_DESCRIPTIONS / OPERATOR_EXAMPLES 被
tests/test_docs.py 锁住、不能改，quantops/metadata.py 里存的是副本。
断言方向：docs.py 的每个键值都必须**原样**存在于 quantops —— docs 是 /api/operators
的唯一生产者，它不能漂；反过来 quantops 允许将来补充（例如给 8 个缺中文的算子补说明）。
"""
import unittest

from custom_bt import _quantops_boot  # noqa: F401  （未安装 quantops 时补 sys.path）
from custom_bt import docs
from custom_bt.docs import enrich_operators
from custom_bt.expressions import list_operators
from quantops import metadata


class MetadataParityTests(unittest.TestCase):
    def test_category_cn_is_identical(self):
        self.assertEqual(docs.CATEGORY_CN, metadata.CATEGORY_CN)

    def test_operator_cn_descriptions_cover_docs_verbatim(self):
        for name, text in docs.OPERATOR_CN_DESCRIPTIONS.items():
            self.assertIn(name, metadata.OPERATOR_CN_DESCRIPTIONS, name)
            self.assertEqual(metadata.OPERATOR_CN_DESCRIPTIONS[name], text, name)

    def test_operator_examples_cover_docs_verbatim(self):
        for name, example in docs.OPERATOR_EXAMPLES.items():
            self.assertIn(name, metadata.OPERATOR_EXAMPLES, name)
            self.assertEqual(metadata.OPERATOR_EXAMPLES[name], example, name)

    def test_catalog_reproduces_the_api_payload(self):
        """/api/operators 的每一行都要能用 quantops.catalog() 原样复现。"""
        self.assertEqual(enrich_operators(list_operators()), metadata.catalog())


if __name__ == "__main__":
    unittest.main()
