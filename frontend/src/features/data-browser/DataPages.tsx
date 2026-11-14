import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Descriptions, Flex, Input, Pagination, Progress, Row, Segmented, Select, Skeleton, Space, Statistic, Table, Tag, Tooltip, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
const { Text } = Typography;
import { fieldCategory } from "../../shared/domain/fieldCategories";
import { useApiData } from "../../shared/api/base";
import { dataApi as api, type FieldInfo, type OperatorInfo, type StockInfo } from "./api";
import { LoadGate } from "../../components/LoadGate";
import { FilterChips } from "../../components/FilterChips";
import type { PageNav } from "../../app/navigation";

export type { PageNav } from "../../app/navigation";

const PERIOD_TYPE_LABELS: Record<string, string> = {
  flow: "累计",
  flow_q: "单季",
  stock: "时点",
  ratio: "比率",
  daily: "日频",
  derived: "派生",
};
const fmtInt = (value: number | null | undefined) => (value == null ? "—" : value.toLocaleString("zh-CN"));
const fmtPrice = (value: number | null | undefined) => (value == null ? "—" : value.toFixed(2));

/** 数据总览 / 数据字段 / 股票列表三个页面走数据库实时查询，失败时给出这句提示 */
const LIVE_HINT = "数据预览和股票池筛选查询公司 ClickHouse；因子生成、回测与组合使用不可变 Parquet 快照。首次取数需连接公司网络并配置 ClickHouse。";

const StockDetail = lazy(() => import("./StockDetail").then((module) => ({ default: module.StockDetail })));

/* ============ 数据总览 ============ */

const snapshotTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function formatSnapshotTime(value?: string | null) {
  if (!value) return "—";
  const time = Date.parse(value);
  return Number.isFinite(time) ? snapshotTime.format(time) : "—";
}

function categoryCounts(labels: string[]) {
  const counts = new Map<string, number>();
  for (const label of labels) counts.set(label, (counts.get(label) ?? 0) + 1);
  return [...counts.entries()].map(([label, count]) => ({ label, count }));
}

