import { CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Descriptions, Drawer, Flex, Input, Row, Select, Statistic, Table, Tag } from "antd";
import type { PageNav } from "../../app/navigation";
import { apiGet, useApiData } from "../../shared/api/base";

type Job = {
  job_id: string;
  operation: string;
  status: string;
  message?: string;
  stage?: string;
  created_at?: string;
  updated_at?: string;
  parameters: Record<string, unknown>;
  result: { run_key?: string; run_id?: string; backtest_id?: string; composition_id?: string };
};

const operations: Record<string, string> = {
  create_pool: "股票池创建",
  generate_factors: "因子生成",
  confirm_factors: "因子确认",
  backtest_factors: "批量回测",
  manual_backtest: "单因子回测",
  compose_factors: "组合选股",
};

const statuses: Record<string, string> = {
  running: "运行中", queued: "排队中", finished: "已完成", failed: "失败",
};

const colors: Record<string, string> = {
  running: "processing", queued: "default", finished: "success", failed: "error",
};

const cards = [
  { status: "running", icon: SyncOutlined, color: "#1677ff", label: "运行中" },
  { status: "queued", icon: ClockCircleOutlined, color: "#595f78", label: "排队中" },
  { status: "finished", icon: CheckCircleOutlined, color: "#237804", label: "今日完成", today: true },
  { status: "failed", icon: CloseCircleOutlined, color: "#c41d25", label: "今日失败", today: true },
];

const parameterLabels: Record<string, string> = {
  pool_id: "股票池", run_id: "因子运行", start_date: "开始日期",
  end_date: "结束日期", expression: "因子表达式", topk: "持仓数量",
};

