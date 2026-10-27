# Web API 数据清单与技术栈（React 原型接入）

> 更新时间：2026-10-25（因子运行列表 + 批量因子回测 `POST /api/factor-backtests`，见 §2.9）｜ 后端代码：`custom_backtester/api/` ｜ 前端接入层：`原型/src/api/client.ts`
> 相关：README「Web API（React 原型用）」、`quantops/README.md`、`progress.md`「2026-10-10 React 原型接入只读 API（第一步）」「2026-10-10 展示端点切换 ClickHouse 实时数据」「2026-10-14 算子抽成独立库 quantops」「2026-10-15 后端日志落盘」「2026-10-20 股票池接入公司数据库真实股票」「2026-10-25 MySQL 集中存档」「2026-10-25 因子批量回测接入 Web」

## 1. 架构总览

```
浏览器（React 原型 :8443）
   └─ fetch /api/*  →  Vite dev proxy（/api → 127.0.0.1:8000）
          └─ FastAPI（custom_backtester/api，:8000，GET + POST）
                 ├─ 数据总览 / 数据字段 / 股票列表 / 股票池候选 → api/live_db.py
                 │        └─ ClickHouse HTTP（<公司ClickHouse地址>:8123，dws.ll_stock_daily_sharing + dim.stock_main_info_fd，实时）
                 ├─ 股票池 → MySQL `pools` / `pool_codes` 优先，连不上回退 data_cache/pools/
                 ├─ 操作符 / 因子运行 / 回测结果 → 复用 custom_bt 现有函数 + 直接读本地文件
                 │        factor_runs/、outputs/saved_backtests/
                 └─ POST /api/pools、POST /api/factor-backtests
                          → create_platform_job + api/job_runner.py 子进程
                          outputs/jobs/<job_id>/ → create_pool / backtest_accepted_factors
```

- **数据总览 / 数据字段 / 股票列表 / 股票池候选是实时查询**：直接查公司 ClickHouse（只读 HTTP，见 §2.7），数值随数据库当天更新。股票池列表/详情优先读 MySQL，未配置或连不上时回退本地 `data_cache/pools/`；因子运行与回测结果仍读本地文件。
- **回测链路仍用本地主缓存**：`data_cache/master`（`prepare-master` 导入的快照）依旧是因子生成 / 股票池数据 / 回测的唯一数据源。股票池候选由公司库决定，但建池前会与本地缓存取交集，池内数据与回测链路不变；两边日期口径不同，页面上均有标注。
- **写操作有 `POST /api/pools`、`POST /api/factor-backtests`**：都只创建后台任务（202 + job_id），由子进程执行，不在 API 进程内同步运行；因子生成 / 因子组合的提交端点仍未接入（见 §6）。
- **因子回测结果按批次版本化**：`outputs/saved_backtests/factor/<pool_id>/<run_id>/<backtest_id>/<factor_id>/`，`backtest_id` 即平台任务 job_id；同一因子运行用不同参数重复回测不会覆盖历史批次（§2.9）。
- 端口：后端 8000（`QL_API_HOST` / `QL_API_PORT` 可改），前端 8443（`PORT` 可改），代理目标用 `QL_API_TARGET` 覆盖。
- 实时数据源凭据：环境变量 `QL_CH_PASSWORD`（及可选 `QL_CH_HOST/PORT/USER`）优先，其次 `configs/clickhouse.local.env`（已 gitignore）；未配置时所有依赖公司库的端点（三个展示端点、三个候选端点、`POST /api/pools`）返回 503 + 中文原因，其余端点不受影响。

## 2. 已接入的真实数据（逐个端点）

| 端点 | 前端页面 | 真实来源 | 实测内容 |
| --- | --- | --- | --- |
| `GET /api/data/master` | 数据总览 | **ClickHouse 实时**（`dws.ll_stock_daily_sharing`） | 1736.9 万行 / 5589 只 / 1990-12-19 ~ 2026-10-09 / 70 可用字段 |
| `GET /api/data/fields` | 数据字段 | **ClickHouse 实时**（`system.columns`，行情表 + dim 表） | 70 个字段（含中文说明与「面板可用」标记） |
| `GET /api/data/stocks` | 股票列表 | **ClickHouse 实时**（逐股聚合 + `dim.stock_main_info_fd` 名称/行业/上市信息） | 5589 只个股（含名称，实测以当日数据库为准） |
| `GET /api/universe/options` | 股票池筛选 | **ClickHouse 实时**（行情聚合 + dim 行业/上市信息） | 行业/市场/板块分布、可建池与自动排除统计 |
| `GET /api/universe/stocks` | 股票池预览 | **ClickHouse 实时**（同一份快照，Python 过滤 + 分页） | 候选清单 + 排除示例 + 本地可建池标记 |
| `GET /api/universe/codes` | 股票池预览（全选/反选） | **ClickHouse 实时**（同一份快照，仅返回代码） | 当前筛选下全部可建池代码（跨页勾选） |
| `POST /api/pools` | 股票池提交 | 候选来自 ClickHouse，建池读本地 `data_cache/master`，成功后写 MySQL | 202 + `job_id`（后台任务） |
| `GET /api/jobs/{job_id}` | 建池任务状态 | `outputs/jobs/<job_id>/status.json` | queued / running / finished / failed |
| `GET /api/operators` | 操作符 | `expressions.list_operators()` + `operator_registry` | 80 个算子（中文分类/说明） |
| `GET /api/pools` `/{pool_id}` | 因子股票池 | **MySQL 优先**（`pools.manifest` + `pool_codes`），回退 `data_cache/pools/*/manifest.json` + `codes.txt` | 5 个股票池；响应带 `storage` 标记 |
| `GET /api/factor-runs` `/{run_id}` | 因子回测（运行选择） | `factor_runs/<run_id>/factor_run.json` + `accepted_factors.jsonl` | 合格因子清单与生成指标 |
| `POST /api/factor-backtests` | 因子回测（提交） | 复用 `backtest_accepted_factors`，读本地 master / pool | 202 + `job_id`（后台任务） |
| `GET /api/factor-backtests` `/{backtest_id}` `/.../files/{file}` | 因子回测（批次结果） | `outputs/saved_backtests/factor/<pool>/<run>/<backtest_id>/` | 批次汇总行、失败明细与 CSV 下载 |
| `GET /api/results/detail?run_key=...`、`GET /api/results/file` | 回测结果 | 任意层级的结果目录（`run_key` 相对路径） | 嵌套因子结果按 `run_key` 打开与下载 |
| `GET /api/results` `/{run_name}` `/{run_name}/files/{file}` | 回测结果（兼容旧扁平名） | `outputs/saved_backtests/*/` | 1 个已保存回测（含净值/指标/文件下载） |

### 2.1 数据总览（实时，实测 2026-10-10）

来源 SQL：`SELECT toString(count()), toString(uniqExact(code)), min(timestamps), max(timestamps) FROM dws.ll_stock_daily_sharing WHERE category='stock'`（冷查询 2.9s）。

