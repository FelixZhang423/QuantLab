import json
import hashlib
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


_SOURCE_ALIASES = {
    "date": "timestamps",
    "volume": "vol",
}


def _source_column(name: str, available: set[str]) -> str:
    source = _SOURCE_ALIASES.get(name, name)
    if source not in available:
        raise ValueError(f"source column for '{name}' was not found: '{source}'")
    return source


def _normalize_code(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()


def _normalize_chunk(
    chunk: pd.DataFrame,
    fields: Sequence[str],
    point_in_time_fields: Sequence[str] = (),
    codes: Optional[set[str]] = None,
) -> pd.DataFrame:
    renamed = chunk.rename(columns={"timestamps": "date", "vol": "volume"}).copy()
    renamed["code"] = renamed["code"].map(_normalize_code)
    renamed["date"] = pd.to_datetime(renamed["date"], errors="coerce")
    renamed = renamed.dropna(subset=["code", "date"])
    if codes is not None:
        renamed = renamed[renamed["code"].isin(codes)]
    if renamed.empty:
        return renamed.reindex(columns=["date", "code", *fields])

    for field in fields:
        renamed[field] = pd.to_numeric(renamed[field], errors="coerce")
    if point_in_time_fields:
        if "InfoPublDate" not in renamed.columns:
            raise ValueError("point-in-time fields require InfoPublDate")
        publication_dates = pd.to_datetime(renamed["InfoPublDate"], errors="coerce")
        for field in point_in_time_fields:
            if field not in fields:
                raise ValueError(f"point-in-time field is not selected: {field}")
            renamed.loc[publication_dates > renamed["date"], field] = np.nan

    columns = ["date", "code", *fields]
    return renamed[columns].sort_values(["date", "code"])


def _detect_separator(source_csv: Path) -> str:
    with source_csv.open("r", encoding="utf-8", errors="replace") as handle:
        header = handle.readline()
    return "\t" if header.count("\t") > header.count(",") else ","


def _read_header(source_csv: Path, separator: str) -> list[str]:
    return list(pd.read_csv(source_csv, sep=separator, nrows=0).columns)


def _write_metadata(
    output_dir: Path,
    source_csv: Path,
    fields: Sequence[str],
    rows_read: int,
    rows_written: int,
    dates: list[pd.Timestamp],
    codes: set[str],
    point_in_time_fields: Sequence[str],
    code_filter: Optional[set[str]],
) -> None:
    metadata = {
        "source_csv": str(source_csv),
        "fields": list(fields),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "n_codes": len(codes),
        "code_filter_count": None if code_filter is None else len(code_filter),
        "date_min": min(dates).strftime("%Y-%m-%d") if dates else None,
        "date_max": max(dates).strftime("%Y-%m-%d") if dates else None,
        "point_in_time_aligned": bool(point_in_time_fields),
        "point_in_time_fields": list(point_in_time_fields),
        "preprocess_version": 1,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def preprocess_csv(
    source_csv: Path | str,
    output_dir: Path | str,
    fields: Iterable[str],
    chunksize: int = 200_000,
    limit_rows: Optional[int] = None,
    overwrite: bool = False,
    point_in_time_fields: Iterable[str] = (),
    codes: Optional[Iterable[str]] = None,
) -> dict:
    """Convert selected columns from a large daily CSV into Parquet.

    The source file is streamed in chunks and only requested feature columns
    are read. The resulting Parquet file is the stable input for later cache
    materialization and factor generation.
    """
    source_path = Path(source_csv).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    panel_path = output_path / "panel.parquet"
    if panel_path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {panel_path}")
    if chunksize <= 0:
        raise ValueError("chunksize must be positive")

    selected_fields = tuple(dict.fromkeys(str(field) for field in fields))
    pit_fields = tuple(dict.fromkeys(str(field) for field in point_in_time_fields))
    code_filter = None if codes is None else {_normalize_code(code) for code in codes}
    if code_filter is not None and not code_filter:
        raise ValueError("codes must contain at least one stock code")
    if not selected_fields:
        raise ValueError("fields must contain at least one feature")

    separator = _detect_separator(source_path)
    available = set(_read_header(source_path, separator))
    source_fields = [_source_column(field, available) for field in selected_fields]
    read_columns = list(dict.fromkeys(["code", "timestamps", *source_fields]))
    if pit_fields:
        if "InfoPublDate" not in available:
            raise ValueError("point-in-time fields require an InfoPublDate column")
        read_columns.append("InfoPublDate")

    if panel_path.exists():
        panel_path.unlink()

    writer: Optional[pq.ParquetWriter] = None
    schema: Optional[pa.Schema] = None
    rows_read = 0
    rows_written = 0
    dates: list[pd.Timestamp] = []
    codes: set[str] = set()
    reader = pd.read_csv(
        source_path,
        usecols=read_columns,
        chunksize=chunksize,
        nrows=limit_rows,
        sep=separator,
        low_memory=False,
    )

    try:
        for chunk in reader:
            rows_read += len(chunk)
            prepared = _normalize_chunk(
                chunk,
                selected_fields,
                pit_fields,
                code_filter,
            )
            if prepared.empty:
                continue
            table = pa.Table.from_pandas(
                prepared,
                preserve_index=False,
            )
            if writer is None:
                schema = table.schema
                writer = pq.ParquetWriter(panel_path, schema=schema, compression="zstd")
            elif schema is not None:
                table = table.cast(schema)
            writer.write_table(table)
            rows_written += len(prepared)
            dates.extend(prepared["date"].tolist())
            codes.update(prepared["code"].tolist())
    finally:
        if writer is not None:
            writer.close()

    if rows_written == 0:
        raise ValueError("no valid rows were written")

    _write_metadata(
        output_dir=output_path,
        source_csv=source_path,
        fields=selected_fields,
        rows_read=rows_read,
        rows_written=rows_written,
        dates=dates,
        codes=codes,
        point_in_time_fields=pit_fields,
        code_filter=code_filter,
    )
    return json.loads((output_path / "metadata.json").read_text(encoding="utf-8"))


def materialize_memmap(
    processed_dir: Path | str,
    output_dir: Path | str,
    codes: Optional[Sequence[str]],
    fields: Sequence[str],
    start: str,
    end: str,
) -> dict:
    """Create date-by-stock NumPy arrays from the processed Parquet panel."""
    processed_path = Path(processed_dir).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    panel_path = processed_path / "panel.parquet"
    selected_fields = tuple(dict.fromkeys(str(field) for field in fields))
    if not selected_fields:
        raise ValueError("fields must contain at least one feature")

    filters = [
        ("date", ">=", pd.Timestamp(start)),
        ("date", "<=", pd.Timestamp(end)),
    ]
    requested_codes = None if codes is None else tuple(sorted(set(codes)))
    if requested_codes:
        filters.append(("code", "in", list(requested_codes)))
    frame = pd.read_parquet(
        panel_path,
        columns=["date", "code", *selected_fields],
        filters=filters,
    )
    if frame.empty:
        raise ValueError("no rows matched the requested date and stock pool")

    frame["date"] = pd.to_datetime(frame["date"])
    frame["code"] = frame["code"].astype(str)
    frame = frame.drop_duplicates(["date", "code"], keep="last")
    dates = pd.DatetimeIndex(sorted(frame["date"].unique()))
    selected_codes = list(requested_codes or sorted(frame["code"].unique()))
    selected_codes = [code for code in selected_codes if code in set(frame["code"])]
    if not selected_codes or len(dates) == 0:
        raise ValueError("no stocks or dates remain after alignment")

    date_index = pd.DatetimeIndex(dates)
    code_index = pd.Index(selected_codes, name="code")
    for field in selected_fields:
        values = (
            frame.pivot(index="date", columns="code", values=field)
            .reindex(index=date_index, columns=code_index)
            .to_numpy(dtype=np.float32)
        )
        memmap = np.lib.format.open_memmap(
            output_path / f"{field}.npy",
            mode="w+",
            dtype=np.float32,
            shape=values.shape,
        )
        memmap[:] = values
        memmap.flush()
        del memmap

    np.save(output_path / "dates.npy", date_index.to_numpy(dtype="datetime64[ns]"))
    (output_path / "codes.json").write_text(
        json.dumps(selected_codes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "feature_index.json").write_text(
        json.dumps({field: i for i, field in enumerate(selected_fields)}, indent=2),
        encoding="utf-8",
    )
    signature_input = {
        "fields": list(selected_fields),
        "codes": selected_codes,
        "dates": [date.strftime("%Y-%m-%d") for date in date_index],
    }
    signature = hashlib.sha256(
        json.dumps(signature_input, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest = {
        **signature_input,
        "n_days": len(date_index),
        "n_stocks": len(selected_codes),
        "signature": signature,
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
