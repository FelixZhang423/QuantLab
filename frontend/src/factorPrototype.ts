/**
 * 因子生成 / 回测的前端原型数据。
 *
 * 生成算法、进度、因子类别判定与有效性评分都在浏览器里完成，不写入
 * factor_runs/，也不调用后端生成接口。生成结果通过 sessionStorage 带到
 * 回测页，让「生成 → 合格因子 → 回测 → 结果讲解」的交互可以完整演示。
 */
import type {
  FactorBacktestBatch,
  FactorBacktestBatchDetail,
  FactorBacktestRow,
} from "./api/client";
import {
  classifyExpression,
  type FactorCategoryKey,
  type OperatorFamilyKey,
} from "./factorInsights";
import { buildValidityReport, type ValidityReport } from "./factorValidity";

export type PrototypeAlgorithmKey = "ppo" | "genetic" | "random" | "llm";

export type PrototypeAlgorithmMeta = {
  key: PrototypeAlgorithmKey;
  label: string;
  description: string;
};

export const PROTOTYPE_ALGORITHMS: readonly PrototypeAlgorithmMeta[] = [
  {
    key: "ppo",
    label: "PPO 强化学习",
    description: "用 PPO 在表达式搜索空间中采样，并按 IC / 有效性奖励迭代。",
  },
  {
    key: "genetic",
    label: "遗传算法",
    description: "对表达式做交叉、变异与精英保留，适合批量探索算子组合。",
  },
  {
    key: "random",
    label: "随机搜索",
    description: "从字段与算子组合中随机采样，作为快速基线。",
  },
  {
    key: "llm",
    label: "LLM 引导生成",
    description: "由大模型根据字段含义提出候选表达式，再交给有效性检验。",
  },
];

export function prototypeAlgorithmLabel(key: PrototypeAlgorithmKey): string {
  return PROTOTYPE_ALGORITHMS.find((item) => item.key === key)?.label ?? key;
}

export type PrototypeGenerationConfig = {
  pool_id: string;
  algorithm: PrototypeAlgorithmKey;
  fields: string[];
  operators: string[];
  start_date: string;
  end_date: string;
  target_count: number;
  score_threshold: number;
};

export type PrototypeFactor = {
  factor_id: string;
  expression: string;
  category: FactorCategoryKey;
  category_reason: string;
  operator_family: OperatorFamilyKey;
  tags: string[];
  ic: number;
  rank_ic: number;
  icir: number;
  coverage: number;
  score: number;
  qualified: boolean;
  annual_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  turnover: number;
  cost: number;
  llm_confidence: number;
  validity: ValidityReport;
};

export type PrototypeFactorRun = {
  run_id: string;
  pool_id: string;
  pool_name?: string;
  config: PrototypeGenerationConfig;
  algorithm_label: string;
  created_at: string;
  factors: PrototypeFactor[];
};

export type PrototypeBacktestParams = {
  start_date: string;
  end_date: string;
  top_k: number;
  initial_cash: number;
  buy_cost: number;
  sell_cost: number;
  slippage: number;
  min_cost: number;
  max_weight_per_stock: number;
};

/** 原型批次额外保留回测参数，供单因子结果详情复用 */
export type PrototypeBatchDetail = FactorBacktestBatchDetail & {
  params: PrototypeBacktestParams;
};

export const FALLBACK_FIELD_NAMES = [
  "close",
  "open",
  "high",
  "low",
  "volume",
  "amount",
  "TurnoverRate",
  "ChangePCT",
  "RangePCT",
  "ycp",
  "vol",
] as const;

export const DEFAULT_PROTOTYPE_FIELDS = ["close", "volume", "high", "low"];
export const DEFAULT_PROTOTYPE_OPERATORS = ["ts_mean", "ts_std", "delta", "ts_corr", "rank", "zscore"];

const PROTOTYPE_STORAGE_KEY = "quantlab.prototype.factorRun";

