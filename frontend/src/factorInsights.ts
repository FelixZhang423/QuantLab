/**
 * 因子归类与回测小结的纯前端规则。
 *
 * 后端 accepted_factors / 批次 CSV 没有 category 字段，这里按表达式里
 * 实际使用的字段与算子做一层可解释的归类，仅用于页面筛选与阅读，
 * 不改变任何回测结果或后端数据。
 */
import type {
  AcceptedFactor,
  FactorBacktestFailure,
  FactorBacktestRow,
  FactorRunDetail,
  OperatorInfo,
} from "./api/client";

/* ---------- 因子类别（语义归类） ---------- */

export type FactorCategoryKey =
  | "volume_price"
  | "volatility"
  | "trend"
  | "cross_section"
  | "conditional"
  | "arithmetic"
  | "other";

export type FactorCategoryMeta = {
  key: FactorCategoryKey;
  label: string;
  /** Ant Design Tag color */
  color: string;
  /** 进度条等使用的十六进制色 */
  stroke: string;
  description: string;
};

export const FACTOR_CATEGORIES: readonly FactorCategoryMeta[] = [
  {
    key: "volume_price",
    label: "量价",
    color: "gold",
    stroke: "#faad14",
    description: "表达式使用了成交量、成交额、换手率等量价字段",
  },
  {
    key: "volatility",
    label: "波动",
    color: "orange",
    stroke: "#fa541c",
    description: "表达式使用了波动率、相关性算子，或最高价/最低价区间",
  },
  {
    key: "trend",
    label: "趋势",
    color: "blue",
    stroke: "#1677ff",
    description: "表达式使用了均线、差分、延迟等趋势型时间序列算子",
  },
  {
    key: "cross_section",
    label: "横截面",
    color: "geekblue",
    stroke: "#2f54eb",
    description: "表达式使用了排名、标准化、缩放或分组算子",
  },
  {
    key: "conditional",
    label: "条件",
    color: "purple",
    stroke: "#722ed1",
    description: "表达式使用了 if_else、trade_when、比较或逻辑运算",
  },
  {
    key: "arithmetic",
    label: "算术",
    color: "default",
    stroke: "#8c8c8c",
    description: "以四则运算、对数、幂等算术组合为主",
  },
  {
    key: "other",
    label: "其他",
    color: "default",
    stroke: "#bfbfbf",
    description: "未识别出明确的主要类别",
  },
];

export const CATEGORY_ORDER: FactorCategoryKey[] = FACTOR_CATEGORIES.map((item) => item.key);
export const CATEGORY_META = Object.fromEntries(
  FACTOR_CATEGORIES.map((item) => [item.key, item]),
) as Record<FactorCategoryKey, FactorCategoryMeta>;
const FACTOR_CATEGORY_KEYS = new Set<FactorCategoryKey>(CATEGORY_ORDER);

export function isFactorCategory(value: unknown): value is FactorCategoryKey {
  return typeof value === "string" && FACTOR_CATEGORY_KEYS.has(value as FactorCategoryKey);
}

export function normalizeFactorCategory(value: unknown): FactorCategoryKey | "all" {
  return isFactorCategory(value) ? value : "all";
}

export type CategoryCount = Record<FactorCategoryKey, number>;

export function emptyCategoryCount(): CategoryCount {
  return CATEGORY_ORDER.reduce(
    (counts, key) => ({ ...counts, [key]: 0 }),
    {} as CategoryCount,
  );
}

export function countFactorCategories(
  views: readonly { category: FactorCategoryKey }[],
): CategoryCount {
  const counts = emptyCategoryCount();
  for (const view of views) counts[view.category] += 1;
  return counts;
}

/* ---------- 算子族（用于展示表达式的技术类型） ---------- */

export type OperatorFamilyKey =
  | "arithmetic"
  | "cross_section"
  | "group"
  | "logic"
  | "time_series"
  | "transformational"
  | "vector"
  | "custom"
  | "other";

