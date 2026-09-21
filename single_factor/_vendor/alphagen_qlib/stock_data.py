from enum import IntEnum
from typing import Any


class FeatureType(IntEnum):
    """Compatibility enum for the vendored AlphaGen expression API."""

    OPEN = 0
    CLOSE = 1
    HIGH = 2
    LOW = 3
    VOLUME = 4
    VWAP = 5


class StockData:
    """Type-only compatibility placeholder; PanelData is used at runtime."""

    max_backtrack_days: int
    max_future_days: int
    n_days: int
    n_stocks: int
    data: Any
