import type { AcceptedFactor, FactorRunDetail } from "../factor-backtest/api";

export function confirmationRow(factor: AcceptedFactor, run: FactorRunDetail | null | undefined) {
  const confirmed = run?.confirmed_factors.find((item) => item.factor_id === factor.factor_id);
  const evaluation = run?.test_evaluations?.find((item) => item.factor_id === factor.factor_id);
  return {
    ...factor,
    ...confirmed,
    segments: { ...factor.segments, ...confirmed?.segments,
      ...(evaluation?.test ? { test: evaluation.test } : {}) },
    phase: confirmed ? "confirmed" as const : "candidate" as const,
    confirmationText: confirmed ? "已通过测试集质量门槛"
      : evaluation ? `${evaluation.test ? "测试未通过" : "评估未完成或失败"}：${evaluation.reason ?? "无详细原因"}`
      : "尚未评估",
  };
}
