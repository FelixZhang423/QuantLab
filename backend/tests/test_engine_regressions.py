import pandas as pd
import pytest
from custom_bt.engine import BacktestConfig, run_backtest


def run(rows, **options):
    panel = pd.DataFrame(rows, columns=["date", "code", "open", "close", "alpha", "Ifsuspend"])
    cfg = dict(start_date="2024-01-01", end_date="2024-01-04", top_k=2,
               initial_cash=1000, buy_cost=0, sell_cost=0, min_cost=0,
               slippage=0, max_weight_per_stock=0.5)
    cfg.update(options)
    return run_backtest(panel, panel[["date", "code", "alpha"]], BacktestConfig(**cfg))


def test_trade_then_same_day_close_valuation():
    r = run([("2024-01-01", "1", 10, 10, 1, 0),
             ("2024-01-02", "1", 20, 30, 1, 0)])
    assert r.daily_report.account.tolist() == [1000, 1250]
    assert r.positions.date.min() == pd.Timestamp("2024-01-02")
    assert r.trades.date.min() == pd.Timestamp("2024-01-02")


def test_suspended_sale_and_missing_quote_preserve_value():
    r = run([("2024-01-01", "1", 10, 10, 1, 0),
             ("2024-01-02", "1", 10, 10, float("nan"), 0),
             ("2024-01-03", "1", float("nan"), float("nan"), 0, 1),
             ("2024-01-04", "2", 10, 10, 1, 0)])
    assert r.daily_report.account.tolist() == [1000]*4
    assert r.trades.side.tolist() == ["buy"]
    assert len(r.positions) == 3


def test_retained_overweight_name_is_trimmed():
    r = run([("2024-01-01", "1", 10, 10, 1, 0),
             ("2024-01-02", "1", 10, 20, 1, 0),
             ("2024-01-03", "1", 20, 20, 1, 0)])
    assert r.trades.side.tolist() == ["buy", "sell"]
    assert r.positions.iloc[-1].weight == pytest.approx(0.5)


@pytest.mark.parametrize("options", [{"price": "close"}, {"rebalance_freq": "3W"}])
def test_unsupported_execution_config_is_rejected(options):
    with pytest.raises(ValueError):
        run([("2024-01-01", "1", 10, 10, 1, 0)], **options)
