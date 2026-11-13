import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Checkbox, Col, DatePicker, Descriptions, Divider, Empty, Flex, Form, Input,
  InputNumber, message, Modal, Progress, Row, Select, Skeleton, Space, Spin, Statistic, Steps, Switch,
  Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CopyOutlined, HistoryOutlined, LoadingOutlined, PlusOutlined, PlayCircleOutlined, ReloadOutlined, RobotOutlined } from "@ant-design/icons";
const { Text } = Typography;
import dayjs, { type Dayjs } from "dayjs";
import { confirmationRow } from "./confirmation";
import { CATEGORY_META, FACTOR_CATEGORIES, classifyFactor, type FactorCategoryKey } from "../../shared/domain/factorCategories";
import { fieldCategory } from "../../shared/domain/fieldCategories";
import { FilterChips } from "../../components/FilterChips";
import type { PageNav } from "../../app/navigation";
import {
  api, useApiData, useJobPolling,
  type AcceptedFactor, type FactorGenerationResponse, type FactorRunDetail, type FactorRunSummary,
  type FieldInfo, type OperatorInfo, type PoolInfo,
} from "../../api/client";

type DateRangeValue = { format: (template: string) => string }[];

type GenFormValues = {
  name: string;
  pool: string;
  fields?: string[];
  operators?: string[];
  train?: DateRangeValue;
  valid?: DateRangeValue;
  test?: DateRangeValue;
  targetHorizon?: number;
  targetFactorCount?: number;
  maxAttempts?: number;
  rolloutTimesteps?: number;
  seed?: number;
  device?: string;
  minCoverage?: number;
  minTrainIc?: number;
  minValidIc?: number;
  minIcir?: number;
  minTrainRankIc?: number;
  minValidRankIc?: number;
  minValidIcir?: number;
};

type GenFactorRow = AcceptedFactor & { category: FactorCategoryKey; phase: "candidate" | "confirmed"; confirmationText: string };

/** 后端 ProgressCallback 上报的 stage 顺序（与 custom_bt/factor_generation.py 一致） */
const GEN_STEPS = [
  { key: "preparing_runtime", title: "准备股票池面板", description: "按 pool_id 导出池内行情并构建训练缓存" },
  { key: "loading_panels", title: "加载训练数据", description: "加载 train / valid 面板，test 留给独立确认任务" },
  { key: "initializing", title: "初始化 PPO 环境", description: "构建 AlphaGen 环境与策略网络" },
  { key: "training", title: "PPO 采样与评估", description: "在字段与算子空间内搜索表达式" },
  { key: "finished", title: "写入运行清单", description: "保存可接受因子与 factor_run.json，等待独立测试确认" },
] as const;

const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  GEN_STEPS.map((step) => [step.key, step.title]),
);

/** 生成器要提交面板列名：优先用后端给的 panel_alias（vol→volume、财务→fund_*、估值→val_*）。 */
const generationFieldName = (field: FieldInfo) =>
  field.panel_alias ?? (field.name === "vol" ? "volume" : field.name);

const FIELD_PERIOD_LABELS: Record<string, string> = {
  flow: "累计",
  flow_q: "单季",
  stock: "时点",
  ratio: "比率",
  daily: "日频",
  derived: "派生",
};

const HiddenValue = () => null;

const asNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const fmtDuration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} 分 ${total % 60} 秒`;
  return `${Math.floor(minutes / 60)} 时 ${minutes % 60} 分`;
};

const fmtDateTime = (value: string | null | undefined): string =>
  value ? String(value).replace("T", " ").slice(0, 19) : "—";

const fmtInteger = (value: number | null | undefined): string =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toLocaleString();

const splitDaysLabel = (run: FactorRunSummary): string =>
  run.split_days
    ? Object.entries(run.split_days).map(([name, days]) => `${name} ${days}`).join(" · ")
    : "—";

const storageLabel = (storage?: string | null): string => {
  if (storage === "mysql+local") return "MySQL+本地";
  if (storage === "mysql") return "MySQL";
  return "本地";
};

/** 可接受因子与确认结果分别展示；测试集只由独立确认任务评估。 */
function RunFactorPreview({ runId }: { runId: string }) {
  const detailApi = useApiData(() => api.factorRun(runId), [runId]);
  const confirmed = detailApi.data?.confirmed_factors ?? [];
  const historical = detailApi.data?.historical_factors ?? [];
  const factors = [
    ...(detailApi.data?.candidate_factors ?? []).map((factor) =>
      confirmationRow(factor, detailApi.data)),
    ...historical.map((factor) => ({ ...factor, phase: "historical", confirmationText: "旧规则接受，未按当前门槛确认" })),
  ];
  const columns: TableColumnsType<AcceptedFactor & { phase: string; confirmationText: string }> = [
    { title: "状态", width: 110, render: (_, record) => <Tag color={record.phase === "confirmed" ? "green" : record.phase === "historical" ? "default" : "blue"}>{record.phase === "confirmed" ? "合格" : record.phase === "historical" ? "旧规则接受" : "可接受因子"}</Tag> },
    {
      title: "表达式", dataIndex: "expression", width: 300,
      render: (value: string) => <Text code copyable>{value}</Text>,
    },
    {
      title: "Score", dataIndex: "score", width: 80, align: "right",
      sorter: (a, b) => asNumber(a.score) - asNumber(b.score),
      render: (value: number | null) => fmtNumber(value),
    },
    { title: "训练 IC", width: 85, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "train")?.ic) },
    { title: "验证 IC", width: 85, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "valid")?.ic) },
    { title: "测试 IC", width: 85, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.ic) },
    { title: "测试 RankIC", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.rank_ic) },
    { title: "测试 ICIR", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.icir) },
    { title: "测试覆盖率", width: 100, align: "right", render: (_, record) => fmtPercent(segmentOf(record, "test")?.coverage) },
    { title: "测试有效天数", width: 110, align: "right", render: (_, record) => fmtInteger(segmentOf(record, "test")?.valid_days) },
    { title: "确认结果", dataIndex: "confirmationText", width: 260 },
    { title: "训练 ICIR", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "train")?.icir, 2) },
    { title: "覆盖率", width: 90, align: "right", render: (_, record) => fmtPercent(segmentOf(record, "train")?.coverage) },
  ];
  if (detailApi.loading) {
    return <Spin size="small" tip="读取已存储的因子…"><div style={{ height: 48 }} /></Spin>;
  }
  if (detailApi.error) {
    return <Alert type="warning" showIcon message="读取运行因子失败" description={detailApi.error} />;
  }
  if (factors.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次运行没有可接受因子" />;
  }
  return (
    <Space direction="vertical" size={8} className="full-width">
      <Text type="secondary">
        可接受因子 {factors.length - historical.length} 个 · 合格 {confirmed.length} 个 · 旧规则接受 {historical.length} 个
        {detailApi.data?.local_available === false
          ? "（来自 MySQL factors 表）"
          : "（candidate / confirmed 两阶段记录）"}
      </Text>
      {historical.length > 0 && <Alert type="info" showIcon message="历史因子仅按旧规则接受，未按当前质量门槛及测试集确认，不计入当前可接受或合格因子。" />}
      <RunConfirmation runId={runId} onComplete={detailApi.reload} />
      <Table
        rowKey="factor_id"
        size="small"
        columns={columns}
        dataSource={factors}
        pagination={{ pageSize: 5, showSizeChanger: false }}
        scroll={{ x: 1750 }}
      />
    </Space>
  );
}

function RunConfirmation({ runId, onComplete }: { runId: string; onComplete: () => void }) {
  const detail = useApiData(() => api.factorRun(runId), [runId]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { job, error, polling } = useJobPolling(jobId);
  const finished = useRef<string | null>(null);
  useEffect(() => {
    if (!jobId || job?.status !== "finished" || finished.current === jobId) return;
    finished.current = jobId;
    detail.reload();
    onComplete();
  }, [jobId, job?.status, detail.reload, onComplete]);
  const submit = async () => {
    setSubmitting(true);
    try { const result = await api.confirmFactorRun(runId); setJobId(result.job_id); }
    catch (err) { message.error(err instanceof Error ? err.message : String(err)); }
    finally { setSubmitting(false); }
  };
  const run = detail.data;
  return <Space direction="vertical" size={4}>
    <Text>可接受因子 {run?.candidate_count ?? 0} · 合格 {run?.confirmed_count ?? 0} · {run?.confirmation_status ?? "pending"}</Text>
    {run?.confirmation_status === "finished" && <Text type="secondary">未通过测试确认 {Math.max(0, (run.candidate_count ?? 0) - (run.confirmed_count ?? 0))} 个；测试结果已保存，不会在回测时重新评估。</Text>}
    <Button onClick={submit} loading={submitting || polling}
      disabled={!run || run.local_available === false || (run.candidate_count ?? 0) === 0 || (run.confirmation_status === "finished" || run.confirmation_status === "running") || run.manifest.generation_status !== "finished"}>
      {run?.confirmation_status === "finished" ? "测试集确认已完成" : "因子确认（一次性测试集评估）"}
    </Button>
    {(error || job?.status === "failed") && <Text type="danger">{error ?? job?.message}</Text>}
    {job && <Text type="secondary">{job.message}</Text>}
  </Space>;
}

const fmtNumber = (value: number | null | undefined, digits = 3) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toFixed(digits);

const fmtPercent = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;

const formatElapsed = (ms: number) => {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes} 分 ${seconds} 秒` : `${seconds} 秒`;
};

