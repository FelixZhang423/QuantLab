from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import pyarrow.parquet as pq

from repositories import company_source
from repositories.local_store import load_meta, normalize_code
from repositories.pool_store import load_candidate, load_pool_codes, load_pool_manifest, write_pool

logger = logging.getLogger(__name__)


def create_pool(
    store_dir: str | Path,
    pools_root: str | Path,
    name: str,
    selection_start: str,
    selection_end: str,
    top_n: Optional[int] = None,
    min_listed_days: int = 0,
    min_coverage: float = 0.0,
    exclude_suspended: bool = True,
    category: Optional[str] = None,
    market_code: Optional[str] = None,
    codes: Optional[Iterable[str]] = None,
    overwrite: bool = False,
    strict_top_n: bool = True,
    provenance: Optional[dict[str, Any]] = None,
) -> dict:
    if not name.strip():
        raise ValueError("pool name must not be empty")
    if top_n is not None and top_n < 1:
        raise ValueError("top_n must be positive when provided")
    if not 0.0 <= min_coverage <= 1.0:
        raise ValueError("min_coverage must be between 0 and 1")
    if min_listed_days < 0:
        raise ValueError("min_listed_days must be non-negative")

    store_path = Path(store_dir).expanduser().resolve()
    pools_path = Path(pools_root).expanduser().resolve()
    meta = load_meta(store_path)
    if not meta:
        staging_path = store_path / "_staging"
        if staging_path.exists() and any(staging_path.iterdir()):
            raise FileNotFoundError(
                f"master store metadata is missing: {store_path / 'meta.json'}; "
                "master import job is still running or was interrupted, wait for it or rerun the import"
            )
        raise FileNotFoundError(f"master store metadata is missing: {store_path / 'meta.json'}")
    stock_dir = store_path / "stocks"
    if not stock_dir.exists():
        raise FileNotFoundError(f"master stock directory is missing: {stock_dir}")

    start = pd.Timestamp(selection_start)
    end = pd.Timestamp(selection_end)
    if start > end:
        raise ValueError("selection_start must not be after selection_end")
    requested_codes = None if codes is None else {normalize_code(code) for code in codes}
    if requested_codes is not None and not requested_codes:
        raise ValueError("codes must contain at least one stock code")

    selection_dates: set[pd.Timestamp] = set()
    candidates: list[dict] = []
    for path in sorted(stock_dir.glob("*.parquet")):
        if requested_codes is not None and normalize_code(path.stem) not in requested_codes:
            continue
        frame, dates = load_candidate(
            path,
            start,
            end,
            exclude_suspended,
            category,
            market_code,
            min_listed_days,
        )
        selection_dates.update(dates)
        if frame.empty:
            continue
        valid_rows = len(frame)
        amount = pd.to_numeric(frame["amount"], errors="coerce")
        candidates.append({
            "code": normalize_code(path.stem),
            "average_amount": float(amount.mean()),
            "valid_rows": int(valid_rows),
        })

    if not selection_dates:
        raise ValueError("no dates found in the selection window")
    minimum_valid_rows = int((len(selection_dates) * min_coverage + 0.9999999999) // 1)
    for row in candidates:
        row["coverage"] = row["valid_rows"] / len(selection_dates)
    candidates = [row for row in candidates if row["valid_rows"] >= minimum_valid_rows]
    candidates.sort(key=lambda row: (-row["average_amount"], row["code"]))
    selected = candidates if top_n is None else candidates[:top_n]
    if top_n is not None and len(selected) < top_n and strict_top_n:
        raise ValueError(f"only {len(selected)} stocks met the pool rules; required {top_n}")
    if not selected:
        raise ValueError("no stocks met the pool rules")

    manifest_base = {
        "name": name,
        "source_signature": meta.get("source_signature"),
        "selection_start": start.strftime("%Y-%m-%d"),
        "selection_end": end.strftime("%Y-%m-%d"),
        "top_n": top_n,
        "min_listed_days": min_listed_days,
        "min_coverage": min_coverage,
        "exclude_suspended": exclude_suspended,
        "category": category,
        "market_code": market_code,
        "requested_codes": sorted(requested_codes) if requested_codes is not None else None,
        "selected_codes": [row["code"] for row in selected],
        "n_stocks": len(selected),
        "selection_days": len(selection_dates),
        "minimum_valid_rows": minimum_valid_rows,
        "selected_stats": selected,
    }
    return write_pool(
        pools_path, manifest_base, strict_top_n=strict_top_n, overwrite=overwrite, provenance=provenance
    )


def create_pool_from_company(
    pools_root: str | Path,
    name: str,
    selection_start: str,
    selection_end: str,
    top_n: Optional[int] = None,
    min_listed_days: int = 0,
    min_coverage: float = 0.0,
    exclude_suspended: bool = True,
    category: Optional[str] = "stock",
    market_code: Optional[str] = None,
    codes: Optional[Iterable[str]] = None,
    overwrite: bool = False,
    strict_top_n: bool = True,
    provenance: Optional[dict[str, Any]] = None,
    settings: Optional[Any] = None,
    client: Optional[Any] = None,
) -> dict:
    """直接按公司 ClickHouse 建池（不再读取 ``data_cache/master``）。

    选样口径与 :func:`create_pool` 一致：窗口内交易日数 → 每只股票的
    有效行数/平均成交额 → 覆盖率 → 按成交额降序取 ``top_n``。
    """
    if not name.strip():
        raise ValueError("pool name must not be empty")
    if top_n is not None and top_n < 1:
        raise ValueError("top_n must be positive when provided")
    if not 0.0 <= min_coverage <= 1.0:
        raise ValueError("min_coverage must be between 0 and 1")
    if min_listed_days < 0:
        raise ValueError("min_listed_days must be non-negative")

    pools_path = Path(pools_root).expanduser().resolve()
    start = pd.Timestamp(selection_start)
    end = pd.Timestamp(selection_end)
    if start > end:
        raise ValueError("selection_start must not be after selection_end")
    requested_codes = None if codes is None else {normalize_code(code) for code in codes}
    if requested_codes is not None and not requested_codes:
        raise ValueError("codes must contain at least one stock code")

    days = company_source.selection_days(
        requested_codes,
        start,
        end,
        category=category,
        market_code=market_code,
        settings=settings,
        client=client,
    )
    if days <= 0:
        raise ValueError("no dates found in the selection window")
    stats = company_source.selection_stats(
        requested_codes,
        start,
        end,
        exclude_suspended=exclude_suspended,
        min_listed_days=min_listed_days,
        category=category,
        market_code=market_code,
        settings=settings,
        client=client,
    )

    minimum_valid_rows = int((days * min_coverage + 0.9999999999) // 1)
    candidates: list[dict] = []
    for row in stats:
        if row["valid_rows"] < minimum_valid_rows:
            continue
        candidates.append({**row, "coverage": row["valid_rows"] / days})
    candidates.sort(key=lambda row: (-row["average_amount"], row["code"]))
    selected = candidates if top_n is None else candidates[:top_n]
    if top_n is not None and len(selected) < top_n and strict_top_n:
        raise ValueError(f"only {len(selected)} stocks met the pool rules; required {top_n}")
    if not selected:
        raise ValueError("no stocks met the pool rules")

    manifest_base = {
        "name": name,
        "data_source": "clickhouse",
        "source_signature": company_source.source_signature(),
        "selection_start": start.strftime("%Y-%m-%d"),
        "selection_end": end.strftime("%Y-%m-%d"),
        "top_n": top_n,
        "min_listed_days": min_listed_days,
        "min_coverage": min_coverage,
        "exclude_suspended": exclude_suspended,
        "category": category,
        "market_code": market_code,
        "requested_codes": sorted(requested_codes) if requested_codes is not None else None,
        "selected_codes": [row["code"] for row in selected],
        "n_stocks": len(selected),
        "selection_days": days,
        "minimum_valid_rows": minimum_valid_rows,
        "selected_stats": selected,
    }
    return write_pool(
        pools_path, manifest_base, strict_top_n=strict_top_n, overwrite=overwrite, provenance=provenance
    )
