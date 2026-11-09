from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from repositories import mysql_store


class FakeCursor:
    def __init__(self) -> None:
        self.executed = []
        self.many = []
        self.fetchone_queue = []
        self.fetchall_queue = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.many.append((sql, list(rows)))

    def fetchone(self):
        return self.fetchone_queue.pop(0) if self.fetchone_queue else None

    def fetchall(self):
        return self.fetchall_queue.pop(0) if self.fetchall_queue else []


class FakeConnection:
    def __init__(self) -> None:
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor


class SingleCursorConnection(FakeConnection):
    """每次 cursor() 都返回同一个游标，便于依次喂 fetchone / fetchall 结果。"""

    def __init__(self) -> None:
        super().__init__()
        self._cursor = FakeCursor()

    def cursor(self):
        self.cursors.append(self._cursor)
        return self._cursor


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


def test_parse_env_file_ignores_comments_and_quotes(tmp_path: Path):
    path = tmp_path / "mysql.local.env"
    path.write_text(
        "# comment\n\nQL_MYSQL_HOST=127.0.0.1\nexport QL_MYSQL_USER='quantlab'\n"
        'QL_MYSQL_PASSWORD="secret"\n',
        encoding="utf-8",
    )
    values = mysql_store.parse_env_file(path)
    assert values == {
        "QL_MYSQL_HOST": "127.0.0.1",
        "QL_MYSQL_USER": "quantlab",
        "QL_MYSQL_PASSWORD": "secret",
    }


