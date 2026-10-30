import { useState } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Descriptions, Flex, Form, Input, InputNumber, message, Pagination, Row, Select, Skeleton, Space, Statistic, Switch, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudUploadOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
const { Text } = Typography;
import { nowStamp, type Task } from "../mockData";
import { api, useApiData, type ApiState, type FieldInfo, type OperatorInfo, type ResultDetail, type StockInfo } from "../api/client";
import { PROTOTYPE_FIELDS } from "../prototypeFields";
import { PROTOTYPE_STOCKS } from "../prototypeStocks";

/** 跨页跳转时夹带的上下文（如从因子生成页带着某个运行/类别去回测） */
export type PageNavContext = {
  runId?: string;
  category?: string;
  /** 来自因子生成工作台的前端原型批次 */
  prototype?: boolean;
  /** 前端原型单因子结果，直接从因子回测表格进入结果详情 */
  prototypeResult?: ResultDetail;
};
export type PageNav = (
  p: string,
  id?: number,
  runKey?: string,
  context?: PageNavContext,
) => void;
export type TaskAdder = (task: Omit<Task, "id"> & { id?: number }) => number;

const fmtInt = (value: number | null | undefined) => (value == null ? "—" : value.toLocaleString("zh-CN"));
const fmtPrice = (value: number | null) => (value == null ? "—" : value.toFixed(2));
const fmtAmount = (value: number | null | undefined) => (
  value == null ? "—" : `¥${value.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`
);

type LiquidityLevel = "high" | "mid" | "low" | "none";

function liquidityLevel(amount: number | null | undefined): {
  key: LiquidityLevel;
  label: string;
  color: string;
} {
  if (amount == null) return { key: "none", label: "无数据", color: "default" };
  if (amount >= 1e9) return { key: "high", label: "高", color: "green" };
  if (amount >= 1e8) return { key: "mid", label: "中", color: "gold" };
  return { key: "low", label: "低", color: "default" };
}

/** 统一处理加载中 / 请求失败 / 正常渲染；hint 用于补充该页特有的失败原因说明 */
export function LoadGate({ state, hint, children }: { state: ApiState<unknown>; hint?: React.ReactNode; children: React.ReactNode }) {
  if (state.loading) return <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>;
  if (state.error) {
    return (
      <Card>
        <Alert
          type="error" showIcon message="数据加载失败"
          description={<Space direction="vertical" size={4}>
            <Text>{state.error}</Text>
            <Text type="secondary">请确认 backend 目录下已运行 <Text code>py -3 -m api</Text>（默认 127.0.0.1:8000）</Text>
            {hint && <Text type="secondary">{hint}</Text>}
          </Space>}
          action={<Button icon={<ReloadOutlined />} onClick={state.reload}>重试</Button>}
        />
      </Card>
    );
  }
  return <>{children}</>;
}

/** 数据总览 / 数据字段 / 股票列表三个页面走数据库实时查询，失败时给出这句提示 */
const LIVE_HINT = "数据总览、字段目录、股票列表、股票池候选、因子面板与回测数据全部直接读公司 ClickHouse：需在公司网络环境下、并已配置 QL_CH_PASSWORD。";

/* ============ 数据总览 ============ */

