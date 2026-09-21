# 独立因子研究系统发现记录

## 已确认需求

- 当前处于研究阶段。
- 新系统必须独立于现有因子生成和回测系统。
- 原系统只作为一次或多次版本化数据导出的来源。
- 独立目录至少保存行情、因子值和因子评价/回测数据。
- 不需要前端页面。
- 最终研究流程覆盖因子生成、因子分类、市场状态识别、条件表现分析、类别选择、具体因子组合与回测。

## 已盘点

- 行情来源：`single_factor/data/selected_500_liquid_processed/panel.parquet`，日期 2021-06-18 至 2026-06-16，导出股票池后 469,982 行；原字段 `timestamps`/`vol` 统一为 `date`/`volume`。
- 股票池来源：`custom_backtester/data_cache/pools/liquid_500_864dc25f`，池 ID `liquid_500_864dc25f`，500 只股票。
- 因子来源：`custom_backtester/factor_runs` 下的 `factor_run.json` 与 `accepted_factors.jsonl`，快照登记 1,264 个 accepted 因子。
- 回测来源：`custom_backtester/outputs/saved_backtests/factor/liquid_500_864dc25f` 下的 `factor_backtest_summary.csv`，快照登记 316 条、4 个运行。
- 原系统没有稳定的逐因子值长表；独立系统已根据快照行情和 catalog 表达式重算 1,264 个因子，并将结果按因子分区保存。

## 独立快照

- 当前快照：`20260831T074757Z_7a98fc5698`。
- `research_system validate` 返回 `valid=true`，无错误；6 个快照文件均记录行数和 SHA-256。

## 当前研究运行

- 状态运行：`state_20260831T081146Z_043b23e6`，1,202 个交易日，规则状态包括 bull、bear、sideways、high_volatility。
- 因子值运行：`values_20260831T074840Z_ff40c015`，1,264 个因子全部成功，单个分区包含 `date`、`code`、`factor_id`、`value`。
- 条件评价：`conditional_20260831T083739Z_4c33fe73`，按 20 日未来收益计算 Pearson IC、Rank IC、ICIR、命中率和稳定性，并输出 train/valid/test。
- 当前输出类别是表达式结构类别：price、liquidity、volatility、trend、technical、mixed、other。真实 accepted catalog 的类别元数据尚未填充，因此条件评价负责生成结构类别并标记 `category_source`。
- 训练段选择：`select` 命令先聚合类别得分，再在指定类别内按 `0.7 * rank_ic_mean + 0.3 * icir` 排序，输出等权组合和淘汰原因。

## 当前限制

- 选择命令当前不自动加载大规模因子值分区做相关性去重；需要相关性约束时，应增加只读取候选因子分区的流式实现。
- 尚未实现基于行为序列的 K-Means/HMM 分类、层级 MoE、MACoE/PACoE 动态路由，以及带成本约束的组合样本外回测。
