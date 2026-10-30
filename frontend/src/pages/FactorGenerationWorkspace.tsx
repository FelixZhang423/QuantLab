import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Flex,
  Form,
  Input,
  InputNumber,
  message,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { api, useApiData, type FieldInfo, type OperatorInfo } from "../api/client";
import { FactorCategoryChips } from "../components/FactorCategoryChips";
import { ValidityReport } from "../components/ValidityReport";
import {
  buildOperatorCategoryMap,
  CATEGORY_META,
  countFactorCategories,
  emptyCategoryCount,
  formatFraction,
  formatNumber,
  OPERATOR_FAMILY_LABELS,
  type FactorCategoryKey,
} from "../factorInsights";
import {
  buildPrototypeRun,
  DEFAULT_PROTOTYPE_FIELDS,
  DEFAULT_PROTOTYPE_OPERATORS,
  loadPrototypeRun,
  PROTOTYPE_ALGORITHMS,
  prototypeAlgorithmLabel,
  savePrototypeRun,
  type PrototypeAlgorithmKey,
  type PrototypeFactor,
  type PrototypeFactorRun,
  type PrototypeGenerationConfig,
} from "../factorPrototype";
import { validityColor } from "../factorValidity";
import { PROTOTYPE_GENERATION_FIELDS } from "../prototypeFields";
import type { PageNav } from "./DataPages";

const { Text } = Typography;

/** 接口不可用时的完整字段选择：行情 + 财务衍生（原型），并补一个面板别名 volume */
const PROTOTYPE_FIELDS_FOR_GENERATION: FieldInfo[] = [
  ...PROTOTYPE_GENERATION_FIELDS,
  {
    name: "volume",
    dtype: "Float64",
    source: "dws.ll_stock_daily_sharing",
    description: "成交量（vol 的面板别名）",
    panel: true,
  },
];

const FALLBACK_OPERATORS: OperatorInfo[] = [
  { name: "ts_mean", category: "time_series", category_cn: "时间序列", canonical_name: "ts_mean", description_cn: "滚动均值", example: "ts_mean(close,20)", generation_enabled: true, manual_enabled: true },
  { name: "ts_std", category: "time_series", category_cn: "时间序列", canonical_name: "ts_std", description_cn: "滚动标准差", example: "ts_std(close,20)", generation_enabled: true, manual_enabled: true },
  { name: "delta", category: "time_series", category_cn: "时间序列", canonical_name: "delta", description_cn: "差分", example: "delta(close,5)", generation_enabled: true, manual_enabled: true },
  { name: "ts_corr", category: "time_series", category_cn: "时间序列", canonical_name: "ts_corr", description_cn: "滚动相关系数", example: "ts_corr(close,volume,20)", generation_enabled: true, manual_enabled: true },
  { name: "delay", category: "time_series", category_cn: "时间序列", canonical_name: "delay", description_cn: "延迟", example: "delay(close,20)", generation_enabled: true, manual_enabled: true },
  { name: "ts_rank", category: "time_series", category_cn: "时间序列", canonical_name: "ts_rank", description_cn: "滚动排名", example: "ts_rank(close,60)", generation_enabled: true, manual_enabled: true },
  { name: "rank", category: "cross_section", category_cn: "横截面", canonical_name: "rank", description_cn: "横截面排名", example: "rank(close)", generation_enabled: true, manual_enabled: true },
  { name: "zscore", category: "cross_section", category_cn: "横截面", canonical_name: "zscore", description_cn: "横截面标准化", example: "zscore(close)", generation_enabled: true, manual_enabled: true },
  { name: "scale", category: "cross_section", category_cn: "横截面", canonical_name: "scale", description_cn: "缩放", example: "scale(close)", generation_enabled: true, manual_enabled: true },
  { name: "div", category: "arithmetic", category_cn: "数学运算", canonical_name: "div", description_cn: "除法", example: "div(close,open)", generation_enabled: true, manual_enabled: true },
  { name: "sub", category: "arithmetic", category_cn: "数学运算", canonical_name: "sub", description_cn: "减法", example: "sub(close,open)", generation_enabled: true, manual_enabled: true },
  { name: "if_else", category: "logic", category_cn: "逻辑判断", canonical_name: "if_else", description_cn: "条件选择", example: "if_else(greater(close,open),close,0)", generation_enabled: true, manual_enabled: true },
  { name: "greater", category: "logic", category_cn: "逻辑判断", canonical_name: "greater", description_cn: "大于比较", example: "greater(close,open)", generation_enabled: true, manual_enabled: true },
];

