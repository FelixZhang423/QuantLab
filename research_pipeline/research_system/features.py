"""Feature and label construction for market-state research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_forward_return(
    market: pd.DataFrame,
    horizon: int = 20,
    price_col: str = "close",
) -> pd.DataFrame:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    required = {"date", "code", price_col}
    missing = required - set(market.columns)
    if missing:
        raise ValueError(f"market data is missing columns: {sorted(missing)}")
    frame = market[["date", "code", price_col]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["code"] = frame["code"].astype(str)
    frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values(["code", "date"])
    future = frame.groupby("code", sort=False)[price_col].shift(-horizon)
    current = frame[price_col].replace(0, np.nan)
    frame["target"] = (future / current - 1.0).replace([np.inf, -np.inf], np.nan)
    return frame[["date", "code", "target"]].sort_values(["date", "code"]).reset_index(drop=True)


def market_state_features(market: pd.DataFrame, volatility_window: int = 20) -> pd.DataFrame:
    if volatility_window <= 0:
        raise ValueError("volatility_window must be positive")
    required = {"date", "code", "close"}
    missing = required - set(market.columns)
    if missing:
        raise ValueError(f"market data is missing columns: {sorted(missing)}")
    frame = market[[column for column in market.columns if column in {"date", "code", "close", "ChangePCT"}]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["code"] = frame["code"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "code"]).sort_values(["code", "date"])
    if "ChangePCT" in frame.columns and frame["ChangePCT"].notna().any():
        frame["daily_return"] = pd.to_numeric(frame["ChangePCT"], errors="coerce") / 100.0
    else:
        frame["daily_return"] = frame.groupby("code", sort=False)["close"].pct_change()
    frame["daily_return"] = frame["daily_return"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    grouped = frame.groupby("date", sort=True)["daily_return"]
    result = grouped.agg(
        market_return="mean",
        cross_section_dispersion=lambda values: float(values.std(ddof=0)),
        up_ratio=lambda values: float((values > 0).mean()),
    ).reset_index()
    result["market_volatility"] = result["market_return"].rolling(
        volatility_window, min_periods=2
    ).std(ddof=0).fillna(0.0)
    return result


def assign_rule_states(
    state_features: pd.DataFrame,
    trend_threshold: float = 0.002,
    volatility_threshold: float = 0.03,
) -> pd.DataFrame:
    required = {"date", "market_return", "market_volatility"}
    missing = required - set(state_features.columns)
    if missing:
        raise ValueError(f"state features are missing columns: {sorted(missing)}")
    result = state_features.copy()
    result["state_id"] = "sideways"
    high_vol = result["market_volatility"] >= volatility_threshold
    result.loc[high_vol, "state_id"] = "high_volatility"
    result.loc[~high_vol & (result["market_return"] >= trend_threshold), "state_id"] = "bull"
    result.loc[~high_vol & (result["market_return"] <= -trend_threshold), "state_id"] = "bear"
    result["state_label"] = result["state_id"]
    result["state_method"] = "rule"
    result["fit_window_end"] = pd.to_datetime(result["date"]).max()
    return result
