import { qualificationReason } from "./validity";
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
import type { PageNav } from "../../app/navigation";
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
  transferFee: number;
  rebalanceFreq: NonNullable<FactorBacktestRequest["rebalance_freq"]>;
  slippage: number;
  minCost: number;
  maxWeight: number;
};

import { compareMetrics, formatMetric, metricNumber, validityRow, isConfirmedRun, confirmedFactors, type FactorValidityRow } from "./validity";

const formatFraction = (value: unknown, digits = 2): string => {
  const number = metricNumber(value);
  return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
};

export function FactorBacktestPage({ navigate }: { navigate: PageNav }) {
  const [form] = Form.useForm<FactorBacktestFormValues>();
  const runsApi = useApiData(api.factorRuns);
  const poolsApi = useApiData(api.pools);
  // 全部运行都展示；MySQL-only 记录保留在列表中但置灰，提示本机缺少运行目录。
  const runs = useMemo(() => runsApi.data?.runs ?? [], [runsApi.data]);
  const availableRuns = useMemo(
    () => runs.filter(isConfirmedRun),
    [runs],
  );
  const [runId, setRunId] = useState<string | undefined>();
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [factorPage, setFactorPage] = useState(1);
  const [factorPageSize, setFactorPageSize] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const { job, error: jobError, polling } = useJobPolling(jobId);

  useEffect(() => {
    if (availableRuns.length === 0) {
      setRunId(undefined);
      return;
    }
    if (!runId || !availableRuns.some((run) => run.run_id === runId)) {
      setRunId(availableRuns[0].run_id);
    }
  }, [availableRuns, runId]);

  const runDetailApi = useApiData(
    () => (runId ? api.factorRun(runId) : Promise.resolve(null)),
    [runId],
  );
  const runDetail = runDetailApi.data?.run_id === runId ? runDetailApi.data : null;
  const poolId = runDetail?.pool_id ?? runs.find((run) => run.run_id === runId)?.pool_id;
  const pool = poolsApi.data?.pools.find((item) => item.pool_id === poolId);
  const selectionStart = pool?.selection_start;
  const selectionEnd = pool?.selection_end;
  useEffect(() => {
    form.setFieldValue("dates", selectionStart && selectionEnd
      ? [dayjs(selectionStart), dayjs(selectionEnd)] : undefined);
  }, [form, runId, poolId, selectionStart, selectionEnd]);
  const factors = useMemo(() => confirmedFactors(runDetail), [runDetail]);
  const factorRows: FactorValidityRow[] = useMemo(
    () => factors.map(validityRow),
    [factors],
  );
  useEffect(() => {
    // 切换运行/首次加载后默认全选；用户取消勾选不会被轮询覆盖
    setSelected(factors.map((factor) => factor.factor_id));
    setCategoryFilter("all");
    setFactorPage(1);
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
    const commission = values.commission ?? 0.0003;
    const stampDuty = values.stampDuty ?? 0.0005;
    const transferFee = values.transferFee ?? 0.00001;
    const topK = values.topK ?? 50;
    const initialCash = values.initialCash ?? 100000000;
    const slippage = values.slippage ?? 0.001;
    const minCost = values.minCost ?? 5;
    const maxWeight = values.maxWeight ?? 0.03;
    const payload: FactorBacktestRequest = {
      factor_run_id: runId,
      factor_ids: allSelected ? undefined : selectedIds,
      start_date: range[0].format("YYYY-MM-DD"),
      end_date: range[1].format("YYYY-MM-DD"),
      top_k: topK,
      initial_cash: initialCash,
      slippage,
      min_cost: minCost,
      max_weight_per_stock: maxWeight,
      rebalance_freq: values.rebalanceFreq ?? "1D",
      commission,
      stamp_duty: stampDuty,
      transfer_fee: transferFee,
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
    { title: "因子 ID", dataIndex: "factor_id", width: 180, ellipsis: true, render: (v) => <Tooltip title={v}><Text code ellipsis>{v}</Text></Tooltip> },
    { title: "表达式", dataIndex: "expression", width: 260, ellipsis: true, render: (v) => <Tooltip title={v}><Text code ellipsis copyable>{v}</Text></Tooltip> },
    { title: "测试 IC", dataIndex: "test_ic", width: 110, align: "right", sorter: (a, b) => compareMetrics(a.test_ic, b.test_ic), render: (v) => formatMetric(v, 4) },
    { title: "测试 RankIC", dataIndex: "test_rank_ic", width: 110, align: "right", sorter: (a, b) => compareMetrics(a.test_rank_ic, b.test_rank_ic), render: (v) => formatMetric(v, 4) },
    { title: "测试 ICIR", dataIndex: "test_icir", width: 110, align: "right", sorter: (a, b) => compareMetrics(a.test_icir, b.test_icir), render: (v) => formatMetric(v, 2) },
    { title: "测试覆盖率", dataIndex: "test_coverage", width: 110, align: "right", sorter: (a, b) => compareMetrics(a.test_coverage, b.test_coverage), render: (v) => formatFraction(v, 1) },
    { title: "测试有效天数", dataIndex: "test_days", width: 110, align: "right", sorter: (a, b) => compareMetrics(a.test_days, b.test_days), render: (v) => formatMetric(v, 0) },
    { title: "合格原因", key: "qualification", width: 240, ellipsis: true, render: (_, record) => <Tooltip title={qualificationReason(record, (runDetail?.hyperparameters?.quality ?? {}) as Record<string, unknown>)}><Text ellipsis>{qualificationReason(record, (runDetail?.hyperparameters?.quality ?? {}) as Record<string, unknown>)}</Text></Tooltip> },
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
              options={runs.map((run) => {
                const available = isConfirmedRun(run);
                return {
                  value: run.run_id,
                  disabled: !available,
                  label: `${run.run_id} · ${run.pool_id ?? "未知池"} · ${run.confirmed_count ?? 0} 个合格因子${available ? "" : " · 尚未完成确认或本机缺少运行目录"}`,
                };
              })}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={runsApi.reload} loading={runsApi.loading}>刷新</Button>
            {runs.length > 0 && (
              <Tag color={availableRuns.length > 0 ? "blue" : "orange"}>
                {availableRuns.length}/{runs.length} 条本机可回测
              </Tag>
            )}
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
          description="请先在「因子生成」页生成因子，或用 CLI 生成 factor_runs/<run_id>/confirmed_factors.jsonl；本页只回测测试集确认后的因子。"
        />
      )}
      {!runsApi.loading && !runsApi.error && runs.length > 0 && availableRuns.length === 0 && (
        <Alert
          type="warning" showIcon message="没有通过测试集门槛的合格因子运行"
          description={`当前 ${runs.length} 条运行尚无已完成确认且本机可用的因子。请在因子生成页完成独立的“因子确认”任务；本页只展示 confirmed_factors.jsonl，不会提交时重跑测试集。`}
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
                  topK: 50, initialCash: 100000000, commission: 0.0003, stampDuty: 0.0005, transferFee: 0.00001,
                  rebalanceFreq: "1D", slippage: 0.001, minCost: 5, maxWeight: 0.03,
                }}
              >
                <Form.Item label="回测区间" name="dates" extra={selectionStart && selectionEnd
                  ? `默认使用股票池筛选范围：${selectionStart} ~ ${selectionEnd}，可手动调整。`
                  : poolsApi.loading ? "正在读取股票池筛选范围…" : "未取得股票池筛选范围，请手动选择回测区间。"}
                  rules={[{ required: true, message: "请选择回测区间" }]}>
                  <DatePicker.RangePicker className="full-width" />
                </Form.Item>
                <Row gutter={12}>
                  <Col span={12}>
                    <Form.Item label="调仓频率" name="rebalanceFreq">
                      <Select options={[
                        { value: "1D", label: "每日" },
                        { value: "1W", label: "每周（周期首个交易日）" },
                        { value: "2W", label: "每两周（固定双周周期）" },
                        { value: "1M", label: "每月（周期首个交易日）" },
                      ]} />
                    </Form.Item>
                  </Col>
                  <Col span={12}><Form.Item label="持仓数量 TopK" name="topK" rules={[{ type: "number", min: 1, max: 1000, message: "范围 1–1000" }]}><InputNumber className="full-width" min={1} max={1000} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="初始资金" name="initialCash"><InputNumber className="full-width" min={1} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="佣金（双向）" name="commission"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="印花税（卖出）" name="stampDuty"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="过户费（双向）" name="transferFee"><InputNumber className="full-width" step={0.00001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="滑点（基准 0.001 / 压力 0.002）" name="slippage"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="最低佣金" name="minCost"><InputNumber className="full-width" min={0} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="单票权重上限" name="maxWeight"><InputNumber className="full-width" min={0.001} max={1} step={0.005} /></Form.Item></Col>
                </Row>
                <Text type="secondary">最低佣金按每笔买卖分别收取；过户费与卖出印花税另计。周／双周／月按日历周期调仓，遇休市顺延至该周期首个交易日。</Text>
                <Button
                  size="large" block type="primary" htmlType="submit" icon={<PlayCircleOutlined />}
                  loading={submitting} disabled={!runDetail || !isConfirmedRun(runDetail) || factors.length === 0 || selectedIds.length === 0 || polling}
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
              title="合格因子清单（测试集门槛通过）"
              extra={<Text type="secondary">已选 {selectedIds.length} / {factors.length}</Text>}
              className="data-card"
            >
              <Space direction="vertical" size={12} className="full-width">
                <FilterChips
                  items={[{ key: "all", label: "全部", count: factors.length }, ...factorCategoryCounts]}
                  value={categoryFilter}
                  onChange={(key) => { setCategoryFilter(key); setFactorPage(1); }}
                />
                <Text type="secondary">表格展示原始表达式在测试集上的真实指标，缺失显示「—」。通过 train／valid 质量门槛的是可接受因子；经独立 test 门槛确认后才是合格因子。回测方向仅由训练 IC 确定，负 IC 因子自动反向；不使用验证集或测试集选方向。</Text>
                <Table
                  rowKey="factor_id" size="middle" tableLayout="fixed" columns={factorColumns} dataSource={filteredFactors}
                  loading={runDetailApi.loading} scroll={{ x: 1400 }}
                  pagination={{ current: factorPage, pageSize: factorPageSize, showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50], showTotal: (total) => `共 ${total} 个因子`,
                    onChange: (page, size) => { setFactorPage(size !== factorPageSize ? 1 : page); setFactorPageSize(size); } }}
                  rowSelection={{ preserveSelectedRowKeys: true, selectedRowKeys: selected, onChange: (keys) => setSelected(keys) }}
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
