# QuantLab 前端原型（React）

企业级 Web 工作台原型：React 19 + Vite + TypeScript + Ant Design 5 + ECharts 6。

数据来源分两类：

- **真实数据（走 `custom_backtester` 的 FastAPI，`/api/*` 经 vite 代理）**：数据总览 / 数据字段 / 股票列表（ClickHouse 实时）、操作符、股票池（候选筛选预览 + 真实建池 + 列表/详情）、回测结果；
- **仍是 mock**：任务中心、用户与权限、审计日志，以及因子生成/回测/组合的提交表单。

后端启动方式与各端点的真实数据来源见 `custom_backtester/docs/web_api.md`。

## 环境要求

- Node.js ≥ 22（本机已验证 v22.16）
- pnpm ≥ 10（或 npm，二选一）

## 启动（日常开发）

PowerShell：

```powershell
cd D:\1\QuantLab\原型

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
├── mockData.ts          # 任务/结果数据 + 状态模拟调度
├── mockExtended.ts      # 字段/股票/池/因子/组合/用户/审计数据
└── pages/
    ├── DataPages.tsx        # 数据总览 / 数据字段 / 股票列表 / 操作符
    ├── ResearchPages.tsx    # 股票池 / 因子生成 / 因子回测
    ├── CompositionPage.tsx  # 因子组合
    └── SystemPages.tsx      # 用户与权限 / 审计日志
```

## 相关服务

| 服务 | 目录 | 启动命令 | 地址 |
|---|---|---|---|
| 本原型 | `D:\1\QuantLab\原型` | `pnpm dev` | http://localhost:8443 |
| FastAPI 数据接口 | `D:\1\QuantLab\custom_backtester` | `py -3 -m api`（见下方说明） | http://localhost:8000 |
| 原始 Streamlit 工作台 | `D:\1\QuantLab\custom_backtester` | `py app\run_streamlit.py` | http://localhost:8501 |

后端默认监听 `127.0.0.1:8000`，vite 把 `/api` 代理过去（`QL_API_TARGET` 可覆盖）。数据总览 / 数据字段 / 股票列表 / 股票池候选查公司 ClickHouse，需要在公司网络下并配置凭据（环境变量 `QL_CH_PASSWORD` 优先，其次 `custom_backtester/configs/clickhouse.local.env`，该文件已被 .gitignore 忽略）；已有股票池列表、池内数据与回测结果只读本地 `data_cache/`、`outputs/`，不需要数据库凭据。

股票池页的「创建股票池」已接真实后端：筛选条件 → 候选预览（支持跨页全选 / 反选 / 部分勾选，默认全选）→ `POST /api/pools`（部分勾选时只提交勾中的代码）→ 轮询 `GET /api/jobs/{job_id}` → 自动刷新列表。候选股票来自公司库，建池时与本地主缓存取交集；公司库有、缓存没有的股票会自动排除并提示。

> 说明：任务中心与用户/审计页面仍是 mock；接入真实平台时，把对应 `src/pages/*` 里的 mock 数据替换为 API 调用即可，任务推演控制器与"状态演示"切换器届时移除。