- **17,368,843 行 / 5,589 只**，区间 **1990-12-19 ~ 2026-10-09**（全历史口径，比本地缓存宽）
- 页面同时显示**本地主缓存口径**小字提示：股票池 / 回测仍使用 `data_cache/master` 快照（2021-06-18 ~ 2026-06-16，599.0 万行 / 5432 只，签名 `8afffe05…`）
- 字段数与字段页共用同一份实时目录（见 2.2），两页数字一致；前端「可用字段」卡片即此数

### 2.2 字段目录（70 个，实时）

来源：`system.columns` 查 `dws.ll_stock_daily_sharing`（去掉 `code` / `timestamps` 两个行标识列，66 列）+ `dim.stock_main_info_fd` 的 4 列（`ListedDate` / `ListedSector` / `ListedState` / `ChiNameAbbr`），按库内列序返回。

- 中文说明优先级：`v_stock_daily_full_字段说明.md` → 库内列注释（70 个里有 49 个库自带注释）→「暂无字段说明」
- 类型为库内原始类型压缩显示（`Nullable(Decimal(18, 2))` → `Decimal(18,2)?`）；示例：`close` 收盘价、`vol` 成交量（说明里标注「回测面板中名为 volume」）、`Ifsuspend` 是否停牌、`ListedDate` 上市日期
- 每行带 **「面板」标记**：该字段是否也在本地主缓存里（能进回测表达式面板）。实测 **44 个「面板可用」/ 26 个「仅数据库」**；本地独有的计算列 `vwap` 不再出现（数据库没有）

### 2.3 股票列表（5589 只，实时，冷查询 3.6s）

来源：`dws.ll_stock_daily_sharing` 按 `code` 分组聚合（行数 / 起止日期 / 最新收盘价、成交量、成交额、最新停牌，取 `argMax(..., timestamps)`），名称/行业/上市信息来自 `dim.stock_main_info_fd`。

- 每只返回：`code / name / rows / start_date / end_date / latest_date / latest_close / latest_volume / latest_amount`，以及 2026-10-20 起新增的 `industry / sector / listed_state / listed_date / latest_ifsuspend`（与候选池共用同一份 `live_stock_rows` 快照；市场/板块由代码前缀推导后仅出现在候选端点）
- 示例（2026-10-10 实测）：`000001` 平安银行 8824 行 1991-04-03 ~ 2026-10-09 最新收 11.59；`600519` 贵州茅台 6083 行（2001-08-27 起）最新收 1263.00；`300750` 宁德时代 2012 行（2018-06-11 起）；`920879` 88 行（2026-03-27 ~ 2026-08-05，次新股/已停止更新）
- 5589 只中 360 只没有简称（退市 / 不在 dim 表），页面显示 `—`（如 `000004`、`000584`）；搜索支持代码和名称（如「平安」）
- 与本地缓存口径的差异：缓存是 2021 年起、5432 只；实时是全历史（含退市），因此行数、股票数、最新日期都更大
- 该端点与股票池候选共用 `stock_rows` 快照（默认 300s，`QL_CH_UNIVERSE_TTL` 可调）；响应里的 `cached / queried_at` 标明本次是否命中缓存。`QL_CH_CACHE_TTL=0` 不会关掉这份候选快照。

### 2.4 操作符（80 个）

来源：`expressions.list_operators()` 与 `operator_registry` 合并，经 `enrich_operators` 补中文分类与说明。

> 2026-10-14 起，这两个函数的实现已搬到独立库 **`quantops/`**（算子唯一实现，库路径 `../quantops`）：`custom_bt/expressions.py` 与 `custom_bt/operator_registry.py` 只剩转发，`expressions.OPERATORS is quantops.operators.OPERATORS`。**本端点响应逐字节不变**（迁移前后 `/api/operators` JSON diff 为空）。改算子请去 `quantops/quantops/operators.py`；`custom_bt/docs.py` 仍是中文元数据的源头（`quantops/metadata.py` 存副本，两边由 `tests/test_quantops_metadata_parity.py` 锁死）。

- 分类分布：时间序列 34、数学运算 18、逻辑判断 12、横截面 6、分组 6、信号转换 2、向量 2
- 其中 **25 个**可进入因子生成（页面显示「可生成」标签）

### 2.5 股票池（1 个：liquid_500）

来源：`data_cache/pools/liquid_500_864dc25f/`（manifest.json + codes.txt）。

| 项目 | 值 |
| --- | --- |
| 池 ID / 名称 | `liquid_500_864dc25f` / liquid_500 |
| 成分数 | 500（top_n 500，剔除停牌） |
| 选样窗口 | 2021-06-18 ~ 2024-07-26，共 755 个交易日 |
| 过滤条件 | 上市满 250 天、有效行 ≥ 680、覆盖率 ≥ 0.9 |
| 实际覆盖率 / 平均成交额 | 99.87% / 8.107 亿元 |
| 状态 / 数据签名 | active / `8afffe05f056f5cb…`（与 master 一致） |

详情端点额外返回 500 个成分代码（示例：300750、600519、300059、002594、601012），前端抽屉展示前 24 个。

2026-10-20 起新建的池（`POST /api/pools`）manifest 还会带 `provenance`（来源表/端点、查询时间、筛选条件、匹配/建池/排除统计与示例）和 `strict_top_n`；两者不参与 `pool_id` 哈希。老池没有这两个字段，接口返回 `null`。

### 2.6 已保存回测（1 个：web_run）

来源：`outputs/saved_backtests/web_run/`（manifest + summary.json + CSV）。

- 类型 manual，创建于 2026-09-29 09:48；表达式 `close / delay(close, 20) - 1`（20 日动量），未限定股票池（全市场），初始资金 1 亿
- **1202 个净值点**（2021-06-18 起）+ 6 个年度指标；净值 = `daily_report.csv` 净值 / initial_cash
- 指标：sharpe -2.84、最大回撤 -100%、胜率 17.89%、平均换手 15.43%、12,503 笔交易；`annual`/`calmar` 为 **null**（源数据是 NaN，见 §7）
- 可下载文件 6 个：daily_report.csv（175KB）、positions.csv（3.4MB）、trades.csv（1.2MB）、annual_metrics.csv、summary.json、summary.png
- ⚠️ 这是链路验证用的演示跑批（累计 -100%），**不代表任何策略结论**；前端「回测结果」页可切换「演示任务 / 真实结果」两个视图

`GET /api/results` 的每条结果都带 `run_key`（结果目录相对 `outputs/saved_backtests` 的路径，也是 MySQL `backtests` 主键）。旧的扁平结果 `run_key = web_run`；因子批次结果是多级路径，前端必须用 `run_key` 调 `GET /api/results/detail` / `GET /api/results/file`，不能再把 `run_name` 当路径。`/api/results/{run_name}` 仅保留给旧扁平结果。

### 2.7 实时数据源（ClickHouse HTTP 只读）

实现：`api/live_db.py`（**纯 stdlib urllib，无新依赖**）。展示端点与股票池候选共用一份连接与缓存。

