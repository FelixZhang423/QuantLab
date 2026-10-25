"""api/main.py 的股票池候选 / 建池 / 任务状态路由测试（无网络、无 TestClient）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import job_runner, live_db, main
from custom_bt.factor_backtest import factor_id


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
    monkeypatch.setattr(main, "MASTER_DIR", root)
    monkeypatch.setattr(main, "POOLS_ROOT", tmp_path / "pools")
    monkeypatch.setattr(main, "JOBS_ROOT", tmp_path / "jobs")
    return root


def _stub_universe(monkeypatch, items=None):
    monkeypatch.setattr(
        main.live_db, "live_stock_rows", lambda *args, **kwargs: _live(items or _items())
    )


def test_universe_options_reports_facets_and_master_coverage(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = main.get_universe_options()

    assert data["total"] == 5
    assert data["master_total"] == 3
    assert data["creatable_total"] == 3
    assert data["excluded_total"] == 2
    assert data["master_ready"] is True
    assert data["cache_date_min"] == "2021-06-18"
    assert {item["value"] for item in data["industries"]} == {"银行", "电池", "半导体"}
    assert data["missing"]["industry"] == 1


def test_universe_stocks_filters_master_only_and_paginates(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = main.get_universe_stocks(
        industries=["银行"],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        master_only=True,
        limit=1,
        offset=1,
    )

    assert data["matched_total"] == 2
    assert data["total"] == 2
    assert data["n_creatable"] == 2
    assert data["n_excluded"] == 0
    assert data["items"][0]["code"] == "600000"  # 按成交额降序后的第二只
    assert data["items"][0]["creatable"] is True


def test_universe_stocks_reports_excluded_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = main.get_universe_stocks(
        industries=["半导体"],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        master_only=True,
        limit=50,
        offset=0,
    )

    assert data["matched_total"] == 1
    assert data["total"] == 0
    assert data["n_excluded"] == 1
    assert data["excluded_examples"] == [{"code": "688981", "name": "中芯国际"}]


def test_universe_codes_returns_all_creatable_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    data = main.get_universe_codes(
        industries=[],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        master_only=True,
    )

    assert data["codes"] == ["000001", "300750", "600000"]  # 排序后返回
    assert data["total"] == 3
    assert data["matched_total"] == 5
    assert data["n_creatable"] == 3
    assert data["master_ready"] is True

    everything = main.get_universe_codes(
        industries=[],
        exchanges=[],
        boards=[],
        sectors=[],
        listed_states=[],
        q="",
        min_listed_days=0,
        as_of="2026-06-16",
        master_only=False,
    )
    assert everything["codes"] == ["000001", "300750", "600000", "688981", "920879"]
    assert everything["total"] == 5


def test_create_pool_builds_payload_and_spawns_job(master, monkeypatch):
    _stub_universe(monkeypatch)
    captured = {}

    def fake_create(jobs_root, operation, payload):
        captured["root"] = jobs_root
        captured["operation"] = operation
        captured["payload"] = payload
        job_dir = Path(jobs_root) / "job_123"
        job_dir.mkdir(parents=True)
        return job_dir

    monkeypatch.setattr(main, "create_platform_job", fake_create)
    monkeypatch.setattr(
        main, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir)
    )

    response = main.create_pool(
        main.PoolCreateRequest(
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
    assert payload["codes"] == ["000001", "600000"]
    assert payload["strict_top_n"] is False
    assert payload["category"] == "stock"
    assert payload["selection_start"] == "2024-01-01"
    assert payload["provenance"]["matched_total"] == 2
    assert payload["provenance"]["excluded_total"] == 0
    assert payload["provenance"]["selection_mode"] == "all"
    assert payload["provenance"]["selected_total"] == 2
    assert payload["provenance"]["filters"]["industries"] == ["银行"]
    assert response["job_id"] == "job_123"
    assert response["status"] == "queued"
    assert any("少于 TopN" in item for item in response["warnings"])


def test_create_pool_auto_excludes_missing_master_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        main,
        "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    monkeypatch.setattr(main, "spawn_platform_job", lambda job_dir: None)

    response = main.create_pool(
        main.PoolCreateRequest(
            name="all_stocks",
            selection_start="2024-01-01",
            selection_end="2024-06-30",
        )
    )

    assert captured["payload"]["codes"] == ["000001", "300750", "600000"]
    assert captured["payload"]["provenance"]["excluded_total"] == 2
    assert any("2 只匹配股票不在本地主缓存" in item for item in response["warnings"])


def test_create_pool_uses_manual_selected_codes(master, monkeypatch):
    _stub_universe(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        main,
        "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    monkeypatch.setattr(main, "spawn_platform_job", lambda job_dir: None)

    response = main.create_pool(
        main.PoolCreateRequest(
            name="manual_bank",
            selection_start="2024-01-01",
            selection_end="2024-06-30",
            selected_codes=["600000", "688981", "999999"],
        )
    )

    payload = captured["payload"]
    assert payload["codes"] == ["600000"]  # 只建勾选且在本地缓存里的股票
    assert payload["provenance"]["selection_mode"] == "manual"
    assert payload["provenance"]["selected_total"] == 1
    assert response["request_summary"]["selection_mode"] == "manual"
    assert response["request_summary"]["selected_total"] == 1
    assert any("不在当前筛选结果" in item for item in response["warnings"])
    assert any("不在本地主缓存" in item for item in response["warnings"])


def test_create_pool_rejects_empty_or_unknown_manual_selection(master, monkeypatch):
    _stub_universe(monkeypatch)

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="empty_selection",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                selected_codes=[],
            )
        )
    assert excinfo.value.status_code == 422
    assert "至少勾选" in excinfo.value.detail

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="no_cache_selection",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                selected_codes=["688981"],
            )
        )
    assert excinfo.value.status_code == 422
    assert "都不在本地主缓存" in excinfo.value.detail

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
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


def test_create_pool_rejects_uncreatable_or_empty_selection(master, monkeypatch):
    _stub_universe(monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="chips",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
                industries=["半导体"],
            )
        )
    assert excinfo.value.status_code == 422
    assert "都不在本地主缓存" in excinfo.value.detail

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
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
    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="../evil",
                selection_start="2024-01-01",
                selection_end="2024-06-30",
            )
        )
    assert excinfo.value.status_code == 422

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="bad_window",
                selection_start="2024-06-30",
                selection_end="2024-01-01",
            )
        )
    assert excinfo.value.status_code == 422

    with pytest.raises(HTTPException) as excinfo:
        main.create_pool(
            main.PoolCreateRequest(
                name="no_overlap",
                selection_start="2030-01-01",
                selection_end="2030-12-31",
            )
        )
    assert excinfo.value.status_code == 422
    assert "没有交集" in excinfo.value.detail


def test_live_db_unavailable_maps_to_503(master, monkeypatch):
    def boom(*args, **kwargs):
        raise live_db.LiveDBUnavailable("company network required")

    monkeypatch.setattr(main.live_db, "live_stock_rows", boom)
    with pytest.raises(HTTPException) as excinfo:
        main.get_universe_options()
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
    monkeypatch.setattr(main, "JOBS_ROOT", jobs_root)

    status = main.get_job("job_123")
    assert status["status"] == "finished"
    assert status["result"]["pool_id"] == "bank_abc"

    with pytest.raises(HTTPException) as excinfo:
        main.get_job("..")
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
        "custom_bt.cli",
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
        {"pool_id": pool_id, "name": pool_id, "source_signature": signature},
    )
    factor_root = tmp_path / "factor_runs"
    run_dir = factor_root / "run_a"
    _write_json(
        run_dir / "factor_run.json",
        {
            "pool_id": pool_id,
            "source_signature": signature,
            "created_at": "2026-10-25T10:00:00",
            "accepted_count": len(expressions),
            "target_reached": True,
        },
    )
    (run_dir / "accepted_factors.jsonl").write_text(
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
    monkeypatch.setattr(main, "FACTOR_RUNS_ROOT", factor_root)
    monkeypatch.setattr(main, "RESULTS_ROOT", tmp_path / "results")
    return pool_id, run_dir, factor_root


def test_factor_runs_list_and_detail(master, tmp_path, monkeypatch):
    pool_id, run_dir, factor_root = _factor_case(
        master, tmp_path, monkeypatch, expressions=("$close", "$open")
    )
    (factor_root / "ignored").mkdir()  # 没有 factor_run.json 的目录不展示

    data = main.get_factor_runs(pool_id=None)
    assert data["total"] == 1
    assert data["runs"][0]["run_id"] == "run_a"
    assert data["runs"][0]["pool_id"] == pool_id
    assert data["runs"][0]["accepted_count"] == 2
    assert data["runs"][0]["target_reached"] is True
    assert main.get_factor_runs(pool_id="other")["total"] == 0

    detail = main.get_factor_run("run_a")
    assert detail["accepted_count"] == 2
    assert [item["factor_id"] for item in detail["accepted_factors"]] == [
        factor_id(1, "$close"),
        factor_id(2, "$open"),
    ]
    assert detail["accepted_factors"][0]["ic"] == 0.01
    assert detail["manifest"]["pool_id"] == pool_id

    with pytest.raises(HTTPException) as excinfo:
        main.get_factor_run("..")
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main.get_factor_run("missing")
    assert excinfo.value.status_code == 404


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

    monkeypatch.setattr(main, "create_platform_job", fake_create)
    monkeypatch.setattr(main, "spawn_platform_job", lambda job_dir: captured.setdefault("spawned", job_dir))

    response = main.create_factor_backtest(
        main.FactorBacktestRequest(
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
    monkeypatch.setattr(
        main,
        "create_platform_job",
        lambda jobs_root, operation, payload: (
            captured.setdefault("payload", payload),
            _make_job_dir(jobs_root),
        )[1],
    )
    monkeypatch.setattr(main, "spawn_platform_job", lambda job_dir: None)

    response = main.create_factor_backtest(
        main.FactorBacktestRequest(factor_run_id="run_a", start_date="2021-06-18", end_date="2021-06-18")
    )

    assert "factor_ids" not in captured["payload"]
    assert response["selected_total"] == 2
    assert response["request_summary"]["factor_ids"] is None


def test_create_factor_backtest_rejects_invalid_parameters(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch, expressions=("$close", "$open"))

    def expect(message, **kwargs):
        with pytest.raises(HTTPException) as excinfo:
            main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a", **kwargs))
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

    _write_json(pool_manifest, {"pool_id": pool_id, "source_signature": "old"})
    with pytest.raises(HTTPException) as excinfo:
        main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "股票池" in excinfo.value.detail

    _write_json(pool_manifest, {"pool_id": pool_id, "source_signature": "sig"})
    _write_json(
        run_dir / "factor_run.json",
        {"pool_id": pool_id, "source_signature": "old"},
    )
    with pytest.raises(HTTPException) as excinfo:
        main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "因子运行" in excinfo.value.detail

    (run_dir / "accepted_factors.jsonl").write_text("", encoding="utf-8")
    _write_json(run_dir / "factor_run.json", {"pool_id": pool_id, "source_signature": "sig"})
    with pytest.raises(HTTPException) as excinfo:
        main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 422
    assert "没有合格因子" in excinfo.value.detail


def test_create_factor_backtest_requires_master(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    empty_master = tmp_path / "empty_master"
    empty_master.mkdir()
    monkeypatch.setattr(main, "MASTER_DIR", empty_master)

    with pytest.raises(HTTPException) as excinfo:
        main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 503
    assert "主缓存" in excinfo.value.detail


def test_create_factor_backtest_marks_job_failed_when_spawn_fails(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    monkeypatch.setattr(
        main,
        "create_platform_job",
        lambda jobs_root, operation, payload: _make_job_dir(jobs_root),
    )

    def boom(job_dir):
        raise OSError("no subprocess")

    monkeypatch.setattr(main, "spawn_platform_job", boom)

    with pytest.raises(HTTPException) as excinfo:
        main.create_factor_backtest(main.FactorBacktestRequest(factor_run_id="run_a"))
    assert excinfo.value.status_code == 500
    assert "启动失败" in excinfo.value.detail
    status = json.loads((main.JOBS_ROOT / "job_123" / "status.json").read_text(encoding="utf-8"))
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
    batch_dir, prefix, fid = _write_batch_result(main.RESULTS_ROOT)

    listing = main.get_factor_backtests("run_a", pool_id=None)
    assert listing["total"] == 1
    assert listing["batches"][0]["backtest_id"] == "batch_001"
    assert listing["batches"][0]["completed"] == 1
    assert listing["batches"][0]["run_key_prefix"] == prefix

    detail = main.get_factor_backtest("batch_001", factor_run_id="run_a", pool_id=None)
    assert detail["batch"]["backtest_id"] == "batch_001"
    assert detail["rows"][0]["factor_id"] == fid
    assert detail["rows"][0]["run_key"] == f"{prefix}/{fid}"
    assert detail["failures"][0]["error"].startswith("NameError")

    response = main.download_factor_backtest_file(
        "batch_001", "factor_backtest_summary.csv", factor_run_id="run_a", pool_id=None
    )
    assert Path(response.path) == batch_dir / "factor_backtest_summary.csv"

    with pytest.raises(HTTPException) as excinfo:
        main.download_factor_backtest_file(
            "batch_001", "other.csv", factor_run_id="run_a", pool_id=None
        )
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main.get_factor_backtest("missing", factor_run_id="run_a", pool_id=None)
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main.get_factor_backtests("run_a", pool_id="other")
    assert excinfo.value.status_code == 422


def test_csv_records_handles_empty_failure_file(tmp_path):
    empty = tmp_path / "factor_backtest_failures.csv"
    empty.write_text("\n", encoding="utf-8")
    assert main._csv_records(empty) == []

    missing = tmp_path / "missing.csv"
    assert main._csv_records(missing) == []


def test_nested_result_detail_and_download_by_run_key(master, tmp_path, monkeypatch):
    _factor_case(master, tmp_path, monkeypatch)
    _, prefix, fid = _write_batch_result(main.RESULTS_ROOT)
    run_key = f"{prefix}/{fid}"

    detail = main.get_result_by_key(run_key)
    assert detail["run_key"] == run_key
    assert detail["backtest_id"] == "batch_001"
    assert detail["factor_run_id"] == "run_a"
    assert detail["pool_id"] == "pool_a"

    response = main.download_result_file_by_key(run_key, "daily_report.csv")
    assert Path(response.path).name == "daily_report.csv"

    with pytest.raises(HTTPException) as excinfo:
        main.get_result_by_key("factor/../../secret")
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main.download_result_file_by_key(run_key, "summary.json")
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main._safe_relative(main.RESULTS_ROOT, "/etc/passwd")
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main._safe_relative(main.RESULTS_ROOT, "factor//pool")
    assert excinfo.value.status_code == 404
