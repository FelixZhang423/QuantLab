# 统一操作符与回测结果中心设计

## 1. 目标

将 PPO 因子生成、手动表达式回测、批量因子回测、组合回测和 Streamlit 展示统一到一套用户易懂的操作符语法中。删除旧版手动回测记录，保留当前主缓存、PPO 因子运行和当前因子回测结果，并把后续结果统一写入 `outputs/saved_backtests/`。

## 2. 统一表达式语法

用户可见和结果保存使用统一的小写规范名称：

| 规范操作符 | 含义 | 示例 |
|---|---|---|
| `abs` | 绝对值 | `abs(close)` |
| `add` / `sub` / `mul` / `div` | 四则运算 | `add(close,volume)` |
| `max` / `min` | 同一时点逐元素取大/取小 | `max(close,open)` |
| `delay` | 按股票向前取历史值 | `delay(close,20)` |
| `ts_mean` / `ts_sum` / `ts_std` / `ts_var` | 时间序列滚动统计 | `ts_mean(close,20)` |
| `ts_max` / `ts_min` / `ts_median` / `ts_mad` | 时间序列滚动极值和稳健统计 | `ts_max(high,20)` |
| `delta` / `ts_wma` / `ts_ema` | 差分及加权均线 | `delta(close,20)` |
| `ts_covariance` / `ts_corr` | 时间序列协方差和相关系数 | `ts_corr(close,volume,20)` |

AlphaGen 的 `Greater/Less/Ref/Mean` 只作为内部实现类或历史兼容别名，不再作为新结果的规范名称。`Greater` 的“取较大值”语义映射为 `max`，不与逻辑“大于判断”混淆。时间序列最大值使用 `ts_max`，避免与二元 `max` 冲突。

## 3. 唯一操作符注册表

新增 `custom_bt/operator_registry.py`，每个操作符只登记一次，至少包含：

- `canonical_name`：规范表达式名称；
- `category`：算术、时间序列、截面或其他类别；
- `arity` 和参数签名；
- 中文说明和示例；
- AlphaGen 类实现引用；
- 本地 Pandas 回测实现引用；
- 是否允许 PPO 生成；
- 是否允许手动回测；
- 兼容旧表达式的别名。

PPO 操作符列表、统一表达式解析器、本地回测 `OPERATORS` 和 Streamlit 操作符表均从该注册表生成。任何未注册或未通过验证的操作符都不能进入 PPO 动作空间和用户界面。

## 4. 执行链路

```text
operator_registry
        |
        +--> PPO operator list and canonical serializer
        +--> manual expression parser
        +--> pandas backtest evaluator
        +--> Streamlit operator table
        +--> result manifest canonical expression
```

PPO 内部仍可使用 Tensor 操作符类，本地回测仍可使用 Pandas 实现，但它们共享同一个操作符 ID、参数签名和语义定义。正常运行不再维护独立的表达式映射表；底层实现差异不暴露给用户。

手动输入、PPO 生成和组合表达式最终都保存为 `canonical_expression`。原始 AlphaGen 表达式只在需要重现历史结果时作为内部字段保留。

## 5. 结果中心

所有新结果统一写入：

```text
custom_backtester/outputs/saved_backtests/
  <result_id>/
    manifest.json
    daily_report.csv
    annual_metrics.csv
    trades.csv
    positions.csv
    summary.json
    summary.png
```

每个结果 manifest 至少包含：

- `result_type`：manual、factor 或 composite；
- `canonical_expression`；
- `pool_id`、`factor_run_id`；
- PPO 的 IC、Rank IC、ICIR、Coverage、Score 和 train/valid/test 指标；
- 回测的收益、年化收益、Sharpe、最大回撤、换手率、成本、胜率和交易次数；
- 数据源签名、回测参数和生成时间。

Streamlit 的“已保存回测结果”只扫描结果中心，展示净值曲线、回撤曲线、年度指标、交易统计、PPO 指标和规范表达式。

## 6. 旧记录处理

删除旧版手动回测目录：

```text
outputs/dif_dea_spread
outputs/job_smoke
outputs/low_turnover60
outputs/macd_momentum
outputs/sample_demo
outputs/sample_demo_v2
outputs/slow_mom120
outputs/web_run
```

不删除：

- 原始 CSV；
- `data_cache/master` 主缓存；
- 当前 `factor_runs/liquid_500_864dc25f_af3e199fe8` PPO 运行记录；
- 当前 54 个因子和 Top10/20/30/40/50/54 组合回测结果，直到它们完成结果中心登记。

当前因子结果不重新导入数据、不重新运行 PPO；迁移时根据已有表达式生成规范表达式和结果 manifest。

## 7. 操作符扩展流程

新增操作符必须同时提交：

1. 注册表定义；
2. AlphaGen/Tensor 实现；
3. Pandas 回测实现；
4. 规范表达式解析测试；
5. PPO 生成测试；
6. 小样本数值一致性测试；
7. Streamlit 文档和示例。

未完成上述验证的操作符保持禁用，不会悄悄进入生成器。

## 8. 测试与验收

必须覆盖：

- 每个已启用操作符的规范名称、别名、参数数量和参数类型；
- AlphaGen AST 到规范表达式的序列化；
- 规范表达式在 Pandas 面板上的计算；
- PPO 和本地回测在相同小面板上的结果一致性；
- 未注册操作符被明确拒绝；
- Streamlit 只显示规范名称；
- 结果中心能读取单因子、组合和手动结果；
- 旧结果目录删除后不会被“已保存回测结果”再次发现；
- 现有 54 个因子和 6 个组合结果迁移后表达式和指标仍完整。

验收标准是：新生成因子、手动回测和组合回测在界面上使用同一套操作符名称；新增操作符不需要分别修改 PPO 列表、转换表、回测注册表和界面列表。
