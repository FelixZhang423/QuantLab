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
    "FallOnDebut", "FallOnNAPS",
    "HighestPrice", "LowestPrice", "LimitBoard", "SurgedLimit", "DeclineLimit",
    "HighestPriceRW", "LowestPriceRW", "HighestPriceTW", "LowestPriceTW",
    "HighestPriceRM", "LowestPriceRM", "HighestPriceTM", "LowestPriceTM",
    "HighestPriceRMThree", "LowestPriceRMThree",
    "HighestPriceRMSix", "LowestPriceRMSix",
    "HighestPriceRY", "LowestPriceRY", "HighestPriceYTD", "LowestPriceYTD",
    "ema12", "ema26", "dif", "dea", "macd",
    "max_high_9", "min_low_9", "RSV", "kdj_k", "kdj_d", "kdj_j", "ma4", "ma5",
    "ma8", "ma12", "ma16", "ma20", "ma47", "market_code", "category",
    "StockBoard", "ListedDate", "ListedSector", "ListedState", "vwap",
)

# 财务原始字段：公司库按 CompanyCode 存，需先经 dwd.secumain 映射到证券代码。
FUNDAMENTAL_TABLE = "ods_dps_target.lc_maindatanew"
FUNDAMENTAL_CODE_TABLE = "dwd.secumain"
# 只保留合并报表（Mark=2）的定期报告（BulletinType=20），避免母公司报表/业绩快报混入。
FUNDAMENTAL_MARK = 2
FUNDAMENTAL_BULLETIN = "20"
FUNDAMENTAL_LOOKBACK_DAYS = 550
FUNDAMENTAL_PREFIX = "fund_"
# 30 个核心财务原始字段；衍生指标（idx_*）不在这一批，见后续阶段。
FUNDAMENTAL_FIELDS: Tuple[str, ...] = (
    "BasicEPS", "DilutedEPS", "EPS", "ROEByReport", "ROE", "ROECut",
    "WROE", "WROECut", "OperatingReenue", "NPFromParentCompanyOwners",
    "NetProfitCut", "NetProfit", "OperatingProfit", "TotalProfit",
    "IncomeTaxCost", "FairValueChangeIncome", "RetainedProfit",
    "NetOperateCashFlow", "NetInvestCashFlow", "NetFinanceCashFlow",
    "TotalAssets", "TotalCurrentAssets", "TotalNonCurrentAssets",
    "TotalLiability", "TotalCurrentLiability", "TotalNonCurrentLiability",
    "SEWithoutMI", "TotalShareholderEquity", "Inventories", "AccountReceivables",
)

# 每日估值字段：SecuCode + data_time 直接对齐日频，无披露日问题。
VALUATION_TABLE = "dws.f10_finance_index_fd"
VALUATION_PREFIX = "val_"
VALUATION_FIELDS: Tuple[str, ...] = (
    "PB", "PSTTM", "PCFTTM", "DividendRatioLYR", "TotalMV",
)
# 字段页展示用中文名，与 441 字段说明表保持一致。
FUNDAMENTAL_LABELS: Dict[str, str] = {
    "BasicEPS": "基本每股收益",
    "DilutedEPS": "稀释每股收益",
    "EPS": "每股收益",
    "ROEByReport": "净资产收益率(报告值)",
    "ROE": "净资产收益率(摊薄)",
    "ROECut": "净资产收益率(摊薄-扣除)",
    "WROE": "加权净资产收益率",
    "WROECut": "加权净资产收益率(扣除)",
    "OperatingReenue": "营业收入",
    "NPFromParentCompanyOwners": "归母净利润",
    "NetProfitCut": "扣非净利润",
    "NetProfit": "净利润",
    "OperatingProfit": "营业利润",
    "TotalProfit": "利润总额",
    "IncomeTaxCost": "所得税费用",
    "FairValueChangeIncome": "公允价值变动收益",
    "RetainedProfit": "未分配利润",
    "NetOperateCashFlow": "经营活动现金流净额",
    "NetInvestCashFlow": "投资活动现金流净额",
    "NetFinanceCashFlow": "筹资活动现金流净额",
    "TotalAssets": "总资产",
    "TotalCurrentAssets": "流动资产合计",
    "TotalNonCurrentAssets": "非流动资产合计",
    "TotalLiability": "总负债",
    "TotalCurrentLiability": "流动负债合计",
    "TotalNonCurrentLiability": "非流动负债合计",
    "SEWithoutMI": "归母所有者权益",
    "TotalShareholderEquity": "股东权益合计",
    "Inventories": "存货",
    "AccountReceivables": "应收账款",
}
VALUATION_LABELS: Dict[str, str] = {
    "PB": "市净率",
    "PSTTM": "市销率(TTM)",
    "PCFTTM": "市现率(TTM)",
    "DividendRatioLYR": "股息率(LYR)",
    "TotalMV": "总市值",
}

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


