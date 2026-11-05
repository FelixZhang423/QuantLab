import { Button, Card, Col, Flex, Progress, Row, Space, Statistic, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { EquityChart } from "../../components/Charts";
import { equityData } from "../results/mock";
import { StatusTag } from "../tasks/TaskCenter";
import type { Task, TaskStatus } from "../tasks/mock";
import type { Page } from "../../app/navigation";

const { Text } = Typography;

function MetricCard({ title, value, suffix, precision = 0, tone = "blue" }: { title: string; value: number; suffix?: string; precision?: number; tone?: string }) {
  return (
    <Card className={`metric-card metric-${tone}`}>
      <Statistic title={title} value={value} suffix={suffix} precision={precision} />
    </Card>
  );
}

export function Dashboard({ tasks, navigate }: { tasks: Task[]; navigate: (p: Page, id?: number) => void }) {
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
        <Col span={12}><Card title="近一年策略净值" extra={<Tag color="blue">基准 +12.4%</Tag>} className="data-card"><EquityChart data={equityData} compact /></Card></Col>
      </Row>
    </Space>
  );
}
