import { useEffect, useState } from "react";
import {
  Alert, Button, Card, Descriptions, Skeleton, Space, Table, Tag, Tooltip, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { CloudDownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  factorBacktestFileUrl,
  type FactorBacktestBatch,
  type FactorBacktestFailure,
  type FactorBacktestRow,
  type ResultDetail,
} from "./api/client";
import { CATEGORY_META, FACTOR_CATEGORIES, classifyFactor, type FactorCategoryKey } from "./factorCategories";

const { Text } = Typography;

/* ---------- 数值 ---------- */

const metricNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
};

const formatFraction = (value: unknown, digits = 2): string => {
  const number = metricNumber(value);
  return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
};

/* ---------- 判定 ---------- */

export type BacktestVerdict = "usable" | "watch" | "unusable";

type FactorVerdict = {
  factor_id: string;
  expression: string;
  category: FactorCategoryKey;
  annual: number | null;
  sharpe: number | null;
  drawdown: number | null;
  verdict: BacktestVerdict;
  reasons: string[];
};

type BacktestAnalysis = {
  pool: string;
  algorithm: string;
  period: string;
  topK: number | null;
  counts: { total: number; completed: number; failed: number };
  categoryCounts: { label: string; count: number }[];
  factors: FactorVerdict[];
  usable: number;
  watch: number;
  unusable: number;
  avgTurnover: number | null;
  avgCost: number | null;
  avgWinRate: number | null;
  sharpeMin: number | null;
  sharpeMax: number | null;
  summary: string[];
  verdictText: string;
  suggestion: string;
  limitations: string[];
};

const VERDICT_META: Record<BacktestVerdict, { label: string; color: string }> = {
  usable: { label: "可用", color: "green" },
  watch: { label: "观察", color: "orange" },
  unusable: { label: "不可用", color: "red" },
};

const VERDICT_ORDER: Record<BacktestVerdict, number> = { usable: 0, watch: 1, unusable: 2 };

export function judgeBacktestRow(row: FactorBacktestRow): FactorVerdict {
  const annual = metricNumber(row.backtest_annual_return);
  const sharpe = metricNumber(row.backtest_sharpe);
  const drawdown = metricNumber(row.backtest_max_drawdown);
  const turnover = metricNumber(row.backtest_average_turnover);
  const expression = String(row.expression ?? row.canonical_expression ?? "");
  const reasons: string[] = [];
  if (annual == null) reasons.push("缺少年化收益");
  else if (annual < 0.05) reasons.push(`年化 ${(annual * 100).toFixed(1)}% < 5%`);
  if (sharpe == null) reasons.push("缺少 Sharpe");
  else if (sharpe < 0.8) reasons.push(`Sharpe ${sharpe.toFixed(2)} < 0.8`);
  if (drawdown == null) reasons.push("缺少最大回撤");
  else if (drawdown < -0.35) reasons.push(`最大回撤 ${(drawdown * 100).toFixed(1)}% 超过 -35%`);
  if (turnover == null) reasons.push("缺少换手率");
  else if (turnover > 0.05) reasons.push(`日均换手 ${(turnover * 100).toFixed(1)}% > 5%`);
  const usable = reasons.length === 0;
  const watch = annual != null && sharpe != null && annual > 0 && sharpe >= 0.3;
  const verdict: BacktestVerdict = usable ? "usable" : watch ? "watch" : "unusable";
  return {
    factor_id: String(row.factor_id ?? "—"),
    expression,
    category: classifyFactor(expression),
    annual,
    sharpe,
    drawdown,
    verdict,
    reasons: usable ? [] : verdict === "watch" ? [`未达到可用门槛：${reasons.join("；")}`] : reasons,
  };
}

const meanOf = (values: (number | null)[]): number | null => {
  const numbers = values.filter((value): value is number => value != null);
  return numbers.length ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length : null;
};

const pct = (value: number | null, digits = 1) => (value == null ? "—" : `${(value * 100).toFixed(digits)}%`);
const num = (value: number | null, digits = 2) => (value == null ? "—" : value.toFixed(digits));

