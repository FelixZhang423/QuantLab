# QuantLab 项目结构与现状

> 更新日期：2026-10-25
> 对应提交：`6143fda`（React 前端 + FastAPI 后端）、`d25666e`（quantops 算子库）
> 仓库：<https://github.com/FelixZhang423/QuantLab>
> 范围：本文只描述本次上传的 `原型/`、`custom_backtester/`、`quantops/`。仓库顶层的 `single_factor/`、`research_pipeline/`、`docs/` 等目录属于早期或周边代码，不在本文范围内。

## 1. 仓库里有什么

| 路径 | 作用 | 上传状态 |
| --- | --- | --- |
| `原型/` | React + TypeScript 前端工作台（数据浏览、股票池、因子回测、结果详情等） | 已上传（`6143fda`） |
| `custom_backtester/` | FastAPI 接口层 + 回测/因子/股票池核心逻辑 + 测试 | 已上传（`6143fda`） |
| `quantops/` | 80 个因子算子 + 表达式引擎的独立库 | 已上传（`d25666e`） |
| `custom_backtester/data_cache/master/` | 本地主缓存（parquet 快照，初始提交已包含） | 已上传，约 810 MB / 5434 个文件 |
| `factor_runs/`（仓库根） | 因子运行结果（包括本地演示运行） | **未上传**（`.gitignore`） |
| `custom_backtester/outputs/` | 后台任务、回测结果、日志 | **未上传**（`.gitignore`） |
| `custom_backtester/data_cache/pools/`、`factor_runtime/` | 股票池、因子运行时缓存 | **未上传**（`.gitignore`） |

> 注意：`custom_backtester/data_cache/master/` 体积很大（约 810 MB），克隆仓库会比较慢。后续建议改用 Git LFS 或把数据放到外部存储，仓库里只保留下载/准备脚本。

## 2. 架构总览

```
浏览器（React 原型，默认 http://localhost:8443）
   │  fetch /api/*
   ▼
Vite dev proxy（/api → 127.0.0.1:8000）
   ▼
FastAPI（custom_backtester/api，默认 http://127.0.0.1:8000）
   ├─ 数据总览 / 数据字段 / 股票列表 / 股票池候选
   │     └─ 公司 ClickHouse（HTTP 只读，实时查询，300s 快照缓存）
   ├─ 操作符 / 股票池 / 因子运行 / 回测结果
   │     └─ 本地文件：data_cache/、factor_runs/、outputs/
   └─ POST /api/pools、POST /api/factor-backtests
         └─ create_platform_job → 子进程
              py -3 -m custom_bt.cli run-platform-job --job-dir <job_dir>
              状态写到 outputs/jobs/<job_id>/status.json

MySQL `QuantLab`：股票池 / 因子 / 回测的尽力而为镜像（API 不读 MySQL）
```

两条数据链要区分清楚：

- **实时链**：公司 ClickHouse 只读查询，用于数据浏览和股票池候选筛选；没有密码或不在公司网络时返回 503，其余页面不受影响。
- **本地链**：`data_cache/master` 是因子生成、建池、回测的唯一数据源；股票池候选会先与本地缓存取交集，本地没有的股票自动排除并提示。

## 3. 前端 `原型/`

### 3.1 技术栈

React 19、TypeScript 5.7、Ant Design 5、ECharts 6、Vite 8、Tailwind 4、pnpm。Node.js 需要 ≥ 22。

### 3.2 目录

```
原型/
├─ src/
│  ├─ App.tsx              # 登录、布局、侧边菜单、页面路由、结果详情
│  ├─ Charts.tsx           # ECharts 图表（净值/回撤、年度收益）
│  ├─ api/client.ts        # API 客户端、useApiData、useJobPolling、文件 URL
│  ├─ mockData.ts          # 任务/演示结果等 mock 数据
│  ├─ mockExtended.ts      # 字段/股票/池/因子/组合/用户/审计 mock
│  └─ pages/
│     ├─ DataPages.tsx     # 数据总览 / 数据字段 / 股票列表 / 操作符
│     ├─ ResearchPages.tsx # 股票池 / 因子生成 / 因子回测
│     ├─ CompositionPage.tsx
│     └─ SystemPages.tsx   # 用户与权限 / 审计日志
├─ vite.config.ts          # 端口 8443，/api 代理到 127.0.0.1:8000
└─ package.json
```

