import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, DatePicker, Empty, Flex, Form, Input, InputNumber, message,
  Progress, Row, Select, Skeleton, Space, Spin, Statistic, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudDownloadOutlined, PlayCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { EquityChart, YearlyChart } from "../Charts";
import {
  api, resultFileUrl, useApiData, useJobPolling,
  type ManualBacktestRequest, type ResultDetail, type YearlyDatum,
} from "../api/client";

const { Text, Title } = Typography;
type Dayjs = dayjs.Dayjs;

type ManualFormValues = {
  expression: string;
  poolId: string;
  dates: [Dayjs, Dayjs];
  topK: number;
  initialCash: number;
  buyCost: number;
  sellCost: number;
  slippage: number;
  minCost: number;
  maxWeight: number;
  runName: string;
};

const EXAMPLES = [
  "close / delay(close, 20) - 1",
  "-rank(TurnoverRate)",
  "close / ts_mean(close, 20) - 1",
];

const yearlyColumns: TableColumnsType<YearlyDatum> = [
  { title: "年份", dataIndex: "year" },
  { title: "收益", dataIndex: "returns", align: "right", render: (v) => <Text type={v >= 0 ? "danger" : "success"}>{v.toFixed(2)}%</Text> },
  { title: "夏普", dataIndex: "sharpe", align: "right", render: (v) => v.toFixed(2) },
  { title: "最大回撤", dataIndex: "drawdown", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "换手率", dataIndex: "turnover", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "成本", dataIndex: "cost", align: "right", render: (v) => `${v.toFixed(2)}%` },
  { title: "胜率", dataIndex: "winRate", align: "right", render: (v) => `${v.toFixed(2)}%` },
];

function MetricCard({ title, value, suffix = "%", tone }: { title: string; value: number | null; suffix?: string; tone: string }) {
  return (
    <Card className={`metric-card metric-${tone}`}>
      <Statistic title={title} value={value ?? "—"} suffix={value == null ? undefined : suffix} precision={2} />
    </Card>
  );
}

function stagePercent(stage: string, finished: boolean): number {
  if (finished) return 100;
  if (stage === "running") return 80;
  if (stage === "evaluating") return 50;
  if (stage === "loading_panel") return 20;
  return 5;
}

