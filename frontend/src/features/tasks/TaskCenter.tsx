import { useEffect, useRef, useState } from "react";
import {
  Button, Card, Descriptions, Drawer, Flex, Input, Modal, Pagination, Progress, Select, Space, Table, Tag,
  Typography, message,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  CheckCircleFilled, ClockCircleOutlined, CloseCircleFilled, LoadingOutlined, PlayCircleOutlined,
  ReloadOutlined, SlidersOutlined,
} from "@ant-design/icons";
import { nowStamp, type Task, type TaskStatus } from "./mock";
import type { Page } from "../../app/navigation";

const { Text } = Typography;

const statusMeta: Record<TaskStatus, { label: string; color: string; icon: React.ReactNode }> = {
  queued: { label: "排队中", color: "default", icon: <ClockCircleOutlined /> },
  running: { label: "运行中", color: "processing", icon: <LoadingOutlined spin /> },
  finished: { label: "已完成", color: "success", icon: <CheckCircleFilled /> },
  failed: { label: "失败", color: "error", icon: <CloseCircleFilled /> },
};

export function TaskAlgorithmTag({ task }: { task: Task }) {
  const algorithm = task.params?.algorithm;
  if (algorithm !== "ppo" && algorithm !== "llm") return <Text type="secondary">—</Text>;
  return <Tag color={algorithm === "llm" ? "purple" : "blue"}>{algorithm === "llm" ? "LLM" : "PPO"}</Tag>;
}

export function StatusTag({ status, cancelled = false }: { status: TaskStatus; cancelled?: boolean }) {
  if (cancelled) {
    return <Tag className="status-tag" color="default" icon={<CloseCircleFilled />}>已取消</Tag>;
  }
  const meta = statusMeta[status];
  return <Tag className={`status-tag status-${status}`} color={meta.color} icon={meta.icon}>{meta.label}</Tag>;
}

export function TaskCenter({ tasks, setTasks, focusedId, navigate }: { tasks: Task[]; setTasks: React.Dispatch<React.SetStateAction<Task[]>>; focusedId?: number; navigate: (p: Page, id?: number) => void }) {
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
    { title: "算法", key: "algorithm", width: 80, render: (_, task) => <TaskAlgorithmTag task={task} /> },
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
            { key: "algorithm", label: "生成算法", children: <TaskAlgorithmTag task={openTask} /> },
            {
              key: "engine",
              label: openTask.params?.algorithm === "llm" ? "模型" : "计算设备",
              children: openTask.params?.algorithm === "llm"
                ? String(openTask.params?.model ?? "—")
                : openTask.params?.algorithm === "ppo" ? String(openTask.params?.device ?? "—") : "—",
            },
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
