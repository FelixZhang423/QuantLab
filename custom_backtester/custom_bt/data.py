from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

import pandas as pd
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


CORE_COLUMNS = [
    "code",
    "timestamps",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "ChangePCT",
    "TurnoverRate",
    "Ifsuspend",
    "if_up",
    "if_flat",
    "if_down",
    "ema12",
    "ema26",
    "dif",
    "dea",
    "macd",
    "RSV",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "ma5",
    "ma20",
    "ma4",
    "ma8",
    "ma12",
    "ma16",
    "ma47",
]

STOCK_LIST_FILENAME = "stock_list.csv"

_POOL_TEXT_COLUMNS = {
    "market_code",
    "category",
    "ChiName",
    "ChiNameAbbr",
    "EngName",
    "EngNameAbbr",
    "SecuAbbr",
    "ChiSpelling",
    "SecuMarket",
    "SecuCategory",
    "ListedSector",
    "ListedState",
    "ISIN",
    "ExtendedAbbr",
    "ExtendedSpelling",
    "InfoSource",
    "BulletinType",
    "AccountingStandards",
    "Mark",
    "ModifiedAuditOpinion",
}
_POOL_DATE_COLUMNS = {"ListedDate", "InfoPublDate", "EndDate"}


def normalize_code(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()


def prepare_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    df = chunk.rename(columns={"timestamps": "date", "vol": "volume"}).copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["code"] = df["code"].map(normalize_code)
    for col in _POOL_DATE_COLUMNS.intersection(df.columns):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in _POOL_TEXT_COLUMNS.intersection(df.columns):
        df[col] = df[col].astype("string")
    numeric_cols = [
        col
        for col in df.columns
        if col not in {"date", "code"}
        and col not in _POOL_TEXT_COLUMNS
        and col not in _POOL_DATE_COLUMNS
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    required = ["date", "code", "open", "close", "high", "low", "volume", "amount"]
    df = df.dropna(subset=required)
    df = df[df["volume"] > 0]
    df["vwap"] = df["amount"] / df["volume"]
    return df.sort_values(["date", "code"])


def read_panel(path: str | Path, columns: Optional[List[str]] = None) -> pd.DataFrame:
    path = Path(path)
    if path.is_dir():
        frames = []
        for child in sorted(path.glob("*.parquet")):
            frames.append(pd.read_parquet(child, columns=columns))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return pd.read_parquet(path, columns=columns)


def _field_catalog_from_files(stock_dir: Path) -> List[Dict[str, str]]:
    dtypes: Dict[str, str] = {}
    for path in sorted(stock_dir.glob("*.parquet")):
        schema = pq.read_schema(path)
        for field in schema:
            if field.name in {"date", "code"}:
                continue
            dtypes.setdefault(field.name, str(field.type))
    return [{"name": name, "dtype": dtype} for name, dtype in sorted(dtypes.items())]


def _fields_from_files(stock_dir: Path) -> List[str]:
    fields = set()
    for path in sorted(stock_dir.glob("*.parquet")):
        schema = pq.read_schema(path)
        fields.update(field.name for field in schema)
    return sorted(fields)


def _count_rows(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def _pandas_dtype_label(dtype: str) -> str:
    if dtype in {"double", "float"}:
        return "float64"
    if dtype.startswith("int") or dtype.startswith("uint"):
        return "int64"
    if "timestamp" in dtype:
        return "datetime64[ns]"
    return dtype


def _normalize_catalog_dtypes(catalog: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [{"name": item["name"], "dtype": _pandas_dtype_label(item["dtype"])} for item in catalog]


def load_meta(store_dir: str | Path) -> Dict[str, object]:
    meta_path = Path(store_dir) / "meta.json"
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def list_store_fields(store_dir: str | Path) -> List[Dict[str, str]]:
    meta = load_meta(store_dir)
    catalog = meta.get("field_catalog")
    if isinstance(catalog, list):
        return catalog
    path = Path(store_dir) / "stocks"
    if not path.exists():
        return []
    panel = read_panel(path)
    if panel.empty:
        return []
    return [
        {"name": col, "dtype": str(panel[col].dtype)}
        for col in panel.columns
        if col not in {"date", "code"}
    ]


def list_store_stocks(store_dir: str | Path) -> List[Dict[str, object]]:
    stock_dir = Path(store_dir) / "stocks"
    if not stock_dir.exists():
        return []
    rows: List[Dict[str, object]] = []
    wanted = ["date", "code", "open", "close", "volume", "amount"]
    for path in sorted(stock_dir.glob("*.parquet")):
        schema_names = set(pq.read_schema(path).names)
        columns = [col for col in wanted if col in schema_names]
        if not {"date", "code"}.issubset(columns):
            continue
        df = pd.read_parquet(path, columns=columns)
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        if df.empty:
            continue
        latest = df.iloc[-1]
        rows.append(
            {
                "code": normalize_code(latest.get("code", path.stem)),
                "rows": int(pq.ParquetFile(path).metadata.num_rows),
                "start_date": str(df["date"].iloc[0].date()),
                "end_date": str(df["date"].iloc[-1].date()),
                "latest_date": str(latest["date"].date()),
                "latest_open": None if "open" not in df.columns or pd.isna(latest.get("open")) else float(latest["open"]),
                "latest_close": None if "close" not in df.columns or pd.isna(latest.get("close")) else float(latest["close"]),
                "latest_volume": None if "volume" not in df.columns or pd.isna(latest.get("volume")) else float(latest["volume"]),
                "latest_amount": None if "amount" not in df.columns or pd.isna(latest.get("amount")) else float(latest["amount"]),
            }
        )
    return rows


def stock_list_path(store_dir: str | Path) -> Path:
    return Path(store_dir) / STOCK_LIST_FILENAME


def save_store_stock_list(store_dir: str | Path, out: str | Path | None = None) -> Dict[str, object]:
    store_dir = Path(store_dir)
    rows = list_store_stocks(store_dir)
    out_path = Path(out) if out is not None else stock_list_path(store_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    return {"stocks": len(rows), "path": str(out_path.resolve())}


def load_store_stock_list(store_dir: str | Path) -> List[Dict[str, object]]:
    path = stock_list_path(store_dir)
    if not path.exists():
        return []
    return pd.read_csv(path, dtype={"code": str}).to_dict("records")


def _write_meta(store_dir: Path, rows: int, fields: List[str], field_catalog: List[Dict[str, str]]) -> None:
    files = sorted((store_dir / "stocks").glob("*.parquet"))
    date_min = None
    date_max = None
    for path in files:
        df = pd.read_parquet(path, columns=["date"])
        if df.empty:
            continue
        cur_min = pd.to_datetime(df["date"]).min()
        cur_max = pd.to_datetime(df["date"]).max()
        date_min = cur_min if date_min is None else min(date_min, cur_min)
        date_max = cur_max if date_max is None else max(date_max, cur_max)
    meta = {
        "rows": rows,
        "n_stocks": len(files),
        "fields": fields,
        "date_min": None if date_min is None else str(date_min.date()),
        "date_max": None if date_max is None else str(date_max.date()),
        "layout": "per_stock_parquet",
        "field_catalog": field_catalog,
    }
    (store_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _detect_delimiter(csv_path: str | Path) -> str:
    path = Path(csv_path).expanduser().resolve()
    with path.open("rb") as handle:
        header = handle.readline().decode("utf-8-sig", errors="replace")
    candidates = ["\t", ",", ";", "|"]
    delimiter = max(candidates, key=header.count)
    if header.count(delimiter) == 0:
        return ","
    return delimiter


def _resolve_delimiter(csv_path: str | Path, delimiter: Optional[str]) -> str:
    if delimiter is None or delimiter == "" or delimiter.lower() == "auto":
        return _detect_delimiter(csv_path)
    if delimiter in {"\\t", "tab", "TAB"}:
        return "\t"
    if len(delimiter) != 1:
        raise ValueError("delimiter must be one character, '\\t', 'tab', or 'auto'")
    return delimiter


def _source_signature(csv_path: str | Path, fields: Iterable[str], delimiter: str) -> str:
    path = Path(csv_path).expanduser().resolve()
    stat = path.stat()
    payload = {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "fields": sorted(set(str(field) for field in fields)),
        "delimiter": delimiter,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def update_store(
    csv_path: str | Path,
    store_dir: str | Path,
    chunksize: int = 200_000,
    columns: Optional[Iterable[str]] = None,
    limit_rows: Optional[int] = None,
    delimiter: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> Dict[str, object]:
    csv_path = Path(csv_path).expanduser().resolve()
    store_dir = Path(store_dir).expanduser().resolve()
    stock_dir = store_dir / "stocks"
    stock_dir.mkdir(parents=True, exist_ok=True)
    usecols = list(columns) if columns is not None else None
    source_delimiter = _resolve_delimiter(csv_path, delimiter)
    rows_in = 0
    rows_out = 0
    touched = set()
    staging_dir = store_dir / "_staging" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    staging_dir.mkdir(parents=True, exist_ok=True)
    reader = _iter_csv_chunks(
        csv_path,
        usecols,
        chunksize,
        limit_rows=limit_rows,
        delimiter=source_delimiter,
    )
    try:
        for chunk_idx, chunk in enumerate(reader):
            rows_in += len(chunk)
            prepared = prepare_chunk(chunk)
            rows_out += len(prepared)
            for code, group in prepared.groupby("code", sort=False):
                code_dir = staging_dir / code
                code_dir.mkdir(parents=True, exist_ok=True)
                group.to_parquet(code_dir / f"part_{chunk_idx:06d}.parquet", index=False)
                touched.add(code)
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "importing",
                        "rows_read": rows_in,
                        "rows_written": rows_out,
                        "stocks_touched": len(touched),
                    }
                )
        for code in sorted(touched):
            path = stock_dir / f"{code}.parquet"
            parts = [pd.read_parquet(item) for item in sorted((staging_dir / code).glob("*.parquet"))]
            incoming = pd.concat(parts, ignore_index=True)
            if path.exists():
                old = pd.read_parquet(path)
                merged = pd.concat([old, incoming], ignore_index=True)
            else:
                merged = incoming
            merged = merged.sort_values("date").drop_duplicates("date", keep="last")
            tmp_path = path.with_suffix(".tmp.parquet")
            merged.to_parquet(tmp_path, index=False)
            tmp_path.replace(path)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        try:
            (store_dir / "_staging").rmdir()
        except OSError:
            pass
    fields = _fields_from_files(stock_dir)
    field_catalog = _normalize_catalog_dtypes(_field_catalog_from_files(stock_dir))
    total_rows = 0
    for path in stock_dir.glob("*.parquet"):
        total_rows += _count_rows(path)
    _write_meta(store_dir, total_rows, fields, field_catalog)
    return {
        "rows_read": rows_in,
        "rows_written": rows_out,
        "stocks_touched": len(touched),
        "delimiter": source_delimiter,
    }


def build_master_store(
    csv_path: str | Path,
    store_dir: str | Path,
    fields: Iterable[str],
    chunksize: int = 200_000,
    limit_rows: Optional[int] = None,
    overwrite: bool = False,
    delimiter: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> Dict[str, object]:
    """Build the reusable selected-field master cache from the source CSV."""
    store_path = Path(store_dir).expanduser().resolve()
    if overwrite and store_path.exists():
        shutil.rmtree(store_path)

    selected_fields = list(dict.fromkeys(str(field) for field in fields))
    requested_columns = list(dict.fromkeys([
        *CORE_COLUMNS,
        "market_code",
        "category",
        "ListedDate",
        "ListedSector",
        "ListedState",
        "StockBoard",
        *selected_fields,
    ]))
    source_delimiter = _resolve_delimiter(csv_path, delimiter)
    available_columns = set(pd.read_csv(csv_path, sep=source_delimiter, nrows=0).columns)
    required_columns = {"code", "timestamps", "open", "close", "high", "low", "vol", "amount"}
    missing_required = sorted(required_columns - available_columns)
    if missing_required:
        raise ValueError(f"source CSV is missing required columns: {missing_required}")
    source_columns = [column for column in requested_columns if column in available_columns]
    result = update_store(
        csv_path=csv_path,
        store_dir=store_path,
        chunksize=chunksize,
        columns=source_columns,
        limit_rows=limit_rows,
        delimiter=source_delimiter,
        progress_callback=progress_callback,
    )
    meta = load_meta(store_path)
    meta.update({
        "source_csv": str(Path(csv_path).expanduser().resolve()),
        "source_signature": _source_signature(csv_path, source_columns, source_delimiter),
        "selected_fields": selected_fields,
        "source_columns": source_columns,
        "delimiter": source_delimiter,
    })
    (store_path / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.update({
        "store_dir": str(store_path),
        "source_signature": meta["source_signature"],
        "n_stocks": meta["n_stocks"],
        "date_min": meta["date_min"],
        "date_max": meta["date_max"],
    })
    return result


def _iter_csv_chunks(
    csv_path: Path,
    usecols: Optional[List[str]],
    chunksize: int,
    limit_rows: Optional[int] = None,
    delimiter: str = ",",
) -> Iterator[pd.DataFrame]:
    convert_options = pacsv.ConvertOptions(include_columns=usecols) if usecols is not None else None
    read_options = pacsv.ReadOptions(block_size=1 << 20)
    parse_options = pacsv.ParseOptions(
        delimiter=delimiter,
        newlines_in_values=True,
        invalid_row_handler=lambda row: "skip",
    )
    reader = pacsv.open_csv(
        csv_path,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )
    pending = []
    pending_rows = 0
    rows_remaining = limit_rows
    for batch in reader:
        df = batch.to_pandas()
        if df.empty:
            continue
        if rows_remaining is not None:
            if rows_remaining <= 0:
                break
            df = df.iloc[:rows_remaining].copy()
            rows_remaining -= len(df)
        pending.append(df)
        pending_rows += len(df)
        if pending_rows >= chunksize:
            combined = pd.concat(pending, ignore_index=True)
            for start in range(0, len(combined), chunksize):
                piece = combined.iloc[start:start + chunksize].copy()
                if len(piece) == chunksize:
                    yield piece
                else:
                    pending = [piece]
                    pending_rows = len(piece)
            if pending_rows >= chunksize:
                pending = []
                pending_rows = 0
    if pending:
        yield pd.concat(pending, ignore_index=True)


def load_pool_panel(
    store_dir: str | Path,
    codes: Iterable[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Load only the requested stock codes from a per-stock master cache."""
    store_path = Path(store_dir)
    stock_dir = store_path / "stocks"
    frames: List[pd.DataFrame] = []
    missing: List[str] = []
    selected_codes = [normalize_code(code) for code in codes]
    for code in sorted(set(selected_codes)):
        path = stock_dir / f"{code}.parquet"
        if not path.exists():
            missing.append(code)
            continue
        frame = pd.read_parquet(path, columns=columns)
        if frame.empty:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        if start_date is not None:
            frame = frame[frame["date"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        if not frame.empty:
            frames.append(frame)
    if missing:
        raise FileNotFoundError(f"pool codes are missing from master store: {missing[:5]}")
    if not frames:
        return pd.DataFrame(columns=columns or [])
    return pd.concat(frames, ignore_index=True).sort_values(["date", "code"]).reset_index(drop=True)


def load_store(store_dir: str | Path, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    store_dir = Path(store_dir)
    panel = read_panel(store_dir / "stocks")
    if panel.empty:
        return panel
    panel["date"] = pd.to_datetime(panel["date"])
    if start_date is not None:
        panel = panel[panel["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        panel = panel[panel["date"] <= pd.Timestamp(end_date)]
    return panel.sort_values(["date", "code"]).reset_index(drop=True)
