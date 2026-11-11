from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from custom_bt.alpha import alpha_components, canonical_alpha_expression
from custom_bt.canonical_expression import normalize_expression
from custom_bt.composition_screen import build_latest_screen
from custom_bt.factor_direction import orient_expression
from repositories import company_source
from repositories.factor_run_store import confirmed_records
from repositories.panel_store import load_panel_for_pool, expression_fields, expression_lookback
from custom_bt.engine import BacktestConfig, run_backtest
from adapters.expressions import evaluate_expression
from custom_bt.pools import load_pool_codes, load_pool_manifest
from services.report_service import save_result
from repositories.composition_store import (
    write_composition_manifest,
    write_latest_screen,
    write_run_outputs,
    write_size_outputs,
)


@dataclass(frozen=True)
class CompositionCandidate:
    factor_id: str
    expression: str
    canonical_expression: str
    backtest_expression: str
    pool_id: str | None
    source_signature: str | None
    metrics: dict[str, float]
    raw: dict[str, Any]

    def metric(self, name: str) -> float:
        key = _metric_key(name)
        return float(self.metrics.get(key, float("nan")))


@dataclass(frozen=True)
class WeightOptimizationResult:
    weights: np.ndarray
    objective: float
    iterations: int
    converged: bool
    method: str = "equal_weight"


@dataclass(frozen=True)
class SelectedComponent:
    candidate: CompositionCandidate
    alpha: pd.DataFrame
    zalpha: pd.DataFrame
    weight: float
    admission: dict[str, Any] | None = None

    @property
    def factor_id(self) -> str:
        return self.candidate.factor_id


@dataclass(frozen=True)
class CompositionSelection:
    components: list[SelectedComponent]
    rejections: list[dict[str, Any]]
    mutual_ic_matrix: list[list[float]]
    optimization: WeightOptimizationResult
    admission_log: list[dict[str, Any]] | None = None
    target_metrics: dict[str, Any] | None = None


FACTOR_PREPROCESS: dict[str, Any] = {
    "method": "alphagen_normalize_by_day",
    "scope": "daily_cross_section",
    "center": "daily_mean",
    "scale": "daily_std",
    "std_ddof": 0,
    "non_finite_fill_value": 0.0,
}

def _factor_preprocess(z_clip: float | None = None) -> dict[str, Any]:
    """日频标准化口径；只有显式截尾时多一个 clip 字段。"""
    preprocess = dict(FACTOR_PREPROCESS)
    if z_clip is not None:
        preprocess["clip"] = float(z_clip)
        preprocess["clip_scope"] = "zscore"
    return preprocess


def _metric_key(name: str) -> str:
    aliases = {
        "generation_score": "score",
        "generation_ic": "ic",
        "generation_rank_ic": "rank_ic",
        "generation_icir": "icir",
        "generation_coverage": "coverage",
        "backtest_sharpe": "backtest_sharpe",
    }
    return aliases.get(str(name), str(name))


def _as_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None:
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _finite_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (int, float, np.integer, np.floating)):
            number = float(value)
            result[key] = number if np.isfinite(number) else None
        else:
            result[key] = value
    return result


