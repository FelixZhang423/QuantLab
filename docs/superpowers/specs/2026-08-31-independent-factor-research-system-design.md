# 独立因子研究系统设计

## 1. 目标与边界

本项目建立一个研究阶段使用的、无前端的独立因子研究系统。它研究已有因子以及已有 PPO 生成因子，完成以下流程：

1. 从原系统导出版本化研究数据快照。
2. 对已有因子进行元数据登记和类别归纳。
3. 从行情数据构造市场状态特征并识别市场状态。
4. 研究不同因子类别在不同市场状态下的表现。
5. 根据当前或指定日期的市场状态选择优势类别。
6. 在类别内按条件表现、稳定性和相关性选择具体因子，并形成组合。
7. 使用时间切分的验证集和样本外数据回测组合。

原系统是数据来源，不是新系统的运行时依赖。导出完成后，研究代码不能导入 `custom_bt`、`single_factor` 或读取原系统目录。新系统不负责 PPO 训练，也不承担生产交易服务。

## 2. 总体架构

```
原系统数据产出
        |
        v
research_pipeline.export  --->  research_data/snapshots/<snapshot_id>
                                      |
                                      v
research_pipeline.io  --->  统一长表与清单校验
                                      |
             +------------------------+-----------------------+
             v                        v                       v
       factor_catalog           market_state             factor_evaluation
             |                        |                       |
             +------------ conditional research ------------+
                                      |
                                      v
                              selection + portfolio
                                      |
                                      v
                              research_runs/<run_id>
```

核心模块职责如下：

- `exporter.py`：只负责读取原系统已存在的文件、标准化列名、复制必要记录、写入快照清单。
- `schema.py`：定义文件名、必需列和版本号，避免隐式字段约定。
- `io.py`：只读取独立数据目录，执行日期、代码、数值类型和唯一键校验。
- `features.py`：从行情长表构造市场状态特征和未来收益标签。
- `evaluation.py`：计算因子整体和状态条件下的 IC、Rank IC、ICIR、分组收益、覆盖率、稳定性等指标。
- `selection.py`：按类别得分、因子条件表现和互相关约束选择因子，输出可审计的选择日志。
- `cli.py`：提供 `export`、`validate`、`evaluate`、`select`、`run` 命令；所有参数来自 YAML/JSON 配置或命令行。

## 3. 独立数据目录

目录约定如下：

```
research_data/
  README.md
  manifest.json
  snapshots/
    <snapshot_id>/
      manifest.json
      market.parquet
      universe.csv
      factor_catalog.parquet
      factor_metrics.parquet
      backtest_metrics.parquet
      backtest_runs.csv
      source_metadata.json
  current -> snapshots/<snapshot_id>   # Windows 下用 current.txt 替代
research_pipeline/
  config.example.yaml
  research_system/
  tests/
research_runs/
  <run_id>/
    config.json
    market_states.parquet
    conditional_metrics.parquet
    selection.json
    portfolio_metrics.json
    manifest.json
```

`market.parquet` 是行情长表，主键为 `(date, code)`。导出时保留原系统当前 PPO 可用的 38 个字段，并额外保留 `market_code`、`category`、`ListedSector`、`ListedState`、`StockBoard`（若来源存在）。`vol` 统一改名为 `volume`，`timestamps` 统一改名为 `date`。

`universe.csv` 至少包含 `code`、`pool_id`、`selected_at`、`source_signature`；同一个 `pool_id` 下代码唯一。若只有静态股票池，`selected_at` 使用股票池选择结束日期，并在研究中明确这是静态池，而非未来每期动态成分股。

`factor_catalog.parquet` 每行一个因子，至少包含：

`factor_id`、`expression`、`canonical_expression`、`backtest_expression`、`factor_run_id`、`pool_id`、`source_signature`、`accepted`、`expected_direction`、`category`、`category_source`、`rationale`。

`category` 初始允许为空。类别可以由人工标签、表达式规则或后续聚类生成，但必须记录 `category_source`，不能把聚类结果伪装成人工经济含义。

`factor_metrics.parquet` 是因子生成阶段的指标长表或宽表归一化结果。至少保存 `factor_id`、`metric_scope`、`split`、`horizon`、`ic`、`rank_ic`、`icir`、`rank_icir`、`coverage`、`sample_count`、`calculated_at`。缺失指标必须为空值，不使用 0 冒充。

`backtest_metrics.parquet` 每行一个因子回测结果，至少包含 `factor_id`、`backtest_run_id`、`split`、`start_date`、`end_date`、`total_return`、`annual_return`、`sharpe`、`max_drawdown`、`calmar`、`win_rate`、`average_turnover`、`total_cost`、`number_of_trades`、`average_holding_count`。原系统只有汇总文件时照实导出，不推断不存在的指标。

研究代码内部会生成：

