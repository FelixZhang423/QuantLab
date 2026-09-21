# Custom Backtester

这是一个独立股票回测系统，直接读取你的原始日频面板 CSV，不依赖 Qlib。

核心流程：

1. 把 CSV 更新到本地缓存，缓存按股票拆成 `data_cache\stock_daily\stocks\*.parquet`
2. 查看当前可用字段和表达式算子
3. 在网页或命令行输入 alpha 表达式
4. 执行 TopK 日频回测
5. 保存 `daily_report.csv`、`annual_metrics.csv`、`trades.csv`、`positions.csv`、`summary.png`

## 1. 进入环境

```powershell
cd "F:\my_code_file\因子构建\custom_backtester"
conda activate alphagen
```

如缺少网页依赖：

```powershell
pip install streamlit
```

## 2. 第一次导入数据

默认只读取核心行情字段，速度更稳：

```powershell
python -m custom_bt.cli prepare `
  --csv "..\v_stock_daily_full.csv" `
  --out "data_cache\stock_daily"
```

如果你的 CSV 里新增了自己的因子字段、行业字段、财务字段，并且也想放入缓存：

```powershell
python -m custom_bt.cli prepare `
  --csv "..\v_stock_daily_full.csv" `
  --out "data_cache\stock_daily" `
  --all-columns
```

## 3. 后续补充新数据

以后你拿到新的日频 CSV，继续写入同一个缓存目录即可：

```powershell
python -m custom_bt.cli update `
  --csv "..\new_daily_data.csv" `
  --out "data_cache\stock_daily" `
  --all-columns
```

更新逻辑：

- `code` 统一成 6 位字符串
- `timestamps` 转成 `date`
- `vol` 改名为 `volume`
- 自动计算 `vwap = amount / volume`
- 按股票拆分保存
- 同一股票同一天重复时，保留后导入的数据
- 字段目录写入 `data_cache\stock_daily\meta.json`

## 4. 统一因子平台工作流

主数据源使用：

```text
F:\\my_code_file\\因子构建\\数据\\daily_with_maindata_v2.csv
```

这个文件约 20GB，平台会分块读取并构建主缓存，不会把整个文件加载进内存。主缓存建立后，因子生成和回测只读取所选股票池。

### 4.1 构建主缓存

默认字段配置在 `configs/platform.yaml`，先使用当前技术指标字段；需要更多财务字段时再追加到配置中：

```powershell
python -m custom_bt.cli prepare-master --config configs/platform.yaml
```

### 4.2 创建股票池

例如创建流动性前 500 股票池：

```powershell
python -m custom_bt.cli create-pool --config configs/pools/liquid_500.yaml
```

每个股票池会保存代码清单、筛选窗口、上市年限、覆盖率、数据签名和成交额统计，生成和回测通过同一个 `pool_id` 绑定。

### 4.3 在股票池上生成 PPO 因子

```powershell
python -m custom_bt.cli generate-factors `
  --pool "<pool_id>" `
  --config configs/factor_generation.yaml
```

生成结果位于 `factor_runs/<run_id>/`，包括：

```text
factor_run.json
accepted_factors.jsonl
rejected_candidates.jsonl
checkpoints/
```

### 4.4 只回测合格因子

```powershell
python -m custom_bt.cli backtest-factors `
  --pool "<pool_id>" `
  --factor-run "<run_id>" `
  --config configs/default.yaml
