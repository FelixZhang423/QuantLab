"""算子语义测试：用可读数值锁定各类算子的计算逻辑。

金标准测试（test_golden_values.py）锁的是哈希；这里补一组显式期望值，
方便判断某个算子“算得对不对”，而不是只知道数值有没有漂移。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import quantops as qo


@pytest.fixture()
def panel() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=4)
    rows = []
    for step, day in enumerate(dates):
        rows.append(
            {
                "date": day,
                "code": "000001",
                "close": 1.0 + step,
                "volume": 1.0 + step,
                "industry": 1.0,
            }
        )
        rows.append(
            {
                "date": day,
                "code": "000002",
                "close": 10.0 + step * 10,
                "volume": 1.0,
                "industry": 1.0,
            }
        )
    return pd.DataFrame(rows)


def series(expr: str, panel: pd.DataFrame, date: str, code: str = "000001"):
    result = qo.evaluate(expr, panel)
    row = result[(result["date"] == pd.Timestamp(date)) & (result["code"] == code)]
    return row["alpha"].to_numpy()


def all_values(expr: str, panel: pd.DataFrame, code: str = "000001"):
    result = qo.evaluate(expr, panel)
    return result[result["code"] == code]["alpha"].to_numpy()


# ---------- 算术 ----------


def test_arithmetic_semantics(panel):
    assert series("abs(close - 3)", panel, "2024-01-01")[0] == 2
    assert series("log(close)", panel, "2024-01-01")[0] == pytest.approx(0.0)
    assert series("inverse(close)", panel, "2024-01-01")[0] == pytest.approx(1.0)
    assert series("sqrt(close)", panel, "2024-01-02")[0] == pytest.approx(math.sqrt(2))
    assert series("sign(close - 2.5)", panel, "2024-01-01")[0] == -1
    assert series("signed_power(close - 3, 2)", panel, "2024-01-01")[0] == -4
    assert series("max(close, 3)", panel, "2024-01-01")[0] == 3
    assert series("min(close, 3)", panel, "2024-01-03")[0] == 3
    assert series("add(close, 1)", panel, "2024-01-01")[0] == 2
    assert series("subtract(close, 1)", panel, "2024-01-01")[0] == 0
    assert series("multiply(close, 3)", panel, "2024-01-01")[0] == 3
    assert series("divide(close, 2)", panel, "2024-01-01")[0] == pytest.approx(0.5)


# ---------- 时间序列 ----------


def test_time_series_semantics(panel):
    assert np.allclose(all_values("delay(close, 1)", panel)[1:], [1, 2, 3])
    assert np.isnan(all_values("delay(close, 1)", panel)[0])
    assert np.allclose(all_values("delta(close, 1)", panel)[1:], [1, 1, 1])
    assert np.allclose(all_values("ts_mean(close, 2)", panel)[1:], [1.5, 2.5, 3.5])
    assert np.allclose(all_values("ts_sum(close, 2)", panel)[1:], [3, 5, 7])
    assert np.allclose(all_values("ts_max(close, 2)", panel)[1:], [2, 3, 4])
    assert np.allclose(all_values("ts_min(close, 2)", panel)[1:], [1, 2, 3])
    assert np.allclose(all_values("ts_std(close, 2)", panel)[1:], [math.sqrt(0.5)] * 3)
    assert np.allclose(all_values("ts_corr(close, volume, 2)", panel)[1:], [1.0] * 3)
    assert np.allclose(all_values("ts_covariance(close, volume, 2)", panel)[1:], [0.5] * 3)
    assert np.allclose(all_values("ts_rank(close, 2)", panel)[1:], [1.0] * 3)
    assert np.allclose(all_values("ts_delay(close, 1)", panel)[1:], [1, 2, 3])
    assert np.allclose(all_values("hump(close, 1)", panel, code="000002"), [10, 11, 12, 13])
    assert np.allclose(all_values("days_from_last_change(close)", panel), [0, 0, 0, 0])


# ---------- 横截面 ----------


def test_cross_section_semantics(panel):
    assert series("rank(close)", panel, "2024-01-01")[0] == pytest.approx(0.5)
    assert series("rank(close)", panel, "2024-01-01", code="000002")[0] == pytest.approx(1.0)
    assert series("zscore(close)", panel, "2024-01-01")[0] == pytest.approx(-1.0)
    assert series("zscore(close)", panel, "2024-01-01", code="000002")[0] == pytest.approx(1.0)
    assert series("scale(close)", panel, "2024-01-01")[0] == pytest.approx(1 / 11)
    assert series("normalize(close)", panel, "2024-01-01")[0] == pytest.approx(-4.5)
    assert series("winsorize(close, 0.5)", panel, "2024-01-01")[0] == pytest.approx(3.25)
    assert series("winsorize(close, 0.5)", panel, "2024-01-01", code="000002")[0] == pytest.approx(7.75)


# ---------- 逻辑 ----------


def test_logic_semantics(panel):
    assert np.allclose(all_values("if_else(close > 2, close, 0)", panel), [0, 0, 3, 4])
    assert all_values("greater(close, 2)", panel).tolist() == [False, False, True, True]
    assert all_values("and_(greater(close, 2), greater(close, 3))", panel).tolist() == [False, False, False, True]
    assert all_values("not_(greater(close, 2))", panel).tolist() == [True, True, False, False]
    assert all_values("is_nan(delay(close, 1))", panel).tolist() == [True, False, False, False]


# ---------- 分组 ----------


def test_group_semantics(panel):
    assert series("group_neutralize(close, industry)", panel, "2024-01-01")[0] == pytest.approx(-4.5)
    assert series("group_rank(close, industry)", panel, "2024-01-01")[0] == pytest.approx(0.5)
    assert series("group_zscore(close, industry)", panel, "2024-01-01")[0] == pytest.approx(-1.0)
    assert series("group_scale(close, industry)", panel, "2024-01-01")[0] == pytest.approx(1 / 11)
    assert series("group_mean(close, volume, industry)", panel, "2024-01-01")[0] == pytest.approx(5.5)
    assert series("group_mean(close, volume, industry)", panel, "2024-01-02")[0] == pytest.approx(8.0)


# ---------- 转换 / 向量 ----------


def test_transformational_and_vector_semantics(panel):
    assert series('bucket(close, "0,100,10")', panel, "2024-01-01")[0] == 0
    assert series('bucket(close, "0,100,10")', panel, "2024-01-01", code="000002")[0] == 1
    traded = all_values("trade_when(close > 0, close, close > 3)", panel)
    assert np.allclose(traded[:3], [1, 2, 3])
    assert np.isnan(traded[3])
    assert np.allclose(all_values("vec_avg(close)", panel), [1, 2, 3, 4])
    assert np.allclose(all_values("vec_sum(close)", panel), [1, 2, 3, 4])
