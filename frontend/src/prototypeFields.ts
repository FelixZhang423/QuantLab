import type { FieldInfo } from "./api/client";

/**
 * 前端原型的完整字段目录。
 *
 * 真实目录由 `/api/data/fields` 返回（目前是行情表 + dim 表）。企业库还有
 * `dws.f10_derivative_index_fd`（财务衍生指标 300+ 字段），接口尚未接入；
 * 原型在接口不可用时用这份目录演示「400+ 字段」的浏览、搜索与筛选体验。
 * 财务字段名按常见财务指标口径生成，仅用于原型展示，接入后整体替换。
 */

const DAILY_SOURCE = "dws.ll_stock_daily_sharing";
const DIM_SOURCE = "dim.stock_main_info_fd";
const INDUSTRY_SOURCE = "dim.stock_industry_fd";
const SECTOR_SOURCE = "dim.stock_sector_info";
const FINANCE_SOURCE = "dws.f10_derivative_index_fd";

type Row = [name: string, description: string, dtype: string, panel: boolean];

const DAILY_ROWS: Row[] = [
  ["market_code", "数据来源（SH 上海 / SZ 深证 / BJ 北京 / GZ 股转）", "String", false],
  ["category", "行情类别（股票 stock、指数 index、基金 fund 等）", "String", false],
  ["open", "开盘价", "Float64", true],
  ["close", "收盘价", "Float64", true],
  ["high", "最高价", "Float64", true],
  ["low", "最低价", "Float64", true],
  ["ycp", "昨收价", "Float64", true],
  ["vol", "成交量（回测面板中名为 volume）", "Float64", true],
  ["amount", "成交额", "Float64", true],
  ["ChangePCT", "涨跌幅（%）", "Float64", true],
  ["RangePCT", "振幅（%）", "Float64", true],
  ["TurnoverRate", "换手率（%）", "Float64", true],
  ["Ifsuspend", "是否停牌", "Int8", true],
  ["if_up", "是否上涨", "Int8", true],
  ["if_flat", "是否平盘", "Int8", true],
  ["if_down", "是否下跌", "Int8", true],
  ["RisingUpDays", "连涨天数", "Int32", true],
  ["FallingDownDays", "连跌天数", "Int32", true],
  ["MaxRisingUpDays", "历史连涨最多天数", "Int32", true],
  ["MaxFallingDownDays", "历史连跌最多天数", "Int32", true],
  ["FallOnDebut", "是否破发", "Int8", true],
  ["FallOnNAPS", "是否破净", "Int8", true],
  ["StockBoard", "今日是否涨停一字板", "Int8", true],
  ["LimitBoard", "今日是否跌停一字板", "Int8", true],
  ["SurgedLimit", "今日是否涨停股", "Int8", true],
  ["DeclineLimit", "今日是否跌停股", "Int8", true],
  ["HighestPrice", "今日是否创历史新高", "Int8", true],
  ["LowestPrice", "今日是否创历史新低", "Int8", true],
  ["HighestPriceRW", "是否近一周新高", "Int8", true],
  ["LowestPriceRW", "是否近一周新低", "Int8", true],
  ["HighestPriceTW", "是否本周以来新高", "Int8", true],
  ["LowestPriceTW", "是否本周以来新低", "Int8", true],
  ["HighestPriceRM", "是否近一月新高", "Int8", true],
  ["LowestPriceRM", "是否近一月新低", "Int8", true],
  ["HighestPriceTM", "是否本月以来新高", "Int8", true],
  ["LowestPriceTM", "是否本月以来新低", "Int8", true],
  ["HighestPriceRMThree", "是否近三个月新高", "Int8", true],
  ["LowestPriceRMThree", "是否近三个月新低", "Int8", true],
  ["HighestPriceRMSix", "是否近半年新高", "Int8", true],
  ["LowestPriceRMSix", "是否近半年新低", "Int8", true],
  ["HighestPriceRY", "是否近一年新高", "Int8", true],
  ["LowestPriceRY", "是否近一年新低", "Int8", true],
  ["HighestPriceYTD", "是否今年以来新高", "Int8", true],
  ["LowestPriceYTD", "是否今年以来新低", "Int8", true],
  ["ema12", "12 日指数移动均线", "Float64", true],
  ["ema26", "26 日指数移动均线", "Float64", true],
  ["dif", "MACD 离差值（EMA12 - EMA26）", "Float64", false],
  ["dea", "MACD 信号线（DIF 的 9 日 EMA）", "Float64", false],
  ["macd", "MACD 柱值", "Float64", false],
  ["max_high_9", "9 日最高价", "Float64", false],
  ["min_low_9", "9 日最低价", "Float64", false],
  ["RSV", "KDJ 未成熟随机值", "Float64", false],
  ["kdj_k", "KDJ K 值", "Float64", false],
  ["kdj_d", "KDJ D 值", "Float64", false],
  ["kdj_j", "KDJ J 值", "Float64", false],
  ["ma5", "5 日均价", "Float64", false],
  ["ma20", "20 日均价", "Float64", false],
  ["ma_signal", "均线信号", "Float64", false],
  ["macd_signal", "MACD 信号", "Float64", false],
  ["kdj_signal", "KDJ 信号", "Float64", false],
  ["strategy", "策略标记", "String", false],
  ["ma4", "4 日均价", "Float64", false],
  ["ma8", "8 日均价", "Float64", false],
  ["ma12", "12 日均价", "Float64", false],
  ["ma16", "16 日均价", "Float64", false],
  ["ma47", "47 日均价", "Float64", false],
];