const CATEGORY_REASON: Record<FactorCategoryKey, string> = {
  volume_price: "表达式直接使用成交量、成交额或换手率字段，大模型将其归为量价类。",
  volatility: "表达式使用波动率、相关性算子，或同时使用最高价/最低价区间，大模型将其归为波动类。",
  trend: "表达式使用均线、差分、延迟等时间序列算子，大模型将其归为趋势类。",
  cross_section: "表达式使用排名、标准化、缩放或分组算子，大模型将其归为横截面类。",
  conditional: "表达式包含 if_else、trade_when 或比较逻辑，大模型将其归为条件类。",
  arithmetic: "表达式以四则运算、对数、幂等算术组合为主，大模型将其归为算术类。",
  other: "表达式未呈现明确的字段或算子特征，大模型暂归为其他类。",
};

type ExpressionTemplate = {
  /** 模板用到的算子；用户选中的算子必须覆盖这些调用 */
  calls: string[];
  /** 无法完全覆盖时用来回退的主算子 */
  primary: string;
  build: (field: string, second: string) => string;
};

const TEMPLATES: readonly ExpressionTemplate[] = [
  {
    calls: ["ts_mean"],
    primary: "ts_mean",
    build: (field) => `sub(ts_mean(${field},20),ts_mean(${field},60))`,
  },
  {
    calls: ["div", "ts_mean"],
    primary: "div",
    build: (field) => `div(${field},ts_mean(${field},20))`,
  },
  {
    calls: ["ts_std", "div", "ts_mean"],
    primary: "ts_std",
    build: (field) => `ts_std(div(${field},ts_mean(${field},20)),20)`,
  },
  {
    calls: ["ts_corr"],
    primary: "ts_corr",
    build: (field, second) => `ts_corr(${field},${second},20)`,
  },
  {
    calls: ["delta"],
    primary: "delta",
    build: (field) => `delta(${field},5)`,
  },
  {
    calls: ["div", "delay"],
    primary: "delay",
    build: (field) => `div(${field},delay(${field},20))`,
  },
  {
    calls: ["rank"],
    primary: "rank",
    build: (field) => `rank(${field})`,
  },
  {
    calls: ["zscore"],
    primary: "zscore",
    build: (field) => `zscore(${field})`,
  },
  {
    calls: ["if_else", "greater", "ts_mean"],
    primary: "if_else",
    build: (field) => `if_else(greater(${field},ts_mean(${field},20)),${field},0)`,
  },
  {
    calls: ["rank", "div", "ts_mean"],
    primary: "rank",
    build: (field) => `rank(div(${field},ts_mean(${field},20)))`,
  },
  {
    calls: ["zscore", "delta"],
    primary: "zscore",
    build: (field) => `zscore(delta(${field},5))`,
  },
  {
    calls: ["mul", "rank"],
    primary: "mul",
    build: (field) => `mul(rank(${field}),-1)`,
  },
  {
    calls: ["log"],
    primary: "log",
    build: (field) => `log(${field})`,
  },
  {
    calls: ["div", "sub", "ts_std"],
    primary: "div",
    build: (field, second) => `div(sub(${field},${second}),ts_std(${field},20))`,
  },
  {
    calls: ["ts_mean", "div"],
    primary: "ts_mean",
    build: (field, second) => `ts_mean(div(${field},${second}),20)`,
  },
  {
    calls: ["scale", "ts_std"],
    primary: "scale",
    build: (field) => `scale(ts_std(${field},20))`,
  },
];

