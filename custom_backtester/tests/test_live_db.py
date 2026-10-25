"""api/live_db.py 的单元测试：全程无网络（假 opener / 假 client 注入）。"""
from __future__ import annotations

import io
import threading
import time
import urllib.error

import pytest


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class _FakeOpener:
    """替身 opener：记录请求，按预设返回响应或抛错。"""

    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    """替身 ClickHouse 客户端：按 SQL 里的标记返回预设行。"""

    def __init__(self, rows_by_marker) -> None:
        self.rows_by_marker = rows_by_marker
        self.calls = []

    def query(self, sql):
        self.calls.append(sql)
        for marker, rows in self.rows_by_marker.items():
            if marker in sql:
                return rows
        raise AssertionError(f"未预期的 SQL：{sql[:80]}")


def _http_error(code: int, body: bytes, url: str = "http://clickhouse.example:8123/"):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


@pytest.fixture(autouse=True)
def _fresh_cache():
    from api import live_db

    live_db.clear_cache()
    yield
    live_db.clear_cache()


# ---------- 解析 / 转换 ----------


def test_parse_json_each_row_skips_blank_lines():
    from api import live_db

    rows = live_db.parse_json_each_row('\n{"a": "1"}\n\n{"a": "2"}\n')
    assert rows == [{"a": "1"}, {"a": "2"}]


def test_parse_json_each_row_rejects_garbage():
    from api import live_db

    with pytest.raises(live_db.LiveDBQueryError):
        live_db.parse_json_each_row('{"a": 1}\nnot json')


def test_to_int_and_to_float_convert_quoted_values():
    from api import live_db

    # JSONEachRow 会把 64 位整数输出成带引号的字符串
    assert live_db.to_int("17368843") == 17368843
    assert live_db.to_int("") is None
    assert live_db.to_int(None) is None
    assert live_db.to_int("abc") is None
    assert live_db.to_float("1034554249.38") == 1034554249.38
    assert live_db.to_float("") is None


def test_short_type_compresses_nullable():
    from api import live_db

    assert live_db._short_type("Nullable(String)") == "String?"
    assert live_db._short_type("Decimal(18, 2)") == "Decimal(18,2)"
    assert live_db._short_type("DateTime64(3, 'Asia/Shanghai')") == "DateTime64(3,'Asia/Shanghai')"


# ---------- 配置 ----------


def test_load_env_file_tolerates_bom_comments_and_quotes(tmp_path):
    from api import live_db

    env_path = tmp_path / "clickhouse.local.env"
    env_path.write_bytes(
        "# 注释\r\nQL_CH_PASSWORD=secret-value\r\nQL_CH_HOST=\"10.0.0.1\"\r\n\r\nBAD_LINE\r\n".encode(
            "utf-8-sig"
        )
    )
    values = live_db.load_env_file(env_path)
    assert values["QL_CH_PASSWORD"] == "secret-value"  # BOM 不能吃掉第一个键
    assert values["QL_CH_HOST"] == "10.0.0.1"
    assert "BAD_LINE" not in values


def test_resolve_settings_env_overrides_file(tmp_path):
    from api import live_db

    env_path = tmp_path / "clickhouse.local.env"
    env_path.write_text("QL_CH_PASSWORD=file-pass\nQL_CH_HOST=10.0.0.9\n", encoding="utf-8")
    settings = live_db.resolve_settings(env_path, environ={"QL_CH_PASSWORD": "env-pass"})
    assert settings.password == "env-pass"  # 环境变量优先
    assert settings.host == "10.0.0.9"  # 文件里的值保留
    assert settings.cache_ttl == live_db.DEFAULT_CACHE_TTL
    assert settings.display == "10.0.0.9:8123"


def test_resolve_settings_requires_password(tmp_path):
    from api import live_db

    with pytest.raises(live_db.LiveDBConfigError):
        live_db.resolve_settings(tmp_path / "missing.env", environ={})


# ---------- 只读护栏 ----------


