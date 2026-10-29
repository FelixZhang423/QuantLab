import { useEffect, useRef, useState } from "react";
import {
  App as AntApp, Avatar, Badge, Breadcrumb, Button, Card, Checkbox, Col, ConfigProvider, Descriptions,
  Divider, Drawer, Dropdown, Empty, Flex, Form, Input, Layout, Menu, message, Modal, Pagination,
  Popover, Progress, Result, Row, Select, Skeleton, Space, Statistic, Table, Tag, Tooltip, Typography,
} from "antd";
import type { MenuProps, TableColumnsType } from "antd";
import {
  AreaChartOutlined, BellOutlined, CheckCircleFilled, ClockCircleOutlined, CloseCircleFilled, CloudDownloadOutlined,
  DashboardOutlined, DatabaseOutlined, ExperimentOutlined, FileTextOutlined, LoadingOutlined,
  LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlayCircleOutlined, ReloadOutlined, SafetyCertificateOutlined,
  SettingOutlined, SlidersOutlined, ToolOutlined, UserOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { EquityChart, YearlyChart } from "./Charts";
import { initialTasks, nowStamp, type Task, type TaskStatus, type YearlyDatum } from "./mockData";
import { api, resultFileUrl, useApiData, type ResultDetail, type ResultSummary } from "./api/client";
import { DataOverviewPage, FieldsPage, OperatorsPage, StocksPage, type PageNav, type PageNavContext, type TaskAdder } from "./pages/DataPages";
import { PoolsPage } from "./pages/PoolsPage";
import { FactorGenerationPage } from "./pages/FactorGenerationPage";
import { FactorBacktestPage } from "./pages/FactorBacktestPage";
import { ManualBacktestPage } from "./pages/ManualBacktestPage";
import { CompositionPage } from "./pages/CompositionPage";
import { AuditPage, UsersPage } from "./pages/SystemPages";

const { Header, Sider, Content } = Layout;
const { Title, Text, Paragraph } = Typography;
type Page = "login" | "dashboard" | "tasks" | "backtest" | "result" | "data_overview" | "fields" | "stocks" | "operators" | "pools" | "factor_generation" | "factor_backtest" | "composition" | "users" | "audit";
type Role = "研究员" | "管理员";

const statusMeta: Record<TaskStatus, { label: string; color: string; icon: React.ReactNode }> = {
  queued: { label: "排队中", color: "default", icon: <ClockCircleOutlined /> },
  running: { label: "运行中", color: "processing", icon: <LoadingOutlined spin /> },
  finished: { label: "已完成", color: "success", icon: <CheckCircleFilled /> },
  failed: { label: "失败", color: "error", icon: <CloseCircleFilled /> },
};

function StatusTag({ status, cancelled = false }: { status: TaskStatus; cancelled?: boolean }) {
  if (cancelled) {
    return <Tag className="status-tag" color="default" icon={<CloseCircleFilled />}>已取消</Tag>;
  }
  const meta = statusMeta[status];
  return <Tag className={`status-tag status-${status}`} color={meta.color} icon={meta.icon}>{meta.label}</Tag>;
}

function Brand({ light = false }: { light?: boolean }) {
  return (
    <Flex align="center" gap={12} className="brand">
      <div className="brand-mark"><AreaChartOutlined /></div>
      <div>
        <Text strong className={light ? "brand-name brand-name-light" : "brand-name"}>QuantLab</Text>
        {!light && <Text className="brand-sub">量化因子研究平台</Text>}
      </div>
    </Flex>
  );
}

function LoginPage({ onLogin }: { onLogin: (role: Role) => void }) {
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const submit = (role: Role = "研究员") => {
    setLoading(true);
    setTimeout(() => { setLoading(false); onLogin(role); message.success(`欢迎回来，${role}`); }, 650);
  };
  return (
    <div className="login-page">
      <div className="login-orb login-orb-a" />
      <div className="login-orb login-orb-b" />
      <Card className="login-card" bordered={false}>
        <Space direction="vertical" size={26} className="full-width">
          <div className="login-heading">
            <Brand />
            <Title level={3}>欢迎登录</Title>
            <Text type="secondary">面向量化研究团队的一站式因子研究与回测平台</Text>
          </div>
          <Form form={form} layout="vertical" initialValues={{ remember: true }} onFinish={() => submit()}>
            <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password size="large" prefix={<SafetyCertificateOutlined />} placeholder="请输入密码" />
            </Form.Item>
            <Flex justify="space-between" align="center" className="login-options">
              <Form.Item name="remember" valuePropName="checked" noStyle><Checkbox>记住我</Checkbox></Form.Item>
              <Button type="link" onClick={() => message.info("请联系系统管理员重置密码")}>忘记密码？</Button>
            </Flex>
            <Button block size="large" type="primary" htmlType="submit" loading={loading}>登录平台</Button>
          </Form>
          <Divider plain><Text type="secondary">演示快捷入口</Text></Divider>
          <Row gutter={12}>
            <Col span={12}><Button block onClick={() => submit("研究员")}>研究员登录</Button></Col>
            <Col span={12}><Button block onClick={() => submit("管理员")}>管理员登录</Button></Col>
          </Row>
        </Space>
      </Card>
      <Text className="login-footer">© 2026 QuantLab · 让每一个因子都经得起验证</Text>
    </div>
  );
}

function MetricCard({ title, value, suffix, precision = 0, tone = "blue" }: { title: string; value: number; suffix?: string; precision?: number; tone?: string }) {
  return (
    <Card className={`metric-card metric-${tone}`}>
      <Statistic title={title} value={value} suffix={suffix} precision={precision} />
    </Card>
  );
}

function Dashboard({ tasks, navigate }: { tasks: Task[]; navigate: (p: Page, id?: number) => void }) {
  const recentColumns: TableColumnsType<Task> = [
    { title: "任务 ID", dataIndex: "id", width: 92, render: (v) => <Text code>#{v}</Text> },
    { title: "类型", dataIndex: "typeLabel", width: 100 },
    { title: "任务名称", dataIndex: "name", ellipsis: true },
    { title: "状态", dataIndex: "status", width: 104, render: (v, r) => <StatusTag status={v} cancelled={r.cancelled} /> },
    { title: "进度", dataIndex: "progress", width: 130, render: (v, r) => <Progress percent={v} size="small" status={r.status === "failed" ? "exception" : r.status === "running" ? "active" : undefined} /> },
    { title: "提交时间", dataIndex: "submittedAt", width: 120 },
    { title: "耗时", dataIndex: "duration", width: 82, align: "right" },
  ];
  const topData = [
    { taskId: 1030, exp: "close / delay(close, 20) - 1", annual: 18.42, sharpe: 1.37, drawdown: -12.6, turnover: 34.2, win: 54.8 },
    { taskId: 1022, exp: "-rank(TurnoverRate)", annual: 16.87, sharpe: 1.29, drawdown: -10.8, turnover: 29.7, win: 53.6 },
    { taskId: 1021, exp: "close / ts_mean(close, 20) - 1", annual: 15.13, sharpe: 1.18, drawdown: -11.4, turnover: 31.2, win: 52.9 },
  ];
  const topColumns: TableColumnsType<(typeof topData)[number]> = [
    { title: "Alpha 表达式", dataIndex: "exp", render: (v) => <Text code>{v}</Text> },
    { title: "年化收益", dataIndex: "annual", align: "right", render: (v) => <Text type="success">{v.toFixed(2)}%</Text>, sorter: (a, b) => a.annual - b.annual },
    { title: "夏普", dataIndex: "sharpe", align: "right" },
    { title: "最大回撤", dataIndex: "drawdown", align: "right", render: (v) => <Text type="danger">{v.toFixed(2)}%</Text> },
    { title: "换手率", dataIndex: "turnover", align: "right", render: (v) => `${v.toFixed(2)}%` },
    { title: "胜率", dataIndex: "win", align: "right", render: (v) => `${v.toFixed(2)}%` },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Row gutter={16}>
        <Col span={6}><MetricCard title="覆盖股票" value={5432} suffix="只" tone="blue" /></Col>
        <Col span={6}><Card className="metric-card metric-violet"><Statistic title="数据区间" value="2021-06-18" suffix={<Text type="secondary">至 2026-06-16</Text>} /></Card></Col>
        <Col span={6}><MetricCard title="有效股票池" value={1} suffix="个" tone="cyan" /></Col>
        <Col span={6}><MetricCard title="运行中任务" value={tasks.filter((t) => t.status === "running").length} suffix="个" tone="orange" /></Col>
      </Row>
      <Row gutter={16}>
        <Col span={16}>
          <Card title="最近任务" extra={<Button type="link" onClick={() => navigate("tasks")}>查看全部</Button>} className="data-card clickable-rows">
            <Table rowKey="id" size="middle" pagination={false} columns={recentColumns} dataSource={tasks.slice(0, 6)}
              onRow={(record) => ({ onClick: () => navigate(record.status === "finished" && record.type.includes("backtest") ? "result" : "tasks", record.id) })} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="任务状态分布" className="data-card status-summary">
            <Space direction="vertical" size={18} className="full-width">
              {(["finished", "running", "queued", "failed"] as TaskStatus[]).map((status) => {
                const count = tasks.filter((t) => t.status === status).length;
                return <div key={status}><Flex justify="space-between"><StatusTag status={status} /><Text strong>{count}</Text></Flex><Progress percent={(count / tasks.length) * 100} showInfo={false} strokeColor={status === "finished" ? "#52c41a" : status === "running" ? "#1677ff" : status === "failed" ? "#ff4d4f" : "#8c8c8c"} /></div>;
              })}
            </Space>
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="Top 回测表现" className="data-card clickable-rows">
            <Table size="small" pagination={false} columns={topColumns} dataSource={topData} rowKey="taskId"
              onRow={(record) => ({ onClick: () => navigate("result", record.taskId) })} />
          </Card>
        </Col>
        <Col span={12}><Card title="近一年策略净值" extra={<Tag color="blue">基准 +12.4%</Tag>} className="data-card"><EquityChart compact /></Card></Col>
      </Row>
    </Space>
  );
}

function TaskCenter({ tasks, setTasks, focusedId, navigate }: { tasks: Task[]; setTasks: React.Dispatch<React.SetStateAction<Task[]>>; focusedId?: number; navigate: (p: Page, id?: number) => void }) {
  const [status, setStatus] = useState<string>("all");
  const [type, setType] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [openTask, setOpenTask] = useState<Task | null>(focusedId ? tasks.find((t) => t.id === focusedId) || null : null);
  const [page, setPage] = useState(1);
  const logRef = useRef<HTMLDivElement>(null);
  const filtered = tasks.filter((t) => (status === "all" || t.status === status) && (type === "all" || t.type === type) && (`${t.id}${t.name}`.toLowerCase().includes(search.toLowerCase())));
  const mutate = (id: number, patch: Partial<Task>) => setTasks((current) => current.map((t) => t.id === id ? { ...t, ...patch } : t));
  const retry = (task: Task) => Modal.confirm({
    title: `确认重试任务 #${task.id}？`, content: "任务将重新进入队列并从头开始执行。",
    onOk: () => { mutate(task.id, { status: "queued", progress: 0, cancelled: false, duration: "—", logs: [...task.logs, `[${nowStamp()}] 用户发起重试，等待资源`] }); message.success("任务已重新入队"); },
  });
  // A1: 从总览/回测/结果页带 focusedId 跳转回来时，重新打开对应任务抽屉
  useEffect(() => {
    if (focusedId !== undefined) {
      const target = tasks.find((t) => t.id === focusedId);
      if (target) setOpenTask(target);
    }
  }, [focusedId, tasks]);
  useEffect(() => { if (openTask) setOpenTask(tasks.find((t) => t.id === openTask.id) || null); }, [tasks]);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [openTask?.logs.length]);
  const columns: TableColumnsType<Task> = [
    { title: "任务 ID", dataIndex: "id", width: 92, sorter: (a, b) => a.id - b.id, render: (v) => <Text code>#{v}</Text> },
    { title: "类型", dataIndex: "typeLabel", width: 108, filters: [...new Map(tasks.map((t) => [t.type, { text: t.typeLabel, value: t.type }])).values()], onFilter: (v, r) => r.type === v },
    { title: "任务名称", dataIndex: "name", ellipsis: true },
    { title: "状态", dataIndex: "status", width: 105, render: (v, r) => <StatusTag status={v} cancelled={r.cancelled} /> },
    { title: "进度", dataIndex: "progress", width: 150, render: (v, r) => <Progress percent={v} size="small" status={r.status === "failed" ? "exception" : r.status === "finished" ? "success" : "active"} /> },
    { title: "提交时间", dataIndex: "submittedAt", width: 118, sorter: (a, b) => a.id - b.id },
    { title: "耗时", dataIndex: "duration", width: 78, align: "right" },
    { title: "操作", key: "action", width: 136, align: "right", render: (_, task) => <Space size={4}>
      <Button type="link" size="small" onClick={() => setOpenTask(task)}>查看</Button>
      {task.status === "finished" && task.type.includes("backtest") && <Button type="link" size="small" onClick={() => navigate("result", task.id)}>结果</Button>}
      {task.status === "failed" && <Button danger type="link" size="small" onClick={() => retry(task)}>重试</Button>}
      {task.status === "queued" && <Button danger type="link" size="small" onClick={() => Modal.confirm({ title: "确认取消该任务？", onOk: () => { mutate(task.id, { status: "failed", cancelled: true, logs: [...task.logs, `[${nowStamp()}] 用户已取消任务`] }); message.success("任务已取消"); } })}>取消</Button>}
    </Space> },
  ];
  const t1029 = tasks.find((t) => t.id === 1029);
  const t1033 = tasks.find((t) => t.id === 1033);
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap>
          <Space wrap>
            <Select value={status} onChange={setStatus} className="filter-select" options={[{ value: "all", label: "全部状态" }, ...Object.entries(statusMeta).map(([value, item]) => ({ value, label: item.label }))]} />
            <Select value={type} onChange={setType} className="filter-select" options={[{ value: "all", label: "全部类型" }, ...new Map(tasks.map((t) => [t.type, { value: t.type, label: t.typeLabel }])).values()]} />
            <Input.Search allowClear value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索任务 ID / 名称" className="task-search" />
            <Button icon={<ReloadOutlined />} onClick={() => message.success("任务列表已刷新")}>刷新</Button>
          </Space>
          <Text type="secondary">共 {filtered.length} 条任务 · 状态每 2 秒同步</Text>
        </Flex>
      </Card>
      <Card className="data-card task-table-card clickable-rows">
        <Table rowKey="id" size="middle" columns={columns} dataSource={filtered.slice((page - 1) * 10, page * 10)} pagination={false}
          rowClassName={(record) => record.id === focusedId ? "highlight-row" : ""} />
        <Flex justify="flex-end" className="table-pagination"><Pagination current={page} pageSize={10} total={filtered.length} showSizeChanger={false} onChange={setPage} /></Flex>
      </Card>
      <Card size="small" title={<Space><SlidersOutlined />原型状态推演控制器<Tag>DEMO ONLY</Tag></Space>} className="simulation-card">
        <Space wrap>
          <Button icon={<PlayCircleOutlined />} disabled={!t1029 || t1029.status !== "queued"}
            onClick={() => mutate(1029, { status: "running", progress: 12, logs: [...(t1029?.logs || []), `[${nowStamp()}] 已分配计算节点 quant-worker-03`] })}>推进 #1029 运行</Button>
          <Button icon={<CheckCircleFilled />} disabled={!t1033 || t1033.status !== "running"}
            onClick={() => mutate(1033, { status: "finished", progress: 100, duration: "4m01s", logs: [...(t1033?.logs || []), `[${nowStamp()}] 完成，结果已保存`] })}>完成 #1033</Button>
          <Button danger icon={<CloseCircleFilled />} disabled={!t1033 || t1033.status !== "running"}
            onClick={() => mutate(1033, { status: "failed", logs: [...(t1033?.logs || []), `[${nowStamp()}] ERROR: 回测执行器异常退出`] })}>使 #1033 失败</Button>
        </Space>
      </Card>
      <Drawer width={520} open={!!openTask} onClose={() => setOpenTask(null)} title={openTask && <Space>任务 <Text code>#{openTask.id}</Text> 详情 <StatusTag status={openTask.status} cancelled={openTask.cancelled} /></Space>}
        extra={openTask?.status === "finished" && openTask.type.includes("backtest") ? <Button type="primary" onClick={() => navigate("result", openTask.id)}>查看结果</Button> : undefined}>
        {openTask && <Space direction="vertical" size={20} className="full-width">
          <Descriptions column={1} size="small" bordered items={[
            { key: "type", label: "任务类型", children: openTask.typeLabel },
            { key: "name", label: "运行名称", children: openTask.name },
            { key: "owner", label: "提交人", children: openTask.owner },
            { key: "time", label: "提交时间", children: `2026-${openTask.submittedAt}` },
            { key: "param", label: "参数摘要", children: <Text code>{openTask.params ? JSON.stringify(openTask.params) : "历史任务，未记录参数"}</Text> },
          ]} />
          <div><Flex justify="space-between"><Text strong>执行进度</Text><Text>{openTask.progress}%</Text></Flex><Progress percent={openTask.progress} status={openTask.status === "failed" && !openTask.cancelled ? "exception" : openTask.status === "finished" ? "success" : "active"} /></div>
          <div><Text strong>实时日志</Text><div className="log-viewer" ref={logRef}>{openTask.logs.map((log, index) => <div key={`${log}-${index}`} className={log.includes("ERROR") ? "log-error" : ""}>{log}</div>)}</div></div>
          {openTask.status === "failed" && <Button danger icon={<ReloadOutlined />} onClick={() => retry(openTask)}>重试任务</Button>}
        </Space>}
      </Drawer>
    </Space>
  );
}

const yearlyColumns: TableColumnsType<YearlyDatum> = [
  { title: "年份", dataIndex: "year" },
  { title: "收益", dataIndex: "returns", align: "right", sorter: (a, b) => a.returns - b.returns, render: (v) => <Text type={v >= 0 ? "danger" : "success"}>{v.toFixed(2)}%</Text> },
  { title: "夏普", dataIndex: "sharpe", align: "right", render: (v) => v.toFixed(2) },
  { title: "最大回撤", dataIndex: "drawdown", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "换手率", dataIndex: "turnover", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "成本", dataIndex: "cost", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "胜率", dataIndex: "winRate", align: "right", render: (v) => `${v.toFixed(2)}%` },
];

function RealMetric({ title, value, suffix = "%", tone }: { title: string; value: number | null; suffix?: string; tone: string }) {
  return (
    <Card className={`metric-card metric-${tone}`}>
      <Statistic title={title} value={value ?? "—"} suffix={value == null ? undefined : suffix} precision={2} />
    </Card>
  );
}

function resultTypeLabel(type: string | null | undefined): string {
  if (type === "manual") return "手动回测";
  if (type === "factor") return "因子回测";
  if (type === "composite") return "因子组合";
  return type ?? "回测";
}

/** 结果 manifest 的数据源：manual 写 clickhouse / clickhouse:...，其余是本地缓存内容哈希 */
function isCompanySource(source: string | null | undefined): boolean {
  return Boolean(source && (source === "clickhouse" || source.startsWith("clickhouse:")));
}

function dataSourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return isCompanySource(source) ? "公司库" : "本地缓存";
}

/** 手动结果把 BacktestConfig 嵌在 config.backtest；因子/组合结果直接平铺在 config */
function splitResultConfig(detail: ResultDetail): { config: Record<string, unknown>; backtest: Record<string, unknown> } {
  const config = detail.config ?? {};
  const nested = config.backtest;
  const backtest = nested && typeof nested === "object" && !Array.isArray(nested)
    ? (nested as Record<string, unknown>)
    : config;
  return { config, backtest };
}

function formatPercentValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : "—";
}

