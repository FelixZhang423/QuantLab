"""因子组合 API 服务层测试：提交、参数校验、结果读取与选股清单。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import common
from errors import DomainError
from repositories import company_source
from schemas import FactorCompositionRequest
from services import composition_service


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_confirmed(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"factor_id": "f1", "accepted": True, "expression": "close", "score": 1.0, "ic": 0.08, "status": "confirmed", "confirmed": True},
        {"factor_id": "f2", "accepted": True, "expression": "ma5", "score": 0.8, "ic": 0.04, "status": "confirmed", "confirmed": True},
    ]
    path = run_dir / "confirmed_factors.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    _write_json(
        run_dir / "confirmation_manifest.json",
        {"status": "finished", "confirmed_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    )


@pytest.fixture()
def composition_env(tmp_path, monkeypatch):
    pools_root = tmp_path / "pools"
    runs_root = tmp_path / "factor_runs"
    jobs_root = tmp_path / "jobs"
    results_root = tmp_path / "results" / "saved_backtests"
    pool_dir = pools_root / "pool_a"
    _write_json(
        pool_dir / "manifest.json",
        {
            "pool_id": "pool_a",
            "codes_file": "codes.txt",
            "selection_start": "2024-01-01",
            "selection_end": "2024-01-31",
            "source_signature": "sig",
        },
    )
    (pool_dir / "codes.txt").write_text("000001\n000002\n", encoding="utf-8")
    run_dir = runs_root / "run_a"
    _write_json(
        run_dir / "factor_run.json",
        {
            "run_id": "run_a",
            "pool_id": "pool_a",
            "snapshot_id": "snap_a",
            "source_signature": "sig",
        },
    )
    _write_confirmed(run_dir)
    monkeypatch.setattr(common, "POOLS_ROOT", pools_root)
    monkeypatch.setattr(common, "FACTOR_RUNS_ROOT", runs_root)
    monkeypatch.setattr(common, "JOBS_ROOT", jobs_root)
    monkeypatch.setattr(common, "RESULTS_ROOT", results_root)
    monkeypatch.setattr(common, "SNAPSHOT_ROOT", tmp_path / "snapshots")
    monkeypatch.setattr(company_source, "resolve_data_source", lambda *args, **kwargs: "local")
    monkeypatch.setattr(
        company_source,
        "meta",
        lambda: {"date_min": "2024-01-01", "date_max": "2024-12-31", "source_signature": "sig"},
    )
    monkeypatch.setattr(composition_service, "spawn_platform_job", lambda job_dir: None)
    return {
        "tmp": tmp_path,
        "pools_root": pools_root,
        "runs_root": runs_root,
        "jobs_root": jobs_root,
        "results_root": results_root,
    }


def _request(**overrides) -> FactorCompositionRequest:
    payload = {
        "pool_id": "pool_a",
        "factor_run_ids": ["run_a"],
        "factor_ids": ["f1"],
        "mutual_ic_threshold": 0.8,
        "z_clip": 3.0,
        "sweep_sizes": [1],
        "max_factors": 1,
        "top_k": 20,
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
    }
    payload.update(overrides)
    return FactorCompositionRequest(**payload)


def test_create_composition_dispatches_equal_weight_payload(composition_env):
    response = composition_service.create_factor_composition(_request())

    assert response["status"] == "queued"
    assert response["operation"] == "compose_factors"
    assert response["selected_total"] == 1
    assert response["candidate_total"] == 2
    assert any("无法满仓" in warning for warning in response["warnings"])
    job_dir = composition_env["jobs_root"] / response["job_id"]
    config = json.loads((job_dir / "platform_job.json").read_text(encoding="utf-8"))
    payload = config["payload"]
    assert payload["pool_id"] == "pool_a"
    assert "weight_method" not in payload
    assert payload["factor_ids"] == ["f1"]
    assert payload["z_clip"] == 3.0
    assert payload["sweep_sizes"] == [1]
    assert payload["max_factors"] == 1
    assert payload["backtest_config"]["start_date"] == "2024-01-01"
    assert payload["backtest_config"]["end_date"] == "2024-01-31"
    assert payload["factor_run_dirs"] == [str((composition_env["runs_root"] / "run_a").resolve())]


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"mutual_ic_threshold": 1.5}, "mutual_ic_threshold"),
        ({"z_clip": 0}, "z_clip"),
        ({"max_factors": 0}, "max_factors"),
        ({"sweep_sizes": [1, 2]}, "sweep_sizes"),
        ({"factor_ids": ["f1", "f2"], "max_factors": 1}, "max_factors"),
        ({"factor_ids": ["missing"]}, "不在所选运行中"),
    ],
)
def test_create_composition_rejects_invalid_requests(composition_env, overrides, expected):
    with pytest.raises(DomainError) as error:
        composition_service.create_factor_composition(_request(**overrides))

    assert error.value.status_code == 422
    assert expected in error.value.detail


def test_create_composition_rejects_pool_mismatch(composition_env):
    run_dir = composition_env["runs_root"] / "run_b"
    _write_json(
        run_dir / "factor_run.json",
        {"run_id": "run_b", "pool_id": "other_pool", "source_signature": "sig"},
    )
    _write_confirmed(run_dir)

    with pytest.raises(DomainError) as error:
        composition_service.create_factor_composition(
            _request(factor_run_ids=["run_b"], factor_ids=None, max_factors=2)
        )

    assert error.value.status_code == 422
    assert "不一致" in error.value.detail


def test_create_composition_requires_confirmed_run(composition_env):
    confirmation = composition_env["runs_root"] / "run_a" / "confirmation_manifest.json"
    _write_json(confirmation, {"status": "running"})

    with pytest.raises(DomainError) as error:
        composition_service.create_factor_composition(_request())

    assert error.value.status_code == 422
    assert "确认" in error.value.detail


def _write_composition_result(results_root: Path) -> Path:
    composition_dir = results_root / "composite" / "pool_a" / "comp_1"
    size_dir = composition_dir / "comp_1_size_002"
    size_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        size_dir / "factor_weights.json",
        [
            {"factor_id": "f1", "weight": 0.5},
            {"factor_id": "f2", "weight": 0.5},
        ],
    )
    _write_json(
        size_dir / "latest_screen.json",
        {
            "signal_date": "2024-01-31",
            "execution_date": None,
            "execution_pending": True,
            "selected_count": 2,
            "rows": [
                {"rank": 1, "code": "000001", "composite_score": 1.2, "selected": True},
                {"rank": 2, "code": "000002", "composite_score": 0.8, "selected": True},
                {"rank": 3, "code": "000003", "composite_score": 0.2, "selected": False},
            ],
        },
    )
    _write_json(
        composition_dir / "composition_manifest.json",
        {
            "composition_id": "comp_1",
            "pool_id": "pool_a",
            "created_at": "2026-11-09T10:00:00",
            "weight_method": "equal",
            "candidate_count": 5,
            "selected_count": 4,
            "completed_sizes": [2],
            "default_size": 2,
            "z_clip": 3.0,
            "sizes": [
                {
                    "size": 2,
                    "output_dir": str(size_dir.resolve()),
                    "composition_metrics": {"ic": 0.05},
                    "backtest_summary": {"sharpe": 1.2},
                    "screen": {"selected_count": 2},
                }
            ],
        },
    )
    return composition_dir


def test_get_composition_and_screen(composition_env, monkeypatch):
    _write_composition_result(composition_env["results_root"])
    monkeypatch.setattr(
        composition_service,
        "_screen_name_map",
        lambda: {"000001": "平安银行", "000002": "万科A"},
    )

    detail = composition_service.get_factor_composition("comp_1", "pool_a")
    assert detail["size"] == 2
    assert detail["available_sizes"] == [2]
    assert detail["manifest"]["weight_method"] == "equal"
    assert [row["factor_id"] for row in detail["weights"]] == ["f1", "f2"]

    screen = composition_service.get_factor_composition_screen("comp_1", "pool_a", limit=2)
    assert screen["size"] == 2
    assert screen["screen"]["returned_rows"] == 2
    assert screen["screen"]["total_returned_rows"] == 3
    assert [row["name"] for row in screen["screen"]["rows"]] == ["平安银行", "万科A"]

    listing = composition_service.get_factor_compositions("pool_a")
    assert listing["total"] == 1
    assert listing["compositions"][0]["composition_id"] == "comp_1"


def test_screen_name_lookup_is_optional(monkeypatch):
    composition_service._name_cache = None
    composition_service._name_failed_at = 0.0

    def boom():
        raise RuntimeError("clickhouse offline")

    monkeypatch.setattr(composition_service.live_db, "live_dim_profiles", boom)
    try:
        assert composition_service._screen_name_map() == {}
    finally:
        composition_service._name_cache = None
        composition_service._name_failed_at = 0.0


def test_get_composition_rejects_unknown_size_and_path_traversal(composition_env):
    _write_composition_result(composition_env["results_root"])

    with pytest.raises(DomainError) as error:
        composition_service.get_factor_composition("comp_1", "pool_a", size=9)
    assert error.value.status_code == 404

    with pytest.raises(DomainError) as error:
        composition_service.get_factor_composition("../comp_1", "pool_a")
    assert error.value.status_code == 404


def test_composition_routes_are_registered():
    from api.main import app

    paths = set(app.openapi().get("paths", {}))
    assert "/api/factor-compositions" in paths
    assert "/api/factor-compositions/{composition_id}" in paths
    assert "/api/factor-compositions/{composition_id}/screen" in paths
