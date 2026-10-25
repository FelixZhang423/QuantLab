"""算子金标准：固定合成面板 × 全部 80 个算子，锁住搬家之后的数值。

数出自当前实现；搬家前用一次性 dump 脚本对 custom_bt 老实现做过逐字节对拍
（算子清单 / 每个 example 的数值 / /api/operators 的 JSON 全部相等），所以这里的
金标准 = 搬家前行为。此后任何数值漂移都会在这里红。

摘要算法：把 alpha 列按 (date, code) 排序，逐值 ``repr(float(v))``、NaN 记 ``"nan"``，
逗号连接后取 sha256 前 16 位。repr 保证浮点逐位可比，不受显示精度影响。
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

import quantops as qo

EXTRA_EXPRESSIONS = {
    # docs 里这三个 canonical 算子没有示例，用能同时驱动两个参数的表达式补上。
    "div": "div(close, volume)",
    "mul": "mul(close, volume)",
    "sub": "sub(close, volume)",
}

PANEL_ROWS = 240
PANEL_NANS = 1

DIGESTS = {
    "abs": "4c327d2dfb8f58a6",
    "add": "c0a13c8a4fea6f6f",
    "and_": "5d806348083f8f4c",
    "bucket": "fb951561988ace81",
    "days_from_last_change": "15087c5c6b880b2b",
    "delay": "3dbb40309b25535b",
    "delta": "43cafd9c458b1f52",
    "densify": "032474accc73caba",
    "div": "01ca5b4d58fcc39e",
    "divide": "133215e9a2f37c29",
    "equal": "f42b6c635f89f4e4",
    "greater": "5d806348083f8f4c",
    "greater_equal": "5d806348083f8f4c",
    "group_backfill": "c79c060207fdd2d1",
    "group_mean": "1ddeda2d427bbf1e",
    "group_neutralize": "6137a2062a224390",
    "group_rank": "015c1234901cd2dd",
    "group_scale": "180e637e5d67f03a",
    "group_zscore": "b2d7709bd9f637c9",
    "hump": "c43208279f1c0d56",
    "if_else": "dc9abadb2b9c0e79",
    "inverse": "139bae774f26a326",
    "is_nan": "c3659cd0c3240cd7",
    "kth_element": "0d7be1b5dd9ccea5",
    "last_diff_value": "e69efd1bdb26832f",
    "less": "c20eaa24bb7353c2",
    "less_equal": "103e68b73d8b9e91",
    "log": "726ee872f128a841",
    "max": "524831f3de6642e3",
    "min": "2223b064b7f273a4",
    "mul": "56d2758d6beabacb",
    "multiply": "afa8ede6646dcfb2",
    "normalize": "45e48e688ac1e50e",
    "not_": "f091ab5a89963da6",
    "not_equal": "f95d1224f1792071",
    "or_": "f95d1224f1792071",
    "power": "13d3b762825bb5ff",
    "quantile": "f90b0a88f3943d92",
    "rank": "151388450ed15f37",
    "reverse": "265f416011d949ab",
    "scale": "1b4b184d7b977281",
    "sign": "db358148414b21f7",
    "signed_power": "5e81157f1663b512",
    "sqrt": "bd9e64a017948e8a",
    "sub": "06a1048344f2c0ab",
    "subtract": "2e3bb71eed3b0158",
    "trade_when": "c73d6cf92aff36e0",
    "ts_arg_max": "9bdf33c0a013eec6",
    "ts_arg_min": "f0606fc1776711e5",
    "ts_av_diff": "0079da3dcee8a541",
    "ts_backfill": "26e4e9ffddc91fcd",
    "ts_corr": "d97647f91d188510",
    "ts_count_nans": "2b51efe0eba2a4b9",
    "ts_covariance": "373e6819fe1ce609",
    "ts_decay_linear": "f2c071258ac638e3",
    "ts_delay": "3dbb40309b25535b",
    "ts_delta": "43cafd9c458b1f52",
    "ts_ema": "bf25b4719d98712f",
    "ts_mad": "e9a0315750c4c1f1",
    "ts_max": "9699d8fbee4947ee",
    "ts_mean": "3fe3670bdca7514d",
    "ts_median": "9531f110a2ff534b",
    "ts_min": "430ee07bf652e517",
    "ts_product": "fc3cf1caa048fe91",
    "ts_quantile": "bc3d0e0bd381d574",
    "ts_rank": "25ecddc4b152ca26",
    "ts_regression": "ad509fae373233b4",
    "ts_scale": "416bdde06e9c103f",
    "ts_std": "b082b84984c93541",
    "ts_std_dev": "b082b84984c93541",
    "ts_step": "8b687061f4a82cc3",
    "ts_sum": "12e6dc4e8ca802eb",
    "ts_var": "be1138141e7b30e9",
    "ts_wma": "8d778da5a81cdc71",
    "ts_zscore": "dc22a3f24be37d44",
    "vec_avg": "89666a8947e20910",
    "vec_sum": "f41b4fd9b9115e96",
    "where": "524831f3de6642e3",
    "winsorize": "89666a8947e20910",
    "zscore": "2ddab59385552b78",
}

# 12 个代表算子的可读样本：摘要不匹配时用来定位（看首日/末日切片是否整体偏移）。
# 每项 = (表达式, NaN 个数, 首日 6 个值, 末日 6 个值)。
REPRESENTATIVES = {
    "rank": (
        "rank(close)",
        1,
        [
            "0.16666666666666666",
            "0.3333333333333333",
            "0.5",
            "0.6666666666666666",
            "0.8333333333333334",
            "1.0",
        ],
        [
            "0.16666666666666666",
            "0.3333333333333333",
            "0.5",
            "0.6666666666666666",
            "1.0",
            "0.8333333333333334",
        ],
    ),
    "ts_mean": (
        "ts_mean(close, 20)",
        122,
        [
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
        ],
        [
            "10.00790549801431",
            "11.112791559822089",
            "14.063748254717328",
            "15.827731260662",
            "25.165410644388054",
            "22.741937320637682",
        ],
    ),
    "ts_corr": (
        "ts_corr(close, volume, 20)",
        136,
        [
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
        ],
        [
            "-0.013076235768198973",
            "-0.16148243643710797",
            "0.33822997099709107",
            "-0.046615149096204296",
            "-0.1854482460181772",
            "-0.2588469017339964",
        ],
    ),
    "ts_rank": (
        "ts_rank(close, 20)",
        122,
        [
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
        ],
        [
            "0.6",
            "0.4",
            "0.1",
            "0.15",
            "1.0",
            "0.1",
        ],
    ),
    "group_rank": (
        "group_rank(close, industry)",
        1,
        [
            "0.5",
            "0.5",
            "0.5",
            "1.0",
            "1.0",
            "1.0",
        ],
        [
            "0.5",
            "0.5",
            "0.5",
            "1.0",
            "1.0",
            "1.0",
        ],
    ),
    "scale": (
        "scale(rank(close), scale=1)",
        1,
        [
            "0.047619047619047616",
            "0.09523809523809523",
            "0.14285714285714285",
            "0.19047619047619047",
            "0.2380952380952381",
            "0.2857142857142857",
        ],
        [
            "0.047619047619047616",
            "0.09523809523809523",
            "0.14285714285714285",
            "0.19047619047619047",
            "0.2857142857142857",
            "0.2380952380952381",
        ],
    ),
    "delay": (
        "delay(close, 5)",
        31,
        [
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
        ],
        [
            "10.131814701518456",
            "10.622721943412818",
            "14.40322947739074",
            "14.855552078336535",
            "25.57231534978988",
            "23.52650080418266",
        ],
    ),
    "if_else": (
        "if_else(greater(close, open), rank(close), reverse(rank(close)))",
        1,
        [
            "-0.16666666666666666",
            "-0.3333333333333333",
            "-0.5",
            "0.6666666666666666",
            "-0.8333333333333334",
            "-1.0",
        ],
        [
            "-0.16666666666666666",
            "-0.3333333333333333",
            "-0.5",
            "0.6666666666666666",
            "1.0",
            "0.8333333333333334",
        ],
    ),
    "signed_power": (
        "signed_power(zscore(close), 2)",
        1,
        [
            "-2.202493764739858",
            "-0.7951830203543918",
            "-0.10128023854878172",
            "0.21035331147629635",
            "0.652450137747658",
            "2.0382395271330136",
        ],
        [
            "-1.0332519057662437",
            "-0.7821199865319253",
            "-0.19524676760917287",
            "-0.10931908385722536",
            "2.9867767129019",
            "0.8932855433335328",
        ],
    ),
    "ts_decay_linear": (
        "ts_decay_linear(close, 10)",
        62,
        [
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
            "nan",
        ],
        [
            "10.23956368938328",
            "10.810739026535447",
            "13.79339512006828",
            "14.676064082144684",
            "25.668206890064845",
            "22.643848329132126",
        ],
    ),
    "hump": (
        "hump(rank(close), 0.01)",
        1,
        [
            "0.16666666666666666",
            "0.3333333333333333",
            "0.5",
            "0.6666666666666666",
            "0.8333333333333334",
            "1.0",
        ],
        [
            "0.16666666666666666",
            "0.3333333333333333",
            "0.5",
            "0.6666666666666666",
            "1.0",
            "0.8333333333333334",
        ],
    ),
    "bucket": (
        "bucket(rank(close), range='0,1,0.1')",
        1,
        [
            "1.0",
            "3.0",
            "5.0",
            "6.0",
            "8.0",
            "9.0",
        ],
        [
            "1.0",
            "3.0",
            "5.0",
            "6.0",
            "9.0",
            "8.0",
        ],
    ),
}



def make_panel() -> pd.DataFrame:
    """固定种子合成面板：40 个交易日 × 6 只股票，含示例表达式用到的全部字段。

    第 7 行 close、第 53 行 volume 各注入一个 NaN，覆盖缺失值分支。
    """
    rng = np.random.default_rng(20261014)
    dates = pd.bdate_range("2024-01-01", periods=40)
    codes = [f"{i:06d}" for i in (1, 2, 3, 4, 5, 6)]
    rows = []
    for code_idx, code in enumerate(codes):
        price = 10.0 + code_idx * 3
        for date in dates:
            ret = float(rng.normal(0, 0.02))
            open_ = price
            close = max(0.5, open_ * (1 + ret))
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": open_,
                    "close": close,
                    "high": max(open_, close) * 1.01,
                    "low": min(open_, close) * 0.99,
                    "amount": close * 1e6,
                    "volume": 1e6 * (1 + abs(ret)),
                    "TurnoverRate": abs(ret),
                    "ChangePCT": ret * 100,
                    "industry": float(code_idx % 3),
                    "ma20": price,
                    "if_up": float(ret > 0),
                    "if_down": float(ret < 0),
                    "if_flat": float(ret == 0),
                    "Ifsuspend": 0.0,
                    "vwap": (open_ + close) / 2,
                }
            )
            price = close
    panel = pd.DataFrame(rows)
    panel.loc[7, "close"] = np.nan
    panel.loc[53, "volume"] = np.nan
    return panel


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return make_panel()


@pytest.fixture(scope="module")
def alpha_cells(panel):
    """{算子名: (表达式, [每行一个 repr 字符串])}，一次算完给两个用例复用。"""
    cache = {}

    def get(name: str):
        if name not in cache:
            expr = expression_for(name)
            series = qo.evaluate(expr, panel).sort_values(["date", "code"])["alpha"]
            cache[name] = (expr, ["nan" if pd.isna(v) else repr(float(v)) for v in series])
        return cache[name]

    return get


def expression_for(name: str) -> str:
    """优先用 docs 里的示例；docs 没给示例的 3 个 canonical 算子用补的表达式。"""
    if name in qo.OPERATOR_EXAMPLES:
        return qo.OPERATOR_EXAMPLES[name]
    if name in EXTRA_EXPRESSIONS:
        return EXTRA_EXPRESSIONS[name]
    return f"{name}(close, 5)" if name.startswith("ts_") else f"{name}(close)"


def test_reference_panel_is_unchanged(panel):
    """面板本身变了会让下面 80 个摘要一起红 —— 先在这里挡住。"""
    assert panel.shape == (PANEL_ROWS, 17)
    assert int(panel["close"].isna().sum()) == PANEL_NANS


def test_golden_table_covers_every_operator():
    assert sorted(DIGESTS) == sorted(qo.OPERATORS)
    assert sorted(REPRESENTATIVES) == sorted(set(REPRESENTATIVES) & set(DIGESTS))


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_operator_matches_golden_digest(name, alpha_cells):
    expr, cells = alpha_cells(name)
    digest = hashlib.sha256(",".join(cells).encode()).hexdigest()[:16]
    assert digest == DIGESTS[name], f"{name} 的数值变了（表达式 {expr}）"


@pytest.mark.parametrize("name", sorted(REPRESENTATIVES))
def test_representative_operators_match_readable_values(name, alpha_cells):
    expected_expr, n_nan, first, last = REPRESENTATIVES[name]
    expr, cells = alpha_cells(name)
    assert expr == expected_expr
    assert cells.count("nan") == n_nan
    assert cells[:6] == first
    assert cells[-6:] == last
