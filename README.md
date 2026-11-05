# QuantLab（生成因子＋回测系统）

QuantLab 是一个独立的股票**因子生成与回测平台**（不依赖 Qlib）。目前系统实现了从原始日频数据出发，把大规模日频数据变成可复用的股票级 Parquet 缓存 → 用特定股票池约束研究对象 → 通过 PPO 强化学习算法自动搜索可解释表达式生成单因子，之后做单因子有效性检测以进行生成阶段筛选 → 用统一 TopK 回测引擎检验合格因子的交易表现 → 最后通过 mutual IC 去重 + 权重优化把单因子升级为组合因子。

## 核心流程

```
原始 CSV ──► 主缓存(master) ──► 股票池(pool) ──► PPO 因子生成
                                                        │
          结果沉淀 ◄── 因子组合 ◄── 合格因子批量回测 ◄──┘
```

完整的七步数据流：

1. **构建主缓存**：读取原始 CSV，标准化字段后按股票保存为 Parquet，并写入 `meta.json`；
2. **创建股票池**：在主缓存上按流动性、覆盖率、上市天数等规则筛出命名股票池，生成 `pool_id`；
3. **准备生成运行时**：根据 `pool_id` 导出池内面板，切分 train / valid / test 三份缓存；
4. **PPO 因子生成**：在可用字段与操作符空间里搜索表达式，用 IC / RankIC / ICIR / 覆盖率筛出合格因子；
5. **批量回测合格因子**：只回测 `accepted_factors.jsonl` 里通过生成阶段筛选的表达式；
6. **因子组合**：mutual IC 去重 + 权重优化 + 多规模组合回测；
7. **结果沉淀与查看**：所有回测产物进入统一结果中心，可在 React 前端查看、下载、备注。

## 系统架构

系统按职责分为七层：

| 层级 | 核心职责 | 主要模块 |
|---|---|---|
| 数据层 | 读取原始日频 CSV，标准化，按股票落 Parquet | `repositories.local_store` |
| 股票池层 | 按成交额/覆盖率/上市天数等规则生成命名股票池 | `custom_bt.pools` |
| 表达式层 | 本地表达式算子、Brain/AlphaGen 风格表达式转换与校验 | `adapters.expressions`、`custom_bt.factor_adapter` |
| 生成层 | 池内面板转 PPO 训练数据，调用 single_factor 生成候选因子 | `custom_bt.factor_generation` + `single_factor` |
| 回测层 | 对手动/合格/组合因子执行 TopK 日频回测 | `custom_bt.engine`、`custom_bt.factor_backtest` |
| 组合层 | mutual IC 去重、权重优化、多规模组合回测 | `custom_bt.factor_composition` |
| 平台层 | FastAPI 接口、CLI、后台任务、结果中心 | `api/routers`、`services`、`workers`、`cli`、`repositories/result_store` |

### 三个子项目的关系

- **`backend/`** 是主平台"大脑"，但它**不自己实现 PPO**——`factor_generation.py` 通过 `sys.path` 定位到根目录后 `from single_factor...` 调用生成核心；
- **`single_factor/`** 是 PPO 生成器，内置 vendored 的 AlphaGen 原语，自带 `runtime.json` 和 `run_server.ps1` 守护脚本；当前 `evaluator.py` 和 AlphaGen 配置仍复用 backend 的 `custom_bt` / `adapters`，单独运行时需要把 `backend/` 加入 `PYTHONPATH`；
- **`research_pipeline/`** 是另一套独立的研究流水线（因子分类、表达式引擎、选股、评估、导出），与主平台无关；当前源码未入库，仅保留目录占位；
- **`backend/custom_bt/ai_research/`** 是用 DeepSeek LLM 驱动的量化研究 agent（`提示词合集/` 里的提示词为其服务）。

### 核心设计原则

- **大文件只导入一次**：约 20GB 的原始 CSV 只在 `prepare-master` 时读取一次，之后全程走缓存；
- **身份锁**：生成、回测、组合必须绑定同一 `master_store`、`pool_id`、`source_signature`；
- **先生成合格因子，再做回测与组合**。

