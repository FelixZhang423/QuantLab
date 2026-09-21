# 独立因子研究系统执行记录

## 2026-08-31

- 创建本次实施计划与发现记录。
- 完成仓库盘点，确认行情面板、股票池、因子运行和回测汇总的真实路径与字段。
- 完成独立数据契约、文件哈希清单、只读加载器和快照导出器。
- 完成未来收益、市场状态特征、逐日 IC、状态条件 IC、类别评分、相关性去重和等权组合基线。
- 完成命令行 `export`/`validate`。
- TDD 测试结果：`13 passed`；导出器回归测试在历史 summary 混合列格式下通过。
- 真实导出结果：`research_data/snapshots/20260831T064224Z_7a98fc5698`，500 只股票、1264 个因子、316 条回测记录。
- 真实校验结果：`valid=true`、`errors=[]`。
- 后续研究前置条件：补充逐因子值长表，才能执行状态条件评价和因子组合。
- 增加 `states` 命令并在真实快照上运行：生成 `research_runs/state_20260831T064831Z_c34189fd`，得到 1,202 个交易日状态记录。
- 重新生成最新快照状态：`research_runs/state_20260831T081146Z_043b23e6`，绑定 `20260831T074757Z_7a98fc5698`。
- 全量逐因子值运行：`research_runs/values_20260831T074840Z_ff40c015`，`requested=1264`、`computed=1264`、`failed=0`。
- 全量状态条件评价：`research_runs/conditional_20260831T082335Z_4ffd450e` 为旧版全样本结果；加入时间切分后正式结果为 `research_runs/conditional_20260831T083739Z_4c33fe73`，`requested=1264`、`computed=1264`、`failed=0`，输出 12,628 条因子-状态-切分记录。
- 增加 `assign_time_splits` 和 CLI `--train-ratio`/`--valid-ratio`；默认按交易日顺序 60%/20%/20%，不随机打乱。
- 选择器增加 `split` 过滤、条件类别回退和 `run_selection`；新增 `select` CLI，并生成三个状态的训练段选择运行。
- 增加值运行/状态运行与研究快照的 manifest 一致性校验。
- 测试结果：条件评价测试 `5 passed`，选择器测试 `4 passed`，CLI 测试 `3 passed`；完整测试 `27 passed`，`compileall: ok`，最新快照校验 `valid=true`。
- 选择结果已按 bull/bear/sideways 三个状态生成训练段运行，每个状态选择 10 个因子并保存等权组合审计文件。
- 一次最终汇总命令因 PowerShell 未保留 `FullName` 产生路径为空错误，已修正命令并重新核验通过。
