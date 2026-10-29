import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, DatePicker, Flex, Form, Input, InputNumber, message, Progress, Row,
  Select, Skeleton, Space, Spin, Statistic, Table, Tag, Tooltip, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  BarChartOutlined, CloudDownloadOutlined, ExperimentOutlined, PlayCircleOutlined,
  ReloadOutlined, SearchOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import {
  api, factorBacktestFileUrl, useApiData, useJobPolling,
  type FactorBacktestRequest, type FactorBacktestRow,
} from "../api/client";
import {
  CATEGORY_META, OPERATOR_FAMILY_LABELS,
  buildBatchInsight, buildOperatorCategoryMap, classifyExpression, countFactorCategories,
  factorDataSourceLabel, formatFraction, formatNumber, metricNumber, normalizeFactorCategory,
  type FactorCategoryKey, type FactorView,
} from "../factorInsights";
import { FactorCategoryChips } from "../components/FactorCategoryChips";
import type { PageNav } from "./DataPages";

const { Text, Paragraph } = Typography;

type DateRangeValue = { format: (template: string) => string }[];

type FactorBacktestFormValues = {
  dates: DateRangeValue;
  topK: number;
  initialCash: number;
  buyCost: number;
  sellCost: number;
  slippage: number;
  minCost: number;
  maxWeight: number;
};

type BatchRowView = FactorBacktestRow & {
  __category: FactorCategoryKey;
};

type Props = {
  navigate: PageNav;
  /** 从因子生成页跳转时带入的运行与类别 */
  initialRunId?: string;
  initialCategory?: string;
};

