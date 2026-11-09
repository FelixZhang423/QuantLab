import type { AcceptedFactor, FactorRunSummary, FactorRunDetail } from "./api";

export const metricNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
};

export const formatMetric = (value: unknown, digits: number): string => {
  const number = metricNumber(value);
  return number == null ? "—" : number.toFixed(digits);
};

export const compareMetrics = (left: unknown, right: unknown): number => {
  const a = metricNumber(left);
  const b = metricNumber(right);
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  return a - b;
};

export const validityRow = (factor: AcceptedFactor) => ({
  ...factor,
  ic: metricNumber(factor.ic),
  rank_ic: metricNumber(factor.rank_ic),
  icir: metricNumber(factor.icir),
  coverage: metricNumber(factor.coverage),
  score: metricNumber(factor.score),
  valid_ic: metricNumber(factor.segments?.valid?.ic),
  valid_icir: metricNumber(factor.segments?.valid?.icir),
  valid_days: metricNumber(factor.segments?.valid?.valid_days),
  test_ic: metricNumber(factor.segments?.test?.ic),
  test_rank_ic: metricNumber(factor.segments?.test?.rank_ic),
  test_icir: metricNumber(factor.segments?.test?.icir),
  test_coverage: metricNumber(factor.segments?.test?.coverage),
  test_days: metricNumber(factor.segments?.test?.valid_days),
});

export type FactorValidityRow = ReturnType<typeof validityRow>;

export const isConfirmedRun = (run: FactorRunSummary): boolean =>
  run.local_available !== false && (run.confirmed_count ?? 0) > 0 && run.confirmation_status === "finished";

export const confirmedFactors = (run: FactorRunDetail | null): AcceptedFactor[] => run?.confirmed_factors ?? [];

export const qualificationReason = (factor: AcceptedFactor, quality: Record<string, unknown> = {}): string => {
  const test = factor.segments?.test;
  const trainIC = metricNumber(factor.segments?.train?.ic) ?? metricNumber(factor.ic);
  const values = [metricNumber(test?.coverage), metricNumber(test?.ic), metricNumber(test?.rank_ic), metricNumber(test?.icir)];
  if (values.some(v => v == null) || trainIC == null || trainIC === 0) return "测试指标或训练方向缺失，无法核实合格原因；请重新生成并执行因子确认。";
  const [coverage, ic, rank, icir] = values as number[];
  const limits = [metricNumber(quality.min_test_coverage) ?? 0.9, metricNumber(quality.min_test_ic) ?? 0.03,
    metricNumber(quality.min_test_rank_ic) ?? 0.03, metricNumber(quality.min_test_icir) ?? 0.3];
  const aligned = [ic, rank, icir].every(v => Math.sign(v) === Math.sign(trainIC));
  const passed = coverage >= limits[0] && Math.abs(ic) >= limits[1] && Math.abs(rank) >= limits[2] && Math.abs(icir) >= limits[3] && aligned;
  if (!passed) return "记录与测试合格门槛不一致：需检查覆盖率、指标绝对值及与训练 IC 的同号条件，不能据此认定合格。";
  return `通过测试门槛：覆盖率 ${(coverage*100).toFixed(1)}% ≥ ${(limits[0]*100).toFixed(1)}%；|IC| ${Math.abs(ic).toFixed(4)} ≥ ${limits[1]}；|RankIC| ${Math.abs(rank).toFixed(4)} ≥ ${limits[2]}；|ICIR| ${Math.abs(icir).toFixed(2)} ≥ ${limits[3]}；三项指标均与训练 IC（${trainIC.toFixed(4)}）同号。该可接受因子经测试确认后成为合格因子。`;
};
