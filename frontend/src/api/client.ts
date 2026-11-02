/**
 * 后端 API 客户端（对应 backend/api/main.py 的查询端点与建池 POST）。
 * 页面只从这里取真实数据；尚未接入的任务/用户模块仍用 mockData。
 */
import { useCallback, useEffect, useRef, useState } from "react";

/* ---------- 类型（与后端返回结构一一对应） ---------- */

export type MasterInfo = {
  ready: boolean;
  /** clickhouse = 股票池、因子与回测都直接读公司库 */
  data_source?: string;
  store_dir: string;
  rows: number | null;
  n_stocks: number | null;
  date_min: string | null;
  date_max: string | null;
  layout: string | null;
  source_signature: string | null;
  n_fields: number;
  fields: string[];
  /** 实时端点：是否命中服务端缓存 / 数据对应的查询时刻 */
  cached?: boolean;
  queried_at?: string | null;
};

export type FieldStatus = "usable" | "pending" | "unavailable";

export type FieldInfo = {
  name: string;
  dtype: string | null;
  source: string;
  description: string;
  /** 该字段能否在因子 / 回测面板（公司库）中使用 */
  panel?: boolean;
  /** 能否直接作为因子表达式的操作数（= status 为 usable） */
  expression?: boolean;
  category?: string;
  status?: FieldStatus;
  /** 面板里的列名（如 fund_ROE / val_PB）；没有则为 null */
  panel_alias?: string | null;
  /** 库里是否能找到该列；离线时为 null */
  found_in_db?: boolean | null;
  /** flow=累计流量，flow_q=单季流量，stock=时点值，ratio=比率 */
  period_type?: "flow" | "flow_q" | "stock" | "ratio" | null;
  /** 单季字段的来源累计字段 */
  derived_from?: string | null;
};

export type StockInfo = {
  code: string;
  /** 股票简称（来自 dim.stock_main_info_fd；库里没有则为 null） */
  name?: string | null;
  rows: number;
  start_date: string;
  end_date: string;
  latest_date: string;
  latest_close: number | null;
  latest_volume: number | null;
  latest_amount: number | null;
  /** 以下字段来自 dim.stock_main_info_fd（/api/data/stocks 与候选池共用） */
  industry?: string | null;
  /** 申万一级行业代码（industry 是名称） */
  industry_code?: string | null;
  sector?: string | null;
  listed_state?: string | null;
  listed_date?: string | null;
  latest_ifsuspend?: number | null;
};

export type UniverseOption = { value: string; label: string; count: number };

export type UniverseOptions = {
  total: number;
  industries: UniverseOption[];
  exchanges: UniverseOption[];
  boards: UniverseOption[];
  sectors: UniverseOption[];
  listed_states: UniverseOption[];
  missing: Record<string, number>;
  /** clickhouse = 候选直接来自公司库 */
  data_source?: string;
  ready?: boolean;
  cached: boolean;
  queried_at: string | null;
};

export type UniverseStock = {
  code: string;
  name: string | null;
  industry: string | null;
  /** 申万一级行业代码（industry 是名称） */
  industry_code: string | null;
  exchange: string;
  exchange_label: string;
  board: string;
  board_label: string;
  sector: string | null;
  listed_state: string | null;
  listed_date: string | null;
  rows: number;
  start_date: string;
  end_date: string;
  latest_date: string;
  latest_close: number | null;
  latest_volume: number | null;
  latest_amount: number | null;
  latest_ifsuspend: number | null;
};

export type UniverseStocks = {
  total: number;
  matched_total: number;
  items: UniverseStock[];
  data_source?: string;
  as_of: string;
  cached: boolean;
  queried_at: string | null;
};

export type UniverseQuery = {
  industries?: string[];
  exchanges?: string[];
  boards?: string[];
  sectors?: string[];
  listed_states?: string[];
  q?: string;
  min_listed_days?: number;
  as_of?: string;
  limit?: number;
  offset?: number;
};

export type UniverseCodes = {
  codes: string[];
  total: number;
  matched_total: number;
  data_source?: string;
  as_of: string;
  cached: boolean;
  queried_at: string | null;
};

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

export type JobStatus = {
  job_id: string;
  operation?: string;
  status: "queued" | "running" | "finished" | "failed" | "missing" | string;
  message?: string;
  updated_at?: string;
  result?: Record<string, unknown> | null;
  progress?: Record<string, unknown> | null;
  traceback?: string | null;
};