function singleNarrative(detail: ResultDetail, verdict: FactorVerdict): string[] {
  const annual = metricNumber(detail.summary.annual_return);
  const sharpe = metricNumber(detail.summary.sharpe);
  const drawdown = metricNumber(detail.summary.max_drawdown);
  const calmar = metricNumber(detail.summary.calmar);
  const winRate = metricNumber(detail.summary.win_rate);
  const turnover = metricNumber(detail.summary.average_turnover);
  const annualCost = metricNumber(detail.summary.annual_cost);
  const totalCost = metricNumber(detail.summary.total_cost);
  const trades = metricNumber(detail.summary.number_of_trades);
  const holding = metricNumber(detail.summary.average_holding_count);
  const category = classifyFactor(detail.canonical_expression ?? "");
  const paragraphs: string[] = [];

  let first = "";
  if (annual == null) first += "缺少年化收益数据，无法判断收益能力。";
  else if (annual < 0) first += `年化 ${pct(annual)}，因子整体在亏钱，收益端不成立。`;
  else if (annual < 0.05) first += `年化 ${pct(annual)}，低于 5% 的可接受线，收益偏弱。`;
  else if (annual < 0.15) first += `年化 ${pct(annual)}，收益中等。`;
  else first += `年化 ${pct(annual)}，收益水平较高。`;
  if (sharpe != null) {
    if (sharpe < 0.5) first += `Sharpe 仅 ${num(sharpe)}，说明这份收益主要是靠承担波动换来的。`;
    else if (sharpe < 1) first += `Sharpe ${num(sharpe)} 一般，收益的稳定性还不够。`;
    else first += `Sharpe ${num(sharpe)} 较好，风险调整后的收益有竞争力。`;
  }
  if (drawdown != null) {
    const severity = drawdown <= -0.35 ? "回撤很深，持有体验会很差" : drawdown <= -0.2 ? "回撤偏大，需要较强的风险承受能力" : drawdown <= -0.1 ? "回撤在可控范围" : "回撤很小";
    first += `最大回撤 ${pct(drawdown)}，${severity}`;
    if (calmar != null && annual != null) first += `；Calmar ${num(calmar)} ${calmar >= 0.5 ? "说明单位回撤换来的收益尚可" : "说明单位回撤换来的收益偏低"}`;
    first += "。";
  }
  paragraphs.push(first);

  let second = "";
  if (turnover != null) {
    second += turnover > 0.05 ? `日均换手 ${pct(turnover)}，交易非常频繁` : turnover > 0.03 ? `日均换手 ${pct(turnover)}，偏高` : turnover > 0.01 ? `日均换手 ${pct(turnover)}，处于中等水平` : `日均换手 ${pct(turnover)}，较低`;
    second += "。";
  }
  if (annualCost != null && annual != null && annual > 0) {
    const ratio = annualCost / annual;
    second += `年化成本约 ${pct(annualCost)}，相当于年化收益的 ${(ratio * 100).toFixed(0)}%，${ratio > 0.3 ? "成本侵蚀明显，实盘净收益会进一步打折" : "成本影响可控"}。`;
  } else if (totalCost != null) {
    second += `累计成本 ${pct(totalCost)}。`;
  }
  if (winRate != null) {
    second += winRate < 0.45 ? `胜率只有 ${pct(winRate)}，收益依赖少数几次大赢家，稳定性偏弱。` : winRate > 0.55 ? `胜率 ${pct(winRate)}，盈利的持续性较好。` : `胜率 ${pct(winRate)}，处于正常区间。`;
  }
  if (trades != null && holding != null) {
    second += `${trades.toFixed(0)} 次交易、平均持仓 ${holding.toFixed(0)} 只，属于${turnover != null && turnover > 0.03 ? "较高" : "中等"}频率的 TopK 组合。`;
  }
  if (category === "volume_price") second += "作为量价类因子，换手和成本是主要约束，需要确认策略容量。";
  else if (category === "trend") second += "趋势类因子在震荡市容易失效，需要关注市场状态切换。";
  else if (category === "cross_section") second += "横截面类因子依赖股票间的相对排序，需要关注风格暴露。";
  paragraphs.push(second);

  if (verdict.verdict === "usable") {
    paragraphs.push("综合收益、风险与成本，该因子达到可用门槛，具备进入组合候选的基础；入组前仍需做相关性和样本外复核。");
  } else if (verdict.verdict === "watch") {
    paragraphs.push(`综合看，该因子尚未达到可用门槛（${verdict.reasons.join("；")}），更适合继续观察而不是直接入组。`);
  } else {
    paragraphs.push(`综合看，该因子不建议用于组合（${verdict.reasons.join("；")}）。`);
  }
  return paragraphs.filter(Boolean);
}

