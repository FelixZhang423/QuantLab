from abc import ABCMeta, abstractmethod
from typing import List, Type, Union, Tuple

import torch
from torch import Tensor
from ..utils.maybe import Maybe, some, none
from ...alphagen_qlib.stock_data import StockData, FeatureType


_ExprOrFloat = Union["Expression", float]
_DTimeOrInt = Union["DeltaTime", int]


try:
    # Keep compatibility with the development workspace where the original
    # AlphaGen package is also importable. The fallback keeps the bundle
    # standalone when that package is absent on the server.
    from alphagen.data.expression import OutOfDataRangeError  # type: ignore
except ImportError:
    class OutOfDataRangeError(IndexError):
        pass


class Expression(metaclass=ABCMeta):
    @abstractmethod
    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor: ...

    def __repr__(self) -> str: return str(self)

    def __add__(self, other: _ExprOrFloat) -> "Add": return Add(self, other)
    def __radd__(self, other: float) -> "Add": return Add(other, self)
    def __sub__(self, other: _ExprOrFloat) -> "Sub": return Sub(self, other)
    def __rsub__(self, other: float) -> "Sub": return Sub(other, self)
    def __mul__(self, other: _ExprOrFloat) -> "Mul": return Mul(self, other)
    def __rmul__(self, other: float) -> "Mul": return Mul(other, self)
    def __truediv__(self, other: _ExprOrFloat) -> "Div": return Div(self, other)
    def __rtruediv__(self, other: float) -> "Div": return Div(other, self)
    def __pow__(self, other: _ExprOrFloat) -> "Pow": return Pow(self, other)
    def __rpow__(self, other: float) -> "Pow": return Pow(other, self)
    def __pos__(self) -> "Expression": return self
    def __neg__(self) -> "Sub": return Sub(0., self)
    def __abs__(self) -> "Abs": return Abs(self)

    @property
    @abstractmethod
    def is_featured(self) -> bool: ...


class Feature(Expression):
    def __init__(self, feature: FeatureType) -> None:
        self._feature = feature

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        assert period.step == 1 or period.step is None
        if (period.start < -data.max_backtrack_days or
                period.stop - 1 > data.max_future_days):
            raise OutOfDataRangeError()
        start = period.start + data.max_backtrack_days
        stop = period.stop + data.max_backtrack_days + data.n_days - 1
        return data.data[start:stop, int(self._feature), :]

    def __str__(self) -> str: return '$' + self._feature.name.lower()

    @property
    def is_featured(self): return True


class Constant(Expression):
    def __init__(self, value: float) -> None:
        self.value = value

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        assert period.step == 1 or period.step is None
        if (period.start < -data.max_backtrack_days or
                period.stop - 1 > data.max_future_days):
            raise OutOfDataRangeError()
        device = data.data.device
        dtype = data.data.dtype
        days = period.stop - period.start - 1 + data.n_days
        return torch.full(size=(days, data.n_stocks),
                          fill_value=self.value, dtype=dtype, device=device)

    def __str__(self) -> str: return str(self.value)

    @property
    def is_featured(self): return False


class DeltaTime(Expression):
    # This is not something that should be in the final expression
    # It is only here for simplicity in the implementation of the tree builder
    def __init__(self, delta_time: int) -> None:
        self._delta_time = delta_time

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        assert False, "Should not call evaluate on delta time"

    def __str__(self) -> str: return f"{self._delta_time}d"

    @property
    def is_featured(self): return False


def _into_expr(value: _ExprOrFloat) -> "Expression":
    return value if isinstance(value, Expression) else Constant(value)


def _into_delta_time(value: Union[int, DeltaTime]) -> DeltaTime:
    return value if isinstance(value, DeltaTime) else DeltaTime(value)


# Operator base classes

