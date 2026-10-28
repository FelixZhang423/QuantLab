# 当前执行计划

- [completed] 1. 全量导入 daily_with_maindata_v2.csv 到 master cache
- [completed] 2. 基于 master cache 创建 500 只股票池
- [completed] 3. 生成足够多的候选因子并保存 IC、Rank IC、ICIR、覆盖率等指标
- [completed] 4. 对合格因子执行批量回测并保存结果
- [completed] 5. 汇总验证产物和任务状态
- [completed] 6. 按合格因子 score 加权，执行 Top10/20/30/40/50/54 组合回测

## 约束

- 不删除原始 CSV。
- 主缓存导入只允许同时运行一个任务。
- 全量导入完成并生成 `data_cache/master/meta.json` 后，才启动后续阶段。
- 组合回测按生成 score 归一化加权；当前只有 54 个合格因子，因此 60/70/80/90/100 组不可执行。

## 错误记录

- 2026-08-11：重复启动主缓存导入导致第二个任务 `[WinError 145]`，已停止旧进程并清理两个旧任务及 staging。

## 2026-08-11 操作符统一与结果中心收尾

- 已完成统一操作符注册表、规范表达式、因子结果中心递归扫描和 PPO 指标展示。
- 已将 54 个因子结果和 6 个组合结果迁移到 `outputs/saved_backtests/`。
- 组合结果 manifest 已记录组件因子、权重、生成分数；`factor_weights.json` 已规范化。
- 旧版 8 个手动回测目录已移入 `outputs/_legacy_archive_20260811/`，可恢复；主缓存、因子运行记录和批量 PPO 源结果保留。

## 2026-08-21 AI Research Agent 可用化追加计划

- [completed] 1. 补充 AI tool plan 执行层测试，覆盖表达式校验、候选 factor run 写入、平台 job 创建/执行、保存结果读取。
- [completed] 2. 实现本地工具执行器，把模型 tool plan 安全映射到现有因子生成、回测和组合能力。
- [completed] 3. 让 Agent 生成的本地表达式可进入现有 factor backtest 链路。
- [completed] 4. 将执行器接入 runner 和 CLI，默认 dry-run，显式参数才同步运行耗时任务。
- [completed] 5. 运行 focused tests、相关回归、compileall，并做 DeepSeek 小样本 smoke。