const segmentOf = (row: AcceptedFactor, name: string) => row.segments?.[name];

function poolOptions(pools: PoolInfo[]) {
  return pools.map((pool) => ({
    value: pool.pool_id,
    label: `${pool.name} · ${pool.n_stocks} 只${pool.data_source === "clickhouse" ? "" : "（本地缓存池）"}`,
  }));
}

export function FactorGenerationPage({ navigate, initialRunId }: { navigate: PageNav; initialRunId?: string }) {
  const [form] = Form.useForm<GenFormValues>();
  const [jobId, setJobId] = useState<string | null>(null);
  const [submission, setSubmission] = useState<FactorGenerationResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [runDetail, setRunDetail] = useState<FactorRunDetail | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [runId, setRunId] = useState<string | null>(initialRunId ?? null);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const loadedRunRef = useRef<string | null>(null);
  const defaultsApplied = useRef(false);
  const splitsAppliedKey = useRef<string | null>(null);

  const [fieldPickerOpen, setFieldPickerOpen] = useState(false);
  const [operatorPickerOpen, setOperatorPickerOpen] = useState(false);
  const [fieldDraft, setFieldDraft] = useState<string[]>([]);
  const [operatorDraft, setOperatorDraft] = useState<string[]>([]);
  const [fieldCategoryFilter, setFieldCategoryFilter] = useState("all");
  const [fieldThemeFilter, setFieldThemeFilter] = useState("all");
  const [fieldPeriodFilter, setFieldPeriodFilter] = useState("all");
  const [fieldUnitFilter, setFieldUnitFilter] = useState("all");
  const [onlyUsable, setOnlyUsable] = useState(true);
  const [fieldSearch, setFieldSearch] = useState("");
  const [operatorCategory, setOperatorCategory] = useState("all");
  const [operatorSearch, setOperatorSearch] = useState("");

  const [historyPool, setHistoryPool] = useState("all");
  const [historyDevice, setHistoryDevice] = useState("all");
  const [historySearch, setHistorySearch] = useState("");

  const selectedPool = Form.useWatch("pool", form) as string | undefined;
  const defaultsApi = useApiData(
    () => api.factorGenerationDefaults(selectedPool),
    [selectedPool],
  );
  const poolsApi = useApiData(api.pools);
  const historyApi = useApiData(api.factorRuns);
  const fieldsApi = useApiData(api.fields);
  const operatorsApi = useApiData(api.operators);
  const { job, error: jobError } = useJobPolling(jobId);

  const selectedFields = (Form.useWatch("fields", form) as string[] | undefined) ?? [];
  const selectedOperators = (Form.useWatch("operators", form) as string[] | undefined) ?? [];

  const fieldOptions = useMemo(() => {
    const seen = new Set<string>();
    return (fieldsApi.data?.fields ?? []).map((field) => ({ ...field, value: generationFieldName(field) })).filter((field) => {
      if (seen.has(field.value)) return false;
      seen.add(field.value);
      return true;
    });
  }, [fieldsApi.data]);
  const fieldMetaByValue = useMemo(
    () => new Map(fieldOptions.map((field) => [field.value, field])),
    [fieldOptions],
  );
  const fieldCategories = [...new Set(fieldOptions.map((field) => fieldCategory(field).label))];
  const fieldScope = fieldCategoryFilter === "all"
    ? fieldOptions
    : fieldOptions.filter((field) => fieldCategory(field).label === fieldCategoryFilter);
  const fieldThemes = [...new Set(fieldScope.map((field) => field.theme).filter(Boolean))].sort() as string[];
  const fieldPeriods = [...new Set(fieldScope.map((field) => field.period_type).filter(Boolean))].sort() as string[];
  const fieldUnits = [...new Set(fieldScope.map((field) => field.unit).filter(Boolean))].sort() as string[];
  const visibleFields = fieldOptions.filter((field) => {
    if (onlyUsable && field.expression === false) return false;
    if (fieldCategoryFilter !== "all" && fieldCategory(field).label !== fieldCategoryFilter) return false;
    if (fieldThemeFilter !== "all" && field.theme !== fieldThemeFilter) return false;
    if (fieldPeriodFilter !== "all" && field.period_type !== fieldPeriodFilter) return false;
    if (fieldUnitFilter !== "all" && field.unit !== fieldUnitFilter) return false;
    return `${field.name}${field.description}${field.theme ?? ""}`.toLowerCase().includes(fieldSearch.toLowerCase());
  });

  const allOperators = useMemo(() => operatorsApi.data?.operators ?? [], [operatorsApi.data]);
  const genOperators = useMemo(
    () => allOperators.filter((operator) => operator.generation_enabled),
    [allOperators],
  );
  const operatorCategories = [...new Set(genOperators.map((operator) => operator.category_cn))];
  const visibleOperators = genOperators.filter((operator) => {
    if (operatorCategory !== "all" && operator.category_cn !== operatorCategory) return false;
    return `${operator.name}${operator.description_cn}`.toLowerCase().includes(operatorSearch.toLowerCase());
  });

  // 后端默认参数：首次加载后写入 PPO 参数与质量阈值，字段由用户选择。
  useEffect(() => {
    const defaults = defaultsApi.data;
    if (!defaults || defaultsApplied.current) return;
    defaultsApplied.current = true;
    form.setFieldsValue({
      targetHorizon: defaults.target_horizon,
      targetFactorCount: defaults.target_factor_count,
      maxAttempts: defaults.max_attempts,
      rolloutTimesteps: defaults.rollout_timesteps,
      seed: defaults.seed,
      device: defaults.device,
      minCoverage: defaults.quality.min_coverage ?? 0.9,
      minTrainIc: defaults.quality.min_train_ic ?? 0.05,
      minValidIc: defaults.quality.min_valid_ic ?? 0.03,
      minTrainRankIc: defaults.quality.min_train_rank_ic ?? 0.03,
      minValidRankIc: defaults.quality.min_valid_rank_ic ?? 0.03,
      minValidIcir: defaults.quality.min_valid_icir ?? 0.3,
      minIcir: defaults.quality.min_icir ?? 0.5,
    });
  }, [defaultsApi.data, form]);

  // 数据切分跟随股票池真实时间跨度：切换股票池后应用后端按比例切好的日期。
  useEffect(() => {
    const defaults = defaultsApi.data;
    if (!defaults) return;
    const key = JSON.stringify({
      source: defaults.split_source,
      window: defaults.pool_window,
      splits: defaults.splits,
    });
    if (splitsAppliedKey.current === key) return;
    splitsAppliedKey.current = key;
    const range = (value?: { cache_start: string; cache_end: string }) =>
      value ? [dayjs(value.cache_start), dayjs(value.cache_end)] : undefined;
    form.setFieldsValue({
      train: range(defaults.splits.train),
      valid: range(defaults.splits.valid),
      test: range(defaults.splits.test),
    });
  }, [defaultsApi.data, form]);

  const pools = poolsApi.data?.pools ?? [];

  // 运行历史：MySQL 元数据 + 本地目录合并后的记录，可按股票池 / 设备 / 关键词过滤。
  const historyRuns = useMemo(() => historyApi.data?.runs ?? [], [historyApi.data]);
  const poolNameById = useMemo(
    () => new Map(pools.map((pool) => [pool.pool_id, pool.name])),
    [pools],
  );
  const historyPoolOptions = useMemo(() => {
    const ids = new Set<string>();
    historyRuns.forEach((run) => { if (run.pool_id) ids.add(String(run.pool_id)); });
    return [...ids].sort().map((id) => ({
      value: id,
      label: poolNameById.has(id) ? `${poolNameById.get(id)} · ${id}` : id,
    }));
  }, [historyRuns, poolNameById]);
  const filteredHistoryRuns = useMemo(() => {
    const keyword = historySearch.trim().toLowerCase();
    return historyRuns.filter((run) => {
      if (historyPool !== "all" && String(run.pool_id ?? "") !== historyPool) return false;
      if (historyDevice === "unknown" && run.device) return false;
      if (historyDevice !== "all" && historyDevice !== "unknown" && String(run.device ?? "") !== historyDevice) return false;
      if (!keyword) return true;
      const poolName = poolNameById.get(String(run.pool_id ?? "")) ?? "";
      return `${run.run_id} ${run.run_name ?? ""} ${run.pool_id ?? ""} ${poolName}`.toLowerCase().includes(keyword);
    });
  }, [historyRuns, historyPool, historyDevice, historySearch, poolNameById]);

  // 默认选中第一个真实创建的股票池，不再硬编码 liquid_500。
  useEffect(() => {
    if (selectedPool || pools.length === 0) return;
    form.setFieldValue("pool", pools[0].pool_id);
  }, [pools, selectedPool, form]);

  // 运行中每秒刷新已用时间；任务结束后冻结。
  useEffect(() => {
    if (!jobId || runStartedAt === null) return;
    if (job && job.status !== "queued" && job.status !== "running") return;
    const timer = window.setInterval(() => setElapsedMs(Date.now() - runStartedAt), 1000);
    return () => window.clearInterval(timer);
  }, [jobId, runStartedAt, job]);

  // PPO 完成后读取可接受因子；测试确认由独立任务执行。
  useEffect(() => {
    if (!job) return;
    if (job.status === "failed" || job.status === "missing") {
      setRunError(jobError ?? job.message ?? "因子生成任务失败");
      return;
    }
    if (job.status !== "finished") return;
    const resultRunId = typeof job.result?.run_id === "string" ? job.result.run_id : null;
    const finishedRunId = resultRunId ?? runId ?? submission?.run_id ?? null;
    if (!finishedRunId) {
      setRunError("任务已完成，但未返回 run_id，无法读取因子结果");
      return;
    }
    setRunId(finishedRunId);
    if (loadedRunRef.current === finishedRunId) return;
    loadedRunRef.current = finishedRunId;
    historyApi.reload();
    let alive = true;
    setRunLoading(true);
    setRunError(null);
    api.factorRun(finishedRunId)
      .then((detail) => { if (alive) setRunDetail(detail); })
      .catch((err: unknown) => {
        if (alive) setRunError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => { if (alive) setRunLoading(false); });
    return () => { alive = false; };
  }, [job, jobError, runId, submission, historyApi.reload]);

  const openFieldPicker = () => {
    setFieldDraft(((form.getFieldValue("fields") as string[] | undefined) ?? []).slice());
    setFieldSearch("");
    setFieldCategoryFilter("all");
    setFieldPickerOpen(true);
  };
  const openOperatorPicker = () => {
    const selected = (form.getFieldValue("operators") as string[] | undefined) ?? [];
    const allowed = new Set(genOperators.map((operator) => operator.name));
    setOperatorDraft(selected.filter((name) => allowed.has(name)));
    setOperatorSearch("");
    setOperatorCategory("all");
    setOperatorPickerOpen(true);
  };
  const confirmFields = () => {
    form.setFieldValue("fields", fieldDraft);
    setFieldPickerOpen(false);
  };
  const confirmOperators = () => {
    form.setFieldValue("operators", operatorDraft);
    setOperatorPickerOpen(false);
  };

  const submit = async (values: GenFormValues) => {
    const fields = values.fields ?? [];
    if (!values.operators?.length) {
      message.error("请至少选择一个操作符");
      return;
    }
    if (fields.length === 0) {
      message.error("请至少选择一个因子字段");
      return;
    }
    if (!values.pool) {
      message.error("请选择股票池；没有股票池时请先到「股票池」页创建");
      return;
    }
    const rawFlowFields = fields.filter((name) => fieldMetaByValue.get(name)?.period_type === "flow");
    const quarterFlowFields = fields.filter((name) => fieldMetaByValue.get(name)?.period_type === "flow_q");
    if (rawFlowFields.length > 0 && quarterFlowFields.length > 0) {
      message.error("财务流量字段不能同时使用累计和单季口径，请只保留一种。");
      return;
    }
    const range = (value?: DateRangeValue) => {
      const dates = value?.map((item) => item.format("YYYY-MM-DD"));
      return dates && dates.length === 2 ? { cache_start: dates[0], cache_end: dates[1] } : undefined;
    };
    const train = range(values.train);
    const valid = range(values.valid);
    const test = range(values.test);
    if (!train || !valid || !test) {
      message.error("请完整填写 train / valid / test 数据切分");
      return;
    }
    const pickedOperators = (values.operators ?? []).filter((name) =>
      genOperators.some((operator) => operator.name === name),
    );
    if (!pickedOperators.length) {
      message.error("请至少选择一个 PPO 支持的操作符");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.createFactorGeneration({
        pool_id: values.pool,
        run_name: values.name,
        fields,
        operators: pickedOperators,
        splits: { train, valid, test },
        target_horizon: values.targetHorizon,
        target_factor_count: values.targetFactorCount,
        max_attempts: values.maxAttempts,
        rollout_timesteps: values.rolloutTimesteps,
        seed: values.seed,
        device: values.device,
        quality: {
          min_coverage: values.minCoverage,
          min_train_ic: values.minTrainIc,
          min_valid_ic: values.minValidIc,
          min_icir: values.minIcir,
          min_train_rank_ic: values.minTrainRankIc,
          min_valid_rank_ic: values.minValidRankIc,
          min_valid_icir: values.minValidIcir,
          min_test_coverage: 0.9,
          min_test_ic: 0.03,
          min_test_rank_ic: 0.03,
          min_test_icir: 0.3,
        },
      });
      setSubmission(response);
      setJobId(response.job_id);
      setRunId(response.run_id);
      setRunDetail(null);
      setRunError(null);
      setRunLoading(false);
      loadedRunRef.current = null;
      setRunStartedAt(Date.now());
      setElapsedMs(0);
      message.success(`已提交因子生成任务 ${response.job_id}`);
      if (response.warnings.length) {
        message.warning(response.warnings.join("；"), 6);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const resetRun = () => {
    setJobId(null);
    setSubmission(null);
    setRunDetail(null);
    setRunError(null);
    setRunLoading(false);
    setRunId(null);
    setRunStartedAt(null);
    setElapsedMs(0);
    loadedRunRef.current = null;
  };

  const active = Boolean(jobId) && !jobError && (!job || job.status === "queued" || job.status === "running");
  const failed = Boolean(jobId) && (Boolean(jobError) || job?.status === "failed" || job?.status === "missing");
  const finished = Boolean(jobId) && job?.status === "finished";
  const showRunPanel = active || failed || finished;

  const progressData = job?.progress ?? {};
  const stage = String(progressData.stage ?? (job?.status === "queued" ? "queued" : ""));
  const attempts = asNumber(progressData.attempts);
  const accepted = asNumber(progressData.candidate_count ?? progressData.accepted_count);
  const targetCount = asNumber(
    progressData.target_count ?? submission?.request_summary?.target_factor_count,
    defaultsApi.data?.target_factor_count ?? 0,
  );
  const maxAttempts = asNumber(
    progressData.max_attempts ?? submission?.request_summary?.max_attempts,
    defaultsApi.data?.max_attempts ?? 0,
  );
  const timesteps = asNumber(progressData.timesteps);
  const percent = finished
    ? 100
    : maxAttempts > 0
      ? Math.min(99, Math.round((attempts / maxAttempts) * 100))
      : targetCount > 0
        ? Math.min(99, Math.round((accepted / targetCount) * 100))
        : 0;
  const stageIndex = GEN_STEPS.findIndex((step) => step.key === stage);
  const currentStep = finished ? GEN_STEPS.length : stage === "queued" ? 0 : Math.max(0, stageIndex);
  const stageLabel = STAGE_LABELS[stage] ?? (job?.status === "queued" ? "等待后台进程启动" : "任务运行中");

  const resultRows: GenFactorRow[] = useMemo(
    () =>
      (runDetail?.candidate_factors ?? [])
        .map((factor) => {
          return { ...confirmationRow(factor, runDetail), category: classifyFactor(String(factor.expression ?? "")) };
        })
        .sort((a, b) => asNumber(b.score) - asNumber(a.score)),
    [runDetail],
  );

  const resultColumns: TableColumnsType<GenFactorRow> = [
    { title: "状态", width: 90, render: (_, record) => <Tag color={record.phase === "confirmed" ? "green" : "blue"}>{record.phase === "confirmed" ? "合格" : "可接受因子"}</Tag> },
    { title: "表达式", dataIndex: "expression", width: 320, fixed: "left", render: (value: string) => <Text code copyable>{value}</Text> },
    {
      title: "类别",
      dataIndex: "category",
      width: 100,
      filters: FACTOR_CATEGORIES.map((item) => ({ text: item.label, value: item.key })),
      onFilter: (value, record) => record.category === value,
      render: (key: FactorCategoryKey) => {
        const meta = CATEGORY_META[key];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "Score", dataIndex: "score", width: 90, align: "right", defaultSortOrder: "descend",
      sorter: (a, b) => asNumber(a.score) - asNumber(b.score), render: (value: number | null) => fmtNumber(value),
    },
    { title: "训练 IC", width: 90, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "train")?.ic) },
    { title: "验证 IC", width: 90, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "valid")?.ic) },
    { title: "测试 IC", width: 90, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.ic) },
    { title: "测试 RankIC", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.rank_ic) },
    { title: "测试 ICIR", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "test")?.icir) },
    { title: "测试覆盖率", width: 100, align: "right", render: (_, record) => fmtPercent(segmentOf(record, "test")?.coverage) },
    { title: "测试有效天数", width: 110, align: "right", render: (_, record) => fmtInteger(segmentOf(record, "test")?.valid_days) },
    { title: "确认结果", dataIndex: "confirmationText", width: 260 },
    { title: "训练 ICIR", width: 100, align: "right", render: (_, record) => fmtNumber(segmentOf(record, "train")?.icir, 2) },
    { title: "覆盖率", width: 90, align: "right", render: (_, record) => fmtPercent(segmentOf(record, "train")?.coverage) },
    { title: "有效天数", width: 90, align: "right", render: (_, record) => segmentOf(record, "train")?.valid_days ?? "—" },
  ];

  const historyColumns: TableColumnsType<FactorRunSummary> = [
    {
      title: "完成时间", dataIndex: "created_at", width: 160,
      render: (value: string | null) => fmtDateTime(value),
    },
    {
      title: "运行名称", dataIndex: "run_name", width: 170, ellipsis: true,
      render: (value: string | null, record) => value || <Text type="secondary">{record.run_id}</Text>,
    },
    {
      title: "股票池", dataIndex: "pool_id", width: 200, ellipsis: true,
      render: (value: string | null) => {
        const id = String(value ?? "");
        const name = poolNameById.get(id);
        return name ? <span title={id}>{name}</span> : (id || "—");
      },
    },
    {
      title: "设备", dataIndex: "device", width: 80,
      render: (value: string | null) => {
        const device = String(value ?? "").toLowerCase();
        if (!device) return <Tag>未知</Tag>;
        return <Tag color={device === "cuda" ? "green" : "blue"}>{device.toUpperCase()}</Tag>;
      },
    },
    {
      title: "训练时长", dataIndex: "training_seconds", width: 120, align: "right",
      sorter: (a, b) => asNumber(a.training_seconds ?? a.duration_seconds) - asNumber(b.training_seconds ?? b.duration_seconds),
      render: (value: number | null, record) => value === null || value === undefined
        ? <span title="历史运行未单独记录纯训练耗时，显示任务总耗时">{fmtDuration(record.duration_seconds)}（总）</span>
        : fmtDuration(value),
    },
    {
      title: "状态", dataIndex: "target_reached", width: 100,
      render: (value: boolean | null, record) => value
        ? <Tag color="green">已达标</Tag>
        : record.attempts_exhausted
          ? <Tag color="orange">次数耗尽</Tag>
          : <Tag>未达标</Tag>,
    },
    {
      title: "尝试", dataIndex: "attempts", width: 80, align: "right",
      sorter: (a, b) => asNumber(a.attempts) - asNumber(b.attempts),
      render: (value: number | null) => fmtInteger(value),
    },
    { title: "合格", dataIndex: "confirmed_count", width: 80, align: "right", render: (value) => value ?? 0 },
    {
      title: "可接受因子", dataIndex: "candidate_count", width: 80, align: "right",
      sorter: (a, b) => asNumber(a.candidate_count) - asNumber(b.candidate_count),
      render: (value: number | null) => fmtInteger(value),
    },
    {
      title: "目标", dataIndex: "target_factor_count", width: 70, align: "right",
      render: (value: number | null) => (value === null || value === undefined ? "—" : value),
    },
    {
      title: "Rollout", dataIndex: "rollout_timesteps", width: 90, align: "right",
      render: (value: number | null) => (value === null || value === undefined ? "—" : value),
    },
    {
      title: "Seed", dataIndex: "seed", width: 70, align: "right",
      render: (value: number | null) => (value === null || value === undefined ? "—" : value),
    },
    {
      title: "来源", dataIndex: "storage", width: 100,
      render: (value: string | null) => (
        <Tag color={String(value ?? "").includes("mysql") ? "geekblue" : "default"}>
          {storageLabel(value)}
        </Tag>
      ),
    },
  ];

  const selectedPoolInfo = pools.find((pool) => pool.pool_id === selectedPool);
  const summary: Record<string, unknown> = submission?.request_summary ?? {};
  const summaryFields = summary.field_count;
  const summaryOperators = summary.operators;
  const summarySplits = summary.splits as Record<string, { cache_start?: string; cache_end?: string }> | undefined;
  const finishedManifest = runDetail?.manifest ?? {};
  const finishedAttempts = asNumber(finishedManifest.attempts, attempts);
  const finishedAccepted = asNumber(runDetail?.candidate_count ?? finishedManifest.candidate_count, accepted);
  const splitWindow = defaultsApi.data?.pool_window ?? null;
  const splitWindowStart = splitWindow ? dayjs(splitWindow.start) : null;
  const splitWindowEnd = splitWindow ? dayjs(splitWindow.end) : null;
  const disabledSplitDate = (current: Dayjs) => {
    if (!splitWindowStart || !splitWindowEnd) return false;
    return current.isBefore(splitWindowStart, "day") || current.isAfter(splitWindowEnd, "day");
  };
  const splitRatioLabel = defaultsApi.data
    ? ["train", "valid", "test"]
        .map((name) => `${name} ${Math.round((defaultsApi.data?.split_ratios[name] ?? 0) * 100)}%`)
        .join(" / ")
    : "";

  return (
    <>
      <Row gutter={16} className="backtest-layout factor-generation-layout">
        <Col span={10}>
          <Card title={<Space><RobotOutlined />PPO 生成参数</Space>} className="form-card">
            {defaultsApi.error && (
              <Alert
                type="error" showIcon className="note-action"
                message="默认参数加载失败"
                description={defaultsApi.error}
                action={<Button size="small" icon={<ReloadOutlined />} onClick={defaultsApi.reload}>重试</Button>}
              />
            )}
            <Form
              form={form}
              layout="vertical"
              onFinish={submit}
              initialValues={{
                name: `ppo_run_${dayjs().format("YYYYMMDD")}`,
                fields: [], operators: [],
                targetHorizon: 20, targetFactorCount: 50,
                maxAttempts: 100000, rolloutTimesteps: 2048, seed: 0, device: "auto",
                minCoverage: 0.9, minTrainIc: 0.05, minValidIc: 0.04, minIcir: 0.5,
              }}
            >
              <Form.Item label="生成算法" extra="当前后端只实现了 PPO 因子生成；大模型生成尚未接入。">
                <Select
                  value="ppo" disabled
                  options={[{ value: "ppo", label: "PPO（已接入）" }, { value: "llm", label: "大模型（暂未接入）", disabled: true }]}
                />
              </Form.Item>
              <Form.Item name="fields" hidden rules={[{ required: true, message: "至少选择一个字段" }]}><HiddenValue /></Form.Item>
              <Form.Item name="operators" hidden><HiddenValue /></Form.Item>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item label="股票池" name="pool" rules={[{ required: true, message: "请选择股票池" }]}>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      loading={poolsApi.loading}
                      disabled={poolsApi.loading || pools.length === 0}
                      placeholder={pools.length === 0 ? "暂无股票池，请先创建" : "选择已创建的股票池"}
                      options={poolOptions(pools)}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="运行名称" name="name" rules={[{ required: true, message: "请输入运行名称" }]}><Input /></Form.Item>
                </Col>
              </Row>
              {poolsApi.error && (
                <Alert
                  type="error" showIcon className="note-action"
                  message="股票池列表加载失败"
                  description={poolsApi.error}
                  action={<Button size="small" icon={<ReloadOutlined />} onClick={poolsApi.reload}>重试</Button>}
                />
              )}
              {poolsApi.data && pools.length === 0 && (
                <Alert
                  type="warning" showIcon className="note-action"
                  message="还没有股票池"
                  description={<span>因子生成必须绑定真实创建的股票池；请先按行业/市场筛选建池。</span>}
                  action={<Button size="small" type="primary" onClick={() => navigate("pools")}>去创建股票池</Button>}
                />
              )}
              <Form.Item
                label={`数据字段（已选 ${selectedFields.length}）`}
                required
                extra="请选择参与因子生成的数据字段；财务流量字段需统一口径：累计（fund_X）与单季（fund_X_q）不能混用。"
              >
                <Flex gap={6} wrap align="center">
                  {selectedFields.slice(0, 8).map((field) => <Tag key={field}>{field}</Tag>)}
                  {selectedFields.length > 8 && <Tag>+{selectedFields.length - 8}</Tag>}
                  <Button size="small" icon={<PlusOutlined />} onClick={openFieldPicker}>选择字段</Button>
                </Flex>
              </Form.Item>
              <Form.Item
                label={`操作符（已选 ${selectedOperators.length}）`}
                required
                extra={allOperators.length > 0 ? `PPO 可采样 ${genOperators.length} / API 共 ${allOperators.length} 个算子` : undefined}
              >
                <Flex gap={6} wrap align="center">
                  {selectedOperators.slice(0, 8).map((operator) => <Tag key={operator}>{operator}</Tag>)}
                  {selectedOperators.length > 8 && <Tag>+{selectedOperators.length - 8}</Tag>}
                  <Button size="small" icon={<PlusOutlined />} onClick={openOperatorPicker}>选择操作符</Button>
                </Flex>
              </Form.Item>
              <Divider orientation="left" plain>PPO 参数</Divider>
              <Row gutter={12}>
                <Col span={12}><Form.Item label="最大尝试次数" name="maxAttempts"><InputNumber className="full-width" min={1} step={10000} /></Form.Item></Col>
                <Col span={12}><Form.Item label="Rollout 步数" name="rolloutTimesteps"><InputNumber className="full-width" min={64} step={512} /></Form.Item></Col>
                <Col span={12}><Form.Item label="随机种子" name="seed"><InputNumber className="full-width" min={0} /></Form.Item></Col>
                <Col span={12}><Form.Item label="计算设备" name="device"><Select options={[{ value: "auto", label: "自动（优先 GPU）" }, { value: "cpu", label: "CPU" }, { value: "cuda", label: "CUDA (GPU)" }]} /></Form.Item></Col>
              </Row>
              <Divider orientation="left" plain>数据切分</Divider>
              {splitWindow ? (
                <Alert
                  type="info" showIcon className="note-action"
                  message={`已按股票池真实时间跨度 ${splitWindow.start} ~ ${splitWindow.end} 自动切分`}
                  description={`${splitRatioLabel}；可手动调整，但日期必须落在该跨度内。`}
                />
              ) : defaultsApi.data?.warnings?.length ? (
                <Alert
                  type="warning" showIcon className="note-action"
                  message="未取到股票池时间跨度，暂用配置默认切分"
                  description={defaultsApi.data.warnings.join("；")}
                />
              ) : null}
              <Form.Item label="训练段 train" name="train" rules={[{ required: true, message: "请选择训练段" }]}><DatePicker.RangePicker className="full-width" disabledDate={disabledSplitDate} /></Form.Item>
              <Form.Item label="验证段 valid" name="valid" rules={[{ required: true, message: "请选择验证段" }]}><DatePicker.RangePicker className="full-width" disabledDate={disabledSplitDate} /></Form.Item>
              <Form.Item label="测试段 test" name="test" rules={[{ required: true, message: "请选择测试段" }]}><DatePicker.RangePicker className="full-width" disabledDate={disabledSplitDate} /></Form.Item>
              <Divider orientation="left" plain>搜索与训练</Divider>
              <Row gutter={12}>
                <Col span={12}><Form.Item label="目标持有期 horizon" name="targetHorizon" rules={[{ type: "number", min: 1, max: 60 }]}><InputNumber className="full-width" min={1} max={60} /></Form.Item></Col>
                <Col span={12}><Form.Item label="目标因子数" name="targetFactorCount"><InputNumber className="full-width" min={1} max={200} /></Form.Item></Col>
              </Row>
              <Divider orientation="left" plain>质量阈值</Divider>
              <Alert type="info" showIcon message="验证和测试的 IC、RankIC、ICIR 符号均须与训练 IC 相同。测试确认门槛固定：coverage ≥ 0.9，|IC| / |RankIC| ≥ 0.03，|ICIR| ≥ 0.3；确认后不可据测试结果反复调参。" style={{ marginBottom: 12 }} />
              <Row gutter={12}>
                <Col span={12}><Form.Item label="训练／验证最低覆盖率" name="minCoverage" rules={[{ type: "number", min: 0.9, max: 1 }]}><InputNumber className="full-width" min={0.9} max={1} step={0.05} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低训练 |IC|" name="minTrainIc" rules={[{ type: "number", min: 0.05, max: 1 }]}><InputNumber className="full-width" min={0.05} max={1} step={0.01} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低验证 |IC|" name="minValidIc" rules={[{ type: "number", min: 0.03, max: 1 }]}><InputNumber className="full-width" min={0.03} max={1} step={0.01} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低训练 |RankIC|" name="minTrainRankIc"><InputNumber className="full-width" min={0.03} max={1} step={0.01} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低验证 |RankIC|" name="minValidRankIc"><InputNumber className="full-width" min={0.03} max={1} step={0.01} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低验证 |ICIR|" name="minValidIcir"><InputNumber className="full-width" min={0.3} step={0.1} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低训练 |ICIR|" name="minIcir" rules={[{ type: "number", min: 0.5, max: 3 }]}><InputNumber className="full-width" min={0.5} max={3} step={0.1} /></Form.Item></Col>
              </Row>
              <Button
                size="large" block type="primary" htmlType="submit"
                loading={submitting}
                disabled={active || defaultsApi.loading || !!defaultsApi.error || pools.length === 0}
                icon={<PlayCircleOutlined />}
              >
                {active ? "生成中…" : "启动 PPO 因子生成"}
              </Button>
            </Form>
          </Card>
        </Col>
        <Col span={14} className="factor-generation-results">
          <Space direction="vertical" size={16} className="full-width">
            {active && (
              <Card
                title={<Space><LoadingOutlined spin />PPO 因子生成中</Space>}
                className="data-card"
                extra={<Button size="small" onClick={resetRun}>收起</Button>}
              >
                <Progress
                  percent={percent}
                  status="active"
                  format={(value) => `${value ?? 0}%`}
                />
                <Flex justify="space-between" gap={12} wrap>
                  <Text strong>{stageLabel}</Text>
                  <Text type="secondary">已运行 {formatElapsed(elapsedMs)}</Text>
                </Flex>
                <Text type="secondary">{job?.message ?? "任务已提交，等待后台子进程启动…"}</Text>
                <Divider />
                <Row gutter={16}>
                  <Col span={8}><Statistic title="已尝试" value={attempts} /></Col>
                  <Col span={8}><Statistic title="可接受因子通过" value={accepted} suffix={targetCount ? `/ ${targetCount}` : undefined} /></Col>
                  <Col span={8}><Statistic title="训练步数" value={timesteps} /></Col>
                </Row>
                <Divider />
                <Steps
                  direction="vertical" size="small" current={currentStep}
                  items={GEN_STEPS.map((step, index) => ({
                    title: step.title,
                    description: index <= currentStep ? step.description : undefined,
                    status: index < currentStep ? "finish" : index === currentStep ? "process" : "wait",
                  }))}
                />
                <Text type="secondary">
                  任务在后台子进程运行，离开本页不会中断；进度写入 outputs/jobs/{jobId}/status.json，本页每 1.5 秒轮询一次。
                </Text>
              </Card>
            )}

            {failed && (
              <Card
                title="因子生成失败"
                className="data-card"
                extra={<Space>
                  <Button size="small" onClick={resetRun}>重置</Button>
                  <Button size="small" type="primary" onClick={() => form.submit()} loading={submitting}>重新提交</Button>
                </Space>}
              >
                <Alert
                  type="error" showIcon
                  message={jobError ?? job?.message ?? "后台任务失败"}
                  description={<Space direction="vertical" size={4}>
                    {jobId && <Text type="secondary">任务 ID：<Text code copyable>{jobId}</Text></Text>}
                    <Text type="secondary">完整堆栈见 outputs/jobs/{jobId}/runner.log 与 status.json。</Text>
                  </Space>}
                />
                {submission?.warnings?.length ? (
                  <Alert type="warning" showIcon className="note-action" message={submission.warnings.join("；")} />
                ) : null}
              </Card>
            )}

            {finished && (
              <Card
                title={<Space><RobotOutlined />生成结果（{resultRows.length} 个因子，区分可接受与合格）</Space>}
                className="data-card"
                extra={<Space>
                  {runId && <Text type="secondary" copyable={{ text: runId, icon: <CopyOutlined /> }}>run_id: {runId}</Text>}
                  <Button size="small" icon={<ReloadOutlined />} onClick={() => { loadedRunRef.current = null; setRunId(null); }}>刷新结果</Button>
                </Space>}
              >
                {submission?.warnings?.length ? (
                  <Alert type="warning" showIcon className="note-action" message={submission.warnings.join("；")} />
                ) : null}
                {runError ? (
                  <Alert type="error" showIcon message="读取因子运行结果失败" description={runError} />
                ) : runLoading ? (
                  <Flex justify="center"><Spin tip="读取可接受因子与确认记录…"><div style={{ width: 240 }} /></Spin></Flex>
                ) : runDetail ? (
                  <>
                    <Row gutter={16} className="note-action">
                      <Col span={6}><Statistic title="可接受因子" value={finishedAccepted} suffix={targetCount ? `/ ${targetCount}` : undefined} /></Col>
                      <Col span={6}><Statistic title="尝试次数" value={finishedAttempts} /></Col>
                      <Col span={6}><Statistic title="股票池" value={String(runDetail.manifest.pool_id ?? selectedPool ?? "—")} /></Col>
                      <Col span={6}><Statistic title="数据源" value={String(runDetail.manifest.data_source ?? submission?.data_source ?? "—")} /></Col>
                    </Row>
                    <Descriptions size="small" column={2} className="note-action" items={[
                      { key: "run", label: "运行名称", children: String(runDetail.manifest.run_name || summary.run_name || "—") },
                      { key: "pool", label: "股票池", children: selectedPoolInfo ? `${selectedPoolInfo.name} · ${selectedPoolInfo.n_stocks} 只` : String(runDetail.manifest.pool_id ?? selectedPool ?? "—") },
                      { key: "fields", label: "字段数", children: String(summaryFields ?? (runDetail.manifest.fields as unknown[] | undefined)?.length ?? "—") },
                      {
                        key: "operators", label: "算子",
                        children: Array.isArray(summaryOperators) && summaryOperators.length
                          ? summaryOperators.join("、")
                          : String(runDetail.manifest.operator_mode === "all" ? "全部 PPO 支持算子" : "—"),
                      },
                      {
                        key: "train", label: "train",
                        children: summarySplits?.train
                          ? `${summarySplits.train.cache_start} ~ ${summarySplits.train.cache_end}`
                          : "—",
                      },
                      {
                        key: "valid", label: "valid / test",
                        children: summarySplits?.valid
                          ? `${summarySplits.valid.cache_start} ~ ${summarySplits.valid.cache_end} / ${summarySplits.test?.cache_start ?? "—"} ~ ${summarySplits.test?.cache_end ?? "—"}`
                          : "—",
                      },
                      { key: "target", label: "目标 / 状态", children: runDetail.manifest.target_reached ? "已达成目标" : runDetail.manifest.attempts_exhausted ? "尝试次数已用完" : "已停止" },
                      { key: "created", label: "完成时间", children: String(runDetail.manifest.created_at ?? runDetail.created_at ?? "—") },
                    ]} />
                    {resultRows.length === 0 ? (
                      <Empty description="本次运行没有可接受因子">
                        <Text type="secondary">
                          {runDetail.manifest.attempts_exhausted
                            ? "尝试次数用完仍未达到质量阈值；可检查字段和切分区间；测试集结果不能用于反复调整门槛、算子或 PPO。"
                            : "没有因子同时满足训练段、验证段的质量阈值；可检查字段组合与切分区间。"}
                        </Text>
                      </Empty>
                    ) : (
                      <Table
                        rowKey="factor_id"
                        size="small"
                        columns={resultColumns}
                        dataSource={resultRows}
                        pagination={{ pageSize: 10, showSizeChanger: false }}
                        scroll={{ x: 1850 }}
                      />
                    )}
                    <Flex justify="space-between" gap={12} wrap className="note-action">
                      <Text type="secondary">
                        PPO 仅使用 train / valid 产生 candidate；生成结束后独立确认任务评估 test 并保存 confirmed，回测不重复评估 test。
                      </Text>
                      <RunConfirmation runId={runDetail.run_id} onComplete={() => { api.factorRun(runDetail.run_id).then(setRunDetail); historyApi.reload(); }} />
                      <Button type="link" onClick={() => navigate("factor_backtest")}>查看合格因子回测</Button>
                    </Flex>
                  </>
                ) : (
                  <Alert type="info" showIcon message="任务已完成，正在等待结果…" />
                )}
              </Card>
            )}

            {!showRunPanel && (
              <>
                <Card size="small" title="PPO 生成流程">
                  <Steps size="small" current={-1} items={GEN_STEPS.map((step) => ({
                    title: step.title, description: step.description,
                  }))} />
                </Card>
                <Card className="data-card">
                  <Empty description="左侧选择真实股票池与字段，启动后会显示后台任务进度和真实生成的因子" />
                </Card>
              </>
            )}

            <Card
              title={<Space><HistoryOutlined />运行历史（MySQL）</Space>}
              className="data-card"
              extra={
                <Space wrap>
                  <Select
                    size="small" value={historyPool} onChange={setHistoryPool}
                    options={[{ value: "all", label: "全部股票池" }, ...historyPoolOptions]}
                    style={{ minWidth: 180 }}
                  />
                  <Select
                    size="small" value={historyDevice} onChange={setHistoryDevice}
                    options={[
                      { value: "all", label: "全部设备" },
                      { value: "cuda", label: "CUDA" },
                      { value: "cpu", label: "CPU" },
                      { value: "unknown", label: "未知" },
                    ]}
                    style={{ minWidth: 100 }}
                  />
                  <Input.Search
                    size="small" allowClear value={historySearch}
                    onChange={(event) => setHistorySearch(event.target.value)}
                    placeholder="搜索 run / 股票池"
                    style={{ width: 200 }}
                  />
                  <Button size="small" icon={<ReloadOutlined />} onClick={historyApi.reload} loading={historyApi.loading}>
                    刷新
                  </Button>
                </Space>
              }
            >
              {historyApi.error ? (
                <Alert
                  type="warning" showIcon
                  message="运行历史加载失败"
                  description={historyApi.error}
                  action={<Button size="small" onClick={historyApi.reload}>重试</Button>}
                />
              ) : (
                <>
                  {historyApi.data?.source === "local" && (
                    <Alert
                      type="warning" showIcon className="note-action"
                      message="MySQL 暂不可用，当前仅显示本地运行记录"
                      description={historyApi.data.mysql_error ?? undefined}
                    />
                  )}
                  <Text type="secondary">
                    共 {historyRuns.length} 次运行
                    {filteredHistoryRuns.length !== historyRuns.length ? `，筛选后 ${filteredHistoryRuns.length} 次` : ""}
                    ；训练时长、运行设备与超参数写入 MySQL，展开行可查看明细。
                  </Text>
                  <div className="factor-history-viewport">
                  <Table
                    rowKey="run_id"
                    size="small"
                    className="note-action"
                    loading={historyApi.loading}
                    columns={historyColumns}
                    dataSource={filteredHistoryRuns}
                    pagination={{ pageSize: 8, showSizeChanger: false }}
                    scroll={{ x: 1250 }}
                    locale={{ emptyText: <Empty description="还没有因子生成记录" /> }}
                    expandable={{
                      expandedRowRender: (run) => (
                        <Space direction="vertical" size={12} className="full-width factor-history-details">
                          <Descriptions
                            size="small" column={3}
                            items={[
                              { key: "run", label: "run_id", children: <Text code copyable>{run.run_id}</Text> },
                              { key: "job", label: "任务 ID", children: run.job_id || "—" },
                              {
                                key: "time", label: "开始 / 结束",
                                children: `${fmtDateTime(run.started_at)} ~ ${fmtDateTime(run.finished_at ?? run.created_at)}`,
                              },
                              { key: "duration", label: "总耗时（含准备）", children: fmtDuration(run.duration_seconds) },
                              { key: "training", label: "训练耗时", children: fmtDuration(run.training_seconds) },
                              { key: "timesteps", label: "训练步数", children: fmtInteger(run.timesteps) },
                              { key: "horizon", label: "持有期 horizon", children: run.target_horizon ?? "—" },
                              {
                                key: "backtrack", label: "回溯 / 未来天数",
                                children: `${run.max_backtrack_days ?? "—"} / ${run.max_future_days ?? "—"}`,
                              },
                              { key: "split", label: "切分交易日", children: splitDaysLabel(run) },
                              { key: "fields", label: "字段数", children: run.fields?.length ?? "—" },
                              {
                                key: "operators", label: "算子数",
                                children: run.operators?.length ?? (run.operator_mode === "all" ? "全部" : "—"),
                              },
                              { key: "stocks", label: "股票数", children: run.n_stocks ?? "—" },
                              {
                                key: "quality", label: "质量阈值", span: 3,
                                children: run.hyperparameters?.quality
                                  ? <Text code>{JSON.stringify(run.hyperparameters.quality)}</Text>
                                  : "—",
                              },
                            ]}
                          />
                          <Divider style={{ margin: "4px 0" }} />
                          <RunFactorPreview runId={run.run_id} />
                        </Space>
                      ),
                    }}
                  />
                  </div>
                </>
              )}
            </Card>
          </Space>
        </Col>
      </Row>

      <Modal title="选择字段" open={fieldPickerOpen} onCancel={() => setFieldPickerOpen(false)} onOk={confirmFields}
        okText={`确定（已选 ${fieldDraft.length}）`} width={760} destroyOnClose>
        <Space direction="vertical" size={12} className="full-width">
          <FilterChips
            items={[{ key: "all", label: "全部", count: fieldOptions.length }, ...fieldCategories.map((category) => ({ key: category, label: category, count: fieldOptions.filter((field) => fieldCategory(field).label === category).length }))]}
            value={fieldCategoryFilter}
            onChange={(value) => {
              setFieldCategoryFilter(value);
              setFieldThemeFilter("all");
              setFieldPeriodFilter("all");
              setFieldUnitFilter("all");
            }}
          />
          <Flex gap={8} wrap align="center">
            <Select
              size="small"
              value={fieldThemeFilter}
              onChange={setFieldThemeFilter}
              style={{ width: 170 }}
              options={[{ value: "all", label: "全部主题" }, ...fieldThemes.map((item) => ({ value: item, label: item }))]}
            />
            <Select
              size="small"
              value={fieldPeriodFilter}
              onChange={setFieldPeriodFilter}
              style={{ width: 120 }}
              options={[{ value: "all", label: "全部口径" }, ...fieldPeriods.map((item) => ({ value: item, label: FIELD_PERIOD_LABELS[item] ?? item }))]}
            />
            <Select
              size="small"
              value={fieldUnitFilter}
              onChange={setFieldUnitFilter}
              style={{ width: 110 }}
              options={[{ value: "all", label: "全部单位" }, ...fieldUnits.map((item) => ({ value: item, label: item }))]}
            />
          </Flex>
          <Flex justify="space-between" gap={12} wrap align="center">
            <Space size={8}><Switch size="small" checked={onlyUsable} onChange={setOnlyUsable} /><Text type="secondary">仅显示可用于因子表达式的字段</Text></Space>
            <Input.Search allowClear value={fieldSearch} onChange={(event) => setFieldSearch(event.target.value)} placeholder="搜索字段名 / 说明" style={{ width: 260 }} />
          </Flex>
          <Flex justify="space-between" gap={12} wrap align="center">
            <Text type="secondary">当前筛选 {visibleFields.length} 个 · 已选 {fieldDraft.length}</Text>
            <Space>
              <Button size="small" onClick={() => setFieldDraft((draft) => [...new Set([...draft, ...visibleFields.filter((field) => field.expression !== false).map((field) => field.value)])])}>全选当前筛选</Button>
              <Button size="small" onClick={() => setFieldDraft([])}>清空</Button>
            </Space>
          </Flex>
          <div style={{ maxHeight: 380, overflow: "auto" }}>
            {fieldsApi.error ? <Alert type="error" showIcon message={fieldsApi.error} /> : fieldsApi.loading ? <Skeleton active paragraph={{ rows: 6 }} /> : (
              <Checkbox.Group value={fieldDraft} onChange={(values) => setFieldDraft(values as string[])} className="full-width">
                <Flex vertical gap={6}>
                  {visibleFields.map((field) => (
                    <Checkbox key={field.value} value={field.value} disabled={field.expression === false}>
                      <Text code>{field.name}</Text>
                      {field.value !== field.name && <Text type="secondary">（面板列 {field.value}）</Text>}
                      <Text type="secondary"> · {field.description}</Text>
                    </Checkbox>
                  ))}
                </Flex>
              </Checkbox.Group>
            )}
          </div>
        </Space>
      </Modal>

      <Modal title="选择操作符（PPO 支持）" open={operatorPickerOpen} onCancel={() => setOperatorPickerOpen(false)} onOk={confirmOperators}
        okText={`确定（已选 ${operatorDraft.length}）`} width={760} destroyOnClose>
        <Space direction="vertical" size={12} className="full-width">
          <FilterChips
            items={[{ key: "all", label: "全部", count: genOperators.length }, ...operatorCategories.map((category) => ({ key: category, label: category, count: genOperators.filter((operator) => operator.category_cn === category).length }))]}
            value={operatorCategory}
            onChange={setOperatorCategory}
          />
          <Flex justify="space-between" gap={12} wrap align="center">
            <Text type="secondary">仅显示 PPO 支持的 {genOperators.length} 个；请主动选择参与生成的操作符</Text>
            <Input.Search allowClear value={operatorSearch} onChange={(event) => setOperatorSearch(event.target.value)} placeholder="搜索操作符 / 说明" style={{ width: 260 }} />
          </Flex>
          <Flex justify="space-between" gap={12} wrap align="center">
            <Text type="secondary">当前筛选 {visibleOperators.length} 个 · 已选 {operatorDraft.length}</Text>
            <Space>
              <Button size="small" onClick={() => setOperatorDraft((draft) => [...new Set([...draft, ...visibleOperators.map((operator) => operator.name)])])}>全选当前筛选</Button>
              <Button size="small" onClick={() => setOperatorDraft([])}>清空</Button>
            </Space>
          </Flex>
          <div style={{ maxHeight: 380, overflow: "auto" }}>
            {operatorsApi.error ? <Alert type="error" showIcon message={operatorsApi.error} /> : operatorsApi.loading ? <Skeleton active paragraph={{ rows: 6 }} /> : (
              <Checkbox.Group value={operatorDraft} onChange={(values) => setOperatorDraft(values as string[])} className="full-width">
                <Flex vertical gap={6}>
                  {visibleOperators.map((operator: OperatorInfo) => (
                    <Checkbox key={operator.name} value={operator.name}>
                      <Text code>{operator.name}</Text>
                      <Tag style={{ marginLeft: 8 }}>{operator.category_cn}</Tag>
                      <Tag color="green">PPO 支持</Tag>
                      <Text type="secondary">{operator.description_cn}</Text>
                    </Checkbox>
                  ))}
                </Flex>
              </Checkbox.Group>
            )}
          </div>
        </Space>
      </Modal>
    </>
  );
}
