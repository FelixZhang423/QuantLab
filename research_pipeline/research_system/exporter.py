"""Export a versioned, independent research snapshot from existing system files."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .io import file_sha256, normalize_code, normalize_market_frame, validate_unique_keys, write_json
from .schema import (
    BACKTEST_METRIC_COLUMNS,
    MARKET_OPTIONAL_COLUMNS,
    MARKET_REQUIRED_COLUMNS,
    SNAPSHOT_VERSION,
    TABLE_FILENAMES,
)


@dataclass(frozen=True)
class ExportSources:
    market_panel: Path | str
    pool_dir: Path | str
    factor_runs_root: Path | str | None = None
    backtests_root: Path | str | None = None
    pool_id: str | None = None

    def resolved(self) -> "ExportSources":
        return ExportSources(
            market_panel=Path(self.market_panel).expanduser().resolve(),
            pool_dir=Path(self.pool_dir).expanduser().resolve(),
            factor_runs_root=None if self.factor_runs_root is None else Path(self.factor_runs_root).expanduser().resolve(),
            backtests_root=None if self.backtests_root is None else Path(self.backtests_root).expanduser().resolve(),
            pool_id=self.pool_id,
        )


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _pool_metadata(sources: ExportSources) -> tuple[str, dict[str, Any], list[str]]:
    pool_dir = Path(sources.pool_dir)
    codes_path = pool_dir / "codes.txt"
    manifest_path = pool_dir / "manifest.json"
    if not codes_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(f"pool requires codes.txt and manifest.json under {pool_dir}")
    metadata = _read_json(manifest_path)
    pool_id = str(sources.pool_id or metadata.get("pool_id") or pool_dir.name)
    codes = sorted({normalize_code(line) for line in codes_path.read_text(encoding="utf-8").splitlines() if normalize_code(line)})
    if not codes:
        raise ValueError(f"pool has no valid codes: {codes_path}")
    return pool_id, metadata, codes


def _read_market(path: Path, codes: Iterable[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"market panel is missing: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    frame = normalize_market_frame(frame)
    missing = set(MARKET_REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"market panel is missing required columns: {sorted(missing)}")
    validate_unique_keys(frame, ("date", "code"))
    selected = set(codes)
    frame = frame[frame["code"].isin(selected)].copy()
    columns = list(dict.fromkeys([*MARKET_REQUIRED_COLUMNS, *[col for col in MARKET_OPTIONAL_COLUMNS if col in frame.columns]]))
    return frame[columns].reset_index(drop=True)


def _factor_records(root: Path | None, pool_id: str) -> list[dict[str, Any]]:
    if root is None or not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for run_manifest_path in sorted(root.rglob("factor_run.json")):
        run_dir = run_manifest_path.parent
        run_manifest = _read_json(run_manifest_path)
        run_pool = str(run_manifest.get("pool_id") or pool_id)
        if run_pool != pool_id:
            continue
        for index, record in enumerate(_read_jsonl(run_dir / "accepted_factors.jsonl"), start=1):
            expression = str(record.get("expression") or record.get("canonical_expression") or "").strip()
            if not expression:
                continue
            factor_id = str(record.get("factor_id") or _factor_id(index, expression))
            item = {
                "factor_id": factor_id,
                "expression": expression,
                "canonical_expression": str(record.get("canonical_expression") or expression),
                "backtest_expression": str(record.get("backtest_expression") or record.get("canonical_expression") or expression),
                "factor_run_id": run_dir.name,
                "pool_id": run_pool,
                "source_signature": record.get("source_signature") or run_manifest.get("source_signature"),
                "accepted": bool(record.get("accepted", True)),
                "expected_direction": record.get("expected_direction"),
                "category": record.get("category"),
                "category_source": record.get("category_source"),
                "rationale": record.get("rationale"),
                "source_path": str((run_dir / "accepted_factors.jsonl").resolve()),
            }
            item["_raw"] = record
            records.append(item)
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped.setdefault(record["factor_id"], record)
    return list(deduped.values())


def _factor_tables(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    catalog_columns = [
        "factor_id", "expression", "canonical_expression", "backtest_expression", "factor_run_id",
        "pool_id", "source_signature", "accepted", "expected_direction", "category", "category_source",
        "rationale", "source_path",
    ]
    catalog = pd.DataFrame([{key: record.get(key) for key in catalog_columns} for record in records], columns=catalog_columns)
    metric_rows: list[dict[str, Any]] = []
    metric_names = ("score", "ic", "rank_ic", "icir", "rank_icir", "coverage", "sample_count")
    for record in records:
        raw = record.get("_raw", {})
        nested = raw.get("generation_metrics") if isinstance(raw.get("generation_metrics"), dict) else {}
        row = {
            "factor_id": record["factor_id"],
            "metric_scope": "generation",
            "split": str(raw.get("split") or "train"),
            "horizon": raw.get("horizon"),
            "calculated_at": raw.get("calculated_at"),
        }
        for name in metric_names:
            row[name] = nested.get(name, raw.get(name))
        metric_rows.append(row)
    metric_columns = ["factor_id", "metric_scope", "split", "horizon", *metric_names, "calculated_at"]
    return catalog, pd.DataFrame(metric_rows, columns=metric_columns)


def _backtest_table(root: Path | None, pool_id: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if root is None or not root.exists():
        warnings.append("backtests_root is not configured or does not exist")
        return pd.DataFrame(columns=BACKTEST_METRIC_COLUMNS), warnings
    frames: list[pd.DataFrame] = []
    for summary_path in sorted(root.rglob("factor_backtest_summary.csv")):
        frame = pd.read_csv(summary_path)
        if "pool_id" in frame.columns:
            frame = frame[frame["pool_id"].astype(str) == pool_id]
        if frame.empty:
            continue
        frame = frame.copy()
        frame["backtest_run_id"] = summary_path.parent.name
        frame["source_path"] = str(summary_path.resolve())
        rename: dict[str, str] = {}
        drop_prefixed: list[str] = []
        for column in frame.columns:
            if column.startswith("backtest_") and column not in {"backtest_run_id"}:
                target = column[len("backtest_"):]
                # Historical summaries may contain both `sharpe` and
                # `backtest_sharpe`; keep the already canonical column.
                if target in frame.columns:
                    drop_prefixed.append(column)
                else:
                    rename[column] = target
        if drop_prefixed:
            frame = frame.drop(columns=drop_prefixed)
        frame = frame.rename(columns=rename)
        frame["split"] = frame.get("split", "unknown")
        frame["start_date"] = frame.get("start_date")
        frame["end_date"] = frame.get("end_date")
        frames.append(frame)
    if not frames:
        warnings.append("no factor_backtest_summary.csv found for the selected pool")
        return pd.DataFrame(columns=BACKTEST_METRIC_COLUMNS), warnings
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "factor_id" not in combined.columns:
        warnings.append("backtest summaries were found but have no factor_id column")
    return combined, warnings


def _factor_id(index: int, expression: str) -> str:
    digest = hashlib.sha256(expression.encode("utf-8")).hexdigest()[:10]
    return f"factor_{index:04d}_{digest}"


def _table_manifest(snapshot_dir: Path, filename: str) -> dict[str, Any]:
    path = snapshot_dir / filename
    if not path.exists():
        return {"path": filename, "rows": 0, "columns": [], "sha256": None}
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)
    dates = pd.to_datetime(frame["date"], errors="coerce") if "date" in frame.columns else pd.Series(dtype="datetime64[ns]")
    return {
        "path": filename,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "date_min": None if dates.empty or dates.dropna().empty else str(dates.min().date()),
        "date_max": None if dates.empty or dates.dropna().empty else str(dates.max().date()),
        "sha256": file_sha256(path),
    }


def export_snapshot(
    sources: ExportSources,
    output_root: str | Path,
    snapshot_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export one immutable snapshot and advance the current pointer on success."""
    sources = sources.resolved()
    output_path = Path(output_root).expanduser().resolve()
    pool_id, pool_metadata, codes = _pool_metadata(sources)
    if snapshot_id is None:
        source_key = json.dumps({"pool": pool_id, "source": pool_metadata.get("source_signature"), "market": str(sources.market_panel)}, sort_keys=True)
        snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(source_key.encode()).hexdigest()[:10]}"
    snapshot_dir = output_path / "snapshots" / snapshot_id
    if snapshot_dir.exists() and not overwrite:
        raise FileExistsError(f"snapshot already exists: {snapshot_dir}")
    if snapshot_dir.exists() and overwrite:
        shutil.rmtree(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    warnings: list[str] = []
    try:
        market = _read_market(sources.market_panel, codes)
        market.to_parquet(snapshot_dir / "market.parquet", index=False)
        universe = pd.DataFrame({
            "code": codes,
            "pool_id": pool_id,
            "selected_at": pool_metadata.get("selection_end"),
            "source_signature": pool_metadata.get("source_signature"),
        })
        universe.to_csv(snapshot_dir / "universe.csv", index=False, encoding="utf-8-sig")

        factors = _factor_records(sources.factor_runs_root, pool_id)
        catalog, factor_metrics = _factor_tables(factors)
        catalog.to_parquet(snapshot_dir / "factor_catalog.parquet", index=False)
        factor_metrics.to_parquet(snapshot_dir / "factor_metrics.parquet", index=False)

        backtests, backtest_warnings = _backtest_table(sources.backtests_root, pool_id)
        warnings.extend(backtest_warnings)
        backtests.to_parquet(snapshot_dir / "backtest_metrics.parquet", index=False)
        backtests[[column for column in ("backtest_run_id", "source_path") if column in backtests.columns]].drop_duplicates().to_csv(
            snapshot_dir / "backtest_runs.csv", index=False, encoding="utf-8-sig"
        )
        if not (snapshot_dir / "backtest_runs.csv").exists():
            pd.DataFrame(columns=["backtest_run_id", "source_path"]).to_csv(snapshot_dir / "backtest_runs.csv", index=False)

        source_metadata = {
            "market_panel": str(sources.market_panel),
            "pool_dir": str(sources.pool_dir),
            "factor_runs_root": None if sources.factor_runs_root is None else str(sources.factor_runs_root),
            "backtests_root": None if sources.backtests_root is None else str(sources.backtests_root),
            "pool_manifest": pool_metadata,
        }
        write_json(snapshot_dir / "source_metadata.json", source_metadata)
        files = [_table_manifest(snapshot_dir, filename) for filename in TABLE_FILENAMES]
        manifest = {
            "snapshot_version": SNAPSHOT_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pool_id": pool_id,
            "n_codes": len(codes),
            "factor_count": int(len(catalog)),
            "warnings": warnings,
            "files": files,
            "valid": True,
        }
        write_json(snapshot_dir / "manifest.json", manifest)
        output_path.mkdir(parents=True, exist_ok=True)
        write_json(output_path / "manifest.json", {"current_snapshot": snapshot_id, "updated_at": manifest["created_at"]})
        (output_path / "current.txt").write_text(f"{snapshot_id}\n", encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