def test_guard_readonly_allows_queries_and_blocks_writes():
    from api import live_db

    assert live_db.guard_readonly("SELECT 1;") == "SELECT 1"
    assert live_db.guard_readonly("  WITH x AS (SELECT 1) SELECT * FROM x  ").startswith("WITH")
    with pytest.raises(live_db.LiveDBQueryError):
        live_db.guard_readonly("DROP TABLE dws.ll_stock_daily_sharing")
    with pytest.raises(live_db.LiveDBQueryError):
        live_db.guard_readonly("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x")
    with pytest.raises(live_db.LiveDBQueryError):
        live_db.guard_readonly("SELECT * FROM t INTO OUTFILE '/tmp/dump'")


def test_module_sql_constants_pass_guard():
    from api import live_db

    for sql in (
        live_db.SQL_MASTER_STATS,
        live_db.SQL_DAILY_COLUMNS,
        live_db.SQL_DIM_COLUMNS,
        live_db.SQL_STOCK_ROWS,
        live_db.SQL_DIM_PROFILES,
    ):
        assert live_db.guard_readonly(sql)


def test_dim_profile_sql_uses_first_level_industry_name():
    """dim.Industry 是细分行业编码；单级行业必须取 FirstIndustryName。"""
    from api import live_db

    assert "FirstIndustryName AS industry" in live_db.SQL_DIM_PROFILES
    assert "FirstIndustryCode AS industry_code" in live_db.SQL_DIM_PROFILES


# ---------- HTTP 客户端 ----------


def test_client_parses_rows_and_keeps_password_out_of_url():
    from api import live_db

    settings = live_db.LiveDBSettings(password="top-secret")
    opener = _FakeOpener(_FakeResponse(b'{"rows": "17368843"}\n'))
    client = live_db.ClickHouseHTTPClient(settings, opener=opener)

    rows = client.query("SELECT toString(count()) AS rows FROM t")
    assert rows == [{"rows": "17368843"}]

    request = opener.requests[0]
    assert "top-secret" not in request.full_url
    assert request.get_header("Authorization").startswith("Basic ")
    assert "default_format=JSONEachRow" in request.full_url
    assert "max_memory_usage=1000000000" in request.full_url
    assert request.data == b"SELECT toString(count()) AS rows FROM t"
    assert opener.timeouts == [settings.timeout]


def test_client_maps_auth_failure_to_unavailable():
    from api import live_db

    settings = live_db.LiveDBSettings(password="top-secret")
    client = live_db.ClickHouseHTTPClient(
        settings, opener=_FakeOpener(error=_http_error(403, b"forbidden"))
    )
    with pytest.raises(live_db.LiveDBUnavailable) as excinfo:
        client.query("SELECT 1")
    assert "认证失败" in str(excinfo.value)
    assert "top-secret" not in str(excinfo.value)


def test_client_maps_query_failure_and_redacts_password():
    from api import live_db

    settings = live_db.LiveDBSettings(password="top-secret")
    body = b"Code: 62. DB::Exception: top-secret rejected"
    client = live_db.ClickHouseHTTPClient(settings, opener=_FakeOpener(error=_http_error(500, body)))
    with pytest.raises(live_db.LiveDBQueryError) as excinfo:
        client.query("SELECT 1")
    message = str(excinfo.value)
    assert "top-secret" not in message
    assert "***" in message


def test_client_retries_connection_error_once(monkeypatch):
    from api import live_db

    monkeypatch.setattr(live_db.time, "sleep", lambda *_: None)
    settings = live_db.LiveDBSettings(password="x")
    opener = _FakeOpener(error=urllib.error.URLError(ConnectionRefusedError("refused")))
    client = live_db.ClickHouseHTTPClient(settings, opener=opener)
    with pytest.raises(live_db.LiveDBUnavailable) as excinfo:
        client.query("SELECT 1")
    assert len(opener.requests) == 2  # 连接类失败重试一次
    assert "公司网络" in str(excinfo.value)


