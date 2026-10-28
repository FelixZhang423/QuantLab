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
cd backend          # 从仓库根目录进入
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

回测结果位于 `outputs/saved_backtests/factor/<pool_id>/<run_id>/`，包含每个因子的收益、Sharpe、最大回撤、换手率和交易成本汇总。Web/平台任务提交时会再套一层批次目录 `<backtest_id>/`（即 job_id），重复回测不覆盖历史结果。

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

From the `backend` directory, run:

```powershell
python app/run_streamlit.py
```

Open the displayed local URL, usually `http://localhost:8501`.

The `平台任务` tab can submit the master-cache import. The `股票池` tab creates a named pool. The `因子生成` tab selects a pool and submits PPO generation. The `因子回测` tab selects a factor run and submits batch backtests for accepted factors. All four operations run in the background and can be monitored in `后台任务`; the original `回测` tab remains available for manual expression debugging.

## MySQL 集中存储（股票池 / 因子 / 回测）

股票池以 MySQL 为主存储：`GET /api/pools` / `GET /api/pools/{pool_id}` 优先读 MySQL，
连不上或未配置时回退本地 `data_cache/pools`；建池成功后自动写入 MySQL，重复同步幂等。
删除池用 `DELETE /api/pools/{pool_id}?confirm=true`，会同时清理 MySQL 四张池表与本地池目录。
因子运行与回测结果仍以本地文件（`factor_runs`、`outputs/saved_backtests`）为准，MySQL 只做集中存档。

连接配置（环境变量优先，其次本地文件）：

```powershell
# 长期配置：复制模板后填写；mysql.local.env 已被 **/*.local.env 忽略
copy configs\mysql.env.example configs\mysql.local.env

# 或当次会话临时指定
$env:QL_MYSQL_HOST = "127.0.0.1"
$env:QL_MYSQL_PORT = "3306"
$env:QL_MYSQL_USER = "quantlab"
$env:QL_MYSQL_PASSWORD = "<密码>"
$env:QL_MYSQL_DATABASE = "QuantLab"
```

安装驱动（已加入 `requirements.txt`）：

```powershell
py -3 -m pip install PyMySQL
```

表结构：

| 分组 | 表 |
| --- | --- |
| 股票池 | `pools`、`pool_codes`、`pool_candidates`、`pool_stats` |
| 因子 | `factor_runs`、`factors` |
| 回测 | `backtests`、`backtest_components`、`backtest_daily`、`backtest_annual`、`backtest_trades`、`backtest_positions` |
| 批量因子回测 | `factor_backtest_runs`（批次汇总，主键 `backtest_id`） |

常用命令（在 `backend` 目录）：

```powershell
py -3 -m custom_bt.mysql_store schema   # 幂等建表
py -3 -m custom_bt.mysql_store check    # 连接自检 + 各表行数
py -3 -m custom_bt.cli mysql-sync       # 把现有本地结果补录到 MySQL
```

说明：MySQL 未配置或连不上时，股票池接口自动回退本地文件，建池/回测也不受影响；密码不会进入日志、响应或 manifest。

## Web API（React 原型用）

`frontend/` 下的 React 前端通过 `/api/*` 读取真实数据，接口层在 `api/main.py`（FastAPI；查询端点 + 建池 `POST /api/pools` + 批量因子回测 `POST /api/factor-backtests` + 手动回测 `POST /api/manual-backtests`）。
在 `backend` 目录启动：

```powershell
python -m api
```

默认监听 `127.0.0.1:8000`，可用环境变量 `QL_API_HOST` / `QL_API_PORT` 覆盖。
本机若 `python` 是 Windows 商店占位程序（退出码 49），改用 `py -3 -m api`。

日志除了照旧打在控制台，还会同时落盘到 `outputs/logs/`（`api_<日期>.log` 应用/错误日志、
`api_access_<日期>.log` 每请求一行），关窗后依然可查。`QL_API_LOG=0` 关闭落盘，
`QL_API_LOG_DIR=D:\logs` 换目录，详见 `docs/web_api.md` §5.1。

