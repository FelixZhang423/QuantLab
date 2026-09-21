"""Streaming stock-pool selection for the large daily source file."""

import json
import math
from pathlib import Path
from typing import Optional

import pandas as pd

from .preprocess import _detect_separator, _normalize_code, _read_header


def select_top_liquid_codes(
    source_csv: Path | str,
    output_file: Path | str,
    selection_start: str,
    selection_end: str,
    top_n: int = 500,
    min_listed_days: int = 250,
    min_coverage: float = 0.9,
    chunksize: int = 200_000,
    summary_file: Optional[Path | str] = None,
) -> dict:
    """Select liquid stocks without loading the full source into memory.

    Eligibility and average amount are computed only inside the explicit
    selection window, which should end before formal factor evaluation.
    """
    if top_n < 1:
        raise ValueError("top_n must be positive")
    if min_listed_days < 0:
        raise ValueError("min_listed_days cannot be negative")
    if not 0.0 <= min_coverage <= 1.0:
        raise ValueError("min_coverage must be between 0 and 1")
    if chunksize <= 0:
        raise ValueError("chunksize must be positive")

    source_path = Path(source_csv).expanduser().resolve()
    output_path = Path(output_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(selection_start)
    end = pd.Timestamp(selection_end)
    if start > end:
        raise ValueError("selection_start must not be after selection_end")

    separator = _detect_separator(source_path)
    available = set(_read_header(source_path, separator))
    required = {
        "code",
        "timestamps",
        "category",
        "amount",
        "vol",
        "Ifsuspend",
        "ListedDate",
    }
    missing = required - available
    if missing:
        raise ValueError(f"source is missing pool-selection columns: {sorted(missing)}")

    reader = pd.read_csv(
        source_path,
        usecols=sorted(required),
        chunksize=chunksize,
        sep=separator,
        low_memory=False,
    )
    selection_dates: set[pd.Timestamp] = set()
    stats: dict[str, dict[str, float]] = {}
    listed_cutoff = end - pd.Timedelta(days=min_listed_days)
    rows_read = 0

    for chunk in reader:
        rows_read += len(chunk)
        chunk["date"] = pd.to_datetime(chunk["timestamps"], errors="coerce")
        chunk = chunk[(chunk["date"] >= start) & (chunk["date"] <= end)]
        if chunk.empty:
            continue

        selection_dates.update(pd.to_datetime(chunk["date"]).dropna().unique())
        chunk = chunk[chunk["category"].astype(str).str.lower().eq("stock")].copy()
        if chunk.empty:
            continue

        chunk["code"] = chunk["code"].map(_normalize_code)
        chunk["amount"] = pd.to_numeric(chunk["amount"], errors="coerce")
        chunk["vol"] = pd.to_numeric(chunk["vol"], errors="coerce")
        chunk["Ifsuspend"] = pd.to_numeric(chunk["Ifsuspend"], errors="coerce")
        chunk["ListedDate"] = pd.to_datetime(chunk["ListedDate"], errors="coerce")
        valid = (
            chunk["amount"].notna()
            & (chunk["amount"] > 0)
            & chunk["vol"].notna()
            & (chunk["vol"] > 0)
            & (chunk["Ifsuspend"] == 0)
            & chunk["ListedDate"].notna()
            & (chunk["ListedDate"] <= listed_cutoff)
        )
        valid_rows = chunk.loc[valid, ["code", "amount"]]
        if valid_rows.empty:
            continue

        grouped = valid_rows.groupby("code")["amount"].agg(["sum", "count"])
        for code, row in grouped.iterrows():
            current = stats.setdefault(code, {"amount_sum": 0.0, "valid_rows": 0.0})
            current["amount_sum"] += float(row["sum"])
            current["valid_rows"] += float(row["count"])

    n_selection_days = len(selection_dates)
    if n_selection_days == 0:
        raise ValueError("no dates found in the selection window")
    minimum_valid_rows = math.ceil(n_selection_days * min_coverage)
    candidates = []
    for code, values in stats.items():
        valid_rows = int(values["valid_rows"])
        if valid_rows < minimum_valid_rows:
            continue
        candidates.append(
            {
                "code": code,
                "average_amount": values["amount_sum"] / valid_rows,
                "valid_rows": valid_rows,
                "coverage": valid_rows / n_selection_days,
            }
        )
    candidates.sort(key=lambda row: (-row["average_amount"], row["code"]))
    selected = candidates[:top_n]
    if len(selected) < top_n:
        raise ValueError(
            f"only {len(selected)} stocks met the pool rules; required {top_n}"
        )

    codes = [row["code"] for row in selected]
    output_path.write_text("\n".join(codes) + "\n", encoding="utf-8")
    result = {
        "source_csv": str(source_path),
        "selection_start": start.strftime("%Y-%m-%d"),
        "selection_end": end.strftime("%Y-%m-%d"),
        "selection_days": n_selection_days,
        "rows_read": rows_read,
        "top_n": top_n,
        "min_listed_days": min_listed_days,
        "min_coverage": min_coverage,
        "minimum_valid_rows": minimum_valid_rows,
        "eligible_candidates": len(candidates),
        "selected_codes": codes,
        "selected_stats": selected,
        "output_file": str(output_path),
    }
    if summary_file is not None:
        summary_path = Path(summary_file).expanduser().resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["summary_file"] = str(summary_path)
    return result