function batchNarrative(analysis: BacktestAnalysis): string[] {
  const { factors, usable, watch, avgTurnover, avgCost, avgWinRate, sharpeMin, sharpeMax, categoryCounts } = analysis;
  if (!factors.length) return ["本批次没有可分析的成功回测结果。"];
  const avgAnnual = meanOf(factors.map((factor) => factor.annual));
  const avgSharpe = meanOf(factors.map((factor) => factor.sharpe));
  const avgDrawdown = meanOf(factors.map((factor) => factor.drawdown));
  const usableRatio = usable / factors.length;
  const paragraphs: string[] = [];
  paragraphs.push(
    `本批次 ${factors.length} 个因子中，${usable} 个达到可用门槛（${pct(usableRatio, 0)}），整体${usableRatio >= 0.5 ? "质量尚可" : usableRatio > 0 ? "只有少数可用" : "质量不理想"}。` +
    `平均年化 ${pct(avgAnnual)}、平均 Sharpe ${num(avgSharpe)}、平均最大回撤 ${pct(avgDrawdown)}，${(avgSharpe ?? 0) >= 0.8 ? "风险调整后的收益整体不错" : "整体收益质量一般"}。`
  );
  const best = [...factors].sort((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity))[0];
  if (best) {
    paragraphs.push(
      `表现最好的是 ${best.factor_id}：年化 ${pct(best.annual)}、Sharpe ${num(best.sharpe)}、最大回撤 ${pct(best.drawdown)}；` +
      `${(best.sharpe ?? 0) >= 1 ? "收益与风险比较均衡" : "虽然可能是收益最高的一只，但风险调整后表现仍有短板"}。`
    );
  }
  if (sharpeMin != null && sharpeMax != null) {
    paragraphs.push(
      `因子之间 Sharpe 从 ${num(sharpeMin)} 到 ${num(sharpeMax)}，${sharpeMax - sharpeMin > 0.5 ? "差异较大，说明表现对表达式细节很敏感" : "差异不大，整体水平接近"}；` +
      `平均日均换手 ${pct(avgTurnover)}、平均成本 ${pct(avgCost)}、平均胜率 ${pct(avgWinRate)}，${(avgTurnover ?? 0) > 0.03 ? "换手偏高，成本会明显侵蚀收益" : "换手和成本在可接受范围"}。`
    );
  }
  if (categoryCounts.length) {
    const top = [...categoryCounts].sort((a, b) => b.count - a.count)[0];
    paragraphs.push(
      `类别上以${top.label}为主（${top.count}/${factors.length}），${top.count / factors.length > 0.6 ? "多样性不足，组合时相关性风险较高" : "类别有一定分散"}。`
    );
  }
  paragraphs.push(
    usable > 0
      ? `综合看，本批次有 ${usable} 个因子具备进入组合候选的基础；建议优先挑 Sharpe 和回撤都过线的因子，而不是只看年化最高。`
      : watch > 0 ? `综合看，本批次暂无可用因子，${watch} 个可继续观察；直接入组的意义不大。`
        : "综合看，本批次没有值得进入组合的因子。"
  );
  return paragraphs;
}