```

回测结果位于 `outputs/factor_backtests/<pool_id>/<run_id>/`，包含每个因子的收益、Sharpe、最大回撤、换手率和交易成本汇总。

### 4.5 网页查看

```powershell
python app/run_streamlit.py
```

网页新增“股票池”“因子生成”“因子回测”区域，可以查看池规模、PPO 找到的表达式、IC/ICIR/coverage，以及合格因子的回测效果。

旧的 `data_cache/stock_daily` 和 `sample_store` 只在新主缓存与一次端到端流程验证通过后再删除。

## 5. 查看字段和算子

查看当前缓存里有哪些字段可以写进表达式：

```powershell
python -m custom_bt.cli fields --data "data_cache\stock_daily"
```

查看当前有哪些算子：

```powershell
python -m custom_bt.cli operators
```

当前内置算子已经扩展到 Brain 风格的主要可实现部分：

- `arithmetic`：`abs`、`add`、`densify`、`divide`、`inverse`、`log`、`max`、`min`、`multiply`、`power`、`reverse`、`sign`、`signed_power`、`sqrt`、`subtract`
- `cross_section`：`normalize`、`quantile`、`rank`、`scale`、`winsorize`、`zscore`
- `group`：`group_backfill`、`group_mean`、`group_neutralize`、`group_rank`、`group_scale`、`group_zscore`
- `logic`：`equal`、`greater`、`greater_equal`、`if_else`、`is_nan`、`less`、`less_equal`、`not_equal`、`where`，并兼容 `and(...) / or(...) / not(...)`
- `time_series`：`days_from_last_change`、`hump`、`kth_element`、`last_diff_value`、`ts_arg_max`、`ts_arg_min`、`ts_av_diff`、`ts_backfill`、`ts_corr`、`ts_count_nans`、`ts_covariance`、`ts_decay_linear`、`ts_delay`、`ts_delta`、`ts_mean`、`ts_product`、`ts_quantile`、`ts_rank`、`ts_regression`、`ts_scale`、`ts_std_dev`、`ts_step`、`ts_sum`、`ts_zscore`
- `transformational`：`bucket`、`trade_when`
- `vector`：`vec_avg`、`vec_sum`

说明：本地 Python 表达式里 `and/or/not` 是保留字，系统会自动把函数调用形式的 `and(...) / or(...) / not(...)` 转成内部别名 `and_ / or_ / not_`。

## 5. 命令行回测

编辑 `configs\default.yaml` 里的表达式和参数，然后运行：

```powershell
python -m custom_bt.cli backtest `
  --data "data_cache\stock_daily" `
  --alpha-config "configs\default.yaml" `
  --run-name "demo_top50"
```

输出目录：

```text
outputs\demo_top50\
  daily_report.csv
  annual_metrics.csv
  trades.csv
  positions.csv
  summary.json
  summary.png
  manifest.json
```

查看已保存结果：

```powershell
python -m custom_bt.cli runs --outputs "outputs"
```

## 6. 网页工作台

```powershell
python app\run_streamlit.py
```

网页里可以做这些事：

- 看当前数据缓存的股票数、行数、日期范围
- 看可用字段
- 按分类看可用算子
- 输入 alpha 表达式并回测
- 查看 PNL / Drawdown 曲线
- 查看年度 `return / sharpe / max_drawdown / turnover / cost / win_rate`
- 查看历史保存结果
- 下载回测输出文件

## 7. 表达式例子

20 日动量：

```text
close / delay(close, 20) - 1
```

换手率反转：

```text
-rank(TurnoverRate)
```

均线偏离：

```text
close / ts_mean(close, 20) - 1
```

组合表达式可以写在 `configs\default.yaml`：

```yaml
alphas:
  - name: momentum_20
    expr: "close / delay(close, 20) - 1"
    weight: 1.0
  - name: turnover_reversal
    expr: "-rank(TurnoverRate)"
    weight: 0.5
```

## 8. 拓展算子

打开 `custom_bt\expressions.py`，新增函数并注册：

```python
def _neg(x):
    return -x

register_operator("neg", "custom", "Negative value.", _neg)
```

注册后：

- 命令行 `python -m custom_bt.cli operators` 能看到
- 网页 Operators 页面能看到
- 表达式里可以直接用，例如 `neg(rank(close))`

## 9. 回测规则

第一版规则：

- 多头 TopK
- `T` 日算 alpha
- `T+1` 日开盘成交
- 按 alpha 从高到低选前 `top_k`
- 等权持仓，并受 `max_weight_per_stock` 限制
- 跳过停牌股票
- 可配置是否跳过涨停买入、跌停卖出
- 成本 = 买入费率 / 卖出费率 + 滑点 + 最低手续费

这套逻辑目前不做空、不融资、不用 Qlib。

## Import note

The configured source file is tab-separated despite its `.csv` suffix. The master-cache importer auto-detects tab, comma, semicolon, and pipe separators; `configs/platform.yaml` uses `delimiter: auto`.

For a large source, build the master cache once. Factor generation and factor backtesting then read only the selected pool from that cache; the full source is not loaded into memory for each factor.

## Streamlit startup and visual workflow

From the `custom_backtester` directory, run:

```powershell
python app/run_streamlit.py
```

Open the displayed local URL, usually `http://localhost:8501`.

The `平台任务` tab can submit the master-cache import. The `股票池` tab creates a named pool. The `因子生成` tab selects a pool and submits PPO generation. The `因子回测` tab selects a factor run and submits batch backtests for accepted factors. All four operations run in the background and can be monitored in `后台任务`; the original `回测` tab remains available for manual expression debugging.