export function DataOverviewPage({ navigate }: { navigate: PageNav }) {
  const master = useApiData(api.master);
  const fieldCatalog = useApiData(api.fields);
  const operatorCatalog = useApiData(api.operators);
  const fields = fieldCatalog.data?.fields ?? [];
  const operators = operatorCatalog.data?.operators ?? [];
  const catalogs = [
    {
      page: "fields", title: "数据字段总览", state: fieldCatalog, total: fields.length,
      counts: categoryCounts(fields.map((field) => fieldCategory(field).label)),
      usable: fieldCatalog.data ? fields.filter((field) => field.status === "usable" || (field.status == null && field.expression)).length : null,
    },
    {
      page: "operators", title: "操作符总览", state: operatorCatalog, total: operators.length,
      counts: categoryCounts(operators.map((operator) => operator.category_cn || operator.category || "其他")),
      usable: null,
    },
  ];
  const info = master.data;
  const coverage = useApiData(api.universeOptions);
  const options = coverage.data;
  const [dimension, setDimension] = useState<"boards" | "exchanges" | "industries">("boards");
  const coverageRows = [...(options?.[dimension] ?? [])].sort((a, b) => b.count - a.count);
  function refresh() {
    master.reload();
    coverage.reload();
    fieldCatalog.reload();
    operatorCatalog.reload();
  }

  return (
    <Space direction="vertical" size={16} className="page-stack data-overview">
      <section className="data-overview-header">
        <Flex justify="space-between" align="center" gap={12} wrap>
          <Space wrap>
            <Typography.Title level={4}>日线行情</Typography.Title>
            <Tag color="cyan">ClickHouse</Tag>
            {info && <Tag color={info.ready && !master.error ? "green" : "orange"}>
              {master.error ? "上次查询结果" : info.ready ? "数据可用" : "数据未就绪"}
            </Tag>}
          </Space>
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={refresh}
              loading={master.loading || coverage.loading || fieldCatalog.loading || operatorCatalog.loading}>重新查询</Button>
            <Button type="primary" onClick={() => navigate("pools")}>创建股票池</Button>
          </Space>
        </Flex>
        <Row gutter={[16, 16]} className="data-overview-metrics">
          <Col xs={12} xl={6}><Statistic title="日线记录" value={info?.rows ?? "—"} /></Col>
          <Col xs={12} xl={6}><Statistic title="覆盖股票" value={info?.n_stocks ?? "—"} suffix="只" /></Col>
          <Col xs={12} xl={6}><Statistic title="最新行情日" value={info?.date_max ?? "—"} /></Col>
          <Col xs={12} xl={6}><Statistic title="研究快照" value={info?.snapshot_count ?? "—"} suffix="份" /></Col>
        </Row>
        <Flex gap={16} wrap className="data-overview-meta">
          <span>覆盖起点 {info?.date_min ?? "—"}</span>
          <span>查询时间 {info?.queried_at ?? "—"}</span>
          {info?.cached && <span>服务端缓存</span>}
        </Flex>
      </section>
      {master.error && <Alert type="error" showIcon message="行情概览查询失败" description={master.error} />}
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Card title="股票覆盖分布" className="data-card"
            extra={<Button type="link" onClick={() => navigate("stocks")}>股票预览</Button>}>
            <Flex align="center" justify="space-between" gap={8} wrap style={{ marginBottom: 12 }}>
              <Segmented value={dimension} onChange={setDimension} options={[
                { value: "boards", label: "板块" },
                { value: "exchanges", label: "交易所" },
                { value: "industries", label: "行业" },
              ]} />
              <Text type="secondary">候选样本 {fmtInt(options?.total)} 只</Text>
            </Flex>
            <LoadGate state={coverage} hint={LIVE_HINT}>
              <Table size="small" rowKey="value" dataSource={coverageRows}
                pagination={{ pageSize: 6, hideOnSinglePage: true, showSizeChanger: false }}
                columns={[
                  { title: "分类", dataIndex: "label" },
                  { title: "股票数", align: "right", render: (_, item) => fmtInt(item.count) },
                  { title: "占候选样本", width: "42%", render: (_, item) => options?.total
                    ? <Progress size="small" percent={Number((item.count / options.total * 100).toFixed(1))} />
                    : "—" },
                ]} />
            </LoadGate>
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card title="数据源与研究快照" className="data-card">
            <Space direction="vertical" size={16} className="full-width">
              <div>
                <Text type="secondary">行情来源</Text>
                <Typography.Paragraph copyable={info?.store_dir ? { text: info.store_dir } : false}
                  style={{ margin: "4px 0 0", overflowWrap: "anywhere" }}>
                  {info?.store_dir ?? "—"}
                </Typography.Paragraph>
              </div>
              <Row gutter={[16, 12]}>
                <Col span={12}>
                  <Text type="secondary">数据布局</Text>
                  <div>{info?.layout === "clickhouse-live" ? "ClickHouse 实时查询" : info?.layout ?? "—"}</div>
                </Col>
                <Col span={12}>
                  <Text type="secondary">行情字段数</Text>
                  <div>{fmtInt(info?.n_fields)}</div>
                </Col>
              </Row>
              <div style={{ paddingTop: 12, borderTop: "1px solid #f0f0f0" }}>
                <Text type="secondary">最近快照（北京时间）</Text>
                <div><Text strong>{formatSnapshotTime(info?.latest_snapshot_at)}</Text></div>
                <Typography.Paragraph style={{ margin: "8px 0 0" }}>
                  快照保存任务所需的股票、日期区间和字段，供因子生成、回测和组合选股复用。
                  最近快照是版本保存时间，最新行情日是行情对应的交易日期。
                </Typography.Paragraph>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        {catalogs.map(({ page, title, state, total, counts, usable }) => (
          <Col key={page} xs={24} lg={12}>
            <Card title={title} className="data-card" extra={
              <Button type="link" onClick={() => navigate(page)}>查看明细</Button>
            }>
              <LoadGate state={state}>
                <Space direction="vertical" size={16} className="full-width">
                  <Space size={24} wrap>
                    <Statistic title="总数" value={total} />
                    <Statistic title="分类数" value={counts.length} />
                    {usable != null && <Statistic title="可用于表达式" value={usable} />}
                  </Space>
                  <Table size="small" rowKey="label" dataSource={counts} pagination={false}
                    columns={[
                      { title: "分类", dataIndex: "label" },
                      { title: "数量", dataIndex: "count", align: "right", sorter: (a, b) => a.count - b.count },
                      { title: "占比", width: "36%", render: (_, item) =>
                        <Progress size="small" percent={Number((item.count / total * 100).toFixed(1))} /> },
                    ]} />
                </Space>
              </LoadGate>
            </Card>
          </Col>
        ))}
      </Row>
    </Space>
  );
}

