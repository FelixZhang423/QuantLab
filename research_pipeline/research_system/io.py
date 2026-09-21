"""I/O helpers that only understand the independent research snapshot format."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .schema import TABLE_FILENAMES


def normalize_code(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()


def normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a source market panel without inventing or filling values."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("market data must be a pandas DataFrame")
    renamed = frame.rename(columns={"timestamps": "date", "vol": "volume"}).copy()
    missing = {"date", "code"} - set(renamed.columns)
    if missing:
        raise ValueError(f"market data is missing required columns: {sorted(missing)}")
    renamed["date"] = pd.to_datetime(renamed["date"], errors="coerce")
    renamed["code"] = renamed["code"].map(normalize_code)
    renamed = renamed.dropna(subset=["date"])
    renamed = renamed[renamed["code"] != ""]
    for column in renamed.columns:
        if column not in {"date", "code"}:
            renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    return renamed.sort_values(["date", "code"]).reset_index(drop=True)


def validate_unique_keys(frame: pd.DataFrame, keys: Iterable[str]) -> None:
    key_columns = tuple(keys)
    missing = set(key_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"missing key columns: {sorted(missing)}")
    if frame.duplicated(list(key_columns)).any():
        raise ValueError(f"duplicate keys found for {key_columns}")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: str | Path, payload: object) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def resolve_snapshot(data_root: str | Path, snapshot_id: str | None = None) -> Path:
    root = Path(data_root)
    selected = snapshot_id
    if selected is None:
        pointer = root / "current.txt"
        if not pointer.exists():
            raise FileNotFoundError(f"current snapshot pointer is missing: {pointer}")
        selected = pointer.read_text(encoding="utf-8").strip()
    if not selected:
        raise ValueError("snapshot id cannot be empty")
    snapshot = root / "snapshots" / selected
    if not snapshot.is_dir():
        raise FileNotFoundError(f"snapshot directory is missing: {snapshot}")
    return snapshot


def load_snapshot_table(
    data_root: str | Path,
    filename: str,
    snapshot_id: str | None = None,
) -> pd.DataFrame:
    if filename not in TABLE_FILENAMES:
        raise ValueError(f"unsupported snapshot table: {filename}")
    snapshot = resolve_snapshot(data_root, snapshot_id)
    path = snapshot / filename
    if not path.exists():
        raise FileNotFoundError(f"snapshot table is missing: {path}")
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