const DIM_ROWS: Row[] = [
  ["ChiName", "中文名称", "String", false],
  ["ChiNameAbbr", "中文名称缩写", "String", false],
  ["EngName", "英文名称", "String", false],
  ["EngNameAbbr", "英文名称缩写", "String", false],
  ["SecuAbbr", "证券简称", "String", false],
  ["ChiSpelling", "拼音证券简称", "String", false],
  ["SecuMarket", "证券市场", "String", false],
  ["SecuCategory", "证券类别", "String", false],
  ["ListedDate", "上市日期", "Date", false],
  ["ListedSector", "上市板块", "String", false],
  ["ListedState", "上市状态", "String", false],
  ["Industry", "所属行业", "String", false],
  ["ConceptName", "概念名称", "String", false],
];

const INDUSTRY_ROWS: Row[] = [
  ["ind_1st_code", "一级行业代码", "String", false],
  ["ind_1st_name", "一级行业名称", "String", false],
  ["ind_2nd_code", "二级行业代码", "String", false],
  ["ind_2nd_name", "二级行业名称", "String", false],
  ["ind_3rd_code", "三级行业代码", "String", false],
  ["ind_3rd_name", "三级行业名称", "String", false],
  ["ind_4th_code", "四级行业代码", "String", false],
  ["ind_4th_name", "四级行业名称", "String", false],
];

const SECTOR_ROWS: Row[] = [
  ["sector_names", "所属板块名称（逗号分隔）", "String", false],
  ["sector_types", "板块类型（100000 概念 / 200000 地区 / 300000 行业）", "String", false],
];

type FinanceMetric = [name: string, label: string, group: string, unit?: string];

