# QuantLab（生成因子＋回测系统）

QuantLab 是股票因子生成、回测与组合研究平台，不依赖 Qlib。公司 ClickHouse 是唯一生产数据源；研究任务先取得不可变 Parquet 快照，再在本地训练、回测和组合。

## 数据流程

```text
ClickHouse → 股票池筛选 → 不可变 Parquet 快照 → train/valid/test memmap → PPO 因子生成
                                  └────────────→ 手动/单因子回测 → 因子组合 → 结果中心
```

数据预览、股票维度查询、字段目录和建池直接查询 ClickHouse，使用服务端 TTL 缓存。研究任务按股票集合、字段、日期范围、as_of 和查询版本创建或复用快照，训练步骤不访问数据库。行情按交易日对齐；财务和衍生字段按披露日期 as-of 合并，估值按交易日合并。

## 项目结构

| 目录 | 职责 |
|---|---|
| `backend/api/` | FastAPI 路由与错误处理 |
| `backend/services/` | 参数校验、后台任务和结果编排 |
| `backend/workers/` | 子进程任务启动、分发及状态落盘 |
| `backend/repositories/` | ClickHouse 查询、快照、股票池、结果与 MySQL 存档 |
| `backend/custom_bt/` | 因子生成编排、TopK 回测、组合优化、AI 研究代理 |
| `single_factor/` | PPO 表达式搜索、指标评估及训练缓存 |
| `quantops/` | NumPy/pandas 算子库、表达式引擎及注册表 |
| `frontend/src/features/` | React 业务页面 |
| `backend/tests/`、`quantops/tests/` | 自动化测试 |
| `docs/`、`提示词合集/` | 研究资料、设计和提示词 |

## 环境与启动

后端使用 Python 3.10+、FastAPI、pandas、NumPy、PyArrow；PPO 另需 PyTorch、Gymnasium 和 sb3-contrib。前端使用 React 19、TypeScript、Vite、Ant Design、ECharts。

```powershell
cd backend
python -m pip install -r requirements.txt
python -m api
```

默认 API 地址为 `http://127.0.0.1:8000`，通过 `QL_API_HOST` / `QL_API_PORT` 覆盖。在公司网络内配置 `backend/configs/clickhouse.local.env`（参考同目录模板）或对应环境变量；不要将凭据写入快照或版本库。

```powershell
cd frontend
pnpm install
pnpm dev
```

前端开发服务器通过 `/api` 代理后端。登录与任务中心等仍含演示逻辑，不能视为后端认证或真实调度；数据总览不再提供模拟导入成功交互。

## 研究工作流

在 `backend/` 下执行：

```powershell
python -m cli create-pool --config configs/pools/liquid_500.yaml
python -m cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml
python -m cli backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml
python -m cli compose-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml --sweep-sizes 10,20,30
```

第一次研究任务构建快照；相同请求复用已发布快照。首次构建可涉及多个源表的 SQL，不等于所有字段只能执行一条 SQL。回测与组合优先绑定因子运行的快照；字段或范围不满足时应明确报错，不得静默覆盖或补查。Web 上也可创建股票池、生成因子、提交手动/批量回测并查看结果。

## 不可变快照

```text
var/data_cache/snapshots/<snapshot_id>/
├── panel.parquet
├── manifest.json
└── checksums.json
```

manifest 包含 `snapshot_id`、`created_at`、`data_source`、源表、`pool_id`、字段、请求区间、`as_of`、实际日期范围、行数、股票数、`query_hash`、`source_signature`、`schema_hash` 和版本。清单不得包含密码或 token。

构建过程在唯一临时目录内完成，验证后原子发布。发布后的面板与清单不被原地更新；刷新创建新快照。默认不自动清理被任务引用的快照。指定已有快照复用时无需重新查询业务数据；公司库不可用时仍可读取已保存且完整的快照。

`source_signature` 标识逻辑来源，不能代替内容校验和。源库补数或修订后，需要新的源版本/as_of 或显式刷新才能创建新的快照；完全离线的复用不会自动发现源端变化。`as_of` 是本次数据捕获的版本标签，不是历史数据库时间旅行保证；没有源端历史版本能力时，不能据此重建任意过去时刻。

运行期文件位于 `var/`，不入库：`data_cache/pools` 为股票池清单，`data_cache/factor_runtime` 为派生训练缓存，`factor_runs` 为因子运行，`outputs/jobs` 为状态和日志，`outputs/saved_backtests` 为统一结果中心。CSV 仅作为小型结果导出格式，不作为生产行情输入。

## 配置

| 文件 | 内容 |
|---|---|
| `backend/configs/pools/liquid_500.yaml` | ClickHouse 建池筛选窗口、流动性及覆盖率 |
| `backend/configs/factor_generation.yaml` | 字段、切分、快照、质量阈值与 PPO 预算 |
| `backend/configs/default.yaml` | 快照配置与 TopK 回测区间、成本、滑点、权重 |
| `backend/configs/ai_research_agent.yaml` | LLM 与工具执行策略、ClickHouse/快照上下文 |

## 旧数据迁移

本地主缓存 `var/data_cache/master` 和巨大 CSV 运行链路已废弃，相关导入命令与执行分支删除，不再保留 fallback。旧 local 股票池或仅绑定旧来源的 factor run 可以查看历史产物，但不能直接重新执行，也不能把来源标签改成 ClickHouse 复用。请从公司库重新建池和生成，绑定新快照。

历史结果目录、下载接口和结果 CSV 保持兼容。此次迁移不会删除磁盘上的历史数据或回测文件。复制研究运行到其他机器时同时复制所引用的快照、股票池及运行清单。

## 验证

```powershell
cd backend
python -m pytest tests -q
```

```powershell
cd frontend
pnpm exec tsc --noEmit
pnpm build
```

详细端点见 [后端 API 文档](backend/docs/web_api.md)，AI 工具流程见 [研究代理说明](backend/docs/ai_research_flow.md)。