/* ============ 数据字段 ============ */

export function FieldsPage() {
  const [category, setCategory] = useState("all");
  const [theme, setTheme] = useState("all");
  const [periodType, setPeriodType] = useState("all");
  const [unit, setUnit] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const fieldsApi = useApiData(api.fields);
  const fields = fieldsApi.data?.fields ?? [];
  const categoryOrder = ["行情与技术", "估值", "财务原始", "财务衍生", "其他"];
  const categories = categoryOrder.filter((item) => fields.some((field) => fieldCategory(field).label === item));
  const categoryFields = category === "all"
    ? fields
    : fields.filter((field) => fieldCategory(field).label === category);
  const themes = [...new Set(categoryFields.map((field) => field.theme).filter(Boolean))].sort() as string[];
  const periodTypes = [...new Set(categoryFields.map((field) => field.period_type).filter(Boolean))].sort() as string[];
  const units = [...new Set(categoryFields.map((field) => field.unit).filter(Boolean))].sort() as string[];

  const filtered = fields
    .filter((field) => {
      if (category !== "all" && fieldCategory(field).label !== category) return false;
      if (theme !== "all" && field.theme !== theme) return false;
      if (periodType !== "all" && field.period_type !== periodType) return false;
      if (unit !== "all" && field.unit !== unit) return false;
      const haystack = `${field.name}${field.description}${field.panel_alias ?? ""}${field.source}${field.theme ?? ""}`.toLowerCase();
      return haystack.includes(search.toLowerCase());
    })
    .sort((a, b) => {
      const categoryDiff = categoryOrder.indexOf(fieldCategory(a).label) - categoryOrder.indexOf(fieldCategory(b).label);
      if (categoryDiff !== 0) return categoryDiff;
      return a.name.localeCompare(b.name);
    });

  const active = category !== "all" || theme !== "all" || periodType !== "all" || unit !== "all" || search !== "";
  const reset = () => {
    setCategory("all");
    setTheme("all");
    setPeriodType("all");
    setUnit("all");
    setSearch("");
    setPage(1);
  };
  const resetCategory = (key: string) => {
    setCategory(key);
    setTheme("all");
    setPeriodType("all");
    setUnit("all");
    setPage(1);
  };

  const columns: TableColumnsType<FieldInfo> = [
    { title: "字段名", dataIndex: "name", width: 200, fixed: "left", sorter: (a, b) => a.name.localeCompare(b.name), render: (v) => <Text code>{v}</Text> },
    {
      title: "分类",
      key: "category",
      width: 110,
      render: (_, record) => {
        const item = fieldCategory(record);
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: "主题",
      dataIndex: "theme",
      width: 130,
      render: (value) => (value ? <Tag color="purple">{value}</Tag> : <Text type="secondary">—</Text>),
    },
    {
      title: "口径",
      key: "period_type",
      width: 90,
      render: (_, record) => (
        record.period_type
          ? <Tag>{PERIOD_TYPE_LABELS[record.period_type] ?? record.period_type}</Tag>
          : <Text type="secondary">—</Text>
      ),
    },
    {
      title: "单位",
      dataIndex: "unit",
      width: 80,
      render: (value) => (value ? <Text>{value}</Text> : <Text type="secondary">—</Text>),
    },
    {
      title: (
        <Tooltip title="因子/回测面板里实际使用的列名；与来源列不同时会加前缀（ROE→fund_ROE、PB→val_PB、vol→volume）。“—”表示暂未接入面板。">
          面板列
        </Tooltip>
      ),
      dataIndex: "panel_alias",
      width: 150,
      render: (v) => (v ? <Text code>{v}</Text> : "—"),
    },
    {
      title: "类型",
      dataIndex: "dtype",
      width: 160,
      ellipsis: true,
      sorter: (a, b) => String(a.dtype ?? "").localeCompare(String(b.dtype ?? "")),
      render: (v) => (v ? <Tag>{v}</Tag> : <Text type="secondary">—</Text>),
    },
    { title: "说明", dataIndex: "description", ellipsis: true },
    { title: "来源", dataIndex: "source", width: 220, ellipsis: true, render: (v) => <Text type="secondary">{v || "未知"}</Text> },
  ];

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex vertical gap={10}>
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>分类</Text>
            <FilterChips
              items={[{ key: "all", label: "全部", count: fields.length }, ...categories.map((item) => ({ key: item, label: item, count: fields.filter((field) => fieldCategory(field).label === item).length }))]}
              value={category}
              onChange={resetCategory}
            />
          </Flex>
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>主题</Text>
            <Select
              size="small"
              value={theme}
              onChange={(value) => { setTheme(value); setPage(1); }}
              style={{ width: 180 }}
              options={[{ value: "all", label: "全部主题" }, ...themes.map((item) => ({ value: item, label: item }))]}
            />
            <Text type="secondary">口径</Text>
            <Select
              size="small"
              value={periodType}
              onChange={(value) => { setPeriodType(value); setPage(1); }}
              style={{ width: 130 }}
              options={[{ value: "all", label: "全部口径" }, ...periodTypes.map((item) => ({ value: item, label: PERIOD_TYPE_LABELS[item] ?? item }))]}
            />
            <Text type="secondary">单位</Text>
            <Select
              size="small"
              value={unit}
              onChange={(value) => { setUnit(value); setPage(1); }}
              style={{ width: 120 }}
              options={[{ value: "all", label: "全部单位" }, ...units.map((item) => ({ value: item, label: item }))]}
            />
          </Flex>
          <Flex justify="space-between" gap={16} wrap align="center">
            <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索字段名 / 说明 / 面板列 / 来源" className="task-search" style={{ width: 380 }} />
            <Flex gap={12} align="center" wrap>
              <Text type="secondary">共 {fieldsApi.data?.total ?? 0} 个字段</Text>
              {active ? <Button size="small" icon={<ReloadOutlined />} onClick={reset}>重置筛选</Button> : null}
            </Flex>
          </Flex>
        </Flex>
      </Card>
      {fieldsApi.data?.offline && (
        <Alert type="warning" showIcon message="数据库元数据暂不可用" description={fieldsApi.data?.metadata_error ?? "字段类型与库校验结果会显示为离线状态。"} />
      )}
      <LoadGate state={fieldsApi} hint={LIVE_HINT}>
        <Card className="data-card">
          <Table
            rowKey="name" size="middle" columns={columns} dataSource={filtered}
            pagination={{
              current: page,
              pageSize,
              total: filtered.length,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: (total) => `共 ${total} 条`,
              onChange: (nextPage, nextSize) => {
                setPage(nextPage);
                if (nextSize !== pageSize) setPageSize(nextSize);
              },
            }}
            scroll={{ x: 1200 }}
          />
        </Card>
      </LoadGate>
    </Space>
  );
}