**数据总览 / 数据字段 / 股票列表 / 股票池候选查公司 ClickHouse（HTTP 只读，实时）**，需要在公司网络下并配置凭据：
环境变量 `QL_CH_PASSWORD`（以及可选的 `QL_CH_HOST` / `QL_CH_PORT` / `QL_CH_USER`）优先，其次读本地文件
`configs/clickhouse.local.env`（已 gitignore，格式见同目录模板与 `.env.example`，不要提交）。
没配凭据时所有依赖公司库的端点返回 503 并带中文原因，其余端点不受影响。

端点：

- `GET /api/data/master` 实时数据源概况（行数、股票数、日期区间、可用字段数、查询时间）
- `GET /api/data/fields` 实时字段清单（库表结构 + 中文说明 + 能否进回测面板）
- `GET /api/data/stocks` 实时股票清单（全市场逐股聚合 + 简称/行业/上市信息）
- `GET /api/universe/options` 股票池筛选分布（行业/市场/板块/库内原始编码）
- `GET /api/universe/stocks` 股票池候选预览（条件筛选 + 服务端分页；候选不再与本地缓存取交集）
- `GET /api/universe/codes` 当前筛选下全部匹配代码（预览表格跨页全选/反选）
- `POST /api/pools` 按筛选结果建池（可传 `selected_codes` 只建勾选股票；202 + job_id，后台子进程执行；选样统计直接查公司库）
- `GET /api/jobs/{job_id}` 建池任务状态（queued / running / finished / failed）
- `GET /api/operators` 表达式算子（operator_registry + 中文说明/示例）
- `GET /api/pools`、`GET /api/pools/{pool_id}` 股票池清单与明细（含池内代码与筛选来源）
- `DELETE /api/pools/{pool_id}?confirm=true` 删除股票池（同步清理本地目录 + MySQL 记录；因子运行/历史回测不级联删除）
- `GET /api/factor-runs`、`GET /api/factor-runs/{run_id}` 因子运行与合格因子清单（`factor_id` 可直接用于提交）
- `POST /api/factor-backtests` 提交批量因子回测（可传 `factor_ids` 只回测勾选因子；202 + job_id）
- `GET /api/factor-backtests`、`GET /api/factor-backtests/{backtest_id}` 批次列表与汇总/失败明细（每行带 `run_key`）
- `GET /api/factor-backtests/{backtest_id}/files/{file_name}` 下载批次汇总/失败 CSV
- `POST /api/manual-backtests` 按股票池 + Alpha 表达式提交手动回测（202 + job_id；公司库池实时读面板，旧本地池回退 `data_cache/master`）
- `GET /api/results`、`GET /api/results/{run_name}` 已保存回测结果（净值/年度指标/文件清单；手动回测 `run_key = manual/<job_id>/<run_name>`）
- `GET /api/results/detail?run_key=...`、`GET /api/results/file?run_key=...` 按相对路径打开/下载任意层级结果（嵌套因子结果用这个）
- `GET /api/results/{run_name}/files/{file_name}` 下载旧扁平结果文件（按 manifest 白名单）

边界：股票池候选、建池选样、因子生成面板、因子回测面板与手动回测面板**全部直接读公司 ClickHouse**，不再依赖本地
`data_cache/master`。公司库有、本地缓存没有的股票同样可以建池和回测。公司库签名固定为
`clickhouse:dws.ll_stock_daily_sharing`；旧本地缓存池 manifest 没有 `data_source` 时仍按本地数据源读取，
仅用于兼容历史池/因子运行。行业只取 `dim.stock_main_info_fd.FirstIndustryName` 单级行业（申万一级；
`Industry` 列是细分行业编码，不能直接当单级行业用）；市场/板块由代码前缀推导。

前端开发时由 vite 把 `/api` 代理到该地址（见 `frontend/vite.config.ts`，可用 `QL_API_TARGET` 覆盖）。
建池、批量因子回测与手动回测的 POST 已接入；结果详情页只读真实结果（`/api/results` + `/api/results/detail`，
兼容手动 `config.backtest` 与因子扁平 `config`）；因子生成/组合的提交端点仍在后续步骤。

已接入的真实数据清单（各端点的实测值）与前后端技术栈详见 [docs/web_api.md](docs/web_api.md)。
