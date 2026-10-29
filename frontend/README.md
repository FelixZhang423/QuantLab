# QuantLab 前端（React）

企业级 Web 工作台：React 19 + Vite + TypeScript + Ant Design 5 + ECharts 6。

数据来源分两类：

- **真实数据（走 `backend` 的 FastAPI，`/api/*` 经 vite 代理）**：数据总览 / 数据字段 / 股票列表、股票池（候选筛选预览 + 真实建池 + 列表/详情/删除）、手动回测（选池 + 表达式 + 后台任务 + 结果预览）、因子生成（运行与合格因子浏览 + 类别筛选 + 生成总结）、因子回测（类别筛选 + 批量提交 + 结果总结）、回测结果；股票池、因子面板与回测全部直接读公司 ClickHouse；
- **仍是 mock**：任务中心、用户与权限、审计日志、因子组合；因子生成的提交仍走 CLI。

后端启动方式与各端点的真实数据来源见 `backend/docs/web_api.md`。

## 环境要求

- Node.js ≥ 22（本机已验证 v22.16）
- pnpm ≥ 10（或 npm，二选一）

## 启动（日常开发）

PowerShell：

```powershell
cd frontend        # 从仓库根目录进入

# 首次或依赖变更后
pnpm install

# 启动开发服务器（默认端口 8443）
pnpm dev
```

浏览器打开 http://localhost:8443

**指定端口启动**（避免与其他服务冲突）：

```powershell
$env:PORT="8517"; pnpm dev
# 然后打开 http://localhost:8517
```

开发服务器支持热更新，改代码保存即生效。

## 构建验证

```powershell
pnpm build        # 生产构建，产物在 dist/
```

## 项目结构

```
src/
├── App.tsx              # 入口：登录 + 布局 + 侧边菜单 + 页面路由
├── Charts.tsx           # ECharts 图表（净值/回撤、年度收益）
├── factorInsights.ts    # 因子分类规则 + 生成/批次总结
├── mockData.ts          # 任务/结果数据 + 状态模拟调度
├── mockExtended.ts      # 字段/股票/池/因子/组合/用户/审计数据
├── components/
│   └── FactorCategoryChips.tsx  # 因子类别筛选 chips
└── pages/
    ├── DataPages.tsx        # 数据总览 / 数据字段 / 股票列表 / 操作符
    ├── PoolsPage.tsx        # 股票池（候选筛选 / 建池 / 列表 / 详情）
    ├── FactorGenerationPage.tsx  # 因子生成（运行 / 分类 / 总结）
    ├── FactorBacktestPage.tsx    # 因子回测（类别筛选 / 批量 / 结果总结）
    ├── ManualBacktestPage.tsx  # 手动回测（真实股票池 + 后台任务 + 结果预览）
    ├── CompositionPage.tsx  # 因子组合
    └── SystemPages.tsx      # 用户与权限 / 审计日志
```

## 相关服务

| 服务 | 目录 | 启动命令 | 地址 |
|---|---|---|---|
| 前端 | `frontend/` | `pnpm dev` | http://localhost:8443 |
| FastAPI 数据接口 | `backend/` | `py -3 -m api`（见下方说明） | http://localhost:8000 |
| Streamlit 工作台 | `backend/` | `py app\run_streamlit.py` | http://localhost:8501 |

后端默认监听 `127.0.0.1:8000`，vite 把 `/api` 代理过去（`QL_API_TARGET` 可覆盖）。**数据总览 / 数据字段 / 股票列表、股票池候选与建池、因子面板与回测全部直接读公司 ClickHouse**，需要在公司网络下并配置凭据（环境变量 `QL_CH_PASSWORD` 优先，其次 `backend/configs/clickhouse.local.env`，该文件已被 .gitignore 忽略）；股票池列表/详情优先读 MySQL，回退本地 `data_cache/pools/`，因子运行与回测结果读本地 `factor_runs/`、`outputs/`，这些页面不需要数据库凭据。

股票池页的「创建股票池」已接真实后端：筛选条件 → 候选预览（支持跨页全选 / 反选 / 部分勾选，默认全选）→ `POST /api/pools`（部分勾选时只提交勾中的代码）→ 轮询 `GET /api/jobs/{job_id}` → 自动刷新列表。候选、选样统计与回测面板都来自公司库，不再与本地 `data_cache/master` 取交集，本地缓存没有的股票同样可以建池。

手动回测页也已接真实后端：选择股票池（公司库池优先，旧本地池会提示走本地缓存）→ 填 Alpha 表达式 / 区间 / TopK 与交易参数 → `POST /api/manual-backtests` → 轮询 `GET /api/jobs/{job_id}`（loading_panel → evaluating → running → finished）→ 右侧直接用 `run_key` 拉取真实指标、净值、年度表与文件下载；「完整结果」跳到结果详情页。

结果详情页只读 `GET /api/results` 的真实结果：下拉按 `run_key` 切换、默认最新一条，兼容手动（`config.backtest` 嵌套）与因子（扁平 `config`）两种参数结构，展示数据源标签、真实指标/净值/年度与 manifest 白名单文件下载；研究备注仅存本机 `localStorage`，不再有 mock 任务或假下载。

因子生成页与回测页共享前端分类：后端没有类别字段，页面按表达式中的字段与算子把合格因子归为量价、波动、趋势、横截面、条件、算术、其他。生成页可点击类别筛选，并把类别带到回测页；回测完成后结果卡会给出成功数、年化/夏普/回撤中位数、最佳/最差因子与表现最好的类别。

> 说明：任务中心与用户/审计页面仍是 mock；接入真实平台时，把对应 `src/pages/*` 里的 mock 数据替换为 API 调用即可，任务推演控制器与"状态演示"切换器届时移除。