export function FactorBacktestPage({ navigate, initialRunId, initialCategory }: Props) {
  const [form] = Form.useForm<FactorBacktestFormValues>();
  const runsApi = useApiData(api.factorRuns);
  const operatorsApi = useApiData(api.operators);
  const runs = useMemo(() => runsApi.data?.runs ?? [], [runsApi.data]);

  const [runId, setRunId] = useState<string | undefined>(initialRunId);
  const [selected, setSelected] = useState<string[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<FactorCategoryKey | "all">(
    normalizeFactorCategory(initialCategory),
  );
  const [pendingCategory, setPendingCategory] = useState<FactorCategoryKey | "all">(
    normalizeFactorCategory(initialCategory),
  );
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [batchId, setBatchId] = useState<string | undefined>();
  const pendingBatchRef = useRef<string | null>(null);
  const appliedInitialRef = useRef<string | null>(null);
  const { job, error: jobError, polling } = useJobPolling(jobId);

  useEffect(() => {
    setPendingCategory(normalizeFactorCategory(initialCategory));
  }, [initialCategory]);

  useEffect(() => {
    if (runsApi.loading) return;
    if (runs.length === 0) {
      setRunId(undefined);
      return;
    }
    if (!runId || !runs.some((run) => run.run_id === runId)) setRunId(runs[0].run_id);
  }, [runs, runId, runsApi.loading]);

  const runDetailApi = useApiData(
    () => (runId ? api.factorRun(runId) : Promise.resolve(null)),
    [runId],
  );
  const runDetail = runDetailApi.data?.run_id === runId ? runDetailApi.data : null;

  const operatorMap = useMemo(
    () => buildOperatorCategoryMap(operatorsApi.data?.operators ?? []),
    [operatorsApi.data],
  );
  const factors = useMemo<FactorView[]>(
    () => (runDetail?.accepted_factors ?? []).map((factor) => ({
      ...factor,
      ...classifyExpression(factor.expression, operatorMap),
    })),
    [runDetail, operatorMap],
  );
  const counts = useMemo(() => countFactorCategories(factors), [factors]);

  // 首次加载 / 从生成页带类别跳转时，只选中该类别的因子；用户后续手动勾选不被覆盖
  useEffect(() => {
    if (!runId || !runDetail) return;
    if (appliedInitialRef.current === runId) return;
    appliedInitialRef.current = runId;
    const category = pendingCategory === "all" || factors.some((factor) => factor.category === pendingCategory)
      ? pendingCategory
      : "all";
    setCategoryFilter(category);
    setSelected(
      category === "all"
        ? factors.map((factor) => factor.factor_id)
        : factors.filter((factor) => factor.category === category).map((factor) => factor.factor_id),
    );
  }, [runId, runDetail, factors, pendingCategory]);

  useEffect(() => {
    setSearch("");
    setPage(1);
  }, [runId]);
  useEffect(() => {
    setPage(1);
  }, [categoryFilter, search, pageSize]);

  const filteredFactors = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return factors.filter((factor) => {
      if (categoryFilter !== "all" && factor.category !== categoryFilter) return false;
      if (!keyword) return true;
      const haystack = [
        factor.factor_id, factor.expression, factor.canonical_expression ?? "",
        factor.tags.join(" "), CATEGORY_META[factor.category].label,
        OPERATOR_FAMILY_LABELS[factor.operatorFamily],
      ].join(" ").toLowerCase();
      return haystack.includes(keyword);
    });
  }, [factors, categoryFilter, search]);

  const selectedIds = useMemo(
    () => selected.filter((id) => factors.some((factor) => factor.factor_id === id)),
    [selected, factors],
  );
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const filteredSet = useMemo(
    () => new Set(filteredFactors.map((factor) => factor.factor_id)),
    [filteredFactors],
  );
  const selectedInFilter = filteredFactors.filter((factor) => selectedSet.has(factor.factor_id)).length;
  const selectedOutsideFilter = selectedIds.length - selectedInFilter;
  const allSelected = factors.length > 0 && selectedIds.length === factors.length;

  const changeRun = (value: string) => {
    pendingBatchRef.current = null;
    setPendingCategory("all");
    setCategoryFilter("all");
    setSelected([]);
    setRunId(value);
  };

  const selectAllFactors = () => setSelected(factors.map((factor) => factor.factor_id));
  const selectFiltered = () => setSelected(filteredFactors.map((factor) => factor.factor_id));
  const unselectFiltered = () => setSelected((current) => current.filter((id) => !filteredSet.has(id)));
  const clearSelection = () => setSelected([]);

  const batchesApi = useApiData(
    () => (runId ? api.factorBacktests(runId) : Promise.resolve(null)),
    [runId],
  );
  const batches = useMemo(
    () => (batchesApi.data?.batches ?? []).filter((batch) => !runId || batch.factor_run_id === runId),
    [batchesApi.data, runId],
  );
  useEffect(() => {
    if (batches.length === 0) {
      if (!pendingBatchRef.current) setBatchId(undefined);
      return;
    }
    const pending = pendingBatchRef.current;
    if (pending && batches.some((batch) => batch.backtest_id === pending)) {
      pendingBatchRef.current = null;
      if (batchId !== pending) setBatchId(pending);
      return;
    }
    if (pending && batchId === pending) return;
    if (!batchId || !batches.some((batch) => batch.backtest_id === batchId)) {
      setBatchId(batches[0].backtest_id);
    }
  }, [batches, batchId]);

  const batchApi = useApiData(
    () => (runId && batchId ? api.factorBacktest(runId, batchId) : Promise.resolve(null)),
    [runId, batchId],
  );
  const batchDetail =
    batchApi.data?.batch.backtest_id === batchId && batchApi.data?.batch.factor_run_id === runId
      ? batchApi.data
      : null;
  const batch = batchDetail?.batch ?? null;

  const finishedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!jobId || job?.status !== "finished" || finishedRef.current === jobId) return;
    finishedRef.current = jobId;
    const resultBatch = job.result && typeof job.result.backtest_id === "string" ? job.result.backtest_id : null;
    if (resultBatch) {
      pendingBatchRef.current = resultBatch;
      setBatchId(resultBatch);
    }
    batchesApi.reload();
    runsApi.reload();
  }, [jobId, job?.status, job?.result, batchesApi.reload, runsApi.reload]);

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
    const payload: FactorBacktestRequest = {
      factor_run_id: runId,
      factor_ids: allSelected ? undefined : selectedIds,
      start_date: range[0].format("YYYY-MM-DD"),
      end_date: range[1].format("YYYY-MM-DD"),
      top_k: values.topK,
      initial_cash: values.initialCash,
      buy_cost: values.buyCost,
      sell_cost: values.sellCost,
      slippage: values.slippage,
      min_cost: values.minCost,
      max_weight_per_stock: values.maxWeight,
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

  const copySummary = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success("回测总结已复制");
    } catch {
      message.error("复制失败，请手动选择文本");
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

  const downloadBatchFile = (fileName: string) => {
    if (!runId || !batch) return;
    window.location.href = factorBacktestFileUrl(runId, batch.backtest_id, fileName);
  };

  const factorColumns: TableColumnsType<FactorView> = [
    {
      title: "因子 ID", dataIndex: "factor_id", width: 190,
      render: (value: string) => <Text code style={{ whiteSpace: "nowrap" }}>{value}</Text>,
    },
    {
      title: "表达式", dataIndex: "expression", ellipsis: true,
      render: (value: string) => <Tooltip title={value}><Text code>{value}</Text></Tooltip>,
    },
    {
      title: "类别", key: "category", width: 150,
      sorter: (a, b) => CATEGORY_META[a.category].label.localeCompare(CATEGORY_META[b.category].label, "zh-CN"),
      render: (_, row) => (
        <Space size={4} wrap>
          <Tooltip title={CATEGORY_META[row.category].description}>
            <Tag color={CATEGORY_META[row.category].color}>{CATEGORY_META[row.category].label}</Tag>
          </Tooltip>
          <Tag>{OPERATOR_FAMILY_LABELS[row.operatorFamily]}</Tag>
        </Space>
      ),
    },
    {
      title: "标签", dataIndex: "tags", width: 128,
      render: (tags: string[]) => (
        tags.length > 0
          ? <Space size={4} wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space>
          : <Text type="secondary">—</Text>
      ),
    },
    {
      title: "IC", dataIndex: "ic", align: "right", width: 80,
      sorter: (a, b) => (metricNumber(a.ic) ?? -Infinity) - (metricNumber(b.ic) ?? -Infinity),
      render: (value) => formatNumber(value, 4),
    },
    {
      title: "RankIC", dataIndex: "rank_ic", align: "right", width: 86,
      sorter: (a, b) => (metricNumber(a.rank_ic) ?? -Infinity) - (metricNumber(b.rank_ic) ?? -Infinity),
      render: (value) => formatNumber(value, 4),
    },
    {
      title: "ICIR", dataIndex: "icir", align: "right", width: 78,
      sorter: (a, b) => (metricNumber(a.icir) ?? -Infinity) - (metricNumber(b.icir) ?? -Infinity),
      render: (value) => formatNumber(value),
    },
    {
      title: "覆盖率", dataIndex: "coverage", align: "right", width: 86,
      render: (value) => formatFraction(value, 1),
    },
    {
      title: "Score", dataIndex: "score", align: "right", width: 78,
      sorter: (a, b) => (metricNumber(a.score) ?? -Infinity) - (metricNumber(b.score) ?? -Infinity),
      render: (value) => formatNumber(value),
    },
  ];

  const batchRows = useMemo<BatchRowView[]>(
    () => (batchDetail?.rows ?? []).map((row) => ({
      ...row,
      __category: classifyExpression(String(row.expression ?? ""), operatorMap).category,
    })),
    [batchDetail, operatorMap],
  );

  const insight = useMemo(
    () => (batchDetail ? buildBatchInsight(batchDetail.rows, batchDetail.failures, operatorMap) : null),
    [batchDetail, operatorMap],
  );

  const batchColumns: TableColumnsType<BatchRowView> = [
    {
      title: "因子 ID", dataIndex: "factor_id", width: 190,
      render: (value) => <Text code style={{ whiteSpace: "nowrap" }}>{String(value ?? "—")}</Text>,
    },
    {
      title: "表达式", dataIndex: "expression", ellipsis: true,
      render: (value) => <Text code>{String(value ?? "—")}</Text>,
    },
    {
      title: "类别", dataIndex: "__category", width: 96,
      render: (key: FactorCategoryKey) => (
        <Tag color={CATEGORY_META[key].color}>{CATEGORY_META[key].label}</Tag>
      ),
    },
    {
      title: "年化收益", key: "annual", align: "right", width: 100,
      sorter: (a, b) => (metricNumber(a.backtest_annual_return) ?? -Infinity) - (metricNumber(b.backtest_annual_return) ?? -Infinity),
      render: (_, row) => {
        const value = metricNumber(row.backtest_annual_return);
        return <Text type={value != null && value < 0 ? "danger" : "success"}>{formatFraction(value)}</Text>;
      },
    },
    {
      title: "夏普", key: "sharpe", align: "right", width: 78,
      sorter: (a, b) => (metricNumber(a.backtest_sharpe) ?? -Infinity) - (metricNumber(b.backtest_sharpe) ?? -Infinity),
      render: (_, row) => formatNumber(row.backtest_sharpe),
    },
    {
      title: "最大回撤", key: "drawdown", align: "right", width: 92,
      render: (_, row) => <Text type="danger">{formatFraction(row.backtest_max_drawdown)}</Text>,
    },
    {
      title: "换手率", key: "turnover", align: "right", width: 88,
      render: (_, row) => formatFraction(row.backtest_average_turnover),
    },
    {
      title: "成本", key: "cost", align: "right", width: 78,
      render: (_, row) => formatFraction(row.backtest_total_cost),
    },
    {
      title: "胜率", key: "win_rate", align: "right", width: 78,
      render: (_, row) => formatFraction(row.backtest_win_rate),
    },
    {
      title: "操作", key: "action", width: 76, align: "right",
      render: (_, row) => (
        <Button type="link" size="small" disabled={!row.run_key} onClick={() => navigate("result", undefined, String(row.run_key))}>
          结果
        </Button>
      ),
    },
  ];

  const batchOptions = batches.map((item) => ({
    value: item.backtest_id,
    label: `${item.backtest_id} · 成功 ${item.completed ?? "—"}/${item.selected_count ?? "—"}${item.created_at ? ` · ${String(item.created_at).replace("T", " ").slice(0, 16)}` : ""}`,
  }));

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex vertical gap={8}>
          <Flex justify="space-between" gap={16} wrap align="center">
            <Space wrap>
              <Text strong><ExperimentOutlined /> 因子运行</Text>
              <Select
                value={runId}
                onChange={changeRun}
                className="factor-run-select"
                loading={runsApi.loading}
                showSearch optionFilterProp="label"
                placeholder={runsApi.error ? "因子运行目录不可读" : "选择已生成的因子运行"}
                options={runs.map((run) => ({
                  value: run.run_id,
                  label: `${run.run_id} · ${run.pool_id ?? "未知池"} · ${run.accepted_count} 个合格因子`,
                }))}
              />
              <Button
                size="small" icon={<ReloadOutlined />}
                onClick={() => { runsApi.reload(); operatorsApi.reload(); }}
                loading={runsApi.loading}
              >
                刷新
              </Button>
              {runDetail && <Tag color="blue">{factors.length} 个合格因子</Tag>}
            </Space>
            <Text type="secondary">批次结果按任务 ID 版本化保存，不会覆盖历史回测</Text>
          </Flex>
          {runDetail && (
            <Space wrap size={6}>
              {runDetail.pool_id && <Tag>股票池 {runDetail.pool_id}</Tag>}
              <Tag>{factorDataSourceLabel(runDetail.data_source)}</Tag>
              {runDetail.created_at && (
                <Text type="secondary">生成于 {String(runDetail.created_at).replace("T", " ")}</Text>
              )}
            </Space>
          )}
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
          description="请先在「因子生成」页查看已生成的因子，或用 CLI 生成 factor_runs/<run_id>/accepted_factors.jsonl；本页只回测生成阶段已合格的因子。"
        />
      )}

      {runId && (
        <Card title={<Space><PlayCircleOutlined />批量回测参数</Space>} className="factor-param-card">
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
                  topK: 50, initialCash: 100000000, buyCost: 0.0015, sellCost: 0.0015,
                  slippage: 0.0005, minCost: 5, maxWeight: 0.02,
                }}
              >
                <Row gutter={12}>
                  <Col span={6}>
                    <Form.Item label="回测区间" name="dates" rules={[{ required: true, message: "请选择回测区间" }]}>
                      <DatePicker.RangePicker className="full-width" />
                    </Form.Item>
                  </Col>
                  <Col span={6}><Form.Item label="持仓数量 TopK" name="topK" rules={[{ type: "number", min: 1, max: 1000, message: "范围 1–1000" }]}><InputNumber className="full-width" min={1} max={1000} /></Form.Item></Col>
                  <Col span={6}><Form.Item label="初始资金" name="initialCash"><InputNumber className="full-width" min={1} addonAfter="元" /></Form.Item></Col>
                  <Col span={6}><Form.Item label="单票权重上限" name="maxWeight"><InputNumber className="full-width" min={0.001} max={1} step={0.01} /></Form.Item></Col>
                  <Col span={6}><Form.Item label="买入费率" name="buyCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={6}><Form.Item label="卖出费率" name="sellCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={6}><Form.Item label="滑点" name="slippage"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={6}><Form.Item label="最低手续费" name="minCost"><InputNumber className="full-width" min={0} addonAfter="元" /></Form.Item></Col>
                </Row>
                <Flex justify="space-between" align="center" gap={12} wrap className="factor-param-actions">
                  <Text type="secondary">
                    已选 {selectedIds.length} / {factors.length} 个因子；类别筛选只影响下方列表，提交以勾选为准。
                  </Text>
                  <Button
                    type="primary" htmlType="submit" icon={<PlayCircleOutlined />}
                    loading={submitting} disabled={!runDetail || factors.length === 0 || selectedIds.length === 0 || polling}
                  >
                    回测 {selectedIds.length} 个合格因子
                  </Button>
                </Flex>
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
      )}

      {runId && (
        <Card
          title={<Space><ExperimentOutlined />合格因子清单<Tag>生成阶段已筛选</Tag></Space>}
              extra={<Text type="secondary">已选 {selectedIds.length} / {factors.length}</Text>}
              className="data-card"
            >
              <Flex justify="space-between" align="center" gap={12} wrap className="factor-toolbar">
                <FactorCategoryChips
                  counts={counts}
                  value={categoryFilter}
                  onChange={(value) => { setCategoryFilter(value); setPage(1); }}
                />
                <Input
                  allowClear value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  prefix={<SearchOutlined />}
                  placeholder="搜索因子 ID / 表达式 / 标签"
                  style={{ width: 240 }}
                />
              </Flex>

              <Flex justify="space-between" align="center" gap={8} wrap className="factor-toolbar factor-selection-toolbar">
                <Space size={6} wrap>
                  <Button size="small" onClick={selectAllFactors} disabled={factors.length === 0}>全选全部</Button>
                  <Button size="small" onClick={selectFiltered} disabled={filteredFactors.length === 0}>只选当前筛选</Button>
                  <Button size="small" onClick={unselectFiltered} disabled={selectedInFilter === 0}>取消当前筛选勾选</Button>
                  <Button size="small" onClick={clearSelection} disabled={selectedIds.length === 0}>清空</Button>
                </Space>
                <Text type="secondary">
                  当前筛选 {filteredFactors.length} 个 · 已选 {selectedIds.length} / {factors.length}
                </Text>
              </Flex>

              {categoryFilter !== "all" && selectedOutsideFilter > 0 && (
                <Alert
                  type="info" showIcon className="factor-selection-hint"
                  message={`已选 ${selectedIds.length} 个因子，其中 ${selectedOutsideFilter} 个不在当前类别。`}
                  action={<Button size="small" type="link" onClick={selectFiltered}>只保留当前筛选</Button>}
                />
              )}

              <Table
                rowKey="factor_id" size="middle" columns={factorColumns} dataSource={filteredFactors}
                loading={runDetailApi.loading} scroll={{ x: 1080 }}
                rowSelection={{
                  selectedRowKeys: selectedIds,
                  preserveSelectedRowKeys: true,
                  onChange: (keys) => setSelected(keys.map(String)),
                }}
                locale={{ emptyText: runDetail && factors.length === 0 ? "该运行没有合格因子" : "没有符合当前筛选条件的因子" }}
                pagination={{
                  current: page, pageSize, total: filteredFactors.length,
                  showSizeChanger: true, pageSizeOptions: [10, 20, 50],
                  showTotal: (total) => `共 ${total} 个`,
                  onChange: (nextPage, nextSize) => {
                    setPage(nextPage);
                    setPageSize(nextSize);
                  },
                }}
              />
              <Text type="secondary" className="factor-table-hint">
                类别筛选只影响列表；提交回测以勾选因子为准。
              </Text>
            </Card>
      )}

      {runId && (
        <Card
          title={<Space><ExperimentOutlined />批量回测结果</Space>}
          className="data-card"
          extra={<Space wrap>
            <Select
              size="small" value={batchId} onChange={setBatchId} options={batchOptions}
              placeholder="暂无批次" style={{ minWidth: 320 }} loading={batchesApi.loading}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={batchesApi.reload}>刷新</Button>
            <Button size="small" icon={<CloudDownloadOutlined />} disabled={!batch || !batch.completed} onClick={() => downloadBatchFile("factor_backtest_summary.csv")}>下载汇总</Button>
            <Button size="small" icon={<CloudDownloadOutlined />} disabled={!batch || !batch.failed} onClick={() => downloadBatchFile("factor_backtest_failures.csv")}>下载失败明细</Button>
          </Space>}
        >
          {batchesApi.error && (
            <Alert type="error" showIcon message="批次列表加载失败" description={batchesApi.error}
              action={<Button size="small" onClick={batchesApi.reload}>重试</Button>} />
          )}
          {!batchesApi.loading && !batchesApi.error && batches.length === 0 && (
            <Alert type="info" showIcon message="该因子运行还没有批量回测记录" description="选好因子和参数后提交，批次结果会出现在这里。" />
          )}
          {batchApi.error && <Alert type="error" showIcon message="批次详情加载失败" description={batchApi.error} style={{ marginBottom: 12 }} />}
          {batch && (
            <Space direction="vertical" size={12} className="full-width">
              <Space wrap size={6}>
                <Tag color="blue">批次 {batch.backtest_id}</Tag>
                <Tag>区间 {batch.start_date ?? "—"} ~ {batch.end_date ?? "—"}</Tag>
                <Tag>TopK {batch.top_k ?? "—"}</Tag>
                <Tag>合格 {batch.accepted_count ?? "—"}</Tag>
                <Tag>本次 {batch.selected_count ?? "—"}</Tag>
                <Tag color="success">成功 {batch.completed ?? "—"}</Tag>
                {!!batch.failed && <Tag color="error">失败 {batch.failed}</Tag>}
              </Space>

              {insight && (
                <Card
                  size="small"
                  className={`factor-summary-card factor-summary-${insight.tone}`}
                  title={<Space><BarChartOutlined />回测总结<Tag color="blue">自动生成</Tag></Space>}
                  extra={<Button size="small" onClick={() => copySummary(insight.text)}>复制总结</Button>}
                >
                  <Paragraph className="factor-summary-text">{insight.text}</Paragraph>
                  <Row gutter={12}>
                    <Col span={6}><Statistic title="成功 / 总数" value={`${insight.count} / ${insight.count + insight.failed}`} /></Col>
                    <Col span={6}><Statistic title="年化中位数" value={formatFraction(insight.medianAnnual)} /></Col>
                    <Col span={6}><Statistic title="夏普中位数" value={formatNumber(insight.medianSharpe)} /></Col>
                    <Col span={6}><Statistic title="回撤中位数" value={formatFraction(insight.medianDrawdown)} /></Col>
                  </Row>
                  <Text type="secondary">总结依据批次汇总 CSV 自动归纳，仅供研究参考。</Text>
                </Card>
              )}

              <Table
                rowKey={(row) => String(row.factor_id ?? row.run_key ?? row.expression)}
                size="small" columns={batchColumns} dataSource={batchRows}
                loading={batchApi.loading} scroll={{ x: 1100 }}
                pagination={{
                  pageSize: 10, showSizeChanger: false, hideOnSinglePage: true,
                  showTotal: (total) => `共 ${total} 个`,
                }}
              />
              {batchDetail && batchDetail.failures.length > 0 && (
                <Alert
                  type="warning" showIcon message={`${batchDetail.failures.length} 个因子回测失败`}
                  description={<Space direction="vertical" size={2}>
                    {batchDetail.failures.slice(0, 6).map((item) => (
                      <Text key={`${item.factor_id}-${item.expression ?? ""}`}>
                        {item.factor_id} · {item.expression ?? "—"}：{item.error ?? "未知错误"}
                      </Text>
                    ))}
                    {batchDetail.failures.length > 6 && <Text type="secondary">仅显示前 6 条，完整明细请下载失败 CSV。</Text>}
                  </Space>}
                />
              )}
            </Space>
          )}
        </Card>
      )}
    </Space>
  );
}
