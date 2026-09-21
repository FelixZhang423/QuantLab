import hashlib

import pandas as pd
import pytest

from research_pipeline.research_system.io import (
    file_sha256,
    normalize_market_frame,
    validate_unique_keys,
)


def test_normalize_market_frame_standardizes_aliases_and_codes():
    source = pd.DataFrame(
        {
            "timestamps": ["2024-01-02", "2024-01-02"],
            "code": [1, "000002"],
            "open": [10, 20],
            "close": [11, 19],
            "vol": [1000, 2000],
        }
    )

    result = normalize_market_frame(source)

    assert list(result.columns) == ["date", "code", "open", "close", "volume"]
    assert result["code"].tolist() == ["000001", "000002"]
    assert pd.api.types.is_datetime64_any_dtype(result["date"])
    assert result["volume"].tolist() == [1000.0, 2000.0]


def test_validate_unique_keys_rejects_duplicate_date_code():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "code": ["000001", "000001"],
        }
    )

    with pytest.raises(ValueError, match="duplicate keys"):
        validate_unique_keys(frame, ("date", "code"))


def test_file_sha256_matches_standard_digest(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"research")

    assert file_sha256(path) == hashlib.sha256(b"research").hexdigest()
