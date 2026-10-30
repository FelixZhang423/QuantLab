import type { Task } from "./mockData";

/* ---------- 数据字段（master 精选 40 + 全量文档样例） ---------- */

export type FieldItem = { name: string; label: string; category: string; source: string };

const MASTER_FIELDS: [string, string, string][] = [
  ["open", "开盘价", "行情"], ["close", "收盘价", "行情"], ["high", "最高价", "行情"], ["low", "最低价", "行情"],
  ["ycp", "昨收价", "行情"], ["volume", "成交量（手）", "行情"], ["amount", "成交额（元）", "行情"],
  ["ChangePCT", "涨跌幅", "行情"], ["RangePCT", "振幅", "行情"], ["TurnoverRate", "换手率", "行情"],
  ["Ifsuspend", "是否停牌", "状态"], ["if_up", "是否上涨", "状态"], ["if_flat", "是否平盘", "状态"], ["if_down", "是否下跌", "状态"],
  ["RisingUpDays", "连涨天数", "趋势形态"], ["FallingDownDays", "连跌天数", "趋势形态"],
  ["MaxRisingUpDays", "最大连涨天数", "趋势形态"], ["MaxFallingDownDays", "最大连跌天数", "趋势形态"],
  ["HighestPrice", "区间最高价", "趋势形态"], ["LowestPrice", "区间最低价", "趋势形态"],
  ["ema12", "12 日指数均线", "技术指标"], ["ema26", "26 日指数均线", "技术指标"],
  ["dif", "MACD 快线 DIF", "技术指标"], ["dea", "MACD 慢线 DEA", "技术指标"], ["macd", "MACD 柱值", "技术指标"],
  ["max_high_9", "9 日最高价", "技术指标"], ["min_low_9", "9 日最低价", "技术指标"],
  ["RSV", "KDJ 未成熟随机值", "技术指标"], ["kdj_k", "KDJ K 值", "技术指标"], ["kdj_d", "KDJ D 值", "技术指标"], ["kdj_j", "KDJ J 值", "技术指标"],
  ["ma4", "4 日均线", "技术指标"], ["ma5", "5 日均线", "技术指标"], ["ma8", "8 日均线", "技术指标"],
  ["ma12", "12 日均线", "技术指标"], ["ma16", "16 日均线", "技术指标"], ["ma20", "20 日均线", "技术指标"], ["ma47", "47 日均线", "技术指标"],
];

const EXTRA_FIELDS: [string, string, string][] = [
  ["code", "股票代码", "基础"], ["date", "交易日期", "基础"],
  ["industry", "行业代码", "基本面"], ["pe_ttm", "市盈率（TTM）", "基本面"], ["pb", "市净率", "基本面"],
  ["total_mv", "总市值（元）", "基本面"], ["float_mv", "流通市值（元）", "基本面"],
  ["revenue", "营业收入（元）", "基本面"], ["roe", "净资产收益率", "基本面"],
];

export const fieldsData: FieldItem[] = [
  ...MASTER_FIELDS.map(([name, label, category]) => ({ name, label, category, source: "master 精选" })),
  ...EXTRA_FIELDS.map(([name, label, category]) => ({ name, label, category, source: "全量文档" })),
];

/* ---------- 股票列表（确定性生成，15 只真实代码 + 185 只模拟） ---------- */

export type StockItem = { code: string; name: string; rows: number; lastClose: number; lastVolume: number; lastAmount: number };

const KNOWN_STOCKS: [string, string][] = [
  ["000001", "平安银行"], ["000002", "万科A"], ["000725", "京东方A"], ["000858", "五粮液"], ["002594", "比亚迪"],
  ["300059", "东方财富"], ["300750", "宁德时代"], ["600030", "中信证券"], ["600036", "招商银行"], ["600276", "恒瑞医药"],
  ["600519", "贵州茅台"], ["601012", "隆基绿能"], ["601318", "中国平安"], ["601398", "工商银行"], ["688981", "中芯国际"],
];