class Operator(Expression):
    @classmethod
    @abstractmethod
    def n_args(cls) -> int: ...

    @classmethod
    @abstractmethod
    def category_type(cls) -> Type["Operator"]: ...

    @classmethod
    @abstractmethod
    def validate_parameters(cls, *args) -> Maybe[str]: ...

    @classmethod
    def _check_arity(cls, *args) -> Maybe[str]:
        arity = cls.n_args()
        if len(args) == arity:
            return none(str)
        else:
            return some(f"{cls.__name__} expects {arity} operand(s), but received {len(args)}")

    @classmethod
    def _check_exprs_featured(cls, args: list) -> Maybe[str]:
        any_is_featured: bool = False
        for i, arg in enumerate(args):
            if not isinstance(arg, (Expression, float)):
                return some(f"{arg} is not a valid expression")
            if isinstance(arg, DeltaTime):
                return some(f"{cls.__name__} expects a normal expression for operand {i + 1}, "
                            f"but got {arg} (a DeltaTime)")
            any_is_featured = any_is_featured or (isinstance(arg, Expression) and arg.is_featured)
        if not any_is_featured:
            if len(args) == 1:
                return some(f"{cls.__name__} expects a featured expression for its operand, "
                            f"but {args[0]} is not featured")
            else:
                return some(f"{cls.__name__} expects at least one featured expression for its operands, "
                            f"but none of {args} is featured")
        return none(str)

    @classmethod
    def _check_delta_time(cls, arg) -> Maybe[str]:
        if not isinstance(arg, (DeltaTime, int)):
            return some(f"{cls.__name__} expects a DeltaTime as its last operand, but {arg} is not")
        return none(str)

    @property
    @abstractmethod
    def operands(self) -> Tuple[Expression, ...]: ...

    def __str__(self) -> str:
        return f"{type(self).__name__}({','.join(str(op) for op in self.operands)})"


class UnaryOperator(Operator):
    def __init__(self, operand: _ExprOrFloat) -> None:
        self._operand = _into_expr(operand)

    @classmethod
    def n_args(cls) -> int: return 1

    @classmethod
    def category_type(cls): return UnaryOperator

    @classmethod
    def validate_parameters(cls, *args) -> Maybe[str]:
        return cls._check_arity(*args).or_else(lambda: cls._check_exprs_featured([args[0]]))

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        return self._apply(self._operand.evaluate(data, period))

    @abstractmethod
    def _apply(self, operand: Tensor) -> Tensor: ...

    @property
    def operands(self): return self._operand,

    @property
    def is_featured(self): return self._operand.is_featured


class BinaryOperator(Operator):
    def __init__(self, lhs: _ExprOrFloat, rhs: _ExprOrFloat) -> None:
        self._lhs = _into_expr(lhs)
        self._rhs = _into_expr(rhs)

    @classmethod
    def n_args(cls) -> int: return 2

    @classmethod
    def category_type(cls): return BinaryOperator

    @classmethod
    def validate_parameters(cls, *args) -> Maybe[str]:
        return cls._check_arity(*args).or_else(lambda: cls._check_exprs_featured([args[0], args[1]]))

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        return self._apply(self._lhs.evaluate(data, period), self._rhs.evaluate(data, period))

    @abstractmethod
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: ...

    def __str__(self) -> str: return f"{type(self).__name__}({self._lhs},{self._rhs})"

    @property
    def operands(self): return self._lhs, self._rhs

    @property
    def is_featured(self): return self._lhs.is_featured or self._rhs.is_featured


class TernaryOperator(Operator):
    def __init__(self, first: _ExprOrFloat, second: _ExprOrFloat, third: _ExprOrFloat) -> None:
        self._first = _into_expr(first)
        self._second = _into_expr(second)
        self._third = _into_expr(third)

    @classmethod
    def n_args(cls) -> int: return 3

    @classmethod
    def category_type(cls): return TernaryOperator

    @classmethod
    def validate_parameters(cls, *args) -> Maybe[str]:
        return cls._check_arity(*args).or_else(
            lambda: cls._check_exprs_featured([args[0], args[1], args[2]])
        )

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        return self._apply(
            self._first.evaluate(data, period),
            self._second.evaluate(data, period),
            self._third.evaluate(data, period),
        )

    @abstractmethod
    def _apply(self, first: Tensor, second: Tensor, third: Tensor) -> Tensor: ...

    def __str__(self) -> str:
        return f"{type(self).__name__}({self._first},{self._second},{self._third})"

    @property
    def operands(self): return self._first, self._second, self._third

    @property
    def is_featured(self): return any(item.is_featured for item in self.operands)


