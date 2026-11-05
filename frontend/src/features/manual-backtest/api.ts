import { apiPost } from "../../shared/api/base";

export type ManualBacktestRequest = {
  expression: string;
  pool_id: string;
  run_name: string;
  /** 省略时后端取股票池选样窗口 */
  start_date?: string;
  end_date?: string;
  top_k?: number;
  initial_cash?: number;
  buy_cost?: number;
  sell_cost?: number;
  slippage?: number;
  min_cost?: number;
  max_weight_per_stock?: number;
};

export type ManualBacktestResponse = {
  job_id: string;
  status: string;
  operation: string;
  pool_id: string;
  /** clickhouse = 公司库池；local = 旧本地池 */
  data_source: string;
  run_name: string;
  expression: string;
  warnings: string[];
  request_summary: Record<string, unknown>;
};

export const manualApi = {
  createManualBacktest: (payload: ManualBacktestRequest) =>
    apiPost<ManualBacktestResponse>("/api/manual-backtests", payload),
};