# 文本 / 日期列不能直接进数值表达式（分类字段可做分组，但不是表达式操作数）。
_EXPRESSION_EXCLUDED = {
    "date", "code", "ListedDate", "ListedSector", "ListedState", "ChiNameAbbr",
    *_TEXT_FIELDS,
}


def is_expression_field(name: str) -> bool:
    """字段能否作为因子表达式的操作数：必须是可加载的数值列。"""
    field = live_db.panel_alias(str(name).strip())
    if field in _EXPRESSION_EXCLUDED:
        return False
    return _loadable(field)


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
    fundamentals: Optional[Sequence[str]] = None,
    valuation: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """从公司库加载股票池面板（与本地 ``load_pool_panel`` 等价的字段集合）。

    ``fundamentals`` 非空时，按 InfoPublDate as-of 合并财务字段，列名加 ``fund_`` 前缀；
    ``valuation`` 非空时按交易日合并估值字段，列名加 ``val_`` 前缀。两者都不进
    ``DEFAULT_PANEL_FIELDS``，由调用方显式请求，避免默认回测变慢。
    """
    codes = [normalize_code(code) for code in codes]
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
    panel = _normalize_panel(frame, selected)
    if fundamentals:
        if start_date is None or end_date is None:
            raise ValueError("fundamentals requires start_date and end_date")
        fund = load_fundamentals(codes, start_date, end_date, fundamentals, settings=settings, client=client)
        panel = attach_fundamentals(panel, fund)
    if valuation:
        if start_date is None or end_date is None:
            raise ValueError("valuation requires start_date and end_date")
        values = load_valuation(codes, start_date, end_date, valuation, settings=settings, client=client)
        panel = attach_valuation(panel, values)
    return panel


def build_company_codes_sql(codes: Iterable[str]) -> str:
    """证券代码 → 公司代码（财务表按 CompanyCode 存）。"""
    return (
        "SELECT toString(SecuCode) AS code, toString(CompanyCode) AS company_code "
        f"FROM {FUNDAMENTAL_CODE_TABLE} WHERE SecuCode IN {_code_list_sql(codes)}"
    )


def build_fundamentals_sql(
    company_codes: Iterable[str],
    fields: Iterable[str],
    start_date: Any,
    end_date: Any,
    lookback_days: int = FUNDAMENTAL_LOOKBACK_DAYS,
) -> str:
    """财务面板 SQL：只取合并报表的定期报告，日期按 InfoPublDate 截断。"""
    codes = ",".join(str(int(str(code).strip())) for code in company_codes)
    selected = [field for field in fields]
    unknown = [field for field in selected if field not in FUNDAMENTAL_FIELDS]
    if unknown:
        raise ValueError(f"unsupported fundamental fields: {unknown}")
    selects = [
        "toString(f.CompanyCode) AS company_code",
        "toDate(f.EndDate) AS end_date",
        "toDate(f.InfoPublDate) AS info_date",
        *[f"toFloat64OrNull(toString(f.{field})) AS {field}" for field in selected],
    ]
    start = _quote(_ymd(start_date, "start_date"))
    end = _quote(_ymd(end_date, "end_date"))
    return (
        f"SELECT {', '.join(selects)} FROM {FUNDAMENTAL_TABLE} AS f "
        f"WHERE f.CompanyCode IN ({codes}) "
        f"AND f.Mark = {FUNDAMENTAL_MARK} AND f.BulletinType = '{FUNDAMENTAL_BULLETIN}' "
        f"AND f.InfoPublDate <= toDate({end}) "
        f"AND f.InfoPublDate >= toDate({start}) - INTERVAL {int(lookback_days)} DAY "
        "ORDER BY f.CompanyCode, f.InfoPublDate"
    )


