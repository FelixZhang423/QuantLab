import { RandomTopKComparison } from "./RandomTopKComparison";
import { useEffect, useState } from "react";
import {
  Alert, Button, Card, Col, Descriptions, Divider, Empty, Flex, Input, Result, Row, Segmented, Select,
  Skeleton, Space, Statistic, Table, Tag, Tooltip, Typography, message,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudDownloadOutlined, ExperimentOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  api, resultFileUrl, useApiData,
  type FactorBacktestBatch, type ResultDetail, type ResultSummary,
} from "../../api/client";
import { EquityChart, YearlyChart } from "../../components/Charts";
import { BacktestBatchPanel, SingleResultAnalysisCard } from "./backtestAnalysis";
import type { Page } from "../../app/navigation";
import type { YearlyDatum } from "./api";

const { Text, Title } = Typography;

const yearlyValue = (value: number | null | undefined, suffix = "") =>
  value == null ? "—" : `${value.toFixed(2)}${suffix}`;

const yearlyColumns: TableColumnsType<YearlyDatum> = [
  { title: "年份", dataIndex: "year" },
  {
    title: "区间累计收益率（%）", dataIndex: "returns", align: "right", sorter: (a, b) => a.returns - b.returns,
    render: (v) => v == null ? "—" : <Text type={v >= 0 ? "danger" : "success"}>{v.toFixed(2)}%</Text>,
  },
  { title: "年化夏普比率", dataIndex: "sharpe", align: "right", render: (v) => yearlyValue(v) },
  { title: "年内最大回撤（%）", dataIndex: "drawdown", align: "right", render: (v) => yearlyValue(v, "%") },
  { title: "日均换手率（%）", dataIndex: "turnover", align: "right", render: (v) => yearlyValue(v, "%") },
  { title: "累计交易成本率（%）", dataIndex: "cost", align: "right", render: (v) => yearlyValue(v, "%") },
  { title: "盈利交易日占比（%）", dataIndex: "winRate", align: "right", render: (v) => yearlyValue(v, "%") },
];

function RealMetric({ title, value, suffix = "%", tone }: { title: string; value: number | null; suffix?: string; tone: string }) {
  return (
    <Card className={`metric-card metric-${tone}`}>
      <Statistic title={title} value={value ?? "—"} suffix={value == null ? undefined : suffix} precision={2} />
    </Card>
  );
}

function resultTypeLabel(type: string | null | undefined): string {
  if (type === "manual") return "手动回测";
  if (type === "factor") return "因子回测";
  if (type === "composite") return "因子组合";
  return type ?? "回测";
}

/** 结果 manifest 的数据源：manual 写 clickhouse / clickhouse:...，其余是本地缓存内容哈希 */
function isCompanySource(source: string | null | undefined): boolean {
  return Boolean(source && (source === "clickhouse" || source.startsWith("clickhouse:")));
}

function dataSourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return isCompanySource(source) ? "公司库" : "本地缓存";
}

/** 手动结果把 BacktestConfig 嵌在 config.backtest；因子/组合结果直接平铺在 config */
function splitResultConfig(detail: ResultDetail): { config: Record<string, unknown>; backtest: Record<string, unknown> } {
  const config = detail.config ?? {};
  const nested = config.backtest;
  const backtest = nested && typeof nested === "object" && !Array.isArray(nested)
    ? (nested as Record<string, unknown>)
    : config;
  return { config, backtest };
}

