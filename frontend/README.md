> 数据链路：数据预览与股票池筛选读取 ClickHouse；生成、回测和组合使用不可变 Parquet 快照。数据总览展示快照数量和最近时间，旧导入 mock 已删除。旧 local 池只可查看历史，新任务需在 ClickHouse 重新建池。

# QuantLab 前端（React）

企业级 Web 工作台：React 19 + Vite + TypeScript + Ant Design 5 + ECharts 6。

数据来源分两类：

- **真实数据（走 `backend` 的 FastAPI，`/api/*` 经 vite 代理）**：数据总览 / 数据字段 / 股票列表、股票池（候选筛选预览 + 真实建池 + 列表/详情/删除）、手动回测（选池 + 表达式 + 后台任务 + 结果预览）、因子回测、回测结果、因子组合（等权 / MSE + 多规模 + 最新选股）；股票池、因子面板与回测全部直接读公司 ClickHouse；
- **仍是 mock**：任务中心、用户与权限、审计日志。

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
├── main.tsx                 # React 入口
├── app/
│   ├── App.tsx              # 应用装配：登录态 + 布局 + 菜单 + 页面切换
│   └── navigation.ts        # Page / Role / PageNav / TaskAdder 类型
├── shared/
│   ├── api/base.ts          # fetch 基座、ApiError、useApiData / useJobPolling
│   └── domain/              # factorCategories / fieldCategories
├── api/client.ts            # 兼容 barrel（合并各 feature API）
├── components/              # Brand / Charts / LoadGate / FilterChips
├── features/                # 每个 feature 自带 index.ts / api.ts / mock.ts
│   ├── auth/                # 登录
│   ├── dashboard/           # 总览
│   ├── tasks/               # 任务中心
│   ├── data-browser/        # 数据总览 / 字段 / 股票 / 操作符
│   ├── pools/               # 股票池
│   ├── factor-generation/   # 因子生成
│   ├── factor-backtest/     # 因子回测
│   ├── manual-backtest/     # 手动回测
│   ├── results/             # 结果详情 / 批次结果 / 结果分析
│   ├── composition/         # 因子组合（等权 / MSE、多规模、最新选股）
│   └── system/              # 用户与审计（mock）
```

## 相关服务

| 服务 | 目录 | 启动命令 | 地址 |
|---|---|---|---|
| 前端 | `frontend/` | `pnpm dev` | http://localhost:8443 |
| FastAPI 数据接口 | `backend/` | `py -3 -m api`（见下方说明） | http://localhost:8000 |

后端默认监听 `127.0.0.1:8000`，vite 把 `/api` 代理过去（`QL_API_TARGET` 可覆盖）。**数据总览 / 数据字段 / 股票列表、股票池候选与建池、因子面板与回测全部直接读公司 ClickHouse**，需要在公司网络下并配置凭据（环境变量 `QL_CH_PASSWORD` 优先，其次 `backend/configs/clickhouse.local.env`，该文件已被 .gitignore 忽略）；股票池列表/详情优先读 MySQL，回退本地 `var/data_cache/pools/`，因子运行与回测结果读本地 `var/factor_runs/`、`var/outputs/`，这些页面不需要数据库凭据。

股票池页的「创建股票池」已接真实后端：筛选条件 → 候选预览（支持跨页全选 / 反选 / 部分勾选，默认全选）→ `POST /api/pools`（部分勾选时只提交勾中的代码）→ 轮询 `GET /api/jobs/{job_id}` → 自动刷新列表。候选与选样统计来自公司库，研究面板通过快照复用，不与旧本地缓存取交集。

手动回测页也已接真实后端：选择股票池（公司库池优先，旧本地池会提示走本地缓存）→ 填 Alpha 表达式 / 区间 / TopK 与交易参数 → `POST /api/manual-backtests` → 轮询 `GET /api/jobs/{job_id}`（loading_panel → evaluating → running → finished）→ 右侧直接用 `run_key` 拉取真实指标、净值、年度表与文件下载；「完整结果」跳到结果详情页。

结果详情页只读 `GET /api/results` 的真实结果：下拉按 `run_key` 切换、默认最新一条，兼容手动（`config.backtest` 嵌套）与因子（扁平 `config`）两种参数结构，展示数据源标签、真实指标/净值/年度与 manifest 白名单文件下载；研究备注仅存本机 `localStorage`，不再有 mock 任务或假下载。

> 说明：任务中心与用户/审计页面仍是 mock；接入真实平台时，把对应 `src/features/*` 里的 mock 数据替换为 API 调用即可，任务推演控制器与"状态演示"切换器届时移除。
