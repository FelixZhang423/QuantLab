import json
import hashlib
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


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
