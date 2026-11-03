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


def make_panel(close_by_code, volume_by_code=None, industry_by_code=None):
    dates = pd.bdate_range("2024-01-01", periods=4)
    rows = []
    for code, closes in close_by_code.items():
        volumes = (volume_by_code or {}).get(code, [1.0] * len(closes))
        industry = (industry_by_code or {}).get(code, 1.0)
        for index, date in enumerate(dates):
            rows.append({
                "date": date,
                "code": code,
                "close": closes[index],
                "volume": volumes[index],
                "industry": industry,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def missing_panel():
    return make_panel(
        {"000001": [1.0, 2.0, 3.0, 4.0], "000002": [10.0, 20.0, 30.0, 40.0]},
        {"000001": [1.0, 2.0, 3.0, 4.0], "000002": [2.0, 4.0, 6.0, 8.0]},
        {"000001": 1.0, "000002": 2.0},
    )


@pytest.fixture()
def non_monotonic():
    return make_panel({"000001": [1.0, 3.0, 2.0, 4.0]})


@pytest.fixture()
def with_nan():
    return make_panel({"000001": [1.0, np.nan, 3.0, 4.0]})


def values(expr, missing_panel, code="000001"):
    result = qo.evaluate(expr, missing_panel)
    return result[result["code"] == code]["alpha"].to_numpy()


def test_arithmetic_missing_semantics(missing_panel):
    assert np.allclose(values("power(close, 2)", missing_panel), [1, 4, 9, 16])
    assert np.allclose(values("reverse(close)", missing_panel), [-1, -2, -3, -4])
    assert np.allclose(values("densify(industry)", missing_panel), [0, 0, 0, 0])


def test_power_guards_clamp_exponent_and_reject_overflow(missing_panel):
    assert np.allclose(values("power(close, 10)", missing_panel), [1, 8, 27, 64])
    assert np.allclose(values("signed_power(close, -10)", missing_panel), [1, 1 / 8, 1 / 27, 1 / 64])

    big = missing_panel.copy()
    big.loc[big["code"] == "000001", "close"] = 200.0
    assert np.isnan(values("power(close, 3)", big)[0])


def test_densify_sparse_labels(missing_panel):
    sparse = missing_panel.copy()
    sparse.loc[sparse["code"] == "000002", "industry"] = 2.0
    assert np.allclose(values("densify(industry)", sparse), [0, 0, 0, 0])
    result = qo.evaluate("densify(industry)", sparse)
    assert sorted(result["alpha"].unique()) == [0.0, 1.0]


def test_time_series_alias_and_basic_semantics(missing_panel):
    assert np.allclose(values("ts_delta(close, 1)", missing_panel)[1:], [1, 1, 1])
    assert np.isnan(values("ts_delta(close, 1)", missing_panel)[0])
    assert np.allclose(values("ts_av_diff(close, 3)", missing_panel)[2:], [1, 1])
    assert np.allclose(values("ts_median(close, 3)", missing_panel)[2:], [2, 3])
    assert np.allclose(values("ts_product(close, 3)", missing_panel)[2:], [6, 24])
    assert np.allclose(values("ts_std_dev(close, 3)", missing_panel)[2:], [1, 1])
    assert np.allclose(values("ts_var(close, 3)", missing_panel)[2:], [1, 1])
    assert np.allclose(values("ts_zscore(close, 3)", missing_panel)[2:], [1, 1])
    assert np.allclose(values("ts_step(close)", missing_panel), [0, 1, 2, 3])


def test_time_series_weighted_semantics(missing_panel):
    assert np.allclose(values("ts_decay_linear(close, 3)", missing_panel)[2], [14 / 6])
    assert np.allclose(values("ts_wma(close, 3)", missing_panel)[2], [8 / 3])
    assert np.allclose(values("ts_ema(close, 3)", missing_panel)[2], [17 / 7])
    assert np.allclose(values("ts_mad(close, 3)", missing_panel)[2], [2 / 3])


def test_time_series_window_position_semantics(non_monotonic):
    assert np.allclose(values("ts_arg_max(close, 3)", non_monotonic)[2:], [1, 0])
    assert np.allclose(values("ts_arg_min(close, 3)", non_monotonic)[2:], [2, 1])
    assert np.allclose(values("kth_element(close, 3, 2)", non_monotonic)[2:], [3, 2])
    assert np.allclose(values("last_diff_value(close, 3)", non_monotonic)[2:], [3, 2])
    assert np.allclose(values("ts_scale(close, 3)", non_monotonic)[2:], [0.5, 1.0])


def test_time_series_skew_and_kurt_semantics(missing_panel):
    # 对称窗口 [1,2,3] / [2,3,4] 偏度为 0；m4=2/3、样本方差=1，超额峰度=2/3-3。
    assert np.allclose(values("ts_skew(close, 3)", missing_panel)[2:], [0.0, 0.0])
    assert np.allclose(values("ts_kurt(close, 3)", missing_panel)[2:], [-7 / 3, -7 / 3])


def test_time_series_quantile_and_regression(missing_panel):
    assert np.allclose(values("ts_quantile(close, 3, \"uniform\")", missing_panel)[2:], [0.5, 0.5])
    assert np.allclose(values("ts_regression(close, volume, 3)", missing_panel)[2:], [1.0, 1.0])


def test_time_series_nan_handling(with_nan):
    backfilled = values("ts_backfill(close, 2)", with_nan)
    assert np.allclose(backfilled, [1, 1, 3, 4], equal_nan=True)
    counts = values("ts_count_nans(close, 3)", with_nan)
    assert np.allclose(counts[2:], [1, 1], equal_nan=True)


def test_cross_section_quantile(missing_panel):
    result = qo.evaluate("quantile(close, \"uniform\")", missing_panel)
    first = result[result["date"] == result["date"].min()]
    mapped = dict(zip(first["code"], first["alpha"]))
    assert mapped["000001"] == pytest.approx(0.0)
    assert mapped["000002"] == pytest.approx(0.5, abs=1e-5)


def test_logic_missing_semantics(missing_panel):
    assert values("equal(close, 2)", missing_panel).tolist() == [False, True, False, False]
    assert values("greater_equal(close, 3)", missing_panel).tolist() == [False, False, True, True]
    assert values("less(close, 3)", missing_panel).tolist() == [True, True, False, False]
    assert values("less_equal(close, 3)", missing_panel).tolist() == [True, True, True, False]
    assert values("not_equal(close, 2)", missing_panel).tolist() == [True, False, True, True]
    assert values("or_(greater(close, 2), greater(close, 3))", missing_panel).tolist() == [False, False, True, True]
    assert np.allclose(values("where(close > 2, close, 0)", missing_panel), [0, 0, 3, 4])


def test_group_backfill_semantics():
    missing_panel = make_panel(
        {"000001": [1.0, 2.0, np.nan, 4.0], "000002": [2.0, 4.0, 6.0, 8.0]},
        industry_by_code={"000001": 1.0, "000002": 1.0},
    )
    filled = values("group_backfill(close, industry, 2)", missing_panel)
    assert filled[2] == 6.0