function formatPercentValue(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(digits)}%` : "—";
}

function formatMoney(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `¥${numeric.toLocaleString("zh-CN")}` : "—";
}

function readLocalNote(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

/** 结果详情页顶部的结果切换（只列后端真实结果） */
function ResultSourceSelect({ value, onChange, results }: { value: string; onChange: (value: string) => void; results: ResultSummary[] }) {
  const options = results.map((run) => ({
    value: run.run_key,
    label: `${resultTypeLabel(run.result_type)} · ${run.run_name}${run.created_at ? ` · ${run.created_at.slice(0, 16).replace("T", " ")}` : ""}`,
  }));
  return <Select size="middle" value={value} onChange={onChange} options={options} style={{ minWidth: 360 }} showSearch optionFilterProp="label" placeholder="选择真实结果" />;
}

/** 研究备注：没有后端备注接口，按 run_key 存在本机浏览器，页面明确标注作用域 */
function ResearchNote({ runKey }: { runKey: string }) {
  const storageKey = `quantlab:result-note:${runKey}`;
  const [note, setNote] = useState(() => readLocalNote(storageKey));
  useEffect(() => { setNote(readLocalNote(storageKey)); }, [storageKey]);
  const save = () => {
    try {
      window.localStorage.setItem(storageKey, note);
      message.success("备注已保存到本机浏览器");
    } catch {
      message.error("浏览器存储不可用，备注未保存");
    }
  };
  return (
    <Card title="研究备注" extra={<Text type="secondary">仅保存在本机浏览器</Text>}>
      <Input.TextArea value={note} onChange={(e) => setNote(e.target.value)} autoSize={{ minRows: 3 }} placeholder="记录对这次回测的观察（可选）" />
      <Flex justify="flex-end" className="note-action"><Button type="primary" onClick={save}>保存备注</Button></Flex>
    </Card>
  );
}

/** 真实回测结果视图（数据来自 /api/results/detail） */
function RealResultView({
  detail, results, onSelect, onRefresh,
}: {
  detail: ResultDetail;
  results: ResultSummary[];
  onSelect: (runKey: string) => void;
  onRefresh: () => void;
}) {
  const { config, backtest } = splitResultConfig(detail);
  const factor = config.factor;
  const factorExpression = factor && typeof factor === "object" ? (factor as Record<string, unknown>).expression : null;
  const expression = detail.canonical_expression ?? (typeof factorExpression === "string" ? factorExpression : null);
  const poolText = detail.pool_id ?? "—";
  const rangeText = backtest.start_date && backtest.end_date ? `${String(backtest.start_date)} 至 ${String(backtest.end_date)}` : "—";
  const topkText = backtest.top_k != null ? `TopK ${String(backtest.top_k)}` : "—";
  const capitalText = formatMoney(backtest.initial_cash);
  const sourceText = dataSourceLabel(detail.data_source);
  const isFactor = detail.result_type === "factor";
  const { metrics } = detail;
  const runApi = useApiData(
    () => (detail.factor_run_id ? api.factorRun(detail.factor_run_id) : Promise.resolve(null)),
    [detail.factor_run_id],
  );
  const algorithm = typeof runApi.data?.manifest?.algorithm === "string" ? String(runApi.data.manifest.algorithm) : "未记录";
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="result-hero">
        <Flex justify="space-between" align="start" gap={16}>
          <div>
            <Space wrap>
              <Tag color="green">真实结果</Tag>
              <Tag color="blue">{resultTypeLabel(detail.result_type)}</Tag>
              <Tag>{poolText}</Tag>
              {detail.backtest_id && <Tag color="purple">{isFactor ? "批次" : "任务"} {detail.backtest_id}</Tag>}
              {detail.factor_run_id && <Tag>运行 {detail.factor_run_id}</Tag>}
              {sourceText && <Tag color={isCompanySource(detail.data_source) ? "cyan" : "default"}>{sourceText}</Tag>}
              <Text type="secondary">{detail.created_at?.replace("T", " ") ?? ""}</Text>
            </Space>
            <Title level={3}>{detail.run_name}</Title>
            <Text code>{expression ?? "—"}</Text>
          </div>
          <Space wrap>
            <ResultSourceSelect value={detail.run_key} onChange={onSelect} results={results} />
            <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
          </Space>
        </Flex>
        <Divider />
        <Descriptions size="small" column={4} items={[
          { key: "pool", label: "股票池", children: poolText },
          { key: "range", label: "回测区间", children: rangeText },
          { key: "topk", label: "持仓", children: topkText },
          { key: "capital", label: "初始资金", children: capitalText },
          { key: "commission", label: "佣金（双向）", children: formatPercentValue(backtest.commission) },
          { key: "transfer", label: "过户费（双向）", children: formatPercentValue(backtest.transfer_fee, 3) },
          { key: "stamp", label: "印花税（卖出）", children: formatPercentValue(backtest.stamp_duty) },
          { key: "slippage", label: "滑点", children: formatPercentValue(backtest.slippage) },
          { key: "weight", label: "单票权重上限", children: formatPercentValue(backtest.max_weight_per_stock) },
        ]} />
      </Card>
      <Row gutter={12}>
        <Col span={4}><RealMetric title="年化收益" value={metrics.annual} tone="green" /></Col>
        <Col span={4}><RealMetric title="夏普比率" value={metrics.sharpe} suffix="" tone="blue" /></Col>
        <Col span={4}><RealMetric title="最大回撤" value={metrics.drawdown} tone="red" /></Col>
        <Col span={4}><RealMetric title="换手率" value={metrics.turnover} tone="violet" /></Col>
        <Col span={4}><RealMetric title="交易成本" value={metrics.cost} tone="orange" /></Col>
        <Col span={4}><RealMetric title="胜率" value={metrics.winRate} tone="cyan" /></Col>
      </Row>
      <Row gutter={16}>
        <Col span={15}><Card title="策略净值与回撤" className="data-card"
          extra={detail.equity.at(-1)?.excess_return_pp != null && <Tooltip title="策略累计收益减去同池等权累计收益，以百分点表示。"><Text tabIndex={0}>累计收益差 {detail.equity.at(-1)?.excess_return_pp?.toFixed(2)} 个百分点</Text></Tooltip>}>{detail.equity.length > 0 ? <EquityChart data={detail.equity} /> : <Empty description="无每日净值数据" />}
          <RandomTopKComparison summary={detail.summary} />
        </Card></Col>
        <Col span={9}><Card title="年度收益" extra={<Text type="secondary">红涨绿跌</Text>} className="data-card">{detail.yearly.length > 0 ? <YearlyChart data={detail.yearly} /> : <Empty description="无年度指标" />}</Card></Col>
      </Row>
      <Card title="年度指标" className="data-card"><Table rowKey="year" size="middle" pagination={false} scroll={{ x: 1050 }} columns={yearlyColumns} dataSource={detail.yearly} /></Card>
      <SingleResultAnalysisCard detail={detail} algorithm={algorithm} />
      <Row gutter={16}>
        <Col span={14}><ResearchNote runKey={detail.run_key} /></Col>
        <Col span={10}>
          <Card title="结果文件" extra={<Text type="secondary">{detail.files.length} 个文件 · 后端真实产物</Text>}>
            <Space wrap>
              {detail.files.map((file) => (
                <Button key={file.name} icon={<CloudDownloadOutlined />} onClick={() => { window.location.href = resultFileUrl(detail.run_key, file.name); }}>
                  {file.name}<Text type="secondary" style={{ marginLeft: 6 }}>{(file.size / 1024).toFixed(1)} KB</Text>
                </Button>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function SingleResultView({ navigate, initialRunKey }: { navigate: (p: Page, id?: number, runKey?: string) => void; initialRunKey?: string }) {
  const resultsApi = useApiData(api.results);
  const [selectedKey, setSelectedKey] = useState<string | null>(initialRunKey ?? null);
  // 从手动回测/因子批次带 run_key 进入时直接打开；普通导航回到最新真实结果
  useEffect(() => { setSelectedKey(initialRunKey ?? null); }, [initialRunKey]);

  const results = [...(resultsApi.data?.results ?? [])].sort(
    (a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")),
  );
  const detailKey = selectedKey ?? results[0]?.run_key ?? null;
  const detailApi = useApiData(
    () => (detailKey ? api.result(detailKey) : Promise.resolve(null)),
    [detailKey],
  );

  if (!detailKey) {
    if (resultsApi.loading) return <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>;
    if (resultsApi.error) {
      return (
        <Card>
          <Result
            status="warning" title="结果列表加载失败" subTitle={resultsApi.error}
            extra={<Button type="primary" onClick={resultsApi.reload}>重试</Button>}
          />
        </Card>
      );
    }
    return (
      <Card>
        <Empty description="还没有真实回测结果">
          <Space>
            <Button type="primary" onClick={() => navigate("backtest")}>去手动回测</Button>
            <Button onClick={() => navigate("factor_backtest")}>因子回测</Button>
          </Space>
        </Empty>
      </Card>
    );
  }
  if (detailApi.error) {
    return (
      <Card>
        <Result
          status="warning" title="真实结果加载失败" subTitle={detailApi.error}
          extra={<Space><Button onClick={() => navigate("backtest")}>去手动回测</Button><Button type="primary" onClick={detailApi.reload}>重试</Button></Space>}
        />
      </Card>
    );
  }
  if (detailApi.data && detailApi.data.run_key === detailKey) {
    return (
      <RealResultView
        detail={detailApi.data}
        results={results}
        onSelect={setSelectedKey}
        onRefresh={() => { detailApi.reload(); resultsApi.reload(); }}
      />
    );
  }
  return <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>;
}

function BatchResultView({ navigate, initialBatchId }: { navigate: (p: Page, id?: number, runKey?: string) => void; initialBatchId?: string }) {
  const runsApi = useApiData(api.factorRuns);
  const [entries, setEntries] = useState<{ runId: string; batch: FactorBacktestBatch }[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(true);
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>(initialBatchId);

  useEffect(() => {
    let alive = true;
    const runs = runsApi.data?.runs ?? [];
    if (!runs.length) {
      setEntries([]);
      setLoadingBatches(Boolean(runsApi.loading));
      return () => { alive = false; };
    }
    setLoadingBatches(true);
    Promise.all(runs.map(async (run) => {
      try {
        const data = await api.factorBacktests(run.run_id);
        return (data.batches ?? []).map((batch) => ({ runId: run.run_id, batch }));
      } catch {
        return [];
      }
    })).then((groups) => {
      if (!alive) return;
      const flat = groups.flat().sort((a, b) => String(b.batch.created_at ?? "").localeCompare(String(a.batch.created_at ?? "")));
      setEntries(flat);
      setLoadingBatches(false);
      setSelectedBatchId((current) => (current && flat.some((entry) => entry.batch.backtest_id === current) ? current : flat[0]?.batch.backtest_id));
    });
    return () => { alive = false; };
  }, [runsApi.data, runsApi.loading]);

  useEffect(() => {
    if (initialBatchId) setSelectedBatchId(initialBatchId);
  }, [initialBatchId]);

  const selected = entries.find((entry) => entry.batch.backtest_id === selectedBatchId) ?? entries[0] ?? null;
  const batchApi = useApiData(
    () => (selected ? api.factorBacktest(selected.runId, selected.batch.backtest_id) : Promise.resolve(null)),
    [selected?.runId, selected?.batch.backtest_id],
  );
  const runDetailApi = useApiData(
    () => (selected ? api.factorRun(selected.runId) : Promise.resolve(null)),
    [selected?.runId],
  );
  const algorithm = typeof runDetailApi.data?.manifest?.algorithm === "string"
    ? String(runDetailApi.data.manifest.algorithm)
    : "未记录";
  const detail = selected && batchApi.data?.batch.backtest_id === selected.batch.backtest_id ? batchApi.data : null;
  const batch = detail?.batch ?? selected?.batch ?? null;

  if (runsApi.loading || loadingBatches) {
    return <Card><Skeleton active paragraph={{ rows: 10 }} /></Card>;
  }
  if (runsApi.error) {
    return (
      <Card>
        <Result status="warning" title="因子运行加载失败" subTitle={runsApi.error}
          extra={<Button onClick={runsApi.reload}>重试</Button>} />
      </Card>
    );
  }
  if (!entries.length) {
    return (
      <Card>
        <Empty description="还没有批次回测记录">
          <Button type="primary" onClick={() => navigate("factor_backtest")}>去因子回测</Button>
        </Empty>
      </Card>
    );
  }
  return (
    <Card
      title={<Space><ExperimentOutlined />批次回测结果</Space>}
      className="data-card"
      extra={<Space wrap>
        <Select
          size="small"
          value={selected?.batch.backtest_id}
          onChange={(value) => setSelectedBatchId(value)}
          options={entries.map((entry) => ({
            value: entry.batch.backtest_id,
            label: `${entry.batch.backtest_id} · ${entry.runId} · 成功 ${entry.batch.completed ?? "—"}/${entry.batch.selected_count ?? "—"}`,
          }))}
          style={{ minWidth: 380 }}
        />
        <Button size="small" icon={<ReloadOutlined />} onClick={runsApi.reload}>刷新</Button>
      </Space>}
    >
      {batchApi.error && <Alert style={{ marginBottom: 12 }} type="error" showIcon message="批次详情加载失败" description={batchApi.error} />}
      {selected && batch && (
        <BacktestBatchPanel
          runId={selected.runId}
          batch={batch}
          rows={detail?.rows ?? []}
          failures={detail?.failures ?? []}
          algorithm={algorithm}
          onOpenResult={(runKey) => navigate("result", undefined, runKey)}
        />
      )}
    </Card>
  );
}

export function ResultPage({ navigate, initialRunKey }: { navigate: (p: Page, id?: number, runKey?: string) => void; initialRunKey?: string }) {
  const batchRequested = initialRunKey?.startsWith("batch:") ?? false;
  const [view, setView] = useState<"single" | "batch">(batchRequested ? "batch" : "single");
  useEffect(() => {
    if (initialRunKey?.startsWith("batch:")) setView("batch");
    else if (initialRunKey) setView("single");
  }, [initialRunKey]);
  const initialBatchId = initialRunKey?.startsWith("batch:") ? initialRunKey.slice("batch:".length) : undefined;
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card" size="small">
        <Segmented
          value={view}
          onChange={(value) => setView(value as "single" | "batch")}
          options={[{ label: "单次结果", value: "single" }, { label: "批次回测", value: "batch" }]}
        />
      </Card>
      {view === "single"
        ? <SingleResultView navigate={navigate} initialRunKey={initialRunKey} />
        : <BatchResultView navigate={navigate} initialBatchId={initialBatchId} />}
    </Space>
  );
}
