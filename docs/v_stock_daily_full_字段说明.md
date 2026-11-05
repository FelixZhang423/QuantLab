# 视图 `v_stock_daily_full` 字段说明（共91字段）

## 来源：`last_5years_daily`（68字段）

| 字段 | 解释 |
|------|------|
| `market_code` | 数据来源（SH:上海、SZ:深证、BJ:北京、GZ:股转） |
| `category` | 行情类别（股票:stock、指数:index、基金:fund 等） |
| `code` | 股票代码 |
| `timestamps` | 时间戳 |
| `open` | 开盘价 |
| `close` | 收盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `ycp` | 昨收价 |
| `vol` | 成交量 |
| `amount` | 成交额 |
| `ChangePCT` | 涨跌幅(%) |
| `RangePCT` | 振幅(%) |
| `TurnoverRate` | 换手率(%) |
| `Ifsuspend` | 是否停牌 |
| `if_up` | 是否上涨 |
| `if_flat` | 是否平盘 |
| `if_down` | 是否下跌 |
| `RisingUpDays` | 连涨天数 |
| `FallingDownDays` | 连跌天数 |
| `MaxRisingUpDays` | 历史连涨最多天数 |
| `MaxFallingDownDays` | 历史连跌最多天数 |
| `FallOnDebut` | 是否破发 |
| `FallOnNAPS` | 是否破净 |
| `StockBoard` | 今日是否涨停一字板 |
| `LimitBoard` | 今日是否跌停一字板 |
| `SurgedLimit` | 今日是否涨停股 |
| `DeclineLimit` | 今日是否跌停股 |
| `HighestPrice` | 今日是否创历史新高 |
| `LowestPrice` | 今日是否创历史新低 |
| `HighestPriceRW` | 是否近一周新高 |
| `LowestPriceRW` | 是否近一周新低 |
| `HighestPriceTW` | 是否本周以来新高 |
| `LowestPriceTW` | 是否本周以来新低 |
| `HighestPriceRM` | 是否近一月新高 |
| `LowestPriceRM` | 是否近一月新低 |
| `HighestPriceTM` | 是否本月以来新高 |
| `LowestPriceTM` | 是否本月以来新低 |
| `HighestPriceRMThree` | 是否近三个月新高 |
| `LowestPriceRMThree` | 是否近三个月新低 |
| `HighestPriceRMSix` | 是否近半年新高 |
| `LowestPriceRMSix` | 是否近半年新低 |
| `HighestPriceRY` | 是否近一年新高 |
| `LowestPriceRY` | 是否近一年新低 |
| `HighestPriceYTD` | 是否今年以来新高 |
| `LowestPriceYTD` | 是否今年以来新低 |
| `ema12` | 12日指数移动均线 |
| `ema26` | 26日指数移动均线 |
| `dif` | MACD 离差值（EMA12 - EMA26） |
| `dea` | MACD 信号线（DIF 的 9日 EMA） |
| `macd` | MACD 柱值 |
| `max_high_9` | 9日最高价 |
| `min_low_9` | 9日最低价 |
| `RSV` | KDJ 未成熟随机值 |
| `kdj_k` | KDJ K 值 |
| `kdj_d` | KDJ D 值 |
| `kdj_j` | KDJ J 值 |
| `ma5` | 5日均价 |
| `ma20` | 20日均价 |
| `ma_signal` | 均线信号 |
| `macd_signal` | MACD 信号 |
| `kdj_signal` | KDJ 信号 |
| `strategy` | 策略标记 |
| `ma4` | 4日均价 |
| `ma8` | 8日均价 |
| `ma12` | 12日均价 |
| `ma16` | 16日均价 |
| `ma47` | 47日均价 |

## 来源：`stock_main_info_fd`（13字段）

| 字段 | 解释 |
|------|------|
| `ChiName` | 中文名称 |
| `ChiNameAbbr` | 中文名称缩写 |
| `EngName` | 英文名称 |
| `EngNameAbbr` | 英文名称缩写 |
| `SecuAbbr` | 证券简称 |
| `ChiSpelling` | 拼音证券简称 |
| `SecuMarket` | 证券市场 |
| `SecuCategory` | 证券类别 |
| `ListedDate` | 上市日期 |
| `ListedSector` | 上市板块 |
| `ListedState` | 上市状态 |
| `Industry` | 所属行业 |
| `ConceptName` | 概念名称 |

## 来源：`stock_industry_fd`（8字段，别名 `ind_*`）

| 字段 | 解释 |
|------|------|
| `ind_1st_code` | 一级行业代码 |
| `ind_1st_name` | 一级行业名称 |
| `ind_2nd_code` | 二级行业代码 |
| `ind_2nd_name` | 二级行业名称 |
| `ind_3rd_code` | 三级行业代码 |
| `ind_3rd_name` | 三级行业名称 |
| `ind_4th_code` | 四级行业代码 |
| `ind_4th_name` | 四级行业名称 |

## 来源：`stock_sector_info`（2字段，聚合后）

| 字段 | 解释 |
|------|------|
| `sector_names` | 所属板块名称（逗号分隔） |
| `sector_types` | 板块类型（100000:概念、200000:地区、300000:行业） |