| 配置项 | 默认值 | 环境变量 |
| --- | --- | --- |
| 主机 / 端口 | `<公司ClickHouse地址>` / `8123` | `QL_CH_HOST` / `QL_CH_PORT` |
| 用户 | `<用户名>` | `QL_CH_USER` |
| 密码 | 无（**必填**，缺失即 503） | `QL_CH_PASSWORD` |
| 连接超时 | 30s | `QL_CH_TIMEOUT` |
| 查询最大执行时间 | 20s | `QL_CH_MAX_EXECUTION_TIME` |
| 数据缓存 TTL | 60s | `QL_CH_CACHE_TTL` |
| 候选快照 TTL | 300s | `QL_CH_UNIVERSE_TTL` |
| 表结构缓存 TTL | 300s | `QL_CH_SCHEMA_TTL` |
| 启动预热 | 开 | `QL_CH_PREWARM=0` 关闭 |

- **凭据来源**：环境变量优先 → 其次 `configs/clickhouse.local.env`（`KEY=VALUE`，支持 `#` 注释与引号，**按 `utf-8-sig` 读以容忍记事本 BOM**）。该文件已被 `.gitignore` 的 `**/*.local.env` 忽略，**密码不写入任何文档或提交文件**。
- **4 个缓存 key**（key 级锁 + 双检 + single-flight，并发只打一次库）：`master_stats`（60s）、`field_catalog`（300s，schema 变更不频繁）、`dim_profiles`（300s，名称/行业/上市信息）、`stock_rows`（`universe_ttl`，默认 300s，合并 dim 后的逐股快照）。`QL_CH_CACHE_TTL=0` 可整体禁用展示缓存；候选快照用独立的 `QL_CH_UNIVERSE_TTL`，不受它影响。
- **本部署的缓存组合**（`configs/clickhouse.local.env` 里 `QL_CH_CACHE_TTL=0` / `QL_CH_SCHEMA_TTL=0` / `QL_CH_PREWARM=0`）：`master_stats` / `field_catalog` / `dim_profiles` 不缓存，每次请求都真查库；`stock_rows`（股票列表 + 股票池候选）用独立的 `QL_CH_UNIVERSE_TTL`（默认 **300s**），命中时响应 `cached: true`。*同一瞬间* 的并发重复请求（开发态 React.StrictMode 会把每页请求发两次）仍会合流成一次查询——第二次请求直接采用并发中的那次结果，不会拿到旧数据，也不会把 3.6 秒的全市场聚合白打两遍。
- **失败即报错、不静默回退**：未配密码 / 认证失败 / 网络不可达 → **503** + 中文原因；库端 SQL 报错 → **502** + 截断后的库错误正文（经密码脱敏）。前端 `LoadGate` 会把这行 `detail` 直接显示在页面上。
- **只读双保险**：SQL 全为模块常量（请求参数绝不拼进 SQL）+ 语句前缀白名单（`SELECT` / `WITH` / `DESCRIBE` / `SHOW` / `EXPLAIN`）与写类关键字黑名单。
- **禁系统代理**：查询走 `ProxyHandler({})` 显式绕过系统代理（公司网里带代理变量时否则会被劫持），连接类失败自动重试 1 次（0.5s），超时与 4xx/5xx 不重试。
- **实测查询耗时（含网络）**：总览聚合 **2.9s** / 字段目录 **0.1s** / 全市场逐股聚合 **3.6s**。2026-10-14 在展示缓存全关时实测两次串行请求 2.88s / 2.50s，均 `cached: false`；`stock_rows` 自 2026-10-20 起默认缓存 300s，命中时 <100ms，首次或过期后的请求仍约 3.5s。

### 2.8 股票池候选与建池（2026-10-20）

候选链路：

```
ClickHouse 行情聚合 + dim 行业/上市信息
  → GET /api/universe/options / /api/universe/stocks（Python 过滤 + 分页）
  → React 股票池页预览
  → POST /api/pools（筛选 → 与 data_cache/master 取交集 → 202 + job_id）
  → GET /api/jobs/{job_id} 轮询 → 子进程 create_pool → 刷新已有股票池
```

**`GET /api/universe/options`**：返回全库 `industries / exchanges / boards / sectors / listed_states` 的 `{value,label,count}`、缺失数量 `missing`、`master_total / creatable_total / excluded_total`、`master_ready` 与本地缓存日期区间；筛选下拉框直接用这份分布。

**`GET /api/universe/stocks`**（参数均可重复）：`industries / exchanges / boards / sectors / listed_states / q / min_listed_days / as_of / master_only / limit(≤500) / offset`。

- `matched_total` 是 facet 过滤后的数量（不受 `master_only` 影响）；`total` 是应用 `master_only` 后、用于分页的总数；`n_excluded = matched_total - n_creatable`。
- `items` 每项含 `code / name / industry / industry_code / exchange / exchange_label / board / board_label / sector / listed_state / listed_date / rows / start_date / end_date / latest_date / latest_close / latest_volume / latest_amount / latest_ifsuspend / creatable`。`industry` 是申万一级行业名称（筛选与下拉框都用它），`industry_code` 是 `FirstIndustryCode`。
- 排除的股票不在 `items` 里，只通过 `excluded_examples`（前 10 个）和 `n_excluded` 告知。

**`GET /api/universe/codes`**：参数与 `/api/universe/stocks` 相同（不含 `limit/offset`），默认 `master_only=true`，只返回 `{codes, total, matched_total, n_creatable, master_ready, as_of, cached, queried_at}`。供预览表格跨页「全选 / 反选」，响应只有代码，5k 只约几十 KB。

**预览勾选（React）**：筛选条件变化后默认全选当前筛选下全部可建池代码；checkbox 支持单行勾选、表头全选本页、表头半选（本页部分勾选）、跨页保留；工具栏「全选 / 反选 / 清空」作用于全部可建池代码（跨页），并显示「已选 N / 可建池 M」。非本地缓存股票（`creatable=false`）的 checkbox 禁用，不能提交。

**`POST /api/pools`**（202）：

```json
{
  "name": "bank_pool", "selection_start": "2024-01-01", "selection_end": "2024-06-30",
  "industries": ["银行"], "exchanges": [], "boards": [], "sectors": [], "listed_states": [],
  "q": "", "min_listed_days": 250, "top_n": 30, "min_coverage": 0.9,
  "exclude_suspended": true, "overwrite": false,
  "selected_codes": ["600036", "601398"]
}
```

`selected_codes` 省略 = 使用筛选结果中的全部可建池股票；传入列表 = 只从勾选的代码建池（仍需通过当前筛选且存在于本地主缓存）；显式空列表 = 422，避免静默退化成全选。传入但不在当前筛选/本地缓存的代码会被忽略并写入 `warnings`；全部无效则 422。`provenance` 增加 `selection_mode`（`all` / `manual`）与 `selected_total`。

返回 `{job_id, status:"queued", operation:"create_pool", warnings:[...], request_summary:{...}}`，不回传全部代码。服务端行为：

