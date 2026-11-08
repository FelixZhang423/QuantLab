from unittest.mock import patch

import pandas as pd
import pytest

from custom_bt.engine import BacktestConfig
from repositories import company_source, snapshot_store
from repositories.panel_store import expression_fields, expression_lookback, load_panel_for_pool


@pytest.fixture
def panel_source(monkeypatch):
    calls = []

    def writer(codes, fields, output, start, end):
        calls.append((start, end))
        dates = pd.date_range(start, end)
        frame = pd.DataFrame({"date": dates, "code": codes[0],
                              **{field: range(len(dates)) for field in fields}})
        frame.to_parquet(output, index=False)

    monkeypatch.setattr(company_source, "write_pool_panel", writer)
    return calls


def test_snapshot_panel_projects_columns_and_reuses_offline(tmp_path, panel_source):
    fields = ["open", "close", "Ifsuspend", "if_up", "if_down", "volume"]
    manifest = snapshot_store.create_or_reuse_snapshot(["1"], fields, "2024-01-01", "2024-01-15",
                                                       pool_id="p", snapshot_root=tmp_path)
    with patch.object(company_source, "write_pool_panel", side_effect=AssertionError("offline")), \
         patch.object(company_source, "meta", side_effect=AssertionError("offline")):
        panel = load_panel_for_pool("clickhouse", ["1"], BacktestConfig("2024-01-10", "2024-01-15"),
                                    pool_id="p", snapshot_root=tmp_path,
                                    snapshot_id=manifest["snapshot_id"], lookback_days=2)
    assert "volume" not in panel
    assert panel.date.min() == pd.Timestamp("2024-01-08")
    assert panel.attrs["snapshot_id"] == manifest["snapshot_id"]


def test_fresh_snapshot_plans_nested_expression_warmup(tmp_path, panel_source):
    expression = "ts_mean(delay(close, 3), 5)"
    assert expression_fields([expression]) == ["close"]
    assert expression_lookback([expression]) == 8
    panel = load_panel_for_pool("clickhouse", ["1"], BacktestConfig("2024-01-10", "2024-01-15"),
                                pool_id="p", fields=["close"], snapshot_root=tmp_path,
                                lookback_days=expression_lookback([expression]))
    assert panel_source[0][0] < "2024-01-10"
    assert len(panel[panel.date < "2024-01-10"]) == 8


def test_old_sources_and_incompatible_snapshot_are_explicit_errors(tmp_path, panel_source):
    config = BacktestConfig("2024-01-10", "2024-01-15")
    with pytest.raises(ValueError, match="retired"):
        load_panel_for_pool("local", ["1"], config, snapshot_root=tmp_path)
    panel = load_panel_for_pool("clickhouse", ["1"], config, pool_id="p", snapshot_root=tmp_path)
    with pytest.raises(ValueError, match="fields"):
        load_panel_for_pool("clickhouse", ["1"], config, pool_id="p", fields=["volume"],
                            snapshot_root=tmp_path, snapshot_id=panel.attrs["snapshot_id"])


def test_completed_runtime_reuses_memmaps_without_loading_wide_panel(tmp_path, panel_source):
    from custom_bt.factor_generation import prepare_factor_runtime
    manifest = {"pool_id": "p", "data_source": "clickhouse",
                "source_signature": company_source.source_signature()}
    options = dict(pools_root=tmp_path / "pools", pool_id="p", runtime_root=tmp_path / "runtime",
                   fields=["close"], snapshot_root=tmp_path / "snapshots", pool_manifest=manifest,
                   pool_codes=["000001"], splits={"train": {"cache_start": "2024-01-01", "cache_end": "2024-01-15"}})
    first = prepare_factor_runtime(**options)
    with patch("single_factor.preprocess.materialize_memmap", side_effect=AssertionError("must reuse")), \
         patch.object(snapshot_store, "load_snapshot", side_effect=AssertionError("no full panel load")):
        assert prepare_factor_runtime(**options) == first
    assert len(panel_source) == 1