function elapsed(job: Job) {
  if (!job.created_at || job.status === "queued") return "—";
  const end = job.status === "running" ? Date.now() : Date.parse(job.updated_at ?? "");
  const seconds = Math.floor((end - Date.parse(job.created_at)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

function isToday(value?: string) {
  return Boolean(value && new Date(value).toDateString() === new Date().toDateString());
}

export function TaskWorkspace({ navigate }: { navigate: PageNav }) {
  const { data, error, loading, reload } = useApiData(() => apiGet<Job[]>("/api/jobs"));
  const [status, setStatus] = useState<string>();
  const [operation, setOperation] = useState<string>();
  const [today, setToday] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string>();
  useEffect(() => {
    if (loading) return;
    const timer = window.setTimeout(reload, 5000);
    return () => window.clearTimeout(timer);
  }, [loading, reload]);

  const jobs = data ?? [];
  const query = search.trim().toLowerCase();
  const visible = jobs.filter((job) =>
    (!query || [job.job_id, operations[job.operation], job.message].some((value) => value?.toLowerCase().includes(query))) &&
    (!status || job.status === status) && (!operation || job.operation === operation) &&
    (!today || isToday(job.updated_at)));
  const detail = jobs.find((job) => job.job_id === selected);
  const resultLink = (job: Job) => {
    if (job.status !== "finished") return null;
    const { backtest_id, composition_id } = job.result;
    if (backtest_id && job.operation === "backtest_factors") {
      return <Button type="link" onClick={() => navigate("result", undefined, `batch:${backtest_id}`)}>查看批次结果</Button>;
    }
    if (composition_id && typeof job.parameters.pool_id === "string" && job.operation === "compose_factors") {
      const key = JSON.stringify([job.parameters.pool_id, composition_id]);
      return <Button type="link" onClick={() => navigate("composition_results", undefined, key)}>查看组合结果</Button>;
    }
    const key = job.result.run_key;
    if (key && job.operation === "manual_backtest") {
      return <Button type="link" onClick={() => navigate("result", undefined, key)}>查看回测结果</Button>;
    }
    if (job.result.run_id && ["generate_factors", "confirm_factors"].includes(job.operation)) {
      return <Button type="link" onClick={() => navigate("factor_generation", undefined, job.result.run_id)}>查看生成结果</Button>;
    }
    return null;
  };

  return <Flex vertical gap={16}>
    {error && <Alert type="error" showIcon message="任务状态获取失败" description={error} />}
    <Row gutter={[12, 12]}>
      {cards.map((card) => <Col key={card.status} xs={12} lg={6}>
        <Button block className="task-status-card" aria-pressed={status === card.status && today === Boolean(card.today)}
          style={{ color: card.color }} disabled={!data}
          onClick={() => {
            const active = status === card.status && today === Boolean(card.today);
            setStatus(active ? undefined : card.status);
            setToday(!active && Boolean(card.today));
          }}>
          <span className="task-status-icon"><card.icon /></span>
          <Statistic title={card.label} value={data ? jobs.filter((job) =>
            job.status === card.status && (!card.today || isToday(job.updated_at))).length : "—"} />
        </Button>
      </Col>)}
    </Row>
    <Card title={<Flex align="center" gap={8}>任务列表{data && <Tag>{visible.length} 条</Tag>}</Flex>}
      extra={<Button icon={<ReloadOutlined />} onClick={reload} loading={loading}>刷新</Button>}>
      <Flex gap={12} wrap style={{ marginBottom: 16 }}>
        <Input.Search allowClear placeholder="搜索任务 ID、类型或运行信息" aria-label="搜索任务"
          value={search} onChange={(event) => setSearch(event.target.value)} style={{ width: 300, maxWidth: "100%" }} />
        <Select allowClear placeholder="全部状态" style={{ width: 150 }} value={status}
          options={Object.entries(statuses).map(([value, label]) => ({ value, label }))}
          onChange={(value) => { setStatus(value); setToday(false); }} />
        <Select allowClear placeholder="全部任务类型" style={{ width: 170 }} value={operation}
          options={Object.entries(operations).map(([value, label]) => ({ value, label }))} onChange={setOperation} />
        {today && <Tag closable onClose={() => setToday(false)}>仅今日更新</Tag>}
      </Flex>
      <Table rowKey="job_id" loading={loading && !data} dataSource={visible} scroll={{ x: 900 }}
        locale={{ emptyText: error && !data ? "任务列表暂不可用" : jobs.length ? "没有匹配的任务" : "暂无任务" }}
        columns={[
          { title: "任务类型", render: (_, job) => operations[job.operation] ?? job.operation },
          { title: "任务 ID", dataIndex: "job_id" },
          { title: "状态", render: (_, job) => <Tag color={colors[job.status]}>{statuses[job.status] ?? job.status}</Tag> },
          { title: "运行阶段", ellipsis: true, render: (_, job) => job.message || job.stage || "—" },
          { title: "提交时间", render: (_, job) => job.created_at?.replace("T", " ") ?? "—" },
          { title: "提交后耗时", render: (_, job) => elapsed(job) },
          { title: "操作", render: (_, job) => <Flex wrap>
            <Button type="link" onClick={() => setSelected(job.job_id)}>详情</Button>{resultLink(job)}
          </Flex> },
        ]} />
    </Card>
    <Drawer title="任务详情" open={Boolean(detail)} onClose={() => setSelected(undefined)}>
      {detail && <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="任务 ID">{detail.job_id}</Descriptions.Item>
        <Descriptions.Item label="任务类型">{operations[detail.operation] ?? detail.operation}</Descriptions.Item>
        <Descriptions.Item label="状态">{statuses[detail.status] ?? detail.status}</Descriptions.Item>
        <Descriptions.Item label={detail.status === "failed" ? "失败原因" : "运行信息"}>{detail.message || "—"}</Descriptions.Item>
        <Descriptions.Item label="提交时间">{detail.created_at?.replace("T", " ") ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="更新时间">{detail.updated_at?.replace("T", " ") ?? "—"}</Descriptions.Item>
        {Object.entries(detail.parameters).map(([key, value]) =>
          <Descriptions.Item key={key} label={parameterLabels[key] ?? key}>{String(value ?? "—")}</Descriptions.Item>)}
        {resultLink(detail) && <Descriptions.Item label="结果">{resultLink(detail)}</Descriptions.Item>}
      </Descriptions>}
    </Drawer>
  </Flex>;
}
