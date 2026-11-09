import { lazy, Suspense, useEffect, useState } from "react";
import {
  App as AntApp, Avatar, Badge, Breadcrumb, Button, Card, ConfigProvider, Divider, Dropdown,
  Empty, Flex, Layout, Menu, Popover, Result, Skeleton, Space, Tag, Tooltip, Typography,
} from "antd";
import type { MenuProps } from "antd";
import {
  AreaChartOutlined, BellOutlined, DashboardOutlined, DatabaseOutlined, ExperimentOutlined,
  FileTextOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SettingOutlined,
  SlidersOutlined, ToolOutlined, UserOutlined,
} from "@ant-design/icons";
import { initialTasks, nowStamp } from "../features/tasks/mock";
import type { Page, PageNav, Role, TaskAdder } from "./navigation";
import { Brand } from "../components/Brand";
import { LoginPage } from "../features/auth";

const Dashboard = lazy(() => import("../features/dashboard").then((m) => ({ default: m.Dashboard })));
const TaskCenter = lazy(() => import("../features/tasks").then((m) => ({ default: m.TaskCenter })));
const ResultPage = lazy(() => import("../features/results").then((m) => ({ default: m.ResultPage })));
const DataOverviewPage = lazy(() => import("../features/data-browser").then((m) => ({ default: m.DataOverviewPage })));
const FieldsPage = lazy(() => import("../features/data-browser").then((m) => ({ default: m.FieldsPage })));
const StocksPage = lazy(() => import("../features/data-browser").then((m) => ({ default: m.StocksPage })));
const OperatorsPage = lazy(() => import("../features/data-browser").then((m) => ({ default: m.OperatorsPage })));
const PoolsPage = lazy(() => import("../features/pools").then((m) => ({ default: m.PoolsPage })));
const FactorGenerationPage = lazy(() => import("../features/factor-generation").then((m) => ({ default: m.FactorGenerationPage })));
const FactorBacktestPage = lazy(() => import("../features/factor-backtest").then((m) => ({ default: m.FactorBacktestPage })));
const ManualBacktestPage = lazy(() => import("../features/manual-backtest").then((m) => ({ default: m.ManualBacktestPage })));
const CompositionPage = lazy(() => import("../features/composition").then((m) => ({ default: m.CompositionPage })));
const UsersPage = lazy(() => import("../features/system").then((m) => ({ default: m.UsersPage })));
const AuditPage = lazy(() => import("../features/system").then((m) => ({ default: m.AuditPage })));

const { Header, Sider, Content } = Layout;
const { Title, Text, Paragraph } = Typography;


function MainShell({ role, onLogout }: { role: Role; onLogout: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");
  const [selectedTaskId, setSelectedTaskId] = useState<number | undefined>();
  const [selectedRunKey, setSelectedRunKey] = useState<string | undefined>();
  const [tasks, setTasks] = useState(initialTasks);
  const [notifRead, setNotifRead] = useState(false);
  const [demoState, setDemoState] = useState<"normal" | "loading" | "empty" | "error" | "forbidden">("normal");
  const navigate = (target: Page, id?: number, runKey?: string) => {
    setPage(target);
    setSelectedTaskId(id);
    setSelectedRunKey(runKey);
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
    data_overview: { title: "数据总览", subtitle: "ClickHouse 数据规模与研究快照" },
    fields: { title: "数据字段", subtitle: "可用于因子表达式的字段" },
    stocks: { title: "股票列表", subtitle: "公司 ClickHouse 股票行情概览" },
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
    { status: "success" as const, title: "数据已更新", desc: "数据预览来自 ClickHouse，研究任务使用不可变快照" },
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
  const navigatePages: PageNav = (target, id, runKey) => navigate(target as Page, id, runKey);
  const pageMap: Record<Exclude<Page, "login">, React.ReactNode> = {
    dashboard: <Dashboard tasks={tasks} navigate={navigate} />,
    tasks: <TaskCenter tasks={tasks} setTasks={setTasks} focusedId={selectedTaskId} navigate={navigate} />,
    backtest: <ManualBacktestPage onOpenResult={(runKey) => navigate("result", undefined, runKey)} />,
    result: <ResultPage navigate={navigate} initialRunKey={selectedRunKey} />,
    data_overview: <DataOverviewPage addTask={addTask} navigate={navigatePages} />,
    fields: <FieldsPage />,
    stocks: <StocksPage />,
    operators: <OperatorsPage />,
    pools: <PoolsPage addTask={addTask} navigate={navigatePages} />,
    factor_generation: <FactorGenerationPage addTask={addTask} navigate={navigatePages} />,
    factor_backtest: <FactorBacktestPage navigate={navigatePages} />,
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
        <Content className="app-content">
          <Suspense fallback={<Card><Skeleton active paragraph={{ rows: 12 }} /></Card>}>{currentContent}</Suspense>
        </Content>
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
