/**
 * 因子有效性 8 项评价（前端原型）。
 *
 * 真实后端提供 IC / RankIC / ICIR / coverage / score 与回测绩效；
 * 分组单调性、多空收益等维度没有明细数据时，这里用可解释的估算规则
 * 给出分数和评语，页面上会明确标注「原型评价」。接入大模型或后端
 * 8 维检验后，只需替换本文件的实现，页面结构不用改。
 */

export type ValidityKey =
  | "ic"
  | "rank_ic"
  | "icir"
  | "monotonicity"
  | "long_short"
  | "turnover"
  | "coverage"
  | "risk";

export type ValidityGrade = "优秀" | "良好" | "合格" | "偏弱";

export type ValidityItem = {
  key: ValidityKey;
  label: string;
  score: number;
  grade: ValidityGrade;
  value: string;
  comment: string;
  /** 是否有真实指标；缺失时按中性分处理 */
  available: boolean;
};

export type ValidityInput = {
  ic?: number | null;
  rankIc?: number | null;
  icir?: number | null;
  coverage?: number | null;
  annualReturn?: number | null;
  sharpe?: number | null;
  maxDrawdown?: number | null;
  winRate?: number | null;
  turnover?: number | null;
  cost?: number | null;
  /** 生成阶段 score；提供时会与 8 项加权分混合 */
  score?: number | null;
};

export type ValidityReport = {
  items: ValidityItem[];
  overall: number;
  grade: ValidityGrade;
  qualified: boolean;
  threshold: number;
  conclusion: string;
  strengths: string[];
  weaknesses: string[];
};

const WEIGHTS: Record<ValidityKey, number> = {
  ic: 0.15,
  rank_ic: 0.15,
  icir: 0.15,
  monotonicity: 0.1,
  long_short: 0.15,
  turnover: 0.1,
  coverage: 0.1,
  risk: 0.1,
};

const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value));

const has = (value: number | null | undefined): value is number =>
  value != null && Number.isFinite(value);

const formatPct = (value: number | null | undefined, digits = 1) =>
  has(value) ? `${(value * 100).toFixed(digits)}%` : "—";