def test_client_does_not_retry_timeouts():
    from api import live_db

    settings = live_db.LiveDBSettings(password="x")
    opener = _FakeOpener(error=urllib.error.URLError(TimeoutError("timed out")))
    client = live_db.ClickHouseHTTPClient(settings, opener=opener)
    with pytest.raises(live_db.LiveDBUnavailable) as excinfo:
        client.query("SELECT 1")
    assert len(opener.requests) == 1  # 超时不重试
    assert "超时" in str(excinfo.value)


# ---------- TTL 缓存 ----------


def test_cached_hits_ttl_and_ttl_zero_disables():
    from api import live_db

    calls = []

    def produce():
        calls.append(1)
        return {"n": len(calls)}

    first = live_db._cached("k", 60.0, produce)
    second = live_db._cached("k", 60.0, produce)
    assert first.cached is False and second.cached is True
    assert second.data == first.data
    assert second.queried_at == first.queried_at
    assert len(calls) == 1

    third = live_db._cached("k", 0.0, produce)
    fourth = live_db._cached("k", 0.0, produce)
    assert third.cached is False and fourth.cached is False
    assert len(calls) == 3


def test_cached_single_flight_under_concurrency():
    from api import live_db

    calls = []
    started = threading.Event()

    def produce():
        calls.append(1)
        started.set()
        time.sleep(0.2)
        return {"ok": True}

    results = []

    def worker():
        results.append(live_db._cached("slow", 60.0, produce))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    threads[0].start()
    assert started.wait(timeout=2)  # 确保第二个线程在 produce 进行中进入
    threads[1].start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(calls) == 1  # 第二个请求等在 key 锁上，没有重复查询
    assert len(results) == 2
    assert results[0].data == results[1].data


def test_cached_ttl_zero_coalesces_concurrent_but_never_reuses_old():
    """关闭缓存（ttl=0）时：并发同发请求合流成一次查询，但串行请求必须重新查库。"""
    from api import live_db

    calls = []
    started = threading.Event()

    def produce():
        calls.append(1)
        started.set()
        time.sleep(0.2)
        return {"n": len(calls)}

    results = []

    def worker():
        results.append(live_db._cached("live", 0.0, produce))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    threads[0].start()
    assert started.wait(timeout=2)  # 第二个线程在 produce 进行中进入
    threads[1].start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(calls) == 1  # 并发合流：只打一次库
    assert len(results) == 2
    assert all(r.cached is False for r in results)  # 都是刚查的，不标记为缓存

    third = live_db._cached("live", 0.0, produce)  # 串行再来一次
    assert third.cached is False
    assert len(calls) == 2  # 不复用上一次的结果，真查库


# ---------- 业务查询（假 client） ----------


def test_live_master_stats_reads_count_row():
    from api import live_db

    client = _FakeClient(
        {
            "uniqExact(code)": [
                {
                    "rows": "17368843",
                    "n_stocks": "5589",
                    "date_min": "1990-12-19",
                    "date_max": "2026-10-09",
                }
            ]
        }
    )
    stats = live_db.live_master_stats(live_db.LiveDBSettings(password="x"), client=client)
    assert stats.data == {
        "rows": 17368843,
        "n_stocks": 5589,
        "date_min": "1990-12-19",
        "date_max": "2026-10-09",
    }
    assert stats.cached is False


def test_live_field_catalog_excludes_keys_and_appends_dim_fields():
    from api import live_db

    client = _FakeClient(
        {
            "table = 'll_stock_daily_sharing'": [
                {"name": "code", "type": "String", "comment": "", "position": "1"},
                {"name": "timestamps", "type": "String", "comment": "交易日", "position": "2"},
                {"name": "close", "type": "Nullable(Decimal(18, 2))", "comment": "收盘价", "position": "3"},
                {"name": "vol", "type": "Nullable(Decimal(18, 2))", "comment": "", "position": "4"},
            ],
            "table = 'stock_main_info_fd'": [
                {"name": "SecuCode", "type": "String", "comment": "", "position": "1"},
                {"name": "ListedDate", "type": "DateTime64(3, 'Asia/Shanghai')", "comment": "", "position": "2"},
                {"name": "ChiNameAbbr", "type": "String", "comment": "简称", "position": "3"},
            ],
        }
    )
    catalog = live_db.live_field_catalog(live_db.LiveDBSettings(password="x"), client=client)
    names = [item["name"] for item in catalog.data]
    assert names == ["close", "vol", "ListedDate", "ChiNameAbbr"]
    assert catalog.data[0]["dtype"] == "Decimal(18,2)?"
    assert catalog.data[0]["comment"] == "收盘价"
    assert catalog.data[0]["table"] == live_db.DAILY_TABLE
    assert catalog.data[2]["table"] == live_db.DIM_TABLE