const PREFIXES = ["6001", "6002", "6003", "6030", "0006", "0007", "0020", "0023", "3000", "3001", "6880"];

function makeStock(code: string, name: string, i: number): StockItem {
  const rows = 800 + ((i * 137) % 420);
  const lastClose = 4 + ((i * 37) % 170) + ((i * 13) % 97) / 100;
  const lastVolume = 100000 + ((i * 511) % 900000);
  return { code, name, rows, lastClose: Number(lastClose.toFixed(2)), lastVolume, lastAmount: Number((lastVolume * lastClose).toFixed(0)) };
}

export const stocksData: StockItem[] = [
  ...KNOWN_STOCKS.map(([code, name], i) => makeStock(code, name, i)),
  ...Array.from({ length: 185 }, (_, i) => {
    const prefix = PREFIXES[i % PREFIXES.length];
    const code = `${prefix}${String(Math.floor(i / PREFIXES.length) + 1).padStart(2, "0")}`;
    return makeStock(code, `模拟股票${code}`, i + 20);
  }),
];

/* ---------- 股票池 ---------- */

export type PoolItem = {
  pool_id: string; name: string; n_stocks: number;
  selection_start: string; selection_end: string;
  min_listed_days: number; min_coverage: number; exclude_suspended: boolean;
  coverage: number; avg_amount: number; created_at: string; status: "active";
};

export const poolsData: PoolItem[] = [
  {
    pool_id: "liquid_500_864dc25f", name: "liquid_500", n_stocks: 500,
    selection_start: "2021-06-18", selection_end: "2024-07-26",
    min_listed_days: 250, min_coverage: 0.9, exclude_suspended: true,
    coverage: 0.962, avg_amount: 1.86e8, created_at: "2026-06-16 07:11", status: "active",
  },
];

/* ---------- 因子生成运行与合格因子 ---------- */

export const factorRunOptions = [
  { value: "ppo_run_100", label: "ppo_run_100 · 24 个合格因子 · 2026-06-15", factorCount: 24 },
];

export type FactorItem = { id: string; expression: string; ic: number; rank_ic: number; icir: number; coverage: number; score: number };

export const acceptedFactors: FactorItem[] = [
  { id: "f_001", expression: "ts_rank(close, 20) - rank(TurnoverRate)", ic: 0.047, rank_ic: 0.052, icir: 1.21, coverage: 0.987, score: 0.74 },
  { id: "f_002", expression: "close / ts_mean(close, 20) - 1", ic: 0.039, rank_ic: 0.045, icir: 1.05, coverage: 0.993, score: 0.68 },
  { id: "f_003", expression: "ts_corr(close, volume, 10)", ic: 0.034, rank_ic: 0.038, icir: 0.92, coverage: 0.962, score: 0.61 },
  { id: "f_004", expression: "ts_std_dev(ChangePCT, 20)", ic: 0.031, rank_ic: 0.036, icir: 0.87, coverage: 0.971, score: 0.58 },
  { id: "f_005", expression: "rank(amount) - ts_delay(rank(amount), 5)", ic: 0.028, rank_ic: 0.033, icir: 0.79, coverage: 0.984, score: 0.55 },
  { id: "f_006", expression: "ts_zscore(close, 60)", ic: 0.026, rank_ic: 0.031, icir: 0.74, coverage: 0.995, score: 0.53 },
  { id: "f_007", expression: "ts_decay_linear(close, 12)", ic: 0.024, rank_ic: 0.029, icir: 0.68, coverage: 0.976, score: 0.51 },
  { id: "f_008", expression: "ts_delta(volume, 5) / ts_mean(volume, 5)", ic: 0.023, rank_ic: 0.027, icir: 0.62, coverage: 0.958, score: 0.48 },
  { id: "f_009", expression: "rank(ema12 - ema26)", ic: 0.022, rank_ic: 0.026, icir: 0.59, coverage: 0.989, score: 0.46 },
  { id: "f_010", expression: "-rank(RisingUpDays)", ic: 0.021, rank_ic: 0.024, icir: 0.55, coverage: 0.944, score: 0.44 },
  { id: "f_011", expression: "ts_corr(ChangePCT, TurnoverRate, 20)", ic: 0.019, rank_ic: 0.022, icir: 0.48, coverage: 0.965, score: 0.41 },
  { id: "f_012", expression: "ts_quantile(close, 20, 0.25)", ic: 0.017, rank_ic: 0.02, icir: 0.42, coverage: 0.972, score: 0.38 },
];