1. 校验池名（`[A-Za-z0-9_.\-一-鿿]+`、≤64 字符，防路径穿越）、日期、TopN、覆盖率；
2. 本地主缓存未就绪 → 503；筛选窗口与缓存区间无交集 → 422；
3. 按公司库筛选，再与 `data_cache/master/stocks/*.parquet` 求交集；空匹配 / 全部不可建池 → 422 + 中文原因；
4. 以显式 `codes` 提交 `create_pool` 任务（`strict_top_n=False`：候选不足 TopN 时按实际数量建池）；`provenance` 写入 manifest 但不参与 pool_id 哈希；
5. `api/job_runner.py` 用子进程运行 `custom_bt.cli run-platform-job`，日志写 `outputs/jobs/<job_id>/runner.log`。

**`GET /api/jobs/{job_id}`**：读 `status.json`，返回 `job_id / operation / status / message / updated_at / result / progress`；不存在或路径穿越 → 404。

口径与边界：

- **行业只做单级**（`dim.stock_main_info_fd.FirstIndustryName`，即申万一级行业；`FirstIndustryCode` 留作追溯）。注意 `Industry` 列是细分行业编码（实测 337 个取值），不是单级行业；四级行业表 `stock_industry_fd` 不在本轮范围。
- **市场/板块由代码前缀推导**（沪/深/北 + 主板/创业板/科创板/北交所），不依赖 `market_code`（本地实测该列是数据商标识 `新华财经`）。`ListedSector / ListedState` 只作为「库内原始编码」高级筛选原样暴露，不猜业务含义。
- **停牌口径**：候选预览只展示 `latest_ifsuspend`，不按它过滤；建池时的停牌过滤仍由 `create_pool` 在整段筛选窗口逐行处理，避免两处口径冲突。
- **缓存**：候选使用 `stock_rows` 快照（`QL_CH_UNIVERSE_TTL`，默认 **300s**），因此部署里 `QL_CH_CACHE_TTL=0` 时筛选预览也不会每次重打 3.5s 全市场聚合；`dim_profiles` 用 `QL_CH_SCHEMA_TTL`。
- **池 ID 稳定性**：`provenance / strict_top_n` 只写 manifest，不进入 `manifest_base`，同一组选样参数/代码的 `pool_id` 与历史一致。

### 2.9 因子运行列表与批量回测（2026-10-25）

链路：

```
factor_runs/<run_id>/（factor_run.json + accepted_factors.jsonl）
  → GET /api/factor-runs、GET /api/factor-runs/{run_id}（React 选择运行与合格因子）
  → POST /api/factor-backtests（202 + job_id；可只回测勾选因子）
  → api/job_runner.py 子进程 → backtest_accepted_factors
  → outputs/saved_backtests/factor/<pool_id>/<run_id>/<backtest_id>/<factor_id>/
  → GET /api/factor-backtests/{backtest_id} 轮询后展示批次结果
```

**`GET /api/factor-runs?pool_id=<可选>`**：扫描 `factor_runs/`（API 默认工作区根目录下，`QL_FACTOR_RUNS_ROOT` 可覆盖），只返回含 `factor_run.json` 的目录，按 `created_at` 倒序。每项含 `run_id / pool_id / source_signature / created_at / accepted_count / attempts / target_reached / attempts_exhausted / factor_run_dir / has_accepted`。`accepted_count` 优先按 `accepted_factors.jsonl` 实际行数统计。

**`GET /api/factor-runs/{run_id}`**：在列表字段基础上返回 `manifest` 与 `accepted_factors`。每个因子的 `factor_id` 由 `factor_<序号>_<表达式 sha256 前 10 位>` 生成（`custom_bt.factor_backtest.factor_id`），预览与回测共用同一算法，因此前端勾选的 ID 可以直接提交。

**`POST /api/factor-backtests`**（202）：

```json
{
  "factor_run_id": "pool_a_20261025_ab12cd34",
  "factor_ids": ["factor_0001_1a2b3c4d5e"],
  "start_date": "2022-01-01", "end_date": "2025-12-31",
  "top_k": 50, "initial_cash": 100000000,
  "buy_cost": 0.0015, "sell_cost": 0.0015, "slippage": 0.0005,
  "min_cost": 5, "max_weight_per_stock": 0.02
}
```

- `factor_ids` 省略或不做限制 = 回测全部合格因子；传列表 = 只回测选中因子（显式空列表 → 422）。未知 ID、空 accepted 文件、数据签名与 pool/master 不一致 → 422；master 未就绪 → 503。
- 日期缺省用本地 master 的 `date_min/date_max`；区间与 master 无交集 → 422，部分超出 → 200 + `warnings`（实际按缓存可用区间计算）。
- `top_k` 1–1000；`initial_cash > 0`；`buy_cost / sell_cost / slippage ∈ [0, 0.1]`；`min_cost ≥ 0`；`max_weight_per_stock ∈ (0, 1]`。
- 服务端只把**白名单参数**写进任务 payload（master/pool/factor run/output 路径全部由服务端常量给出，客户端不能指定路径）；任务由 `create_platform_job(..., "backtest_factors", ...)` 创建并 `spawn_platform_job` 起子进程。
- 返回 `{job_id, backtest_id, status:"queued", operation:"backtest_factors", factor_run_id, pool_id, accepted_total, selected_total, warnings, request_summary}`；`backtest_id` 与 `job_id` 相同，是输出目录的版本后缀。

**执行与进度**：`platform_jobs` 在调用 `backtest_accepted_factors` 前注入 `backtest_id=job_dir.name` 和 `progress_callback`。每个因子处理完写一次 `status.json.progress`：

```json
{
  "stage": "running | finished", "pool_id": "...", "factor_run_id": "...",
  "backtest_id": "...", "accepted_count": 5, "selected_count": 3,
  "processed": 2, "completed": 1, "failed": 1, "current_factor_id": "factor_0002_..."
}
```

`GET /api/jobs/{job_id}` 返回该 `progress` 与 `result`；前端按 `processed / selected_count` 显示进度条，完成后自动刷新批次列表。进度回调抛错只记 warning，不中断回测。

**输出与 `run_key`**：

```text
outputs/saved_backtests/factor/<pool_id>/<run_id>/<backtest_id>/
  factor_backtest_summary.csv      # 每个成功因子一行，含 run_key
  factor_backtest_failures.csv     # 失败因子与错误
  factor_backtest_manifest.json    # 批次汇总（backtest_id / 计数 / 参数 / run_key_prefix）
  <factor_id>/manifest.json        # 单因子结果，run_key 指向该目录
```

单因子 `run_key = factor/<pool_id>/<run_id>/<backtest_id>/<factor_id>`；批次 `run_key_prefix` 是去掉最后一段的路径。未传 `backtest_id` 的 CLI 调用仍写旧扁平目录 `factor/<pool_id>/<run_id>/`，兼容历史结果。

**`GET /api/factor-backtests?factor_run_id=...&pool_id=<可选>`**：列出该运行下的批次（读各批次 `factor_backtest_manifest.json`，按 `created_at` 倒序），返回 `{total, batches}`。**`GET /api/factor-backtests/{backtest_id}?factor_run_id=...`**：返回 `{batch, rows, failures}`；`rows` 来自汇总 CSV，并补齐 `run_key`，前端「查看结果」用 `navigate("result", undefined, row.run_key)`。**`GET /api/factor-backtests/{backtest_id}/files/{file_name}`**：只允许下载 `factor_backtest_summary.csv` / `factor_backtest_failures.csv` / `factor_backtest_manifest.json`，路径按 `_safe_child` 校验。

