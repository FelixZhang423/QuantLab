export const factorRunOptions = [
  { value: "ppo_run_100", label: "ppo_run_100 · 24 个合格因子 · 2026-06-15", factorCount: 24 },
];

export type WeightRow = { factor: string; expression: string; weight: number };

export const compositionWeights: WeightRow[] = [
  { factor: "f_001", expression: "ts_rank(close, 20) - rank(TurnoverRate)", weight: 0.18 },
  { factor: "f_002", expression: "close / ts_mean(close, 20) - 1", weight: 0.15 },
  { factor: "f_003", expression: "ts_corr(close, volume, 10)", weight: 0.13 },
  { factor: "f_004", expression: "ts_std_dev(ChangePCT, 20)", weight: 0.12 },
  { factor: "f_005", expression: "rank(amount) - ts_delay(rank(amount), 5)", weight: 0.11 },
  { factor: "f_006", expression: "ts_zscore(close, 60)", weight: 0.1 },
  { factor: "f_007", expression: "ts_decay_linear(close, 12)", weight: 0.11 },
  { factor: "f_008", expression: "ts_delta(volume, 5) / ts_mean(volume, 5)", weight: 0.1 },
];

export const compositionMetrics = { ic: 0.058, rankIc: 0.063, icir: 1.34, factors: compositionWeights.length };

export type SizeRow = { size: number; annual: number; sharpe: number; drawdown: number; turnover: number; cost: number };

export const compositionSizes: SizeRow[] = [
  { size: 10, annual: 24.18, sharpe: 1.68, drawdown: -8.6, turnover: 41.2, cost: 0.78 },
  { size: 20, annual: 19.72, sharpe: 1.45, drawdown: -9.9, turnover: 36.8, cost: 0.69 },
  { size: 30, annual: 16.05, sharpe: 1.24, drawdown: -11.2, turnover: 33.4, cost: 0.63 },
];