def test_load_settings_prefers_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "mysql.local.env"
    path.write_text(
        "QL_MYSQL_HOST=file-host\nQL_MYSQL_USER=file-user\n"
        "QL_MYSQL_PASSWORD=file-pass\nQL_MYSQL_DATABASE=file-db\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("QL_MYSQL_ENABLED", raising=False)
    monkeypatch.setenv("QL_MYSQL_HOST", "env-host")
    monkeypatch.setenv("QL_MYSQL_USER", "env-user")
    monkeypatch.setenv("QL_MYSQL_PASSWORD", "env-pass")
    monkeypatch.setenv("QL_MYSQL_DATABASE", "env-db")
    settings = mysql_store.load_settings(path)
    assert settings is not None
    assert settings.host == "env-host"
    assert settings.user == "env-user"
    assert settings.database == "env-db"
    assert settings.password == "env-pass"
    assert "env-pass" not in json.dumps(settings.summary())


def test_load_settings_returns_none_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "mysql.local.env"
    path.write_text(
        "QL_MYSQL_HOST=host\nQL_MYSQL_USER=user\nQL_MYSQL_DATABASE=db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QL_MYSQL_ENABLED", "0")
    assert mysql_store.load_settings(path) is None


def test_json_safe_converts_nan_and_numpy_scalars():
    import numpy as np

    payload = {
        "nan": float("nan"),
        "inf": float("inf"),
        "numpy_int": np.int64(3),
        "numpy_float": np.float64(1.5),
        "nested": [float("-inf"), {"ok": np.bool_(True)}],
    }
    safe = mysql_store._json_safe(payload)
    assert safe["nan"] is None
    assert safe["inf"] is None
    assert safe["numpy_int"] == 3
    assert safe["numpy_float"] == 1.5
    assert safe["nested"][0] is None
    assert safe["nested"][1]["ok"] is True
    json.dumps(safe, allow_nan=False)


def test_schema_contains_expected_tables():
    names = mysql_store.table_names()
    assert "pools" in names
    assert "pool_codes" in names
    assert "factor_runs" in names
    assert "factors" in names
    assert "backtests" in names
    assert "backtest_daily" in names
    assert "backtest_positions" in names
    assert "factor_backtest_runs" in names


def test_persist_pool_writes_manifest_codes_and_stats(tmp_path: Path):
    pool_dir = tmp_path / "demo_pool_abcd1234"
    pool_dir.mkdir()
    manifest = {
        "pool_id": "demo_pool_abcd1234",
        "name": "demo_pool",
        "category": "stock",
        "source_signature": "sig",
        "selection_start": "2025-01-01",
        "selection_end": "2025-06-30",
        "top_n": 2,
        "min_listed_days": 250,
        "min_coverage": 0.9,
        "exclude_suspended": True,
        "strict_top_n": False,
        "n_stocks": 2,
        "selection_days": 120,
        "minimum_valid_rows": 108,
        "requested_codes": ["000001", "600000", "300750"],
        "selected_stats": [
            {"code": "000001", "average_amount": 1.5e8, "valid_rows": 120, "coverage": 1.0},
            {"code": "600000", "average_amount": 2.5e8, "valid_rows": 118, "coverage": 0.983},
        ],
        "provenance": {"source": "clickhouse", "filters": {"industries": ["银行"]}},
    }
    (pool_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pool_dir / "codes.txt").write_text("000001\n600000\n", encoding="utf-8")

    conn = FakeConnection()
    mysql_store._persist_pool_conn(conn, pool_dir)
    cursor = conn.cursors[0]
    sqls = [sql for sql, _ in cursor.executed]
    assert any("INSERT INTO `pools`" in sql for sql in sqls)
    assert any("DELETE FROM pool_codes" in sql for sql in sqls)
    assert any("DELETE FROM pool_candidates" in sql for sql in sqls)
    assert any("DELETE FROM pool_stats" in sql for sql in sqls)

    pool_row = next(params for sql, params in cursor.executed if "INSERT INTO `pools`" in sql)
    assert pool_row[0] == "demo_pool_abcd1234"
    assert pool_row[11] == 2  # n_stocks
    assert pool_row[14] == 3  # requested_total
    assert json.loads(pool_row[15])["source"] == "clickhouse"

    code_rows = next(rows for sql, rows in cursor.many if "INSERT INTO pool_codes" in sql)
    assert code_rows == [
        ("demo_pool_abcd1234", "000001", 0),
        ("demo_pool_abcd1234", "600000", 1),
    ]
    candidate_rows = next(rows for sql, rows in cursor.many if "INSERT INTO pool_candidates" in sql)
    assert [row[1] for row in candidate_rows] == ["000001", "600000", "300750"]


def test_fetch_pools_reads_manifest_and_formats_created_at():
    conn = SingleCursorConnection()
    cursor = conn.cursor()
    cursor.fetchall_queue.append(
        [
            {
                "pool_id": "demo_pool",
                "manifest": json.dumps(
                    {
                        "name": "demo",
                        "n_stocks": 2,
                        "selected_stats": [
                            {"code": "000001", "average_amount": 1.5e8, "coverage": 1.0},
                            {"code": "600000", "average_amount": 2.5e8, "coverage": 0.5},
                        ],
                    }
                ),
                "created_at": datetime(2026, 10, 27, 10, 30),
            }
        ]
    )

    rows = mysql_store._fetch_pools_conn(conn)

    assert len(rows) == 1
    assert rows[0]["pool_id"] == "demo_pool"
    assert rows[0]["manifest"]["pool_id"] == "demo_pool"
    assert rows[0]["manifest"]["name"] == "demo"
    assert rows[0]["created_at"] == "2026-10-27 10:30"


def test_fetch_pool_reads_codes_and_manifest_fields():
    conn = SingleCursorConnection()
    cursor = conn.cursor()
    cursor.fetchone_queue.append(
        {
            "pool_id": "demo_pool",
            "manifest": json.dumps({"name": "demo", "requested_codes": ["000001"]}),
            "minimum_valid_rows": 100,
            "created_at": datetime(2026, 10, 27, 10, 30),
        }
    )
    cursor.fetchall_queue.append([{"code": "000001"}, {"code": "600000"}])

    row = mysql_store._fetch_pool_conn(conn, "demo_pool")

    assert row is not None
    assert row["pool_id"] == "demo_pool"
    assert row["codes"] == ["000001", "600000"]
    assert row["manifest"]["minimum_valid_rows"] == 100
    assert row["manifest"]["requested_codes"] == ["000001"]
    assert row["created_at"] == "2026-10-27 10:30"


def test_fetch_pool_falls_back_to_pool_candidates():
    conn = SingleCursorConnection()
    cursor = conn.cursor()
    cursor.fetchone_queue.append(
        {
            "pool_id": "demo_pool",
            "manifest": json.dumps({"name": "demo"}),
            "minimum_valid_rows": None,
            "created_at": datetime(2026, 10, 27, 10, 30),
        }
    )
    cursor.fetchall_queue.extend(
        [
            [{"code": "000001"}],
            [{"code": "000001"}, {"code": "600000"}],
        ]
    )

    row = mysql_store._fetch_pool_conn(conn, "demo_pool")

    assert row is not None
    assert row["codes"] == ["000001"]
    assert row["manifest"]["requested_codes"] == ["000001", "600000"]


def test_fetch_pools_returns_none_without_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mysql_store, "load_settings", lambda *args, **kwargs: None)

    assert mysql_store.fetch_pools() is None
    assert mysql_store.fetch_pool("demo_pool") is None


