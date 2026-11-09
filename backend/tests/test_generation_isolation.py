import pandas as pd
import pytest
from custom_bt.generation_splits import validate_splits


def test_gap_uses_actual_sessions_not_calendar_days():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-09", "2024-01-10"])
    splits = {"train": {"cache_start": "2024-01-02", "cache_end": "2024-01-02"},
              "valid": {"cache_start": "2024-01-08", "cache_end": "2024-01-08"}}
    with pytest.raises(ValueError, match="隔离不足"):
        validate_splits(splits, dates, 2)
    splits["valid"]["cache_start"] = "2024-01-09"
    splits["valid"]["cache_end"] = "2024-01-09"
    assert validate_splits(splits, dates, 2)["gap_trading_days"]["train_valid"] == 2


def test_overlapping_splits_and_missing_test_are_rejected():
    splits = {"train": {"cache_start": "2024-01-01", "cache_end": "2024-01-10"},
              "valid": {"cache_start": "2024-01-08", "cache_end": "2024-01-20"}}
    with pytest.raises(ValueError, match="重叠"):
        validate_splits(splits, pd.bdate_range("2024-01-01", "2024-01-20"), 1)
    with pytest.raises(ValueError, match="三个"):
        validate_splits(splits, [], 1, require_all=True)
