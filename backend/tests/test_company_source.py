"""custom_bt/company_source.py 的单元测试：公司库 SQL、面板写出与公司库建池。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from api import live_db
from custom_bt import company_source, mysql_store
from custom_bt.pools import create_pool_from_company, load_pool_codes, load_pool_manifest


def _settings() -> live_db.LiveDBSettings:
    # 假 client 不会联网，settings 只需要是一个合法对象。
    return live_db.LiveDBSettings()


class _FakePanelClient:
    """替身 client：把预置的列直接写成 ClickHouse 风格的 Parquet（日期为整数天数）。"""

    def __init__(self, columns):
        self.columns = columns
        self.sqls = []
        self.kwargs = []

    def query_to_file(self, sql, path, **kwargs):
        self.sqls.append(sql)
        self.kwargs.append(kwargs)
        pq.write_table(pa.table(self.columns), path)
        return path


def _days(*values: str) -> list[int]:
    return [(date.fromisoformat(value) - date(1970, 1, 1)).days for value in values]


# ---------- 数据源解析 ----------


def test_resolve_data_source_prefers_explicit_value_then_manifest():
    assert company_source.resolve_data_source("clickhouse") == "clickhouse"
    assert company_source.resolve_data_source("company") == "clickhouse"
    assert company_source.resolve_data_source("LIVE") == "clickhouse"
    assert company_source.resolve_data_source(None, {"data_source": "clickhouse"}) == "clickhouse"
    assert company_source.resolve_data_source("local", {"data_source": "clickhouse"}) == "local"
    assert company_source.resolve_data_source(None, {}) == "local"
    assert company_source.resolve_data_source(None) == "local"


def test_source_signature_and_panel_fields():
    assert company_source.source_signature() == company_source.SOURCE_SIGNATURE
    fields = company_source.panel_field_names()
    assert {"date", "code", "close", "volume", "vwap", "ListedDate"} <= fields
    assert len(company_source.DEFAULT_PANEL_FIELDS) == 45


# ---------- SQL ----------


def test_selection_days_sql_is_readonly_and_escapes_codes():
    sql = company_source.build_selection_days_sql(
        ["1", "600000"], "2024-01-02", "2024-01-31"
    )
    live_db.guard_readonly(sql)
    assert "uniqExact(toDate(d.timestamps))" in sql
    assert live_db.DAILY_TABLE in sql
    assert "d.timestamps BETWEEN '2024-01-02' AND '2024-01-31'" in sql
    assert "d.category = 'stock'" in sql
    assert "d.code IN ('000001','600000')" in sql

    escaped = company_source.build_selection_days_sql(
        ["O'BRIEN"], "2024-01-02", "2024-01-31"
    )
    assert "d.code IN ('O\\'BRIEN')" in escaped
    live_db.guard_readonly(escaped)


def test_selection_days_sql_without_codes_has_no_code_filter():
    sql = company_source.build_selection_days_sql(None, "2024-01-02", "2024-01-31")
    assert "d.code IN" not in sql
    live_db.guard_readonly(sql)


def test_selection_stats_sql_applies_suspension_and_listing_filters():
    sql = company_source.build_selection_stats_sql(
        ["000001"],
        "2024-01-02",
        "2024-01-31",
        exclude_suspended=True,
        min_listed_days=365,
    )
    live_db.guard_readonly(sql)
    assert "toFloat64(d.vol) > 0 AND toFloat64(d.amount) > 0" in sql
    assert "d.Ifsuspend = '0'" in sql
    assert f"LEFT ANY JOIN {live_db.DIM_TABLE} AS m" in sql
    assert "dateDiff('day', toDate(m.ListedDate), toDate(d.timestamps)) >= 365" in sql
    assert "avgIf(toFloat64(d.amount)" in sql

    plain = company_source.build_selection_stats_sql(
        None,
        "2024-01-02",
        "2024-01-31",
        exclude_suspended=False,
        min_listed_days=0,
    )
    assert "Ifsuspend" not in plain
    assert "LEFT ANY JOIN" not in plain

    with pytest.raises(ValueError):
        company_source.build_selection_stats_sql(
            None,
            "2024-01-02",
            "2024-01-31",
            exclude_suspended=True,
            min_listed_days=-1,
        )


def test_panel_sql_maps_volume_vwap_and_dim_fields():
    sql = company_source.build_panel_sql(
        ["000001"], ["volume", "vwap", "ListedDate", "close"], "2024-01-01", "2024-01-31"
    )
    live_db.guard_readonly(sql)
    assert "toDate(d.timestamps) AS `date`" in sql
    assert "toString(d.code) AS `code`" in sql
    assert "toFloat64(d.`vol`) AS `volume`" in sql
    assert "toFloat64(d.amount) / nullIf(toFloat64(d.vol), 0) AS `vwap`" in sql
    assert "toDate(m.ListedDate) AS `ListedDate`" in sql
    assert f"LEFT ANY JOIN {live_db.DIM_TABLE} AS m" in sql
    assert "d.timestamps >= '2024-01-01'" in sql
    assert "d.timestamps <= '2024-01-31'" in sql
    assert "ORDER BY d.timestamps, d.code" in sql


def test_panel_sql_without_dim_fields_has_no_join():
    sql = company_source.build_panel_sql(["000001"], ["close"])
    assert "LEFT ANY JOIN" not in sql
    assert "d.timestamps >=" not in sql


def test_panel_sql_rejects_unknown_fields():
    with pytest.raises(ValueError, match="unsupported panel field"):
        company_source.build_panel_sql(["000001"], ["not_a_field"])


# ---------- Parquet 日期重写 ----------


def test_rewrite_dates_turns_integer_days_into_timestamps(tmp_path):
    raw = tmp_path / "raw.parquet"
    final = tmp_path / "panel.parquet"
    pq.write_table(
        pa.table(
            {
                "date": pa.array(_days("2024-01-01", "2024-01-02"), type=pa.uint16()),
                "code": pa.array(["000001", "000001"]),
                "close": pa.array([10.0, 10.5]),
            }
        ),
        raw,
    )

    company_source._rewrite_dates(raw, final)

    frame = pd.read_parquet(final)
    assert str(frame["date"].dtype).startswith("datetime64")
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-01-02"]
    # materialize_memmap 用的 PyArrow 日期过滤必须可用
    filtered = pd.read_parquet(
        final, filters=[("date", ">=", pd.Timestamp("2024-01-02"))]
    )
    assert filtered["close"].tolist() == [10.5]


# ---------- 面板读写 ----------


def test_write_pool_panel_writes_timestamp_panel(tmp_path):
    client = _FakePanelClient(
        {
            "date": pa.array(_days("2024-01-01", "2024-01-02"), type=pa.uint16()),
            "code": pa.array(["000001", "000001"]),
            "close": pa.array([10.0, 10.5]),
        }
    )
    output = tmp_path / "run" / "panel.parquet"

    result = company_source.write_pool_panel(
        ["000001"],
        ["close"],
        output,
        "2024-01-01",
        "2024-01-02",
        settings=_settings(),
        client=client,
    )

    assert result["rows"] == 2
    assert result["n_stocks"] == 1
    assert result["date_min"] == "2024-01-01"
    assert result["date_max"] == "2024-01-02"
    assert result["panel_path"] == str(output.resolve())
    assert client.sqls and "toFloat64(d.`close`) AS `close`" in client.sqls[0]
    assert client.kwargs[0]["timeout"] == _settings().panel_timeout
    assert output.is_file()
    assert not output.with_name(output.name + ".raw.parquet").exists()

    frame = pd.read_parquet(output)
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-01-02"]
    assert frame["close"].tolist() == [10.0, 10.5]


def test_write_pool_panel_removes_empty_output(tmp_path):
    client = _FakePanelClient(
        {
            "date": pa.array([], type=pa.uint16()),
            "code": pa.array([], type=pa.string()),
            "close": pa.array([], type=pa.float64()),
        }
    )
    output = tmp_path / "panel.parquet"

    with pytest.raises(ValueError, match="no rows"):
        company_source.write_pool_panel(
            ["000001"], ["close"], output, settings=_settings(), client=client
        )
    assert not output.exists()
    assert not output.with_name(output.name + ".raw.parquet").exists()


def test_load_panel_normalizes_clickhouse_types():
    client = _FakePanelClient(
        {
            "date": pa.array(_days("2024-01-01", "2024-01-02"), type=pa.uint16()),
            "code": pa.array(["000001", "000001"]),
            "close": pa.array([10.0, 10.5]),
            "volume": pa.array([100.0, 200.0]),
        }
    )

    frame = company_source.load_panel(
        ["000001"],
        "2024-01-01",
        "2024-01-02",
        ["close", "volume"],
        settings=_settings(),
        client=client,
    )

    assert frame.columns.tolist() == ["date", "code", "close", "volume"]
    assert str(frame["date"].dtype).startswith("datetime64")
    assert frame["close"].dtype.kind == "f"
    assert frame["volume"].tolist() == [100.0, 200.0]
    assert "toFloat64(d.`vol`) AS `volume`" in client.sqls[0]


def test_load_panel_rejects_empty_columns():
    with pytest.raises(ValueError):
        company_source.load_panel(["000001"], columns=[])


# ---------- create_pool_from_company ----------


def _stub_selection(monkeypatch, days, stats):
    monkeypatch.setattr(company_source, "selection_days", lambda *args, **kwargs: days)
    monkeypatch.setattr(company_source, "selection_stats", lambda *args, **kwargs: stats)


def test_create_pool_from_company_selects_by_amount_and_writes_manifest(tmp_path, monkeypatch):
    _stub_selection(
        monkeypatch,
        10,
        [
            {"code": "000001", "valid_rows": 10, "average_amount": 100.0},
            {"code": "600000", "valid_rows": 8, "average_amount": 300.0},
            {"code": "300750", "valid_rows": 10, "average_amount": 200.0},
        ],
    )
    monkeypatch.setattr(mysql_store, "persist_pool", lambda pool_dir: True)

    manifest = create_pool_from_company(
        tmp_path / "pools",
        "company_pool",
        "2024-01-01",
        "2024-01-31",
        top_n=2,
        min_coverage=1.0,
    )

    assert manifest["data_source"] == "clickhouse"
    assert manifest["source_signature"] == company_source.SOURCE_SIGNATURE
    assert manifest["selection_days"] == 10
    assert manifest["minimum_valid_rows"] == 10
    assert manifest["n_stocks"] == 2
    # 600000 覆盖率不足被过滤；其余按平均成交额降序
    codes = load_pool_codes(tmp_path / "pools", manifest["pool_id"])
    assert codes == ["300750", "000001"]
    stored = load_pool_manifest(tmp_path / "pools", manifest["pool_id"])
    assert stored["data_source"] == "clickhouse"
    assert stored["selected_stats"][0]["coverage"] == 1.0


def test_create_pool_from_company_strict_top_n(tmp_path, monkeypatch):
    _stub_selection(
        monkeypatch,
        5,
        [
            {"code": "000001", "valid_rows": 5, "average_amount": 100.0},
            {"code": "600000", "valid_rows": 5, "average_amount": 200.0},
        ],
    )
    monkeypatch.setattr(mysql_store, "persist_pool", lambda pool_dir: True)

    with pytest.raises(ValueError, match="only 2 stocks"):
        create_pool_from_company(
            tmp_path / "pools", "strict", "2024-01-01", "2024-01-31", top_n=5
        )

    manifest = create_pool_from_company(
        tmp_path / "pools",
        "lenient",
        "2024-01-01",
        "2024-01-31",
        top_n=5,
        strict_top_n=False,
    )
    assert manifest["n_stocks"] == 2
    assert manifest["top_n"] == 5


def test_create_pool_from_company_pool_id_ignores_provenance(tmp_path, monkeypatch):
    _stub_selection(
        monkeypatch,
        5,
        [{"code": "000001", "valid_rows": 5, "average_amount": 100.0}],
    )
    monkeypatch.setattr(mysql_store, "persist_pool", lambda pool_dir: True)

    first = create_pool_from_company(
        tmp_path / "pools",
        "same_pool",
        "2024-01-01",
        "2024-01-31",
        provenance={"selection_mode": "all"},
    )
    second = create_pool_from_company(
        tmp_path / "pools",
        "same_pool",
        "2024-01-01",
        "2024-01-31",
        provenance={"selection_mode": "manual"},
        overwrite=True,
    )

    assert first["pool_id"] == second["pool_id"]
    assert second["provenance"] == {"selection_mode": "manual"}


def test_create_pool_from_company_rejects_empty_selection(tmp_path, monkeypatch):
    _stub_selection(monkeypatch, 0, [])
    with pytest.raises(ValueError, match="no dates"):
        create_pool_from_company(tmp_path / "pools", "empty", "2024-01-01", "2024-01-31")

    _stub_selection(monkeypatch, 5, [])
    with pytest.raises(ValueError, match="no stocks"):
        create_pool_from_company(tmp_path / "pools", "empty", "2024-01-01", "2024-01-31")
