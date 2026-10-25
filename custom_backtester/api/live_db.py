"""ClickHouse 实时数据源：只读 HTTP 客户端 + 进程内 TTL 缓存。

服务 api/main.py 的展示端点（数据总览 / 数据字段 / 股票列表）与股票池候选
（/api/universe/*）：候选股票、行业与上市信息来自公司库，但建池、因子与回测
仍走本地 data_cache 主缓存。

约定：
- 纯标准库（urllib），不引入新依赖；不 import fastapi（异常由 main.py 映射成 HTTP 状态码）。
- 只读：SQL 全部是模块常量，且都要过 guard_readonly 白名单（前缀 + 关键字黑名单）。
- 凭据：环境变量 QL_CH_* 优先，其次 configs/clickhouse.local.env（已 gitignore）。
  错误消息与日志里绝不出现密码。
- 数值：ClickHouse 的 JSONEachRow 默认把 64 位整数输出成带引号的字符串，Decimal 走
  浮点有精度风险 —— 因此 SQL 一律显式 toString()，Python 侧用 Decimal 转换
  （to_int / to_float）。
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from custom_bt.data import normalize_code  # 复用：代码统一成 6 位字符串

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / "configs" / "clickhouse.local.env"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8123
DEFAULT_USER = "default"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_EXECUTION_TIME = 20
DEFAULT_MAX_MEMORY = 1_000_000_000
DEFAULT_CACHE_TTL = 60.0
DEFAULT_SCHEMA_TTL = 300.0
# 股票池候选快照：部署里 QL_CH_CACHE_TTL=0 时，筛选预览也不能每次都打 3.5s 聚合
DEFAULT_UNIVERSE_TTL = 300.0

DAILY_DB = "dws"
DAILY_NAME = "ll_stock_daily_sharing"
DIM_DB = "dim"
DIM_NAME = "stock_main_info_fd"
DAILY_TABLE = f"{DAILY_DB}.{DAILY_NAME}"
DIM_TABLE = f"{DIM_DB}.{DIM_NAME}"

# 「可用字段」口径：行标识列不作为可用字段列出（与本地 meta.json 口径一致）
_CATALOG_EXCLUDED = {"code", "timestamps"}
# dim 表随行情一起展示 / 进面板的 4 列（ChiNameAbbr 供股票名称列）
_DIM_FIELDS = ("ListedDate", "ListedSector", "ListedState", "ChiNameAbbr")
# 数据库列名 → 回测面板字段名（与 custom_bt.docs.FIELD_ALIASES 反向对应）
_PANEL_ALIASES = {"vol": "volume"}
# 字段说明文档里的来源名 → 真实数据库表名
_SOURCE_RELABEL = {
    "last_5years_daily": DAILY_TABLE,
    "stock_main_info_fd": DIM_TABLE,
}


class LiveDBError(RuntimeError):
    """实时数据源相关错误的基类。"""


class LiveDBConfigError(LiveDBError):
    """未配置（缺密码等）。"""


class LiveDBUnavailable(LiveDBError):
    """连不上 / 认证失败 / 超时。"""


class LiveDBQueryError(LiveDBError):
    """连上了但查询本身失败。"""


# ---------- SQL（全部为模块常量，任何请求参数都不拼进来） ----------

SQL_MASTER_STATS = f"""
SELECT
    toString(count()) AS rows,
    toString(uniqExact(code)) AS n_stocks,
    min(timestamps) AS date_min,
    max(timestamps) AS date_max
FROM {DAILY_TABLE}
WHERE category = 'stock'
"""

# 注意：不要写 toString(position) AS position —— 别名会把 ORDER BY position 解析成
# 字符串列，字段顺序会变成字典序（1, 10, 11, …, 2, 20 …）。position 只用于排序。
SQL_DAILY_COLUMNS = f"""
SELECT name, type, comment
FROM system.columns
WHERE database = '{DAILY_DB}' AND table = '{DAILY_NAME}'
ORDER BY position
"""

SQL_DIM_COLUMNS = f"""
SELECT name, type, comment
FROM system.columns
WHERE database = '{DIM_DB}' AND table = '{DIM_NAME}'
ORDER BY position
"""

SQL_STOCK_ROWS = f"""
SELECT
    code,
    toString(count()) AS rows,
    min(timestamps) AS start_date,
    max(timestamps) AS end_date,
    toString(argMax(close, timestamps)) AS latest_close,
    toString(argMax(vol, timestamps)) AS latest_volume,
    toString(argMax(amount, timestamps)) AS latest_amount,
    toString(argMax(Ifsuspend, timestamps)) AS latest_ifsuspend