export const OPERATOR_FAMILY_LABELS: Record<OperatorFamilyKey, string> = {
  arithmetic: "数学运算",
  cross_section: "横截面",
  group: "分组",
  logic: "逻辑判断",
  time_series: "时间序列",
  transformational: "信号转换",
  vector: "向量",
  custom: "自定义",
  other: "未识别",
};

const FAMILY_PRIORITY: OperatorFamilyKey[] = [
  "cross_section",
  "group",
  "logic",
  "time_series",
  "transformational",
  "vector",
  "arithmetic",
  "custom",
  "other",
];

function isOperatorFamily(value: unknown): value is OperatorFamilyKey {
  return typeof value === "string" && value in OPERATOR_FAMILY_LABELS;
}

/* ---------- 表达式识别 ---------- */

const VOLUME_FIELDS = new Set([
  "volume", "vol", "amount", "turnover", "turnoverrate", "changepct", "vwap",
]);
const PRICE_FIELDS = new Set(["open", "close", "high", "low", "ycp", "vwap"]);
const TECHNICAL_FIELDS = new Set([
  "ma4", "ma5", "ma8", "ma12", "ma16", "ma20", "ma47",
  "ema12", "ema26", "dif", "dea", "macd", "rsv",
  "kdj_k", "kdj_d", "kdj_j", "max_high_9", "min_low_9",
  "highestprice", "lowestprice",
]);
const FUNDAMENTAL_FIELDS = new Set([
  "pe_ttm", "pb", "total_mv", "float_mv", "revenue", "roe", "industry",
]);

const VOLATILITY_OPS = new Set([
  "ts_std", "ts_std_dev", "ts_var", "ts_mad", "ts_covariance", "ts_corr",
]);
const CROSS_SECTION_OPS = new Set([
  "rank", "zscore", "scale", "winsorize", "normalize", "quantile",
  "group_backfill", "group_mean", "group_neutralize", "group_rank", "group_scale", "group_zscore",
]);
const CONDITIONAL_OPS = new Set([
  "if_else", "where", "trade_when", "bucket", "and", "and_", "or", "or_", "not", "not_",
  "equal", "not_equal", "greater", "greater_equal", "less", "less_equal", "is_nan",
]);
const TREND_OPS = new Set([
  "delay", "delta", "ts_delay", "ts_delta", "ts_mean", "ts_sum", "ts_product",
  "ts_median", "ts_wma", "ts_ema", "ts_max", "ts_min", "ts_decay_linear",
  "ts_rank", "ts_zscore", "ts_scale", "ts_av_diff", "ts_arg_max", "ts_arg_min",
  "ts_backfill", "ts_count_nans", "ts_regression", "ts_step", "ts_quantile",
  "days_from_last_change", "last_diff_value", "kth_element", "hump",
]);
const ARITHMETIC_OPS = new Set([
  "abs", "add", "densify", "div", "divide", "inverse", "log", "max", "min",
  "mul", "multiply", "power", "reverse", "sign", "signed_power", "sqrt", "sub", "subtract",
]);
const VECTOR_OPS = new Set(["vec_avg", "vec_sum"]);

/** API 不可用时的兜底算子族映射 */
const FALLBACK_OPERATOR_FAMILIES: Record<string, OperatorFamilyKey> = {};
for (const name of ARITHMETIC_OPS) FALLBACK_OPERATOR_FAMILIES[name] = "arithmetic";
for (const name of CROSS_SECTION_OPS) {
  FALLBACK_OPERATOR_FAMILIES[name] = name.startsWith("group_") ? "group" : "cross_section";
}
for (const name of CONDITIONAL_OPS) FALLBACK_OPERATOR_FAMILIES[name] = "logic";
for (const name of TREND_OPS) FALLBACK_OPERATOR_FAMILIES[name] = "time_series";
for (const name of VOLATILITY_OPS) FALLBACK_OPERATOR_FAMILIES[name] = "time_series";
for (const name of VECTOR_OPS) FALLBACK_OPERATOR_FAMILIES[name] = "vector";

