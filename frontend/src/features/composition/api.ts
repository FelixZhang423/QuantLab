import { apiGet, apiPost, withQuery } from "../../shared/api/base";

export type FactorCompositionRequest = {
  snapshot_id?: string;
  as_of?: string;
  pool_id: string;
  factor_run_ids: string[];
  /** 省略 = 自动按 selection_metric 取前 max_factors 个；显式列表 = 只组合这些因子 */
  factor_ids?: string[];
  selection_metric?: string;
  min_score?: number;
  min_ic?: number;
  min_rank_ic?: number;
  min_coverage?: number;
  min_backtest_sharpe?: number;
  mutual_ic_threshold?: number;
  z_clip?: number | null;
  sweep_sizes?: number[];
  max_factors?: number;
  target_horizon?: number;
  start_date?: string;
  end_date?: string;
  top_k?: number;
  initial_cash?: number;
  rebalance_freq?: "1D" | "1W" | "2W" | "1M";
  commission?: number;
  transfer_fee?: number;
  stamp_duty?: number;
  buy_cost?: number;
  sell_cost?: number;
  slippage?: number;
  min_cost?: number;
  max_weight_per_stock?: number;
};

export type FactorCompositionResponse = {
  job_id: string;
  status: string;
  operation: string;
  pool_id: string;
  data_source: string;
  factor_run_ids: string[];
  factor_ids: string[] | null;
  candidate_total: number;
  selected_total: number | null;
  warnings: string[];
  request_summary: Record<string, unknown>;
};

export type CompositionMetrics = {
  ic?: number | null;
  rank_ic?: number | null;
  icir?: number | null;
  rank_icir?: number | null;
  coverage?: number | null;
  valid_days?: number | null;
};

export type CompositionBacktestSummary = {
  total_return?: number | null;
  annual_return?: number | null;
  sharpe?: number | null;
  max_drawdown?: number | null;
  calmar?: number | null;
  win_rate?: number | null;
  average_turnover?: number | null;
  total_cost?: number | null;
  annual_cost?: number | null;
  number_of_trades?: number | null;
  average_holding_count?: number | null;
  [key: string]: number | null | undefined;
};

export type CompositionScreenSummary = {
  signal_date?: string | null;
  execution_date?: string | null;
  execution_pending?: boolean | null;
  total_ranked?: number | null;
  selected_count?: number | null;
  buyable_count?: number | null;
  planned_weight_per_stock?: number | null;
};

export type CompositionSizeEntry = {
  size: number;
  run_name: string;
  run_key: string;
  output_dir: string;
  composition_metrics: CompositionMetrics;
  backtest_summary: CompositionBacktestSummary;
  screen: CompositionScreenSummary;
};

export type CompositionManifest = {
  composition_id: string;
  created_at: string;
  pool_id: string;
  data_source: string;
  snapshot_id: string | null;
  source_snapshot_ids: string[];
  source_factor_run_ids: string[];
  run_dirs: string[];
  /** 历史产物兼容字段：新组合恒为 "equal" */
  weight_method?: string | null;
  selection_metric: string;
  mutual_ic_threshold: number;
  z_clip: number | null;
  target_horizon: number;
  requested_factor_ids: string[] | null;
  candidate_ids: string[];
  candidate_count: number;
  selected_count: number;
  rejected_count: number;
  requested_sizes: number[];
  completed_sizes: number[];
  underfilled_final_size: number | null;
  default_size: number | null;
  filters: Record<string, number | null>;
  backtest_config: Record<string, unknown>;
  marginal_gate: Record<string, unknown> | null;
  sizes: CompositionSizeEntry[];
};

export type CompositionFactorWeight = {
  factor_id: string;
  expression: string | null;
  preprocessed_expression: string | null;
  weight: number;
  applied_to: string;
  preprocess: Record<string, unknown>;
  marginal: Record<string, unknown> | null;
  metrics: CompositionMetrics & Record<string, unknown>;
  direction: number | null;
  training_ic: number | null;
  direction_source: string | null;
  effective_expression: string | null;
};

export type CompositionContribution = {
  factor_id: string;
  zscore: number;
  weight: number;
  contribution: number;
};

export type CompositionScreenRow = {
  rank: number;
  code: string;
  name?: string | null;
  composite_score: number;
  selected: boolean;
  rank_selected: boolean;
  target_weight: number;
  status: "buyable" | "pending_next_open" | "blocked" | "not_selected" | string;
  blocked_reason: string | null;
  signal_date: string | null;
  signal_ifsuspend: number | null;
  signal_if_up: number | null;
  execution_date: string | null;
  next_open: number | null;
  next_ifsuspend: number | null;
  next_if_up: number | null;
  buyable_next_open: boolean | null;
  contributions: CompositionContribution[];
};

export type CompositionScreenFactor = {
  factor_id: string;
  expression: string | null;
  preprocessed_expression: string | null;
  weight: number;
  training_ic: number | null;
  direction: number | null;
};

export type CompositionScreen = CompositionScreenSummary & {
  panel_end_date: string | null;
  top_k: number;
  max_weight_per_stock: number;
  planned_weight_per_stock: number;
  factors: CompositionScreenFactor[];
  rows: CompositionScreenRow[];
  returned_rows: number;
  total_returned_rows: number;
};

export type FactorCompositionDetail = {
  composition_id: string;
  pool_id: string;
  size: number;
  available_sizes: number[];
  manifest: CompositionManifest;
  result: CompositionSizeEntry;
  weights: CompositionFactorWeight[];
};

export type CompositionScreenResponse = {
  composition_id: string;
  pool_id: string;
  size: number;
  screen: CompositionScreen;
};

export type CompositionSummary = {
  composition_id: string;
  pool_id: string;
  created_at: string | null;
  /** 历史产物兼容字段：新组合恒为 "equal" */
  weight_method?: string | null;
  candidate_count: number | null;
  selected_count: number | null;
  completed_sizes: number[];
  default_size: number | null;
  z_clip: number | null;
  source_factor_run_ids: string[];
  mutual_ic_threshold: number | null;
};

export const compositionApi = {
  createFactorComposition: (payload: FactorCompositionRequest) =>
    apiPost<FactorCompositionResponse>("/api/factor-compositions", payload),
  factorCompositions: (poolId?: string, limit = 50) =>
    apiGet<{ total: number; compositions: CompositionSummary[] }>(
      withQuery("/api/factor-compositions", { pool_id: poolId, limit }),
    ),
  factorComposition: (poolId: string, compositionId: string, size?: number) =>
    apiGet<FactorCompositionDetail>(
      withQuery(`/api/factor-compositions/${encodeURIComponent(compositionId)}`, {
        pool_id: poolId,
        size,
      }),
    ),
  factorCompositionScreen: (poolId: string, compositionId: string, size?: number, limit = 200) =>
    apiGet<CompositionScreenResponse>(
      withQuery(`/api/factor-compositions/${encodeURIComponent(compositionId)}/screen`, {
        pool_id: poolId,
        size,
        limit,
      }),
    ),
};
