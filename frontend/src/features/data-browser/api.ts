import { apiGet, withQuery } from "../../shared/api/base";

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
  /** flow=累计流量，flow_q=单季流量，stock=时点值，ratio=比率，daily=日频，derived=派生指标 */
  period_type?: "flow" | "flow_q" | "stock" | "ratio" | "daily" | "derived" | null;
  /** 二级业务主题，例如 利润表/盈利能力、成长能力、偿债能力 */
  theme?: string | null;
  /** 单位，例如 元、元/股、%、倍、天 */
  unit?: string | null;
  /** 量纲，例如 money、price、percent、ratio、shares、count */
  dimension?: string | null;
  /** 是否为 _q 派生字段 */
  derived?: boolean;
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

export type OperatorInfo = {
  name: string;
  category: string;
  category_cn: string;
  canonical_name: string;
  description_cn: string;
  example: string;
  generation_enabled: boolean;
  manual_enabled: boolean;
  /** 该 canonical 算子兼容的别名，例如 sub 的 subtract/Sub */
  aliases?: string[];
};

export const dataApi = {
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
};