## 目录结构

```text
生成因子＋回测系统/
├── .github/
│   └── workflows/
│       └── ci.yml                         # GitHub Actions：后端 compileall + 分层/API 测试，前端 tsc + build
├── .gitignore                             # 忽略运行期数据（/var/）、缓存、凭据、构建产物
├── README.md                              # 项目总览：流程、架构、启动方式、数据说明
│
├── backend/                               # Python 后端：FastAPI + 业务编排 + 数据访问 + CLI
│   ├── api/                               # HTTP 接入层：只负责请求/响应，不写业务逻辑
│   │   ├── __init__.py                    # 包说明
│   │   ├── __main__.py                    # HTTP 启动入口：py -3 -m api；配置 uvicorn 与日志
│   │   ├── main.py                        # FastAPI app 装配：lifespan、CORS、错误处理、include_router
│   │   ├── errors.py                      # DomainError -> JSONResponse，统一 HTTP 错误响应
│   │   └── routers/                       # 路由层：参数绑定 + 调 service + 返回
│   │       ├── __init__.py
│   │       ├── data.py                    # /api/data/master|fields|stocks、/api/universe/*、/api/operators
│   │       ├── pools.py                   # /api/pools*：列表/详情/删除/建池（202 + job_id）
│   │       ├── jobs.py                    # /api/jobs/{job_id}：后台任务状态
│   │       ├── factor_generation.py       # 因子生成默认参数与提交
│   │       ├── factor_backtest.py         # 因子运行、批量回测、批次文件下载
│   │       ├── manual_backtest.py         # 手动表达式回测提交
│   │       └── results.py                 # 结果列表/详情/按 run_key 打开/下载
│   │
│   ├── services/                          # 业务编排层：校验、拼装、创建任务、调用 repository
│   │   ├── __init__.py
│   │   ├── data_service.py                # 数据总览/字段/股票/算子/候选股票池查询
│   │   ├── pool_service.py                # 股票池列表/详情/删除/建池；MySQL 优先，本地回退
│   │   ├── job_service.py                 # 后台任务状态读取
│   │   ├── generation_service.py          # 因子生成参数/字段/算子/切分校验与提交
│   │   ├── factor_backtest_service.py     # 因子运行列表/详情、批量回测提交/查询/下载
│   │   ├── manual_backtest_service.py     # 手动表达式回测校验与提交
│   │   ├── backtest_service.py            # 旧版组合/手动回测任务执行
│   │   ├── result_service.py              # 结果列表/详情/文件下载
│   │   └── report_service.py              # 结果落盘编排：文件 -> PNG -> MySQL
│   │
│   ├── repositories/                      # 数据访问层：只做 IO
│   │   ├── __init__.py
│   │   ├── clickhouse.py                  # ClickHouse HTTP 客户端 + TTL 缓存 + 只读校验
│   │   ├── company_source.py              # 公司库 SQL：候选/面板/财务/估值/衍生指标
│   │   ├── local_store.py                 # 本地 Parquet/CSV 主缓存
│   │   ├── mysql_store.py                 # MySQL 集中存档：建表、幂等 upsert、sync
│   │   ├── pool_store.py                  # 股票池 manifest/codes 读写
│   │   ├── factor_run_store.py            # 因子运行 JSONL / 结果根目录 / backtest_id 校验
│   │   ├── panel_store.py                 # 按数据源加载回测面板
│   │   ├── result_store.py                # 结果 CSV/manifest 落盘与 list_runs
│   │   ├── composition_store.py           # 组合权重/摘要/admission log/拒绝记录
│   │   ├── runtime_store.py               # 因子生成运行时面板导出
│   │   └── job_store.py                   # status.json 原子读写
│   │
│   ├── workers/                           # 后台任务进程
│   │   ├── __init__.py
│   │   ├── job_runner.py                  # Popen 拉起 `python -m cli run-platform-job`
│   │   └── job_dispatcher.py              # platform job 创建/分发/执行/进度写盘
│   │
│   ├── config/                            # 运行配置
│   │   ├── __init__.py
│   │   ├── settings.py                    # PROJECT_ROOT / VAR_ROOT / 数据路径；支持环境变量覆盖
│   │   └── logging.py                     # 控制台 + 文件日志；uvicorn 配置
│   │
│   ├── adapters/                          # 外部库适配
│   │   ├── __init__.py
│   │   ├── expressions.py                 # quantops 表达式/算子转发
│   │   ├── operator_registry.py           # quantops 注册表 + AlphaGen 类加载
│   │   └── _quantops_boot.py              # 未安装 quantops 时补 sys.path
│   │
│   ├── infra/                             # 基础设施
│   │   ├── __init__.py
│   │   └── plotting.py                    # 回测摘要图（Agg 后端）
│   │
│   ├── cli/                               # 命令行入口
│   │   ├── __init__.py
│   │   ├── __main__.py                    # `python -m cli`
│   │   └── main.py                        # prepare/create-pool/generate/backtest/compose/... 子命令
│   │
│   ├── scripts/                           # 一次性维护脚本
│   │   ├── __init__.py
│   │   └── migrate_results.py             # 旧结果目录迁移
│   │
│   ├── custom_bt/                         # 因子领域 + 流水线
│   │   ├── __init__.py
│   │   ├── engine.py                      # TopK 日频回测引擎
│   │   ├── metrics.py                     # 年化/Sharpe/回撤/换手/成本
│   │   ├── alpha.py                       # alpha 定义规范化与组合
│   │   ├── expression_parser.py           # AlphaGen 表达式 tokenizer/parser 公共实现
│   │   ├── canonical_expression.py         # canonical 表达式与节点序列化
│   │   ├── factor_adapter.py              # AlphaGen -> 本地表达式与回测前校验
│   │   ├── pools.py                       # 股票池选样
│   │   ├── factor_backtest.py             # 合格因子批量回测
│   │   ├── manual_backtest.py             # 手动表达式回测
│   │   ├── factor_composition.py          # mutual IC 去重 + 权重优化 + 多规模组合
│   │   ├── factor_generation.py           # PPO 运行时准备与生成编排
│   │   ├── docs.py                        # 算子中文元数据
│   │   └── ai_research/                   # DeepSeek LLM 研究 agent
│   │       ├── __init__.py
│   │       ├── cli.py                     # AI research 命令行
│   │       ├── config.py                  # agent 配置与 guardrails
│   │       ├── context.py                 # 研究上下文快照
│   │       ├── llm_client.py              # DeepSeek HTTP 客户端
│   │       ├── memory.py                  # accepted/rejected/reflections 记忆
│   │       ├── prompts.py                 # 分层提示词
│   │       ├── runner.py                  # 研究主循环
│   │       ├── schemas.py                 # ResearchSpec 等
│   │       ├── tool_executor.py           # 工具执行与审计
│   │       └── tools.py                   # 数据/建池/生成/回测/组合工具
│   │
│   ├── configs/                           # 配置与凭据模板
│   │   ├── platform.yaml                  # 主数据源、master_store、factor_fields、分隔符
│   │   ├── factor_generation.yaml         # PPO 字段/算子/切分/质量阈值/预算
│   │   ├── default.yaml                   # 回测 BacktestConfig
│   │   ├── ai_research_agent.yaml         # LLM agent 配置
│   │   ├── field_catalog.json             # 字段目录
│   │   ├── clickhouse.env.example         # ClickHouse 凭据模板
│   │   ├── clickhouse.local.env           # 本地 ClickHouse 凭据（gitignored）
│   │   ├── mysql.env.example              # MySQL 凭据模板
│   │   ├── mysql.local.env                # 本地 MySQL 凭据（gitignored）
│   │   └── pools/
│   │       └── liquid_500.yaml            # 股票池预设
│   │
│   ├── docs/                              # 后端文档
│   │   ├── web_api.md                     # Web API 端点/数据来源/排障
│   │   ├── ai_research_flow.md            # AI research 流程
│   │   └── superpowers/                   # 历史计划/规格
│   │       ├── plans/
│   │       │   ├── 2026-08-11-operator-unification.md
│   │       │   └── 2026-08-20-ai-research-agent-foundation.md
│   │       └── specs/
│   │           └── 2026-08-11-operator-unification-design.md
│   │
│   ├── tests/                             # pytest
│   │   ├── conftest.py                    # OpenMP/matplotlib 测试环境、MySQL 默认关闭
│   │   ├── test_layering.py               # 分层守卫
│   │   ├── test_api_routes.py             # 路由/服务行为
│   │   ├── test_api_logging.py            # API 日志
│   │   ├── test_live_db.py                # ClickHouse 客户端
│   │   ├── test_company_source.py         # 公司库字段/面板
│   │   ├── test_data_store.py             # 本地主缓存
│   │   ├── test_pools.py                  # 股票池选样
│   │   ├── test_jobs.py                   # status.json / 旧版回测任务
│   │   ├── test_platform_jobs.py          # platform job
│   │   ├── test_platform_smoke.py         # 平台冒烟
│   │   ├── test_factor_backtest.py        # 批量因子回测
│   │   ├── test_manual_backtest.py        # 手动回测
│   │   ├── test_factor_composition.py     # 因子组合
│   │   ├── test_factor_generation.py      # PPO 运行时/生成
│   │   ├── test_factor_storage_metadata.py# 因子存储元数据
│   │   ├── test_results.py                # 结果落盘/列表
│   │   ├── test_migrate_results.py        # 历史结果迁移
│   │   ├── test_mysql_store.py            # MySQL 表/upsert/表达式
│   │   ├── test_canonical_expression.py   # canonical 表达式
│   │   ├── test_factor_adapter.py         # AlphaGen -> 本地表达式
│   │   ├── test_expressions.py            # 表达式引擎
│   │   ├── test_operator_registry.py      # 算子注册表
│   │   ├── test_docs.py                   # 算子元数据
│   │   ├── test_metrics.py                # 指标
│   │   ├── test_engine_small.py           # 小面板回测
│   │   ├── test_quantops_boot.py          # quantops sys.path 兜底
│   │   ├── test_quantops_metadata_parity.py # 元数据一致性
│   │   ├── test_alphagen_operator_semantics.py # AlphaGen 算子语义
│   │   ├── test_ai_research_agent.py      # LLM agent
│   │   ├── test_cli.py                    # CLI
│   │   ├── test_single_factor_environment.py # single_factor gym 环境
│   │   └── test_single_factor_evaluator.py   # single_factor 评估器
│   │
│   ├── .env.example                       # 通用环境变量模板
│   ├── .gitignore                         # 后端局部忽略
│   ├── common.py                          # 共享工具：settings 再导出、_sanitize、_safe_child 等
│   ├── errors.py                          # DomainError 体系
│   ├── schemas.py                         # 请求/响应 Pydantic 模型
│   ├── pyproject.toml                     # 包配置
│   ├── pytest.ini                         # rootdir/testpaths
│   ├── requirements.txt                   # 后端依赖
│   └── README.md                          # 后端说明
│
├── frontend/                              # React 前端
│   ├── src/
│   │   ├── main.tsx                       # React 入口
│   │   ├── index.css                      # Tailwind v4 + 全局样式
│   │   ├── vite-env.d.ts                  # Vite 类型
│   │   ├── app/
│   │   │   ├── App.tsx                    # 应用壳：登录态/布局/菜单/懒加载
│   │   │   └── navigation.ts              # Page/Role/PageNav/TaskAdder
│   │   ├── api/
│   │   │   └── client.ts                  # 兼容 barrel：合并 feature API
│   │   ├── shared/
│   │   │   ├── api/
│   │   │   │   └── base.ts                # fetch 基座、ApiError、useApiData/useJobPolling
│   │   │   └── domain/
│   │   │       ├── factorCategories.ts    # 因子分类
│   │   │       └── fieldCategories.ts     # 字段分类
│   │   ├── components/                    # 跨 feature 组件
│   │   │   ├── Brand.tsx
│   │   │   ├── Charts.tsx                 # ECharts 净值/回撤、年度收益
│   │   │   ├── FilterChips.tsx
│   │   │   └── LoadGate.tsx
│   │   └── features/                      # 按业务功能聚合
│   │       ├── auth/
│   │       │   ├── LoginPage.tsx
│   │       │   └── index.ts
│   │       ├── dashboard/
│   │       │   ├── Dashboard.tsx
│   │       │   └── index.ts
│   │       ├── tasks/
│   │       │   ├── TaskCenter.tsx
│   │       │   ├── mock.ts
│   │       │   └── index.ts
│   │       ├── data-browser/
│   │       │   ├── DataPages.tsx           # 数据总览/字段/股票/操作符
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── pools/
│   │       │   ├── PoolsPage.tsx
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── factor-generation/
│   │       │   ├── FactorGenerationPage.tsx
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── factor-backtest/
│   │       │   ├── FactorBacktestPage.tsx
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── manual-backtest/
│   │       │   ├── ManualBacktestPage.tsx
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── results/
│   │       │   ├── ResultViews.tsx
│   │       │   ├── backtestAnalysis.tsx
│   │       │   ├── mock.ts
│   │       │   ├── api.ts
│   │       │   └── index.ts
│   │       ├── composition/
│   │       │   ├── CompositionPage.tsx
│   │       │   ├── mock.ts
│   │       │   └── index.ts
│   │       └── system/
│   │           ├── SystemPages.tsx
│   │           ├── mock.ts
│   │           └── index.ts
│   ├── index.html                         # Vite HTML shell
│   ├── package.json                       # 依赖与脚本
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json
│   ├── vite.config.ts                     # React/Tailwind/Figma 插件 + /api 代理
│   ├── AGENTS.md                          # 前端开发约定
│   ├── CLAUDE.md                          # @AGENTS.md
│   ├── README.md
│   └── dist/                              # 构建产物（不入库）
│
├── quantops/                              # 独立算子库（可 pip install）
│   ├── quantops/
│   │   ├── __init__.py                    # 公开 API
│   │   ├── __main__.py                    # CLI
│   │   ├── accessor.py                    # pandas Series.qo
│   │   ├── core.py                        # Series 助手
│   │   ├── errors.py                      # ExpressionError
│   │   ├── expression.py                  # AST 白名单 + 求值
│   │   ├── metadata.py                    # 中文分类/说明/示例
│   │   ├── operators.py                   # 82 个算子 + 注册表
│   │   ├── opset.py                       # OperatorSet
│   │   ├── panel.py                       # 面板互转
│   │   └── registry.py                    # canonical 定义
│   ├── tests/
│   │   ├── test_cli.py
│   │   ├── test_golden_values.py
│   │   ├── test_operator_semantics.py
│   │   ├── test_opset.py
│   │   ├── test_public_api.py
│   │   └── test_quantops_expression.py
│   ├── pyproject.toml
│   └── README.md
│
├── single_factor/                         # PPO 单因子生成器
│   ├── _vendor/
│   │   ├── alphagen/                      # vendored AlphaGen 原语
│   │   │   ├── __init__.py
│   │   │   ├── config.py                  # 常量/算子集合
│   │   │   ├── data/
│   │   │   │   ├── exception.py
│   │   │   │   ├── expression.py
│   │   │   │   ├── parser.py
│   │   │   │   ├── tokens.py
│   │   │   │   └── tree.py
│   │   │   ├── rl/
│   │   │   │   └── policy.py
│   │   │   └── utils/
│   │   │       ├── correlation.py
│   │   │       ├── maybe.py
│   │   │       ├── misc.py
│   │   │       └── pytorch_utils.py
│   │   └── alphagen_qlib/
│   │       └── stock_data.py
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── data.py
│   ├── environment.py                     # gym 环境
│   ├── evaluator.py                       # 单因子指标；复用 backend canonical
│   ├── expression.py
│   ├── features.py
│   ├── pool_selection.py
│   ├── preprocess.py                      # CSV -> Parquet -> memmap
│   ├── runner.py                          # PPO 训练/生成
│   ├── storage.py
│   ├── universe.py
│   ├── runtime.json
│   ├── run_server.ps1                     # Windows 守护脚本
│   ├── requirements.txt
│   └── README.md
│
├── research_pipeline/                     # 占位：源码未入库
│   ├── config.local.yaml                  # 流水线配置
│   └── __pycache__/                       # 历史编译缓存
│
├── var/                                   # 运行期数据根（gitignored）
│   ├── data_cache/
│   │   ├── master/                        # 主缓存：per-stock Parquet + meta.json
│   │   ├── pools/                         # 股票池：manifest.json + codes.txt
│   │   └── factor_runtime/                # PPO 运行时缓存
│   ├── outputs/
│   │   ├── jobs/                          # 后台任务状态与日志
│   │   ├── logs/                          # API 日志
│   │   └── saved_backtests/               # 回测结果中心
│   └── factor_runs/                       # 因子运行结果
│
├── docs/                                  # 设计文档与参考资料
│   ├── ai_research/                       # AI 研究资料/设计/进度
│   ├── superpowers/
│   │   ├── plans/                         # 历史实现计划
│   │   └── specs/                         # 历史设计规格
│   ├── brain平台操作符.md                 # WorldQuant BRAIN 算子参考
│   ├── v_stock_daily_full_字段说明.md     # 原始数据字段说明
│   └── *.docx                             # 整体逻辑/方法论/研究方案等
│
├── 提示词合集/                            # LLM agent 提示词模板
├── tools/                                 # 空目录
├── README.md
└── .gitignore
```

