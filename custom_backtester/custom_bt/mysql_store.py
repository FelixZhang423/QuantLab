"""MySQL 持久化层：股票池、因子运行、回测结果。

设计口径：

- **本地文件仍是主存储**：建池/因子生成/回测照旧写 ``data_cache/pools``、
  ``factor_runs``、``outputs/saved_backtests``，MySQL 是集中存档，便于跨机器查询；
- 所有 ``persist_*`` 都是**尽力而为**：未配置或连不上 MySQL 时返回 ``False``，
  不影响本地流程；
- 表结构由 ``ensure_schema()`` 幂等创建，写入使用 ``INSERT ... ON DUPLICATE KEY UPDATE``
  与「先删子表再插入」，重复同步同一份结果不会产生重复行；
- 密码只从环境变量或已 gitignore 的 ``configs/mysql.local.env`` 读取，不写入代码/日志。

配置项（环境变量优先，其次 ``configs/mysql.local.env``）：

``QL_MYSQL_HOST`` / ``QL_MYSQL_PORT`` / ``QL_MYSQL_USER`` /
``QL_MYSQL_PASSWORD`` / ``QL_MYSQL_DATABASE`` / ``QL_MYSQL_ENABLED`` /
``QL_MYSQL_ENV_FILE``

CLI::

    py -3 -m custom_bt.mysql_store schema
    py -3 -m custom_bt.mysql_store check
    py -3 -m custom_bt.mysql_store sync
    py -3 -m custom_bt.cli mysql-sync
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / "configs" / "mysql.local.env"
SCHEMA_VERSION = "3"
_BATCH_SIZE = 1000
_TABLE_COLUMNS_CACHE: Dict[str, List[str]] = {}
_SCHEMA_READY: set[Tuple[str, int, str]] = set()
_SCHEMA_LOCK = threading.Lock()


@dataclass(frozen=True)
class MySQLSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    source: str = "environment"

    def summary(self) -> Dict[str, Any]:
        """可安全打印的连接信息（不含密码）。"""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def parse_env_file(path: str | Path) -> Dict[str, str]:
    """解析 KEY=VALUE 形式的环境文件；忽略注释、空行和可选 export 前缀。"""
    values: Dict[str, str] = {}
    path = Path(path)
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_settings(env_file: str | Path | None = None) -> Optional[MySQLSettings]:
    """读取连接配置；未配置或显式关闭时返回 None。"""
    enabled = os.environ.get("QL_MYSQL_ENABLED", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return None

    path = Path(
        env_file
        or os.environ.get("QL_MYSQL_ENV_FILE")
        or DEFAULT_ENV_FILE
    ).expanduser()
    file_values = parse_env_file(path)

    def get(key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.environ.get(key)
        if value is not None and value != "":
            return value
        return file_values.get(key, default)

    host = (get("QL_MYSQL_HOST") or "").strip()
    user = (get("QL_MYSQL_USER") or "").strip()
    database = (get("QL_MYSQL_DATABASE") or "").strip()
    if not host or not user or not database:
        return None
    raw_port = (get("QL_MYSQL_PORT") or "3306").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 3306
    source = "environment" if os.environ.get("QL_MYSQL_HOST") else (str(path) if file_values else "environment")
    return MySQLSettings(
        host=host,
        port=port,
        user=user,
        password=get("QL_MYSQL_PASSWORD") or "",
        database=database,
        source=source,
    )


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid MySQL identifier: {value!r}")
    return value


def _is_unknown_database(exc: BaseException) -> bool:
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == 1049


def connect(settings: MySQLSettings | None = None, *, with_database: bool = True):
    """创建 PyMySQL 连接；未安装驱动时给出可执行的提示。"""
    settings = settings or load_settings()
    if settings is None:
        raise RuntimeError(
            "MySQL 未配置：请设置 QL_MYSQL_HOST/QL_MYSQL_USER/QL_MYSQL_DATABASE，"
            f"或填写 {DEFAULT_ENV_FILE}"
        )
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时才会触发
        raise RuntimeError("需要 PyMySQL：py -3 -m pip install PyMySQL") from exc

    kwargs: Dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "user": settings.user,
        "password": settings.password,
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
        "connect_timeout": 8,
        "read_timeout": 120,
        "write_timeout": 120,
    }
    if with_database:
        kwargs["database"] = settings.database
    return pymysql.connect(**kwargs)


def _connect(settings: MySQLSettings):
    try:
        return connect(settings)
    except Exception as exc:
        if not _is_unknown_database(exc):
            raise
        base = connect(settings, with_database=False)
        try:
            with base.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{_safe_identifier(settings.database)}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            base.commit()
        finally:
            base.close()
        return connect(settings)


# ---------------------------------------------------------------------------
# 表结构
# ---------------------------------------------------------------------------

_TABLE_DDL: Tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS pools (
        pool_id VARCHAR(191) NOT NULL,
        name VARCHAR(191) NOT NULL,
        category VARCHAR(64) NULL,
        source_signature VARCHAR(128) NULL,
        selection_start DATE NULL,
        selection_end DATE NULL,
        top_n INT NULL,
        min_listed_days INT NULL,
        min_coverage DOUBLE NULL,
        exclude_suspended TINYINT(1) NULL,
        strict_top_n TINYINT(1) NULL,
        n_stocks INT NULL,
        selection_days INT NULL,
        minimum_valid_rows INT NULL,
        requested_total INT NULL,
        provenance JSON NULL,
        manifest JSON NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (pool_id),
        KEY idx_pools_name (name),
        KEY idx_pools_window (selection_start, selection_end)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pool_codes (
        pool_id VARCHAR(191) NOT NULL,
        code CHAR(6) NOT NULL,
        seq INT NOT NULL,
        PRIMARY KEY (pool_id, code),
        KEY idx_pool_codes_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pool_candidates (
        pool_id VARCHAR(191) NOT NULL,
        code CHAR(6) NOT NULL,
        seq INT NOT NULL,
        PRIMARY KEY (pool_id, code),
        KEY idx_pool_candidates_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pool_stats (
        pool_id VARCHAR(191) NOT NULL,
        code CHAR(6) NOT NULL,
        seq INT NOT NULL,
        average_amount DOUBLE NULL,
        valid_rows INT NULL,
        coverage DOUBLE NULL,
        PRIMARY KEY (pool_id, code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_runs (
        run_id VARCHAR(191) NOT NULL,
        pool_id VARCHAR(191) NULL,
        factor_run_dir VARCHAR(1024) NULL,
        source_signature VARCHAR(128) NULL,
        runtime_id VARCHAR(191) NULL,
        created_at DATETIME NOT NULL,
        accepted_count INT NULL,
        attempts INT NULL,
        target_reached TINYINT(1) NULL,
        attempts_exhausted TINYINT(1) NULL,
        raw JSON NULL,
        PRIMARY KEY (run_id),
        KEY idx_factor_runs_pool (pool_id),
        KEY idx_factor_runs_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS factors (
        run_id VARCHAR(191) NOT NULL,
        seq INT NOT NULL,
        factor_id VARCHAR(191) NOT NULL,
        accepted TINYINT(1) NOT NULL,
        expression TEXT NULL,
        canonical_expression TEXT NULL,
        backtest_expression TEXT NULL,
        ic DOUBLE NULL,
        rank_ic DOUBLE NULL,
        icir DOUBLE NULL,
        coverage DOUBLE NULL,
        score DOUBLE NULL,
        raw JSON NULL,
        PRIMARY KEY (run_id, seq),
        KEY idx_factors_factor_id (factor_id),
        KEY idx_factors_pool_expression (factor_id, accepted)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_backtest_runs (
        backtest_id VARCHAR(191) NOT NULL,
        job_id VARCHAR(191) NULL,
        factor_run_id VARCHAR(191) NOT NULL,
        pool_id VARCHAR(191) NOT NULL,
        start_date DATE NULL,
        end_date DATE NULL,
        top_k INT NULL,
        initial_cash DOUBLE NULL,
        accepted_count INT NOT NULL DEFAULT 0,
        selected_count INT NOT NULL DEFAULT 0,
        completed INT NOT NULL DEFAULT 0,
        failed INT NOT NULL DEFAULT 0,
        output_dir VARCHAR(1024) NOT NULL,
        run_key_prefix VARCHAR(512) NULL,
        config JSON NULL,
        manifest JSON NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (backtest_id),
        KEY idx_factor_backtest_runs_factor_run (factor_run_id),
        KEY idx_factor_backtest_runs_pool (pool_id),
        KEY idx_factor_backtest_runs_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtests (
        run_key VARCHAR(512) NOT NULL,
        run_name VARCHAR(191) NOT NULL,
        pool_id VARCHAR(191) NULL,
        factor_run_id VARCHAR(191) NULL,
        result_type VARCHAR(32) NULL,
        canonical_expression TEXT NULL,
        created_at DATETIME NOT NULL,
        total_return DOUBLE NULL,
        annual_return DOUBLE NULL,
        sharpe DOUBLE NULL,
        max_drawdown DOUBLE NULL,
        calmar DOUBLE NULL,
        win_rate DOUBLE NULL,
        average_turnover DOUBLE NULL,
        total_cost DOUBLE NULL,
        annual_cost DOUBLE NULL,
        number_of_trades DOUBLE NULL,
        average_holding_count DOUBLE NULL,
        generation_metrics JSON NULL,
        summary JSON NULL,
        config JSON NULL,
        manifest JSON NULL,
        PRIMARY KEY (run_key),
        KEY idx_backtests_run_name (run_name),
        KEY idx_backtests_pool (pool_id),
        KEY idx_backtests_factor_run (factor_run_id),
        KEY idx_backtests_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_components (
        run_key VARCHAR(512) NOT NULL,
        seq INT NOT NULL,
        factor_id VARCHAR(191) NULL,
        expression TEXT NULL,
        weight DOUBLE NULL,
        PRIMARY KEY (run_key, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_daily (
        run_key VARCHAR(512) NOT NULL,
        trade_date DATE NOT NULL,
        account DOUBLE NULL,
        daily_return DOUBLE NULL,
        cost DOUBLE NULL,
        turnover DOUBLE NULL,
        cash DOUBLE NULL,
        stock_value DOUBLE NULL,
        pnl DOUBLE NULL,
        drawdown DOUBLE NULL,
        trade_count INT NULL,
        holding_count INT NULL,
        PRIMARY KEY (run_key, trade_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_annual (
        run_key VARCHAR(512) NOT NULL,
        metric_year INT NOT NULL,
        annual_return DOUBLE NULL,
        sharpe DOUBLE NULL,
        max_drawdown DOUBLE NULL,
        turnover DOUBLE NULL,
        cost DOUBLE NULL,
        win_rate DOUBLE NULL,
        PRIMARY KEY (run_key, metric_year)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_trades (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        run_key VARCHAR(512) NOT NULL,
        trade_date DATE NULL,
        code CHAR(6) NULL,
        side VARCHAR(16) NULL,
        price DOUBLE NULL,
        shares DOUBLE NULL,
        amount DOUBLE NULL,
        cost DOUBLE NULL,
        reason VARCHAR(64) NULL,
        PRIMARY KEY (id),
        KEY idx_backtest_trades_run (run_key, trade_date),
        KEY idx_backtest_trades_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_positions (
        run_key VARCHAR(512) NOT NULL,
        position_date DATE NOT NULL,
        code CHAR(6) NOT NULL,
        weight DOUBLE NULL,
        shares DOUBLE NULL,
        price DOUBLE NULL,
        position_value DOUBLE NULL,
        alpha DOUBLE NULL,
        PRIMARY KEY (run_key, position_date, code),
        KEY idx_backtest_positions_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ql_schema_meta (
        meta_key VARCHAR(64) NOT NULL,
        meta_value VARCHAR(255) NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (meta_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def table_names() -> List[str]:
    return [name for name in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "\n".join(_TABLE_DDL))]


_LEGACY_BACKTEST_TABLES = (
    "backtest_positions",
    "backtest_trades",
    "backtest_annual",
    "backtest_daily",
    "backtest_components",
    "backtests",
)


def _has_column(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s LIMIT 1",
        (table, column),
    )
    return cur.fetchone() is not None


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        # v1 以 run_name 作为回测主键，不同股票池/因子运行下的同名因子会互相覆盖。
        # 本地文件仍是主存储，检测到旧结构时重建回测表，再用 mysql-sync 补录。
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name='backtests' LIMIT 1"
        )
        if cur.fetchone() is not None and not _has_column(cur, "backtests", "run_key"):
            logger.warning(
                "检测到旧版回测表结构（run_name 主键），重建回测表；"
                "请运行 py -3 -m custom_bt.cli mysql-sync 补录本地回测结果"
            )
            cur.execute("DROP TABLE IF EXISTS " + ", ".join(_LEGACY_BACKTEST_TABLES))
        for statement in _TABLE_DDL:
            cur.execute(statement)
        cur.execute(
            "INSERT INTO ql_schema_meta (meta_key, meta_value) VALUES ('schema_version', %s) "
            "ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value)",
            (SCHEMA_VERSION,),
        )
    conn.commit()


def _ensure_schema_cached(conn, settings: MySQLSettings) -> None:
    key = (settings.host, settings.port, settings.database)
    if key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        ensure_schema(conn)
        _SCHEMA_READY.add(key)


@contextmanager
def _connection(settings: MySQLSettings) -> Iterator[Any]:
    conn = _connect(settings)
    try:
        _ensure_schema_cached(conn, settings)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    """把 numpy/pandas 标量和 NaN/Inf 转成 MySQL JSON 可接受的值。"""
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(_json_safe(value), ensure_ascii=False, allow_nan=False)


def _read_json(path: str | Path) -> Optional[Any]:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json_object(value: Any) -> Dict[str, Any]:
    """把 MySQL JSON 列（str / bytes / dict）统一成 dict。"""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _format_datetime(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value else None


def _normalize_db_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(6) if digits else ""


def _read_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_codes(path: str | Path) -> List[str]:
    path = Path(path)
    if not path.is_file():
        return []
    codes: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code = line.strip()
        if not code:
            continue
        digits = re.sub(r"\D", "", code)
        if digits:
            codes.append(digits.zfill(6))
    return codes


def _read_csv_rows(path: str | Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        import pandas as pd

        frame = pd.read_csv(path)
    except Exception:
        return []
    return [_json_safe(row) for row in frame.to_dict("records")]


def _to_datetime(value: Any, fallback_path: str | Path | None = None) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if value not in (None, ""):
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    if fallback_path is not None:
        path = Path(fallback_path)
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime)
    return None


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value: Any) -> Optional[int]:
    number = _to_float(value)
    return None if number is None else int(number)


def _to_bool(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "y", "on"} else 0
    return 1 if bool(value) else 0


def _clean_text(value: Any, limit: int | None = None) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if limit is not None:
        text = text[:limit]
    return text


def _upsert(cur, table: str, key_columns: Sequence[str], row: Mapping[str, Any]) -> None:
    columns = list(row.keys())
    column_sql = ", ".join(f"`{name}`" for name in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(
        f"`{name}`=VALUES(`{name}`)" for name in columns if name not in key_columns
    )
    sql = f"INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})"
    if updates:
        sql += f" ON DUPLICATE KEY UPDATE {updates}"
    else:
        sql += " ON DUPLICATE KEY UPDATE `" + key_columns[0] + "`=VALUES(`" + key_columns[0] + "`)"
    cur.execute(sql, tuple(row[name] for name in columns))


def _batch_insert(cur, sql: str, rows: Sequence[Sequence[Any]]) -> None:
    for start in range(0, len(rows), _BATCH_SIZE):
        cur.executemany(sql, rows[start:start + _BATCH_SIZE])


def _run_persist(settings: Optional[MySQLSettings], conn, callback) -> bool:
    if conn is not None:
        callback(conn)
        return True
    settings = settings or load_settings()
    if settings is None:
        return False
    with _connection(settings) as owned:
        callback(owned)
    return True


# ---------------------------------------------------------------------------
# 股票池
# ---------------------------------------------------------------------------


def _persist_pool_conn(conn, pool_dir: Path) -> None:
    manifest_path = pool_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"pool manifest missing or invalid: {manifest_path}")
    pool_id = str(manifest.get("pool_id") or pool_dir.name)
    codes = _read_codes(pool_dir / str(manifest.get("codes_file") or "codes.txt"))
    requested = manifest.get("requested_codes")
    requested_codes = [] if requested is None else [
        re.sub(r"\D", "", str(code)).zfill(6) for code in requested if re.sub(r"\D", "", str(code))
    ]
    stats = manifest.get("selected_stats") or []
    created_at = _to_datetime(manifest.get("created_at"), manifest_path) or datetime.now()

    row = {
        "pool_id": pool_id,
        "name": _clean_text(manifest.get("name") or pool_id, 191),
        "category": _clean_text(manifest.get("category"), 64),
        "source_signature": _clean_text(manifest.get("source_signature"), 128),
        "selection_start": _to_date(manifest.get("selection_start")),
        "selection_end": _to_date(manifest.get("selection_end")),
        "top_n": _to_int(manifest.get("top_n")),
        "min_listed_days": _to_int(manifest.get("min_listed_days")),
        "min_coverage": _to_float(manifest.get("min_coverage")),
        "exclude_suspended": _to_bool(manifest.get("exclude_suspended")),
        "strict_top_n": _to_bool(manifest.get("strict_top_n")),
        "n_stocks": _to_int(manifest.get("n_stocks")) or len(codes),
        "selection_days": _to_int(manifest.get("selection_days")),
        "minimum_valid_rows": _to_int(manifest.get("minimum_valid_rows")),
        "requested_total": len(requested_codes) if requested is not None else None,
        "provenance": _json_text(manifest.get("provenance")),
        "manifest": _json_text(manifest),
        "created_at": created_at,
    }

    with conn.cursor() as cur:
        _upsert(cur, "pools", ["pool_id"], row)
        cur.execute("DELETE FROM pool_codes WHERE pool_id=%s", (pool_id,))
        if codes:
            _batch_insert(
                cur,
                "INSERT INTO pool_codes (pool_id, code, seq) VALUES (%s, %s, %s)",
                [(pool_id, code, index) for index, code in enumerate(codes)],
            )
        cur.execute("DELETE FROM pool_candidates WHERE pool_id=%s", (pool_id,))
        if requested_codes:
            _batch_insert(
                cur,
                "INSERT INTO pool_candidates (pool_id, code, seq) VALUES (%s, %s, %s)",
                [(pool_id, code, index) for index, code in enumerate(dict.fromkeys(requested_codes))],
            )
        cur.execute("DELETE FROM pool_stats WHERE pool_id=%s", (pool_id,))
        stats_rows = []
        for index, item in enumerate(stats):
            if not isinstance(item, dict):
                continue
            code = re.sub(r"\D", "", str(item.get("code") or "")).zfill(6)
            if not code:
                continue
            stats_rows.append(
                (
                    pool_id,
                    code,
                    index,
                    _to_float(item.get("average_amount")),
                    _to_int(item.get("valid_rows")),
                    _to_float(item.get("coverage")),
                )
            )
        if stats_rows:
            _batch_insert(
                cur,
                "INSERT INTO pool_stats (pool_id, code, seq, average_amount, valid_rows, coverage) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                stats_rows,
            )


def persist_pool(pool_dir: str | Path, *, settings: MySQLSettings | None = None, conn=None) -> bool:
    """把单个股票池目录同步到 MySQL；未配置连接时返回 False。"""
    return _run_persist(
        settings,
        conn,
        lambda owned: _persist_pool_conn(owned, Path(pool_dir)),
    )


def _fetch_pools_conn(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pool_id, manifest, created_at FROM pools "
            "ORDER BY created_at DESC, pool_id"
        )
        rows = cur.fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        manifest = _json_object(row.get("manifest"))
        pool_id = str(row.get("pool_id") or manifest.get("pool_id") or "")
        if not pool_id:
            continue
        manifest.setdefault("pool_id", pool_id)
        manifest.setdefault("name", pool_id)
        results.append(
            {
                "pool_id": pool_id,
                "manifest": manifest,
                "created_at": _format_datetime(row.get("created_at")),
            }
        )
    return results


def fetch_pools(
    *, settings: MySQLSettings | None = None, conn=None
) -> Optional[List[Dict[str, Any]]]:
    """从 MySQL 读取全部股票池；未配置 MySQL 时返回 None。

    返回项形如 ``{"pool_id", "manifest", "created_at"}``，manifest 即建池时
    写入的完整 JSON（含 provenance / selected_stats / requested_codes）。
    """
    if conn is not None:
        return _fetch_pools_conn(conn)
    settings = settings or load_settings()
    if settings is None:
        return None
    owned = connect(settings)
    try:
        return _fetch_pools_conn(owned)
    finally:
        owned.close()


def _fetch_pool_conn(conn, pool_id: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pool_id, manifest, minimum_valid_rows, created_at FROM pools "
            "WHERE pool_id=%s",
            (pool_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        manifest = _json_object(row.get("manifest"))
        resolved_id = str(row.get("pool_id") or pool_id)
        manifest.setdefault("pool_id", resolved_id)
        if manifest.get("minimum_valid_rows") is None and row.get("minimum_valid_rows") is not None:
            manifest["minimum_valid_rows"] = row.get("minimum_valid_rows")
        cur.execute(
            "SELECT code FROM pool_codes WHERE pool_id=%s ORDER BY seq",
            (pool_id,),
        )
        codes = [_normalize_db_code(item.get("code")) for item in cur.fetchall()]
        codes = [code for code in codes if code]
        if manifest.get("requested_codes") is None:
            cur.execute(
                "SELECT code FROM pool_candidates WHERE pool_id=%s ORDER BY seq",
                (pool_id,),
            )
            requested = [_normalize_db_code(item.get("code")) for item in cur.fetchall()]
            manifest["requested_codes"] = [code for code in requested if code]
    return {
        "pool_id": resolved_id,
        "manifest": manifest,
        "codes": codes,
        "created_at": _format_datetime(row.get("created_at")),
    }


def fetch_pool(
    pool_id: str, *, settings: MySQLSettings | None = None, conn=None
) -> Optional[Dict[str, Any]]:
    """从 MySQL 读取单个股票池；未配置或不存在时返回 None。"""
    if conn is not None:
        return _fetch_pool_conn(conn, pool_id)
    settings = settings or load_settings()
    if settings is None:
        return None
    owned = connect(settings)
    try:
        return _fetch_pool_conn(owned, pool_id)
    finally:
        owned.close()


# ---------------------------------------------------------------------------
# 因子运行
# ---------------------------------------------------------------------------


def _factor_rows(run_id: str, accepted: List[Dict[str, Any]], rejected: List[Dict[str, Any]]) -> List[tuple]:
    rows: List[tuple] = []
    seq = 0
    for accepted_flag, records in ((1, accepted), (0, rejected)):
        for record in records:
            factor_id = (
                record.get("factor_id")
                or record.get("id")
                or record.get("name")
                or f"factor_{seq:04d}"
            )
            rows.append(
                (
                    run_id,
                    seq,
                    _clean_text(factor_id, 191),
                    accepted_flag,
                    _clean_text(record.get("expression")),
                    _clean_text(record.get("canonical_expression")),
                    _clean_text(record.get("backtest_expression")),
                    _to_float(record.get("ic")),
                    _to_float(record.get("rank_ic")),
                    _to_float(record.get("icir")),
                    _to_float(record.get("coverage")),
                    _to_float(record.get("score")),
                    _json_text(record),
                )
            )
            seq += 1
    return rows


def _persist_factor_run_conn(conn, run_dir: Path) -> None:
    manifest = _read_json(run_dir / "factor_run.json")
    accepted = _read_jsonl(run_dir / "accepted_factors.jsonl")
    rejected = _read_jsonl(run_dir / "rejected_candidates.jsonl")
    if not isinstance(manifest, dict) and not accepted and not rejected:
        raise ValueError(f"factor run manifest missing: {run_dir / 'factor_run.json'}")
    manifest = manifest if isinstance(manifest, dict) else {}
    run_id = str(manifest.get("run_id") or run_dir.name)
    created_at = _to_datetime(manifest.get("created_at"), run_dir / "factor_run.json") or datetime.now()
    pool_id = manifest.get("pool_id")
    if not pool_id:
        for record in accepted + rejected:
            if record.get("pool_id"):
                pool_id = record.get("pool_id")
                break

    row = {
        "run_id": run_id,
        "pool_id": _clean_text(pool_id, 191),
        "factor_run_dir": _clean_text(str(run_dir.resolve()), 1024),
        "source_signature": _clean_text(manifest.get("source_signature"), 128),
        "runtime_id": _clean_text(manifest.get("runtime_id"), 191),
        "created_at": created_at,
        "accepted_count": _to_int(manifest.get("accepted_count")) or len(accepted),
        "attempts": _to_int(manifest.get("attempts")),
        "target_reached": _to_bool(manifest.get("target_reached")),
        "attempts_exhausted": _to_bool(manifest.get("attempts_exhausted")),
        "raw": _json_text(manifest),
    }
    factor_rows = _factor_rows(run_id, accepted, rejected)

    with conn.cursor() as cur:
        _upsert(cur, "factor_runs", ["run_id"], row)
        cur.execute("DELETE FROM factors WHERE run_id=%s", (run_id,))
        if factor_rows:
            _batch_insert(
                cur,
                "INSERT INTO factors (run_id, seq, factor_id, accepted, expression, "
                "canonical_expression, backtest_expression, ic, rank_ic, icir, coverage, score, raw) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                factor_rows,
            )


def persist_factor_run(run_dir: str | Path, *, settings: MySQLSettings | None = None, conn=None) -> bool:
    """把单个因子运行目录同步到 MySQL；未配置连接时返回 False。"""
    return _run_persist(
        settings,
        conn,
        lambda owned: _persist_factor_run_conn(owned, Path(run_dir)),
    )


# ---------------------------------------------------------------------------
# 因子批量回测批次
# ---------------------------------------------------------------------------


def _persist_factor_backtest_run_conn(conn, output_dir: Path, job_id: str | None = None) -> None:
    output_dir = Path(output_dir)
    manifest_path = output_dir / "factor_backtest_manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"factor backtest manifest missing or invalid: {manifest_path}")
    backtest_id = _clean_text(manifest.get("backtest_id") or job_id or output_dir.name, 191)
    factor_run_id = _clean_text(manifest.get("factor_run_id") or output_dir.parent.name, 191)
    pool_id = _clean_text(manifest.get("pool_id") or output_dir.parent.parent.name, 191)
    if not backtest_id or not factor_run_id or not pool_id:
        raise ValueError(f"factor backtest manifest is missing backtest/run/pool id: {manifest_path}")
    accepted_count = _to_int(manifest.get("accepted_count"))
    selected_count = _to_int(manifest.get("selected_count"))
    config = manifest.get("backtest_config") if isinstance(manifest.get("backtest_config"), dict) else {}
    run_key_prefix = _clean_text(
        manifest.get("run_key_prefix") or f"factor/{pool_id}/{factor_run_id}/{backtest_id}",
        512,
    )
    row = {
        "backtest_id": backtest_id,
        "job_id": _clean_text(manifest.get("job_id") or job_id, 191),
        "factor_run_id": factor_run_id,
        "pool_id": pool_id,
        "start_date": _to_date(manifest.get("start_date")),
        "end_date": _to_date(manifest.get("end_date")),
        "top_k": _to_int(manifest.get("top_k")),
        "initial_cash": _to_float(manifest.get("initial_cash")),
        "accepted_count": 0 if accepted_count is None else accepted_count,
        "selected_count": accepted_count if selected_count is None else selected_count,
        "completed": _to_int(manifest.get("completed")) or 0,
        "failed": _to_int(manifest.get("failed")) or 0,
        "output_dir": _clean_text(str(output_dir.resolve()), 1024),
        "run_key_prefix": run_key_prefix,
        "config": _json_text(config),
        "manifest": _json_text(manifest),
        "created_at": _to_datetime(manifest.get("created_at"), manifest_path) or datetime.now(),
    }
    with conn.cursor() as cur:
        _upsert(cur, "factor_backtest_runs", ["backtest_id"], row)


def persist_factor_backtest_run(
    output_dir: str | Path,
    *,
    job_id: str | None = None,
    settings: MySQLSettings | None = None,
    conn=None,
) -> bool:
    """把一次批量因子回测的汇总 manifest 同步到 MySQL；未配置连接时返回 False。"""
    return _run_persist(
        settings,
        conn,
        lambda owned: _persist_factor_backtest_run_conn(owned, Path(output_dir), job_id),
    )


# ---------------------------------------------------------------------------
# 回测结果
# ---------------------------------------------------------------------------


def _backtest_run_key(manifest: Mapping[str, Any], run_name: str, run_dir: Path) -> str:
    """回测在 MySQL 中的唯一键。

    ``run_name`` 只是结果目录名，不同因子运行/股票池下可能重名（比如同一个因子
    表达式在两个池里回测都会得到 ``factor_0001_<hash>``），因此不能当主键。
    优先使用 ``save_result`` 写入的相对路径 ``run_key``；旧 manifest 没有该字段时
    按来源推导，最后退回结果目录的绝对路径，保证不会互相覆盖。
    """
    existing = _clean_text(manifest.get("run_key"), 512)
    if existing:
        return existing
    pool_id = _clean_text(manifest.get("pool_id"), 191)
    factor_run_id = _clean_text(manifest.get("factor_run_id"), 191)
    if factor_run_id:
        return _clean_text(f"factor/{pool_id or '_'}/{factor_run_id}/{run_name}", 512)
    if manifest.get("result_type") == "composite":
        return _clean_text(f"composite/{run_name}", 512)
    if manifest.get("result_type") == "manual":
        return _clean_text(f"manual/{run_name}", 512)
    try:
        return _clean_text(run_dir.resolve().as_posix(), 512)
    except OSError:  # pragma: no cover - 路径无法解析时才会触发
        return _clean_text(run_name, 512)


def _persist_backtest_conn(conn, run_dir: Path, run_key: str | None = None) -> None:
    manifest = _read_json(run_dir / "manifest.json")
    if not isinstance(manifest, dict):
        raise ValueError(f"backtest manifest missing or invalid: {run_dir / 'manifest.json'}")
    summary = _read_json(run_dir / "summary.json") or {}
    summary = summary if isinstance(summary, dict) else {}
    run_name = str(manifest.get("run_name") or run_dir.name)
    run_key = _clean_text(run_key, 512) or _backtest_run_key(manifest, run_name, run_dir)
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    created_at = _to_datetime(manifest.get("created_at"), run_dir / "manifest.json") or datetime.now()
    pool_id = manifest.get("pool_id") or config.get("pool_id")
    factor_run_id = manifest.get("factor_run_id") or config.get("factor_run_id")

    row = {
        "run_key": run_key,
        "run_name": run_name,
        "pool_id": _clean_text(pool_id, 191),
        "factor_run_id": _clean_text(factor_run_id, 191),
        "result_type": _clean_text(manifest.get("result_type"), 32),
        "canonical_expression": _clean_text(manifest.get("canonical_expression")),
        "created_at": created_at,
        "total_return": _to_float(summary.get("total_return")),
        "annual_return": _to_float(summary.get("annual_return")),
        "sharpe": _to_float(summary.get("sharpe")),
        "max_drawdown": _to_float(summary.get("max_drawdown")),
        "calmar": _to_float(summary.get("calmar")),
        "win_rate": _to_float(summary.get("win_rate")),
        "average_turnover": _to_float(summary.get("average_turnover")),
        "total_cost": _to_float(summary.get("total_cost")),
        "annual_cost": _to_float(summary.get("annual_cost")),
        "number_of_trades": _to_float(summary.get("number_of_trades")),
        "average_holding_count": _to_float(summary.get("average_holding_count")),
        "generation_metrics": _json_text(manifest.get("generation_metrics")),
        "summary": _json_text(summary),
        "config": _json_text(config),
        "manifest": _json_text(manifest),
    }

    components = manifest.get("components") or []
    component_rows = []
    for index, item in enumerate(components if isinstance(components, list) else []):
        if not isinstance(item, dict):
            continue
        component_rows.append(
            (
                run_key,
                index,
                _clean_text(item.get("factor_id"), 191),
                _clean_text(item.get("expression")),
                _to_float(item.get("weight")),
            )
        )

    daily_rows = []
    for item in _read_csv_rows(run_dir / "daily_report.csv"):
        trade_date = _to_date(item.get("date"))
        if trade_date is None:
            continue
        daily_rows.append(
            (
                run_key,
                trade_date,
                _to_float(item.get("account")),
                _to_float(item.get("return")),
                _to_float(item.get("cost")),
                _to_float(item.get("turnover")),
                _to_float(item.get("cash")),
                _to_float(item.get("stock_value")),
                _to_float(item.get("pnl")),
                _to_float(item.get("drawdown")),
                _to_int(item.get("trade_count")),
                _to_int(item.get("holding_count")),
            )
        )

    annual_rows = []
    for item in _read_csv_rows(run_dir / "annual_metrics.csv"):
        metric_year = _to_int(item.get("year"))
        if metric_year is None:
            continue
        annual_rows.append(
            (
                run_key,
                metric_year,
                _to_float(item.get("return")),
                _to_float(item.get("sharpe")),
                _to_float(item.get("max_drawdown")),
                _to_float(item.get("turnover")),
                _to_float(item.get("cost")),
                _to_float(item.get("win_rate")),
            )
        )

    trade_rows = []
    for item in _read_csv_rows(run_dir / "trades.csv"):
        trade_rows.append(
            (
                run_key,
                _to_date(item.get("date")),
                _clean_text(item.get("code"), 6),
                _clean_text(item.get("side"), 16),
                _to_float(item.get("price")),
                _to_float(item.get("shares")),
                _to_float(item.get("amount")),
                _to_float(item.get("cost")),
                _clean_text(item.get("reason"), 64),
            )
        )

    position_rows = []
    for item in _read_csv_rows(run_dir / "positions.csv"):
        position_date = _to_date(item.get("date"))
        code = _clean_text(item.get("code"), 6)
        if position_date is None or not code:
            continue
        position_rows.append(
            (
                run_key,
                position_date,
                code,
                _to_float(item.get("weight")),
                _to_float(item.get("shares")),
                _to_float(item.get("price")),
                _to_float(item.get("value")),
                _to_float(item.get("alpha")),
            )
        )

    with conn.cursor() as cur:
        _upsert(cur, "backtests", ["run_key"], row)
        cur.execute("DELETE FROM backtest_components WHERE run_key=%s", (run_key,))
        if component_rows:
            _batch_insert(
                cur,
                "INSERT INTO backtest_components (run_key, seq, factor_id, expression, weight) "
                "VALUES (%s, %s, %s, %s, %s)",
                component_rows,
            )
        cur.execute("DELETE FROM backtest_daily WHERE run_key=%s", (run_key,))
        if daily_rows:
            _batch_insert(
                cur,
                "INSERT INTO backtest_daily (run_key, trade_date, account, daily_return, cost, "
                "turnover, cash, stock_value, pnl, drawdown, trade_count, holding_count) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                daily_rows,
            )
        cur.execute("DELETE FROM backtest_annual WHERE run_key=%s", (run_key,))
        if annual_rows:
            _batch_insert(
                cur,
                "INSERT INTO backtest_annual (run_key, metric_year, annual_return, sharpe, "
                "max_drawdown, turnover, cost, win_rate) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                annual_rows,
            )
        cur.execute("DELETE FROM backtest_trades WHERE run_key=%s", (run_key,))
        if trade_rows:
            _batch_insert(
                cur,
                "INSERT INTO backtest_trades (run_key, trade_date, code, side, price, shares, "
                "amount, cost, reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                trade_rows,
            )
        cur.execute("DELETE FROM backtest_positions WHERE run_key=%s", (run_key,))
        if position_rows:
            _batch_insert(
                cur,
                "INSERT INTO backtest_positions (run_key, position_date, code, weight, shares, "
                "price, position_value, alpha) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                position_rows,
            )


def persist_backtest(
    run_dir: str | Path,
    *,
    run_key: str | None = None,
    settings: MySQLSettings | None = None,
    conn=None,
) -> bool:
    """把单个回测结果目录同步到 MySQL；未配置连接时返回 False。"""
    return _run_persist(
        settings,
        conn,
        lambda owned: _persist_backtest_conn(owned, Path(run_dir), run_key),
    )


# ---------------------------------------------------------------------------
# 批量同步
# ---------------------------------------------------------------------------


def sync_all(
    *,
    pools_root: str | Path | None = None,
    factor_runs_root: str | Path | None = None,
    outputs_root: str | Path | None = None,
    settings: MySQLSettings | None = None,
) -> Dict[str, Any]:
    """把现有本地股票池 / 因子运行 / 回测结果全量补录到 MySQL。"""
    settings = settings or load_settings()
    if settings is None:
        raise RuntimeError(
            "MySQL 未配置：请设置 QL_MYSQL_HOST/QL_MYSQL_USER/QL_MYSQL_DATABASE，"
            f"或填写 {DEFAULT_ENV_FILE}"
        )
    pools_root = Path(pools_root or PROJECT_ROOT / "data_cache" / "pools")
    # 与 configs/factor_generation.yaml（../factor_runs）保持一致；旧布局可显式传参
    factor_runs_root = Path(factor_runs_root or PROJECT_ROOT.parent / "factor_runs")
    outputs_root = Path(outputs_root or PROJECT_ROOT / "outputs" / "saved_backtests")

    report: Dict[str, Any] = {
        "pools": 0,
        "factor_runs": 0,
        "factor_backtests": 0,
        "backtests": 0,
        "errors": [],
    }

    if pools_root.is_dir():
        for pool_dir in sorted(path for path in pools_root.iterdir() if path.is_dir()):
            if not (pool_dir / "manifest.json").is_file():
                continue
            try:
                if persist_pool(pool_dir, settings=settings):
                    report["pools"] += 1
            except Exception as exc:
                report["errors"].append({"kind": "pool", "path": str(pool_dir), "error": f"{type(exc).__name__}: {exc}"})

    if factor_runs_root.is_dir():
        for run_dir in sorted(path for path in factor_runs_root.iterdir() if path.is_dir()):
            if not (run_dir / "factor_run.json").is_file():
                continue
            try:
                if persist_factor_run(run_dir, settings=settings):
                    report["factor_runs"] += 1
            except Exception as exc:
                report["errors"].append({"kind": "factor_run", "path": str(run_dir), "error": f"{type(exc).__name__}: {exc}"})

    if outputs_root.is_dir():
        for manifest_path in sorted(outputs_root.rglob("manifest.json")):
            run_dir = manifest_path.parent
            if not (run_dir / "summary.json").is_file() or not (run_dir / "daily_report.csv").is_file():
                continue
            try:
                try:
                    run_key = run_dir.resolve().relative_to(outputs_root.resolve()).as_posix()
                except ValueError:  # pragma: no cover - rglob 结果应总在根目录下
                    run_key = None
                if persist_backtest(run_dir, run_key=run_key, settings=settings):
                    report["backtests"] += 1
            except Exception as exc:
                report["errors"].append({"kind": "backtest", "path": str(run_dir), "error": f"{type(exc).__name__}: {exc}"})

        for manifest_path in sorted(outputs_root.rglob("factor_backtest_manifest.json")):
            batch_dir = manifest_path.parent
            try:
                if persist_factor_backtest_run(batch_dir, settings=settings):
                    report["factor_backtests"] += 1
            except Exception as exc:
                report["errors"].append(
                    {"kind": "factor_backtest", "path": str(batch_dir), "error": f"{type(exc).__name__}: {exc}"}
                )

    report["settings"] = settings.summary()
    return report


def check_connection(settings: MySQLSettings | None = None) -> Dict[str, Any]:
    """连接并返回版本、表数量与各表行数，用于启动前自检。"""
    settings = settings or load_settings()
    if settings is None:
        raise RuntimeError("MySQL 未配置")
    with _connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS version")
            version = cur.fetchone()["version"]
            counts: Dict[str, int] = {}
            for table in table_names():
                cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                counts[table] = int(cur.fetchone()["n"])
    return {"settings": settings.summary(), "version": version, "tables": counts}


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="QuantLab MySQL 持久化工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="创建/校验表结构")
    sub.add_parser("check", help="连接自检并打印各表行数")
    p_sync = sub.add_parser("sync", help="把本地股票池/因子运行/回测结果补录到 MySQL")
    p_sync.add_argument("--pools-root", default=None)
    p_sync.add_argument("--factor-runs-root", default=None)
    p_sync.add_argument("--outputs-root", default=None)
    args = parser.parse_args(argv)

    settings = load_settings()
    if settings is None:
        raise SystemExit(f"MySQL 未配置：请设置环境变量或填写 {DEFAULT_ENV_FILE}")
    if args.command == "schema":
        with _connection(settings) as conn:
            ensure_schema(conn)
        print(json.dumps({"ok": True, "settings": settings.summary(), "tables": table_names()}, ensure_ascii=False, indent=2))
    elif args.command == "check":
        print(json.dumps(check_connection(settings), ensure_ascii=False, indent=2, default=str))
    elif args.command == "sync":
        print(
            json.dumps(
                sync_all(
                    pools_root=args.pools_root,
                    factor_runs_root=args.factor_runs_root,
                    outputs_root=args.outputs_root,
                    settings=settings,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
