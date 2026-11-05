import { apiDelete, apiGet, apiPost, withQuery } from "../../shared/api/base";

export type PoolProvenance = {
  source?: string;
  daily_table?: string;
  dim_table?: string;
  endpoint?: string;
  queried_at?: string;
  as_of?: string;
  filters?: Record<string, unknown>;
  universe_total?: number;
  matched_total?: number;
  /** all = 使用全部匹配候选；manual = 预览表格手动勾选 */
  selection_mode?: string;
  selected_total?: number;
};

export type PoolCreateRequest = {
  name: string;
  selection_start: string;
  selection_end: string;
  industries?: string[];
  exchanges?: string[];
  boards?: string[];
  sectors?: string[];
  listed_states?: string[];
  q?: string;
  min_listed_days?: number;
  top_n?: number | null;
  min_coverage?: number;
  exclude_suspended?: boolean;
  overwrite?: boolean;
  /** 预览表格手动勾选的代码；省略 = 使用全部匹配候选 */
  selected_codes?: string[];
};

export type PoolCreateResponse = {
  job_id: string;
  status: string;
  operation: string;
  warnings: string[];
  request_summary: {
    name: string;
    selection_start: string;
    selection_end: string;
    filters: Record<string, unknown>;
    top_n: number | null;
    min_coverage: number;
    exclude_suspended: boolean;
    matched_total: number;
    selection_mode?: string;
    selected_total?: number;
    universe_queried_at: string;
  };
};

export type PoolInfo = {
  pool_id: string;
  name: string;
  /** clickhouse = 该池按公司库选样；local = 旧本地缓存池 */
  data_source?: string;
  n_stocks: number;
  selection_start: string;
  selection_end: string;
  top_n: number | null;
  min_listed_days: number;
  min_coverage: number;
  exclude_suspended: boolean;
  category: string | null;
  market_code: string | null;
  source_signature: string | null;
  selection_days: number | null;
  coverage: number | null;
  avg_amount: number | null;
  created_at: string;
  status: string;
  strict_top_n?: boolean | null;
  provenance?: PoolProvenance | null;
  /** 该池的存储来源：MySQL / MySQL+本地文件 / 仅本地文件 */
  storage?: "mysql" | "mysql+local" | "local";
};

export type PoolDetail = PoolInfo & {
  requested_codes: string[] | null;
  minimum_valid_rows: number | null;
  codes: string[];
};

export type PoolDeleteResponse = {
  pool_id: string;
  deleted_local: boolean;
  deleted_mysql: boolean;
  mysql_configured: boolean;
  /** 未随池删除的引用（因子运行 / 历史回测）与 MySQL 离线提示 */
  warnings: string[];
};

export const poolApi = {
  createPool: (payload: PoolCreateRequest) => apiPost<PoolCreateResponse>("/api/pools", payload),
  pools: () => apiGet<{ total: number; pools: PoolInfo[]; storage?: string }>("/api/pools"),
  pool: (poolId: string) => apiGet<PoolDetail>(`/api/pools/${encodeURIComponent(poolId)}`),
  deletePool: (poolId: string) =>
    apiDelete<PoolDeleteResponse>(
      withQuery(`/api/pools/${encodeURIComponent(poolId)}`, { confirm: "true" }),
    ),
};