def test_delete_pool_removes_children_before_pool_row():
    conn = SingleCursorConnection()
    cursor = conn.cursor()
    cursor.rowcount = 1

    deleted = mysql_store.delete_pool("demo_pool", conn=conn)

    assert deleted is True
    assert [sql.split(" FROM ")[1].split(" ")[0] for sql, _ in cursor.executed] == [
        "pool_stats",
        "pool_candidates",
        "pool_codes",
        "pools",
    ]
    assert all(params == ("demo_pool",) for _, params in cursor.executed)


def test_delete_pool_reports_missing_pool():
    conn = SingleCursorConnection()
    conn.cursor().rowcount = 0

    assert mysql_store.delete_pool("missing_pool", conn=conn) is False


def test_delete_pool_returns_none_without_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mysql_store, "load_settings", lambda *args, **kwargs: None)

    assert mysql_store.delete_pool("demo_pool") is None


def test_persist_backtest_writes_summary_and_result_tables(tmp_path: Path):
    run_dir = tmp_path / "demo_run"
    run_dir.mkdir()
    manifest = {
        "run_name": "demo_run",
        "created_at": "2026-10-25T10:00:00",
        "result_type": "factor",
        "pool_id": "demo_pool_abcd1234",
        "factor_run_id": "run_001",
        "canonical_expression": "rank(close)",
        "config": {"backtest": {"top_k": 10}},
        "components": [{"factor_id": "f1", "expression": "rank(close)", "weight": 1.0}],
        "generation_metrics": {"ic": 0.01, "score": float("nan")},
    }
    summary = {"total_return": 0.2, "sharpe": 1.5, "annual_return": float("nan")}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_dir / "daily_report.csv").write_text(
        "date,account,return,cost,turnover,cash,stock_value,pnl,drawdown,trade_count,holding_count\n"
        "2026-01-05,100000000.0,0.01,10.0,0.2,50000000.0,50000000.0,1000000.0,-0.02,3,10\n",
        encoding="utf-8",
    )
    (run_dir / "annual_metrics.csv").write_text(
        "year,return,sharpe,max_drawdown,turnover,cost,win_rate\n"
        "2026,0.2,1.5,-0.1,0.3,100.0,0.55\n",
        encoding="utf-8",
    )
    (run_dir / "trades.csv").write_text(
        "date,code,side,price,shares,amount,cost,reason\n"
        "2026-01-05,600000,buy,10.0,1000.0,10000.0,5.0,rebalance\n",
        encoding="utf-8",
    )
    (run_dir / "positions.csv").write_text(
        "date,code,weight,shares,price,value,alpha\n"
        "2026-01-05,600000,0.02,1000.0,10.0,10000.0,1.2\n",
        encoding="utf-8",
    )

    conn = FakeConnection()
    mysql_store._persist_backtest_conn(conn, run_dir)
    cursor = conn.cursors[0]
    sqls = [sql for sql, _ in cursor.executed]
    assert any("INSERT INTO `backtests`" in sql for sql in sqls)
    for table in (
        "backtest_components",
        "backtest_daily",
        "backtest_annual",
        "backtest_trades",
        "backtest_positions",
    ):
        assert any(f"DELETE FROM {table}" in sql for sql in sqls)

    backtest_row = next(params for sql, params in cursor.executed if "INSERT INTO `backtests`" in sql)
    expected_key = "factor/demo_pool_abcd1234/run_001/demo_run"
    assert backtest_row[0] == expected_key
    assert backtest_row[1] == "demo_run"
    assert backtest_row[2] == "demo_pool_abcd1234"
    assert backtest_row[3] == "run_001"
    assert backtest_row[7] == 0.2  # total_return
    assert backtest_row[8] is None  # annual_return NaN -> NULL

    daily_rows = next(rows for sql, rows in cursor.many if "INSERT INTO backtest_daily" in sql)
    assert daily_rows[0][0] == expected_key
    assert daily_rows[0][1] == date(2026, 1, 5)
    assert daily_rows[0][3] == 0.01