MySQL：批次汇总额外写入 `factor_backtest_runs`（主键 `backtest_id`，含 job_id / factor_run_id / pool_id / 区间 / TopK / 初始资金 / accepted、selected、completed、failed / output_dir / run_key_prefix / config / manifest / created_at），`backtest_accepted_factors` 尽最大努力同步，失败只记 warning。

## 3. 仍是演示数据的部分

以下页面/表单数据来自 `src/mockData.ts`、`src/mockExtended.ts`，**未接真实数据**：

- 任务中心（建池/因子回测任务的 `GET /api/jobs/{job_id}` 已暴露并用于股票池页与因子回测页，任务中心页面本身仍渲染 mock）
- 用户管理、审计日志
- 因子生成 / 因子组合的**提交表单**（因子回测页已全部接真实数据，见 §2.9；因子生成页的展示部分仍部分使用 mock）

股票池创建表单**已不再是 mock**：候选来自公司库，提交走 `POST /api/pools` 并轮询任务状态（§2.8）。因子回测页也已完成真实接入：运行/因子来自 `factor_runs/`，提交走 `POST /api/factor-backtests`，轮询进度并读取批次结果（§2.9）。

后端作业机制已就绪：`platform_jobs.py` 支持 5 种操作（prepare_master / create_pool / generate_factors / backtest_factors / compose_factors），与 Streamlit 端共用 `outputs/jobs/` 目录。

## 4. 技术栈

### 后端（custom_backtester/api）

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 语言 | Python 3.12.3 | Windows 下必须用 `py -3`（`python` 是应用商店占位符，退出码 49） |
| Web 框架 | FastAPI 0.143.0 + uvicorn 0.54.0 | 纯 ASGI，无 ORM |
| 数据库访问 | **stdlib `urllib.request`**（`api/live_db.py`） | 直连 ClickHouse HTTP 接口，**零新增依赖**（不装 clickhouse-driver / requests） |
| 本地数据读取 | pandas 3.0.3 + pyarrow 25.0.1 | 沿用 custom_bt 的 per-stock parquet 读取路径 |
| 数据形态 | 实时库 + 本地文件 | 展示端点查 ClickHouse；pools / saved_backtests / jobs 读 `data_cache/` + `outputs/` |
| 跨域 | CORS 全开，GET + POST | 生产可改由反代承担 |

代码只有五个文件：`api/__init__.py`、`api/main.py`（全部端点）、`api/live_db.py`（ClickHouse 只读客户端 + TTL 缓存）、`api/job_runner.py`（起 `run-platform-job` 子进程）、`api/__main__.py`（`py -3 -m api` 启动入口）。

### 前端（原型/）

| 层 | 选型 |
| --- | --- |
| 框架 | React 19 + TypeScript 5.7（Figma Make 脚手架） |
| UI | Ant Design 5.29 + @ant-design/icons 6 |
| 图表 | ECharts 6.1（净值/回撤双轴、年度柱状，轴界按真实数据自适应） |
| 样式 | Tailwind CSS 4（@tailwindcss/vite） |
| 构建 | Vite 8.0.5；工具链 Node 22 / pnpm 10.34.3（`.mise.toml`） |
| 数据访问 | `src/api/client.ts`：手写类型化 fetch（`apiGet` / `apiPost` + `ApiError`）+ `useApiData`（loading/error/reload）+ `useJobPolling`（建池任务轮询），未引入状态管理库 |
| 加载/错误态 | 各页统一 `LoadGate` 组件（Skeleton / Alert+重试） |

### 连接方式

- `vite.config.ts` 中 `server.proxy` 与 `preview.proxy` 均配置 `/api → QL_API_TARGET || http://127.0.0.1:8000`，开发期免 CORS；生产部署时后端自带 CORS 或由反代转发。

## 5. 启动与验证

```bash
# 0) 一次性的凭据配置（二选一，均在公司网络下）
#    a. 环境变量（当次会话有效）
export QL_CH_PASSWORD=<密码>
#    b. 本地文件（长期，已 gitignore）：编辑 custom_backtester/configs/clickhouse.local.env
#       QL_CH_PASSWORD=<密码>

# 0.5) 可选：把算子库装成真包（不装也能跑 —— custom_bt/_quantops_boot.py 会自动把 ../quantops 加进 sys.path）
py -3 -m pip install -e ../quantops

# 1) 后端（custom_backtester 目录）
py -3 -m api                      # 默认 127.0.0.1:8000

# 2) 前端（原型 目录）
pnpm dev                          # 默认 0.0.0.0:8443

# 3) 验证
curl http://127.0.0.1:8000/api/health          # 直连后端（不依赖数据库）
curl http://127.0.0.1:8000/api/data/master     # 实时端点：需凭据 + 公司网络
curl http://127.0.0.1:8443/api/data/master     # 经 vite 代理
```

浏览器打开 http://localhost:8443 ：数据总览 / 数据字段 / 股票列表（均实时查库）/ 操作符 / 因子股票池（实时筛选预览 + 建池 + 详情抽屉）/ 回测结果（切换「真实结果」）应为真实数据。

未配凭据时，依赖公司库的端点（数据总览 / 字段 / 股票列表 / 候选 options / 候选预览 / `POST /api/pools`）返回 503 + 中文原因（页面上直接显示），操作符 / 已有股票池列表 / 回测结果不受影响。

### 5.1 后端日志落盘（`outputs/logs/`，2026-10-15 起）

`py -3 -m api` 启动时除了照旧往控制台打日志，还会**同时落盘**（`api/logging_setup.py`）：

| 文件 | 内容 |
| --- | --- |
| `outputs/logs/api_<日期>.log` | 启动信息、uvicorn 报错、应用自己的 `logging.getLogger(...)`（制表符分隔：时间 / 级别 / logger 名 / 消息） |
| `outputs/logs/api_access_<日期>.log` | 每个 HTTP 请求一行（时间 / 客户端地址 / 请求行 / 状态码），与上面的错误日志分开 |

```bash
QL_API_LOG=0 py -3 -m api                    # 关掉落盘，回到「只在控制台看」的行为
QL_API_LOG_DIR=D:\logs py -3 -m api          # 换目录（默认 custom_backtester/outputs/logs）
tail -f outputs/logs/api_access_$(date +%F).log   # 想看实时请求流
```

- 文件名带**启动日期**，跨零点不换名、重启才换；单文件 10MB 滚动，最多留 3 个 `.1/.2/.3` 备份（按大小滚动 —— Windows 上 `TimedRotatingFileHandler` 改名会 PermissionError）。
- 文件一律 UTF-8（`encoding="utf-8"`），不受 Windows 控制台代码页影响；控制台那两行启动信息故意写成纯 ASCII，免得在 `chcp 936` 的终端里显示成乱码。
- `outputs/` 已被根 `.gitignore` 忽略，日志不会进版本库。

### 5.2 MySQL 集中存储（2026-10-25 起）