export function DataOverviewPage({ addTask, navigate }: { addTask: TaskAdder; navigate: PageNav }) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const master = useApiData(api.master);
  const submit = (values: Record<string, unknown>) => {
    setSubmitting(true);
    setTimeout(() => {
      const id = addTask({
        type: "prepare_master", typeLabel: "主缓存导入", name: String(values.name), status: "queued", progress: 0,
        submittedAt: "刚刚", duration: "—", owner: "系统",
        logs: [`[${nowStamp()}] 参数校验通过`, `[${nowStamp()}] 已进入任务队列`],
        params: {
          csv_path: values.csvPath, chunksize: values.chunksize, limit: values.limit || null,
          overwrite: values.overwrite, fields_count: String(values.fields || "").split("\n").filter(Boolean).length,
        },
      });
      setSubmitting(false);
      message.success(`主缓存导入任务 #${id} 已提交`);
      navigate("tasks", id);
    }, 750);
  };
  const info = master.data;
  return (
    <LoadGate state={master} hint={LIVE_HINT}>
      {info && (
        <Space direction="vertical" size={16} className="page-stack">
          <Row gutter={16}>
            <Col span={6}><Card className="metric-card metric-blue"><Statistic title="数据行数" value={info.rows ?? 0} /></Card></Col>
            <Col span={6}><Card className="metric-card metric-cyan"><Statistic title="覆盖股票" value={info.n_stocks ?? 0} suffix="只" /></Card></Col>
            <Col span={6}><Card className="metric-card metric-violet"><Statistic title="数据区间" value={info.date_min ?? "—"} suffix={<Text type="secondary">至 {info.date_max ?? "—"}</Text>} /></Card></Col>
            <Col span={6}><Card className="metric-card metric-orange"><Statistic title="可用字段" value={info.n_fields} suffix="个" /></Card></Col>
          </Row>
          <Card title="实时数据源" className="data-card" extra={<Tag color="success">实时连接正常</Tag>}>
            <Descriptions column={2} size="small" bordered items={[
              { key: "store", label: "数据源", children: <Text code copyable={{ text: info.store_dir }}>{info.store_dir}</Text> },
              { key: "layout", label: "数据布局", children: info.layout ?? "—" },
              { key: "rows", label: "总行数", children: fmtInt(info.rows) },
              { key: "stocks", label: "股票数", children: `${fmtInt(info.n_stocks)} 只` },
              { key: "fields", label: "可用字段", children: `${info.n_fields} 个` },
              { key: "queried", label: "查询时间", children: <Space size={6}><Text code>{info.queried_at ?? "—"}</Text><Tag color={info.cached ? "default" : "green"}>{info.cached ? "60 秒缓存" : "实时查询"}</Tag></Space> },
            ]} />
          </Card>
          <Card title={<Space><CloudUploadOutlined />构建 / 更新主数据缓存<Tag color="warning">第二步接入后端任务</Tag></Space>} className="form-card">
            <Alert type="info" showIcon message="真实导入由 custom_bt 的 prepare_master 任务执行；当前表单仍在本地模拟。股票池、因子生成与回测已改为直接读公司 ClickHouse，不再依赖本地主缓存。" className="page-stack-item" />
            <Form form={form} layout="vertical" onFinish={submit} initialValues={{
              csvPath: "../../../数据/daily_with_maindata_v2.csv", name: "daily_master_import",
              fields: "open\nclose\nhigh\nlow\nvolume\namount\nTurnoverRate", chunksize: 200000, overwrite: false,
            }} className="import-form">
              <Row gutter={12}>
                <Col span={14}><Form.Item label="源 CSV / TSV 路径" name="csvPath" rules={[{ required: true, message: "请输入源数据路径" }]}><Input placeholder="原始日频面板数据路径" /></Form.Item></Col>
                <Col span={5}><Form.Item label="运行名称" name="name" rules={[{ required: true, message: "请输入运行名称" }]}><Input /></Form.Item></Col>
                <Col span={5}><Form.Item label="分块大小（行）" name="chunksize"><InputNumber className="full-width" min={1000} step={10000} /></Form.Item></Col>
              </Row>
              <Form.Item label="导入字段（每行一个，支持逗号分隔）" name="fields" rules={[{ required: true, message: "至少填写一个字段" }]}>
                <Input.TextArea className="code-input" autoSize={{ minRows: 4, maxRows: 8 }} />
              </Form.Item>
              <Flex justify="space-between" align="center">
                <Space>
                  <Form.Item name="overwrite" valuePropName="checked" noStyle><Checkbox>覆盖已有 master 缓存</Checkbox></Form.Item>
                  <Tag color="warning">覆盖会改变数据签名，所有股票池与因子运行将失效</Tag>
                </Space>
                <Button type="primary" htmlType="submit" loading={submitting} icon={<CloudUploadOutlined />}>提交导入任务</Button>
              </Flex>
            </Form>
          </Card>
        </Space>
      )}
    </LoadGate>
  );
}

/** 横铺的筛选标签行（操作符分类 / 字段来源共用）：选中项置灰，未选中为浅色胶囊 */
function FilterChips<T extends string>({ items, value, onChange }: { items: { key: T; label: string; count: number }[]; value: T; onChange: (key: T) => void }) {
  return (
    <Flex gap={8} wrap>
      {items.map(({ key, label, count }) => (
        <Tag.CheckableTag key={key} checked={value === key} className={`category-chip${value === key ? " category-chip-active" : ""}`} onChange={() => onChange(key)}>
          {label}<span className="category-chip-count">{count}</span>
        </Tag.CheckableTag>
      ))}
    </Flex>
  );
}

/* ============ 数据字段 ============ */

const FINANCE_FIELD_SOURCE = "dws.f10_derivative_index_fd";

