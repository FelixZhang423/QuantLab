import json
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import torch

from ._vendor.alphagen.data.expression import OutOfDataRangeError


class PanelData:
    """Date-by-stock panel with the same period semantics as StockData."""

    def __init__(
        self,
        arrays: Mapping[str, np.ndarray],
        dates: Sequence,
        stock_ids: Sequence[str],
        max_backtrack_days: int = 0,
        max_future_days: int = 0,
    ) -> None:
        if not arrays:
            raise ValueError("arrays must contain at least one feature")
        self._arrays = {name: np.asarray(values) for name, values in arrays.items()}
        first_shape = next(iter(self._arrays.values())).shape
        if len(first_shape) != 2:
            raise ValueError("feature arrays must have shape (days, stocks)")
        if any(values.shape != first_shape for values in self._arrays.values()):
            raise ValueError("all feature arrays must have the same shape")
        self.dates = pd.DatetimeIndex(dates)
        self.stock_ids = tuple(str(stock_id) for stock_id in stock_ids)
        if len(self.dates) != first_shape[0] or len(self.stock_ids) != first_shape[1]:
            raise ValueError("dates and stock_ids do not match feature array shape")
        if max_backtrack_days < 0 or max_future_days < 0:
            raise ValueError("lookback and lookahead must be non-negative")
        if first_shape[0] <= max_backtrack_days + max_future_days:
            raise ValueError("panel does not contain any valid evaluation day")
        self.max_backtrack_days = max_backtrack_days
        self.max_future_days = max_future_days
        # Existing Constant uses only dtype/device from StockData.data.
        self.data = torch.empty(
            (0, len(self._arrays), first_shape[1]),
            dtype=torch.float32,
        )

    @classmethod
    def from_memmap(
        cls,
        cache_dir: Path | str,
        max_backtrack_days: int = 0,
        max_future_days: int = 0,
    ) -> "PanelData":
        cache_path = Path(cache_dir)
        manifest = json.loads((cache_path / "manifest.json").read_text(encoding="utf-8"))
        arrays = {
            field: np.load(cache_path / f"{field}.npy", mmap_mode="r")
            for field in manifest["fields"]
        }
        dates = np.load(cache_path / "dates.npy")
        stock_ids = json.loads((cache_path / "codes.json").read_text(encoding="utf-8"))
        return cls(
            arrays,
            dates,
            stock_ids,
            max_backtrack_days=max_backtrack_days,
            max_future_days=max_future_days,
        )

    @property
    def n_days(self) -> int:
        return len(self.dates) - self.max_backtrack_days - self.max_future_days

    @property
    def n_stocks(self) -> int:
        return len(self.stock_ids)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(self._arrays)

    def feature(self, name: str, period: slice = slice(0, 1)) -> torch.Tensor:
        if name not in self._arrays:
            raise KeyError(f"unknown feature: {name}")
        if period.step not in (None, 1):
            raise ValueError("only contiguous periods are supported")
        start = 0 if period.start is None else period.start
        stop = 1 if period.stop is None else period.stop
        if start < -self.max_backtrack_days:
            raise OutOfDataRangeError()
        if stop - 1 > self.max_future_days:
            raise OutOfDataRangeError()
        data_start = start + self.max_backtrack_days
        data_stop = stop + self.max_backtrack_days + self.n_days - 1
        values = self._arrays[name][data_start:data_stop]
        return torch.as_tensor(np.asarray(values), dtype=torch.float32)

    def target(self, horizon: int) -> torch.Tensor:
        if "close" not in self._arrays:
            raise KeyError("target construction requires a close feature")
        if horizon <= 0 or horizon > self.max_future_days:
            raise ValueError("target horizon must be within max_future_days")
        values = self.feature("close", slice(0, horizon + 1))
        current = values[: self.n_days]
        future = values[horizon : horizon + self.n_days]
        return future / current - 1