class RollingOperator(Operator):
    def __init__(self, operand: _ExprOrFloat, delta_time: _DTimeOrInt) -> None:
        self._operand = _into_expr(operand)
        self._delta_time = _into_delta_time(delta_time)._delta_time

    @classmethod
    def n_args(cls) -> int: return 2

    @classmethod
    def category_type(cls): return RollingOperator

    @classmethod
    def validate_parameters(cls, *args) -> Maybe[str]:
        return cls._check_arity(*args).or_else(
            lambda: cls._check_exprs_featured([args[0]])
        ).or_else(
            lambda: cls._check_delta_time(args[1])
        )

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        start = period.start - self._delta_time + 1
        stop = period.stop
        # L: period length (requested time window length)
        # W: window length (dt for rolling)
        # S: stock count
        values = self._operand.evaluate(data, slice(start, stop))   # (L+W-1, S)
        values = values.unfold(0, self._delta_time, 1)              # (L, S, W)
        return self._apply(values)                                  # (L, S)

    @abstractmethod
    def _apply(self, operand: Tensor) -> Tensor: ...

    @property
    def operands(self): return self._operand, DeltaTime(self._delta_time)

    @property
    def is_featured(self): return self._operand.is_featured


class PairRollingOperator(Operator):
    def __init__(self, lhs: _ExprOrFloat, rhs: _ExprOrFloat, delta_time: _DTimeOrInt) -> None:
        self._lhs = _into_expr(lhs)
        self._rhs = _into_expr(rhs)
        self._delta_time = _into_delta_time(delta_time)._delta_time

    @classmethod
    def n_args(cls) -> int: return 3

    @classmethod
    def category_type(cls): return PairRollingOperator

    @classmethod
    def validate_parameters(cls, *args) -> Maybe[str]:
        return cls._check_arity(*args).or_else(
            lambda: cls._check_exprs_featured([args[0], args[1]])
        ).or_else(
            lambda: cls._check_delta_time(args[2])
        )

    def _unfold_one(self, expr: Expression,
                    data: StockData, period: slice = slice(0, 1)) -> Tensor:
        start = period.start - self._delta_time + 1
        stop = period.stop
        # L: period length (requested time window length)
        # W: window length (dt for rolling)
        # S: stock count
        values = expr.evaluate(data, slice(start, stop))            # (L+W-1, S)
        return values.unfold(0, self._delta_time, 1)                # (L, S, W)

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        lhs = self._unfold_one(self._lhs, data, period)
        rhs = self._unfold_one(self._rhs, data, period)
        return self._apply(lhs, rhs)                                # (L, S)

    @abstractmethod
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: ...

    @property
    def operands(self): return self._lhs, self._rhs, DeltaTime(self._delta_time)

    @property
    def is_featured(self): return self._lhs.is_featured or self._rhs.is_featured


# Operator implementations

