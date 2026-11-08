# ClickHouse 与不可变快照迁移交付报告

日期：2026-11-08

## 迁移摘要

ClickHouse 是唯一生产行情、维度、财务、估值及衍生字段来源。预览和建池继续实时查询；生成、手动回测、批量回测、组合通过统一面板入口读取已验证的 Parquet 快照。生产入口不再读取或创建本地主缓存，也不再接受巨大 CSV 行情输入。

保留已有财务/衍生披露日对齐、估值交易日对齐语义，以及此前回测时间线、停牌、估值、权重修正、测试集隔离和状态原子写入修复。结果目录和历史查看入口保留；组合 ID 额外绑定快照、来源快照和回测配置，防止不同版本覆盖。

实际代码原先已具备 ClickHouse 查询、Parquet 导出和 Web 公司库入口，本次复用这些能力，重点移除本地分支并补齐数据版本、缓存复用与并发安全。未把计划中的现状推测当作真实数据库联调结论。

## 快照结构和身份

```text
var/data_cache/snapshots/<64位snapshot_id>/
  panel.parquet
  manifest.json
  checksums.json
```

同级 `.locks/` 保存操作系统锁文件。构建使用唯一 `.building-<uuid>/`，只有校验完成后才原子改名发布。发布后的内容不覆盖；默认不自动清理任何快照。数据源请求边界复用 `company_source.write_pool_panel()`，首次构建可能分别查询行情、财务、估值和衍生表。

manifest 示例（标识和数量仅为示意）：

```json
{
  "snapshot_id": "<64位SHA256标识>",
  "created_at": "2026-11-08T08:00:00+00:00",
  "data_source": "clickhouse",
  "pool_id": "liquid_500_<hash>",
  "codes": ["000001", "600000"],
  "fields": ["Ifsuspend", "close", "if_down", "if_up", "open"],
  "tables": ["dws.ll_stock_daily_sharing"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "as_of": "research-v1",
  "as_of_kind": "capture-label",
  "rows": 480,
  "n_stocks": 2,
  "date_min": "2024-01-02",
  "date_max": "2024-12-31",
  "query_hash": "<SHA256>",
  "request_hash": "<SHA256>",
  "query_version": "<查询与字段处理代码SHA256>",
  "source_signature": "clickhouse:dws.ll_stock_daily_sharing",
  "schema_hash": "<SHA256>",
  "snapshot_version": 1
}
```

另记录无凭据的源地址标识；密码、token 和用户凭据不写入清单。`checksums.json` 保存 panel 和 manifest 的 SHA256。读取前验证校验和，损坏明确失败，不暗中重建。

`source_signature` 标识逻辑来源，`snapshot_id` 和校验和标识物化版本。请求指纹包含规范化股票集合、字段、池、日期、as_of、源地址和查询处理版本。相同请求复用最近的已发布版本；`create_or_reuse_snapshot(..., refresh=True)` 创建新版本。指定 snapshot_id 始终固定该版本。

**as_of 是捕获标签，不是数据库历史时点查询。** 未提供源端版本接口时，完全离线复用无法发现公司库补数；通过新 as_of 或显式 refresh 固定新版本，旧版本不覆盖。

## 配置与调用变化

- 新增 `QL_SNAPSHOT_ROOT`，默认仓库 `var/data_cache/snapshots`；API 通过该设置选择根目录。
- YAML 中新增 `snapshot_root`，可选 `snapshot_id`、`as_of`。CLI 相对路径以配置文件所在目录解析。
- 三种研究请求模型新增可选 `snapshot_id` 和 `as_of`；不再传递 master 路径。批量回测默认继承 factor run 的 snapshot_id。
- `factor_generation.yaml` 保留字段、切分、预算及 ClickHouse 来源；`default.yaml`、股票池和 AI 配置统一使用新路径。
- 删除旧平台导入配置 `backend/configs/platform.yaml`。
- 删除 `prepare`、`update`、`prepare-master` 及导入任务操作；通用 backtest/fields/stock-list CLI 使用 snapshot_id。
- 独立 single_factor 删除 CSV 导入与 CSV 股票池筛选命令，保留快照到 memmap 以及 PPO 训练。
- 数据总览保留 `/api/data/master` 兼容路径，但表示 ClickHouse 统计，并返回 `snapshot_count`、`latest_snapshot_at`。前端移除模拟主缓存导入交互。

