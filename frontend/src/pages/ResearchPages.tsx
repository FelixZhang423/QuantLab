import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Collapse, DatePicker, Descriptions, Divider, Drawer, Flex, Form, Input, InputNumber, message, Popconfirm, Progress, Row, Select, Skeleton, Space, Spin, Statistic, Steps, Switch, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType, TableProps } from "antd";
import { CloudDownloadOutlined, CopyOutlined, DeleteOutlined, ExperimentOutlined, FilterOutlined, PlusOutlined, PlayCircleOutlined, ReloadOutlined, RobotOutlined, TeamOutlined } from "@ant-design/icons";
const { Text } = Typography;
import dayjs from "dayjs";
import { nowStamp } from "../mockData";
import { acceptedFactors, fieldsData, generationSummary, type FactorItem } from "../mockExtended";
import { LoadGate, type PageNav, type TaskAdder } from "./DataPages";
import {
  api, ApiError, factorBacktestFileUrl, useApiData, useJobPolling,
  type AcceptedFactor, type FactorBacktestBatch, type FactorBacktestRequest, type FactorBacktestRow,
  type PoolCreateRequest, type PoolInfo, type PoolProvenance, type UniverseQuery, type UniverseStock, type UniverseStocks,
} from "../api/client";

/* ============ 股票池 ============ */

const PREVIEW_PAGE_SIZE = 50;

const EXCHANGE_LABELS: Record<string, string> = { SH: "沪市", SZ: "深市", BJ: "北交所", OTHER: "其他" };

type DateRangeValue = { format: (template: string) => string }[];

type PoolFormValues = {
  name: string;
  selection?: DateRangeValue;
  industries?: string[];
  exchanges?: string[];
  boards?: string[];
  sectors?: string[];
  listedStates?: string[];
  q?: string;
  topN?: number | null;
  minListedDays?: number;
  minCoverage?: number;
  excludeSuspended?: boolean;
  overwrite?: boolean;
};

type PreviewFilters = {
  industries: string[];
  exchanges: string[];
  boards: string[];
  sectors: string[];
  listed_states: string[];
  q: string;
  min_listed_days: number;
  as_of: string;
};

function formatAmount(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 1e8) return `¥${(value / 1e8).toFixed(2)} 亿`;
  if (Math.abs(value) >= 1e4) return `¥${(value / 1e4).toFixed(2)} 万`;
  return `¥${value.toFixed(2)}`;
}

function describeFilters(filters?: Record<string, unknown>): string {
  if (!filters) return "—";
  const asList = (value: unknown): string =>
    Array.isArray(value) ? value.map((item) => String(item)).join("、") : typeof value === "string" ? value : "";
  const parts: string[] = [];
  const industries = asList(filters.industries);
  if (industries) parts.push(`行业 ${industries}`);
  const exchanges = Array.isArray(filters.exchanges)
    ? filters.exchanges.map((value) => EXCHANGE_LABELS[String(value)] ?? String(value)).join("、")
    : "";
  if (exchanges) parts.push(`市场 ${exchanges}`);
  const boards = asList(filters.boards);
  if (boards) parts.push(`板块 ${boards}`);
  const sectors = asList(filters.sectors);
  if (sectors) parts.push(`库内板块 ${sectors}`);
  const states = asList(filters.listed_states);
  if (states) parts.push(`库内上市状态 ${states}`);
  if (typeof filters.q === "string" && filters.q) parts.push(`关键词 ${filters.q}`);
  if (typeof filters.min_listed_days === "number" && filters.min_listed_days > 0) {
    parts.push(`上市 ≥ ${filters.min_listed_days} 天`);
  }
  return parts.length > 0 ? parts.join("；") : "全市场（无筛选）";
}