### 命名约定

- **产品名**：QuantLab
- **仓库目录**：`backend/`（后端）、`frontend/`（前端）
- **Python 包**：`custom_bt`（历史名，保持稳定；命令行入口仍是 `python -m cli`）
- 文档中不再使用旧名 `custom_backtester/`、`原型/`

详细架构见 [docs/生成因子与回测系统整体逻辑说明书.docx](docs/生成因子与回测系统整体逻辑说明书.docx)。

## 环境要求

- Python 3.11（或 3.8）
- conda 环境 `alphagen`
- 仅跑手动回测只需 `backend` 依赖；跑 PPO 生成还需 `single_factor` 的 torch / stable-baselines3 等

```powershell
conda create -n alphagen python=3.11 -y
conda activate alphagen

# 后端（FastAPI + 回测）
pip install numpy pandas "pyarrow>=12.0" pyyaml matplotlib fastapi uvicorn PyMySQL certifi "pytest>=7.0"

# PPO 生成（强化学习）
pip install "gymnasium>=0.28" "stable-baselines3>=2.0" "sb3-contrib>=2.0"

# torch（默认 CPU；GPU 请改用 https://download.pytorch.org/whl/cu121）
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

三个子模块各自的依赖见 `backend/requirements.txt`、`single_factor/requirements.txt`、`research_pipeline/requirements.txt`。

## 快速开始

### 后端 API

```powershell
cd backend
py -3 -m api
```

默认监听 <http://127.0.0.1:8000>，可用 `QL_API_HOST` / `QL_API_PORT` 覆盖。

### 前端

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器打开 <http://localhost:8443>，开发服务器会把 `/api` 代理到后端。

### 命令行主流程

```powershell
cd backend

