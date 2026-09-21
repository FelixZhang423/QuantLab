# custom_backtester 因子组合流程设计（AlphaGen 风格）

## 1. 目标

把“单因子生成”和“因子组合”拆成两条独立流程：

- 单因子流程负责产出、评分、回测单因子；
- 组合流程只消费“已合格的单因子”，再做相关性门槛、权重优化和组合回测。

这套组合策略借鉴 `alphagen-master` 的核心思想：

- 先做单因子质量筛选；
- 再做因子间 mutual IC 去重；
- 再用线性池优化权重；
- 最后把组合表达式和回测结果统一落到结果中心。

## 2. 设计结论

推荐采用“AlphaGen 风格的线性组合池”作为唯一正式方案。

### 方案 A：AlphaGen 风格线性组合池（推荐）

- 候选因子先按评分排序；
- 新因子进入组合前先过 mutual IC 门槛；
- 进入池后再做权重优化；
- 池子超容量时删除绝对权重最小的因子；
- 支持按 10/20/30/.../100 的不同池大小批量生成组合结果。

优点：

- 和 `alphagen-master` 的流程一致；
- 权重不是随机的，而是可解释、可复现、可回测的；
- 适合你现在“先跑很多单因子，再拿去组合”的工作方式。

### 方案 B：等权组合

- 只做筛选，不做权重优化；
- 所有通过门槛的因子等权相加。

优点是简单，缺点是偏离 `alphagen-master` 的主逻辑，表达力弱。

### 方案 C：全局一次性最优化

- 先固定一批因子，再一次性求全局最优权重。

优点是数学上直接，缺点是对候选集合质量和稳定性要求更高，不如 AlphaGen 那种“逐步入池 + 复优化”稳。

本项目第一版采用方案 A，方案 B 作为应急 fallback，方案 C 暂不启用。

## 3. 概念边界

这里要严格区分两个 pool：

- 股票池：决定“在哪些股票上做信号和回测”；
- 因子组合池：决定“哪些单因子可以进入线性组合”。

这两个池子不共用语义，也不共用 ID。

- 股票池继续沿用现有 `pool_id`；
- 因子组合池建议新增 `composition_id` / `combo_id`；
- 组合结果必须记录两者，防止后续混淆。

## 4. 输入与输出

### 4.1 输入

组合流程消费的不是原始 PPO 生成器，而是已经完成打分和筛选的单因子结果。

优先输入源：

- `outputs/saved_backtests/factor/<pool_id>/<factor_run_id>/factor_backtest_summary.csv`
- `factor_runs/<run_id>/accepted_factors.jsonl`
- `factor_runs/<run_id>/factor_run.json`

最少需要这些字段：

- `factor_id`
- `expression`
- `canonical_expression`
- `backtest_expression`
- `pool_id`
- `source_signature`
- `generation_ic`
- `generation_rank_ic`
- `generation_icir`
- `generation_coverage`
- `generation_score`
- `backtest_sharpe`
- `backtest_annual_return`
- `backtest_max_drawdown`

### 4.2 输出

每次组合运行都要输出：

- 组合表达式；
- 组合权重；
- 组合池中保留的因子列表；
- 相关性门槛命中情况；
- 组合回测结果；
- 保存到统一结果中心的 manifest。

建议输出目录：

- `outputs/saved_backtests/composite/<pool_id>/<composition_id>/`

建议产物：

- `manifest.json`
- `composition_summary.csv`
- `factor_weights.json`
- `daily_report.csv`
- `positions.csv`
- `trades.csv`
- `annual_metrics.csv`
- `summary.json`
- `summary.png`

## 5. 组合流程

### 5.1 候选因子准备

先把单因子结果按统一规则标准化：

1. 只保留 `accepted = true` 的因子；
2. 统一使用 `canonical_expression`；
3. 同一 `pool_id` 和 `source_signature` 才允许混在一个组合任务里；
4. 按选定的排序指标排序，默认用 `generation_score`，也可切换为 `generation_ic`、`backtest_sharpe` 等。

### 5.2 质量门槛

组合前先做单因子质量过滤，避免差因子进入组合池。

默认门槛建议：

- `generation_score >= threshold`
- `generation_ic >= threshold`
- `generation_rank_ic >= threshold`
- `generation_coverage >= threshold`
- `backtest_sharpe >= threshold`（可选）

这些门槛只是进入“候选集”的前置条件，不是最终组合结果。

### 5.3 mutual IC 去重

这是组合前的核心门槛。

对新候选因子 `f_new`，计算它与当前组合池中每个已入池因子 `f_i` 的 mutual IC：

- mutual IC 使用同一股票池、同一时间窗口上的横截面相关；
- 为保持与 AlphaGen 一致，默认使用按日横截面标准化后的 Pearson 相关；
- 默认拒绝规则：
  - 若 `mutual_ic > threshold`，则认为过于重复，拒绝入池。

默认阈值建议沿用 AlphaGen 风格：

- `mutual_ic_threshold = 0.99`

可选严格模式：

- `abs(mutual_ic) > threshold` 也拒绝。

建议默认不开严格模式，原因是 AlphaGen 主要拒绝“高度正相关重复因子”，而不是强行排斥所有负相关因子。

### 5.4 入池与初始权重

如果候选因子通过 mutual IC 门槛，则允许入池。

初始权重规则参考 `alphagen-master`：

- 第一个因子：`w0 = max(single_ic, 0.01)`
- 后续因子：先用当前池内权重均值做 warm start

注意：

- 这里的初始权重只是优化前的起点，不是最终权重；
- 最终权重由后续优化器求解；
- 这个规则必须保留为“初始化语义”，不能当成最终分配结果理解。

