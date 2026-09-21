# 执行进度

## 2026-08-11

- 已完成重复主缓存任务保护的实现。
- 验证：60 passed，77 subtests passed；compileall 通过。
- 已停止旧导入进程并删除旧任务记录和残留 staging。
- 当前开始新的全量导入。
- 首次启动因 PowerShell 内联命令将中文源路径编码为 `????` 而失败，未读取数据；改用 ASCII 通配路径自动定位原始 CSV。
- 主缓存完成：job `20260811_012816_50dafc3b`。
- 股票池完成：`liquid_500_864dc25f`，500 只股票。
- 因子生成完成：`liquid_500_864dc25f_af3e199fe8`，54 个合格因子。
- 因子批量回测完成：54 个完成，0 个失败。
- 最终验证：60 passed，77 subtests passed；compileall 通过。
- 组合回测完成：Top10、Top20、Top30、Top40、Top50、Top54 共 6 组，均已生成独立结果和总汇总表。

## 2026-08-11 结果中心与操作符统一收尾

- 因子回测新输出路径为 `outputs/saved_backtests/factor/<pool_id>/<factor_run_id>/`。
- 结果中心现递归读取 `manual`、`factor`、`composite` 三类 manifest，并展示规范表达式、PPO IC/Rank IC/ICIR/Coverage/Score 及回测指标。
- 真实结果迁移刷新：54 个因子幂等跳过，6 个组合更新，失败 0 个。
- 组合组件权重文件已统一为规范操作符。
- 8 个旧手动结果目录已移动到 `outputs/_legacy_archive_20260811/`（可恢复）。

## 2026-08-21 AI Research Agent 可用化

- 已确认 foundation 计划全部完成；当前缺口是 tool plan 仍停留在记录层，没有真正连接本地因子生成/回测/组合工具。
- DeepSeek API key 已保存到本地 `.env.local`，后续运行使用 DeepSeek provider；不在日志或回复中输出密钥。
- 当前实现方向：先 TDD 补 tool executor，再接入 runner/CLI，默认 dry-run 创建耗时 job，显式执行参数才同步运行重任务。
- 已完成 `custom_bt.ai_research.tool_executor.AIToolExecutor`，支持白名单工具：context、表达式校验、记忆写入、候选回测 job、PPO 生成 job、组合 job、保存结果读取。
- 已让本地表达式 `rank(ts_mean(volume,20))` 可进入 `backtest_accepted_factors` 链路。
- 验证：`tests/test_ai_research_agent.py` 25 passed；相关回归 60 passed、1 个 torch/pynvml FutureWarning；`python -m compileall -q custom_bt app` 通过。
- DeepSeek smoke：session `smoke_deepseek_20260821_tools` 生成 2 个候选，2 个校验通过，创建 2 个回测 job；其中 job `20260821_012823_d578e522` 已真实运行完成，1 completed、0 failed。

## 2026-08-21 AI Research Flow 文档整理

- 已开始按当前实现整理 AI 研究全链路说明。
- 已确认核心入口包括 `custom_bt.cli ai-research`、`custom_bt.ai_research.cli run` 和 `AIResearchRunner.run_research_session`。
- 已确认当前链路是 DeepSeek 模型驱动，默认不执行本地工具；传入 `--execute-tools` 才执行工具计划，传入 `--execute-long-jobs` 才同步运行耗时平台 job。
- 已新增说明文档 `docs/ai_research_flow.md`，覆盖 17 个主章节：前置条件、配置、DeepSeek 调用、context snapshot、Research Spec、候选表达式、本地校验、tool plan、工具执行、产物目录、真实 smoke 示例、命令和排障。
- 收尾验证：`python -m pytest tests/test_ai_research_agent.py -q` 25 passed；`python -m compileall -q custom_bt app` 通过；`python -m custom_bt.cli ai-research --help` 通过；文档未匹配真实 key 形态或 TODO/TBD/FIXME。

## 2026-08-21 DeepSeek SSL 证书问题修复

- 用户在 `alphagen` 环境真实调用 DeepSeek 时遇到 `ssl.SSLError: [ASN1: NOT_ENOUGH_DATA] not enough data`。
- 已复现根因：`alphagen` 环境单独执行 `ssl.create_default_context()` 会在读取 Windows 证书库时失败；使用 `certifi.where()` 创建 context 可以成功。
- 已修复 `custom_bt.ai_research.llm_client.DeepSeekChatClient`：默认 HTTPS 调用优先使用显式 CA bundle 或 certifi CA bundle，避免直接依赖 Windows 证书库。
- 已新增可选环境变量 `DEEPSEEK_CA_BUNDLE`，并更新 `.env.example` 和 `docs/ai_research_flow.md` 排障说明。
- 验证：新增回归测试先红后绿；`python -m pytest tests/test_ai_research_agent.py -q` 26 passed；`F:\anaconda3\envs\alphagen\python.exe` 可创建 `create_https_context()` 和 DeepSeek client；`python -m compileall -q custom_bt app` 通过；CLI help 通过。