type StatusFilter = "all" | "qualified" | "rejected";

export function FactorGenerationWorkspace({ navigate }: { navigate: PageNav }) {
  const fieldsApi = useApiData(api.fields);
  const operatorsApi = useApiData(api.operators);
  const poolsApi = useApiData(api.pools);

  const fields = fieldsApi.data?.fields ?? [];
  const operators = operatorsApi.data?.operators ?? [];
  const pools = poolsApi.data?.pools ?? [];

  const usableFields = fields.filter((field) => field.panel !== false);
  const apiFields = usableFields.length > 0 ? usableFields : PROTOTYPE_FIELDS_FOR_GENERATION;
  const apiOperators = operators.filter((operator) => operator.generation_enabled);
  const operatorOptions = apiOperators.length > 0
    ? apiOperators
    : (operators.length > 0 ? operators : FALLBACK_OPERATORS);
  const operatorMap = buildOperatorCategoryMap(operators.length > 0 ? operators : FALLBACK_OPERATORS);

  const [poolId, setPoolId] = useState("liquid_300_43a25f67");
  const [algorithm, setAlgorithm] = useState<PrototypeAlgorithmKey>("ppo");
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([dayjs("2021-06-18"), dayjs("2026-06-16")]);
  const [targetCount, setTargetCount] = useState(9);
  const [threshold, setThreshold] = useState(60);
  const [selectedFields, setSelectedFields] = useState<string[]>(DEFAULT_PROTOTYPE_FIELDS);
  const [selectedOperators, setSelectedOperators] = useState<string[]>(DEFAULT_PROTOTYPE_OPERATORS);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [run, setRun] = useState<PrototypeFactorRun | null>(() => loadPrototypeRun());
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<FactorCategoryKey | "all">("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [validityFactor, setValidityFactor] = useState<PrototypeFactor | null>(null);

  const generationTimerRef = useRef<number | null>(null);
  const generationTimeoutRef = useRef<number | null>(null);
  const poolInitRef = useRef(false);

  useEffect(() => {
    if (poolInitRef.current || pools.length === 0) return;
    poolInitRef.current = true;
    if (!pools.some((pool) => pool.pool_id === poolId)) setPoolId(pools[0].pool_id);
  }, [pools, poolId]);

  useEffect(() => () => {
    if (generationTimerRef.current != null) window.clearInterval(generationTimerRef.current);
    if (generationTimeoutRef.current != null) window.clearTimeout(generationTimeoutRef.current);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [categoryFilter, statusFilter, search, pageSize]);

  const poolOptions = pools.length > 0
    ? pools.map((pool) => ({
      value: pool.pool_id,
      label: `${pool.name || pool.pool_id} · ${pool.n_stocks} 只`,
    }))
    : [{ value: "liquid_300_43a25f67", label: "liquid_300_43a25f67 · 示例池" }];
  if (!poolOptions.some((option) => option.value === poolId)) {
    poolOptions.push({ value: poolId, label: `${poolId} · 当前选择` });
  }

  const fieldGroups = (() => {
    const groups = new Map<string, { label: string; options: { value: string; label: string }[] }>();
    for (const field of apiFields) {
      const groupKey = field.source || "其他";
      if (!groups.has(groupKey)) groups.set(groupKey, { label: groupKey, options: [] });
      groups.get(groupKey)?.options.push({
        value: field.name,
        label: `${field.name}${field.description ? ` · ${field.description}` : ""}`,
      });
    }
    return [...groups.values()];
  })();

  const operatorGroups = (() => {
    const groups = new Map<string, { label: string; options: { value: string; label: string; disabled?: boolean }[] }>();
    for (const operator of operatorOptions) {
      const groupKey = operator.category_cn || "其他";
      if (!groups.has(groupKey)) groups.set(groupKey, { label: groupKey, options: [] });
      groups.get(groupKey)?.options.push({
        value: operator.name,
        label: `${operator.name}${operator.description_cn ? ` · ${operator.description_cn}` : ""}`,
        disabled: !operator.generation_enabled,
      });
    }
    return [...groups.values()];
  })();

  const algorithmMeta = PROTOTYPE_ALGORITHMS.find((item) => item.key === algorithm);
  const counts = run ? countFactorCategories(run.factors) : emptyCategoryCount();
  const qualifiedFactors = run?.factors.filter((factor) => factor.qualified) ?? [];
  const categoryCount = run ? new Set(run.factors.map((factor) => factor.category)).size : 0;
  const averageScore = run && run.factors.length > 0
    ? Math.round(run.factors.reduce((sum, factor) => sum + factor.score, 0) / run.factors.length)
    : null;
  const searchValue = search.trim().toLowerCase();
  const filteredFactors = (run?.factors ?? []).filter((factor) => {
    if (statusFilter === "qualified" && !factor.qualified) return false;
    if (statusFilter === "rejected" && factor.qualified) return false;
    if (categoryFilter !== "all" && factor.category !== categoryFilter) return false;
    if (searchValue) {
      const haystack = `${factor.expression} ${CATEGORY_META[factor.category].label} ${factor.tags.join(" ")}`.toLowerCase();
      if (!haystack.includes(searchValue)) return false;
    }
    return true;
  });

  const fallbackNotes = [
    fieldsApi.error ? "字段目录接口不可用，当前使用内置原型字段目录（含财务衍生字段）。" : null,
    operatorsApi.error ? "操作符接口不可用，当前使用内置示例算子。" : null,
    poolsApi.error ? "股票池列表接口不可用，当前使用示例股票池。" : null,
  ].filter((note): note is string => Boolean(note));

  const fieldNames = new Set(apiFields.map((field) => field.name.toLowerCase()));
  const operatorNames = new Set(operatorOptions.map((operator) => operator.name.toLowerCase()));
  const pickOperators = (names: string[]) => names.filter((name) => operatorNames.has(name));
  const setFieldPreset = (names: string[]) => {
    const picked = names.filter((name) => fieldNames.has(name.toLowerCase()));
    setSelectedFields(picked.length > 0 ? picked : apiFields.slice(0, 4).map((field) => field.name));
  };

  const startGeneration = () => {
    if (generating) return;
    const fieldsForRun = selectedFields
      .map((name) => apiFields.find((field) => field.name.toLowerCase() === name.toLowerCase())?.name)
      .filter((name): name is string => Boolean(name));
    const operatorsForRun = selectedOperators
      .map((name) => operatorOptions.find((operator) => operator.name.toLowerCase() === name.toLowerCase())?.name)
      .filter((name): name is string => Boolean(name));
    if (fieldsForRun.length === 0) {
      message.warning("请至少选择一个可用的数据字段");
      return;
    }
    if (operatorsForRun.length === 0) {
      message.warning("请至少选择一个可用的操作符");
      return;
    }

    const config: PrototypeGenerationConfig = {
      pool_id: poolId,
      algorithm,
      fields: fieldsForRun,
      operators: operatorsForRun,
      start_date: dateRange[0].format("YYYY-MM-DD"),
      end_date: dateRange[1].format("YYYY-MM-DD"),
      target_count: Math.max(1, Math.min(30, Math.round(targetCount || 9))),
      score_threshold: Math.max(40, Math.min(90, Math.round(threshold || 60))),
    };

    if (generationTimerRef.current != null) window.clearInterval(generationTimerRef.current);
    if (generationTimeoutRef.current != null) window.clearTimeout(generationTimeoutRef.current);
    setGenerating(true);
    setProgress(4);
    setRun(null);
    const startedAt = Date.now();
    generationTimerRef.current = window.setInterval(() => {
      const next = Math.min(94, Math.round(((Date.now() - startedAt) / 2200) * 100));
      setProgress(next);
      if (next < 94) return;
      if (generationTimerRef.current != null) {
        window.clearInterval(generationTimerRef.current);
        generationTimerRef.current = null;
      }
      generationTimeoutRef.current = window.setTimeout(() => {
        try {
          const generated = buildPrototypeRun(config, operatorMap);
          setRun(generated);
          savePrototypeRun(generated);
          setStatusFilter("all");
          setCategoryFilter("all");
          setSearch("");
          setPage(1);
          const qualified = generated.factors.filter((factor) => factor.qualified).length;
          message.success(`生成完成：${generated.factors.length} 个候选，${qualified} 个合格`);
        } catch {
          message.error("原型生成失败，请调整参数后重试");
        } finally {
          setGenerating(false);
          setProgress(100);
          generationTimeoutRef.current = null;
        }
      }, 360);
    }, 120);
  };

  const goBacktest = () => {
    if (!run) return;
    if (qualifiedFactors.length === 0) {
      message.warning("本次生成没有合格因子，无法带入回测");
      return;
    }
    savePrototypeRun(run);
    navigate("factor_backtest", undefined, undefined, { runId: run.run_id, prototype: true });
  };

  const columns: TableColumnsType<PrototypeFactor> = [
    {
      title: "因子表达式",
      dataIndex: "expression",
      width: 300,
      ellipsis: true,
      render: (value: string) => (
        <Tooltip title={value}>
          <Text code>{value}</Text>
        </Tooltip>
      ),
    },
    {
      title: "大模型类别",
      dataIndex: "category",
      width: 190,
      render: (_, factor) => (
        <Tooltip title={factor.category_reason}>
          <Space size={4} wrap>
            <Tag color={CATEGORY_META[factor.category].color}>{CATEGORY_META[factor.category].label}</Tag>
            <Text type="secondary" className="prototype-llm-confidence">LLM {factor.llm_confidence}%</Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: "算子族",
      dataIndex: "operator_family",
      width: 110,
      render: (value: PrototypeFactor["operator_family"]) => (
        <Tag color="geekblue">{OPERATOR_FAMILY_LABELS[value]}</Tag>
      ),
    },
    {
      title: "有效性 Score",
      dataIndex: "score",
      width: 150,
      sorter: (a, b) => a.score - b.score,
      render: (_, factor) => (
        <Flex align="center" gap={8} className="prototype-score-cell">
          <Progress
            percent={factor.score}
            showInfo={false}
            size="small"
            strokeColor={validityColor(factor.validity.grade)}
            trailColor="#edf0f4"
          />
          <Text strong>{factor.score}</Text>
        </Flex>
      ),
    },
    {
      title: "状态",
      dataIndex: "qualified",
      width: 96,
      render: (qualified: boolean) => (
        qualified
          ? <Tag color="success" icon={<CheckCircleOutlined />}>合格</Tag>
          : <Tag color="error" icon={<CloseCircleOutlined />}>淘汰</Tag>
      ),
    },
    { title: "IC", dataIndex: "ic", width: 90, align: "right", render: (value: number) => formatNumber(value, 4) },
    { title: "RankIC", dataIndex: "rank_ic", width: 90, align: "right", render: (value: number) => formatNumber(value, 4) },
    { title: "ICIR", dataIndex: "icir", width: 80, align: "right", render: (value: number) => formatNumber(value, 2) },
    { title: "覆盖率", dataIndex: "coverage", width: 90, align: "right", render: (value: number) => formatFraction(value, 1) },
    {
      title: "操作",
      key: "actions",
      width: 170,
      render: (_, factor) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setValidityFactor(factor)}>8 维评价</Button>
          {factor.qualified && (
            <Button type="link" size="small" onClick={goBacktest}>带入回测</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card
        title={<Space><ThunderboltOutlined />生成配置<Tag color="purple">前端原型</Tag></Space>}
        extra={<Text type="secondary">生成过程在浏览器内模拟，不写入 factor_runs</Text>}
        className="generation-config-card"
      >
        <Form layout="vertical">
          <Row gutter={12}>
            <Col xs={24} md={12} xl={6}>
              <Form.Item label="股票池">
                <Select
                  value={poolId}
                  onChange={setPoolId}
                  options={poolOptions}
                  showSearch
                  optionFilterProp="label"
                  loading={poolsApi.loading}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item label="生成算法">
                <Select
                  value={algorithm}
                  onChange={(value: PrototypeAlgorithmKey) => setAlgorithm(value)}
                  options={PROTOTYPE_ALGORITHMS.map((item) => ({ value: item.key, label: item.label }))}
                />
                <Text type="secondary" className="generation-algorithm-hint">{algorithmMeta?.description}</Text>
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item label="生成 / 训练区间">
                <DatePicker.RangePicker
                  value={dateRange}
                  allowClear={false}
                  style={{ width: "100%" }}
                  onChange={(values) => {
                    if (values?.[0] && values[1]) setDateRange([values[0], values[1]]);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6} xl={3}>
              <Form.Item label="目标因子数">
                <InputNumber
                  className="full-width"
                  min={1}
                  max={30}
                  value={targetCount}
                  onChange={(value) => setTargetCount(value ?? 9)}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6} xl={3}>
              <Form.Item label="合格 Score 阈值">
                <InputNumber
                  className="full-width"
                  min={40}
                  max={90}
                  value={threshold}
                  onChange={(value) => setThreshold(value ?? 60)}
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={12}>
            <Col xs={24} xl={12}>
              <Form.Item label={`数据字段（已选 ${selectedFields.length} / 可用 ${apiFields.length}）`}>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  maxTagCount="responsive"
                  value={selectedFields}
                  onChange={setSelectedFields}
                  options={fieldGroups}
                  placeholder={fieldsApi.loading ? "字段目录加载中…" : "搜索并选择数据字段"}
                  listHeight={320}
                />
              </Form.Item>
              <Space size={6} wrap className="generation-preset-row">
                <Button size="small" onClick={() => setSelectedFields(apiFields.map((field) => field.name))}>全部面板字段</Button>
                <Button size="small" onClick={() => setFieldPreset(DEFAULT_PROTOTYPE_FIELDS)}>量价常用</Button>
                <Button size="small" onClick={() => setSelectedFields([])}>清空</Button>
              </Space>
            </Col>
            <Col xs={24} xl={12}>
              <Form.Item label={`操作符（已选 ${selectedOperators.length} / 可用 ${operatorOptions.length}）`}>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  maxTagCount="responsive"
                  value={selectedOperators}
                  onChange={setSelectedOperators}
                  options={operatorGroups}
                  placeholder={operatorsApi.loading ? "操作符加载中…" : "搜索并选择操作符"}
                  listHeight={320}
                />
              </Form.Item>
              <Space size={6} wrap className="generation-preset-row">
                <Button size="small" onClick={() => setSelectedOperators(pickOperators(["ts_mean", "ts_std", "delta", "ts_corr", "ts_rank", "delay"]))}>时序常用</Button>
                <Button size="small" onClick={() => setSelectedOperators(pickOperators(["rank", "zscore", "scale", "group_rank"]))}>横截面</Button>
                <Button size="small" onClick={() => setSelectedOperators(operatorOptions.filter((operator) => operator.generation_enabled).map((operator) => operator.name))}>全选可生成</Button>
                <Button size="small" onClick={() => setSelectedOperators([])}>清空</Button>
              </Space>
            </Col>
          </Row>
        </Form>

        {fallbackNotes.length > 0 && (
          <Alert
            type="warning"
            showIcon
            className="generation-fallback-alert"
            message="部分接口不可用，已启用内置示例数据"
            description={fallbackNotes.join(" ")}
          />
        )}

        <Flex justify="space-between" align="center" gap={12} wrap className="generation-actions">
          <Text type="secondary">
            选择算法、字段与操作符后开始；生成完成后由大模型判定因子类别，并计算 8 项有效性 Score。
          </Text>
          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            loading={generating}
            disabled={generating || apiFields.length === 0 || operatorOptions.length === 0}
            onClick={startGeneration}
          >
            开始生成
          </Button>
        </Flex>

        {generating && (
          <div className="generation-progress">
            <Progress percent={progress} status="active" strokeColor="#722ed1" />
            <Text type="secondary">正在搜索表达式并评估有效性… {progress}%</Text>
          </div>
        )}
      </Card>

      {!run && !generating && (
        <Alert
          type="info"
          showIcon
          message="尚无生成结果"
          description="配置参数后点击「开始生成」。原型会模拟生成进度，并在完成后展示大模型类别、有效性 Score 与 8 项因子有效性评价。"
        />
      )}

      {run && (
        <>
          <Row gutter={16}>
            <Col xs={12} md={6}><Card className="metric-card metric-blue"><Statistic title="候选因子" value={run.factors.length} suffix="个" /></Card></Col>
            <Col xs={12} md={6}><Card className="metric-card metric-violet"><Statistic title="合格因子" value={qualifiedFactors.length} suffix="个" /></Card></Col>
            <Col xs={12} md={6}><Card className="metric-card metric-cyan"><Statistic title="大模型类别" value={categoryCount} suffix="类" /></Card></Col>
            <Col xs={12} md={6}><Card className="metric-card metric-orange"><Statistic title="平均 Score" value={averageScore ?? "—"} suffix={averageScore == null ? undefined : "分"} /></Card></Col>
          </Row>

          <Alert
            type={qualifiedFactors.length > 0 ? "success" : "warning"}
            showIcon
            message={`生成完成：${run.factors.length} 个候选，${qualifiedFactors.length} 个合格`}
            description={`${run.run_id} · ${prototypeAlgorithmLabel(run.config.algorithm)} · 合格线 ${run.config.score_threshold} 分 · 生成区间 ${run.config.start_date} ~ ${run.config.end_date}`}
            action={(
              <Button
                type="primary"
                icon={<ExperimentOutlined />}
                onClick={goBacktest}
                disabled={qualifiedFactors.length === 0}
              >
                回测全部合格因子
              </Button>
            )}
          />

          <Card
            className="data-card prototype-result-card"
            title={<Space><ExperimentOutlined />生成结果<Tag color="purple">大模型判定 + 8 项有效性</Tag></Space>}
            extra={<Text type="secondary">当前筛选 {filteredFactors.length} / {run.factors.length}</Text>}
          >
            <Flex justify="space-between" align="center" gap={12} wrap className="factor-toolbar">
              <FactorCategoryChips
                counts={counts}
                value={categoryFilter}
                onChange={(value) => setCategoryFilter(value)}
              />
              <Space size={8} wrap>
                <Segmented
                  value={statusFilter}
                  onChange={(value) => setStatusFilter(value as StatusFilter)}
                  options={[
                    { label: `全部 ${run.factors.length}`, value: "all" },
                    { label: `合格 ${qualifiedFactors.length}`, value: "qualified" },
                    { label: `淘汰 ${run.factors.length - qualifiedFactors.length}`, value: "rejected" },
                  ]}
                />
                <Input
                  allowClear
                  prefix={<SearchOutlined />}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索表达式 / 类别"
                  style={{ width: 220 }}
                />
              </Space>
            </Flex>
            <Table
              rowKey="factor_id"
              size="middle"
              columns={columns}
              dataSource={filteredFactors}
              scroll={{ x: 1280 }}
              rowClassName={(factor) => (factor.qualified ? "" : "prototype-factor-rejected")}
              pagination={{
                current: page,
                pageSize,
                total: filteredFactors.length,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 30],
                showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条 / 共 ${total} 条`,
                onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
              }}
            />
            <Text type="secondary" className="factor-table-hint">
              类别由前端按表达式字段与算子模拟大模型判定；Score 为 8 项有效性评价的综合分，达到阈值即视为合格。
            </Text>
          </Card>
        </>
      )}

      <Drawer
        open={validityFactor != null}
        onClose={() => setValidityFactor(null)}
        width={860}
        title={(
          <Space>
            <RobotOutlined />
            {validityFactor ? `${validityFactor.factor_id} · 因子有效性评价` : "因子有效性评价"}
            <Tag color="purple">原型</Tag>
          </Space>
        )}
      >
        {validityFactor && (
          <Space direction="vertical" size={16} className="full-width">
            <Card size="small">
              <Space direction="vertical" size={8} className="full-width">
                <Text code>{validityFactor.expression}</Text>
                <Space size={6} wrap>
                  <Tag color={CATEGORY_META[validityFactor.category].color}>
                    {CATEGORY_META[validityFactor.category].label}类
                  </Tag>
                  <Tag color="purple">大模型置信度 {validityFactor.llm_confidence}%</Tag>
                  <Tag
                    color={validityFactor.qualified ? "success" : "error"}
                    icon={validityFactor.qualified ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                  >
                    {validityFactor.qualified ? "合格" : "淘汰"}
                  </Tag>
                </Space>
                <Text type="secondary">{validityFactor.category_reason}</Text>
              </Space>
            </Card>
            <ValidityReport report={validityFactor.validity} bare prototype />
          </Space>
        )}
      </Drawer>
    </Space>
  );
}