function hashString(input: string): number {
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seeded(seed: string, min: number, max: number): number {
  return min + (hashString(seed) / 0xffffffff) * (max - min);
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function compactStamp(date = new Date()): string {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function selectTemplates(selected: ReadonlySet<string>): readonly ExpressionTemplate[] {
  if (selected.size === 0) return TEMPLATES.slice(0, 8);
  const fullyUsable = TEMPLATES.filter((template) => template.calls.every((call) => selected.has(call)));
  if (fullyUsable.length > 0) return fullyUsable;
  const primaryUsable = TEMPLATES.filter((template) => selected.has(template.primary));
  if (primaryUsable.length > 0) return primaryUsable;
  const partlyUsable = TEMPLATES.filter((template) => template.calls.some((call) => selected.has(call)));
  return partlyUsable.length > 0 ? partlyUsable : TEMPLATES.slice(0, 6);
}

function buildFactor(
  expression: string,
  index: number,
  config: PrototypeGenerationConfig,
  operatorMap: ReadonlyMap<string, OperatorFamilyKey>,
): PrototypeFactor {
  const classification = classifyExpression(expression, operatorMap);
  const seed = `${config.pool_id}|${config.algorithm}|${expression}|${index}`;
  const ic = seeded(`${seed}|ic`, -0.03, 0.06);
  const rankIc = ic * 0.9 + seeded(`${seed}|rank_ic`, -0.008, 0.008);
  const icir = seeded(`${seed}|icir`, -0.6, 2.4);
  const coverage = seeded(`${seed}|coverage`, 0.65, 0.98);
  const annualReturn = clamp(ic * 3.2 + seeded(`${seed}|annual`, -0.12, 0.12), -0.25, 0.35);
  const sharpe = clamp(ic * 12 + seeded(`${seed}|sharpe`, -0.6, 0.8), -1, 2.4);
  const maxDrawdown = -seeded(`${seed}|drawdown`, 0.06, 0.32);
  const winRate = clamp(0.5 + ic * 1.2 + seeded(`${seed}|win_rate`, -0.04, 0.04), 0.38, 0.66);
  const turnover = seeded(`${seed}|turnover`, 0.15, 0.6);
  const cost = turnover * seeded(`${seed}|cost`, 0.002, 0.005);
  const validity = buildValidityReport(
    {
      ic,
      rankIc,
      icir,
      coverage,
      annualReturn,
      sharpe,
      maxDrawdown,
      winRate,
      turnover,
      cost,
    },
    config.score_threshold,
  );

  return {
    factor_id: `proto_${String(index + 1).padStart(4, "0")}`,
    expression,
    category: classification.category,
    category_reason: CATEGORY_REASON[classification.category],
    operator_family: classification.operatorFamily,
    tags: classification.tags,
    ic,
    rank_ic: rankIc,
    icir,
    coverage,
    score: validity.overall,
    qualified: validity.qualified,
    annual_return: annualReturn,
    sharpe,
    max_drawdown: maxDrawdown,
    win_rate: winRate,
    turnover,
    cost,
    llm_confidence: Math.round(seeded(`${seed}|llm_confidence`, 72, 97)),
    validity,
  };
}

/** 生成一次原型运行；相同配置与字段顺序会得到相同结果 */
export function buildPrototypeRun(
  config: PrototypeGenerationConfig,
  operatorMap: ReadonlyMap<string, OperatorFamilyKey>,
): PrototypeFactorRun {
  const target = Math.max(1, Math.min(30, Math.round(config.target_count || 9)));
  const fields = config.fields.length > 0 ? config.fields : ["close"];
  const selectedOperators = new Set(config.operators.map((operator) => operator.toLowerCase()));
  const templates = selectTemplates(selectedOperators);
  const seen = new Set<string>();
  const factors: PrototypeFactor[] = [];
  let cursor = 0;

  while (factors.length < target && cursor < target * 10 + 24) {
    const template = templates[cursor % templates.length];
    const field = fields[cursor % fields.length];
    const second = fields[(cursor + 1) % fields.length] ?? field;
    const expression = template.build(field, second);
    cursor += 1;
    if (seen.has(expression)) continue;
    seen.add(expression);
    factors.push(buildFactor(expression, factors.length, config, operatorMap));
  }

  const createdAt = new Date();
  return {
    run_id: `proto_${compactStamp(createdAt)}_${String(hashString(`${createdAt.getTime()}|${config.algorithm}`)).slice(-3)}`,
    pool_id: config.pool_id,
    config,
    algorithm_label: prototypeAlgorithmLabel(config.algorithm),
    created_at: createdAt.toISOString(),
    factors,
  };
}

export function savePrototypeRun(run: PrototypeFactorRun): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PROTOTYPE_STORAGE_KEY, JSON.stringify(run));
  } catch {
    // 原型演示：存储失败不阻塞页面
  }
}

