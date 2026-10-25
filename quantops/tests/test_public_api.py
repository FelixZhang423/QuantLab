"""公开接口与独立性测试：算子出口、目录接口、面板互转、访问器、注册表锁定。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import quantops as qo
from quantops.operators import OPERATORS
from quantops.registry import get_operator

PROJECT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_operators():
    snapshot = dict(OPERATORS)
    yield
    OPERATORS.clear()
    OPERATORS.update(snapshot)


@pytest.fixture()
def panel() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=12)
    codes = ["000001", "000002", "000003"]
    rows = []
    for idx, code in enumerate(codes):
        base = 10.0 + idx
        for step, date in enumerate(dates):
            close = base + step * 0.1 * (idx + 1)
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": close - 0.05,
                    "close": close,
                    "high": close + 0.1,
                    "low": close - 0.1,
                    "volume": 1_000.0 + step,
                    "amount": 10_000.0 + step,
                    "TurnoverRate": 0.01 * (idx + 1),
                    "ChangePCT": 0.5 * (idx + 1),
                    "industry": float(idx),
                    "ma20": base,
                    "if_up": 1.0,
                    "if_down": 0.0,
                    "if_flat": 0.0,
                    "Ifsuspend": 0.0,
                }
            )
    return pd.DataFrame(rows)


# ---------- 算子出口 ----------

def test_all_operators_are_flat_callable_exports():
    assert len(OPERATORS) == 80
    missing = [name for name in OPERATORS if not callable(getattr(qo, name, None))]
    assert missing == []


def test_list_operators_shape_is_unchanged():
    """老接口：3 个键、按 (category, name) 排序 —— 后端 /api/operators 直接吃这个形状。"""
    items = qo.list_operators()
    assert len(items) == 80
    assert all(set(item) == {"name", "category", "description"} for item in items)
    assert items == sorted(items, key=lambda item: (item["category"], item["name"]))


def test_catalog_and_describe_and_categories():
    catalog = qo.catalog()
    assert len(catalog) == 80
    assert set(catalog[0]) == {
        "name",
        "category",
        "category_cn",
        "canonical_name",
        "description_cn",
        "example",
        "generation_enabled",
        "manual_enabled",
    }
    entry = qo.describe("ts_mean")
    assert entry["category_cn"] == "时间序列"
    assert entry["example"] == "ts_mean(close, 20)"
    assert entry["generation_enabled"] is True
    with pytest.raises(KeyError):
        qo.describe("not_an_operator")

    categories = qo.categories()
    assert sum(item["count"] for item in categories) == 80
    assert {item["key"] for item in categories} == {
        "arithmetic",
        "cross_section",
        "group",
        "logic",
        "time_series",
        "transformational",
        "vector",
    }


def test_version_matches_pyproject():
    tomllib = pytest.importorskip("tomllib")
    with open(PROJECT_DIR / "pyproject.toml", "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    assert version == qo.__version__


def test_canonical_merge_keeps_literal_wins_semantics():
    """锁定 19/3 的合并口径：字面量优先，只有 sub/mul/div 采用 registry 定义文案。"""
    assert OPERATORS["max"].description == "Element-wise maximum across inputs."
    assert get_operator("max").description == "Element-wise maximum across two expressions."
    assert OPERATORS["div"].description == get_operator("div").description == "Element-wise division."
    assert OPERATORS["sub"].category == get_operator("sub").category == "arithmetic"


# ---------- 面板互转 ----------

def test_to_series_and_to_frame_round_trip(panel):
    series = qo.to_series(panel, "close")
    assert series.index.names == ["date", "code"]
    assert series.name == "close"
    frame = qo.to_frame(series)
    assert list(frame.columns) == ["date", "code", "alpha"]
    assert len(frame) == len(panel)

    with pytest.raises(qo.ExpressionError):
        qo.to_series(panel, "no_such_field")
    with pytest.raises(qo.ExpressionError):
        qo.to_frame(pd.Series([1.0, 2.0]))


def test_prepare_panel_normalizes_code_and_sorts(panel):
    messy = panel.copy()
    messy["code"] = messy["code"].astype(int)  # 1 而不是 "000001"
    prepared = qo.prepare_panel(messy)
    assert set(prepared.index.get_level_values("code")) == {"000001", "000002", "000003"}
    assert prepared.index.is_monotonic_increasing
    assert qo.available_fields(messy)[0]["name"] == "open"


def test_align_outer_and_inner(panel):
    close = qo.to_series(panel, "close")
    short = close.iloc[:10]
    outer, _ = qo.align(close, short, join="outer")
    inner, _ = qo.align(close, short, join="inner")
    assert len(outer) == len(close)
    assert len(inner) == 10


# ---------- pandas 访问器 ----------

def test_accessor_matches_function_call(panel):
    close = qo.to_series(panel, "close")
    via_accessor = close.qo.ts_mean(3)
    via_function = qo.ts_mean(close, 3)
    pd.testing.assert_series_equal(via_accessor, via_function)


def test_accessor_chain_and_apply_escape_hatch(panel):
    close = qo.to_series(panel, "close")
    chained = close.qo.delay(1).qo.rank()
    direct = qo.rank(qo.delay(close, 1))
    pd.testing.assert_series_equal(chained, direct)

    qo.register_operator("times_three_t", "custom", "x * 3", lambda x: x * 3)
    pd.testing.assert_series_equal(close.qo.apply("times_three_t"), close * 3)


def test_accessor_rejects_plain_series():
    with pytest.raises(qo.ExpressionError):
        pd.Series([1.0, 2.0]).qo.rank()


# ---------- 表达式 & 文档示例 ----------

def test_unsafe_expression_is_rejected(panel):
    with pytest.raises(qo.ExpressionError):
        qo.evaluate("__import__('os').system('echo bad')", panel)
    with pytest.raises(qo.ExpressionError):
        qo.evaluate("close.__class__", panel)


def test_every_documented_example_still_evaluates(panel):
    """docs 里的每个示例都必须能跑通——这里锁住唯一的例外（div 没有示例、回落 div(close)）。"""
    failures = {}
    for name in sorted(OPERATORS):
        expr = qo.OPERATOR_EXAMPLES.get(name, f"{name}(close)")
        try:
            out = qo.evaluate(expr, panel)
            assert list(out.columns) == ["date", "code", "alpha"]
        except Exception as exc:  # noqa: BLE001 - 记录失败原因即可
            failures[name] = f"{type(exc).__name__}: {exc}"
    assert sorted(failures) == ["div"], failures


def test_import_quantops_does_not_import_custom_bt():
    """库必须能独立使用：新进程里 import quantops 不应牵连任何 custom_bt 模块。"""
    code = (
        "import sys, quantops;"
        " leaked = sorted(m for m in sys.modules if m.startswith('custom_bt'));"
        " assert not leaked, leaked;"
        " print(quantops.__file__)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(PROJECT_DIR), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    resolved = Path(proc.stdout.strip())
    assert resolved.name == "__init__.py" and resolved.parent.name == "quantops"


def test_numpy_and_pandas_are_the_only_heavy_deps():
    """零新增依赖的守门测试：库源码里不应该出现其它第三方 import。"""
    allowed = {"numpy", "pandas", "quantops"}
    stdlib_or_allowed = allowed | {
        "__future__",
        "argparse",
        "ast",
        "dataclasses",
        "difflib",
        "importlib",
        "inspect",
        "json",
        "pathlib",
        "re",
        "statistics",
        "sys",
        "typing",
        "functools",
    }
    offenders = set()
    for path in (PROJECT_DIR / "quantops").glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                module = stripped.split()[1].split(".")[0]
            elif stripped.startswith("from ") and " import " in stripped:
                module = stripped.split()[1].split(".")[0]
            else:
                continue
            if module not in stdlib_or_allowed:
                offenders.add(f"{path.name}: {module}")
    assert not offenders, sorted(offenders)


def test_operators_are_deterministic(panel):
    """同一输入两次求值必须逐位相同（无隐藏状态）。"""
    first = qo.evaluate("rank(ts_mean(close, 3)) + trade_when(greater(volume, 0), close, less(volume, -1))", panel)
    second = qo.evaluate("rank(ts_mean(close, 3)) + trade_when(greater(volume, 0), close, less(volume, -1))", panel)
    pd.testing.assert_frame_equal(first, second)
    assert np.isfinite(first["alpha"].dropna()).all()
