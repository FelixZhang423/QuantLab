from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from repositories import company_source
from repositories.local_store import normalize_code
from repositories.pool_store import load_pool_codes, load_pool_manifest, write_pool

logger = logging.getLogger(__name__)


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
    """Select a stock pool using company ClickHouse statistics."""
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
