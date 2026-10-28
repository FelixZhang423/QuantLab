"""公司 ClickHouse 数据源：股票池选样、因子面板与回测共用。

股票池、因子生成和因子回测都不再依赖 ``data_cache/master``：候选、窗口内
有效行数/成交额、因子面板和回测面板全部直接从公司库读取。

约定：
- 只读。SQL 由本模块拼接，代码/日期都经过规范化与转义，再交给
  :func:`api.live_db.guard_readonly` 二次校验。
- 凭据只来自环境变量或 ``configs/clickhouse.local.env``；错误信息里不出现密码。
- 大结果走 ``FORMAT Parquet`` 流式落盘（``ClickHouseHTTPClient.query_to_file``），
  避免 JSONEachRow 解析几百万行。
- ClickHouse 的 Parquet 输出把 Date / DateTime 写成无逻辑类型的整数（Days / 秒），
  写因子面板时统一重写成 Arrow timestamp，确保 ``single_factor`` 的日期过滤可用。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from api import live_db
from custom_bt.data import normalize_code

# 逻辑数据源签名：所有公司库池/因子运行共用；本地缓存池使用内容哈希，两者不会混用。
SOURCE_SIGNATURE = "clickhouse:dws.ll_stock_daily_sharing"

_COMPANY_ALIASES = {"clickhouse", "company", "live"}


def is_company_source(value: Any) -> bool:
    return str(value or "").strip().lower() in _COMPANY_ALIASES


def resolve_data_source(
    requested: Any = None, manifest: Optional[Mapping[str, Any]] = None
) -> str:
    """显式参数 > 池/运行 manifest 里的 data_source > 本地（兼容旧数据）。"""
    value = requested
    if not str(value or "").strip() and manifest:
        value = manifest.get("data_source")
    return "clickhouse" if is_company_source(value) else "local"

# 与本地 data_cache/master 面板字段一一对应（不含 date / code）。
# 因子生成配置里的 38 个字段是它的子集；回测面板默认加载这一整组，保证表达式
# 在切换数据源后仍能解析到相同字段名。
DEFAULT_PANEL_FIELDS: Tuple[str, ...] = (
    "open", "close", "high", "low", "ycp", "volume", "amount", "ChangePCT",
    "RangePCT", "TurnoverRate", "Ifsuspend", "if_up", "if_flat", "if_down",
    "RisingUpDays", "FallingDownDays", "MaxRisingUpDays", "MaxFallingDownDays",
    "HighestPrice", "LowestPrice", "ema12", "ema26", "dif", "dea", "macd",
    "max_high_9", "min_low_9", "RSV", "kdj_k", "kdj_d", "kdj_j", "ma4", "ma5",
    "ma8", "ma12", "ma16", "ma20", "ma47", "market_code", "category",
    "StockBoard", "ListedDate", "ListedSector", "ListedState", "vwap",
)

_IDENTIFIER_FIELDS = {"date", "code"}
_DIM_FIELDS = {"ListedDate", "ListedSector", "ListedState"}
# 公司库里这些列是 Decimal，直接 toFloat64。
_DECIMAL_FIELDS = {
    "open", "close", "high", "low", "ycp", "volume", "amount", "ChangePCT",
    "RangePCT", "TurnoverRate", "ema12", "ema26", "dif", "dea", "macd",
    "max_high_9", "min_low_9", "RSV", "kdj_k", "kdj_d", "kdj_j", "ma4", "ma5",
    "ma8", "ma12", "ma16", "ma20", "ma47",
}
# 公司库里这些列是 String，但值实际是数字（本地缓存里是 int64）。
_STRING_NUMERIC_FIELDS = {
    "Ifsuspend", "if_up", "if_flat", "if_down", "RisingUpDays",
    "FallingDownDays", "MaxRisingUpDays", "MaxFallingDownDays", "FallOnDebut",
    "FallOnNAPS", "StockBoard", "LimitBoard", "SurgedLimit", "DeclineLimit",
    "HighestPrice", "LowestPrice", "HighestPriceRW", "LowestPriceRW",
    "HighestPriceTW", "LowestPriceTW", "HighestPriceRM", "LowestPriceRM",
    "HighestPriceTM", "LowestPriceTM", "HighestPriceRMThree",
    "LowestPriceRMThree", "HighestPriceRMSix", "LowestPriceRMSix",
    "HighestPriceRY", "LowestPriceRY", "HighestPriceYTD", "LowestPriceYTD",
}
# 保留为字符串的列（本地缓存同样是字符串）。
_TEXT_FIELDS = {"market_code", "category", "ma_signal", "macd_signal", "kdj_signal", "strategy"}
_SOURCE_COLUMN = {"volume": "vol"}


def _panel_name(name: str) -> str:
    return live_db.panel_alias(str(name).strip())


def _source_column(field: str) -> str:
    return _SOURCE_COLUMN.get(field, field)


def _quote(value: Any) -> str:
    """ClickHouse 单引号字面量；只用于代码/枚举，日期另走 _ymd。"""
    text = str(value)
    if "\x00" in text:
        raise ValueError("SQL literal must not contain NUL")
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ymd(value: Any, field: str) -> str:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a YYYY-MM-DD date") from None
    if pd.isna(stamp):
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    return stamp.strftime("%Y-%m-%d")


def _normalized_codes(codes: Iterable[str]) -> List[str]:
    result = sorted({normalize_code(code) for code in codes if normalize_code(code)})
    if not result:
        raise ValueError("codes must contain at least one stock code")
    return result


def _code_list_sql(codes: Optional[Iterable[str]]) -> Optional[str]:
    if codes is None:
        return None
    normalized = _normalized_codes(codes)
    return "(" + ",".join(_quote(code) for code in normalized) + ")"


def _where_sql(
    codes: Optional[Iterable[str]],
    start: Any,
    end: Any,
    *,
    category: Optional[str],
    market_code: Optional[str],
) -> str:
    parts = [
        f"d.timestamps BETWEEN {_quote(_ymd(start, 'selection_start'))} "
        f"AND {_quote(_ymd(end, 'selection_end'))}"
    ]
    if category is not None and str(category).strip():
        parts.append(f"d.category = {_quote(str(category).strip())}")
    if market_code is not None and str(market_code).strip():
        parts.append(f"d.market_code = {_quote(str(market_code).strip())}")
    code_list = _code_list_sql(codes)
    if code_list is not None:
        parts.append(f"d.code IN {code_list}")
    return " AND ".join(parts)


def build_selection_days_sql(
    codes: Optional[Iterable[str]],
    start: Any,
    end: Any,
    *,
    category: Optional[str] = "stock",
    market_code: Optional[str] = None,
) -> str:
    where = _where_sql(
        codes, start, end, category=category, market_code=market_code
    )
    return (
        "SELECT toString(uniqExact(toDate(d.timestamps))) AS days "
        f"FROM {live_db.DAILY_TABLE} AS d WHERE {where}"
    )


def build_selection_stats_sql(
    codes: Optional[Iterable[str]],
    start: Any,
    end: Any,
    *,
    exclude_suspended: bool,
    min_listed_days: int,
    category: Optional[str] = "stock",
    market_code: Optional[str] = None,
) -> str:
    if min_listed_days < 0:
        raise ValueError("min_listed_days must be non-negative")
    where = _where_sql(
        codes, start, end, category=category, market_code=market_code
    )
    valid = "toFloat64(d.vol) > 0 AND toFloat64(d.amount) > 0"
    if exclude_suspended:
        valid += " AND d.Ifsuspend = '0'"
    join = ""
    if min_listed_days > 0:
        join = f" LEFT ANY JOIN {live_db.DIM_TABLE} AS m ON d.code = m.SecuCode"
        valid += (
            " AND dateDiff('day', toDate(m.ListedDate), toDate(d.timestamps)) "
            f">= {int(min_listed_days)}"
        )
    return (
        "SELECT toString(d.code) AS code, "
        f"toString(countIf({valid})) AS valid_rows, "
        f"toString(ifNull(avgIf(toFloat64(d.amount), {valid}), 0)) AS avg_amount "
        f"FROM {live_db.DAILY_TABLE} AS d{join} "
        f"WHERE {where} GROUP BY d.code ORDER BY d.code"
    )


def _panel_select(field: str) -> str:
    if field == "vwap":
        return (
            "toFloat64(d.amount) / nullIf(toFloat64(d.vol), 0) AS `vwap`"
        )
    if field in _DIM_FIELDS:
        if field == "ListedDate":
            return "toDate(m.ListedDate) AS `ListedDate`"
        return f"toString(m.`{field}`) AS `{field}`"
    source = _source_column(field)
    if field in _TEXT_FIELDS:
        return f"toString(d.`{source}`) AS `{field}`"
    if field in _STRING_NUMERIC_FIELDS:
        return f"toFloat64OrZero(d.`{source}`) AS `{field}`"
    if field in _DECIMAL_FIELDS:
        return f"toFloat64(d.`{source}`) AS `{field}`"
    raise ValueError(f"unsupported panel field: {field}")


def build_panel_sql(
    codes: Iterable[str],
    fields: Iterable[str],
    start: Any = None,
    end: Any = None,
) -> str:
    selected = list(dict.fromkeys(_panel_name(field) for field in fields))
    selects: List[str] = [
        "toDate(d.timestamps) AS `date`",
        "toString(d.code) AS `code`",
    ]
    needs_dim = False
    for field in selected:
        if field in _IDENTIFIER_FIELDS:
            continue
        if field in _DIM_FIELDS:
            needs_dim = True
        selects.append(_panel_select(field))
    where_parts = []
    if start is not None:
        where_parts.append(f"d.timestamps >= {_quote(_ymd(start, 'start_date'))}")
    if end is not None:
        where_parts.append(f"d.timestamps <= {_quote(_ymd(end, 'end_date'))}")
    where_parts.append(f"d.code IN {_code_list_sql(codes)}")
    join = f" LEFT ANY JOIN {live_db.DIM_TABLE} AS m ON d.code = m.SecuCode" if needs_dim else ""
    return (
        f"SELECT {', '.join(selects)} FROM {live_db.DAILY_TABLE} AS d{join} "
        f"WHERE {' AND '.join(where_parts)} ORDER BY d.timestamps, d.code"
    )


def _loadable(field: str) -> bool:
    return (
        field in _IDENTIFIER_FIELDS
        or field in _DIM_FIELDS
        or field in _DECIMAL_FIELDS
        or field in _STRING_NUMERIC_FIELDS
        or field in _TEXT_FIELDS
        or field == "vwap"
    )


def panel_field_names() -> set[str]:
    """可进因子面板的字段名（不查库，供接口打「面板可用」标记）。"""
    return {"date", "code", *DEFAULT_PANEL_FIELDS}


def available_panel_fields(
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> List[str]:
    """公司库可进面板的字段（含 date/code/vwap 与 dim 的 3 个上市字段）。"""
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)
    names: List[str] = ["date", "code", "vwap"]
    for entry in live_db.live_field_catalog(settings, client).data:
        if entry.get("table") != live_db.DAILY_TABLE:
            continue
        name = _panel_name(entry.get("name", ""))
        if name and _loadable(name) and name not in names:
            names.append(name)
    for name in ("ListedDate", "ListedSector", "ListedState"):
        if name not in names:
            names.append(name)
    return names


def source_signature() -> str:
    return SOURCE_SIGNATURE


def meta(
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> Dict[str, Any]:
    """公司库版 ``meta.json``：日期区间 / 股票数 / 可用字段 / 稳定签名。"""
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)
    stats = live_db.live_master_stats(settings, client).data
    return {
        "data_source": "clickhouse",
        "layout": "clickhouse-live",
        "store_dir": live_db.target_label(settings),
        "rows": stats.get("rows"),
        "n_stocks": stats.get("n_stocks"),
        "date_min": stats.get("date_min"),
        "date_max": stats.get("date_max"),
        "fields": ["date", "code", *DEFAULT_PANEL_FIELDS],
        "source_signature": SOURCE_SIGNATURE,
    }


def selection_days(
    codes: Optional[Iterable[str]],
    start: Any,
    end: Any,
    *,
    category: Optional[str] = "stock",
    market_code: Optional[str] = None,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> int:
    """窗口内候选股票出现过的交易日数（与本地 ``create_pool`` 同口径）。"""
    sql = build_selection_days_sql(
        codes, start, end, category=category, market_code=market_code
    )
    settings = settings or live_db.resolve_settings()
    rows = live_db._client(settings, client).query(sql)
    if not rows:
        return 0
    return live_db.to_int(rows[0].get("days")) or 0


def selection_stats(
    codes: Optional[Iterable[str]],
    start: Any,
    end: Any,
    *,
    exclude_suspended: bool = True,
    min_listed_days: int = 0,
    category: Optional[str] = "stock",
    market_code: Optional[str] = None,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> List[Dict[str, Any]]:
    """每只股票在窗口内的有效行数与平均成交额。"""
    sql = build_selection_stats_sql(
        codes,
        start,
        end,
        exclude_suspended=exclude_suspended,
        min_listed_days=min_listed_days,
        category=category,
        market_code=market_code,
    )
    settings = settings or live_db.resolve_settings()
    rows = live_db._client(settings, client).query(sql)
    stats: List[Dict[str, Any]] = []
    for row in rows:
        code = normalize_code(row.get("code", ""))
        valid_rows = live_db.to_int(row.get("valid_rows"))
        average_amount = live_db.to_float(row.get("avg_amount"))
        if not code or valid_rows is None or average_amount is None:
            continue
        stats.append(
            {
                "code": code,
                "valid_rows": valid_rows,
                "average_amount": average_amount,
            }
        )
    return stats


def _validate_fields(fields: Iterable[str]) -> None:
    unsupported = [
        field
        for field in fields
        if field not in _IDENTIFIER_FIELDS and not _loadable(field)
    ]
    if unsupported:
        raise ValueError(f"unsupported panel fields: {unsupported}")


def _date_column(series: pd.Series) -> pd.Series:
    """ClickHouse Parquet 的 Date 列是 uint16「1970-01-01 起的天数」。"""
    if pd.api.types.is_integer_dtype(series.dtype):
        return pd.to_datetime(series, unit="D", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def _normalize_panel(frame: pd.DataFrame, fields: Sequence[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["date"] = _date_column(frame["date"])
    frame["code"] = frame["code"].map(normalize_code)
    for field in fields:
        if field in _IDENTIFIER_FIELDS or field not in frame.columns:
            continue
        if field == "ListedDate":
            frame[field] = _date_column(frame[field])
        elif field in _TEXT_FIELDS or field in {"ListedSector", "ListedState"}:
            frame[field] = frame[field].astype("string")
        else:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    keep = ["date", "code", *[field for field in fields if field not in _IDENTIFIER_FIELDS]]
    frame = frame.dropna(subset=["date", "code"]).drop_duplicates(["date", "code"], keep="last")
    return frame.sort_values(["date", "code"]).reset_index(drop=True)[keep]


def load_panel(
    codes: Iterable[str],
    start_date: Any = None,
    end_date: Any = None,
    columns: Optional[Sequence[str]] = None,
    *,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> pd.DataFrame:
    """从公司库加载股票池面板（与本地 ``load_pool_panel`` 等价的字段集合）。"""
    selected = list(
        dict.fromkeys(
            _panel_name(field)
            for field in (DEFAULT_PANEL_FIELDS if columns is None else columns)
        )
    )
    if not selected:
        raise ValueError("columns must contain at least one field")
    _validate_fields(selected)
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)
    sql = build_panel_sql(codes, selected, start_date, end_date)
    handle = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    temp_path = Path(handle.name)
    handle.close()
    try:
        client.query_to_file(
            sql,
            temp_path,
            timeout=settings.panel_timeout,
            max_execution_time=settings.panel_max_execution_time,
            max_memory_usage=settings.panel_max_memory,
        )
        frame = pd.read_parquet(
            temp_path, columns=["date", "code", *[f for f in selected if f not in _IDENTIFIER_FIELDS]]
        )
    finally:
        temp_path.unlink(missing_ok=True)
    return _normalize_panel(frame, selected)


def _rewrite_dates(raw_path: Path, final_path: Path) -> None:
    """把 ClickHouse 的 Date/DateTime 整数列重写成 Arrow timestamp。

    ClickHouse 的 Parquet writer 不给 Date/DateTime 写 logical type，PyArrow 会读成
    uint16/uint32；``single_factor.materialize_memmap`` 用 ``pd.Timestamp`` 过滤日期，
    必须显式转成 timestamp 列。
    """
    reader = pq.ParquetFile(raw_path)
    schema = reader.schema_arrow
    targets = {"date", "ListedDate"}
    converted = set()
    fields: List[pa.Field] = []
    for field in schema:
        if field.name in targets and pa.types.is_integer(field.type):
            fields.append(pa.field(field.name, pa.timestamp("s"), nullable=field.nullable))
            converted.add(field.name)
        else:
            fields.append(field)
    output_schema = pa.schema(fields, metadata=schema.metadata)
    writer = pq.ParquetWriter(final_path, schema=output_schema, compression="zstd")
    try:
        for batch in reader.iter_batches(batch_size=200_000):
            table = pa.Table.from_batches([batch], schema=schema)
            for name in converted:
                index = table.schema.get_field_index(name)
                seconds = pc.multiply(pc.cast(table.column(index), pa.int64()), 86400)
                table = table.set_column(
                    index, pa.field(name, pa.timestamp("s")), pc.cast(seconds, pa.timestamp("s"))
                )
            writer.write_table(table.cast(output_schema))
    finally:
        writer.close()


def write_pool_panel(
    codes: Iterable[str],
    fields: Iterable[str],
    output_path: str | Path,
    start_date: Any = None,
    end_date: Any = None,
    *,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> Dict[str, Any]:
    """生成因子运行用的 ``panel.parquet``（直接由公司库流式写入）。"""
    selected = list(dict.fromkeys(_panel_name(field) for field in fields))
    if not selected:
        raise ValueError("fields must contain at least one field")
    _validate_fields(selected)
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)
    panel_path = Path(output_path).expanduser().resolve()
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel_path.unlink(missing_ok=True)
    raw_path = panel_path.with_name(panel_path.name + ".raw.parquet")
    raw_path.unlink(missing_ok=True)
    written = False
    try:
        client.query_to_file(
            build_panel_sql(codes, selected, start_date, end_date),
            raw_path,
            timeout=settings.panel_timeout,
            max_execution_time=settings.panel_max_execution_time,
            max_memory_usage=settings.panel_max_memory,
        )
        _rewrite_dates(raw_path, panel_path)
        table = pq.read_table(panel_path, columns=["date", "code"])
        rows = table.num_rows
        if rows == 0:
            raise ValueError("no rows remain for the requested pool panel")
        dates = pd.to_datetime(table.column("date").to_pandas(), errors="coerce").dropna()
        if dates.empty:
            raise ValueError("no rows remain for the requested pool panel")
        n_stocks = pc.count_distinct(table.column("code")).as_py()
        written = True
    finally:
        raw_path.unlink(missing_ok=True)
        if not written:
            panel_path.unlink(missing_ok=True)
    return {
        "panel_path": str(panel_path),
        "fields": selected,
        "rows": int(rows),
        "n_stocks": int(n_stocks),
        "date_min": str(dates.min().date()),
        "date_max": str(dates.max().date()),
    }