股票池以 MySQL 为主存储：列表/详情优先读 `pools` / `pool_codes`，未配置或连接失败时回退本地 `data_cache/pools`。因子运行与回测结果仍以本地文件为主，MySQL 只做集中存档。写入是**尽力而为**：失败只记 warning，不影响建池与回测。

配置优先级：`QL_MYSQL_*` 环境变量 > `configs/mysql.local.env`（已被根 `.gitignore` 的 `**/*.local.env` 忽略）。模板见 `configs/mysql.env.example`；驱动为 `PyMySQL`（已加入 `requirements.txt`）。

自动同步点：

| 触发 | 写入表 |
| --- | --- |
| `create_pool` 写完 `manifest.json` | `pools`、`pool_codes`、`pool_candidates`、`pool_stats` |
| `run_factor_generation` 写完 `factor_run.json` | `factor_runs`、`factors` |
| `backtest_accepted_factors` 写完批次目录 | `factor_backtest_runs`（批次汇总）+ 每个因子结果的 `backtests` 及子表 |
| `save_result` 写完回测目录 | `backtests`、`backtest_components`、`backtest_daily`、`backtest_annual`、`backtest_trades`、`backtest_positions` |

全量补录与自检：

```powershell
py -3 -m custom_bt.mysql_store schema   # CREATE TABLE IF NOT EXISTS
py -3 -m custom_bt.mysql_store check    # 版本 + 各表行数
py -3 -m custom_bt.cli mysql-sync       # 本地 pools / factor_runs / saved_backtests 全量 upsert
```

从 v1（`backtests.run_name` 主键）升级时，`schema` 会自动重建回测表并提示执行一次 `mysql-sync`；本地结果文件不受影响，补录后回测数据完整回来。v3（2026-10-25）只新增 `factor_backtest_runs`，`schema` 幂等补建，不需要重建旧表；`sync_all` 会额外扫描 `outputs/saved_backtests/**/factor_backtest_manifest.json`。

约定：

- 同一份结果重复同步是幂等的（父表 upsert，子表先删后插）。
- `backtests` 主键是 `run_key`（结果相对路径，如 `factor/<pool_id>/<run_id>/<backtest_id>/<factor_id>`），`run_name` 只做展示和索引；不同股票池/因子运行下同名的 `factor_0001_<hash>` 不会互相覆盖。
- `factor_backtest_runs` 主键是 `backtest_id`（平台任务 job_id），保存批次级计数与参数，单因子明细仍在 `backtests` 子表；`run_key_prefix` 可用于拼出批次内所有结果路径。
- `pool_candidates` 存的是建池时的候选代码（manifest 的 `requested_codes`），`pool_stats` 存 `selected_stats`；公司库筛选条件与来源在 `pools.provenance`。
- NaN/Inf 统一转 NULL，避免 MySQL JSON 拒绝非标准 JSON。
- 密码只存在于环境变量或 gitignored 的 `configs/mysql.local.env`，不会写入日志、manifest、API 响应或本文档。

## 6. 下一步（写操作续）

- ~~`POST /api/pools`~~ 已完成（2026-10-20，§2.8）：复用 `create_platform_job` + `api/job_runner.py`，与 Streamlit 共用 `outputs/jobs/`。
- ~~`POST /api/factor-backtests`~~ 已完成（2026-10-25，§2.9）：运行列表、批次进度、版本化输出、批次查询与结果跳转均已接通。
- 待接：`POST /api/backtest`（手工表达式）、`POST /api/factor-generations`、`POST /api/factor-compositions`，同样复用 `create_platform_job` / `run_platform_job`。
- 任务中心改读 `outputs/jobs/*/status.json` 状态机（queued → running → finished/failed）；目前股票池页与因子回测页分别轮询各自提交的任务。
- 用户 / 审计页面保持演示数据（无真实后端）

## 7. 已知坑（均已处理）