export function PoolsPage({ addTask, navigate }: { addTask: TaskAdder; navigate: PageNav }) {
  const [form] = Form.useForm<PoolFormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [openPool, setOpenPool] = useState<PoolInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<UniverseStocks | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  // 预览表格勾选：allCodes 是当前筛选下的全部代码（跨页全选/反选用），
  // selectedCodes 是用户当前勾选的代码；筛选条件变化后重置为全选。
  const [allCodes, setAllCodes] = useState<string[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [codesLoading, setCodesLoading] = useState(false);
  const [codesError, setCodesError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const poolsApi = useApiData(api.pools);
  const optionsApi = useApiData(api.universeOptions);
  const poolDetail = useApiData(() => (openPool ? api.pool(openPool.pool_id) : Promise.resolve(null)), [openPool?.pool_id]);
  const { job, error: jobError, polling } = useJobPolling(jobId);

  const watchIndustries = Form.useWatch("industries", form) as string[] | undefined;
  const watchExchanges = Form.useWatch("exchanges", form) as string[] | undefined;
  const watchBoards = Form.useWatch("boards", form) as string[] | undefined;
  const watchSectors = Form.useWatch("sectors", form) as string[] | undefined;
  const watchListedStates = Form.useWatch("listedStates", form) as string[] | undefined;
  const watchQ = Form.useWatch("q", form) as string | undefined;
  const watchMinListedDays = Form.useWatch("minListedDays", form) as number | undefined;
  const watchSelection = Form.useWatch("selection", form) as DateRangeValue | undefined;

  const filters = useMemo<PreviewFilters>(() => ({
    industries: watchIndustries ?? [],
    exchanges: watchExchanges ?? [],
    boards: watchBoards ?? [],
    sectors: watchSectors ?? [],
    listed_states: watchListedStates ?? [],
    q: (watchQ ?? "").trim(),
    min_listed_days: watchMinListedDays ?? 0,
    as_of: watchSelection?.[1]?.format("YYYY-MM-DD") ?? "",
  }), [watchIndustries, watchExchanges, watchBoards, watchSectors, watchListedStates, watchQ, watchMinListedDays, watchSelection]);

  // 筛选条件变化后 300ms 才真正查询，避免多选/打字时连续打库
  const [debounced, setDebounced] = useState<PreviewFilters>(filters);
  useEffect(() => {
    setPage(1);
    const timer = setTimeout(() => setDebounced(filters), 300);
    return () => clearTimeout(timer);
  }, [filters]);
  // 表单值已变、预览/勾选还没跟上时，禁止提交，避免把旧勾选套到新筛选上
  const filtersPending = JSON.stringify(filters) !== JSON.stringify(debounced);

  useEffect(() => {
    let alive = true;
    setPreviewLoading(true);
    setPreviewError(null);
    const query: UniverseQuery = {
      industries: debounced.industries,
      exchanges: debounced.exchanges,
      boards: debounced.boards,
      sectors: debounced.sectors,
      listed_states: debounced.listed_states,
      q: debounced.q,
      min_listed_days: debounced.min_listed_days,
      as_of: debounced.as_of || undefined,
      limit: PREVIEW_PAGE_SIZE,
      offset: (page - 1) * PREVIEW_PAGE_SIZE,
    };
    api.universeStocks(query)
      .then((data) => {
        if (!alive) return;
        setPreview(data);
        setPreviewLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setPreview(null);
        setPreviewError(err instanceof Error ? err.message : String(err));
        setPreviewLoading(false);
      });
    return () => { alive = false; };
  }, [debounced, page, previewTick]);

  // 当前筛选下的全部代码：用于跨页全选/反选。筛选变化后默认全选。
  useEffect(() => {
    let alive = true;
    setCodesLoading(true);
    setCodesError(null);
    setAllCodes([]);
    setSelectedCodes([]);
    api.universeCodes({
      industries: debounced.industries,
      exchanges: debounced.exchanges,
      boards: debounced.boards,
      sectors: debounced.sectors,
      listed_states: debounced.listed_states,
      q: debounced.q,
      min_listed_days: debounced.min_listed_days,
      as_of: debounced.as_of || undefined,
    })
      .then((data) => {
        if (!alive) return;
        setAllCodes(data.codes);
        setSelectedCodes(data.codes);
        setCodesLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setAllCodes([]);
        setSelectedCodes([]);
        setCodesError(err instanceof Error ? err.message : String(err));
        setCodesLoading(false);
      });
    return () => { alive = false; };
  }, [debounced]);

  const codeSet = useMemo(() => new Set(allCodes), [allCodes]);
  const selectedList = useMemo(
    () => selectedCodes.filter((code) => codeSet.has(code)),
    [selectedCodes, codeSet],
  );
  const selectedSet = useMemo(() => new Set(selectedList), [selectedList]);
  const pageSelectable = preview?.items ?? [];
  const pageSelectedCount = pageSelectable.filter((item) => selectedSet.has(item.code)).length;
  const pagePartial = pageSelectedCount > 0 && pageSelectedCount < pageSelectable.length;

  const selectAll = () => setSelectedCodes(allCodes);
  const invertSelection = () => {
    const current = new Set(selectedList);
    setSelectedCodes(allCodes.filter((code) => !current.has(code)));
  };
  const clearSelection = () => setSelectedCodes([]);

  // 以已建池为模板：回填筛选条件/窗口/参数，改名后创建新池（pool_id 会按新参数重算）
  const applyPoolTemplate = () => {
    if (!openPool) return;
    const filters = (openPool.provenance?.filters ?? {}) as Record<string, unknown>;
    const list = (value: unknown): string[] =>
      Array.isArray(value) ? value.map((item) => String(item)) : [];
    const name = `${openPool.name}_copy`.slice(0, 64);
    form.setFieldsValue({
      name,
      selection: openPool.selection_start && openPool.selection_end
        ? [dayjs(openPool.selection_start), dayjs(openPool.selection_end)]
        : undefined,
      industries: list(filters.industries),
      exchanges: list(filters.exchanges),
      boards: list(filters.boards),
      sectors: list(filters.sectors),
      listedStates: list(filters.listed_states),
      q: typeof filters.q === "string" ? filters.q : "",
      topN: openPool.top_n ?? undefined,
      minListedDays: openPool.min_listed_days,
      minCoverage: openPool.min_coverage,
      excludeSuspended: openPool.exclude_suspended,
      overwrite: false,
    });
    setOpenPool(null);
    setPage(1);
    message.info(
      openPool.provenance
        ? "已按该池的筛选条件回填左侧表单，修改名称后即可创建新池"
        : "该池没有筛选来源信息，已回填名称、窗口与参数",
    );
  };

  const deleteOpenPool = async () => {
    if (!openPool) return;
    const current = openPool;
    setDeleting(true);
    try {
      const result = await api.deletePool(current.pool_id);
      const stores = [
        result.deleted_local ? "本地文件" : null,
        result.deleted_mysql ? "MySQL" : null,
      ].filter(Boolean).join(" + ");
      message.success(`已删除股票池 ${current.name}${stores ? `（${stores}）` : ""}`);
      result.warnings.forEach((item) => message.warning(item, 6));
      setOpenPool(null);
      poolsApi.reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  };

  // 任务完成只刷新一次列表，避免轮询 effect 反复触发
  const reloadedJobRef = useRef<string | null>(null);
  useEffect(() => {
    if (jobId && job?.status === "finished" && reloadedJobRef.current !== jobId) {
      reloadedJobRef.current = jobId;
      poolsApi.reload();
    }
  }, [jobId, job?.status, poolsApi.reload]);

  const submit = async (values: PoolFormValues) => {
    const range = values.selection;
    if (!range?.[0] || !range?.[1]) {
      message.error("请选择筛选窗口");
      return;
    }
    if (filtersPending) {
      message.error("筛选条件正在更新，请稍候");
      return;
    }
    if (codesLoading) {
      message.error("正在加载全部候选代码，请稍候");
      return;
    }
    if (selectedList.length === 0) {
      message.error("请至少勾选一只股票（可点击「全选」）");
      return;
    }
    // 全选时省略 selected_codes，后端按“全部匹配候选”处理；
    // 部分勾选时只把勾中的代码交给建池任务。
    const allSelected = selectedList.length === allCodes.length;
    const payload: PoolCreateRequest = {
      name: String(values.name ?? "").trim(),
      selection_start: range[0].format("YYYY-MM-DD"),
      selection_end: range[1].format("YYYY-MM-DD"),
      industries: values.industries ?? [],
      exchanges: values.exchanges ?? [],
      boards: values.boards ?? [],
      sectors: values.sectors ?? [],
      listed_states: values.listedStates ?? [],
      q: (values.q ?? "").trim(),
      min_listed_days: values.minListedDays ?? 0,
      top_n: values.topN ?? null,
      min_coverage: values.minCoverage ?? 0.9,
      exclude_suspended: values.excludeSuspended ?? true,
      overwrite: values.overwrite ?? false,
      selected_codes: allSelected ? undefined : selectedList,
    };
    setSubmitting(true);
    setWarnings([]);
    try {
      const response = await api.createPool(payload);
      setJobId(response.job_id);
      setWarnings(response.warnings);
      message.info(`建池任务已提交：${response.job_id}`);
    } catch (err) {
      const text = err instanceof ApiError && err.status === 503
        ? `${err.message}（公司库筛选不可用，未提交建池任务）`
        : err instanceof Error ? err.message : String(err);
      message.error(text);
    } finally {
      setSubmitting(false);
    }
  };

  const industryOptions = useMemo(
    () => (optionsApi.data?.industries ?? []).map((item) => ({ value: item.value, label: `${item.label}（${item.count}）` })),
    [optionsApi.data],
  );
  const marketOptions = useMemo(
    () => (optionsApi.data?.exchanges ?? []).map((item) => ({ value: item.value, label: item.label })),
    [optionsApi.data],
  );
  const boardOptions = useMemo(
    () => (optionsApi.data?.boards ?? []).map((item) => ({ value: item.value, label: `${item.label}（${item.count}）` })),
    [optionsApi.data],
  );
  const sectorOptions = useMemo(
    () => (optionsApi.data?.sectors ?? []).map((item) => ({ value: item.value, label: `${item.label}（${item.count}）` })),
    [optionsApi.data],
  );
  const listedStateOptions = useMemo(
    () => (optionsApi.data?.listed_states ?? []).map((item) => ({ value: item.value, label: `${item.label}（${item.count}）` })),
    [optionsApi.data],
  );

  const filtersDisabled = !optionsApi.data;
  const createDisabled = filtersDisabled || !!previewError || polling
    || filtersPending || codesLoading || !!codesError || selectedList.length === 0
    || (!!preview && preview.matched_total === 0);

  const previewColumns: TableColumnsType<UniverseStock> = [
    { title: "代码", dataIndex: "code", width: 84, render: (v) => <Text code>{v}</Text> },
    { title: "名称", dataIndex: "name", width: 100, render: (v: string | null) => v || "—" },
    { title: "行业", dataIndex: "industry", width: 100, render: (v: string | null) => v || <Text type="secondary">未分类</Text> },
    { title: "市场", dataIndex: "exchange_label", width: 76 },
    { title: "板块", dataIndex: "board_label", width: 96 },
    { title: "上市日期", dataIndex: "listed_date", width: 108, render: (v: string | null) => v || "—" },
    { title: "最新成交额", dataIndex: "latest_amount", align: "right", width: 116, render: (v: number | null) => formatAmount(v) },
    {
      title: "状态", key: "status", width: 120,
      render: (_, row) => (
        <Space size={4} wrap>
          {row.latest_ifsuspend === 1 && <Tag color="warning">最新停牌</Tag>}
        </Space>
      ),
    },
  ];

  const previewRowSelection: NonNullable<TableProps<UniverseStock>["rowSelection"]> = {
    selectedRowKeys: selectedList,
    // 翻页后保留其他页勾选的代码
    preserveSelectedRowKeys: true,
    onChange: (keys) => setSelectedCodes(keys.map(String)),
  };

  const columns: TableColumnsType<PoolInfo> = [
    { title: "池名称", dataIndex: "name", render: (v) => <Text strong>{v}</Text> },
    { title: "股票数", dataIndex: "n_stocks", align: "right", sorter: (a, b) => a.n_stocks - b.n_stocks, render: (v) => v.toLocaleString("zh-CN") },
    { title: "筛选窗口", key: "window", render: (_, r) => <Text type="secondary">{r.selection_start} ~ {r.selection_end}</Text> },
    { title: "覆盖率", dataIndex: "coverage", align: "right", render: (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`) },
    { title: "来源", key: "source", width: 110, render: (_, r) => (r.data_source === "clickhouse" || r.provenance ? <Tag color="blue">公司库筛选</Tag> : <Tag>旧本地缓存</Tag>) },
    { title: "创建时间", dataIndex: "created_at", width: 140 },
    { title: "状态", dataIndex: "status", width: 84, render: () => <Tag color="success">可用</Tag> },
  ];

  const jobPoolId = job?.result && typeof job.result.pool_id === "string" ? job.result.pool_id : null;
  const jobType = jobError || job?.status === "failed" ? "error" : job?.status === "finished" ? "success" : "info";
  const jobMessage = !job
    ? (jobError ? "建池任务状态查询失败" : "建池任务已提交，等待状态…")
    : job.status === "queued" ? `建池任务排队中（${jobId}）`
      : job.status === "running" ? `正在创建股票池（${jobId}）`
        : job.status === "finished" ? "股票池创建完成"
          : job.status === "failed" ? "股票池创建失败"
            : `任务状态：${job.status}`;

  return (
    <Row gutter={16} className="backtest-layout">
      <Col span={10}>
        <Card title={<Space><PlusOutlined />创建股票池<Tag color="success">公司库实时筛选</Tag></Space>} className="form-card">
          {optionsApi.error && (
            <Alert
              type="error" showIcon style={{ marginBottom: 16 }}
              message="公司数据库不可用，暂时无法筛选候选股票"
              description={<Space direction="vertical" size={2}>
                <Text>{optionsApi.error}</Text>
                <Text type="secondary">需在公司网络环境并配置 QL_CH_PASSWORD；已有股票池仍可查看。</Text>
              </Space>}
              action={<Button size="small" icon={<ReloadOutlined />} onClick={optionsApi.reload}>重试</Button>}
            />
          )}
          <Form form={form} layout="vertical" onFinish={submit} initialValues={{
            name: "liquid_300", selection: [dayjs("2021-06-18"), dayjs("2024-07-26")], topN: 300,
            minListedDays: 250, minCoverage: 0.9, excludeSuspended: true, overwrite: false, q: "",
          }}>
            <Form.Item label="股票池名称" name="name" rules={[{ required: true, message: "请输入股票池名称" }]}>
              <Input placeholder="如 liquid_300" />
            </Form.Item>
            <Form.Item label="筛选窗口" name="selection" rules={[{ required: true, message: "请选择筛选窗口" }]}>
              <DatePicker.RangePicker className="full-width" />
            </Form.Item>
            <Form.Item label="行业（公司库单级行业）" name="industries">
              <Select
                mode="multiple" allowClear showSearch optionFilterProp="label"
                disabled={filtersDisabled} loading={optionsApi.loading}
                options={industryOptions} placeholder={optionsApi.error ? "公司库不可用" : "全部行业"}
                maxTagCount={4}
              />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item label="市场" name="exchanges">
                  <Select mode="multiple" allowClear disabled={filtersDisabled} options={marketOptions} placeholder="全部市场" maxTagCount={2} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="板块" name="boards" extra="按代码前缀推导，可多选">
                  <Select mode="multiple" allowClear disabled={filtersDisabled} options={boardOptions} placeholder="全部板块" maxTagCount={2} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="代码 / 名称关键词" name="q">
              <Input allowClear placeholder="如 600000 或 银行" />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}><Form.Item label="入选股票数 TopN" name="topN" extra="作为上限；勾选不足此数时按实际数量建池" rules={[{ type: "number", min: 1, max: 5000, message: "范围 1–5000" }]}><InputNumber className="full-width" min={1} max={5000} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最低上市天数" name="minListedDays" rules={[{ type: "number", min: 1 }]}><InputNumber className="full-width" min={1} /></Form.Item></Col>
            </Row>
            <Row gutter={12}>
              <Col span={12}><Form.Item label="最低覆盖率" name="minCoverage" rules={[{ type: "number", min: 0, max: 1 }]}><InputNumber className="full-width" min={0} max={1} step={0.05} /></Form.Item></Col>
              <Col span={12}><Form.Item label="停牌过滤" name="excludeSuspended" valuePropName="checked"><Switch checkedChildren="过滤停牌" unCheckedChildren="包含停牌" /></Form.Item></Col>
            </Row>
            <Collapse
              ghost size="small"
              items={[{
                key: "advanced",
                label: "高级筛选（库内原始编码）",
                children: (
                  <Space direction="vertical" size={0} className="full-width">
                    <Form.Item label="库内板块原始值 ListedSector" name="sectors" extra="公司库原始编码，业务含义以数据库为准。">
                      <Select mode="multiple" allowClear disabled={filtersDisabled} options={sectorOptions} placeholder="不限制" maxTagCount={3} />
                    </Form.Item>
                    <Form.Item label="库内上市状态原始值 ListedState" name="listedStates" extra="公司库原始编码，业务含义以数据库为准。">
                      <Select mode="multiple" allowClear disabled={filtersDisabled} options={listedStateOptions} placeholder="不限制" maxTagCount={3} />
                    </Form.Item>
                  </Space>
                ),
              }]}
            />
            <Form.Item name="overwrite" valuePropName="checked" noStyle><Switch checkedChildren="覆盖已有同名池" unCheckedChildren="同名池已存在则报错" /></Form.Item>
            <Button
              size="large" block type="primary" htmlType="submit" loading={submitting}
              disabled={createDisabled} icon={<PlayCircleOutlined />} className="pool-submit"
            >
              创建股票池
            </Button>
          </Form>
          {warnings.length > 0 && (
            <Alert
              style={{ marginTop: 16 }} type="warning" showIcon message="建池提示"
              description={<Space direction="vertical" size={2}>
                {warnings.map((item) => <Text key={item}>{item}</Text>)}
              </Space>}
            />
          )}
          {jobId && (
            <Alert
              style={{ marginTop: 16 }} showIcon type={jobType}
              icon={polling ? <Spin size="small" /> : undefined}
              message={jobMessage}
              description={<Space direction="vertical" size={2}>
                {jobError && <Text>{jobError}</Text>}
                {job?.status === "failed" && job.message && <Text>{job.message}</Text>}
                {job?.status === "finished" && <Text>{jobPoolId ? `Pool ID：${jobPoolId}` : "已有股票池列表已刷新。"}</Text>}
                {polling && <Text type="secondary">任务在后台运行，完成后自动刷新列表。</Text>}
              </Space>}
            />
          )}
        </Card>
      </Col>
      <Col span={14}>
        <Space direction="vertical" size={16} className="full-width">
          <Card
            title={<Space><FilterOutlined />筛选预览</Space>}
            extra={<Space>
              <Text type="secondary">基准日 {preview?.as_of ?? filters.as_of ?? "今天"}</Text>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => setPreviewTick((value) => value + 1)}>刷新</Button>
            </Space>}
            className="data-card"
          >
            {previewError ? (
              <Alert
                type="error" showIcon message="候选股票预览失败" description={previewError}
                action={<Button size="small" icon={<ReloadOutlined />} onClick={() => setPreviewTick((value) => value + 1)}>重试</Button>}
              />
            ) : previewLoading && !preview ? (
              <Skeleton active paragraph={{ rows: 6 }} />
            ) : preview ? (
              <Space direction="vertical" size={12} className="full-width">
                <Row gutter={12}>
                  <Col span={8}><Statistic title="匹配股票" value={preview.matched_total} suffix="只" /></Col>
                  <Col span={8}><Statistic title="已勾选" value={selectedList.length} suffix="只" /></Col>
                  <Col span={8}><Statistic title="当前页" value={preview.items.length} suffix="只" /></Col>
                </Row>
                <Flex justify="space-between" align="center" wrap gap={8}>
                  <Space size={6} wrap>
                    <Button
                      size="small" onClick={selectAll}
                      disabled={codesLoading || allCodes.length === 0}
                      title="全选当前筛选下全部股票（跨页）"
                    >全选</Button>
                    <Button
                      size="small" onClick={invertSelection}
                      disabled={codesLoading || allCodes.length === 0}
                      title="在当前筛选的全部股票中反选（跨页）"
                    >反选</Button>
                    <Button size="small" onClick={clearSelection} disabled={selectedList.length === 0}>清空</Button>
                    {codesLoading && <Spin size="small" />}
                    {pagePartial && (
                      <Tag color="processing">本页部分勾选 {pageSelectedCount}/{pageSelectable.length}</Tag>
                    )}
                  </Space>
                  <Text type="secondary">
                    已选 <Text strong>{selectedList.length}</Text> / 匹配 {preview.matched_total} 只
                  </Text>
                </Flex>
                {codesError && !previewError && (
                  <Alert
                    type="error" showIcon
                    message="无法加载全部候选代码，暂时不能建池"
                    description={codesError}
                  />
                )}
                {preview.matched_total === 0 && (
                  <Alert type="error" showIcon message="当前筛选没有匹配的股票，请放宽条件" />
                )}
                <Flex justify="space-between" align="center" wrap gap={8}>
                  <Text type="secondary">
                    候选直接来自公司 ClickHouse（全市场 {optionsApi.data?.total ?? "—"} 只）
                  </Text>
                </Flex>
                <Table
                  rowKey="code" size="small" columns={previewColumns} dataSource={preview.items}
                  rowSelection={previewRowSelection}
                  loading={previewLoading} scroll={{ x: 920 }}
                  pagination={{
                    current: page, pageSize: PREVIEW_PAGE_SIZE, total: preview.total,
                    showSizeChanger: false, showTotal: (total) => `共 ${total} 只`,
                    onChange: setPage,
                  }}
                />
                <Text type="secondary">
                  数据查询时间 {preview.queried_at ?? "—"}{preview.cached ? "（命中服务端缓存）" : ""}；
                  候选、建池与回测全部直接使用公司 ClickHouse。
                </Text>
              </Space>
            ) : null}
          </Card>
          <LoadGate state={poolsApi}>
            <Card title={<Space><TeamOutlined />已有股票池</Space>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={poolsApi.reload}>刷新</Button>} className="data-card clickable-rows">
              <Table rowKey="pool_id" size="middle" columns={columns} dataSource={poolsApi.data?.pools ?? []} pagination={false}
                onRow={(record) => ({ onClick: () => setOpenPool(record) })} />
              <Drawer width={480} open={!!openPool} onClose={() => setOpenPool(null)} title={openPool && <Space>股票池 <Text code>{openPool.name}</Text></Space>}>
                {openPool && <Space direction="vertical" size={20} className="full-width">
                  <Descriptions column={1} size="small" bordered items={[
                    { key: "id", label: "Pool ID", children: <Text code copyable>{openPool.pool_id}</Text> },
                    { key: "n", label: "股票数", children: openPool.n_stocks },
                    { key: "window", label: "筛选窗口", children: `${openPool.selection_start} ~ ${openPool.selection_end}` },
                    { key: "listed", label: "最低上市天数", children: openPool.min_listed_days },
                    { key: "coverage", label: "最低覆盖率", children: `${(openPool.min_coverage * 100).toFixed(0)}%` },
                    { key: "suspend", label: "停牌过滤", children: openPool.exclude_suspended ? "是" : "否" },
                    { key: "cov", label: "实际覆盖率", children: openPool.coverage == null ? "—" : `${(openPool.coverage * 100).toFixed(1)}%` },
                    { key: "amount", label: "平均日成交额", children: openPool.avg_amount == null ? "—" : `¥${(openPool.avg_amount / 1e8).toFixed(2)} 亿` },
                    {
                      key: "storage", label: "存储位置",
                      children: openPool.storage === "mysql" ? "MySQL"
                        : openPool.storage === "mysql+local" ? "MySQL + 本地文件"
                          : openPool.storage === "local" ? "本地文件" : "—",
                    },
                    { key: "created", label: "创建时间", children: openPool.created_at },
                  ]} />
                  {openPool.provenance && (
                    <>
                      <Divider orientation="left" plain style={{ margin: 0 }}>筛选来源</Divider>
                      <Descriptions column={1} size="small" bordered items={[
                        { key: "source", label: "候选来源", children: "公司 ClickHouse" },
                        { key: "filters", label: "筛选条件", children: describeFilters(openPool.provenance.filters) },
                        {
                          key: "counts", label: "匹配 / 建池",
                          children: `${openPool.provenance.matched_total ?? "—"} / ${openPool.provenance.selected_total ?? openPool.n_stocks ?? "—"}${
                            openPool.provenance.selection_mode === "manual" ? "（手动勾选）" : "（全部匹配候选）"
                          }`,
                        },
                        { key: "asof", label: "筛选基准日", children: openPool.provenance.as_of ?? "—" },
                        { key: "query", label: "候选查询时间", children: openPool.provenance.queried_at ?? "—" },
                      ]} />
                    </>
                  )}
                  {poolDetail.loading && <Skeleton active paragraph={{ rows: 3 }} />}
                  {poolDetail.data && (
                    <div>
                      <Text strong>池内股票（{poolDetail.data.codes.length} 只）</Text>
                      <Flex gap={6} wrap style={{ marginTop: 8 }}>
                        {poolDetail.data.codes.slice(0, 24).map((code) => <Tag key={code}>{code}</Tag>)}
                        {poolDetail.data.codes.length > 24 && <Tag>…共 {poolDetail.data.codes.length} 只</Tag>}
                      </Flex>
                    </div>
                  )}
                  <Text type="secondary">池 ID 由「名称 + 数据签名」哈希生成：主缓存重建或换机器后池 ID 会变化，旧因子运行需重新绑定。</Text>
                  <Divider style={{ margin: 0 }} />
                  <Space wrap>
                    <Button icon={<CopyOutlined />} onClick={applyPoolTemplate}>以此为模板新建</Button>
                    <Popconfirm
                      title="删除股票池"
                      description="将删除本地目录与 MySQL 记录，且不可恢复；因子运行和历史回测结果不会删除。"
                      okText="确认删除" cancelText="取消" okButtonProps={{ danger: true }}
                      onConfirm={deleteOpenPool}
                    >
                      <Button danger icon={<DeleteOutlined />} loading={deleting}>删除股票池</Button>
                    </Popconfirm>
                  </Space>
                </Space>}
              </Drawer>
            </Card>
          </LoadGate>
        </Space>
      </Col>
    </Row>
  );
}

/* ============ 因子回测 ============ */

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

const metricNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
};

const formatFraction = (value: unknown, digits = 2): string => {
  const number = metricNumber(value);
  return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
};

export function FactorBacktestPage({ navigate }: { navigate: PageNav }) {
  const [form] = Form.useForm<FactorBacktestFormValues>();
  const runsApi = useApiData(api.factorRuns);
  const runs = useMemo(() => runsApi.data?.runs ?? [], [runsApi.data]);
  const [runId, setRunId] = useState<string | undefined>();
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [batchId, setBatchId] = useState<string | undefined>();
  const pendingBatchRef = useRef<string | null>(null);
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
  useEffect(() => {
    // 切换运行/首次加载后默认全选；用户取消勾选不会被轮询覆盖
    setSelected(factors.map((factor) => factor.factor_id));
  }, [factors]);
  const selectedIds = selected.map(String);
  const allSelected = factors.length > 0 && selectedIds.length === factors.length;

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
      // 新任务完成、批次列表刷新后自动选中刚提交的批次
      pendingBatchRef.current = null;
      if (batchId !== pending) setBatchId(pending);
      return;
    }
    if (pending && batchId === pending) return; // 列表尚未刷新，别回退到旧批次
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

  const factorColumns: TableColumnsType<AcceptedFactor> = [
    { title: "因子 ID", dataIndex: "factor_id", width: 200, render: (v) => <Text code style={{ whiteSpace: "nowrap" }}>{v}</Text> },
    { title: "表达式", dataIndex: "expression", ellipsis: true, render: (v) => <Text code>{v}</Text> },
    { title: "IC", dataIndex: "ic", align: "right", width: 82, sorter: (a, b) => (a.ic ?? -Infinity) - (b.ic ?? -Infinity), render: (v) => metricNumber(v)?.toFixed(4) ?? "—" },
    { title: "RankIC", dataIndex: "rank_ic", align: "right", width: 88, sorter: (a, b) => (a.rank_ic ?? -Infinity) - (b.rank_ic ?? -Infinity), render: (v) => metricNumber(v)?.toFixed(4) ?? "—" },
    { title: "ICIR", dataIndex: "icir", align: "right", width: 82, sorter: (a, b) => (a.icir ?? -Infinity) - (b.icir ?? -Infinity), render: (v) => metricNumber(v)?.toFixed(2) ?? "—" },
    { title: "覆盖率", dataIndex: "coverage", align: "right", width: 88, render: (v) => formatFraction(v, 1) },
    { title: "Score", dataIndex: "score", align: "right", width: 82, sorter: (a, b) => (a.score ?? -Infinity) - (b.score ?? -Infinity), render: (v) => metricNumber(v)?.toFixed(2) ?? "—" },
  ];

  const batchColumns: TableColumnsType<FactorBacktestRow> = [
    { title: "因子 ID", dataIndex: "factor_id", width: 200, render: (v) => <Text code style={{ whiteSpace: "nowrap" }}>{String(v ?? "—")}</Text> },
    { title: "表达式", dataIndex: "expression", ellipsis: true, render: (v) => <Text code>{String(v ?? "—")}</Text> },
    {
      title: "年化收益", key: "annual", align: "right", width: 100,
      sorter: (a, b) => (metricNumber(a.backtest_annual_return) ?? -Infinity) - (metricNumber(b.backtest_annual_return) ?? -Infinity),
      render: (_, row) => {
        const value = metricNumber(row.backtest_annual_return);
        return <Text type={value != null && value < 0 ? "danger" : "success"}>{formatFraction(value)}</Text>;
      },
    },
    { title: "夏普", key: "sharpe", align: "right", width: 78, sorter: (a, b) => (metricNumber(a.backtest_sharpe) ?? -Infinity) - (metricNumber(b.backtest_sharpe) ?? -Infinity), render: (_, row) => metricNumber(row.backtest_sharpe)?.toFixed(2) ?? "—" },
    { title: "最大回撤", key: "drawdown", align: "right", width: 92, render: (_, row) => <Text type="danger">{formatFraction(row.backtest_max_drawdown)}</Text> },
    { title: "换手率", key: "turnover", align: "right", width: 88, render: (_, row) => formatFraction(row.backtest_average_turnover) },
    { title: "成本", key: "cost", align: "right", width: 78, render: (_, row) => formatFraction(row.backtest_total_cost) },
    { title: "胜率", key: "win_rate", align: "right", width: 78, render: (_, row) => formatFraction(row.backtest_win_rate) },
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
        <Flex justify="space-between" gap={16} wrap align="center">
          <Space wrap>
            <Text strong><ExperimentOutlined /> 因子运行</Text>
            <Select
              value={runId}
              onChange={(value) => {
                pendingBatchRef.current = null;
                setRunId(value);
              }}
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
                  topK: 50, initialCash: 100000000, buyCost: 0.0015, sellCost: 0.0015,
                  slippage: 0.0005, minCost: 5, maxWeight: 0.02,
                }}
              >
                <Form.Item label="回测区间" name="dates" rules={[{ required: true, message: "请选择回测区间" }]}>
                  <DatePicker.RangePicker className="full-width" />
                </Form.Item>
                <Row gutter={12}>
                  <Col span={12}><Form.Item label="持仓数量 TopK" name="topK" rules={[{ type: "number", min: 1, max: 1000, message: "范围 1–1000" }]}><InputNumber className="full-width" min={1} max={1000} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="初始资金" name="initialCash"><InputNumber className="full-width" min={1} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="买入费率" name="buyCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="卖出费率" name="sellCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="滑点" name="slippage"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="最低手续费" name="minCost"><InputNumber className="full-width" min={0} addonAfter="元" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="单票权重上限" name="maxWeight"><InputNumber className="full-width" min={0.001} max={1} step={0.01} /></Form.Item></Col>
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
              <Table
                rowKey="factor_id" size="middle" columns={factorColumns} dataSource={factors}
                loading={runDetailApi.loading} pagination={false} scroll={{ x: 760, y: 420 }}
                rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys) }}
                locale={{ emptyText: runDetail && factors.length === 0 ? "该运行没有合格因子" : "请选择因子运行" }}
              />
            </Card>
          </Col>
        </Row>
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
              <Table
                rowKey={(row) => String(row.factor_id ?? row.run_key ?? row.expression)}
                size="small" columns={batchColumns} dataSource={batchDetail?.rows ?? []}
                loading={batchApi.loading} pagination={false} scroll={{ x: 1020 }}
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

/* ============ 因子生成（PPO） ============ */

export function FactorGenerationPage({ addTask, navigate }: { addTask: TaskAdder; navigate: PageNav }) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const masterFields = fieldsData.filter((f) => f.source === "master 精选").map((f) => f.name);
  const defaultFields = ["open", "close", "high", "low", "volume", "amount", "ChangePCT", "TurnoverRate", "ma5", "ma20", "ema12", "macd"];
  const toRange = (v: unknown) => (v as unknown as { format: (f: string) => string }[] | undefined)?.map((d) => d.format("YYYY-MM-DD"));
  const selectedFields = Form.useWatch("fields", form) as string[] | undefined;
  const submit = (values: Record<string, unknown>) => {
    setSubmitting(true);
    setTimeout(() => {
      const id = addTask({
        type: "generate_factors", typeLabel: "因子生成", name: String(values.name), status: "queued", progress: 0,
        submittedAt: "刚刚", duration: "—", owner: "林研究员",
        logs: [`[${nowStamp()}] PPO 训练环境初始化（device=${values.device}）`, `[${nowStamp()}] 已进入任务队列`],
        params: {
          pool: values.pool, fields_count: (values.fields as string[]).length, target_horizon: values.targetHorizon,
          max_backtrack_days: values.maxBacktrackDays, target_factor_count: values.targetFactorCount,
          max_attempts: values.maxAttempts, rollout_timesteps: values.rolloutTimesteps, seed: values.seed, device: values.device,
          splits: { train: toRange(values.train), valid: toRange(values.valid), test: toRange(values.test) },
          quality: { min_coverage: values.minCoverage, min_train_ic: values.minTrainIc, min_valid_ic: values.minValidIc, min_icir: values.minIcir },
        },
      });
      setSubmitting(false);
      message.success(`因子生成任务 #${id} 已提交`);
      navigate("tasks", id);
    }, 750);
  };
  const previewColumns: TableColumnsType<FactorItem> = [
    { title: "因子 ID", dataIndex: "id", width: 84, render: (v) => <Text code>{v}</Text> },
    { title: "表达式", dataIndex: "expression", render: (v) => <Text code>{v}</Text> },
    { title: "ICIR", dataIndex: "icir", align: "right", width: 76 },
    { title: "Score", dataIndex: "score", align: "right", width: 76 },
  ];
  return (
    <Row gutter={16} className="backtest-layout">
      <Col span={10}>
        <Card title={<Space><RobotOutlined />PPO 生成参数</Space>} className="form-card">
          <Form form={form} layout="vertical" onFinish={submit} initialValues={{
            name: "ppo_run_102", pool: "liquid_500", fields: defaultFields,
            train: [dayjs("2022-01-14"), dayjs("2024-07-26")], valid: [dayjs("2024-01-25"), dayjs("2025-07-28")], test: [dayjs("2025-01-27"), dayjs("2026-06-12")],
            targetHorizon: 20, maxBacktrackDays: 100, targetFactorCount: 50, maxAttempts: 100000, rolloutTimesteps: 2048, seed: 0, device: "cpu",
            minCoverage: 0.9, minTrainIc: 0.05, minValidIc: 0.04, minIcir: 0.5,
          }}>
            <Row gutter={12}>
              <Col span={12}><Form.Item label="股票池" name="pool" rules={[{ required: true }]}><Select options={[{ value: "liquid_500", label: "liquid_500 · 500只" }]} /></Form.Item></Col>
              <Col span={12}><Form.Item label="运行名称" name="name" rules={[{ required: true, message: "请输入运行名称" }]}><Input /></Form.Item></Col>
            </Row>
            <Form.Item label={`可用字段（已选 ${(selectedFields || []).length} / ${masterFields.length}）`} name="fields" rules={[{ required: true, message: "至少选择一个字段" }]}>
              <Select mode="multiple" allowClear showSearch options={masterFields.map((f) => ({ value: f, label: f }))} placeholder="选择参与搜索的字段" maxTagCount={6} />
            </Form.Item>
            <Divider orientation="left" plain>数据切分</Divider>
            <Form.Item label="训练段 train" name="train" rules={[{ required: true }]}><DatePicker.RangePicker className="full-width" /></Form.Item>
            <Form.Item label="验证段 valid" name="valid" rules={[{ required: true }]}><DatePicker.RangePicker className="full-width" /></Form.Item>
            <Form.Item label="测试段 test" name="test" rules={[{ required: true }]}><DatePicker.RangePicker className="full-width" /></Form.Item>
            <Divider orientation="left" plain>搜索与训练</Divider>
            <Row gutter={12}>
              <Col span={12}><Form.Item label="目标持有期 horizon" name="targetHorizon" rules={[{ type: "number", min: 1, max: 60 }]}><InputNumber className="full-width" min={1} max={60} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最大回溯天数" name="maxBacktrackDays"><InputNumber className="full-width" min={10} max={250} /></Form.Item></Col>
              <Col span={12}><Form.Item label="目标因子数" name="targetFactorCount"><InputNumber className="full-width" min={1} max={200} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最大尝试次数" name="maxAttempts"><InputNumber className="full-width" min={1000} step={10000} /></Form.Item></Col>
              <Col span={12}><Form.Item label="Rollout 步数" name="rolloutTimesteps"><InputNumber className="full-width" min={512} step={512} /></Form.Item></Col>
              <Col span={12}><Form.Item label="随机种子" name="seed"><InputNumber className="full-width" min={0} /></Form.Item></Col>
              <Col span={12}><Form.Item label="计算设备" name="device"><Select options={[{ value: "cpu", label: "CPU" }, { value: "cuda", label: "CUDA (GPU)" }]} /></Form.Item></Col>
            </Row>
            <Divider orientation="left" plain>质量阈值</Divider>
            <Row gutter={12}>
              <Col span={12}><Form.Item label="最低覆盖率" name="minCoverage" rules={[{ type: "number", min: 0, max: 1 }]}><InputNumber className="full-width" min={0} max={1} step={0.05} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最低训练 IC" name="minTrainIc" rules={[{ type: "number", min: 0, max: 1 }]}><InputNumber className="full-width" min={0} max={1} step={0.01} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最低验证 IC" name="minValidIc" rules={[{ type: "number", min: 0, max: 1 }]}><InputNumber className="full-width" min={0} max={1} step={0.01} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最低 ICIR" name="minIcir" rules={[{ type: "number", min: 0, max: 3 }]}><InputNumber className="full-width" min={0} max={3} step={0.1} /></Form.Item></Col>
            </Row>
            <Button size="large" block type="primary" htmlType="submit" loading={submitting} icon={<PlayCircleOutlined />}>启动 PPO 因子生成</Button>
          </Form>
        </Card>
      </Col>
      <Col span={14}>
        <Space direction="vertical" size={16} className="full-width">
          <Card size="small" title="生成流程">
            <Steps size="small" current={4} items={[
              { title: "导出池内面板", description: "按 pool_id 导出行情" },
              { title: "构造训练数据", description: "train / valid / test 切分" },
              { title: "PPO 搜索表达式", description: "在算子空间内组合" },
              { title: "质量筛选", description: "IC / RankIC / ICIR / 覆盖率" },
            ]} />
          </Card>
          <Card title={`最近一次生成运行（${generationSummary.runId} · #${generationSummary.taskId}）`} className="data-card"
            extra={<Button type="link" onClick={() => navigate("tasks", generationSummary.taskId)}>查看任务</Button>}>
            <Row gutter={12}>
              <Col span={6}><Statistic title="尝试次数" value={generationSummary.attempts} /></Col>
              <Col span={6}><Statistic title="合格因子" value={generationSummary.accepted} suffix="个" /></Col>
              <Col span={6}><Statistic title="最佳 ICIR" value={generationSummary.bestIcir} precision={2} /></Col>
              <Col span={6}><Statistic title="最佳 Score" value={generationSummary.bestScore} precision={2} /></Col>
            </Row>
            <Divider />
            <Table rowKey="id" size="small" columns={previewColumns} dataSource={acceptedFactors.slice(0, 6)} pagination={false} />
            <Flex justify="flex-end" className="note-action">
              <Button type="link" onClick={() => navigate("factor_backtest")}>在因子回测页查看全部 {generationSummary.accepted} 个合格因子</Button>
            </Flex>
          </Card>
        </Space>
      </Col>
    </Row>
  );
}
