"""Shared stock-code normalization and columnar panel reading helpers."""
from pathlib import Path
from typing import Optional, List

import pandas as pd


def normalize_code(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()



def read_panel(path: str | Path, columns: Optional[List[str]] = None) -> pd.DataFrame:
    path = Path(path)
    if path.is_dir():
        frames = []
        for child in sorted(path.glob("*.parquet")):
            frames.append(pd.read_parquet(child, columns=columns))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if path.suffix.lower() != ".parquet":
        raise ValueError("Runtime panels must be Parquet; CSV data sources are not supported")
    return pd.read_parquet(path, columns=columns)
