import pandas as pd
import pytest

from custom_bt.engine import BacktestConfig, run_backtest


def run(dates, frequency="1D", **options):
    rows = []
    for i, date in enumerate(pd.to_datetime(dates)):
        for j, code in enumerate(["000001", "000002"]):
            rows.append(dict(date=date, code=code, open=10, close=10,
                             alpha=(1 if i % 2 == j else 0), Ifsuspend=0, if_up=0, if_down=0))
    panel = pd.DataFrame(rows)
    config = dict(start_date=str(min(dates)), end_date=str(max(dates)), top_k=1,
                  initial_cash=100000, max_weight_per_stock=1, rebalance_freq=frequency,
                  commission=0, transfer_fee=0, stamp_duty=0, slippage=0, min_cost=0)
    config.update(options)
    return run_backtest(panel, panel[["date", "code", "alpha"]], BacktestConfig(**config))


@pytest.mark.parametrize("frequency,expected", [
    ("1W", ["2024-01-03", "2024-01-08", "2024-01-15", "2024-02-01"]),
    ("2W", ["2024-01-03", "2024-01-08", "2024-02-01"]),
    ("1M", ["2024-01-03", "2024-02-01"]),
])
def test_calendar_schedule_holidays_and_daily_valuation(frequency, expected):
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08", "2024-01-09",
             "2024-01-15", "2024-01-16", "2024-02-01", "2024-02-02"]
    result = run(dates, frequency)
    # Constant-price, single-name holdings: candidate swaps make every due date observable.
    trade_dates = set(result.trades.date.dt.strftime("%Y-%m-%d"))
    assert trade_dates <= set(expected)
    assert result.daily_report.loc[result.daily_report.rebalance_scheduled, "date"].dt.strftime("%Y-%m-%d").tolist() == expected
    assert "2024-01-03" in trade_dates
    assert len(result.daily_report) == len(dates)
    assert result.daily_report.account.tolist() == pytest.approx([100000] * len(dates))


def test_new_fee_components_and_sell_tax():
    result = run(["2024-01-01", "2024-01-02", "2024-01-03"],
                 commission=0.0003, transfer_fee=0.00001, stamp_duty=0.0005, min_cost=5)
    buys = result.trades[result.trades.side == "buy"]
    sells = result.trades[result.trades.side == "sell"]
    for row in result.trades.itertuples():
        assert row.commission == pytest.approx(max(row.amount * 0.0003, 5))
        assert row.transfer_fee == pytest.approx(row.amount * 0.00001)
        assert row.stamp_duty == pytest.approx(row.amount * 0.0005 if row.side == "sell" else 0)
        assert row.cost == pytest.approx(row.commission + row.transfer_fee + row.stamp_duty)
    assert not sells.empty and not buys.empty
    assert (result.daily_report.cash >= -1e-8).all()


def test_minimum_applies_only_to_commission_and_budget_remains_nonnegative():
    result = run(["2024-01-01", "2024-01-02"], initial_cash=100,
                 commission=0.0003, transfer_fee=0.001, stamp_duty=0.0005, min_cost=5)
    trade = result.trades.iloc[0]
    assert trade.commission == 5
    assert trade.cost == pytest.approx(5 + trade.amount * 0.001)
    assert trade.amount + trade.cost == pytest.approx(100)
    assert result.daily_report.iloc[-1].cash == pytest.approx(0, abs=1e-8)


def test_explicit_legacy_rates_do_not_add_new_taxes():
    result = run(["2024-01-01", "2024-01-02", "2024-01-03"],
                 buy_cost=0.001, sell_cost=0.002, commission=0.003, transfer_fee=0.001, stamp_duty=0.005)
    for row in result.trades.itertuples():
        assert row.cost == pytest.approx(row.amount * (0.001 if row.side == "buy" else 0.002))


def test_invalid_rates_fail_before_trading():
    with pytest.raises(ValueError):
        run(["2024-01-01", "2024-01-02"], commission=float("nan"))