### 3.3 页面与数据来源

| 页面 | 数据来源 | 状态 |
| --- | --- | --- |
| 数据总览 / 数据字段 / 股票列表 | ClickHouse 实时 | 真实 |
| 操作符 | 本地 `custom_bt/docs.py` + `quantops` 元数据 | 真实 |
| 股票池（筛选预览、建池、列表、详情） | `api/universe/*`、`api/pools`、`api/jobs/*` | 真实 |
| 因子回测（运行列表、批次、提交、进度、结果文件） | `api/factor-runs`、`api/factor-backtests`、`api/jobs/*` | 真实 |
| 结果详情 | `api/results` 真实结果 + 本地演示任务切换 | 真实为主 |
| 因子生成 | `setTimeout` + `addTask` | **mock** |
| 手动回测 | `setTimeout` + mock 指标 | **mock** |
| 因子组合 | `setTimeout` + `mockExtended` | **mock** |
| 总览 Dashboard | mock 任务列表 | **mock**（部分结果数来自 API） |
| 任务中心 / 用户与权限 / 审计日志 | mock | **mock** |
| 登录 | 页面内“研究员登录”按钮 | **mock**（无鉴权） |

### 3.4 股票池筛选口径

- **行业**：公司库 `FirstIndustryName`（申万一级），多选。
- **市场**：沪市 / 深市 / 北交所 / 其他，按代码前缀推导。
- **板块**：沪市主板 / 深市主板 / 创业板 / 科创板 / 北交所 / 其他，按代码前缀推导；下拉选项带数量，例如“创业板（1415）”。
- **关键词**：代码或名称。
- **上市天数**：按 `as_of - ListedDate` 计算，缺上市日期时排除。
- **高级筛选**：`ListedSector` / `ListedState` 库内原始编码，含义以库为准。
- 预览支持服务端分页、全选 / 反选 / 部分勾选；提交建池时会把最终勾选的代码区间与筛选条件一起写入 manifest 的 `provenance`。

### 3.5 启动与构建

```powershell
cd D:\1\QuantLab\原型
pnpm install
pnpm dev        # http://localhost:8443
pnpm build      # 生产构建，产物在 dist/
```

可用环境变量：`PORT`（前端端口，默认 8443）、`QL_API_TARGET`（代理目标，默认 `http://127.0.0.1:8000`）。

## 4. 后端 `custom_backtester/`

### 4.1 技术栈与启动

Python 3.12、FastAPI、uvicorn、pandas 3、PyMySQL。**在 `custom_backtester` 目录下用 `py -3` 启动**：

```powershell
cd D:\1\QuantLab\custom_backtester
py -3 -m pip install -r requirements.txt
py -3 -m api
```

默认监听 `127.0.0.1:8000`，可用 `QL_API_HOST` / `QL_API_PORT` 覆盖。日志同时写到控制台和 `outputs/logs/api_<日期>.log`、`api_access_<日期>.log`；`QL_API_LOG=0` 可关闭落盘。

### 4.2 主要模块

| 路径 | 作用 |
| --- | --- |
| `api/main.py` | FastAPI 应用与全部路由；`_sanitize` 把 NaN/Infinity 转 null；路径穿越防护 |
| `api/live_db.py` | 公司 ClickHouse 只读 HTTP 客户端；SQL 走 `guard_readonly`；行业/市场/板块筛选；300s universe 快照缓存 |
| `api/job_runner.py` | 用子进程执行平台任务，日志写 `outputs/jobs/<job_id>/runner.log` |
| `api/logging_setup.py` | 控制台 + 文件日志配置 |
| `custom_bt/pools.py` | 建池、候选过滤、`strict_top_n`、provenance、MySQL 镜像 |
| `custom_bt/factor_generation.py` | 因子生成流程（PPO 生成 + 质量筛选） |
| `custom_bt/factor_backtest.py` | 已合格因子的批量回测、版本化输出、MySQL 镜像 |
| `custom_bt/results.py` | 本地回测结果扫描与详情 |
| `custom_bt/expressions.py` | 转发 `quantops` 的表达式求值；兼容旧接口 |
| `custom_bt/operator_registry.py` | 转发 22 个 canonical 定义；AlphaGen 类加载留在本仓库 |
| `custom_bt/docs.py` | `/api/operators` 的唯一生产者；**被测试锁住，不要修改** |
| `custom_bt/mysql_store.py` | MySQL `QuantLab` 镜像，schema v3，14 张表 |
| `custom_bt/platform_jobs.py` | 平台任务目录、`status.json`、进度 |
| `configs/` | YAML 配置 + `*.local.env`（本地凭据，已 gitignore）+ `*.env.example` |
| `tests/` | 后端单元/集成测试 |

