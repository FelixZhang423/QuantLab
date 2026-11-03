"""AlphaGen 侧新增算子的数值语义：与 quantops 的同名算子保持同一口径。"""
from statistics import NormalDist

import torch
from torch.testing import assert_close

from custom_bt.operator_registry import load_alphagen_operator_classes

load_alphagen_operator_classes()  # 把仓库根加入 sys.path，下面才能导入 single_factor

from single_factor._vendor.alphagen.data.expression import (  # noqa: E402
    And,
    Constant,
    DaysFromLastChange,
    Equal,
    GreaterEqual,
    GreaterThan,
    Hump,
    IfElse,
    Inverse,
    IsNan,
    KthElement,
    LastDiffValue,
    LessEqual,
    LessThan,
    Normalize,
    Not,
    NotEqual,
    Or,
    Pow,
    Quantile,
    Reverse,
    Scale,
    SignedPower,
    Sqrt,
    TSArgMax,
    TSArgMin,
    TSAvDiff,
    TSBackfill,
    TSCountNans,
    TSDecayLinear,
    TSProduct,
    TSQuantile,
    TSRegression,
    TSScale,
    TSStep,
    TSZScore,
    Winsorize,
    ZScore,
)

NAN = torch.nan


def apply_unary(operator, values):
    return operator._apply(torch.tensor(values, dtype=torch.float32))


def apply_rolling(operator, values):
    window = torch.tensor([values], dtype=torch.float32).unsqueeze(0)
    return operator._apply(window)[0, 0]


def test_inverse_reverse_and_sqrt():
    assert_close(apply_unary(Inverse(Constant(1.0)), [-1.0, 0.0, 2.0]), torch.tensor([-1.0, NAN, 0.5]), equal_nan=True)
    assert_close(apply_unary(Reverse(Constant(1.0)), [1.0, -2.0]), torch.tensor([-1.0, 2.0]))
    assert_close(apply_unary(Sqrt(Constant(1.0)), [1.0, 4.0, -1.0]), torch.tensor([1.0, 2.0, NAN]), equal_nan=True)


def test_signed_power():
    operator = SignedPower(Constant(1.0), Constant(1.0))
    actual = operator._apply(
        torch.tensor([-4.0, -1.0, 4.0]),
        torch.tensor([0.5, 2.0, 0.5]),
    )
    assert_close(actual, torch.tensor([-2.0, -1.0, 2.0]))


def test_power_guards_clamp_exponent_and_reject_overflow():
    pow_operator = Pow(Constant(1.0), Constant(1.0))
    assert_close(
        pow_operator._apply(torch.tensor([2.0]), torch.tensor([10.0])),
        torch.tensor([8.0]),
    )
    assert_close(
        pow_operator._apply(torch.tensor([200.0]), torch.tensor([3.0])),
        torch.tensor([NAN]),
        equal_nan=True,
    )

    signed = SignedPower(Constant(1.0), Constant(1.0))
    assert_close(
        signed._apply(torch.tensor([-2.0]), torch.tensor([-10.0])),
        torch.tensor([-0.125]),
    )
    assert_close(
        signed._apply(torch.tensor([-200.0]), torch.tensor([3.0])),
        torch.tensor([NAN]),
        equal_nan=True,
    )


def test_cross_section_zscore_and_scale():
    assert_close(
        apply_unary(ZScore(Constant(1.0)), [[1.0, 2.0, 3.0], [1.0, 1.0, 1.0]]),
        torch.tensor([
            [-(1.5 ** 0.5), 0.0, 1.5 ** 0.5],
            [NAN, NAN, NAN],
        ]),
        equal_nan=True,
    )
    assert_close(
        apply_unary(Scale(Constant(1.0)), [[1.0, -2.0, 2.0]]),
        torch.tensor([[0.2, -0.4, 0.4]]),
    )


def test_cross_section_winsorize_and_normalize():
    values = [0.0] * 19 + [100.0]
    clipped = apply_unary(Winsorize(Constant(1.0)), [values])
    upper = 5.0 + 4.0 * (475.0 ** 0.5)
    assert_close(clipped[0, -1], torch.tensor(upper), rtol=1e-5, atol=0.0)
    assert_close(clipped[0, :19], torch.zeros(19))
    assert_close(
        apply_unary(Normalize(Constant(1.0)), [[1.0, 2.0, 3.0]]),
        torch.tensor([[-1.0, 0.0, 1.0]]),
    )


def test_cross_section_quantile_matches_normal_scores():
    expected = torch.tensor([
        NormalDist().inv_cdf(1 / 3),
        NormalDist().inv_cdf(2 / 3),
        NormalDist().inv_cdf(1 - 1e-6),
    ], dtype=torch.float32)
    # float32 在 p≈1 处的分辨率有限，最后一位允许 0.003 的绝对误差。
    assert_close(apply_unary(Quantile(Constant(1.0)), [[1.0, 2.0, 3.0]])[0], expected, rtol=1e-5, atol=3e-3)