class Abs(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.abs()


class Sign(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.sign()


class Inverse(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return torch.where(operand == 0, torch.full_like(operand, torch.nan), 1.0 / operand)


class Reverse(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor: return -operand


class Sqrt(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        result = operand.clamp_min(0).sqrt()
        return torch.where(operand >= 0, result, torch.full_like(operand, torch.nan))


class Log(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.log()


class CSRank(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        nan_mask = operand.isnan()
        n = (~nan_mask).sum(dim=1, keepdim=True)
        rank = operand.argsort().argsort() / n
        rank[nan_mask] = torch.nan
        return rank


def _cross_section_mean_std(operand: Tensor):
    mean = torch.nanmean(operand, dim=1, keepdim=True)
    var = torch.nanmean((operand - mean) ** 2, dim=1, keepdim=True)
    return mean, var.sqrt()


class ZScore(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        mean, std = _cross_section_mean_std(operand)
        return torch.where(std > 0, (operand - mean) / std, torch.full_like(operand, torch.nan))


class Scale(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        denom = torch.nansum(operand.abs(), dim=1, keepdim=True)
        return torch.where(denom > 0, operand / denom, torch.full_like(operand, torch.nan))


class Winsorize(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        mean, std = _cross_section_mean_std(operand)
        lower, upper = mean - 4 * std, mean + 4 * std
        clipped = torch.maximum(torch.minimum(operand, upper), lower)
        return torch.where(std.isnan(), operand, clipped)


class Normalize(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        mean = torch.nanmean(operand, dim=1, keepdim=True)
        return operand - mean


class Quantile(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        valid = ~operand.isnan()
        n = valid.sum(dim=1, keepdim=True).clamp_min(1)
        ranks = operand.argsort(dim=1, stable=True).argsort(dim=1) + 1
        pct = (ranks / n).clamp(1e-6, 1 - 1e-6)
        result = (2 ** 0.5) * torch.erfinv(2 * pct - 1)
        return torch.where(valid, result, torch.full_like(operand, torch.nan))


class DaysFromLastChange(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        result = torch.empty_like(operand)
        result[0] = 0
        days = torch.zeros_like(operand[0])
        prev = operand[0]
        for index in range(1, operand.shape[0]):
            current = operand[index]
            same = (current == prev) | (current.isnan() & prev.isnan())
            days = torch.where(same, days + 1, torch.zeros_like(days))
            result[index] = days
            prev = current
        return result


class Hump(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        result = torch.empty_like(operand)
        result[0] = operand[0]
        prev = operand[0]
        for index in range(1, operand.shape[0]):
            current = operand[index]
            stepped = prev + (current - prev).clamp(-0.01, 0.01)
            value = torch.where(prev.isnan() | current.isnan(), current, stepped)
            result[index] = value
            prev = value
        return result


class TSStep(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        steps = torch.arange(operand.shape[0], dtype=operand.dtype, device=operand.device)
        return steps if operand.dim() == 1 else steps.unsqueeze(1).expand_as(operand)


class Add(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs + rhs


class Sub(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs - rhs


class Mul(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs * rhs


class Div(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs / rhs


class Pow(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        result = lhs ** rhs.clamp(-3, 3)
        return torch.where(result.abs() > 1e6, torch.full_like(result, torch.nan), result)


class SignedPower(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        result = lhs.sign() * lhs.abs() ** rhs.clamp(-3, 3)
        return torch.where(result.abs() > 1e6, torch.full_like(result, torch.nan), result)


class Greater(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs.max(rhs)


class Less(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return lhs.min(rhs)


class Equal(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs == rhs).to(lhs.dtype)


class NotEqual(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs != rhs).to(lhs.dtype)


class GreaterThan(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs > rhs).to(lhs.dtype)


class GreaterEqual(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs >= rhs).to(lhs.dtype)


class LessThan(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs < rhs).to(lhs.dtype)


class LessEqual(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor: return (lhs <= rhs).to(lhs.dtype)


class And(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        return (lhs.bool() & rhs.bool()).to(lhs.dtype)


class Or(BinaryOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        return (lhs.bool() | rhs.bool()).to(lhs.dtype)


class Not(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return (~operand.bool()).to(operand.dtype)


class IsNan(UnaryOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return operand.isnan().to(operand.dtype)


class IfElse(TernaryOperator):
    def _apply(self, first: Tensor, second: Tensor, third: Tensor) -> Tensor:
        return torch.where(first.bool(), second, third)


class Ref(RollingOperator):
    # Ref is not *really* a rolling operator, in that other rolling operators
    # deal with the values in (-dt, 0], while Ref only deal with the values
    # at -dt. Nonetheless, it should be classified as rolling since it modifies
    # the time window.

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        start = period.start - self._delta_time
        stop = period.stop - self._delta_time
        return self._operand.evaluate(data, slice(start, stop))

    def _apply(self, operand: Tensor) -> Tensor:
        # This is just for fulfilling the RollingOperator interface
        ...


class Mean(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.mean(dim=-1)


class Sum(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.sum(dim=-1)


class Std(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.std(dim=-1)


class Var(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.var(dim=-1)


class Skew(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        # skew = m3 / m2^(3/2)
        central = operand - operand.mean(dim=-1, keepdim=True)
        m3 = (central ** 3).mean(dim=-1)
        m2 = (central ** 2).mean(dim=-1)
        return m3 / m2 ** 1.5


class Kurt(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        # kurt = m4 / var^2 - 3
        central = operand - operand.mean(dim=-1, keepdim=True)
        m4 = (central ** 4).mean(dim=-1)
        var = operand.var(dim=-1)
        return m4 / var ** 2 - 3


class Max(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.max(dim=-1)[0]


class Min(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.min(dim=-1)[0]


class Med(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor: return operand.median(dim=-1)[0]


class Mad(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        central = operand - operand.mean(dim=-1, keepdim=True)
        return central.abs().mean(dim=-1)


class Rank(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        n = operand.shape[-1]
        last = operand[:, :, -1, None]
        left = (last < operand).count_nonzero(dim=-1)
        right = (last <= operand).count_nonzero(dim=-1)
        result = (right + left + (right > left)) / (2 * n)
        return result


class Delta(RollingOperator):
    # Delta is not *really* a rolling operator, in that other rolling operators
    # deal with the values in (-dt, 0], while Delta only deal with the values
    # at -dt and 0. Nonetheless, it should be classified as rolling since it
    # modifies the time window.

    def evaluate(self, data: StockData, period: slice = slice(0, 1)) -> Tensor:
        start = period.start - self._delta_time
        stop = period.stop
        values = self._operand.evaluate(data, slice(start, stop))
        return values[self._delta_time:] - values[:-self._delta_time]

    def _apply(self, operand: Tensor) -> Tensor:
        # This is just for fulfilling the RollingOperator interface
        ...


class WMA(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        n = operand.shape[-1]
        weights = torch.arange(n, dtype=operand.dtype, device=operand.device)
        weights /= weights.sum()
        return (weights * operand).sum(dim=-1)


class EMA(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        n = operand.shape[-1]
        alpha = 1 - 2 / (1 + n)
        power = torch.arange(n, 0, -1, dtype=operand.dtype, device=operand.device)
        weights = alpha ** power
        weights /= weights.sum()
        return (weights * operand).sum(dim=-1)


class Cov(PairRollingOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        n = lhs.shape[-1]
        clhs = lhs - lhs.mean(dim=-1, keepdim=True)
        crhs = rhs - rhs.mean(dim=-1, keepdim=True)
        return (clhs * crhs).sum(dim=-1) / (n - 1)


class Corr(PairRollingOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        clhs = lhs - lhs.mean(dim=-1, keepdim=True)
        crhs = rhs - rhs.mean(dim=-1, keepdim=True)
        ncov = (clhs * crhs).sum(dim=-1)
        nlvar = (clhs ** 2).sum(dim=-1)
        nrvar = (crhs ** 2).sum(dim=-1)
        stdmul = (nlvar * nrvar).sqrt()
        stdmul[(nlvar < 1e-6) | (nrvar < 1e-6)] = 1
        return ncov / stdmul


class TSArgMax(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        all_nan = operand.isnan().all(dim=-1)
        filled = torch.where(operand.isnan(), torch.full_like(operand, -torch.inf), operand)
        index = filled.argmax(dim=-1)
        result = (operand.shape[-1] - 1 - index).to(operand.dtype)
        return torch.where(all_nan, torch.full_like(result, torch.nan), result)


class TSArgMin(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        all_nan = operand.isnan().all(dim=-1)
        filled = torch.where(operand.isnan(), torch.full_like(operand, torch.inf), operand)
        index = filled.argmin(dim=-1)
        result = (operand.shape[-1] - 1 - index).to(operand.dtype)
        return torch.where(all_nan, torch.full_like(result, torch.nan), result)


class TSAvDiff(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return operand[..., -1] - operand.mean(dim=-1)


class TSBackfill(RollingOperator):
    def evaluate(self, data, period=slice(0, 1)) -> Tensor:
        start = period.start - self._delta_time
        values = self._operand.evaluate(data, slice(start, period.stop))
        return self._apply(values.unfold(0, self._delta_time + 1, 1))

    def _apply(self, operand: Tensor) -> Tensor:
        valid = ~operand.isnan()
        positions = torch.arange(operand.shape[-1], device=operand.device).view(1, 1, -1)
        last_valid = torch.where(valid, positions, -1).max(dim=-1).values
        values = operand.gather(-1, last_valid.clamp_min(0).unsqueeze(-1)).squeeze(-1)
        return torch.where(last_valid < 0, torch.full_like(values, torch.nan), values)


class TSCountNans(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return operand.isnan().sum(dim=-1).to(operand.dtype)


class TSDecayLinear(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        weights = torch.arange(1, operand.shape[-1] + 1, dtype=operand.dtype, device=operand.device)
        return (operand * weights).sum(dim=-1) / weights.sum()


class TSProduct(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        return operand.prod(dim=-1)


class TSQuantile(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        last = operand[..., -1:]
        valid = ~operand.isnan()
        left = ((operand < last) & valid).sum(dim=-1, keepdim=True)
        right = ((operand <= last) & valid).sum(dim=-1, keepdim=True)
        count = valid.sum(dim=-1, keepdim=True).clamp_min(1)
        pct = ((left + 1 + right) / (2 * count)).clamp(1e-6, 1 - 1e-6)
        result = (2 ** 0.5) * torch.erfinv(2 * pct - 1)
        return torch.where(last.isnan(), torch.full_like(result, torch.nan), result).squeeze(-1)


class TSScale(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        low = operand.min(dim=-1).values
        high = operand.max(dim=-1).values
        denom = high - low
        result = (operand[..., -1] - low) / denom
        return torch.where(denom == 0, torch.full_like(result, torch.nan), result)


class TSZScore(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        mean = operand.mean(dim=-1)
        std = operand.std(dim=-1)
        result = (operand[..., -1] - mean) / std
        return torch.where(std == 0, torch.full_like(result, torch.nan), result)


class KthElement(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        result = torch.full_like(operand[..., 0], torch.nan)
        remaining = torch.full(operand.shape[:-1], 2, dtype=torch.long, device=operand.device)
        for index in range(operand.shape[-1] - 1, -1, -1):
            take = (~operand[..., index].isnan()) & (remaining > 0)
            result = torch.where(take, operand[..., index], result)
            remaining = remaining - take.long()
        return result


class LastDiffValue(RollingOperator):
    def _apply(self, operand: Tensor) -> Tensor:
        current = operand[..., -1]
        result = torch.full_like(current, torch.nan)
        found = torch.zeros_like(current, dtype=torch.bool)
        for index in range(operand.shape[-1] - 2, -1, -1):
            value = operand[..., index]
            same = (value == current) | (value.isnan() & current.isnan())
            take = (~same) & (~found)
            result = torch.where(take, value, result)
            found = found | take
        return result


class TSRegression(PairRollingOperator):
    def _apply(self, lhs: Tensor, rhs: Tensor) -> Tensor:
        mean_lhs = lhs.mean(dim=-1, keepdim=True)
        mean_rhs = rhs.mean(dim=-1, keepdim=True)
        cov = ((lhs - mean_lhs) * (rhs - mean_rhs)).sum(dim=-1)
        var = ((rhs - mean_rhs) ** 2).sum(dim=-1)
        result = cov / var
        return torch.where(var == 0, torch.full_like(result, torch.nan), result)


Operators: List[Type[Operator]] = [
    # Unary
    Abs, Sign, Inverse, Reverse, Sqrt, Log, CSRank,
    ZScore, Scale, Winsorize, Normalize, Quantile,
    DaysFromLastChange, Hump, TSStep,
    Not, IsNan,
    # Binary
    Add, Sub, Mul, Div, Pow, SignedPower, Greater, Less,
    Equal, NotEqual, GreaterThan, GreaterEqual, LessThan, LessEqual, And, Or,
    # Ternary
    IfElse,
    # Rolling
    Ref, Mean, Sum, Std, Var, Skew, Kurt, Max, Min,
    Med, Mad, Rank, Delta, WMA, EMA,
    TSArgMax, TSArgMin, TSAvDiff, TSBackfill, TSCountNans,
    TSDecayLinear, TSProduct, TSQuantile, TSScale, TSZScore,
    KthElement, LastDiffValue,
    # Pair rolling
    Cov, Corr, TSRegression
]
