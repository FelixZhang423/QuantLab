import { lazy, Suspense, useState } from "react";
import {
  App as AntApp, Avatar, Breadcrumb, Button, Card, ConfigProvider, Dropdown,
  Flex, Layout, Menu, Skeleton, Space, Tag, Typography,
} from "antd";
import type { MenuProps } from "antd";
import {
  AreaChartOutlined, DatabaseOutlined, ExperimentOutlined,
  FileTextOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SettingOutlined,
  ToolOutlined, UserOutlined,
} from "@ant-design/icons";
import { TaskWorkspace } from "../features/tasks/TaskWorkspace";
import type { Page, PageNav, Role, TaskAdder } from "./navigation";
import { Brand } from "../components/Brand";
import { LoginPage } from "../features/auth";

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
const { Title, Text } = Typography;


function MainShell({ role, onLogout }: { role: Role; onLogout: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [page, setPage] = useState<Page>("tasks");
  const [selectedRunKey, setSelectedRunKey] = useState<string | undefined>();
  const navigate = (target: Page, _id?: number, runKey?: string) => {
    setPage(target === "dashboard" ? "tasks" : target);
    setSelectedRunKey(runKey);
    window.scrollTo(0, 0);
  };
  const addTask: TaskAdder = () => 0;
  const menuItems: MenuProps["items"] = [
    { key: "tasks", icon: <FileTextOutlined />, label: "任务中心" },
    { key: "data", icon: <DatabaseOutlined />, label: "数据配置", children: [
      { key: "data_overview", label: "数据总览" },
      { key: "fields", label: "数据字段" },
      { key: "operators", label: "操作符" },
    ] },
    { key: "stock-group", icon: <DatabaseOutlined />, label: "股票管理", children: [
      { key: "stocks", label: "股票预览" },
      { key: "pools", label: "股票池创建" },
    ] },
    { key: "factor_generation", icon: <ExperimentOutlined />, label: "因子生成" },
    { key: "backtest-group", icon: <AreaChartOutlined />, label: "策略回测", children: [
      { key: "factor_backtest", label: "批量回测" },
      { key: "backtest", label: "单因子回测" },
      { key: "result", label: "回测结果" },
    ] },
    { key: "composition", icon: <ToolOutlined />, label: "组合选股" },
    { key: "system", icon: <SettingOutlined />, label: "系统管理", children: [
      { key: "users", label: "用户与权限" },
      { key: "audit", label: "审计日志" },
    ] },
  ];
  const titles: Record<Page, { title: string; subtitle: string }> = {
    login: { title: "", subtitle: "" },
    dashboard: { title: "任务中心", subtitle: "掌握数据、任务与策略表现" },
    tasks: { title: "任务中心", subtitle: "监控计算任务全生命周期" },
    backtest: { title: "单因子回测", subtitle: "配置 Alpha 表达式与交易参数" },
    result: { title: "回测结果", subtitle: "指标、净值、年度表现与结果文件" },
    data_overview: { title: "数据总览", subtitle: "ClickHouse 数据规模与研究快照" },
    fields: { title: "数据字段", subtitle: "可用于因子表达式的字段" },
    stocks: { title: "股票预览", subtitle: "公司 ClickHouse 股票行情概览" },
    operators: { title: "操作符", subtitle: "Brain 风格表达式算子" },
    pools: { title: "股票池创建", subtitle: "创建与查看命名股票池" },
    factor_generation: { title: "因子生成", subtitle: "PPO 自动搜索可解释因子表达式" },
    factor_backtest: { title: "批量回测", subtitle: "批量回测合格因子" },
    composition: { title: "组合选股", subtitle: "mutual IC 去重 + 权重优化 + 多规模回测" },
    users: { title: "用户与权限", subtitle: "平台账号与角色管理" },
    audit: { title: "审计日志", subtitle: "操作留痕与合规追溯" },
  };
  const profileItems: MenuProps["items"] = [
    { key: "identity", label: <Space><Avatar size="small" icon={<UserOutlined />} /><div><Text strong>林研究员</Text><br/><Text type="secondary">{role}</Text></div></Space>, disabled: true },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: onLogout },
  ];
  const navigatePages: PageNav = (target, id, runKey) => navigate(target as Page, id, runKey);
  const taskWorkspace = <TaskWorkspace navigate={navigatePages} />;
  const pageMap: Record<Exclude<Page, "login">, React.ReactNode> = {
    dashboard: taskWorkspace,
    tasks: taskWorkspace,
    backtest: <ManualBacktestPage onOpenResult={(runKey) => navigate("result", undefined, runKey)} />,
    result: <ResultPage navigate={navigate} initialRunKey={selectedRunKey} />,
    data_overview: <DataOverviewPage addTask={addTask} navigate={navigatePages} />,
    fields: <FieldsPage />,
    stocks: <StocksPage />,
    operators: <OperatorsPage />,
    pools: <PoolsPage addTask={addTask} navigate={navigatePages} />,
    factor_generation: <FactorGenerationPage initialRunId={selectedRunKey} addTask={addTask} navigate={navigatePages} />,
    factor_backtest: <FactorBacktestPage navigate={navigatePages} />,
    composition: <CompositionPage initialResult={page === "composition" && selectedRunKey ? JSON.parse(selectedRunKey) : undefined} addTask={addTask} navigate={navigatePages} />,
    users: <UsersPage role={role} />,
    audit: <AuditPage role={role} />,
  };
  const pageContent = page === "login" ? null : pageMap[page];
  return (
    <Layout className="app-shell">
      <Sider width={220} collapsedWidth={72} collapsed={collapsed} className="app-sider">
        <div className="sider-brand"><Brand light /></div>
        <Menu theme="dark" mode="inline" selectedKeys={[page === "dashboard" ? "tasks" : page]} defaultOpenKeys={["data", "stock-group", "backtest-group"]} items={menuItems} onClick={({ key }) => { if (["dashboard", "tasks", "backtest", "result", "data_overview", "fields", "stocks", "operators", "pools", "factor_generation", "factor_backtest", "composition", "users", "audit"].includes(key)) navigate(key as Page); }} />
        <div className="sider-version">{!collapsed && <Text>QuantLab Prototype</Text>}<Tag>v0.9</Tag></div>
      </Sider>
      <Layout>
        <Header className="top-header">
          <Flex align="center" justify="space-between" className="full-height">
            <Flex align="center" gap={16}>
              <Button type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} />
              <div><Breadcrumb items={[{ title: titles[page].title }]} /><Flex align="baseline" gap={10}><Title level={4}>{titles[page].title}</Title><Text type="secondary">{titles[page].subtitle}</Text></Flex></div>
            </Flex>
            <Space size={18}>
              <Dropdown menu={{ items: profileItems }} placement="bottomRight"><Button type="text" className="profile-button"><Space><Avatar size="small" className="user-avatar">林</Avatar><Text strong>林研究员</Text><Tag color={role === "管理员" ? "gold" : "blue"}>{role}</Tag></Space></Button></Dropdown>
            </Space>
          </Flex>
        </Header>
        <Content className="app-content">
          <Suspense fallback={<Card><Skeleton active paragraph={{ rows: 12 }} /></Card>}>{pageContent}</Suspense>
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
