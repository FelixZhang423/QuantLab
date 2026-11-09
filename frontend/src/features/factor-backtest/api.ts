import { apiGet, apiPost, withQuery } from "../../shared/api/base";

export type FactorRunSummary = {
  run_id: string;
  pool_id: string | null;
  source_signature: string | null;
  runtime_id: string | null;
  created_at: string | null;
  accepted_count: number;
  candidate_count?: number;
  confirmed_count?: number;
  confirmation_status?: "pending" | "running" | "finished" | "failed";
  attempts: number | null;
  target_reached: boolean | null;
  attempts_exhausted: boolean | null;
  factor_run_dir: string;
  has_accepted: boolean;
  /** 训练元数据（MySQL factor_runs 表） */
  run_name?: string | null;
  job_id?: string | null;
  device?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  training_seconds?: number | null;
  timesteps?: number | null;
  target_factor_count?: number | null;
  max_attempts?: number | null;
  rollout_timesteps?: number | null;
  seed?: number | null;
  target_horizon?: number | null;
  max_backtrack_days?: number | null;
  max_future_days?: number | null;
  split_days?: Record<string, number> | null;
  hyperparameters?: Record<string, unknown> | null;
  fields?: string[] | null;
  operators?: string[] | null;
  operator_mode?: string | null;
  n_stocks?: number | null;
  storage?: string;
  local_available?: boolean;
};

export type SegmentMetrics = {
  ic: number | null;
  rank_ic: number | null;
  icir: number | null;
  coverage: number | null;
  valid_days: number | null;
};

export type AcceptedFactor = {
  factor_id: string;
  expression: string;
  canonical_expression: string | null;
  backtest_expression: string | null;
  ic: number | null;
  rank_ic: number | null;
  icir: number | null;
  coverage: number | null;
  score: number | null;
  reason: string | null;
  /** train / valid / test 分段指标 */
  segments?: Record<string, SegmentMetrics>;
};

export type FactorRunDetail = FactorRunSummary & {
  manifest: Record<string, unknown>;
  accepted_factors: AcceptedFactor[];
  candidate_factors: AcceptedFactor[];
  confirmed_factors: AcceptedFactor[];
  historical_factors?: AcceptedFactor[];
};

export type FactorBacktestRequest = {
  factor_run_id: string;
  /** 省略 = 回测该运行的全部合格因子 */
  factor_ids?: string[];
  start_date?: string;
  end_date?: string;
  top_k?: number;
  initial_cash?: number;
  buy_cost?: number;
  sell_cost?: number;
  slippage?: number;
  min_cost?: number;
  max_weight_per_stock?: number;
  rebalance_freq?: "1D" | "1W" | "2W" | "1M";
  commission?: number;
  stamp_duty?: number;
  transfer_fee?: number;
};

export type FactorBacktestResponse = {
  job_id: string;
  backtest_id: string;
  status: string;
  operation: string;
  factor_run_id: string;
  pool_id: string;
  accepted_total: number;
  selected_total: number;
  warnings: string[];
  request_summary: Record<string, unknown>;
};

export type FactorBacktestBatch = {
  backtest_id: string;
  job_id: string | null;
  factor_run_id: string;
  pool_id: string | null;
  created_at: string | null;
  accepted_count: number | null;
  selected_count: number | null;
  completed: number | null;
  failed: number | null;
  start_date: string | null;
  end_date: string | null;
  top_k: number | null;
  initial_cash: number | null;
  run_key_prefix: string | null;
  summary_file: string;
  failures_file: string;
  output_dir: string;
};

export type FactorBacktestRow = {
  factor_id?: string;
  expression?: string;
  canonical_expression?: string;
  run_key?: string;
  [key: string]: unknown;
};

export type FactorBacktestFailure = {
  factor_id?: string;
  expression?: string;
  error?: string;
};

export type FactorBacktestBatchDetail = {
  batch: FactorBacktestBatch;
  rows: FactorBacktestRow[];
  failures: FactorBacktestFailure[];
};

export const factorApi = {
  confirmFactorRun: (runId: string) =>
    apiPost<{job_id: string; status: string; operation: "confirm_factors"; run_id: string}>(`/api/factor-runs/${encodeURIComponent(runId)}/confirm`, {}),
  factorRuns: (poolId?: string) =>
    apiGet<{ total: number; runs: FactorRunSummary[]; source?: string; mysql_error?: string | null }>(
      withQuery("/api/factor-runs", { pool_id: poolId }),
    ),
  factorRun: (runId: string) =>
    apiGet<FactorRunDetail>(`/api/factor-runs/${encodeURIComponent(runId)}`),
  createFactorBacktest: (payload: FactorBacktestRequest) =>
    apiPost<FactorBacktestResponse>("/api/factor-backtests", payload),
  factorBacktests: (factorRunId: string) =>
    apiGet<{ total: number; batches: FactorBacktestBatch[] }>(
      withQuery("/api/factor-backtests", { factor_run_id: factorRunId }),
    ),
  factorBacktest: (factorRunId: string, backtestId: string) =>
    apiGet<FactorBacktestBatchDetail>(
      withQuery(`/api/factor-backtests/${encodeURIComponent(backtestId)}`, { factor_run_id: factorRunId }),
    ),
};

export function factorBacktestFileUrl(
  factorRunId: string,
  backtestId: string,
  fileName: string,
): string {
  return withQuery(
    `/api/factor-backtests/${encodeURIComponent(backtestId)}/files/${encodeURIComponent(fileName)}`,
    { factor_run_id: factorRunId },
  );
}
