"""类式入口 `OperatorSet`：80 个算子当方法调、字段名解析、表达式求值、错误提示。

核心要求：类式调用与函数式调用**逐值相等**（底层是同一份实现），
以及「字符串参数只有恰好是字段名时才解析」这条规则别误伤
`bucket(x, "0,1,0.1")` / `ts_quantile(x, 20, "gaussian")` 这类字面量参数。
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

import quantops as qo
from quantops.opset import OperatorSet
from quantops.operators import OPERATORS


@pytest.fixture(autouse=True)
def _restore_operators():
    snapshot = dict(OPERATORS)
    yield
    OPERATORS.clear()
    OPERATORS.update(snapshot)


@pytest.fixture()
def panel() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=30)
    codes = ["000001", "000002", "000003", "000004"]
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
                    "industry": float(idx % 2),
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture()
def ops(panel) -> OperatorSet:
    return OperatorSet(panel)


# ---------- 出口与覆盖 ----------

def test_exported_from_top_level():
    assert qo.OperatorSet is OperatorSet
    assert "OperatorSet" in qo.__all__


def test_every_registered_operator_is_a_method():
    for name in OPERATORS:
        method = getattr(OperatorSet, name)
        assert callable(method), name
        assert method.__name__ == name


def test_method_docs_come_from_chinese_metadata():
    doc = OperatorSet.ts_mean.__doc__
    assert "按股票计算滚动均值" in doc
    assert "分类：时间序列" in doc
    assert "示例：ts_mean(close, 20)" in doc


def test_signature_matches_underlying_function_without_self():
    # 底层：lambda x, n: ...；类上: (self, x, n)；实例上（绑定后）: (x, n)
    assert list(inspect.signature(OperatorSet.ts_mean).parameters) == ["self", "x", "n"]
    assert list(inspect.signature(OperatorSet().ts_mean).parameters) == ["x", "n"]


# ---------- 与函数式逐值一致 ----------

def test_method_equals_function_with_field_names(ops, panel):
    close = qo.to_series(panel, "close")
    pd.testing.assert_series_equal(ops.ts_mean("close", 5), qo.ts_mean(close, 5))
    pd.testing.assert_series_equal(ops.rank("close"), qo.rank(close))


def test_method_without_panel_takes_series(panel):
    close = qo.to_series(panel, "close")
    ops = OperatorSet()
    pd.testing.assert_series_equal(ops.ts_mean(close, 5), qo.ts_mean(close, 5))


def test_nested_calls(ops, panel):
    close = qo.to_series(panel, "close")
    expected = qo.rank(qo.ts_mean(close, 10))
    pd.testing.assert_series_equal(ops.rank(ops.ts_mean("close", 10)), expected)


def test_varargs_operator(ops, panel):
    close = qo.to_series(panel, "close")
    open_ = qo.to_series(panel, "open")
    pd.testing.assert_series_equal(ops.max("close", "open"), qo.max(close, open_))
    pd.testing.assert_series_equal(ops.min("close", "open"), qo.min(close, open_))


def test_group_operator_resolves_all_three_fields(ops, panel):
    close = qo.to_series(panel, "close")
    volume = qo.to_series(panel, "volume")
    industry = qo.to_series(panel, "industry")
    expected = qo.group_mean(close, volume, industry)
    pd.testing.assert_series_equal(ops.group_mean("close", "volume", "industry"), expected)


# ---------- 字符串参数：只有字段名才解析 ----------

def test_bucket_range_string_is_not_treated_as_field(ops, panel):
    close = qo.to_series(panel, "close")
    pd.testing.assert_series_equal(
        ops.bucket("close", "0,1,0.1"), qo.bucket(close, "0,1,0.1")
    )


def test_ts_quantile_driver_string_survives(ops, panel):
    close = qo.to_series(panel, "close")
    pd.testing.assert_series_equal(
        ops.ts_quantile("close", 5, "uniform"), qo.ts_quantile(close, 5, "uniform")
    )
    # 关键字传参也一样
    pd.testing.assert_series_equal(
        ops.ts_quantile("close", 5, driver="uniform"),
        qo.ts_quantile(close, 5, driver="uniform"),
    )


# ---------- 字段访问 ----------

def test_field_attribute_and_dir(ops, panel):
    pd.testing.assert_series_equal(ops.close, qo.to_series(panel, "close"))
    assert "close" in ops.fields
    assert "close" in dir(ops)


def test_unknown_attribute_gets_readable_error(ops):
    with pytest.raises(AttributeError) as excinfo:
        ops.ts_meen
    message = str(excinfo.value)
    assert "不是算子名" in message
    assert "ts_mean" in message  # 顺带给相近算子提示


def test_unknown_field_gets_readable_error(ops):
    with pytest.raises(qo.ExpressionError) as excinfo:
        ops.field("nope")
    assert "可用字段" in str(excinfo.value)


def test_field_without_panel_raises():
    with pytest.raises(qo.ExpressionError):
        OperatorSet().field("close")


# ---------- 表达式 / apply / 元数据 ----------

def test_eval_equals_module_evaluate(ops, panel):
    expression = "rank(ts_mean(close, 5))"
    pd.testing.assert_frame_equal(ops.eval(expression), qo.evaluate(expression, panel))


def test_eval_requires_panel():
    with pytest.raises(qo.ExpressionError):
        OperatorSet().eval("rank(close)")


def test_apply_and_getitem(ops, panel):
    close = qo.to_series(panel, "close")
    expected = qo.ts_mean(close, 5)
    pd.testing.assert_series_equal(ops.apply("ts_mean", "close", 5), expected)
    pd.testing.assert_series_equal(ops["ts_mean"]("close", 5), expected)


def test_unknown_operator_errors(ops):
    with pytest.raises(qo.ExpressionError):
        ops.apply("not_an_operator")
    with pytest.raises(KeyError):
        ops["not_an_operator"]


def test_registered_operator_is_usable_via_class(ops, panel):
    qo.register_operator("triple_test", "arithmetic", "test only", lambda x: x * 3)
    close = qo.to_series(panel, "close")

    pd.testing.assert_series_equal(ops.triple_test("close"), close * 3)
    pd.testing.assert_series_equal(ops.apply("triple_test", "close"), close * 3)


def test_to_frame(ops):
    frame = ops.to_frame(ops.rank("close"))
    assert list(frame.columns) == ["date", "code", "alpha"]


def test_metadata_helpers(ops):
    item = ops.describe("ts_mean")
    assert item["name"] == "ts_mean"
    assert item["category"] == "time_series"
    assert sum(c["count"] for c in ops.categories()) == len(OPERATORS)
    assert len(ops.list_operators()) == len(OPERATORS)


def test_repr_and_names(ops):
    assert "80 operators" in repr(ops)
    assert "7 fields" in repr(ops)  # open/close/high/low/volume/amount/industry
    assert "no panel" in repr(OperatorSet())
    assert len(ops.names) == len(OPERATORS)