function ResultPreview({
  detail, loading, error, onReload, onOpenResult,
}: {
  detail: ResultDetail | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  onOpenResult: (runKey: string) => void;
}) {
  if (error) {
    return (
      <Alert
        type="error" showIcon message="结果加载失败" description={error}
        action={<Button size="small" icon={<ReloadOutlined />} onClick={onReload}>重试</Button>}
      />
    );
  }
  if (loading && !detail) return <Skeleton active paragraph={{ rows: 10 }} />;
  if (!detail) {
    return <Empty description="提交手动回测后，结果展示在这里"><Text type="secondary">也可以先查看「结果详情」页里的历史真实结果</Text></Empty>;
  }
  const backtest = (detail.config?.backtest ?? {}) as Record<string, unknown>;
  const range = backtest.start_date && backtest.end_date
    ? `${String(backtest.start_date)} ~ ${String(backtest.end_date)}`
    : "—";
  const topk = backtest.top_k != null ? `TopK ${String(backtest.top_k)}` : "—";
  const { metrics } = detail;
  return (
    <Space direction="vertical" size={16} className="full-width">
      <div>
        <Flex justify="space-between" align="start" gap={12}>
          <div>
            <Space wrap size={6}>
              <Tag color="green">真实结果</Tag>
              <Tag color="blue">手动回测</Tag>
              <Tag>池 {detail.pool_id ?? "—"}</Tag>
              <Tag>{range}</Tag>
              <Tag>{topk}</Tag>
            </Space>
            <Title level={4} style={{ marginTop: 10 }}>{detail.run_name}</Title>
            <Text code>{detail.canonical_expression ?? "—"}</Text>
          </div>
          <Button icon={<CloudDownloadOutlined />} onClick={() => onOpenResult(detail.run_key)}>完整结果</Button>
        </Flex>
      </div>
      <Row gutter={12}>
        <Col span={8}><MetricCard title="年化收益" value={metrics.annual} tone="green" /></Col>
        <Col span={8}><MetricCard title="夏普比率" value={metrics.sharpe} suffix="" tone="blue" /></Col>
        <Col span={8}><MetricCard title="最大回撤" value={metrics.drawdown} tone="red" /></Col>
        <Col span={8}><MetricCard title="换手率" value={metrics.turnover} tone="violet" /></Col>
        <Col span={8}><MetricCard title="交易成本" value={metrics.cost} tone="orange" /></Col>
        <Col span={8}><MetricCard title="胜率" value={metrics.winRate} tone="cyan" /></Col>
      </Row>
      <Row gutter={12}>
        <Col span={15}><Card title="策略净值与回撤" className="data-card">{detail.equity.length > 0 ? <EquityChart data={detail.equity} /> : <Empty description="无每日净值数据" />}</Card></Col>
        <Col span={9}><Card title="年度收益" extra={<Text type="secondary">红涨绿跌</Text>} className="data-card">{detail.yearly.length > 0 ? <YearlyChart data={detail.yearly} /> : <Empty description="无年度指标" />}</Card></Col>
      </Row>
      <Card title="年度指标" className="data-card">
        <Table rowKey="year" size="small" pagination={false} columns={yearlyColumns} dataSource={detail.yearly} />
      </Card>
      <Card title="结果文件" className="data-card" extra={<Text type="secondary">{detail.files.length} 个文件</Text>}>
        <Space wrap>
          {detail.files.map((file) => (
            <Button key={file.name} icon={<CloudDownloadOutlined />} onClick={() => { window.location.href = resultFileUrl(detail.run_key, file.name); }}>
              {file.name}
            </Button>
          ))}
        </Space>
      </Card>
    </Space>
  );
}