const FINANCE_METRICS: FinanceMetric[] = [
  ["ROEWeighted", "加权净资产收益率", "盈利能力", "%"],
  ["ROEDiluted", "摊薄净资产收益率", "盈利能力", "%"],
  ["ROA", "总资产收益率", "盈利能力", "%"],
  ["ROIC", "投入资本回报率", "盈利能力", "%"],
  ["GrossMargin", "销售毛利率", "盈利能力", "%"],
  ["NetMargin", "销售净利率", "盈利能力", "%"],
  ["OperatingMargin", "营业利润率", "盈利能力", "%"],
  ["EBITMargin", "息税前利润率", "盈利能力", "%"],
  ["CostRatio", "成本费用率", "盈利能力", "%"],
  ["RevenueGrowth", "营业收入增长率", "成长能力", "%"],
  ["NetProfitGrowth", "净利润增长率", "成长能力", "%"],
  ["EPSGrowth", "每股收益增长率", "成长能力", "%"],
  ["OperatingProfitGrowth", "营业利润增长率", "成长能力", "%"],
  ["TotalAssetGrowth", "总资产增长率", "成长能力", "%"],
  ["EquityGrowth", "净资产增长率", "成长能力", "%"],
  ["OCFGrowth", "经营现金流增长率", "成长能力", "%"],
  ["CurrentRatio", "流动比率", "偿债能力", "倍"],
  ["QuickRatio", "速动比率", "偿债能力", "倍"],
  ["CashRatio", "现金比率", "偿债能力", "倍"],
  ["DebtToAsset", "资产负债率", "偿债能力", "%"],
  ["EquityMultiplier", "权益乘数", "偿债能力", "倍"],
  ["InterestCoverage", "利息保障倍数", "偿债能力", "倍"],
  ["NetDebtToEquity", "净负债率", "偿债能力", "%"],
  ["InventoryTurnover", "存货周转率", "运营能力", "次"],
  ["ReceivableTurnover", "应收账款周转率", "运营能力", "次"],
  ["PayableTurnover", "应付账款周转率", "运营能力", "次"],
  ["AssetTurnover", "总资产周转率", "运营能力", "次"],
  ["FixedAssetTurnover", "固定资产周转率", "运营能力", "次"],
  ["CashConversionCycle", "现金转换周期", "运营能力", "天"],
  ["InventoryDays", "存货周转天数", "运营能力", "天"],
  ["OCF", "经营活动现金流净额", "现金流", "元"],
  ["FCF", "自由现金流", "现金流", "元"],
  ["OCFToRevenue", "经营现金流 / 营业收入", "现金流", "%"],
  ["OCFToNetProfit", "经营现金流 / 净利润", "现金流", "%"],
  ["CapexToRevenue", "资本开支 / 营业收入", "现金流", "%"],
  ["PE", "市盈率", "估值", "倍"],
  ["PB", "市净率", "估值", "倍"],
  ["PS", "市销率", "估值", "倍"],
  ["EVToEBITDA", "EV / EBITDA", "估值", "倍"],
  ["DividendYield", "股息率", "估值", "%"],
  ["BasicEPS", "基本每股收益", "每股指标", "元"],
  ["DilutedEPS", "稀释每股收益", "每股指标", "元"],
  ["NetAssetPS", "每股净资产", "每股指标", "元"],
  ["OCFPS", "每股经营现金流", "每股指标", "元"],
  ["TotalAssets", "资产总计", "规模", "元"],
  ["Revenue", "营业收入", "规模", "元"],
];

const FINANCE_VARIANTS: { suffix: string; note: string }[] = [
  { suffix: "", note: "最新报告期" },
  { suffix: "_Q", note: "单季度" },
  { suffix: "_TTM", note: "TTM" },
  { suffix: "_YOY", note: "同比增速" },
  { suffix: "_CAGR3", note: "近三年复合增速" },
  { suffix: "_AVG5", note: "近五年均值" },
  { suffix: "_STD5", note: "近五年波动" },
];

function rowsToFields(rows: Row[], source: string): FieldInfo[] {
  return rows.map(([name, description, dtype, panel]) => ({ name, description, dtype, source, panel }));
}

const financeRows: Row[] = FINANCE_METRICS.flatMap(([name, label, group, unit]) => (
  FINANCE_VARIANTS.map(({ suffix, note }) => [
    `${name}${suffix}`,
    `${group} · ${label}（${note}${unit ? `，${unit}` : ""}）`,
    "Float64",
    false,
  ] as Row)
));

export const PROTOTYPE_FIELDS: FieldInfo[] = [
  ...rowsToFields(DAILY_ROWS, DAILY_SOURCE),
  ...rowsToFields(DIM_ROWS, DIM_SOURCE),
  ...rowsToFields(INDUSTRY_ROWS, INDUSTRY_SOURCE),
  ...rowsToFields(SECTOR_ROWS, SECTOR_SOURCE),
  ...rowsToFields(financeRows, FINANCE_SOURCE),
];

export const PROTOTYPE_FIELD_COUNT = PROTOTYPE_FIELDS.length;
export const PROTOTYPE_FINANCE_COUNT = financeRows.length;

/** 因子生成页在接口不可用时使用：优先价量字段，财务字段也可选（原型） */
export const PROTOTYPE_GENERATION_FIELDS = PROTOTYPE_FIELDS.filter(
  (field) => field.source !== DIM_SOURCE && field.source !== INDUSTRY_SOURCE && field.source !== SECTOR_SOURCE,
);