FROM {DAILY_TABLE}
WHERE category = 'stock'
GROUP BY code
ORDER BY code
"""

# dim 表：名称 + 单级行业 + 上市信息。日期/数值列统一 toString，避免类型差异。
# 注意：Industry 是细分行业编码（实测 337 个取值，如 60103483），不是单级行业；
# 单级行业取 FirstIndustryName（申万一级，实测 31 类），代码为 FirstIndustryCode。
SQL_DIM_PROFILES = f"""
SELECT
    toString(SecuCode) AS code,
    ChiNameAbbr AS name,
    FirstIndustryName AS industry,
    FirstIndustryCode AS industry_code,
    toString(ListedSector) AS sector,
    toString(ListedState) AS listed_state,
    toString(ListedDate) AS listed_date
FROM {DIM_TABLE}
"""

# ---------- 只读护栏 ----------

_ALLOWED_PREFIXES = ("SELECT", "WITH", "DESCRIBE", "SHOW", "EXPLAIN")
# 双保险：即使前缀是 SELECT / WITH，也不允许出现写操作关键字（如 WITH ... INSERT）
_FORBIDDEN_KEYWORDS = (
    "INSERT", "ALTER", "DROP", "CREATE", "DELETE", "TRUNCATE", "RENAME",
    "ATTACH", "DETACH", "OPTIMIZE", "KILL", "UPDATE", "EXCHANGE", "MOVE",
    "GRANT", "REVOKE", "OUTFILE", "DUMP",
)


def guard_readonly(sql: str) -> str:
    """只读白名单：前缀必须是查询类，且不含写操作关键字；返回去分号后的语句。"""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise LiveDBQueryError("空查询")
    upper = statement.upper()
    if not upper.startswith(_ALLOWED_PREFIXES):
        raise LiveDBQueryError("只允许只读查询（SELECT / WITH / DESCRIBE / SHOW / EXPLAIN）")
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise LiveDBQueryError(f"查询包含被禁止的关键字 {keyword}")
    return statement


# ---------- 配置 ----------


@dataclass(frozen=True)
class LiveDBSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    user: str = DEFAULT_USER
    password: str = ""
    timeout: float = DEFAULT_TIMEOUT
    max_execution_time: int = DEFAULT_MAX_EXECUTION_TIME
    max_memory_usage: int = DEFAULT_MAX_MEMORY
    cache_ttl: float = DEFAULT_CACHE_TTL
    schema_ttl: float = DEFAULT_SCHEMA_TTL
    universe_ttl: float = DEFAULT_UNIVERSE_TTL

    @property
    def display(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/"


def _as_int(value: Any, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return default


def _as_float(value: Any, default: float) -> float:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def load_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    """读取 KEY=VALUE 形式的本地环境文件；文件不存在返回空字典。

    用 utf-8-sig 解码：Windows 记事本另存为 UTF-8 会带 BOM，BOM 会让第一个键名
    变成 "\\ufeffQL_CH_HOST" 而静默失效。
    """
    env_path = Path(path) if path is not None else DEFAULT_ENV_FILE
    if not env_path.is_file():
        return {}
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def resolve_settings(
    env_file: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> LiveDBSettings:
    """合并配置：本地环境文件 < 进程环境变量（QL_CH_*）；缺密码直接报错。"""
    merged: Dict[str, str] = dict(load_env_file(env_file))
    process_values = os.environ if environ is None else environ
    for key, value in process_values.items():
        if key.startswith("QL_CH_") and str(value).strip():
            merged[key] = str(value).strip()

    password = merged.get("QL_CH_PASSWORD", "").strip()
    if not password:
        raise LiveDBConfigError(
            "未配置 ClickHouse 密码：请设置环境变量 QL_CH_PASSWORD，"
            "或在 configs/clickhouse.local.env 中填写（该文件已被 .gitignore 忽略）"
        )

    return LiveDBSettings(
        host=merged.get("QL_CH_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
        port=_as_int(merged.get("QL_CH_PORT"), DEFAULT_PORT),
        user=merged.get("QL_CH_USER", DEFAULT_USER).strip() or DEFAULT_USER,
        password=password,
        timeout=_as_float(merged.get("QL_CH_TIMEOUT"), DEFAULT_TIMEOUT),
        max_execution_time=_as_int(
            merged.get("QL_CH_MAX_EXECUTION_TIME"), DEFAULT_MAX_EXECUTION_TIME
        ),
        max_memory_usage=_as_int(merged.get("QL_CH_MAX_MEMORY"), DEFAULT_MAX_MEMORY),
        cache_ttl=_as_float(merged.get("QL_CH_CACHE_TTL"), DEFAULT_CACHE_TTL),
        schema_ttl=_as_float(merged.get("QL_CH_SCHEMA_TTL"), DEFAULT_SCHEMA_TTL),
        universe_ttl=_as_float(merged.get("QL_CH_UNIVERSE_TTL"), DEFAULT_UNIVERSE_TTL),
    )


# ---------- 数值 / 类型转换 ----------


def to_int(value: Any) -> Optional[int]:
    """把 JSONEachRow 的数值列（toString 后的字符串）转成 int；空值 / 非法返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError):
        return None