### 5.5 权重优化

建议支持两种 AlphaGen 同款目标：

#### A. MSE / IC 主目标（默认）

设：

- `w` 为组合权重向量；
- `ic` 为单因子的单独 IC 向量；
- `M` 为 mutual IC 矩阵；

则目标可写为：

`L = w^T M w - 2 w^T ic + 1 + λ ||w||_1`

含义：

- 提高组合后的预测能力；
- 惩罚彼此高度重复的因子同时拿高权重；
- 用 L1 正则压缩弱因子权重。

#### B. ICIR / LCB 主目标（可选）

对组合因子每天的 IC 序列计算：

- `mean(IC_daily) / std(IC_daily)`，或
- `mean(IC_daily) - β * std(IC_daily)`

适合希望组合结果更稳、跨期波动更小的场景。

### 5.6 容量控制

组合池支持最大容量 `max_factors`。

当新增因子后池子超过容量时：

- 重新优化权重；
- 删除绝对权重最小的因子；
- 再继续下一轮候选筛选。

这一步也是 AlphaGen 的核心习惯：让“最不重要的因子”先出局。

### 5.7 多尺寸组合扫描

组合任务支持对多个池大小批量生成：

- 10 个因子；
- 20 个因子；
- 30 个因子；
- ...
- 最多 100 个因子。

每个尺寸都要单独：

1. 选出对应数量的候选因子；
2. 过 mutual IC 门槛；
3. 优化权重；
4. 回测；
5. 保存结果；
6. 记录曲线和指标。

## 6. 表达式与权重序列化

组合表达式继续沿用当前系统的统一表达式语义，不新增第二套 operator 语法。

最终表达式格式：

`(w1)*(expr1) + (w2)*(expr2) + ... + (wn)*(exprn)`

要求：

- `expr` 必须先 canonicalize；
- 权重要保留为优化后的原始浮点数；
- 只在展示层做格式化，不在表达式层偷偷改语义。

### 6.1 保存字段

建议在组合结果 `manifest.json` 中至少保存：

- `result_type = composite`
- `pool_id`
- `composition_id`
- `source_factor_run_ids`
- `selected_factor_ids`
- `selection_metric`
- `mutual_ic_threshold`
- `objective_type`
- `max_factors`
- `canonical_expression`
- `components`

其中 `components` 结构建议和现有单因子结果一致：

```json
[
  {
    "factor_id": "factor_0001",
    "expression": "rank(close)",
    "weight": 0.142
  }
]
```

## 7. 平台与任务入口

新增一个独立组合任务，不复用“手动回测”入口。

### 7.1 后端任务

建议增加平台操作：

- `compose_factors`

输入参数建议：

- `master_store`
- `pools_root`
- `pool_id`
- `factor_result_roots` 或 `factor_run_ids`
- `selection_metric`
- `selection_thresholds`
- `mutual_ic_threshold`
- `objective_type`
- `max_factors`
- `sweep_sizes`
- `backtest_config`

### 7.2 前端 UI

建议在 Streamlit 里新增独立标签：

- `因子组合`

界面上至少要有：

- 股票池选择；
- 候选因子来源选择；
- 排序指标；
- 单因子筛选阈值；
- mutual IC 阈值；
- 目标函数选择；
- 池大小扫描（10/20/30/...）；
- 启动按钮；
- 任务进度；
- 结果表；
- 结果下载。

## 8. 错误处理

组合流程必须明确失败原因，不能悄悄跳过。

常见失败包括：

- `pool_id` 与单因子结果的 `source_signature` 不一致；
- 候选因子表达式无法 canonicalize；
- mutual IC 计算时候选因子没法在当前池上求值；
- 所有候选因子都被阈值过滤掉；
- 权重优化失败或数值发散；
- 回测引擎对表达式/数据字段报错。

处理原则：

- 失败因子要记录到失败清单；
- 组合任务要记录失败原因；
- 组合池为空时，直接失败，不伪造结果；
- 回测成功与否必须写入统一结果中心。

## 9. 测试策略

至少覆盖以下几类测试：

1. 单因子候选输入测试
   - 能从现有 `factor_backtest_summary.csv` 读取候选；
   - 能按 `pool_id` 和 `source_signature` 过滤。

2. mutual IC 门槛测试
   - 高相关候选会被拒绝；
   - 低相关候选会被保留。

3. 权重优化测试
   - 初始权重和最终权重不同；
   - L1 正则不会把权重全打成 0；
   - 组合池超容量时会删除最弱因子。

4. 多尺寸扫描测试
   - 10/20/30/... 的结果都能生成；
   - 每个结果都能进入 saved_backtests。

5. UI 任务接线测试
   - 因子组合页能选股票池；
   - 能提交组合任务；
   - 结果中心能看到组合记录。

## 10. 验收标准

这次设计通过的标准是：

1. 单因子和组合因子是两条独立流程；
2. 组合流程只消费已合格单因子，不要求重新生成单因子；
3. 组合前必须做 mutual IC 门槛；
4. 权重不是随机数，而是可优化、可复现的结果；
5. 支持 10/20/30/.../100 的组合尺寸扫描；
6. 组合回测结果统一进入 `outputs/saved_backtests`；
7. UI 可以直接看到组合任务进度、权重和回测曲线。

## 11. 非目标

本阶段不做：

- 重新设计 PPO 单因子生成器；
- 重写表达式解析器；
- 改变股票池的定义；
- 引入第二套 operator 语法；
- 做跨股票池的组合池混跑。

这次只做“单因子 → 组合池 → 权重优化 → 组合回测”的完整闭环。