export function buildBacktestAnalysis(
  batch: FactorBacktestBatch,
  rows: FactorBacktestRow[],
  failures: number,
  algorithm: string,
): BacktestAnalysis {
  const factors = rows
    .map(judgeBacktestRow)
    .sort((a, b) => VERDICT_ORDER[a.verdict] - VERDICT_ORDER[b.verdict] || (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));
  const categoryMap = new Map<FactorCategoryKey, number>();
  for (const factor of factors) categoryMap.set(factor.category, (categoryMap.get(factor.category) ?? 0) + 1);
  const categoryCounts = FACTOR_CATEGORIES
    .filter((item) => categoryMap.get(item.key))
    .map((item) => ({ label: item.label, count: categoryMap.get(item.key) as number }));
  const usable = factors.filter((factor) => factor.verdict === "usable").length;
  const watch = factors.filter((factor) => factor.verdict === "watch").length;
  const unusable = factors.filter((factor) => factor.verdict === "unusable").length;
  const avgTurnover = meanOf(rows.map((row) => metricNumber(row.backtest_average_turnover)));
  const avgCost = meanOf(rows.map((row) => metricNumber(row.backtest_total_cost)));
  const avgWinRate = meanOf(rows.map((row) => metricNumber(row.backtest_win_rate)));
  const sharpeValues = factors.map((factor) => factor.sharpe).filter((value): value is number => value != null);
  const sharpeMin = sharpeValues.length ? Math.min(...sharpeValues) : null;
  const sharpeMax = sharpeValues.length ? Math.max(...sharpeValues) : null;
  const verdictText = usable > 0
    ? `本批次有 ${usable} 个可用因子，可作为组合候选。`
    : watch > 0 ? `本批次暂无可用因子，${watch} 个因子建议继续观察。` : "本批次没有可用因子。";
  const suggestion = usable > 0
    ? "建议将可用因子纳入组合候选；入组前先做相关性去重、换股票池和样本外复核。"
    : watch > 0 ? "暂不建议直接进入组合，可延长样本区间或换股票池复核后再决定。"
      : "不建议用于组合，建议调整表达式或更换股票池重新生成。";
  const limitations = [
    algorithm === "未记录" ? "生成算法未记录，无法回溯生成参数。" : `生成算法：${algorithm}。`,
    "分析为前端规则模拟（LLM 未接入）。",
    "回测为单一路径，未做滚动样本外与参数敏感性检验。",
  ];
  if (failures > 0) limitations.push(`${failures} 个因子回测异常，未纳入分析。`);
  const analysis: BacktestAnalysis = {
    pool: batch.pool_id ?? "—",
    algorithm,
    period: `${batch.start_date ?? "—"} ~ ${batch.end_date ?? "—"}`,
    topK: batch.top_k,
    counts: { total: rows.length, completed: factors.length, failed: failures },
    categoryCounts,
    factors,
    usable,
    watch,
    unusable,
    avgTurnover,
    avgCost,
    avgWinRate,
    sharpeMin,
    sharpeMax,
    summary: [],
    verdictText,
    suggestion,
    limitations,
  };
  analysis.summary = batchNarrative(analysis);
  return analysis;
}

/* ---------- 组件 ---------- */

