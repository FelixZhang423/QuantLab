"""quantops 未安装时 `custom_bt/_quantops_boot.py` 的 sys.path 兜底。

本机装了库的情况下这个分支平时走不到，所以用 mock 把 `find_spec` 打成「找不到」，
再断言补进 sys.path 的是**库的项目目录**（不是仓库根 —— 仓库根下同名目录会被当成
namespace 包，见模块 docstring）。
"""
import importlib.machinery
import sys
import unittest
from pathlib import Path
from unittest import mock

from custom_bt import _quantops_boot

PROJECT_DIR = Path(_quantops_boot.__file__).resolve().parents[2] / "quantops"


class QuantOpsBootTests(unittest.TestCase):
    def setUp(self):
        self._path_snapshot = list(sys.path)

    def tearDown(self):
        sys.path[:] = self._path_snapshot

    def test_does_nothing_when_quantops_is_importable(self):
        installed = mock.Mock(origin=str(PROJECT_DIR / "quantops" / "__init__.py"))
        with mock.patch.object(
            _quantops_boot.importlib.util, "find_spec", return_value=installed
        ):
            with mock.patch.object(_quantops_boot, "Path") as fake_path:
                self.assertFalse(_quantops_boot.ensure_quantops_on_path())
        fake_path.assert_not_called()  # 已装就别碰 sys.path
        self.assertEqual(sys.path, self._path_snapshot)

    def test_namespace_package_without_origin_still_counts_as_missing(self):
        """仓库根下那个同名目录解析出来 origin 是 None —— 必须继续走兜底。"""
        namespace = mock.Mock(origin=None)
        with mock.patch.object(
            _quantops_boot.importlib.util, "find_spec", return_value=namespace
        ):
            self.assertTrue(_quantops_boot.ensure_quantops_on_path())
        self.assertEqual(sys.path[0], str(PROJECT_DIR))

    def test_adds_project_dir_to_sys_path(self):
        with mock.patch.object(_quantops_boot.importlib.util, "find_spec", return_value=None):
            self.assertTrue(_quantops_boot.ensure_quantops_on_path())

        self.assertEqual(sys.path[0], str(PROJECT_DIR))
        # 项目目录下确实是一个正规包（有 __init__.py），不是 namespace 片段
        spec = importlib.machinery.PathFinder.find_spec("quantops", [str(PROJECT_DIR)])
        self.assertIsNotNone(spec)
        self.assertEqual(Path(spec.origin).parent, PROJECT_DIR / "quantops")

    def test_is_idempotent(self):
        with mock.patch.object(_quantops_boot.importlib.util, "find_spec", return_value=None):
            _quantops_boot.ensure_quantops_on_path()
            _quantops_boot.ensure_quantops_on_path()
        self.assertEqual(sys.path.count(str(PROJECT_DIR)), 1)

    def test_missing_library_raises_with_install_hint(self):
        with mock.patch.object(_quantops_boot.importlib.util, "find_spec", return_value=None):
            with mock.patch.object(_quantops_boot.Path, "is_file", return_value=False):
                with self.assertRaises(ImportError) as ctx:
                    _quantops_boot.ensure_quantops_on_path()
        self.assertIn("pip install -e", str(ctx.exception))
        self.assertEqual(sys.path, self._path_snapshot)


if __name__ == "__main__":
    unittest.main()