def load_fundamentals(
    codes: Iterable[str],
    start_date: Any,
    end_date: Any,
    fields: Optional[Sequence[str]] = None,
    *,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
    lookback_days: int = FUNDAMENTAL_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """按证券代码取财务原始字段，返回 [code, info_date, end_date, *fields]。"""
    codes = [normalize_code(code) for code in codes]
    selected = list(dict.fromkeys(fields or FUNDAMENTAL_FIELDS))
    unknown = [field for field in selected if field not in FUNDAMENTAL_FIELDS]
    if unknown:
        raise ValueError(f"unsupported fundamental fields: {unknown}")
    columns = ["code", "info_date", "end_date", *selected]
    if not codes:
        return pd.DataFrame(columns=columns)
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)

    by_company: Dict[str, List[str]] = {}
    for row in client.query(build_company_codes_sql(codes)):
        code = normalize_code(row.get("code", ""))
        company = str(row.get("company_code", "")).strip()
        if code and company:
            by_company.setdefault(company, []).append(code)
    if not by_company:
        return pd.DataFrame(columns=columns)

    sql = build_fundamentals_sql(by_company, selected, start_date, end_date, lookback_days)
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
        frame = pd.read_parquet(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame["company_code"] = frame["company_code"].astype(str)
    frame["info_date"] = _date_column(frame["info_date"])
    frame["end_date"] = _date_column(frame["end_date"])
    for field in selected:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")

    # 一个公司可能对应多个证券代码（A/B 股等），按映射展开。
    parts = []
    for company, group in frame.groupby("company_code", sort=False):
        for code in by_company.get(company, []):
            part = group.copy()
            part["code"] = code
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=columns)
    merged = pd.concat(parts, ignore_index=True).dropna(subset=["info_date"])
    merged = merged.sort_values(["code", "info_date", "end_date"])
    merged = merged.drop_duplicates(["code", "info_date", "end_date"], keep="last")
    return merged[columns].reset_index(drop=True)


def attach_fundamentals(panel: pd.DataFrame, fundamentals: Optional[pd.DataFrame]) -> pd.DataFrame:
    """按 InfoPublDate 做 as-of 合并：每日只取当日已披露的最新一期，避免未来函数。"""
    if fundamentals is None or fundamentals.empty:
        return panel
    left = panel.copy()
    left["code"] = left["code"].astype(str)
    left["date"] = pd.to_datetime(left["date"]).astype("datetime64[ns]")
    right = fundamentals.copy()
    right["code"] = right["code"].astype(str)
    right["info_date"] = pd.to_datetime(right["info_date"]).astype("datetime64[ns]")
    right["end_date"] = pd.to_datetime(right["end_date"])
    rename = {field: f"{FUNDAMENTAL_PREFIX}{field}" for field in right.columns if field not in {"code", "info_date", "end_date"}}
    rename["info_date"] = f"{FUNDAMENTAL_PREFIX}info_date"
    rename["end_date"] = f"{FUNDAMENTAL_PREFIX}end_date"
    right = right.rename(columns=rename)
    right_key = f"{FUNDAMENTAL_PREFIX}info_date"
    left = left.sort_values(["date", "code"])
    right = right.sort_values([right_key, "code"])
    merged = pd.merge_asof(
        left, right, left_on="date", right_on=right_key, by="code", direction="backward"
    )
    return merged.reset_index(drop=True)


def build_valuation_sql(
    codes: Iterable[str], fields: Iterable[str], start_date: Any, end_date: Any
) -> str:
    """每日估值面板 SQL（按交易日直接对齐，不做 as-of）。"""
    selected = [field for field in fields]
    unknown = [field for field in selected if field not in VALUATION_FIELDS]
    if unknown:
        raise ValueError(f"unsupported valuation fields: {unknown}")
    selects = [
        "toString(SecuCode) AS code",
        "toDate(data_time) AS date",
        *[f"toFloat64OrNull(toString({field})) AS {field}" for field in selected],
    ]
    start = _quote(_ymd(start_date, "start_date"))
    end = _quote(_ymd(end_date, "end_date"))
    return (
        f"SELECT {', '.join(selects)} FROM {VALUATION_TABLE} "
        f"WHERE SecuCode IN {_code_list_sql(codes)} "
        f"AND data_time >= toDate({start}) AND data_time <= toDate({end})"
    )