def test_live_stock_rows_converts_types_and_merges_profiles():
    from api import live_db

    client = _FakeClient(
        {
            "ChiNameAbbr AS name": [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "industry": "银行",
                    "industry_code": "480000",
                    "sector": "1.0",
                    "listed_state": "1.0",
                    "listed_date": "1991-04-03 00:00:00",
                },
                {
                    "code": "920879",
                    "name": "",
                    "industry": None,
                    "industry_code": None,
                    "sector": None,
                    "listed_state": None,
                    "listed_date": None,
                },
            ],
            "FROM dws.ll_stock_daily_sharing\nWHERE category": [
                {
                    "code": "000001",
                    "rows": "8824",
                    "start_date": "1991-04-03",
                    "end_date": "2026-10-09",
                    "latest_close": "11.59",
                    "latest_volume": "107810561",
                    "latest_amount": "1259717108.28",
                    "latest_ifsuspend": "0",
                },
                {
                    "code": "920879",
                    "rows": "53",
                    "start_date": "2026-03-27",
                    "end_date": "2026-10-09",
                    "latest_close": "3.20",
                    "latest_volume": "100",
                    "latest_amount": "320.00",
                    "latest_ifsuspend": "1",
                },
            ],
        }
    )
    live = live_db.live_stock_rows(live_db.LiveDBSettings(password="x"), client=client)
    items = {item["code"]: item for item in live.data}
    pingan = items["000001"]
    assert pingan["rows"] == 8824
    assert pingan["name"] == "平安银行"
    assert pingan["industry"] == "银行"
    assert pingan["industry_code"] == "480000"
    assert pingan["sector"] == "1.0"
    assert pingan["listed_state"] == "1.0"
    assert pingan["listed_date"] == "1991-04-03"
    assert pingan["exchange"] == "SZ"
    assert pingan["board"] == "深市主板"
    assert pingan["latest_close"] == 11.59
    assert pingan["latest_volume"] == 107810561
    assert pingan["latest_amount"] == 1259717108.28
    assert pingan["latest_date"] == "2026-10-09"
    assert pingan["latest_ifsuspend"] == 0
    assert items["920879"]["name"] is None  # dim 里没有名称
    assert items["920879"]["industry"] is None
    assert items["920879"]["industry_code"] is None
    assert items["920879"]["board"] == "北交所"
    assert items["920879"]["latest_ifsuspend"] == 1


def test_parse_listed_date_and_code_classification():
    from api import live_db

    assert live_db.parse_listed_date("1991-04-03 00:00:00") == "1991-04-03"
    assert live_db.parse_listed_date("2020-01-01") == "2020-01-01"
    assert live_db.parse_listed_date("") is None
    assert live_db.parse_listed_date("not-a-date") is None

    assert live_db.exchange_for_code("600000") == "SH"
    assert live_db.exchange_for_code("688981") == "SH"
    assert live_db.exchange_for_code("000001") == "SZ"
    assert live_db.exchange_for_code("300750") == "SZ"
    assert live_db.exchange_for_code("920879") == "BJ"
    assert live_db.exchange_for_code("900901") == "SH"
    assert live_db.exchange_for_code("") == "OTHER"

    assert live_db.board_for_code("600000") == "沪市主板"
    assert live_db.board_for_code("688981") == "科创板"
    assert live_db.board_for_code("000001") == "深市主板"
    assert live_db.board_for_code("300750") == "创业板"
    assert live_db.board_for_code("920879") == "北交所"
    assert live_db.board_for_code("900901") == "其他"


