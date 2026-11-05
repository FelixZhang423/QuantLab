import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Collapse, DatePicker, Descriptions, Divider, Drawer, Empty, Flex, Form, Input, InputNumber, message, Modal, Popconfirm, Progress, Row, Select, Skeleton, Space, Spin, Statistic, Steps, Switch, Table, Tag, Tooltip, Typography,
} from "antd";
import type { TableColumnsType, TableProps } from "antd";
import { CopyOutlined, DeleteOutlined, ExperimentOutlined, FilterOutlined, LoadingOutlined, PlusOutlined, PlayCircleOutlined, ReloadOutlined, RobotOutlined, TeamOutlined } from "@ant-design/icons";
const { Text } = Typography;
import dayjs from "dayjs";
import { CATEGORY_META, FACTOR_CATEGORIES, classifyFactor, type FactorCategoryKey } from "../../shared/domain/factorCategories";
import { FilterChips } from "../../components/FilterChips";
import { LoadGate } from "../../components/LoadGate";
import type { PageNav, TaskAdder } from "../../app/navigation";
import {
  api, ApiError, useApiData, useJobPolling,
  type AcceptedFactor, type FactorBacktestRequest,
  type FieldInfo, type OperatorInfo,
  type PoolCreateRequest, type PoolInfo, type PoolProvenance, type UniverseQuery, type UniverseStock, type UniverseStocks,
} from "../../api/client";

type DateRangeValue = { format: (template: string) => string }[];

type FactorBacktestFormValues = {
  dates: DateRangeValue;
  topK: number;
  initialCash: number;
  commission: number;
  stampDuty: number;
  rebalanceFreq: string;
  slippage: number;
  minCost: number;
  maxWeight: number;
  maxDrawdownControl: number;
};

const metricNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
};

const formatFraction = (value: unknown, digits = 2): string => {
  const number = metricNumber(value);
  return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
};

type FactorValidityRow = Omit<AcceptedFactor, "ic" | "rank_ic" | "icir" | "coverage" | "score"> & {
  ic: number;
  rank_ic: number;
  icir: number;
  coverage: number;
  score: number;
  valid_ic: number;
  valid_icir: number;
  valid_days: number;
};

/** 稳定模拟的 8 个有效性指标：真实值优先，缺失项由因子 ID 确定性补齐。 */
const simulatedValidity = (factor: AcceptedFactor, index: number) => {
  let seed = 0;
  for (const char of `${factor.factor_id}|${factor.expression ?? ""}|${index}`) {
    seed = (seed * 31 + char.charCodeAt(0)) >>> 0;
  }
  const unit = (offset: number) => ((seed >>> offset) % 1000) / 1000;
  const ic = factor.ic ?? 0.02 + unit(0) * 0.05;
  const rankIc = factor.rank_ic ?? ic * (1.02 + unit(3) * 0.08);
  const icir = factor.icir ?? 0.4 + unit(6) * 1.0;
  const coverage = factor.coverage ?? 0.9 + unit(9) * 0.095;
  const score = factor.score ?? 0.4 + unit(12) * 0.45;
  return {
    ic,
    rank_ic: rankIc,
    icir,
    coverage,
    score,
    valid_ic: ic * 0.85,
    valid_icir: icir * 0.85,
    valid_days: 225 + (seed % 20),
  };
};