export type OperatorInfo = {
  name: string;
  category: string;
  category_cn: string;
  canonical_name: string;
  description_cn: string;
  example: string;
  generation_enabled: boolean;
  manual_enabled: boolean;
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

export type ResultMetrics = {
  annual: number | null;
  sharpe: number | null;
  drawdown: number | null;
  turnover: number | null;
  cost: number | null;
  winRate: number | null;
};

export type EquityPoint = { date: string; equity: number; drawdown: number };
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

/* ---------- 因子运行 / 因子批量回测 ---------- */

export type FactorRunSummary = {
  run_id: string;
  pool_id: string | null;
  source_signature: string | null;
  runtime_id: string | null;
  created_at: string | null;
  accepted_count: number;
  attempts: number | null;
  target_reached: boolean | null;
  attempts_exhausted: boolean | null;
  factor_run_dir: string;
  has_accepted: boolean;
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
};

export type FactorRunDetail = FactorRunSummary & {
  manifest: Record<string, unknown>;
  accepted_factors: AcceptedFactor[];
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
  /** 以下参数后端暂未消费，先随请求透传 */
  rebalance_freq?: string;
  commission?: number;
  stamp_duty?: number;
  max_drawdown_control?: number;
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

/* ---------- 手动回测 ---------- */

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

/* ---------- 请求封装 ---------- */

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readResponse<T>(response: Response, path: string): Promise<T> {
  if (!response.ok) {
    // 后端用 detail 传中文原因（如「未配置 ClickHouse 密码」「需要在公司网络环境下访问」），
    // 必须带出来，否则页面只剩一个 HTTP 状态码
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      // 响应体不是 JSON：保留状态码信息即可
    }
    throw new ApiError(
      `请求 ${path} 失败（HTTP ${response.status}）${detail ? `：${detail}` : ""}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

async function apiGet<T>(path: string): Promise<T> {
  // 后端改了响应结构时，避免浏览器拿旧的 GET 缓存（HMR 不会重新触发已挂载的请求）。
  const response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  return readResponse<T>(response, path);
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<T>(response, path);
}

async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  return readResponse<T>(response, path);
}

function withQuery(path: string, params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== "") search.append(key, String(item));
      }
    } else {
      search.set(key, String(value));
    }
  }
  return search.size > 0 ? `${path}?${search.toString()}` : path;
}

export const api = {
  master: () => apiGet<MasterInfo>("/api/data/master"),
  fields: () => apiGet<{
    total: number;
    fields: FieldInfo[];
    offline?: boolean;
    metadata_error?: string | null;
    status_counts?: Record<FieldStatus, number>;
  }>("/api/data/fields"),
  stocks: (params: { q?: string; limit?: number; offset?: number } = {}) =>
    apiGet<{ total: number; total_rows: number; n_stocks_all: number; items: StockInfo[] }>(
      withQuery("/api/data/stocks", params),
    ),
  operators: () => apiGet<{ total: number; operators: OperatorInfo[] }>("/api/operators"),
  universeOptions: () => apiGet<UniverseOptions>("/api/universe/options"),
  universeStocks: (params: UniverseQuery = {}) =>
    apiGet<UniverseStocks>(withQuery("/api/universe/stocks", params)),
  universeCodes: (params: UniverseQuery = {}) =>
    apiGet<UniverseCodes>(withQuery("/api/universe/codes", params)),
  createPool: (payload: PoolCreateRequest) => apiPost<PoolCreateResponse>("/api/pools", payload),
  job: (jobId: string) => apiGet<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`),
  pools: () => apiGet<{ total: number; pools: PoolInfo[]; storage?: string }>("/api/pools"),
  pool: (poolId: string) => apiGet<PoolDetail>(`/api/pools/${encodeURIComponent(poolId)}`),
  deletePool: (poolId: string) =>
    apiDelete<PoolDeleteResponse>(
      withQuery(`/api/pools/${encodeURIComponent(poolId)}`, { confirm: "true" }),
    ),
  results: () => apiGet<{ total: number; results: ResultSummary[] }>("/api/results"),
  result: (runKey: string) => apiGet<ResultDetail>(withQuery("/api/results/detail", { run_key: runKey })),
  factorRuns: (poolId?: string) =>
    apiGet<{ total: number; runs: FactorRunSummary[] }>(withQuery("/api/factor-runs", { pool_id: poolId })),
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
  createManualBacktest: (payload: ManualBacktestRequest) =>
    apiPost<ManualBacktestResponse>("/api/manual-backtests", payload),
};

export function resultFileUrl(runKey: string, fileName: string): string {
  return withQuery("/api/results/file", { run_key: runKey, file_name: fileName });
}

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

/* ---------- 通用加载 Hook ---------- */

export type ApiState<T> = { data: T | null; loading: boolean; error: string | null; reload: () => void };

export function useApiData<T>(loader: () => Promise<T>, deps: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    loaderRef.current()
      .then((value) => { if (alive) { setData(value); setLoading(false); } })
      .catch((err: unknown) => {
        if (alive) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, loading, error, reload };
}

/* ---------- 后台任务轮询 Hook ---------- */

export type JobPollingState = {
  job: JobStatus | null;
  error: string | null;
  /** queued / running 期间为 true */
  polling: boolean;
};

/**
 * 轮询建池任务；返回 queued/running 状态并持续查询，
 * finished/failed/missing 后自动停止（不会无限打后端）。
 */
export function useJobPolling(jobId: string | null, intervalMs = 1500): JobPollingState {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setError(null);
      setPolling(false);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setJob(null);
    setError(null);
    setPolling(true);

    const tick = () => {
      api
        .job(jobId)
        .then((status) => {
          if (!alive) return;
          setJob(status);
          setError(null);
          if (status.status === "queued" || status.status === "running") {
            timer = setTimeout(tick, intervalMs);
          } else {
            setPolling(false);
          }
        })
        .catch((err: unknown) => {
          if (!alive) return;
          setError(err instanceof Error ? err.message : String(err));
          setPolling(false);
        });
    };

    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { job, error, polling };
}