const FIELD_CATEGORY: Record<string, { label: string; color: string }> = {
  "dws.ll_stock_daily_sharing": { label: "行情与技术", color: "blue" },
  "dws.f10_derivative_index_fd": { label: "财务", color: "purple" },
  "dws.f10_finance_index_fd": { label: "估值", color: "gold" },
  "dim.stock_main_info_fd": { label: "证券信息", color: "cyan" },
  "dim.stock_industry_fd": { label: "行业", color: "geekblue" },
  "dim.stock_sector_info": { label: "板块", color: "orange" },
};

function fieldCategory(field: FieldInfo) {
  return FIELD_CATEGORY[field.source ?? ""] ?? { label: "其他", color: "default" };
}

/** 后端会给出 expression；原型目录没有该字段时，按数值类型推断 */
function fieldExpression(field: FieldInfo): boolean {
  if (field.expression !== undefined) return field.expression;
  return field.dtype !== "String" && field.dtype !== "Date";
}

/** 财务衍生字段的说明以「分组 · 指标」开头，例如「盈利能力 · 加权净资产收益率（TTM，%）」 */
function fieldGroup(field: FieldInfo): string {
  const separator = field.description.indexOf(" · ");
  return separator > 0 ? field.description.slice(0, separator) : "";
}

type ExpressionFilter = "all" | "yes" | "no";

