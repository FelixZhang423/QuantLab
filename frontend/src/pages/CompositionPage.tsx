import { useState } from "react";
import {
  Button, Card, Checkbox, Col, Flex, InputNumber, message, Row, Select, Space, Statistic, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudDownloadOutlined, ExperimentOutlined, PlayCircleOutlined, ToolOutlined } from "@ant-design/icons";
import { nowStamp } from "../mockData";
import { compositionMetrics, compositionSizes, compositionWeights, factorRunOptions, type SizeRow, type WeightRow } from "../mockExtended";
import type { PageNav, TaskAdder } from "./DataPages";

const { Text } = Typography;

export function CompositionPage({ addTask, navigate }: { addTask: TaskAdder; navigate: PageNav }) {
  const [run, setRun] = useState<string>(factorRunOptions[0].value);
  const [sizes, setSizes] = useState<number[]>([10, 20, 30]);
  const [mutualIc, setMutualIc] = useState<number>(0.8);
  const [method, setMethod] = useState<string>("ic_weight");
  const [submitting, setSubmitting] = useState(false);
  const currentRun = factorRunOptions.find((r) => r.value === run)!;
  const submit = () => {
    setSubmitting(true);
    setTimeout(() => {
      const id = addTask({
        type: "compose_factors", typeLabel: "因子组合", name: `compose_${run}_${sizes.join("")}`, status: "queued", progress: 0,
        submittedAt: "刚刚", duration: "—", owner: "林研究员",
        logs: [`[${nowStamp()}] 载入 ${currentRun.factorCount} 个候选因子`, `[${nowStamp()}] 已进入任务队列`],
        params: { run, mutual_ic: mutualIc, weight_method: method, sweep_sizes: sizes },
      });
      setSubmitting(false);
      message.success(`因子组合任务 #${id} 已提交（规模 ${sizes.join(" / ")}）`);
      navigate("tasks", id);
    }, 750);
  };
  const downloadWeights = () => {
    const blob = new Blob([JSON.stringify({ composition: "quality_momentum_v2", method: "ic_weight", weights: compositionWeights }, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "factor_weights.json"; anchor.click(); URL.revokeObjectURL(url);
    message.success("factor_weights.json 已开始下载");
  };
  const weightColumns: TableColumnsType<WeightRow> = [
    { title: "因子", dataIndex: "factor", width: 76, render: (v) => <Text code>{v}</Text> },
    { title: "表达式", dataIndex: "expression", render: (v) => <Text code>{v}</Text> },
    { title: "权重", dataIndex: "weight", align: "right", width: 90, sorter: (a, b) => a.weight - b.weight, render: (v) => <Text strong>{(v * 100).toFixed(0)}%</Text> },
  ];
  const sizeColumns: TableColumnsType<SizeRow> = [
    { title: "组合规模", dataIndex: "size", width: 100, render: (v) => <Tag color="blue">Top {v}</Tag> },
    { title: "年化收益", dataIndex: "annual", align: "right", sorter: (a, b) => a.annual - b.annual, render: (v) => <Text type="success">{v.toFixed(2)}%</Text> },
    { title: "夏普", dataIndex: "sharpe", align: "right" },
    { title: "最大回撤", dataIndex: "drawdown", align: "right", render: (v) => <Text type="danger">{v.toFixed(2)}%</Text> },
    { title: "换手率", dataIndex: "turnover", align: "right", render: (v) => `${v.toFixed(2)}%` },
    { title: "成本", dataIndex: "cost", align: "right", render: (v) => `${v.toFixed(2)}%` },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap align="center">
          <Space wrap>
            <Text strong><ExperimentOutlined /> 因子运行</Text>
            <Select value={run} onChange={setRun} className="factor-run-select" options={factorRunOptions.map((r) => ({ value: r.value, label: r.label }))} />
            <Text strong><ToolOutlined /> 组合规模</Text>
            <Checkbox.Group options={[10, 20, 30].map((s) => ({ label: `Top ${s}`, value: s }))} value={sizes} onChange={(v) => setSizes(v as number[])} />
            <Text strong>mutual IC 阈值</Text>
            <InputNumber min={0} max={1} step={0.05} value={mutualIc} onChange={(v) => setMutualIc(v ?? 0.8)} style={{ width: 84 }} />
            <Text strong>权重方法</Text>
            <Select value={method} onChange={setMethod} className="filter-select" options={[
              { value: "equal", label: "等权" }, { value: "ic_weight", label: "IC 加权" }, { value: "optimized", label: "协方差优化" },
            ]} />
          </Space>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={submitting} disabled={sizes.length === 0} onClick={submit}>提交因子组合</Button>
        </Flex>
      </Card>
      <Card title="最近组合结果（quality_momentum_v2 · #1032）" className="data-card"
        extra={<Space><Button type="link" onClick={() => navigate("tasks", 1032)}>查看任务</Button><Button icon={<CloudDownloadOutlined />} onClick={downloadWeights}>下载权重 JSON</Button></Space>}>
        <Row gutter={12}>
          <Col span={6}><Card className="metric-card metric-green"><Statistic title="组合 IC" value={compositionMetrics.ic} precision={3} /></Card></Col>
          <Col span={6}><Card className="metric-card metric-blue"><Statistic title="组合 RankIC" value={compositionMetrics.rankIc} precision={3} /></Card></Col>
          <Col span={6}><Card className="metric-card metric-violet"><Statistic title="组合 ICIR" value={compositionMetrics.icir} precision={2} /></Card></Col>
          <Col span={6}><Card className="metric-card metric-cyan"><Statistic title="参与因子数" value={compositionMetrics.factors} suffix="个" /></Card></Col>
        </Row>
        <Row gutter={16} className="composition-row">
          <Col span={12}>
            <Text strong>因子权重（mutual IC 去重后）</Text>
            <Table rowKey="factor" size="small" className="composition-table" columns={weightColumns} dataSource={compositionWeights} pagination={false} />
          </Col>
          <Col span={12}>
            <Text strong>多规模组合回测对比</Text>
            <Table rowKey="size" size="small" className="composition-table" columns={sizeColumns} dataSource={compositionSizes} pagination={false} />
          </Col>
        </Row>
      </Card>
    </Space>
  );
}