def to_float(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError):
        return None


def _short_type(raw: Any) -> str:
    """把 ClickHouse 类型压成适合表格展示的形式：Nullable(X) → X?。"""
    text = re.sub(r",\s*", ",", str(raw or "").strip())
    match = re.fullmatch(r"Nullable\((.+)\)", text, flags=re.DOTALL)
    if match:
        return _short_type(match.group(1)) + "?"
    return text


# ---------- 股票画像 / 代码分类 ----------

_EXCHANGE_LABELS = {"SH": "沪市", "SZ": "深市", "BJ": "北交所", "OTHER": "其他"}
_EXCHANGE_ORDER = ("SH", "SZ", "BJ", "OTHER")
_BOARD_ORDER = ("沪市主板", "深市主板", "创业板", "科创板", "北交所", "其他")

# A 股代码前缀（不依赖 market_code：本地缓存里它是数据商标识「新华财经」）
_SH_MAIN_PREFIXES = ("600", "601", "603", "605")
_SH_STAR_PREFIXES = ("688", "689")
_SZ_MAIN_PREFIXES = ("000", "001", "002", "003")
_SZ_CHINEXT_PREFIXES = ("300", "301")
_BJ_PREFIXES = ("43", "83", "87", "88", "92")

_LISTED_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _clean_text(value: Any) -> Optional[str]:
    """库内字符串清洗：空串 / JSON null / 字面量 null 统一成 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null", "\\n"}:
        return None
    return text


def parse_listed_date(value: Any) -> Optional[str]:
    """把 Date / DateTime / 字符串统一成 ``YYYY-MM-DD``；无法解析返回 None。"""
    text = _clean_text(value)
    if not text:
        return None
    match = _LISTED_DATE_RE.match(text)
    if not match:
        return None
    candidate = match.group(1)
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _date_from_value(value: Any) -> Optional[date]:
    text = parse_listed_date(value)
    return date.fromisoformat(text) if text else None


def exchange_for_code(value: Any) -> str:
    """由代码前缀推导交易所（SH/SZ/BJ/OTHER）；market_code 不可靠，不用它。"""
    code = normalize_code(value)
    if not code:
        return "OTHER"
    if code.startswith(_SH_MAIN_PREFIXES + _SH_STAR_PREFIXES + ("900",)):
        return "SH"
    if code.startswith(_SZ_MAIN_PREFIXES + _SZ_CHINEXT_PREFIXES + ("200",)):
        return "SZ"
    if code.startswith(_BJ_PREFIXES):
        return "BJ"
    return "OTHER"


def board_for_code(value: Any) -> str:
    """由代码前缀推导上市板块；未知/非 A 股代码归入「其他」。"""
    code = normalize_code(value)
    if not code:
        return "其他"
    if code.startswith(_SH_STAR_PREFIXES):
        return "科创板"
    if code.startswith(_SZ_CHINEXT_PREFIXES):
        return "创业板"
    if code.startswith(_SH_MAIN_PREFIXES):
        return "沪市主板"
    if code.startswith(_SZ_MAIN_PREFIXES):
        return "深市主板"
    if code.startswith(_BJ_PREFIXES):
        return "北交所"
    return "其他"


def parse_json_each_row(body: str) -> List[Dict[str, Any]]:
    """解析 FORMAT JSONEachRow 响应；空行跳过，坏行直接报错（数据完整性）。"""
    rows: List[Dict[str, Any]] = []
    for line in body.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            raise LiveDBQueryError(f"ClickHouse 返回了无法解析的行：{text[:120]}") from None
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


# ---------- HTTP 客户端 ----------


class ClickHouseHTTPClient:
    """POST SQL 到 ClickHouse HTTP 接口，返回 JSONEachRow 解析后的行列表。"""

    def __init__(self, settings: LiveDBSettings, opener: Any = None) -> None:
        self.settings = settings
        # 显式禁用系统代理：HTTP_PROXY 会让内网地址（172.29.x.x）的请求被代理劫持
        self._opener = opener if opener is not None else urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def query(self, sql: str) -> List[Dict[str, Any]]:
        statement = guard_readonly(sql)
        settings = self.settings
        params = urllib.parse.urlencode(
            {
                "default_format": "JSONEachRow",
                "max_execution_time": settings.max_execution_time,
                "max_memory_usage": settings.max_memory_usage,
            }
        )
        request = urllib.request.Request(
            f"{settings.endpoint}?{params}",
            data=statement.encode("utf-8"),
            method="POST",
        )
        request.add_header("Content-Type", "text/plain; charset=utf-8")
        # 密码只走 Basic 认证头，不放 URL（URL 会进日志 / 报错信息）
        token = base64.b64encode(
            f"{settings.user}:{settings.password}".encode("utf-8")
        ).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
        return parse_json_each_row(self._send(request))

    def _send(self, request: urllib.request.Request) -> str:
        settings = self.settings
        last_error: Optional[BaseException] = None
        for attempt in (1, 2):
            try:
                with self._opener.open(request, timeout=settings.timeout) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                # HTTPError 是 URLError 的子类，必须先捕获；超时与 4xx/5xx 不重试
                raise self._http_error(exc) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", None) or exc
                if isinstance(reason, TimeoutError) or "timed out" in str(exc).lower():
                    raise LiveDBUnavailable(
                        f"ClickHouse 查询超时（{settings.display}，超过 {settings.timeout:.0f} 秒）"
                    ) from None
                last_error = exc
                if attempt == 1:
                    time.sleep(0.5)  # 连接类失败重试一次（瞬时抖动 / 服务刚启动）
                    continue
        raise LiveDBUnavailable(
            f"无法连接 ClickHouse {settings.display}（{self._redact(str(last_error))}）；"
            "实时数据需要在公司网络环境下访问"
        ) from None

    def _http_error(self, exc: urllib.error.HTTPError) -> LiveDBError:
        detail = self._redact(_read_error_body(exc))[:200]
        if exc.code in (401, 403):
            return LiveDBUnavailable(
                f"ClickHouse 认证失败（HTTP {exc.code}）：请检查 QL_CH_USER / QL_CH_PASSWORD"
            )
        if exc.code in (502, 503, 504):
            return LiveDBUnavailable(f"ClickHouse 服务不可用（HTTP {exc.code}）：{detail}")
        return LiveDBQueryError(f"ClickHouse 查询失败（HTTP {exc.code}）：{detail}")

    def _redact(self, text: str) -> str:
        password = self.settings.password
        if not password:
            return text
        return text.replace(password, "***")


# ---------- TTL 缓存（key 级 single-flight） ----------

_cache_guard = threading.Lock()
_cache_key_locks: Dict[str, threading.Lock] = {}
_cache_values: Dict[str, Tuple[float, str, Any]] = {}
# 每个 key 已完成的真查询次数：等待锁的请求据此判断"我等的这段时间里别人查完了"。
# 不用时间戳比较，因为 Windows 上 time.monotonic() 只有约 15ms 分辨率，
# 同一瞬间的调用会拿到相同时间戳，串行请求会被误判成并发。
_cache_generation: Dict[str, int] = {}


class LiveResult:
    """一次业务查询的结果：数据本身 + 是否命中缓存 + 数据对应的查询时刻。"""

    __slots__ = ("data", "cached", "queried_at")

    def __init__(self, data: Any, cached: bool, queried_at: str) -> None:
        self.data = data
        self.cached = cached
        self.queried_at = queried_at


def _key_lock(key: str) -> threading.Lock:
    with _cache_guard:
        lock = _cache_key_locks.get(key)
        if lock is None:
            lock = _cache_key_locks[key] = threading.Lock()
        return lock


def clear_cache() -> None:
    """清空 TTL 缓存（测试用）。"""
    with _cache_guard:
        _cache_values.clear()
        _cache_generation.clear()


def _cached(key: str, ttl: float, produce: Callable[[], Any]) -> LiveResult:
    """进程内 TTL 缓存 + key 级 single-flight。

    ttl > 0：按 TTL 复用结果。
    ttl <= 0（QL_CH_CACHE_TTL=0，本部署默认）：**不缓存结果**，每次调用都真查库；
    但同一瞬间的并发重复请求仍会合流——若在本次调用等待锁期间别的线程查完了，
    直接采用它的结果（等价于自己刚查完，不会拿到旧数据）。React.StrictMode 开发态
    对每个页面发两次请求，不合流的话 3.5 秒的全市场聚合会白打两遍。
    调用方应把返回的 data 当只读用（复用时拿到的是同一个对象）。
    """
    entry = _cache_values.get(key)
    if entry is not None and ttl > 0 and time.monotonic() - entry[0] < ttl:
        return LiveResult(entry[2], True, entry[1])
    seen = _cache_generation.get(key)  # 进锁前记下当前代数
    with _key_lock(key):
        entry = _cache_values.get(key)
        within_ttl = entry is not None and ttl > 0 and time.monotonic() - entry[0] < ttl
        joined = entry is not None and _cache_generation.get(key) != seen
        if entry is not None and (within_ttl or joined):
            return LiveResult(entry[2], within_ttl, entry[1])
        data = produce()
        queried_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _cache_values[key] = (time.monotonic(), queried_at, copy.deepcopy(data))
        _cache_generation[key] = _cache_generation.get(key, 0) + 1
        return LiveResult(data, False, queried_at)


# ---------- 业务查询 ----------


def _client(
    settings: LiveDBSettings, client: Optional[ClickHouseHTTPClient] = None
) -> ClickHouseHTTPClient:
    return client if client is not None else ClickHouseHTTPClient(settings)


def live_master_stats(
    settings: Optional[LiveDBSettings] = None,
    client: Optional[ClickHouseHTTPClient] = None,
) -> LiveResult:
    """全市场行数 / 股票数 / 日期区间（实测约 2.3 秒）。"""
    settings = settings or resolve_settings()
    client = _client(settings, client)

    def produce() -> Dict[str, Any]:
        rows = client.query(SQL_MASTER_STATS)
        row = rows[0] if rows else {}
        return {
            "rows": to_int(row.get("rows")),
            "n_stocks": to_int(row.get("n_stocks")),
            "date_min": row.get("date_min") or None,
            "date_max": row.get("date_max") or None,
        }

    return _cached("master_stats", settings.cache_ttl, produce)


def _catalog_entry(row: Mapping[str, Any], table: str) -> Dict[str, Any]:
    return {
        "name": str(row.get("name", "")).strip(),
        "dtype": _short_type(row.get("type")),
        "comment": str(row.get("comment") or "").strip(),
        "table": table,
    }


def live_field_catalog(
    settings: Optional[LiveDBSettings] = None,
    client: Optional[ClickHouseHTTPClient] = None,
) -> LiveResult:
    """「可用字段」清单：行情表全列（排除 code / timestamps）+ dim 表的 4 个字段。

    数据总览与数据字段两个端点共用这一份结果，两页数字因此不可能不一致。
    """
    settings = settings or resolve_settings()
    client = _client(settings, client)

    def produce() -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for row in client.query(SQL_DAILY_COLUMNS):
            name = str(row.get("name", "")).strip()
            if not name or name in _CATALOG_EXCLUDED:
                continue
            entries.append(_catalog_entry(row, DAILY_TABLE))
        for row in client.query(SQL_DIM_COLUMNS):
            name = str(row.get("name", "")).strip()
            if name in _DIM_FIELDS:
                entries.append(_catalog_entry(row, DIM_TABLE))
        return entries

    return _cached("field_catalog", settings.schema_ttl, produce)


def live_dim_profiles(
    settings: Optional[LiveDBSettings] = None,
    client: Optional[ClickHouseHTTPClient] = None,
) -> LiveResult:
    """code → 名称 / 单级行业（FirstIndustryName）/ 上市板块、状态、日期。

    ``industry`` 用申万一级名称（如「银行」），而不是 dim.Industry 的细分行业
    编码；``industry_code`` 保留一级行业代码以便追溯。
    """
    settings = settings or resolve_settings()
    client = _client(settings, client)

    def produce() -> Dict[str, Dict[str, Any]]:
        profiles: Dict[str, Dict[str, Any]] = {}
        for row in client.query(SQL_DIM_PROFILES):
            code = normalize_code(row.get("code", ""))
            if not code:
                continue
            profiles[code] = {
                "name": _clean_text(row.get("name")),
                "industry": _clean_text(row.get("industry")),
                "industry_code": _clean_text(row.get("industry_code")),
                "sector": _clean_text(row.get("sector")),
                "listed_state": _clean_text(row.get("listed_state")),
                "listed_date": parse_listed_date(row.get("listed_date")),
            }
        return profiles

    return _cached("dim_profiles", settings.schema_ttl, produce)


def live_stock_rows(
    settings: Optional[LiveDBSettings] = None,
    client: Optional[ClickHouseHTTPClient] = None,
) -> LiveResult:
    """每只股票：行情聚合 + 名称/行业/上市信息 + 市场/板块（实测约 3.5 秒）。

    结果同时供股票列表页与股票池候选使用；缓存时间用 universe_ttl（默认 300s），
    避免筛选预览在 QL_CH_CACHE_TTL=0 的部署里反复打全市场聚合。
    """
    settings = settings or resolve_settings()
    client = _client(settings, client)

    def produce() -> List[Dict[str, Any]]:
        profiles = live_dim_profiles(settings, client).data
        items: List[Dict[str, Any]] = []
        for row in client.query(SQL_STOCK_ROWS):
            code = normalize_code(row.get("code", ""))
            if not code:
                continue
            profile = profiles.get(code) or {}
            end_date = str(row.get("end_date") or "")
            exchange = exchange_for_code(code)
            board = board_for_code(code)
            items.append(
                {
                    "code": code,
                    "name": profile.get("name"),
                    "industry": profile.get("industry"),
                    "industry_code": profile.get("industry_code"),
                    "sector": profile.get("sector"),
                    "listed_state": profile.get("listed_state"),
                    "listed_date": profile.get("listed_date"),
                    "exchange": exchange,
                    "exchange_label": _EXCHANGE_LABELS[exchange],
                    "board": board,
                    "board_label": board,
                    "rows": to_int(row.get("rows")) or 0,
                    "start_date": str(row.get("start_date") or ""),
                    "end_date": end_date,
                    "latest_date": end_date,
                    "latest_close": to_float(row.get("latest_close")),
                    "latest_volume": to_int(row.get("latest_volume")),
                    "latest_amount": to_float(row.get("latest_amount")),
                    "latest_ifsuspend": to_int(row.get("latest_ifsuspend")),
                }
            )
        return items

    return _cached("stock_rows", settings.universe_ttl, produce)


def filter_universe(
    items: Iterable[Mapping[str, Any]],
    *,
    industries: Iterable[str] = (),
    exchanges: Iterable[str] = (),
    boards: Iterable[str] = (),
    sectors: Iterable[str] = (),
    listed_states: Iterable[str] = (),
    q: str = "",
    min_listed_days: int = 0,
    as_of: Any = None,
) -> List[Dict[str, Any]]:
    """按行业/市场/板块/库内原始值/关键词/上市天数筛选候选股票。

    停牌不在这一层过滤：``create_pool`` 会按整段窗口逐行剔除停牌记录，
    只按「最新一条是否停牌」筛候选会错误地把窗口内正常交易的股票排除掉。
    空列表表示该条件不生效；返回浅拷贝并按最新成交额降序、代码升序排序。
    """
    industry_set = {value for value in (str(item).strip() for item in industries) if value}
    exchange_set = {value.upper() for value in (str(item).strip() for item in exchanges) if value}
    board_set = {value for value in (str(item).strip() for item in boards) if value}
    sector_set = {value for value in (str(item).strip() for item in sectors) if value}
    state_set = {value for value in (str(item).strip() for item in listed_states) if value}
    keyword = str(q or "").strip().lower()

    as_of_date = _date_from_value(as_of) if as_of else None
    if min_listed_days > 0 and as_of_date is None:
        raise ValueError("as_of is required when min_listed_days > 0")

    selected: List[Dict[str, Any]] = []
    for item in items:
        if industry_set and item.get("industry") not in industry_set:
            continue
        if exchange_set and str(item.get("exchange") or "").upper() not in exchange_set:
            continue
        if board_set and item.get("board") not in board_set:
            continue
        if sector_set and item.get("sector") not in sector_set:
            continue
        if state_set and item.get("listed_state") not in state_set:
            continue
        if keyword:
            code = str(item.get("code") or "").lower()
            name = str(item.get("name") or "").lower()
            if keyword not in code and keyword not in name:
                continue
        if min_listed_days > 0:
            listed = _date_from_value(item.get("listed_date"))
            if listed is None or (as_of_date - listed).days < min_listed_days:
                continue
        selected.append(dict(item))

    selected.sort(
        key=lambda item: (
            -(item.get("latest_amount") or 0.0),
            str(item.get("code") or ""),
        )
    )
    return selected


def aggregate_universe(
    items: Iterable[Mapping[str, Any]], master_codes: Iterable[str]
) -> Dict[str, Any]:
    """全库 facet 分布 + 本地主缓存覆盖统计（供 /api/universe/options）。"""
    item_list = list(items)
    master_set = {normalize_code(code) for code in master_codes}
    creatable_total = sum(1 for item in item_list if item.get("code") in master_set)

    def _counts(key: str) -> Tuple[Counter, int]:
        counts: Counter = Counter()
        missing = 0
        for item in item_list:
            value = _clean_text(item.get(key))
            if value is None:
                missing += 1
            else:
                counts[value] += 1
        return counts, missing

    industry_counts, missing_industry = _counts("industry")
    exchange_counts, missing_exchange = _counts("exchange")
    board_counts, missing_board = _counts("board")
    sector_counts, missing_sector = _counts("sector")
    state_counts, missing_state = _counts("listed_state")
    _, missing_listed_date = _counts("listed_date")

    industries = [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(industry_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    exchanges = [
        {"value": key, "label": _EXCHANGE_LABELS[key], "count": exchange_counts[key]}
        for key in _EXCHANGE_ORDER
        if exchange_counts.get(key)
    ]
    boards = [
        {"value": key, "label": key, "count": board_counts[key]}
        for key in _BOARD_ORDER
        if board_counts.get(key)
    ]
    sectors = [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(sector_counts.items(), key=lambda pair: (len(pair[0]), pair[0]))
    ]
    listed_states = [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(state_counts.items(), key=lambda pair: (len(pair[0]), pair[0]))
    ]

    return {
        "total": len(item_list),
        "industries": industries,
        "exchanges": exchanges,
        "boards": boards,
        "sectors": sectors,
        "listed_states": listed_states,
        "missing": {
            "industry": missing_industry,
            "exchange": missing_exchange,
            "board": missing_board,
            "sector": missing_sector,
            "listed_state": missing_state,
            "listed_date": missing_listed_date,
        },
        "master_total": len(master_set),
        "creatable_total": creatable_total,
        "excluded_total": len(item_list) - creatable_total,
    }


# ---------- 展示辅助 ----------


def source_label(doc_source: str, table: str) -> str:
    """字段说明文档里的来源名 → 真实数据库表名（文档没有时退回所属表）。"""
    source = (doc_source or "").strip()
    if source in _SOURCE_RELABEL:
        return _SOURCE_RELABEL[source]
    return source or table


def panel_alias(name: str) -> str:
    """数据库列名 → 回测面板字段名（vol → volume）。"""
    return _PANEL_ALIASES.get(name, name)


def target_label(settings: Optional[LiveDBSettings] = None) -> str:
    """给前端展示的数据源标识，例如 host:8123 · dws.ll_stock_daily_sharing。"""
    settings = settings or resolve_settings()
    return f"{settings.display} · {DAILY_TABLE}"


def prewarm() -> None:
    """启动时后台预热 3 个缓存 key（best-effort：任何失败都静默）。

    没配密码 / 不在公司网络时不打扰：端点自己会返回可读的错误。
    QL_CH_PREWARM=0 可关闭。
    """
    if str(os.environ.get("QL_CH_PREWARM", "1")).strip().lower() in ("0", "false", "no"):
        return

    def _run() -> None:
        try:
            settings = resolve_settings()
        except LiveDBConfigError:
            return
        for loader in (live_master_stats, live_field_catalog, live_stock_rows):
            try:
                loader(settings)
            except LiveDBError:
                pass

    threading.Thread(target=_run, name="live-db-prewarm", daemon=True).start()
