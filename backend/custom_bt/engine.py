from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from custom_bt.metrics import annual_metrics, performance_summary


@dataclass
class BacktestConfig:
    start_date: str
    end_date: str
    top_k: int = 50
    rebalance_freq: str = "1D"
    price: str = "next_open"
    initial_cash: float = 100_000_000.0
    buy_cost: float = 0.0015
    sell_cost: float = 0.0015
    slippage: float = 0.0005
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.02
    exclude_limit_up_buy: bool = True
    exclude_limit_down_sell: bool = True


@dataclass
class BacktestResult:
    daily_report: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    summary: Dict[str, float]
    annual: pd.DataFrame


def _cost(amount: float, rate: float, min_cost: float) -> float:
    if amount <= 0:
        return 0.0
    return max(abs(amount) * rate, min_cost)


def _tradable(row: pd.Series) -> bool:
    return bool(row.get("Ifsuspend", 0) == 0 and pd.notna(row.get("open")) and row.get("open", 0) > 0)


def run_backtest(panel: pd.DataFrame, alpha: pd.DataFrame, config: BacktestConfig) -> BacktestResult:
    if config.rebalance_freq != "1D" or config.price != "next_open":
        raise ValueError("Only rebalance_freq='1D' and price='next_open' are supported")
    if config.top_k < 1 or not 0 < config.max_weight_per_stock <= 1:
        raise ValueError("top_k must be positive and max_weight_per_stock must be in (0, 1]")
    data = panel.copy()
    scores = alpha.copy()
    data["date"] = pd.to_datetime(data["date"])
    scores["date"] = pd.to_datetime(scores["date"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    scores["code"] = scores["code"].astype(str).str.zfill(6)
    for col in ["open", "close", "high", "low"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            data.loc[data[col] <= 0, col] = pd.NA
    scores["alpha"] = pd.to_numeric(scores["alpha"], errors="coerce")
    data = data[(data["date"] >= pd.Timestamp(config.start_date)) & (data["date"] <= pd.Timestamp(config.end_date))]
    data = data.sort_values(["date", "code"]).reset_index(drop=True)
    scores = scores.sort_values(["date", "code"]).reset_index(drop=True)
    dates = sorted(data["date"].unique())
    by_date = {pd.Timestamp(k): v.set_index("code") for k, v in data.groupby("date")}
    alpha_by_date = {pd.Timestamp(k): v.set_index("code")["alpha"] for k, v in scores.groupby("date")}
    cash = float(config.initial_cash)
    holdings: Dict[str, float] = {}
    daily_rows: List[Dict[str, float]] = []
    trade_rows: List[Dict[str, object]] = []
    position_rows: List[Dict[str, object]] = []
    prev_account = cash
    last_prices: Dict[str, float] = {}

    for i, date in enumerate(dates):
        date = pd.Timestamp(date)
        today = by_date[date]
        signal_date = pd.Timestamp(dates[i - 1]) if i > 0 else None
        trade_cost = 0.0
        trade_amount = 0.0
        trade_count = 0

        if signal_date is not None and signal_date in alpha_by_date:
            next_panel = today
            raw_scores = alpha_by_date[signal_date].dropna().sort_values(ascending=False)
            candidates = []
            for code in raw_scores.index:
                if code not in next_panel.index:
                    continue
                row = next_panel.loc[code]
                if not _tradable(row):
                    continue
                if config.exclude_limit_up_buy and row.get("if_up", 0) == 1 and code not in holdings:
                    continue
                candidates.append(code)
                if len(candidates) >= config.top_k:
                    break

            account_before = cash + sum(
                shares * (float(today.loc[code, "open"])
                          if code in today.index and pd.notna(today.loc[code, "open"])
                          else last_prices[code])
                for code, shares in holdings.items()
            )
            max_names = max(int(1.0 / config.max_weight_per_stock), config.top_k)
            weight = min(1.0 / max(len(candidates), 1), config.max_weight_per_stock)
            if len(candidates) < max_names:
                weight = min(weight, 1.0 / max(len(candidates), 1)) if candidates else 0.0
            target_value = {code: account_before * weight for code in candidates}

            for code, shares in list(holdings.items()):
                if code not in next_panel.index:
                    continue
                row = next_panel.loc[code]
                if not _tradable(row):
                    continue
                if config.exclude_limit_down_sell and row.get("if_down", 0) == 1:
                    continue
                price = float(row["open"]) * (1.0 - config.slippage)
                target_shares = target_value.get(code, 0.0) / float(row["open"])
                shares = max(shares - target_shares, 0.0)
                if shares <= 0:
                    continue
                amount = shares * price
                fee = _cost(amount, config.sell_cost, config.min_cost)
                cash += amount - fee
                trade_cost += fee
                trade_amount += amount
                trade_count += 1
                holdings[code] -= shares
                if holdings[code] <= 1e-10:
                    holdings.pop(code)
                trade_rows.append({"date": date, "code": code, "side": "sell", "price": price, "shares": shares, "amount": amount, "cost": fee, "reason": "rebalance"})

            for code, target in target_value.items():
                row = next_panel.loc[code]
                if config.exclude_limit_up_buy and row.get("if_up", 0) == 1:
                    continue
                price = float(row["open"]) * (1.0 + config.slippage)
                current_shares = holdings.get(code, 0.0)
                current_value = current_shares * price
                diff_value = target - current_value
                if diff_value <= 0:
                    continue
                shares = diff_value / price
                amount = shares * price
                fee = _cost(amount, config.buy_cost, config.min_cost)
                if amount + fee > cash:
                    shares = max((cash - config.min_cost) / (price * (1.0 + config.buy_cost)), 0.0)
                    amount = shares * price
                    fee = _cost(amount, config.buy_cost, config.min_cost)
                if shares <= 0 or amount + fee > cash:
                    continue
                last_prices.setdefault(code, float(row["open"]))
                holdings[code] = current_shares + shares
                cash -= amount + fee
                trade_cost += fee
                trade_amount += amount
                trade_count += 1
                trade_rows.append({"date": date, "code": code, "side": "buy", "price": price, "shares": shares, "amount": amount, "cost": fee, "reason": "rebalance"})

        for code, row in today.iterrows():
            if pd.notna(row["close"]):
                last_prices[code] = float(row["close"])
        stock_value = 0.0
        day_positions = []
        for code, shares in holdings.items():
            price = last_prices[code]
            value = shares * price
            stock_value += value
            alpha_value = float(alpha_by_date.get(date, pd.Series(dtype=float)).get(code, float("nan")))
            day_positions.append({"date": date, "code": code, "weight": 0.0, "shares": shares, "price": price, "value": value, "alpha": alpha_value})
        account = cash + stock_value
        for row in day_positions:
            row["weight"] = row["value"] / account if account > 0 else 0.0
        position_rows.extend(day_positions)
        daily_ret = account / prev_account - 1.0 if prev_account else 0.0
        turnover = trade_amount / prev_account if prev_account else 0.0
        daily_rows.append({"date": date, "account": account, "return": daily_ret, "cost": trade_cost / prev_account if prev_account else 0.0, "turnover": turnover, "cash": cash, "stock_value": stock_value, "pnl": account - config.initial_cash, "drawdown": 0.0, "trade_count": trade_count, "holding_count": len(holdings)})
        prev_account = account

    daily_report = pd.DataFrame(daily_rows)
    if not daily_report.empty:
        nav = daily_report["account"] / float(config.initial_cash)
        daily_report["drawdown"] = nav / nav.cummax() - 1.0
    positions = pd.DataFrame(position_rows)
    trades = pd.DataFrame(trade_rows)
    summary = performance_summary(daily_report, config.initial_cash)
    annual = annual_metrics(daily_report)
    return BacktestResult(daily_report=daily_report, positions=positions, trades=trades, summary=summary, annual=annual)