| 问题 | 处理 |
| --- | --- |
| `summary.json` 含 `NaN`（annual_return、calmar） | API 层 `_sanitize` 递归把非有限浮点转 `null`；Starlette `allow_nan=False` 与浏览器 `JSON.parse` 都不接受 NaN |
| pandas `itertuples()` 重命名关键字列 `return`（annual_metrics.csv） | 该代码路径改用 `to_dict("records")` + 字典取值 |
| 路径遍历（pool_id / run_name / file_name） | 白名单正则 + 子路径校验，逃逸一律 404；文件下载仅限清单内文件 |
| Windows `python` 命令不可用（退出码 49） | 全链路统一 `py -3`；README 与页面错误提示均已注明 |
| 真实净值远低于演示数据的 0.9 轴下界 | ECharts y 轴 min 按数据自适应 |
| ClickHouse `JSONEachRow` 把大整数输出成字符串、Decimal 走浮点会丢精度 | 所有数值列 SQL 里显式 `toString(...)` 取回，Python 侧用 `Decimal` 转 `int` / `float` |
| `SELECT toString(position) AS position … ORDER BY position` 被解析成对**字符串别名**排序（1, 10, 11, …, 2, 20） | 列序 SQL 不返回 `position`，只用它做 `ORDER BY`；已验证返回顺序与库内 `system.columns` 一致 |
| 用记事本创建 env 文件会带 UTF-8 BOM，`QL_CH_PASSWORD` 读成 `﻿QL_CH_PASSWORD` | env 文件按 `encoding="utf-8-sig"` 读取（单测有 BOM 回归用例） |
| 公司网/本机存在系统代理变量时，urllib 会把内网请求发给代理（连不上或超时） | 查询 opener 用 `build_opener(ProxyHandler({}))` 显式禁代理 |
| 全市场逐股聚合冷查询 3.5s，且 React StrictMode 开发态每页发 2 次请求 | 60s/300s TTL 缓存 + key 级 single-flight（并发只打一次库）+ 启动后台预热 |
| 库端错误正文可能回显连接串（含密码） | `_redact` 兜底把密码替换成 `***` 后才写日志 / 响应；单测断言错误消息不含密码 |
| 访问日志用普通 `Formatter` + `%(client_addr)s` 会整行丢弃（文件 0 字节，stderr 刷 `--- Logging error ---`） | uvicorn 打访问日志用的是**位置参数**，`client_addr / request_line / status_code` 由 `uvicorn.logging.AccessFormatter` 解析后临时塞进 record，因此文件 formatter 必须配 `"()": "uvicorn.logging.AccessFormatter"` + `use_colors: False`；单测按 uvicorn 的原始调用形状（位置参数）回归 |
| 关掉落盘时给 `uvicorn.Config(log_config=None)` → 控制台**一个字都没有**（启动横幅、访问日志全没） | `None` 不是「用默认配置」而是让 uvicorn 跳过 `configure_logging()`；关掉落盘时返回 `uvicorn.config.LOGGING_CONFIG` 的拷贝，单测断言 `is not None` |
| 实时口径 ≠ 缓存口径，页面上会出现"两个真相" | 实时为全历史（含退市）：行数 599.0 万 → **1736.9 万**、股票数 5432 → **5589**、最新日期 2026-06-16 → **2026-10-09**；总览页标注本地缓存窗口用于回测口径对照，字段页标注"面板可用/仅数据库" |
| 360 只股票在 `dim.stock_main_info_fd` 里没有简称（多为退市） | 名称返回 `null`，页面显示 `—`；搜索仍支持按代码 |
| `dim.stock_main_info_fd.Industry` 是**细分行业编码**（`DESCRIBE` 后实测 337 个取值，如 `60103483`），不是单级行业；直接用会把行业下拉框显示成数字编码 | 单级行业改取 `FirstIndustryName`（申万一级，实测 31 类，如「银行」），`FirstIndustryCode` 一并取回留作追溯；`Industry` 列不再使用 |
| `dim.stock_main_info_fd` 的列名与类型需在公司网核对；`Industry / ListedSector / ListedState / ListedDate` 早期只在文档中确认 | 2026-10-21 已用 `DESCRIBE` 核对（名称、类型与注释均存在）；SQL 仍对数值/日期列统一 `toString(...)` 兜底，列名若再变只改 `SQL_DIM_PROFILES` 与对应测试 |
| 本地缓存的 `market_code` 实测是数据商标识 `新华财经`，`ListedSector/ListedState` 是 `'1.0'/'6.0'/'8.0'` 这类原始编码 | 市场/板块改由代码前缀推导（`exchange_for_code / board_for_code`）；原始 `sector/listed_state` 仅作为「库内原始值」高级筛选原样暴露，不猜中文含义 |
| 公司库有、`data_cache/master` 没有的股票无法回测 | 建池前与本地缓存取交集，自动排除并在预览/提交响应/manifest provenance 里给出数量与示例代码 |
| 候选不足 TopN 时 `create_pool` 默认会抛 `only N stocks…` | API 建池传 `strict_top_n=False`，TopN 只作上限；manifest 仍记录请求的 `top_n` 与实际股票数 |
| 池名最终进目录名，存在路径穿越风险 | 池名白名单 `[A-Za-z0-9_.\-一-鿿]+` 且 ≤64 字符；job_id 走 `_safe_child`，非法一律 404/422 |
| `provenance` 若参与 pool_id 哈希，会让同一组选样参数因来源时间不同而生成新池 | `provenance / strict_top_n` 只写 manifest，不进入 `manifest_base`；单测锁定 pool_id 不变 |
| 候选预览每改一次筛选都重跑 3.5s 全市场聚合（部署里 `QL_CH_CACHE_TTL=0`） | 候选快照单独用 `QL_CH_UNIVERSE_TTL`（默认 300s）；前端筛选再做 300ms 防抖 |
| 翻页后只保留当前页勾选，跨页建池会漏股票 | 表格 `preserveSelectedRowKeys`；另用 `GET /api/universe/codes` 取当前筛选下全部可建池代码，供「全选 / 反选」跨页使用 |
| 手动勾选为空时若静默当成「全部候选」，会误建全市场股票池 | `selected_codes=[]` 显式返回 422；前端清空后禁用建池按钮，并提示可点「全选」 |
| 同一因子运行用不同参数重复回测会覆盖上一次结果 | 平台任务把 job_id 注入 `backtest_id`，输出目录与 `run_key` 都带批次版本；CLI 不传时保留旧扁平目录 |
| 嵌套结果目录无法用 `run_name` 定位，旧 `/api/results/{run_name}` 会 404 | `list_runs` 为无 `run_key` 的 manifest 按相对路径补全；新增 `/api/results/detail?run_key=` 与 `/api/results/file`，`_safe_relative` 拒绝绝对路径/`..`/空段 |
| 静态 `/api/results/detail`、`/api/results/file` 被 `/api/results/{run_name}` 吞掉 | 静态路由声明在动态路由之前（FastAPI 按注册顺序匹配） |
| 因子组合只认扁平回测目录，版本化后找不到汇总 | `_find_factor_backtest_summary` 先找 `factor/<pool>/<run>/<backtest_id>/` 下最新批次，再回退旧扁平路径 |
| 因子运行根目录口径不一致（API / mysql-sync / CLI 配置） | 统一解析到工作区根目录 `factor_runs/`：API 默认 `WORKSPACE_ROOT/factor_runs`（`QL_FACTOR_RUNS_ROOT` 可覆盖），`mysql_store.sync_all` 默认 `PROJECT_ROOT.parent/factor_runs`，`configs/factor_generation.yaml` 已改为 `../../factor_runs` |
| 前端切运行/批次时 `useApiData` 仍短暂保留上一条数据 | 渲染前校验 `runDetail.run_id === runId`、`batch.factor_run_id === runId`，不匹配按加载中处理 |
| 批次进度在任务 `finished` 时丢失 | `update_job_status` 只在 queued/running 清空 progress；finished/failed 保留最后一次进度与 result |

## 8. 如何验证「前端数据 = 数据库数据」

数据总览 / 数据字段 / 股票列表的链路缩短为：

```
ClickHouse（实时）→ api/live_db.py（SQL 写死，60s/300s TTL 缓存）→ FastAPI → vite 代理 → 前端
```

**前端不直连数据库**，中间只有一层按 key 的 TTL 缓存；验证 = 同一时刻对拍"直连库的 SQL 结果"与"页面数字"。

**Step 1 前端 ↔ API（浏览器）**
DevTools → Network 过滤 `/api/`，刷新页面看真实请求（`data/master`、`data/fields`、`data/stocks`）；Console 执行 `await fetch('/api/data/master').then(r => r.json())` 对照页面数字，响应里的 `cached` / `queried_at` 说明数据是本次查询还是 60s 内缓存。

**Step 2 API ↔ ClickHouse 实时库（同一时刻对拍）**

```bash
cd custom_backtester

# a) 直连库：单只股票的最新一条 + 聚合口径（绕过 API，独立一条 SQL）
curl -s -u <用户名>:<密码> "http://<公司ClickHouse地址>:8123/?max_memory_usage=8000000000" --data-binary "
SELECT toString(count()) AS rows, min(timestamps) AS start_date, max(timestamps) AS end_date,
       toString(argMax(close,  timestamps)) AS latest_close,
       toString(argMax(vol,    timestamps)) AS latest_volume,
       toString(argMax(amount, timestamps)) AS latest_amount
FROM dws.ll_stock_daily_sharing WHERE category='stock' AND code='000001' FORMAT Vertical"

# b) 从 API 读同一只
curl -s http://127.0.0.1:8000/api/data/stocks | py -3 -c "import json,sys; it=next(x for x in json.load(sys.stdin)['items'] if x['code']=='000001'); print(it)"

# c) 总览口径
curl -s -u <用户名>:<密码> "http://<公司ClickHouse地址>:8123/" --data-binary "
SELECT toString(count()), toString(uniqExact(code)), min(timestamps), max(timestamps)
FROM dws.ll_stock_daily_sharing WHERE category='stock' FORMAT Vertical"
```

2026-10-10 实测一致（a = b = 页面）：
- `000001` 平安银行：**8824 行 / 1991-04-03 ~ 2026-10-09 / 最新收 11.59 / 量 107,810,561 / 额 1,259,717,108.28**
- 全表：**17,368,843 行 / 5,589 只 / 1990-12-19 ~ 2026-10-09**（与页面"数据总览"四张卡片逐字相同）