### 4.3 主要接口

| 分组 | 接口 |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 本地数据 | `GET /api/data/master`、`GET /api/data/fields`、`GET /api/data/stocks` |
| 公司库候选 | `GET /api/universe/options`、`GET /api/universe/stocks`、`GET /api/universe/codes` |
| 操作符 | `GET /api/operators` |
| 股票池 | `GET /api/pools`、`GET /api/pools/{pool_id}`、`POST /api/pools`（202 + job_id） |
| 任务 | `GET /api/jobs/{job_id}` |
| 因子运行 | `GET /api/factor-runs`、`GET /api/factor-runs/{run_id}` |
| 因子回测 | `POST /api/factor-backtests`（202）、`GET /api/factor-backtests`、`GET /api/factor-backtests/{backtest_id}`、`GET /api/factor-backtests/{backtest_id}/files/{file_name}` |
| 回测结果 | `GET /api/results`、`GET /api/results/detail`、`GET /api/results/file`、`GET /api/results/{run_name}`、`GET /api/results/{run_name}/files/{file_name}` |

### 4.4 本地文件与后台任务

- 主缓存：`custom_backtester/data_cache/master/`（回测唯一数据源）。
- 股票池：`custom_backtester/data_cache/pools/<pool_id>/`。
- 因子运行：仓库根 `factor_runs/<run_id>/`（API 默认 `WORKSPACE_ROOT/factor_runs`，可用 `QL_FACTOR_RUNS_ROOT` 覆盖）。
- 回测结果：`outputs/saved_backtests/factor/<pool_id>/<run_id>/<backtest_id>/<factor_id>/`，`run_key` 即相对路径/MySQL 主键。
- 后台任务：`outputs/jobs/<job_id>/status.json`，前端 `useJobPolling` 每 1.5s 轮询。
- 因子生成配置 `configs/factor_generation.yaml` 的 `factor_runs_root` 必须是 `../../factor_runs`，与 API / `mysql_store.sync_all` 的口径一致。

### 4.5 MySQL 镜像

- 库：`QuantLab`，schema 版本 **3**，14 张表：`pools`、`pool_codes`、`pool_candidates`、`pool_stats`、`factor_runs`、`factors`、`factor_backtest_runs`、`backtests`、`backtest_components`、`backtest_daily`、`backtest_annual`、`backtest_trades`、`backtest_positions`、`ql_schema_meta`。
- 写入是**尽力而为**：未配置或连不上 MySQL 时返回 `False`，不阻塞主流程；API 不读 MySQL，页面仍以本地文件为准。
- 本地配置：复制 `configs/mysql.env.example` 为 `configs/mysql.local.env`（已 gitignore）后填写。常用命令：

```powershell
py -3 -m custom_bt.mysql_store schema   # 幂等建表
py -3 -m custom_bt.mysql_store check    # 连接自检 + 各表行数
py -3 -m custom_bt.cli mysql-sync       # 本地结果补录到 MySQL
```

## 5. 算子库 `quantops/`

### 5.1 定位

80 个 Alpha101 / BRAIN 风格算子 + 表达式引擎，只依赖 numpy / pandas，可独立于本项目使用。`custom_backtester/custom_bt/expressions.py` 只是转发，算子实现以 `quantops/` 为准。

### 5.2 结构

| 文件 | 作用 |
| --- | --- |
| `quantops/core.py` | 底层原语：按 code 滚动、按 date 横截面、分组运算、协方差/相关/EMA 等 |
| `quantops/operators.py` | 80 个算子的 `OPERATORS` 注册表 + `register_operator` |
| `quantops/registry.py` | 22 个 canonical 定义（arity、AlphaGen 名、是否参与生成、别名） |
| `quantops/expression.py` | AST 白名单沙箱，`evaluate()` |
| `quantops/panel.py` | 长表 ↔ `MultiIndex(date, code)` Series 互转 |
| `quantops/metadata.py` | 中文分类/说明/示例，`catalog()` 与 `/api/operators` 对齐 |
| `quantops/accessor.py` | pandas 访问器 `Series.qo` |
| `quantops/opset.py` | `OperatorSet` 类式入口（动态生成 80 个方法） |
| `quantops/__main__.py` | CLI：`list` / `describe` / `eval` |
| `quantops/tests/` | 表达式、公开 API、金标准、CLI、OperatorSet 测试 |

