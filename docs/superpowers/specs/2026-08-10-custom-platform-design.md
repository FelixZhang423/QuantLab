# custom_backtester 统一因子平台设计

## 1. 目标

将 `single_factor` 与 `custom_backtester` 合并为一个以 `custom_backtester` 为唯一入口的因子研究平台。平台使用
`F:\\my_code_file\\因子构建\\数据\\daily_with_maindata_v2.csv` 作为唯一主数据源，支持：

1. 流式导入大规模日频数据，不把 20GB 级 CSV 一次性加载到内存。
2. 创建和复用不同规模、不同条件的股票池。
3. 在指定股票池上运行现有 PPO 强化学习因子生成器。
4. 按训练/验证/测试质量指标筛选合格因子。
5. 只对合格因子执行 TopK 回测，并展示生成指标和回测指标。

本设计不要求一开始用全部股票生成因子；主缓存可覆盖全市场，实际计算由股票池决定。

## 2. 方案选择

### 方案 A：统一平台、保留生成引擎边界（推荐）

`custom_backtester` 负责数据导入、股票池、任务编排、表达式适配、回测和 UI；`single_factor` 的 PPO、AlphaGen 表达式和质量评估逻辑作为内部生成模块复用。

优点是保留现有强化学习实现和断点续跑能力，且可以统一股票池口径。代价是需要增加一层缓存适配和表达式转换。

### 方案 B：物理搬迁所有 `single_factor` 文件

将 `single_factor` 的代码整体移动到 `custom_backtester` 内部并改 import。目录表面上更统一，但会把两套数据、配置和执行逻辑继续耦合在一起，后续难以维护。

### 方案 C：把因子生成器重写为 pandas 引擎

直接让 PPO 使用 `custom_backtester` 的 pandas 表达式引擎。这样只有一个表达式运行时，但需要重写强化学习环境和高频候选评估路径，对 20GB 级数据的内存和速度风险较高。

本项目采用方案 A。

## 3. 总体架构

```text
daily_with_maindata_v2.csv
        |
        | 一次性分块导入，按配置选择字段
        v
master data cache + security metadata
        |
        +--> pool manager: 生成 pool_id 和 codes.txt
        |
        +--> pool materializer: 生成 train/valid/test memmap
                              |
                              v
                    PPO factor generator
                              |
                              v
                 accepted/rejected factor catalog
                              |
                              v
                   expression adapter + validator
                              |
                              v
                         TopK backtester
```

`pool_id` 是全链路主键。因子生成、质量记录、回测任务和输出目录都必须携带 `pool_id` 与数据签名。

## 4. 数据导入与缓存

### 4.1 主数据源

只使用用户指定的 CSV。导入器采用 PyArrow CSV 或等价的分块读取方式，禁止整体 `read_csv`。

默认导入字段分为三组：

- 股票池字段：`market_code`、`category`、`code`、`timestamps`、`amount`、`vol`、`Ifsuspend`、`ListedDate`、`ListedSector`、`ListedState`、`StockBoard`。
- 回测字段：`open`、`close`、`high`、`low`、`ycp`、`vol`、`amount`、`Ifsuspend`、`if_up`、`if_flat`、`if_down`。
- 因子字段：沿用当前 `single_factor/runtime.json` 中的技术指标字段，并允许通过配置追加财务字段。

字段选择必须可配置。导入器只缓存选中的字段，不默认缓存 CSV 中全部财务字段。

### 4.2 元数据类型

导入时保留以下字段的原始语义：

- `date/timestamps` 转为日期类型。
- `code` 统一为六位字符串。
- `category`、市场/板块等分类字段保留为字符串或分类类型。
- `ListedDate`、`InfoPublDate`、`EndDate` 保留为日期类型。
- 数值型行情、技术指标和财务字段转为可计算数值。

不能再将所有非 `date/code` 字段统一强制为数值，否则股票池条件会丢失。

### 4.3 建议目录

```text
custom_backtester/data_cache/master/
  stocks/<code>.parquet
  security_meta.parquet
  meta.json

custom_backtester/data_cache/pools/<pool_id>/
  codes.txt
  manifest.json
  selection_summary.csv

custom_backtester/data_cache/factor_runtime/<pool_id>/<runtime_id>/
  train/
  valid/
  test/
```

主缓存只构建一次；股票池不复制全部行情，只保存代码清单和筛选结果。因子生成缓存只包含当前股票池。

## 5. 股票池管理

股票池是平台的一等对象，不再依赖某个固定的 `pool_codes_500_liquid.txt`。

初始支持：

- 固定代码清单。
- 按成交额排序取前 N 名，例如 500、1000、2000。
- 最小上市天数。
- 最小有效覆盖率。
- 成交量/成交额大于零。
- 排除停牌股票。
- 按 `category`、`market_code`、`StockBoard`、`ListedSector` 等字段筛选。
- 指定股票池统计窗口，防止用未来数据选择股票池。

每个 `manifest.json` 至少保存：

```json
{
  "pool_id": "liquid_500_2021_2024_a1b2c3d4",
  "source_signature": "...",
  "selection_start": "2021-06-18",
  "selection_end": "2024-07-26",
  "top_n": 500,
  "min_listed_days": 250,
  "min_coverage": 0.9,
  "filters": {},
  "n_stocks": 500,
  "codes_file": "codes.txt"
}
```

同一个股票池可以重复用于不同因子生成任务和回测任务；如果筛选条件或源数据签名改变，则生成新的 `pool_id`。