/* ============ 股票列表 ============ */

export function StocksPage() {
  const [selectedStock, setSelectedStock] = useState<StockInfo | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [suspended, setSuspended] = useState("all");
  const [sort, setSort] = useState({ sort_by: "code", sort_order: "asc" });
  const refreshRequested = useRef(false);
  const optionsApi = useApiData(api.universeOptions);
  useEffect(() => {
    const timer = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  const stocksApi = useApiData(() => {
    const refresh = refreshRequested.current;
    refreshRequested.current = false;
    return api.stocks({ q: query, limit: pageSize, offset: (page - 1) * pageSize,
      ...filters, suspended, ...sort, refresh });
  }, [query, page, pageSize, filters, suspended, sort]);
  const items = stocksApi.data?.items ?? [];
  const columns: TableColumnsType<StockInfo> = [
    { title: "股票代码", dataIndex: "code", width: 110, sorter: true, render: (v, stock) => <Button type="link" size="small" onClick={(event) => { event.stopPropagation(); setSelectedStock(stock); }}>{v}</Button> },
    { title: "名称", dataIndex: "name", width: 140, ellipsis: true, render: (v) => v || "—" },
    { title: "行业", dataIndex: "industry", width: 120 },
    { title: "板块", dataIndex: "board", width: 120 },
    { title: "交易状态", dataIndex: "latest_ifsuspend", width: 110, render: (v) => v === 1 ? <Tag color="orange">停牌</Tag> : v === 0 ? <Tag color="green">正常</Tag> : "未知" },
    { title: "数据行数", dataIndex: "rows", align: "right", sorter: true, render: (v) => fmtInt(v) },
    { title: "起止日期", key: "range", width: 220, render: (_, s) => <Text type="secondary">{s.start_date} ~ {s.end_date}</Text> },
    { title: "最近交易日", dataIndex: "latest_date", width: 120 },
    { title: "最近开盘价", dataIndex: "latest_open", align: "right", render: (v) => fmtPrice(v) },
    { title: "最近收盘价", dataIndex: "latest_close", align: "right", sorter: true, render: (v) => fmtPrice(v) },
    { title: "最近成交量", dataIndex: "latest_volume", align: "right", render: (v) => fmtInt(v) },
    { title: "最近成交额", dataIndex: "latest_amount", align: "right", render: (v) => (v == null ? "—" : `¥${v.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`) },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Row gutter={16}>
        <Col span={8}><Card className="metric-card metric-blue"><Statistic title="全库股票数" value={stocksApi.data?.n_stocks_all ?? 0} suffix="只" /></Card></Col>
        <Col span={8}><Card className="metric-card metric-cyan"><Statistic title="匹配数据行数" value={stocksApi.data?.total_rows ?? 0} /></Card></Col>
        <Col span={8}><Card className="metric-card metric-violet"><Statistic title="匹配股票数" value={stocksApi.data?.total ?? 0} suffix="只" /></Card></Col>
      </Row>
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap>
          <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索股票代码 / 名称" className="task-search" prefix={<SearchOutlined />} />
          <Button icon={<ReloadOutlined />} loading={stocksApi.loading} onClick={() => {
            refreshRequested.current = true; stocksApi.reload(); optionsApi.reload();
          }}>刷新公司数据</Button>
        </Flex>
        <Flex gap={12} wrap style={{ marginTop: 12 }}>
          {(["industries", "exchanges", "boards", "listed_states"] as const).map((key, index) => (
            <Select key={key} mode="multiple" allowClear showSearch optionFilterProp="label"
              placeholder={["行业", "市场", "板块", "上市状态（库内值）"][index]} style={{ minWidth: 170 }}
              value={filters[key] ?? []} loading={optionsApi.loading}
              options={optionsApi.data?.[key].map((option) => ({ value: option.value, label: `${option.label} (${option.count})` }))}
              onChange={(value) => { setFilters((old) => ({ ...old, [key]: value })); setPage(1); }} />
          ))}
          <Select value={suspended} style={{ width: 140 }} onChange={(value) => { setSuspended(value); setPage(1); }}
            options={[{value: "all", label: "全部交易状态"}, {value: "yes", label: "停牌"}, {value: "no", label: "正常交易"}]} />
        </Flex>
        <Text type="secondary">公司 ClickHouse · 查询时间 {stocksApi.data?.queried_at ?? "—"} · {stocksApi.data?.cached ? "缓存命中" : "本次查询更新"} · 缓存有效期 {stocksApi.data?.cache_ttl_seconds ?? "—"} 秒。刷新会绕过服务端缓存；状态以最新记录为准。</Text>
        {optionsApi.error && <Alert type="warning" message="筛选选项读取失败" description={optionsApi.error} />}
      </Card>
      <LoadGate state={stocksApi} hint={LIVE_HINT}>
        <Card className="data-card">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            点击任意一行，查看该股票的日 K 线和历史行情。
          </Typography.Paragraph>
          <Table rowKey="code" size="middle" className="clickable-rows" columns={columns} dataSource={items}
            loading={stocksApi.loading} onRow={(stock) => ({ onClick: () => setSelectedStock(stock) })}
            scroll={{ x: 1700 }} pagination={{ current: page, pageSize, total: stocksApi.data?.total ?? 0,
              showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: (total) => `共 ${total} 只股票` }}
            onChange={(pagination, _, sorter, extra) => {
              if (extra.action === "sort") {
                const selected = Array.isArray(sorter) ? sorter[0] : sorter;
                setSort({ sort_by: selected.order ? String(selected.field) : "code", sort_order: selected.order === "descend" ? "desc" : "asc" });
                setPage(1);
              } else {
                setPage(pagination.pageSize !== pageSize ? 1 : pagination.current ?? 1);
                setPageSize(pagination.pageSize ?? 20);
              }
            }} />
        </Card>
      </LoadGate>
      {selectedStock && <Suspense fallback={<Skeleton active />}>
        <StockDetail key={selectedStock.code} stock={selectedStock} onClose={() => setSelectedStock(null)} />
      </Suspense>}
    </Space>
  );
}

/* ============ 操作符 ============ */

const ALL_OPERATORS = "all";

export function OperatorsPage() {
  const [category, setCategory] = useState<string>(ALL_OPERATORS);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const operatorsApi = useApiData(api.operators);
  const operators = operatorsApi.data?.operators ?? [];
  const categories = [...new Set(operators.map((o) => o.category_cn))];
  const filtered = operators.filter((o) => (category === ALL_OPERATORS || o.category_cn === category) && `${o.name}${o.description_cn}${o.example}`.toLowerCase().includes(search.toLowerCase()));
  const chips = [{ key: ALL_OPERATORS, label: "全部", count: operators.length }, ...categories.map((c) => ({ key: c, label: c, count: operators.filter((o) => o.category_cn === c).length }))];
  const columns: TableColumnsType<OperatorInfo> = [
    { title: "算子名", dataIndex: "name", width: 180, render: (v) => <Text code>{v}</Text> },
    { title: "分类", dataIndex: "category_cn", width: 100, render: (v) => <Tag color="geekblue">{v}</Tag> },
    {
      title: "别名",
      dataIndex: "aliases",
      width: 180,
      ellipsis: true,
      render: (v?: string[]) => (v?.length ? <Text type="secondary">{v.join(" / ")}</Text> : <Text type="secondary">—</Text>),
    },
    { title: "说明", dataIndex: "description_cn", ellipsis: true },
    { title: "示例", dataIndex: "example", width: 260, ellipsis: true, render: (v) => <Text code>{v}</Text> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex vertical gap={12}>
          <FilterChips items={chips} value={category} onChange={(key) => { setCategory(key); setPage(1); }} />
          <Flex justify="space-between" gap={16} wrap align="center">
            <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索算子名 / 说明" className="task-search" />
            <Text type="secondary">
              共 {operators.length} 个去重算子 · PPO 可生成 {operators.filter((operator) => operator.generation_enabled).length} 个
            </Text>
          </Flex>
        </Flex>
      </Card>
      <LoadGate state={operatorsApi}>
        <Card className="data-card">
          <Table rowKey="name" size="middle" columns={columns} dataSource={filtered.slice((page - 1) * 15, page * 15)} pagination={false} />
          <Flex justify="flex-end" className="table-pagination"><Pagination current={page} pageSize={15} total={filtered.length} showSizeChanger={false} onChange={setPage} /></Flex>
        </Card>
      </LoadGate>
    </Space>
  );
}