def test_stateful_time_series_operators():
    assert_close(apply_unary(DaysFromLastChange(Constant(1.0)), [1.0, 1.0, 2.0, 2.0]), torch.tensor([0.0, 1.0, 0.0, 1.0]))
    assert_close(apply_unary(Hump(Constant(1.0)), [1.0, 2.0, 3.0]), torch.tensor([1.0, 1.01, 1.02]), rtol=1e-5, atol=1e-6)
    assert_close(apply_unary(TSStep(Constant(1.0)), [5.0, 5.0, 5.0]), torch.tensor([0.0, 1.0, 2.0]))


def test_rolling_time_series_operators():
    values = [1.0, 2.0, 3.0]
    assert_close(apply_rolling(TSArgMax(Constant(1.0), 3), [1.0, 3.0, 2.0]), torch.tensor(1.0))
    assert_close(apply_rolling(TSArgMin(Constant(1.0), 3), [1.0, 3.0, 2.0]), torch.tensor(2.0))
    assert_close(apply_rolling(TSAvDiff(Constant(1.0), 3), values), torch.tensor(1.0))
    assert_close(apply_rolling(TSBackfill(Constant(1.0), 4), [1.0, NAN, NAN, 3.0]), torch.tensor(3.0))
    assert_close(apply_rolling(TSBackfill(Constant(1.0), 4), [1.0, NAN, NAN, NAN]), torch.tensor(1.0))
    assert_close(apply_rolling(TSCountNans(Constant(1.0), 4), [1.0, NAN, 3.0, NAN]), torch.tensor(2.0))
    assert_close(apply_rolling(TSDecayLinear(Constant(1.0), 3), values), torch.tensor(14 / 6))
    assert_close(apply_rolling(TSProduct(Constant(1.0), 3), values), torch.tensor(6.0))
    assert_close(apply_rolling(TSScale(Constant(1.0), 3), values), torch.tensor(1.0))
    assert_close(apply_rolling(TSZScore(Constant(1.0), 3), values), torch.tensor(1.0))
    assert_close(apply_rolling(KthElement(Constant(1.0), 3), values), torch.tensor(2.0))
    assert_close(apply_rolling(LastDiffValue(Constant(1.0), 3), [1.0, 3.0, 3.0]), torch.tensor(1.0))

    expected = torch.tensor(NormalDist().inv_cdf(1 - 1e-6))
    assert_close(apply_rolling(TSQuantile(Constant(1.0), 3), values), expected, rtol=1e-5, atol=3e-3)


def test_rolling_regression_slope():
    operator = TSRegression(Constant(1.0), Constant(1.0), 3)
    lhs = torch.tensor([[[1.0, 2.0, 3.0]]])
    rhs = torch.tensor([[[2.0, 4.0, 6.0]]])
    assert_close(operator._apply(lhs, rhs)[0, 0], torch.tensor(0.5))


def test_logic_comparison_and_boolean_operators():
    lhs = torch.tensor([1.0, 2.0, 3.0])
    rhs = torch.tensor([1.0, 3.0, 2.0])
    assert_close(Equal(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([1.0, 0.0, 0.0]))
    assert_close(NotEqual(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([0.0, 1.0, 1.0]))
    assert_close(GreaterThan(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([0.0, 0.0, 1.0]))
    assert_close(GreaterEqual(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([1.0, 0.0, 1.0]))
    assert_close(LessThan(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([0.0, 1.0, 0.0]))
    assert_close(LessEqual(Constant(1.0), Constant(1.0))._apply(lhs, rhs), torch.tensor([1.0, 1.0, 0.0]))

    first = torch.tensor([1.0, 0.0, 1.0])
    second = torch.tensor([0.0, 1.0, 1.0])
    assert_close(And(Constant(1.0), Constant(1.0))._apply(first, second), torch.tensor([0.0, 0.0, 1.0]))
    assert_close(Or(Constant(1.0), Constant(1.0))._apply(first, second), torch.tensor([1.0, 1.0, 1.0]))
    assert_close(Not(Constant(1.0))._apply(first), torch.tensor([0.0, 1.0, 0.0]))
    assert_close(IsNan(Constant(1.0))._apply(torch.tensor([1.0, NAN])), torch.tensor([0.0, 1.0]))


def test_if_else_operator():
    condition = torch.tensor([1.0, 0.0, 1.0])
    second = torch.tensor([10.0, 20.0, 30.0])
    third = torch.tensor([-1.0, -2.0, -3.0])
    result = IfElse(Constant(1.0), Constant(1.0), Constant(1.0))._apply(condition, second, third)
    assert_close(result, torch.tensor([10.0, -2.0, 30.0]))
