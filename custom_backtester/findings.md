# 当前执行发现

- 原始数据：`F:\my_code_file\因子构建\数据\daily_with_maindata_v2.csv`
- 文件大小：约 19.77 GB。
- 文件实际为制表符分隔，导入器支持自动识别。
- 当前 `data_cache/master/meta.json` 不存在，主缓存需要重新全量构建。
- 平台支持 `prepare_master`、`create_pool`、`generate_factors`、`backtest_factors` 四类后台任务。
- 因子生成结果包含 `accepted_factors.jsonl`，每条记录包含 `ic`、`rank_ic`、`icir`、`coverage`、`score` 等指标；批量回测写入 `factor_backtest_summary.csv`。
- 本次主缓存任务 `20260811_012816_50dafc3b` 完成：5,990,248 行、5,432 只股票、2021-06-18 至 2026-06-16。
- 本次股票池：`liquid_500_864dc25f`，正好 500 只，和主缓存 source signature 一致。
- 本次因子运行：`liquid_500_864dc25f_af3e199fe8`，54 个合格因子，227 次尝试。
- 本次批量回测：54/54 完成，0 失败；汇总包含生成指标和回测指标。
- 有 1 个因子最终账户归零，导致其年化收益和 Calmar 数值为 NaN；其总收益为 -100%，属于回测结果本身的数学不可定义情况。
- 组合回测输出位于 `outputs/factor_backtests/liquid_500_864dc25f/liquid_500_864dc25f_af3e199fe8/composites/`，权重方式为 generation score 归一化。
- 组合汇总包含 6 行：Top10、Top20、Top30、Top40、Top50、Top54；当前 54 个因子不足以执行 60 至 100 因子组。