注意对拍的是**数值**：JSON 里的 `latest_close` 是数字，会丢掉金额的小数尾零（`1263.00` → `1263.0`、`4453223189.00` → `4453223189.0`），页面用 `toFixed(2)` 格式化显示——这是表示差异不是数据差异，按数值比较即可。

**Step 3 字段页对拍（表结构）**
页面上「字段数」应等于：`SELECT count() FROM system.columns WHERE database='dws' AND table='ll_stock_daily_sharing'` **减 2**（`code` / `timestamps` 是行标识，不算字段）**再加 4**（dim 表的 `ListedDate` / `ListedSector` / `ListedState` / `ChiNameAbbr`）。实测 66 + 4 = **70**。名称与顺序应与 `DESCRIBE TABLE` 一致（`ORDER BY position` 的坑见 §7）。

**Step 4 断源证伪（区分实时页面与 mock / 缓存）**
三种做法任选：清空 `QL_CH_PASSWORD` 重启、把 `QL_CH_HOST` 指向不可达地址、或在公司网络外访问。此时数据总览 / 数据字段 / 股票列表 / 候选 options / 候选预览 / `POST /api/pools` 应显示 **503 + 中文原因**（连不上/未配置），而**操作符 / 已有股票池列表 / 回测结果仍正常**——这正好证明前几类页面走的是实时库、后几类读本地文件。任务中心 / 用户 / 审计仍渲染（本地 mock）。

**Step 5 回测口径对拍（缓存 ↔ 数据库，需公司网络与密码）**
股票池 / 因子 / 回测用的仍是本地快照，与实时库对拍可以确认缓存没有失真：

```bash
curl -s -u <用户名>:<密码> "http://<公司ClickHouse地址>:8123/?max_memory_usage=1000000000" \
  --data-binary "SELECT code, timestamps, close, vol, amount FROM dws.ll_stock_daily_sharing WHERE category='stock' AND code='000001' AND timestamps='2026-06-16' FORMAT Vertical"
```

应返回 `10.94 / 94,270,804 / 1,034,554,249.38`，与 `data_cache/master/stocks/000001.parquet` 末行一致（字段对应：缓存 `volume` ← 库 `vol`）。若不一致，先 `DESCRIBE TABLE` 核对列名与复权口径。命令详情见 `docs/公司数据库取数指南.md`。

**Step 6 股票池候选对拍（2026-10-20 起，需公司网络与密码）**

```bash
# a) 直连库：单级行业分布与缺失数（用 FirstIndustryName，不是 Industry 细分编码）
curl -s -u <用户名>:<密码> "http://<公司ClickHouse地址>:8123/" --data-binary "
SELECT FirstIndustryName, count() AS n FROM dim.stock_main_info_fd
WHERE FirstIndustryName != '' GROUP BY FirstIndustryName ORDER BY n DESC FORMAT JSONEachRow"

# b) API 的同一份分布
curl -s http://127.0.0.1:8000/api/universe/options

# c) 行业筛选预览（看 matched_total / n_creatable / excluded_examples）
curl -s "http://127.0.0.1:8000/api/universe/stocks?industries=%E9%93%B6%E8%A1%8C&master_only=true&limit=5"

# c2) 当前筛选下全部可建池代码（跨页全选/反选）
curl -s "http://127.0.0.1:8000/api/universe/codes?industries=%E9%93%B6%E8%A1%8C&master_only=true"

# d) 建池后轮询任务，再核对 manifest 与 codes.txt
curl -s -X POST http://127.0.0.1:8000/api/pools -H "Content-Type: application/json" \
  -d '{"name":"bank_pool","selection_start":"2024-01-01","selection_end":"2024-06-30","industries":["银行"],"top_n":30,"min_coverage":0.9}'
curl -s http://127.0.0.1:8000/api/jobs/<job_id>
py -3 -c "import json; m=json.load(open(r'data_cache/pools/<pool_id>/manifest.json',encoding='utf-8')); print(m['provenance'], m['strict_top_n'])"
```

- `options.industries` 的 `count` 之和 + `missing.industry` 应等于全库股票数；与 (a) 逐行业对拍（注意 API 的 `count` 是过滤前的全库分布）。
- `payload.codes`（manifest 的 `requested_codes`）必须全部存在于 `data_cache/master/stocks/*.parquet`；排除示例应能在库里查到但缓存里没有。
- 建池完成后用该 pool_id 跑一次现有回测链路，确认数据仍来自本地快照。
- 全流程检查 API 响应、`outputs/jobs/<job_id>/runner.log`、manifest 中**不含密码**；`QL_CH_PASSWORD` 只存在于环境变量或 gitignored 的 `configs/clickhouse.local.env`。

**Step 7 因子批量回测对拍（2026-10-25 起，本地文件，无需公司库）**

```bash
# 1) 看有哪些因子运行与合格因子（factor_id 与页面勾选一致）
curl -s http://127.0.0.1:8000/api/factor-runs
curl -s http://127.0.0.1:8000/api/factor-runs/<run_id>

# 2) 提交批次（只回测第一个因子；省略 factor_ids = 全部）
curl -s -X POST http://127.0.0.1:8000/api/factor-backtests -H "Content-Type: application/json" \
  -d '{"factor_run_id":"<run_id>","factor_ids":["factor_0001_<hash>"],"start_date":"2022-01-01","end_date":"2025-12-31","top_k":50}'

# 3) 轮询任务，观察 progress.processed / completed / failed
curl -s http://127.0.0.1:8000/api/jobs/<job_id>

# 4) 批次列表 / 详情 / 下载，再按 run_key 打开单因子结果
curl -s "http://127.0.0.1:8000/api/factor-backtests?factor_run_id=<run_id>"
curl -s "http://127.0.0.1:8000/api/factor-backtests/<job_id>?factor_run_id=<run_id>"
curl -s "http://127.0.0.1:8000/api/factor-backtests/<job_id>/files/factor_backtest_summary.csv?factor_run_id=<run_id>"
curl -s "http://127.0.0.1:8000/api/results/detail?run_key=factor/<pool_id>/<run_id>/<job_id>/<factor_id>"
```

核对：`factor_backtest_manifest.json` 的 `backtest_id` = job_id；汇总 CSV 每行 `run_key` 以 `run_key_prefix` 开头；输出目录只含本次选中的因子；MySQL `factor_backtest_runs` 有一行同 `backtest_id`（`py -3 -m custom_bt.mysql_store check`）。重复用不同参数提交同一运行 → 出现新批次目录，旧批次仍在。

**两点提醒**

- `source_signature` 是导入时对源 CSV 的 {绝对路径, 字节大小, mtime, 字段列表, 分隔符} 做 sha256（`custom_bt/data.py` 的 `_source_signature`），**不是内容哈希**：它只能证明缓存来自那次文件状态，内容正确性要靠 Step 5 的抽样复查。实时端点不返回该签名（`source_signature: null`）。
- 源 CSV 为 `F:\my_code_file\因子构建\数据\daily_with_maindata_v2.csv`（另一台机器，本机已不存在），因此「缓存 ↔ 源 CSV」的复算在本机做不了，只能走 Step 5 回库复查。