/** 生成页模拟结果：8 个有效性指标，判定由页面按阈值计算。 */
export type GeneratedFactor = {
  id: string;
  expression: string;
  ic: number;
  rank_ic: number;
  icir: number;
  coverage: number;
  score: number;
  valid_ic: number;
  valid_icir: number;
  valid_days: number;
};

export const generatedFactors: GeneratedFactor[] = [
  { id: "f_001", expression: "ts_rank(close, 20) - rank(TurnoverRate)", ic: 0.062, rank_ic: 0.068, icir: 1.35, coverage: 0.987, score: 0.81, valid_ic: 0.055, valid_icir: 1.12, valid_days: 242 },
  { id: "f_002", expression: "close / ts_mean(close, 20) - 1", ic: 0.058, rank_ic: 0.063, icir: 1.22, coverage: 0.993, score: 0.77, valid_ic: 0.049, valid_icir: 1.05, valid_days: 240 },
  { id: "f_003", expression: "ts_corr(close, volume, 10)", ic: 0.054, rank_ic: 0.059, icir: 1.11, coverage: 0.962, score: 0.71, valid_ic: 0.046, valid_icir: 0.98, valid_days: 238 },
  { id: "f_004", expression: "ts_std_dev(ChangePCT, 20)", ic: 0.052, rank_ic: 0.056, icir: 1.03, coverage: 0.971, score: 0.66, valid_ic: 0.038, valid_icir: 0.91, valid_days: 236 },
  { id: "f_005", expression: "rank(amount) - ts_delay(rank(amount), 5)", ic: 0.057, rank_ic: 0.061, icir: 1.08, coverage: 0.984, score: 0.69, valid_ic: 0.048, valid_icir: 0.95, valid_days: 241 },
  { id: "f_006", expression: "ts_zscore(close, 60)", ic: 0.051, rank_ic: 0.055, icir: 0.99, coverage: 0.995, score: 0.63, valid_ic: 0.044, valid_icir: 0.88, valid_days: 235 },
  { id: "f_007", expression: "ts_decay_linear(close, 12)", ic: 0.048, rank_ic: 0.052, icir: 0.93, coverage: 0.976, score: 0.59, valid_ic: 0.041, valid_icir: 0.83, valid_days: 234 },
  { id: "f_008", expression: "ts_delta(volume, 5) / ts_mean(volume, 5)", ic: 0.056, rank_ic: 0.06, icir: 1.06, coverage: 0.958, score: 0.67, valid_ic: 0.047, valid_icir: 0.93, valid_days: 239 },
  { id: "f_009", expression: "rank(ema12 - ema26)", ic: 0.053, rank_ic: 0.057, icir: 1.01, coverage: 0.989, score: 0.64, valid_ic: 0.043, valid_icir: 0.9, valid_days: 237 },
  { id: "f_010", expression: "-rank(RisingUpDays)", ic: 0.052, rank_ic: 0.056, icir: 0.47, coverage: 0.944, score: 0.43, valid_ic: 0.042, valid_icir: 0.52, valid_days: 230 },
  { id: "f_011", expression: "ts_corr(ChangePCT, TurnoverRate, 20)", ic: 0.051, rank_ic: 0.055, icir: 0.72, coverage: 0.965, score: 0.52, valid_ic: 0.041, valid_icir: 0.7, valid_days: 232 },
  { id: "f_012", expression: "ts_quantile(close, 20, 0.25)", ic: 0.055, rank_ic: 0.059, icir: 1.04, coverage: 0.912, score: 0.61, valid_ic: 0.044, valid_icir: 0.86, valid_days: 228 },
];

