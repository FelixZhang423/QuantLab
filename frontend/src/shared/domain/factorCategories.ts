/**
 * 因子语义分类（演示用规则）。
 *
 * 后端暂无 LLM 分类接口；生成页先按表达式里的字段/算子做可解释归类，
 * 界面标注“LLM 分类（演示）”，后端接入后替换 classifyFactor 即可。
 */

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
  color: string;
  description: string;
};

export const FACTOR_CATEGORIES: readonly FactorCategoryMeta[] = [
  { key: "volume_price", label: "量价", color: "gold", description: "使用成交量、成交额、换手率等量价字段" },
  { key: "volatility", label: "波动", color: "orange", description: "使用波动率、相关性算子，或高低价区间" },
  { key: "trend", label: "趋势", color: "blue", description: "使用均线、差分、延迟等趋势型时序算子" },
  { key: "cross_section", label: "横截面", color: "geekblue", description: "使用排名、标准化、缩放或分组算子" },
  { key: "conditional", label: "条件", color: "purple", description: "使用 if_else、trade_when、比较或逻辑运算" },
  { key: "arithmetic", label: "算术", color: "default", description: "以四则运算、对数、幂等算术组合为主" },
  { key: "other", label: "其他", color: "default", description: "未识别出明确的主要类别" },
];

export const CATEGORY_META = Object.fromEntries(
  FACTOR_CATEGORIES.map((item) => [item.key, item])
) as Record<FactorCategoryKey, FactorCategoryMeta>;

const VOLUME_FIELDS = new Set(["volume", "vol", "amount", "turnover", "turnoverrate", "changepct", "vwap"]);
const VOLATILITY_OPS = new Set(["ts_std", "ts_std_dev", "ts_var", "ts_mad", "ts_covariance", "ts_corr"]);
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

const CALL_PATTERN = /([A-Za-z_][A-Za-z0-9_]*)\s*\(/g;
const IDENTIFIER_PATTERN = /[A-Za-z_][A-Za-z0-9_]*/g;

function expressionCalls(expression: string): string[] {
  const calls = new Set<string>();
  for (const match of expression.matchAll(CALL_PATTERN)) calls.add(match[1].toLowerCase());
  return [...calls];
}

function expressionFields(expression: string): string[] {
  const fields = new Set<string>();
  for (const match of expression.matchAll(IDENTIFIER_PATTERN)) {
    const end = (match.index ?? 0) + match[0].length;
    if (expression.slice(end).trimStart().startsWith("(")) continue;
    const name = match[0].toLowerCase();
    if (name !== "true" && name !== "false" && name !== "nan") fields.add(name);
  }
  return [...fields];
}

export function classifyFactor(expression: string): FactorCategoryKey {
  const calls = expressionCalls(expression);
  const fields = expressionFields(expression);
  const hasVolume = fields.some((field) => VOLUME_FIELDS.has(field));
  const hasRange = fields.includes("high") && fields.includes("low");
  const hasVolatility = calls.some((name) => VOLATILITY_OPS.has(name));
  const hasCrossSection = calls.some((name) => CROSS_SECTION_OPS.has(name));
  const hasConditional = calls.some((name) => CONDITIONAL_OPS.has(name));
  const hasTrend = calls.some((name) => TREND_OPS.has(name));
  const hasArithmetic = calls.some((name) => ARITHMETIC_OPS.has(name));

  if (hasVolume) return "volume_price";
  if (hasVolatility || hasRange) return "volatility";
  if (hasCrossSection) return "cross_section";
  if (hasConditional) return "conditional";
  if (hasTrend) return "trend";
  if (hasArithmetic) return "arithmetic";
  return "other";
}
