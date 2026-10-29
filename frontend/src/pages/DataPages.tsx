import { useState } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Descriptions, Flex, Form, Input, InputNumber, message, Pagination, Row, Skeleton, Space, Statistic, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudUploadOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
const { Text } = Typography;
import { nowStamp, type Task } from "../mockData";
import { api, useApiData, type ApiState, type FieldInfo, type OperatorInfo, type StockInfo } from "../api/client";

/** 跨页跳转时夹带的上下文（如从因子生成页带着某个运行/类别去回测） */
export type PageNavContext = {
  runId?: string;
  category?: string;
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

const FIELD_CATEGORY: Record<string, { label: string; color: string }> = {
  "dws.ll_stock_daily_sharing": { label: "行情与技术", color: "blue" },
  "ods_dps_target.lc_maindatanew": { label: "财务", color: "purple" },
  "dws.f10_finance_index_fd": { label: "估值", color: "gold" },
  "dim.stock_main_info_fd": { label: "证券信息", color: "cyan" },
};

function fieldCategory(field: FieldInfo) {
  return FIELD_CATEGORY[field.source ?? ""] ?? { label: "其他", color: "default" };
}

export function FieldsPage() {
  const [source, setSource] = useState("all");
  const [category, setCategory] = useState("all");
  const [usable, setUsable] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const fieldsApi = useApiData(api.fields);
  const fields = fieldsApi.data?.fields ?? [];
  const sources = [...new Set(fields.map((f) => f.source).filter(Boolean))];
  const categories = [...new Set(fields.map((f) => fieldCategory(f).label))];
  const pageSize = 15;

  const filtered = fields.filter((f) => {
    if (source !== "all" && f.source !== source) return false;
    if (category !== "all" && fieldCategory(f).label !== category) return false;
    if (usable === "yes" && !f.expression) return false;
    if (usable === "no" && f.expression) return false;
    return `${f.name}${f.description}${f.source}`.toLowerCase().includes(search.toLowerCase());
  });
  const active = source !== "all" || category !== "all" || usable !== "all" || search !== "";
  const reset = () => {
    setSource("all"); setCategory("all"); setUsable("all"); setSearch(""); setPage(1);
  };

  const columns: TableColumnsType<FieldInfo> = [
    { title: "字段名", dataIndex: "name", width: 190, render: (v) => <Text code>{v}</Text> },
    { title: "说明", dataIndex: "description", ellipsis: true },
    {
      title: "类别",
      key: "category",
      width: 110,
      render: (_, record) => {
        const cat = fieldCategory(record);
        return <Tag color={cat.color}>{cat.label}</Tag>;
      },
    },
    {
      title: "因子表达式",
      dataIndex: "expression",
      width: 110,
      render: (v) => (v ? <Tag color="green">可用</Tag> : <Tag>不可用</Tag>),
    },
    { title: "类型", dataIndex: "dtype", width: 150, ellipsis: true, render: (v) => <Tag>{v || "—"}</Tag> },
    { title: "来源", dataIndex: "source", width: 220, ellipsis: true, render: (v) => <Text type="secondary">{v || "未知"}</Text> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex vertical gap={10}>
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>类别</Text>
            <FilterChips
              items={[
                { key: "all", label: "全部", count: fields.length },
                ...categories.map((c) => ({ key: c, label: c, count: fields.filter((f) => fieldCategory(f).label === c).length })),
              ]}
              value={category}
              onChange={(key) => { setCategory(key); setPage(1); }}
            />
          </Flex>
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>表达式</Text>
            <FilterChips
              items={[
                { key: "all", label: "全部", count: fields.length },
                { key: "yes", label: "可用", count: fields.filter((f) => f.expression).length },
                { key: "no", label: "不可用", count: fields.filter((f) => !f.expression).length },
              ]}
              value={usable}
              onChange={(key) => { setUsable(key); setPage(1); }}
            />
          </Flex>
          <Flex gap={12} align="center" wrap>
            <Text type="secondary" style={{ width: 48 }}>来源</Text>
            <FilterChips
              items={[
                { key: "all", label: "全部", count: fields.length },
                ...sources.map((s) => ({ key: s, label: s, count: fields.filter((f) => f.source === s).length })),
              ]}
              value={source}
              onChange={(key) => { setSource(key); setPage(1); }}
            />
          </Flex>
          <Flex justify="space-between" gap={16} wrap align="center">
            <Input.Search allowClear value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="搜索字段名 / 说明 / 来源" className="task-search" />
            <Flex gap={12} align="center" wrap>
              <Text type="secondary">显示 {filtered.length} / {fieldsApi.data?.total ?? 0} 个字段 · 可用 = 数值字段，可直接写进因子表达式</Text>
              {active ? <Button size="small" icon={<ReloadOutlined />} onClick={reset}>重置筛选</Button> : null}
            </Flex>
          </Flex>
        </Flex>
      </Card>
      <LoadGate state={fieldsApi} hint={LIVE_HINT}>
        <Card className="data-card">
          <Table rowKey="name" size="middle" columns={columns} dataSource={filtered.slice((page - 1) * pageSize, page * pageSize)} pagination={false} />
          <Flex justify="flex-end" className="table-pagination">
            <Pagination current={page} pageSize={pageSize} total={filtered.length} showSizeChanger={false} showTotal={(total) => `共 ${total} 条`} onChange={setPage} />
          </Flex>
        </Card>
      </LoadGate>
    </Space>
  );
}

/* ============ 股票列表 ============ */

export function StocksPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const stocksApi = useApiData(() => api.stocks());
  const items = stocksApi.data?.items ?? [];
  const keyword = search.trim();
  const filtered = items.filter((s) => s.code.includes(keyword) || (s.name ?? "").includes(keyword));
  const columns: TableColumnsType<StockInfo> = [
    { title: "股票代码", dataIndex: "code", width: 110, sorter: (a, b) => a.code.localeCompare(b.code), render: (v) => <Text code>{v}</Text> },
    { title: "名称", dataIndex: "name", width: 140, ellipsis: true, render: (v) => v || "—" },
    { title: "数据行数", dataIndex: "rows", align: "right", sorter: (a, b) => a.rows - b.rows, render: (v) => fmtInt(v) },
    { title: "起止日期", key: "range", width: 220, render: (_, s) => <Text type="secondary">{s.start_date} ~ {s.end_date}</Text> },
    { title: "最近交易日", dataIndex: "latest_date", width: 120 },
    { title: "最近收盘价", dataIndex: "latest_close", align: "right", sorter: (a, b) => (a.latest_close ?? 0) - (b.latest_close ?? 0), render: (v) => fmtPrice(v) },
    { title: "最近成交量", dataIndex: "latest_volume", align: "right", render: (v) => fmtInt(v) },
    { title: "最近成交额", dataIndex: "latest_amount", align: "right", render: (v) => (v == null ? "—" : `¥${v.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`) },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Row gutter={16}>
        <Col span={8}><Card className="metric-card metric-blue"><Statistic title="股票数量" value={stocksApi.data?.n_stocks_all ?? 0} suffix="只" /></Card></Col>
        <Col span={8}><Card className="metric-card metric-cyan"><Statistic title="总数据行数" value={stocksApi.data?.total_rows ?? 0} /></Card></Col>
        <Col span={8}><Card className="metric-card metric-violet"><Statistic title="当前筛选数量" value={filtered.length} suffix="只" /></Card></Col>
      </Row>
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap>
          <Input.Search allowClear value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索股票代码 / 名称" className="task-search" prefix={<SearchOutlined />} />
          <Text type="secondary">实时聚合 dws.ll_stock_daily_sharing（60 秒缓存）· 名称来自 dim.stock_main_info_fd</Text>
        </Flex>
      </Card>
      <LoadGate state={stocksApi} hint={LIVE_HINT}>
        <Card className="data-card">
          <Table rowKey="code" size="middle" columns={columns} dataSource={filtered.slice((page - 1) * 20, page * 20)} pagination={false} />
          <Flex justify="flex-end" className="table-pagination"><Pagination current={page} pageSize={20} total={filtered.length} showSizeChanger={false} onChange={setPage} /></Flex>
        </Card>
      </LoadGate>
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