def test_backtest_run_key_disambiguates_same_run_name(tmp_path: Path):
    manifest = {
        "run_name": "factor_0001_abcdef1234",
        "result_type": "factor",
        "pool_id": "pool_a",
        "factor_run_id": "run_001",
    }
    other = {**manifest, "pool_id": "pool_b"}
    key_a = mysql_store._backtest_run_key(manifest, manifest["run_name"], tmp_path)
    key_b = mysql_store._backtest_run_key(other, manifest["run_name"], tmp_path)
    assert key_a == "factor/pool_a/run_001/factor_0001_abcdef1234"
    assert key_b == "factor/pool_b/run_001/factor_0001_abcdef1234"
    assert key_a != key_b


def test_backtest_run_key_prefers_manifest_value(tmp_path: Path):
    manifest = {"run_key": "custom/key", "run_name": "demo", "result_type": "manual"}
    assert mysql_store._backtest_run_key(manifest, "demo", tmp_path) == "custom/key"


def test_persist_factor_backtest_run_upserts_batch_summary(tmp_path: Path):
    batch_dir = tmp_path / "results" / "factor" / "pool_a" / "run_a" / "job_abc"
    batch_dir.mkdir(parents=True)
    manifest = {
        "backtest_id": "job_abc",
        "job_id": "job_abc",
        "pool_id": "pool_a",
        "factor_run_id": "run_a",
        "run_key_prefix": "factor/pool_a/run_a/job_abc",
        "accepted_count": 5,
        "selected_count": 3,
        "completed": 2,
        "failed": 1,
        "start_date": "2024-01-01",
        "end_date": "2024-06-30",
        "top_k": 20,
        "initial_cash": 50000000.0,
        "backtest_config": {"top_k": 20, "slippage": 0.0005},
        "created_at": "2026-10-25T10:00:00",
    }
    (batch_dir / "factor_backtest_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    conn = FakeConnection()
    mysql_store._persist_factor_backtest_run_conn(conn, batch_dir, job_id="job_abc")
    cursor = conn.cursors[0]
    sql, row = next(
        (sql, params)
        for sql, params in cursor.executed
        if "INSERT INTO `factor_backtest_runs`" in sql
    )
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert row[0] == "job_abc"
    assert row[1] == "job_abc"
    assert row[2] == "run_a"
    assert row[3] == "pool_a"
    assert row[4] == date(2024, 1, 1)
    assert row[5] == date(2024, 6, 30)
    assert row[6] == 20
    assert row[7] == 50000000.0
    assert row[8] == 5
    assert row[9] == 3
    assert row[10] == 2
    assert row[11] == 1
    assert row[13] == "factor/pool_a/run_a/job_abc"
    assert json.loads(row[15])["completed"] == 2


def _factor_run_insert_row(conn: FakeConnection) -> dict:
    cursor = conn.cursors[0]
    sql, params = next(
        (sql, params)
        for sql, params in cursor.executed
        if "INSERT INTO `factor_runs`" in sql
    )
    columns_sql = sql.split("(", 1)[1].split(")", 1)[0]
    columns = re.findall(r"`(\w+)`", columns_sql)
    return dict(zip(columns, params))


def test_persist_factor_run_writes_training_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mysql_store, "_JOBS_ROOT", tmp_path / "jobs")
    run_dir = tmp_path / "factor_runs" / "run_meta"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_meta",
        "pool_id": "pool_a",
        "run_name": "demo",
        "job_id": "20260101_120000_abcd",
        "data_source": "clickhouse",
        "device": "cuda",
        "started_at": "2026-01-01T12:00:00",
        "finished_at": "2026-01-01T12:10:00",
        "duration_seconds": 600.5,
        "training_seconds": 500.25,
        "timesteps": 4096,
        "n_stocks": 50,
        "created_at": "2026-01-01T12:10:00",
        "accepted_count": 1,
        "attempts": 10,
        "target_reached": True,
        "attempts_exhausted": False,
        "split_days": {"train": 100, "valid": 20, "test": 20},
        "fields": ["close", "volume"],
        "operators": ["add"],
        "operator_mode": "selected",
        "hyperparameters": {
            "target_factor_count": 1,
            "max_attempts": 10,
            "rollout_timesteps": 64,
            "seed": 7,
            "device": "cuda",
            "target_horizon": 5,
            "max_backtrack_days": 20,
            "max_future_days": 5,
            "quality": {"min_train_ic": 0.05},
        },
    }
    (run_dir / "factor_run.json").write_text(json.dumps(manifest), encoding="utf-8")

    conn = FakeConnection()
    _seal_confirmed(run_dir)
    evaluation = {"factor_id": "failed", "confirmed": False, "test": {"ic": 0.01}, "reason": "low IC"}
    (run_dir / "test_evaluations.jsonl").write_text(json.dumps(evaluation) + "\n", encoding="utf-8")
    mysql_store._persist_factor_run_conn(conn, run_dir)
    row = _factor_run_insert_row(conn)

    assert row["run_id"] == "run_meta"
    assert json.loads(row["raw"])["test_evaluations"] == [evaluation]
    assert row["device"] == "cuda"
    assert row["run_name"] == "demo"
    assert row["job_id"] == "20260101_120000_abcd"
    assert row["training_seconds"] == 500.25
    assert row["duration_seconds"] == 600.5
    assert row["timesteps"] == 4096
    assert row["n_stocks"] == 50
    assert row["max_attempts"] == 10
    assert row["rollout_timesteps"] == 64
    assert row["seed"] == 7
    assert json.loads(row["split_days"])["valid"] == 20
    assert json.loads(row["hyperparameters"])["device"] == "cuda"
    assert json.loads(row["fields"]) == ["close", "volume"]