export type FactorBtRow = { expression: string; annual: number; sharpe: number; drawdown: number; turnover: number; cost: number };

export const factorBacktestSummary: FactorBtRow[] = [
  { expression: "ts_rank(close, 20) - rank(TurnoverRate)", annual: 21.35, sharpe: 1.52, drawdown: -9.8, turnover: 38.6, cost: 0.72 },
  { expression: "close / ts_mean(close, 20) - 1", annual: 18.94, sharpe: 1.39, drawdown: -10.2, turnover: 35.4, cost: 0.65 },
  { expression: "ts_corr(close, volume, 10)", annual: 15.27, sharpe: 1.21, drawdown: -11.6, turnover: 33.1, cost: 0.6 },
  { expression: "ts_std_dev(ChangePCT, 20)", annual: 12.68, sharpe: 1.05, drawdown: -12.9, turnover: 30.8, cost: 0.57 },
  { expression: "rank(amount) - ts_delay(rank(amount), 5)", annual: 9.41, sharpe: 0.87, drawdown: -14.3, turnover: 36.2, cost: 0.69 },
  { expression: "ts_zscore(close, 60)", annual: 7.15, sharpe: 0.68, drawdown: -16.8, turnover: 27.5, cost: 0.51 },
];

/* ---------- 操作符（Brain 风格，与主平台 operator_registry 一致） ---------- */

export type OperatorItem = { name: string; category: string; description: string };

const OPS: [string, string, string][] = [
  ["abs", "arithmetic", "绝对值"], ["add", "arithmetic", "加法"], ["densify", "arithmetic", "缺失值填充"],
  ["divide", "arithmetic", "除法"], ["inverse", "arithmetic", "倒数"], ["log", "arithmetic", "自然对数"],
  ["max", "arithmetic", "取较大值"], ["min", "arithmetic", "取较小值"], ["multiply", "arithmetic", "乘法"],
  ["power", "arithmetic", "幂运算"], ["reverse", "arithmetic", "时序反转"], ["sign", "arithmetic", "符号函数"],
  ["signed_power", "arithmetic", "带符号幂"], ["sqrt", "arithmetic", "平方根"], ["subtract", "arithmetic", "减法"],
  ["normalize", "cross_section", "截面归一化"], ["quantile", "cross_section", "截面分位数"], ["rank", "cross_section", "截面排名"],
  ["scale", "cross_section", "截面缩放"], ["winsorize", "cross_section", "截面缩尾"], ["zscore", "cross_section", "截面标准化"],
  ["group_backfill", "group", "分组回填"], ["group_mean", "group", "分组均值"], ["group_neutralize", "group", "分组中性化"],
  ["group_rank", "group", "分组排名"], ["group_scale", "group", "分组缩放"], ["group_zscore", "group", "分组标准化"],
  ["equal", "logic", "相等判断"], ["greater", "logic", "大于判断"], ["greater_equal", "logic", "大于等于判断"],
  ["if_else", "logic", "条件分支"], ["is_nan", "logic", "缺失值判断"], ["less", "logic", "小于判断"],
  ["less_equal", "logic", "小于等于判断"], ["not_equal", "logic", "不等判断"], ["where", "logic", "条件选择"],
  ["and_", "logic", "逻辑与（表达式内 and 的别名）"], ["or_", "logic", "逻辑或（表达式内 or 的别名）"], ["not_", "logic", "逻辑非（表达式内 not 的别名）"],
  ["days_from_last_change", "time_series", "距上次变化天数"], ["hump", "time_series", "驼峰衰减加权"],
  ["kth_element", "time_series", "窗口内第 K 个元素"], ["last_diff_value", "time_series", "最后差分值"],
  ["ts_arg_max", "time_series", "时序最大值位置"], ["ts_arg_min", "time_series", "时序最小值位置"],
  ["ts_av_diff", "time_series", "平均差分"], ["ts_backfill", "time_series", "时序回填"],
  ["ts_corr", "time_series", "时序相关系数"], ["ts_count_nans", "time_series", "时序缺失计数"],
  ["ts_covariance", "time_series", "时序协方差"], ["ts_decay_linear", "time_series", "线性衰减加权"],
  ["ts_delay", "time_series", "滞后取值"], ["ts_delta", "time_series", "差分"], ["ts_mean", "time_series", "时序均值"],
  ["ts_product", "time_series", "时序乘积"], ["ts_quantile", "time_series", "时序分位数"], ["ts_rank", "time_series", "时序排名"],
  ["ts_regression", "time_series", "时序回归残差"], ["ts_scale", "time_series", "时序缩放"], ["ts_std_dev", "time_series", "时序标准差"],
  ["ts_step", "time_series", "阶跃函数"], ["ts_sum", "time_series", "时序求和"], ["ts_zscore", "time_series", "时序标准化"],
  ["bucket", "transformational", "分桶"], ["trade_when", "transformational", "条件交易"],
  ["vec_avg", "vector", "向量均值"], ["vec_sum", "vector", "向量求和"],
];

