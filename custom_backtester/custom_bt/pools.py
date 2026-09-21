from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pyarrow.parquet as pq

from custom_bt.data import load_meta, normalize_code


def _available_columns(path: Path) -> set[str]:
    return set(pq.read_schema(path).names)


def _load_candidate(
    path: Path,
    selection_start: pd.Timestamp,
    selection_end: pd.Timestamp,
    exclude_suspended: bool,
    category: Optional[str],
    market_code: Optional[str],
    min_listed_days: int,
) -> tuple[pd.DataFrame, set[pd.Timestamp]]:
    available = _available_columns(path)
    wanted = [
        column
        for column in [
            "date",
            "code",
            "amount",
            "volume",
            "Ifsuspend",
            "category",
            "market_code",
            "ListedDate",
        ]
        if column in available
    ]
    frame = pd.read_parquet(path, columns=wanted)
    if frame.empty:
        return frame, set()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[(frame["date"] >= selection_start) & (frame["date"] <= selection_end)]
    selection_dates = set(frame["date"].dropna().tolist())
    if frame.empty:
        return frame, selection_dates
    if category is not None and "category" in frame.columns:
        frame = frame[frame["category"].astype("string").str.lower() == str(category).lower()]
    if market_code is not None and "market_code" in frame.columns:
        frame = frame[frame["market_code"].astype("string") == str(market_code)]
    if exclude_suspended and "Ifsuspend" in frame.columns:
        frame = frame[pd.to_numeric(frame["Ifsuspend"], errors="coerce").fillna(1).eq(0)]
    if "volume" in frame.columns:
        frame = frame[pd.to_numeric(frame["volume"], errors="coerce").fillna(0).gt(0)]
    if "amount" in frame.columns:
        frame = frame[pd.to_numeric(frame["amount"], errors="coerce").fillna(0).gt(0)]
    if min_listed_days > 0:
        if "ListedDate" not in frame.columns:
            return frame.iloc[0:0], selection_dates
        listed = pd.to_datetime(frame["ListedDate"], errors="coerce")
        frame = frame[(frame["date"] - listed).dt.days >= min_listed_days]
    return frame, selection_dates


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
        frame, dates = _load_candidate(
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
    if top_n is not None and len(selected) < top_n:
        raise ValueError(f"only {len(selected)} stocks met the pool rules; required {top_n}")
    if not selected:
        raise ValueError("no stocks met the pool rules")

    selected_codes = [row["code"] for row in selected]
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
        "selected_codes": selected_codes,
        "n_stocks": len(selected_codes),
        "selection_days": len(selection_dates),
        "minimum_valid_rows": minimum_valid_rows,
        "selected_stats": selected,
    }
    digest = hashlib.sha256(json.dumps(manifest_base, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    pool_id = f"{name}_{digest}"
    pool_dir = pools_path / pool_id
    if pool_dir.exists() and not overwrite:
        raise FileExistsError(f"pool already exists: {pool_dir}")
    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / "codes.txt").write_text("\n".join(selected_codes) + "\n", encoding="utf-8")
    pd.DataFrame(selected).to_csv(pool_dir / "selection_summary.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "pool_id": pool_id,
        "codes_file": "codes.txt",
        **manifest_base,
    }
    (pool_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_pool_manifest(pools_root: str | Path, pool_id: str) -> dict:
    path = Path(pools_root).expanduser().resolve() / pool_id / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"pool manifest is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool_codes(pools_root: str | Path, pool_id: str) -> list[str]:
    manifest = load_pool_manifest(pools_root, pool_id)
    path = Path(pools_root).expanduser().resolve() / pool_id / manifest.get("codes_file", "codes.txt")
    if not path.exists():
        raise FileNotFoundError(f"pool code file is missing: {path}")
    return [normalize_code(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
