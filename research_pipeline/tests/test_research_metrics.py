import pandas as pd
import pytest

from research_pipeline.research_system.evaluation import conditional_ic, daily_ic
from research_pipeline.research_system.features import make_forward_return, market_state_features


def _market():
    rows = []
    prices = {"000001": [10, 11, 12, 13], "000002": [10, 10, 9, 10], "000003": [10, 9, 10, 9]}
    for code, values in prices.items():
        for index, close in enumerate(values):
            rows.append({
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                "code": code,
                "open": close,
                "close": close,
                "high": close,
                "low": close,
                "volume": 100.0,
                "amount": close * 100,
            })
    return pd.DataFrame(rows)


def test_make_forward_return_shifts_within_each_code():
    result = make_forward_return(_market(), horizon=1)
    first = result[(result["code"] == "000001") & (result["date"] == pd.Timestamp("2024-01-01"))].iloc[0]

    assert first["target"] == pytest.approx(0.1)
    assert result["target"].isna().sum() == 3


def test_market_state_features_produce_explainable_daily_features():
    result = market_state_features(_market(), volatility_window=2)

    assert {"date", "market_return", "market_volatility", "up_ratio", "cross_section_dispersion"}.issubset(result.columns)
    assert len(result) == 4
    assert result["up_ratio"].between(0, 1).all()


def test_conditional_ic_aggregates_only_dates_with_three_valid_stocks():
    market = _market()
    factor_values = market[["date", "code"]].copy()
    factor_values["factor_id"] = "f1"
    factor_values["value"] = factor_values["code"].map({"000001": 3.0, "000002": 2.0, "000003": 1.0})
    target = market[["date", "code"]].copy()
    target["target"] = target["code"].map({"000001": 0.03, "000002": 0.01, "000003": -0.01})
    states = pd.DataFrame({"date": sorted(market["date"].unique()), "state_id": ["bull", "bull", "bear", "bear"]})

    daily = daily_ic(factor_values, target)
    result = conditional_ic(factor_values, target, states)

    assert len(daily) == 4
    assert daily["rank_ic"].notna().all()
    assert set(result["state_id"]) == {"bull", "bear"}
    assert result["sample_count"].min() == 2
    assert result["ic_mean"].notna().all()