function formatMoney(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `¥${numeric.toLocaleString("zh-CN")}` : "—";
}

function readLocalNote(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

/** 结果详情页顶部的结果切换（只列后端真实结果） */
function ResultSourceSelect({ value, onChange, results }: { value: string; onChange: (value: string) => void; results: ResultSummary[] }) {
  const options = results.map((run) => ({
    value: run.run_key,
    label: `${resultTypeLabel(run.result_type)} · ${run.run_name}${run.created_at ? ` · ${run.created_at.slice(0, 16).replace("T", " ")}` : ""}`,
  }));
  return <Select size="middle" value={value} onChange={onChange} options={options} style={{ minWidth: 360 }} showSearch optionFilterProp="label" placeholder="选择真实结果" />;
}

/** 研究备注：没有后端备注接口，按 run_key 存在本机浏览器，页面明确标注作用域 */
function ResearchNote({ runKey }: { runKey: string }) {
  const storageKey = `quantlab:result-note:${runKey}`;
  const [note, setNote] = useState(() => readLocalNote(storageKey));
  useEffect(() => { setNote(readLocalNote(storageKey)); }, [storageKey]);
  const save = () => {
    try {
      window.localStorage.setItem(storageKey, note);
      message.success("备注已保存到本机浏览器");
    } catch {
      message.error("浏览器存储不可用，备注未保存");
    }
  };
  return (
    <Card title="研究备注" extra={<Text type="secondary">仅保存在本机浏览器</Text>}>
      <Input.TextArea value={note} onChange={(e) => setNote(e.target.value)} autoSize={{ minRows: 3 }} placeholder="记录对这次回测的观察（可选）" />
      <Flex justify="flex-end" className="note-action"><Button type="primary" onClick={save}>保存备注</Button></Flex>
    </Card>
  );
}

/** 真实回测结果视图（数据来自 /api/results/detail） */
function RealResultView({
  detail, results, onSelect, onRefresh,
}: {
  detail: ResultDetail;
  results: ResultSummary[];
  onSelect: (runKey: string) => void;
  onRefresh: () => void;
}) {
  const { config, backtest } = splitResultConfig(detail);
  const factor = config.factor;
  const factorExpression = factor && typeof factor === "object" ? (factor as Record<string, unknown>).expression : null;
  const expression = detail.canonical_expression ?? (typeof factorExpression === "string" ? factorExpression : null);
  const poolText = detail.pool_id ?? "—";
  const rangeText = backtest.start_date && backtest.end_date ? `${String(backtest.start_date)} 至 ${String(backtest.end_date)}` : "—";
  const topkText = backtest.top_k != null ? `TopK ${String(backtest.top_k)}` : "—";
  const capitalText = formatMoney(backtest.initial_cash);
  const sourceText = dataSourceLabel(detail.data_source);
  const isFactor = detail.result_type === "factor";
  const { metrics } = detail;
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="result-hero">
        <Flex justify="space-between" align="start" gap={16}>
          <div>
            <Space wrap>
              <Tag color="green">真实结果</Tag>
              <Tag color="blue">{resultTypeLabel(detail.result_type)}</Tag>
              <Tag>{poolText}</Tag>
              {detail.backtest_id && <Tag color="purple">{isFactor ? "批次" : "任务"} {detail.backtest_id}</Tag>}
              {detail.factor_run_id && <Tag>运行 {detail.factor_run_id}</Tag>}
              {sourceText && <Tag color={isCompanySource(detail.data_source) ? "cyan" : "default"}>{sourceText}</Tag>}
              <Text type="secondary">{detail.created_at?.replace("T", " ") ?? ""}</Text>
            </Space>
            <Title level={3}>{detail.run_name}</Title>
            <Text code>{expression ?? "—"}</Text>
          </div>
          <Space wrap>
            <ResultSourceSelect value={detail.run_key} onChange={onSelect} results={results} />
            <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
          </Space>
        </Flex>
        <Divider />
        <Descriptions size="small" column={4} items={[
          { key: "pool", label: "股票池", children: poolText },
          { key: "range", label: "回测区间", children: rangeText },
          { key: "topk", label: "持仓", children: topkText },
          { key: "capital", label: "初始资金", children: capitalText },
          { key: "buy", label: "买入费率", children: formatPercentValue(backtest.buy_cost) },
          { key: "sell", label: "卖出费率", children: formatPercentValue(backtest.sell_cost) },
          { key: "slippage", label: "滑点", children: formatPercentValue(backtest.slippage) },
          { key: "weight", label: "单票权重上限", children: formatPercentValue(backtest.max_weight_per_stock) },
        ]} />
      </Card>
      <Row gutter={12}>
        <Col span={4}><RealMetric title="年化收益" value={metrics.annual} tone="green" /></Col>
        <Col span={4}><RealMetric title="夏普比率" value={metrics.sharpe} suffix="" tone="blue" /></Col>
        <Col span={4}><RealMetric title="最大回撤" value={metrics.drawdown} tone="red" /></Col>
        <Col span={4}><RealMetric title="换手率" value={metrics.turnover} tone="violet" /></Col>
        <Col span={4}><RealMetric title="交易成本" value={metrics.cost} tone="orange" /></Col>
        <Col span={4}><RealMetric title="胜率" value={metrics.winRate} tone="cyan" /></Col>
      </Row>
      <Row gutter={16}>
        <Col span={15}><Card title="策略净值与回撤" className="data-card">{detail.equity.length > 0 ? <EquityChart data={detail.equity} /> : <Empty description="无每日净值数据" />}</Card></Col>
        <Col span={9}><Card title="年度收益" extra={<Text type="secondary">红涨绿跌</Text>} className="data-card">{detail.yearly.length > 0 ? <YearlyChart data={detail.yearly} /> : <Empty description="无年度指标" />}</Card></Col>
      </Row>
      <Card title="年度指标" className="data-card"><Table rowKey="year" size="middle" pagination={false} columns={yearlyColumns} dataSource={detail.yearly} /></Card>
      <Row gutter={16}>
        <Col span={14}><ResearchNote runKey={detail.run_key} /></Col>
        <Col span={10}>
          <Card title="结果文件" extra={<Text type="secondary">{detail.files.length} 个文件 · 后端真实产物</Text>}>
            <Space wrap>
              {detail.files.map((file) => (
                <Button key={file.name} icon={<CloudDownloadOutlined />} onClick={() => { window.location.href = resultFileUrl(detail.run_key, file.name); }}>
                  {file.name}<Text type="secondary" style={{ marginLeft: 6 }}>{(file.size / 1024).toFixed(1)} KB</Text>
                </Button>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function ResultPage({ navigate, initialRunKey }: { navigate: (p: Page, id?: number) => void; initialRunKey?: string }) {
  const resultsApi = useApiData(api.results);
  const [selectedKey, setSelectedKey] = useState<string | null>(initialRunKey ?? null);
  // 从手动回测/因子批次带 run_key 进入时直接打开；普通导航回到最新真实结果
  useEffect(() => { setSelectedKey(initialRunKey ?? null); }, [initialRunKey]);

  const results = [...(resultsApi.data?.results ?? [])].sort(
    (a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")),
  );
  const detailKey = selectedKey ?? results[0]?.run_key ?? null;
  const detailApi = useApiData(
    () => (detailKey ? api.result(detailKey) : Promise.resolve(null)),
    [detailKey],
  );

  if (!detailKey) {
    if (resultsApi.loading) return <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>;
    if (resultsApi.error) {
      return (
        <Card>
          <Result
            status="warning" title="结果列表加载失败" subTitle={resultsApi.error}
            extra={<Button type="primary" onClick={resultsApi.reload}>重试</Button>}
          />
        </Card>
      );
    }
    return (
      <Card>
        <Empty description="还没有真实回测结果">
          <Space>
            <Button type="primary" onClick={() => navigate("backtest")}>去手动回测</Button>
            <Button onClick={() => navigate("factor_backtest")}>因子回测</Button>
          </Space>
        </Empty>
      </Card>
    );
  }
  if (detailApi.error) {
    return (
      <Card>
        <Result
          status="warning" title="真实结果加载失败" subTitle={detailApi.error}
          extra={<Space><Button onClick={() => navigate("backtest")}>去手动回测</Button><Button type="primary" onClick={detailApi.reload}>重试</Button></Space>}
        />
      </Card>
    );
  }
  if (detailApi.data && detailApi.data.run_key === detailKey) {
    return (
      <RealResultView
        detail={detailApi.data}
        results={results}
        onSelect={setSelectedKey}
        onRefresh={() => { detailApi.reload(); resultsApi.reload(); }}
      />
    );
  }
  return <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>;
}

function MainShell({ role, onLogout }: { role: Role; onLogout: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");
  const [selectedTaskId, setSelectedTaskId] = useState<number | undefined>();
  const [selectedRunKey, setSelectedRunKey] = useState<string | undefined>();
  const [navContext, setNavContext] = useState<PageNavContext | undefined>();
  const [tasks, setTasks] = useState(initialTasks);
  const [notifRead, setNotifRead] = useState(false);
  const [demoState, setDemoState] = useState<"normal" | "loading" | "empty" | "error" | "forbidden">("normal");
  const navigate = (target: Page, id?: number, runKey?: string, context?: PageNavContext) => {
    setPage(target);
    setSelectedTaskId(id);
    setSelectedRunKey(runKey);
    setNavContext(context);
    window.scrollTo(0, 0);
  };
  // 任务调度模拟：queued 自动进入 running，running 按节奏推进（新提交的 #1034 加速演示）
  useEffect(() => {
    const timer = window.setInterval(() => {
      setTasks((current) => current.map((task) => {
        if (task.status === "queued" && !task.cancelled) {
          return { ...task, status: "running", progress: 4, logs: [...task.logs, `[${nowStamp()}] 已分配计算资源，开始执行`] };
        }
        if (task.status !== "running") return task;
        const step = task.id === 1034 ? 35 : 3;
        const progress = Math.min(task.progress + step, 100);
        if (progress === 100) {
          return { ...task, progress, status: "finished", duration: task.id === 1034 ? "3m48s" : task.duration, logs: [...task.logs, `[${nowStamp()}] 完成，结果已保存`] };
        }
        if (task.progress % 12 < step) return { ...task, progress, logs: [...task.logs, `[${nowStamp()}] 计算进度 ${progress}%`] };
        return { ...task, progress };
      }));
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);
  // 新任务自动分配递增 ID，供提交页面跳转高亮
  const addTask: TaskAdder = (task) => {
    const id = task.id ?? Math.max(0, ...tasks.map((t) => t.id)) + 1;
    setTasks((current) => [{ ...task, id }, ...current.filter((t) => t.id !== id)]);
    return id;
  };
  const planned = (label: string, icon?: React.ReactNode) => ({ key: `planned-${label}`, icon, label: <Tooltip title="规划中" placement="right"><Text disabled>{label}</Text></Tooltip>, disabled: true });
  const menuItems: MenuProps["items"] = [
    { key: "dashboard", icon: <DashboardOutlined />, label: "总览" },
    { key: "data", icon: <DatabaseOutlined />, label: "数据", children: [
      { key: "data_overview", label: "数据总览" },
      { key: "fields", label: "数据字段" },
      { key: "stocks", label: "股票列表" },
      { key: "operators", label: "操作符" },
    ] },
    { key: "factor", icon: <ExperimentOutlined />, label: "因子研究", children: [
      { key: "pools", label: "股票池" },
      { key: "factor_generation", label: "因子生成" },
    ] },
    { key: "backtest-group", icon: <AreaChartOutlined />, label: "回测", children: [
      { key: "factor_backtest", label: "因子回测" },
      { key: "backtest", label: "手动回测" },
      { key: "result", label: "结果详情" },
    ] },
    { key: "composition", icon: <ToolOutlined />, label: "组合" },
    { key: "system", icon: <SettingOutlined />, label: "系统管理", children: [
      { key: "users", label: "用户与权限" },
      { key: "audit", label: "审计日志" },
    ] },
    { key: "tasks", icon: <FileTextOutlined />, label: "任务中心" },
  ];
  const titles: Record<Page, { title: string; subtitle: string }> = {
    login: { title: "", subtitle: "" },
    dashboard: { title: "总览", subtitle: "掌握数据、任务与策略表现" },
    tasks: { title: "任务中心", subtitle: "监控计算任务全生命周期" },
    backtest: { title: "手动回测", subtitle: "配置 Alpha 表达式与交易参数" },
    result: { title: "结果详情", subtitle: "指标、净值、年度表现与结果文件" },
    data_overview: { title: "数据总览", subtitle: "主缓存规模与导入任务" },
    fields: { title: "数据字段", subtitle: "可用于因子表达式的字段" },
    stocks: { title: "股票列表", subtitle: "缓存内全部股票概览" },
    operators: { title: "操作符", subtitle: "Brain 风格表达式算子" },
    pools: { title: "股票池", subtitle: "创建与查看命名股票池" },
    factor_generation: { title: "因子生成", subtitle: "PPO 自动搜索可解释因子表达式" },
    factor_backtest: { title: "因子回测", subtitle: "批量回测合格因子" },
    composition: { title: "因子组合", subtitle: "mutual IC 去重 + 权重优化 + 多规模回测" },
    users: { title: "用户与权限", subtitle: "平台账号与角色管理" },
    audit: { title: "审计日志", subtitle: "操作留痕与合规追溯" },
  };
  const profileItems: MenuProps["items"] = [
    { key: "identity", label: <Space><Avatar size="small" icon={<UserOutlined />} /><div><Text strong>林研究员</Text><br/><Text type="secondary">{role}</Text></div></Space>, disabled: true },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: onLogout },
  ];
  const stateItems: MenuProps["items"] = [
    { key: "normal", label: "正常内容" },
    { key: "loading", label: "加载中 · Skeleton" },
    { key: "empty", label: "空数据 · Empty" },
    { key: "error", label: "异常 · 500" },
    { key: "forbidden", label: "无权限 · 403" },
  ];
  // A5: 通知由任务状态派生，不再硬编码
  const runningNotifs = tasks.filter((t) => t.status === "running" && !t.cancelled);
  const failedNotifs = tasks.filter((t) => t.status === "failed" && !t.cancelled);
  const finishedNotif = tasks.filter((t) => t.status === "finished").sort((a, b) => b.id - a.id)[0];
  const notifItems = [
    ...runningNotifs.slice(0, 2).map((t) => ({ status: "processing" as const, title: `任务 #${t.id} 运行中`, desc: `当前进度 ${t.progress}% · ${t.name}` })),
    ...failedNotifs.slice(0, 1).map((t) => ({ status: "error" as const, title: `任务 #${t.id} 执行失败`, desc: t.logs[t.logs.length - 1]?.split("] ")[1] ?? "请查看任务详情" })),
    ...(finishedNotif ? [{ status: "success" as const, title: `任务 #${finishedNotif.id} 已完成`, desc: finishedNotif.name }] : []),
    { status: "success" as const, title: "数据已更新", desc: "主缓存更新至 2026-06-16" },
  ];
  const notifCount = notifRead ? 0 : notifItems.length;
  const notificationContent = <div className="notification-list">
    <Flex justify="space-between"><Text strong>通知中心</Text><Button type="link" size="small" onClick={() => setNotifRead(true)}>全部已读</Button></Flex>
    <Divider />
    <Space direction="vertical" size={14}>
      {notifItems.map((item, index) => (
        <div key={`${item.status}-${index}`}><Badge status={item.status} /><Text strong>{item.title}</Text><Paragraph type="secondary">{item.desc}</Paragraph></div>
      ))}
    </Space>
  </div>;
  const navigatePages: PageNav = (target, id, runKey, context) => navigate(target as Page, id, runKey, context);
  const pageMap: Record<Exclude<Page, "login">, React.ReactNode> = {
    dashboard: <Dashboard tasks={tasks} navigate={navigate} />,
    tasks: <TaskCenter tasks={tasks} setTasks={setTasks} focusedId={selectedTaskId} navigate={navigate} />,
    backtest: <ManualBacktestPage onOpenResult={(runKey) => navigate("result", undefined, runKey)} />,
    result: <ResultPage navigate={navigate} initialRunKey={selectedRunKey} />,
    data_overview: <DataOverviewPage addTask={addTask} navigate={navigatePages} />,
    fields: <FieldsPage />,
    stocks: <StocksPage />,
    operators: <OperatorsPage />,
    pools: <PoolsPage />,
    factor_generation: <FactorGenerationPage navigate={navigatePages} />,
    factor_backtest: (
      <FactorBacktestPage
        navigate={navigatePages}
        initialRunId={navContext?.runId}
        initialCategory={navContext?.category}
      />
    ),
    composition: <CompositionPage addTask={addTask} navigate={navigatePages} />,
    users: <UsersPage role={role} />,
    audit: <AuditPage role={role} />,
  };
  const pageContent = page === "login" ? null : pageMap[page];
  const currentContent = demoState === "normal" ? pageContent
    : demoState === "loading" ? <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>
    : demoState === "empty" ? <Card><Empty description="当前筛选条件下暂无数据"><Button type="primary" onClick={() => { setDemoState("normal"); navigate("backtest"); }}>去提交任务</Button></Empty></Card>
    : demoState === "error" ? <Card><Result status="500" title="页面加载失败" subTitle="服务暂时不可用，请稍后重试" extra={<Button type="primary" onClick={() => setDemoState("normal")}>重新加载</Button>} /></Card>
    : <Card><Result status="403" title="无访问权限" subTitle="当前角色没有访问此页面的权限" extra={<Button type="primary" onClick={() => { setDemoState("normal"); navigate("dashboard"); }}>返回总览</Button>} /></Card>;
  return (
    <Layout className="app-shell">
      <Sider width={220} collapsedWidth={72} collapsed={collapsed} className="app-sider">
        <div className="sider-brand"><Brand light /></div>
        <Menu theme="dark" mode="inline" selectedKeys={[page]} defaultOpenKeys={["data", "factor", "backtest-group"]} items={menuItems} onClick={({ key }) => { if (["dashboard", "tasks", "backtest", "result", "data_overview", "fields", "stocks", "operators", "pools", "factor_generation", "factor_backtest", "composition", "users", "audit"].includes(key)) navigate(key as Page); }} />
        <div className="sider-version">{!collapsed && <Text>QuantLab Prototype</Text>}<Tag>v0.9</Tag></div>
      </Sider>
      <Layout>
        <Header className="top-header">
          <Flex align="center" justify="space-between" className="full-height">
            <Flex align="center" gap={16}>
              <Button type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} />
              <div><Breadcrumb items={page === "result" ? [{ title: "回测结果" }, { title: "结果详情" }] : [{ title: titles[page].title }]} /><Flex align="baseline" gap={10}><Title level={4}>{titles[page].title}</Title><Text type="secondary">{titles[page].subtitle}</Text></Flex></div>
            </Flex>
            <Space size={18}>
              <Dropdown menu={{ items: stateItems, selectable: true, selectedKeys: [demoState], onClick: ({ key }) => setDemoState(key as typeof demoState) }}>
                <Button icon={<SlidersOutlined />}>状态演示</Button>
              </Dropdown>
              <Popover content={notificationContent} trigger="click" placement="bottomRight"><Badge count={notifCount} size="small"><Button type="text" shape="circle" icon={<BellOutlined />} /></Badge></Popover>
              <Dropdown menu={{ items: profileItems }} placement="bottomRight"><Button type="text" className="profile-button"><Space><Avatar size="small" className="user-avatar">林</Avatar><Text strong>林研究员</Text><Tag color={role === "管理员" ? "gold" : "blue"}>{role}</Tag></Space></Button></Dropdown>
            </Space>
          </Flex>
        </Header>
        <Content className="app-content">{currentContent}</Content>
      </Layout>
    </Layout>
  );
}

function RootApp() {
  const [role, setRole] = useState<Role | null>(null);
  return role ? <MainShell role={role} onLogout={() => setRole(null)} /> : <LoginPage onLogin={setRole} />;
}

export default function App() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#1677ff", colorBgLayout: "#f3f6fa", borderRadius: 8, fontFamily: "'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif" }, components: { Layout: { headerBg: "#ffffff", siderBg: "#001529" }, Card: { paddingLG: 18 } } }}>
      <AntApp><RootApp /></AntApp>
    </ConfigProvider>
  );
}