const formatSignedPct = (value: number | null | undefined, digits = 2) =>
  has(value) ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%` : "—";

const formatNum = (value: number | null | undefined, digits = 2) =>
  has(value) ? value.toFixed(digits) : "—";

export function validityGrade(score: number): ValidityGrade {
  if (score >= 80) return "优秀";
  if (score >= 70) return "良好";
  if (score >= 60) return "合格";
  return "偏弱";
}

export function validityColor(grade: ValidityGrade): string {
  switch (grade) {
    case "优秀":
      return "#52c41a";
    case "良好":
      return "#1677ff";
    case "合格":
      return "#faad14";
    default:
      return "#ff4d4f";
  }
}

export function validityTagColor(grade: ValidityGrade): string {
  switch (grade) {
    case "优秀":
      return "success";
    case "良好":
      return "processing";
    case "合格":
      return "warning";
    default:
      return "error";
  }
}

function item(
  key: ValidityKey,
  label: string,
  score: number,
  value: string,
  comment: string,
  available = true,
): ValidityItem {
  const rounded = Math.round(clamp(score));
  return {
    key,
    label,
    score: rounded,
    grade: validityGrade(rounded),
    value,
    comment,
    available,
  };
}

function neutral(key: ValidityKey, label: string, comment: string): ValidityItem {
  return item(key, label, 50, "—", comment, false);
}

function icItem(ic?: number | null): ValidityItem {
  if (!has(ic)) return neutral("ic", "IC 显著性", "缺少 IC 数据，暂按中性分处理。");
  const score = clamp(50 + ic * 900);
  const comment = ic >= 0.02
    ? "IC 均值达到常用可用区间，预测方向较稳定。"
    : ic > 0
      ? "IC 方向为正，但强度偏弱，需要更多样本确认。"
      : "IC 为负，需检查因子方向或反向使用。";
  return item("ic", "IC 显著性", score, ic.toFixed(4), `IC 均值 ${ic.toFixed(4)}。${comment}`);
}

function rankIcItem(rankIc?: number | null): ValidityItem {
  if (!has(rankIc)) return neutral("rank_ic", "RankIC 稳定性", "缺少 RankIC 数据，暂按中性分处理。");
  const score = clamp(50 + rankIc * 900);
  const comment = rankIc >= 0.02
    ? "秩相关方向稳定，横截面区分能力较好。"
    : rankIc > 0
      ? "秩相关为正但幅度有限，稳定性仍需观察。"
      : "秩相关为负，排序方向与预期相反。";
  return item(
    "rank_ic",
    "RankIC 稳定性",
    score,
    rankIc.toFixed(4),
    `RankIC 均值 ${rankIc.toFixed(4)}。${comment}`,
  );
}

function icirItem(icir?: number | null): ValidityItem {
  if (!has(icir)) return neutral("icir", "ICIR 信息比率", "缺少 ICIR 数据，暂按中性分处理。");
  const score = clamp(50 + icir * 18);
  const comment = icir >= 1
    ? "信息比率较稳定，IC 的波动相对可控。"
    : icir > 0
      ? "稳定性一般，建议结合样本外区间复核。"
      : "ICIR 为负，IC 序列稳定性不足。";
  return item("icir", "ICIR 信息比率", score, icir.toFixed(2), `ICIR ${icir.toFixed(2)}。${comment}`);
}

function monotonicityItem(ic?: number | null, rankIc?: number | null): ValidityItem {
  if (!has(ic) && !has(rankIc)) {
    return neutral("monotonicity", "分组单调性", "缺少 IC 与 RankIC，无法估计分组单调性。");
  }
  const rank = rankIc ?? 0;
  const raw = ic ?? 0;
  const direction = rank >= 0 ? "正向" : "反向";
  const score = clamp(45 + Math.abs(rank) * 700 + Math.max(0, raw) * 150);
  return item(
    "monotonicity",
    "分组单调性",
    score,
    `${direction}估计`,
    `按 RankIC 与 IC 估计${direction}分组单调性；真实五分组收益待接入后替换。`,
  );
}

function longShortItem(
  annualReturn?: number | null,
  winRate?: number | null,
): ValidityItem {
  if (!has(annualReturn) && !has(winRate)) {
    return neutral("long_short", "多空收益", "缺少组合收益与胜率，暂按中性分处理。");
  }
  const annual = annualReturn ?? 0;
  const winRateValue = winRate ?? 0.5;
  const score = clamp(50 + annual * 160 + (winRateValue - 0.5) * 120);
  return item(
    "long_short",
    "多空收益",
    score,
    `${formatSignedPct(annualReturn)} / 胜率 ${formatPct(winRate)}`,
    `组合年化 ${formatSignedPct(annualReturn)}，胜率 ${formatPct(winRate)}；以组合表现估计多空价差。`,
  );
}

function turnoverItem(turnover?: number | null, cost?: number | null): ValidityItem {
  if (!has(turnover) && !has(cost)) {
    return neutral("turnover", "换手与成本", "缺少换手与成本数据，暂按中性分处理。");
  }
  const score = clamp(100 - (turnover ?? 0.3) * 110 - (cost ?? 0) * 100);
  return item(
    "turnover",
    "换手与成本",
    score,
    `换手 ${formatPct(turnover)} / 成本 ${formatPct(cost)}`,
    `平均换手 ${formatPct(turnover)}，总成本 ${formatPct(cost)}；换手和成本越低越有利于净收益。`,
  );
}

function coverageItem(coverage?: number | null): ValidityItem {
  if (!has(coverage)) return neutral("coverage", "覆盖率与容量", "缺少覆盖率数据，暂按中性分处理。");
  const score = clamp(coverage * 100);
  return item(
    "coverage",
    "覆盖率与容量",
    score,
    formatPct(coverage),
    `因子有效覆盖 ${formatPct(coverage)} 的股票；覆盖不足会放大选股偏差。`,
  );
}

function riskItem(
  annualReturn?: number | null,
  sharpe?: number | null,
  maxDrawdown?: number | null,
): ValidityItem {
  if (!has(sharpe) && !has(maxDrawdown)) {
    return neutral("risk", "风险调整收益", "缺少夏普与回撤数据，暂按中性分处理。");
  }
  const score = clamp(
    50
      + (sharpe ?? 0) * 18
      + (maxDrawdown ?? -0.2) * 60
      + Math.max(0, annualReturn ?? 0) * 40,
  );
  return item(
    "risk",
    "风险调整收益",
    score,
    `夏普 ${formatNum(sharpe)} / 回撤 ${formatPct(maxDrawdown)}`,
    `夏普 ${formatNum(sharpe)}，最大回撤 ${formatPct(maxDrawdown)}，年化 ${formatSignedPct(annualReturn)}。`,
  );
}

/**
 * 生成 8 项有效性评价。
 * @param threshold 合格线，默认 60
 */
export function buildValidityReport(input: ValidityInput, threshold = 60): ValidityReport {
  const items: ValidityItem[] = [
    icItem(input.ic),
    rankIcItem(input.rankIc),
    icirItem(input.icir),
    monotonicityItem(input.ic, input.rankIc),
    longShortItem(input.annualReturn, input.winRate),
    turnoverItem(input.turnover, input.cost),
    coverageItem(input.coverage),
    riskItem(input.annualReturn, input.sharpe, input.maxDrawdown),
  ];

  const weighted = items.reduce((sum, current) => sum + current.score * WEIGHTS[current.key], 0);
  const overall = Math.round(
    has(input.score) ? weighted * 0.75 + clamp(input.score) * 0.25 : weighted,
  );
  const grade = validityGrade(overall);
  const qualified = overall >= threshold;
  const available = items.filter((current) => current.available);
  const strengths = [...available]
    .filter((current) => current.score >= 70)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((current) => current.label);
  const weaknesses = [...available]
    .filter((current) => current.score < 60)
    .sort((a, b) => a.score - b.score)
    .slice(0, 3)
    .map((current) => current.label);

  const head = `8 项评价综合得分 ${overall}，${qualified ? "达到" : "未达到"}合格线 ${threshold}。`;
  const strengthText = strengths.length > 0 ? `优势项：${strengths.join("、")}。` : "";
  const weaknessText = weaknesses.length > 0 ? `需关注：${weaknesses.join("、")}。` : "";
  const tail = qualified
    ? weaknesses.length > 0
      ? "建议针对短板补充样本外检验后再放大使用。"
      : "各项表现较均衡，建议结合样本外表现复核。"
    : "建议优先补强短板，或调整因子方向后重新生成。";

  return {
    items,
    overall,
    grade,
    qualified,
    threshold,
    conclusion: `${head}${strengthText}${weaknessText}${tail}`,
    strengths,
    weaknesses,
  };
}