### 5.3 用法与验证

```python
import quantops as qo

close = qo.to_series(panel, "close")
qo.ts_mean(close, 20)
qo.evaluate("rank(ts_mean(close, 20))", panel)
```

```bash
cd D:\1\QuantLab\quantops
py -3 -m pytest -q          # 148 passed
py -3 -m quantops list
py -3 -m quantops describe ts_mean
```

**必须从 `quantops/` 目录运行**：仓库根目录下也有一个同名 `quantops/` 文件夹，Python 会把它解析成空的 namespace 包，报 `module 'quantops' has no attribute 'OPERATORS'`。回测器内部走 `_quantops_boot.py`，不受影响。

## 6. 目前已经实现的功能

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 公司库实时数据浏览 | ✅ | 数据总览、字段、股票列表；ClickHouse 只读 |
| 股票池候选筛选 | ✅ | 行业 / 市场 / 板块 / 关键词 / 上市天数 / 库内原始编码 |
| 候选预览与勾选 | ✅ | 服务端分页、全选 / 反选 / 部分勾选、本地可建池标记 |
| 真实建池 | ✅ | `POST /api/pools` → 后台任务 → 进度轮询 → manifest 带 provenance |
| 股票池列表/详情 | ✅ | 本地文件为主，MySQL 尽力镜像 |
| 操作符目录 | ✅ | `/api/operators`，与 `quantops` 元数据逐字段对齐 |
| 因子运行列表/详情 | ✅ | 扫描 `factor_runs/`，展示合格因子 |
| 批量因子回测 | ✅ | 真实运行、逐因子结果、进度轮询、批次版本化、MySQL 汇总 |
| 回测结果浏览/下载 | ✅ | `/api/results`，真实结果 + 演示任务切换 |
| quantops 80 算子 | ✅ | 四种调用方式；表达式 AST 沙箱 |
| 因子生成核心/CLI | ✅ | `custom_bt.factor_generation` + CLI；Web 提交页仍是 mock |
| 手动回测核心/Streamlit | ✅ | 原 Streamlit 工作台仍可运行；React 页仍是 mock |
| 因子组合核心/Streamlit | ✅ | 同上 |
| MySQL `QuantLab` 镜像 | ✅ | schema v3、14 表、尽力而为 |
| 登录 / 权限 / 任务中心 / 审计 | ❌ | 前端 mock，无真实鉴权 |
| 一键部署 / CI | ❌ | 目前是本地手动启动，无 GitHub Actions / Docker |

## 7. 待完善与已知问题

### P0（建议优先）

1. **因子生成 Web 页面仍是 mock**（`setTimeout` + `addTask`），没有接真实后端；PPO 依赖（`gymnasium`、`stable-baselines3`、`sb3-contrib`）也未安装。
2. **手动回测、因子组合、任务中心、用户/审计仍是 mock**，需要按 `/api/*` 的模式逐个接真实后端。
3. **没有真实登录与权限控制**；CORS 目前是 `allow_origins=["*"]`，只适合本地/可信网络，公开部署前必须收紧。

### P1（功能与工程质量）

4. **MySQL 镜像没有重试/补偿队列**：写失败只返回 `False`；需要时手动跑 `mysql-sync`。可考虑后台重试或定时同步。
5. **演示因子运行不是 PPO 输出**：`factor_runs/demo_liquid_300_20261025/` 是联调用的真实本地评估结果（`demo: true`、`quality_mode: demo-relaxed`），9 个因子，**不是投资结论**；它已在 `.gitignore` 中，不会上传，也不在 MySQL `factor_runs` 表里（批次有镜像）。是否保留/删除需要明确。
6. **数据体积**：`data_cache/master` 约 810 MB 已进 Git；`factor_runs/`、`outputs/` 会持续增长。建议 Git LFS、外部对象存储或定期清理。
7. **没有 CI**。建议加 GitHub Actions：`quantops` 跑 `pytest`，`custom_backtester` 跑现有测试，前端跑 `pnpm exec tsc --noEmit && pnpm build`。
8. **已知失败测试（pandas 3.0 兼容性）**：`custom_backtester/tests/test_streamlit_app.py::StreamlitAppTests::test_saved_runs_table_keeps_topk_arrow_compatible` 断言 `dtype == object`，pandas 3.0 下实际是 `str`。属于旧 Streamlit 页面的历史问题，不影响 FastAPI/React。
9. **文档/注释有少量过期**：
    - `custom_backtester/api/main.py` 中 `FACTOR_RUNS_ROOT` 的注释仍写 `../factor_runs`，实际配置是 `../../factor_runs`；
    - `quantops/quantops/metadata.py` 的 docstring 提到 `quantops/tests/test_metadata.py`，实际一致性测试在 `custom_backtester/tests/test_quantops_metadata_parity.py`；
    - `原型/README.md` 仍说“因子回测的提交表单是 mock”，实际已接真实后端。
