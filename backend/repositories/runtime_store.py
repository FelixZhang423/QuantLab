"""因子生成运行时数据：把股票池面板导出为 AlphaGen 兼容 Parquet。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from repositories.local_store import normalize_code


def export_pool_panel(
    master_store: str | Path,
    pool_codes: Iterable[str],
    fields: Iterable[str],
    output_path: str | Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Stream selected per-stock files into one AlphaGen-compatible panel."""
    store_path = Path(master_store).expanduser().resolve()
    panel_path = Path(output_path).expanduser().resolve()
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    if panel_path.exists():
        panel_path.unlink()
    selected_fields = list(dict.fromkeys(str(field) for field in fields))
    columns = ["date", "code", *selected_fields]
    writer: Optional[pq.ParquetWriter] = None
    schema: Optional[pa.Schema] = None
    rows = 0
    codes_written: set[str] = set()
    date_min = None
    date_max = None
    for code in sorted({normalize_code(value) for value in pool_codes}):
        stock_path = store_path / "stocks" / f"{code}.parquet"
        if not stock_path.exists():
            raise FileNotFoundError(f"pool code is missing from master store: {code}")
        available = set(pq.read_schema(stock_path).names)
        missing = [column for column in columns if column not in available]
        if missing:
            raise ValueError(f"stock {code} is missing factor fields: {missing}")
        frame = pd.read_parquet(stock_path, columns=columns)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        if start_date is not None:
            frame = frame[frame["date"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        frame = frame.dropna(subset=["date"]).drop_duplicates(["date", "code"], keep="last")
        if frame.empty:
            continue
        frame = frame.sort_values(["date", "code"])
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(panel_path, schema=schema, compression="zstd")
        elif schema is not None:
            table = table.cast(schema)
        writer.write_table(table)
        rows += len(frame)
        codes_written.add(code)
        current_min = frame["date"].min()
        current_max = frame["date"].max()
        date_min = current_min if date_min is None else min(date_min, current_min)
        date_max = current_max if date_max is None else max(date_max, current_max)
    if writer is not None:
        writer.close()
    if rows == 0:
        raise ValueError("no rows remain for the requested pool panel")
    return {
        "panel_path": str(panel_path),
        "fields": selected_fields,
        "rows": rows,
        "n_stocks": len(codes_written),
        "date_min": str(pd.Timestamp(date_min).date()),
        "date_max": str(pd.Timestamp(date_max).date()),
    }
