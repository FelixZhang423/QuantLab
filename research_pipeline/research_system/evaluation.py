"""Cross-sectional factor evaluation, including market-state conditioning."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _correlation(left: pd.Series, right: pd.Series, rank: bool = False) -> float:
    values = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 3:
        return float("nan")
    if rank:
        values = values.rank(method="average")
    left_std = float(values["left"].std(ddof=0))
    right_std = float(values["right"].std(ddof=0))
    if left_std == 0 or right_std == 0:
        return float("nan")
    return float(values["left"].corr(values["right"]))


def daily_ic(factor_values: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    required_factor = {"date", "code", "factor_id", "value"}
    required_target = {"date", "code", "target"}
    if missing := required_factor - set(factor_values.columns):
        raise ValueError(f"factor values are missing columns: {sorted(missing)}")
    if missing := required_target - set(target.columns):
        raise ValueError(f"target is missing columns: {sorted(missing)}")
    values = factor_values[["date", "code", "factor_id", "value"]].copy()
    labels = target[["date", "code", "target"]].copy()
    values["date"] = pd.to_datetime(values["date"], errors="coerce")
    labels["date"] = pd.to_datetime(labels["date"], errors="coerce")
    values["code"] = values["code"].astype(str)
    labels["code"] = labels["code"].astype(str)
    values["value"] = pd.to_numeric(values["value"], errors="coerce")
    labels["target"] = pd.to_numeric(labels["target"], errors="coerce")
    merged = values.merge(labels, on=["date", "code"], how="inner")
    rows: list[dict[str, object]] = []
    for (date, factor_id), group in merged.groupby(["date", "factor_id"], sort=True):
        valid = group[["value", "target"]].replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({
            "date": date,
            "factor_id": str(factor_id),
            "ic": _correlation(valid["value"], valid["target"]),
            "rank_ic": _correlation(valid["value"], valid["target"], rank=True),
            "sample_count": int(len(valid)),
        })
    return pd.DataFrame(rows, columns=["date", "factor_id", "ic", "rank_ic", "sample_count"])


def _icir(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 2:
        return float("nan")
    std = float(clean.std(ddof=1))
    return float(clean.mean() / std) if std > 0 else float("nan")


def conditional_ic(
    factor_values: pd.DataFrame,
    target: pd.DataFrame,
    states: pd.DataFrame,
) -> pd.DataFrame:
    required = {"date", "state_id"}
    if missing := required - set(states.columns):
        raise ValueError(f"states are missing columns: {sorted(missing)}")
    daily = daily_ic(factor_values, target)
    if daily.empty:
        return pd.DataFrame(columns=[
            "factor_id", "state_id", "sample_count", "coverage", "ic_mean", "rank_ic_mean",
            "icir", "hit_rate", "stability",
        ])
    state_frame = states[["date", "state_id"]].copy()
    state_frame["date"] = pd.to_datetime(state_frame["date"], errors="coerce")
    merged = daily.merge(state_frame, on="date", how="inner")
    rows: list[dict[str, object]] = []
    for (factor_id, state_id), group in merged.groupby(["factor_id", "state_id"], sort=True):
        ics = pd.to_numeric(group["ic"], errors="coerce")
        rank_ics = pd.to_numeric(group["rank_ic"], errors="coerce")
        valid_ic = ics.dropna()
        rows.append({
            "factor_id": str(factor_id),
            "state_id": str(state_id),
            "sample_count": int(len(valid_ic)),
            "coverage": float((group["sample_count"] >= 3).mean()),
            "ic_mean": float(valid_ic.mean()) if not valid_ic.empty else float("nan"),
            "rank_ic_mean": float(rank_ics.dropna().mean()) if rank_ics.notna().any() else float("nan"),
            "icir": _icir(ics),
            "hit_rate": float((valid_ic > 0).mean()) if not valid_ic.empty else float("nan"),
            "stability": float(abs(valid_ic.mean()) / valid_ic.abs().mean()) if not valid_ic.empty and valid_ic.abs().mean() > 0 else float("nan"),
        })
    return pd.DataFrame(rows, columns=[
        "factor_id", "state_id", "sample_count", "coverage", "ic_mean", "rank_ic_mean",
        "icir", "hit_rate", "stability",
    ])
