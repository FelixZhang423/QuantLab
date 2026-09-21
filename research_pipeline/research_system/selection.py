"""Explainable category and factor selection baselines."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import resolve_snapshot, write_json


def score_categories(
    conditional_metrics: pd.DataFrame,
    factor_catalog: pd.DataFrame,
    state_id: str,
    min_sample_count: int = 10,
    split: str | None = None,
) -> pd.DataFrame:
    required_metrics = {"factor_id", "state_id", "rank_ic_mean", "icir", "sample_count"}
    required_catalog = {"factor_id", "category"}
    if missing := required_metrics - set(conditional_metrics.columns):
        raise ValueError(f"conditional metrics are missing columns: {sorted(missing)}")
    if missing := required_catalog - set(factor_catalog.columns):
        raise ValueError(f"factor catalog is missing columns: {sorted(missing)}")
    frame = conditional_metrics[conditional_metrics["state_id"].astype(str) == str(state_id)].copy()
    if split is not None:
        if "split" not in frame.columns:
            raise ValueError("conditional metrics are missing columns: ['split']")
        frame = frame[frame["split"].astype(str) == str(split)]
    frame = frame[frame["sample_count"] >= min_sample_count]
    catalog_categories = factor_catalog[["factor_id", "category"]].rename(columns={"category": "catalog_category"})
    frame = frame.merge(catalog_categories, on="factor_id", how="inner")
    if frame.empty:
        return pd.DataFrame(columns=["category", "score", "factor_count", "mean_rank_ic", "mean_icir"])
    if "category" in conditional_metrics.columns:
        frame["category"] = frame["catalog_category"].where(frame["catalog_category"].notna(), frame["category"])
    else:
        frame["category"] = frame["catalog_category"]
    frame["rank_ic_mean"] = pd.to_numeric(frame["rank_ic_mean"], errors="coerce")
    frame["icir"] = pd.to_numeric(frame["icir"], errors="coerce")
    frame["score"] = frame["rank_ic_mean"].fillna(0.0) * 0.7 + frame["icir"].fillna(0.0) * 0.3
    result = frame.groupby("category", dropna=False).agg(
        score=("score", "mean"),
        factor_count=("factor_id", "nunique"),
        mean_rank_ic=("rank_ic_mean", "mean"),
        mean_icir=("icir", "mean"),
    ).reset_index()
    return result.sort_values(["score", "category"], ascending=[False, True], na_position="last").reset_index(drop=True)


def _correlation_matrix(factor_values: pd.DataFrame, factor_ids: list[str]) -> pd.DataFrame:
    frame = factor_values[factor_values["factor_id"].isin(factor_ids)].copy()
    if frame.empty:
        return pd.DataFrame()
    pivot = frame.pivot_table(index=["date", "code"], columns="factor_id", values="value", aggfunc="last")
    return pivot.corr(method="spearman", min_periods=3)


def select_factors(
    conditional_metrics: pd.DataFrame,
    state_id: str,
    category: str,
    factor_values: pd.DataFrame | None = None,
    top_n: int = 10,
    correlation_threshold: float = 0.8,
    min_sample_count: int = 10,
    split: str | None = None,
) -> dict[str, list[dict[str, object]]]:
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    required = {"factor_id", "category", "state_id", "rank_ic_mean", "icir", "sample_count"}
    if missing := required - set(conditional_metrics.columns):
        raise ValueError(f"conditional metrics are missing columns: {sorted(missing)}")
    frame = conditional_metrics[
        (conditional_metrics["state_id"].astype(str) == str(state_id))
        & (conditional_metrics["category"].astype(str) == str(category))
        & (conditional_metrics["sample_count"] >= min_sample_count)
    ].copy()
    if split is not None:
        if "split" not in frame.columns:
            raise ValueError("conditional metrics are missing columns: ['split']")
        frame = frame[frame["split"].astype(str) == str(split)]
    frame["rank_ic_mean"] = pd.to_numeric(frame["rank_ic_mean"], errors="coerce")
    frame["icir"] = pd.to_numeric(frame["icir"], errors="coerce")
    frame["selection_score"] = frame["rank_ic_mean"].fillna(0.0) * 0.7 + frame["icir"].fillna(0.0) * 0.3
    frame = frame.sort_values(["selection_score", "factor_id"], ascending=[False, True]).reset_index(drop=True)
    selected: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    correlation = _correlation_matrix(factor_values, frame["factor_id"].tolist()) if factor_values is not None else pd.DataFrame()
    for row in frame.to_dict("records"):
        factor_id = str(row["factor_id"])
        if len(selected) >= top_n:
            rejections.append({"factor_id": factor_id, "reason": "top_n_limit", "selection_score": row["selection_score"]})
            continue
        correlated_with = None
        if not correlation.empty and factor_id in correlation.columns:
            for item in selected:
                other_id = str(item["factor_id"])
                value = correlation.loc[factor_id, other_id] if other_id in correlation.index else np.nan
                if pd.notna(value) and abs(float(value)) >= correlation_threshold:
                    correlated_with = {"factor_id": other_id, "correlation": float(value)}
                    break
        if correlated_with is not None:
            rejections.append({"factor_id": factor_id, "reason": "mutual_correlation", "with": correlated_with})
            continue
        selected.append({
            "factor_id": factor_id,
            "selection_score": float(row["selection_score"]),
            "rank_ic_mean": row["rank_ic_mean"],
            "icir": row["icir"],
            "sample_count": row["sample_count"],
        })
    return {"selected": selected, "rejections": rejections}


def equal_weight_portfolio(selected: list[dict[str, object]]) -> dict[str, float]:
    factor_ids = [str(item["factor_id"]) for item in selected]
    if not factor_ids:
        return {}
    weight = 1.0 / len(factor_ids)
    return {factor_id: weight for factor_id in factor_ids}


def run_selection(
    data_root: str | Path,
    conditional_run: str | Path,
    runs_root: str | Path,
    snapshot_id: str | None = None,
    state_id: str = "bull",
    category: str | None = None,
    split: str = "train",
    top_n: int = 10,
    min_sample_count: int = 10,
    correlation_threshold: float = 0.8,
) -> dict[str, Any]:
    """Select a state-specific factor set using only the requested time split."""
    snapshot = resolve_snapshot(data_root, snapshot_id)
    metrics_path = Path(conditional_run).expanduser().resolve() / "conditional_metrics.parquet"
    if not metrics_path.exists():
        raise FileNotFoundError(f"conditional metrics file is missing: {metrics_path}")
    metrics = pd.read_parquet(metrics_path)
    catalog = pd.read_parquet(snapshot / "factor_catalog.parquet")
    category_scores = score_categories(
        metrics,
        catalog,
        state_id=state_id,
        min_sample_count=min_sample_count,
        split=split,
    )
    if category is None:
        if category_scores.empty:
            raise ValueError(f"no eligible categories for state={state_id!r}, split={split!r}")
        category = str(category_scores.iloc[0]["category"])
    selection = select_factors(
        metrics,
        state_id=state_id,
        category=category,
        top_n=top_n,
        correlation_threshold=correlation_threshold,
        min_sample_count=min_sample_count,
        split=split,
    )
    portfolio = equal_weight_portfolio(selection["selected"])
    seed = json.dumps(
        {
            "snapshot": snapshot.name,
            "conditional_run": str(metrics_path.parent),
            "state_id": state_id,
            "category": category,
            "split": split,
            "top_n": top_n,
            "min_sample_count": min_sample_count,
            "correlation_threshold": correlation_threshold,
        },
        sort_keys=True,
    )
    run_id = f"selection_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{hashlib.sha256(seed.encode()).hexdigest()[:8]}"
    run_dir = Path(runs_root).expanduser().resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "run_id": run_id,
        "snapshot_id": snapshot.name,
        "conditional_run": str(metrics_path.parent),
        "state_id": state_id,
        "category": category,
        "split": split,
        "category_scores": category_scores.to_dict("records"),
        "selected": selection["selected"],
        "rejections": selection["rejections"],
        "portfolio": portfolio,
        "top_n": top_n,
        "min_sample_count": min_sample_count,
        "correlation_threshold": correlation_threshold,
    }
    write_json(run_dir / "selection.json", payload)
    write_json(run_dir / "manifest.json", {
        "run_id": run_id,
        "snapshot_id": snapshot.name,
        "conditional_run": str(metrics_path.parent),
        "state_id": state_id,
        "category": category,
        "split": split,
        "selected_count": len(selection["selected"]),
        "files": ["selection.json", "manifest.json"],
    })
    return {**payload, "run_dir": str(run_dir)}