const CATEGORY_LABELS: Record<string, string> = {
  arithmetic: "算术", cross_section: "截面", group: "分组", logic: "逻辑", time_series: "时序", transformational: "变换", vector: "向量",
};

export const operatorsData: OperatorItem[] = OPS.map(([name, category, description]) => ({ name, category: CATEGORY_LABELS[category] ?? category, description }));

/* ---------- 因子生成运行摘要 ---------- */

export const generationSummary = {
  runId: "ppo_run_100", taskId: 1026, attempts: 3842, accepted: 24, bestIcir: 1.21, bestScore: 0.74, duration: "18m32s",
};

/* ---------- 因子组合结果 ---------- */

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

/* ---------- 系统管理：用户与审计 ---------- */

export type UserRole = "研究员" | "管理员";

export type UserItem = {
  username: string; name: string; role: UserRole; email: string; lastLogin: string; enabled: boolean; service?: boolean;
};

export const usersData: UserItem[] = [
  { username: "admin", name: "系统管理员", role: "管理员", email: "admin@quantlab.cn", lastLogin: "2026-10-07 09:12", enabled: true },
  { username: "system", name: "系统服务账号", role: "管理员", email: "system@quantlab.local", lastLogin: "2026-10-07 06:30", enabled: true, service: true },
  { username: "lin", name: "林研究员", role: "研究员", email: "lin@quantlab.cn", lastLogin: "2026-10-07 08:47", enabled: true },
  { username: "zhou", name: "周研究员", role: "研究员", email: "zhou@quantlab.cn", lastLogin: "2026-10-07 08:05", enabled: true },
  { username: "zhang", name: "张研究员", role: "研究员", email: "zhang@quantlab.cn", lastLogin: "2026-10-06 17:15", enabled: true },
  { username: "chen", name: "陈研究员", role: "研究员", email: "chen@quantlab.cn", lastLogin: "2026-10-06 14:28", enabled: true },
  { username: "wang", name: "王研究员", role: "研究员", email: "wang@quantlab.cn", lastLogin: "2026-09-28 11:02", enabled: false },
];

export type AuditItem = { id: number; time: string; user: string; action: string; target: string; detail: string; ip: string };