def _universe_fixture():
    return [
        {
            "code": "600000", "name": "浦发银行", "industry": "银行",
            "exchange": "SH", "exchange_label": "沪市", "board": "沪市主板",
            "sector": "1.0", "listed_state": "1.0", "listed_date": "1999-11-10",
            "latest_amount": 100.0, "latest_ifsuspend": 0,
        },
        {
            "code": "000001", "name": "平安银行", "industry": "银行",
            "exchange": "SZ", "exchange_label": "深市", "board": "深市主板",
            "sector": "1.0", "listed_state": "1.0", "listed_date": "1991-04-03",
            "latest_amount": 300.0, "latest_ifsuspend": 0,
        },
        {
            "code": "300750", "name": "宁德时代", "industry": "电池",
            "exchange": "SZ", "exchange_label": "深市", "board": "创业板",
            "sector": "6.0", "listed_state": "1.0", "listed_date": "2018-06-11",
            "latest_amount": 200.0, "latest_ifsuspend": None,
        },
        {
            "code": "688981", "name": "中芯国际", "industry": None,
            "exchange": "SH", "exchange_label": "沪市", "board": "科创板",
            "sector": None, "listed_state": None, "listed_date": "2020-07-16",
            "latest_amount": None, "latest_ifsuspend": None,
        },
    ]


def test_filter_universe_by_industry_market_keyword_and_listed_days():
    from api import live_db

    items = _universe_fixture()
    banks = live_db.filter_universe(items, industries=["银行"])
    assert [item["code"] for item in banks] == ["000001", "600000"]  # 成交额降序

    sz = live_db.filter_universe(items, exchanges=["sz"])
    assert {item["code"] for item in sz} == {"000001", "300750"}

    keyword = live_db.filter_universe(items, q="平安")
    assert [item["code"] for item in keyword] == ["000001"]

    mature = live_db.filter_universe(items, min_listed_days=2000, as_of="2024-01-01")
    assert {item["code"] for item in mature} == {"600000", "000001", "300750"}

    unknown_industry = live_db.filter_universe(items, industries=["银行"], sectors=["6.0"])
    assert unknown_industry == []

    assert live_db.filter_universe(items, industries=[]) == sorted(
        items, key=lambda item: (-(item["latest_amount"] or 0.0), item["code"])
    )
    assert items[0]["code"] == "600000"  # 入参未被排序/修改


def test_aggregate_universe_counts_facets_and_master_coverage():
    from api import live_db

    data = live_db.aggregate_universe(
        _universe_fixture(), master_codes={"600000", "000001"}
    )
    assert data["total"] == 4
    assert data["master_total"] == 2
    assert data["creatable_total"] == 2
    assert data["excluded_total"] == 2
    industries = {item["value"]: item["count"] for item in data["industries"]}
    assert industries == {"银行": 2, "电池": 1}
    assert data["missing"]["industry"] == 1
    assert [item["value"] for item in data["exchanges"]] == ["SH", "SZ"]
    assert [item["value"] for item in data["boards"]] == [
        "沪市主板", "深市主板", "创业板", "科创板",
    ]
    assert [item["value"] for item in data["sectors"]] == ["1.0", "6.0"]


def test_source_label_and_panel_alias():
    from api import live_db

    assert live_db.source_label("last_5years_daily", live_db.DAILY_TABLE) == live_db.DAILY_TABLE
    assert live_db.source_label("stock_main_info_fd", live_db.DIM_TABLE) == live_db.DIM_TABLE
    assert live_db.source_label("", live_db.DIM_TABLE) == live_db.DIM_TABLE
    assert live_db.source_label("computed", live_db.DAILY_TABLE) == "computed"
    assert live_db.panel_alias("vol") == "volume"
    assert live_db.panel_alias("close") == "close"
