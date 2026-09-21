"""Stable data contracts for the independent research data directory."""

SNAPSHOT_VERSION = 1

MARKET_REQUIRED_COLUMNS = (
    "date",
    "code",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
)

MARKET_OPTIONAL_COLUMNS = (
    "ycp",
    "market_code",
    "category",
    "ChangePCT",
    "RangePCT",
    "TurnoverRate",
    "Ifsuspend",
    "if_up",
    "if_flat",
    "if_down",
    "RisingUpDays",
    "FallingDownDays",
    "MaxRisingUpDays",
    "MaxFallingDownDays",
    "HighestPrice",
    "LowestPrice",
    "ema12",
    "ema26",
    "dif",
    "dea",
    "macd",
    "max_high_9",
    "min_low_9",
    "RSV",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "ma4",
    "ma5",
    "ma8",
    "ma12",
    "ma16",
    "ma20",
    "ma47",
    "ListedSector",
    "ListedState",
    "StockBoard",
)

FACTOR_REQUIRED_COLUMNS = (
    "factor_id",
    "expression",
    "pool_id",
    "accepted",
)

BACKTEST_REQUIRED_COLUMNS = (
    "factor_id",
    "backtest_run_id",
    "split",
    "start_date",
    "end_date",
)

FACTOR_METRIC_REQUIRED_COLUMNS = (
    "factor_id",
    "metric_scope",
    "split",
)

BACKTEST_METRIC_REQUIRED_COLUMNS = (
    "factor_id",
    "backtest_run_id",
    "split",
    "start_date",
    "end_date",
)

BACKTEST_METRIC_COLUMNS = (
    *BACKTEST_METRIC_REQUIRED_COLUMNS,
    "total_return",
    "annual_return",
    "sharpe",
    "max_drawdown",
    "calmar",
    "win_rate",
    "average_turnover",
    "total_cost",
    "annual_cost",
    "number_of_trades",
    "average_holding_count",
    "source_path",
)

UNIVERSE_REQUIRED_COLUMNS = (
    "code",
    "pool_id",
    "selected_at",
    "source_signature",
)

TABLE_FILENAMES = (
    "market.parquet",
    "universe.csv",
    "factor_catalog.parquet",
    "factor_metrics.parquet",
    "backtest_metrics.parquet",
    "backtest_runs.csv",
)
