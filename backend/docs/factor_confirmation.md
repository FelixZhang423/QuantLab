# 候选生成与因子确认

## 两个阶段

1. PPO reward 只使用训练集评分。训练和验证均通过质量门槛后写入 `candidate_factors.jsonl`。生成完成后冻结候选、数据版本、算子和超参数。
2. 在生成页执行“因子确认”，或使用下面的 CLI/API。独立任务只在冻结后打开测试集。通过测试门槛的记录进入 `confirmed_factors.jsonl`，原始表达式及 train/valid/test 指标一并保留。

| 数据段 | coverage | abs(IC) | abs(RankIC) | abs(ICIR) | 符号规则 |
|---|---:|---:|---:|---:|---|
| train | ≥0.9 | ≥0.05 | ≥0.03 | ≥0.5 | train IC 是方向依据 |
| valid | ≥0.9 | ≥0.03 | ≥0.03 | ≥0.3 | 三个指标各自与 train IC 同号 |
| test | ≥0.9 | ≥0.03 | ≥0.03 | ≥0.3 | 三个指标各自与 train IC 同号 |

覆盖率分母是各段有效评估日期与股票构成的单元格，非有限值不算有效。训练 IC 必须有限且非零。测试结果不进入 PPO reward；测试门槛从生成时保存的配置读取，确认请求没有修改门槛的参数。不能根据测试结果继续修改同一运行的候选、算子、PPO 参数或质量门槛。

## 执行

```powershell
cd backend
python -m cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml
python -m cli confirm-factors --factor-run <run_id> --config configs/factor_generation.yaml
python -m cli backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml
```

Web：生成完成后点击“因子确认”，等待任务结束；回测页只列已确认的因子。生成页同时展示候选数、已确认数和确认状态。

API：`POST /api/factor-runs/{run_id}/confirm`，请求体为空，返回后台 `job_id`。任务操作为 `confirm_factors`。生成、确认、回测是分开的任务；提交回测不会执行或重跑测试集。

## 落盘与恢复

```text
var/factor_runs/<run_id>/
  candidate_factors.jsonl       # train/valid 通过，保留原始稳定 factor_id
  rejected_candidates.jsonl     # PPO 候选阶段拒绝
  generation_freeze.json        # 生成结束后的配置、数据与候选摘要
  confirmation_request.json     # 首次确认绑定的输入、测试缓存与门槛
  test_evaluations.jsonl         # 所有候选的 test 指标、结论、拒绝原因
  confirmed_factors.jsonl       # 仅确认通过的候选，保留原 candidate ID
  confirmation_manifest.json    # 状态、数量和产物校验和
  factor_run.json               # 运行概要和两阶段状态
```

确认使用跨进程锁，已完成且落盘的候选不重复评估。中断后重试只处理未完成项；追加日志末尾不完整的行会在锁内恢复。已完成确认的再次调用只验证产物并修复运行概要/归档，不重新计算 test。

`confirmed_factors.jsonl` 原子发布，确认清单最后提交。下游检查确认状态、校验和与每条 confirmed 状态；不回退读取 candidate 或旧 `accepted_factors.jsonl`。一个运行内即使部分候选被 test 拒绝，也保留其评估结果和失败原因。异常中断的尚未完整落盘的计算可能重试，系统不把半行日志视为已完成。

确认后不可继续向同一运行添加候选。首次确认前也会核对生成冻结清单，不能修改冻结门槛再使用同一测试集确认该轮。对多个运行重复试探测试集属于研究流程纪律，系统不承诺跨运行识别人工调参。

## 数据切分

生产生成必须包含 train、valid、test。三个缓存窗口按时间排序且互不重叠；train/valid 和 valid/test 之间各保留至少 `target_horizon` 个实际交易日。快照包含隔离区间供校验，但隔离区间不进入任何切分缓存。

默认日期预览采用保守日历余量预留间隔，任务在物化 memmap 前按快照中的实际交易日再次验证，不满足就报错。短股票池窗口可能不能支持三段评估与隔离，需要扩大研究区间。

滚动回看与未来标签只使用各自缓存内部的数据。`PanelData` 会从评估区间扣除回看和未来标签所需的行；测试确认沿用该轮生成保存的回看、标签周期和数据版本，不能重新选择窗口。

## 兼容边界

旧 accepted 文件不等同于 confirmed，不会自动改名或被回测。请按新门槛与隔离规则重新生成，再运行确认。历史回测结果仍可查看。MySQL 的因子明细只存已确认因子，完整候选与确认信息进入运行的 JSON 归档。

低层 `single_factor` CLI 仍可在已准备且隔离的 memmap 上训练候选；正式的冻结、确认和平台回测工作流请使用 backend CLI/API，以具备完整的股票池、快照和运行身份信息。

## 验证结果

完整后端回归：411 passed、163 subtests passed。前端类型检查、生产构建及3项真实指标/confirmed消费测试通过。覆盖候选门槛、同号规则、实际交易日隔离、冻结条件篡改拒绝、部分日志恢复、确认完成后摘要修复和 canonical 算子解析。未对真实公司数据执行完整 PPO 训练或生产规模确认。