def _first_present(record: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return value
    return None


def _passes_min(value: float, threshold: float | None) -> bool:
    if threshold is None:
        return True
    return np.isfinite(value) and value >= float(threshold)


def _fallback_factor_id(index: int, expression: str) -> str:
    digest = hashlib.sha256(expression.encode("utf-8")).hexdigest()[:10]
    return f"factor_{index:04d}_{digest}"


def _candidate_from_record(index: int, record: Mapping[str, Any], default_pool_id: str | None = None) -> CompositionCandidate | None:
    if record.get("accepted", True) is False:
        return None
    expression = str(_first_present(record, ["expression", "canonical_expression", "backtest_expression"]) or "").strip()
    if not expression:
        return None
    canonical_expression = str(_first_present(record, ["canonical_expression", "expression"]) or expression).strip()
    canonical_expression = normalize_expression(canonical_expression)
    backtest_expression = str(_first_present(record, ["backtest_expression", "canonical_expression", "expression"]) or canonical_expression).strip()
    backtest_expression = normalize_expression(backtest_expression)
    backtest_expression, orientation = orient_expression(backtest_expression, record)
    metrics: dict[str, float] = {}
    for key in [
        "score",
        "ic",
        "rank_ic",
        "icir",
        "coverage",
        "backtest_sharpe",
        "backtest_annual_return",
        "backtest_max_drawdown",
    ]:
        value = _first_present(record, [key, f"generation_{key}"])
        if value is not None:
            metrics[key] = _as_float(value)
    training_metrics = (record.get("segments") or {}).get("train") or {}
    for signed_metric in ("ic", "rank_ic", "icir"):
        training_value = _as_float(training_metrics.get(signed_metric))
        if np.isfinite(training_value):
            metrics[signed_metric] = training_value
        if signed_metric in metrics:
            metrics[signed_metric] *= orientation["direction"]
    factor_id = str(record.get("factor_id") or _fallback_factor_id(index, canonical_expression))
    return CompositionCandidate(
        factor_id=factor_id,
        expression=expression,
        canonical_expression=canonical_expression,
        backtest_expression=backtest_expression,
        pool_id=str(record.get("pool_id") or default_pool_id) if (record.get("pool_id") or default_pool_id) else None,
        source_signature=str(record.get("source_signature")) if record.get("source_signature") else None,
        metrics=metrics,
        raw={**record, **orientation},
    )


def load_composition_candidates(
    records: Iterable[Mapping[str, Any]],
    pool_id: str | None,
    selection_metric: str = "score",
    min_score: float | None = None,
    min_ic: float | None = None,
    min_rank_ic: float | None = None,
    min_coverage: float | None = None,
    min_backtest_sharpe: float | None = None,
) -> list[CompositionCandidate]:
    selected: list[CompositionCandidate] = []
    for index, record in enumerate(records, start=1):
        candidate = _candidate_from_record(index, record, default_pool_id=pool_id)
        if candidate is None:
            continue
        if pool_id and candidate.pool_id and candidate.pool_id != pool_id:
            continue
        if not _passes_min(candidate.metric("score"), min_score):
            continue
        if not _passes_min(candidate.metric("ic"), min_ic):
            continue
        if not _passes_min(candidate.metric("rank_ic"), min_rank_ic):
            continue
        if not _passes_min(candidate.metric("coverage"), min_coverage):
            continue
        if not _passes_min(candidate.metric("backtest_sharpe"), min_backtest_sharpe):
            continue
        selected.append(candidate)
    metric_name = _metric_key(selection_metric)
    return sorted(
        selected,
        key=lambda item: (
            -item.metric(metric_name) if np.isfinite(item.metric(metric_name)) else float("inf"),
            item.factor_id,
        ),
    )


def daily_cross_section_zscore(values: pd.DataFrame, clip: float | None = None) -> pd.DataFrame:
    if clip is not None and (not np.isfinite(clip) or float(clip) <= 0):
        raise ValueError("zscore clip must be a positive finite value")
    frame = values[["date", "code", "alpha"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["alpha"] = pd.to_numeric(frame["alpha"], errors="coerce")

    def zscore(series: pd.Series) -> pd.Series:
        std = float(series.std(ddof=0))
        if not np.isfinite(std) or std <= 0:
            return pd.Series(0.0, index=series.index, dtype=float)
        normalized = (series - float(series.mean())) / std
        normalized = normalized.replace([np.inf, -np.inf], np.nan)
        if clip is not None:
            normalized = normalized.clip(lower=-float(clip), upper=float(clip))
        return normalized.fillna(0.0)

    frame["alpha"] = frame.groupby("date", group_keys=False)["alpha"].transform(zscore)
    return frame


def daily_mutual_ic(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    return _daily_mutual_ic_from_zscores(daily_cross_section_zscore(left), daily_cross_section_zscore(right))


def make_forward_return_target(panel: pd.DataFrame, horizon: int = 20, price_col: str = "close") -> pd.DataFrame:
    if int(horizon) <= 0:
        raise ValueError("target horizon must be positive")
    if price_col not in panel.columns:
        raise ValueError(f"target construction requires {price_col!r} column")
    frame = panel[["date", "code", price_col]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values(["code", "date"])
    future = frame.groupby("code", group_keys=False)[price_col].shift(-int(horizon))
    current = frame[price_col].replace(0, np.nan)
    frame["target"] = (future / current - 1.0).replace([np.inf, -np.inf], np.nan)
    return frame[["date", "code", "target"]]


def _safe_corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or len(right) < 2:
        return float("nan")
    left_mean = float(left.mean())
    right_mean = float(right.mean())
    left_std = float(left.std(ddof=0))
    right_std = float(right.std(ddof=0))
    denom = left_std * right_std
    if left_std < 1e-3 or right_std < 1e-3 or denom == 0:
        return 0.0
    return float(((left * right).mean() - left_mean * right_mean) / denom)


def evaluate_alpha_target_metrics(alpha: pd.DataFrame, target: pd.DataFrame) -> dict[str, Any]:
    scores = alpha[["date", "code", "alpha"]].copy()
    tgt = target[["date", "code", "target"]].copy()
    scores["date"] = pd.to_datetime(scores["date"], errors="coerce")
    tgt["date"] = pd.to_datetime(tgt["date"], errors="coerce")
    scores["code"] = scores["code"].astype(str).str.zfill(6)
    tgt["code"] = tgt["code"].astype(str).str.zfill(6)
    scores["alpha"] = pd.to_numeric(scores["alpha"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    tgt["target"] = pd.to_numeric(tgt["target"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    merged = tgt.merge(scores, on=["date", "code"], how="left")
    total = int(len(merged))
    valid_mask = merged["alpha"].notna() & merged["target"].notna()
    coverage = float(valid_mask.mean()) if total else 0.0
    daily_ic: list[float] = []
    daily_rank_ic: list[float] = []
    for _, group in merged[valid_mask].groupby("date"):
        if len(group) < 2:
            continue
        x = group["alpha"].to_numpy(dtype=float)
        y = group["target"].to_numpy(dtype=float)
        corr = _safe_corr(x, y)
        rank_corr = _safe_corr(
            group["alpha"].rank(method="average").to_numpy(dtype=float),
            group["target"].rank(method="average").to_numpy(dtype=float),
        )
        if np.isfinite(corr):
            daily_ic.append(float(corr))
        if np.isfinite(rank_corr):
            daily_rank_ic.append(float(rank_corr))
    if not daily_ic or not daily_rank_ic:
        return {
            "ic": float("nan"),
            "rank_ic": float("nan"),
            "icir": float("nan"),
            "rank_icir": float("nan"),
            "coverage": coverage,
            "valid_days": 0,
        }
    ic_values = np.asarray(daily_ic, dtype=float)
    rank_values = np.asarray(daily_rank_ic, dtype=float)
    ic = float(ic_values.mean())
    rank_ic = float(rank_values.mean())
    return {
        "ic": ic,
        "rank_ic": rank_ic,
        "icir": float(ic / max(float(ic_values.std(ddof=0)), 1e-6)),
        "rank_icir": float(rank_ic / max(float(rank_values.std(ddof=0)), 1e-6)),
        "coverage": coverage,
        "valid_days": int(min(len(daily_ic), len(daily_rank_ic))),
    }


def _daily_mutual_ic_from_zscores(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    lft = left[["date", "code", "alpha"]].rename(columns={"alpha": "left_alpha"})
    rgt = right[["date", "code", "alpha"]].rename(columns={"alpha": "right_alpha"})
    merged = lft.merge(rgt, on=["date", "code"], how="inner")
    daily_values: list[dict[str, Any]] = []
    for date, group in merged.groupby("date"):
        pair = group[["left_alpha", "right_alpha"]].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if len(pair) < 2:
            continue
        left_values = pair["left_alpha"].to_numpy(dtype=float)
        right_values = pair["right_alpha"].to_numpy(dtype=float)
        left_mean = float(left_values.mean())
        right_mean = float(right_values.mean())
        left_std = float(left_values.std(ddof=0))
        right_std = float(right_values.std(ddof=0))
        cov = float((left_values * right_values).mean() - left_mean * right_mean)
        denom = left_std * right_std
        corr = cov / denom if left_std >= 1e-3 and right_std >= 1e-3 and denom != 0 else 0.0
        if np.isfinite(corr):
            daily_values.append({"date": pd.Timestamp(date), "ic": float(corr), "n": int(len(pair))})
    mean_ic = float(np.mean([item["ic"] for item in daily_values])) if daily_values else float("nan")
    return {"mutual_ic": mean_ic, "usable_dates": len(daily_values), "daily": daily_values}


def _equal_weights(count: int) -> np.ndarray:
    if count < 1:
        return np.array([], dtype=float)
    return np.full(int(count), 1.0 / float(count), dtype=float)


def _equal_weight_result(count: int) -> WeightOptimizationResult:
    return WeightOptimizationResult(
        weights=_equal_weights(count),
        objective=0.0,
        iterations=0,
        converged=True,
        method="equal_weight",
    )


def _components_from_matrix(
    candidates: Sequence[CompositionCandidate],
    alphas: Sequence[pd.DataFrame],
    zalphas: Sequence[pd.DataFrame],
    matrix: Sequence[Sequence[float]],
    admissions: Mapping[str, dict[str, Any]] | None = None,
) -> tuple[list[SelectedComponent], list[list[float]], WeightOptimizationResult]:
    matrix_list = [list(row) for row in matrix]
    optimization = _equal_weight_result(len(candidates))
    admissions = admissions or {}
    components = [
        SelectedComponent(
            candidate=candidate,
            alpha=alpha,
            zalpha=zalpha,
            weight=float(weight),
            admission=admissions.get(candidate.factor_id),
        )
        for candidate, alpha, zalpha, weight in zip(candidates, alphas, zalphas, optimization.weights)
    ]
    return components, matrix_list, optimization


def _provisional_components(
    candidates: Sequence[CompositionCandidate],
    alphas: Sequence[pd.DataFrame],
    zalphas: Sequence[pd.DataFrame],
    admissions: Mapping[str, dict[str, Any]] | None = None,
) -> list[SelectedComponent]:
    admissions = admissions or {}
    return [
        SelectedComponent(candidate=candidate, alpha=alpha, zalpha=zalpha, weight=0.0, admission=admissions.get(candidate.factor_id))
        for candidate, alpha, zalpha in zip(candidates, alphas, zalphas)
    ]


def _append_matrix(matrix: Sequence[Sequence[float]], pair_values: Sequence[float]) -> list[list[float]]:
    new_matrix = [list(row) for row in matrix]
    if len(pair_values) != len(new_matrix):
        raise ValueError("pair_values length must match existing matrix size")
    for row, value in zip(new_matrix, pair_values):
        row.append(float(value) if np.isfinite(value) else 0.0)
    new_matrix.append([float(value) if np.isfinite(value) else 0.0 for value in pair_values] + [1.0])
    return new_matrix


def _combine_weighted_alphas(components: Sequence[SelectedComponent]) -> pd.DataFrame:
    frames = []
    for component in components:
        frame = component.zalpha[["date", "code", "alpha"]].copy()
        column = component.factor_id
        frame = frame.rename(columns={"alpha": column})
        frame[column] = pd.to_numeric(frame[column], errors="coerce") * float(component.weight)
        frames.append(frame)
    if not frames:
        raise ValueError("composition must contain at least one component")
    merged = frames[0]
    value_cols = [frames[0].columns[-1]]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=["date", "code"], how="outer")
        value_cols.append(frame.columns[-1])
    merged[value_cols] = merged[value_cols].fillna(0.0)
    merged["alpha"] = merged[value_cols].sum(axis=1)
    return merged[["date", "code", "alpha"]]


def _components_from_saved_weights(
    panel: pd.DataFrame,
    weights: Sequence[Mapping[str, Any]],
) -> list[SelectedComponent]:
    """用已落盘的因子权重重建组合分量，仅用于刷新选股清单（不重新选因子）。"""
    components: list[SelectedComponent] = []
    for row in weights:
        factor_id = str(row.get("factor_id") or "").strip()
        expression = str(
            row.get("effective_expression") or row.get("expression") or ""
        ).strip()
        if not factor_id or not expression:
            raise ValueError("因子权重记录缺少 factor_id 或有效表达式，无法刷新选股清单")
        weight = _as_float(row.get("weight"))
        if not np.isfinite(weight):
            raise ValueError(f"因子 {factor_id} 的权重无效")
        alpha = evaluate_expression(expression, panel, output_name="alpha")
        preprocess = row.get("preprocess") or {}
        clip = preprocess.get("clip") if isinstance(preprocess, Mapping) else None
        if clip is not None:
            clip = _as_float(clip)
            if not np.isfinite(clip) or clip <= 0:
                raise ValueError(f"因子 {factor_id} 的 z_clip 无效")
        zalpha = daily_cross_section_zscore(alpha, clip=clip)
        raw = {
            "training_ic": row.get("training_ic"),
            "direction": row.get("direction"),
            "direction_source": row.get("direction_source"),
        }
        candidate = CompositionCandidate(
            factor_id=factor_id,
            expression=str(row.get("expression") or expression),
            canonical_expression=str(row.get("expression") or expression),
            backtest_expression=expression,
            pool_id=None,
            source_signature=None,
            metrics={},
            raw=raw,
        )
        components.append(
            SelectedComponent(
                candidate=candidate,
                alpha=alpha,
                zalpha=zalpha,
                weight=float(weight),
            )
        )
    if not components:
        raise ValueError("因子权重记录为空，无法刷新选股清单")
    return components


def rebuild_latest_screen(
    panel: pd.DataFrame,
    weights: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    max_weight_per_stock: float,
    signal_date: str,
) -> dict[str, Any]:
    """用已保存的权重和最新面板复算指定信号日的选股清单。"""
    components = _components_from_saved_weights(panel, weights)
    composite = _combine_weighted_alphas(components)
    return build_latest_screen(
        composite,
        components,
        panel,
        top_k,
        max_weight_per_stock=max_weight_per_stock,
        signal_date=signal_date,
    )


def _preprocessed_expression(expression: str) -> str:
    return normalize_expression(f"zscore({expression})")


def _empty_composition_metrics() -> dict[str, Any]:
    return {
        "ic": 0.0,
        "rank_ic": 0.0,
        "icir": 0.0,
        "rank_icir": 0.0,
        "coverage": 0.0,
        "valid_days": 0,
    }


def _metric_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, float]:
    keys = ["ic", "rank_ic", "icir", "rank_icir", "coverage", "valid_days"]
    delta = {}
    for key in keys:
        left = _as_float(after.get(key), default=0.0)
        right = _as_float(before.get(key), default=0.0)
        delta[key] = float(left - right)
    return delta


def _marginal_thresholds(
    min_marginal_ic_improvement: float | None,
    min_marginal_rank_ic_improvement: float | None,
    min_marginal_icir_improvement: float | None,
    min_marginal_rank_icir_improvement: float | None,
) -> dict[str, float | None]:
    return {
        "ic": min_marginal_ic_improvement,
        "rank_ic": min_marginal_rank_ic_improvement,
        "icir": min_marginal_icir_improvement,
        "rank_icir": min_marginal_rank_icir_improvement,
    }


def _marginal_gate_enabled(thresholds: Mapping[str, float | None]) -> bool:
    return any(value is not None for value in thresholds.values())


def _passes_marginal_gate(delta: Mapping[str, Any], thresholds: Mapping[str, float | None]) -> bool:
    for key, threshold in thresholds.items():
        if threshold is None:
            continue
        value = _as_float(delta.get(key))
        if not np.isfinite(value) or value < float(threshold):
            return False
    return True


def _marginal_report(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    thresholds: Mapping[str, float | None],
    before_objective: float,
    after_objective: float,
) -> dict[str, Any]:
    delta = _metric_delta(before, after)
    delta["objective"] = float(before_objective - after_objective)
    return {
        "before": dict(before),
        "after": dict(after),
        "delta": delta,
        "thresholds": {key: value for key, value in thresholds.items() if value is not None},
        "objective_before": float(before_objective),
        "objective_after": float(after_objective),
        "passed": _passes_marginal_gate(delta, thresholds),
    }


def _evaluation_window(frame: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    if not panel.attrs.get("evaluation_start"):
        return frame
    return frame[(frame["date"] >= pd.Timestamp(panel.attrs["evaluation_start"]))
                 & (frame["date"] <= pd.Timestamp(panel.attrs["evaluation_end"]))]


def select_composition_pool(
    panel: pd.DataFrame,
    candidates: Sequence[CompositionCandidate],
    max_factors: int,
    mutual_ic_threshold: float = 0.99,
    target_horizon: int = 20,
    min_marginal_ic_improvement: float | None = None,
    min_marginal_rank_ic_improvement: float | None = None,
    min_marginal_icir_improvement: float | None = None,
    min_marginal_rank_icir_improvement: float | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    z_clip: float | None = None,
) -> CompositionSelection:
    if max_factors < 1:
        raise ValueError("max_factors must be positive")
    if z_clip is not None and (not np.isfinite(z_clip) or float(z_clip) <= 0):
        raise ValueError("z_clip must be a positive finite value")
    thresholds = _marginal_thresholds(
        min_marginal_ic_improvement,
        min_marginal_rank_ic_improvement,
        min_marginal_icir_improvement,
        min_marginal_rank_icir_improvement,
    )
    marginal_enabled = _marginal_gate_enabled(thresholds)
    target = _evaluation_window(make_forward_return_target(panel, target_horizon), panel) if marginal_enabled else None
    selected_candidates: list[CompositionCandidate] = []
    selected_alphas: list[pd.DataFrame] = []
    selected_zalphas: list[pd.DataFrame] = []
    rejections: list[dict[str, Any]] = []
    admission_log: list[dict[str, Any]] = []
    admissions_by_factor: dict[str, dict[str, Any]] = {}
    components: list[SelectedComponent] = []
    matrix: list[list[float]] = []
    optimization = WeightOptimizationResult(weights=np.array([], dtype=float), objective=0.0, iterations=0, converged=True)
    current_metrics = _empty_composition_metrics()
    for index, candidate in enumerate(candidates, start=1):
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "evaluating",
                    "candidate_index": index,
                    "candidate_count": len(candidates),
                    "accepted_count": len(selected_candidates),
                    "rejected_count": len(rejections),
                    "factor_id": candidate.factor_id,
                }
            )
        if len(selected_candidates) >= max_factors:
            rejections.append(
                {
                    "factor_id": candidate.factor_id,
                    "reason": "capacity_limit",
                    "max_factors": int(max_factors),
                }
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "selecting",
                        "candidate_index": index,
                        "candidate_count": len(candidates),
                        "accepted_count": len(selected_candidates),
                        "rejected_count": len(rejections),
                    }
                )
            continue
        try:
            alpha = evaluate_expression(candidate.backtest_expression, panel, output_name="alpha")
            alpha = _evaluation_window(alpha, panel)
        except Exception as exc:
            rejections.append({"factor_id": candidate.factor_id, "reason": "evaluation_error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        candidate_zalpha = daily_cross_section_zscore(alpha, clip=z_clip)
        duplicate = None
        pair_values: list[float] = []
        if progress_callback is not None and components:
            progress_callback(
                {
                    "stage": "correlating",
                    "candidate_index": index,
                    "candidate_count": len(candidates),
                    "accepted_count": len(selected_candidates),
                    "rejected_count": len(rejections),
                    "factor_id": candidate.factor_id,
                }
            )
        for component in components:
            info = _daily_mutual_ic_from_zscores(component.zalpha, candidate_zalpha)
            mutual_ic = info["mutual_ic"]
            pair_values.append(float(mutual_ic) if np.isfinite(mutual_ic) else 0.0)
            # 等权组合没有优化器抵消负相关/反向暴露，重复度按绝对值判断。
            gate_value = abs(float(mutual_ic))
            if np.isfinite(mutual_ic) and gate_value > float(mutual_ic_threshold):
                duplicate = {
                    "factor_id": candidate.factor_id,
                    "reason": "mutual_ic",
                    "with_factor_id": component.factor_id,
                    "mutual_ic": float(mutual_ic),
                    "gate_value": float(gate_value),
                    "comparison": "abs",
                    "threshold": float(mutual_ic_threshold),
                }
                break
        if duplicate is not None:
            rejections.append(duplicate)
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "selecting",
                        "candidate_index": index,
                        "candidate_count": len(candidates),
                        "accepted_count": len(selected_candidates),
                        "rejected_count": len(rejections),
                    }
                )
            continue
        trial_candidates = selected_candidates + [candidate]
        trial_alphas = selected_alphas + [alpha]
        trial_zalphas = selected_zalphas + [candidate_zalpha]
        trial_matrix = _append_matrix(matrix, pair_values)
        trial_components: list[SelectedComponent] | None = None
        trial_optimization: WeightOptimizationResult | None = None
        candidate_admission: dict[str, Any] | None = None
        if marginal_enabled:
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "evaluating_marginal",
                        "candidate_index": index,
                        "candidate_count": len(candidates),
                        "accepted_count": len(selected_candidates),
                        "rejected_count": len(rejections),
                        "factor_id": candidate.factor_id,
                    }
                )
            trial_components, trial_matrix, trial_optimization = _components_from_matrix(
                trial_candidates,
                trial_alphas,
                trial_zalphas,
                trial_matrix,
                admissions_by_factor,
            )
            assert target is not None
            trial_metrics = evaluate_alpha_target_metrics(_combine_weighted_alphas(trial_components), target)
            marginal = _marginal_report(
                current_metrics,
                trial_metrics,
                thresholds,
                optimization.objective,
                trial_optimization.objective,
            )
            if not marginal["passed"]:
                rejections.append(
                    {
                        "factor_id": candidate.factor_id,
                        "reason": "marginal_contribution",
                        "marginal": marginal,
                    }
                )
                if progress_callback is not None:
                    progress_callback(
                        {
                            "stage": "selecting",
                            "candidate_index": index,
                            "candidate_count": len(candidates),
                            "accepted_count": len(selected_candidates),
                            "rejected_count": len(rejections),
                        }
                    )
                continue
            candidate_admission = {
                "factor_id": candidate.factor_id,
                "accepted": True,
                "before": marginal["before"],
                "after": marginal["after"],
                "delta": marginal["delta"],
                "thresholds": marginal["thresholds"],
            }
            admissions_by_factor[candidate.factor_id] = candidate_admission
            admission_log.append(candidate_admission)
            current_metrics = trial_metrics
            optimization = trial_optimization
        selected_candidates = trial_candidates
        selected_alphas = trial_alphas
        selected_zalphas = trial_zalphas
        matrix = trial_matrix
        components = (
            trial_components
            if marginal_enabled and trial_components is not None
            else _provisional_components(selected_candidates, selected_alphas, selected_zalphas, admissions_by_factor)
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "selecting",
                    "candidate_index": index,
                    "candidate_count": len(candidates),
                    "accepted_count": len(selected_candidates),
                    "rejected_count": len(rejections),
                }
            )
    if not components:
        raise ValueError("no factors passed the composition gates")
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "optimizing_weights",
                "candidate_count": len(candidates),
                "accepted_count": len(selected_candidates),
                "rejected_count": len(rejections),
                "reason": "final_selection",
            }
        )
    components, matrix, optimization = _components_from_matrix(
        selected_candidates,
        selected_alphas,
        selected_zalphas,
        matrix,
        admissions_by_factor,
    )
    if marginal_enabled:
        assert target is not None
        current_metrics = evaluate_alpha_target_metrics(_combine_weighted_alphas(components), target)
    return CompositionSelection(
        components=components,
        rejections=rejections,
        mutual_ic_matrix=matrix,
        optimization=optimization,
        admission_log=admission_log,
        target_metrics=current_metrics,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _find_factor_backtest_summary(
    path: Path,
    manifest: Mapping[str, Any],
    expected_pool_id: str,
    saved_results_root: Path | None,
) -> Path | None:
    run_ids = [path.name]
    manifest_run_id = manifest.get("run_id")
    if manifest_run_id and str(manifest_run_id) not in run_ids:
        run_ids.append(str(manifest_run_id))
    candidates = [
        path / "factor_backtest_summary.csv",
        path.parent / "factor_backtest_summary.csv",
    ]
    if saved_results_root is not None:
        for run_id in run_ids:
            run_result_dir = saved_results_root / "factor" / expected_pool_id / run_id
            # 平台任务按 backtest_id 版本化输出：优先使用最新一次批次
            if run_result_dir.exists():
                candidates.extend(
                    sorted(
                        run_result_dir.glob("*/factor_backtest_summary.csv"),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )
                )
            candidates.append(run_result_dir / "factor_backtest_summary.csv")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if saved_results_root is not None:
        for run_id in run_ids:
            matches = sorted(
                (saved_results_root / "factor" / expected_pool_id).glob(f"**/{run_id}/factor_backtest_summary.csv")
                if (saved_results_root / "factor" / expected_pool_id).exists()
                else []
            )
            if matches:
                return matches[0]
    return None


def _load_records_from_factor_run(
    path: Path,
    expected_pool_id: str,
    expected_source_signature: str | None,
    saved_results_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = path / "factor_run.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"factor run manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("pool_id") != expected_pool_id:
        raise ValueError(f"factor run pool_id {manifest.get('pool_id')!r} does not match requested pool_id {expected_pool_id!r}")
    if expected_source_signature and manifest.get("source_signature") not in (None, expected_source_signature):
        raise ValueError("factor run source signature does not match company source")
    records = confirmed_records(path)
    summary_path = _find_factor_backtest_summary(path, manifest, expected_pool_id, saved_results_root)
    if summary_path is not None:
        summary = pd.read_csv(summary_path)
        by_factor = {str(row.get("factor_id")): row for row in summary.to_dict("records") if row.get("factor_id") is not None}
        by_expr = {str(row.get("expression")): row for row in summary.to_dict("records") if row.get("expression") is not None}
        merged = []
        for record in records:
            current = dict(record)
            extra = by_factor.get(str(record.get("factor_id"))) or by_expr.get(str(record.get("expression")))
            if extra:
                current.update({key: value for key, value in extra.items() if not pd.isna(value)})
            merged.append(current)
        records = merged
    for record in records:
        record.setdefault("pool_id", expected_pool_id)
        if expected_source_signature:
            record.setdefault("source_signature", expected_source_signature)
    return records, manifest


def _composition_id(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:10]
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + digest


def _saved_results_root(outputs_root: str | Path) -> Path:
    root = Path(outputs_root).expanduser().resolve()
    return root if root.name == "saved_backtests" else root / "saved_backtests"


def _summary_row(
    size: int,
    selection: CompositionSelection,
    out_dir: Path,
    expression: str,
    summary: Mapping[str, Any],
    composition_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    composition_metrics = composition_metrics or {}
    return {
        "size": size,
        "selected_count": len(selection.components),
        "rejected_count": len(selection.rejections),
        "output_dir": str(out_dir),
        "canonical_expression": expression,
        "positive_total_return": bool(_as_float(summary.get("total_return"), 0.0) > 0.0),
        "positive_annual_return": bool(_as_float(summary.get("annual_return"), 0.0) > 0.0),
        **{f"composition_{key}": value for key, value in composition_metrics.items()},
        **{f"backtest_{key}": value for key, value in summary.items()},
    }


def compose_factors(
    pools_root: str | Path,
    pool_id: str,
    factor_run_dirs: Iterable[str | Path],
    outputs_root: str | Path,
    backtest_config: Mapping[str, Any],
    selection_metric: str = "score",
    min_score: float | None = None,
    min_ic: float | None = None,
    min_rank_ic: float | None = None,
    min_coverage: float | None = None,
    min_backtest_sharpe: float | None = None,
    mutual_ic_threshold: float = 0.99,
    sweep_sizes: Iterable[int] | None = None,
    max_factors: int = 100,
    factor_ids: Sequence[str] | None = None,
    z_clip: float | None = None,
    target_horizon: int = 20,
    min_marginal_ic_improvement: float | None = None,
    min_marginal_rank_ic_improvement: float | None = None,
    min_marginal_icir_improvement: float | None = None,
    min_marginal_rank_icir_improvement: float | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    data_source: str | None = None,
    snapshot_root: str | Path | None = None,
    snapshot_id: str | None = None,
    as_of: str | None = None,
    pool_manifest: Mapping[str, Any] | None = None,
    pool_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    if z_clip is not None and (not np.isfinite(z_clip) or float(z_clip) <= 0):
        raise ValueError("z_clip must be a positive finite value")
    requested_factor_ids: list[str] | None = None
    if factor_ids is not None:
        requested_factor_ids = list(
            dict.fromkeys(str(item).strip() for item in factor_ids if str(item).strip())
        )
        if not requested_factor_ids:
            raise ValueError("factor_ids must not be empty when provided")
    if pool_manifest is None or pool_codes is None:
        try:
            resolved_manifest = load_pool_manifest(pools_root, pool_id)
            resolved_codes = load_pool_codes(pools_root, pool_id)
        except FileNotFoundError:
            from repositories.mysql_store import fetch_pool
            stored = fetch_pool(pool_id)
            if not stored:
                raise ValueError(f"pool not found locally or in MySQL: {pool_id}") from None
            resolved_manifest = stored.get("manifest") or {}
            resolved_codes = stored.get("codes") or []
        pool_manifest = dict(pool_manifest) if pool_manifest is not None else resolved_manifest
        pool_codes = list(pool_codes) if pool_codes is not None else resolved_codes
    pool_manifest = dict(pool_manifest)
    if pool_manifest.get("pool_id") not in (None, pool_id):
        raise ValueError("pool manifest ID does not match requested pool")
    codes = list(dict.fromkeys(str(code).strip() for code in pool_codes if str(code).strip()))
    if not codes:
        raise ValueError("pool has no stock codes")
    source = company_source.resolve_data_source(data_source, pool_manifest)
    source_signature = company_source.source_signature()
    if source_signature and pool_manifest.get("source_signature") and source_signature != pool_manifest.get("source_signature"):
        raise ValueError("pool source signature does not match data source")
    all_records: list[dict[str, Any]] = []
    run_manifests: list[dict[str, Any]] = []
    run_dirs = [Path(item).expanduser().resolve() for item in factor_run_dirs]
    saved_results_root = _saved_results_root(outputs_root)
    for run_dir in run_dirs:
        records, manifest = _load_records_from_factor_run(run_dir, pool_id, source_signature, saved_results_root)
        company_source.resolve_data_source(None, manifest)
        all_records.extend(records)
        run_manifests.append(manifest)
    candidates = load_composition_candidates(
        all_records,
        pool_id=pool_id,
        selection_metric=selection_metric,
        min_score=min_score,
        min_ic=min_ic,
        min_rank_ic=min_rank_ic,
        min_coverage=min_coverage,
        min_backtest_sharpe=min_backtest_sharpe,
    )
    if requested_factor_ids is not None:
        available_ids = {candidate.factor_id for candidate in candidates}
        missing_ids = [factor_id for factor_id in requested_factor_ids if factor_id not in available_ids]
        if missing_ids:
            preview = "、".join(missing_ids[:5])
            suffix = " 等" if len(missing_ids) > 5 else ""
            raise ValueError(
                f"{len(missing_ids)} 个因子不在候选集中或未通过筛选（示例：{preview}{suffix}）"
            )
        requested_set = set(requested_factor_ids)
        candidates = [candidate for candidate in candidates if candidate.factor_id in requested_set]
    if not candidates:
        raise ValueError("no composition candidates remain after filtering")
    requested_sizes = sorted({int(size) for size in (sweep_sizes or range(10, 101, 10)) if int(size) > 0 and int(size) <= int(max_factors)})
    if not requested_sizes:
        raise ValueError("sweep_sizes must contain at least one positive size no larger than max_factors")
    required_size = max(requested_sizes)
    parent_snapshots = sorted({m["snapshot_id"] for m in run_manifests if m.get("snapshot_id")})
    if snapshot_id is None and len(parent_snapshots) > 1:
        raise ValueError("Factor runs use different snapshots; explicitly select a compatible composition snapshot")
    snapshot_id = snapshot_id or (parent_snapshots[0] if parent_snapshots else None)
    fields = expression_fields([candidate.backtest_expression for candidate in candidates])
    panel = load_panel_for_pool(source, codes, BacktestConfig(**dict(backtest_config)),
                                pool_id=pool_id, fields=fields, snapshot_root=snapshot_root,
                                snapshot_id=snapshot_id, as_of=as_of,
                                lookback_days=expression_lookback([c.backtest_expression for c in candidates]))
    snapshot_id = panel.attrs["snapshot_id"]
    if panel.empty:
        raise ValueError("no panel rows remain for composition")
    if progress_callback is not None:
        progress_callback({"stage": "loaded", "candidate_count": len(candidates), "required_size": required_size})
    marginal_gate = {
        "target_horizon": int(target_horizon),
        "min_marginal_ic_improvement": min_marginal_ic_improvement,
        "min_marginal_rank_ic_improvement": min_marginal_rank_ic_improvement,
        "min_marginal_icir_improvement": min_marginal_icir_improvement,
        "min_marginal_rank_icir_improvement": min_marginal_rank_icir_improvement,
    }
    panel.attrs["evaluation_start"] = backtest_config["start_date"]
    panel.attrs["evaluation_end"] = backtest_config["end_date"]
    full_selection = select_composition_pool(
        panel,
        candidates,
        max_factors=required_size,
        mutual_ic_threshold=mutual_ic_threshold,
        target_horizon=int(target_horizon),
        min_marginal_ic_improvement=min_marginal_ic_improvement,
        min_marginal_rank_ic_improvement=min_marginal_rank_ic_improvement,
        min_marginal_icir_improvement=min_marginal_icir_improvement,
        min_marginal_rank_icir_improvement=min_marginal_rank_icir_improvement,
        progress_callback=progress_callback,
        z_clip=z_clip,
    )
    selected_count = len(full_selection.components)
    sizes = [size for size in requested_sizes if size <= selected_count]
    underfilled_final_size = None
    if selected_count > 0 and selected_count < required_size and selected_count not in sizes:
        underfilled_final_size = selected_count
        sizes.append(selected_count)
        sizes = sorted(sizes)
    output_base = saved_results_root / "composite" / pool_id
    composition_payload = {
        "snapshot_id": snapshot_id,
        "source_snapshot_ids": parent_snapshots,
        "backtest_config": dict(backtest_config),
        "pool_id": pool_id,
        "run_dirs": [str(item) for item in run_dirs],
        "selection_metric": selection_metric,
        "mutual_ic_threshold": mutual_ic_threshold,
        "z_clip": z_clip,
        "requested_factor_ids": requested_factor_ids,
        "requested_sizes": requested_sizes,
        "sizes": sizes,
        "underfilled_final_size": underfilled_final_size,
        "candidate_ids": [item.factor_id for item in candidates],
        "marginal_gate": marginal_gate,
    }
    composition_id = _composition_id(composition_payload)
    completed_sizes: list[int] = []
    output_dirs: list[str] = []
    positive_output_dirs: list[str] = []
    summary_rows: list[dict[str, Any]] = []
    size_entries: list[dict[str, Any]] = []
    (output_base / composition_id).mkdir(parents=True, exist_ok=True)
    target = _evaluation_window(make_forward_return_target(panel, int(target_horizon)), panel)
    for size in sizes:
        if len(full_selection.components) < size:
            continue
        size_candidates = [component.candidate for component in full_selection.components[:size]]
        size_alphas = [component.alpha for component in full_selection.components[:size]]
        size_zalphas = [component.zalpha for component in full_selection.components[:size]]
        matrix = [row[:size] for row in full_selection.mutual_ic_matrix[:size]]
        admission_by_factor = {
            str(item.get("factor_id")): item
            for item in (full_selection.admission_log or [])
            if item.get("factor_id") is not None
        }
        components, matrix, optimization = _components_from_matrix(
            size_candidates,
            size_alphas,
            size_zalphas,
            matrix,
            admission_by_factor,
        )
        factor_preprocess = _factor_preprocess(z_clip)
        alpha_defs = [
            {
                "factor_id": component.factor_id,
                "name": component.factor_id,
                "expr": _preprocessed_expression(component.candidate.backtest_expression),
                "source_expr": component.candidate.canonical_expression,
                "preprocess": factor_preprocess,
                "weight": component.weight,
            }
            for component in components
        ]
        composite_alpha = _combine_weighted_alphas(components)
        composition_metrics = evaluate_alpha_target_metrics(composite_alpha, target)
        expression = canonical_alpha_expression(alpha_defs)
        config = BacktestConfig(**dict(backtest_config))
        screen = build_latest_screen(
            composite_alpha,
            components,
            panel,
            config.top_k,
            max_weight_per_stock=config.max_weight_per_stock,
        )
        screen_summary = {
            "signal_date": screen["signal_date"],
            "execution_date": screen["execution_date"],
            "execution_pending": screen["execution_pending"],
            "total_ranked": screen["total_ranked"],
            "selected_count": screen["selected_count"],
            "buyable_count": screen["buyable_count"],
            "planned_weight_per_stock": screen["planned_weight_per_stock"],
        }
        backtest = run_backtest(panel, composite_alpha, config)
        is_positive_backtest = bool(_as_float(backtest.summary.get("total_return"), 0.0) > 0.0)
        run_name = f"{composition_id}_size_{size:03d}"
        metadata = {
            "result_type": "composite",
            "run_key": f"composite/{pool_id}/{composition_id}/{run_name}",
            "pool_id": pool_id,
            "data_source": source,
            "snapshot_id": snapshot_id,
            "source_snapshot_ids": parent_snapshots,
            "composition_id": composition_id,
            "source_factor_run_ids": [item.get("run_id") or Path(run_dir).name for item, run_dir in zip(run_manifests, run_dirs)],
            "selected_factor_ids": [component.factor_id for component in components],
            "selection_metric": selection_metric,
            "mutual_ic_threshold": float(mutual_ic_threshold),
            "weight_method": "equal",
            "requested_factor_ids": requested_factor_ids,
            "factor_preprocess": factor_preprocess,
            "z_clip": z_clip,
            "target_horizon": int(target_horizon),
            "composition_metrics": composition_metrics,
            "latest_screen": screen_summary,
            "marginal_gate": marginal_gate,
            "admission_log": [
                item for item in (full_selection.admission_log or [])
                if item.get("factor_id") in {component.factor_id for component in components}
            ],
            "positive_backtest": is_positive_backtest,
            "max_factors": int(size),
            "canonical_expression": expression,
            "components": alpha_components(alpha_defs),
            "optimization": {
                "method": optimization.method,
                "factor_count": len(components),
                "weight_per_factor": 1.0 / len(components) if components else 0.0,
                "objective": optimization.objective,
                "iterations": optimization.iterations,
                "converged": optimization.converged,
            },
            "mutual_ic_matrix": matrix,
        }
        out_dir = save_result(
            backtest,
            output_base / composition_id,
            run_name,
            config={"backtest": dict(backtest_config), "composition": composition_payload},
            metadata=metadata,
        )
        weights = [
            {
                "factor_id": component.factor_id,
                "expression": component.candidate.canonical_expression,
                "preprocessed_expression": _preprocessed_expression(component.candidate.backtest_expression),
                "weight": component.weight,
                "weight_method": "equal",
                "applied_to": "preprocessed_alpha",
                "preprocess": factor_preprocess,
                "marginal": component.admission,
                "metrics": component.candidate.metrics,
                "direction": component.candidate.raw.get("direction", 1),
                "training_ic": component.candidate.raw.get("training_ic"),
                "direction_source": component.candidate.raw.get("direction_source"),
                "effective_expression": component.candidate.backtest_expression,
            }
            for component in components
        ]
        write_size_outputs(out_dir, weights, metadata["admission_log"])
        write_latest_screen(out_dir, screen)
        completed_sizes.append(size)
        output_dirs.append(str(out_dir))
        size_entries.append(
            {
                "size": int(size),
                "run_name": run_name,
                "run_key": metadata["run_key"],
                "output_dir": str(out_dir),
                "composition_metrics": _finite_mapping(composition_metrics),
                "backtest_summary": _finite_mapping(backtest.summary),
                "screen": screen_summary,
            }
        )
        if is_positive_backtest:
            positive_output_dirs.append(str(out_dir))
        summary_rows.append(
            _summary_row(
                size,
                CompositionSelection(components, full_selection.rejections, matrix, optimization, full_selection.admission_log, composition_metrics),
                out_dir,
                expression,
                backtest.summary,
                composition_metrics,
            )
        )
        if progress_callback is not None:
            progress_callback({"stage": "backtesting", "current_size": size, "completed_sizes": completed_sizes})
    write_run_outputs(output_base, composition_id, summary_rows, full_selection.admission_log or [], full_selection.rejections)
    source_factor_run_ids = [
        item.get("run_id") or Path(run_dir).name
        for item, run_dir in zip(run_manifests, run_dirs)
    ]
    default_size = max(completed_sizes) if completed_sizes else None
    composition_manifest = {
        "composition_id": composition_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "pool_id": pool_id,
        "data_source": source,
        "snapshot_id": snapshot_id,
        "source_snapshot_ids": parent_snapshots,
        "source_factor_run_ids": source_factor_run_ids,
        "run_dirs": [str(item) for item in run_dirs],
        "weight_method": "equal",
        "selection_metric": selection_metric,
        "mutual_ic_threshold": float(mutual_ic_threshold),
        "z_clip": z_clip,
        "target_horizon": int(target_horizon),
        "requested_factor_ids": requested_factor_ids,
        "candidate_ids": [item.factor_id for item in candidates],
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "rejected_count": len(full_selection.rejections),
        "requested_sizes": requested_sizes,
        "completed_sizes": completed_sizes,
        "underfilled_final_size": underfilled_final_size,
        "default_size": default_size,
        "filters": {
            "min_score": min_score,
            "min_ic": min_ic,
            "min_rank_ic": min_rank_ic,
            "min_coverage": min_coverage,
            "min_backtest_sharpe": min_backtest_sharpe,
        },
        "backtest_config": dict(backtest_config),
        "marginal_gate": marginal_gate,
        "sizes": size_entries,
    }
    write_composition_manifest(output_base, composition_id, composition_manifest)
    result = {
        "snapshot_id": snapshot_id,
        "source_snapshot_ids": parent_snapshots,
        "pool_id": pool_id,
        "composition_id": composition_id,
        "weight_method": "equal",
        "z_clip": z_clip,
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "rejected_count": len(full_selection.rejections),
        "requested_sizes": requested_sizes,
        "underfilled_final_size": underfilled_final_size,
        "completed_sizes": completed_sizes,
        "default_size": default_size,
        "output_dirs": output_dirs,
        "positive_output_dirs": positive_output_dirs,
        "summary_path": str(output_base / composition_id / "composition_run_summary.csv"),
        "positive_summary_path": str(output_base / composition_id / "positive_composition_results.csv"),
        "manifest_path": str(output_base / composition_id / "composition_manifest.json"),
    }
    return result
