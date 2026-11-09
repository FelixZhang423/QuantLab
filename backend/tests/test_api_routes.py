"""api/main.py 的股票池候选 / 建池 / 任务状态路由测试（无网络、无 TestClient）。"""
from __future__ import annotations

import pandas as pd

import json
import subprocess
import sys
from pathlib import Path

import pytest
from errors import DomainError

from schemas import FactorBacktestRequest, FactorGenerationRequest, FactorGenerationSplit, ManualBacktestRequest, PoolCreateRequest
from workers.job_dispatcher import create_platform_job
from repositories import clickhouse as live_db
from workers import job_runner
from repositories import company_source
from custom_bt.factor_backtest import factor_id

import common
from services import (
    data_service,
    factor_backtest_service,
    generation_service,
    job_service,
    manual_backtest_service,
    pool_service,
    result_service,
)
from repositories import mysql_store


def _seal_confirmed(run_dir):
    import hashlib
    path = run_dir / "confirmed_factors.jsonl"
    if not path.exists():
        return
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for record in records:
        record.update(status="confirmed", confirmed=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    (run_dir / "confirmation_manifest.json").write_text(json.dumps({"status": "finished", "confirmed_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")


def _patch_job_deps(monkeypatch, attr, value):
    for module in (
        pool_service,
        generation_service,
        factor_backtest_service,
        manual_backtest_service,
    ):
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, value)


def _live(items, cached=False):
    return live_db.LiveResult(items, cached, "2026-10-20 10:00:00")


def _items():
    return [
        {
            "code": "000001", "name": "平安银行", "industry": "银行",
            "exchange": "SZ", "exchange_label": "深市", "board": "深市主板",
            "sector": "1.0", "listed_state": "1.0", "listed_date": "1991-04-03",
            "rows": 100, "start_date": "1991-04-03", "end_date": "2026-10-09",
            "latest_date": "2026-10-09", "latest_close": 11.59,
            "latest_volume": 1000, "latest_amount": 300.0, "latest_ifsuspend": 0,
        },
        {
            "code": "600000", "name": "浦发银行", "industry": "银行",
            "exchange": "SH", "exchange_label": "沪市", "board": "沪市主板",
            "sector": "1.0", "listed_state": "1.0", "listed_date": "1999-11-10",
            "rows": 100, "start_date": "1999-11-10", "end_date": "2026-10-09",
            "latest_date": "2026-10-09", "latest_close": 8.0,
            "latest_volume": 900, "latest_amount": 100.0, "latest_ifsuspend": 0,
        },
        {
            "code": "300750", "name": "宁德时代", "industry": "电池",
            "exchange": "SZ", "exchange_label": "深市", "board": "创业板",
            "sector": "6.0", "listed_state": "1.0", "listed_date": "2018-06-11",
            "rows": 100, "start_date": "2018-06-11", "end_date": "2026-10-09",
            "latest_date": "2026-10-09", "latest_close": 200.0,
            "latest_volume": 800, "latest_amount": 200.0, "latest_ifsuspend": 0,
        },
        {
            "code": "688981", "name": "中芯国际", "industry": "半导体",
            "exchange": "SH", "exchange_label": "沪市", "board": "科创板",
            "sector": "7.0", "listed_state": "1.0", "listed_date": "2020-07-16",
            "rows": 100, "start_date": "2020-07-16", "end_date": "2026-10-09",
            "latest_date": "2026-10-09", "latest_close": 50.0,
            "latest_volume": 700, "latest_amount": 50.0, "latest_ifsuspend": 0,
        },
        {
            "code": "920879", "name": None, "industry": None,
            "exchange": "BJ", "exchange_label": "北交所", "board": "北交所",
            "sector": None, "listed_state": None, "listed_date": "2026-03-27",
            "rows": 10, "start_date": "2026-03-27", "end_date": "2026-10-09",
            "latest_date": "2026-10-09", "latest_close": 3.2,
            "latest_volume": 10, "latest_amount": 10.0, "latest_ifsuspend": 1,
        },
    ]


@pytest.fixture()
def master(tmp_path, monkeypatch):
    root = tmp_path / "master"
    (root / "stocks").mkdir(parents=True)
    (root / "meta.json").write_text(
        json.dumps(
            {
                "date_min": "2021-06-18",
                "date_max": "2026-06-16",
                "source_signature": "sig",
            }
        ),
        encoding="utf-8",
    )
    for code in ("000001", "600000", "300750"):
        (root / "stocks" / f"{code}.parquet").write_bytes(b"")
    monkeypatch.setattr(company_source, "meta", lambda: {"date_min": "2021-06-18", "date_max": "2026-06-16", "source_signature": "sig"})
    monkeypatch.setattr(common, "SNAPSHOT_ROOT", root)
    monkeypatch.setattr(common, "POOLS_ROOT", tmp_path / "pools")
    monkeypatch.setattr(common, "JOBS_ROOT", tmp_path / "jobs")
    return root


def _catalog_entry(name, category, table, column, alias=None, description="测试字段"):
    return {
        "name": name,
        "category": category,
        "source_table": table,
        "column": column,
        "panel_alias": alias,
        "description": description,
    }


def test_fields_endpoint_merges_catalog_and_metadata(monkeypatch):
    catalog = [
        _catalog_entry("vol", "行情与技术", live_db.DAILY_TABLE, "vol", "volume"),
        _catalog_entry("ma_signal", "行情与技术", live_db.DAILY_TABLE, "ma_signal"),
        _catalog_entry("ROE", "财务原始", company_source.FUNDAMENTAL_TABLE, "ROE", "fund_ROE"),
        _catalog_entry("WROE", "财务原始", company_source.FUNDAMENTAL_TABLE, "WROE"),
        _catalog_entry("PB", "估值", company_source.VALUATION_TABLE, "PB", "val_PB"),
    ]
    metadata = {
        (live_db.DAILY_TABLE, "vol"): {"dtype": "Decimal(18, 2)", "comment": ""},
        (live_db.DAILY_TABLE, "ma_signal"): {"dtype": "String", "comment": ""},
        (company_source.FUNDAMENTAL_TABLE, "ROE"): {"dtype": "Decimal(20, 0)", "comment": ""},
        (company_source.FUNDAMENTAL_TABLE, "WROE"): {"dtype": "Decimal(20, 0)", "comment": ""},
        (company_source.VALUATION_TABLE, "PB"): {"dtype": "Decimal(18, 4)", "comment": ""},
    }
    monkeypatch.setattr(data_service, "_field_catalog", lambda: catalog)
    monkeypatch.setattr(data_service, "_field_metadata", lambda: (metadata, None))
    payload = data_service.get_fields()
    by_name = {field["name"]: field for field in payload["fields"]}
    assert payload["total"] == 5
    assert payload["offline"] is False
    assert by_name["vol"]["status"] == "usable"
    assert by_name["vol"]["panel_alias"] == "volume"
    assert by_name["ma_signal"]["status"] == "unavailable"
    assert by_name["ROE"]["status"] == "usable" and by_name["ROE"]["panel_alias"] == "fund_ROE"
    assert by_name["WROE"]["status"] == "pending"
    assert by_name["PB"]["status"] == "usable" and by_name["PB"]["dtype"] == "Decimal(18, 4)"
    assert payload["status_counts"] == {"usable": 3, "pending": 1, "unavailable": 1}


def test_fields_endpoint_offline_fallback(monkeypatch):
    catalog = [
        _catalog_entry("vol", "行情与技术", live_db.DAILY_TABLE, "vol", "volume"),
        _catalog_entry("ROE", "财务原始", company_source.FUNDAMENTAL_TABLE, "ROE", "fund_ROE"),
        _catalog_entry("PB", "估值", company_source.VALUATION_TABLE, "PB", "val_PB"),
    ]
    monkeypatch.setattr(data_service, "_field_catalog", lambda: catalog)
    monkeypatch.setattr(data_service, "_field_metadata", lambda: (None, "ClickHouse 不可达"))
    payload = data_service.get_fields()
    assert payload["offline"] is True
    assert payload["metadata_error"] == "ClickHouse 不可达"
    assert all(field["found_in_db"] is None and field["dtype"] is None for field in payload["fields"])
    assert payload["status_counts"]["usable"] == 3


def test_field_catalog_file_has_expected_categories():
    catalog = data_service._field_catalog()
    assert len(catalog) == 384
    counts = {}
    for entry in catalog:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    assert counts == {"行情与技术": 27, "财务原始": 67, "财务衍生": 248, "估值": 42}
    assert all(entry.get("theme") and entry.get("unit") and entry.get("dimension") for entry in catalog)
    assert not any(entry["name"] in {"BasicEPS", "DilutedEPS", "EPS"} for entry in catalog)
    assert not any(entry["category"] == "证券信息" for entry in catalog)
    assert not any(
        entry["name"] in {"market_code", "category", "code", "timestamps",
                          "ma_signal", "macd_signal", "kdj_signal", "strategy"}
        for entry in catalog
    )
    valuation_columns = {
        entry["column"] for entry in catalog
        if entry["source_table"] == company_source.VALUATION_TABLE
    }
    assert len(company_source.VALUATION_FIELDS) == 42
    assert valuation_columns == set(company_source.VALUATION_FIELDS)
    assert not {"DividendRatioLYR2", "DividendRatio2", "HoldProportionPAccount"} & valuation_columns
    assert "PE" in valuation_columns
    assert len(company_source.FUNDAMENTAL_FIELDS) == 51
    assert len(company_source.DERIVED_FUNDAMENTAL_FIELDS) == 16
    assert sum(1 for entry in catalog if entry.get("panel_alias")) == 384
    derivative_columns = {
        entry["column"] for entry in catalog if entry["category"] == "财务衍生"
    }
    assert len(derivative_columns) == 248
    assert "EndDate" not in derivative_columns
    assert "InfoPublDate" not in derivative_columns
    assert all(
        entry.get("panel_alias")
        for entry in catalog if entry["category"] == "财务衍生"
    )
    assert {
        entry["name"] for entry in catalog if entry.get("period_type") == "flow_q"
    } == set(company_source.DERIVED_FUNDAMENTAL_FIELDS)
    assert not {
        "ROEByReport", "InvestmentProperty", "FairValueChangeIncome",
        "NAPSAdjusted", "DividendPayable", "TradingAssets", "WROECut",
        "FairValueChangeIncome_q",
    } & {entry["name"] for entry in catalog}
    assert not {
        "Ifsuspend", "if_up", "if_flat", "if_down", "FallOnDebut", "FallOnNAPS",
        "StockBoard", "LimitBoard", "SurgedLimit", "DeclineLimit",
    } & {entry["name"] for entry in catalog}
    assert not {
        "dif", "LowestPrice", "HighestPrice", "LowestPriceRY", "HighestPriceRY",
        "LowestPriceRMSix", "HighestPriceRMSix", "LowestPriceYTD", "HighestPriceYTD",
        "HighestPriceRMThree", "LowestPriceRMThree", "LowestPriceRM", "HighestPriceRM",
        "HighestPriceTM", "LowestPriceTM", "HighestPriceRW", "LowestPriceRW",
        "HighestPriceTW", "dea", "LowestPriceTW", "macd", "FallingDownDays",
        "RisingUpDays",
    } & {entry["name"] for entry in catalog}
    aliased_raw_columns = {
        entry["column"] for entry in catalog
        if entry["category"] == "财务原始" and entry.get("panel_alias")
    }
    assert aliased_raw_columns == set(company_source.FUNDAMENTAL_FIELDS)
    assert sum(
        1 for entry in catalog
        if entry["category"] == "财务原始" and not entry.get("panel_alias")
    ) == 0


def _stub_universe(monkeypatch, items=None):
    monkeypatch.setattr(
        live_db, "live_stock_rows", lambda *args, **kwargs: _live(items or _items())
    )


def test_universe_options_reports_facets_from_company_db(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = data_service.get_universe_options()

    assert data["total"] == 5
    assert data["data_source"] == "clickhouse"
    assert data["ready"] is True
    # 候选不再与本地缓存取交集：creatable 与全库一致，无排除
    assert data["master_total"] == 5
    assert data["creatable_total"] == 5
    assert data["excluded_total"] == 0
    assert "master_ready" not in data
    assert {item["value"] for item in data["industries"]} == {"银行", "电池", "半导体"}
    assert data["missing"]["industry"] == 1


def test_universe_stocks_paginates_all_matched(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = data_service.get_universe_stocks(
        industries=["银行"],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        limit=1,
        offset=1,
    )

    assert data["matched_total"] == 2
    assert data["total"] == 2
    assert data["data_source"] == "clickhouse"
    assert "n_creatable" not in data
    assert "n_excluded" not in data
    assert data["items"][0]["code"] == "600000"  # 按成交额降序后的第二只
    assert data["items"][0]["creatable"] is True


def test_universe_stocks_includes_stocks_outside_local_master(master, monkeypatch):
    """本地缓存没有的股票（688981 / 920879）也必须出现在候选里。"""
    _stub_universe(monkeypatch)
    data = data_service.get_universe_stocks(
        industries=["半导体"],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        limit=50,
        offset=0,
    )

    assert data["matched_total"] == 1
    assert data["total"] == 1
    assert data["items"][0]["code"] == "688981"
    assert data["items"][0]["creatable"] is True


def test_universe_codes_returns_all_matched_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = data_service.get_universe_codes(
        industries=[],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
    )

    assert data["codes"] == ["000001", "300750", "600000", "688981", "920879"]  # 排序后返回
    assert data["total"] == 5
    assert data["matched_total"] == 5
    assert data["data_source"] == "clickhouse"
    assert "master_ready" not in data
    assert "n_creatable" not in data

    banks = data_service.get_universe_codes(
        industries=["银行"],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
    )
    assert banks["codes"] == ["000001", "600000"]
    assert banks["total"] == 2


def test_create_pool_builds_company_payload_and_spawns_job(master, monkeypatch):
    _stub_universe(monkeypatch)
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["root"] = jobs_root
        captured["operation"] = operation
        captured["payload"] = payload
        job_dir = Path(jobs_root) / "job_123"
        job_dir.mkdir(parents=True)
        return job_dir

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir)
    )

    response = pool_service.create_pool(
        PoolCreateRequest(
            name="bank_pool",
            selection_start="2024-01-01",
            selection_end="2024-06-30",
            industries=["银行"],
            top_n=10,
            min_coverage=0.9,
        )
    )

    payload = captured["payload"]
    assert captured["operation"] == "create_pool"
    assert captured["spawned"].name == "job_123"
    assert payload["data_source"] == "clickhouse"
    assert "store_dir" not in payload  # 不再需要本地主缓存目录
    assert payload["pools_root"] == str(common.POOLS_ROOT)
    assert payload["codes"] == ["000001", "600000"]
    assert payload["strict_top_n"] is False
    assert payload["category"] == "stock"
    assert payload["selection_start"] == "2024-01-01"
    assert payload["provenance"]["source"] == "clickhouse"
    assert payload["provenance"]["daily_table"] == live_db.DAILY_TABLE
    assert payload["provenance"]["dim_table"] == live_db.DIM_TABLE
    assert payload["provenance"]["matched_total"] == 2
    assert payload["provenance"]["selection_mode"] == "all"
    assert payload["provenance"]["selected_total"] == 2
    assert payload["provenance"]["filters"]["industries"] == ["银行"]
    assert "excluded_total" not in payload["provenance"]
    assert response["job_id"] == "job_123"
    assert response["status"] == "queued"
    assert any("少于 TopN" in item for item in response["warnings"])


def test_create_pool_takes_all_matched_codes_from_company(master, monkeypatch, tmp_path):
    """不传 selected_codes = 使用全部匹配股票，不再按本地缓存排除。"""
    _stub_universe(monkeypatch)
    monkeypatch.setattr(common, "SNAPSHOT_ROOT", tmp_path / "no-master")  # 不依赖本地缓存
    captured = {}
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = pool_service.create_pool(
        PoolCreateRequest(
            name="all_stocks",
            selection_start="2024-01-01",
            selection_end="2024-06-30",
        )
    )

    assert captured["payload"]["codes"] == ["000001", "300750", "600000", "688981", "920879"]
    assert captured["payload"]["provenance"]["matched_total"] == 5
    assert captured["payload"]["provenance"]["selected_total"] == 5
    assert response["warnings"] == []


def test_create_pool_uses_manual_selected_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    captured = {}
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = pool_service.create_pool(
        PoolCreateRequest(
            name="manual_bank",
            selection_start="2024-01-01",
            selection_end="2024-06-30",
            selected_codes=["600000", "688981", "999999"],
        )
    )

    payload = captured["payload"]
    assert payload["codes"] == ["600000", "688981"]  # 只保留当前筛选结果中的勾选股票
    assert payload["provenance"]["selection_mode"] == "manual"
    assert payload["provenance"]["selected_total"] == 2
    assert response["request_summary"]["selection_mode"] == "manual"
    assert response["request_summary"]["selected_total"] == 2
    assert any("不在当前筛选结果" in item for item in response["warnings"])
    assert not any("本地主缓存" in item for item in response["warnings"])


def test_create_pool_rejects_empty_or_unknown_manual_selection(master, monkeypatch):
    _stub_universe(monkeypatch)

    with pytest.raises(DomainError) as excinfo:
        pool_service.create_pool(
            PoolCreateRequest(
                name="empty_selection",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                selected_codes=[],
            )
        )
    assert excinfo.value.status_code == 422
    assert "至少勾选" in excinfo.value.detail

    with pytest.raises(DomainError) as excinfo:
        pool_service.create_pool(
            PoolCreateRequest(
                name="stale_selection",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                selected_codes=["999999"],
            )
        )
    assert excinfo.value.status_code == 422
    assert "都不在当前筛选结果" in excinfo.value.detail


def _make_job_dir(root: Path) -> Path:
    job_dir = Path(root) / "job_123"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def test_create_pool_rejects_empty_match(master, monkeypatch):
    _stub_universe(monkeypatch)
    with pytest.raises(DomainError) as excinfo:
        pool_service.create_pool(
            PoolCreateRequest(
                name="none",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                industries=["不存在的行业"],
            )
        )
    assert excinfo.value.status_code == 422
    assert "没有股票" in excinfo.value.detail


def test_create_pool_validates_name_and_window(master, monkeypatch):
    _stub_universe(monkeypatch)
    with pytest.raises(DomainError) as excinfo:
        pool_service.create_pool(
            PoolCreateRequest(
                name="../evil",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
            )
        )
    assert excinfo.value.status_code == 422

    with pytest.raises(DomainError) as excinfo:
        pool_service.create_pool(
            PoolCreateRequest(
                name="bad_window",
                selection_start="2024-06-30",
                selection_end="2024-01-01",
            )
        )
    assert excinfo.value.status_code == 422


def test_live_db_unavailable_maps_to_503(master, monkeypatch):
    def boom(*args, **kwargs):
        raise live_db.LiveDBUnavailable("company network required")

    monkeypatch.setattr(live_db, "live_stock_rows", boom)
    with pytest.raises(DomainError) as excinfo:
        data_service.get_universe_options()
    assert excinfo.value.status_code == 503


def test_job_status_route_reads_status_file(tmp_path, monkeypatch):
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "job_123"
    job_dir.mkdir(parents=True)
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "job_id": "job_123",
                "operation": "create_pool",
                "status": "finished",
                "message": "ok",
                "result": {"pool_id": "bank_abc"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(common, "JOBS_ROOT", jobs_root)

    status = job_service.get_job("job_123")
    assert status["status"] == "finished"
    assert status["result"]["pool_id"] == "bank_abc"

    with pytest.raises(DomainError) as excinfo:
        job_service.get_job("..")
    assert excinfo.value.status_code == 404


def test_spawn_platform_job_builds_command(tmp_path, monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(job_runner.subprocess, "Popen", FakePopen)
    job_dir = tmp_path / "job_123"
    job_dir.mkdir()

    job_runner.spawn_platform_job(job_dir)

    args, kwargs = calls[0]
    assert args[0] == [
        sys.executable,
        "-m",
        "cli",
        "run-platform-job",
        "--job-dir",
        str(job_dir),
    ]
    assert kwargs["cwd"] == str(job_runner.PROJECT_ROOT)
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert (job_dir / "runner.log").exists()


# ---------- 因子运行 / 因子批量回测 ----------


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _factor_case(master, tmp_path, monkeypatch, expressions=("$close",), signature="sig"):
    """搭建 master 元数据、股票池 manifest 与一个因子运行。"""
    pool_id = "pool_a"
    pool_dir = tmp_path / "pools" / pool_id
    _write_json(
        pool_dir / "manifest.json",
        {"pool_id": pool_id, "name": pool_id, "data_source": "clickhouse", "source_signature": signature},
    )
    factor_root = tmp_path / "factor_runs"
    run_dir = factor_root / "run_a"
    _write_json(
        run_dir / "factor_run.json",
        {
            "pool_id": pool_id,
            "source_signature": signature,
            "created_at": "2026-10-25T10:00:00",
            "data_source": "clickhouse",
            "accepted_count": len(expressions),
            "target_reached": True,
        },
    )
    _write_json(run_dir / "confirmation_manifest.json", {"status": "finished"})
    (run_dir / "confirmed_factors.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "expression": expression,
                    "accepted": True,
                    "pool_id": pool_id,
                    "source_signature": signature,
                    "ic": 0.01,
                    "rank_ic": 0.02,
                    "score": 1.5,
                },
                ensure_ascii=False,
            )
            for expression in expressions
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", factor_root)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    _seal_confirmed(run_dir)
    return pool_id, run_dir, factor_root


def test_factor_runs_list_and_detail(master, tmp_path, monkeypatch):
    pool_id, run_dir, factor_root = _factor_case(
        master, tmp_path, monkeypatch, expressions=("$close", "$open")
    )
    (factor_root / "ignored").mkdir()  # 没有 factor_run.json 的目录不展示

    data = factor_backtest_service.get_factor_runs(pool_id=None)
    assert data["total"] == 1
    assert data["runs"][0]["run_id"] == "run_a"
    assert data["runs"][0]["pool_id"] == pool_id
    assert data["runs"][0]["accepted_count"] == 2
    assert data["runs"][0]["target_reached"] is True
    assert factor_backtest_service.get_factor_runs(pool_id="other")["total"] == 0

    detail = factor_backtest_service.get_factor_run("run_a")
    assert detail["accepted_count"] == 2
    assert [item["factor_id"] for item in detail["accepted_factors"]] == [
        factor_id(1, "$close"),
        factor_id(2, "$open"),
    ]
    assert detail["accepted_factors"][0]["ic"] == 0.01
    assert detail["accepted_factors"][0]["canonical_expression"] == "close"
    assert detail["accepted_factors"][0]["backtest_expression"] == "close"
    assert detail["accepted_factors"][1]["canonical_expression"] == "open"
    assert detail["manifest"]["pool_id"] == pool_id

    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.get_factor_run("..")
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.get_factor_run("missing")
    assert excinfo.value.status_code == 404


def test_factor_runs_merge_mysql_metadata(master, tmp_path, monkeypatch):
    _, run_dir, _ = _factor_case(master, tmp_path, monkeypatch)
    run_dir_manifest = json.loads((run_dir / "factor_run.json").read_text(encoding="utf-8"))
    _write_json(run_dir / "factor_run.json", {**run_dir_manifest, "device": "cpu"})

    def fake_fetch(pool_id=None, limit=500):
        return [
            {
                "run_id": "run_a",
                "pool_id": "pool_a",
                "created_at": "2026-10-25T10:00:00",
                "accepted_count": 1,
                "attempts": 12,
                "device": "cuda",
                "training_seconds": 9.5,
                "duration_seconds": 12.0,
                "timesteps": 512,
                "hyperparameters": {"seed": 0},
                "split_days": {"train": 20},
            },
            {
                "run_id": "run_mysql_only",
                "pool_id": "pool_a",
                "created_at": "2026-10-24T09:00:00",
                "accepted_count": 2,
                "attempts": 30,
                "device": "cpu",
            },
        ]

    monkeypatch.setattr(mysql_store, "fetch_factor_runs", fake_fetch)

    data = factor_backtest_service.get_factor_runs(pool_id=None)

    assert data["source"] == "mysql"
    assert data["total"] == 2
    by_id = {run["run_id"]: run for run in data["runs"]}
    assert by_id["run_a"]["storage"] == "mysql+local"
    assert by_id["run_a"]["local_available"] is True
    assert by_id["run_a"]["device"] == "cpu"  # 本地 manifest 优先
    assert by_id["run_a"]["training_seconds"] == 9.5
    assert by_id["run_a"]["timesteps"] == 512
    assert by_id["run_a"]["hyperparameters"] == {"seed": 0}
    assert by_id["run_a"]["split_days"] == {"train": 20}
    assert by_id["run_mysql_only"]["storage"] == "mysql"
    assert by_id["run_mysql_only"]["local_available"] is False


def test_factor_run_detail_falls_back_to_mysql(master, tmp_path, monkeypatch):
    _, _, factor_root = _factor_case(master, tmp_path, monkeypatch)
    monkeypatch.setattr(mysql_store, "fetch_factor_run", lambda run_id: {
        "run_id": run_id,
        "pool_id": "pool_a",
        "created_at": "2026-10-24T09:00:00",
        "accepted_count": 1,
        "device": "cuda",
        "raw": {"pool_id": "pool_a", "run_name": "mysql_only", "confirmed_factors": [{"factor_id": factor_id(1,"$close"), "expression": "$close", "confirmed": True, "status": "confirmed"}]},
    })
    monkeypatch.setattr(
        mysql_store,
        "fetch_factor_run_factors",
        lambda run_id, accepted_only=False: [
            {
                "factor_id": factor_id(1, "$close"),
                "expression": "$close",
                "ic": 0.02,
                "segments": {"train": {"ic": 0.02}},
            }
        ],
    )

    detail = factor_backtest_service.get_factor_run("run_mysql_only")

    assert detail["storage"] == "mysql"
    assert detail["local_available"] is False
    assert detail["accepted_count"] == 1
    assert detail["accepted_factors"][0]["expression"] == "$close"
    assert detail["manifest"]["run_name"] == "mysql_only"
    assert not (factor_root / "run_mysql_only").exists()


def test_create_factor_backtest_builds_payload_and_spawns_job(master, tmp_path, monkeypatch):
    _, _, _ = _factor_case(master, tmp_path, monkeypatch, expressions=("$close", "$open"))
    selected = factor_id(2, "$open")
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        job_dir = Path(jobs_root) / "job_42"
        job_dir.mkdir(parents=True)
        return job_dir

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir))

    response = factor_backtest_service.create_factor_backtest(
        FactorBacktestRequest(
            factor_run_id="run_a",
            factor_ids=[selected],
            start_date="2022-01-01",
            end_date="2025-12-31",
            top_k=20,
            initial_cash=50_000_000,
            buy_cost=0.001,
            sell_cost=0.002,
            slippage=0.0003,
            min_cost=2.0,
            max_weight_per_stock=0.05,
        )
    )

    payload = captured["payload"]
    assert captured["operation"] == "backtest_factors"
    assert captured["spawned"].name == "job_42"
    assert payload["factor_run_dir"].endswith("run_a")
    assert payload["expected_pool_id"] == "pool_a"
    assert payload["factor_ids"] == [selected]
    assert "backtest_id" not in payload  # 由 platform_jobs 用 job_id 注入
    assert payload["backtest_config"] == {
        "start_date": "2022-01-01",
        "end_date": "2025-12-31",
        "top_k": 20,
        "initial_cash": 50_000_000.0,
        "buy_cost": 0.001,
        "sell_cost": 0.002,
        "rebalance_freq": "1D",
        "commission": 0.0003,
        "transfer_fee": 0.00001,
        "stamp_duty": 0.0005,
        "slippage": 0.0003,
        "min_cost": 2.0,
        "max_weight_per_stock": 0.05,
    }
    assert response["job_id"] == "job_42"
    assert response["backtest_id"] == "job_42"
    assert response["status"] == "queued"
    assert response["operation"] == "backtest_factors"
    assert response["accepted_total"] == 2
    assert response["selected_total"] == 1
    assert response["warnings"] == []
    assert response["request_summary"]["factor_ids"] == [selected]
    assert response["request_summary"]["top_k"] == 20


def test_create_factor_backtest_defaults_to_all_accepted(master, tmp_path, monkeypatch):
    _, _, _ = _factor_case(master, tmp_path, monkeypatch, expressions=("$close", "$open"))
    captured = {}
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = factor_backtest_service.create_factor_backtest(
        FactorBacktestRequest(factor_run_id="run_a", start_date="2021-06-18", end_date="2021-06-18")
    )

    assert "factor_ids" not in captured["payload"]
    assert response["selected_total"] == 2
    assert response["request_summary"]["factor_ids"] is None


def test_create_factor_backtest_rejects_invalid_parameters(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch, expressions=("$close", "$open"))

    def expect(message, **kwargs):
        with pytest.raises(DomainError) as excinfo:
            factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a", **kwargs))
        assert excinfo.value.status_code == 422
        assert message in excinfo.value.detail

    expect("top_k", top_k=0)
    expect("initial_cash", initial_cash=0)
    expect("buy_cost", buy_cost=0.5)
    expect("min_cost", min_cost=-1)
    expect("max_weight_per_stock", max_weight_per_stock=0)
    expect("YYYY-MM-DD", start_date="2024/01/01")
    expect("start_date 不能晚于 end_date", start_date="2025-01-01", end_date="2024-01-01")
    expect("没有交集", start_date="2030-01-01", end_date="2030-12-31")
    expect("请至少选择一个因子", factor_ids=[])
    expect("不在该运行中", factor_ids=["factor_9999_missing"])


def test_create_factor_backtest_rejects_data_or_signature_mismatch(master, tmp_path, monkeypatch):
    pool_id, run_dir, _ = _factor_case(master, tmp_path, monkeypatch)
    pool_manifest = tmp_path / "pools" / pool_id / "manifest.json"

    _write_json(pool_manifest, {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": "old"})
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "股票池" in excinfo.value.detail

    _write_json(pool_manifest, {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": "sig"})
    _write_json(
        run_dir / "factor_run.json",
        {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": "old"},
    )
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "因子运行" in excinfo.value.detail

    _write_json(run_dir / "confirmation_manifest.json", {"status": "finished"})
    (run_dir / "confirmed_factors.jsonl").write_text("", encoding="utf-8")
    _seal_confirmed(run_dir)
    _write_json(run_dir / "factor_run.json", {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": "sig"})
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "没有合格因子" in excinfo.value.detail


def test_create_factor_backtest_uses_company_source(master, tmp_path, monkeypatch):
    """公司库因子运行：不读本地主缓存，默认区间用运行面板的实际起止日期。"""
    pool_id, run_dir, _ = _factor_case(master, tmp_path, monkeypatch, expressions=("$close",))
    signature = company_source.source_signature()
    _write_json(
        tmp_path / "pools" / pool_id / "manifest.json",
        {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": signature},
    )
    runtime_manifest = run_dir / "runtime_manifest.json"
    _write_json(
        runtime_manifest,
        {"data_source": "clickhouse", "panel": {"date_min": "2024-02-01", "date_max": "2024-11-29"}},
    )
    run_manifest = json.loads((run_dir / "factor_run.json").read_text(encoding="utf-8"))
    run_manifest.update(
        {
            "data_source": "clickhouse",
            "source_signature": signature,
            "runtime_manifest": str(runtime_manifest),
        }
    )
    _write_json(run_dir / "factor_run.json", run_manifest)
    monkeypatch.setattr(
        company_source,
        "meta",
        lambda *args, **kwargs: {
            "date_min": "2024-01-01",
            "date_max": "2024-12-31",
            "source_signature": signature,
        },
    )
    # 即使本地主缓存缺失，公司库回测也必须能提交
    monkeypatch.setattr(common, "SNAPSHOT_ROOT", tmp_path / "no-master")
    captured = {}
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = factor_backtest_service.create_factor_backtest(
        FactorBacktestRequest(factor_run_id="run_a")
    )

    payload = captured["payload"]
    assert payload["data_source"] == "clickhouse"
    assert payload["backtest_config"]["start_date"] == "2024-02-01"
    assert payload["backtest_config"]["end_date"] == "2024-11-29"
    assert response["data_source"] == "clickhouse"
    assert response["warnings"] == []


def test_create_factor_backtest_rejects_company_signature_mismatch(master, tmp_path, monkeypatch):
    pool_id, _, _ = _factor_case(master, tmp_path, monkeypatch)
    _write_json(
        tmp_path / "pools" / pool_id / "manifest.json",
        {"pool_id": pool_id, "data_source": "clickhouse", "source_signature": "old"},
    )
    monkeypatch.setattr(
        company_source,
        "meta",
        lambda *args, **kwargs: {
            "date_min": "2024-01-01",
            "date_max": "2024-12-31",
            "source_signature": company_source.source_signature(),
        },
    )

    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "数据源签名" in excinfo.value.detail


def test_create_factor_backtest_rejects_local_pool(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    _write_json(common.POOLS_ROOT / "pool_a" / "manifest.json", {"pool_id": "pool_a", "data_source": "local"})

    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "ClickHouse" in excinfo.value.detail


def test_create_factor_backtest_marks_job_failed_when_spawn_fails(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: _make_job_dir(jobs_root),
    )

    def boom(job_dir):
        raise OSError("no subprocess")

    _patch_job_deps(monkeypatch, "spawn_platform_job", boom)

    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 500
    assert "启动失败" in excinfo.value.detail
    status = json.loads((common.JOBS_ROOT / "job_123" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert "no subprocess" in status["message"]


def _write_batch_result(results_root: Path, pool_id="pool_a", run_id="run_a", batch_id="batch_001"):
    batch_dir = results_root / "factor" / pool_id / run_id / batch_id
    prefix = f"factor/{pool_id}/{run_id}/{batch_id}"
    _write_json(
        batch_dir / "factor_backtest_manifest.json",
        {
            "backtest_id": batch_id,
            "job_id": batch_id,
            "pool_id": pool_id,
            "factor_run_id": run_id,
            "run_key_prefix": prefix,
            "accepted_count": 2,
            "selected_count": 2,
            "completed": 1,
            "failed": 1,
            "start_date": "2024-01-01",
            "end_date": "2024-01-05",
            "top_k": 10,
            "initial_cash": 1000000.0,
            "created_at": "2026-10-25T10:00:00",
            "summary_file": "factor_backtest_summary.csv",
            "failures_file": "factor_backtest_failures.csv",
        },
    )
    fid = factor_id(1, "$close")
    (batch_dir / "factor_backtest_summary.csv").write_text(
        "factor_id,expression,run_key,backtest_annual_return,backtest_sharpe\n"
        f"{fid},$close,{prefix}/{fid},0.12,1.5\n",
        encoding="utf-8",
    )
    (batch_dir / "factor_backtest_failures.csv").write_text(
        "factor_id,expression,error\n"
        f"{factor_id(2, '$missing')},$missing,NameError: missing\n",
        encoding="utf-8",
    )
    _write_json(
        batch_dir / fid / "manifest.json",
        {
            "run_name": fid,
            "run_key": f"{prefix}/{fid}",
            "result_type": "factor",
            "pool_id": pool_id,
            "factor_run_id": run_id,
            "backtest_id": batch_id,
            "files": ["daily_report.csv"],
        },
    )
    (batch_dir / fid / "summary.json").write_text("{}", encoding="utf-8")
    (batch_dir / fid / "daily_report.csv").write_text("date,account\n", encoding="utf-8")
    return batch_dir, prefix, fid


def test_factor_backtests_list_detail_and_download(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    batch_dir, prefix, fid = _write_batch_result(common.RESULTS_ROOT)

    listing = factor_backtest_service.get_factor_backtests("run_a", pool_id=None)
    assert listing["total"] == 1
    assert listing["batches"][0]["backtest_id"] == "batch_001"
    assert listing["batches"][0]["completed"] == 1
    assert listing["batches"][0]["run_key_prefix"] == prefix

    detail = factor_backtest_service.get_factor_backtest("batch_001", factor_run_id="run_a", pool_id=None)
    assert detail["batch"]["backtest_id"] == "batch_001"
    assert detail["rows"][0]["factor_id"] == fid
    assert detail["rows"][0]["run_key"] == f"{prefix}/{fid}"
    assert detail["failures"][0]["error"].startswith("NameError")

    response = factor_backtest_service.download_factor_backtest_file(
        "batch_001", "factor_backtest_summary.csv", factor_run_id="run_a", pool_id=None
    )
    assert Path(response) == batch_dir / "factor_backtest_summary.csv"

    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.download_factor_backtest_file(
            "batch_001", "other.csv", factor_run_id="run_a", pool_id=None
        )
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.get_factor_backtest("missing", factor_run_id="run_a", pool_id=None)
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        factor_backtest_service.get_factor_backtests("run_a", pool_id="other")
    assert excinfo.value.status_code == 422


def test_csv_records_handles_empty_failure_file(tmp_path):
    empty = tmp_path / "factor_backtest_failures.csv"
    empty.write_text("\n", encoding="utf-8")
    assert factor_backtest_service._csv_records(empty) == []

    missing = tmp_path / "missing.csv"
    assert factor_backtest_service._csv_records(missing) == []


def test_nested_result_detail_and_download_by_run_key(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    _, prefix, fid = _write_batch_result(common.RESULTS_ROOT)
    run_key = f"{prefix}/{fid}"

    detail = result_service.get_result_by_key(run_key)
    assert detail["run_key"] == run_key
    assert detail["backtest_id"] == "batch_001"
    assert detail["factor_run_id"] == "run_a"
    assert detail["pool_id"] == "pool_a"

    response = result_service.download_result_file_by_key(run_key, "daily_report.csv")
    assert Path(response).name == "daily_report.csv"

    with pytest.raises(DomainError) as excinfo:
        result_service.get_result_by_key("factor/../../secret")
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        result_service.download_result_file_by_key(run_key, "summary.json")
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        common._safe_relative(common.RESULTS_ROOT, "/etc/passwd")
    assert excinfo.value.status_code == 404
    with pytest.raises(DomainError) as excinfo:
        common._safe_relative(common.RESULTS_ROOT, "factor//pool")
    assert excinfo.value.status_code == 404


def _write_result_with_daily(root: Path, run_key: str, config, daily: str) -> Path:
    run_dir = root / run_key
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "manifest.json",
        {
            "run_name": run_dir.name,
            "run_key": run_key,
            "result_type": "factor",
            "config": config,
            "files": ["daily_report.csv"],
        },
    )
    (run_dir / "daily_report.csv").write_text(daily, encoding="utf-8")
    return run_dir


def test_result_detail_uses_flat_config_initial_cash(tmp_path, monkeypatch):
    """因子结果 config 是扁平的：净值必须按 config 里的 initial_cash 归一化。"""
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    run_key = "factor/pool_a/run_a/batch_001/factor_1"
    config = {"initial_cash": 1000000.0, "start_date": "2024-01-01", "top_k": 10}
    _write_result_with_daily(
        common.RESULTS_ROOT,
        run_key,
        config,
        "date,account,drawdown\n2024-01-02,1100000.0,0.0\n2024-01-03,900000.0,-0.18\n",
    )

    detail = result_service.get_result_by_key(run_key)
    summary = result_service._result_summary(
        {"run_name": "factor_1", "run_key": run_key, "result_type": "factor", "config": config}
    )

    assert [row["equity"] for row in detail["equity"]] == [1.1, 0.9]
    assert detail["equity"][1]["drawdown"] == -18.0
    assert (summary["start_date"], summary["top_k"], summary["initial_cash"]) == (
        "2024-01-01",
        10,
        1000000.0,
    )


def test_result_detail_uses_nested_manual_config_initial_cash(tmp_path, monkeypatch):
    """手动回测 config 是嵌套的：仍须读 config.backtest.initial_cash。"""
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    run_key = "manual/job_001/manual_run"
    _write_result_with_daily(
        common.RESULTS_ROOT,
        run_key,
        {"backtest": {"initial_cash": 500000.0}, "expression": "close / delay(close, 20) - 1"},
        "date,account,drawdown\n2024-01-02,550000.0,0.0\n",
    )

    detail = result_service.get_result_by_key(run_key)

    assert detail["equity"][0]["equity"] == 1.1


def _write_pool(root: Path, pool_id: str, name: str, codes=("000001",)) -> Path:
    pool_dir = root / pool_id
    pool_dir.mkdir(parents=True)
    manifest = {
        "pool_id": pool_id,
        "name": name,
        "n_stocks": len(codes),
        "selection_start": "2025-01-01",
        "selection_end": "2025-06-30",
        "selected_stats": [
            {"code": code, "average_amount": 1e8, "coverage": 1.0} for code in codes
        ],
    }
    (pool_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pool_dir / "codes.txt").write_text("\n".join(codes) + "\n", encoding="utf-8")
    return pool_dir


def test_get_pools_merges_mysql_and_local(master, monkeypatch):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")
    monkeypatch.setattr(
        mysql_store,
        "fetch_pools",
        lambda: [
            {
                "pool_id": "mysql_pool",
                "manifest": {
                    "pool_id": "mysql_pool",
                    "name": "MySQL 池",
                    "n_stocks": 2,
                    "selected_stats": [
                        {"code": "000001", "average_amount": 1e8, "coverage": 1.0},
                        {"code": "600000", "average_amount": 2e8, "coverage": 0.5},
                    ],
                },
                "created_at": "2026-10-27 12:00",
            }
        ],
    )

    data = pool_service.get_pools()

    assert data["total"] == 2
    assert data["storage"] == "mysql+local"
    by_id = {item["pool_id"]: item for item in data["pools"]}
    assert by_id["mysql_pool"]["storage"] == "mysql"
    assert by_id["local_pool"]["storage"] == "local"
    assert by_id["mysql_pool"]["coverage"] == 0.75


def test_get_pools_falls_back_to_local_when_mysql_unavailable(master, monkeypatch):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")

    def boom():
        raise RuntimeError("mysql down")

    monkeypatch.setattr(mysql_store, "fetch_pools", boom)

    data = pool_service.get_pools()

    assert data["storage"] == "local"
    assert data["total"] == 1
    assert data["pools"][0]["pool_id"] == "local_pool"


def test_get_pool_reads_from_mysql(master, monkeypatch):
    monkeypatch.setattr(
        mysql_store,
        "fetch_pool",
        lambda pool_id: {
            "pool_id": pool_id,
            "manifest": {
                "pool_id": pool_id,
                "name": "MySQL 池",
                "requested_codes": ["000001"],
                "minimum_valid_rows": 100,
            },
            "codes": ["000001", "600000"],
            "created_at": "2026-10-27 12:00",
        },
    )

    data = pool_service.get_pool("mysql_pool")

    assert data["storage"] == "mysql"
    assert data["codes"] == ["000001", "600000"]
    assert data["requested_codes"] == ["000001"]
    assert data["minimum_valid_rows"] == 100


def test_get_pool_falls_back_to_local_file(master, monkeypatch):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池", codes=("000001", "600000"))
    monkeypatch.setattr(mysql_store, "fetch_pool", lambda pool_id: None)

    data = pool_service.get_pool("local_pool")

    assert data["storage"] == "local"
    assert data["codes"] == ["000001", "600000"]


def test_delete_pool_requires_confirmation(master):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")

    with pytest.raises(DomainError) as excinfo:
        pool_service.delete_pool("local_pool", confirm=False)

    assert excinfo.value.status_code == 400
    assert (common.POOLS_ROOT / "local_pool").is_dir()


def test_delete_pool_removes_local_and_mysql(master, monkeypatch, tmp_path):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")
    monkeypatch.setattr(mysql_store, "delete_pool", lambda pool_id: True)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", tmp_path / "factor_runs")
    run_dir = tmp_path / "factor_runs" / "run_001"
    run_dir.mkdir(parents=True)
    (run_dir / "factor_run.json").write_text(
        json.dumps({"pool_id": "local_pool"}), encoding="utf-8"
    )
    (tmp_path / "results" / "factor" / "local_pool").mkdir(parents=True)

    data = pool_service.delete_pool("local_pool", confirm=True)

    assert data["deleted_local"] is True
    assert data["deleted_mysql"] is True
    assert data["mysql_configured"] is True
    assert not (common.POOLS_ROOT / "local_pool").exists()
    assert any("1 个因子运行" in item for item in data["warnings"])
    assert any("历史因子回测结果" in item for item in data["warnings"])


def test_delete_pool_local_only_without_mysql(master, monkeypatch, tmp_path):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")
    monkeypatch.setattr(mysql_store, "delete_pool", lambda pool_id: None)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", tmp_path / "factor_runs")

    data = pool_service.delete_pool("local_pool", confirm=True)

    assert data["deleted_local"] is True
    assert data["deleted_mysql"] is False
    assert data["mysql_configured"] is False
    assert data["warnings"][0].startswith("MySQL 未配置")


def test_delete_pool_mysql_only(master, monkeypatch, tmp_path):
    monkeypatch.setattr(mysql_store, "delete_pool", lambda pool_id: True)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", tmp_path / "factor_runs")

    data = pool_service.delete_pool("mysql_pool", confirm=True)

    assert data["deleted_local"] is False
    assert data["deleted_mysql"] is True


def test_delete_pool_returns_404_when_missing(master, monkeypatch, tmp_path):
    monkeypatch.setattr(mysql_store, "delete_pool", lambda pool_id: False)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", tmp_path / "factor_runs")

    with pytest.raises(DomainError) as excinfo:
        pool_service.delete_pool("nope", confirm=True)

    assert excinfo.value.status_code == 404


def test_delete_pool_keeps_local_when_mysql_fails(master, monkeypatch):
    _write_pool(common.POOLS_ROOT, "local_pool", "本地池")

    def boom(pool_id):
        raise RuntimeError("mysql down")

    monkeypatch.setattr(mysql_store, "delete_pool", boom)

    with pytest.raises(DomainError) as excinfo:
        pool_service.delete_pool("local_pool", confirm=True)

    assert excinfo.value.status_code == 502
    assert (common.POOLS_ROOT / "local_pool" / "manifest.json").is_file()


# ---------- 手动回测 ----------


def _write_manual_pool(
    root: Path,
    *,
    pool_id: str = "pool_company",
    signature: str = company_source.SOURCE_SIGNATURE,
    data_source: str = "clickhouse",
    selection_start: str = "2024-01-01",
    selection_end: str = "2024-01-25",
) -> Path:
    pool_dir = root / pool_id
    pool_dir.mkdir(parents=True)
    manifest = {
        "pool_id": pool_id,
        "name": pool_id,
        "data_source": data_source,
        "source_signature": signature,
        "selection_start": selection_start,
        "selection_end": selection_end,
        "n_stocks": 2,
    }
    (pool_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pool_dir / "codes.txt").write_text("000001\n600000\n", encoding="utf-8")
    return pool_dir


def _stub_company_meta(monkeypatch, signature=company_source.SOURCE_SIGNATURE):
    monkeypatch.setattr(
        company_source,
        "meta",
        lambda *args, **kwargs: {
            "data_source": "clickhouse",
            "source_signature": signature,
            "date_min": "2024-01-01",
            "date_max": "2024-12-31",
        },
    )


def test_create_manual_backtest_builds_company_payload(master, tmp_path, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    monkeypatch.setattr(common, "RESULTS_ROOT", tmp_path / "results")
    _stub_company_meta(monkeypatch)
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return _make_job_dir(jobs_root)

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir))

    response = manual_backtest_service.create_manual_backtest(
        ManualBacktestRequest(
            expression="close / delay(close, 21) - 1",
            pool_id="pool_company",
            run_name="manual_demo",
            top_k=5,
            initial_cash=50_000_000,
            buy_cost=0.001,
            sell_cost=0.002,
            slippage=0.0003,
            min_cost=2.0,
            max_weight_per_stock=0.05,
        )
    )

    payload = captured["payload"]
    assert captured["operation"] == "manual_backtest"
    assert captured["spawned"].name == "job_123"
    assert payload["pools_root"] == str(common.POOLS_ROOT)
    assert payload["output_root"] == str(tmp_path / "results")
    assert payload["pool_id"] == "pool_company"
    assert payload["data_source"] == "clickhouse"
    assert payload["run_name"] == "manual_demo"
    assert payload["expression"] == "close / delay(close, 21) - 1"
    assert "backtest_id" not in payload  # 由 platform_jobs 用 job_id 注入
    assert payload["backtest_config"] == {
        "start_date": "2024-01-01",
        "end_date": "2024-01-25",
        "top_k": 5,
        "initial_cash": 50_000_000.0,
        "buy_cost": 0.001,
        "sell_cost": 0.002,
        "rebalance_freq": "1D",
        "commission": 0.0003,
        "transfer_fee": 0.00001,
        "stamp_duty": 0.0005,
        "slippage": 0.0003,
        "min_cost": 2.0,
        "max_weight_per_stock": 0.05,
    }
    assert response["job_id"] == "job_123"
    assert response["status"] == "queued"
    assert response["operation"] == "manual_backtest"
    assert response["data_source"] == "clickhouse"
    assert response["run_name"] == "manual_demo"
    assert response["warnings"] == []
    assert response["request_summary"]["top_k"] == 5


def test_create_manual_backtest_uses_mysql_pool_when_local_files_are_missing(master, monkeypatch):
    _stub_company_meta(monkeypatch)
    monkeypatch.setattr(
        mysql_store,
        "fetch_pool",
        lambda pool_id: {
            "manifest": {
                "pool_id": pool_id,
                "name": "mysql_only",
                "data_source": "clickhouse",
                "source_signature": company_source.SOURCE_SIGNATURE,
                "selection_start": "2024-01-01",
                "selection_end": "2024-01-25",
            },
            "codes": ["000001", "600000"],
        },
    )
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["payload"] = payload
        return _make_job_dir(jobs_root)

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = manual_backtest_service.create_manual_backtest(
        ManualBacktestRequest(
            expression="close",
            pool_id="pool_mysql",
            run_name="mysql_pool_run",
            start_date="2024-01-01",
            end_date="2024-01-25",
        )
    )

    assert response["job_id"] == "job_123"
    assert captured["payload"]["pool_codes"] == ["000001", "600000"]
    assert captured["payload"]["pool_manifest"]["source_signature"] == company_source.SOURCE_SIGNATURE


def test_create_manual_backtest_warns_when_range_exceeds_company_source(master, tmp_path, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    _stub_company_meta(monkeypatch)
    _patch_job_deps(monkeypatch, "create_platform_job", lambda jobs_root, operation, payload: _make_job_dir(jobs_root)
    )
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = manual_backtest_service.create_manual_backtest(
        ManualBacktestRequest(
            expression="close",
            pool_id="pool_company",
            run_name="wide_range",
            start_date="2023-12-01",
            end_date="2025-01-31",
        )
    )

    assert len(response["warnings"]) == 2
    assert "起点早于数据源" in response["warnings"][0]
    assert "终点晚于数据源" in response["warnings"][1]


def test_create_manual_backtest_rejects_invalid_expression_and_name(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    _stub_company_meta(monkeypatch)

    def expect(message, **kwargs):
        with pytest.raises(DomainError) as excinfo:
            manual_backtest_service.create_manual_backtest(
                ManualBacktestRequest(
                    expression=kwargs.pop("expression", "close"),
                    pool_id="pool_company",
                    run_name=kwargs.pop("run_name", "demo"),
                    **kwargs,
                )
            )
        assert excinfo.value.status_code == 422
        assert message in excinfo.value.detail

    expect("表达式无效", expression="not_a_field + 1")
    expect("表达式无效", expression="close +")
    expect("run_name", run_name="../escape")
    expect("top_k", top_k=0)
    expect("initial_cash", initial_cash=0)
    expect("buy_cost", buy_cost=0.5)
    expect("min_cost", min_cost=-1)
    expect("max_weight_per_stock", max_weight_per_stock=0)
    expect("YYYY-MM-DD", start_date="2024/01/01")
    expect("start_date 不能晚于 end_date", start_date="2024-06-01", end_date="2024-01-01")
    expect("没有交集", start_date="2030-01-01", end_date="2030-12-31")


def test_create_manual_backtest_rejects_signature_mismatch_and_missing_pool(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT, signature="other")
    _stub_company_meta(monkeypatch)

    with pytest.raises(DomainError) as excinfo:
        manual_backtest_service.create_manual_backtest(
            ManualBacktestRequest(expression="close", pool_id="pool_company", run_name="demo")
        )
    assert excinfo.value.status_code == 422
    assert "签名" in excinfo.value.detail

    with pytest.raises(DomainError) as excinfo:
        manual_backtest_service.create_manual_backtest(
            ManualBacktestRequest(expression="close", pool_id="missing", run_name="demo")
        )
    assert excinfo.value.status_code == 404


def test_create_manual_backtest_rejects_local_pool(master, tmp_path, monkeypatch):
    _write_manual_pool(
        common.POOLS_ROOT,
        data_source="local",
        signature="local_sig",
    )
    monkeypatch.setattr(common, "SNAPSHOT_ROOT", tmp_path / "missing-master")

    with pytest.raises(DomainError) as excinfo:
        manual_backtest_service.create_manual_backtest(
            ManualBacktestRequest(expression="close", pool_id="pool_company", run_name="demo")
        )
    assert excinfo.value.status_code == 422
    assert "ClickHouse" in excinfo.value.detail


def test_create_manual_backtest_marks_job_failed_when_spawn_fails(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    _stub_company_meta(monkeypatch)
    marked = {}
    _patch_job_deps(monkeypatch, "create_platform_job", lambda jobs_root, operation, payload: _make_job_dir(jobs_root)
    )

    def boom(job_dir):
        raise OSError("spawn failed")

    _patch_job_deps(monkeypatch, "spawn_platform_job", boom)
    _patch_job_deps(monkeypatch, "update_job_status", lambda job_dir, status, message, extra=None: marked.update(
            {"job_dir": job_dir, "status": status, "message": message}
        )
    )

    with pytest.raises(DomainError) as excinfo:
        manual_backtest_service.create_manual_backtest(
            ManualBacktestRequest(expression="close", pool_id="pool_company", run_name="demo")
        )
    assert excinfo.value.status_code == 500
    assert marked["status"] == "failed"


# ---------- 因子生成（PPO） ----------


def _generation_splits(start="2024-01-01", end="2024-12-31"):
    span = (pd.Timestamp(end) - pd.Timestamp(start)).days
    dates = [(0, int(span*.35)), (int(span*.55), int(span*.68)), (int(span*.88), span)]
    return {name: FactorGenerationSplit(cache_start=str((pd.Timestamp(start)+pd.Timedelta(days=a)).date()),
                                         cache_end=str((pd.Timestamp(start)+pd.Timedelta(days=b)).date()))
            for name, (a,b) in zip(("train", "valid", "test"), dates)}


def _generation_request(**overrides):
    base = {
        "pool_id": "pool_company",
        "fields": ["close", "open"],
        "operators": ["add"],
        "splits": _generation_splits(),
        "target_factor_count": 1,
        "max_attempts": 2,
        "rollout_timesteps": 64,
    }
    base.update(overrides)
    return FactorGenerationRequest(**base)


def test_create_factor_generation_builds_payload_and_returns_run_id(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT, selection_end="2024-12-31")
    _stub_company_meta(monkeypatch)
    real_create = create_platform_job
    captured = {}

    def wrapped_create(jobs_root, operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return real_create(jobs_root, operation, payload)

    _patch_job_deps(monkeypatch, "create_platform_job", wrapped_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir)
    )

    response = generation_service.create_factor_generation(
        FactorGenerationRequest(
            pool_id="pool_company",
            run_name="ppo_demo",
            fields=["close", "open", "fund_OperatingReenue"],
            operators=["add", "divide", "Add"],
            splits=_generation_splits(),
            target_factor_count=3,
            max_attempts=12,
            rollout_timesteps=64,
            seed=7,
            device="cpu",
            quality={"min_coverage": 0.9},
        )
    )

    payload = captured["payload"]
    assert captured["operation"] == "generate_factors"
    assert captured["spawned"].is_dir()
    assert payload["pool_id"] == "pool_company"
    assert payload["fields"] == ["close", "open", "fund_OperatingReenue"]
    assert payload["operators"] == ["add", "div"]
    assert payload["splits"] == {name: value.model_dump() for name, value in _generation_splits().items()}
    assert payload["max_backtrack_days"] == 100
    assert payload["target_horizon"] == 20
    assert payload["max_future_days"] == 20
    assert payload["data_source"] == "clickhouse"
    config = payload["generation_config"]
    assert config["run_name"] == "ppo_demo"
    assert config["target_factor_count"] == 3
    assert config["max_attempts"] == 12
    assert config["rollout_timesteps"] == 64
    assert config["seed"] == 7
    assert config["device"] == "cpu"
    assert config["quality"]["min_coverage"] == 0.9
    assert config["quality"]["min_train_ic"] == 0.05

    created = json.loads(
        (captured["spawned"] / "platform_job.json").read_text(encoding="utf-8")
    )
    run_id = created["payload"]["generation_config"]["run_id"]
    assert run_id.startswith("ppo_demo_")
    assert response["job_id"] == captured["spawned"].name
    assert response["status"] == "queued"
    assert response["operation"] == "generate_factors"
    assert response["run_id"] == run_id
    assert response["run_name"] == "ppo_demo"
    assert len(response["warnings"]) == 2
    assert any("valid" in warning for warning in response["warnings"])
    assert any("test" in warning for warning in response["warnings"])
    summary = response["request_summary"]
    assert summary["pool_id"] == "pool_company"
    assert summary["n_stocks"] == 2
    assert summary["field_count"] == 3
    assert summary["operators"] == ["add", "div"]
    assert summary["operator_mode"] == "selected"


def test_factor_generation_defaults_follow_pool_time_span(master):
    _write_manual_pool(
        common.POOLS_ROOT,
        selection_start="2024-01-01",
        selection_end="2024-12-31",
    )

    defaults = generation_service.get_factor_generation_defaults(pool_id="pool_company")

    assert defaults["split_source"] == "pool"
    assert defaults["pool_window"] == {"start": "2024-01-01", "end": "2024-12-31"}
    splits = defaults["splits"]
    assert splits["train"]["cache_start"] == "2024-01-01"
    assert splits["train"]["cache_end"] < splits["valid"]["cache_start"]
    assert splits["valid"]["cache_end"] < splits["test"]["cache_start"]
    assert splits["test"]["cache_end"] == "2024-12-31"
    assert defaults["warnings"] == []


def test_factor_generation_defaults_without_pool_use_config(master):
    defaults = generation_service.get_factor_generation_defaults()

    assert defaults["split_source"] == "config"
    assert defaults["pool_window"] is None
    assert defaults["splits"]["train"]["cache_start"] == "2024-01-01"


def test_factor_generation_defaults_read_mysql_only_pool(master, monkeypatch):
    monkeypatch.setattr(
        mysql_store,
        "fetch_pool",
        lambda pool_id: {
            "pool_id": pool_id,
            "manifest": {
                "pool_id": pool_id,
                "name": "MySQL 池",
                "data_source": "clickhouse",
                "source_signature": company_source.SOURCE_SIGNATURE,
                "selection_start": "2024-01-01",
                "selection_end": "2024-12-31",
            },
            "codes": ["000001", "600000"],
            "created_at": "2026-10-29 14:18",
        },
    )

    defaults = generation_service.get_factor_generation_defaults(pool_id="mysql_pool")

    assert defaults["split_source"] == "pool"
    assert defaults["pool_window"] == {"start": "2024-01-01", "end": "2024-12-31"}
    assert defaults["splits"]["train"]["cache_start"] == "2024-01-01"
    assert defaults["splits"]["train"]["cache_end"] < defaults["splits"]["valid"]["cache_start"]
    assert defaults["warnings"] == []


def test_create_factor_generation_supports_mysql_only_pool(master, monkeypatch):
    _stub_company_meta(monkeypatch)
    monkeypatch.setattr(
        mysql_store,
        "fetch_pool",
        lambda pool_id: {
            "pool_id": pool_id,
            "manifest": {
                "pool_id": pool_id,
                "name": "MySQL 池",
                "data_source": "clickhouse",
                "source_signature": company_source.SOURCE_SIGNATURE,
                "selection_start": "2024-01-01",
                "selection_end": "2024-12-31",
                "n_stocks": 2,
            },
            "codes": ["000001", "600000"],
            "created_at": "2026-10-29 14:18",
        },
    )
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["operation"] = operation
        captured["payload"] = payload
        return _make_job_dir(jobs_root)

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir)
    )

    response = generation_service.create_factor_generation(
        _generation_request(pool_id="mysql_pool", splits=None)
    )

    payload = captured["payload"]
    assert captured["operation"] == "generate_factors"
    assert payload["pool_id"] == "mysql_pool"
    assert payload["pool_codes"] == ["000001", "600000"]
    assert payload["pool_manifest"]["name"] == "MySQL 池"
    assert payload["pool_manifest"]["selection_start"] == "2024-01-01"
    assert payload["splits"]["train"]["cache_start"] == "2024-01-01"
    assert response["pool_storage"] == "mysql"
    assert response["request_summary"]["pool_storage"] == "mysql"
    assert response["request_summary"]["n_stocks"] == 2


def test_create_factor_generation_local_pool_does_not_send_pool_payload(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT, selection_end="2024-12-31")
    _stub_company_meta(monkeypatch)
    monkeypatch.setattr(mysql_store, "fetch_pool", lambda pool_id: None)
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["payload"] = payload
        return _make_job_dir(jobs_root)

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = generation_service.create_factor_generation(_generation_request(splits=None))

    assert "pool_manifest" not in captured["payload"]
    assert "pool_codes" not in captured["payload"]
    assert response["pool_storage"] == "local"


def test_create_factor_generation_defaults_splits_to_pool_window(master, monkeypatch):
    _write_manual_pool(
        common.POOLS_ROOT,
        selection_start="2024-01-01",
        selection_end="2024-12-31",
    )
    _stub_company_meta(monkeypatch)
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["payload"] = payload
        return _make_job_dir(jobs_root)

    _patch_job_deps(monkeypatch, "create_platform_job", fake_create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    response = generation_service.create_factor_generation(
        _generation_request(
            splits=None,
            max_backtrack_days=1,
            target_horizon=1,
            max_future_days=1,
            target_factor_count=1,
            max_attempts=1,
        )
    )

    splits = captured["payload"]["splits"]
    assert splits["train"]["cache_end"] < splits["valid"]["cache_start"]
    assert splits["valid"]["cache_end"] < splits["test"]["cache_start"]
    assert response["request_summary"]["split_source"] == "pool"
    assert response["request_summary"]["pool_window"] == {
        "start": "2024-01-01",
        "end": "2024-12-31",
    }


def test_create_factor_generation_rejects_splits_outside_pool_window(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    _stub_company_meta(monkeypatch)

    with pytest.raises(DomainError) as excinfo:
        generation_service.create_factor_generation(_generation_request())

    assert excinfo.value.status_code == 422
    assert "股票池真实时间跨度" in excinfo.value.detail


def test_create_factor_generation_validates_fields_operators_and_bounds(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT)
    _stub_company_meta(monkeypatch)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda job_dir: None)

    def expect(status, message, **overrides):
        with pytest.raises(DomainError) as excinfo:
            generation_service.create_factor_generation(_generation_request(**overrides))
        assert excinfo.value.status_code == status
        assert message in excinfo.value.detail

    expect(422, "不能用于因子生成", fields=["not_a_real_field"])
    expect(
        422,
        "财务流量字段口径冲突",
        fields=["fund_OperatingReenue", "fund_OperatingReenue_q"],
    )
    expect(422, "未知算子", operators=["not_an_operator"])
    expect(422, "max_attempts", target_factor_count=5, max_attempts=1)
    expect(422, "max_future_days", target_horizon=50, max_future_days=20)
    expect(422, "rollout_timesteps", rollout_timesteps=1)
    expect(422, "run_name", run_name="bad/name")
    expect(
        422,
        "不能晚于",
        splits={**_generation_splits(), "train": FactorGenerationSplit(cache_start="2024-06-01",cache_end="2024-01-01")},
    )
    expect(
        422,
        "没有交集",
        splits=_generation_splits("2030-01-01", "2030-12-31"),
    )
    expect(422, "train、valid、test", splits={})

    with pytest.raises(DomainError) as excinfo:
        generation_service.create_factor_generation(_generation_request(pool_id="missing"))
    assert excinfo.value.status_code == 404

    with pytest.raises(DomainError) as excinfo:
        generation_service.create_factor_generation(_generation_request(pool_id=""))
    assert excinfo.value.status_code == 422
    assert "请选择股票池" in excinfo.value.detail


def test_create_factor_generation_rejects_signature_mismatch(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT, signature="other")
    _stub_company_meta(monkeypatch)

    with pytest.raises(DomainError) as excinfo:
        generation_service.create_factor_generation(_generation_request())
    assert excinfo.value.status_code == 422
    assert "签名" in excinfo.value.detail


def test_create_factor_generation_marks_job_failed_when_spawn_fails(master, monkeypatch):
    _write_manual_pool(common.POOLS_ROOT, selection_end="2024-12-31")
    _stub_company_meta(monkeypatch)
    marked = {}
    _patch_job_deps(monkeypatch, "create_platform_job",
        lambda jobs_root, operation, payload: _make_job_dir(jobs_root),
    )

    def boom(job_dir):
        raise OSError("spawn failed")

    _patch_job_deps(monkeypatch, "spawn_platform_job", boom)
    _patch_job_deps(monkeypatch, "update_job_status",
        lambda job_dir, status, message, extra=None: marked.update(
            {"status": status, "message": message}
        ),
    )

    with pytest.raises(DomainError) as excinfo:
        generation_service.create_factor_generation(_generation_request())
    assert excinfo.value.status_code == 500
    assert marked["status"] == "failed"


def test_accepted_factor_rows_exposes_train_valid_test_segments(tmp_path):
    run_dir = tmp_path / "run_segments"
    run_dir.mkdir()
    _write_json(run_dir / "confirmation_manifest.json", {"status": "finished"})
    (run_dir / "confirmed_factors.jsonl").write_text(
        json.dumps(
            {
                "expression": "$close",
                "accepted": True,
                "ic": 0.1,
                "segments": {
                    "train": {
                        "ic": 0.1,
                        "rank_ic": 0.12,
                        "icir": 0.8,
                        "coverage": 0.99,
                        "valid_days": 120,
                    },
                    "valid": {"ic": 0.06, "rank_ic": 0.07, "icir": 0.5,
                              "coverage": 0.97, "valid_days": 60},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    _seal_confirmed(run_dir)
    rows = factor_backtest_service._accepted_factor_rows(run_dir)

    assert rows[0]["segments"]["train"]["ic"] == 0.1
    assert rows[0]["segments"]["valid"]["valid_days"] == 60


@pytest.mark.parametrize("frequency", ["1D", "1W", "2W", "1M"])
def test_factor_backtest_passes_frequency_and_component_fees(master, tmp_path, monkeypatch, frequency):
    _factor_case(master, tmp_path, monkeypatch)
    captured = {}
    def create(jobs_root, operation, payload):
        captured.update(payload)
        return _make_job_dir(jobs_root)
    _patch_job_deps(monkeypatch, "create_platform_job", create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda _: None)
    response = factor_backtest_service.create_factor_backtest(
        FactorBacktestRequest(factor_run_id="run_a", rebalance_freq=frequency))
    config = captured["backtest_config"]
    assert config["rebalance_freq"] == frequency
    assert config["commission"] == 0.0003
    assert config["transfer_fee"] == 0.00001
    assert config["stamp_duty"] == 0.0005
    assert config["slippage"] == 0.001
    assert config["max_weight_per_stock"] == 0.03
    assert "buy_cost" not in config and "sell_cost" not in config
    assert all(response["request_summary"][key] == value for key, value in config.items())


@pytest.mark.parametrize("options", [
    {"commission": -1}, {"transfer_fee": float("nan")}, {"stamp_duty": float("inf")},
    {"rebalance_freq": "5D"}, {"initial_cash": float("nan")}, {"min_cost": float("inf")},
])
def test_backtest_rejects_invalid_new_parameters_before_loading_data(options):
    with pytest.raises(DomainError) as error:
        factor_backtest_service.create_factor_backtest(FactorBacktestRequest(factor_run_id="missing", **options))
    assert error.value.status_code == 422
    with pytest.raises(DomainError) as error:
        manual_backtest_service.create_manual_backtest(
            ManualBacktestRequest(expression="close", pool_id="missing", run_name="x", **options))
    assert error.value.status_code == 422


def test_confirmation_submission_and_spawn_failure_are_persisted(master, tmp_path, monkeypatch):
    _, run_dir, _ = _factor_case(master, tmp_path, monkeypatch)
    assert run_dir.is_relative_to(tmp_path)
    manifest = json.loads((run_dir / "factor_run.json").read_text())
    _write_json(run_dir / "factor_run.json", {**manifest, "generation_status": "finished"})
    (run_dir / "candidate_factors.jsonl").write_text("", encoding="utf-8")
    captured = {}
    def create(root, operation, payload):
        captured.update(operation=operation, payload=payload)
        return _make_job_dir(root)
    _patch_job_deps(monkeypatch, "create_platform_job", create)
    _patch_job_deps(monkeypatch, "spawn_platform_job", lambda directory: None)
    result = factor_backtest_service.create_factor_confirmation("run_a")
    assert result["operation"] == "confirm_factors"
    assert captured["operation"] == "confirm_factors"
    assert captured["payload"]["factor_run_dir"] == str(run_dir)
    def failed(directory):
        raise OSError("spawn failed")
    marked = {}
    _patch_job_deps(monkeypatch, "spawn_platform_job", failed)
    _patch_job_deps(monkeypatch, "update_job_status", lambda directory, status, message: marked.update(status=status))
    with pytest.raises(DomainError):
        factor_backtest_service.create_factor_confirmation("run_a")
    assert marked["status"] == "failed"


def test_pending_confirmation_does_not_expose_partial_confirmed_file(master, tmp_path, monkeypatch):
    _, run_dir, _ = _factor_case(master, tmp_path, monkeypatch)
    _write_json(run_dir / "confirmation_manifest.json", {"status": "running"})
    assert factor_backtest_service._factor_run_summary(run_dir)["confirmed_count"] == 0
    assert factor_backtest_service._accepted_factor_rows(run_dir) == []