10. **`custom_bt/docs.py` 不要改**：`tests/test_docs.py` 锁住其内容；算子中文元数据以它为准，`quantops/metadata.py` 是副本，由 parity 测试保证一致。

### P2（后续可做）

13. Docker / docker-compose 一键起后端 + 前端 + MySQL。
14. `quantops` 发布到私有 PyPI 或继续用仓库内路径；接入 CI 后自动跑金标准测试。
15. 前端补组件测试/端到端测试（Playwright 已在本地用于手工验证）。
16. 日志轮转、监控、任务失败告警。
17. 回测结果的权限隔离与多用户隔离。

## 8. 运行与验证

### 8.1 依赖

- Python 3.12（必须用 `py -3`，不要用 `python`）
- Node.js ≥ 22、pnpm ≥ 10
- 公司网络 + ClickHouse 凭据（实时数据相关页面）
- MySQL（可选，镜像功能）

### 8.2 ClickHouse 凭据

二选一：

- 环境变量：`QL_CH_PASSWORD`（必需），可选 `QL_CH_HOST` / `QL_CH_PORT` / `QL_CH_USER`；
- 或复制 `custom_backtester/configs/clickhouse.env.example` 为 `clickhouse.local.env`（已 gitignore）后填写真实值。

**不要把密码写进任何提交文件、文档、响应或日志。** 没有密码或不在公司网络时，实时端点返回 503 中文原因，其余页面正常。

### 8.3 验证命令

```powershell
# 算子库
cd D:\1\QuantLab\quantops
py -3 -m pytest -q
# 148 passed

# 后端：实时库 + API 路由
cd D:\1\QuantLab\custom_backtester
py -3 -m pytest -q tests/test_live_db.py tests/test_api_routes.py
# 48 passed

# 后端：quantops 集成
cd D:\1\QuantLab\custom_backtester
py -3 -m pytest -q tests/test_quantops_boot.py tests/test_quantops_metadata_parity.py
# 9 passed

# 前端
cd D:\1\QuantLab\原型
pnpm exec tsc --noEmit
pnpm build
```

## 9. 安全与上传注意事项

1. **绝不提交密码**：`*.local.env` 只留在本地；仓库只上传 `configs/clickhouse.env.example`、`configs/mysql.env.example` 两个模板，统一用 `<密码>`、`<公司ClickHouse地址>`、`<用户名>` 占位。
2. **公司库只读**：只允许 `SELECT` / `DESCRIBE` 等只读语句，`api/live_db.py` 的 `guard_readonly` 会拦截写 SQL。
3. **公开仓库**：本仓库是公开的。代码/文档里的内网地址和用户名已经脱敏；新增文档时不要把它们写回去。
4. **`custom_bt/docs.py` 不要修改**：被测试锁死，改它会导致 `/api/operators` 和元数据测试失败。
5. **Windows 编码**：用 PowerShell 管道处理中文时设置 `$env:PYTHONIOENCODING="utf-8"`，避免 curl 输出被按本地代码页解码成乱码。
6. **端口冲突**：后端 8000、前端 8443；被占用时用 `QL_API_PORT` / `PORT` 改端口。
7. **quantops 目录歧义**：手工 `import quantops` / `py -3 -m quantops` 时先 `cd quantops`，不要在仓库根执行。
8. **因子运行根目录**：`factor_runs_root` 必须指向 `WORKSPACE_ROOT/factor_runs`（配置里是 `../../factor_runs`），否则 API、CLI、MySQL 三处会读不到同一批结果。
