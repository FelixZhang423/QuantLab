import json

import numpy as np
import pandas as pd
import pytest

from research_pipeline.research_system.expression_engine import ExpressionError, evaluate_expression
from research_pipeline.research_system.factor_values import materialize_factor_values


def _market():
    rows = []
    for code, values in {"000001": [10, 11, 12, 13], "000002": [20, 19, 18, 17]}.items():
        for index, close in enumerate(values):
            rows.append({
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=index),
                "code": code,
                "open": close - 0.5,
                "close": close,
                "ycp": close - 1,
                "high": close + 1,
                "low": close - 1,
                "volume": 100 + index,
            })
    return pd.DataFrame(rows)


def test_evaluate_expression_supports_time_series_and_cross_section_operators():
    result = evaluate_expression("rank(ts_mean(close,2))", _market())

    assert list(result.columns) == ["date", "code", "value"]
    assert result["value"].isna().sum() == 2
    assert set(result.dropna()["value"].unique()) == {0.5, 1.0}


def test_evaluate_expression_supports_infix_arithmetic_and_aliases():
    result = evaluate_expression("close - delay(close,1)", _market())
    first_code = result[result["code"] == "000001"]["value"].tolist()

    assert np.isnan(first_code[0])
    assert first_code[1:] == [1.0, 1.0, 1.0]


def test_evaluate_expression_accepts_alphagen_dollar_field_prefix():
    result = evaluate_expression("$close", _market())

    assert result["value"].tolist() == [10.0, 20.0, 11.0, 19.0, 12.0, 18.0, 13.0, 17.0]


def test_evaluate_expression_accepts_alphagen_day_suffix_constants():
    result = evaluate_expression("ts_mean(close,2d)", _market())

    assert result["value"].notna().sum() == 6


def test_evaluate_expression_rejects_unknown_names():
    with pytest.raises(ExpressionError, match="unknown field"):
        evaluate_expression("rank(not_a_field)", _market())


def test_materialize_factor_values_writes_partition_and_manifest(tmp_path):
    data_root = tmp_path / "research_data"
    snapshot = data_root / "snapshots" / "snap"
    snapshot.mkdir(parents=True)
    _market().to_parquet(snapshot / "market.parquet", index=False)
    catalog = pd.DataFrame({"factor_id": ["f1"], "expression": ["close"], "accepted": [True]})
    catalog.to_parquet(snapshot / "factor_catalog.parquet", index=False)
    (data_root / "current.txt").write_text("snap\n", encoding="utf-8")

    result = materialize_factor_values(data_root, tmp_path / "runs", snapshot_id="snap")
    run_dir = tmp_path / "runs" / result["run_id"]
    manifest = json.loads((run_dir / "factor_values_manifest.json").read_text(encoding="utf-8"))

    assert result["computed"] == 1
    assert manifest["errors"] == []
    values = pd.read_parquet(run_dir / "factor_values" / "factor_id=f1" / "values.parquet")
    assert len(values) == 8
    assert values["factor_id"].unique().tolist() == ["f1"]