const CALL_PATTERN = /([A-Za-z_][A-Za-z0-9_]*)\s*\(/g;
const IDENTIFIER_PATTERN = /[A-Za-z_][A-Za-z0-9_]*/g;

export function expressionCalls(expression: string): string[] {
  const calls = new Set<string>();
  for (const match of expression.matchAll(CALL_PATTERN)) {
    calls.add(match[1].toLowerCase());
  }
  return [...calls];
}

export function expressionFields(expression: string): string[] {
  const fields = new Set<string>();
  for (const match of expression.matchAll(IDENTIFIER_PATTERN)) {
    const end = (match.index ?? 0) + match[0].length;
    if (expression.slice(end).trimStart().startsWith("(")) continue;
    const name = match[0].toLowerCase();
    if (name === "true" || name === "false" || name === "nan") continue;
    fields.add(name);
  }
  return [...fields];
}

function fieldTags(fields: readonly string[]): string[] {
  const tags: string[] = [];
  if (fields.some((field) => VOLUME_FIELDS.has(field))) tags.push("量价");
  if (fields.some((field) => PRICE_FIELDS.has(field))) tags.push("价格");
  if (fields.some((field) => TECHNICAL_FIELDS.has(field))) tags.push("技术指标");
  if (fields.some((field) => FUNDAMENTAL_FIELDS.has(field))) tags.push("基本面");
  return tags;
}

export function buildOperatorCategoryMap(
  operators: readonly OperatorInfo[],
): Map<string, OperatorFamilyKey> {
  const map = new Map<string, OperatorFamilyKey>();
  for (const operator of operators) {
    if (!isOperatorFamily(operator.category)) continue;
    map.set(operator.name.toLowerCase(), operator.category);
    if (operator.canonical_name) {
      map.set(operator.canonical_name.toLowerCase(), operator.category);
    }
  }
  for (const [name, family] of Object.entries(FALLBACK_OPERATOR_FAMILIES)) {
    if (!map.has(name)) map.set(name, family);
  }
  return map;
}

export type FactorClassification = {
  /** 语义类别：量价 / 波动 / 趋势 / 横截面 / 条件 / 算术 / 其他 */
  category: FactorCategoryKey;
  /** 表达式里优先级最高的算子族 */
  operatorFamily: OperatorFamilyKey;
  /** 字段标签：量价 / 价格 / 技术指标 / 基本面 */
  tags: string[];
  calls: string[];
  fields: string[];
};

export function classifyExpression(
  expression: string,
  operatorMap: ReadonlyMap<string, OperatorFamilyKey>,
): FactorClassification {
  const calls = expressionCalls(expression);
  const fields = expressionFields(expression);
  const families = calls.map((name) => operatorMap.get(name) ?? "other");

  const hasVolume = fields.some((field) => VOLUME_FIELDS.has(field));
  const hasRange = fields.includes("high") && fields.includes("low");
  const hasVolatility = calls.some((name) => VOLATILITY_OPS.has(name));
  const hasCrossSection = calls.some((name) => CROSS_SECTION_OPS.has(name));
  const hasConditional = calls.some((name) => CONDITIONAL_OPS.has(name));
  const hasTrend = calls.some((name) => TREND_OPS.has(name));
  const hasArithmetic = calls.some((name) => ARITHMETIC_OPS.has(name))
    || families.includes("arithmetic");

  let category: FactorCategoryKey = "other";
  if (hasVolume) category = "volume_price";
  else if (hasVolatility || hasRange) category = "volatility";
  else if (hasCrossSection) category = "cross_section";
  else if (hasConditional) category = "conditional";
  else if (hasTrend) category = "trend";
  else if (hasArithmetic) category = "arithmetic";

  return {
    category,
    operatorFamily: FAMILY_PRIORITY.find((family) => families.includes(family)) ?? "other",
    tags: fieldTags(fields),
    calls,
    fields,
  };
}

export type FactorView = AcceptedFactor & FactorClassification;

/* ---------- 数值与文案 ---------- */

export function metricNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

export function formatFraction(value: unknown, digits = 2): string {
  const number = metricNumber(value);
  return number == null ? "—" : `${(number * 100).toFixed(digits)}%`;
}

export function formatNumber(value: unknown, digits = 2): string {
  const number = metricNumber(value);
  return number == null ? "—" : number.toFixed(digits);
}

export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

export function mean(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function factorDataSourceLabel(source?: string | null): string {
  if (!source) return "—";
  return source === "clickhouse" || source.startsWith("clickhouse:") ? "公司库" : "本地缓存";
}

/** 生成阶段小结：尝试次数、类别分布、综合最佳因子 */
export function buildGenerationInsight(
  run: FactorRunDetail | null,
  views: readonly FactorView[],
): string {
  if (!run) return "请选择一个因子运行查看生成小结。";
  const counts = countFactorCategories(views);
  const parts: string[] = [];
  parts.push(`本次运行共尝试 ${run.attempts ?? "—"} 次，产出 ${views.length} 个合格因子`);
  if (run.target_reached) parts.push("，已达到目标数量");
  else if (run.attempts_exhausted) parts.push("，尝试次数已耗尽");
  parts.push("。");

  const distribution = CATEGORY_ORDER
    .filter((key) => counts[key] > 0)
    .map((key) => `${CATEGORY_META[key].label} ${counts[key]} 个`)
    .join("、");
  if (distribution) parts.push(`类别分布：${distribution}。`);

  const best = [...views].sort(
    (a, b) => (metricNumber(b.score) ?? -Infinity) - (metricNumber(a.score) ?? -Infinity)
      || (metricNumber(b.icir) ?? -Infinity) - (metricNumber(a.icir) ?? -Infinity),
  )[0];
  if (best) {
    parts.push(
      `Score 最高的是 ${best.factor_id}（Score ${formatNumber(best.score)}、ICIR ${formatNumber(best.icir)}、覆盖率 ${formatFraction(best.coverage, 1)}）。`,
    );
  }
  if (views.length > 0 && views.every((view) => (metricNumber(view.icir) ?? 0) <= 0)) {
    parts.push("本次合格因子的 ICIR 均为非正，需谨慎解读生成质量。");
  }
  if (views.length === 0) {
    parts.push("该运行没有合格因子，可检查质量阈值或重新生成。");
  }
  return parts.join("");
}

export type BatchInsight = {
  text: string;
  tone: "positive" | "neutral" | "negative";
  count: number;
  failed: number;
  medianAnnual: number | null;
  medianSharpe: number | null;
  medianDrawdown: number | null;
  averageWinRate: number | null;
  best: InsightFactor | null;
  worst: InsightFactor | null;
  bestCategory: { key: FactorCategoryKey; count: number; medianAnnual: number | null } | null;
};

type InsightFactor = {
  id: string;
  expression: string;
  annual: number | null;
  sharpe: number | null;
  drawdown: number | null;
};

function toInsightFactor(row: FactorBacktestRow): InsightFactor {
  return {
    id: String(row.factor_id ?? "—"),
    expression: String(row.expression ?? ""),
    annual: metricNumber(row.backtest_annual_return),
    sharpe: metricNumber(row.backtest_sharpe),
    drawdown: metricNumber(row.backtest_max_drawdown),
  };
}

function conclusionText(medianAnnual: number | null, medianSharpe: number | null): string {
  if (medianAnnual == null) return "部分指标缺失，暂无法给出整体强弱判断。";
  if (medianAnnual > 0.08 && (medianSharpe ?? 0) > 0.8) {
    return "整体表现偏强，但仍需结合样本外区间、换手率与交易成本复核。";
  }
  if (medianAnnual > 0) {
    return "整体表现中性，类别之间的差异可能比全局平均值更有参考价值。";
  }
  return "整体表现偏弱，建议优先检查因子方向、覆盖率与交易成本。";
}

/** 回测批次小结：成功/失败、收益与夏普中位数、最佳/最弱因子、类别对比 */
export function buildBatchInsight(
  rows: readonly FactorBacktestRow[],
  failures: readonly FactorBacktestFailure[],
  operatorMap: ReadonlyMap<string, OperatorFamilyKey>,
): BatchInsight {
  const annuals = rows
    .map((row) => metricNumber(row.backtest_annual_return))
    .filter((value): value is number => value != null);
  const sharpes = rows
    .map((row) => metricNumber(row.backtest_sharpe))
    .filter((value): value is number => value != null);
  const drawdowns = rows
    .map((row) => metricNumber(row.backtest_max_drawdown))
    .filter((value): value is number => value != null);
  const winRates = rows
    .map((row) => metricNumber(row.backtest_win_rate))
    .filter((value): value is number => value != null);

  const medianAnnual = median(annuals);
  const medianSharpe = median(sharpes);
  const medianDrawdown = median(drawdowns);
  const averageWinRate = mean(winRates);

  const factors = rows.map(toInsightFactor);
  const ranked = factors.filter((factor) => factor.annual != null);
  const best = ranked.length > 0
    ? ranked.reduce((winner, factor) => (
      (factor.annual ?? -Infinity) > (winner.annual ?? -Infinity) ? factor : winner
    ))
    : null;
  const worst = ranked.length > 0
    ? ranked.reduce((loser, factor) => (
      (factor.annual ?? Infinity) < (loser.annual ?? Infinity) ? factor : loser
    ))
    : null;

  const categoryGroups = new Map<FactorCategoryKey, number[]>();
  for (const row of rows) {
    const annual = metricNumber(row.backtest_annual_return);
    if (annual == null) continue;
    const category = classifyExpression(String(row.expression ?? ""), operatorMap).category;
    const values = categoryGroups.get(category) ?? [];
    values.push(annual);
    categoryGroups.set(category, values);
  }
  const bestCategory = [...categoryGroups.entries()]
    .map(([key, values]) => ({ key, count: values.length, medianAnnual: median(values) }))
    .filter((item) => item.medianAnnual != null)
    .sort((a, b) => (b.medianAnnual ?? -Infinity) - (a.medianAnnual ?? -Infinity))[0] ?? null;

  const total = rows.length + failures.length;
  const parts: string[] = [];
  parts.push(
    `本次批次共回测 ${total} 个因子，成功 ${rows.length} 个${failures.length > 0 ? `，失败 ${failures.length} 个` : ""}。`,
  );

  if (rows.length === 0) {
    parts.push(failures.length > 0 ? "成功结果为 0，建议查看失败明细中的报错。" : "批次暂未产出成功结果。");
  } else {
    parts.push(
      `成功因子的年化收益中位数 ${formatFraction(medianAnnual)}，夏普中位数 ${formatNumber(medianSharpe)}，最大回撤中位数 ${formatFraction(medianDrawdown)}，平均胜率 ${formatFraction(averageWinRate)}。`,
    );
    if (best && worst) {
      if (best.id === worst.id) {
        parts.push(`本次仅有 ${best.id} 个有效结果（年化 ${formatFraction(best.annual)}、夏普 ${formatNumber(best.sharpe)}）。`);
      } else {
        parts.push(
          `表现最好的是 ${best.id}（年化 ${formatFraction(best.annual)}、夏普 ${formatNumber(best.sharpe)}、最大回撤 ${formatFraction(best.drawdown)}）；最弱的是 ${worst.id}（年化 ${formatFraction(worst.annual)}）。`,
        );
      }
    }
    if (bestCategory) {
      parts.push(
        `分类型看，${CATEGORY_META[bestCategory.key].label}类因子的年化收益中位数最高（${bestCategory.count} 个，${formatFraction(bestCategory.medianAnnual)}）。`,
      );
    }
    parts.push(conclusionText(medianAnnual, medianSharpe));
  }
  if (failures.length > 0) {
    parts.push("失败因子请查看下方明细或下载失败 CSV。");
  }

  const tone: BatchInsight["tone"] =
    medianAnnual == null ? "neutral"
      : medianAnnual > 0.08 && (medianSharpe ?? 0) > 0.8 ? "positive"
        : medianAnnual > 0 ? "neutral"
          : "negative";

  return {
    text: parts.join(""),
    tone,
    count: rows.length,
    failed: failures.length,
    medianAnnual,
    medianSharpe,
    medianDrawdown,
    averageWinRate,
    best,
    worst,
    bestCategory,
  };
}