export function ManualBacktestPage({ onOpenResult }: { onOpenResult: (runKey: string) => void }) {
  const [form] = Form.useForm<ManualFormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [resultKey, setResultKey] = useState<string | null>(null);
  const finishedRef = useRef<string | null>(null);
  const { job, error: jobError, polling } = useJobPolling(jobId);

  const poolsApi = useApiData(api.pools);
  const pools = useMemo(() => {
    const items = poolsApi.data?.pools ?? [];
    // 公司库池排在前面；旧本地池仍可选，兼容历史数据
    return [...items].sort((a, b) => Number(a.data_source !== "clickhouse") - Number(b.data_source !== "clickhouse"));
  }, [poolsApi.data]);
  const watchedPoolId = Form.useWatch("poolId", form) as string | undefined;
  const pool = pools.find((item) => item.pool_id === watchedPoolId) ?? null;

  useEffect(() => {
    if (pools.length === 0) {
      if (watchedPoolId) form.setFieldValue("poolId", undefined);
      return;
    }
    if (!watchedPoolId || !pools.some((item) => item.pool_id === watchedPoolId)) {
      form.setFieldValue("poolId", pools[0].pool_id);
    }
  }, [pools, watchedPoolId, form]);

  useEffect(() => {
    if (!pool?.selection_start || !pool.selection_end) return;
    form.setFieldValue("dates", [dayjs(pool.selection_start), dayjs(pool.selection_end)]);
    // 只在切换股票池时重置默认区间，用户手动改过的日期不会被轮询/重渲染覆盖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool?.pool_id]);

  const resultsApi = useApiData(api.results);
  const latestManual = useMemo(() => {
    // 只展示新版 manual/<job_id>/<run_name> 结果；旧扁平 web_run 等不当作本页历史
    const items = (resultsApi.data?.results ?? []).filter(
      (item) => item.result_type === "manual" && item.run_key.startsWith("manual/"),
    );
    return items.sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))[0] ?? null;
  }, [resultsApi.data]);

  const previewKey = resultKey ?? latestManual?.run_key ?? null;
  const detailApi = useApiData(
    () => (previewKey ? api.result(previewKey) : Promise.resolve(null)),
    [previewKey],
  );
  const detail = detailApi.data?.run_key === previewKey ? detailApi.data : null;

  useEffect(() => {
    if (!jobId || job?.status !== "finished" || finishedRef.current === jobId) return;
    finishedRef.current = jobId;
    const key = typeof job.result?.run_key === "string" ? job.result.run_key : null;
    if (key) {
      setResultKey(key);
      message.success(`手动回测完成：${key}`);
    }
    resultsApi.reload();
  }, [jobId, job?.status, job?.result, resultsApi.reload]);

  const submit = async (values: ManualFormValues) => {
    if (!pool) {
      message.error("请选择股票池");
      return;
    }
    if (!values.dates?.[0] || !values.dates?.[1]) {
      message.error("请选择回测区间");
      return;
    }
    const payload: ManualBacktestRequest = {
      expression: values.expression,
      pool_id: pool.pool_id,
      run_name: values.runName,
      start_date: values.dates[0].format("YYYY-MM-DD"),
      end_date: values.dates[1].format("YYYY-MM-DD"),
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
      const response = await api.createManualBacktest(payload);
      setJobId(response.job_id);
      setWarnings(response.warnings);
      message.info(`手动回测任务已提交：${response.job_id}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  // 同一份 stage 文案只用于粗粒度进度条，真实进度以任务 message 为准
  const stage = String((job?.progress ?? {}).stage ?? "");
  const jobPercent = stagePercent(stage, job?.status === "finished");
  const jobType = jobError || job?.status === "failed" ? "error" : job?.status === "finished" ? "success" : "info";
  const jobMessage = !job
    ? (jobError ? "手动回测任务状态查询失败" : "手动回测任务已提交，等待状态…")
    : job.status === "queued" ? `手动回测排队中（${jobId}）`
      : job.status === "running" ? "手动回测运行中"
        : job.status === "finished" ? "手动回测完成"
          : job.status === "failed" ? "手动回测失败"
            : `任务状态：${job.status}`;

  const canSubmit = Boolean(pool) && !polling && !submitting;

  return (
    <Space direction="vertical" size={16} className="page-stack">
      {poolsApi.error && (
        <Alert
          type="error" showIcon message="无法读取股票池列表" description={poolsApi.error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={poolsApi.reload}>重试</Button>}
        />
      )}
      {!poolsApi.loading && !poolsApi.error && pools.length === 0 && (
        <Alert
          type="info" showIcon message="还没有可回测的股票池"
          description="请先在「股票池」页按公司库条件创建股票池；手动回测与因子回测都基于股票池面板执行。"
        />
      )}

      <Row gutter={16} className="backtest-layout">
        <Col span={10}>
          <Card title={<Space><PlayCircleOutlined />回测参数</Space>} className="form-card">
            <Form
              form={form} layout="vertical" onFinish={submit}
              initialValues={{
                expression: EXAMPLES[0],
                dates: [dayjs().subtract(1, "year"), dayjs()],
                topK: 50, initialCash: 100000000, buyCost: 0.0015, sellCost: 0.0015,
                slippage: 0.0005, minCost: 5, maxWeight: 0.02, runName: "manual_run",
              }}
            >
              <Form.Item label="Alpha 表达式" name="expression" rules={[{ required: true, message: "请输入 Alpha 表达式" }]}>
                <Input.TextArea className="code-input" autoSize={{ minRows: 3, maxRows: 5 }} placeholder="例如 close / delay(close, 20) - 1" />
              </Form.Item>
              <Flex gap={6} wrap className="example-row">
                {EXAMPLES.map((item, index) => (
                  <Button size="small" type="dashed" key={item} onClick={() => form.setFieldValue("expression", item)}>
                    示例 {index + 1}
                  </Button>
                ))}
              </Flex>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item label="股票池" name="poolId" rules={[{ required: true, message: "请选择股票池" }]}>
                    <Select
                      showSearch optionFilterProp="label" placeholder="选择股票池"
                      loading={poolsApi.loading}
                      options={pools.map((item) => ({
                        value: item.pool_id,
                        label: `${item.name} · ${item.n_stocks}只${item.data_source === "clickhouse" ? "" : "（旧本地池）"}`,
                      }))}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="日期区间" name="dates" rules={[{ required: true, message: "请选择回测区间" }]}>
                    <DatePicker.RangePicker className="full-width" />
                  </Form.Item>
                </Col>
              </Row>
              {pool && (
                <Alert
                  type={pool.data_source === "clickhouse" ? "info" : "warning"}
                  showIcon
                  style={{ marginBottom: 16 }}
                  message={pool.data_source === "clickhouse"
                    ? `公司库面板 · ${pool.n_stocks} 只股票 · 选样窗口 ${pool.selection_start ?? "—"} ~ ${pool.selection_end ?? "—"}`
                    : "旧本地池：没有公司库签名，回测将读取本地 data_cache/master（仅兼容历史池）"}
                />
              )}
              <Row gutter={12}>
                <Col span={12}><Form.Item label="持仓数量 TopK" name="topK" rules={[{ type: "number", min: 1, max: 1000, message: "范围 1–1000" }]}><InputNumber className="full-width" min={1} max={1000} /></Form.Item></Col>
                <Col span={12}><Form.Item label="初始资金" name="initialCash"><InputNumber className="full-width" min={1} addonAfter="元" /></Form.Item></Col>
                <Col span={12}><Form.Item label="买入费率" name="buyCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                <Col span={12}><Form.Item label="卖出费率" name="sellCost"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                <Col span={12}><Form.Item label="滑点" name="slippage"><InputNumber className="full-width" step={0.0001} min={0} max={0.1} /></Form.Item></Col>
                <Col span={12}><Form.Item label="最低手续费" name="minCost"><InputNumber className="full-width" min={0} addonAfter="元" /></Form.Item></Col>
                <Col span={12}><Form.Item label="单票权重上限" name="maxWeight"><InputNumber className="full-width" min={0.001} max={1} step={0.01} /></Form.Item></Col>
                <Col span={12}><Form.Item label="运行名称" name="runName" rules={[{ required: true, message: "请输入运行名称" }, { max: 64, message: "不超过 64 个字符" }]}><Input /></Form.Item></Col>
              </Row>
              <Button size="large" block type="primary" htmlType="submit" loading={submitting} disabled={!canSubmit} icon={<PlayCircleOutlined />}>
                提交回测
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
                  {job?.message && <Text type="secondary">{job.message}</Text>}
                  {(job?.status === "running" || job?.status === "finished") && (
                    <Progress percent={jobPercent} size="small" status={job.status === "finished" ? "success" : "active"} />
                  )}
                  {job?.status === "finished" && resultKey && <Text>结果：<Text code>{resultKey}</Text></Text>}
                  {polling && <Text type="secondary">任务在后台运行，完成后右侧自动展示结果。</Text>}
                </Space>}
              />
            )}
          </Card>
        </Col>
        <Col span={14}>
          <Card
            title="回测结果"
            extra={!detail ? undefined : (
              <Space wrap>
                <Tag color={resultKey ? "blue" : "default"}>{resultKey ? "本次提交" : "最近完成"}</Tag>
                <Button size="small" icon={<ReloadOutlined />} onClick={detailApi.reload}>刷新</Button>
              </Space>
            )}
            className="result-preview"
          >
            <ResultPreview
              detail={detail}
              loading={detailApi.loading}
              error={detailApi.error}
              onReload={detailApi.reload}
              onOpenResult={onOpenResult}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