export function loadPrototypeRun(): PrototypeFactorRun | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PROTOTYPE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PrototypeFactorRun | null;
    if (!parsed || typeof parsed !== "object") return null;
    if (!parsed.run_id || !parsed.config || !Array.isArray(parsed.factors)) return null;
    return parsed;
  } catch {
    return null;
  }
}

const PROTOTYPE_BATCH_STORAGE_KEY = "quantlab.prototype.factorBatch";

/** 保存最近一次原型回测批次，从单因子结果返回回测页时用它恢复表格 */
export function savePrototypeBatchDetail(detail: PrototypeBatchDetail): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PROTOTYPE_BATCH_STORAGE_KEY, JSON.stringify(detail));
  } catch {
    // 原型演示：存储失败不阻塞页面
  }
}

export function loadPrototypeBatchDetail(runId?: string): PrototypeBatchDetail | null {
  if (typeof window === "undefined" || !runId) return null;
  try {
    const raw = window.sessionStorage.getItem(PROTOTYPE_BATCH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PrototypeBatchDetail | null;
    if (!parsed || typeof parsed !== "object") return null;
    if (!parsed.batch || !Array.isArray(parsed.rows) || !parsed.params) return null;
    if (parsed.batch.factor_run_id !== runId) return null;
    return parsed;
  } catch {
    return null;
  }
}

/** 将原型回测结果包装成与真实批次相同的结构，便于复用页面表格 */
export function buildPrototypeBatch(
  run: PrototypeFactorRun,
  factors: readonly PrototypeFactor[],
  params: PrototypeBacktestParams,
): PrototypeBatchDetail {
  const createdAt = new Date();
  const years = Math.max(
    0.1,
    (new Date(params.end_date).getTime() - new Date(params.start_date).getTime())
      / (365.25 * 24 * 60 * 60 * 1000),
  );
  const batch: FactorBacktestBatch = {
    backtest_id: `proto_bt_${compactStamp(createdAt)}_${String(hashString(`${createdAt.getTime()}|${run.run_id}`)).slice(-3)}`,
    job_id: null,
    factor_run_id: run.run_id,
    pool_id: run.pool_id,
    created_at: createdAt.toISOString(),
    accepted_count: run.factors.filter((factor) => factor.qualified).length,
    selected_count: factors.length,
    completed: factors.length,
    failed: 0,
    start_date: params.start_date,
    end_date: params.end_date,
    top_k: params.top_k,
    initial_cash: params.initial_cash,
    run_key_prefix: null,
    summary_file: "",
    failures_file: "",
    output_dir: "",
  } as FactorBacktestBatch;

  const rows: FactorBacktestRow[] = factors.map((factor) => ({
    factor_id: factor.factor_id,
    expression: factor.expression,
    canonical_expression: factor.expression,
    backtest_total_return: factor.annual_return * years,
    backtest_annual_return: factor.annual_return,
    backtest_sharpe: factor.sharpe,
    backtest_max_drawdown: factor.max_drawdown,
    backtest_calmar: factor.max_drawdown !== 0 ? factor.annual_return / Math.abs(factor.max_drawdown) : null,
    backtest_win_rate: factor.win_rate,
    backtest_average_turnover: factor.turnover,
    backtest_total_cost: factor.cost,
    backtest_annual_cost: factor.cost / years,
    backtest_number_of_trades: Math.round(factor.turnover * 250),
    backtest_average_holding_count: params.top_k,
    generation_ic: factor.ic,
    generation_rank_ic: factor.rank_ic,
    generation_icir: factor.icir,
    generation_coverage: factor.coverage,
    generation_score: factor.score,
  }));

  return { batch, rows, failures: [], params: { ...params } };
}