示例配置：

```yaml
data_source: clickhouse
snapshot_root: ../../var/data_cache/snapshots
pools_root: ../../var/data_cache/pools
# snapshot_id: <已有的64位ID，指定后固定版本>
# as_of: research-v1
```

生成将快照目录直接作为 processed_dir，不复制宽面板。派生 runtime ID 绑定快照及预处理代码版本。跨进程锁保护构建，完成清单原子写入；再次运行复用完成的 memmap，不截断活跃训练文件。PPO dataset signature 也绑定 snapshot_id。

回测按表达式依赖字段投影读取；滚动表达式规划额外历史区间，裁取所需历史行，避免将整个多年宽表读入内存。历史不足时保留缺失值语义，不从未来填充；固定快照明显缺少所需预热区间时明确要求新建更早的快照。组合统计剔除仅用于预热的行。

## 兼容与旧数据

- 旧 local 池、缺少公司来源的 factor run 和旧本地执行任务明确拒绝重新运行，提示从 ClickHouse 重建。
- 不通过改来源标签或静默 fallback 复用旧本地数据。
- 已保存结果及旧文件仍可查询和下载；本次不删除磁盘历史数据。
- 指定快照字段、股票集合、池或时间范围不匹配时明确失败，需显式选择/创建兼容快照。
- 组合多个不同生成快照时要求显式选择兼容的组合快照，保留来源快照引用。
- MySQL 原有 JSON 归档保存完整运行/结果清单，无需新建数据库或修改现有表结构。

## 验证结果

- 完整后端：`cd backend; python -m pytest tests -q`：**346 passed，163 subtests passed**，1 条既有 pytest 插件弃用警告。
- 前端：`pnpm exec tsc --noEmit` 通过；`pnpm build` 通过，仍有图表大 chunk 的构建提示。
- Python compileall 和 git diff --check 通过。
- 快照测试覆盖创建/复用/刷新、并发单次构建、损坏拒绝、缺字段不发布、路径与 CSV 拒绝；面板测试覆盖按需读列、离线复用、预热窗口、旧来源拒绝、runtime 安全复用。
- 业务测试用小型 Parquet 与 fake ClickHouse 网络边界执行真实快照和领域逻辑，没有通过删除核心校验来绕过失败。
- CI 增加快照、面板以及回测/状态存储回归用例。
- 残留检查：生产代码不再有旧 master 参数、构建函数或导入操作的有效引用；文档历史记录、迁移说明与验证删除/拒绝行为的测试保留文字引用。

## 限制和未验证项

未连接真实公司库执行全市场多字段导出、完整 PPO 训练和生产容量测试。完整财务宽表附加仍沿用现有 DataFrame 合并实现，应在真实规模下测量内存和导出耗时。快照内容校验需要顺序读取文件，超大快照复用有校验 IO 成本。预热查询采用日历余量，上市初期或长停牌历史不足仍会产生缺失值。没有源端历史版本能力时，不承诺任意历史时点重建或多表读取的全局事务一致性。不实现自动 GC。

## 新增、修改和删除的文件

