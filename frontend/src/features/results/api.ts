import { apiGet, withQuery } from "../../shared/api/base";

export type ResultMetrics = {
  annual: number | null;
  sharpe: number | null;
  drawdown: number | null;
  turnover: number | null;
  cost: number | null;
  winRate: number | null;
};

export type EquityPoint = { date: string; equity: number; drawdown: number; benchmark_equity?: number; relative_equity?: number; excess_return_pp?: number };
export type YearlyDatum = { year: string; returns: number; sharpe: number; drawdown: number; turnover: number; cost: number; winRate: number };

export type ResultSummary = {
  run_name: string;
  /** 结果相对路径，MySQL 主键；嵌套因子结果必须用它打开 */
  run_key: string;
  created_at: string | null;
  result_type: string | null;
  canonical_expression: string | null;
  pool_id: string | null;
  factor_run_id?: string | null;
  backtest_id?: string | null;
  /** 手动回测记录的数据源签名，如 clickhouse:dws.ll_stock_daily_sharing */
  data_source?: string | null;
  summary: Record<string, number | null>;
  start_date: string | null;
  end_date: string | null;
  top_k: number | null;
  initial_cash: number | null;
};

export type ResultFile = { name: string; size: number; updated_at: string };

export type ResultDetail = {
  run_name: string;
  run_key: string;
  created_at: string | null;
  result_type: string | null;
  canonical_expression: string | null;
  pool_id: string | null;
  factor_run_id?: string | null;
  backtest_id?: string | null;
  /** 数据源签名；手动回测写入，旧结果可能为空 */
  data_source?: string | null;
  config: Record<string, unknown>;
  summary: Record<string, number | null>;
  metrics: ResultMetrics;
  equity: EquityPoint[];
  yearly: YearlyDatum[];
  files: ResultFile[];
};

export const resultApi = {
  results: () => apiGet<{ total: number; results: ResultSummary[] }>("/api/results"),
  result: (runKey: string) => apiGet<ResultDetail>(withQuery("/api/results/detail", { run_key: runKey })),
};

export function resultFileUrl(runKey: string, fileName: string): string {
  return withQuery("/api/results/file", { run_key: runKey, file_name: fileName });
}