def load_valuation(
    codes: Iterable[str],
    start_date: Any,
    end_date: Any,
    fields: Optional[Sequence[str]] = None,
    *,
    settings: Optional[live_db.LiveDBSettings] = None,
    client: Optional[live_db.ClickHouseHTTPClient] = None,
) -> pd.DataFrame:
    """按代码和交易日取估值字段，返回 [code, date, *fields]。"""
    codes = [normalize_code(code) for code in codes]
    selected = list(dict.fromkeys(fields or VALUATION_FIELDS))
    unknown = [field for field in selected if field not in VALUATION_FIELDS]
    if unknown:
        raise ValueError(f"unsupported valuation fields: {unknown}")
    columns = ["code", "date", *selected]
    if not codes:
        return pd.DataFrame(columns=columns)
    settings = settings or live_db.resolve_settings()
    client = live_db._client(settings, client)
    handle = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    temp_path = Path(handle.name)
    handle.close()
    try:
        client.query_to_file(
            build_valuation_sql(codes, selected, start_date, end_date),
            temp_path,
            timeout=settings.panel_timeout,
            max_execution_time=settings.panel_max_execution_time,
            max_memory_usage=settings.panel_max_memory,
        )
        frame = pd.read_parquet(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["code"] = frame["code"].astype(str)
    frame["date"] = _date_column(frame["date"])
    for field in selected:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=["date", "code"])
    frame = frame.drop_duplicates(["code", "date"], keep="last")
    return frame[columns].sort_values(["code", "date"]).reset_index(drop=True)


def attach_valuation(panel: pd.DataFrame, valuation: Optional[pd.DataFrame]) -> pd.DataFrame:
    """按交易日合并估值字段（左连接，缺失保留 NaN）。"""
    if valuation is None or valuation.empty:
        return panel
    left = panel.copy()
    left["code"] = left["code"].astype(str)
    left["date"] = pd.to_datetime(left["date"]).astype("datetime64[ns]")
    right = valuation.copy()
    right["code"] = right["code"].astype(str)
    right["date"] = pd.to_datetime(right["date"]).astype("datetime64[ns]")
    rename = {
        field: f"{VALUATION_PREFIX}{field}"
        for field in right.columns
        if field not in {"code", "date"}
    }
    right = right.rename(columns=rename)
    return left.merge(right, on=["date", "code"], how="left")


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
    """生成因子运行用的 ``panel.parquet``（直接由公司库流式写入）。

    ``fields`` 里带 ``fund_`` 前缀的字段会按 InfoPublDate as-of 合并进来，
    其余字段走日频面板 SQL；这样因子生成和回测能共用同一份字段空间。
    """
    codes = [normalize_code(code) for code in codes]
    selected = list(dict.fromkeys(_panel_name(field) for field in fields))
    if not selected:
        raise ValueError("fields must contain at least one field")
    fund_fields = [
        field[len(FUNDAMENTAL_PREFIX):]
        for field in selected
        if field.startswith(FUNDAMENTAL_PREFIX)
    ]
    val_fields = [
        field[len(VALUATION_PREFIX):]
        for field in selected
        if field.startswith(VALUATION_PREFIX)
    ]
    daily_fields = [
        field
        for field in selected
        if not field.startswith((FUNDAMENTAL_PREFIX, VALUATION_PREFIX))
    ]
    if not daily_fields:
        raise ValueError("panel fields must contain at least one daily field")
    _validate_fields(daily_fields)
    unknown = [field for field in fund_fields if field not in FUNDAMENTAL_FIELDS]
    if unknown:
        raise ValueError(f"unsupported fundamental fields: {unknown}")
    unknown = [field for field in val_fields if field not in VALUATION_FIELDS]
    if unknown:
        raise ValueError(f"unsupported valuation fields: {unknown}")
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
            build_panel_sql(codes, daily_fields, start_date, end_date),
            raw_path,
            timeout=settings.panel_timeout,
            max_execution_time=settings.panel_max_execution_time,
            max_memory_usage=settings.panel_max_memory,
        )
        _rewrite_dates(raw_path, panel_path)
        if fund_fields or val_fields:
            if start_date is None or end_date is None:
                raise ValueError("fundamental/valuation fields require start_date and end_date")
            frame = pd.read_parquet(panel_path)
            if fund_fields:
                fund = load_fundamentals(codes, start_date, end_date, fund_fields, settings=settings, client=client)
                frame = attach_fundamentals(frame, fund)
            if val_fields:
                valuation = load_valuation(codes, start_date, end_date, val_fields, settings=settings, client=client)
                frame = attach_valuation(frame, valuation)
            frame.to_parquet(panel_path, index=False)
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