| 操作 | 文件 |
|---|---|
| 修改 | `.github/workflows/ci.yml` |
| 修改 | `README.md` |
| 修改 | `backend/README.md` |
| 修改 | `backend/cli/main.py` |
| 修改 | `backend/common.py` |
| 修改 | `backend/config/settings.py` |
| 修改 | `backend/configs/ai_research_agent.yaml` |
| 修改 | `backend/configs/default.yaml` |
| 修改 | `backend/configs/factor_generation.yaml` |
| 删除 | `backend/configs/platform.yaml` |
| 修改 | `backend/configs/pools/liquid_500.yaml` |
| 修改 | `backend/custom_bt/ai_research/config.py` |
| 修改 | `backend/custom_bt/ai_research/context.py` |
| 修改 | `backend/custom_bt/ai_research/prompts.py` |
| 修改 | `backend/custom_bt/ai_research/runner.py` |
| 修改 | `backend/custom_bt/ai_research/tool_executor.py` |
| 修改 | `backend/custom_bt/ai_research/tools.py` |
| 修改 | `backend/custom_bt/factor_backtest.py` |
| 修改 | `backend/custom_bt/factor_composition.py` |
| 修改 | `backend/custom_bt/factor_generation.py` |
| 修改 | `backend/custom_bt/manual_backtest.py` |
| 修改 | `backend/custom_bt/pools.py` |
| 修改 | `backend/docs/ai_research_flow.md` |
| 修改 | `backend/docs/web_api.md` |
| 修改 | `backend/repositories/company_source.py` |
| 修改 | `backend/repositories/local_store.py` |
| 修改 | `backend/repositories/panel_store.py` |
| 修改 | `backend/repositories/pool_store.py` |
| 删除 | `backend/repositories/runtime_store.py` |
| 修改 | `backend/schemas.py` |
| 修改 | `backend/services/backtest_service.py` |
| 修改 | `backend/services/data_service.py` |
| 修改 | `backend/services/factor_backtest_service.py` |
| 修改 | `backend/services/generation_service.py` |
| 修改 | `backend/services/job_service.py` |
| 修改 | `backend/services/manual_backtest_service.py` |
| 修改 | `backend/services/pool_service.py` |
| 修改 | `backend/services/result_service.py` |
| 修改 | `backend/tests/test_ai_research_agent.py` |
| 修改 | `backend/tests/test_api_routes.py` |
| 修改 | `backend/tests/test_cli.py` |
| 修改 | `backend/tests/test_company_source.py` |
| 修改 | `backend/tests/test_data_store.py` |
| 修改 | `backend/tests/test_factor_backtest.py` |
| 修改 | `backend/tests/test_factor_composition.py` |
| 修改 | `backend/tests/test_factor_generation.py` |
| 修改 | `backend/tests/test_jobs.py` |
| 修改 | `backend/tests/test_manual_backtest.py` |
| 修改 | `backend/tests/test_platform_jobs.py` |
| 修改 | `backend/tests/test_platform_smoke.py` |
| 修改 | `backend/tests/test_pools.py` |
| 修改 | `backend/workers/job_dispatcher.py` |
| 修改 | `backend/workers/job_runner.py` |
| 修改 | `frontend/README.md` |
| 修改 | `frontend/src/app/App.tsx` |
| 修改 | `frontend/src/features/data-browser/DataPages.tsx` |
| 修改 | `frontend/src/features/data-browser/api.ts` |
| 修改 | `frontend/src/features/manual-backtest/ManualBacktestPage.tsx` |
| 修改 | `frontend/src/features/pools/PoolsPage.tsx` |
| 修改 | `frontend/src/features/system/mock.ts` |
| 修改 | `frontend/src/features/tasks/mock.ts` |
| 修改 | `single_factor/README.md` |
| 修改 | `single_factor/__init__.py` |
| 修改 | `single_factor/cli.py` |
| 修改 | `single_factor/config.py` |
| 删除 | `single_factor/pool_selection.py` |
| 修改 | `single_factor/preprocess.py` |
| 修改 | `single_factor/run_server.ps1` |
| 修改 | `single_factor/runtime.json` |
| 新增 | `backend/repositories/snapshot_store.py` |
| 新增 | `backend/tests/snapshot_fixtures.py` |
| 新增 | `backend/tests/test_snapshots.py` |
| 新增 | `backend/tests/test_panel_snapshots.py` |
| 新增 | `docs/2026-11-08-clickhouse-snapshot-migration.md` |
