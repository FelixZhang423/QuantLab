"""State-conditional factor evaluation over partitioned factor values."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .classification import infer_category
from .features import make_forward_return
from .io import resolve_snapshot, write_json


def assign_time_splits(
    dates: pd.Index | pd.Series | list[Any],
    train_ratio: float = 0.6,
    valid_ratio: float = 0.2,
) -> pd.Series:
    """Assign chronological train/valid/test labels to unique trading dates."""
    if not 0 < train_ratio < 1 or not 0 <= valid_ratio < 1:
        raise ValueError("train_ratio must be in (0, 1) and valid_ratio must be in [0, 1)")
    if train_ratio + valid_ratio >= 1:
        raise ValueError("train_ratio + valid_ratio must be less than 1")
    index = pd.DatetimeIndex(pd.to_datetime(pd.Index(dates), errors="coerce")).dropna().unique().sort_values()
    if index.empty:
        return pd.Series([], index=index, dtype="string")
    n = len(index)
    train_count = max(1, int(n * train_ratio))
    valid_count = int(n * valid_ratio)
    if n >= 3:
        valid_count = max(1, valid_count)
    if train_count + valid_count >= n:
        valid_count = max(0, n - train_count - 1)
    labels = ["train"] * train_count + ["valid"] * valid_count + ["test"] * (n - train_count - valid_count)
    return pd.Series(labels, index=index, dtype="string")


def _assert_run_snapshot(run_dir: Path, manifest_name: str, snapshot_id: str) -> None:
    manifest_path = run_dir / manifest_name
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid run manifest: {manifest_path}") from exc
    run_snapshot = str(manifest.get("snapshot_id") or "").strip()
    if run_snapshot and run_snapshot != snapshot_id:
        raise ValueError(
            f"snapshot mismatch: run={run_snapshot!r}, requested={snapshot_id!r}, path={run_dir}"
        )


def _corr(left: pd.Series, right: pd.Series, rank: bool = False) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 3:
        return float("nan")
    if rank:
        frame = frame.rank(method="average")
    if frame["left"].std(ddof=0) == 0 or frame["right"].std(ddof=0) == 0:
        return float("nan")
    return float(frame["left"].corr(frame["right"]))


def _daily_correlation(frame: pd.DataFrame, rank: bool = False) -> pd.DataFrame:
    valid = frame[["date", "value", "target"]].replace([np.inf, -np.inf], np.nan).dropna()
    if rank:
        valid[["value", "target"]] = valid.groupby("date")[["value", "target"]].rank(method="average")
    valid["xy"] = valid["value"] * valid["target"]
    valid["x2"] = valid["value"] ** 2
    valid["y2"] = valid["target"] ** 2
    stats = valid.groupby("date", sort=True).agg(
        valid_count=("value", "size"),
        sum_x=("value", "sum"),
        sum_y=("target", "sum"),
        sum_xy=("xy", "sum"),
        sum_x2=("x2", "sum"),
        sum_y2=("y2", "sum"),
    ).reset_index()
    numerator = stats["sum_xy"] - stats["sum_x"] * stats["sum_y"] / stats["valid_count"]
    left = stats["sum_x2"] - stats["sum_x"] ** 2 / stats["valid_count"]
    right = stats["sum_y2"] - stats["sum_y"] ** 2 / stats["valid_count"]
    denominator = np.sqrt(left.clip(lower=0) * right.clip(lower=0))
    stats["correlation"] = numerator / denominator.replace(0, np.nan)
    stats.loc[stats["valid_count"] < 3, "correlation"] = np.nan
    return stats[["date", "valid_count", "correlation"]]


def _evaluate_partition(
    values_path: Path,
    target: pd.DataFrame,
    states: pd.DataFrame,
    factor_id: str,
    category: str,
    horizon: int,
    split_by_date: pd.Series,
) -> list[dict[str, Any]]:
    values = pd.read_parquet(values_path, columns=["date", "code", "value"])
    values["date"] = pd.to_datetime(values["date"], errors="coerce")
    values["code"] = values["code"].astype(str)
    values["value"] = pd.to_numeric(values["value"], errors="coerce")
    labels = target.set_index(["date", "code"])["target"]
    key = pd.MultiIndex.from_frame(values[["date", "code"]])
    values["target"] = labels.reindex(key).to_numpy()
    pearson = _daily_correlation(values, rank=False).rename(columns={"correlation": "ic"})
    ranked = _daily_correlation(values, rank=True).rename(columns={"correlation": "rank_ic", "valid_count": "rank_valid_count"})
    daily = pearson.merge(ranked[["date", "rank_ic"]], on="date", how="outer")
    if daily.empty:
        return []
    daily["state_id"] = daily["date"].map(states.set_index("date")["state_id"])
    daily["split"] = daily["date"].map(split_by_date)
    rows: list[dict[str, Any]] = []
    for (state_id, split), group in daily.dropna(subset=["state_id", "split"]).groupby(["state_id", "split"], sort=True):
        ic = pd.to_numeric(group["ic"], errors="coerce").dropna()
        rank_ic = pd.to_numeric(group["rank_ic"], errors="coerce").dropna()
        rows.append({
            "factor_id": factor_id,
            "category": category,
            "category_source": "expression_structure",
            "state_id": str(state_id),
            "split": str(split),
            "horizon": horizon,
            "sample_count": int(len(ic)),
            "coverage": float((group["valid_count"] >= 3).mean()),
            "ic_mean": float(ic.mean()) if not ic.empty else float("nan"),
            "rank_ic_mean": float(rank_ic.mean()) if not rank_ic.empty else float("nan"),
            "icir": float(ic.mean() / ic.std(ddof=1)) if len(ic) >= 2 and ic.std(ddof=1) > 0 else float("nan"),
            "hit_rate": float((ic > 0).mean()) if not ic.empty else float("nan"),
            "stability": float(abs(ic.mean()) / ic.abs().mean()) if not ic.empty and ic.abs().mean() > 0 else float("nan"),
        })
    return rows


def run_conditional_evaluation(
    data_root: str | Path,
    values_run: str | Path,
    state_run: str | Path,
    runs_root: str | Path,
    snapshot_id: str | None = None,
    horizon: int = 20,
    max_factors: int | None = None,
    train_ratio: float = 0.6,
    valid_ratio: float = 0.2,
) -> dict[str, Any]:
    snapshot = resolve_snapshot(data_root, snapshot_id)
    market = pd.read_parquet(snapshot / "market.parquet")
    catalog = pd.read_parquet(snapshot / "factor_catalog.parquet")
    values_root = Path(values_run).expanduser().resolve() / "factor_values"
    state_path = Path(state_run).expanduser().resolve() / "market_states.parquet"
    if not values_root.exists():
        raise FileNotFoundError(f"factor values directory is missing: {values_root}")
    if not state_path.exists():
        raise FileNotFoundError(f"market states file is missing: {state_path}")
    _assert_run_snapshot(values_root.parent, "factor_values_manifest.json", snapshot.name)
    _assert_run_snapshot(state_path.parent, "manifest.json", snapshot.name)
    target = make_forward_return(market, horizon=horizon)
    states = pd.read_parquet(state_path, columns=["date", "state_id"])
    states["date"] = pd.to_datetime(states["date"], errors="coerce")
    split_by_date = assign_time_splits(target["date"], train_ratio=train_ratio, valid_ratio=valid_ratio)
    partitions = sorted(values_root.glob("factor_id=*/values.parquet"))
    if max_factors is not None:
        partitions = partitions[:max_factors]
    catalog_by_id = catalog.assign(factor_id=catalog["factor_id"].astype(str)).set_index("factor_id")
    all_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for values_path in partitions:
        factor_id = values_path.parent.name.split("=", 1)[-1]
        expression = str(catalog_by_id.loc[factor_id].get("expression", "")) if factor_id in catalog_by_id.index else ""
        category = infer_category(expression)["category"]
        try:
            all_rows.extend(_evaluate_partition(values_path, target, states, factor_id, category, horizon, split_by_date))
        except Exception as exc:
            errors.append({"factor_id": factor_id, "error": f"{type(exc).__name__}: {exc}"})
    seed = json.dumps({"snapshot": snapshot.name, "values_run": str(values_run), "state_run": str(state_run), "horizon": horizon, "train_ratio": train_ratio, "valid_ratio": valid_ratio}, sort_keys=True)
    run_id = f"conditional_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(seed.encode()).hexdigest()[:8]}"
    run_dir = Path(runs_root).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    result_frame = pd.DataFrame(all_rows)
    result_frame.to_parquet(run_dir / "conditional_metrics.parquet", index=False)
    manifest = {
        "run_id": run_id,
        "snapshot_id": snapshot.name,
        "requested": len(partitions),
        "computed": len(partitions) - len(errors),
        "failed": len(errors),
        "errors": errors,
        "values_run": str(Path(values_run).resolve()),
        "state_run": str(Path(state_run).resolve()),
        "horizon": horizon,
        "train_ratio": train_ratio,
        "valid_ratio": valid_ratio,
    }
    write_json(run_dir / "conditional_metrics_manifest.json", manifest)
    return {**manifest, "run_dir": str(run_dir)}