# ① 构建主缓存（需源 CSV 就位，路径见 configs/platform.yaml 的 source_csv）
python -m cli prepare-master --config configs/platform.yaml

# ② 创建股票池
python -m cli create-pool --config configs/pools/liquid_500.yaml

# ③ PPO 生成因子
python -m cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml

# ④ 合格因子批量回测
python -m cli backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml

# ⑤ 因子组合
python -m cli compose-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml --sweep-sizes 10,20,30
```

### 独立 PPO 生成器（服务器守护，自动重启）

```powershell
# 在项目根目录（包含 single_factor 的那一层）
python -m single_factor.cli run --config single_factor/runtime.json
# 或守护脚本（断线自动重启，复用 run_state.json 与 checkpoint）
powershell -ExecutionPolicy Bypass -File .\single_factor\run_server.ps1
```

## CLI 命令

| 命令 | 作用 |
|---|---|
| `prepare-master` | 构建主缓存（读源 CSV） |
| `create-pool` | 创建股票池 |
| `generate-factors` | PPO 因子生成 |
| `backtest-factors` | 合格因子批量回测 |
| `compose-factors` | 因子组合 |
| `backtest` | 手动表达式回测 |
| `fields` / `operators` / `runs` / `stock-list` | 查看字段 / 算子 / 结果 / 股票列表 |
| `prepare` / `update` | 旧式缓存导入与增量更新 |
| `migrate-results` | 历史结果目录迁移 |
| `ai-research` | LLM 量化研究 agent（需 DeepSeek API Key） |

## 配置说明

| 配置文件 | 作用 |
|---|---|
| `configs/platform.yaml` | 主数据源 `source_csv`、`master_store`、`factor_fields`、分隔符、chunksize |
| `configs/pools/liquid_500.yaml` | 股票池名称、筛选窗口、top_n、覆盖率、上市天数、停牌过滤 |
| `configs/factor_generation.yaml` | PPO 可用字段、train/valid/test split、target_horizon、质量阈值、生成预算 |
| `configs/default.yaml` | 回测 BacktestConfig（区间、TopK、成本、滑点、单票权重、涨跌停过滤） |

> **注意**：`backtest-factors` / `compose-factors` 会从 `--config` 读取 `master_store`、`pools_root`、`backtest`。若 `default.yaml` 缺少前两个键会报 `KeyError`，需补上：
>
> ```yaml
> master_store: "../var/data_cache/master"
> pools_root: "../var/data_cache/pools"
> ```

## 数据说明

- **源数据**：约 20GB 的日频面板 CSV（tab 分隔，`.csv` 后缀）。必需列 `code/timestamps/open/close/high/low/vol/amount`，字段说明见 [docs/v_stock_daily_full_字段说明.md](docs/v_stock_daily_full_字段说明.md)（共 91 字段）。
- **主缓存 `var/data_cache/master`**：按股票拆分的 Parquet + `meta.json`（含 `source_signature`），由 `prepare-master` 从源 CSV 重建，**不入库**。
- **运行期数据根 `var/`**（见 `.gitignore`）：`data_cache`（master / pools / factor_runtime）、`outputs`（jobs / logs / saved_backtests）、`factor_runs`（历史因子）全部不入库；`single_factor` 的 `data/cache/run` 同样不入库。
- **敏感配置**：`.env.local`、`config.local.yaml` 不入库，模板见 `.env.example` / `config.example.yaml`。

### 身份锁（source_signature / pool_id）

`source_signature` 由源 CSV 的路径、大小、mtime、字段列表、分隔符哈希得到；`pool_id` 由名称 + manifest（含签名）哈希得到。因此：

- 换路径/换机器重建主缓存后，`pool_id` 会改变，旧 `var/factor_runs` 与新池子不匹配，需重新 `create-pool` + `generate-factors`；
- 迁移时若 `var/data_cache/master`、`var/data_cache/pools`、`var/factor_runs` 一起拷贝且签名一致，则无需重建，可直接回测 / 组合。

## 已知注意点

- “数据字段”页面显示公司库字段目录（`configs/field_catalog.json` + 实时库表结构）；因子生成/回测实际使用 `platform.yaml` 的 `factor_fields` 精选字段，页面里看到的字段未必都能用于因子表达式。

## 附录：environment.yml

```yaml
name: alphagen
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - pip
  - pip:
      - numpy
      - pandas
      - pyarrow>=12.0
      - pyyaml
      - matplotlib
      - fastapi
      - uvicorn
      - PyMySQL
      - certifi
      - gymnasium>=0.28
      - stable-baselines3>=2.0
      - sb3-contrib>=2.0
      - torch
      - pytest>=7.0
```