export const auditData: AuditItem[] = [
  { id: 1, time: "2026-10-07 09:12:04", user: "admin", action: "login", target: "—", detail: "管理员登录成功", ip: "192.168.1.15" },
  { id: 2, time: "2026-10-07 08:47:33", user: "lin", action: "login", target: "—", detail: "研究员登录成功", ip: "192.168.1.23" },
  { id: 3, time: "2026-10-07 08:12:45", user: "zhou", action: "task_submit", target: "#1031", detail: "提交因子生成任务 ppo_run_101", ip: "192.168.1.31" },
  { id: 4, time: "2026-10-07 08:13:52", user: "zhou", action: "task_retry", target: "#1031", detail: "重试失败任务（特征覆盖率低于阈值）", ip: "192.168.1.31" },
  { id: 5, time: "2026-10-06 17:22:18", user: "zhang", action: "task_submit", target: "#1027", detail: "提交批量回测任务 value_pack_06（24 个因子）", ip: "192.168.1.18" },
  { id: 6, time: "2026-10-06 17:35:40", user: "zhang", action: "download", target: "#1027", detail: "下载因子回测汇总 factor_backtest_summary.csv", ip: "192.168.1.18" },
  { id: 7, time: "2026-10-06 16:04:09", user: "zhou", action: "task_submit", target: "#1026", detail: "提交因子生成任务 ppo_run_100", ip: "192.168.1.31" },
  { id: 8, time: "2026-10-06 15:41:27", user: "zhang", action: "task_submit", target: "#1021", detail: "提交手动回测任务 ma_bias_20", ip: "192.168.1.18" },
  { id: 9, time: "2026-10-06 14:31:56", user: "chen", action: "task_submit", target: "#1025", detail: "提交建池任务 liquid_500_refresh", ip: "192.168.1.42" },
  { id: 10, time: "2026-10-06 13:12:03", user: "lin", action: "task_submit", target: "#1024", detail: "提交因子组合任务 multi_factor_v8", ip: "192.168.1.23" },
  { id: 11, time: "2026-10-06 11:08:30", user: "system", action: "data_import", target: "#1023", detail: "主缓存导入 fundamental_q1（分块写入）", ip: "127.0.0.1" },
  { id: 12, time: "2026-10-06 10:02:44", user: "zhang", action: "download", target: "#1022", detail: "下载回测结果 turnover_neutral 全部文件", ip: "192.168.1.18" },
  { id: 13, time: "2026-10-05 19:21:10", user: "lin", action: "note", target: "#1030", detail: "保存结果备注（momentum_20_prod）", ip: "192.168.1.23" },
  { id: 14, time: "2026-10-05 10:40:22", user: "admin", action: "permission", target: "wang", detail: "新增用户 wang（研究员角色）", ip: "192.168.1.15" },
  { id: 15, time: "2026-10-04 15:02:17", user: "admin", action: "permission", target: "wang", detail: "禁用用户 wang（离职交接）", ip: "192.168.1.15" },
  { id: 16, time: "2026-10-04 09:18:55", user: "chen", action: "pool_create", target: "liquid_500", detail: "创建股票池 liquid_500（500 只）", ip: "192.168.1.42" },
  { id: 17, time: "2026-10-03 06:30:00", user: "system", action: "data_import", target: "#1028", detail: "主缓存导入 daily_master_0616（6,031,842 行）", ip: "127.0.0.1" },
  { id: 18, time: "2026-10-02 16:45:38", user: "admin", action: "config", target: "platform.yaml", detail: "修改回测默认成本参数（滑点 0.0004 → 0.0005）", ip: "192.168.1.15" },
  { id: 19, time: "2026-10-02 11:32:51", user: "lin", action: "task_cancel", target: "#1029", detail: "取消排队中的建池任务", ip: "192.168.1.23" },
  { id: 20, time: "2026-10-01 09:05:12", user: "system", action: "login", target: "—", detail: "服务账号定时任务启动", ip: "127.0.0.1" },
];

/* ---------- 页面提交任务用到的构造器 ---------- */

export type NewTaskPayload = Omit<Task, "id"> & { id?: number };
