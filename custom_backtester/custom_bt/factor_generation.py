from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from custom_bt.data import load_meta, normalize_code
from custom_bt.pools import load_pool_codes, load_pool_manifest


def _close_panel(panel) -> None:
    arrays = getattr(panel, "_arrays", {})
    for array in arrays.values():
        mmap = getattr(array, "_mmap", None)
        if mmap is not None:
            mmap.close()
    arrays.clear()


def _single_factor_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def new_factor_run_id(pool_id: str, runtime_id: str) -> str:
    """Create a unique factor run id so default generation starts from a clean run."""
    safe_pool = str(pool_id).strip() or "pool"
    safe_runtime = str(runtime_id).strip() or "runtime"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_pool}_{safe_runtime}_{stamp}_{uuid4().hex[:8]}"


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


def prepare_factor_runtime(
    master_store: str | Path,
    pools_root: str | Path,
    pool_id: str,
    runtime_root: str | Path,
    fields: Iterable[str],
    splits: Mapping[str, Mapping[str, str]],
    max_backtrack_days: int = 100,
    target_horizon: int = 20,
    max_future_days: int = 20,
) -> dict:
    """Create pool-specific processed panel and train/valid/test caches."""
    if not splits:
        raise ValueError("splits must not be empty")
    selected_fields = list(dict.fromkeys(str(field) for field in fields))
    if "close" not in selected_fields:
        raise ValueError("factor runtime fields must include close")
    pool_manifest = load_pool_manifest(pools_root, pool_id)
    meta = load_meta(master_store)
    if pool_manifest.get("source_signature") != meta.get("source_signature"):
        raise ValueError("pool source signature does not match master store")
    split_payload = {
        name: {"cache_start": str(value["cache_start"]), "cache_end": str(value["cache_end"])}
        for name, value in sorted(splits.items())
    }
    runtime_key = {
        "pool_id": pool_id,
        "fields": selected_fields,
        "splits": split_payload,
        "max_backtrack_days": max_backtrack_days,
        "target_horizon": target_horizon,
        "max_future_days": max_future_days,
    }
    runtime_id = hashlib.sha256(json.dumps(runtime_key, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    runtime_dir = Path(runtime_root).expanduser().resolve() / pool_id / runtime_id
    processed_dir = runtime_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    pool_codes = load_pool_codes(pools_root, pool_id)
    all_starts = [pd.Timestamp(value["cache_start"]) for value in splits.values()]
    all_ends = [pd.Timestamp(value["cache_end"]) for value in splits.values()]
    panel_result = export_pool_panel(
        master_store,
        pool_codes,
        selected_fields,
        processed_dir / "panel.parquet",
        start_date=str(min(all_starts).date()),
        end_date=str(max(all_ends).date()),
    )

    _single_factor_root()
    from single_factor.preprocess import materialize_memmap

    split_results: Dict[str, dict] = {}
    for name, split in splits.items():
        cache_dir = runtime_dir / name
        manifest = materialize_memmap(
            processed_dir=processed_dir,
            output_dir=cache_dir,
            codes=pool_codes,
            fields=selected_fields,
            start=split["cache_start"],
            end=split["cache_end"],
        )
        split_results[name] = {
            "cache_dir": str(cache_dir),
            "cache_start": str(split["cache_start"]),
            "cache_end": str(split["cache_end"]),
            "manifest": manifest,
        }
    result = {
        "runtime_id": runtime_id,
        "runtime_dir": str(runtime_dir),
        "processed_dir": str(processed_dir),
        "pool_id": pool_id,
        "source_signature": meta.get("source_signature"),
        "fields": selected_fields,
        "pool_codes": pool_codes,
        "max_backtrack_days": max_backtrack_days,
        "target_horizon": target_horizon,
        "max_future_days": max_future_days,
        "panel": panel_result,
        "splits": split_results,
    }
    (runtime_dir / "runtime_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return result


def run_factor_generation(
    master_store: str | Path,
    pools_root: str | Path,
    pool_id: str,
    runtime_root: str | Path,
    factor_runs_root: str | Path,
    fields: Iterable[str],
    splits: Mapping[str, Mapping[str, str]],
    max_backtrack_days: int = 100,
    target_horizon: int = 20,
    max_future_days: int = 20,
    generation_config: Optional[Mapping[str, object]] = None,
    ppo_runner=None,
) -> dict:
    """Prepare a pool runtime and run the existing PPO factor generator."""
    config = dict(generation_config or {})
    runtime = prepare_factor_runtime(
        master_store=master_store,
        pools_root=pools_root,
        pool_id=pool_id,
        runtime_root=runtime_root,
        fields=fields,
        splits=splits,
        max_backtrack_days=max_backtrack_days,
        target_horizon=target_horizon,
        max_future_days=max_future_days,
    )
    _single_factor_root()
    from single_factor.config import QualityConfig
    from single_factor.data import PanelData
    from single_factor.evaluator import SingleFactorEvaluator
    from single_factor.features import FeatureRegistry
    from single_factor.runner import run_with_ppo

    panel_kwargs = {
        "max_backtrack_days": int(max_backtrack_days),
        "max_future_days": int(max_future_days),
    }
    train_cache = runtime["splits"].get("train")
    if train_cache is None:
        raise ValueError("factor generation requires a train split")
    valid_cache = runtime["splits"].get("valid")
    test_cache = runtime["splits"].get("test")
    train_panel = PanelData.from_memmap(train_cache["cache_dir"], **panel_kwargs)
    valid_panel = PanelData.from_memmap(valid_cache["cache_dir"], **panel_kwargs) if valid_cache else None
    test_panel = PanelData.from_memmap(test_cache["cache_dir"], **panel_kwargs) if test_cache else None
    quality = QualityConfig(**dict(config.get("quality", {})))
    evaluator = SingleFactorEvaluator(
        train_panel=train_panel,
        valid_panel=valid_panel,
        test_panel=test_panel,
        target_horizon=int(target_horizon),
        quality=quality,
    )
    registry = FeatureRegistry(runtime["fields"])
    runtime_id = runtime["runtime_id"]
    explicit_run_id = str(config.get("run_id") or "").strip()
    run_id = explicit_run_id or new_factor_run_id(pool_id, runtime_id)
    factor_run_dir = Path(factor_runs_root).expanduser().resolve() / run_id
    runner_function = ppo_runner or run_with_ppo
    try:
        runner = runner_function(
            feature_names=registry.names(),
            evaluator=evaluator,
            output_dir=factor_run_dir,
            target_count=int(config.get("target_factor_count", 50)),
            max_attempts=int(config.get("max_attempts", 100000)),
            dataset_signature=runtime["splits"]["train"]["manifest"]["signature"],
            total_timesteps_per_rollout=int(config.get("rollout_timesteps", 2048)),
            seed=int(config.get("seed", 0)),
            device=str(config.get("device", "cpu")),
            storage_metadata={
                "pool_id": pool_id,
                "source_signature": runtime["source_signature"],
                "runtime_id": runtime_id,
            },
        )
    finally:
        _close_panel(train_panel)
        if valid_panel is not None:
            _close_panel(valid_panel)
        if test_panel is not None:
            _close_panel(test_panel)
    result = {
        "run_id": run_id,
        "factor_run_dir": str(factor_run_dir),
        "pool_id": pool_id,
        "source_signature": runtime["source_signature"],
        "runtime_id": runtime_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "accepted_count": int(getattr(runner, "accepted_count", 0)),
        "attempts": int(getattr(runner, "attempts", 0)),
        "target_reached": bool(getattr(runner, "target_reached", False)),
        "attempts_exhausted": bool(getattr(runner, "attempts_exhausted", False)),
        "runtime_manifest": str(Path(runtime["runtime_dir"]) / "runtime_manifest.json"),
    }
    factor_run_dir.mkdir(parents=True, exist_ok=True)
    (factor_run_dir / "factor_run.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