def test_factor_expressions_fill_canonical_and_backtest():
    expression, canonical, backtest = mysql_store._factor_expressions(
        {"expression": "CSRank(Delta(close, 5))"}
    )

    assert expression == "CSRank(Delta(close, 5))"
    assert canonical == "rank(delta(close,5))"
    assert backtest == canonical


def test_factor_expressions_keep_explicit_values_and_handle_blank():
    expression, canonical, backtest = mysql_store._factor_expressions(
        {
            "expression": "rank(close)",
            "canonical_expression": "rank(close)",
            "backtest_expression": "rank(close) / 2",
        }
    )
    assert (expression, canonical, backtest) == ("rank(close)", "rank(close)", "rank(close) / 2")

    assert mysql_store._factor_expressions({"expression": "  "}) == (None, None, None)
    # 无法完全规范化的表达式也不能抛错，至少保留原文
    _, fallback, _ = mysql_store._factor_expressions({"expression": "rank(close"})
    assert fallback == "rank(close"


def test_persist_factor_run_writes_canonical_expressions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mysql_store, "_JOBS_ROOT", tmp_path / "jobs")
    run_dir = tmp_path / "factor_runs" / "run_expr"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_expr",
        "pool_id": "pool_a",
        "created_at": "2026-01-01T12:00:00",
        "attempts": 3,
        "accepted_count": 1,
    }
    (run_dir / "factor_run.json").write_text(json.dumps(manifest), encoding="utf-8")
    accepted = [{"expression": "CSRank(Delta(close, 5))", "ic": 0.03}]
    rejected = [{"expression": "Div(close, open)"}]
    (run_dir / "confirmed_factors.jsonl").write_text(
        "\n".join(json.dumps(record) for record in accepted) + "\n", encoding="utf-8"
    )
    (run_dir / "rejected_candidates.jsonl").write_text(
        "\n".join(json.dumps(record) for record in rejected) + "\n", encoding="utf-8"
    )

    conn = FakeConnection()
    _seal_confirmed(run_dir)
    mysql_store._persist_factor_run_conn(conn, run_dir)

    inserts = [
        rows
        for cursor in conn.cursors
        for sql, rows in cursor.many
        if "INSERT INTO factors" in sql
    ]
    assert len(inserts) == 1
    rows = inserts[0]
    assert [row[3] for row in rows] == [1, 0]  # 合格在前，拒绝在后
    assert rows[0][4] == "CSRank(Delta(close, 5))"
    assert rows[0][5] == "rank(delta(close,5))"
    assert rows[0][6] == "rank(delta(close,5))"
    assert rows[1][4] == "Div(close, open)"
    assert rows[1][5] == "div(close,open)"
    assert rows[1][6] == "div(close,open)"