const analysisColumns: TableColumnsType<FactorVerdict> = [
  { title: "因子 ID", dataIndex: "factor_id", width: 200, render: (v) => <Text code style={{ whiteSpace: "nowrap" }}>{v}</Text> },
  { title: "表达式", dataIndex: "expression", ellipsis: true, render: (v) => <Text code>{v}</Text> },
  {
    title: "类别",
    dataIndex: "category",
    width: 100,
    render: (key: FactorCategoryKey) => {
      const meta = CATEGORY_META[key];
      return <Tag color={meta.color}>{meta.label}</Tag>;
    },
  },
  { title: "年化", dataIndex: "annual", width: 90, align: "right", render: (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`) },
  { title: "Sharpe", dataIndex: "sharpe", width: 90, align: "right", render: (v: number | null) => (v == null ? "—" : v.toFixed(2)) },
  { title: "最大回撤", dataIndex: "drawdown", width: 100, align: "right", render: (v: number | null) => (v == null ? "—" : <Text type="danger">{(v * 100).toFixed(1)}%</Text>) },
  {
    title: "判定",
    dataIndex: "verdict",
    width: 100,
    render: (value: BacktestVerdict, record) => (
      <Tooltip title={record.reasons.join("；")}>
        <Tag color={VERDICT_META[value].color}>{VERDICT_META[value].label}</Tag>
      </Tooltip>
    ),
  },
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
];

export function BacktestAnalysisCard({ batch, rows, failures, algorithm }: {
  batch: FactorBacktestBatch;
  rows: FactorBacktestRow[];
  failures: number;
  algorithm: string;
}) {
  const [analysis, setAnalysis] = useState<BacktestAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const batchId = batch.backtest_id;

  useEffect(() => {
    if (!batch.completed) {
      setAnalysis(null);
      setLoading(false);
      return;
    }
    setAnalysis(null);
    setLoading(true);
    const timer = window.setTimeout(() => {
      setAnalysis(buildBacktestAnalysis(batch, rows, failures, algorithm));
      setLoading(false);
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [batchId, batch.completed, rows, failures, algorithm, tick]);

  if (!batch.completed) {
    return (
      <Card size="small" title="大模型分析总结（演示）">
        <Text type="secondary">本批次没有成功的回测结果，暂不分析。</Text>
      </Card>
    );
  }
  if (loading || !analysis) {
    return (
      <Card size="small" title="大模型分析总结（演示）">
        <Skeleton active paragraph={{ rows: 5 }} />
      </Card>
    );
  }
  return (
    <Card
      size="small"
      title="大模型分析总结（演示）"
      extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => setTick((value) => value + 1)}>重新分析</Button>}
    >
      <Space direction="vertical" size={12} className="full-width">
        <Descriptions size="small" column={3} bordered items={[
          { key: "pool", label: "股票池", children: analysis.pool },
          { key: "algorithm", label: "生成算法", children: analysis.algorithm },
          { key: "period", label: "回测区间", children: analysis.period },
          { key: "topk", label: "TopK", children: analysis.topK ?? "—" },
          { key: "counts", label: "因子数", children: `${analysis.counts.total}（成功 ${analysis.counts.completed} / 异常 ${analysis.counts.failed}）` },
          { key: "categories", label: "分类分布", children: analysis.categoryCounts.length ? analysis.categoryCounts.map((item) => `${item.label} ${item.count}`).join(" · ") : "—" },
        ]} />
        <div>
          <Text strong>专家解读</Text>
          <Space direction="vertical" size={6} style={{ marginTop: 6 }}>
            {analysis.summary.map((line) => <Text key={line}>{line}</Text>)}
          </Space>
        </div>
        <Alert
          type={analysis.usable > 0 ? "success" : analysis.watch > 0 ? "warning" : "error"}
          showIcon message={analysis.verdictText} description={analysis.suggestion}
        />
        <Table rowKey="factor_id" size="small" pagination={false} columns={analysisColumns} dataSource={analysis.factors} scroll={{ x: 900 }} />
        <div>
          <Text strong>局限说明</Text>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {analysis.limitations.map((line) => <li key={line}><Text type="secondary">{line}</Text></li>)}
          </ul>
        </div>
      </Space>
    </Card>
  );
}

export function BacktestBatchPanel({
  runId, batch, rows, failures, algorithm, onOpenResult,
}: {
  runId: string;
  batch: FactorBacktestBatch;
  rows: FactorBacktestRow[];
  failures: FactorBacktestFailure[];
  algorithm: string;
  onOpenResult?: (runKey: string) => void;
}) {
  return (
    <Space direction="vertical" size={12} className="full-width">
      <Space wrap size={6}>
        <Tag color="blue">批次 {batch.backtest_id}</Tag>
        <Tag>区间 {batch.start_date ?? "—"} ~ {batch.end_date ?? "—"}</Tag>
        <Tag>TopK {batch.top_k ?? "—"}</Tag>
        <Tag>合格 {batch.accepted_count ?? "—"}</Tag>
        <Tag>本次 {batch.selected_count ?? "—"}</Tag>
        <Tag color="success">成功 {batch.completed ?? "—"}</Tag>
        {!!batch.failed && <Tag color="error">异常 {batch.failed}</Tag>}
      </Space>
      <Space wrap size={8}>
        <Button size="small" icon={<CloudDownloadOutlined />} disabled={!batch.completed} onClick={() => { window.location.href = factorBacktestFileUrl(runId, batch.backtest_id, "factor_backtest_summary.csv"); }}>下载汇总</Button>
        <Button size="small" icon={<CloudDownloadOutlined />} disabled={!batch.failed} onClick={() => { window.location.href = factorBacktestFileUrl(runId, batch.backtest_id, "factor_backtest_failures.csv"); }}>下载异常明细</Button>
      </Space>
      <Table
        rowKey={(row) => String(row.factor_id ?? row.run_key ?? row.expression)}
        size="small" columns={[
          ...batchColumns,
          ...(onOpenResult ? [{
            title: "操作", key: "action", width: 76, align: "right" as const,
            render: (_: unknown, row: FactorBacktestRow) => (
              <Button type="link" size="small" disabled={!row.run_key} onClick={() => onOpenResult(String(row.run_key))}>结果</Button>
            ),
          }] : []),
        ]}
        dataSource={rows} pagination={false} scroll={{ x: 1020 }}
      />
      <BacktestAnalysisCard batch={batch} rows={rows} failures={batch.failed ?? failures.length} algorithm={algorithm} />
      {failures.length > 0 && (
        <Alert
          type="warning" showIcon message={`${failures.length} 个因子回测异常`}
          description={<Space direction="vertical" size={2}>
            {failures.slice(0, 6).map((item) => (
              <Text key={`${item.factor_id}-${item.expression ?? ""}`}>
                {item.factor_id} · {item.expression ?? "—"}：{item.error ?? "未知错误"}
              </Text>
            ))}
            {failures.length > 6 && <Text type="secondary">仅显示前 6 条，完整明细请下载异常 CSV。</Text>}
          </Space>}
        />
      )}
    </Space>
  );
}

export function SingleResultAnalysisCard({ detail, algorithm }: { detail: ResultDetail; algorithm: string }) {
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setLoading(true);
    const timer = window.setTimeout(() => setLoading(false), 2500);
    return () => window.clearTimeout(timer);
  }, [detail.run_key, tick]);

  const expression = detail.canonical_expression ?? "";
  const category = CATEGORY_META[classifyFactor(expression)];
  const verdict = judgeBacktestRow({
    factor_id: detail.run_name,
    expression,
    backtest_annual_return: detail.summary.annual_return,
    backtest_sharpe: detail.summary.sharpe,
    backtest_max_drawdown: detail.summary.max_drawdown,
    backtest_average_turnover: detail.summary.average_turnover,
  });
  const config = (detail.config.backtest as Record<string, unknown> | undefined) ?? detail.config;
  const start = String(config.start_date ?? "—");
  const end = String(config.end_date ?? "—");
  const topK = config.top_k;
  const verdictText = verdict.verdict === "usable"
    ? "该因子达到可用门槛，可作为组合候选。"
    : verdict.verdict === "watch" ? "该因子未达到可用门槛，建议继续观察。" : "该因子不建议用于组合。";
  const suggestion = verdict.verdict === "usable"
    ? "入组前先做相关性去重、换股票池和样本外复核。"
    : verdict.verdict === "watch"
      ? `未达标项：${verdict.reasons.join("；")}。可延长样本或换股票池复核。`
      : `原因：${verdict.reasons.join("；")}。建议调整表达式或重新生成。`;

  const header = (
    <Space><Text strong>大模型分析总结（演示）</Text></Space>
  );
  const rerun = <Button size="small" icon={<ReloadOutlined />} onClick={() => setTick((value) => value + 1)}>重新分析</Button>;

  return (
    <Card size="small" title={header} extra={rerun}>
      {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : (
        <Space direction="vertical" size={12} className="full-width">
          <Descriptions size="small" column={3} bordered items={[
            { key: "pool", label: "股票池", children: detail.pool_id ?? "—" },
            { key: "algorithm", label: "生成算法", children: algorithm },
            { key: "period", label: "回测区间", children: `${start} ~ ${end}` },
            { key: "topk", label: "TopK", children: topK != null ? String(topK) : "—" },
            { key: "category", label: "因子类别", children: <Tag color={category.color}>{category.label}</Tag> },
            { key: "expression", label: "表达式", children: <Text code>{expression || "—"}</Text> },
          ]} />
          <div>
            <Text strong>专家解读</Text>
            <Space direction="vertical" size={6} style={{ marginTop: 6 }}>
              {singleNarrative(detail, verdict).map((line) => <Text key={line}>{line}</Text>)}
            </Space>
          </div>
          <Alert
            type={verdict.verdict === "usable" ? "success" : verdict.verdict === "watch" ? "warning" : "error"}
            showIcon message={verdictText} description={suggestion}
          />
          <div>
            <Text strong>局限说明</Text>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              <li><Text type="secondary">{algorithm === "未记录" ? "生成算法未记录，无法回溯生成参数。" : `生成算法：${algorithm}。`}</Text></li>
              <li><Text type="secondary">分析为前端规则模拟（LLM 未接入）。</Text></li>
              <li><Text type="secondary">回测为单一路径，未做滚动样本外与参数敏感性检验。</Text></li>
            </ul>
          </div>
        </Space>
      )}
    </Card>
  );
}