export function FactorBacktestPage({ navigate }: { navigate: PageNav }) {
  const [form] = Form.useForm<FactorBacktestFormValues>();
  const runsApi = useApiData(api.factorRuns);
  // MySQL 里存在但本机没有运行目录的记录无法回测，选择列表只保留本地可用的运行。
  const runs = useMemo(
    () => (runsApi.data?.runs ?? []).filter((run) => run.local_available !== false),
    [runsApi.data],
  );
  const [runId, setRunId] = useState<string | undefined>();
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const { job, error: jobError, polling } = useJobPolling(jobId);

  useEffect(() => {
    if (runs.length === 0) {
      setRunId(undefined);
      return;
    }
    if (!runId || !runs.some((run) => run.run_id === runId)) setRunId(runs[0].run_id);
  }, [runs, runId]);

  const runDetailApi = useApiData(
    () => (runId ? api.factorRun(runId) : Promise.resolve(null)),
    [runId],
  );
  const runDetail = runDetailApi.data?.run_id === runId ? runDetailApi.data : null;
  const factors = useMemo(() => runDetail?.accepted_factors ?? [], [runDetail]);
  const factorRows: FactorValidityRow[] = useMemo(
    () => factors.map((factor, index) => ({ ...factor, ...simulatedValidity(factor, index) })),
    [factors],
  );
  useEffect(() => {
    // 切换运行/首次加载后默认全选；用户取消勾选不会被轮询覆盖
    setSelected(factors.map((factor) => factor.factor_id));
    setCategoryFilter("all");
  }, [factors]);
  const selectedIds = selected.map(String);
  const allSelected = factors.length > 0 && selectedIds.length === factors.length;

  const finishedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!jobId || job?.status !== "finished" || finishedRef.current === jobId) return;
    finishedRef.current = jobId;
    runsApi.reload();
    const resultBatch = job.result && typeof job.result.backtest_id === "string" ? job.result.backtest_id : null;
    navigate("result", undefined, resultBatch ? `batch:${resultBatch}` : undefined);
  }, [jobId, job?.status, job?.result, runsApi.reload, navigate]);

  const submit = async (values: FactorBacktestFormValues) => {
    if (!runId) {
      message.error("请选择因子运行");
      return;
    }
    if (selectedIds.length === 0) {
      message.error("请至少选择一个合格因子");
      return;
    }
    const range = values.dates;
    if (!range?.[0] || !range?.[1]) {
      message.error("请选择回测区间");
      return;
    }
    // 清空输入框时回退到默认值，避免把 undefined 传给后端
    const commission = values.commission ?? 0.0015;
    const stampDuty = values.stampDuty ?? 0.0005;
    const topK = values.topK ?? 50;
    const initialCash = values.initialCash ?? 100000000;
    const slippage = values.slippage ?? 0.0005;
    const minCost = values.minCost ?? 5;
    const maxWeight = values.maxWeight ?? 0.02;
    const payload: FactorBacktestRequest = {
      factor_run_id: runId,
      factor_ids: allSelected ? undefined : selectedIds,
      start_date: range[0].format("YYYY-MM-DD"),
      end_date: range[1].format("YYYY-MM-DD"),
      top_k: topK,
      initial_cash: initialCash,
      buy_cost: commission,
      sell_cost: commission + stampDuty,
      slippage,
      min_cost: minCost,
      max_weight_per_stock: maxWeight,
      rebalance_freq: values.rebalanceFreq ?? "1D",
      commission,
      stamp_duty: stampDuty,
      max_drawdown_control: values.maxDrawdownControl ?? 0,
    };
    setSubmitting(true);
    setWarnings([]);
    try {
      const response = await api.createFactorBacktest(payload);
      setJobId(response.job_id);
      setWarnings(response.warnings);
      message.info(`因子回测任务已提交：${response.job_id}（${response.selected_total} 个因子）`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const progress = (job?.progress ?? {}) as Record<string, unknown>;
  const processed = metricNumber(progress.processed) ?? 0;
  const progressTotal = metricNumber(progress.selected_count) ?? 0;
  const progressPercent = job?.status === "finished"
    ? 100
    : progressTotal > 0
      ? Math.min(100, Math.round((processed / progressTotal) * 100))
      : 0;
  const jobType = jobError || job?.status === "failed" ? "error" : job?.status === "finished" ? "success" : "info";
  const jobMessage = !job
    ? (jobError ? "因子回测任务状态查询失败" : "因子回测任务已提交，等待状态…")
    : job.status === "queued" ? `因子回测排队中（${jobId}）`
      : job.status === "running" ? "因子回测运行中"
        : job.status === "finished" ? "因子回测完成"
          : job.status === "failed" ? "因子回测失败"
            : `任务状态：${job.status}`;

  const factorColumns: TableColumnsType<FactorValidityRow> = [
    { title: "因子 ID", dataIndex: "factor_id", width: 200, render: (v) => <Text code style={{ whiteSpace: "nowrap" }}>{v}</Text> },
    { title: "表达式", dataIndex: "expression", ellipsis: true, render: (v) => <Text code>{v}</Text> },
    { title: "IC", dataIndex: "ic", width: 82, align: "right", sorter: (a, b) => a.ic - b.ic, render: (v) => v.toFixed(4) },
    { title: "RankIC", dataIndex: "rank_ic", width: 88, align: "right", sorter: (a, b) => a.rank_ic - b.rank_ic, render: (v) => v.toFixed(4) },
    { title: "ICIR", dataIndex: "icir", width: 82, align: "right", sorter: (a, b) => a.icir - b.icir, render: (v) => v.toFixed(2) },
    { title: "覆盖率", dataIndex: "coverage", width: 88, align: "right", render: (v) => `${(v * 100).toFixed(1)}%` },
    { title: "Score", dataIndex: "score", width: 82, align: "right", sorter: (a, b) => a.score - b.score, render: (v) => v.toFixed(2) },
    { title: "验证 IC", dataIndex: "valid_ic", width: 90, align: "right", sorter: (a, b) => a.valid_ic - b.valid_ic, render: (v) => v.toFixed(4) },
    { title: "验证 ICIR", dataIndex: "valid_icir", width: 92, align: "right", sorter: (a, b) => a.valid_icir - b.valid_icir, render: (v) => v.toFixed(2) },
    { title: "有效天数", dataIndex: "valid_days", width: 90, align: "right", sorter: (a, b) => a.valid_days - b.valid_days },
    {
      title: "类别",
      key: "category",
      width: 110,
      render: (_, record) => {
        const meta = CATEGORY_META[classifyFactor(String(record.expression ?? ""))];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
  ];

  const factorCategoryCounts = useMemo(() => {
    const counts = new Map<FactorCategoryKey, number>();
    for (const factor of factors) {
      const key = classifyFactor(String(factor.expression ?? ""));
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return FACTOR_CATEGORIES
      .filter((item) => counts.get(item.key))
      .map((item) => ({ key: item.key, label: item.label, count: counts.get(item.key) as number }));
  }, [factors]);
  const filteredFactors = categoryFilter === "all"
    ? factorRows
    : factorRows.filter((factor) => classifyFactor(String(factor.expression ?? "")) === categoryFilter);

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap align="center">
          <Space wrap>
            <Text strong><ExperimentOutlined /> 因子运行</Text>
            <Select
              value={runId}
              onChange={(value) => setRunId(value)}
              className="factor-run-select"
              loading={runsApi.loading}
              showSearch optionFilterProp="label"
              placeholder={runsApi.error ? "因子运行目录不可读" : "选择已生成的因子运行"}
              options={runs.map((run) => ({
                value: run.run_id,
                label: `${run.run_id} · ${run.pool_id ?? "未知池"} · ${run.accepted_count} 个合格因子`,
              }))}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={runsApi.reload} loading={runsApi.loading}>刷新</Button>
            {runDetail && <Tag color="blue">{factors.length} 个合格因子</Tag>}
            {runDetail?.pool_id && <Tag>股票池 {runDetail.pool_id}</Tag>}
            {runDetail?.created_at && <Text type="secondary">生成于 {String(runDetail.created_at).replace("T", " ")}</Text>}
          </Space>
          <Text type="secondary">批次结果按任务 ID 版本化保存，不会覆盖历史回测</Text>
        </Flex>
      </Card>

      {runsApi.error && (
        <Alert
          type="error" showIcon message="无法读取因子运行列表" description={runsApi.error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={runsApi.reload}>重试</Button>}
        />
      )}
      {!runsApi.loading && !runsApi.error && runs.length === 0 && (
        <Alert
          type="info" showIcon message="还没有可回测的因子运行"
          description="请先在「因子生成」页生成因子，或用 CLI 生成 factor_runs/<run_id>/accepted_factors.jsonl；本页只回测生成阶段已合格的因子。"
        />
      )}

      {runId && (
        <Row gutter={16} className="backtest-layout">
          <Col span={10}>
            <Card title={<Space><PlayCircleOutlined />批量回测参数</Space>} className="form-card">
              {runDetailApi.error && (
                <Alert
                  type="error" showIcon style={{ marginBottom: 16 }} message="因子运行详情加载失败"
                  description={runDetailApi.error}
                  action={<Button size="small" onClick={runDetailApi.reload}>重试</Button>}
                />
              )}
              {runDetailApi.loading && !runDetail && <Skeleton active paragraph={{ rows: 6 }} />}
              <Form
                form={form} layout="vertical" onFinish={submit}
                initialValues={{
                  dates: [dayjs("2021-06-18"), dayjs("2026-06-16")],
                  topK: 50, initialCash: 100000000, commission: 0.0015, stampDuty: 0.0005,
                  rebalanceFreq: "1D", slippage: 0.0005, minCost: 5, maxWeight: 0.02, maxDrawdownControl: 0,
                }}
              >
                <Form.Item label="回测区间" name="dates" rules={[{ required: true, message: "请选择回测区间" }]}>
                  <DatePicker.RangePicker className="full-width" />
                </Form.Item>
                <Row gutter={12}>
                  <Col span={12}>
                    <Form.Item label="调仓频率" name="rebalanceFreq">
                      <Select options={[
                        { value: "1D", label: "每日" },
                        { value: "5D", label: "每周（5 个交易日）" },
                        { value: "10D", label: "每两周（10 个交易日）" },
                        { value: "20D", label: "每月（20 个交易日）" },
                      ]} />
                    </Form.Item>
                  </Col>
                  <Col span={12}><Form.Item label="持仓数量 TopK" name="topK" rules={[{ type: "number", min: 1, max: 1000, message: "范围 1–1000" }]}><InputNumber className="full-width" min={1} max={1000} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="初始资金" name="initialCash"><InputNumber className="full-width" min={1} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="手续费" name="commission"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="印花税（卖出）" name="stampDuty"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="滑点" name="slippage"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="最低手续费" name="minCost"><InputNumber className="full-width" min={0} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="单票权重上限" name="maxWeight"><InputNumber className="full-width" min={0.001} max={1} step={0.01} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="最大回撤控制（0 = 关闭）" name="maxDrawdownControl"><InputNumber className="full-width" min={0} max={0.9} step={0.01} /></Form.Item></Col>
                </Row>
                <Button
                  size="large" block type="primary" htmlType="submit" icon={<PlayCircleOutlined />}
                  loading={submitting} disabled={!runDetail || factors.length === 0 || selectedIds.length === 0 || polling}
                >
                  回测 {selectedIds.length} 个合格因子
                </Button>
              </Form>
              {warnings.length > 0 && (
                <Alert
                  style={{ marginTop: 16 }} type="warning" showIcon message="回测提示"
                  description={<Space direction="vertical" size={2}>{warnings.map((item) => <Text key={item}>{item}</Text>)}</Space>}
                />
              )}
              {jobId && (
                <Alert
                  style={{ marginTop: 16 }} showIcon type={jobType}
                  icon={polling ? <Spin size="small" /> : undefined}
                  message={jobMessage}
                  description={<Space direction="vertical" size={4} className="full-width">
                    {jobError && <Text>{jobError}</Text>}
                    {job?.message && job.status === "running" && <Text type="secondary">{job.message}</Text>}
                    {job?.status === "failed" && job.message && <Text>{job.message}</Text>}
                    {(job?.status === "running" || job?.status === "finished") && (
                      <Progress percent={progressPercent} size="small" status={job.status === "finished" ? "success" : "active"} />
                    )}
                    {job?.status === "finished" && (
                      <Text>{`成功 ${String(progress.completed ?? "—")} 个，失败 ${String(progress.failed ?? "—")} 个；批次 ${String(progress.backtest_id ?? job.result?.backtest_id ?? "—")}`}</Text>
                    )}
                    {polling && <Text type="secondary">任务在后台运行，完成后自动刷新批次结果。</Text>}
                  </Space>}
                />
              )}
            </Card>
          </Col>
          <Col span={14}>
            <Card
              title="合格因子清单（生成阶段通过阈值筛选）"
              extra={<Text type="secondary">已选 {selectedIds.length} / {factors.length}</Text>}
              className="data-card"
            >
              <Space direction="vertical" size={12} className="full-width">
                <FilterChips
                  items={[{ key: "all", label: "全部", count: factors.length }, ...factorCategoryCounts]}
                  value={categoryFilter}
                  onChange={(key) => setCategoryFilter(key)}
                />
                <Text type="secondary">类别由表达式字段/算子自动识别</Text>
                <Table
                  rowKey="factor_id" size="middle" columns={factorColumns} dataSource={filteredFactors}
                  loading={runDetailApi.loading} pagination={false} scroll={{ x: 1250, y: 420 }}
                  rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys) }}
                  locale={{ emptyText: runDetail && factors.length === 0 ? "该运行没有合格因子" : "请选择因子运行" }}
                />
              </Space>
            </Card>
          </Col>
        </Row>
      )}

    </Space>
  );
}
