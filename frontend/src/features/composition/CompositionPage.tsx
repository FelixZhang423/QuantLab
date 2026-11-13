import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Checkbox, Col, Collapse, DatePicker, Descriptions, Divider, Empty, Flex,
  InputNumber, message, Progress, Row, Segmented, Select, Space, Spin, Statistic, Switch, Table,
  Tag, Typography,
} from "antd";
import type { TableColumnsType, TableProps } from "antd";
import {
  CloudDownloadOutlined, ExperimentOutlined, HistoryOutlined, LoadingOutlined, PlayCircleOutlined,
  ReloadOutlined, ToolOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import type { PageNav } from "../../app/navigation";
import {
  api, useApiData, useJobPolling,
  type AcceptedFactor, type CompositionFactorWeight, type CompositionScreenRow,
  type CompositionSizeEntry, type CompositionSummary,
  type FactorCompositionRequest, type FactorCompositionResponse, type FactorRunDetail,
  type FactorRunSummary,
} from "../../api/client";

const { Text } = Typography;

type CandidateRow = AcceptedFactor & { run_id: string; run_label: string };
type SelectionMode = "auto" | "manual";
type RebalanceFreq = "1D" | "1W" | "2W" | "1M";

const asNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const fmtNumber = (value: unknown, digits = 3): string => {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
};

const fmtPercent = (value: unknown, digits = 1): string => {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—";
};

const fmtDateTime = (value: string | null | undefined): string =>
  value ? String(value).replace("T", " ").slice(0, 16) : "—";

const methodLabel = (method: string | null | undefined): string =>
  method === "equal" ? "等权 1/N" : method === "mse" ? "MSE 优化" : method ?? "—";

const usableRun = (run: FactorRunSummary): boolean =>
  run.local_available !== false
  && run.has_accepted
  && run.confirmation_status === "finished"
  && (run.confirmed_count ?? 0) > 0;

const STAGE_LABELS: Record<string, string> = {
  queued: "任务排队中",
  loaded: "面板已加载",
  evaluating: "逐个评估候选因子",
  correlating: "计算 mutual IC",
  evaluating_marginal: "评估边际增益",
  selecting: "筛选因子与容量控制",
  optimizing_weights: "计算组合权重",
  backtesting: "回测组合",
};

const SCREEN_STATUS: Record<string, { label: string; color: string }> = {
  buyable: { label: "次日可买", color: "green" },
  pending_next_open: { label: "待次日校验", color: "blue" },
  blocked: { label: "次日不可买", color: "orange" },
  not_selected: { label: "未选中", color: "default" },
};

const BLOCKED_LABELS: Record<string, string> = {
  next_open_missing_row: "下一交易日无行情",
  next_open_suspended: "下一交易日停牌",
  next_open_missing: "下一交易日无有效开盘价",
  next_open_limit_up: "下一交易日涨停",
};

export function CompositionPage({ navigate, initialResult, resultsOnly = false }: { navigate: PageNav; initialResult?: [string, string | null, string[]?]; resultsOnly?: boolean }) {

  const [poolId, setPoolId] = useState<string | undefined>(initialResult?.[0]);
  const [resultRunIds, setResultRunIds] = useState(initialResult?.[2] ?? []);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("auto");
  const [maxFactors, setMaxFactors] = useState(20);
  const [sizes, setSizes] = useState<number[]>([5, 10, 20]);
  const [mutualIc, setMutualIc] = useState(0.8);
  const [zClip, setZClip] = useState<number | null>(3);
  const [selectedFactorIds, setSelectedFactorIds] = useState<string[]>([]);
  const [topK, setTopK] = useState(50);
  const [maxWeight, setMaxWeight] = useState(0.03);
  const [rebalance, setRebalance] = useState<RebalanceFreq>("1D");
  const [targetHorizon, setTargetHorizon] = useState(20);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [submission, setSubmission] = useState<FactorCompositionResponse | null>(null);
  const [jobWarnings, setJobWarnings] = useState<string[]>([]);
  const [compositionId, setCompositionId] = useState<string | null>(initialResult?.[1] ?? null);
  const [activeSize, setActiveSize] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [onlySelected, setOnlySelected] = useState(true);
  const [refreshSignalDate, setRefreshSignalDate] = useState<Dayjs | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const finishedRef = useRef<string | null>(null);
  const lastPoolRef = useRef<string | null>(initialResult?.[0] ?? null);

  const poolsApi = useApiData(api.pools);
  const pools = useMemo(() => poolsApi.data?.pools ?? [], [poolsApi.data]);

  useEffect(() => {
    if (poolId || pools.length === 0) return;
    setPoolId(pools[0].pool_id);
  }, [pools, poolId]);

  const runsApi = useApiData(
    () => (poolId
      ? api.factorRuns(poolId)
      : Promise.resolve({ total: 0, runs: [] as FactorRunSummary[] })),
    [poolId],
  );
  const usableRuns = useMemo(
    () => (runsApi.data?.runs ?? []).filter(
      (run) => usableRun(run) && (!poolId || run.pool_id === poolId),
    ),
    [runsApi.data, poolId],
  );

  useEffect(() => {
    if (lastPoolRef.current === (poolId ?? null)) return;
    lastPoolRef.current = poolId ?? null;
    setResultRunIds([]);
    setRunIds([]);
    setSelectedFactorIds([]);
    setCompositionId(null);
    setActiveSize(null);
    setJobId(null);
    setSubmission(null);
    setJobWarnings([]);
    finishedRef.current = null;
  }, [poolId]);

  useEffect(() => {
    setRunIds((current) => {
      const allowed = new Set(usableRuns.map((run) => run.run_id));
      const kept = current.filter((id) => allowed.has(id));
      return kept.length === current.length ? current : kept;
    });
  }, [usableRuns]);

  useEffect(() => {
    if (runIds.length === 0 && usableRuns.length === 1) {
      setRunIds([usableRuns[0].run_id]);
    }
  }, [runIds.length, usableRuns]);

  const runKey = useMemo(() => [...runIds].sort().join("|"), [runIds]);
  useEffect(() => {
    if (resultsOnly) return;
    setSelectedFactorIds([]);
    setCompositionId(null);
    setActiveSize(null);
    setJobId(null);
    setSubmission(null);
    setJobWarnings([]);
    finishedRef.current = null;
  }, [runKey]);

  const detailsApi = useApiData(
    () => (runIds.length
      ? Promise.all(runIds.map((runId) => api.factorRun(runId)))
      : Promise.resolve([] as FactorRunDetail[])),
    [runKey],
  );
  const detailByRun = useMemo(
    () => new Map((detailsApi.data ?? []).map((detail) => [detail.run_id, detail])),
    [detailsApi.data],
  );
  const candidateRows = useMemo(() => {
    const rows = new Map<string, CandidateRow>();
    for (const runId of runIds) {
      const detail = detailByRun.get(runId);
      if (!detail) continue;
      for (const factor of detail.confirmed_factors ?? []) {
        if (rows.has(factor.factor_id)) continue;
        rows.set(factor.factor_id, {
          ...factor,
          run_id: runId,
          run_label: detail.run_name || runId,
        });
      }
    }
    return [...rows.values()].sort((left, right) => asNumber(right.score) - asNumber(left.score));
  }, [runIds, detailByRun]);

  const historyApi = useApiData(
    () => (poolId
      ? api.factorCompositions(poolId, 20)
      : Promise.resolve({ total: 0, compositions: [] as CompositionSummary[] })),
    [poolId],
  );
  const historyOptions = useMemo(
    () => (historyApi.data?.compositions ?? []).filter((item) =>
      resultRunIds.length === 0 || (item.source_factor_run_ids?.length === resultRunIds.length &&
        resultRunIds.every((id) => item.source_factor_run_ids.includes(id))),
    ).map((item) => ({
      value: item.composition_id,
      label: `${fmtDateTime(item.created_at)} · ${item.composition_id} · ${methodLabel(item.weight_method)} · ${item.selected_count ?? 0} 因子`,
    })),
    [historyApi.data, resultRunIds],
  );

  const { job, error: jobError } = useJobPolling(jobId);
  const detailApi = useApiData(
    () => (poolId && compositionId
      ? api.factorComposition(poolId, compositionId, activeSize ?? undefined)
      : Promise.resolve(null)),
    [poolId, compositionId, activeSize],
  );
  const detail = detailApi.data?.composition_id === compositionId
    && (activeSize === null || detailApi.data.size === activeSize)
    ? detailApi.data
    : null;
  const displaySize = activeSize ?? detail?.size ?? null;
  const screenApi = useApiData(
    () => (poolId && compositionId && displaySize
      ? api.factorCompositionScreen(poolId, compositionId, displaySize, 1000)
      : Promise.resolve(null)),
    [poolId, compositionId, displaySize],
  );
  const screen = screenApi.data?.composition_id === compositionId
    && screenApi.data.size === displaySize
    ? screenApi.data.screen
    : null;
  const screenSummary = screen ?? detail?.result.screen ?? null;

  useEffect(() => {
    const signalDate = screen?.signal_date ?? detail?.result.screen?.signal_date;
    if (signalDate) setRefreshSignalDate(dayjs(signalDate));
  }, [screen?.signal_date, detail?.result.screen?.signal_date]);

  useEffect(() => {
    if (!jobId || job?.status !== "finished" || finishedRef.current === jobId) return;
    finishedRef.current = jobId;
    const result = job.result ?? {};
    const nextId = typeof result.composition_id === "string" ? result.composition_id : null;
    const nextSize = typeof result.default_size === "number" ? result.default_size : null;
    if (!nextId) {
      message.warning("组合任务已完成，但未返回 composition_id，无法读取结果");
      return;
    }
    setCompositionId(nextId);
    setActiveSize(nextSize);
    historyApi.reload();
    message.success(`因子组合完成：${nextId}`);
    if (poolId) navigate("composition_results", undefined, JSON.stringify([poolId, nextId]));
  }, [jobId, job?.status, job?.result, historyApi.reload, poolId, navigate]);

  const active = Boolean(jobId) && !jobError && (!job || job.status === "queued" || job.status === "running");
  const failed = Boolean(jobId) && (Boolean(jobError) || job?.status === "failed" || job?.status === "missing");
  const finished = Boolean(jobId) && job?.status === "finished";

  const progressData = job?.progress ?? {};
  const stage = String(progressData.stage ?? (job?.status === "queued" ? "queued" : ""));
  const stageLabel = STAGE_LABELS[stage] ?? (active ? "组合任务运行中" : "");
  const candidateCount = asNumber(progressData.candidate_count);
  const candidateIndex = asNumber(progressData.candidate_index);
  const acceptedCount = asNumber(progressData.accepted_count);
  const currentSize = asNumber(progressData.current_size);
  const requestedSizes = Array.isArray(submission?.request_summary?.sweep_sizes)
    ? (submission.request_summary.sweep_sizes as unknown[]).length
    : 0;
  const completedSizes = Array.isArray(progressData.completed_sizes)
    ? (progressData.completed_sizes as unknown[]).length
    : 0;
  const percent = finished
    ? 100
    : stage === "backtesting"
      ? Math.min(99, 80 + Math.round((completedSizes / Math.max(requestedSizes, 1)) * 19))
      : stage === "optimizing_weights"
        ? 80
        : candidateCount > 0
          ? Math.min(79, Math.round(5 + (candidateIndex / candidateCount) * 70))
          : active
            ? 5
            : 0;

  const effectiveMax = selectionMode === "manual" ? selectedFactorIds.length : maxFactors;
  const desiredSizes = useMemo(() => [...sizes].sort((left, right) => left - right), [sizes]);
  const effectiveSizes = useMemo(() => {
    const allowed = desiredSizes.filter((size) => size <= effectiveMax);
    return allowed.length ? allowed : (effectiveMax > 0 ? [effectiveMax] : []);
  }, [desiredSizes, effectiveMax]);
  const cashDrag = topK > 0 && maxWeight > 0 && topK * maxWeight < 1;
  const plannedExposure = Math.min(1, Math.max(0, topK * maxWeight));

  const loadComposition = (nextId: string) => {
    setCompositionId(nextId);
    setActiveSize(null);
    setJobId(null);
    setSubmission(null);
    setJobWarnings([]);
    finishedRef.current = null;
  };

  const submit = async () => {
    if (!poolId) {
      message.error("请选择股票池");
      return;
    }
    if (runIds.length === 0) {
      message.error("请至少选择一个已完成测试确认的因子运行");
      return;
    }
    if (selectionMode === "manual" && selectedFactorIds.length === 0) {
      message.error("手动模式下请至少勾选一个因子");
      return;
    }
    if (effectiveMax < 1) {
      message.error("组合因子数必须大于 0");
      return;
    }
    if (sizes.length === 0) {
      message.error("请至少选择一个组合规模");
      return;
    }
    if (effectiveSizes.length === 0) {
      message.error("请选择至少一个组合规模");
      return;
    }
    if (topK < 1) {
      message.error("TopK 必须大于 0");
      return;
    }
    if (!(maxWeight > 0 && maxWeight <= 1)) {
      message.error("单股上限必须在 (0, 1] 之间");
      return;
    }
    const payload: FactorCompositionRequest = {
      pool_id: poolId,
      factor_run_ids: runIds,
      factor_ids: selectionMode === "manual" ? selectedFactorIds : undefined,
      selection_metric: "score",
      mutual_ic_threshold: mutualIc,
      z_clip: zClip,
      sweep_sizes: effectiveSizes,
      max_factors: effectiveMax,
      target_horizon: targetHorizon,
      start_date: range?.[0]?.format("YYYY-MM-DD"),
      end_date: range?.[1]?.format("YYYY-MM-DD"),
      top_k: topK,
      max_weight_per_stock: maxWeight,
      rebalance_freq: rebalance,
    };
    setSubmitting(true);
    setJobWarnings([]);
    setCompositionId(null);
    setActiveSize(null);
    finishedRef.current = null;
    try {
      const response = await api.createFactorComposition(payload);
      setSubmission(response);
      setJobId(response.job_id);
      setJobWarnings(response.warnings ?? []);
      message.success(`因子组合任务已提交：${response.job_id}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const refreshScreen = async () => {
    if (!poolId || !compositionId) {
      message.error("请先选择已完成的因子组合");
      return;
    }
    if (!refreshSignalDate) {
      message.error("请选择信号日");
      return;
    }
    setRefreshing(true);
    try {
      const response = await api.refreshFactorCompositionScreen(compositionId, {
        pool_id: poolId,
        signal_date: refreshSignalDate.format("YYYY-MM-DD"),
        size: displaySize ?? undefined,
      });
      message.success(
        `选股清单已刷新：信号日 ${response.screen.signal_date ?? "—"}，执行日 ${response.screen.execution_date ?? "—"}`,
      );
      detailApi.reload();
      screenApi.reload();
      historyApi.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  };

  const downloadWeights = () => {
    if (!detail) return;
    const payload = {
      composition_id: detail.composition_id,
      pool_id: detail.pool_id,
      size: detail.size,
      weight_method: "equal",
      z_clip: detail.manifest.z_clip,
      mutual_ic_threshold: detail.manifest.mutual_ic_threshold,
      composition_metrics: detail.result.composition_metrics,
      backtest_summary: detail.result.backtest_summary,
      screen_summary: detail.result.screen,
      weights: detail.weights,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${detail.composition_id}_size_${detail.size}_weights.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    message.success("因子权重 JSON 已开始下载");
  };

  const candidateColumns: TableColumnsType<CandidateRow> = [
    {
      title: "因子 ID", dataIndex: "factor_id", width: 190,
      render: (value: string) => <Text code style={{ whiteSpace: "nowrap" }}>{value}</Text>,
    },
    {
      title: "表达式", dataIndex: "expression", ellipsis: true,
      render: (value: string) => <Text code>{value}</Text>,
    },
    {
      title: "Score", dataIndex: "score", width: 86, align: "right", defaultSortOrder: "descend",
      sorter: (left, right) => asNumber(left.score) - asNumber(right.score),
      render: (value: number | null) => fmtNumber(value, 3),
    },
    {
      title: "训练 IC", width: 92, align: "right",
      render: (_, record) => fmtNumber(record.segments?.train?.ic ?? record.ic, 4),
    },
    {
      title: "验证 IC", width: 92, align: "right",
      render: (_, record) => fmtNumber(record.segments?.valid?.ic, 4),
    },
    {
      title: "测试 IC", width: 92, align: "right",
      render: (_, record) => fmtNumber(record.segments?.test?.ic, 4),
    },
    {
      title: "测试覆盖率", width: 104, align: "right",
      render: (_, record) => fmtPercent(record.segments?.test?.coverage ?? record.coverage, 1),
    },
    {
      title: "运行", dataIndex: "run_label", width: 160, ellipsis: true,
      render: (value: string, record) => <span title={record.run_id}>{value}</span>,
    },
  ];

  const weightColumns: TableColumnsType<CompositionFactorWeight> = [
    {
      title: "因子", dataIndex: "factor_id", width: 170,
      render: (value: string) => <Text code>{value}</Text>,
    },
    {
      title: "表达式", dataIndex: "expression", ellipsis: true,
      render: (value: string | null) => <Text code>{value ?? "—"}</Text>,
    },
    {
      title: "权重", dataIndex: "weight", width: 84, align: "right",
      sorter: (left, right) => left.weight - right.weight,
      render: (value: number) => <Text strong>{fmtPercent(value, 2)}</Text>,
    },
    {
      title: "训练 IC", dataIndex: "training_ic", width: 92, align: "right",
      render: (value: number | null) => fmtNumber(value, 4),
    },
  ];

  const sizeColumns: TableColumnsType<CompositionSizeEntry> = [
    {
      title: "规模", dataIndex: "size", width: 84, fixed: "left",
      render: (value: number) => <Tag color="blue">Top {value}</Tag>,
    },
    {
      title: "组合 IC", width: 92, align: "right",
      sorter: (left, right) => asNumber(left.composition_metrics.ic) - asNumber(right.composition_metrics.ic),
      render: (_, record) => fmtNumber(record.composition_metrics.ic, 4),
    },
    {
      title: "RankIC", width: 92, align: "right",
      render: (_, record) => fmtNumber(record.composition_metrics.rank_ic, 4),
    },
    {
      title: "ICIR", width: 80, align: "right",
      render: (_, record) => fmtNumber(record.composition_metrics.icir, 2),
    },
    {
      title: "年化", width: 86, align: "right",
      render: (_, record) => <Text type={asNumber(record.backtest_summary.annual_return) >= 0 ? "success" : "danger"}>
        {fmtPercent(record.backtest_summary.annual_return)}
      </Text>,
    },
    {
      title: "夏普", width: 76, align: "right",
      render: (_, record) => fmtNumber(record.backtest_summary.sharpe, 2),
    },
    {
      title: "最大回撤", width: 92, align: "right",
      render: (_, record) => <Text type="danger">{fmtPercent(record.backtest_summary.max_drawdown)}</Text>,
    },
    {
      title: "平均换手", width: 92, align: "right",
      render: (_, record) => fmtPercent(record.backtest_summary.average_turnover),
    },
    {
      title: "选股", width: 74, align: "right",
      render: (_, record) => record.screen.selected_count ?? "—",
    },
  ];

  const screenColumns: TableColumnsType<CompositionScreenRow> = [
    {
      title: "排名", dataIndex: "rank", width: 68, align: "right",
      sorter: (left, right) => left.rank - right.rank,
    },
    {
      title: "代码", dataIndex: "code", width: 96,
      render: (value: string) => <Text code>{value}</Text>,
    },
    {
      title: "名称", dataIndex: "name", width: 120, ellipsis: true,
      render: (value: string | null | undefined) => value || "—",
    },
    {
      title: "综合分", dataIndex: "composite_score", width: 96, align: "right",
      sorter: (left, right) => left.composite_score - right.composite_score,
      render: (value: number) => <Text strong>{fmtNumber(value, 4)}</Text>,
    },
    {
      title: "状态", dataIndex: "status", width: 116,
      render: (value: string) => {
        const meta = SCREEN_STATUS[value] ?? { label: value, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "目标权重", dataIndex: "target_weight", width: 92, align: "right",
      render: (value: number) => fmtPercent(value, 2),
    },
    {
      title: "次日开盘", dataIndex: "next_open", width: 96, align: "right",
      render: (value: number | null) => fmtNumber(value, 2),
    },
    {
      title: "阻塞原因", dataIndex: "blocked_reason", width: 170,
      render: (value: string | null) => value ? BLOCKED_LABELS[value] ?? value : "—",
    },
    {
      title: "最大贡献", width: 180, ellipsis: true,
      render: (_, record) => {
        const top = [...record.contributions].sort(
          (left, right) => Math.abs(right.contribution) - Math.abs(left.contribution),
        )[0];
        return top
          ? <span title={`${top.factor_id} · z=${top.zscore.toFixed(3)} · 贡献=${top.contribution.toFixed(4)}`}>
              <Text code>{top.factor_id}</Text> · {fmtNumber(top.contribution, 4)}
            </span>
          : "—";
      },
    },
  ];

  const visibleScreenRows = useMemo(
    () => (screen?.rows ?? []).filter((row) => (onlySelected ? row.selected : true)),
    [screen, onlySelected],
  );

  const rowSelection: TableProps<CandidateRow>["rowSelection"] = selectionMode === "manual"
    ? {
        selectedRowKeys: selectedFactorIds,
        onChange: (keys) => setSelectedFactorIds(keys.map(String)),
        preserveSelectedRowKeys: true,
      }
    : undefined;

  const selectedPool = pools.find((pool) => pool.pool_id === poolId);
  const showResultPanel = active || failed || finished || Boolean(compositionId) || Boolean(submission);
  const detailLoading = detailApi.loading && !detail;
  const weightMethodTag = methodLabel(detail?.manifest.weight_method ?? "equal");

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap align="center">
          <Space wrap>
            <Text strong><ExperimentOutlined /> 股票池</Text>
            <Select
              value={poolId}
              onChange={setPoolId}
              loading={poolsApi.loading}
              showSearch optionFilterProp="label"
              placeholder={poolsApi.error ? "股票池加载失败" : "选择股票池"}
              style={{ minWidth: 230 }}
              options={pools.map((pool) => ({
                value: pool.pool_id,
                label: `${pool.name} · ${pool.n_stocks} 只`,
              }))}
            />
            {resultsOnly && resultRunIds.length > 0 && <Space wrap>
              <Text strong>因子运行</Text>
              {resultRunIds.map((id) => <Tag key={id}>{usableRuns.find((run) => run.run_id === id)?.run_name || id}</Tag>)}
              <Button type="link" onClick={() => setResultRunIds([])}>查看全部运行</Button>
            </Space>}
            {resultsOnly ? <Select value={compositionId ?? undefined} onChange={loadComposition}
              loading={historyApi.loading} disabled={!poolId} options={historyOptions}
              placeholder="选择历史组合" style={{ minWidth: 330 }} /> : <>
            <Text strong>因子运行</Text>
            <Select
              mode="multiple"
              value={runIds}
              onChange={(values) => setRunIds(values)}
              loading={runsApi.loading}
              showSearch optionFilterProp="label"
              maxTagCount="responsive"
              disabled={!poolId || runsApi.loading}
              placeholder={usableRuns.length ? "选择已完成确认的运行（可多选）" : "该股票池暂无已确认运行"}
              style={{ minWidth: 380 }}
              options={usableRuns.map((run) => ({
                value: run.run_id,
                label: `${run.run_name || run.run_id} · ${run.confirmed_count ?? 0} 个合格因子${run.device ? ` · ${run.device}` : ""}`,
              }))}
            />
            <Button
              size="small" icon={<ReloadOutlined />}
              loading={runsApi.loading || detailsApi.loading}
              onClick={() => { runsApi.reload(); detailsApi.reload(); }}
            >
              刷新因子
            </Button></>}
          </Space>
          {!resultsOnly && <Space wrap>
            <Text strong>权重方法</Text>
            <Tag color="blue">等权 1/N</Tag>
            <Button
              type="primary" icon={<PlayCircleOutlined />}
              loading={submitting} disabled={active || pools.length === 0 || sizes.length === 0}
              onClick={submit}
            >
              提交组合
            </Button>
          </Space>}
        </Flex>

        {!resultsOnly && <>
        {poolsApi.error && (
          <Alert
            type="error" showIcon className="note-action"
            message="股票池加载失败" description={poolsApi.error}
            action={<Button size="small" onClick={poolsApi.reload}>重试</Button>}
          />
        )}
        {!poolsApi.loading && pools.length === 0 && (
          <Alert
            type="warning" showIcon className="note-action"
            message="还没有股票池"
            description="因子组合需要绑定真实股票池；请先创建股票池并完成因子生成与测试确认。"
            action={<Button size="small" type="primary" onClick={() => navigate("pools")}>去创建股票池</Button>}
          />
        )}
        {runsApi.error && (
          <Alert
            type="warning" showIcon className="note-action"
            message="因子运行加载失败" description={runsApi.error}
            action={<Button size="small" onClick={runsApi.reload}>重试</Button>}
          />
        )}
        {poolId && !runsApi.loading && usableRuns.length === 0 && (
          <Alert
            type="info" showIcon className="note-action"
            message="该股票池没有可用于组合的因子运行"
            description="只有完成测试集确认、且合格因子数大于 0、运行目录在本地存在的 factor run 才能参与组合。"
            action={<Button size="small" onClick={() => navigate("factor_generation")}>去生成因子</Button>}
          />
        )}

        <Divider style={{ margin: "12px 0" }} />

        <Flex gap={16} wrap align="center">
          <Space wrap>
            <Text strong>选因子</Text>
            <Segmented
              size="small" value={selectionMode}
              onChange={(value) => {
                const mode = value as SelectionMode;
                setSelectionMode(mode);
                if (mode === "auto") setSelectedFactorIds([]);
              }}
              options={[
                { value: "auto", label: "自动 TopN" },
                { value: "manual", label: "手动勾选" },
              ]}
            />
            <Text strong>最多因子</Text>
            <InputNumber
              min={1} max={200} value={effectiveMax}
              disabled={selectionMode === "manual"}
              onChange={(value) => setMaxFactors(value ?? 20)}
              style={{ width: 84 }}
            />
            <Text strong>mutual IC</Text>
            <InputNumber
              min={0} max={1} step={0.05} value={mutualIc}
              onChange={(value) => setMutualIc(value ?? 0.8)}
              style={{ width: 84 }}
            />
            <Text strong>z-clip</Text>
            <InputNumber
              min={0.5} max={10} step={0.5} value={zClip} placeholder="不截断"
              onChange={(value) => setZClip(value ?? null)}
              style={{ width: 84 }}
            />
          </Space>
          <Space wrap>
            <Text strong><ToolOutlined /> 组合规模</Text>
            <Checkbox.Group
              options={[5, 10, 20, 30, 50].map((size) => ({ label: `Top ${size}`, value: size }))}
              value={sizes}
              onChange={(values) => setSizes(values as number[])}
            />
            <Text type="secondary">实际提交 {effectiveSizes.length ? effectiveSizes.join(" / ") : "—"}</Text>
          </Space>
          <Space wrap>
            <Button icon={<HistoryOutlined />} onClick={() => navigate("composition_results", undefined, poolId ? JSON.stringify([poolId, null, runIds]) : undefined)}>查看组合结果</Button>

          </Space>
        </Flex>

        <Collapse
          ghost size="small" className="note-action"
          items={[{
            key: "advanced",
            label: <Text type="secondary">高级：回测区间、TopK、单股上限与再平衡</Text>,
            children: (
              <Space direction="vertical" size={10} className="full-width">
                <Row gutter={12} align="bottom">
                  <Col span={7}>
                    <Text type="secondary">回测区间（留空跟随股票池窗口）</Text>
                    <DatePicker.RangePicker
                      className="full-width" value={range}
                      onChange={(values) => {
                        if (values?.[0] && values[1]) setRange([values[0], values[1]]);
                        else setRange(null);
                      }}
                    />
                  </Col>
                  <Col span={3}>
                    <Text type="secondary">TopK 选股</Text>
                    <InputNumber
                      className="full-width" min={1} max={1000} value={topK}
                      onChange={(value) => setTopK(value ?? 50)}
                    />
                  </Col>
                  <Col span={3}>
                    <Text type="secondary">单股上限</Text>
                    <InputNumber
                      className="full-width" min={0.001} max={1} step={0.01} value={maxWeight}
                      onChange={(value) => setMaxWeight(value ?? 0.03)}
                    />
                  </Col>
                  <Col span={3}>
                    <Text type="secondary">再平衡</Text>
                    <Select
                      className="full-width" value={rebalance}
                      onChange={(value) => setRebalance(value as RebalanceFreq)}
                      options={[
                        { value: "1D", label: "每日" },
                        { value: "1W", label: "每周" },
                        { value: "2W", label: "双周" },
                        { value: "1M", label: "每月" },
                      ]}
                    />
                  </Col>
                  <Col span={3}>
                    <Text type="secondary">目标持有期</Text>
                    <InputNumber
                      className="full-width" min={1} max={250} value={targetHorizon}
                      onChange={(value) => setTargetHorizon(value ?? 20)}
                    />
                  </Col>
                  <Col span={5}>
                    {cashDrag && (
                      <Alert
                        type="warning" showIcon
                        message={`TopK × 单股上限 = ${fmtPercent(plannedExposure, 0)}，组合会保留现金`}
                      />
                    )}
                  </Col>
                </Row>
                <Text type="secondary">
                  z-clip 将每日截面 z-score 截断到 ±{zClip ?? "∞"}；留空表示不截断。等权组合不做权重优化，
                  综合分 = 各因子方向调整后每日截面 z-score 的等权平均。
                </Text>
              </Space>
            ),
          }]}
        />

        {jobWarnings.length > 0 && (
          <Alert
            type="warning" showIcon className="note-action"
            message="提交提示"
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>
              {jobWarnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>}
          />
        )}
        </>}
      </Card>

      {!resultsOnly && <Card
        title={<Space><ToolOutlined />候选合格因子<Tag>{candidateRows.length}</Tag>
          {selectionMode === "manual" && <Tag color="blue">已选 {selectedFactorIds.length}</Tag>}
        </Space>}
        className="data-card"
        extra={<Space wrap>
          <Text type="secondary">
            {selectionMode === "auto"
              ? `自动按 Score 取前 ${maxFactors} 个，再做 mutual IC 去重与容量控制`
              : "手动勾选会作为组合上限；仍会做 mutual IC 去重"}
          </Text>
          {selectionMode === "manual" && <>
            <Button
              size="small" disabled={candidateRows.length === 0}
              onClick={() => setSelectedFactorIds(candidateRows.slice(0, maxFactors).map((row) => row.factor_id))}
            >
              选择前 {Math.min(maxFactors, candidateRows.length)} 个
            </Button>
            <Button size="small" disabled={selectedFactorIds.length === 0} onClick={() => setSelectedFactorIds([])}>
              清空
            </Button>
          </>}
          <Button
            size="small" icon={<ReloadOutlined />} loading={detailsApi.loading}
            disabled={runIds.length === 0} onClick={detailsApi.reload}
          >
            刷新
          </Button>
        </Space>}
      >
        {detailsApi.error ? (
          <Alert
            type="error" showIcon message="合格因子加载失败" description={detailsApi.error}
            action={<Button size="small" onClick={detailsApi.reload}>重试</Button>}
          />
        ) : runIds.length === 0 ? (
          <Empty description="先选择股票池和已完成测试确认的因子运行" />
        ) : (
          <Table
            rowKey="factor_id"
            size="small"
            loading={detailsApi.loading}
            columns={candidateColumns}
            dataSource={candidateRows}
            rowSelection={rowSelection}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 1050 }}
            locale={{ emptyText: <Empty description="所选运行没有合格因子" /> }}
          />
        )}
      </Card>}

      {resultsOnly && !showResultPanel && <Card><Empty description="请选择股票池和历史组合" /></Card>}
      {showResultPanel && (
        <Card
          title={<Space>
            <Text>组合结果</Text>
            {compositionId && <Text code>{compositionId}</Text>}
            {displaySize && <Tag color="blue">Top {displaySize}</Tag>}
            {detail && <Tag>{weightMethodTag}</Tag>}
          </Space>}
          className="data-card"
          extra={<Space wrap>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => { detailApi.reload(); screenApi.reload(); historyApi.reload(); }}>
              刷新结果
            </Button>
            <Button size="small" icon={<CloudDownloadOutlined />} onClick={downloadWeights} disabled={!detail}>
              下载权重 JSON
            </Button>
          </Space>}
        >
          {active && (
            <>
              <Flex justify="space-between" gap={12} wrap className="note-action">
                <Text strong><LoadingOutlined spin /> {stageLabel}</Text>
                <Text type="secondary">{job?.message ?? "任务已提交，等待后台子进程启动…"}</Text>
              </Flex>
              <Progress percent={percent} status="active" />
              <Row gutter={16}>
                <Col span={6}><Statistic title="候选因子" value={candidateCount || submission?.candidate_total || 0} /></Col>
                <Col span={6}><Statistic title="已选中" value={acceptedCount} /></Col>
                <Col span={6}><Statistic title="当前规模" value={currentSize || "—"} /></Col>
                <Col span={6}><Statistic title="已完成规模" value={`${completedSizes}${requestedSizes ? ` / ${requestedSizes}` : ""}`} /></Col>
              </Row>
              <Text type="secondary">
                任务在后台子进程运行，离开本页不会中断；本页每 1.5 秒轮询任务状态。
              </Text>
            </>
          )}

          {failed && (
            <Alert
              type="error" showIcon className="note-action"
              message="因子组合任务失败"
              description={<Space direction="vertical" size={4}>
                <Text>{jobError ?? job?.message ?? "后台任务失败"}</Text>
                {jobId && <Text type="secondary">任务 ID：<Text code copyable>{jobId}</Text></Text>}
                <Text type="secondary">完整堆栈见后台任务目录下的 runner.log 与 status.json。</Text>
              </Space>}
            />
          )}

          {finished && !detail && !failed && !detailApi.error && (
            <Flex justify="center" className="note-action">
              <Spin tip="读取组合结果…"><div style={{ width: 240 }} /></Spin>
            </Flex>
          )}

          {!active && !failed && detailApi.error && (
            <Alert
              type="error" showIcon className="note-action"
              message="组合结果读取失败" description={detailApi.error}
              action={<Button size="small" onClick={detailApi.reload}>重试</Button>}
            />
          )}

          {!active && !failed && !detailApi.error && !detail && !finished && (
            <Empty description="还没有可展示的组合结果；提交任务或载入历史组合" />
          )}

          {detail && (
            <Spin spinning={detailApi.loading || screenApi.loading}>
              <Divider />
              <Row gutter={12}>
                <Col span={6}><Card className="metric-card metric-green"><Statistic title="组合 IC" value={fmtNumber(detail.result.composition_metrics.ic, 4)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-blue"><Statistic title="组合 RankIC" value={fmtNumber(detail.result.composition_metrics.rank_ic, 4)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-violet"><Statistic title="组合 ICIR" value={fmtNumber(detail.result.composition_metrics.icir, 2)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-cyan"><Statistic title="参与因子数" value={detail.weights.length} suffix="个" /></Card></Col>
              </Row>
              <Row gutter={12} className="note-action">
                <Col span={6}><Card className="metric-card metric-green"><Statistic title="年化收益" value={fmtPercent(detail.result.backtest_summary.annual_return)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-blue"><Statistic title="夏普" value={fmtNumber(detail.result.backtest_summary.sharpe, 2)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-red"><Statistic title="最大回撤" value={fmtPercent(detail.result.backtest_summary.max_drawdown)} /></Card></Col>
                <Col span={6}><Card className="metric-card metric-orange"><Statistic title="平均换手" value={fmtPercent(detail.result.backtest_summary.average_turnover)} /></Card></Col>
              </Row>

              <Descriptions
                size="small" column={3} className="note-action"
                items={[
                  { key: "pool", label: "股票池", children: selectedPool ? `${selectedPool.name} · ${selectedPool.n_stocks} 只` : detail.pool_id },
                  { key: "method", label: "权重方法", children: methodLabel(detail.manifest.weight_method) },
                  { key: "created", label: "创建时间", children: fmtDateTime(detail.manifest.created_at) },
                  { key: "candidate", label: "候选因子", children: `${detail.manifest.candidate_count} 个` },
                  { key: "selected", label: "入选因子", children: `${detail.manifest.selected_count} 个` },
                  { key: "rejected", label: "去重/容量剔除", children: `${detail.manifest.rejected_count} 个` },
                  { key: "mutual", label: "mutual IC 阈值", children: fmtNumber(detail.manifest.mutual_ic_threshold, 2) },
                  { key: "clip", label: "z-clip", children: detail.manifest.z_clip ?? "不截断" },
                  { key: "runs", label: "来源运行", children: detail.manifest.source_factor_run_ids.join("、") || "—" },
                ]}
              />

              <Divider orientation="left" plain>因子权重</Divider>
              <Table
                rowKey="factor_id" size="small"
                columns={weightColumns} dataSource={detail.weights}
                pagination={false} scroll={{ x: 520 }}
                locale={{ emptyText: <Empty description="没有因子权重记录" /> }}
              />
              <Divider orientation="left" plain>多规模对比</Divider>
              <Table
                rowKey="size" size="small" className="clickable-rows"
                columns={sizeColumns} dataSource={detail.manifest.sizes}
                pagination={false} scroll={{ x: 760 }}
                rowClassName={(record) => record.size === displaySize ? "highlight-row" : ""}
                onRow={(record) => ({ onClick: () => setActiveSize(record.size) })}
                locale={{ emptyText: <Empty description="没有规模结果" /> }}
              />
              <Text type="secondary">点击规模行可切换下方选股清单；默认展示最大规模。</Text>

              <Divider orientation="left" plain>最新一期选股清单</Divider>
              <Flex justify="space-between" gap={12} wrap align="center">
                <Space wrap>
                  <Tag color="blue">信号日 {screenSummary?.signal_date ?? "—"}</Tag>
                  <Tag color={screenSummary?.execution_pending ? "orange" : "green"}>
                    执行日 {screenSummary?.execution_date ?? (screenSummary?.execution_pending ? "下一交易日待定" : "—")}
                  </Tag>
                  <Tag>选中 {screenSummary?.selected_count ?? 0} / TopK {screen?.top_k ?? topK}</Tag>
                  <Tag color="green">次日可买 {screenSummary?.buyable_count ?? "—"}</Tag>
                  <Tag>全市场排名 {screenSummary?.total_ranked ?? "—"}</Tag>
                  <Tag color="cyan">单股计划权重 {fmtPercent(screenSummary?.planned_weight_per_stock, 2)}</Tag>
                  {screen?.refreshed_at && <Tag color="purple">已刷新 {fmtDateTime(screen.refreshed_at)}</Tag>}
                </Space>
                <Space wrap>
                  <Text type="secondary">信号日</Text>
                  <DatePicker
                    size="small"
                    value={refreshSignalDate}
                    allowClear={false}
                    disabledDate={(current) => Boolean(current && current > dayjs().endOf("day"))}
                    onChange={(value) => setRefreshSignalDate(value)}
                  />
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    loading={refreshing}
                    disabled={!refreshSignalDate}
                    onClick={refreshScreen}
                    title="用最新数据重新加载面板，按所选信号日 T 的收盘信号与 T+1 行情复算可买状态（不重跑组合回测）"
                  >
                    刷新选股清单
                  </Button>
                  <Switch size="small" checked={onlySelected} onChange={setOnlySelected} />
                  <Text type="secondary">只看选中</Text>
                  <Text type="secondary">返回 {screen?.returned_rows ?? 0} / {screen?.total_returned_rows ?? 0} 行</Text>
                </Space>
              </Flex>
              {screenApi.error ? (
                <Alert
                  type="warning" showIcon className="note-action"
                  message="最新选股清单读取失败" description={screenApi.error}
                  action={<Button size="small" onClick={screenApi.reload}>重试</Button>}
                />
              ) : screen ? (
                <Table
                  rowKey="rank" size="small" className="note-action"
                  columns={screenColumns} dataSource={visibleScreenRows}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  scroll={{ x: 1100 }}
                  expandable={{
                    expandedRowRender: (record) => (
                      <Table
                        rowKey="factor_id" size="small" pagination={false}
                        dataSource={record.contributions}
                        columns={[
                          { title: "因子", dataIndex: "factor_id", render: (value: string) => <Text code>{value}</Text> },
                          { title: "z-score", dataIndex: "zscore", align: "right", render: (value: number) => fmtNumber(value, 3) },
                          { title: "权重", dataIndex: "weight", align: "right", render: (value: number) => fmtPercent(value, 2) },
                          { title: "贡献", dataIndex: "contribution", align: "right", render: (value: number) => fmtNumber(value, 4) },
                        ]}
                      />
                    ),
                  }}
                  locale={{ emptyText: <Empty description={onlySelected ? "最新一期没有选中的股票" : "没有选股记录"} /> }}
                />
              ) : (
                <Flex justify="center" className="note-action">
                  <Spin tip="读取最新选股清单…"><div style={{ width: 240 }} /></Spin>
                </Flex>
              )}
              <Text type="secondary">
                选股口径：信号日收盘计算组合分，下一交易日开盘买入；停牌、开盘价缺失或涨停的股票会被跳过，
                并继续按排名补足 TopK。执行日为待定时，先用信号日排名展示，次日开盘前需再做可买校验。
              </Text>
            </Spin>
          )}
        </Card>
      )}
    </Space>
  );
}