def test_persist_factor_run_backfills_job_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_root = tmp_path / "jobs"
    job_dir = jobs_root / "20260102_090000_deadbeef"
    job_dir.mkdir(parents=True)
    payload = {
        "operation": "generate_factors",
        "payload": {
            "generation_config": {
                "run_id": "run_old",
                "target_factor_count": 2,
                "max_attempts": 20,
                "rollout_timesteps": 128,
                "seed": 3,
                "device": "cpu",
                "quality": {"min_train_ic": 0.04},
            }
        },
    }
    status = {
        "status": "finished",
        "updated_at": "2026-01-02T09:05:00",
        "progress": {"timesteps": 256},
    }
    (job_dir / "platform_job.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr(mysql_store, "_JOBS_ROOT", jobs_root)

    run_dir = tmp_path / "factor_runs" / "run_old"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_old",
        "pool_id": "pool_b",
        "created_at": "2026-01-02T09:05:00",
        "attempts": 5,
        "accepted_count": 0,
    }
    (run_dir / "factor_run.json").write_text(json.dumps(manifest), encoding="utf-8")

    conn = FakeConnection()
    _seal_confirmed(run_dir)
    mysql_store._persist_factor_run_conn(conn, run_dir)
    row = _factor_run_insert_row(conn)

    assert row["job_id"] == job_dir.name
    assert row["device"] == "cpu"
    assert row["target_factor_count"] == 2
    assert row["max_attempts"] == 20
    assert row["rollout_timesteps"] == 128
    assert row["seed"] == 3
    assert row["timesteps"] == 256
    assert row["started_at"] == datetime(2026, 1, 2, 9, 0, 0)
    assert row["finished_at"] == datetime(2026, 1, 2, 9, 5, 0)
    assert row["duration_seconds"] == 300.0
    assert json.loads(row["quality"])["min_train_ic"] == 0.04


def test_persist_pool_returns_false_without_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mysql_store, "load_settings", lambda *args, **kwargs: None)
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    (pool_dir / "manifest.json").write_text(json.dumps({"pool_id": "p", "name": "p"}), encoding="utf-8")
    assert mysql_store.persist_pool(pool_dir) is False


def test_upsert_without_non_key_columns_is_valid():
    cursor = FakeCursor()
    mysql_store._upsert(cursor, "pool_codes", ["pool_id", "code"], {"pool_id": "p", "code": "000001"})
    sql, params = cursor.executed[0]
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert params == ("p", "000001")