export function FieldsPage() {
  const [source, setSource] = useState<string>("all");
  const [group, setGroup] = useState<string>("all");
  const [dtype, setDtype] = useState<string>("all");
  const [panelOnly, setPanelOnly] = useState(false);
  const [expressionFilter, setExpressionFilter] = useState<ExpressionFilter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const fieldsApi = useApiData(api.fields);
  const apiFields = fieldsApi.data?.fields ?? [];
  const usingPrototype = apiFields.length === 0;
  const fields = usingPrototype ? PROTOTYPE_FIELDS : apiFields;
  const totalCount = usingPrototype ? fields.length : (fieldsApi.data?.total ?? fields.length);
  const sources = [...new Set(fields.map((f) => f.source).filter(Boolean))];
  const dtypes = [...new Set(fields.map((f) => f.dtype).filter(Boolean))].sort();
  const panelCount = fields.filter((f) => f.panel).length;
  const expressionCount = fields.filter(fieldExpression).length;
  const financeCount = fields.filter((f) => f.source === FINANCE_FIELD_SOURCE).length;
  const financeGroups = [...new Set(
    fields.filter((f) => f.source === FINANCE_FIELD_SOURCE).map(fieldGroup).filter(Boolean),
  )];
  const keyword = search.trim().toLowerCase();
  const filtered = fields.filter((f) => {
    if (source !== "all" && f.source !== source) return false;
    if (source === FINANCE_FIELD_SOURCE && group !== "all" && fieldGroup(f) !== group) return false;
    if (dtype !== "all" && f.dtype !== dtype) return false;
    if (panelOnly && !f.panel) return false;
    if (expressionFilter === "yes" && !fieldExpression(f)) return false;
    if (expressionFilter === "no" && fieldExpression(f)) return false;
    if (keyword && !`${f.name}${f.description}${f.source}${f.dtype}`.toLowerCase().includes(keyword)) return false;
    return true;
  });
  const chips = [{ key: "all", label: "全部来源", count: fields.length }, ...sources.map((s) => ({ key: s, label: s, count: fields.filter((f) => f.source === s).length }))];
  const expressionChips: { key: ExpressionFilter; label: string; count: number }[] = [
    { key: "all", label: "全部", count: fields.length },
    { key: "yes", label: "可用", count: expressionCount },
    { key: "no", label: "不可用", count: fields.length - expressionCount },
  ];
  const columns: TableColumnsType<FieldInfo> = [
    { title: "字段名", dataIndex: "name", width: 180, render: (v) => <Text code>{v}</Text> },
    { title: "说明", dataIndex: "description", ellipsis: true },
    { title: "类别", key: "category", width: 110, render: (_, record) => { const cat = fieldCategory(record); return <Tag color={cat.color}>{cat.label}</Tag>; } },
    { title: "因子表达式", key: "expression", width: 110, render: (_, record) => (fieldExpression(record) ? <Tag color="green">可用</Tag> : <Tag>不可用</Tag>) },
    { title: "类型", dataIndex: "dtype", width: 150, render: (v) => <Tag>{v || "—"}</Tag> },
    { title: "可用性", dataIndex: "panel", width: 120, render: (v) => (v ? <Tag color="green">面板可用</Tag> : <Tag>仅数据库</Tag>) },
    { title: "来源", dataIndex: "source", width: 220, ellipsis: true, render: (v) => <Tag color="blue">{v || "未知"}</Tag> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Row gutter={16}>
        <Col span={6}><Card className="metric-card metric-blue"><Statistic title="字段总数" value={totalCount} suffix="个" /></Card></Col>
        <Col span={6}><Card className="metric-card metric-violet"><Statistic title="面板可用" value={panelCount} suffix="个" /></Card></Col>
        <Col span={6}>
          <Card className="metric-card metric-cyan">
            <Statistic
              title={financeCount > 0 ? "财务衍生" : "仅数据库"}
              value={financeCount > 0 ? financeCount : Math.max(0, fields.length - panelCount)}
              suffix="个"
            />
          </Card>
        </Col>
        <Col span={6}><Card className="metric-card metric-orange"><Statistic title="来源表" value={sources.length} suffix="个" /></Card></Col>
      </Row>
      {usingPrototype && (
        <Alert
          type={fieldsApi.error ? "warning" : "info"}
          showIcon
          message={`${fieldsApi.error ? "字段接口暂不可用" : "正在读取公司库字段"}，已展示 ${fields.length} 个内置原型字段`}
          description={<Space direction="vertical" size={4}>
            <Text>原型目录覆盖行情 / 主信息 / 行业 / 板块 89 个字段，以及财务衍生 322 个字段；接口返回后会自动替换为公司库实时目录。</Text>
            {fieldsApi.error && <Space size={8}><Text type="secondary">{fieldsApi.error}</Text><Button size="small" icon={<ReloadOutlined />} onClick={fieldsApi.reload}>重试</Button></Space>}
          </Space>}
        />
      )}
      {!usingPrototype && fields.length < 400 && (
        <Alert
          type="warning"
          showIcon
          message={`接口返回 ${fields.length} 个字段，财务衍生目录尚未接入`}
          description="后端 /api/data/fields 目前只查询行情表与 dim 表。页面按 400+ 字段设计；把 dws.f10_derivative_index_fd（300+ 字段）纳入字段接口后即可完整展示。"
        />
      )}
      <Card className="filter-card">
        <Flex vertical gap={12}>
          <FilterChips items={chips} value={source} onChange={(key) => { setSource(key); setGroup("all"); setPage(1); }} />
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>表达式</Text>
            <FilterChips
              items={expressionChips}
              value={expressionFilter}
              onChange={(key) => { setExpressionFilter(key); setPage(1); }}
            />
          </Flex>
          <Flex justify="space-between" gap={16} wrap align="center">
            <Space wrap size={8}>
              <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索字段名 / 说明 / 类型" className="task-search" />
              <Select
                value={dtype}
                onChange={(value) => { setDtype(value); setPage(1); }}
                style={{ width: 190 }}
                options={[
                  { value: "all", label: "全部数据类型" },
                  ...dtypes.map((value) => ({ value, label: value })),
                ]}
              />
              {source === FINANCE_FIELD_SOURCE && (
                <Select
                  value={group}
                  onChange={(value) => { setGroup(value); setPage(1); }}
                  style={{ width: 170 }}
                  options={[
                    { value: "all", label: "全部分组" },
                    ...financeGroups.map((value) => ({ value, label: value })),
                  ]}
                />
              )}
              <Space size={6}>
                <Switch
                  size="small"
                  checked={panelOnly}
                  onChange={(checked) => { setPanelOnly(checked); setPage(1); }}
                />
                <Text type="secondary">仅面板可用</Text>
              </Space>
            </Space>
            <Space size={8} wrap>
              <Tag color={usingPrototype ? "purple" : "blue"}>{usingPrototype ? "原型字段目录" : "完整字段目录"}</Tag>
              <Text type="secondary">共 {totalCount} 个字段 · 当前筛选 {filtered.length} 个 · {expressionCount} 个可用于因子表达式</Text>
            </Space>
          </Flex>
        </Flex>
      </Card>
      <Card className="data-card">
        <Table
          rowKey="name"
          size="middle"
          columns={columns}
          dataSource={filtered}
          scroll={{ x: 1320, y: 560 }}
          sticky
          pagination={{
            current: page,
            pageSize,
            total: filtered.length,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100],
            showQuickJumper: true,
            showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条 / 共 ${total} 条`,
            onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
          }}
        />
      </Card>
    </Space>
  );
}

/* ============ 股票列表 ============ */

export function StocksPage() {
  const [search, setSearch] = useState("");
  const [industryFilter, setIndustryFilter] = useState<string[]>([]);
  const [liquidity, setLiquidity] = useState<"all" | "high" | "mid" | "low">("all");
  const [minAmountYi, setMinAmountYi] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const stocksApi = useApiData(() => api.stocks());
  const apiItems = stocksApi.data?.items ?? [];
  const usingPrototype = apiItems.length === 0;
  const items = usingPrototype ? PROTOTYPE_STOCKS : apiItems;
  const totalStocks = usingPrototype ? items.length : (stocksApi.data?.n_stocks_all ?? items.length);

  const industryCounts = new Map<string, number>();
  for (const item of items) {
    if (item.industry) industryCounts.set(item.industry, (industryCounts.get(item.industry) ?? 0) + 1);
  }
  const industryOptions = [...industryCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"))
    .map(([value, count]) => ({ value, label: `${value}（${count}）` }));

  const keyword = search.trim();
  const filtered = items.filter((stock) => {
    if (keyword && !stock.code.includes(keyword) && !(stock.name ?? "").includes(keyword)) return false;
    if (industryFilter.length > 0 && (!stock.industry || !industryFilter.includes(stock.industry))) return false;
    const amount = stock.latest_amount ?? 0;
    if (liquidity === "high" && amount < 1e9) return false;
    if (liquidity === "mid" && (amount < 1e8 || amount >= 1e9)) return false;
    if (liquidity === "low" && amount >= 1e8) return false;
    if (minAmountYi != null && minAmountYi > 0 && amount < minAmountYi * 1e8) return false;
    return true;
  });
  const activeFilterCount = (keyword ? 1 : 0)
    + (industryFilter.length > 0 ? 1 : 0)
    + (liquidity !== "all" ? 1 : 0)
    + (minAmountYi != null && minAmountYi > 0 ? 1 : 0);
  const resetFilters = () => {
    setSearch("");
    setIndustryFilter([]);
    setLiquidity("all");
    setMinAmountYi(null);
    setPage(1);
  };
  const highLiquidityCount = items.filter((stock) => (stock.latest_amount ?? 0) >= 1e9).length;

  const columns: TableColumnsType<StockInfo> = [
    { title: "股票代码", dataIndex: "code", width: 110, sorter: (a, b) => a.code.localeCompare(b.code), render: (v) => <Text code>{v}</Text> },
    { title: "名称", dataIndex: "name", width: 140, ellipsis: true, render: (v) => v || "—" },
    { title: "行业", dataIndex: "industry", width: 130, ellipsis: true, render: (v) => (v ? <Tag color="geekblue">{v}</Tag> : <Text type="secondary">—</Text>) },
    {
      title: "流动性",
      key: "liquidity",
      width: 90,
      render: (_, stock) => {
        const level = liquidityLevel(stock.latest_amount);
        return <Tag color={level.color}>{level.label}</Tag>;
      },
    },
    { title: "数据行数", dataIndex: "rows", align: "right", sorter: (a, b) => a.rows - b.rows, render: (v) => fmtInt(v) },
    { title: "起止日期", key: "range", width: 220, render: (_, s) => <Text type="secondary">{s.start_date} ~ {s.end_date}</Text> },
    { title: "最近交易日", dataIndex: "latest_date", width: 120 },
    { title: "最近收盘价", dataIndex: "latest_close", align: "right", sorter: (a, b) => (a.latest_close ?? 0) - (b.latest_close ?? 0), render: (v) => fmtPrice(v) },
    { title: "最近成交量", dataIndex: "latest_volume", align: "right", render: (v) => fmtInt(v) },
    { title: "最近成交额", dataIndex: "latest_amount", align: "right", sorter: (a, b) => (a.latest_amount ?? 0) - (b.latest_amount ?? 0), render: (v) => fmtAmount(v) },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Row gutter={16}>
        <Col span={6}><Card className="metric-card metric-blue"><Statistic title="股票数量" value={totalStocks} suffix="只" /></Card></Col>
        <Col span={6}><Card className="metric-card metric-violet"><Statistic title="当前筛选" value={filtered.length} suffix="只" /></Card></Col>
        <Col span={6}><Card className="metric-card metric-cyan"><Statistic title="高流动性（≥10 亿）" value={highLiquidityCount} suffix="只" /></Card></Col>
        <Col span={6}><Card className="metric-card metric-orange"><Statistic title="覆盖行业" value={industryOptions.length} suffix="个" /></Card></Col>
      </Row>
      {usingPrototype && (
        <Alert
          type={stocksApi.error ? "warning" : "info"}
          showIcon
          message={`${stocksApi.error ? "股票接口暂不可用" : "正在读取公司库股票"}，已展示 ${items.length} 只内置示例股票`}
          description={<Space direction="vertical" size={4}>
            <Text>行情数字取自本地主缓存 2026-06-16 快照，名称与行业为原型标注；接口返回后会自动替换为公司库实时股票列表。</Text>
            {stocksApi.error && <Space size={8}><Text type="secondary">{stocksApi.error}</Text><Button size="small" icon={<ReloadOutlined />} onClick={stocksApi.reload}>重试</Button></Space>}
          </Space>}
        />
      )}
      <Card className="filter-card">
        <Flex vertical gap={10}>
          <Flex justify="space-between" gap={16} wrap align="center">
            <Space wrap size={8}>
              <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索股票代码 / 名称" className="task-search" prefix={<SearchOutlined />} />
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                maxTagCount="responsive"
                value={industryFilter}
                onChange={(values) => { setIndustryFilter(values); setPage(1); }}
                options={industryOptions}
                placeholder="按行业筛选（可多选）"
                style={{ minWidth: 260 }}
              />
              <Select
                value={liquidity}
                onChange={(value) => { setLiquidity(value); setPage(1); }}
                style={{ width: 190 }}
                options={[
                  { value: "all", label: "全部流动性" },
                  { value: "high", label: "高（≥10 亿）" },
                  { value: "mid", label: "中（1–10 亿）" },
                  { value: "low", label: "低（<1 亿）" },
                ]}
              />
              <InputNumber
                value={minAmountYi}
                onChange={(value) => { setMinAmountYi(value); setPage(1); }}
                min={0}
                step={0.1}
                addonAfter="亿元"
                placeholder="最低成交额"
                style={{ width: 170 }}
              />
              <Button icon={<ReloadOutlined />} onClick={resetFilters} disabled={activeFilterCount === 0}>重置</Button>
            </Space>
            <Space size={8}>
              <Tag color={usingPrototype ? "purple" : "blue"}>{usingPrototype ? "原型示例" : "实时数据"}</Tag>
              <Text type="secondary">共 {items.length} 只 · 当前筛选 {filtered.length} 只 · {usingPrototype ? "本地主缓存快照" : "实时聚合 dws.ll_stock_daily_sharing"}</Text>
            </Space>
          </Flex>
          {industryFilter.length > 0 && (
            <Space size={4} wrap>
              <Text type="secondary">已选行业：</Text>
              {industryFilter.map((industry) => (
                <Tag
                  key={industry}
                  closable
                  onClose={() => {
                    setIndustryFilter((current) => current.filter((item) => item !== industry));
                    setPage(1);
                  }}
                >
                  {industry}
                </Tag>
              ))}
              <Button type="link" size="small" onClick={() => { setIndustryFilter([]); setPage(1); }}>清空行业</Button>
            </Space>
          )}
        </Flex>
      </Card>
      <Card className="data-card">
        <Table
          rowKey="code"
          size="middle"
          columns={columns}
          dataSource={filtered}
          scroll={{ x: 1320 }}
          pagination={{
            current: page,
            pageSize,
            total: filtered.length,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100],
            showQuickJumper: true,
            showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条 / 共 ${total} 条`,
            onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
          }}
        />
      </Card>
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
    { title: "算子名", dataIndex: "name", width: 220, render: (v, o) => <Space size={6}><Text code>{v}</Text>{o.generation_enabled && <Tag color="green">可生成</Tag>}</Space> },
    { title: "分类", dataIndex: "category_cn", width: 110, render: (v) => <Tag color="geekblue">{v}</Tag> },
    { title: "说明", dataIndex: "description_cn", ellipsis: true },
    { title: "示例", dataIndex: "example", width: 280, ellipsis: true, render: (v) => <Text code>{v}</Text> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex vertical gap={12}>
          <FilterChips items={chips} value={category} onChange={(key) => { setCategory(key); setPage(1); }} />
          <Flex justify="space-between" gap={16} wrap align="center">
            <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索算子名 / 说明" className="task-search" />
            <Text type="secondary">共 {operatorsApi.data?.total ?? 0} 个算子 · 来自后端 operator_registry</Text>
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