## 6. 因子生成

`custom_backtester` 新增因子生成任务编排层，内部调用现有 PPO 生成逻辑。

建议命令接口：

```powershell
python -m custom_bt.cli prepare-master --config configs/platform.yaml
python -m custom_bt.cli create-pool --config configs/pools/liquid_500.yaml
python -m custom_bt.cli generate-factors --pool liquid_500 --config configs/factor_generation.yaml
```

生成任务执行时：

1. 校验 `pool_id`、数据签名和字段缓存是否匹配。
2. 为该股票池创建 train/valid/test memmap。
3. 复用现有 AlphaGen AST、PPO、断点 checkpoint 和 `run_state.json`。
4. 将生成表达式和指标写入股票池专属的因子运行目录。

因子记录必须增加：

- `pool_id`。
- `source_signature` 和 runtime signature。
- 原始 AlphaGen 表达式 `expression`。
- 可回测表达式 `backtest_expression`。
- 生成任务 ID 和时间范围。
- train/valid/test 的 IC、RankIC、ICIR、coverage、score。

默认先沿用当前 runtime 配置中的技术指标字段，后续通过字段配置扩展财务字段；不因为主 CSV 字段很多而默认将所有字段放入 PPO 状态空间。

## 7. 表达式适配

AlphaGen 表达式保留为研究结果的原始真值，回测前经过显式适配和校验。

适配器负责：

- 去除并校验字段名中的 `$` 标记。
- 将 `20d` 转成回测引擎所需的整数窗口。
- 将 `Ref/Mean/Sum/Std/Var/Max/Min/Delta` 等 AlphaGen 算子映射到 custom 表达式算子。
- 将 `Add/Sub/Mul/Div` 等函数形式转换为安全的 custom 表达式形式。
- 对 custom 当前缺少的等价时间序列算子补齐实现或明确标记为不支持。

每条合格因子在回测前必须通过：字段存在性、算子签名、表达式 AST 安全校验和小样本数值结果检查。适配失败的因子只记录失败原因，不进入回测。

## 8. 合格因子回测

建议命令接口：

```powershell
python -m custom_bt.cli backtest-factors --pool liquid_500 --factor-run <run_id> --accepted-only
```

回测任务只读取因子目录中 `accepted=true` 的记录，并使用同一个 `pool_id` 的行情数据。每个因子单独保存回测结果，另生成一个汇总表比较：

- 组合收益和年化收益。
- Sharpe、最大回撤、胜率。
- 换手率、交易成本和交易次数。
- 因子生成阶段的 IC/ICIR 与回测阶段的表现。

输出建议为：

```text
custom_backtester/outputs/<pool_id>/<factor_run_id>/
  factor_backtest_summary.csv
  <factor_id>/daily_report.csv
  <factor_id>/annual_metrics.csv
  <factor_id>/trades.csv
  <factor_id>/positions.csv
  <factor_id>/summary.json
```

## 9. Streamlit 平台

现有回测页面扩展为以下区域：

1. 数据源与主缓存状态：源文件、字段配置、数据签名、日期范围。
2. 股票池：创建、查看、复制和选择 `pool_id`。
3. 因子生成：选择股票池、字段、时间切分、质量阈值，提交后台任务。
4. 因子目录：查看 PPO 找到的表达式及 train/valid/test 指标。
5. 因子回测：批量回测合格因子，查看排序和明细。
6. 历史任务和结果：支持断点恢复、失败原因和结果下载。

原有手工输入 Alpha 表达式的回测入口保留，作为调试和人工验证功能。

## 10. 迁移与删除策略

迁移顺序：

1. 使用小样本或限制行数验证新导入器。
2. 用完整 CSV 构建 master cache。
3. 生成 500 股票池并完成一次 PPO 生成冒烟测试。
4. 对至少一个合格因子完成回测并检查输出。
5. 对比新旧回测引擎的同一表达式结果。
6. 确认新链路稳定后，再删除旧的 `custom_backtester/data_cache/sample_store`、`stock_daily` 和 `sample_200k.csv`。

删除只针对旧缓存，不删除源码、因子结果和回测结果；删除前保留主数据源 CSV。

## 11. 错误处理与可恢复性

- 主缓存和股票池使用数据签名，防止读取错误版本。
- 生成任务沿用 checkpoint 和 `run_state.json`，服务器中断后可恢复。
- 回测任务逐因子记录状态，单个因子失败不阻塞其他因子。
- 股票池不足、字段缺失、表达式不支持、内存不足和数据日期不连续都写入任务状态和错误日志。
- 生成和回测禁止静默切换股票池；`pool_id` 不匹配时直接失败。

## 12. 验收标准

1. 不整体加载 20GB CSV，能够流式构建主缓存。
2. 能生成至少 500 只股票的命名股票池，并能再生成另一规模股票池。
3. 生成任务只使用选中的股票池，能恢复 PPO checkpoint。
4. 合格因子记录中包含生成指标和 `pool_id`。
5. 回测只处理合格因子，且使用同一 `pool_id`。
6. Streamlit 能查看因子表达式、质量指标、回测指标和结果文件。
7. 新链路验证完成后，旧 custom 数据缓存可安全移除。

## 13. 非目标

- 本阶段不重写 PPO 算法。
- 本阶段不默认启用全部财务字段参与强化学习。
- 本阶段不改变现有 TopK 交易规则，除非兼容测试发现必要问题。
- 本阶段不删除原始 CSV。
