from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import math

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
    buy_cost: float | None = None
    sell_cost: float | None = None
    commission: float = 0.0003
    transfer_fee: float = 0.00001
    stamp_duty: float = 0.0005
    slippage: float = 0.001
    min_cost: float = 5.0
    max_weight_per_stock: float = 0.03
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


def _trade_fees(amount: float, side: str, config: BacktestConfig) -> dict:
    legacy = config.buy_cost if side == "buy" else config.sell_cost
    if legacy is not None:
        fee = _cost(amount, legacy, config.min_cost)
        return {"commission": fee, "transfer_fee": 0.0, "stamp_duty": 0.0,
                "cost": fee, "fee_model": "legacy_all_in"}
    commission = _cost(amount, config.commission, config.min_cost)
    transfer = amount * config.transfer_fee
    stamp = amount * config.stamp_duty if side == "sell" else 0.0
    return {"commission": commission, "transfer_fee": transfer, "stamp_duty": stamp,
            "cost": commission + transfer + stamp, "fee_model": "components"}


def _buy_budget(cash: float, config: BacktestConfig) -> float:
    rate = config.buy_cost if config.buy_cost is not None else config.commission
    transfer = 0.0 if config.buy_cost is not None else config.transfer_fee
    return max(0.0, min(cash / (1 + rate + transfer), (cash - config.min_cost) / (1 + transfer)))


def _rebalance_dates(dates, frequency: str) -> set:
    """Initial execution on day two; subsequent periods use the first observed trading day.

    Fortnights are anchored to Monday 1970-01-05, independent of the run start.
    """
    executable = [pd.Timestamp(date) for date in dates[1:]]
    if frequency == "1D":
        return set(executable)
    result = set()
    previous = None
    for date in executable:
        if frequency == "1M":
            key = date.year * 12 + date.month
        else:
            days = (date.normalize() - pd.Timestamp("1970-01-05")).days
            key = days // (14 if frequency == "2W" else 7)
        if key != previous:
            result.add(date)
        previous = key
    return result


def _tradable(row: pd.Series) -> bool:
    return bool(row.get("Ifsuspend", 0) == 0 and pd.notna(row.get("open")) and row.get("open", 0) > 0)


def run_backtest(panel: pd.DataFrame, alpha: pd.DataFrame | None, config: BacktestConfig) -> BacktestResult:
    if config.rebalance_freq not in {"1D", "1W", "2W", "1M"} or config.price != "next_open":
        raise ValueError("Supported rebalance_freq: 1D/1W/2W/1M; price must be next_open")
    for name in ("commission", "transfer_fee", "stamp_duty", "buy_cost", "sell_cost", "slippage", "min_cost"):
        value = getattr(config, name)
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} must be finite and nonnegative")
    if not math.isfinite(config.initial_cash) or config.initial_cash <= 0 or config.slippage >= 1:
        raise ValueError("initial_cash must be positive and slippage must be below 1")
    if config.top_k < 1 or not 0 < config.max_weight_per_stock <= 1:
        raise ValueError("top_k must be positive and max_weight_per_stock must be in (0, 1]")
    data = panel.copy()
    equal_weight = alpha is None
    scores = panel[["date", "code"]].assign(alpha=0.0) if equal_weight else alpha.copy()
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
    rebalance_dates = _rebalance_dates(dates, config.rebalance_freq)
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

        if date in rebalance_dates and signal_date is not None and signal_date in alpha_by_date:
            next_panel = today
            ranked = alpha_by_date[signal_date]
            raw_scores = ranked if equal_weight else ranked.dropna().sort_values(ascending=False)
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
                if not equal_weight and len(candidates) >= config.top_k:
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
                fees = _trade_fees(amount, "sell", config)
                fee = fees["cost"]
                cash += amount - fee
                trade_cost += fee
                trade_amount += amount
                trade_count += 1
                holdings[code] -= shares
                if holdings[code] <= 1e-10:
                    holdings.pop(code)
                trade_rows.append({"date": date, "code": code, "side": "sell", "price": price, "shares": shares, "amount": amount, "cost": fee, "reason": "rebalance", **fees})

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
                amount = min(diff_value, _buy_budget(cash, config))
                if amount <= 0:
                    continue
                fees = _trade_fees(amount, "buy", config)
                if amount + fees["cost"] > cash:
                    amount = math.nextafter(amount, 0.0)
                    fees = _trade_fees(amount, "buy", config)
                shares = amount / price
                fee = fees["cost"]
                if shares <= 0 or amount + fee > cash:
                    continue
                last_prices.setdefault(code, float(row["open"]))
                holdings[code] = current_shares + shares
                cash -= amount + fee
                trade_cost += fee
                trade_amount += amount
                trade_count += 1
                trade_rows.append({"date": date, "code": code, "side": "buy", "price": price, "shares": shares, "amount": amount, "cost": fee, "reason": "rebalance", **fees})

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
        daily_rows.append({"date": date, "account": account, "return": daily_ret, "cost": trade_cost / prev_account if prev_account else 0.0, "turnover": turnover, "cash": cash, "stock_value": stock_value, "pnl": account - config.initial_cash, "drawdown": 0.0, "trade_count": trade_count, "holding_count": len(holdings), "rebalance_scheduled": date in rebalance_dates})
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


def equal_weight_benchmark(panel: pd.DataFrame, config: BacktestConfig) -> pd.Series:
    """同池全量等权，沿用策略的成交、成本、调仓和权重约束。"""
    report = run_backtest(panel, None, config).daily_report
    return report.set_index("date")["account"] if not report.empty else pd.Series(dtype=float)


def attach_benchmark(result: BacktestResult, benchmark: pd.Series) -> None:
    if not result.daily_report.empty:
        result.daily_report["benchmark_account"] = result.daily_report["date"].map(benchmark)