- `market_states.parquet`：`date`、状态特征、`state_id`、`state_label`、`state_method`、`fit_window_end`。
- `conditional_metrics.parquet`：`factor_id`、`category`、`state_id`、`split`、`horizon`、`sample_count`、`coverage`、`ic_mean`、`rank_ic_mean`、`icir`、`long_short_return`、`hit_rate`、`stability`。
- 因子值文件为可选输入，统一使用长表 `(date, code, factor_id, value)`；当前原系统未稳定保存逐因子值时，不伪造该文件，先使用已有生成指标与回测汇总，后续再由独立表达式计算器生成。

## 4. 导出规则

导出命令接收原系统根目录、行情面板路径、股票池目录、因子运行根目录、回测结果根目录和目标 `research_data` 路径。默认只读，不删除或覆盖原系统文件。每次导出使用时间戳加源签名生成 `snapshot_id`；目标快照已存在时直接报错，避免静默覆盖。

导出过程：

1. 读取 `panel.parquet`，只保留真实存在且被配置允许的字段，标准化 `date`、`code`、`volume` 和数值类型。
2. 读取股票池 `codes.txt` 与 `manifest.json`，生成 `universe.csv`。
3. 扫描因子运行目录中的 `factor_run.json`、`accepted_factors.jsonl` 和必要的拒绝记录；优先登记 accepted 因子。
4. 扫描回测结果目录的 `factor_backtest_summary.csv`，将 `generation_` 和 `backtest_` 前缀归一为 `factor_metrics`、`backtest_metrics` 对应字段，并保留来源路径。
5. 对所有输出文件计算 SHA-256、记录行数、列名、日期范围和来源文件，写入 snapshot manifest。
6. 校验快照；只有校验通过才更新根目录的 `manifest.json` 和 `current.txt`。

导出不把原系统的绝对路径写入研究计算配置；绝对路径只允许出现在来源审计信息中。目标目录若已有快照，新增快照不会影响旧快照。

## 5. 研究方法

### 5.1 数据质量

先检查 `(date, code)` 重复、日期解析失败、代码缺失、价格非正、停牌数据、缺失比例、异常极值和来源签名一致性。每个研究运行都固定 `snapshot_id`、股票池、日期范围、预测周期、成本和切分边界。

### 5.2 市场状态

第一版采用可解释的规则/聚类接口：从宽基市场横截面或可选指数构造收益趋势、波动率、成交额变化、上涨比例、涨跌停比例和横截面离散度；对特征使用仅基于过去数据的滚动标准化。默认规则标签为 `bull`、`bear`、`sideways`、`high_volatility`，规则阈值必须进入配置。后续可以替换为 K-Means/HMM，但必须在训练窗口拟合，验证和测试窗口只调用已拟合参数，并保存 `state_method` 与 `fit_window_end`。

### 5.3 因子分类

分类按证据强度分三层：人工经济含义标签、表达式结构规则、数值行为聚类。结构规则从表达式中提取基础字段族（价格、成交量、波动、趋势、技术指标）和算子族；聚类使用因子在共同样本上的横截面序列或日度 IC 序列，并进行标准化。类别数量、距离、随机种子和缺失处理必须可复现。分类是描述性步骤，不允许直接用测试期收益反向命名类别。

### 5.4 条件表现与选择

在每个时间切分、预测周期和市场状态内计算 IC、Rank IC、ICIR、覆盖率、分组收益、长短组合收益、命中率和稳定性。类别得分以成员因子在训练窗口的稳健聚合为主，至少要求最小样本日数和最小覆盖率；验证窗口只用于选择规则和阈值确认，测试窗口只用于最终报告。

类别选择后，因子选择按条件表现、整体表现、稳定性、换手/成本和与已选因子的互相关综合排序。组合权重先采用等权或风险缩放基线，只有在样本外改进稳定且约束明确时再使用优化权重。输出所有入选和淘汰原因。

### 5.5 回测与防泄漏

至少使用 train/validation/test 三段时间切分，禁止随机打乱。因子在日期 `t` 使用的信息只能来自 `t` 或之前，交易价格按配置的下一开盘或下一交易时点执行。状态模型、分类器、标准化器、阈值和权重都必须在训练窗口拟合或确定。测试期只能运行一次最终方案。回测需计入手续费、滑点、停牌和涨跌停约束，并同时报告收益、Sharpe、最大回撤、Calmar、换手、成本和持仓数量。

## 6. 错误处理与可审计性

- 缺少必需文件或列：立即失败并指出路径、文件和缺列。
- 源文件存在但没有有效行：失败，不生成半成品 current 快照。
- 日期、代码或指标无法解析：记录行数；超过配置容忍度则失败，否则丢弃并在 manifest 记录。
- 因子缺少值文件：允许导出，但在需要逐值计算的研究命令中明确失败，不默认为零。
- 任何实验输出都包含配置、快照签名、代码版本（若可获得）、随机种子和输入文件哈希。

## 7. 验证策略

使用小型合成面板做单元测试和端到端测试：验证列名标准化、代码补零、静态股票池导出、JSONL 因子登记、回测汇总解析、manifest 哈希、重复键检测、未来收益标签和状态条件 IC。再对当前仓库真实文件运行 `export` 与 `validate`，检查输出行数、日期范围和字段集合；不运行 PPO，不修改原系统数据。

