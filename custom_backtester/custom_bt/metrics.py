from __future__ import annotations

from math import sqrt
from typing import Dict

import numpy as np
import pandas as pd


TRADING_DAYS = 252


def max_drawdown(nav: pd.Series) -> float:
    nav = pd.Series(nav).astype(float)
    if nav.empty:
        return float("nan")
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def _safe_sharpe(returns: pd.Series) -> float:
    returns = returns.dropna().astype(float)
    std = returns.std(ddof=1)
    if returns.empty or std == 0 or np.isnan(std):
        return float("nan")
    return float(returns.mean() / std * sqrt(TRADING_DAYS))


def _safe_annual_return(total_return: float, n_days: int) -> float:
    base = 1.0 + float(total_return)
    if not np.isfinite(base) or base <= 0:
        return float("nan")
    return float(base ** (TRADING_DAYS / max(n_days, 1)) - 1.0)


def performance_summary(daily_report: pd.DataFrame, initial_cash: float) -> Dict[str, float]:
    daily = daily_report.copy()
    returns = daily["return"].fillna(0.0).astype(float)
    account = daily["account"].astype(float)
    nav = account / float(initial_cash)
    total_return = float(nav.iloc[-1] - 1.0) if not nav.empty else float("nan")
    n_days = max(len(daily), 1)
    annual_return = _safe_annual_return(total_return, n_days)
    mdd = max_drawdown(nav)
    total_cost = float(daily.get("cost", pd.Series(dtype=float)).fillna(0.0).sum())
    avg_turnover = float(daily.get("turnover", pd.Series(dtype=float)).fillna(0.0).mean())
    win_rate = float((returns > 0).mean()) if len(returns) else float("nan")
    calmar = float(annual_return / abs(mdd)) if mdd < 0 else float("nan")
    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": _safe_sharpe(returns),
        "max_drawdown": mdd,
        "calmar": calmar,
        "win_rate": win_rate,
        "average_turnover": avg_turnover,
        "total_cost": total_cost,
        "annual_cost": float(total_cost / n_days * TRADING_DAYS),
        "number_of_trades": float(daily.get("trade_count", pd.Series(dtype=float)).fillna(0.0).sum()),
        "average_holding_count": float(daily.get("holding_count", pd.Series(dtype=float)).fillna(0.0).mean()),
    }


def annual_metrics(daily_report: pd.DataFrame) -> pd.DataFrame:
    daily = daily_report.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    rows = []
    for year, group in daily.groupby(daily["date"].dt.year):
        returns = group["return"].fillna(0.0).astype(float)
        nav = (1.0 + returns).cumprod()
        rows.append(
            {
                "year": int(year),
                "return": float(nav.iloc[-1] - 1.0),
                "sharpe": _safe_sharpe(returns),
                "max_drawdown": max_drawdown(nav),
                "turnover": float(group.get("turnover", pd.Series(dtype=float)).fillna(0.0).mean()),
                "cost": float(group.get("cost", pd.Series(dtype=float)).fillna(0.0).sum()),
                "win_rate": float((returns > 0).mean()) if len(returns) else float("nan"),
            }
        )
    return pd.DataFrame(rows)
